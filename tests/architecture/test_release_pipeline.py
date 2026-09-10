import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/release'))
import images
import manifest


def fixture():
    return {'schema': 'byq-release.v1', 'source_sha': 'a' * 40, 'profile': 'full',
            'ci_url': 'https://github.com/jefison-x/BeyondQuant/actions/runs/123', 'migration': 'none',
            'images': {s: {'ref': f'ghcr.io/jefison-x/beyondquant/{s}@sha256:' + 'b' * 64,
                           'image_id': 'sha256:' + 'c' * 64} for s in images.SERVICES},
            'sbom': {s: {'file': s + '.spdx.json', 'sha256': 'sha256:' + 'd' * 64} for s in images.SERVICES}}


class ReleasePipelineTests(unittest.TestCase):
    def test_digest_manifest_rejects_registry_escape_mutable_tags_and_missing_service(self):
        manifest.validate(fixture())
        for value in ('ghcr.io/attacker/backend@sha256:' + 'b' * 64,
                      'ghcr.io/jefison-x/beyondquant/backend:latest',
                      'ghcr.io/jefison-x/beyondquant/backend@sha256:short'):
            data = fixture()
            data['images']['backend']['ref'] = value
            with self.assertRaises(ValueError):
                manifest.validate(data)
        data = fixture()
        del data['images']['backend']
        with self.assertRaises(ValueError):
            manifest.validate(data)

    def test_unqualified_or_cross_repository_run_rejected(self):
        for key, value in (('profile', 'selective'), ('source_sha', 'main'),
                           ('ci_url', 'https://github.com/other/repo/actions/runs/123'),
                           ('migration', 'unknown')):
            data = fixture()
            data[key] = value
            with self.assertRaises(ValueError):
                manifest.validate(data)

    def test_untrusted_dispatch_cannot_export_or_publish(self):
        with patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_REF': 'refs/heads/main',
                                     'GITHUB_REPOSITORY': 'jefison-x/BeyondQuant'}, clear=True):
            with self.assertRaises(ValueError):
                images.trusted_main()
        with patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/feature',
                                     'GITHUB_REPOSITORY': 'jefison-x/BeyondQuant'}, clear=True):
            with self.assertRaises(ValueError):
                images.trusted_main()

    def test_handoff_binds_source_attempt_service_and_config_digest(self):
        receipt = {'schema': 'byq-release-images.v1', 'source_sha': 'a' * 40, 'run_id': '123-1',
                   'profile': 'full', 'archive_sha256': 'sha256:' + 'b' * 64,
                   'images': {s: {'tag': f'byq-release-123-1-{s}:tested', 'image_id': 'sha256:' + 'c' * 64}
                              for s in images.SERVICES}}
        images.validate(receipt, 'a' * 40, '123-1')
        for sha, run in [('d' * 40, '123-1'), ('a' * 40, '123-2')]:
            with self.assertRaises(ValueError):
                images.validate(receipt, sha, run)
        data = copy.deepcopy(receipt)
        data['images']['backend']['tag'] = 'production-backend:latest'
        with self.assertRaises(ValueError):
            images.validate(data, 'a' * 40, '123-1')

    def test_release_permissions_and_no_automatic_main_publication(self):
        source = (ROOT / '.github/workflows/release-images.yml').read_text()
        qualify, publish = source.split('\n  publish:', 1)
        self.assertNotIn('packages: write', qualify)
        self.assertNotIn('secrets.', source)
        self.assertNotIn('pull_request_target', source)
        self.assertNotIn('\n  push:', source)
        self.assertIn('needs: qualify', publish)
        self.assertIn('packages: write', publish)
        self.assertNotIn('local-ci.sh', publish)
        self.assertIn('--release-artifacts', qualify)
        self.assertIn('cancel-in-progress: false', source)

    def test_full_profile_runs_integration_even_with_documentation_diff(self):
        source = (ROOT / 'scripts/ci/local-ci.sh').read_text()
        self.assertIn('if [ "$ALL" -eq 1 ] || [ "$INTEGRATION_ONLY" -eq 1 ]; then integration=yes; fi', source)
        self.assertIn('docker image tag "$(ci_image runtime-adapter)" "$candidate_image"', source)
        self.assertNotIn('docker build -f services/runtime-adapter/Dockerfile.post-u8-candidate', source)

    def test_parallel_gate_requires_plan_and_all_lanes(self):
        source = (ROOT / '.github/workflows/ci-selfhosted.yml').read_text()
        self.assertIn('needs: [plan, checks]', source)
        self.assertIn('test "$PLAN_RESULT" = success', source)
        self.assertIn('test "$CHECKS_RESULT" = success', source)
        self.assertIn('fail-fast: false', source)
        self.assertIn('if: matrix.browser', source)

    def test_plan_full_and_docs_use_the_same_classifier(self):
        spec = importlib.util.spec_from_file_location('ci_plan', ROOT / 'scripts/ci/plan.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        real = subprocess.check_output
        def fake(args, **kwargs):
            if args[:2] == ['git', 'merge-base']:
                return 'a' * 40
            if args[:2] == ['git', 'diff']:
                return 'docs/evidence/example.md\n'
            return real(args, **kwargs)
        with patch.object(module.subprocess, 'check_output', side_effect=fake):
            self.assertEqual([x['lane'] for x in module.plan('main')['include']], ['docs'])
            full = module.plan('main', True)['include']
            self.assertEqual({x['lane'] for x in full}, set(module.COMPONENTS) | {'integration'})
            self.assertEqual({x['lane'] for x in full if x['browser']}, {'frontend', 'integration'})

    def test_corrupt_archive_stops_before_docker_load_or_push(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / 'receipt.json').write_text('{}')
            (directory / 'images.tar').write_bytes(b'corrupt')
            with patch.object(images, 'trusted_main', return_value='a' * 40), \
                 patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}), \
                 patch.object(images, 'validate'), patch.object(images.subprocess, 'run') as docker:
                (directory / 'receipt.json').write_text(json.dumps({'archive_sha256': 'sha256:' + '0' * 64}))
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    images.publish(directory, 'none')
                docker.assert_not_called()

    def test_promotion_rejects_existing_other_digest_before_any_mutation(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({'digest': 'sha256:' + '0' * 64}), '')
        with patch.object(manifest.subprocess, 'run', return_value=result) as run:
            with self.assertRaisesRegex(ValueError, 'different image'):
                manifest.promote(fixture(), 'v0.2.0')
            self.assertEqual(run.call_count, 1)
            self.assertIn('inspect', run.call_args.args[0])

    def test_promotion_is_idempotent_and_does_not_rebuild(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({'digest': 'sha256:' + 'b' * 64}), '')
        with patch.object(manifest.subprocess, 'run', return_value=result) as run:
            manifest.promote(fixture(), 'v0.2.0')
            self.assertEqual(run.call_count, len(images.SERVICES))
            self.assertTrue(all('inspect' in call.args[0] for call in run.call_args_list))

    def test_failed_registry_lookup_cannot_be_treated_as_new_version(self):
        result = subprocess.CompletedProcess([], 1, '', 'unauthorized')
        with patch.object(manifest.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(ValueError, 'absence'):
                manifest.promote(fixture(), 'v0.2.0')
