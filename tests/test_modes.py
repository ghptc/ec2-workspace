"""Local catalog/startup fixtures; no Docker daemon, SSH or licensed assets."""
import copy
import hashlib
import json
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import modes
# Avoid a package named runtime elsewhere on the host.
_spec = importlib.util.spec_from_file_location('operations_runtime', Path(modes.__file__).with_name('runtime.py'))
runtime = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runtime)


def write_catalog(root):
    (root / 'shared').mkdir(parents=True)
    (root / 'modes/promod').mkdir(parents=True)
    (root / 'shared/server.cfg').write_text('set sv_pure "1"\nset sv_voice "0"\n')
    (root / 'modes/promod/mode.cfg').write_text('set fs_game "mods/pml220"\n')
    (root / 'modes/promod/server.cfg').write_text(
        'set sv_hostname "Fixture"\nset sv_maxclients "12"\nset g_gametype "sd"\n'
        'set promod_mode "match_mr12_pb"\n'
        'set sv_mapRotation "gametype sd map mp_crash gametype sd map mp_strike"\n')


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        write_catalog(self.root)
        self.metadata = self.root / 'modes/promod/mode.cfg'
        self.server = self.root / 'modes/promod/server.cfg'

    def test_selection_and_mode_isolation(self):
        selected = modes.select(self.root, 'promod')
        self.assertEqual(selected[:2], ('mods/pml220', 'mp_crash'))
        self.assertEqual(selected[3], 'mp_crash,mp_strike')
        other = self.root / 'modes/fixture'
        other.mkdir()
        (other / 'mode.cfg').write_text('set fs_game ""\n')
        (other / 'server.cfg').write_bytes(self.server.read_bytes())
        self.assertEqual(modes.select(self.root, 'fixture')[0], '')
        self.assertEqual(modes.select(self.root, 'promod'), selected)
        other.rename(self.root / 'removed-mode')
        self.assertEqual(modes.select(self.root, 'promod'), selected)

    def test_unknown_identifier(self):
        for name in ('absent', '../promod', 'Promod', ''):
            with self.subTest(name=name), self.assertRaises(ValueError):
                modes.select(self.root, name)

    def test_metadata_rejection(self):
        for data in ('', '// comment\n', 'set fs_game "mods/../secret"\n',
                     'set fs_game "mods/pml220"; quit\n', 'exec private.cfg\n',
                     'set fs_game "mods/pml220"\nset fs_game "mods/other"\n',
                     'set fs_game "mods/pml220"\nset developer "1"\n'):
            self.metadata.write_text(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                modes.select(self.root, 'promod')

    def test_required_files_and_symlinks(self):
        self.metadata.rename(self.root / 'saved')
        with self.assertRaises(ValueError):
            modes.select(self.root, 'promod')
        self.metadata.symlink_to(self.root / 'saved')
        with self.assertRaises(ValueError):
            modes.select(self.root, 'promod')

    def test_bad_sibling_not_silently_skipped(self):
        (self.root / 'modes/incomplete').mkdir()
        with self.assertRaises(ValueError):
            modes.select(self.root, 'promod')

    def test_invalid_directory_and_parent_symlink(self):
        (self.root / 'modes/promod').rename(self.root / 'modes/Promod')
        with self.assertRaises(ValueError):
            modes.select(self.root, 'promod')
        (self.root / 'shared').rename(self.root / 'saved-shared')
        (self.root / 'shared').symlink_to(self.root / 'saved-shared')
        with self.assertRaises(ValueError):
            modes.select(self.root, 'promod')

    def test_invalid_settings(self):
        original = self.server.read_text()
        for extra in ('set rcon_password "never-publish"\n', 'set fs_game "mods/pml220"\n',
                      'set sv_pure "0"\n', 'set sv_voice "1"\n',
                      'set g_gametype "sd"\n', 'set G_GAMETYPE "sd"\n',
                      'set sv_hostname "a\\b"\n'):
            self.server.write_text(original + extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                modes.select(self.root, 'promod')
        self.server.write_text(original + '// Override shared: sv_voice\nset sv_voice "1"\n')
        modes.select(self.root, 'promod')

    def test_rotation_and_capacity(self):
        original = self.server.read_text()
        for old, new in (('gametype sd map mp_crash', 'map mp_crash'),
                         ('set g_gametype "sd"', 'set g_gametype "war"'),
                         ('sv_maxclients "12"', 'sv_maxclients "0"')):
            self.server.write_text(original.replace(old, new))
            with self.subTest(new=new), self.assertRaises(ValueError):
                modes.select(self.root, 'promod')

    def test_hash_binds_all_three_cfgs(self):
        original = modes.select(self.root, 'promod')[2]
        for path in (self.metadata, self.server, self.root/'shared/server.cfg'):
            before = path.read_bytes()
            path.write_bytes(before+b'// reviewed change\n')
            self.assertNotEqual(modes.select(self.root, 'promod')[2], original)
            path.write_bytes(before)


class PackagingTests(unittest.TestCase):
    setUp = CatalogTests.setUp

    def test_btd_packaging_and_rejection(self):
        self.metadata.write_text('set fs_game "mods/btd_alpha_001"\n')
        original_server = self.server.read_text()
        navigation_cases = {'valid_navigation', 'navigation_killhouse', 'missing_navigation_field',
                            'missing_navigation_overlay', 'missing_navigation_file',
                            'tampered_navigation', 'bad_navigation_hash', 'null_navigation_hash',
                            'symlink_navigation', 'symlink_navigation_parent', 'navigation_extra_overlay',
                            'undeclared_navigation'}
        allied_cases = {'valid_allied', 'allied_missing_declaration', 'allied_undeclared_files', 'allied_false_declaration',
                        'allied_string_declaration', 'allied_missing_navigation',
                        'allied_missing_survival_hash', 'allied_bad_zombie_hash',
                        'allied_missing_ammo_hash', 'allied_bad_ammo_hash', 'allied_undeclared_ammo_hash',
                        'allied_missing_ammo', 'allied_tampered_ammo', 'allied_missing_ammo_manifest',
                        'allied_bad_death_hash', 'allied_bad_spawn_hash',
                        'allied_missing_adapter', 'allied_missing_survival', 'allied_missing_zombie',
                        'allied_tampered_adapter', 'allied_tampered_survival', 'allied_tampered_zombie',
                        'allied_undeclared_source', 'allied_extra_manifest', 'allied_symlink_adapter'}
        cases = ('valid', 'tampered', 'path', 'missing', 'wrong_recipe', 'missing_overlay',
                 'tampered_overlay', 'extra_overlay', 'undeclared_source', 'legacy_killhouse',
                 *sorted(navigation_cases | allied_cases))
        for case in cases:
            with self.subTest(case=case):
                self.server.write_text(original_server)
                if case in ('legacy_killhouse', 'navigation_killhouse'):
                    self.server.write_text(original_server.replace('map mp_strike', 'map mp_killhouse'))
                output = self.root / case
                headers = output / 'integrity/addiwdheaders'
                headers.mkdir(parents=True)
                names = {'jcod4x_00.dat'} | {f'localized_english_iw{i:02}.dat' for i in range(7)}
                for name in names:
                    (headers / name).write_bytes(b'header')
                mod = output / 'mods/btd_alpha_001'
                mod.mkdir(parents=True)
                assets = ('mod.ff', 'btd_images.iwd', 'btd_music.iwd', 'btd_weapons.iwd', 'btd_settings.cfg')
                for name in assets:
                    (mod / name).write_bytes(b'private fixture')
                overlay = mod / 'maps/mp/gametypes/_globallogic.gsx'
                overlay.parent.mkdir(parents=True)
                overlay.write_bytes(b'guarded private fixture')
                spawn = mod / 'btd_gametypes/survival/_survival_spawns.gsx'
                spawn.parent.mkdir(parents=True)
                spawn.write_bytes(b'initialized angles fixture')
                (output / 'cod4x18_dedrun').write_bytes(b'engine')
                record = {'maps': ['mp_crash', 'mp_strike', 'mp_killhouse'], 'asset_type': 'btd-alpha-001',
                          'fs_game': 'mods/btd_alpha_001',
                          'binary_sha256': modes.digest(output / 'cod4x18_dedrun'),
                          'headers': {n: modes.digest(headers / n) for n in names},
                          'assets': {n: modes.digest(mod / n) for n in assets},
                          'default_cfgs': ['btd_settings.cfg'],
                          'overlays': {'maps/mp/gametypes/_globallogic.gsx': modes.digest(overlay),
                                       'btd_gametypes/survival/_survival_spawns.gsx': modes.digest(spawn)}}
                if case in navigation_cases | allied_cases:
                    navigation = mod / 'svr/pezbot.gsx'
                    navigation.parent.mkdir()
                    navigation.write_bytes(b'map-specific terminal sentinel fixture')
                    record['navigation_source_sha256'] = 'ebe235fd9a6f5879c1aacb7b79e1ff87fb99d617ca8dd347737e5e88abc91f09'
                    record['overlays']['svr/pezbot.gsx'] = modes.digest(navigation)
                    if case in ('missing_navigation_field', 'undeclared_navigation'):
                        record.pop('navigation_source_sha256')
                    if case == 'undeclared_navigation': record['overlays'].pop('svr/pezbot.gsx')
                    if case == 'missing_navigation_overlay': record['overlays'].pop('svr/pezbot.gsx')
                    if case == 'missing_navigation_file': navigation.unlink()
                    if case == 'tampered_navigation': navigation.write_bytes(b'changed')
                    if case == 'bad_navigation_hash': record['navigation_source_sha256'] = '0' * 64
                    if case == 'null_navigation_hash': record['navigation_source_sha256'] = None
                    if case == 'symlink_navigation':
                        target = output / 'external-navigation'
                        navigation.rename(target)
                        navigation.symlink_to(target)
                    if case == 'symlink_navigation_parent':
                        target = output / 'external-svr'
                        navigation.parent.rename(target)
                        navigation.parent.symlink_to(target, target_is_directory=True)
                if case in allied_cases:
                    allied_paths = {'adapter': 'btd_allies.gsx',
                                    'survival': 'btd_gametypes/survival/_survival_logic.gsx',
                                    'zombie': 'k3/_zombie.gsx',
                                    'ammo': 'btd_general/_ammo_drops.gsx'}
                    for name in allied_paths.values():
                        path = mod / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(b'private allied fixture')
                        record['overlays'][name] = modes.digest(path)
                    record.update(allied_bots=True,
                        death_callback_source_sha256='b6ca82d2d1f8dcd0c454d5e193f54ce1c1147619d547cba4472bbe00bfa60861',
                        spawn_points_source_sha256='b351917eb399ffbd3e4a93551d0bb8e62954414ea6b1659ff3b4d83becdc7408',
                        allied_survival_source_sha256='197c86b48d3c11cf7ab2cda46b7d692dce071c1cebc2b73fa4f02830dda6eb11',
                        allied_zombie_source_sha256='0e1713b629a8e9b79fae09161a18193eb3e5cdcc63c301a6650ddb519ceb39c8',
                        allied_ammo_source_sha256='545021b1444b643d270db77fad21767368b94c439a560dd739ed6de6d321b7ad')
                    if case == 'allied_missing_declaration': record.pop('allied_bots')
                    if case == 'allied_undeclared_files':
                        for field in ('allied_bots', 'allied_survival_source_sha256', 'allied_zombie_source_sha256', 'allied_ammo_source_sha256'):
                            record.pop(field)
                        for name in allied_paths.values(): record['overlays'].pop(name)
                    if case == 'allied_false_declaration': record['allied_bots'] = False
                    if case == 'allied_string_declaration': record['allied_bots'] = 'true'
                    if case == 'allied_missing_navigation':
                        record.pop('navigation_source_sha256')
                        record['overlays'].pop('svr/pezbot.gsx')
                        navigation.unlink()
                    if case == 'allied_missing_survival_hash': record.pop('allied_survival_source_sha256')
                    if case == 'allied_missing_ammo_hash': record.pop('allied_ammo_source_sha256')
                    if case == 'allied_undeclared_ammo_hash':
                        for field in ('allied_bots', 'allied_survival_source_sha256', 'allied_zombie_source_sha256'):
                            record.pop(field)
                        for name in allied_paths.values():
                            (mod / name).unlink()
                            record['overlays'].pop(name)
                    if case == 'allied_missing_ammo_manifest': record['overlays'].pop(allied_paths['ammo'])
                    for short in ('zombie', 'death', 'spawn', 'ammo'):

                        if case == 'allied_bad_' + short + '_hash':
                            field = {'zombie': 'allied_zombie_source_sha256', 'death': 'death_callback_source_sha256',
                                     'spawn': 'spawn_points_source_sha256', 'ammo': 'allied_ammo_source_sha256'}[short]
                            record[field] = '0' * 64
                    for short, name in allied_paths.items():
                        path = mod / name
                        if case == 'allied_missing_' + short: path.unlink()
                        if case == 'allied_tampered_' + short: path.write_bytes(b'changed')
                    if case == 'allied_symlink_adapter':
                        path = mod / allied_paths['adapter']
                        target = output / 'external-adapter'
                        path.rename(target)
                        path.symlink_to(target)
                if case in ('undeclared_source', 'allied_undeclared_source'):
                    (mod / 'extra.gsc').write_bytes(b'undeclared source')
                if case in ('extra_overlay', 'navigation_extra_overlay', 'allied_extra_manifest'):
                    extra = mod / 'extra.gsx'
                    extra.write_bytes(b'unreviewed fixture')
                    record['overlays']['extra.gsx'] = modes.digest(extra)
                if case == 'tampered': (mod / 'mod.ff').write_bytes(b'changed')
                if case == 'path': record['default_cfgs'] = ['../server.cfg']
                if case == 'missing': record['assets'].pop('btd_weapons.iwd')
                if case == 'wrong_recipe': record['asset_type'] = 'unknown'
                if case == 'missing_overlay': overlay.unlink()
                if case == 'tampered_overlay': overlay.write_bytes(b'changed')
                (output / 'inputs.json').write_text(json.dumps(record))
                if case not in ('valid', 'valid_navigation', 'navigation_killhouse', 'valid_allied'):
                    with self.assertRaises(ValueError):
                        modes.package(self.root, 'promod', output, 'engine', 'config', 'none')
                    self.assertFalse((output / 'configuration').exists())
                    self.assertFalse((mod / 'canonical-mode.cfg').exists())
                    continue
                modes.package(self.root, 'promod', output, 'engine', 'config', 'none')
                self.assertEqual((mod / 'mod.ff').read_bytes(), b'private fixture')
                self.assertEqual((mod / 'canonical-mode.cfg').read_bytes(), self.server.read_bytes())
                self.assertTrue((mod / 'canonical-shared.cfg').read_text().endswith('exec btd_settings.cfg\n'))
                self.assertNotIn('fps333', json.loads((output / 'inputs.json').read_text()))

    def test_promod_warning_policy_startup_and_disable(self):
        output = self.root / 'runtime'
        headers = output / 'integrity/addiwdheaders'
        headers.mkdir(parents=True)
        names = {'jcod4x_00.dat'} | {f'localized_english_iw{i:02}.dat' for i in range(7)}
        for name in names:
            (headers / name).write_bytes(b'header')
        mod = output / 'mods/pml220'
        (mod / 'promod').mkdir(parents=True)
        overlay = mod / 'promod/servercheck.gsx'
        (mod / 'mod.ff').write_bytes(b'fastfile')
        (output / 'fps333.json').write_text(json.dumps({'mod_ff_sha256': modes.digest(mod / 'mod.ff')}))
        record = {'maps': ['mp_crash', 'mp_strike'],
                  'headers': {name: modes.digest(headers / name) for name in names},
                  'punkbuster_warning_policy_overlay': True}
        (output / 'inputs.json').write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'overlay missing'):
            modes.package(self.root, 'promod', output, 'engine', 'config', 'bots')
        overlay.write_text('verified upstream overlay fixture')
        modes.package(self.root, 'promod', output, 'engine', 'config', 'bots')
        cfg = mod / 'canonical-shared.cfg'
        self.assertEqual(modes.read_cfg(cfg)[0]['promod_allow_no_punkbuster'], '1')
        self.assertEqual(overlay.read_text(), 'verified upstream overlay fixture')
        service = StartupTests()
        service.setUp()
        args = service.adapt()['command']
        self.assertLess(args.index('canonical-mode.cfg'), args.index('+map_rotate'))
        # A private override restores the original warning without removing assets.
        service.service['command'] += ['+set', 'promod_allow_no_punkbuster', '0']
        args = service.adapt()['command']
        self.assertLess(args.index('promod_allow_no_punkbuster'), args.index('canonical-mode.cfg'))
        self.assertLess(args.index('promod_allow_no_punkbuster'), args.index('+map_rotate'))
        self.assertEqual(args[args.index('promod_allow_no_punkbuster') + 1], '0')
        # Packaging without the optional policy leaves the canonical CFG unchanged.
        record['punkbuster_warning_policy_overlay'] = False
        (output / 'inputs.json').write_text(json.dumps(record))
        (output / 'configuration/mode.cfg').unlink()
        (output / 'configuration').rmdir()
        modes.package(self.root, 'promod', output, 'engine', 'config', 'bots')
        self.assertEqual(cfg.read_bytes(), (self.root / 'shared/server.cfg').read_bytes())
        self.assertEqual(modes.read_cfg(mod / 'canonical-shared.cfg')[0]['sv_pure'], '1')
        self.assertEqual(json.loads((output / 'inputs.json').read_text())['headers'], record['headers'])

    def test_selected_package_preserves_assets_and_binds_provenance(self):
        other = self.root / 'modes/other'
        other.mkdir()
        (other/'mode.cfg').write_text('set fs_game "mods/other"\n')
        (other/'server.cfg').write_bytes(self.server.read_bytes())
        output = self.root / 'runtime'
        headers = output/'integrity/addiwdheaders'
        headers.mkdir(parents=True)
        names = {'jcod4x_00.dat'} | {f'localized_english_iw{i:02}.dat' for i in range(7)}
        for name in names:
            (headers/name).write_bytes(b'qualified-header')
        mod = output/'mods/pml220'
        mod.mkdir(parents=True)
        (mod/'mod.ff').write_bytes(b'qualified-333-fastfile')
        (mod/'bots.iwd').write_bytes(b'qualified-bot-warfare')
        fps = {'mod_ff_sha256': modes.digest(mod/'mod.ff')}
        (output/'fps333.json').write_text(json.dumps(fps))
        record = {'maps': ['mp_crash', 'mp_strike'],
                  'headers': {name: modes.digest(headers/name) for name in names},
                  'binary_sha256': 'retained-binary-identity'}
        (output/'inputs.json').write_text(json.dumps(record))
        revisions = ('a'*40, 'b'*40, 'c'*40)
        self.server.write_text(self.server.read_text() + 'set g_allowVote "1"\n')
        with self.assertRaisesRegex(ValueError, 'voting overlay'):
            modes.package(self.root, 'promod', output, *revisions)
        record['map_voting_policy_overlay'] = True
        (output/'inputs.json').write_text(json.dumps(record))
        (mod/'promod').mkdir()
        (mod/'promod/comp.gsx').write_text('verified voting overlay fixture')
        modes.package(self.root, 'promod', output, *revisions)
        result = json.loads((output/'inputs.json').read_text())
        self.assertEqual([result[k] for k in ('engine_revision', 'config_revision', 'bot_revision')],
                         list(revisions))
        self.assertEqual(result['headers'], record['headers'])
        self.assertEqual(result['binary_sha256'], record['binary_sha256'])
        self.assertEqual(result['fps333'], fps)
        self.assertEqual(result['config_hash'], modes.select(self.root, 'promod')[2])
        self.assertEqual(set(result['config_files']),
                         {'shared/server.cfg', 'modes/promod/mode.cfg', 'modes/promod/server.cfg'})
        self.assertEqual((mod/'canonical-shared.cfg').read_bytes(),
                         (self.root/'shared/server.cfg').read_bytes())
        self.assertEqual((mod/'canonical-mode.cfg').read_bytes(), self.server.read_bytes())
        self.assertEqual((output/'configuration/mode.cfg').read_bytes(), self.metadata.read_bytes())
        self.assertFalse((output/'mods/other').exists())
        self.assertEqual((mod/'bots.iwd').read_bytes(), b'qualified-bot-warfare')
        self.assertEqual(modes.digest(mod/'mod.ff'), fps['mod_ff_sha256'])

    def test_missing_or_corrupt_headers(self):
        runtime_root = self.root / 'runtime'
        runtime_root.mkdir()
        (runtime_root/'inputs.json').write_text(json.dumps({'maps':['mp_crash','mp_strike'], 'headers':{}}))
        with self.assertRaisesRegex(ValueError, 'eight'):
            modes.package(self.root, 'promod', runtime_root, 'engine', 'config', 'bots')
        header_dir = runtime_root/'integrity/addiwdheaders'
        header_dir.mkdir(parents=True)
        names = {'jcod4x_00.dat'} | {f'localized_english_iw{i:02}.dat' for i in range(7)}
        for name in names:
            (header_dir/name).write_bytes(b'header')
        record = {'maps':['mp_crash','mp_strike'],
                  'headers':{name:hashlib.sha256(b'header').hexdigest() for name in names}}
        (runtime_root/'inputs.json').write_text(json.dumps(record))
        (header_dir/'jcod4x_00.dat').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'header mismatch'):
            modes.package(self.root, 'promod', runtime_root, 'engine', 'config', 'bots')

    def test_unqualified_rotation_rejected(self):
        runtime_root = self.root / 'runtime'
        runtime_root.mkdir()
        (runtime_root/'inputs.json').write_text(json.dumps({'maps':['mp_crash']}))
        with self.assertRaisesRegex(ValueError, 'not qualified'):
            modes.package(self.root, 'promod', runtime_root, 'engine', 'config', 'bots')


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.service = {
            'entrypoint': ['/home/user/cod4/cod4x18_dedrun'],
            'command': ['+map', 'mp_strike', '+exec', 'server.cfg', '+set', 'fs_game', 'mods/old',
                        '+set', 'rcon_password', 'private$value', '+exec', 'private.cfg'],
            'volumes': [{'target': path} for path in ('/home/user/cod4/main', '/home/user/cod4/zone',
                                                     '/home/user/.callofduty4')],
        }

    def adapt(self, service=None, fs_game='mods/pml220'):
        return runtime.adapt(copy.deepcopy(service or self.service), 'sha256:fixture', 'fixture',
                             'hash', fs_game, 'mp_crash', 'mp_crash,mp_strike', '12')

    def test_order_and_private_precedence(self):
        result = self.adapt()
        args = result['command']
        self.assertEqual(args[:3], ['+set', 'fs_game', 'mods/pml220'])
        self.assertEqual(args[15:17], ['+exec','canonical-shared.cfg'])
        self.assertEqual(args[-3:], ['+exec', 'canonical-mode.cfg', '+map_rotate'])
        self.assertEqual(args[17:-3], ['+exec','server.cfg','+set','rcon_password','private$value',
                                     '+exec','private.cfg'])
        self.assertEqual(args[-1:], ['+map_rotate'])
        self.assertEqual(args[12:15], ['+set','sv_maxclients','12'])
        self.assertEqual(result['volumes'], self.service['volumes'])
        self.assertEqual(self.adapt(result), result)
        self.assertEqual(self.adapt(fs_game='')['command'][:3], ['+set','fs_game',''])

    def test_managed_updater_opt_out(self):
        self.service['read_only'] = True
        result = self.adapt()
        args = result['command']
        self.assertEqual(args[9:12], ['+set', 'sv_autoupdate', '0'])
        self.assertTrue(result['read_only'])
        self.assertEqual(result['volumes'], self.service['volumes'])
        self.assertEqual(self.adapt(result), result)
        for extra in (['+set', 'sv_autoupdate', '1'], ['+set', 'SV_AUTOUPDATE', '0'],
                      ['+set', 'sv_autoupdate', '0', '+set', 'sv_autoupdate', '0']):
            service = copy.deepcopy(self.service)
            service['command'] += extra
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.adapt(service)

    def test_default_initial_map_and_legacy_exec_migration(self):
        self.service['command'] = ['+exec','canonical-promod.cfg','+exec','server.cfg']
        args = self.adapt()['command']
        self.assertNotIn('canonical-promod.cfg', args)
        self.assertEqual(args[-1:], ['+map_rotate'])
        self.assertEqual(args.count('server.cfg'), 1)

    def test_existing_homolog_filesystem_command_and_runtime_preserved(self):
        # Exact argv from the locally saved homolog Compose snapshot; no EC2 access.
        self.service['command'] = [
            '+set', 'dedicated', '2', '+set', 'net_ip', '0.0.0.0',
            '+set', 'net_port', '28960', '+set', 'fs_basepath', '/home/user/cod4',
            '+set', 'fs_homepath', '/home/user/.callofduty4',
            '+set', 'fs_game', 'mods/pml220', '+set', 'fs_localizedHeadersPath', '/opt/integrity',
            '+set', 'com_zoneMegs', '64', '+set', 'sv_maxclients', '12',
            '+set', 'sv_pure', '1', '+set', 'bot_enable', '1',
            '+exec', 'server.cfg', '+map', 'mp_crash',
        ]
        self.service.update(user='1000:1000', read_only=True, pids_limit=128,
                            tmpfs=['/tmp:rw,nosuid,size=64m'], restart='no',
                            ports=[{'target': 28960, 'published': '28962', 'protocol': 'udp'}],
                            environment={'PRIVATE_FIXTURE': 'retained'})
        for mount in self.service['volumes']:
            mount.update(type='bind', source='/fixture'+mount['target'],
                         read_only=mount['target'] != runtime.PERSISTENT_HOME,
                         bind={'create_host_path': True})
        self.service['volumes'].extend([
            {'type': 'bind', 'source': '/fixture/private.cfg',
             'target': runtime.PERSISTENT_HOME+'/main/server.cfg', 'read_only': True},
            {'type': 'volume', 'source': 'fixture-usermaps', 'target': '/home/user/cod4/usermaps'},
        ])
        result = self.adapt()
        for key in self.service.keys() - {'entrypoint', 'command'}:
            self.assertEqual(result[key], self.service[key], key)
        args = result['command']
        self.assertEqual(args.count('fs_homepath'), 1)
        self.assertEqual(args[args.index('fs_homepath')+1], runtime.PERSISTENT_HOME)
        self.assertEqual(args[:3], ['+set', 'fs_game', 'mods/pml220'])
        self.assertEqual(args[-1:], ['+map_rotate'])
        self.assertEqual(self.adapt(result), result)

    def test_homepath_optional_and_strictly_validated(self):
        self.assertNotIn('fs_homepath', self.adapt()['command'])
        for value in ('/tmp', '/opt/cod4-artifact', '/', '../home', '',
                      '/home/user/.callofduty4/../other', '/home/user/.callofduty4/child'):
            self.service['command'] = ['+set', 'fs_homepath', value]
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Unsafe fs_homepath'):
                self.adapt()
        for args in (
            ['+set', 'FS_HOMEPATH', runtime.PERSISTENT_HOME],
            ['+set', 'fs_homepath', runtime.PERSISTENT_HOME]*2,
            ['+set', 'fs_homepath', runtime.PERSISTENT_HOME,
             '+set', 'FS_HOMEPATH', runtime.PERSISTENT_HOME],
        ):
            self.service['command'] = args
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, 'Ambiguous filesystem'):
                self.adapt()
        self.service['command'] = ['+set', 'fs_cdpath', '/tmp']
        with self.assertRaisesRegex(ValueError, "Unsupported filesystem override: fs_cdpath='/tmp'"):
            self.adapt()

    def test_reject_conflicts(self):
        for command in (
            ['+set','fs_game','mods/a','+set','fs_game','mods/b'],
            ['+set','FS_GAME','mods/a'], ['+set','fs_homepath','/unexpected'],
            ['+set','sv_pure','0'], ['+set','sv_maxclients','65'], ['+map','mp_unqualified'],
            ['+map','mp_crash','+map','mp_strike'], ['+set','rcon_password','value+quit'], ['+set','fs_game'], ['+vstr','unsafe']
        ):
            self.service['command'] = command
            with self.subTest(command=command), self.assertRaises(ValueError):
                self.adapt()

    def test_private_capacity_and_ambiguous_capacity(self):
        self.service['command'] += ['+set', 'sv_maxclients', '16']
        with self.assertRaisesRegex(ValueError, 'mode-owned'):
            self.adapt()
        self.service['command'][-1] = '12'
        self.assertEqual(self.adapt()['command'][12:15], ['+set','sv_maxclients','12'])
        self.service['command'] += ['+set', 'sv_maxclients', '20']
        with self.assertRaises(ValueError):
            self.adapt()

    def test_reject_shadow_mount(self):
        for path in ('/opt', '/', '/opt/cod4-artifact/mods/pml220'):
            service = copy.deepcopy(self.service)
            service['volumes'].append({'target':path})
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.adapt(service)


if __name__ == '__main__':
    unittest.main()
