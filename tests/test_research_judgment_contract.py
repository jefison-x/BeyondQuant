"""ADR-0085 P3 bounded research-judgment contract and adversarial negatives.

Pure, offline, no model/provider/database: it locks the closed stage-input and
proposal schemas, the server-side commit reducer, the two-call bound and the
first-check no-progress fence.
"""

from __future__ import annotations

import json
import unittest

from packages.contracts.research_execution_plan import new_plan, plan_at_stage
from packages.contracts.research_judgment import (
    DEFAULT_MAX_MODEL_CALLS_PER_STAGE,
    FORBIDDEN_PROPOSAL_FIELDS,
    JUDGMENT_STAGES,
    NO_DURABLE_PROGRESS,
    PROGRESS_EVIDENCE_KINDS,
    PROPOSAL_SCHEMA_VERSION,
    STAGE_ALLOWED_TOOLS,
    STAGE_INPUT_MAX_BYTES,
    STAGE_INPUT_SCHEMA_VERSION,
    STAGE_PROPOSAL_KINDS,
    action_requires_model,
    assert_model_turn_allowed,
    derive_proposal_commit,
    proposal_identity,
    proposal_request_hash,
    stage_model_call_limit,
    stage_model_call_outcome,
    stage_requires_model,
    validate_judgment_result_request,
    validate_progress_evidence,
    validate_proposal,
    validate_stage_admission_request,
    validate_stage_input,
    validate_stage_progress_request,
)

TASK = "task_" + "a" * 32
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64

DETERMINISTIC_STAGES = (
    "waiting_for_strategy_approval", "ready_to_create_backtest_task",
    "waiting_for_task_create_approval", "waiting_for_data",
    "waiting_for_task_execute_approval", "ready_to_execute_backtest_task",
    "waiting_for_backtest_job", "needs_attention", "completed",
)


def plan(stage: str, *, iteration: int = 1):
    return plan_at_stage(
        task_id=TASK, owner_principal="owner_1", workspace_id="ws_1",
        conversation_id="conv_1", task_version=5, stage=stage, iteration=iteration,
        idempotency_key=f"plan-{stage}-{iteration}")


def stage_input(stage: str, *, iteration: int = 1, **overrides):
    value = {
        "schema_version": STAGE_INPUT_SCHEMA_VERSION, "task_id": TASK,
        "plan_version": 1, "task_version": 5, "stage": stage, "iteration": iteration,
        "status": "active", "objective": "bounded objective", "stage_instruction": "judge",
        "proposal_kinds": sorted(STAGE_PROPOSAL_KINDS[stage]),
        "evidence": [{"kind": "backtest_result", "id": "artifact_" + "c" * 32,
                      "summary": "bounded metric summary"}],
        "allowed_tools": sorted(STAGE_ALLOWED_TOOLS[stage]), "model_call_limit": 2,
        "escalation_allowed": True,
    }
    value.update(overrides)
    return value


def proposal(stage: str, kind: str, *, iteration: int = 1, **overrides):
    value = {
        "schema_version": PROPOSAL_SCHEMA_VERSION, "task_id": TASK, "plan_version": 1,
        "task_version": 5, "stage": stage, "iteration": iteration, "proposal_kind": kind,
        "evidence_sufficient": True, "escalate": False, "summary": "bounded judgment",
    }
    value.update(overrides)
    return value


class JudgmentStageTests(unittest.TestCase):
    def test_only_genuine_research_stages_require_a_model(self) -> None:
        self.assertEqual(JUDGMENT_STAGES, frozenset({
            "strategy_draft", "backtest_analysis", "iteration_comparison", "final_selection"}))
        for stage in JUDGMENT_STAGES:
            self.assertTrue(stage_requires_model(stage))
            self.assertEqual(stage_model_call_limit(stage), DEFAULT_MAX_MODEL_CALLS_PER_STAGE)
            self.assertEqual(assert_model_turn_allowed(stage), stage)
        for stage in DETERMINISTIC_STAGES:
            self.assertFalse(stage_requires_model(stage))
            with self.assertRaises(ValueError):
                assert_model_turn_allowed(stage)
            with self.assertRaises(ValueError):
                stage_model_call_limit(stage)
        self.assertTrue(action_requires_model("analyse_backtest_result"))
        self.assertFalse(action_requires_model("execute_backtest_task"))


