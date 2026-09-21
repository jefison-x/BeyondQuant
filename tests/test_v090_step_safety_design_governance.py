"""Governance for the design-only step-safety + budget binding + rescheduling slice.

Runs under ``unittest`` (architecture lane). Asserts the slice is design/evidence
only, that no runtime implementation or ADR acceptance is claimed, that the full
ADR-0084 business-recovery gate stays ``IN_PROGRESS / BLOCKED_INTERNAL``, that no
D15 superseding assessment is created while B1/B2 stay ``BLOCKED_EXTERNAL``,
D15-G stays ``NO_GO`` and ``R3_RESUME = NO``, and that the design statements are
consistent with the REAL committed code facts (rectification P1-A..P1-E).
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
CONTINUATION = ROOT / "services/backend/app/research_continuation.py"
RECEIPTS = ROOT / "services/backend/app/research_receipts.py"
CALL_EVIDENCE = ROOT / "services/backend/app/domain_call_admission.py"
LIFECYCLE = ROOT / "services/runtime-adapter/app/lifecycle_journal.py"
ADR_DIR = ROOT / "docs/architecture/adr"
CURRENT_BUILD_REVISION = "dsh-0.1.2rc1-post-u8.192"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class DesignEvidenceTests(unittest.TestCase):
    def test_slice_declares_design_only_and_no_runtime_implementation(self):
        inventory, design = _load(INVENTORY), _load(DESIGN)
        self.assertEqual(inventory["schema_version"], "byq-v090-step-safety-inventory.v1")
        self.assertEqual(design["schema_version"], "byq-v090-step-safety-design.v1")
        self.assertEqual(design["revision"], "rectified-p1-a-e")
        self.assertEqual(inventory["revision"], "rectified-p1-a-e")
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
        self.assertTrue(inventory["non_authoritative_display_only"])
        self.assertIn("client-supplied step flags", " ".join(inventory["non_authoritative_display_only"]))

    def test_inventory_budget_mechanism_matches_real_code(self):
        inventory = _load(INVENTORY)
        budget = next(entry for entry in inventory["budget_binding"]
                      if "research_continuation" in entry["interface"])
        mechanism = budget["real_mechanism"]
        self.assertIn("FOR UPDATE", mechanism["row_lock"])
        self.assertIs(mechanism["per_event_key_unique_constraint"], False)
        self.assertIs(mechanism["pg_advisory_xact_lock_on_this_path"], False)
        self.assertIn("research_continuation.py:309-310", mechanism["previous_unconfirmed_rejection"])
        self.assertIn("research_continuation.py:563-567", mechanism["dispatch_sets_outcome_unknown"])

    def test_design_forbids_new_reservation_and_uses_original_row_rearm(self):
        design = _load(DESIGN)
        budget = design["budget_binding"]
        self.assertIs(budget["original_row_rearm"], True)
        self.assertIs(budget["new_reservation_created"], False)
        self.assertIn("withdrawn", budget["withdrawn_semantics"])
        self.assertIs(budget["unknown_cost_is_zero"], False)
        self.assertIs(budget["unknown_cost_refunded"], False)
        self.assertIs(budget["db_uniqueness_required"], False)
        self.assertIn("FOR UPDATE", budget["real_concurrency_mechanism"])
        formula = budget["formula"]
        for key in ("committed", "unresolved", "permission_remaining", "known_charge",
                    "reservation_remaining", "available", "budget_available"):
            self.assertIn(key, formula)
        self.assertIn("token_limit", formula["unresolved"])
        self.assertEqual(len(budget["state_table"]), 6)
        statuses = {row["reservation_status"] for row in budget["state_table"]}
        self.assertIn("accepted/outcome_unknown", statuses)

    def test_design_attempt_ordinal_and_transport_retry_are_separate(self):
        safe = _load(DESIGN)["safe_rescheduling"]
        self.assertEqual(safe["recovery_attempt_max"], 3)
        self.assertEqual(safe["transport_dispatch_attempt_cap"], 8)
        self.assertIs(safe["dispatch_attempts_are_transport_retry"], True)
        self.assertIn("recovery-v1:", safe["attempt_ordinal_identity"])
        self.assertIn("k", safe["attempt_ordinal_identity"])
        self.assertIn("FOR UPDATE", safe["exactly_one_per_ordinal"])

    def test_design_call_evidence_sequence_closure_and_eligible_condition(self):
        design = _load(DESIGN)
        source = design["authoritative_source"]
        self.assertIn("ORDER BY sequence", source["occurred_step_set"])
        self.assertIn("contiguous", source["sequence_closure"])
        self.assertIn("zero_evidence_dispatched_run", source)
        self.assertEqual(source["zero_evidence_dispatched_run"], "paused")
        self.assertEqual(source["no_task_reservation_ordinary_turn"], "paused")
        for forbidden in ("prompt text", "mcp_display_strings", "client_fields", "last_call_heuristic"):
            self.assertIn(forbidden, source["forbidden_inference"])
        reconcile = design["call_evidence_reconciliation"]
        self.assertIn("eligible_condition", reconcile)
        self.assertIn("ALL occurred side effects settled", reconcile["eligible_condition"])
        self.assertIn("sequence_gap_or_conflict", reconcile)

    def test_no_new_adr_is_required_or_proposed(self):
        design = _load(DESIGN)
        self.assertIs(design["adr_decision"]["required"], False)
        self.assertIs(design["adr_decision"]["proposed"], False)
        self.assertIn("no new adr is required", README.read_text(encoding="utf-8").lower())
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
        # The status narrative must carry the rectified semantics, not the old ones.
        self.assertIn("原行内 rearm", status)
        self.assertIn("FOR UPDATE", status)

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


class RealCodeFactTests(unittest.TestCase):
    """The design's claims must track the actual committed mechanisms."""

    def test_previous_unconfirmed_rejection_and_outcome_unknown(self):
        source = CONTINUATION.read_text(encoding="utf-8")
        self.assertIn("previous continuation result is unconfirmed", source)
        self.assertIn("row['status'] = 'outcome_unknown'", source)
        self.assertIn("SELECT * FROM research_tasks", source)
        self.assertIn("FOR UPDATE", source)

    def test_continuation_path_has_no_advisory_lock(self):
        # The advisory lock belongs to the receipt-watch path, not the budget path.
        self.assertNotIn("pg_advisory_xact_lock", CONTINUATION.read_text(encoding="utf-8"))
        self.assertIn("pg_advisory_xact_lock", RECEIPTS.read_text(encoding="utf-8"))

    def test_call_evidence_pk_and_exact_per_call_receipt(self):
        source = CALL_EVIDENCE.read_text(encoding="utf-8")
        self.assertIn("PRIMARY KEY (owner_principal, workspace_id, session_id, sequence)", source)
        self.assertIn("UNIQUE(root_run_id,task_id,action,idempotency_key)", source)
        self.assertIn("prior_call_outcome_unknown", source)

    def test_adapter_call_sequence_is_gap_free(self):
        source = LIFECYCLE.read_text(encoding="utf-8")
        self.assertIn('evidence["sequence"] != len(self.state["calls"]) + 1', source)


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
        source = GATEWAY_MAIN.read_text(encoding="utf-8")
        self.assertIn('result["budget_available"] = None', source)

    def test_step_safety_is_not_declared_from_client_or_display(self):
        source = SESSION_CONTAINMENT.read_text(encoding="utf-8")
        self.assertIn("step_declared_idempotent=False", source)
        self.assertIn("step_result_verifiable=False", source)
        self.assertNotIn("client", source.lower())
        for path in (ROOT / "services/gateway/app").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("byq-recovery-attempts", text, str(path))
            self.assertNotIn("RecoveryAttemptStore", text, str(path))

    def test_build_revision_is_the_next_unused_id(self):
        from scripts.dsh import build_revision as builds
        self.assertEqual(builds.selected_build_id("dsh-0.1.2rc1"), CURRENT_BUILD_REVISION)
        self.assertTrue((ROOT / "config/dsh/builds" / f"{CURRENT_BUILD_REVISION}.json").is_file())
        self.assertTrue((ROOT / "config/dsh/builds/dsh-0.1.2rc1-post-u8.191.json").is_file())


if __name__ == "__main__":
    unittest.main()
