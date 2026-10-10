import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.dsh import build_revision as builds


class BuildRevisionTests(unittest.TestCase):
    def test_sdk_322_is_a_frozen_identity_not_current_sdk_qualification(self):
        build_id = builds.selected_build_id("dsh-0.1.5rc1")
        self.assertEqual(build_id, "dsh-0.1.5rc1-post-u8.322")
        stored = builds.check(build_id)
        rendered = builds.render(build_id)
        self.assertEqual(builds.validate(rendered), rendered)
        self.assertNotEqual(rendered, stored)
        self.assertEqual(builds.digest(builds.BUILDS / f"{build_id}.json"),
                         "sha256:ee97823eb01251c48f99a0b7d2a1d5b50debba6f1f9533e39c47862eedce90cc")
        self.assertEqual(builds.digest(builds.ROOT / builds.identity(build_id)[1]),
                         "sha256:dc87eeb772d37fafd29fd4c38d81475cffe1549bd767419f766307cc9d36bfa5")
        descriptor = builds.ROOT / "config/dsh/releases/dsh-0.1.5rc1.json"
        self.assertEqual(stored["release_descriptor_hash"], builds.digest(descriptor))
        self.assertEqual(rendered["release_descriptor_hash"], builds.digest(descriptor))
        self.assertEqual(stored["dockerfile"], "services/runtime-adapter/Dockerfile.post-u8-322-candidate")
        self.assertEqual(rendered["dockerfile"], builds.identity(build_id)[1])
        historical = json.loads(descriptor.read_text())
        self.assertIn("services/runtime-adapter/Dockerfile.post-u8-candidate", historical["build_inputs"])
        self.assertNotIn(rendered["dockerfile"], historical["build_inputs"])
        for path in ("packages/operations/admission.py", "services/runtime-adapter/app/main.py",
                     "services/gateway/app/main.py", "workers/data/worker.py",
                     "workers/ml/worker.py", "services/signal-sandbox/runner.py",
                     "infra/postgres/init/10-byq-databases.sql", "scripts/ci/cleanup-resources.sh",
                     "tests/test_dsh_build_revision.py",
                     "services/runtime-adapter/tests/test_dsh015_foreground_child_process.py",
                     "apps/frontend/vitest.config.ts", ".github/workflows/ci-selfhosted.yml",
                     "docs/contracts/product-api.openapi.yaml"):
            self.assertIn(path, rendered["inputs"])

    def test_previous_and_current_post_u8_builds_keep_distinct_dockerfiles(self):
        frozen = "dsh-0.1.5rc1-post-u8.215"
        newest_frozen = "dsh-0.1.5rc1-post-u8.238"
        previous = "dsh-0.1.5rc1-post-u8.235"
        older = "dsh-0.1.5rc1-post-u8.225"
        older_224 = "dsh-0.1.5rc1-post-u8.224"
        older_223 = "dsh-0.1.5rc1-post-u8.223"
        oldest = "dsh-0.1.5rc1-post-u8.222"
        current = builds.selected_build_id("dsh-0.1.5rc1")
        self.assertEqual(builds.identity(frozen)[1],
                         "services/runtime-adapter/Dockerfile.post-u8-candidate")
        self.assertEqual(builds.identity(oldest)[1],
                         "services/runtime-adapter/Dockerfile.post-u8-222-candidate")
        self.assertEqual(builds.identity(previous)[1],
                         "services/runtime-adapter/Dockerfile.post-u8-235-candidate")
        self.assertEqual(builds.identity(older)[1],
                         "services/runtime-adapter/Dockerfile.post-u8-225-candidate")
        self.assertEqual(builds.identity(older_224)[1],
                         "services/runtime-adapter/Dockerfile.post-u8-224-candidate")
        self.assertEqual(builds.identity(older_223)[1],
                         "services/runtime-adapter/Dockerfile.post-u8-223-candidate")
        self.assertEqual(builds.check(previous)["build_id"], previous)
        self.assertEqual(builds.check(newest_frozen)["build_id"], newest_frozen)
        self.assertEqual(builds.check(older)["build_id"], older)
        self.assertEqual(current, "dsh-0.1.5rc1-post-u8.322")
        self.assertEqual(builds.identity(current)[1],
                         "services/runtime-adapter/Dockerfile.post-u8-322-candidate")
        self.assertEqual(builds.check(current)["build_id"], current)
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.303")["build_id"],
                         "dsh-0.1.5rc1-post-u8.303")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.302")["build_id"],
                         "dsh-0.1.5rc1-post-u8.302")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.288")["build_id"],
                         "dsh-0.1.5rc1-post-u8.288")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.289")["build_id"],
                         "dsh-0.1.5rc1-post-u8.289")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.290")["build_id"],
                         "dsh-0.1.5rc1-post-u8.290")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.291")["build_id"],
                         "dsh-0.1.5rc1-post-u8.291")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.297")["build_id"],
                         "dsh-0.1.5rc1-post-u8.297")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.298")["build_id"],
                         "dsh-0.1.5rc1-post-u8.298")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.299")["build_id"],
                         "dsh-0.1.5rc1-post-u8.299")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.300")["build_id"],
                         "dsh-0.1.5rc1-post-u8.300")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.301")["build_id"],
                         "dsh-0.1.5rc1-post-u8.301")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.296")["build_id"],
                         "dsh-0.1.5rc1-post-u8.296")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.295")["build_id"],
                         "dsh-0.1.5rc1-post-u8.295")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.294")["build_id"],
                         "dsh-0.1.5rc1-post-u8.294")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.293")["build_id"],
                         "dsh-0.1.5rc1-post-u8.293")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.292")["build_id"],
                         "dsh-0.1.5rc1-post-u8.292")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.287")["build_id"],
                         "dsh-0.1.5rc1-post-u8.287")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.286")["build_id"],
                         "dsh-0.1.5rc1-post-u8.286")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.285")["build_id"],
                         "dsh-0.1.5rc1-post-u8.285")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.284")["build_id"],
                         "dsh-0.1.5rc1-post-u8.284")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.283")["build_id"],
                         "dsh-0.1.5rc1-post-u8.283")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.282")["build_id"],
                         "dsh-0.1.5rc1-post-u8.282")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.281")["build_id"],
                         "dsh-0.1.5rc1-post-u8.281")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.280")["build_id"],
                         "dsh-0.1.5rc1-post-u8.280")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.279")["build_id"],
                         "dsh-0.1.5rc1-post-u8.279")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.278")["build_id"],
                         "dsh-0.1.5rc1-post-u8.278")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.277")["build_id"],
                         "dsh-0.1.5rc1-post-u8.277")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.276")["build_id"],
                         "dsh-0.1.5rc1-post-u8.276")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.275")["build_id"],
                         "dsh-0.1.5rc1-post-u8.275")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.274")["build_id"],
                         "dsh-0.1.5rc1-post-u8.274")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.273")["build_id"],
                         "dsh-0.1.5rc1-post-u8.273")
        self.assertEqual(builds.check("dsh-0.1.5rc1-post-u8.270")["build_id"],
                         "dsh-0.1.5rc1-post-u8.270")

    def test_forged_revision_missing_input_drift_and_cross_release_fail(self):
        original = builds.render(builds.selected_build_id("dsh-0.1.5rc1"))
        mutations = (
            lambda v: v.update(release_id="dsh-0.1.1rc1"),
            lambda v: v.update(release_descriptor_hash="sha256:" + "0" * 64),
            lambda v: v["inputs"].pop("packages/operations/admission.py"),
            lambda v: v["inputs"].update({"../../escape": "sha256:" + "0" * 64}),
            lambda v: v["inputs"].update({"services/runtime-adapter/app/main.py": "sha256:" + "0" * 64}),
            lambda v: v["inputs"].pop("workers/data/worker.py"),
            lambda v: v["inputs"].update({"workers/ml/worker.py": "sha256:" + "0" * 64}),
            lambda v: v.update(qualified=True),
            lambda v: v.update(build_id="dsh-0.1.5rc1-u6.999"),
        )
        for mutate in mutations:
            value = copy.deepcopy(original)
            mutate(value)
            with self.assertRaises(ValueError):
                builds.validate(value)

    def test_create_refuses_to_overwrite_previous_build(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(builds, "BUILDS", Path(directory)), \
                patch("sys.argv", ["build_revision", "create", "--build", builds.selected_build_id("dsh-0.1.5rc1")]):
            builds.main()
            path = Path(directory) / f"{builds.selected_build_id('dsh-0.1.5rc1')}.json"
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                builds.main()
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
