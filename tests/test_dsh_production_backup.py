import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('production_backup', Path(__file__).resolve().parents[1] / 'scripts/dsh/production_backup.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProductionBackupSafetyTests(unittest.TestCase):
    def test_nonapproved_backup_roots_are_rejected_before_creation(self):
        for path in ('/', '/tmp/byq-backup', '/home/jefison', '/home/jefison/projects/BeyondQuant'):
            with self.subTest(path=path), patch.object(Path, 'mkdir') as mkdir:
                with self.assertRaisesRegex(ValueError, 'approved canonical'):
                    MODULE.private_directory(Path(path))
                mkdir.assert_not_called()

    def test_operator_never_restores_or_drops_production_database(self):
        source = Path(MODULE.__file__).read_text()
        self.assertNotIn('DROP DATABASE', source)
        self.assertNotIn("'pg_restore', '-d'", source)
        self.assertIn('REPEATABLE READ READ ONLY', source)
        self.assertIn("'--snapshot', snapshot", source)
        self.assertIn("'actual_restore': 'NOT_RUN'", source)
