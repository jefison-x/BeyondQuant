"""Regression: run-scoped CI images must be referenced by immutable id, never a mutable tag.

The backend lane builds run-scoped images (`byq-ci-stack-<scope>-<service>`) and
later runs containers from them. If the mutable `:latest` tag is lost between the
build and a later step, `docker run <tag>` would attempt a registry pull and fail
with a confusing pull-access error. The lane captures the immutable image id
immediately after build and resolves every run-scoped `docker run` through that
captured id; a missing id is a hard failure before Docker starts, never a silent
fallback to the mutable run-scoped tag, and every run-scoped run passes
`--pull=never`. Because a command substitution used as a Docker argument does not
propagate failure to the caller, each call site must capture the id explicitly and
abort on failure. The same captured ids are persisted to a run/attempt-scoped
manifest that the independent always-cleanup process consumes, so a dangling image
(tag lost but id present) is removed and verified too. The identity gate is
unchanged (not relaxed); the cleanup image-id behavior is covered end to end by
``tests/test_ci_cleanup_image_ids.py``.

Runs under ``unittest``.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_CI = ROOT / "scripts/ci/local-ci.sh"
CLEANUP = ROOT / "scripts/ci/cleanup-resources.sh"


def _logical_docker_run_commands(source: str) -> list[str]:
    """Return each ``docker run`` invocation as one logical command.

    Backslash line continuations are joined first so a run's flags and its image
    reference are evaluated together, not as unrelated source lines. This keeps
    the assertions specific to an actual command/behavior instead of counting
    substrings across the whole script.
    """
    joined = source.replace("\\\n", " ")
    return [line.strip() for line in joined.splitlines() if "docker run" in line]


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

    def test_image_ref_uses_the_immutable_id_and_fails_closed_without_one(self):
        self.assertIn("ci_image_ref()", self.script)
        helper = self.script.split("ci_image_ref()", 1)[1].split("\n}", 1)[0]
        self.assertIn("CI_IMAGE_IDS[$service]", helper)
        # Missing captured id returns non-zero: no mutable tag fallback.
        self.assertIn("return 1", helper)
        self.assertNotIn('printf \'%s\' "$(ci_image "$service")"', helper)
        self.assertNotIn('ci_image "$service"', helper)
        # Never produce or consume a registry-qualified reference.
        for forbidden in ("docker.io/", "ghcr.io/", "registry-1.docker.io", "docker pull"):
            self.assertNotIn(forbidden, self.script)

    def test_run_scoped_docker_runs_never_pull_and_never_use_a_mutable_tag(self):
        commands = _logical_docker_run_commands(self.script)
        self.assertTrue(commands)
        # postgres:16-alpine is a public base image, not a run-scoped build.
        run_scoped = [c for c in commands if "postgres:16-alpine" not in c]
        self.assertTrue(run_scoped)
        for command in run_scoped:
            self.assertIn("--pull=never", command)
            # Resolve a captured local id; never the mutable run-scoped tag and
            # never an unpropagated inline command substitution.
            self.assertNotIn('"$(ci_image ', command)
            self.assertNotIn('"$(ci_image_ref', command)
        # Each service id is resolved through ci_image_ref with explicit failure
        # propagation so a missing id aborts before Docker starts.
        for service in ("backend", "gateway", "mcp", "runtime-adapter"):
            self.assertIn(f'="$(ci_image_ref {service})"', self.script)
        # The sharded backend suite runs its own fail-closed container run.
        shard_script = (ROOT / "scripts/ci/run_backend_shards.py").read_text()
        self.assertIn('args.image, "python", "-m", "pytest"', shard_script)
        self.assertIn('"docker", "run", "--pull=never"', shard_script)
        self.assertNotIn("feedback publisher fake-GitHub", self.script)
        self.assertNotIn("--profile feedback-publisher", self.script)

    def test_identity_gate_is_unchanged(self):
        self.assertIn(
            "image_id=\"$(docker image inspect \"$(ci_image \"$service\")\" "
            "--format '{{.Id}}')\" || return 1",
            self.script)

    def test_captured_ids_are_persisted_to_a_run_scoped_manifest(self):
        self.assertIn("ci_image_manifest_path()", self.script)
        self.assertIn(
            'printf \'%s\' "$REPO_ROOT/.ci-artifacts/$BYQ_CI_SCOPE/image-ids.env"',
            self.script)
        self.assertIn('printf \'%s=%s\\n\' "$service" "${CI_IMAGE_IDS[$service]}"', self.script)
        # The cleanup gate consumes the same scope-scoped manifest and removes the
        # exact captured ids (behavior is proven in test_ci_cleanup_image_ids.py).
        self.assertIn('ARTIFACT_ROOT="$REPO_ROOT/.ci-artifacts"', self.cleanup)
        self.assertIn('MANIFEST_DIR="$ARTIFACT_ROOT/$SCOPE"', self.cleanup)
        self.assertIn('MANIFEST="$MANIFEST_DIR/image-ids.env"', self.cleanup)
        self.assertIn('docker image rm "$PROJECT-$service"', self.cleanup)
        self.assertIn('docker image rm "$image_id"', self.cleanup)
        self.assertIn("image_has_foreign_reference", self.cleanup)
        self.assertIn("CI cleanup verification failed: image tag remains", self.cleanup)

    def test_helper_returns_captured_id_and_fails_closed_without_one(self):
        script = "\n".join([
            "set -e",
            "source scripts/ci/local-ci.sh",
            "export COMPOSE_PROJECT_NAME=byq-ci-stack-demo",
            "if ci_image_ref backend; then echo UNEXPECTED_TAG_FALLBACK; exit 3; fi",
            "CI_IMAGE_IDS[backend]=sha256:deadbeef",
            'test "$(ci_image_ref backend)" = "sha256:deadbeef"',
            "if ci_image_ref mcp; then echo UNEXPECTED_TAG_FALLBACK; exit 4; fi",
            "echo ok",
        ])
        completed = subprocess.run(
            ["bash", "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("ok", completed.stdout)
        self.assertNotIn("UNEXPECTED_TAG_FALLBACK", completed.stdout)
        self.assertIn("not captured", completed.stderr)

    def test_run_scoped_checks_fail_closed_before_docker_without_captured_ids(self):
        # Real callers: with no captured ids, each run-scoped check must abort
        # before invoking Docker at all (a bare "$(ci_image_ref ...)" argument
        # would otherwise reach Docker with an empty image and the failure would
        # not propagate).
        for function in ("check_gateway", "check_runtime"):
            with self.subTest(function=function), tempfile.TemporaryDirectory() as tmp:
                calls = Path(tmp) / "calls.log"
                calls.write_text("", encoding="utf-8")
                script = "\n".join([
                    "set -e",
                    "source scripts/ci/local-ci.sh",
                    "trap - EXIT INT TERM HUP",
                    "export COMPOSE_PROJECT_NAME=byq-ci-stack-demo",
                    f"run_interruptible() {{ printf 'RUN %s\\n' \"$*\" >> \"{calls}\"; return 0; }}",
                    f"docker() {{ printf 'DOCKER %s\\n' \"$*\" >> \"{calls}\"; return 0; }}",
                    "CI_IMAGE_IDS=()",
                    function,
                ])
                completed = subprocess.run(
                    ["bash", "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=60)
                self.assertEqual(completed.returncode, 0,
                                 completed.stdout + completed.stderr)
                self.assertIn("[FAIL]", completed.stdout)
                self.assertIn("not captured", completed.stderr)
                recorded = calls.read_text(encoding="utf-8")
                self.assertNotIn("RUN", recorded, recorded)
                self.assertNotIn("DOCKER run", recorded, recorded)

    def test_runtime_unit_containers_bypass_role_dispatcher_and_stay_offline(self):
        with tempfile.TemporaryDirectory() as temp:
            calls = Path(temp) / "calls.log"
            command = r'''source scripts/ci/local-ci.sh
trap - EXIT INT TERM HUP
run_interruptible() {
  printf '%q ' "$@" >> "$FAKE_CALLS"
  printf '\n' >> "$FAKE_CALLS"
  return 0
}
export COMPOSE_PROJECT_NAME="byq-ci-stack-$BYQ_CI_SCOPE"
CI_IMAGE_IDS[mcp]=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
CI_IMAGE_IDS[runtime-adapter]=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
check_runtime
check_f6_chain
test "$FAIL" -eq 0
'''
            result = subprocess.run(
                ["bash", "-c", command], cwd=ROOT, capture_output=True, text=True,
                env={**os.environ, "BYQ_CI_SCOPE": "entrypoint-contract",
                     "BYQ_F6_EXECUTOR_ENABLED": "0", "FAKE_CALLS": str(calls)},
                timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            commands = [shlex.split(line) for line in calls.read_text().splitlines()]
            docker_runs = [tokens for tokens in commands
                           if tokens[:2] == ["docker", "run"]]
            runtime_unit = next(tokens for tokens in docker_runs
                                if "--name" in tokens and "byq-ci-runtime-test-entrypoint-contract"
                                in tokens)
            f6_unit = next(tokens for tokens in docker_runs
                           if "tests/test_f6_synthetic_runtime_contract.py" in tokens)
            for tokens in (runtime_unit, f6_unit):
                entrypoint = tokens.index("--entrypoint")
                self.assertEqual(tokens[entrypoint + 1], "/opt/byq-venv/bin/python3")
                image_index = entrypoint + 2
                self.assertTrue(tokens[image_index].startswith("sha256:"))
                self.assertEqual(tokens[image_index + 1:image_index + 3], ["-m", "pytest"])
                self.assertIn("--network", tokens)
                self.assertEqual(tokens[tokens.index("--network") + 1], "none")
                self.assertFalse(any(token.startswith(("BYQ_ACP_ROLE=", "OPENCODE_API_KEY=",
                                                       "DEEPSEEK_API_KEY="))
                                     for token in tokens))


if __name__ == "__main__":
    unittest.main()
