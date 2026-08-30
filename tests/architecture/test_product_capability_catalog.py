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
