import importlib.util
import json
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/dsh/prepare_candidate.py"
SPEC = importlib.util.spec_from_file_location("prepare_candidate", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DshUpgradePreparationTests(unittest.TestCase):
    def test_python_and_npm_prerelease_spelling_must_match(self) -> None:
        self.assertEqual(MODULE.npm_version_for_python("0.1.1rc1"), "0.1.1-rc.1")
        with self.assertRaises(ValueError):
            MODULE.npm_version_for_python("latest")

    def test_repository_runtime_is_a_complete_exact_single_release_closure(self) -> None:
        manifest = json.loads(MODULE.RUNTIME_MANIFEST.read_text())
        lock = json.loads(MODULE.RUNTIME_LOCK.read_text())
        closure = MODULE.verify_closure(manifest, lock, "0.1.1-rc.1")
        self.assertEqual(len(closure), 78)
        self.assertEqual(closure["@deepseek-ai/dsh-llm-pi-ai"], "0.1.1-rc.1")
        self.assertEqual(closure["@deepseek-ai/dsh-authorization"], "0.1.1-rc.1")
        dsh_versions = {
            version
            for name, version in closure.items()
            if name.startswith(MODULE.DSH_PACKAGE_PREFIX)
        }
        self.assertEqual(dsh_versions, {"0.1.1-rc.1"})

    def test_mixed_prerelease_lock_fails_closed(self) -> None:
        manifest = {"dependencies": {"@deepseek-ai/dsh-agent": "0.1.1-rc.1"}}
        lock = {
            "packages": {
                "node_modules/@deepseek-ai/dsh-agent": {"version": "0.1.1-rc.2"}
            }
        }
        with self.assertRaisesRegex(ValueError, "closure mismatch|mixed"):
            MODULE.verify_closure(manifest, lock, "0.1.1-rc.1")

    def test_nested_mixed_prerelease_fails_closed(self) -> None:
        manifest = json.loads(MODULE.RUNTIME_MANIFEST.read_text())
        lock = json.loads(MODULE.RUNTIME_LOCK.read_text())
        poisoned = copy.deepcopy(lock)
        poisoned["packages"][
            "node_modules/example/node_modules/@deepseek-ai/dsh-agent"
        ] = {"version": "0.1.2-rc.1"}
        with self.assertRaisesRegex(ValueError, "nested"):
            MODULE.verify_closure(manifest, poisoned, "0.1.1-rc.1")

    def test_incompatible_dsh_peer_fails_closed(self) -> None:
        manifest = json.loads(MODULE.RUNTIME_MANIFEST.read_text())
        lock = json.loads(MODULE.RUNTIME_LOCK.read_text())
        poisoned = copy.deepcopy(lock)
        poisoned["packages"]["node_modules/@deepseek-ai/dsh-agent"][
            "peerDependencies"
        ]["@deepseek-ai/dsh-invariants"] = "^0.1.2-rc.1"
        with self.assertRaisesRegex(ValueError, "peer requirement"):
            MODULE.verify_closure(manifest, poisoned, "0.1.1-rc.1")

    def test_candidate_failure_cleans_staging_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "candidate"
            with patch(
                "sys.argv",
                [str(SCRIPT), "--release-id", "dsh-0.1.2rc1", "--output", str(output)],
            ), patch.object(MODULE, "fetch_json", side_effect=RuntimeError("offline")):
                with self.assertRaisesRegex(RuntimeError, "offline"):
                    MODULE.main()
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
