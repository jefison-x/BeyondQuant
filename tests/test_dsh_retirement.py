"""Retirement must not erase provenance or allow a new old-runtime build."""
import hashlib
from pathlib import Path
import unittest
from scripts.dsh import build_revision as builds
from scripts.dsh.historical_inputs import read_blob

ROOT = Path(__file__).resolve().parents[1]

class RetirementTests(unittest.TestCase):
    def test_old_install_manifests_are_archived_byte_for_byte(self):
        for name in ('package.json', 'package-lock.json'):
            original = 'services/runtime-adapter/runtime/' + name
            self.assertFalse((ROOT / original).exists())
            archived = ROOT / 'config/dsh/archive/dsh-0.1.1rc1' / (name + '.archive')
            self.assertEqual(archived.read_bytes(), read_blob(builds.RETIRED_SOURCE, original))

    def test_only_current_release_can_produce_new_builds(self):
        self.assertEqual(builds.RELEASES, {'dsh-0.1.2rc1'})
        with self.assertRaisesRegex(ValueError, 'retired release'):
            builds.render('dsh-0.1.1rc1-post-u8.999')
        self.assertEqual(builds.check(builds.RETIRED_BUILD)['release_id'], 'dsh-0.1.1rc1')

    def test_ci_and_default_compose_do_not_install_old_runtime(self):
        ci = (ROOT / 'scripts/ci/local-ci.sh').read_text()
        self.assertNotIn('export BYQ_DSH_COMPATIBILITY_RELEASE=dsh-0.1.1rc1', ci)
        self.assertNotIn('baseline-benchmark.json', ci)
        self.assertIn('Dockerfile.post-u8-candidate', ci)
        self.assertIn('Dockerfile.post-u8-candidate', (ROOT / 'compose.yml').read_text())
