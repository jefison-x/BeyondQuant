"""Fail-closed caller tests for the shared ACP Compose route (ADR-0110).

``set_ci_compose_files`` resolves the single checked-in Compose route through
``scripts/release/images.py route``. Bash suppresses ``errexit`` while
local-ci.sh invokes ``build_test_images`` under ``if !``, so a bare
``prepare_ci_compose_env`` call could let a route resolution failure be ignored
and reach a Docker/Compose command with an ambient, empty or stale route.

These tests are fully offline: they source local-ci.sh, replace the route
wrapper with failing/empty/malformed output, stub every Docker/Compose command,
and prove that no build/up/compose command is attempted. No real Docker is
invoked.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICES_17 = (
    "backend gateway runtime-adapter mcp frontend data-worker backtest-worker "
    "factor-worker optimization-worker signal-worker ml-worker signal-sandbox "
    "feedback-hub-relay acp-product-runner acp-judgment-runner mcp-acp-judgment "
    "judgment-consumer"
)

# ``NO_CLEANUP=1`` prevents the sourced EXIT trap from running the real
# Docker-backed scripts/ci/cleanup-resources.sh. Every Docker/Compose command is
# replaced with a logging stub that records into ``$FAKE_COMMANDS``.
PREAMBLE = r'''
source scripts/ci/local-ci.sh
NO_CLEANUP=1
RESOURCES_TOUCHED=0
docker() { printf 'docker %s\n' "$*" >> "$FAKE_COMMANDS"; return 0; }
acp_compose() { printf 'acp_compose %s\n' "$*" >> "$FAKE_COMMANDS"; return 0; }
run_interruptible() { printf 'run_interruptible %s\n' "$*" >> "$FAKE_COMMANDS"; "$@"; }
python3() { return 0; }
acquire_heavy_capacity() { return 0; }
export COMPOSE_PROJECT_NAME="byq-ci-stack-$BYQ_CI_SCOPE"
'''

FAILURE_ROUTE = "acp_compose_route_files() { return 7; }\n"
EMPTY_ROUTE = 'acp_compose_route_files() { printf ""; }\n'
FORBIDDEN_CALLS = ("docker", "acp_compose", "run_interruptible", " build", " up ")


class ComposeRouteCallerFailClosedTests(unittest.TestCase):
    def _run(self, body, extra_env=None):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "commands.txt"
            env = {**os.environ, "BYQ_CI_SCOPE": "route-caller-contract",
                   "FAKE_COMMANDS": str(log)}
            if extra_env:
                env.update(extra_env)
            result = subprocess.run(
                ["bash", "-c", PREAMBLE + body], cwd=ROOT,
                capture_output=True, text=True, env=env)
            calls = log.read_text(encoding="utf-8") if log.exists() else ""
            return result, calls

    def _assert_no_compose_command(self, calls):
        for marker in FORBIDDEN_CALLS:
            self.assertNotIn(
                marker, calls,
                f"route failure reached a Docker/Compose command: {calls!r}")

    def test_build_test_images_fails_before_any_docker_build(self):
        # ONLY=runtime would select a non-empty build batch, so a suppressed
        # route failure would visibly reach `acp_compose build` under the defect.
        for override in (FAILURE_ROUTE, EMPTY_ROUTE):
            with self.subTest(route=override.strip()):
                body = "ONLY=runtime\n" + override \
                    + "if build_test_images; then exit 9; fi\n"
                result, calls = self._run(body)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self._assert_no_compose_command(calls)

    def test_check_smoke_accounts_failure_and_returns_before_compose(self):
        for override in (FAILURE_ROUTE, EMPTY_ROUTE):
            with self.subTest(route=override.strip()):
                result, calls = self._run(
                    override + 'if check_smoke; then exit 9; fi\ntest "$FAIL" -eq 1\n')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("[FAIL] isolated compose route selection", result.stdout)
                self._assert_no_compose_command(calls)

    def test_check_dsh_web_accounts_failure_and_returns_before_compose(self):
        for override in (FAILURE_ROUTE, EMPTY_ROUTE):
            with self.subTest(route=override.strip()):
                result, calls = self._run(
                    override + 'if check_dsh_web; then exit 9; fi\ntest "$FAIL" -eq 1\n')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("[FAIL] dsh-web compose route selection", result.stdout)
                self._assert_no_compose_command(calls)

    def test_set_ci_compose_files_accepts_absolute_ordered_entries(self):
        body = (
            'acp_compose_route_files() { printf \'%s\\n%s\\n\' "$ROUTE_A" "$ROUTE_B"; }\n'
            "set_ci_compose_files\n"
            'test "$COMPOSE_FILE" = "$ROUTE_A:$ROUTE_B"\n'
            'test "${#CI_COMPOSE_FILES[@]}" -eq 2\n')
        with tempfile.TemporaryDirectory() as temp:
            route_a = str(Path(temp) / "compose.yml")
            route_b = str(Path(temp) / "compose.override.yml")
            result, _calls = self._run(body, {"ROUTE_A": route_a, "ROUTE_B": route_b})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_set_ci_compose_files_rejects_blank_relative_and_empty_routes(self):
        cases = {
            "empty": 'acp_compose_route_files() { printf ""; }\n',
            "blank entry": (
                'acp_compose_route_files() { printf \'%s\\n\\n%s\\n\' "$ROUTE_A" "$ROUTE_B"; }\n'),
            "relative entry": (
                'acp_compose_route_files() { printf \'%s\\n%s\\n\' '
                '"$ROUTE_A" "compose.override.yml"; }\n'),
        }
        with tempfile.TemporaryDirectory() as temp:
            route_a = str(Path(temp) / "compose.yml")
            route_b = str(Path(temp) / "compose.override.yml")
            for name, override in cases.items():
                with self.subTest(case=name):
                    body = (override + 'COMPOSE_FILE="sentinel"\n'
                            "if set_ci_compose_files; then exit 9; fi\n"
                            'test "$COMPOSE_FILE" = "sentinel"\n')
                    result, _calls = self._run(
                        body, {"ROUTE_A": route_a, "ROUTE_B": route_b})
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("no fallback route is permitted", result.stderr)

    def test_every_route_call_site_propagates_explicitly(self):
        source = (ROOT / "scripts/ci/local-ci.sh").read_text(encoding="utf-8")
        self.assertIn("prepare_ci_compose_env || return 1", source)
        self.assertEqual(source.count("if ! prepare_ci_compose_env; then"), 2)
        self.assertNotIn("\n  prepare_ci_compose_env\n", source)
        self.assertIn(
            'run_interruptible python3 "$REPO_ROOT/scripts/dsh/acp_build.py" -- bash ./tests/smoke/run.sh',
            source,
        )
        self.assertIn('phase48-product-golden.py --workspace-receipt', source)
        self.assertIn("docker inspect \"$container_id\" --format '{{.Image}}'", source)
        self.assertIn('[ "$running_image" != "$captured_image" ]', source)


SINGLE_IMAGE_BUILD_BODY = r'''
source scripts/ci/local-ci.sh
NO_CLEANUP=1
RESOURCES_TOUCHED=0
export COMPOSE_PROJECT_NAME="byq-ci-stack-$BYQ_CI_SCOPE"
WITH_SMOKE=1
declare -A CI_IMAGE_IDS=()
SHARED_ID="sha256:$(printf 'a%.0s' {1..64})"
STALE_ID="sha256:$(printf 'b%.0s' {1..64})"
TAG_STATE="$FAKE_TAG_STATE"
mkdir -p "$TAG_STATE"
if [ -n "${STALE_ROLE:-}" ]; then
  printf '%s' "$STALE_ID" > "$TAG_STATE/$COMPOSE_PROJECT_NAME-$STALE_ROLE"
fi
prepare_ci_compose_env() { return 0; }
acp_route_topology() { printf '%s' "$TOPOLOGY"; }
acp_unified_image_tag() { printf '%s' "$COMPOSE_PROJECT_NAME-acp-unified"; }
release_image_services() { printf '%s\n' $SERVICES17; }
acquire_heavy_capacity() { return 0; }
python3() { return 0; }
run_interruptible() { "$@"; }
acp_compose() {
  printf 'acp_compose %s\n' "$*" >> "$FAKE_COMMANDS"
  if [ "${1:-}" = build ] && [ "${FAIL_BUILD:-0}" = 1 ]; then return 1; fi
  return 0
}
docker() {
  printf 'docker %s\n' "$*" >> "$FAKE_COMMANDS"
  if [ "$1" = image ] && [ "$2" = inspect ]; then
    tag="$3"
    if [ -f "$TAG_STATE/$tag" ]; then
      cat "$TAG_STATE/$tag"
    elif [ "$tag" = "$COMPOSE_PROJECT_NAME-acp-unified" ]; then
      printf '%s\n' "$SHARED_ID"
    else
      printf 'sha256:%s\n' "$(printf '%s' "$tag" | sha256sum | cut -c1-64)"
    fi
    return 0
  fi
  if [ "$1" = tag ]; then
    src="$2"; dst="$3"
    if [ -f "$TAG_STATE/$src" ]; then
      src_id="$(cat "$TAG_STATE/$src")"
    else
      src_id="$src"
    fi
    printf '%s' "$src_id" > "$TAG_STATE/$dst"
    return 0
  fi
  return 0
}
if build_test_images; then build_rc=0; else build_rc=$?; fi
printf 'BUILD_RC=%s\n' "$build_rc"
exit "$build_rc"
'''

ROLE_SERVICES = ("runtime-adapter", "acp-product-runner", "acp-judgment-runner")


class SingleImageBuildCaptureTests(unittest.TestCase):
    def _run_build(self, *, topology, stale_role="", fail_build=False):
        scope = f"si-{topology}" + (f"-{stale_role}" if stale_role else "")
        if fail_build:
            scope += "-fail"
        manifest_dir = ROOT / ".ci-artifacts" / scope
        self.addCleanup(shutil.rmtree, manifest_dir, ignore_errors=True)
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "commands.txt"
            tag_state = Path(temp) / "tags"
            env = {
                **os.environ,
                "BYQ_CI_SCOPE": scope,
                "FAKE_COMMANDS": str(log),
                "FAKE_TAG_STATE": str(tag_state),
                "TOPOLOGY": topology,
                "STALE_ROLE": stale_role,
                "FAIL_BUILD": "1" if fail_build else "0",
                "SERVICES17": SERVICES_17,
            }
            result = subprocess.run(
                ["bash", "-c", SINGLE_IMAGE_BUILD_BODY], cwd=ROOT,
                capture_output=True, text=True, env=env, timeout=60)
            calls = log.read_text(encoding="utf-8") if log.exists() else ""
        manifest = manifest_dir / "image-ids.env"
        text = manifest.read_text(encoding="utf-8") if manifest.exists() else ""
        return result, calls, text

    def _build_line(self, calls):
        return next(
            line for line in calls.splitlines() if line.startswith("acp_compose build"))

    def test_single_image_builds_one_acp_target_and_captures_one_shared_id(self):
        result, calls, manifest = self._run_build(topology="single-image")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BUILD_RC=0", result.stdout)
        build = self._build_line(calls)
        # The canonical unified target is built exactly once and neither runner
        # target is built independently under the one shared image.
        self.assertEqual(build.split().count("runtime-adapter"), 1, build)
        self.assertNotIn("acp-product-runner", build)
        self.assertNotIn("acp-judgment-runner", build)
        shared = "sha256:" + "a" * 64
        for role in ROLE_SERVICES:
            self.assertIn(
                f"docker tag {shared} byq-ci-stack-si-single-image-{role}", calls)
        entries = dict(line.split("=", 1) for line in manifest.splitlines() if line)
        self.assertEqual(len(entries), 17)
        self.assertEqual(
            {entries[role] for role in ROLE_SERVICES}, {shared})

    def test_pre_existing_stale_role_tags_are_unconditionally_replaced(self):
        # A pre-existing per-role tag with a different image id must never be
        # captured: the run aliases the built shared immutable id and asserts
        # every role now equals that shared id.
        for stale_role in ROLE_SERVICES:
            with self.subTest(stale_role=stale_role):
                result, calls, manifest = self._run_build(
                    topology="single-image", stale_role=stale_role)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("BUILD_RC=0", result.stdout)
                shared = "sha256:" + "a" * 64
                self.assertIn(
                    f"docker tag {shared} byq-ci-stack-si-single-image-{stale_role}",
                    calls)
                entries = dict(line.split("=", 1) for line in manifest.splitlines() if line)
                self.assertEqual(len(entries), 17)
                self.assertEqual(
                    {entries[role] for role in ROLE_SERVICES}, {shared})

    def test_build_failure_fails_closed_without_alias_capture_or_manifest(self):
        # A failed canonical build must never reach the alias/capture step, so a
        # stale per-role tag can never be captured or released.
        result, calls, manifest = self._run_build(
            topology="single-image", stale_role="acp-product-runner", fail_build=True)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BUILD_RC=1", result.stdout)
        self.assertNotIn("docker tag", calls)
        self.assertNotIn("docker image inspect", calls)
        self.assertEqual(manifest, "")

    def test_unknown_topology_fails_closed_before_any_build(self):
        result, calls, manifest = self._run_build(topology="unknown-topology")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BUILD_RC=1", result.stdout)
        self.assertNotIn("acp_compose build", calls)
        self.assertEqual(manifest, "")


if __name__ == "__main__":
    unittest.main()
