"""Governance for the design-only step-safety + budget binding + rescheduling slice.

Runs under ``unittest`` (architecture lane). Asserts the slice is design/evidence
only, that no runtime implementation or ADR acceptance is claimed, that the full
ADR-0084 business-recovery gate stays ``IN_PROGRESS / BLOCKED_INTERNAL``, and
that no D15 superseding assessment is created while B1/B2 stay
``BLOCKED_EXTERNAL``, D15-G stays ``NO_GO`` and ``R3_RESUME = NO``.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/v090-step-safety-design"
INVENTORY = EVIDENCE / "inventory.v1.json"
DESIGN = EVIDENCE / "design.v1.json"
README = EVIDENCE / "README.md"
STATUS = ROOT / "docs/roadmap/STATUS.md"
PLAN = ROOT / "docs/roadmap/IMPLEMENTATION_PLAN.md"
GATEWAY_MAIN = ROOT / "services/gateway/app/main.py"
SESSION_CONTAINMENT = ROOT / "services/gateway/app/session_containment.py"
ADR_DIR = ROOT / "docs/architecture/adr"
CURRENT_BUILD_REVISION = "dsh-0.1.2rc1-post-u8.191"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class DesignEvidenceTests(unittest.TestCase):
    def test_slice_declares_design_only_and_no_runtime_implementation(self):
        inventory, design = _load(INVENTORY), _load(DESIGN)
        self.assertEqual(inventory["schema_version"], "byq-v090-step-safety-inventory.v1")
        self.assertEqual(design["schema_version"], "byq-v090-step-safety-design.v1")
        for value in (inventory, design):
            self.assertEqual(value["delivered_scope"], "inventory+minimal-design")
            self.assertFalse(value["runtime_implementation"])

    def test_inventory_covers_every_required_authority_surface(self):
        inventory = _load(INVENTORY)
        for section in ("step_safety", "budget_binding", "safe_rescheduling"):
            self.assertTrue(inventory[section], section)
            for entry in inventory[section]:
                self.assertTrue(entry["interface"] and entry["authoritative"] and entry["missing"], entry)
        self.assertEqual(len(inventory["missing_authoritative_pieces"]), 3)
        # Client step flags and MCP display strings are never authority.
        self.assertTrue(inventory["non_authoritative_display_only"])
        self.assertIn("client-supplied step flags", " ".join(inventory["non_authoritative_display_only"]))

    def test_design_maps_contract_budget_safety_and_failure_semantics(self):
        design = _load(DESIGN)
        self.assertIn("session_failure_containment", design["contract_mapping"]["keep_closed"])
        self.assertIn("domain_call_admission", design["contract_mapping"]["step_safety_registry"])
        self.assertIn("continuation_budget", design["authoritative_source"]["budget"])
        self.assertIn("receipt", design["authoritative_source"]["receipt"])
        self.assertIn("event_key", design["budget_binding"]["task_bound_run"])
        for key in ("bounded", "idempotent_exactly_one", "receipt_first", "auditable", "fenced"):
            self.assertIn(key, design["safe_rescheduling"])
        self.assertIn("paused", design["failure_semantics"]["unknown_or_unavailable_authority"])
        self.assertGreaterEqual(len(design["next_slice_acceptance_criteria"]), 6)

    def test_no_new_adr_is_required_or_proposed(self):
        design = _load(DESIGN)
        self.assertIs(design["adr_decision"]["required"], False)
        self.assertIs(design["adr_decision"]["proposed"], False)
        self.assertIn("No new ADR is required", README.read_text(encoding="utf-8"))
        # If a step-safety ADR is ever added it must be Proposed, never Accepted.
        for path in ADR_DIR.glob("ADR-*step-safety*.md"):
            text = path.read_text(encoding="utf-8")
            self.assertIn("Status: Proposed", text, str(path))
            self.assertNotIn("Status: Accepted", text, str(path))

    def test_status_and_plan_keep_gate_and_boundaries_unchanged(self):
        status, plan = STATUS.read_text(encoding="utf-8"), PLAN.read_text(encoding="utf-8")
        for marker in (
            "<!-- byq:v090-step-safety-design=inventory-design-delivered -->",
            "<!-- byq:session-failure-containment=in-progress-blocked-internal -->",
            "<!-- byq:v090-step5-b1-subagent-child-crash=blocked-external -->",
            "<!-- byq:v090-step5-b2-adapter-restart=blocked-external -->",
        ):
            self.assertIn(marker, status)
        self.assertIn("IN_PROGRESS / BLOCKED_INTERNAL", status)
        self.assertIn("R3_RESUME = NO", status)
        self.assertNotIn("<!-- byq:session-failure-containment=complete -->", status)
        self.assertNotIn("<!-- byq:v090-step-safety-design=complete -->", status)
        self.assertIn("inventory + minimal design", plan)
        self.assertIn("IN_PROGRESS / BLOCKED_INTERNAL", plan)

    def test_no_superseding_assessment_is_created_or_claimed(self):
        status = STATUS.read_text(encoding="utf-8")
        plan = PLAN.read_text(encoding="utf-8")
        for text in (status, plan, README.read_text(encoding="utf-8")):
            self.assertNotIn("superseding_assessment_passed", text)
            self.assertNotIn("superseding assessment 已通过", text)
        self.assertNotIn("byq:v090-d15-superseding=passed", status)
        for path in EVIDENCE.rglob("*"):
            if path.is_file():
                self.assertNotIn("superseding_assessment_passed",
                                 path.read_text(encoding="utf-8", errors="ignore"), str(path))

    def test_historical_d15_verdict_and_production_selector_unchanged(self):
        verdict = _load(ROOT / "docs/evidence/d15/d15-g/verdict.v1.json")
        self.assertEqual(verdict["verdict"], "NO_GO")
        deployment = _load(ROOT / "config/dsh/deployment.json")
        self.assertEqual(deployment["default_release"], "dsh-0.1.2rc1")

    def test_build_revision_is_the_next_unused_id(self):
        from scripts.dsh import build_revision as builds
        self.assertEqual(builds.selected_build_id("dsh-0.1.2rc1"), CURRENT_BUILD_REVISION)
        self.assertTrue((ROOT / "config/dsh/builds" / f"{CURRENT_BUILD_REVISION}.json").is_file())
        self.assertTrue((ROOT / "config/dsh/builds/dsh-0.1.2rc1-post-u8.190.json").is_file())


class NoRuntimeImplementationTests(unittest.TestCase):
    def test_recovery_endpoint_still_never_submits(self):
        source = GATEWAY_MAIN.read_text(encoding="utf-8")
        start = source.index("def get_recovery_classification(")
        end = source.index("@app.", start)
        body = source[start:end]
        self.assertNotIn("_adapter_post", body)
        self.assertNotIn("/prompt", body)
        self.assertNotIn("_runtime_recovery_payload", body)
        self.assertIn('"submitted": False', body)

    def test_budget_binding_is_not_implemented_yet(self):
        # The design is not implemented: an arbitrary turn still has no
        # authoritative budget binding, so the gateway stays paused.
        source = GATEWAY_MAIN.read_text(encoding="utf-8")
        self.assertIn('result["budget_available"] = None', source)

    def test_step_safety_is_not_declared_from_client_or_display(self):
        source = SESSION_CONTAINMENT.read_text(encoding="utf-8")
        self.assertIn("step_declared_idempotent=False", source)
        self.assertIn("step_result_verifiable=False", source)
        self.assertNotIn("client", source.lower())
        # No second persistence/attempt authority was introduced by this slice.
        for path in (ROOT / "services/gateway/app").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("byq-recovery-attempts", text, str(path))
            self.assertNotIn("RecoveryAttemptStore", text, str(path))


if __name__ == "__main__":
    unittest.main()
