#!/usr/bin/env python3
"""Root-owned local IPC bridge; disabled unless explicitly qualified and authorized.

The kernel binds requests to the running production engine. The qualified native
engine's ingress-only dispatcher is trusted; native process compromise is outside
this boundary. No credentials, shell, image or container arguments are accepted.
"""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import select
import socket
import stat
import struct
import subprocess
import sys
import time

SCRIPTS = Path(__file__).resolve().parent
c = None  # Loaded from verified source only, never a sibling bytecode cache.
SOCKET = Path('/run/cod4-mode-bridge/control.sock')
REQUEST = re.compile(rb'C4M1 switch ([a-f0-9]{32}) (promod|zombies)')
TERMINAL = {'success', 'rolled_back', 'denied'}
PHASES = {'idle', 'denied', 'pending', 'verifying', 'success', 'rolling_back', 'rolled_back', 'recovery_required'}


def policy(registry):
    c.qualification(registry)
    if registry.get('rcon_bridge_enabled') is not True:
        raise ValueError('RCON bridge disabled')
    if any(record['labels'].get('io.cod4.rcon-mode-bridge') != 'C4M1' for record in registry['modes'].values()):
        raise ValueError('Both images require the native bridge protocol')
    for gate in ('rcon_security_review', 'rcon_activation_approval'):
        item = registry[gate]
        c.evidence(item)
        if item.get('images') != {m: registry['modes'][m]['image'] for m in c.MODES}:
            raise ValueError('RCON authorization belongs to different images')


def response(channel, code, operation='none', mode='none', phase='idle'):
    if not re.fullmatch(r'(?:[a-f0-9]{32}|none)', operation): operation = 'none'
    if mode not in c.MODES: mode = 'none'
    if code not in PHASES | {'submitted','failed','accepted','busy','replay','already_active','not_qualified','disabled','invalid','unavailable'}: code = 'recovery_required'
    if phase not in PHASES: phase = 'recovery_required'
    try: channel.send(f'C4M1 {code} {operation} {mode} {phase}'.encode())
    except OSError: pass  # The accepted host job outlives the game process.


def public_status(state=None):
    state = state or c.STATE
    path = state / 'active.json'
    if not path.exists(): return 'idle', 'none', 'none'
    data = json.loads(path.read_text())
    return data.get('phase', 'recovery_required'), data.get('operation', 'none'), data.get('target_mode', 'none')


def bridge_status():
    active = c.STATE / 'active.json'
    latest = c.STATE / 'bridge-status.json'
    tx = json.loads(active.read_text()) if active.exists() else {}
    request = json.loads(latest.read_text()) if latest.exists() else {}
    if tx.get('phase') not in TERMINAL | {None} or tx.get('updated_at', 0) >= request.get('updated_at', 0):
        return tx
    return request


def receipt(operation, mode, code, phase):
    c.atomic(c.STATE / 'bridge-status.json', {'operation': operation, 'target_mode': mode,
             'code': code, 'phase': phase, 'updated_at': time.time()})


def process_matches(pid, container_id):
    try:
        proc = Path('/proc') / str(pid)
        executable = (proc/'exe').stat()
        packaged = (proc/'root'/c.runtime.EXECUTABLE.lstrip('/')).stat()
        return ((executable.st_dev, executable.st_ino) == (packaged.st_dev, packaged.st_ino)
                and container_id in (proc/'cgroup').read_text())
    except OSError: return False


def peer_matches(credentials, inspection):
    pid, uid, gid = credentials
    return (pid > 0 and pid == inspection.get('State', {}).get('Pid') and
            inspection.get('State', {}).get('Running') is True and
            inspection.get('Name') == '/cod4-production' and
            inspection.get('Path') == c.runtime.EXECUTABLE and
            re.fullmatch(r'[a-f0-9]{64}', inspection.get('Id', '')) is not None and
            inspection.get('Config', {}).get('Labels', {}).get('io.cod4.rcon-mode-bridge') == 'C4M1' and
            [{k: m.get(k) for k in ('Type','Source','Destination','RW')} for m in inspection.get('Mounts', []) if m.get('Destination') == str(SOCKET.parent)] ==
                [{'Type': 'bind', 'Source': str(SOCKET.parent), 'Destination': str(SOCKET.parent), 'RW': False}] and
            process_matches(pid, inspection['Id']))


def registry():
    return json.loads(c.trusted(c.REGISTRY).read_text())