class StageInputTests(unittest.TestCase):
    def test_valid_stage_inputs_validate_and_are_bounded(self) -> None:
        for stage in JUDGMENT_STAGES:
            value = stage_input(stage, iteration=3 if stage in {"iteration_comparison", "final_selection"} else 1)
            self.assertEqual(validate_stage_input(value), value)
            self.assertLessEqual(
                len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()),
                STAGE_INPUT_MAX_BYTES)

    def test_deterministic_stage_input_is_refused(self) -> None:
        deterministic = stage_input("strategy_draft", status="waiting")
        deterministic["stage"] = "waiting_for_data"
        deterministic["proposal_kinds"] = ["wait_for_data"]
        deterministic["allowed_tools"] = ["byq_research_get"]
        with self.assertRaises(ValueError):
            validate_stage_input(deterministic)

    def test_unknown_and_raw_and_oversized_payloads_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            validate_stage_input(stage_input("backtest_analysis", surprise="x"))
        raw = stage_input("backtest_analysis")
        raw["evidence"] = [{"kind": "backtest_result", "id": "artifact_" + "c" * 32,
                            "summary": "x", "bars_frame": [1, 2, 3]}]
        with self.assertRaises(ValueError):
            validate_stage_input(raw)
        oversized = stage_input("backtest_analysis", objective="x" * (STAGE_INPUT_MAX_BYTES + 1))
        with self.assertRaises(ValueError):
            validate_stage_input(oversized)

    def test_tool_and_proposal_kind_sets_are_closed(self) -> None:
        with self.assertRaises(ValueError):
            validate_stage_input(stage_input("strategy_draft", allowed_tools=["byq_strategy_version_create"]))
        with self.assertRaises(ValueError):
            validate_stage_input(stage_input("backtest_analysis", proposal_kinds=["select_iteration"]))
        with self.assertRaises(ValueError):
            validate_stage_input(stage_input("strategy_draft", model_call_limit=8))


class ProposalTests(unittest.TestCase):
    def test_valid_proposals_validate_for_every_stage(self) -> None:
        for stage, kinds in STAGE_PROPOSAL_KINDS.items():
            for kind in kinds:
                extra = {}
                if kind == "select_iteration":
                    extra["selected_iteration"] = 3
                if kind == "propose_revision":
                    extra["revision_direction"] = "tighten_risk"
                if kind == "escalate":
                    extra["escalate"] = True
                value = proposal(stage, kind, iteration=3 if stage in {"iteration_comparison", "final_selection"} else 1, **extra)
                self.assertEqual(validate_proposal(value), value)

    def test_forged_routing_identity_and_idempotency_fields_are_refused(self) -> None:
        for field in ("next_action", "next_stage", "target_stage", "status", "target_status",
                      "route", "routing", "idempotency_key", "business_identity", "object_id",
                      "new_object_id", "plan", "conversation_id", "capabilities",
                      "allowed_capabilities", "approval", "proposal_id", "event_id", "resource_id"):
            self.assertIn(field, FORBIDDEN_PROPOSAL_FIELDS)
            forged = proposal("strategy_draft", "strategy_draft")
            forged[field] = "forged"
            with self.assertRaises(ValueError):
                validate_proposal(forged)
        with self.assertRaises(ValueError):
            validate_proposal(proposal("strategy_draft", "strategy_draft", unknown_field=1))

    def test_raw_and_oversized_proposals_are_refused(self) -> None:
        raw = proposal("backtest_analysis", "backtest_analysis", state={"date_index": [1, 2, 3]})
        with self.assertRaises(ValueError):
            validate_proposal(raw)
        huge = proposal("backtest_analysis", "backtest_analysis", rationale="x" * 5000)
        with self.assertRaises(ValueError):
            validate_proposal(huge)

    def test_kind_specific_requirements_are_enforced(self) -> None:
        with self.assertRaises(ValueError):
            validate_proposal(proposal("iteration_comparison", "select_iteration", iteration=3))
        with self.assertRaises(ValueError):
            validate_proposal(proposal("iteration_comparison", "propose_revision", iteration=2))
        with self.assertRaises(ValueError):
            validate_proposal(proposal("backtest_analysis", "escalate"))

    def test_identity_and_hash_are_deterministic_and_content_bound(self) -> None:
        first = proposal("backtest_analysis", "backtest_analysis")
        second = proposal("backtest_analysis", "backtest_analysis", summary="other")
        self.assertEqual(proposal_identity(first), proposal_identity(first))
        self.assertEqual(proposal_request_hash(first), proposal_request_hash(first))
        self.assertNotEqual(proposal_identity(first), proposal_identity(second))
        self.assertTrue(proposal_identity(first).startswith("research_proposal_"))


