"""Keep the Clean Break authority switch consistent across repository entry points."""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class CleanBreakGovernanceTests(unittest.TestCase):
    def test_current_adr_baseline_and_historical_records(self):
        activation = (ROOT / "docs/architecture/adr/ADR-0088-clean-break-baseline-activation.md").read_text()
        index = (ROOT / "docs/clean-break/adr/README.md").read_text()
        self.assertIn("Status: Accepted", activation)
        self.assertIn("sole current", index)
        self.assertIn("ADR-0001 through ADR-0087", activation)
        for number in range(1, 7):
            matches = list((ROOT / "docs/clean-break/adr").glob(f"ADR-{number:03d}-*.md"))
            self.assertEqual(len(matches), 1)
            self.assertIn("Status: Accepted under ADR-0088", matches[0].read_text())
        old_adrs = list((ROOT / "docs/architecture/adr").glob("ADR-*.md"))
        historical = [p for p in old_adrs if p.name != "ADR-0088-clean-break-baseline-activation.md"]
        self.assertTrue(historical)
        governance = {15, 59, 68, 70, 80}
        for path in historical:
            number = int(path.name[4:8])
            if number in governance:
                self.assertIn("Current non-product governance/security policy", path.read_text(), path.name)
            else:
                self.assertIn("Historical-only under BYQ 0.10 Clean Break", path.read_text(), path.name)
        for name in ("ADR-0059", "ADR-0068", "ADR-0080"):
            self.assertIn(name, activation)

    def test_current_route_is_distinct_from_legacy_product_marker(self):
        status = (ROOT / "docs/roadmap/STATUS.md").read_text()
        readme = (ROOT / "README.md").read_text()
        plan = (ROOT / "docs/roadmap/IMPLEMENTATION_PLAN.md").read_text()
        architecture = (ROOT / "ARCHITECTURE.md").read_text()
        expected = "<!-- byq:clean-break-current-phase=10 -->"
        self.assertIn(expected, status)
        self.assertIn(expected, readme)
        self.assertEqual(re.findall(r"<!-- byq:current-completed-phase=(\d+) -->", status), ["97"])
        self.assertIn("Next phase: Clean Break", status.split("## Historical 0.9/P4 status")[0])
        self.assertIn("Phase 7–17 sequence", plan.split("## Historical implementation plan")[0])
        current_architecture = architecture.split("## Historical pre-Clean-Break architecture")[0]
        for required in ("DSH owns Agent loop", "BYQ owns quant domain", "Product Agent-to-Domain calls MUST use BYQ MCP", "Long deterministic compute"):
            self.assertIn(required, current_architecture)


if __name__ == "__main__":
    unittest.main()