def worker(operation, mode, peer_pid, container_id, descriptor, lock_fd):
    c.LOCK_FD = lock_fd
    channel = socket.socket(fileno=descriptor) if descriptor >= 0 else None
    controller = c.Controller()
    try:
        rules = registry()
        if mode == 'recover':
            controller.recover(rules); return
        policy(rules)
        inspected = controller.inspect()
        if not peer_matches((peer_pid, 0, 0), inspected) or inspected['Id'] != container_id:
            response(channel, 'denied', operation, mode); return
        request = c.STATE / (operation + '-request.json')
        if request.exists():
            response(channel, 'replay', operation, mode); return
        c.atomic(request, {'operation': operation, 'mode': mode, 'peer_pid': peer_pid,
                           'container_id': container_id, 'requested_at': time.time()})

        def ready(tx):
            response(channel, 'accepted', operation, mode, 'pending')
            # Engine acknowledges the fixed broadcast. Losing the engine/socket
            # cannot cancel an accepted durable transaction: timeout then proceed.
            try:
                channel.settimeout(2)
                data, _, flags, _ = channel.recvmsg(128)
                notified = not flags & socket.MSG_TRUNC and data == f'C4M1 notified {operation}'.encode()
            except OSError: notified = False
            receipt(operation, mode, 'accepted', 'pending')
            tx['players_notified'] = notified
            controller.phase(tx, 'pending', players_notified=notified)
            channel.close()
            if not notified:
                try:
                    current = controller.inspect()
                    if current['State']['Running'] and current['State']['Pid'] == peer_pid: return False
                except Exception: return False
            return True
        controller.transition(mode, rules, operation=operation, on_ready=ready)
        # Already-active is a successful no-op, not a completed transition.
        phase, active_id, _ = public_status()
        if active_id != operation:
            receipt(operation, mode, 'already_active', 'success')
            if channel.fileno() >= 0: response(channel, 'already_active', operation, mode, 'success')
        else: receipt(operation, mode, phase, phase)
    except Exception:
        phase, active_id, active_mode = public_status()
        if phase in ('rolling_back', 'pending', 'verifying', 'recovery_required') and active_id == operation:
            # Startup reconciliation will restore only the previous exact runtime.
            pass
        if active_id != operation:
            receipt(operation, mode, 'not_qualified', 'denied')
        elif phase in TERMINAL | {'recovery_required'}: receipt(operation, mode, phase, phase)
        if channel is not None and channel.fileno() >= 0:
            response(channel, 'not_qualified', operation, mode, 'denied')
    finally:
        if channel is not None: channel.close()


