"""Catalog pool validation and binding, without remote operations."""
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import modes
from test_modes import write_catalog


class MilitaryNames(unittest.TestCase):
    def test_pool_changes_configuration_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_catalog(root)
            cfg = root / 'modes/promod/server.cfg'
            cfg.write_text(cfg.read_text() + 'set bot_use_names "1"\n')
            pool = root / 'modes/promod/botnames.txt'
            with self.assertRaises(ValueError): modes.select(root, 'promod')
            pool.write_text('Capt. Price\nGaz\n')
            first = modes.select(root, 'promod')
            self.assertIn('modes/promod/botnames.txt', first[-1])
            pool.write_text('Soap MacTavish\nGaz\n')
            self.assertNotEqual(first[2], modes.select(root, 'promod')[2])

    def test_unsafe_duplicate_oversized_and_symlink_pools_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'botnames.txt'
            for content in ('', 'Gaz\ngaz\n', 'x' * 32, 'Bad;quit', '^1Gaz', 'Bad\\name', ' Gaz', 'x' * 8193):
                path.write_text(content)
                with self.subTest(content=content[:40]), self.assertRaises(ValueError): modes.bot_names(path)
            target = path.with_name('source')
            target.write_text('Gaz\n')
            path.unlink(); path.symlink_to(target)
            with self.assertRaises(ValueError): modes.bot_names(path)

    def test_package_binds_names_and_rejects_missing_or_changed_objectives(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_catalog(root)
            cfg = root / 'modes/promod/server.cfg'
            cfg.write_text(cfg.read_text() + 'set bot_use_names "1"\nset bot_sd_objectives "1"\n')
            pool = root / 'modes/promod/botnames.txt'
            pool.write_text('Capt. Price\nGaz\n')
            output = root / 'runtime'
            headers = output / 'integrity/addiwdheaders'
            headers.mkdir(parents=True)
            for name in {'jcod4x_00.dat'} | {f'localized_english_iw{i:02}.dat' for i in range(7)}:
                (headers / name).write_bytes(b'fixture header')
            mod = output / 'mods/pml220'
            mod.mkdir(parents=True)
            (mod / 'mod.ff').write_bytes(b'fixture fastfile')
            (output / 'fps333.json').write_text(json.dumps({'mod_ff_sha256': modes.digest(mod / 'mod.ff')}))
            record = {'maps': ['mp_crash', 'mp_strike'],
                      'headers': {p.name: modes.digest(p) for p in headers.iterdir()}}
            manifest = output / 'inputs.json'
            manifest.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, 'S&D objective preparation'):
                modes.package(root, 'promod', output, 'engine', 'config', 'bots')
            record['sd_objectives_overlay'] = True
            for name, key in [('maps/mp/bots/sd_objectives.gsc', 'sd_objectives_sha256'),
                              ('maps/mp/gametypes/sd.gsx', 'sd_native_overlay_sha256')]:
                path = mod / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('verified fixture')
                record[key] = modes.digest(path)
            manifest.write_text(json.dumps(record))
            ai = mod / 'maps/mp/bots/sd_objectives.gsc'
            ai.write_text('tampered fixture')
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                modes.package(root, 'promod', output, 'engine', 'config', 'bots')
            ai.write_text('verified fixture')
            modes.package(root, 'promod', output, 'engine', 'config', 'bots')
            self.assertEqual((output / 'scriptdata/botnames.txt').read_bytes(), pool.read_bytes())
            result = json.loads(manifest.read_text())
            self.assertEqual(result['config_files']['modes/promod/botnames.txt'], modes.digest(pool))
