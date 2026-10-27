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
