from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/dsh/release.py"
SPEC = importlib.util.spec_from_file_location("dsh_release", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DshReleaseTests(unittest.TestCase):
    def test_repository_descriptors_are_closed_and_default_remains_old(self) -> None:
        deployment, releases = MODULE.load_all()
        self.assertEqual(deployment["default_release"], "dsh-0.1.1rc1")
        self.assertEqual(deployment["candidate_releases"], ["dsh-0.1.2rc1"])
        self.assertEqual(releases["dsh-0.1.1rc1"]["python"]["sdk"], "0.1.1rc1")
        self.assertEqual(
            releases["dsh-0.1.2rc1"]["carrier"]["kind"],
            "python-bundled-executable",
        )
        self.assertEqual(
            releases["dsh-0.1.2rc1"]["profile"]["composition"],
            "plugins/dsh-byq/profiles/dsh-0.1.2rc1/byq-product.patch.yml",
        )
        self.assertEqual(MODULE.render(), MODULE.render())
        self.assertEqual(MODULE.OUTPUT_PATH.read_text(), MODULE.render())
        self.assertEqual(
            MODULE.candidate_output_path("dsh-0.1.2rc1").read_text(),
            MODULE.render_release("dsh-0.1.2rc1", deployment, releases),
        )
        runtime_package = json.loads(
            (ROOT / "plugins/dsh-byq/runtime/package.json").read_text()
        )
        self.assertEqual(runtime_package["name"], "@beyondquant/dsh-runtime-plugins")
        self.assertRegex(runtime_package["version"], r"^\d+\.\d+\.\d+$")

    def test_invalid_release_schema_carrier_and_path_fail_closed(self) -> None:
        release = MODULE.load_json(MODULE.RELEASE_ROOT / "dsh-0.1.1rc1.json")
        cases = [
            (lambda value: value.update(extra=True), "closed schema"),
            (lambda value: value["carrier"].update(kind="private-demo"), "unknown carrier"),
            (lambda value: value["carrier"].pop("integrity"), "closed schema"),
            (lambda value: value.update(compatibility_family="nearest-version"), "compatibility"),
            (lambda value: value["build_inputs"].update({"../escape": "sha256:" + "0" * 64}), "contained"),
        ]
        for mutation, message in cases:
            with self.subTest(message=message):
                value = copy.deepcopy(release)
                mutation(value)
                with self.assertRaisesRegex(MODULE.ReleaseError, message):
                    MODULE.validate_release(value, verify_files=False)

    def test_unknown_deployment_release_and_input_drift_fail_closed(self) -> None:
        release = MODULE.load_json(MODULE.RELEASE_ROOT / "dsh-0.1.1rc1.json")
        relative = "services/runtime-adapter/pyproject.toml"
        release["build_inputs"][relative] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(MODULE.ReleaseError, "build input drift"):
            MODULE.validate_release(release, verify_files=True)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release_root = root / "releases"
            release_root.mkdir()
            source = MODULE.RELEASE_ROOT / "dsh-0.1.1rc1.json"
            (release_root / source.name).write_text(source.read_text())
            deployment = root / "deployment.json"
            deployment.write_text(json.dumps({
                "schema_version": "dsh-deployment.v1",
                "default_release": "dsh-missing",
                "candidate_releases": [],
            }))
            with patch.multiple(MODULE, RELEASE_ROOT=release_root, DEPLOYMENT_PATH=deployment):
                with self.assertRaisesRegex(MODULE.ReleaseError, "not registered"):
                    MODULE.load_all(verify_files=False)

    def test_check_mode_does_not_rewrite_stale_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "identity.json"
            output.write_text("stale\n")
            before = output.read_bytes()
            with patch.object(MODULE, "OUTPUT_PATH", output), patch(
                "sys.argv", [str(SCRIPT), "check"]
            ):
                with self.assertRaises(SystemExit):
                    MODULE.main()
            self.assertEqual(output.read_bytes(), before)

    def test_release_specific_generation_is_deterministic_and_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first"
            second = Path(directory) / "second"
            for output in (first, second):
                with patch(
                    "sys.argv",
                    [str(SCRIPT), "generate", "--release", "dsh-0.1.2rc1", "--output", str(output)],
                ):
                    self.assertEqual(MODULE.main(), 0)
            self.assertEqual(
                (first / "release.identity.json").read_bytes(),
                (second / "release.identity.json").read_bytes(),
            )
            with patch(
                "sys.argv",
                [str(SCRIPT), "check", "--release", "dsh-0.1.2rc1", "--output", str(first)],
            ):
                self.assertEqual(MODULE.main(), 0)
            identity = first / "release.identity.json"
            identity.write_text("stale\n")
            with patch(
                "sys.argv",
                [str(SCRIPT), "check", "--release", "dsh-0.1.2rc1", "--output", str(first)],
            ):
                with self.assertRaisesRegex(SystemExit, "stale"):
                    MODULE.main()

    def test_unknown_release_and_nonempty_output_fail_closed(self) -> None:
        deployment, releases = MODULE.load_all()
        with self.assertRaisesRegex(MODULE.ReleaseError, "not registered"):
            MODULE.render_release("dsh-latest", deployment, releases)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing"
            output.mkdir()
            with self.assertRaisesRegex(MODULE.ReleaseError, "overwrite"):
                MODULE.write_new_output(output, "identity.json", "{}\n")

    def test_python_lock_rejects_mixed_release(self) -> None:
        lock = MODULE.load_json(
            MODULE.RELEASE_ROOT / "dsh-0.1.2rc1.python.lock"
        )
        lock["packages"][1]["version"] = "0.1.1rc1"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lock.json"
            path.write_text(json.dumps(lock))
            with self.assertRaisesRegex(MODULE.ReleaseError, "runtime-bin version mismatch"):
                MODULE.validate_python_lock(path, "dsh-0.1.2rc1", "0.1.2rc1")


if __name__ == "__main__":
    unittest.main()
