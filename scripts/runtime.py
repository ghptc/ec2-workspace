#!/usr/bin/env python3
"""Adapt and verify startup argv without evaluating private runtime values."""
import json
import re
import sys

ARTIFACT_ROOT = '/opt/cod4-artifact'
EXECUTABLE = ARTIFACT_ROOT + '/cod4x18_dedrun'
CANONICAL = ('canonical-shared.cfg', 'canonical-mode.cfg')
PERSISTENT_HOME = '/home/user/.callofduty4'
# Remove the previous managed exec during migration; private execs stay ordered.
MANAGED_EXECS = set(CANONICAL) | {'canonical-promod.cfg'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def startup_values(labels):
    fs_game = labels.get('io.cod4.fs-game', '')
    startup = labels.get('io.cod4.startup-map', '')
    maps = labels.get('io.cod4.maps', '')
    capacity = labels.get('io.cod4.maxclients', '')
    require(re.fullmatch(r'[1-9][0-9]*', capacity) and int(capacity) <= 64, 'Invalid artifact capacity')
    require('io.cod4.fs-game' in labels and re.fullmatch(r'(?:mods/[A-Za-z0-9_-]+)?', fs_game),
            'Invalid artifact fs_game')
    require(re.fullmatch(r'[A-Za-z0-9_]+', startup) and startup in maps.split(','),
            'Invalid artifact startup map')
    require(all(re.fullmatch(r'[A-Za-z0-9_]+', value) for value in maps.split(',')),
            'Invalid artifact map list')
    return fs_game, startup, maps, capacity


def adapt(service, image, mode_id, fingerprint, fs_game, startup, maps, capacity):
    service['image'] = image
    targets = [v.get('target', '') for v in service.get('volumes', []) if isinstance(v, dict)]
    require({'/home/user/cod4/main', '/home/user/cod4/zone', '/home/user/.callofduty4'}.issubset(targets),
            'Expected game-data and persistent home mounts missing')
    require(not any(p == '/' or p == ARTIFACT_ROOT or ARTIFACT_ROOT.startswith(p.rstrip('/')+'/') or
                    p.startswith(ARTIFACT_ROOT+'/') for p in targets if p),
            'A mount shadows the packaged artifact')
    require(service.get('entrypoint') in ([EXECUTABLE], ['/home/user/cod4/cod4x18_dedrun']),
            'Unsupported runtime entrypoint')
    args = service.get('command')
    require(isinstance(args, list) and all(isinstance(a, str) for a in args), 'Expected list-form runtime command')
    managed = {'fs_game': fs_game, 'fs_basepath': ARTIFACT_ROOT,
               'fs_localizedHeadersPath': ARTIFACT_ROOT+'/integrity', 'sv_autoupdate': '0'}
    seen, private, initial_maps, slots = set(), [], [], []
    i = 0
    while i < len(args):
        command = args[i]
        size = {'+set': 3, '+exec': 2, '+map': 2}.get(command)
        require(size and i+size <= len(args), 'Unsupported or incomplete startup command')
        group = args[i:i+size]
        require(not any(any(char in value for char in '+\r\n') for value in group[1:]),
                'Ambiguous startup argument; use a private CFG for command separators')
        if command == '+set':
            key, value = group[1:]
            if key.lower() == 'sv_maxclients':
                require(not slots and re.fullmatch(r'[1-9][0-9]*', value) and int(value) <= 64,
                        'Invalid or ambiguous private capacity')
                slots.append(value)
            elif key.lower() in {k.lower() for k in managed}:
                require(key in managed and key not in seen, f'Ambiguous filesystem selection: {key}')
                require(key != 'sv_autoupdate' or value == '0', 'Managed runtime requires sv_autoupdate=0')
                seen.add(key)
            elif key.lower() == 'fs_homepath':
                # The existing persistent home remains separate from the packaged artifact.
                require(key == 'fs_homepath' and key not in seen,
                        f'Ambiguous filesystem selection: {key}')
                require(value == PERSISTENT_HOME,
                        f'Unsafe fs_homepath: {value!r}; expected {PERSISTENT_HOME}')
                seen.add(key)
                private.extend(group)
            else:
                require(not key.lower().startswith('fs_'), f'Unsupported filesystem override: {key}={value!r}')
                require(key.lower() != 'sv_pure' or value == '1', 'Private argv disables purity')
                private.extend(group)
        elif command == '+exec':
            if group[1] not in MANAGED_EXECS:
                private.extend(group)
        else:
            initial_maps.append(group[1])
        i += size
    require(len(initial_maps) <= 1, 'Ambiguous startup map')
    initial = initial_maps[0] if initial_maps else startup
    require(initial in maps.split(','), 'Private initial map is not qualified for selected mode')
    service['command'] = [item for key, value in managed.items() for item in ('+set', key, value)]
    service['command'] += ['+set', 'sv_maxclients', slots[0] if slots else capacity]
    service['command'] += ['+exec', CANONICAL[0], '+exec', CANONICAL[1]] + private + ['+map', initial]
    service['working_dir'] = ARTIFACT_ROOT
    service['entrypoint'] = [EXECUTABLE]
    labels = service.setdefault('labels', {})
    require(isinstance(labels, dict), 'Expected resolved Compose labels')
    labels.update({'io.cod4.mode': mode_id, 'io.cod4.config.hash': fingerprint})
    return service


def main():
    operation, *args = sys.argv[1:]
    data = json.load(sys.stdin)
    if operation == 'identity':
        image, revision, assets, bots, config, mode, fingerprint, source = args
        labels = data[0]['Config'].get('Labels') or {}
        expected = {'org.opencontainers.image.revision': revision,
                    'org.opencontainers.image.source': source, 'io.cod4.assets.lock': assets,
                    'io.cod4.bot-warfare.revision': bots, 'io.cod4.config.revision': config,
                    'io.cod4.mode': mode, 'io.cod4.config.hash': fingerprint}
        require(data[0]['Id'] == image and all(labels.get(k) == v for k, v in expected.items()),
                'Image source/mode/config/dependency identity mismatch')
        print('\n'.join(startup_values(labels)))
    elif operation == 'adapt':
        service_name, image, mode, fingerprint, fs_game, startup, maps, capacity = args
        adapt(data['services'][service_name], image, mode, fingerprint, fs_game, startup, maps, capacity)
        print(json.dumps(data))
    elif operation == 'verify':
        image, revision, config, mode, fingerprint, fs_game, startup, maps, capacity = args
        c = data[0]
        require(c['Name'] == '/cod4-homolog' and c['Image'] == image and c['State']['Running'],
                'Approved homolog image is not running')
        labels = c['Config'].get('Labels') or {}
        expected = {'org.opencontainers.image.revision': revision, 'io.cod4.config.revision': config,
                    'io.cod4.mode': mode, 'io.cod4.config.hash': fingerprint}
        require(all(labels.get(k) == v for k, v in expected.items()), 'Homolog provenance differs')
        require(startup_values(labels) == (fs_game, startup, maps, capacity), 'Homolog startup metadata differs')
        require(c['Path'] == EXECUTABLE and c['Config'].get('WorkingDir') == ARTIFACT_ROOT,
                'Homolog must run the packaged artifact')
        targets = [m['Destination'] for m in c['Mounts']]
        require(not any(p == '/' or p == ARTIFACT_ROOT or ARTIFACT_ROOT.startswith(p.rstrip('/')+'/') or
                        p.startswith(ARTIFACT_ROOT+'/') for p in targets), 'Homolog mounts shadow artifact')
        # Re-normalization must not change the actual command, including private/map ordering.
        original = c['Config'].get('Cmd')
        service = {'entrypoint': [EXECUTABLE], 'command': original,
                   'volumes': [{'target': t} for t in ('/home/user/cod4/main', '/home/user/cod4/zone',
                                                      '/home/user/.callofduty4')]}
        require(adapt(service, image, mode, fingerprint, fs_game, startup, maps, capacity)['command'] == original,
                'Homolog startup order or filesystem selection differs')
    else:
        raise ValueError('Unknown runtime operation')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        sys.exit(f'Runtime error: {exc}')
