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
            old_dockerfile = "services/runtime-adapter/Dockerfile" + (".candidate" if release.endswith("2rc1") else "")
            self.assertEqual(builds.digest(builds.ROOT / old_dockerfile), historical["build_inputs"][old_dockerfile])
            self.assertNotEqual(value["dockerfile"], old_dockerfile)
            self.assertIn("packages/operations/admission.py", value["inputs"])
            self.assertIn("services/runtime-adapter/app/main.py", value["inputs"])
            self.assertIn("services/gateway/app/main.py", value["inputs"])

    def test_forged_revision_missing_input_drift_and_cross_release_fail(self):
        original = builds.render(builds.selected_build_id("dsh-0.1.2rc1"))
        mutations = (
            lambda v: v.update(release_id="dsh-0.1.1rc1"),
            lambda v: v.update(release_descriptor_hash="sha256:" + "0" * 64),
            lambda v: v["inputs"].pop("packages/operations/admission.py"),
            lambda v: v["inputs"].update({"../../escape": "sha256:" + "0" * 64}),
            lambda v: v["inputs"].update({"services/runtime-adapter/app/main.py": "sha256:" + "0" * 64}),
            lambda v: v.update(qualified=True),
            lambda v: v.update(build_id="dsh-0.1.2rc1-u6.999"),
        )
        for mutate in mutations:
            value = copy.deepcopy(original)
            mutate(value)
            with self.assertRaises(ValueError):
                builds.validate(value)

    def test_create_refuses_to_overwrite_previous_build(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(builds, "BUILDS", Path(directory)), \
                patch("sys.argv", ["build_revision", "create", "--build", builds.selected_build_id("dsh-0.1.2rc1")]):
            builds.main()
            path = Path(directory) / f"{builds.selected_build_id('dsh-0.1.2rc1')}.json"
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                builds.main()
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
