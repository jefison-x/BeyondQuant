"""Governance for the design-only step-safety + budget binding + rescheduling slice.

Runs under ``unittest`` (architecture lane). Asserts the slice is design/evidence
only, that no runtime implementation or ADR acceptance is claimed, that the full
ADR-0084 business-recovery gate stays ``IN_PROGRESS / BLOCKED_INTERNAL``, that no
D15 superseding assessment is created while B1/B2 stay ``BLOCKED_EXTERNAL``,
D15-G stays ``NO_GO`` and ``R3_RESUME = NO``, and that the design statements are
consistent with the REAL committed code facts (rectification P1-A..P1-K).
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
ADAPTER_RUNTIME = ROOT / "services/runtime-adapter/app/runtime.py"
ADAPTER_BUDGET = ROOT / "services/runtime-adapter/app/continuation_budget.py"
ADR_DIR = ROOT / "docs/architecture/adr"
CURRENT_BUILD_REVISION = "dsh-0.1.2rc1-post-u8.193"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def session_global_closure(sequences: list[int], target: list[int]) -> bool:
    """Documented closure rule: global 1..N contiguous; target strictly increasing.

    The target subset is NOT required to start at 1 because the adapter call
    sequence accumulates across roots in one session.
    """

    if not sequences or sorted(sequences) != list(range(1, len(sequences) + 1)):
        return False
    if target != sorted(target):
        return False
    if len(set(target)) != len(target):
        return False
    return all(sequence in sequences for sequence in target)


class DesignEvidenceTests(unittest.TestCase):
    def test_slice_declares_design_only_and_no_runtime_implementation(self):
        inventory, design = _load(INVENTORY), _load(DESIGN)
        self.assertEqual(inventory["schema_version"], "byq-v090-step-safety-inventory.v1")
        self.assertEqual(design["schema_version"], "byq-v090-step-safety-design.v1")
        self.assertEqual(design["revision"], "rectified-p1-f-k")
        self.assertEqual(inventory["revision"], "rectified-p1-f-k")
        for value in (inventory, design):
            self.assertEqual(value["delivered_scope"], "inventory+minimal-design")
            self.assertFalse(value["runtime_implementation"])

    def test_identity_separation_is_backend_minted(self):
        identity = _load(DESIGN)["identity_separation"]
        self.assertIn("reservation_id", identity["budget_authority_identity"])
        self.assertIn("recovery_attempt_key", identity["recovery_submission_identity"])
        self.assertIn("recovery_attempt_key", identity["prompt_idempotency_key"])
        self.assertIn("task-continuation-reservation.v1", identity["trusted_carrier_extension"])
        self.assertEqual(identity["issuer"], "Backend only")
        self.assertIs(identity["client_or_model_must_not_mint"], True)
        self.assertIn("epoch/generation", identity["adapter_validation"])

    def test_per_attempt_receipt_is_closed_and_bounded(self):
        receipt = _load(DESIGN)["per_attempt_receipt"]
        self.assertIn("attempt_key", receipt["prompt_receipt"])
        self.assertIn("attempt_key.json", receipt["settlement_receipt"])
        self.assertIn("settlement_sha256", receipt["settlement_receipt"])
        self.assertIn("reserved", receipt["closed_states"])
        self.assertIn("outcome_unknown", receipt["closed_states"])
        self.assertEqual(receipt["unknown_attempt_charge"], "paused")
        self.assertIn("R.token_limit", receipt["cumulative_bound"])
        self.assertIs(receipt["never_overwrite_old_receipts"], True)
        self.assertIs(receipt["no_new_authority_store"], True)

    def test_trigger_key_dedups_before_ordinal_allocation(self):
        trigger = _load(DESIGN)["recovery_trigger"]
        self.assertIn("recovery-trigger.v1", trigger["trigger_key"])
        for field in ("reservation_id", "interrupted_run_id", "interrupted_generation",
                      "containment_attempt", "executor_epoch"):
            self.assertIn(field, trigger["binds"])
        self.assertIn("SAME trigger_key returns the existing attempt", trigger["dedup_rule"])
        self.assertIn("NEW authoritative fenced loss identity", trigger["dedup_rule"])
        self.assertEqual(trigger["cap"], 3)
        self.assertIs(trigger["recomputable_and_verifiable"], True)

    def test_session_global_closure_accepts_second_root_first_sequence_gt_one(self):
        source = _load(DESIGN)["authoritative_source"]
        self.assertIn("session-global", source["sequence_nature"])
        self.assertIn("does NOT need to start at 1", source["closure_rule"])
        self.assertIs(source["second_root_first_sequence_gt_1_legal"], True)
        # Positive: a second root whose first observed sequence is 3 is legal.
        self.assertTrue(session_global_closure([1, 2, 3, 4], [3, 4]))
        # Negative: a session-global gap is not closure.
        self.assertFalse(session_global_closure([1, 2, 4], [4]))
        # Negative: a per-root out-of-order subset is not closure.
        self.assertFalse(session_global_closure([1, 2, 3, 4], [4, 3]))

    def test_budget_formula_does_not_double_deduct(self):
        budget = _load(DESIGN)["budget_binding"]
        example = budget["numeric_example"]
        self.assertEqual(example["permission_token_limit"], 100)
        self.assertEqual(example["other_settled"], 30)
        self.assertEqual(example["r_token_limit"], 60)
        self.assertEqual(example["r_cumulative_exact_charge"], 20)
        self.assertEqual(example["r_available"], 40)
        self.assertEqual(example["old_wrong_value"], 10)
        formula = budget["formula"]
        self.assertIn("other_settled + other_unresolved + R.token_limit", formula["step_1_grant_invariant"])
        self.assertIn("R.token_limit - cum_exact", formula["step_2_r_headroom"])
        self.assertIn("do NOT deduct", formula["step_3_no_double_deduction"])
        self.assertIn("max_turns", formula["step_4_authority"])

    def test_recovery_admission_envelope_constrains_future_writes(self):
        envelope = _load(DESIGN)["recovery_admission_envelope"]
        allowed = " ".join(envelope["allowed"])
        self.assertIn("read-only", allowed)
        self.assertIn("request_sha256", allowed)
        self.assertIn("agent_domain_call_evidence", envelope["enforcement"])
        self.assertIn("may_produce_new_key", _load(DESIGN)["next_slice_acceptance_criteria"][0])
        self.assertIs(envelope["model_must_not_choose"], True)
        self.assertEqual(envelope["undeterminable_work"], "not eligible")

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
        adapter = next(entry for entry in inventory["budget_binding"]
                       if "continuation_budget.py" in entry["interface"])
        self.assertIn("reservation_id", adapter["real_mechanism"]["settlement_path"])
        self.assertIn("original continuation settlement cannot change",
                      adapter["real_mechanism"]["immutable_settlement_message"])
        submit = next(entry for entry in inventory["budget_binding"]
                      if "submit_prompt" in entry["interface"])
        self.assertIn("durable run_id", submit["real_mechanism"]["old_run_dedup"])
        self.assertIn("budget['reservation_id']", submit["real_mechanism"]["forces_reservation_key"])

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
        # The status narrative carries the rectified semantics.
        self.assertIn("原行 rearm", status)
        self.assertIn("身份分离", status)
        self.assertIn("FOR UPDATE", status)
        self.assertIn("session-global cursor", status)
        self.assertIn("40", status)

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

    def test_adapter_returns_old_run_and_forces_reservation_key(self):
        source = ADAPTER_RUNTIME.read_text(encoding="utf-8")
        self.assertIn('if durable["state"] == "accepted":', source)
        self.assertIn('return durable["run_id"]', source)
        self.assertIn("if idempotency_key != budget['reservation_id']:", source)
        self.assertIn("continuation requires its original reservation key", source)

    def test_settlement_is_one_immutable_slot_per_reservation(self):
        source = ADAPTER_BUDGET.read_text(encoding="utf-8")
        self.assertIn("receipt['reservation_id'] + '.json'", source)
        self.assertIn("original continuation settlement cannot change", source)

    def test_prompt_receipt_key_cannot_be_replaced(self):
        source = LIFECYCLE.read_text(encoding="utf-8")
        self.assertIn("prompt receipt cannot be replaced", source)
        self.assertIn('state["prompts"][key]', source)

    def test_call_sequence_is_session_global(self):
        source = LIFECYCLE.read_text(encoding="utf-8")
        self.assertIn('evidence["sequence"] != len(self.state["calls"]) + 1', source)
        call_evidence = CALL_EVIDENCE.read_text(encoding="utf-8")
        self.assertIn("PRIMARY KEY (owner_principal, workspace_id, session_id, sequence)", call_evidence)

    def test_previous_unconfirmed_rejection_and_outcome_unknown(self):
        source = CONTINUATION.read_text(encoding="utf-8")
        self.assertIn("previous continuation result is unconfirmed", source)
        self.assertIn("row['status'] = 'outcome_unknown'", source)
        self.assertIn("FOR UPDATE", source)

    def test_continuation_path_has_no_advisory_lock(self):
        self.assertNotIn("pg_advisory_xact_lock", CONTINUATION.read_text(encoding="utf-8"))
        self.assertIn("pg_advisory_xact_lock", RECEIPTS.read_text(encoding="utf-8"))

    def test_exact_per_call_receipt_and_unknown_outcome(self):
        source = CALL_EVIDENCE.read_text(encoding="utf-8")
        self.assertIn("UNIQUE(root_run_id,task_id,action,idempotency_key)", source)
        self.assertIn("prior_call_outcome_unknown", source)


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
        self.assertTrue((ROOT / "config/dsh/builds/dsh-0.1.2rc1-post-u8.192.json").is_file())


if __name__ == "__main__":
    unittest.main()
