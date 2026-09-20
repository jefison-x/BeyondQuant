"""Workflow-level CI-A contracts: early-fail, cancellation and fail-closed gates.

These tests read the checked-in workflow and scripts as text plus the pure
functions they expose. They do not execute GitHub Actions; they pin the
structural invariants so a later edit cannot silently reintroduce a run where a
failed contribution still spends ~20 minutes of heavy lanes, or where a skipped
lane is treated as success.
"""
import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/ci-selfhosted.yml").read_text()


def module(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/ci" / f"{name}.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def job_block(name: str) -> str:
    pattern = rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)"
    match = re.search(pattern, WORKFLOW)
    if not match:
        raise AssertionError(f"job not found: {name}")
    return match.group(0)


class CiWorkflowContractTests(unittest.TestCase):
    def test_heavy_lanes_depend_on_plan_and_contribution_success(self) -> None:
        checks = job_block("checks")
        self.assertIn("needs: [plan, contribution]", checks)
        self.assertIn("fail-fast: false", checks)

    def test_plan_selection_still_owns_all_components_and_integration(self) -> None:
        plan = module("plan")
        plan_step = job_block("plan")
        self.assertIn("matrix=$(python3 scripts/ci/plan.py", plan_step)
        self.assertIn("--full", plan_step)
        self.assertEqual(plan.COMPONENTS,
                         ("docs", "architecture", "backend", "gateway", "runtime", "mcp", "frontend"))

    def test_missing_matrix_or_empty_plan_is_not_an_empty_success(self) -> None:
        plan = module("plan")
        from unittest import mock

        outputs = {
            ("git", "merge-base"): "base",
            ("git", "diff"): "",
            ("bash", "scripts/ci/classify-changes.sh"): (
                "changed_count=0\ndocs=no\ndocs_only=no\narchitecture=no\nbackend=no\n"
                "gateway=no\nruntime=no\nmcp=no\nfrontend=no\nintegration=no\nunknown=no\n"
            ),
        }

        def fake_check_output(command, **kwargs):
            return outputs.get(tuple(command[:2]), "")

        with mock.patch.object(plan.subprocess, "check_output", side_effect=fake_check_output):
            with self.assertRaises(ValueError):
                plan.plan("origin/main", full=False)

    def test_aggregate_gates_require_success_and_never_treat_skipped_as_pass(self) -> None:
        local_ci = job_block("local-ci")
        self.assertIn("if: always()", local_ci)
        self.assertIn("needs: [plan, checks]", local_ci)
        self.assertIn('test "$PLAN_RESULT" = success', local_ci)
        self.assertIn('test "$CHECKS_RESULT" = success', local_ci)

        gate = job_block("ci-gate")
        self.assertIn("if: always()", gate)
        self.assertIn("needs: [local-ci, contribution]", gate)
        self.assertIn('test "$CI_RESULT" = success', gate)
        self.assertIn('test "$CONTRIBUTION_RESULT" = success', gate)

    def test_cancellation_and_cleanup_are_preserved(self) -> None:
        self.assertIn("cancel-in-progress: true", WORKFLOW)
        checks = job_block("checks")
        self.assertIn("fail-fast: false", checks)
        self.assertIn("if: always()", checks)
        self.assertIn("cleanup-resources.sh", checks)
        self.assertIn("if-no-files-found: error", checks)
        # The whole matrix must not fail-fast: cleanup and diagnostics still run
        # for untouched lanes and the aggregate gate owns the failure.
        self.assertNotIn("fail-fast: true", WORKFLOW)

    def test_measurement_is_low_noise_and_adds_no_full_run(self) -> None:
        local_ci = (ROOT / "scripts/ci/local-ci.sh").read_text()
        self.assertIn("[byq-timing] phase=", local_ci)
        self.assertIn("[byq-timing] total seconds=", local_ci)
        self.assertIn("--durations=20 --durations-min=1.0", local_ci)
        # Measurement must not introduce a second workflow or a schedule change.
        workflows = sorted(path.name for path in (ROOT / ".github/workflows").glob("*.yml"))
        self.assertEqual(workflows, ["ci-selfhosted.yml", "promote-images.yml", "release-images.yml"])
        self.assertIn("cron: '0 19 * * *'", WORKFLOW)

    def test_contribution_uses_trusted_base_and_exact_head(self) -> None:
        contribution = job_block("contribution")
        self.assertIn("ref: ${{ github.event.pull_request.base.sha || github.sha }}", contribution)
        self.assertIn("sparse-checkout: scripts/ci", contribution)
        self.assertIn("persist-credentials: false", contribution)
        self.assertIn("--expected-head", contribution)
        self.assertIn("GH_TOKEN: ${{ github.token }}", contribution)
        # The heavy lanes may not gain any write token or fork privileges.
        self.assertIn("permissions:\n      contents: read", contribution)
        self.assertIn("pull-requests: read", contribution)


if __name__ == "__main__":
    unittest.main()
