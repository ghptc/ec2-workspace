#!/usr/bin/env python3
"""Restricted host CLI. RCON activation remains disabled.
Run only on the Docker host as root, with root-owned qualification records.
Uses common.sh snapshot_runtime/apply_runtime and runtime.py adaptation.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import time
import tarfile
import uuid
import shutil

SCRIPTS = Path(__file__).resolve().parent
MODES = {'promod': ('mods/pml220', 'sd'), 'zombies': ('mods/btd_alpha_001', 'war')}
REGISTRY = Path('/etc/cod4-modes/qualified.json')
STATE = Path('/opt/services/cod4/.mode-controller')
EXTERNAL_VERIFIER = Path('/etc/cod4-modes/external-verify')
IMAGE_RE = __import__('re').compile(r'sha256:[0-9a-f]{64}')
DEPLOY_LOCK = Path('/opt/services/cod4/.production-transition.lock')
DEPLOY_GUARD = Path('/opt/services/cod4/.production-deployment.json')
LOCK_FD = None
runtime = None


def load_runtime():
    global runtime
    import types
    source = SCRIPTS / 'runtime.py'
    runtime = types.ModuleType('runtime')
    runtime.__file__ = str(source)
    exec(compile(source.read_bytes(), str(source), 'exec'), runtime.__dict__)


def trusted(path, directory=False):
    """Reject symlinks and writable ancestors; root is the host CLI authority."""
    path = Path(path).absolute()
    for item in (path, *path.parents):
        s = item.lstat()
        if stat.S_ISLNK(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
            raise ValueError(f'Untrusted ownership/permissions: {item}')
    if directory and not path.is_dir():
        raise ValueError('Expected trusted directory')
    return path


def atomic(path, value):
    data = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def run(argv, payload=None, audit=None):
    # Child output can contain private configuration; never echo it on errors.
    result = subprocess.run(argv, input=payload, text=True, capture_output=True, timeout=300,
                            pass_fds=(() if LOCK_FD is None else (LOCK_FD,)))
    if audit is not None:
        atomic(audit, {'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
    if result.returncode:
        suffix = f'; private diagnostics: {audit}' if audit is not None else ''
        raise RuntimeError(f'{argv[0]} failed with exit {result.returncode}{suffix}')
    return result.stdout


def primitive(operation, payload=None, audit=None):
    scripts = {
        'snapshot': 'select_environment production; snapshot_runtime; printf "%s\\n" "$config"',
        'apply': 'select_environment production; project=cod4-production; service=cod4; work=/opt/services/cod4; apply_runtime',
    }
    return run(['bash', '-c', 'set -euo pipefail; source "$1/common.sh"; '
                'remote() { "$@"; }; ' + scripts[operation], 'mode-controller', str(SCRIPTS)], payload, audit)


class Controller:
    container = 'cod4-production'
    project = 'cod4-production'
    udp_port = 28960
    private_home = Path('/opt/services/cod4/production/home')
    readiness_timeout = 90

    def __init__(self, state=STATE):
        self.state = state
        self.current = None
        self.audit_sequence = 0
        self.operation = None

    def inspect(self):
        return json.loads(run(['docker', 'inspect', self.container]))[0]

    def snapshot(self):
        config = json.loads(primitive('snapshot'))
        return self.validate_snapshot(config)

    def validate_snapshot(self, config):
        if config.get('name') != self.project or set(config['services']) != {'cod4'}:
            raise ValueError('Unexpected production Compose project/services')
        service = config['services']['cod4']
        if service.get('container_name') != self.container or service.get('build'):
            raise ValueError('Expected pinned prebuilt production service')
        if service.get('read_only') is not True:
            raise ValueError('Production root filesystem must be read-only')
        if not any(p.get('protocol') == 'udp' and str(p.get('published')) == str(self.udp_port)
                   and p.get('target') == 28960 for p in service.get('ports', [])):
            raise ValueError('Expected UDP 28960 mapping')
        return config

    def image(self, record, mode):
        image = record['image']
        if not IMAGE_RE.fullmatch(image):
            raise ValueError('Immutable image ID required')
        data = json.loads(run(['docker', 'image', 'inspect', image]))[0]
        labels = data['Config'].get('Labels') or {}
        if data['Id'] != image or labels.get('io.cod4.mode') != mode:
            raise ValueError('Image/mode identity mismatch')
        required = {'org.opencontainers.image.revision', 'org.opencontainers.image.source',
                    'io.cod4.assets.lock', 'io.cod4.bot-warfare.revision',
                    'io.cod4.config.revision', 'io.cod4.config.hash', 'io.cod4.mode',
                    'io.cod4.fs-game', 'io.cod4.startup-map', 'io.cod4.maps', 'io.cod4.maxclients'}
        expected = record['labels']
        if not required.issubset(expected) or any(labels.get(k) != v for k, v in expected.items()):
            raise ValueError('Qualified image provenance mismatch')
        contract = runtime.startup_values(labels)
        if contract[0] != MODES[mode][0]:
            raise ValueError('Qualified fs_game mismatch')
        return labels, contract

    def backup_private(self, config, operation):
        volumes = config['services']['cod4']['volumes']
        homes = [v for v in volumes if v.get('target') == runtime.PERSISTENT_HOME]
        if len(homes) != 1 or homes[0].get('type') != 'bind':
            raise ValueError('Expected one explicit persistent home bind mount')
        source = Path(homes[0]['source'])
        trusted(source.parent, directory=True)
        if source.is_symlink() or source.stat().st_dev != self.state.stat().st_dev:
            raise ValueError('Private home must be a directory on the rollback filesystem')
        if any(v.get('target') != runtime.PERSISTENT_HOME and v.get('type') != 'tmpfs' and v.get('read_only') is not True for v in volumes):
            raise ValueError('Only the private home may be a writable persistent mount')
        if source != self.private_home or not source.is_dir():
            raise ValueError('Unexpected private home source')
        archive = self.state / (operation + '-private.tar.gz')
        with archive.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            with tarfile.open(fileobj=stream, mode='w:gz', dereference=False) as tar:
                tar.add(source, arcname='production/home')
            stream.flush(); os.fsync(stream.fileno())
        with tarfile.open(archive, 'r:gz') as tar: self.validate_members(tar.getmembers())

    def apply(self, config):
        self.audit_sequence += 1
        audit = self.state / f'{self.operation}-apply-{self.audit_sequence}.json'
        primitive('apply', json.dumps(config), audit)

    def query(self, host):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(4)
            s.connect((host, self.udp_port))
            s.send(b'\xff' * 4 + b'getstatus\n')
            data = s.recv(65535)
        if not data.startswith(b'\xff' * 4 + b'statusResponse\n'):
            raise ValueError('Invalid UDP status response')
        fields = data.split(b'\n')[1].split(b'\\')
        return {k.decode(): v.decode() for k, v in zip(fields[1::2], fields[2::2])}

    def external(self, record, operation):
        # A root-owned verifier runs on a separate machine and queries UDP from
        # there. Host hairpin/public-IP queries do not count as external proof.
        trusted(EXTERNAL_VERIFIER)
        self.audit_sequence += 1
        audit = self.state / f'{operation}-external-{self.audit_sequence}.json'
        data = json.loads(run([str(EXTERNAL_VERIFIER), operation], audit=audit))
        if data.get('external') is not True or data.get('operation') != operation:
            raise ValueError('External verifier attestation mismatch')
        return data

    def verify(self, config, mode, record, operation):
        expected = config['services']['cod4']; observed = self.inspect()
        if observed['Image'] != expected['image'] or not observed['State']['Running']:
            raise ValueError('Restored Docker image/state mismatch')
        if not observed['HostConfig']['ReadonlyRootfs']:
            raise ValueError('Container root filesystem is writable')
        for docker_key, compose_key in [('Cmd', 'command'), ('Entrypoint', 'entrypoint'), ('WorkingDir', 'working_dir')]:
            if observed['Config'].get(docker_key) != expected.get(compose_key):
                raise ValueError('Docker startup configuration mismatch')
        before = self.current
        if before is not None:
            mounts = lambda c: sorted(c['Mounts'], key=lambda m: m['Destination'])
            if mounts(observed) != mounts(before) or observed['Config'].get('Env') != before['Config'].get('Env'):
                raise ValueError('Private mounts/environment changed')
            if set(observed['NetworkSettings']['Networks']) != set(before['NetworkSettings']['Networks']):
                raise ValueError('Container networks changed')
            if observed['HostConfig'].get('PortBindings') != before['HostConfig'].get('PortBindings'):
                raise ValueError('Published ports changed')
        # Poll readiness only; this never repeats recreation.
        deadline = time.monotonic() + self.readiness_timeout
        while True:
            try:
                local = self.query('127.0.0.1')
                self.status_values(local, mode)
                health = self.inspect()['State']
                if not health['Running'] or health.get('Health', {}).get('Status', 'healthy') != 'healthy':
                    raise ValueError('Docker health check is not healthy')
                break
            except (OSError, ValueError):
                if time.monotonic() >= deadline: raise
                time.sleep(1)
        observed = self.inspect()
        if observed.get('State', {}).get('Health', {}).get('Status', 'healthy') != 'healthy':
            raise ValueError('Docker health check is not healthy')
        for key, value in expected.get('labels', {}).items():
            if observed['Config'].get('Labels', {}).get(key) != value:
                raise ValueError('Docker runtime labels mismatch')
        self.status_values(self.external(record, operation), mode)

    @staticmethod
    def status_values(values, mode):
        fs_game, gametype = MODES[mode]
        if any(values.get(k) != v for k, v in {'fs_game': fs_game, 'g_gametype': gametype, 'sv_pure': '1'}.items()):
            raise ValueError('UDP mode/gametype/purity mismatch')
        if not values.get('mapname'):
            raise ValueError('UDP map readiness missing')

    def phase(self, tx, phase, **extra):
        now = time.time()
        tx.setdefault('events', []).append({'phase': phase, 'at': now, **extra})
        tx.update(phase=phase, updated_at=now, **extra)
        atomic(self.state / 'active.json', tx)
        atomic(self.state / (tx['operation'] + '.json'), tx)
        print(json.dumps({k: tx[k] for k in ('operation', 'phase', 'previous_mode', 'target_mode')}), flush=True)

    def transition(self, mode, registry, operation=None, on_ready=None):
        if mode not in MODES:
            raise ValueError('Only zombies and promod are allowed')
        active = self.state / 'active.json'
        if active.exists() and json.loads(active.read_text())['phase'] not in ('success', 'rolled_back', 'denied'):
            raise ValueError('Unfinished transition; operator recovery required')
        # All trust/evidence checks precede mutation.
        records = qualification(registry)
        config = self.snapshot()
        self.current = self.inspect()
        baseline = json.loads(json.dumps(config))
        baseline['services']['cod4']['image'] = self.current['Image']
        previous = [m for m, r in records.items() if r['image'] == self.current['Image']]
        if len(previous) != 1:
            raise ValueError('Current image is not an independently qualified rollback target')
        previous = previous[0]
        self.image(records[previous], previous)
        self.verify(baseline, previous, registry, 'preflight')
        if previous == mode:
            print(json.dumps({'phase': 'success', 'mode': mode, 'already_active': True})); return
        labels, contract = self.image(records[mode], mode)
        target = json.loads(json.dumps(config))
        runtime.adapt(target['services']['cod4'], records[mode]['image'], mode,
                      labels['io.cod4.config.hash'], *contract)
        operation = operation or uuid.uuid4().hex
        if not __import__('re').fullmatch(r'[a-f0-9]{32}', operation):
            raise ValueError('Invalid operation identifier')
        tx = {'operation': operation, 'previous_mode': previous, 'target_mode': mode,
              'previous_image': self.current['Image'], 'target_image': records[mode]['image'],
              'operator_uid': os.getuid(), 'started_at': time.time()}
        # Exact private configuration stays in restrictive snapshots, outside the
        # journal and stdout. It is never reconstructed from mode defaults.
        atomic(self.state / (tx['operation'] + '-previous.json'), baseline)
        atomic(self.state / (tx['operation'] + '-target.json'), target)
        atomic(self.state / (tx['operation'] + '-inspection.json'), self.current)
        self.operation = tx['operation']
        self.backup_private(baseline, tx['operation'])
        self.phase(tx, 'pending')
        if on_ready is not None and on_ready(tx) is False:
            self.phase(tx, 'denied', failure='PlayerNotificationUnavailable')
            return
        try:
            self.apply(target)
            self.phase(tx, 'verifying')
            self.verify(target, mode, registry, tx['operation'])
            self.phase(tx, 'success')
        except Exception as error:
            # Keep private subprocess output out of the journal.
            self.phase(tx, 'rolling_back', failure=type(error).__name__, failure_detail=str(error)[:200])
            try:
                self.restore_private(baseline, tx['operation'])
                self.apply(baseline)
                self.verify(baseline, previous, registry, tx['operation'])
            except Exception as rollback:
                self.phase(tx, 'recovery_required', rollback_failure=type(rollback).__name__, rollback_detail=str(rollback)[:200])
                raise RuntimeError('Transition and rollback failed; operator recovery required') from None
            self.phase(tx, 'rolled_back')
            raise RuntimeError('Transition failed; exact previous runtime restored') from None

    def restore_private(self, config, operation):
        """Stop only production before atomically restoring the archived home.

        Keep the failed home privately for diagnosis. Never extract through links.
        """
        if run(['docker', 'ps', '-a', '--filter', 'name=^/' + self.container + '$', '--format', '{{.ID}}']).strip():
            run(['docker', 'stop', '--time', '10', self.container])
        self.restore_home(config, operation)

    def restore_home(self, config, operation):
        home = self.private_home
        mounts = config['services']['cod4']['volumes']
        if [v.get('source') for v in mounts if v.get('target') == runtime.PERSISTENT_HOME] != [str(home)]:
            raise ValueError('Unexpected rollback private home')
        self.extract_home(home, operation)

    @staticmethod
    def validate_members(members):
        links = {m.name for m in members if m.issym() or m.islnk()}
        by_name = {member.name: member for member in members}
        if len(by_name) != len(members): raise ValueError('Duplicate private archive member')
        for member in members:
            name = Path(member.name)
            if str(name) != member.name or name.is_absolute() or '..' in name.parts or name.parts[:2] != ('production', 'home'):
                raise ValueError('Unsafe private archive member')
            if any(str(parent) in links for parent in name.parents):
                raise ValueError('Private archive traverses a link')
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise ValueError('Special private archive member')
            if member.islnk():
                link = Path(member.linkname)
                if str(link) != member.linkname or link.is_absolute() or '..' in link.parts or link.parts[:2] != ('production', 'home') or str(link) in links or any(str(parent) in links for parent in link.parents):
                    raise ValueError('Unsafe archive hard link')
                if str(link) not in by_name or not by_name[str(link)].isfile():
                    raise ValueError('Archive hard link lacks a regular target')

    def extract_home(self, home, operation):
        # Archive contents were produced locally before mutation. Validate again
        # for crash recovery and reject special files or extraction through links.
        stage = self.state / (operation + '-restore-' + uuid.uuid4().hex)
        stage.mkdir(mode=0o700)
        with tarfile.open(self.state / (operation + '-private.tar.gz'), 'r:gz') as tar:
            members = tar.getmembers()
            self.validate_members(members)
            # All destinations and hardlinks are bounded; symlinks have no children.
            tar.extractall(stage, members=members, **({'filter': 'fully_trusted'} if sys.version_info >= (3,12) else {}))
        restored = stage / 'production/home'
        if not restored.is_dir() or restored.is_symlink(): raise ValueError('Missing private archive root')
        failed = self.state / (operation + '-failed-home-' + uuid.uuid4().hex)
        if home.exists(): os.rename(home, failed)
        os.rename(restored, home)
        descriptor = os.open(home.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
        shutil.rmtree(stage)

    def recover(self, registry):
        """Resume only the previous image; revoking the target cannot force it live."""
        active = self.state / 'active.json'
        if not active.exists(): return
        tx = None
        try:
            tx = json.loads(active.read_text())
            if tx['phase'] in ('success', 'rolled_back', 'denied'): return
            operation = tx['operation']
            if not __import__('re').fullmatch(r'[a-f0-9]{32}', operation): raise ValueError('Invalid recovery operation')
            record = rollback_qualification(registry, tx['previous_mode'])
            baseline = json.loads((self.state / (operation + '-previous.json')).read_text())
            if record['image'] != baseline['services']['cod4']['image'] or record['image'] != tx['previous_image']:
                raise ValueError('Recovery image is not qualified')
            self.image(record, tx['previous_mode'])
            self.current = json.loads((self.state / (operation + '-inspection.json')).read_text())
            self.operation = operation
            self.phase(tx, 'rolling_back', failure='InterruptedWorker')
            self.restore_private(baseline, operation)
            self.apply(baseline)
            self.verify(baseline, tx['previous_mode'], registry, operation)
            self.phase(tx, 'rolled_back')
        except Exception:
            if not isinstance(tx, dict) or not __import__('re').fullmatch(r'[a-f0-9]{32}', str(tx.get('operation', ''))):
                shutil.copyfile(active, self.state / ('corrupt-active-' + uuid.uuid4().hex + '.json'))
                tx = {'operation':uuid.uuid4().hex, 'previous_mode':'unknown', 'target_mode':'unknown'}
            self.phase(tx, 'recovery_required', rollback_failure='RecoveryFailed')
            raise RuntimeError('Interrupted transition requires operator recovery') from None


def qualification(registry):
    if registry.get('enabled') is not True:
        raise ValueError('Controller disabled pending reviewed authorization/rollback tests')
    for gate in ('authorization_tests', 'rollback_tests'):
        evidence(registry[gate])
    records = registry['modes']
    if set(records) != set(MODES):
        raise ValueError('Both independently qualified modes must be registered')
    if records['promod'].get('image') == records['zombies'].get('image'):
        raise ValueError('Modes require separate immutable images')
    for mode, record in records.items():
        if record.get('qualified') is not True:
            raise ValueError(f'{mode} is not qualified')
        for gate in ('independent_review', 'mandatory_ci', 'operator_approval', 'gameplay'):
            evidence(record['evidence'][gate])
            if record['evidence'][gate].get('image') != record['image']:
                raise ValueError('Qualification evidence belongs to a different image')
        if record['evidence']['gameplay'].get('actual_client_session') is not True:
            raise ValueError(f'{mode} lacks actual-client gameplay qualification')
    return records


def rollback_qualification(registry, mode):
    # Restoring a previously approved image does not require the failed target
    # or RCON activation to remain approved. Its own evidence must remain valid.
    if mode not in MODES: raise ValueError('Unknown rollback mode')
    record = registry['modes'][mode]
    if record.get('qualified') is not True: raise ValueError('Rollback image not qualified')
    for gate in ('independent_review', 'mandatory_ci', 'operator_approval', 'gameplay'):
        evidence(record['evidence'][gate])
        if record['evidence'][gate].get('image') != record['image']: raise ValueError('Rollback evidence image mismatch')
    if record['evidence']['gameplay'].get('actual_client_session') is not True:
        raise ValueError('Rollback image lacks actual-client qualification')
    return record


def evidence(record):
    path = trusted(Path(record['path']))
    if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
        raise ValueError('Qualification evidence hash mismatch')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('switch', 'status', 'recover'))
    p.add_argument('mode', nargs='?', choices=tuple(MODES))
    args = p.parse_args()
    if os.geteuid() != 0:
        p.error('Host root authorization required; RCON cannot invoke this CLI')
    os.umask(0o077)
    trusted(SCRIPTS, directory=True)
    for path in (Path(__file__), SCRIPTS / 'common.sh', SCRIPTS / 'runtime.py'):
        trusted(path)
    trusted(STATE, directory=True)
    load_runtime()
    global LOCK_FD
    with trusted(DEPLOY_LOCK).open('r') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: p.exit(2, 'busy: another host transition is pending\n')
        if DEPLOY_GUARD.exists() or DEPLOY_GUARD.is_symlink():
            p.exit(2, 'busy: production deployment active or interrupted; operator recovery required\n')
        LOCK_FD = lock.fileno()
        if args.command == 'status':
            active = STATE / 'active.json'
            print(active.read_text() if active.exists() else '{"phase":"idle"}')
        elif args.command == 'recover':
            Controller().recover(json.loads(trusted(REGISTRY).read_text()))
        else:
            if args.mode is None: p.error('switch requires a mode')
            registry = json.loads(trusted(REGISTRY).read_text())
            Controller().transition(args.mode, registry)


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        sys.exit(f'Mode controller stopped: {exc}')
