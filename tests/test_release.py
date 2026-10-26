"""Local policy and deployment fixtures. No GitHub, Docker daemon, SSH or EC2."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import release
spec = importlib.util.spec_from_file_location('release_health', ROOT / 'scripts/release-health.py')
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


def manifest():
    return {'schema': 1, 'source_date_epoch': 1793038037, 'created_at': '2026-10-26T18:00:00+00:00',
            'evidence': {k:'0'*64 for k in ('security_sha256','runtime_sha256','trivy_binary_sha256')}, 'repository': release.REPO, 'tag': 'v0.1.0-rc.1', 'mode': 'promod',
            'workspace': 'a'*40, 'dependencies': {
                'engine': 'b'*40, 'config': 'c'*40, 'bot_warfare': 'd'*40,
                'engine_dependencies_sha256': 'e'*64, 'builder': 'sha256:'+'f'*64,
                'runtime_base': 'sha256:'+'1'*64},
            'image': {'id': 'sha256:'+'2'*64, 'reference': release.IMAGE+'@sha256:'+'3'*64,
                      'platform': 'linux/amd64'},
            'config_hash': '4'*64, 'runtime_data': {'main/iw_00.iwd': '0'*64, 'zone/english/common.ff': '1'*64}, 'assets': {'binary': '5'*64}, 'files': {'inputs.json': '6'*64},
            'startup': {'sv_pure': '1', 'sv_autoupdate': '0', 'bot_enable': '1'},
            'gates': {gate: True for gate in release.GATES}}


def reply():
    data = '\n'.join(f'"{k}" is: "{v}^7" default: "{v}^7"' for k, v in {
        'sv_pure': '1', 'sv_autoupdate': '0', 'bot_enable': '1', 'bot_fill_limit': '12',
        'sv_maxclients': '12', 'fs_game': 'mods/pml220'}.items())
    return data + '\nBOT_STATUS enabled=1 state=active humans=0 connecting=0 bots=12 ready=1 pure=1 limit=12 difficulty=fixed\n'


class VersionTests(unittest.TestCase):
    def test_initial_and_rc_sequence(self):
        self.assertEqual(release.next_version([], ['feat: release lifecycle']), 'v0.1.0-rc.1')
        self.assertEqual(release.next_version(['v0.1.0-rc.1'], ['feat: release lifecycle']), 'v0.1.0-rc.2')

    def test_semver_bumps(self):
        for message, expected in [('fix: repair', 'v1.2.4-rc.1'), ('feat(mode): add', 'v1.3.0-rc.1'),
                                  ('feat!: break', 'v2.0.0-rc.1'),
                                  ('fix: change\n\nBREAKING CHANGE: contract', 'v2.0.0-rc.1')]:
            self.assertEqual(release.next_version(['v1.2.3'], [message]), expected)
        self.assertEqual(release.next_version(['v1.9.0', 'v1.10.0'], ['fix: issue']), 'v1.10.1-rc.1')

    def test_invalid_versions_and_commits(self):
        for value in ('master', 'latest', '1.0.0', 'v01.2.3', 'v1.2.3-rc.0', 'v1.2.3;true', 'v1.2.3-rc.01'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                release.version(value)
        for message in ('update stuff', 'chore: docs'):
            with self.assertRaises(ValueError):
                release.next_version(['v1.0.0'], [message])


class PolicyTests(unittest.TestCase):
    def test_successful_candidate_and_stable_contracts(self):
        m = manifest()
        self.assertIs(release.validate_manifest(m, m['tag'], 'promod', 'homolog'), m)
        m['tag'] = 'v0.1.0'
        m['promotion'] = {'candidate': 'v0.1.0-rc.1', 'deployment_id': 123, 'manifest_sha256': '7'*64}
        release.validate_manifest(m, m['tag'], 'promod', 'production')

    def test_every_failed_gate_blocks_publication_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            for gate in release.GATES:
                m = manifest(); m['gates'][gate] = False
                with self.subTest(gate=gate), patch.dict(os.environ, {
                    'GITHUB_REPOSITORY': release.REPO, 'GITHUB_REF': 'refs/heads/master',
                    'GITHUB_EVENT_NAME': 'workflow_dispatch'}), patch.object(release, 'api') as api:
                    with self.assertRaises(ValueError):
                        release.publish(m, Path(directory))
                    api.assert_not_called()
                    self.assertFalse((Path(directory)/'release-manifest.json').exists())

    def test_mutable_inputs_and_missing_identity_rejected(self):
        for path, value in [(('dependencies', 'engine'), 'master'), (('dependencies', 'builder'), 'latest'),
                            (('image', 'reference'), release.IMAGE+':latest'),
                            (('image', 'id'), 'sha256:123'), (('mode',), 'zombies'),
                            (('config_hash',), ''), (('startup', 'bot_enable'), '0'),
                            (('assets',), {}), (('files',), {})]:
            m = manifest(); target = m
            for key in path[:-1]: target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(ValueError):
                release.validate_manifest(m, 'v0.1.0-rc.1', 'promod', 'homolog')

    def test_production_rejects_rc_before_network(self):
        with patch.object(release, 'api') as api, tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                release.resolve('v0.1.0-rc.1', 'promod', 'production', Path(directory))
            api.assert_not_called()

    def test_stable_requires_matching_candidate_evidence(self):
        m = manifest(); m['tag'] = 'v0.1.0'
        for promotion in ({}, {'candidate': 'v0.2.0-rc.1'},
                          {'candidate': 'v0.1.0-rc.1', 'deployment_id': 0, 'manifest_sha256': '7'*64}):
            m['promotion'] = promotion
            with self.assertRaises(ValueError):
                release.validate_manifest(m, m['tag'], 'promod', 'production')

    def test_promotion_payload_keeps_every_artifact_field(self):
        candidate = manifest(); stable = copy.deepcopy(candidate)
        stable['tag'] = 'v0.1.0'; stable['promotion'] = {'deployment_id': 1}
        self.assertEqual(release.promotion_payload(candidate), release.promotion_payload(stable))
        for field in ('image', 'dependencies', 'files', 'assets', 'config_hash', 'workspace'):
            changed = copy.deepcopy(stable); changed[field] = 'tampered'
            self.assertNotEqual(release.promotion_payload(candidate), release.promotion_payload(changed))

    def test_reject_draft_mutable_and_flag_mismatch(self):
        for values in ({'draft': True}, {'immutable': False}, {'prerelease': False}):
            r = {'id': 1, 'tag_name': 'v0.1.0-rc.1', 'draft': False, 'immutable': True, 'prerelease': True} | values
            with patch.object(release, 'api', return_value=r), patch.object(release, 'run') as run:
                with self.assertRaises(ValueError):
                    release.resolve('v0.1.0-rc.1', 'promod', 'homolog', Path('/unused'))
                run.assert_not_called()

    def test_resolve_attestation_and_tag_identity(self):
        m = manifest()
        def api(path, *args, **kwargs):
            if '/releases/tags/' in path:
                return {'id': 12, 'tag_name': m['tag'], 'draft': False, 'immutable': True, 'prerelease': True}
            if '/assets?' in path: return [{'name': 'release-manifest.json'}]
            if '/git/ref/' in path: return {'object': {'type': 'commit', 'sha': m['workspace']}}
            raise AssertionError(path)
        with tempfile.TemporaryDirectory() as directory:
            def run(*args, **kwargs):
                if args[:3] == ('gh', 'release', 'download'):
                    (Path(directory)/'release-manifest.json').write_text(release.canonical(m))
                return ''
            with patch.object(release, 'api', side_effect=api), patch.object(release, 'run', side_effect=run) as calls:
                resolved, r = release.resolve(m['tag'], m['mode'], 'homolog', Path(directory))
                self.assertEqual(resolved, m); self.assertEqual(r['id'], 12)
                self.assertTrue(any(c.args[:3] == ('gh', 'release', 'verify-asset') for c in calls.call_args_list))
            with patch.object(release, 'api', side_effect=api), patch.object(release, 'run'):
                with self.assertRaisesRegex(ValueError, 'overwrite'):
                    release.resolve(m['tag'], m['mode'], 'homolog', Path(directory))

    def test_homolog_evidence_checks_exact_artifact_and_latest_status(self):
        m = manifest(); h = '8'*64
        d = {'environment': 'homolog', 'sha': m['workspace'], 'payload': {
            'tag': m['tag'], 'image': m['image'], 'mode': m['mode'], 'manifest_sha256': h}}
        with patch.object(release, 'api', return_value=d), patch.object(release, 'pages', return_value=[{'state': 'success'}]):
            release.verify_homolog_record(m, 123, h)
            with self.assertRaises(ValueError): release.verify_homolog_record(m, 123, '9'*64)
        with patch.object(release, 'api', return_value=d), patch.object(release, 'pages', return_value=[{'state': 'failure'}, {'state': 'success'}]):
            with self.assertRaises(ValueError): release.verify_homolog_record(m, 123, h)

    def test_git_history_dirty_shallow_replace_and_wrong_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            branch = {'protected': True, 'commit': {'sha': 'a'*40}}
            for answers in (['b'*40], ['a'*40, 'true'], ['a'*40, 'false', ' M file'],
                            ['a'*40, 'false', '', 'replace-ref']):
                with patch.object(release, 'api', return_value=branch), patch.object(release, 'run', side_effect=answers):
                    with self.assertRaises(ValueError): release.protected_history(release.REPO, 'a'*40, directory)
            with patch.object(release, 'api', return_value={'protected': False}):
                with self.assertRaises(ValueError): release.protected_history(release.REPO, 'a'*40, directory)

    def test_inventory_redacts_private_configuration_and_preserves_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'approved').write_text('image source hash bot config promod fingerprint\n')
            (root/'rollback-production.json').write_text(json.dumps({'services': {'cod4': {
                'image': 'sha256:old', 'environment': {'RCON_PASSWORD': 'private'}}}}))
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            result = release.inventory(root)
            self.assertNotIn('private', json.dumps(result)); self.assertFalse(result['remote_access'])
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})


class PublicationTests(unittest.TestCase):
    def preflight_api(self, path, *args, **kwargs):
        if path.endswith('immutable-releases'): return {'enabled': True}
        if '/packages/' in path: return {'visibility': 'private'}
        if path.endswith('rulesets/1'): return {'target': 'tag', 'enforcement': 'active',
            'conditions': {'ref_name': {'include': ['refs/tags/v*'], 'exclude': []}},
            'rules': [{'type': k} for k in ('creation','update','deletion')]}
        if '/matching-refs/' in path: return []
        if '/rulesets?' in path: return [{'id': 1}]
        if '/releases?' in path: return []
        raise AssertionError(path)

    def test_preflight_requires_private_registry_immutable_releases_and_tag_protection(self):
        with patch.object(release, 'api', side_effect=self.preflight_api):
            release.publication_preflight('v0.1.0-rc.1')
        for suffix, value in [('immutable-releases', {'enabled': False}),
                              ('cod4-runtime', {'visibility': 'public'}),
                              ('rulesets/1', {'target': 'tag', 'enforcement': 'disabled'})]:
            def api(path, *args, **kwargs):
                self.assertEqual(args, ())
                return value if path.endswith(suffix) else self.preflight_api(path)
            with patch.object(release, 'api', side_effect=api), self.assertRaises(ValueError):
                release.publication_preflight('v0.1.0-rc.1')

    def test_duplicate_tag_and_interrupted_draft_block_without_writes(self):
        for existing in ('tag', 'draft'):
            def api(path, *args, **kwargs):
                self.assertEqual(args, ())
                if existing == 'tag' and '/matching-refs/' in path:
                    return [{'ref': 'refs/tags/v0.1.0-rc.1'}]
                if existing == 'draft' and '/releases?' in path:
                    return [{'tag_name': 'v0.1.0-rc.1', 'draft': True}]
                return self.preflight_api(path)
            with patch.object(release, 'api', side_effect=api), self.assertRaises(ValueError):
                release.publication_preflight('v0.1.0-rc.1')

    def test_publication_orders_verified_draft_before_tag_and_public_release(self):
        with tempfile.TemporaryDirectory() as directory:
            self.exercise_publication(Path(directory), False)

    def test_concurrent_atomic_tag_creation_failure_keeps_draft_unpublished(self):
        with tempfile.TemporaryDirectory() as directory:
            self.exercise_publication(Path(directory), True)

    def exercise_publication(self, root, concurrent):
        m = manifest(); writes = []
        def api(path, method='GET', data=None):
            if method != 'GET': writes.append((path, method, data))
            if method == 'POST' and path.endswith('/releases'): return {'id': 1}
            if method == 'POST' and path.endswith('/git/refs'):
                if concurrent: raise ValueError('422 reference already exists')
                return {}
            if method == 'PATCH': return {'immutable': True, 'draft': False}
            raise AssertionError(path)
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': release.REPO, 'GITHUB_REF': 'refs/heads/master',
                                     'GITHUB_EVENT_NAME': 'workflow_dispatch'}), \
             patch.object(release, 'expected_version', return_value=m['tag']), \
             patch.object(release, 'publication_preflight'), patch.object(release, 'verify_registry_image'), patch.object(release, 'peeled_or_head', return_value=m['workspace']), \
             patch.object(release, 'api', side_effect=api), patch.object(release, 'run'), \
             patch.object(release, 'pages', side_effect=lambda _: [{'name': 'release-manifest.json',
                                      'digest': 'sha256:'+release.sha256(root/'release-manifest.json')}]):
            if concurrent:
                with self.assertRaises(ValueError): release.publish(m, root)
                self.assertFalse(any(w[1] == 'PATCH' for w in writes))
            else:
                release.publish(m, root)
                self.assertEqual([w[1] for w in writes], ['POST', 'POST', 'PATCH'])
                self.assertTrue(writes[0][2]['draft']); self.assertFalse(writes[-1][2]['draft'])


class EffectiveConfigurationTests(unittest.TestCase):
    def test_qualified_bot_startup_and_humans(self):
        health.validate(reply(), 'mods/pml220', '12', empty=True)
        health.validate(reply().replace('humans=0', 'humans=2').replace('bots=12', 'bots=10'), 'mods/pml220', '12')

    def test_bot_and_security_parity_fail_closed(self):
        for old, new in [('"sv_pure" is: "1', '"sv_pure" is: "0'),
                         ('"sv_autoupdate" is: "0', '"sv_autoupdate" is: "1'),
                         ('"bot_enable" is: "1', '"bot_enable" is: "0'),
                         ('"bot_fill_limit" is: "12', '"bot_fill_limit" is: "0'),
                         ('ready=1', 'ready=0'), ('state=active', 'state=paused-with-humans'),
                         ('humans=0', 'humans=13')]:
            with self.subTest(old=old), self.assertRaises(ValueError):
                health.validate(reply().replace(old, new), 'mods/pml220', '12')
        with self.assertRaises(ValueError): health.validate('Bad rconpassword', 'mods/pml220', '12')


class DeploymentTransactionTests(unittest.TestCase):
    def fixture(self, root):
        m = manifest(); (root/'release-manifest.json').write_text(release.canonical(m))
        labels = {'org.opencontainers.image.revision': m['dependencies']['engine'],
                  'org.opencontainers.image.source': 'https://github.com/ghptc/cod4x-server.git',
                  'io.cod4.assets.lock': m['dependencies']['engine_dependencies_sha256'],
                  'io.cod4.bot-warfare.revision': m['dependencies']['bot_warfare'],
                  'io.cod4.config.revision': m['dependencies']['config'], 'io.cod4.mode': 'promod',
                  'io.cod4.config.hash': m['config_hash'], 'io.cod4.workspace.revision': m['workspace'],
                  'io.cod4.fs-game': 'mods/pml220', 'io.cod4.startup-map': 'mp_crash',
                  'io.cod4.maps': 'mp_crash,mp_strike', 'io.cod4.maxclients': '12'}
        image = {'Id': m['image']['id'], 'Os': 'linux', 'Architecture': 'amd64',
                 'RepoDigests': [m['image']['reference']], 'Config': {'Labels': labels}}
        (root/'image.json').write_text(json.dumps([image]))
        old = 'sha256:'+'9'*64
        (root/'baseline.json').write_text(json.dumps([{'Image': old}]))
        (root/'current-image').write_text(old)
        (root/'config.json').write_text(json.dumps({'services': {'cod4': {
            'image': old, 'container_name': 'cod4-homolog', 'read_only': True, 'user': '1000:1000',
            'entrypoint': ['/home/user/cod4/cod4x18_dedrun'],
            'command': ['+set', 'fs_game', 'mods/pml220', '+set', 'fs_homepath', '/home/user/.callofduty4',
                        '+exec', 'private.cfg', '+map', 'mp_crash'],
            'volumes': [{'target': v} for v in ('/home/user/cod4/main', '/home/user/cod4/zone', '/home/user/.callofduty4')],
            'environment': {'PRIVATE': 'retained'}, 'ports': [{'target': 28960, 'published': '28962', 'protocol': 'udp'}]}}}))
        return m, image, old

    def invoke(self, root, m, failure='', environment='homolog'):
        script = r'''
set -euo pipefail
source "$REPOSITORY/scripts/common.sh"
source "$REPOSITORY/scripts/release-deploy.sh"
select_environment "$TARGET_ENV"
release_transaction=$FIXTURE
release_active=1
mode_id=promod; artifact=$CANDIDATE
revision=$(printf 'b%.0s' {1..40}); asset_ref=$(printf 'e%.0s' {1..64})
bot_revision=$(printf 'd%.0s' {1..40}); config_revision=$(printf 'c%.0s' {1..40}); config_hash=$(printf '4%.0s' {1..64})
need() { command -v "$1" >/dev/null; }
docker() {
    if [[ "$1 $2" == 'image inspect' ]]; then cat "$FIXTURE/image.json"
    elif [[ "$1 $2" == 'image save' ]]; then printf fixture-image
    else return 1; fi
}
remote() {
    if [[ "$1 $2" == 'docker version' ]]; then printf linux/amd64
    elif [[ "$1 $2 $3" == 'docker image load' ]]; then cat >/dev/null; printf 'image-load\n' >> "$FIXTURE/mutations"
    elif [[ "$1 $2" == 'docker inspect' ]]; then
        if [[ "$*" == *'{{.State.Running}}'* ]]; then printf '%s true' "$CANDIDATE"
        else cat "$FIXTURE/current-image"; fi
    else return 1; fi
}
snapshot_runtime() {
    inspection=$(cat "$FIXTURE/baseline.json"); config=$(cat "$FIXTURE/config.json")
    project=fixture; service=cod4; work=/opt/services/cod4
}
verify_release_data() { :; }
verify_homolog() { printf 'homolog-identity-health\n' >> "$FIXTURE/checks"; }
confirm() { printf 'confirmation\n' >> "$FIXTURE/checks"; }
apply_runtime() {
    local payload next
    payload=$(cat)
    next=$(python3 -c 'import json,sys;print(json.load(sys.stdin)["services"]["cod4"]["image"])' <<< "$payload")
    printf '%s' "$next" > "$FIXTURE/current-image"
    printf '%s\n' "$next" >> "$FIXTURE/mutations"
    if [[ "$FAILURE" == interrupted && "$next" == "$CANDIDATE" ]]; then kill -TERM "$BASHPID"; fi
    [[ "$FAILURE" != recreate || "$next" != "$CANDIDATE" ]]
}
check_health() { [[ "$FAILURE" != udp || $(cat "$FIXTURE/current-image") != "$CANDIDATE" ]]; }
check_release_effective() { [[ "$FAILURE" != effective ]]; }
release_journal validated
if deploy_image "$artifact"; then release_journal complete; else exit 1; fi
'''
        return subprocess.run(['bash', '-c', script], env=os.environ | {
            'REPOSITORY': str(ROOT), 'FIXTURE': str(root), 'CANDIDATE': m['image']['id'],
            'FAILURE': failure, 'TARGET_ENV': environment}, text=True, capture_output=True)

    def test_homolog_and_production_deploy_preserve_private_runtime_without_approval(self):
        for environment in ('homolog', 'production'):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory); m, _, _ = self.fixture(root)
                result = self.invoke(root, m, environment=environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root/'current-image').read_text(), m['image']['id'])
                events = [json.loads(line) for line in (root/'events.jsonl').read_text().splitlines()]
                self.assertEqual([e['state'] for e in events], ['validated','mutating','complete'])
                self.assertTrue(all(e['environment'] == environment for e in events))
                self.assertTrue(all('timestamp' in e and e['version'] == m['tag'] for e in events))
                candidate = json.loads((root/'candidate.json').read_text())['services']['cod4']
                baseline = json.loads((root/'config.json').read_text())['services']['cod4']
                for key in ('volumes','ports','environment','read_only','user'):
                    self.assertEqual(candidate[key], baseline[key])
                self.assertFalse((root/'approved').exists())

    def test_failed_health_configuration_recreation_and_signal_roll_back_exact_baseline(self):
        for failure in ('udp', 'effective', 'recreate', 'interrupted'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); m, _, old = self.fixture(root)
                result = self.invoke(root, m, failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((root/'current-image').read_text(), old, result.stderr)
                events = [json.loads(line) for line in (root/'events.jsonl').read_text().splitlines()]
                self.assertEqual(events[-1]['state'], 'rolled-back', result.stderr)
                self.assertTrue((root/'rollback.json').exists())

    def test_digest_source_mode_and_isolation_failures_cause_no_remote_mutation(self):
        for failure in ('digest','source','mode','readonly','private-capacity'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); m, image, old = self.fixture(root)
                if failure == 'digest': image['RepoDigests'] = [release.IMAGE+'@sha256:'+'8'*64]
                if failure == 'source': image['Config']['Labels']['io.cod4.workspace.revision'] = '8'*40
                if failure == 'mode': image['Config']['Labels']['io.cod4.mode'] = 'zombies'
                (root/'image.json').write_text(json.dumps([image]))
                config = json.loads((root/'config.json').read_text())
                if failure == 'readonly': config['services']['cod4']['read_only'] = False
                if failure == 'private-capacity': config['services']['cod4']['command'] += ['+set','sv_maxclients','1']
                (root/'config.json').write_text(json.dumps(config))
                result = self.invoke(root, m)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root/'mutations').exists(), result.stderr)
                self.assertEqual((root/'current-image').read_text(), old)


class ReleaseScriptValidationTests(unittest.TestCase):
    def test_embedded_python_payloads_compile(self):
        import re
        for script in ('release-build.sh','release-deploy.sh'):
            text = (ROOT/'scripts'/script).read_text()
            for match in re.finditer(r"<<'(PY[A-Z_]*)'\n", text):
                delimiter = '\n'+match[1]+'\n'
                end = text.find(delimiter, match.end())
                self.assertNotEqual(end, -1, script)
                compile(text[match.end():end], script+':'+match[1], 'exec')

    def test_invalid_release_interface_never_contacts_ssh_or_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            import shutil
            shutil.copytree(ROOT/'scripts', root/'scripts')
            for name in ('ssh','docker','gh'):
                path = root/name
                path.write_text('#!/usr/bin/env bash\nprintf unexpected >> "$CALL_LOG"\nexit 90\n')
                path.chmod(0o700)
            for script, args in [('deploy-production.sh',['promod','v1.2.3-rc.1']),
                                 ('deploy-homolog.sh',['../promod','v1.2.3']),
                                 ('deploy-production.sh',['promod','master']),
                                 ('deploy-homolog.sh',['promod','v01.2.3'])]:
                env = os.environ | {'PATH': str(root)+':'+os.environ['PATH'], 'CALL_LOG': str(root/'calls'),
                                    'COD4_HOMOLOG_RCON_PASSWORD': 'fixture', 'COD4_PRODUCTION_RCON_PASSWORD': 'fixture'}
                # A leading-zero version is rejected by Python before API reads; gh itself must not run.
                result = subprocess.run([str(root/'scripts'/script), *args], env=env, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root/'calls').exists(), result.stderr)


class GameDataGateTests(unittest.TestCase):
    def test_exact_readonly_game_data_and_drift_rejection(self):
        import hashlib
        for drift in ('none','content','added','missing','symlink','writable'):
            with self.subTest(drift=drift), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); (root/'game/main').mkdir(parents=True); (root/'game/zone').mkdir()
                for name in ('main/iw_00.iwd','zone/common.ff'): (root/'game'/name).write_bytes(b'authorized fixture')
                m = manifest(); m['runtime_data'] = {
                    name: hashlib.sha256(b'authorized fixture').hexdigest() for name in ('main/iw_00.iwd','zone/common.ff')}
                (root/'release-manifest.json').write_text(json.dumps(m))
                config = {'services': {'cod4': {'volumes': [
                    {'type': 'bind', 'source': '/opt/services/cod4/game/'+name,
                     'target': '/home/user/cod4/'+name, 'read_only': drift != 'writable'} for name in ('main','zone')]}}}
                (root/'config.json').write_text(json.dumps(config))
                if drift == 'content': (root/'game/main/iw_00.iwd').write_bytes(b'changed')
                if drift == 'added': (root/'game/main/additional.iwd').write_bytes(b'extra')
                if drift == 'missing': (root/'game/zone/common.ff').rename(root/'saved.ff')
                if drift == 'symlink':
                    (root/'game/zone/common.ff').rename(root/'saved.ff')
                    (root/'game/zone/common.ff').symlink_to(root/'saved.ff')
                script = '''
set -euo pipefail
source "$REPOSITORY/scripts/common.sh"
source "$REPOSITORY/scripts/release-deploy.sh"
release_transaction=$FIXTURE; service=cod4
config=$(cat "$FIXTURE/config.json")
remote() { bash -c "$3" "$4" "$FIXTURE/game/"; }
verify_release_data
'''
                result = subprocess.run(['bash','-c',script], env=os.environ | {
                    'REPOSITORY': str(ROOT), 'FIXTURE': str(root)}, capture_output=True)
                self.assertEqual(result.returncode == 0, drift == 'none', result.stderr)

    def test_interrupted_transaction_blocks_before_any_remote_or_registry_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); txn = root/'.state/deployments/homolog/transaction.fixture'; txn.mkdir(parents=True)
            (txn/'events.jsonl').write_text('{"state":"mutating"}\n')
            script = '''
set -euo pipefail
source "$REPOSITORY/scripts/common.sh"
source "$REPOSITORY/scripts/release-deploy.sh"
ROOT=$FIXTURE
select_environment homolog
need() { :; }
docker() { printf forbidden >> "$FIXTURE/calls"; return 99; }
remote() { printf forbidden >> "$FIXTURE/calls"; return 99; }
export COD4_HOMOLOG_RCON_PASSWORD=fixture
deploy_release promod v0.1.0-rc.1
'''
            result = subprocess.run(['bash','-c',script], env=os.environ | {
                'REPOSITORY': str(ROOT), 'FIXTURE': str(root)}, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'Unresolved deployment transaction', result.stderr)
            self.assertFalse((root/'calls').exists())
