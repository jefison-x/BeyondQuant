import importlib
from pathlib import Path
import sys
import unittest

PATH = str(Path(__file__).resolve().parents[1] / 'scripts/dsh')
sys.path.insert(0, PATH)
try:
    MODULE = importlib.import_module('production_session_backup')
finally:
    sys.path.remove(PATH)


class SessionBackupTests(unittest.TestCase):
    def writers(self):
        return [{'Id': name, 'Name': '/beyondquant-' + name + '-1',
                 'Config': {'Labels': {'com.docker.compose.project': 'beyondquant', 'com.docker.compose.service': name}},
                 'State': {'Running': False, 'Restarting': False, 'FinishedAt': 'fixed'},
                 'Mounts': [{'Type': 'volume', 'Name': volume, 'Destination': target}]}
                for name, (volume, target) in MODULE.VOLUMES.items()]

    def test_both_stopped_exact_writers_required(self):
        writers = self.writers()
        self.assertEqual(set(MODULE.checked_writers(writers)), {'runtime-adapter', 'gateway'})
        for key in ('Running', 'Restarting'):
            changed = self.writers()
            changed[0]['State'][key] = True
            with self.assertRaises(ValueError):
                MODULE.checked_writers(changed)
        with self.assertRaises(ValueError):
            MODULE.checked_writers(writers[:1])

    def test_foreign_project_and_database_volume_are_rejected(self):
        changed = self.writers()
        changed[0]['Config']['Labels']['com.docker.compose.project'] = 'community'
        with self.assertRaises(ValueError):
            MODULE.checked_writers(changed)
        changed = self.writers()
        changed[0]['Mounts'][0]['Name'] = 'byq-postgres-clean-20260904'
        with self.assertRaises(ValueError):
            MODULE.checked_writers(changed)
