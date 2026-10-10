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
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

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


if __name__ == "__main__":
    unittest.main()
