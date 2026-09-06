import importlib
from pathlib import Path
import sys
import unittest

PATH = str(Path(__file__).resolve().parents[1] / 'scripts/dsh')
sys.path.insert(0, PATH)
try:
    MODULE = importlib.import_module('production_prepare')
finally:
    sys.path.remove(PATH)


class ProductionPrepareTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path('/home/jefison/backups/byq-dsh-u7/release-20260907T000000Z')
        self.receipt = {'images': {name: {'image_id': 'sha256:' + str(index) * 64}
                                  for index, name in enumerate((*MODULE.SERVICES, 'runtime-candidate'))}}

    def test_exact_allowlist_readonly_gate_and_three_separate_namespaces(self):
        namespaces = set()
        for mode in ('prepare', 'target', 'rollback'):
            services = MODULE.overlay(self.receipt, self.directory, mode)['services']
            self.assertEqual(set(services), set(MODULE.SERVICES))
            self.assertNotIn('postgres', services)
            for name in ('gateway', 'runtime-adapter'):
                self.assertTrue(services[name]['volumes'][0]['read_only'])
                self.assertEqual(services[name]['volumes'][0]['source'], str(self.directory / 'gate'))
            runtime = services['runtime-adapter']
            namespaces.add(runtime['environment']['DSH_SESSION_ROOT'])
            self.assertEqual(runtime['image'], self.receipt['images']['runtime-candidate' if mode == 'target' else 'runtime-adapter']['image_id'])
            self.assertEqual(services['backend']['environment']['BYQ_WEB_EVIDENCE_PROVENANCE_POLICY'], services['mcp']['environment']['BYQ_WEB_EVIDENCE_PROVENANCE_POLICY'])
        self.assertEqual(len(namespaces), 3)

    def test_broad_targets_unknown_modes_and_floating_images_are_rejected(self):
        for path in ('/', '/home/jefison', '/tmp/release-20260907T000000Z'):
            with self.assertRaises(ValueError):
                MODULE.overlay(self.receipt, Path(path), 'target')
        with self.assertRaises(ValueError):
            MODULE.overlay(self.receipt, self.directory, 'main')
        self.receipt['images']['backend']['image_id'] = 'backend:latest'
        with self.assertRaises(ValueError):
            MODULE.overlay(self.receipt, self.directory, 'target')