class CommitReducerTests(unittest.TestCase):
    def test_each_stage_commits_to_its_server_derived_target(self) -> None:
        strategy = plan("strategy_draft")
        decision = derive_proposal_commit(strategy, proposal("strategy_draft", "strategy_draft"))
        self.assertEqual((decision["outcome"], decision["next_stage"]),
                         ("advance", "waiting_for_strategy_approval"))

        analysis = plan("backtest_analysis")
        decision = derive_proposal_commit(analysis, proposal("backtest_analysis", "backtest_analysis"))
        self.assertEqual((decision["outcome"], decision["next_stage"]), ("advance", "iteration_comparison"))

        comparison = plan("iteration_comparison", iteration=3)
        decision = derive_proposal_commit(
            comparison, proposal("iteration_comparison", "select_iteration", iteration=3, selected_iteration=3))
        self.assertEqual((decision["outcome"], decision["next_stage"]), ("advance", "final_selection"))

        revision = plan("iteration_comparison", iteration=2)
        decision = derive_proposal_commit(
            revision, proposal("iteration_comparison", "propose_revision", iteration=2,
                               revision_direction="tighten_risk"))
        self.assertEqual((decision["outcome"], decision["next_stage"]),
                         ("advance", "waiting_for_task_create_approval"))
        self.assertEqual(decision["iteration"], 3)

        final = plan("final_selection", iteration=3)
        decision = derive_proposal_commit(
            final, proposal("final_selection", "select_iteration", iteration=3, selected_iteration=2))
        self.assertEqual((decision["outcome"], decision["next_stage"]), ("advance", "completed"))

    def test_escalation_and_insufficient_evidence_stop_without_routing(self) -> None:
        base = plan("backtest_analysis")
        escalated = derive_proposal_commit(
            base, proposal("backtest_analysis", "escalate", escalate=True))
        self.assertEqual((escalated["outcome"], escalated["reason"]),
                         ("needs_attention", "escalation_requested"))
        insufficient = derive_proposal_commit(
            base, proposal("backtest_analysis", "backtest_analysis", evidence_sufficient=False))
        self.assertEqual((insufficient["outcome"], insufficient["reason"]),
                         ("needs_attention", "insufficient_evidence"))

    def test_stale_and_mismatched_bindings_never_advance(self) -> None:
        base = plan("strategy_draft")
        stale_plan = derive_proposal_commit(
            base, proposal("strategy_draft", "strategy_draft", plan_version=99))
        self.assertEqual((stale_plan["outcome"], stale_plan["reason"]),
                         ("needs_attention", "stale_plan_version"))
        stale_task = derive_proposal_commit(
            base, proposal("strategy_draft", "strategy_draft", task_version=99))
        self.assertEqual((stale_task["outcome"], stale_task["reason"]),
                         ("needs_attention", "stale_task_version"))
        wrong_task = derive_proposal_commit(
            base, proposal("strategy_draft", "strategy_draft", task_id="task_" + "b" * 32))
        self.assertEqual((wrong_task["outcome"], wrong_task["reason"]),
                         ("needs_attention", "proposal_task_mismatch"))
        wrong_stage = derive_proposal_commit(
            base, proposal("backtest_analysis", "backtest_analysis"))
        self.assertEqual((wrong_stage["outcome"], wrong_stage["reason"]),
                         ("needs_attention", "proposal_stage_mismatch"))
        revision_beyond_final = derive_proposal_commit(
            plan("iteration_comparison", iteration=3),
            proposal("iteration_comparison", "propose_revision", iteration=3,
                     revision_direction="tighten_risk"))
        self.assertEqual((revision_beyond_final["outcome"], revision_beyond_final["reason"]),
                         ("needs_attention", "revision_beyond_final_iteration"))


class ModelCallFenceTests(unittest.TestCase):
    def test_default_two_call_bound_and_first_check_no_progress_fence(self) -> None:
        first_no_progress = stage_model_call_outcome(
            stage="backtest_analysis", calls_used=1, durable_progress_identity=None)
        self.assertEqual((first_no_progress["status"], first_no_progress["reason"]),
                         ("stop", NO_DURABLE_PROGRESS))
        self.assertEqual(first_no_progress["outcome"], "needs_attention")
        self.assertEqual(first_no_progress["model_calls_remaining"], 1)
        self.assertFalse(first_no_progress["continue"])

        first_progress = stage_model_call_outcome(
            stage="backtest_analysis", calls_used=1, durable_progress_identity=DIGEST_A)
        self.assertTrue(first_progress["continue"])
        self.assertEqual(first_progress["model_calls_remaining"], 1)

        second = stage_model_call_outcome(
            stage="backtest_analysis", calls_used=2, durable_progress_identity=DIGEST_B)
        self.assertFalse(second["continue"])
        self.assertEqual(second["model_calls_used"], 2)

        exceeded = stage_model_call_outcome(
            stage="backtest_analysis", calls_used=3, durable_progress_identity=DIGEST_B)
        self.assertEqual((exceeded["status"], exceeded["reason"]),
                         ("stop", "model_call_limit_exceeded"))
        self.assertEqual(exceeded["outcome"], "needs_attention")

    def test_deterministic_stage_has_zero_model_calls(self) -> None:
        for stage in DETERMINISTIC_STAGES:
            with self.assertRaises(ValueError):
                stage_model_call_outcome(stage=stage, calls_used=1, durable_progress_identity=None)


