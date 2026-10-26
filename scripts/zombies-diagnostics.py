#!/usr/bin/env python3
"""Operator-run, read-only P0 collectors. Never launches or configures a client."""
import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

PAYLOAD = ('mod.ff', 'btd_images.iwd', 'btd_music.iwd', 'btd_weapons.iwd')
LABELS = ('connect_requested', 'download_started', 'download_finished',
          'loading_started', 'ring_error', 'joined', 'session_finished')
ERROR = 'CL_CGameNeedsServerCommand: a reliable command was cycled out'


def emit(kind, **fields):
    print(json.dumps({'event': kind, 'observed_utc': datetime.now(timezone.utc).isoformat(),
                      'observer_monotonic_ns': time.monotonic_ns(), **fields}), flush=True)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def prefix_digest(stream, size):
    stream.seek(0)
    h = hashlib.sha256()
    remaining = size
    while remaining:
        chunk = stream.read(min(remaining, 1024 * 1024))
        if not chunk:
            raise ValueError('Log truncated during prefix verification')
        h.update(chunk); remaining -= len(chunk)
    return h.hexdigest()


def snapshot(pid, proc=Path('/proc')):
    directory = proc / str(pid)
    # No cmdline, environ, memory, registry or profiles: these may contain secrets.
    comm = (directory / 'comm').read_text().strip().lower()
    if comm != 'iw3mp.exe':
        raise ValueError('PID must identify the already-running iw3mp.exe process')
    start = (directory / 'stat').read_text().rsplit(')', 1)[1].split()[19]
    files = set()
    with (directory / 'maps').open() as stream:
        for line in stream:
            parts = line.split(None, 5)
            if len(parts) == 6 and parts[5].strip().startswith('/'):
                files.add(parts[5].strip())
    modules = []
    for name in sorted(files):
        path = Path(name)
        if path.suffix.lower() not in ('.dll', '.exe', '.so') and '.so.' not in path.name:
            continue
        item = {'path': name}
        try:
            item.update(bytes=path.stat().st_size, sha256=digest(path))
        except OSError:
            item['hash_unavailable'] = True
        modules.append(item)
    after = (directory / 'stat').read_text().rsplit(')', 1)[1].split()[19]
    if after != start:
        raise ValueError('Process changed during snapshot; discard and repeat')
    return {'pid': pid, 'process_start_ticks': start, 'mapped_files': modules,
            'coverage': 'host mapped files only; Windows loader inventory may be incomplete',
            'hash_scope': 'current on-disk backing paths, not mapped memory; files may have been replaced'}


