"""0.9 strict-order step-5 G-split gate-order decision acceptance tests.

These tests assert the factual consistency of the decision/record batch only. They do
not implement anything: B2 `subagent-byq-adapter-restart` is not started, there is no
runtime/provider/child-bridge/TerminalAttachment code, the production DSH selector is
unchanged, no deployment happens, and no tag/release is created or moved.

Runs under ``unittest`` (the architecture lane has no pytest).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/v090-closeout"
DECISION = EVIDENCE / "gsplit-decision.v1.json"
SLICES = EVIDENCE / "DSH-015RC1-CLOSEOUT-SLICES.md"

B1 = "subagent-child-crash"
B2 = "subagent-byq-adapter-restart"
STRICT_INTERNAL_ORDER = [
    "subagent-byq-adapter-restart",
    "terminal-adapter-restart",
    "terminal-dsh-runtime-restart",
]
B2_OWNER = "d15-4-candidate-composition-hookup"


def _decision() -> dict:
    return json.loads(DECISION.read_text(encoding="utf-8"))


class GsplitDecisionRecordTests(unittest.TestCase):
    def test_record_is_a_maintainer_decision_not_a_github_approval(self):
        record = _decision()
        self.assertEqual(record["schema_version"], "byq-v090-gsplit-decision.v1")
        self.assertIn("maintainer", record["decision_authority"])
        self.assertEqual(record["decided_at"], "2026-09-21")
        self.assertFalse(record["github_approval_claimed"])
        self.assertIn("G-split", record["decision_source"])
        self.assertRegex(record["base"]["origin_main_commit"], r"^[0-9a-f]{40}$")

    def test_chosen_option_is_g_split(self):
        record = _decision()
        self.assertEqual(record["chosen_option"], "G-split")
        # The reject/downgrade options must not have been chosen.
        for rejected in ("G-keep", "G-reorder", "G-reclassify"):
            self.assertNotEqual(record["chosen_option"], rejected)

    def test_b1_stays_a_mandatory_external_blocker(self):
        b1 = _decision()["b1_subagent_child_crash"]
        self.assertEqual(b1["blocker"], B1)
        self.assertEqual(b1["status"], "BLOCKED")
        self.assertTrue(b1["mandatory"])
        self.assertTrue(b1["is_final_external_gate"])
        self.assertFalse(b1["downgraded"])
        self.assertFalse(b1["deleted"])
        self.assertFalse(b1["made_optional"])
        # The gate split separates B1 as the external item.
        gate_split = _decision()["gate_split"]
        self.assertEqual(gate_split["external_item"], B1)
        self.assertEqual(gate_split["internal_items"], STRICT_INTERNAL_ORDER)

    def test_strict_internal_order_is_b2_terminal_adapter_terminal_runtime(self):
        order = _decision()["allowed_internal_order"]
        self.assertTrue(order["strict"])
        self.assertEqual(order["items"], STRICT_INTERNAL_ORDER)
        self.assertEqual(order["enabled_by"], "G-split")

    def test_d15_g_stays_no_go_until_b1_passes(self):
        gate = _decision()["gate"]
        self.assertEqual(gate["id"], "d15-g")
        self.assertEqual(gate["status"], "NO_GO")
        self.assertTrue(gate["go_requires_all_required_atomic_capabilities_pass"])
        self.assertIn("B1", gate["stays_no_go_until"])
        self.assertIn(B1, gate["stays_no_go_until"])
        self.assertIn("PASS", gate["stays_no_go_until"])

    def test_next_task_is_b2_with_the_candidate_composition_owner(self):
        next_task = _decision()["next_task"]
        self.assertEqual(next_task["blocker"], B2)
        self.assertEqual(next_task["owner_node"], B2_OWNER)
        self.assertTrue(next_task["not_started_in_this_batch"])

    def test_constraints_keep_r3_frozen_and_0_9_open(self):
        constraints = _decision()["constraints"]
        self.assertEqual(constraints["r3_resume"], "NO")
        self.assertTrue(constraints["d15_frozen"])
        self.assertTrue(constraints["r3_frozen"])
        self.assertEqual(constraints["production_selector"], "dsh-0.1.2rc1")
        self.assertTrue(constraints["production_default_unchanged"])
        self.assertEqual(constraints["deployment"], "none")
        self.assertFalse(constraints["release_or_tag_created"])
        self.assertFalse(constraints["v090_closed"])
        joined = " ".join(_decision()["non_actions"]).lower()
        for phrase in ("subagent-byq-adapter-restart", "selector", "deployment",
                       "tag or release", "d15-g re-run"):
            self.assertIn(phrase, joined)


class GsplitDocTests(unittest.TestCase):
    def _status(self) -> str:
        return (ROOT / "docs/roadmap/STATUS.md").read_text(encoding="utf-8")

    def _plan(self) -> str:
        return (ROOT / "docs/roadmap/IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")

    def test_status_records_the_decision_marker_and_section(self):
        status = self._status()
        self.assertIn("<!-- byq:v090-step5-gsplit-decision=complete -->", status)
        self.assertIn("0.9 step-5 G-split gate-order decision", status)
        self.assertIn("`G-split`", status)
        self.assertIn("**0.9 未关闭**", status)
        self.assertIn("D15-G 保持 `NO_GO` 直到 B1 真正 PASS", status)
        self.assertIn("`R3_RESUME = NO`", status)
        self.assertIn(B2_OWNER, status)
        # B1 must not have been marked optional/downgraded anywhere.
        self.assertNotIn("subagent-child-crash=optional", status)
        self.assertNotIn("subagent-child-crash=deleted", status)

    def test_plan_records_the_decision_and_the_build_bump(self):
        plan = self._plan()
        self.assertIn("0.9 step-5 G-split gate-order decision", plan)
        self.assertIn(B2_OWNER, plan)
        self.assertIn("`post-u8.181 → post-u8.182`", plan)

    def test_slices_doc_records_the_chosen_option_and_strict_order(self):
        slices = SLICES.read_text(encoding="utf-8")
        self.assertIn("Maintainer decision (2026-09-21): `G-split`", slices)
        self.assertIn("MANDATORY external blocker", slices)
        self.assertIn("`subagent-byq-adapter-restart` → `terminal-adapter-restart` →\n  `terminal-dsh-runtime-restart`", slices)
        self.assertIn("D15-G stays `NO_GO` until B1 truly PASSes", slices)
        self.assertIn("`R3_RESUME = NO`", slices)
        self.assertIn(B2_OWNER, slices)

    def test_readme_links_the_machine_readable_decision(self):
        readme = (EVIDENCE / "README.md").read_text(encoding="utf-8")
        self.assertIn("gsplit-decision.v1.json", readme)


class BlockerNotDowngradedTests(unittest.TestCase):
    def test_d15_g_verdict_still_blocked_and_no_go(self):
        capability = json.loads(
            (ROOT / "docs/evidence/d15/d15-g/capability-matrix.v1.json").read_text(encoding="utf-8"))
        self.assertIn(B1, capability["primary_named_blockers"])
        verdict = json.loads(
            (ROOT / "docs/evidence/d15/d15-g/verdict.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(verdict["verdict"], "NO_GO")
        self.assertEqual(verdict["derived_capabilities"][B1], "BLOCKED")

    def test_b1_external_blocked_record_options_are_satisfied(self):
        blocked = json.loads(
            (ROOT / "docs/evidence/v090-d15-child-provider-remediation/external-blocked.v1.json")
            .read_text(encoding="utf-8"))
        options = blocked["maintainer_decision_required"]["options"]
        self.assertIn(_decision()["chosen_option"], options)
        self.assertIn(B2, blocked["downstream_not_started"])

    def test_no_b2_runtime_implementation(self):
        services = ROOT / "services"
        offenders = []
        for path in services.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".js", ".ts", ".mjs"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "resume_delegated_child" in text or "dsh-terminal" in text:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_production_selector_is_unchanged(self):
        deployment = json.loads(
            (ROOT / "config/dsh/deployment.json").read_text(encoding="utf-8"))
        self.assertEqual(deployment["default_release"], "dsh-0.1.2rc1")


if __name__ == "__main__":
    unittest.main()