class AdmissionAndEvidenceTests(unittest.TestCase):
    def test_admission_request_is_closed_and_never_carries_a_count(self) -> None:
        self.assertEqual(validate_stage_admission_request({"call_identity": "turn-a"}),
                         {"call_identity": "turn-a"})
        for invalid in ({"call_identity": "turn-a", "call_index": 1},
                        {"call_identity": "turn-a", "count": 0}, {}, {"call_index": 1}):
            with self.assertRaises(ValueError):
                validate_stage_admission_request(invalid)

    def test_admission_request_accepts_an_optional_attempt_binding_only(self) -> None:
        self.assertEqual(
            validate_stage_admission_request({
                "call_identity": "turn-a", "attempt_binding": "3:backtest_analysis:1"}),
            {"call_identity": "turn-a", "attempt_binding": "3:backtest_analysis:1"})
        for invalid in ("3:backtest_analysis", "Backtest:1", "3:backtest_analysis:",
                        "future:backtest_analysis:1", 5, None):
            with self.assertRaises(ValueError):
                validate_stage_admission_request(
                    {"call_identity": "turn-a", "attempt_binding": invalid})

    def test_attempt_binding_matches_the_persisted_plan(self) -> None:
        from packages.contracts.research_judgment import attempt_binding
        self.assertEqual(attempt_binding(3, "backtest_analysis", 1), "3:backtest_analysis:1")
        self.assertNotEqual(attempt_binding(4, "backtest_analysis", 1),
                            attempt_binding(3, "backtest_analysis", 1))

    def test_progress_evidence_is_a_closed_durable_record_never_a_digest(self) -> None:
        self.assertEqual(PROGRESS_EVIDENCE_KINDS,
                         frozenset({"none", "plan_advance", "artifact", "experiment", "backtest_job"}))
        for valid in ({"kind": "none"}, {"kind": "plan_advance"},
                      {"kind": "artifact", "id": "artifact_" + "a" * 32},
                      {"kind": "experiment", "id": "experiment_" + "a" * 32},
                      {"kind": "backtest_job", "id": "backtest_" + "a" * 32}):
            self.assertEqual(validate_progress_evidence(valid), valid)
        for invalid in ({"kind": "artifact", "id": "sha256:" + "a" * 64},
                        {"kind": "artifact"}, {"kind": "none", "id": "x"},
                        {"kind": "digest", "id": "sha256:" + "a" * 64},
                        {"kind": "artifact", "id": "artifact_" + "a" * 32, "extra": 1}):
            with self.assertRaises(ValueError):
                validate_progress_evidence(invalid)

    def test_judgment_result_envelope_is_closed_and_evidence_is_a_record(self) -> None:
        base = {"call_identity": "turn-a", "durable_evidence": {"kind": "none"}}
        self.assertEqual(validate_judgment_result_request(base), base)
        with_proposal = {**base, "proposal": proposal("backtest_analysis", "backtest_analysis")}
        self.assertEqual(validate_judgment_result_request(with_proposal), with_proposal)
        for invalid in ({"call_identity": "turn-a"},
                        {**base, "progress_identity": "sha256:" + "a" * 64},
                        {**base, "durable_evidence": {"kind": "digest", "id": "x"}},
                        {**base, "proposal": {"not": "a proposal"}},
                        {**base, "unknown": 1}):
            with self.assertRaises(ValueError):
                validate_judgment_result_request(invalid)

    def test_progress_request_binds_identity_and_evidence(self) -> None:
        valid = {"call_identity": "turn-a", "durable_evidence": {"kind": "none"}}
        self.assertEqual(validate_stage_progress_request(valid), valid)
        for invalid in ({"call_identity": "turn-a"},
                        {"call_identity": "turn-a", "durable_evidence": {"kind": "none"}, "extra": 1},
                        {"call_identity": "turn-a", "durable_evidence": {"kind": "unknown"}}):
            with self.assertRaises(ValueError):
                validate_stage_progress_request(invalid)


if __name__ == "__main__":
    unittest.main()
