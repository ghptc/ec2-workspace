#!/usr/bin/env python3
"""Read the native CFG catalog; never execute configuration as code."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

ID = r'[a-z][a-z0-9-]*'
FS_GAME = r'(?:mods/[A-Za-z0-9_-]+)?'
SETTING = re.compile(r'set ([A-Za-z_][A-Za-z0-9_]*) "([^"\\;\x00-\x1f\x7f]*)"')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_cfg(path):
    if path.is_symlink() or not path.is_file() or not path.stat().st_size:
        raise ValueError(f'Missing, empty or symlinked configuration: {path}')
    settings, overrides = {}, set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith('// Override shared: '):
            overrides.add(line.removeprefix('// Override shared: '))
        if not line or line.startswith('//'):
            continue
        match = SETTING.fullmatch(line)
        if not match:
            raise ValueError(f'Unsupported CFG syntax: {path}')
        key, value = match.groups()
        if key.lower() in {k.lower() for k in settings}:
            raise ValueError(f'Duplicate setting: {key}')
        if re.search(r'password|rcon|token|secret|credential', key, re.I):
            raise ValueError(f'Private setting in public configuration: {key}')
        settings[key] = value
    return settings, overrides


def select(root, requested):
    if not re.fullmatch(ID, requested):
        raise ValueError('Invalid mode identifier')
    for directory in (root / 'shared', root / 'modes'):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(f'Missing or symlinked catalog directory: {directory}')
    shared_path = root / 'shared/server.cfg'
    shared, _ = read_cfg(shared_path)
    catalog = {}
    for directory in sorted((root / 'modes').iterdir(), key=lambda p: p.name.encode()):
        if directory.is_symlink() or not directory.is_dir() or not re.fullmatch(ID, directory.name):
            raise ValueError(f'Invalid mode directory: {directory.name}')
        metadata_path, server_path = directory / 'mode.cfg', directory / 'server.cfg'
        metadata, _ = read_cfg(metadata_path)
        mode, overrides = read_cfg(server_path)
        if set(metadata) != {'fs_game'} or not re.fullmatch(FS_GAME, metadata['fs_game']):
            raise ValueError(f'Invalid startup metadata: {directory.name}')
        if any(key.lower().startswith('fs_') for key in shared | mode):
            raise ValueError('Filesystem settings belong only in mode.cfg')
        shared_keys = {key.lower(): key for key in shared}
        for key in mode:
            if key.lower() in shared_keys and key not in overrides:
                raise ValueError(f'Undocumented shared override: {key}')
            if key.lower() in shared_keys and key != shared_keys[key.lower()]:
                raise ValueError(f'Inconsistent setting capitalization: {key}')
        effective = shared | mode
        if not all(effective.get(k) for k in ('sv_hostname', 'g_gametype', 'sv_mapRotation')):
            raise ValueError(f'Missing required mode settings: {directory.name}')
        if not re.fullmatch(r'[1-9][0-9]*', effective.get('sv_maxclients', '')) or int(effective['sv_maxclients']) > 64:
            raise ValueError('Invalid slot limit')
        if effective.get('sv_pure') != '1':
            raise ValueError('Supported runtime requires sv_pure=1')
        rotation = effective['sv_mapRotation'].split()
        if not rotation or len(rotation) % 4:
            raise ValueError('Invalid map rotation')
        for i in range(0, len(rotation), 4):
            if rotation[i] != 'gametype' or rotation[i+2] != 'map' or not all(
                re.fullmatch(r'[A-Za-z0-9_]+', rotation[j]) for j in (i+1, i+3)
            ):
                raise ValueError('Invalid map rotation group')
        if rotation[1] != effective['g_gametype']:
            raise ValueError('Initial game type differs from rotation')
        paths = (shared_path, metadata_path, server_path)
        hashes = {str(p.relative_to(root)): digest(p) for p in paths}
        fingerprint = hashlib.sha256(('\n'.join(hashes.values())+'\n').encode()).hexdigest()
        catalog[directory.name] = (metadata['fs_game'], rotation[3], fingerprint,
                                   ','.join(dict.fromkeys(rotation[3::4])), effective['sv_maxclients'], hashes)
    if requested not in catalog:
        raise ValueError(f'Unknown mode: {requested}')
    return catalog[requested]


def package(root, mode_id, runtime, engine_revision, config_revision, bot_revision):
    fs_game, startup_map, fingerprint, maps, _, hashes = select(root, mode_id)
    record_path = runtime / 'inputs.json'
    record = json.loads(record_path.read_text())
    if not set(maps.split(',')).issubset(record['maps']):
        raise ValueError('Rotation contains maps not qualified by asset preparation')
    # The engine tool verifies hashes; require all eight outputs to survive packaging.
    expected_headers = {'jcod4x_00.dat'} | {f'localized_english_iw{i:02}.dat' for i in range(7)}
    if set(record['headers']) != expected_headers:
        raise ValueError('Expected all eight administrative IWD headers')
    for name, expected in record['headers'].items():
        if digest(runtime / 'integrity/addiwdheaders' / name) != expected:
            raise ValueError(f'Administrative header mismatch: {name}')
    destination = runtime / (fs_game or 'main')
    mode_settings, _ = read_cfg(root / f'modes/{mode_id}/server.cfg')
    if fs_game == 'mods/pml220' and mode_settings.get('g_allowVote') == '1':
        if record.get('map_voting_policy_overlay') is not True or not (destination / 'promod/comp.gsx').is_file():
            raise ValueError('Enabled native voting requires the verified Promod voting overlay')
    if fs_game == 'mods/pml220' and record.get('bot_readyup_overlay') is True:
        if not (destination / 'promod/readyup.gsx').is_file():
            raise ValueError('Promod bot Ready Up overlay missing')
    defaults = []
    if fs_game != 'mods/pml220':
        if fs_game != 'mods/btd_alpha_001' or record.get('asset_type') != 'btd-alpha-001' or record.get('fs_game') != fs_game:
            raise ValueError('No verified asset recipe for selected fs_game')
        assets = record.get('assets', {})
        required = {'mod.ff', 'btd_images.iwd', 'btd_music.iwd', 'btd_weapons.iwd'}
        if not required.issubset(assets) or digest(runtime / 'cod4x18_dedrun') != record['binary_sha256']:
            raise ValueError('Missing BTD assets or engine identity mismatch')
        for name, expected in assets.items():
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..'):
                raise ValueError('Invalid BTD asset name')
            path = destination / name
            if path.is_symlink() or digest(path) != expected:
                raise ValueError(f'BTD asset identity mismatch: {name}')
        overlay_names = {'maps/mp/gametypes/_globallogic.gsx',
                         'btd_gametypes/survival/_survival_spawns.gsx'}
        overlays = record.get('overlays', {})
        if set(overlays) != overlay_names:
            raise ValueError('Verified BTD death and spawn overlays required')
        for name, expected in overlays.items():
            overlay = destination / name
            if overlay.is_symlink() or not overlay.is_file() or any(
                parent.is_symlink() for parent in overlay.parents if parent != destination.parent
            ):
                raise ValueError('Verified BTD source overlay required')
            if digest(overlay) != expected:
                raise ValueError('BTD source overlay identity mismatch')
        defaults = record.get('default_cfgs', [])
        if not defaults or len(defaults) != len(set(defaults)) or any(
            not re.fullmatch(r'btd_[a-z]+\.cfg', name) or name not in assets for name in defaults
        ):
            raise ValueError('Invalid BTD default CFG list')
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / 'shared/server.cfg', destination / 'canonical-shared.cfg')
    shutil.copyfile(root / f'modes/{mode_id}/server.cfg', destination / 'canonical-mode.cfg')
    if fs_game == 'mods/pml220' and record.get('punkbuster_warning_policy_overlay') is True:
        overlay = destination / 'promod/servercheck.gsx'
        if not overlay.is_file() or not overlay.stat().st_size:
            raise ValueError('Promod PB warning overlay missing')
        # Shared defaults execute before private CFGs and the final mode rules. They can
        # explicitly restore the warning by setting this policy back to zero.
        with (destination / 'canonical-shared.cfg').open('a') as cfg:
            cfg.write('\n// Prepared Promod PB warning policy; authentication unchanged.\n'
                      'set promod_allow_no_punkbuster "1"\n')
    if defaults:
        # Original vendor defaults participate in the shared phase. Private
        # credentials and the final canonical policy still execute afterward.
        with (destination / 'canonical-shared.cfg').open('a') as cfg:
            cfg.write('\n// Verified private original BTD defaults.\n')
            for name in defaults:
                cfg.write(f'exec {name}\n')
    provenance = runtime / 'configuration'
    provenance.mkdir()
    shutil.copyfile(root / f'modes/{mode_id}/mode.cfg', provenance / 'mode.cfg')
    if fs_game == 'mods/pml220':
        fps = json.loads((runtime / 'fps333.json').read_text())
        if digest(destination / 'mod.ff') != fps['mod_ff_sha256']:
            raise ValueError('Rebuilt FPS fastfile differs')
        record['fps333'] = fps
    record.update(engine_revision=engine_revision, config_revision=config_revision,
                  bot_revision=bot_revision, mode_id=mode_id, fs_game=fs_game,
                  startup_map=startup_map, config_hash=fingerprint,
                  config_files=hashes)
    record_path.write_text(json.dumps(record, indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('select', 'package'))
    parser.add_argument('root', type=Path)
    parser.add_argument('mode')
    parser.add_argument('packaging', nargs='*')
    args = parser.parse_args()
    try:
        if args.operation == 'select':
            print('\n'.join(select(args.root, args.mode)[:5]))
        else:
            if len(args.packaging) != 4:
                parser.error('package requires runtime, engine SHA, config SHA and bot SHA')
            package(args.root, args.mode, Path(args.packaging[0]), *args.packaging[1:])
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'Configuration error: {exc}\n')


if __name__ == '__main__':
    main()
