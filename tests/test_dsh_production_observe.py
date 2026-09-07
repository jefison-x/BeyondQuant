import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('production_observe', Path(__file__).resolve().parents[1] / 'scripts/dsh/production_observe.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProductionObserveTests(unittest.TestCase):
    def test_elapsed_window_is_not_acceptance(self):
        self.assertEqual(MODULE.result_state(86399), 'OBSERVING')
        self.assertEqual(MODULE.result_state(86400), 'WINDOW_ELAPSED_ACCEPTANCE_PENDING_REVIEW')
        self.assertEqual(MODULE.result_state(99999, True), 'SAMPLE_ONLY')

    def test_dense_then_bounded_observation(self):
        self.assertEqual(MODULE.interval(1799), 60)
        self.assertEqual(MODULE.interval(1800), 300)

    def test_unapproved_output_roots_rejected(self):
        for value in ('/', '/tmp/release-20260907T000000Z', '/home/jefison/backups/byq-dsh-u7'):
            with self.assertRaises(ValueError):
                MODULE.validate_release(Path(value))

    def test_projection_drops_unknown_fields_and_credentials(self):
        keys = ('status', 'sdk', 'runtime_bin', 'release_id', 'release_identity',
                'plugin_profile', 'composition_hash', 'enabled_plugin_ids')
        value = {'runtime': {**dict.fromkeys(keys, 'test'), 'secret': 'never'},
                 'sessions': {'active': 1, 'active_prompts': 0, 'status_counts': {}, 'conversation': 'never'},
                 'usage': {'input_tokens': 2, 'output_tokens': 'never', 'secret': 'never'}}
        result = MODULE.runtime_projection(value)
        self.assertNotIn('never', str(result))
        self.assertEqual(result['usage'], {'input_tokens': 2})

    def test_exact_identity_and_plugins_fail_closed(self):
        value = {'status': 'ready', 'release_identity': 'matched',
                 'release_id': 'dsh-0.1.2rc1', 'sdk': 'deepseek-harness-sdk==0.1.2rc1',
                 'runtime_bin': 'deepseek-harness-runtime-bin==0.1.2rc1',
                 'plugin_profile': 'byq-product-candidate', 'composition_hash': MODULE.COMPOSITION,
                 'enabled_plugin_ids': ['guard', 'web-search', 'compaction']}
        self.assertTrue(MODULE.identity_matches(value))
        for key in value:
            altered = {**value, key: [] if key == 'enabled_plugin_ids' else 'wrong'}
            self.assertFalse(MODULE.identity_matches(altered))
