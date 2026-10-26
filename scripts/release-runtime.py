#!/usr/bin/env python3
"""Exercise the actual packaged image locally, with no network or host ports."""
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import modes
import importlib.util
_spec = importlib.util.spec_from_file_location("release_health", Path(__file__).with_name("release-health.py"))
health = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(health)


def qualify(image, game, stage, mode):
    fs_game, startup, _, _, capacity, _ = modes.select(stage / 'config', mode)
    # Existing local game data is mounted read-only; no live runtime is used.
    command = ['docker', 'run', '--rm', '-i', '--pull', 'never', '--network', 'none', '--read-only',
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
               '--tmpfs', '/tmp:rw,nosuid,noexec,size=128m', '--user', '1000:1000',
               '--mount', f'type=bind,src={game / "main"},dst=/home/user/cod4/main,readonly',
               '--mount', f'type=bind,src={game / "zone"},dst=/home/user/cod4/zone,readonly',
               '--tmpfs', '/home/user/.callofduty4:rw,uid=1000,gid=1000,size=128m', image,
               '+set', 'dedicated', '1', '+set', 'net_ip', '127.0.0.1',
               '+set', 'fs_basepath', '/opt/cod4-artifact', '+set', 'fs_homepath', '/home/user/.callofduty4',
               '+set', 'fs_localizedHeadersPath', '/opt/cod4-artifact/integrity',
               '+set', 'fs_game', fs_game, '+set', 'sv_maxclients', capacity,
               '+set', 'sv_autoupdate', '0', '+exec', 'canonical-shared.cfg',
               '+exec', 'canonical-mode.cfg', '+map_rotate']
    log = stage / 'packaged-console.log'
    with log.open('w') as output:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT, text=True)
        try:
            time.sleep(40)
            proc.stdin.write('sv_pure\nsv_autoupdate\nbot_enable\nbot_fill_limit\nbot_status\nfs_game\nsv_maxclients\n')
            proc.stdin.flush()
            time.sleep(3)
            proc.communicate('quit\n', timeout=30)
            if proc.returncode:
                raise ValueError('Packaged runtime exited unsuccessfully')
        finally:
            if proc.poll() is None:
                # Only this disposable test process; never target a named live container.
                proc.communicate('quit\n', timeout=30)
    text = log.read_text()
    health.validate(text, fs_game, capacity, empty=True)
    if 'Loaded 8 administrative IWD checksums' not in text:
        raise ValueError('Eight administrative headers not confirmed')
    (stage / 'runtime-check.json').write_text(json.dumps({'image': image, 'mode': mode,
        'startup_map': startup, 'effective_configuration': True, 'bots': 12, 'headers': 8}) + '\n')


if __name__ == '__main__':
    qualify(sys.argv[1], Path(sys.argv[2]).resolve(), Path(sys.argv[3]), sys.argv[4])
