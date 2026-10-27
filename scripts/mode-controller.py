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

SCRIPTS = Path(__file__).resolve().parent
MODES = {'promod': ('mods/pml220', 'sd'), 'zombies': ('mods/btd_alpha_001', 'war')}
REGISTRY = Path('/etc/cod4-modes/qualified.json')
STATE = Path('/opt/services/cod4/.mode-controller')
EXTERNAL_VERIFIER = Path('/etc/cod4-modes/external-verify')
IMAGE_RE = __import__('re').compile(r'sha256:[0-9a-f]{64}')
runtime = None


def load_runtime():
    global runtime
    spec = importlib.util.spec_from_file_location('runtime', SCRIPTS / 'runtime.py')
    runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)


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


def run(argv, payload=None):
    # Child output can contain private configuration; never echo it on errors.
    result = subprocess.run(argv, input=payload, text=True, capture_output=True, timeout=300)
    if result.returncode:
        raise RuntimeError(f'{argv[0]} failed with exit {result.returncode}')
    return result.stdout


def primitive(operation, payload=None):
    scripts = {
        'snapshot': 'select_environment production; snapshot_runtime; printf "%s\\n" "$config"',
        'apply': 'select_environment production; project=cod4-production; service=cod4; work=/opt/services/cod4; apply_runtime',
    }
    return run(['bash', '-c', 'set -euo pipefail; source "$1/common.sh"; '
                'remote() { "$@"; }; ' + scripts[operation], 'mode-controller', str(SCRIPTS)], payload)


class Controller:
    def __init__(self, state=STATE):
        self.state = state
        self.current = None

    def inspect(self):
        return json.loads(run(['docker', 'inspect', 'cod4-production']))[0]

    def snapshot(self):
        config = json.loads(primitive('snapshot'))
        if config.get('name') != 'cod4-production' or set(config['services']) != {'cod4'}:
            raise ValueError('Unexpected production Compose project/services')
        service = config['services']['cod4']
        if service.get('container_name') != 'cod4-production' or service.get('build'):
            raise ValueError('Expected pinned prebuilt production service')
        if service.get('read_only') is not True:
            raise ValueError('Production root filesystem must be read-only')
        if not any(p.get('protocol') == 'udp' and str(p.get('published')) == '28960'
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
        if source != Path('/opt/services/cod4/production/home') or not source.is_dir():
            raise ValueError('Unexpected private home source')
        archive = self.state / (operation + '-private.tar.gz')
        with archive.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            with tarfile.open(fileobj=stream, mode='w:gz', dereference=False) as tar:
                tar.add(source, arcname='production/home')
            stream.flush(); os.fsync(stream.fileno())

    def apply(self, config):
        primitive('apply', json.dumps(config))

    def query(self, host):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(4)
            s.sendto(b'\xff' * 4 + b'getstatus\n', (host, 28960))
            data, _ = s.recvfrom(65535)
        if not data.startswith(b'\xff' * 4 + b'statusResponse\n'):
            raise ValueError('Invalid UDP status response')
        fields = data.split(b'\n')[1].split(b'\\')
        return {k.decode(): v.decode() for k, v in zip(fields[1::2], fields[2::2])}

    def external(self, record, operation):
        # A root-owned verifier runs on a separate machine and queries UDP from
        # there. Host hairpin/public-IP queries do not count as external proof.
        trusted(EXTERNAL_VERIFIER)
        data = json.loads(run([str(EXTERNAL_VERIFIER), operation]))
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
            if observed['Mounts'] != before['Mounts'] or observed['Config'].get('Env') != before['Config'].get('Env'):
                raise ValueError('Private mounts/environment changed')
            if set(observed['NetworkSettings']['Networks']) != set(before['NetworkSettings']['Networks']):
                raise ValueError('Container networks changed')
            if observed['HostConfig'].get('PortBindings') != before['HostConfig'].get('PortBindings'):
                raise ValueError('Published ports changed')
        # Poll readiness only; this never repeats recreation.
        deadline = time.monotonic() + 90
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

    def transition(self, mode, registry):
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
        tx = {'operation': uuid.uuid4().hex, 'previous_mode': previous, 'target_mode': mode,
              'previous_image': self.current['Image'], 'target_image': records[mode]['image'],
              'operator_uid': os.getuid(), 'started_at': time.time()}
        # Exact private configuration stays in restrictive snapshots, outside the
        # journal and stdout. It is never reconstructed from mode defaults.
        atomic(self.state / (tx['operation'] + '-previous.json'), baseline)
        atomic(self.state / (tx['operation'] + '-target.json'), target)
        self.backup_private(baseline, tx['operation'])
        self.phase(tx, 'pending')
        try:
            self.apply(target)
            self.phase(tx, 'verifying')
            self.verify(target, mode, registry, tx['operation'])
            self.phase(tx, 'success')
        except Exception as error:
            # Keep private subprocess output out of the journal.
            self.phase(tx, 'rolling_back', failure=type(error).__name__, failure_detail=str(error)[:200])
            try:
                self.apply(baseline)
                self.verify(baseline, previous, registry, tx['operation'])
            except Exception as rollback:
                self.phase(tx, 'recovery_required', rollback_failure=type(rollback).__name__, rollback_detail=str(rollback)[:200])
                raise RuntimeError('Transition and rollback failed; operator recovery required') from None
            self.phase(tx, 'rolled_back')
            raise RuntimeError('Transition failed; exact previous runtime restored') from None


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


def evidence(record):
    path = trusted(Path(record['path']))
    if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
        raise ValueError('Qualification evidence hash mismatch')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('switch', 'status'))
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
    with (STATE / 'transition.lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: p.exit(2, 'busy: another host transition is pending\n')
        if args.command == 'status':
            active = STATE / 'active.json'
            print(active.read_text() if active.exists() else '{"phase":"idle"}')
        else:
            if args.mode is None: p.error('switch requires a mode')
            registry = json.loads(trusted(REGISTRY).read_text())
            Controller().transition(args.mode, registry)


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        sys.exit(f'Mode controller stopped: {exc}')