class Bridge:
    def __init__(self):
        self.children = []
        self.inspection = {}
        self.refreshed = 0

    def refresh(self):
        if time.monotonic() - self.refreshed < 1: return
        self.refreshed = time.monotonic()
        try:
            result = subprocess.run(['docker', 'inspect', 'cod4-production'], capture_output=True, text=True, timeout=2, check=True)
            self.inspection = json.loads(result.stdout)[0]
        except Exception: self.inspection = {}

    def lock(self):
        stream = c.trusted(c.DEPLOY_LOCK).open('r')
        try: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: stream.close(); return None
        if c.DEPLOY_GUARD.exists() or c.DEPLOY_GUARD.is_symlink(): stream.close(); return None
        return stream

    def spawn(self, operation, mode, connection=None, credentials=(0, 0, 0)):
        lock = self.lock()
        if lock is None:
            if connection is not None: response(connection, 'busy', operation, mode, 'pending')
            return
        if mode != 'recover': receipt(operation, mode, 'submitted', 'pending')
        log = c.STATE / ('bridge-worker-' + operation + '.log')
        with log.open('ab') as output:
            os.fchmod(output.fileno(), 0o600)
            fd = connection.fileno() if connection is not None else -1
            process = subprocess.Popen([sys.executable, '-I', str(Path(__file__).resolve()), 'worker',
                operation, mode, str(credentials[0]), self.inspection.get('Id', 'none'), str(fd), str(lock.fileno())],
                stdin=subprocess.DEVNULL, stdout=output, stderr=output, start_new_session=True,
                pass_fds=tuple(v for v in (fd, lock.fileno()) if v >= 0))
            self.children.append(process)
        lock.close()  # Worker owns the open-file lease, including subprocesses.

    def recover(self):
        phase, operation, mode = public_status()
        if phase not in TERMINAL | {'idle', 'recovery_required'}:
            self.spawn(operation, 'recover')
        else:
            lock = self.lock()
            if lock is not None:
                status = bridge_status()
                if status.get('code') in ('submitted', 'accepted'):
                    receipt(status['operation'], status['target_mode'], 'failed', 'denied')
                lock.close()

    def handle(self, connection):
        credentials = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        # Reject other processes before expensive trust/qualification operations.
        if not peer_matches(credentials, self.inspection):
            response(connection, 'denied'); return
        connection.settimeout(.2)
        data, _, flags, _ = connection.recvmsg(256)
        if flags & socket.MSG_TRUNC: response(connection, 'invalid'); return
        match = REQUEST.fullmatch(data)
        if data != b'C4M1 status' and match is None:
            response(connection, 'invalid'); return
        operation = match[1].decode() if match else 'none'
        mode = match[2].decode() if match else 'none'
        try: rules = registry()
        except Exception:
            response(connection, 'disabled', operation, mode); return
        if rules.get('rcon_bridge_enabled') is not True:
            response(connection, 'disabled', operation, mode); return
        try: c.qualification(rules)
        except Exception:
            response(connection, 'not_qualified', operation, mode); return
        try: policy(rules)
        except Exception:
            response(connection, 'disabled', operation, mode); return
        if data == b'C4M1 status':
            status = bridge_status()
            phase = status.get('phase', 'idle')
            response(connection, status.get('code', phase), status.get('operation', 'none'), status.get('target_mode', 'none'), phase)
        else:
            operation, mode = (v.decode() for v in match.groups())
            phase, _, _ = public_status()
            if phase == 'recovery_required':
                response(connection, 'recovery_required', operation, mode, phase); return
            self.spawn(operation, mode, connection, credentials)

    def serve(self):
        c.trusted(SOCKET.parent, directory=True)
        # Separate daemon lease allows stale socket cleanup only by one owner.
        with (c.STATE / 'bridge.lock').open('a') as lease:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if SOCKET.exists() or SOCKET.is_symlink():
                if not stat.S_ISSOCK(SOCKET.lstat().st_mode) or SOCKET.lstat().st_uid != 0:
                    raise ValueError('Unexpected bridge socket entry')
                SOCKET.unlink()
            with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as listener:
                listener.bind(str(SOCKET)); os.chmod(SOCKET, 0o666); listener.listen(8)
                self.recover()
                while True:
                    self.refresh()
                    self.children = [p for p in self.children if p.poll() is None]
                    if not self.children: self.recover()
                    if not select.select([listener], [], [], 1)[0]: continue
                    connection, _ = listener.accept()
                    with connection:
                        try: self.handle(connection)
                        except (OSError, ValueError, KeyError): response(connection, 'invalid')


def load_controller():
    import types
    # This small bootstrap must precede execution of any adjacent private code.
    for path in (Path(__file__).absolute(), SCRIPTS/'mode-controller.py'):
        for item in (path, *path.parents):
            metadata = item.lstat()
            if stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
                raise ValueError('Untrusted bridge installation')
    module = types.ModuleType('mode_controller')
    source = SCRIPTS/'mode-controller.py'; module.__file__ = str(source)
    exec(compile(source.read_bytes(), str(source), 'exec'), module.__dict__)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('serve', 'worker'))
    parser.add_argument('worker_args', nargs='*')
    args = parser.parse_args()
    if os.geteuid() != 0: parser.error('Host root authorization required')
    os.umask(0o077)
    global c
    c = load_controller()
    for path in (SCRIPTS, Path(__file__), SCRIPTS/'mode-controller.py', SCRIPTS/'common.sh', SCRIPTS/'runtime.py', c.STATE):
        c.trusted(path, directory=path in (SCRIPTS, c.STATE))
    c.trusted(c.DEPLOY_LOCK)
    if not c.DEPLOY_LOCK.is_file() or stat.S_IMODE(c.DEPLOY_LOCK.stat().st_mode) != 0o644:
        parser.error('Root-owned shared deployment lock mode 0644 required')
    c.load_runtime()
    if args.command == 'serve':
        if args.worker_args: parser.error('serve takes no arguments')
        Bridge().serve()
    else:
        if len(args.worker_args) != 6: parser.error('Invalid internal worker arguments')
        operation, mode, pid, container, descriptor, lock = args.worker_args
        if not re.fullmatch(r'[a-f0-9]{32}', operation) or mode not in {*c.MODES, 'recover'}:
            parser.error('Invalid internal worker')
        # Workers are host-root children, never a container command API.
        worker(operation, mode, int(pid), container, int(descriptor), int(lock))


if __name__ == '__main__':
    try: main()
    except Exception: sys.exit('Mode bridge stopped; inspect private host diagnostics')
