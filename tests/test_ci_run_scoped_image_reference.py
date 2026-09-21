"""Regression: run-scoped CI images must be referenced by immutable id, never a mutable tag.

The backend lane builds run-scoped images (`byq-ci-stack-<scope>-<service>`) and
later runs containers from them. If the mutable `:latest` tag is lost between the
build and a later step, `docker run <tag>` would attempt a registry pull and fail
with a confusing pull-access error. The lane now captures the immutable image id
immediately after build and uses `--pull=never` for backend/mcp run-scoped runs,
so a missing image fails closed instead of resolving a stale image from a
registry. These assertions lock that behaviour in and prove the cleanup and
identity gates are unchanged (not relaxed).

Runs under ``unittest``.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_CI = ROOT / "scripts/ci/local-ci.sh"
CLEANUP = ROOT / "scripts/ci/cleanup-resources.sh"


class RunScopedImageReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.script = LOCAL_CI.read_text(encoding="utf-8")
        self.cleanup = CLEANUP.read_text(encoding="utf-8")

    def test_image_id_is_captured_after_the_run_scoped_build(self):
        self.assertIn("declare -A CI_IMAGE_IDS=()", self.script)
        self.assertIn(
            "image_id=\"$(docker image inspect \"$(ci_image \"$service\")\" "
            "--format '{{.Id}}')\" || return 1",
            self.script)
        self.assertIn('CI_IMAGE_IDS["$service"]="$image_id"', self.script)

    def test_image_ref_prefers_the_immutable_id_and_never_a_registry(self):
        self.assertIn("ci_image_ref()", self.script)
        helper = self.script.split("ci_image_ref()", 1)[1].split("\n}", 1)[0]
        self.assertIn("CI_IMAGE_IDS[$service]", helper)
        self.assertIn('printf \'%s\' "$(ci_image "$service")"', helper)
        # Never produce or consume a registry-qualified reference.
        for forbidden in ("docker.io/", "ghcr.io/", "registry-1.docker.io", "docker pull"):
            self.assertNotIn(forbidden, self.script)

    def test_backend_and_mcp_runs_use_the_captured_ref_and_never_pull(self):
        backend_refs = self.script.count('"$(ci_image_ref backend)"')
        self.assertGreaterEqual(backend_refs, 5)
        self.assertIn('"$(ci_image_ref mcp)"', self.script)
        # 4 backend test runs + live backend + live mcp.
        self.assertGreaterEqual(self.script.count("--pull=never"), 6)
        # Every backend-lane test step pairs --pull=never with the captured ref.
        for block in ("--durations=20", "tests/test_schema_isolation.py",
                      "feedback publisher fake-GitHub", "feedback hub relay"):
            self.assertIn(block, self.script)
        self.assertGreaterEqual(
            len(re.findall(r"docker run[^\n]*--pull=never", self.script)), 6)

    def test_identity_gate_is_unchanged(self):
        self.assertIn(
            "image_id=\"$(docker image inspect \"$(ci_image \"$service\")\" "
            "--format '{{.Id}}')\" || return 1",
            self.script)

    def test_cleanup_gate_is_unchanged_and_still_removes_run_scoped_tags(self):
        self.assertIn('docker image rm "$PROJECT-$service"', self.cleanup)
        self.assertIn("CI cleanup verification failed: image tag remains", self.cleanup)

    def test_helper_returns_captured_id_and_only_falls_back_to_run_scoped_tag(self):
        script = "\n".join([
            "set -e",
            "source scripts/ci/local-ci.sh",
            "export COMPOSE_PROJECT_NAME=byq-ci-stack-demo",
            'test "$(ci_image_ref backend)" = "byq-ci-stack-demo-backend"',
            "CI_IMAGE_IDS[backend]=sha256:deadbeef",
            'test "$(ci_image_ref backend)" = "sha256:deadbeef"',
            'test "$(ci_image_ref mcp)" = "byq-ci-stack-demo-mcp"',
            "echo ok",
        ])
        completed = subprocess.run(
            ["bash", "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("ok", completed.stdout)


if __name__ == "__main__":
    unittest.main()
