import json
import unittest
from tests.dsh_upgrade.h5_stack import manifest


class H5TopologyTest(unittest.TestCase):
    def test_candidate_has_signal_execution_without_model_or_database_exposure(self):
        value = manifest('byq-h5-candidate')
        self.assertEqual(len(value['services']), 10)
        self.assertFalse(value['x-byq-execution-authorized'])
        self.assertTrue(value['networks']['model']['internal'])
        self.assertEqual(value['services']['runtime-adapter']['environment']['DEEPSEEK_API_KEY'], '')
        self.assertEqual(value['services']['signal-sandbox']['networks'], ['signal'])
        self.assertNotIn('environment', value['services']['signal-sandbox'])
        self.assertNotIn('volumes', value['services']['signal-sandbox'])
        self.assertEqual([name for name, item in value['services'].items() if 'ports' in item], ['frontend'])
        raw = json.dumps(value)
        self.assertNotIn('${', raw)
        self.assertNotIn('/var/run/docker.sock', raw)
        self.assertNotIn('byq-u5-candidate', raw)
        self.assertNotIn('TUSHARE_TOKEN', raw)

    def test_production_or_invalid_scope_is_rejected(self):
        for scope in ('beyondquant', 'byq-u5-old', '../byq-h5-test', None):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                manifest(scope)

    def test_modified_candidate_cannot_enable_external_access_or_privileges(self):
        from copy import deepcopy
        from tests.dsh_upgrade.h5_stack import validate_candidate
        original = manifest('byq-h5-candidate')
        self.assertEqual(validate_candidate(original), original)
        for change in ('model_network', 'key', 'sandbox_database', 'host_mount', 'privileged', 'approval', 'extra_service'):
            value = deepcopy(original)
            if change == 'model_network': value['networks']['model']['internal'] = False
            if change == 'key': value['services']['runtime-adapter']['environment']['DEEPSEEK_API_KEY'] = 'synthetic-not-authorized'
            if change == 'sandbox_database': value['services']['signal-sandbox']['networks'].append('product')
            if change == 'host_mount': value['services']['signal-sandbox']['volumes'] = ['/var/run/docker.sock:/var/run/docker.sock']
            if change == 'privileged': value['services']['signal-worker']['privileged'] = True
            if change == 'approval': value['x-byq-execution-authorized'] = True
            if change == 'extra_service': value['services']['unreviewed'] = {'image': 'unknown'}
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_candidate(value)