def extract(line):
    """Allowlist structured fields; never return raw log text or command bodies."""
    line = re.sub(r'\^[0-9]', '', line)
    source = re.match(r'^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z)\s', line)
    base = {'source_utc': source[1]} if source else {}
    body = (line[source.end():] if source else line).strip()
    # Ring/command bodies are arbitrary text: do not scan them for other fields.
    for pattern, field in ((r'^\s*cmd\s+(\d+):', 'dump_ring_slot'),
                           (r'^\s*serverCommand:\s*(\d+)\s*:', 'cgame_requested_sequence')):
        match = re.match(pattern, body)
        if match:
            return [{**base, field: match[1]}]
    if re.search(r'rcon|password|passwd|token|secret|authorization|userinfo', body, re.I):
        return []
    results = []
    ack = re.fullmatch(r'Out of range reliableAcknowledge message from .+ - reliableSequence is (-?\d+), reliableAcknowledge is (-?\d+)', body)
    if ack:
        results.append({'reliable_sequence': int(ack[1]), 'reliable_acknowledge': int(ack[2]),
                        'diagnostic': 'out_of_range_ack'})
    progress = re.fullmatch(r'clientDownload: \d+ : writing position (\d+) with (\d+) bytes of (\d+) bytes', body)
    if progress:
        results.append({'download_offset': int(progress[1]), 'download_block_bytes': int(progress[2]),
                        'download_total_bytes': int(progress[3])})
    if re.fullmatch(r'(?:Error:\s*)?' + re.escape(ERROR), body):
        results.append({'diagnostic': 'command_ring_cycled_out'})
    if re.fullmatch(r'(?:Error:\s*)?CL_CGameNeedsServerCommand: requested a command not received', body):
        results.append({'diagnostic': 'command_not_received'})
    for pattern, field in (
        (r'^serverCommandNumber:\s*(\d+)\s*$', 'requested_ring_index'),
        (r'^(?:"?version"? is:\s*"?)?(?:CoD4 MP|CoD4 X|CoD4x)[ :v]*(\d+\.\d+(?:\.\d+)?)\b', 'reported_version'),
        (r'^protocol\s+(\d+)\s*$', 'reported_protocol'),
    ):
        match = re.search(pattern, body)
        if match:
            results.append({field: match[1]})
            if field == 'reported_version':
                build = re.search(r'\bbuild\s+(\d+)\b', body)
                if build:
                    results.append({'reported_build': build[1]})
    # Only fixed, known BTD basenames are retained; URLs/credentials are omitted.
    started = re.fullmatch(r'clientDownload: (\d+) : begin(?:n)?ing "(?:mods/btd_alpha_001/)?([^"/]+)"', body)
    if started and started[2] in PAYLOAD:
        results.append({'download_file': started[2], 'phase': 'started', 'client_slot': int(started[1])})
    for pattern, event in (
        (r'^SV_SendClientGameState\(\) for .+$', 'server_gamestate_event'),
        (r'^CL_ParseGamestateX?\(\):$', 'client_gamestate_event'),
        (r'^(?:Error:\s*)?EXE_SERVERCOMMANDOVERFLOW$', 'server_command_overflow'),
        (r'^\*{5} CL_BeginDownload(?:Legacy|X)? \*{5}$', 'client_download_begin'),
        (r'^WWW Download finished\. Have to download next file$', 'http_download_file_finished'),
        (r'^clientDownload: .+ Done$', 'server_download_done_callback'),
    ):
        if re.fullmatch(pattern, body):
            results.append({'diagnostic': event})
    return [{**base, **entry} for entry in results]


def filter_stream(stream, skip=0):
    skipped_fragment = False
    if skip:
        stream.seek(skip-1)
        boundary = stream.read(1) == b'\n'
        stream.seek(skip)
        if not boundary:
            skipped_fragment = True
            while True:
                fragment = stream.readline(16385)
                if not fragment or fragment.endswith(b'\n'):
                    break
    lines, matched = 0, 0
    while True:
        line = stream.readline(16385)
        if not line:
            break
        lines += 1
        if len(line) > 16384:
            while line and not line.endswith(b'\n'):
                line = stream.readline(16385)
            continue
        text = line.decode('utf-8', errors='replace')
        for fields in extract(text):
            matched += 1
            emit('log_diagnostic', **fields)
    emit('filter_summary', lines_seen=lines, diagnostics_retained=matched,
         skipped_partial_line=skipped_fragment,
         timing='observer timestamps describe ingestion; only source_utc describes log event time')


