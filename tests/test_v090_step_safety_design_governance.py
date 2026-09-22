"""Governance for the design-only step-safety + budget binding + rescheduling slice.

Runs under ``unittest`` (architecture lane). Asserts the slice is design/evidence
only, that no runtime implementation or ADR acceptance is claimed, that the full
ADR-0084 business-recovery gate stays ``IN_PROGRESS / BLOCKED_INTERNAL``, that no
D15 superseding assessment is created while B1/B2 stay ``BLOCKED_EXTERNAL``,
D15-G stays ``NO_GO`` and ``R3_RESUME = NO``, and that the design statements are
consistent with the REAL committed code facts (rectification P1-A..P1-Q).
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
ADAPTER_CONTAINMENT = ROOT / "services/runtime-adapter/app/containment.py"
CONTAINMENT_TEST = ROOT / "services/runtime-adapter/tests/test_session_containment.py"
ADR_DIR = ROOT / "docs/architecture/adr"
CURRENT_BUILD_REVISION = "dsh-0.1.5rc1-post-u8.201"

CARRIER_FIELDS = {
    "attempt_key", "ordinal", "trigger_key", "interrupted_run_id",
    "interrupted_generation", "containment_attempt", "interrupted_executor_epoch",
    "snapshot_tail_sequence", "snapshot_digest",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def session_global_closure(sequences: list[int], target: list[int]) -> bool:
    """Global 1..N contiguous; target strictly increasing, not required to start at 1."""

    if not sequences or sorted(sequences) != list(range(1, len(sequences) + 1)):
        return False
    if target != sorted(target) or len(set(target)) != len(target):
        return False
    return all(sequence in sequences for sequence in target)


def snapshot_unchanged(expected_tail: int, expected_digest: str,
                       actual_tail: int, actual_digest: str) -> bool:
    """The check-and-start re-verification: tail and digest must be identical."""

    return expected_tail == actual_tail and expected_digest == actual_digest


def stable_snapshot_closure(more: bool, idle: bool, reconciled: bool,
                            sequences: list[int], target: list[int]) -> bool:
    """Stable-snapshot closure: more=false AND idle=true AND item-by-item reconciled."""

    if more or not idle or not reconciled:
        return False
    return session_global_closure(sequences, target)


class DesignEvidenceTests(unittest.TestCase):
    def test_slice_declares_design_only_and_no_runtime_implementation(self):
        inventory, design = _load(INVENTORY), _load(DESIGN)
        self.assertEqual(inventory["schema_version"], "byq-v090-step-safety-inventory.v1")
        self.assertEqual(design["schema_version"], "byq-v090-step-safety-design.v1")
        self.assertEqual(design["revision"], "rectified-p1-o-q")
        self.assertEqual(inventory["revision"], "rectified-p1-o-q")
        for value in (inventory, design):
            self.assertEqual(value["delivered_scope"], "inventory+minimal-design")
            self.assertFalse(value["runtime_implementation"])

    def test_two_epochs_are_separated(self):
        identity = _load(DESIGN)["identity_separation"]
        epochs = identity["two_epochs"]
        self.assertIs(epochs["interrupted_executor_epoch"]["must_equal_live_epoch"], False)
        self.assertIs(epochs["target_executor_epoch_and_generation"]["must_equal_live_epoch"], True)
        self.assertIn("containment", epochs["interrupted_executor_epoch"]["source"])
        self.assertIn("LIVE", epochs["target_executor_epoch_and_generation"]["source"])
        self.assertIn("1 -> 2", identity["legal_positive"])

    def test_identity_separation_carries_closed_recovery_attempt_fields(self):
        identity = _load(DESIGN)["identity_separation"]
        carrier = identity["trusted_carrier_extension"]
        self.assertEqual(set(carrier["closed_fields"]), CARRIER_FIELDS)
        self.assertEqual(carrier["issuer"], "Backend only")
        self.assertIs(carrier["client_or_model_must_not_mint"], True)
        self.assertIs(carrier["carries_expected_target_executor_epoch"], False)

    def test_adapter_recomputes_and_verifies_and_rejects(self):
        identity = _load(DESIGN)["identity_separation"]
        steps = " ".join(identity["adapter_recompute_and_verify"])
        self.assertIn("recompute trigger_key'", steps)
        self.assertIn("recompute attempt_key'", steps)
        self.assertIn("LIVE epoch", steps)
        self.assertIn("RuntimeGeneration", steps)
        self.assertIn("target_executor_epoch", steps)
        self.assertIn("target_executor_epoch", identity["target_receipt_binding"])
        rejections = " ".join(identity["rejections_fail_closed"])
        for expected in ("missing carrier field", "tampered or mismatched trigger_key",
                         "tampered or mismatched attempt_key", "stale target receipt",
                         "treating interrupted_executor_epoch as the live epoch",
                         "target epoch/generation mismatch"):
            self.assertIn(expected, rejections)
        self.assertIs(identity["new_attempt_key_yields_new_run"], True)

    def test_trigger_key_binds_interrupted_epoch_not_live(self):
        trigger = _load(DESIGN)["recovery_trigger"]
        self.assertIn("interrupted_executor_epoch", trigger["trigger_key"])
        self.assertIn("interrupted_executor_epoch", trigger["binds"])
        self.assertIs(trigger["epoch_bound_is_interrupted_not_live"], True)
        self.assertEqual(trigger["cap"], 3)

    def test_carrier_carries_snapshot_identity_and_canonical_digest(self):
        design = _load(DESIGN)
        carrier = design["identity_separation"]["trusted_carrier_extension"]
        self.assertIn("snapshot_tail_sequence", carrier["closed_fields"])
        self.assertIn("snapshot_digest", carrier["closed_fields"])
        source = design["authoritative_source"]
        canonical = source["snapshot_digest_canonical_input"]
        for token in ("session_id", "trace_id", "tail_sequence", "calls",
                      "request_sha256", "input_sha256", "ordered"):
            self.assertIn(token, canonical)
        self.assertIn("SAME snapshot identity", source["snapshot_identity_bound_where"])
        # Aggregate/ordinal semantics (P1-R).
        self.assertIn("does NOT increase the ordinal", source["same_snapshot_retry"])
        self.assertIn("MUST NOT silently rewrite", source["snapshot_change_semantics"])
        self.assertIn("MUST NOT consume another ordinal", source["snapshot_change_semantics"])
        aggregate = design["per_attempt_receipt"]["final_authoritative_aggregate"]
        self.assertIn("SAME snapshot identity", aggregate)

    def test_snapshot_anchoring_and_atomic_check_and_start(self):
        source = _load(DESIGN)["authoritative_source"]
        self.assertIs(source["no_cross_request_lock"], True)
        self.assertIn("snapshot_tail_sequence", source["snapshot_anchoring"])
        self.assertIn("snapshot_digest", source["snapshot_anchoring"])
        self.assertIn("validate", source["atomic_check_and_start"].lower())
        self.assertIn("recomputes the CURRENT snapshot", source["atomic_check_and_start"])
        self.assertIn("record.lock", source["atomic_check_and_start"])
        self.assertIn("idle == true", source["atomic_check_and_start"])
        self.assertIn("TOCTOU", source["atomic_check_and_start"])
        self.assertIn("does NOT increase the ordinal", source["same_snapshot_retry"])
        steps = " ".join(_load(DESIGN)["identity_separation"]["adapter_recompute_and_verify"])
        self.assertIn("canonical snapshot digest", steps)
        self.assertIn("re-verify the CURRENT snapshot tail/digest", steps)
        # Positive: closed stable snapshot with a second root first sequence > 1.
        self.assertTrue(stable_snapshot_closure(False, True, True, [1, 2, 3, 4], [3, 4]))
        # Negatives: not idle, pagination unfinished, reconciliation failed.
        self.assertFalse(stable_snapshot_closure(False, False, True, [1, 2, 3], [3]))
        self.assertFalse(stable_snapshot_closure(True, True, True, [1, 2, 3], [3]))
        self.assertFalse(stable_snapshot_closure(False, True, False, [1, 2, 3], [3]))
        # Negative: tail/digest tamper between evidence review and re-dispatch.
        self.assertFalse(snapshot_unchanged(4, "d" * 64, 5, "d" * 64))
        self.assertFalse(snapshot_unchanged(4, "d" * 64, 4, "e" * 64))
        self.assertTrue(snapshot_unchanged(4, "d" * 64, 4, "d" * 64))
        # Negative: session-global gap / out-of-order per-root subset.
        self.assertFalse(session_global_closure([1, 2, 4], [4]))
        self.assertFalse(session_global_closure([1, 2, 3, 4], [4, 3]))

    def test_budget_tri_state_requires_model_floor_for_any_new_run(self):
        budget = _load(DESIGN)["budget_binding"]
        self.assertIs(budget["unknown_cost_is_zero"], False)
        self.assertIs(budget["unknown_cost_refunded"], False)
        formula = budget["formula"]
        self.assertIs(formula["model_call_floor_required_for_any_new_recovery_run"], True)
        self.assertIn("NONE", formula["read_only_floor_exemption"])
        self.assertIn("controller", formula["controller_only_observation_below_floor"])
        self.assertIn("MUST NOT be called an eligible reschedule",
                      formula["controller_only_observation_below_floor"])
        table = {row["condition"]: row["decision"] for row in budget["tri_state_decision_table"]}
        self.assertEqual(table["R_available KNOWN and < model_call_floor (any new recovery model run)"], "blocked")
        self.assertEqual(table["R_available is None (any attempt charge unknown) or any input unreadable"], "None/paused")
        self.assertEqual(table["otherwise (known R_available >= model_call_floor)"], "eligible")
        self.assertNotIn("read-only", table["otherwise (known R_available >= model_call_floor)"])

    def test_budget_formula_does_not_double_deduct(self):
        example = _load(DESIGN)["budget_binding"]["numeric_example"]
        self.assertEqual(example["permission_token_limit"], 100)
        self.assertEqual(example["other_settled"], 30)
        self.assertEqual(example["r_token_limit"], 60)
        self.assertEqual(example["r_cumulative_exact_charge"], 20)
        self.assertEqual(example["r_available"], 40)
        self.assertEqual(example["old_wrong_value"], 10)

    def test_recovery_admission_envelope_read_only_does_not_exempt_budget(self):
        envelope = _load(DESIGN)["recovery_admission_envelope"]
        self.assertIn("side effects only", envelope["read_only_constrains"])
        self.assertIs(envelope["read_only_exempts_token_budget"], False)
        self.assertIs(envelope["may_produce_new_key_conservative_only"], True)
        self.assertIs(envelope["may_produce_new_key_true_always_ineligible"], True)
        self.assertIn("Proposed ADR", envelope["new_key_authorization"])
        self.assertIs(envelope["model_must_not_choose"], True)
        self.assertEqual(envelope["undeterminable_work"], "not eligible")

    def test_inventory_budget_mechanism_matches_real_code(self):
        inventory = _load(INVENTORY)
        budget = next(entry for entry in inventory["budget_binding"]
                      if "research_continuation" in entry["interface"])
        mechanism = budget["real_mechanism"]
        self.assertIn("FOR UPDATE", mechanism["row_lock"])
        self.assertIs(mechanism["per_event_key_unique_constraint"], False)
        adapter = next(entry for entry in inventory["budget_binding"]
                       if "continuation_budget.py" in entry["interface"])
        self.assertIn("reservation_id", adapter["real_mechanism"]["settlement_path"])
        step = next(entry for entry in inventory["step_safety"]
                    if "agent_domain_call_evidence" in entry["interface"])
        self.assertIn("idle", step["real_mechanism"]["adapter_page_shape"])
        self.assertIn("no_cross_request_lock", step["real_mechanism"])

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
        self.assertIn("interrupted_executor_epoch", status)
        self.assertIn("target_executor_epoch", status)
        self.assertIn("snapshot", status)
        self.assertIn("model_call_floor", status)
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
        self.assertEqual(deployment["default_release"], "dsh-0.1.5rc1")
        self.assertIn("dsh-0.1.2rc1", deployment["candidate_releases"])


class RealCodeFactTests(unittest.TestCase):
    """The design's claims must track the actual committed mechanisms."""

    def test_containment_records_failing_epoch_and_takeover_fences_old(self):
        containment = ADAPTER_CONTAINMENT.read_text(encoding="utf-8")
        self.assertIn("executor_epoch", containment)
        self.assertIn("assert_write_allowed_locked", containment)
        test = CONTAINMENT_TEST.read_text(encoding="utf-8")
        self.assertIn("def test_containment_write_fails_closed_on_stale_executor_epoch", test)
        self.assertIn("takeover", test)

    def test_no_cross_request_lock_is_claimed(self):
        source = ADAPTER_RUNTIME.read_text(encoding="utf-8")
        self.assertIn("with record.lock:", source)
        readme = README.read_text(encoding="utf-8")
        self.assertIn("does **NOT** assume", readme)
        self.assertIs(_load(DESIGN)["authoritative_source"]["no_cross_request_lock"], True)

    def test_adapter_returns_old_run_and_forces_reservation_key(self):
        source = ADAPTER_RUNTIME.read_text(encoding="utf-8")
        self.assertIn('if durable["state"] == "accepted":', source)
        self.assertIn('return durable["run_id"]', source)
        self.assertIn("if idempotency_key != budget['reservation_id']:", source)
        self.assertIn("continuation requires its original reservation key", source)

    def test_adapter_page_exposes_more_and_idle(self):
        source = ADAPTER_RUNTIME.read_text(encoding="utf-8")
        self.assertIn('"more": len(state["calls"]) > after_sequence + len(rows)', source)
        self.assertIn('"idle": state["open_root"] is None', source)

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
        self.assertEqual(builds.selected_build_id("dsh-0.1.5rc1"), CURRENT_BUILD_REVISION)
        self.assertTrue((ROOT / "config/dsh/builds" / f"{CURRENT_BUILD_REVISION}.json").is_file())
        self.assertTrue((ROOT / "config/dsh/builds/dsh-0.1.2rc1-post-u8.195.json").is_file())


if __name__ == "__main__":
    unittest.main()
