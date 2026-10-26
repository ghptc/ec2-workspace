#!/usr/bin/env python3
"""Fail-closed immutable GitHub Release policy and orchestration (no EC2 access)."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REPO = 'ghptc/ec2-workspace'
IMAGE = 'ghcr.io/ghptc/cod4-runtime'
SHA = r'[a-f0-9]{40}'
HASH = r'[a-f0-9]{64}'
DIGEST = 'sha256:' + HASH
VERSION = re.compile(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-rc\.([1-9][0-9]*))?')
GATES = {'history', 'dependencies', 'assets', 'compile', 'unit', 'integration',
         'security', 'runtime', 'startup', 'image', 'reproducibility'}


def require(value, message):
    if not value:
        raise ValueError(message)


def run(*args, input=None, cwd=None):
    return subprocess.run(args, input=input, text=True, cwd=cwd, check=True,
                          stdout=subprocess.PIPE).stdout.strip()


def api(path, method='GET', data=None):
    args = ['gh', 'api', '--method', method, '-H', 'X-GitHub-Api-Version: 2026-03-10', path]
    if data is not None:
        args += ['--input', '-']
    return json.loads(run(*args, input=json.dumps(data) if data is not None else None) or '{}')


def pages(path):
    result = []
    for page in range(1, 1001):
        batch = api(f'{path}{"&" if "?" in path else "?"}per_page=100&page={page}')
        require(isinstance(batch, list), 'Expected paginated GitHub list')
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise ValueError('GitHub pagination exceeded limit')


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n'


def version(tag):
    match = VERSION.fullmatch(tag)
    require(match, 'Expected explicit vMAJOR.MINOR.PATCH[-rc.N]')
    return tuple(int(x) if x else None for x in match.groups())


def next_version(tags, messages):
    versions = [(version(t), t) for t in tags if VERSION.fullmatch(t)]
    stable = [v[:3] for v, _ in versions if v[3] is None]
    base = max(stable, default=(0, 0, 0))
    level = 0
    for message in messages:
        header = message.splitlines()[0]
        require(re.match(r'\w+(?:\([^\n)]+\))?!?: .+', header),
                f'Non-Conventional Commit: {header}')
        if re.match(r'\w+(?:\([^\n)]+\))?!:', header) or re.search(r'^BREAKING CHANGE: ', message, re.M):
            level = max(level, 3)
        elif header.startswith(('feat:', 'feat(')):
            level = max(level, 2)
        elif header.startswith(('fix:', 'fix(', 'perf:', 'perf(')):
            level = max(level, 1)
    require(level or not stable, 'No release-worthy Conventional Commits')
    if not stable:
        target = (0, 1, 0)
    elif level == 3:
        target = (base[0] + 1, 0, 0)
    elif level == 2:
        target = (base[0], base[1] + 1, 0)
    else:
        target = (base[0], base[1], base[2] + 1)
    rc = max((v[3] for v, _ in versions if v[:3] == target and v[3]), default=0) + 1
    return 'v%d.%d.%d-rc.%d' % (*target, rc)


def expected_version(local=ROOT):
    refs = api(f'repos/{REPO}/git/matching-refs/tags/')
    tags = [r['ref'].removeprefix('refs/tags/') for r in refs]
    stable = [t for t in tags if VERSION.fullmatch(t) and version(t)[3] is None]
    if stable:
        start = peeled_tag(max(stable, key=lambda t: version(t)[:3]))
    else:
        start = json.loads((Path(local) / 'release/version-baseline.json').read_text())['workspace']
    run('git', '-C', str(local), 'merge-base', '--is-ancestor', start, 'HEAD')
    messages = run('git', '-C', str(local), 'log', '--first-parent', '--format=%B%x00', start + '..HEAD')
    commits = [m.strip() for m in messages.split('\x00') if m.strip()]
    # Preserve normal GitHub merge envelopes; the merged subject is authoritative.
    commits = [m.split('\n\n', 1)[1] if m.startswith('Merge pull request #') and '\n\n' in m else m
               for m in commits]
    return next_version(tags, commits)


def validate_manifest(m, tag, mode, environment):
    v = version(tag)
    require(environment in ('homolog', 'production'), 'Unknown environment')
    require(m.get('schema') == 1 and m.get('repository') == REPO, 'Unknown manifest repository/schema')
    require(m.get('tag') == tag and m.get('mode') == mode and re.fullmatch(r'[a-z][a-z0-9-]*', mode),
            'Release tag or mode mismatch')
    require(re.fullmatch(SHA, m['workspace']), 'Invalid workspace SHA')
    for key in ('engine', 'config', 'bot_warfare'):
        require(re.fullmatch(SHA, m['dependencies'][key]), f'Invalid {key} SHA')
    for key in ('engine_dependencies_sha256',):
        require(re.fullmatch(HASH, m['dependencies'][key]), 'Invalid dependency hash')
    for key in ('builder', 'runtime_base'):
        require(re.fullmatch(DIGEST, m['dependencies'][key]), 'Unpinned build image')
    require(re.fullmatch(DIGEST, m['image']['id']), 'Invalid image config digest')
    require(re.fullmatch(re.escape(IMAGE) + '@' + DIGEST, m['image']['reference']), 'Invalid OCI reference')
    require(re.fullmatch(HASH, m['config_hash']), 'Invalid configuration hash')
    require(m['assets'] and all(re.fullmatch(HASH, h) for h in m['assets'].values()), 'Missing asset hashes')
    require(set(m['gates']) == GATES and all(v is True for v in m['gates'].values()), 'Incomplete release gates')
    require(m['files'] and all(re.fullmatch(HASH, h) for h in m['files'].values()), 'Missing artifact inventory')
    require(m['startup'] == {'sv_pure': '1', 'sv_autoupdate': '0', 'bot_enable': '1'}, 'Unsafe startup contract')
    require(m.get('runtime_data') and all(
        re.fullmatch(r'(?:main|zone)/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+', path)
        and '..' not in Path(path).parts and re.fullmatch(HASH, h)
        for path, h in m['runtime_data'].items()), 'Missing or unsafe game-data hashes')
    require(m['image']['platform'] == 'linux/amd64', 'Unsupported runtime platform')
    require(isinstance(m['source_date_epoch'], int) and m['source_date_epoch'] > 0, 'Missing reproducible epoch')
    require(datetime.fromisoformat(m['created_at']).utcoffset() is not None, 'Missing timezone in build timestamp')
    require(all(re.fullmatch(HASH, m['evidence'][key]) for key in
                ('security_sha256', 'runtime_sha256', 'trivy_binary_sha256')), 'Missing private gate evidence')
    if v[3] is None:
        source = m.get('promotion', {})
        require(VERSION.fullmatch(source.get('candidate', '')) and version(source['candidate'])[:3] == v[:3]
                and version(source['candidate'])[3] is not None, 'Stable requires matching candidate')
        require(isinstance(source.get('deployment_id'), int) and source['deployment_id'] > 0,
                'Stable requires homolog deployment evidence')
        require(re.fullmatch(HASH, source.get('manifest_sha256', '')), 'Missing candidate manifest hash')
    else:
        require(environment != 'production', 'Production rejects prereleases')
        require('promotion' not in m, 'Candidate cannot claim promotion')
    return m


def peeled_tag(tag):
    ref = api(f'repos/{REPO}/git/ref/tags/{tag}')['object']
    for _ in range(5):
        if ref['type'] == 'commit':
            require(re.fullmatch(SHA, ref['sha']), 'Invalid tag commit')
            return ref['sha']
        require(ref['type'] == 'tag', 'Tag does not resolve to a commit')
        ref = api(f'repos/{REPO}/git/tags/{ref["sha"]}')['object']
    raise ValueError('Excessive tag indirection')


def resolve(tag, mode, environment, directory):
    version(tag)  # No network requests for invalid arguments.
    require(environment != 'production' or version(tag)[3] is None, 'Production rejects prereleases')
    release = api(f'repos/{REPO}/releases/tags/{tag}')
    require(release['tag_name'] == tag and release.get('immutable') is True and not release['draft'],
            'Release must be published and immutable')
    require(release['prerelease'] == (version(tag)[3] is not None), 'Release prerelease flag mismatch')
    assets = pages(f'repos/{REPO}/releases/{release["id"]}/assets')
    require(sum(a['name'] == 'release-manifest.json' for a in assets) == 1, 'Missing/duplicate manifest asset')
    run('gh', 'release', 'verify', tag, '--repo', REPO)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'release-manifest.json'
    require(not path.exists(), 'Refusing to overwrite release evidence')
    run('gh', 'release', 'download', tag, '--repo', REPO, '--pattern', path.name, '--dir', str(directory))
    run('gh', 'release', 'verify-asset', tag, str(path), '--repo', REPO)
    m = validate_manifest(json.loads(path.read_text()), tag, mode, environment)
    require(peeled_tag(tag) == m['workspace'], 'Release tag commit mismatch')
    if version(tag)[3] is None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate, _ = resolve(m['promotion']['candidate'], mode, 'homolog', Path(temporary))
            require(sha256(Path(temporary) / path.name) == m['promotion']['manifest_sha256'], 'Candidate changed')
        require(promotion_payload(candidate) == promotion_payload(m), 'Promotion rebuilt or changed candidate')
        verify_homolog_record(candidate, m['promotion']['deployment_id'], m['promotion']['manifest_sha256'])
    return m, release


def promotion_payload(m):
    return {k: v for k, v in m.items() if k not in ('tag', 'promotion', 'created_at')}


def verify_homolog_record(m, deployment_id, manifest_hash):
    d = api(f'repos/{REPO}/deployments/{deployment_id}')
    require(d['environment'] == 'homolog' and d['sha'] == m['workspace'], 'Wrong homolog deployment')
    require(d['payload'] == {'tag': m['tag'], 'image': m['image'], 'manifest_sha256': manifest_hash,
                              'mode': m['mode']}, 'Homolog deployment artifact mismatch')
    statuses = pages(f'repos/{REPO}/deployments/{deployment_id}/statuses')
    require(statuses and statuses[0]['state'] == 'success', 'Homolog deployment is not successful')


def protected_history(repository, commit, local, tip=False):
    require(re.fullmatch(SHA, commit), 'Full commit SHA required')
    branch = api(f'repos/{repository}/branches/master')
    require(branch.get('protected') is True, f'{repository}: master is not protected')
    if branch['commit']['sha'] != commit:
        require(not tip, f'{repository}: commit differs from protected master tip')
        comparison = api(f'repos/{repository}/compare/{commit}...{branch["commit"]["sha"]}')
        require(comparison['status'] == 'ahead', f'{repository}: pin is outside protected master history')
    require(run('git', '-C', str(local), 'rev-parse', 'HEAD') == commit, 'Checkout identity differs')
    require(run('git', '-C', str(local), 'rev-parse', '--is-shallow-repository') == 'false', 'Shallow history')
    require(not run('git', '-C', str(local), 'status', '--porcelain', '--untracked-files=all'), 'Dirty checkout')
    require(not run('git', '-C', str(local), 'replace', '-l'), 'Git replace refs forbidden')
    require(not (Path(local) / '.git/info/grafts').exists(), 'Git grafts forbidden')
    run('git', '-C', str(local), 'fsck', '--full', '--no-dangling')


def publication_preflight(tag):
    version(tag)
    require(api(f'repos/{REPO}/immutable-releases').get('enabled') is True, 'Enable immutable releases first')
    require(api('users/ghptc/packages/container/cod4-runtime')['visibility'] == 'private',
            'Pre-provision a PRIVATE cod4-runtime package; never upload licensed assets publicly')
    protected_tags = False
    for summary in pages(f'repos/{REPO}/rulesets'):
        ruleset = api(f'repos/{REPO}/rulesets/{summary["id"]}')
        if ruleset.get('target') != 'tag' or ruleset.get('enforcement') != 'active':
            continue
        refs = ruleset.get('conditions', {}).get('ref_name', {})
        if 'refs/tags/v*' in refs.get('include', []) and not refs.get('exclude'):
            protected_tags |= {'creation', 'update', 'deletion'}.issubset({r['type'] for r in ruleset['rules']})
    require(protected_tags, 'Active creation/update/deletion ruleset for refs/tags/v* required')
    tags = api(f'repos/{REPO}/git/matching-refs/tags/')
    require(not any(t['ref'] == f'refs/tags/{tag}' for t in tags), 'Tag already exists; never reuse')
    releases = pages(f'repos/{REPO}/releases')
    require(not any(r['tag_name'] == tag for r in releases), 'Release/draft already exists; recover it explicitly')


def verify_registry_image(m):
    run('docker', 'pull', m['image']['reference'])
    image = json.loads(run('docker', 'image', 'inspect', m['image']['reference']))[0]
    require(image['Id'] == m['image']['id'] and m['image']['reference'] in image.get('RepoDigests', []),
            'Registry artifact is unavailable or changed')
    labels = image['Config'].get('Labels') or {}
    expected = {'io.cod4.workspace.revision': m['workspace'],
                'org.opencontainers.image.revision': m['dependencies']['engine'],
                'io.cod4.config.revision': m['dependencies']['config'],
                'io.cod4.bot-warfare.revision': m['dependencies']['bot_warfare'],
                'io.cod4.assets.lock': m['dependencies']['engine_dependencies_sha256'],
                'io.cod4.config.hash': m['config_hash'], 'io.cod4.mode': m['mode']}
    require(all(labels.get(k) == v for k, v in expected.items()), 'Registry image source labels differ')
    require(image['Os'] + '/' + image['Architecture'] == m['image']['platform'], 'Registry platform differs')


def publish(m, directory):
    # Only the manually dispatched, protected workflow is supported as a writer.
    require(os.environ.get('GITHUB_REPOSITORY') == REPO and
            os.environ.get('GITHUB_REF') == 'refs/heads/master' and
            os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch', 'Protected manual workflow required')
    validate_manifest(m, m['tag'], m['mode'], 'homolog')
    if 'promotion' not in m:
        require(expected_version() == m['tag'], 'Version differs from Conventional Commit calculation')
    publication_preflight(m['tag'])
    require(peeled_or_head(m) == m['workspace'], 'Workspace history changed')
    if 'promotion' in m:
        with tempfile.TemporaryDirectory() as temporary:
            candidate, _ = resolve(m['promotion']['candidate'], m['mode'], 'homolog', Path(temporary))
            require(sha256(Path(temporary) / 'release-manifest.json') == m['promotion']['manifest_sha256'],
                    'Candidate evidence changed')
        require(promotion_payload(candidate) == promotion_payload(m), 'Promotion changed artifact')
        verify_homolog_record(candidate, m['promotion']['deployment_id'], m['promotion']['manifest_sha256'])
    verify_registry_image(m)
    manifest = directory / 'release-manifest.json'
    manifest.write_text(canonical(m))
    # Draft first; all assets are verified remotely before reserving the tag.
    draft = api(f'repos/{REPO}/releases', 'POST', {'tag_name': m['tag'], 'target_commitish': m['workspace'],
                'name': m['tag'], 'draft': True, 'prerelease': version(m['tag'])[3] is not None,
                'body': 'Validated immutable runtime. See release-manifest.json for provenance.'})
    run('gh', 'release', 'upload', m['tag'], str(manifest), '--repo', REPO)
    assets = pages(f'repos/{REPO}/releases/{draft["id"]}/assets')
    require(len(assets) == 1 and assets[0]['name'] == manifest.name and
            assets[0]['digest'] == 'sha256:' + sha256(manifest), 'Draft asset digest mismatch')
    # Ref creation is an atomic compare-and-create: a concurrent tag wins, never overwritten.
    api(f'repos/{REPO}/git/refs', 'POST', {'ref': 'refs/tags/' + m['tag'], 'sha': m['workspace']})
    result = api(f'repos/{REPO}/releases/{draft["id"]}', 'PATCH', {'draft': False})
    require(result.get('immutable') is True and not result['draft'], 'Publication requires manual recovery')
    run('gh', 'release', 'verify', m['tag'], '--repo', REPO)
    run('gh', 'release', 'verify-asset', m['tag'], str(manifest), '--repo', REPO)
    return result


def peeled_or_head(m):
    # Stable points to the candidate commit, which must still be in protected history.
    branch = api(f'repos/{REPO}/branches/master')
    require(branch.get('protected') is True, 'Unprotected workspace branch')
    if 'promotion' in m:
        comparison = api(f'repos/{REPO}/compare/{m["workspace"]}...{branch["commit"]["sha"]}')
        require(comparison['status'] in ('ahead', 'identical'), 'Candidate is no longer in master history')
        return m['workspace']
    return branch['commit']['sha']


def record(m, release, environment, manifest_path):
    d = api(f'repos/{REPO}/deployments', 'POST', {
        'ref': m['workspace'], 'environment': environment, 'auto_merge': False,
        'required_contexts': [], 'transient_environment': False,
        'production_environment': environment == 'production',
        'payload': {'tag': m['tag'], 'image': m['image'], 'mode': m['mode'],
                    'manifest_sha256': sha256(manifest_path)},
        'description': f'Healthy {m["tag"]}; release {release["id"]}'})
    api(f'repos/{REPO}/deployments/{d["id"]}/statuses', 'POST', {
        'state': 'success', 'environment': environment, 'auto_inactive': False,
        'description': f'Validated image {m["image"]["id"][:19]}'})
    return d


def inventory(directory):
    # Local evidence only. Never inspect SSH or Docker resources.
    result = {'created_at': datetime.now(timezone.utc).isoformat(), 'remote_access': False, 'files': {}}
    for path in sorted(directory.glob('*')):
        if path.is_file() and (path.name in ('approved', 'prepared') or path.name.startswith('rollback-')):
            result['files'][path.name] = {'sha256': sha256(path), 'bytes': path.stat().st_size}
            if path.name in ('approved', 'prepared'):
                result['files'][path.name]['identity'] = path.read_text().strip().split()
            else:
                d = json.loads(path.read_text())
                result['files'][path.name]['images'] = {k: v.get('image') for k, v in d['services'].items()}
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    for name in ('resolve',):
        q = commands.add_parser(name)
        q.add_argument('tag'); q.add_argument('mode'); q.add_argument('environment', choices=('homolog', 'production'))
        q.add_argument('directory', type=Path)
    q = commands.add_parser('inventory'); q.add_argument('directory', type=Path, nargs='?', default=ROOT / '.state')
    q = commands.add_parser('next-version'); q.add_argument('messages', type=Path)
    q = commands.add_parser('preflight'); q.add_argument('tag')
    q = commands.add_parser('publish'); q.add_argument('manifest', type=Path)
    q = commands.add_parser('promote'); q.add_argument('candidate'); q.add_argument('stable')
    q.add_argument('mode'); q.add_argument('deployment_id', type=int); q.add_argument('directory', type=Path)
    q = commands.add_parser('record'); q.add_argument('manifest', type=Path)
    q.add_argument('environment', choices=('homolog', 'production'))
    a = p.parse_args()
    if a.command == 'resolve':
        m, r = resolve(a.tag, a.mode, a.environment, a.directory)
        print(canonical({'manifest': m, 'release_id': r['id']}), end='')
    elif a.command == 'inventory':
        print(canonical(inventory(a.directory)), end='')
    elif a.command == 'next-version':
        refs = api(f'repos/{REPO}/git/matching-refs/tags/')
        print(next_version([r['ref'].removeprefix('refs/tags/') for r in refs], json.loads(a.messages.read_text())))
    elif a.command == 'preflight':
        publication_preflight(a.tag)
    elif a.command == 'publish':
        print(canonical(publish(json.loads(a.manifest.read_text()), a.manifest.parent)), end='')
    elif a.command == 'promote':
        require(version(a.stable)[3] is None, 'Promotion target must be stable')
        m, _ = resolve(a.candidate, a.mode, 'homolog', a.directory)
        fingerprint = sha256(a.directory / 'release-manifest.json')
        verify_homolog_record(m, a.deployment_id, fingerprint)
        m['promotion'] = {'candidate': a.candidate, 'deployment_id': a.deployment_id, 'manifest_sha256': fingerprint}
        m['tag'] = a.stable
        # Preserve original candidate manifest; publication gets a separate directory.
        target = a.directory / 'stable'; target.mkdir()
        print(canonical(publish(m, target)), end='')
    elif a.command == 'record':
        original = json.loads(a.manifest.read_text())
        with tempfile.TemporaryDirectory() as temporary:
            m, r = resolve(original['tag'], original['mode'], a.environment, Path(temporary))
        require(m == original, 'Deployment manifest differs from release')
        print(canonical(record(m, r, a.environment, a.manifest)), end='')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        sys.exit(f'Release error: {exc}')
