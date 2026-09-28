import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.dsh import build_revision as builds


class BuildRevisionTests(unittest.TestCase):
    def test_current_revision_binds_history_without_replacing_it(self):
        for release in sorted(builds.RELEASES):
            value = builds.render(builds.selected_build_id(release))
            self.assertEqual(builds.check(value["build_id"]), value)
            self.assertEqual(builds.validate(value), value)
            descriptor = builds.ROOT / "config/dsh/releases" / f"{release}.json"
            historical = json.loads(descriptor.read_text())
            self.assertEqual(value["release_descriptor_hash"], builds.digest(descriptor))
            self.assertEqual(value["dockerfile"], builds.identity(value["build_id"])[1])
            self.assertIn("services/runtime-adapter/Dockerfile.post-u8-candidate", historical["build_inputs"])
            self.assertNotIn(value["dockerfile"], historical["build_inputs"])
            self.assertIn("packages/operations/admission.py", value["inputs"])
            self.assertIn("services/runtime-adapter/app/main.py", value["inputs"])
            self.assertIn("services/gateway/app/main.py", value["inputs"])
            for path in ("workers/data/worker.py", "workers/ml/worker.py",
                         "services/signal-sandbox/runner.py", "infra/postgres/init/10-byq-databases.sql",
                         "scripts/ci/cleanup-resources.sh", "tests/test_dsh_build_revision.py",
                         "services/runtime-adapter/tests/test_dsh015_foreground_child_process.py",
                         "apps/frontend/vitest.config.ts", ".github/workflows/ci-selfhosted.yml",
                         "docs/contracts/product-api.openapi.yaml"):
                self.assertIn(path, value["inputs"])

    def test_previous_and_current_post_u8_builds_keep_distinct_dockerfiles(self):
        frozen = "dsh-0.1.5rc1-post-u8.215"
        newest_frozen = "dsh-0.1.5rc1-post-u8.237"
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
        self.assertEqual(current, "dsh-0.1.5rc1-post-u8.238")
        self.assertEqual(builds.identity(current)[1],
                         "services/runtime-adapter/Dockerfile.post-u8-238-candidate")

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
