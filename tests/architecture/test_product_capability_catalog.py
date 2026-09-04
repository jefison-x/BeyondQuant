import unittest
from pathlib import Path

from scripts.validate_product_capability_catalog import validate


class ProductCapabilityCatalogTests(unittest.TestCase):
    def test_product_capability_catalog_matches_product_and_mcp_surfaces(self) -> None:
        validate()

    def test_product_guide_is_bundled_and_help_is_root_read_only_metadata(self) -> None:
        root = Path(__file__).resolve().parents[2]
        skill = (root / "plugins/dsh-byq/skills/byq-product-guide/SKILL.md").read_text()
        role = (root / "services/backend/app/agent_research.py").read_text()
        mcp = (root / "services/mcp/src/server.ts").read_text()
        self.assertIn("byq_product_help_query", skill)
        self.assertIn('"byq_product_help_query"', role)
        self.assertIn("Read-only; this never grants access or mutates Domain state", mcp)
        self.assertIn("do not start a domain AgentRun", skill)

    def test_backtest_agent_surface_is_task_only_and_never_accepts_raw_inputs(self) -> None:
        root = Path(__file__).resolve().parents[2]
        mcp = (root / "services/mcp/src/server.ts").read_text()
        roles = (root / "services/backend/app/agent_research.py").read_text()
        contract = (root / "docs/contracts/backtest-task.md").read_text()
        for tool in (
            "byq_backtest_task_prepare",
            "byq_backtest_task_create",
            "byq_backtest_task_get",
            "byq_backtest_task_execute",
            "byq_backtest_task_cancel",
        ):
            self.assertIn(f'"{tool}"', mcp)
            self.assertIn(f'"{tool}"', roles)
        for retired in ("byq_backtest_submit", "byq_backtest_run", "byq_backtest_cancel"):
            self.assertNotIn(f'    "{retired}",', roles)
            self.assertNotIn(f'    "{retired}",', mcp)
        task_registration = mcp[mcp.index('"byq_backtest_task_prepare"'):mcp.index('"byq_backtest_get"')]
        self.assertNotIn("bars:", task_registration)
        self.assertNotIn("signals:", task_registration)
        self.assertIn("not a second workflow", contract)

    def test_feedback_agent_surface_requires_preview_and_has_no_admin_or_publisher_tools(self) -> None:
        root = Path(__file__).resolve().parents[2]
        mcp = (root / "services/mcp/src/server.ts").read_text()
        roles = (root / "services/backend/app/agent_research.py").read_text()
        skill = (root / "plugins/dsh-byq/skills/byq-product-feedback/SKILL.md").read_text()
        for tool in ("byq_feedback_create_draft", "byq_feedback_update_draft", "byq_feedback_preview", "byq_feedback_submit"):
            self.assertIn(f'"{tool}"', mcp)
            self.assertIn(f'"{tool}"', roles)
        for prohibited in ("byq_feedback_moderate", "byq_feedback_publish", "github_token", "github_repository"):
            self.assertNotIn(f'"{prohibited}"', mcp)
        self.assertIn("global approval", skill)
        self.assertIn("agent_approval_id", skill)
        self.assertIn("do not submit yet", skill)

    def test_ml_agent_surface_is_closed_training_only_and_keeps_human_approval(self) -> None:
        root = Path(__file__).resolve().parents[2]
        mcp = (root / "services/mcp/src/server.ts").read_text()
        roles = (root / "services/backend/app/agent_research.py").read_text()
        composition = (root / "plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml").read_text()
        skill = (root / "plugins/dsh-byq/skills/byq-ml-researcher/SKILL.md").read_text()
        contract = (root / "docs/contracts/machine-learning-research.md").read_text()
        allowed = (
            "byq_ml_capabilities", "byq_ml_workspace_get", "byq_ml_strategy_create",
            "byq_ml_strategy_approve",
            "byq_ml_training_create", "byq_ml_training_get", "byq_ml_training_cancel",
            "byq_ml_prediction_create", "byq_ml_prediction_get",
        )
        for tool in allowed:
            self.assertIn(f'"{tool}"', mcp)
            self.assertIn(f'"{tool}"', roles)
            self.assertIn(tool, composition)
        ml_role = roles.split('role_id="ml_researcher"', 1)[1].split("    ),", 1)[0]
        ml_delegate = composition.split("- id: delegate-ml-research", 1)[1].split("# Qualified", 1)[0]
        for prohibited in (
            "byq_strategy_approve",
            "byq_backtest_task_prepare", "byq_backtest_task_create", "byq_artifact_create",
        ):
            self.assertNotIn(prohibited, ml_role)
            self.assertNotIn(prohibited, ml_delegate)
        registration = mcp[mcp.index('"byq_ml_strategy_create"'):mcp.index('"byq_signal_snapshot_get"')]
        for prohibited in ("python:", "sql:", "url:", "model_object", "object_reference", "feature_rows"):
            self.assertNotIn(prohibited, registration.lower())
        self.assertIn("the user to a business page", skill)
        self.assertIn("exact Agent approval ID", skill)
        self.assertIn("ML Strategy Approval", contract)
        self.assertIn("backtesttask_ml_", contract)