def remote(args):
    # All callers supply fixed program/arguments, except validated ISO timestamp.
    return ['ssh', '-F', str(Path.home() / '.ssh/config'), '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
            'aws-prod', shlex.join(args)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('clock')
    mark = sub.add_parser('mark'); mark.add_argument('label', choices=LABELS)
    process = sub.add_parser('process'); process.add_argument('--pid', type=int, required=True)
    payload = sub.add_parser('payload'); payload.add_argument('--directory', type=Path, required=True)
    console = sub.add_parser('console')
    console.add_argument('--file', type=Path)
    console.add_argument('--offset', type=int, default=0)
    console.add_argument('--checkpoint', type=Path)
    checkpoint = sub.add_parser('checkpoint'); checkpoint.add_argument('--file', type=Path, required=True)
    server = sub.add_parser('server')
    server.add_argument('--since', required=True)
    server.add_argument('--follow', action='store_true')
    packet = sub.add_parser('packet-command')
    packet.add_argument('--server-ip', type=ipaddress.ip_address, required=True)
    args = parser.parse_args()
    if args.command == 'clock':
        emit('local_clock', clock='system UTC, synchronization not certified')
    elif args.command == 'mark':
        emit('operator_marker', label=args.label, precision='operator observation, not protocol timestamp')
    elif args.command == 'process':
        emit('client_process', **snapshot(args.pid))
    elif args.command == 'payload':
        for name in PAYLOAD:
            path = args.directory / name
            if path.is_file():
                before = path.stat()
                checksum = digest(path)
                after = path.stat()
                emit('payload_file', name=name, bytes=after.st_size, sha256=checksum,
                     stable_during_read=(before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns))
            else:
                emit('payload_missing', name=name)
    elif args.command == 'console':
        if args.offset < 0:
            raise ValueError('Offset must be nonnegative')
        if args.file:
            with args.file.open('rb') as stream:
                if args.checkpoint:
                    record = json.loads(args.checkpoint.read_text())
                    current = os.fstat(stream.fileno())
                    if (record['device'], record['inode']) != (current.st_dev, current.st_ino):
                        raise ValueError('Log rotated; checkpoint no longer matches')
                    args.offset = record['bytes']
                    if prefix_digest(stream, args.offset) != record['prefix_sha256']:
                        raise ValueError('Log prefix changed; checkpoint invalid')
                if args.offset > os.fstat(stream.fileno()).st_size:
                    raise ValueError('Log truncated; offset exceeds size')
                filter_stream(stream, args.offset)
        else:
            if args.offset or args.checkpoint:
                raise ValueError('Offset requires a seekable --file')
            filter_stream(sys.stdin.buffer)
    elif args.command == 'checkpoint':
        with args.file.open('rb') as stream:
            current = os.fstat(stream.fileno())
            checksum = prefix_digest(stream, current.st_size)
        emit('log_checkpoint', device=current.st_dev, inode=current.st_ino,
             bytes=current.st_size, mtime_ns=current.st_mtime_ns, prefix_sha256=checksum)
    elif args.command == 'server':
        if not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', args.since):
            raise ValueError('--since requires UTC YYYY-MM-DDTHH:MM:SSZ')
        datetime.strptime(args.since, '%Y-%m-%dT%H:%M:%SZ')
        before = time.time_ns()
        result = subprocess.run(remote(['date', '-u', '+%Y-%m-%dT%H:%M:%S.%NZ']),
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True, timeout=20)
        after = time.time_ns()
        stamp = result.stdout.decode().strip()
        if not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{9}Z', stamp):
            raise ValueError('Unexpected server clock response')
        emit('server_clock', remote_utc=stamp, local_before_ns=before, local_after_ns=after,
             rtt_ns=after-before, precision='clock sample bracket includes SSH latency')
        identity = subprocess.run(remote(['docker', 'inspect', '--format',
            '{{.Id}} {{.Image}} {{.State.Running}}', 'cod4-homolog']),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True, timeout=20).stdout.decode().strip()
        match = re.fullmatch(r'([a-f0-9]{64}) (sha256:[a-f0-9]{64}) (true|false)', identity)
        if not match:
            raise ValueError('Unexpected homolog identity response')
        emit('homolog_identity', container_id=match[1], image_id=match[2], running=match[3] == 'true')
        command = ['docker', 'logs', '--timestamps', '--since', args.since, '--tail', '2000']
        if args.follow: command.append('--follow')
        command.append('cod4-homolog')
        child = subprocess.Popen(remote(command), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            filter_stream(child.stdout)
            if child.wait(): raise ValueError('Server log command failed; raw response suppressed')
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill(); child.wait(timeout=5)
    elif args.command == 'packet-command':
        # Print only. Operator chooses whether to run a privileged metadata capture.
        expression = f'host {args.server_ip} and (udp port 28962 or tcp port 80 or tcp port 443)'
        print(shlex.join(['timeout', '--signal=INT', '300', 'sudo', 'tcpdump', '-i', 'any',
                          '-n', '-q', '-tt', '-l', expression]))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        # Exceptions may contain raw log paths/remote data: emit a fixed failure.
        emit('collection_failed', detail='Check permissions, PID, input and connectivity; no raw error retained')
        sys.exit(1)
