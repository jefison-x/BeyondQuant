import copy
import importlib.util
import json
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('promotion', ROOT / 'scripts/dsh/promotion.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PromotionTests(unittest.TestCase):
    def test_rollback_dockerfile_never_uses_promoted_default_identity(self):
        source = (ROOT / 'services/runtime-adapter/Dockerfile.u7').read_text()
        self.assertIn('ARG BYQ_DSH_RELEASE_IDENTITY_SOURCE=config/dsh/generated/dsh-0.1.1rc1.identity.json', source)
        self.assertNotIn('ARG BYQ_DSH_RELEASE_IDENTITY_SOURCE=config/dsh/generated/deployment.identity.json', source)

    def test_installed_promotion_files_reject_wrong_policy_and_identity(self):
        from tests.dsh_upgrade import live_stack
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'stack.json'
            path.write_text(json.dumps(live_stack.manifest('byq-u5-u7-file-test', 'dsh-0.1.2rc1', 18210, promoted=True)))
            expected = [ROOT / 'config/dsh/generated' / name for name in (
                'deployment.identity.json', 'qualified-web-evidence-provenance.json',
                'qualified-web-evidence-provenance.json', 'product-plugin-registry.json')]
            with patch.object(live_stack.subprocess, 'check_output', side_effect=[p.read_bytes() for p in expected]):
                result = live_stack.attest_promoted_files(path)
                self.assertEqual(len(result['files']), 4)
            for index in range(4):
                values = [p.read_bytes() for p in expected]
                values[index] = b'{}'
                with patch.object(live_stack.subprocess, 'check_output', side_effect=values):
                    with self.assertRaisesRegex(ValueError, 'installed promotion projection mismatch'):
                        live_stack.attest_promoted_files(path)

    def test_promotion_requires_exact_build_bound_rehearsal(self):
        report = json.loads(MODULE.REPORT.read_text())
        MODULE.validate_report(report)
        for mutate in (lambda r: r.update(schema_version='dsh-qualification-report.v1'),
                       lambda r: r['checks'][38].update(result='NOT_RUN'),
                       lambda r: r.update(qualification_state='WITHDRAWN'),
                       lambda r: r['build_revisions']['candidate'].update(manifest_hash='sha256:' + '0'*64)):
            value = copy.deepcopy(report)
            mutate(value)
            with self.assertRaises(ValueError):
                MODULE.validate_report(value)

    def test_qualified_projection_preserves_capability_ceiling(self):
        registry, policy = MODULE.projections()
        source = json.loads((ROOT / 'plugins/dsh-byq/registry/plugins.json').read_text())
        self.assertEqual(registry['runtime_baseline']['python_sdk'], '0.1.2rc1')
        self.assertEqual(policy['mode'], 'qualified')
        self.assertEqual({p['release_id'] for p in policy['recognized_producers']}, {'dsh-0.1.1rc1', 'dsh-0.1.2rc1'})
        for old, new in zip(source['plugins'], registry['plugins']):
            self.assertEqual(old['capabilities'], new['capabilities'])
            self.assertEqual(old['agents'], new['agents'])
            self.assertEqual(old['product_policy'], new['product_policy'])
            self.assertEqual(new['qualification']['state'], 'QUALIFIED' if new['id'] in {'guard', 'compaction', 'web-search'} else 'BLOCKED')

    def test_promoted_stack_uses_exact_qualified_and_rollback_policy(self):
        from tests.dsh_upgrade.live_stack import manifest, validate_manifest
        for release, name in (('dsh-0.1.2rc1', 'qualified-web-evidence-provenance.json'),
                              ('dsh-0.1.1rc1', 'qualified-rollback-web-evidence-provenance.json')):
            value = manifest('byq-u5-u7-test', release, 18210, promoted=True)
            validate_manifest(value)
            for service in ('backend', 'mcp'):
                self.assertEqual(value['services'][service]['environment']['BYQ_WEB_EVIDENCE_PROVENANCE_POLICY'], '/app/' + name)
            value['services']['backend']['environment']['BYQ_WEB_EVIDENCE_PROVENANCE_POLICY'] = '/production/unsafe.json'
            with self.assertRaises(ValueError):
                validate_manifest(value)

    def test_artifact_stage_has_no_production_or_cross_stage_alias(self):
        from scripts.dsh.retain_u6_ci_images import names, stage
        self.assertEqual(stage('local-u7-test-artifacts'), 'u7')
        self.assertTrue(all(v['retained_tag'].startswith('byq-u7-artifact-') for v in names('local-u7-test-artifacts').values()))
        for scope in ('local-u8-test', 'beyondquant', 'local-u7-../main'):
            with self.assertRaises(ValueError):
                names(scope)
