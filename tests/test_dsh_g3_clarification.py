import unittest
from unittest.mock import patch
import contextlib
import hashlib
import io
import json

from tests.dsh_upgrade.live_model_probe import PROMPTS, G3_STRATEGY_APPROVAL, scenario_prompt, verify_no_training


class G3ClarificationTests(unittest.TestCase):
    def test_g4_artifact_dictionary_does_not_replace_prompt_hash(self):
        from tests.dsh_upgrade import live_model_probe as probe
        artifact = {'artifact_id': 'synthetic-evidence', 'kind': 'web_research_evidence',
                    'content': {'usage_policy': {'research_only': True, 'deterministic_input': False,
                                                'authoritative_market_data': False},
                                'sources': [{'url': 'https://www.csrc.gov.cn/'}]}}
        before = {'artifacts': 0}
        output = io.StringIO()
        with patch('sys.argv', ['probe', 'G4', '--release', 'dsh-0.1.2rc1', '--stack-file', '/tmp/synthetic.json']), \
                patch.object(probe, 'preflight', return_value={'release': 'dsh-0.1.2rc1', 'gateway': 'http://synthetic', 'fake_hub_container': 'synthetic'}), \
                patch.object(probe, 'attest_runtime_build', return_value={}), \
                patch.object(probe, 'fake_hub_evidence', return_value={'received': 0}), \
                patch.object(probe, 'research_artifacts', side_effect=[[], [artifact]]), \
                patch.object(probe, 'counts', side_effect=[before, {'artifacts': 1}]), \
                patch.object(probe, 'Client') as client, contextlib.redirect_stdout(output):
            client.return_value.call.side_effect = [
                {'session_id': 'synthetic'}, {'messages': []}, {'accepted': True},
                {'messages': [{'role': 'assistant', 'content': 'Saved https://www.csrc.gov.cn/ evidence.'}]}]
            probe.main()
        result = json.loads(output.getvalue())
        self.assertEqual(result['result'], 'PASS')
        self.assertEqual(result['prompt_sha256'], hashlib.sha256(PROMPTS['G4'].encode()).hexdigest())

    def test_only_explicit_g3_selects_new_prompt(self):
        for scenario in PROMPTS:
            self.assertEqual(scenario_prompt(scenario), PROMPTS[scenario])
            if scenario != 'G3':
                with self.assertRaises(ValueError):
                    scenario_prompt(scenario, True)
        self.assertEqual(scenario_prompt('G3', True), G3_STRATEGY_APPROVAL)
        self.assertIn('需要审批时', PROMPTS['G3'])
        self.assertIn('明确申请一次研究策略审批', G3_STRATEGY_APPROVAL)

    def test_training_and_prediction_mutations_fail(self):
        before = {'ml_training': 0, 'ml_predictions': 0}
        verify_no_training(before, dict(before))
        for key in before:
            with self.assertRaises(AssertionError):
                verify_no_training(before, {**before, key: 1})
