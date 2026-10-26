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
        self.assertEqual(args[12:16], ['+exec','canonical-shared.cfg','+exec','canonical-mode.cfg'])
        self.assertEqual(args[16:-2], ['+exec','server.cfg','+set','rcon_password','private$value',
                                     '+exec','private.cfg'])
        self.assertEqual(args[-2:], ['+map', 'mp_strike'])
        self.assertEqual(args[9:12], ['+set','sv_maxclients','12'])
        self.assertEqual(result['volumes'], self.service['volumes'])
        self.assertEqual(self.adapt(result), result)
        self.assertEqual(self.adapt(fs_game='')['command'][:3], ['+set','fs_game',''])

    def test_default_initial_map_and_legacy_exec_migration(self):
        self.service['command'] = ['+exec','canonical-promod.cfg','+exec','server.cfg']
        args = self.adapt()['command']
        self.assertNotIn('canonical-promod.cfg', args)
        self.assertEqual(args[-2:], ['+map','mp_crash'])
        self.assertEqual(args.count('server.cfg'), 1)

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
        self.assertEqual(self.adapt()['command'][9:12], ['+set','sv_maxclients','16'])
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
