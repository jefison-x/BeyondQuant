import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def classify(*paths: str) -> dict[str, str]:
    result = subprocess.run(
        [str(ROOT / "scripts/ci/classify-changes.sh")],
        cwd=ROOT,
        input="\n".join(paths) + "\n",
        check=True,
        capture_output=True,
        text=True,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


class CiPolicyTests(unittest.TestCase):
    def test_inline_schema_and_runtime_protocol_are_integration_risks(self) -> None:
        for path in ("services/backend/app/backtest.py", "services/backend/app/engineering.py",
                     "services/backend/app/conversation_catalog.py", "services/runtime-adapter/app/runtime.py"):
            with self.subTest(path=path):
                self.assertEqual(classify(path)["integration"], "yes")

    def test_integration_risks_precede_broad_component_and_docs_matches(self) -> None:
        for path in (
            "docs/contracts/product-api.openapi.yaml",
            "docs/contracts/product-capability-catalog.v1.json",
            "apps/frontend/tests/e2e/real-new.spec.ts",
            "services/backend/app/main.py",
            "services/backend/migrations/next.sql",
            "services/runtime-adapter/runtime/package-lock.json",
            "services/runtime-adapter/pyproject.toml",
            "plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml",
            "scripts/dsh/release.py",
        ):
            with self.subTest(path=path):
                plan = classify(path)
                self.assertEqual(plan["docs_only"], "no")
                self.assertEqual(plan["integration"], "yes")
                for component in ("backend", "gateway", "runtime", "mcp", "frontend"):
                    self.assertEqual(plan[component], "yes")

    def test_normative_docs_run_architecture_without_compose(self) -> None:
        for path in ("docs/DEVELOPMENT_WORKFLOW.md", "docs/operations/ci-policy.md",
                     "docs/roadmap/DSH_012RC1_UPGRADE_PLAN.md"):
            with self.subTest(path=path):
                plan = classify(path)
                self.assertEqual(plan["architecture"], "yes")
                self.assertEqual(plan["integration"], "no")

    def test_docs_only_uses_the_lightweight_lane(self) -> None:
        plan = classify("docs/operations/self-hosted-ci.md")
        self.assertEqual(plan["docs_only"], "yes")
        self.assertEqual(plan["docs"], "yes")
        self.assertEqual(plan["frontend"], "no")
        self.assertEqual(plan["integration"], "no")

    def test_frontend_change_runs_frontend_without_full_compose(self) -> None:
        plan = classify("apps/frontend/src/views/StrategyView.vue")
        self.assertEqual(plan["frontend"], "yes")
        self.assertEqual(plan["architecture"], "yes")
        self.assertEqual(plan["backend"], "no")
        self.assertEqual(plan["integration"], "no")

    def test_shared_contract_change_fans_out_and_runs_integration(self) -> None:
        plan = classify("packages/contracts/workflow-trace.schema.json")
        for component in ("backend", "gateway", "runtime", "mcp", "frontend"):
            self.assertEqual(plan[component], "yes")
        self.assertEqual(plan["integration"], "yes")

    def test_unknown_source_fails_closed_to_full_integration(self) -> None:
        plan = classify("tools/new-runner.ts")
        self.assertEqual(plan["unknown"], "yes")
        self.assertEqual(plan["integration"], "yes")

    def test_workflow_and_cleanup_enforce_resource_safety(self) -> None:
        workflow = (ROOT / ".github/workflows/ci-selfhosted.yml").read_text()
        local_ci = (ROOT / "scripts/ci/local-ci.sh").read_text()
        cleanup = (ROOT / "scripts/ci/cleanup-resources.sh").read_text()

        self.assertIn("cancel-in-progress: true", workflow)
        self.assertIn("if: always()", workflow)
        self.assertIn("${{ github.run_id }}-${{ github.run_attempt }}", workflow)
        self.assertNotIn("push:\n    branches:\n      - main", workflow)
        self.assertIn("trap cleanup_on_exit EXIT", local_ci)
        self.assertIn("trap 'terminate_on_signal 143' TERM HUP", local_ci)
        self.assertIn("run_interruptible docker run", local_ci)
        self.assertIn("--no-cleanup is forbidden in GitHub Actions", local_ci)
        self.assertIn("BYQ_CI_MIN_AVAILABLE_MEMORY_KB", local_ci)
        self.assertIn("flock -w", local_ci)
        self.assertIn('label=byq.ci.scope=$SCOPE', cleanup)
        self.assertIn("if ! docker info", cleanup)
        self.assertIn("cleanup verification failed", cleanup)


if __name__ == "__main__":
    unittest.main()
