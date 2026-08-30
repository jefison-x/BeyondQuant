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
