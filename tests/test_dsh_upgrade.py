import importlib.util
import json
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
