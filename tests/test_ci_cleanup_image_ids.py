"""Real behavior tests for the run-scoped cleanup image-id contract.

These drive ``scripts/ci/cleanup-resources.sh`` end to end against a strict fake
``docker`` (``tests/ci/fake_docker.py``) that keeps a small content-addressed image
store. They assert the actual command targets and failure semantics, not source
strings:

* a dangling image whose mutable run-scoped tag was lost but whose exact immutable
  id is still present is removed and verified absent;
* the exact tags and the exact captured ids are both removed;
* a shared image still referenced by another scope's tag is never deleted;
* a missing manifest stays backward compatible;
* an invalid or foreign manifest fails closed and its text is never handed to
  ``docker image rm``;
* no global prune is ever issued.

Runs under ``unittest``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLEANUP = ROOT / "scripts/ci/cleanup-resources.sh"
FAKE_DOCKER = ROOT / "tests/ci/fake_docker.py"

ID_A = "sha256:" + "a" * 64
ID_B = "sha256:" + "b" * 64


def _parse_state(path: Path) -> dict[str, list[str]]:
    images: dict[str, list[str]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            image_id, _, tags = line.partition("\t")
            images[image_id] = [tag for tag in tags.split(",") if tag]
    return images


class CleanupImageIdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        shim = self.bin / "docker"
        shutil.copyfile(FAKE_DOCKER, shim)
        shim.chmod(0o755)
        self.state = Path(self.tmp.name) / "state"
        self.log = Path(self.tmp.name) / "docker.log"
        self.log.write_text("", encoding="utf-8")
        self.scope = "cleanupids-" + self._testMethodName.replace("_", "")
        self.manifest_dir = ROOT / ".ci-artifacts" / self.scope
        self.manifest = self.manifest_dir / "image-ids.env"
        self.addCleanup(shutil.rmtree, self.manifest_dir, ignore_errors=True)
        self.addCleanup(shutil.rmtree, ROOT / ".ci-artifacts" / "cleanupids-otherscope",
                        ignore_errors=True)

    # ---------------------------------------------------------------- helpers
    def _run(self, *args: str, scope: str | None = None) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "FAKE_DOCKER_STATE": str(self.state),
            "FAKE_DOCKER_LOG": str(self.log),
            "BYQ_CI_CLEANUP_MAX_ATTEMPTS": "4",
            "BYQ_CI_CLEANUP_RETRY_SECONDS": "0",
        }
        return subprocess.run(
            ["bash", str(CLEANUP), f"--scope={scope or self.scope}", *args],
            cwd=ROOT, capture_output=True, text=True, env=env, timeout=60)

    def _images(self) -> dict[str, list[str]]:
        return _parse_state(self.state)

    def _write_manifest(self, text: str, *, scope: str | None = None) -> None:
        directory = ROOT / ".ci-artifacts" / (scope or self.scope)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "image-ids.env").write_text(text, encoding="utf-8")

    def _log(self) -> str:
        return self.log.read_text(encoding="utf-8")

    def _assert_no_global_prune(self) -> None:
        log = self._log()
        for forbidden in ("image prune", "system prune", "builder prune", "container prune"):
            self.assertNotIn(forbidden, log)

    # ------------------------------------------------------------------ tests
    def test_lost_tag_with_present_id_is_removed_and_verified(self) -> None:
        self.state.write_text(f"{ID_A}\t\n", encoding="utf-8")  # tag lost, id dangling
        self._write_manifest(f"backend={ID_A}\n")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(ID_A, self._images(), "dangling captured id must be removed")
        self.assertIn(f"image rm {ID_A}", self._log())
        self.assertFalse(self.manifest.exists(), "manifest retired after clean verification")
        self._assert_no_global_prune()

    def test_exact_tag_and_exact_id_are_both_removed(self) -> None:
        tag = f"byq-ci-stack-{self.scope}-backend"
        self.state.write_text(f"{ID_A}\t{tag}\n", encoding="utf-8")
        self._write_manifest(f"backend={ID_A}\n")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(ID_A, self._images())
        log = self._log()
        self.assertIn(f"image rm {tag}", log)
        self.assertIn(f"image rm {ID_A}", log)
        self.assertFalse(self.manifest.exists())

    def test_missing_manifest_is_backward_compatible(self) -> None:
        self.state.write_text(f"{ID_A}\t\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(ID_A, self._images(), "no manifest means the id is unknown and retained")
        self.assertNotIn(f"image rm {ID_A}", self._log())
        self._assert_no_global_prune()

    def test_shared_foreign_tag_image_is_never_deleted(self) -> None:
        foreign = "byq-ci-stack-otherscope-backend"
        self.state.write_text(f"{ID_A}\t{foreign}\n", encoding="utf-8")
        self._write_manifest(f"backend={ID_A}\n")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self._images().get(ID_A), [foreign], "shared image must survive")
        self.assertNotIn(f"image rm {ID_A}", self._log())
        self.assertIn("retained shared image id", result.stdout)

    def test_invalid_manifest_value_fails_closed_never_fed_to_docker(self) -> None:
        self.state.write_text(f"{ID_A}\t\n", encoding="utf-8")
        self._write_manifest("backend=not-an-image-id\n")
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid image-id manifest", result.stderr)
        self.assertNotIn("not-an-image-id", self._log(), "arbitrary text must never reach docker")
        self.assertTrue(self.manifest.exists(), "invalid manifest retained for diagnostics")

    def test_malformed_manifest_line_fails_closed(self) -> None:
        self.state.write_text(f"{ID_A}\t\n", encoding="utf-8")
        self._write_manifest("backend\n")
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid", result.stderr)
        self.assertNotIn("image rm backend", self._log())

    def test_foreign_scope_manifest_is_not_read(self) -> None:
        self.state.write_text(f"{ID_B}\t\n", encoding="utf-8")
        self._write_manifest(f"backend={ID_B}\n", scope="cleanupids-otherscope")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(ID_B, self._images(), "another scope's manifest must not drive cleanup")
        self.assertNotIn(f"image rm {ID_B}", self._log())

    def test_duplicate_manifest_ids_are_removed_once(self) -> None:
        self.state.write_text(f"{ID_A}\t\n", encoding="utf-8")
        self._write_manifest(f"backend={ID_A}\nmcp={ID_A}\n")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(ID_A, self._images())
        self.assertEqual(self._log().count(f"image rm {ID_A}"), 1)


if __name__ == "__main__":
    unittest.main()
