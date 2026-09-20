import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

COMPONENTS = ("backend", "gateway", "runtime", "mcp", "frontend")


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/ci" / f"{name}.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


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
                     "docs/roadmap/DSH_012RC1_UPGRADE_PLAN.md", "LICENSE", "README.md",
                     "CONTRIBUTING.md", "CONTRIBUTOR_LICENSE_AGREEMENT.md", "SECURITY.md",
                     "THIRD_PARTY_NOTICES.md", "docs/legal/OWNERSHIP.md"):
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


class CiRoutingContractTests(unittest.TestCase):
    """Fail-closed routing contract for the impact graph.

    These lock the required coverage that CI-C must not trade away. Narrowing is
    only allowed for paths whose consumers are provably limited; everything
    unknown, cross-boundary, dependency-bearing or build-identity-bearing keeps
    the conservative lane set.
    """

    def assert_full_fail_closed(self, path: str) -> None:
        plan = classify(path)
        self.assertEqual(plan["unknown"], "yes", path)
        self.assertEqual(plan["docs_only"], "no", path)
        self.assertEqual(plan["integration"], "yes", path)
        for component in COMPONENTS:
            self.assertEqual(plan[component], "yes", f"{path}:{component}")

    def test_unknown_and_new_paths_fail_closed_to_all_and_integration(self) -> None:
        for path in (
            "tools/new-runner.ts",
            "newtopdir/module.py",
            "services/new-service/app/main.py",
            "config/dsh/builds/dsh-0.1.2rc1-post-u8.999.json",
            "scripts/ops/brand-new-op.py",
        ):
            with self.subTest(path=path):
                self.assert_full_fail_closed(path)

    def test_contracts_keep_complete_cross_component_coverage(self) -> None:
        for path in (
            "docs/contracts/product-api.openapi.yaml",
            "docs/contracts/product-capability-catalog.v1.json",
            "packages/contracts/workflow_trace.py",
        ):
            with self.subTest(path=path):
                plan = classify(path)
                self.assertEqual(plan["integration"], "yes")
                self.assertEqual(plan["docs_only"], "no")
                for component in COMPONENTS:
                    self.assertEqual(plan[component], "yes")

    def test_migrations_lock_deps_and_container_startup_keep_integration(self) -> None:
        for path in (
            "services/backend/migrations/0002_next.sql",
            "services/runtime-adapter/pyproject.toml",
            "services/runtime-adapter/requirements.candidate.lock",
            "services/runtime-adapter/runtime/package-lock.json",
            "services/runtime-adapter/Dockerfile",
            "services/runtime-adapter/Dockerfile.post-u8-candidate",
            "services/dsh/Dockerfile",
            "compose.yml",
        ):
            with self.subTest(path=path):
                plan = classify(path)
                self.assertEqual(plan["integration"], "yes")
                self.assertEqual(plan["docs_only"], "no")

    def test_runtime_protocol_cross_boundary_keeps_all_components(self) -> None:
        for path in (
            "services/runtime-adapter/app/runtime.py",
            "services/runtime-adapter/app/main.py",
            "services/runtime-adapter/runtime/byq-continuation-budget.js",
        ):
            with self.subTest(path=path):
                plan = classify(path)
                self.assertEqual(plan["integration"], "yes")
                for component in COMPONENTS:
                    self.assertEqual(plan[component], "yes")

    def test_build_identity_drift_stays_conservative(self) -> None:
        for path in (
            "config/dsh/builds/dsh-0.1.2rc1-post-u8.158.json",
            "scripts/dsh/build_revision.py",
            "scripts/dsh/release.py",
            "scripts/dsh/promotion.py",
        ):
            with self.subTest(path=path):
                plan = classify(path)
                self.assertEqual(plan["integration"], "yes")
                for component in COMPONENTS:
                    self.assertEqual(plan[component], "yes")

    def test_mixed_changes_take_the_risk_union(self) -> None:
        plan = classify(
            "apps/frontend/src/views/StrategyView.vue",
            "services/gateway/app/main.py",
        )
        self.assertEqual(plan["frontend"], "yes")
        self.assertEqual(plan["gateway"], "yes")
        self.assertEqual(plan["integration"], "no")

        plan = classify(
            "docs/operations/self-hosted-ci.md",
            "services/runtime-adapter/tests/test_continuation_budget_process.py",
        )
        self.assertEqual(plan["docs"], "yes")
        self.assertEqual(plan["runtime"], "yes")
        self.assertEqual(plan["integration"], "yes")
        self.assertEqual(plan["backend"], "no")

    def test_rename_and_delete_consider_old_and_new_paths(self) -> None:
        # Both sides of a rename are fed to the classifier: a contract that was
        # moved into a documentation-looking destination still carries its risk.
        plan = classify(
            "docs/former_contract.py",
            "packages/contracts/former_contract.py",
        )
        self.assertEqual(plan["integration"], "yes")
        for component in COMPONENTS:
            self.assertEqual(plan[component], "yes")

    def test_callers_disable_rename_collapsing(self) -> None:
        plan_source = (ROOT / "scripts/ci/plan.py").read_text()
        local_source = (ROOT / "scripts/ci/local-ci.sh").read_text()
        self.assertIn("--no-renames", plan_source)
        self.assertIn("--no-renames", local_source)

    def test_plan_reports_old_path_risk_for_a_real_rename(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "scripts/ci").mkdir(parents=True)
            (repo / "scripts/ci/classify-changes.sh").write_bytes(
                (ROOT / "scripts/ci/classify-changes.sh").read_bytes()
            )

            def git(*args: str) -> None:
                subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

            git("init", "-q")
            git("config", "user.email", "ci@example.invalid")
            git("config", "user.name", "CI")
            source = repo / "packages/contracts/former_contract.py"
            source.parent.mkdir(parents=True)
            source.write_text("VALUE = 1\n")
            git("add", "-A")
            git("commit", "-qm", "add contract")
            (repo / "docs").mkdir()
            git("mv", "packages/contracts/former_contract.py", "docs/former_contract.py")
            git("commit", "-qm", "rename contract")

            original = os.getcwd()
            os.chdir(repo)
            try:
                result = load_script("plan").plan("HEAD~1")
            finally:
                os.chdir(original)
            self.assertIn("integration", [entry["lane"] for entry in result["include"]])

    def test_proven_safe_narrowings_keep_only_required_lanes(self) -> None:
        # packages/operations is imported only by Gateway and the runtime
        # adapter; it is a cross-boundary startup gate, so integration stays.
        plan = classify("packages/operations/admission.py")
        self.assertEqual(plan["gateway"], "yes")
        self.assertEqual(plan["runtime"], "yes")
        self.assertEqual(plan["architecture"], "yes")
        self.assertEqual(plan["integration"], "yes")
        for component in ("backend", "mcp", "frontend"):
            self.assertEqual(plan[component], "no")

        # runtime-adapter tests are test-only: the runtime lane executes them and
        # the integration candidate qualification mounts them.
        plan = classify("services/runtime-adapter/tests/test_chat_admission.py")
        self.assertEqual(plan["runtime"], "yes")
        self.assertEqual(plan["integration"], "yes")
        for component in ("backend", "gateway", "mcp", "frontend"):
            self.assertEqual(plan[component], "no")

        # Operator-only production scripts: no service or CI lane imports them,
        # only root architecture tests exercise them.
        plan = classify("scripts/dsh/production_observe.py")
        self.assertEqual(plan["architecture"], "yes")
        self.assertEqual(plan["integration"], "no")
        for component in COMPONENTS:
            self.assertEqual(plan[component], "no")


if __name__ == "__main__":
    unittest.main()
