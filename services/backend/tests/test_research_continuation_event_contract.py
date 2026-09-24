"""ADR-0085 P2 contract tests: closed event envelope + deterministic reducer.

Pure logic: no PostgreSQL, no model turn, no HTTP route.
"""

from __future__ import annotations

import hashlib

import pytest

from packages.contracts.research_continuation_event import (
    AGENT_APPROVAL_PLAN_ACTION,
    EVENT_DECISIONS,
    EVENT_SCHEMA_VERSION,
    EVENT_TYPES,
    EVENT_VERSION,
    FORBIDDEN_EVENT_FIELDS,
    OUTCOMES,
    PLAN_APPROVAL_ACTION,
    RESULT_STATUSES,
    bind_command_digest,
    bound_approval,
    event_identity,
    event_request_hash,
    event_result_status,
    plan_command_digest,
    plan_command_idempotency_key,
    reduce_continuation_event,
    validate_event,
)
from packages.contracts.research_execution_plan import (
    advance,
    new_plan,
    plan_at_stage,
)

TASK = "task_" + "a" * 32
WORKSPACE = "workspace_" + "b" * 32
CONVERSATION = "conversation_" + "c" * 32
STRATEGY = "artifact_" + "d" * 32
BACKTEST_TASK = "backtesttask_" + "f" * 32
SIGNAL_JOB = "signaljob_" + "1" * 32
SNAPSHOT = "artifact_" + "2" * 32
BACKTEST_JOB = "backtest_" + "3" * 32
RESULT = "artifact_" + "4" * 32

APPROVAL_DIGEST = "sha256:" + "a" * 64


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _references(**extra: str) -> dict:
    references = {
        "research_task": {"research_task": TASK},
        "conversation": {"conversation": CONVERSATION},
    }
    references.update({kind: {kind: identity} for kind, identity in extra.items()})
    return references


def _approval(action: str, resource_kind: str, resource_id: str, *, plan: int, task: int = 1,
              params_digest: str | None = APPROVAL_DIGEST):
    approval = {"action": action, "resource_kind": resource_kind, "resource_id": resource_id,
                "plan_version": plan, "task_version": task}
    if params_digest is not None:
        approval["params_digest"] = params_digest
    return approval


def _gate_plan(stage: str, *, references: dict, approval=None, iteration: int = 1):
    return plan_at_stage(
        task_id=TASK, owner_principal="alice", workspace_id=WORKSPACE,
        conversation_id=CONVERSATION, task_version=1, stage=stage,
        idempotency_key="plan-1", references=references, approval=approval, iteration=iteration,
    )


def _event(event_type: str, plan: dict, *, source_identity: str = "source_1",
           expected_postcondition=None, references=None, decision=None,
           params_digest=None, plan_version=None, task_version=None,
           task_id=None, owner_principal=None, workspace_id=None):
    event: dict = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": event_identity(event_type=event_type, source_identity=source_identity,
                                   event_version=EVENT_VERSION),
        "event_type": event_type,
        "event_version": EVENT_VERSION,
        "source_identity": source_identity,
        "task_id": task_id or plan["task_id"],
        "owner_principal": owner_principal or plan["owner_principal"],
        "workspace_id": workspace_id or plan["workspace_id"],
        "plan_version": plan["plan_version"] if plan_version is None else plan_version,
        "task_version": plan["task_version"] if task_version is None else task_version,
        "references": references if references is not None else dict(plan["references"]),
        "expected_postcondition": expected_postcondition or "strategy_approval_requested",
        "request_hash": "",
    }
    if decision is not None:
        event["decision"] = decision
    if params_digest is None and event_type in {"plan_approval", "data_ready", "backtest_completed"}:
        params_digest = _digest("default")
    if params_digest is not None:
        event["params_digest"] = params_digest
    event["request_hash"] = event_request_hash(event)
    return event


# --------------------------------------------------------------------------- #
# Closed envelope
# --------------------------------------------------------------------------- #

def test_event_vocabulary_only_covers_the_five_planned_types() -> None:
    assert EVENT_TYPES == {"plan_approval", "data_ready", "backtest_completed",
                           "user_resume", "recovery"}
    assert EVENT_DECISIONS == {"approved", "rejected", "expired", "revoked"}
    assert "next_stage" in FORBIDDEN_EVENT_FIELDS and "idempotency_key" in FORBIDDEN_EVENT_FIELDS


def test_event_identity_is_deterministic_and_version_bound() -> None:
    first = event_identity(event_type="data_ready", source_identity=SIGNAL_JOB, event_version=1)
    assert first == event_identity(event_type="data_ready", source_identity=SIGNAL_JOB, event_version=1)
    assert first != event_identity(event_type="recovery", source_identity=SIGNAL_JOB, event_version=1)
    with pytest.raises(ValueError):
        event_identity(event_type="data_ready", source_identity=SIGNAL_JOB, event_version=2)
    with pytest.raises(ValueError):
        event_identity(event_type="unknown_type", source_identity=SIGNAL_JOB, event_version=1)


def test_event_request_hash_binds_every_authoritative_field() -> None:
    plan = _gate_plan("waiting_for_data", references=_references(strategy_version=STRATEGY))
    event = _event("data_ready", plan, expected_postcondition="signal_job_completed_with_validated_snapshot")
    validate_event(event)
    # Tampering an authoritative field without recomputing the hash is rejected.
    for field, replacement in (("plan_version", 9), ("task_version", 9),
                               ("params_digest", APPROVAL_DIGEST), ("source_identity", "source_2")):
        tampered = dict(event)
        tampered[field] = replacement
        with pytest.raises(ValueError):
            validate_event(tampered)


def test_forbidden_caller_routing_fields_fail_closed() -> None:
    plan = _gate_plan("waiting_for_data", references=_references(strategy_version=STRATEGY))
    base = _event("data_ready", plan)
    for field, value in (("next_stage", "ready_to_execute_backtest_task"),
                         ("next_action", "execute_backtest_task"),
                         ("status", "active"), ("idempotency_key", "attacker-key"),
                         ("object_id", "backtesttask_" + "9" * 32), ("routing", "model")):
        tampered = {**base, field: value}
        tampered["request_hash"] = event_request_hash(tampered)
        with pytest.raises(ValueError):
            validate_event(tampered)


def test_unknown_and_missing_event_keys_fail_closed() -> None:
    plan = _gate_plan("waiting_for_data", references=_references(strategy_version=STRATEGY))
    event = _event("data_ready", plan)
    with pytest.raises(ValueError):
        validate_event({**event, "unexpected": 1})
    missing = dict(event)
    del missing["task_id"]
    with pytest.raises(ValueError):
        validate_event(missing)
    with pytest.raises(ValueError):
        validate_event({**event, "event_type": "made_up"})
    with pytest.raises(ValueError):
        validate_event({**event, "schema_version": "research-continuation-event.v2"})


def test_data_ready_and_backtest_completed_require_a_params_digest() -> None:
    plan = _gate_plan("waiting_for_data", references=_references(strategy_version=STRATEGY))
    event = _event("data_ready", plan)
    event.pop("params_digest")
    event["request_hash"] = event_request_hash(event)
    with pytest.raises(ValueError):
        validate_event(event)


# --------------------------------------------------------------------------- #
# Stale plan/task/event
# --------------------------------------------------------------------------- #

def test_stale_plan_and_task_versions_never_advance() -> None:
    plan = _gate_plan("waiting_for_data", references=_references(strategy_version=STRATEGY))
    stale_plan = _event("user_resume", plan, plan_version=plan["plan_version"] + 1,
                        expected_postcondition="signal_job_completed_with_validated_snapshot")
    assert reduce_continuation_event(plan, stale_plan, facts={})["outcome"] == "needs_attention"
    assert reduce_continuation_event(plan, stale_plan, facts={})["reason"] == "stale_plan_version"
    stale_task = _event("user_resume", plan, task_version=plan["task_version"] + 1,
                        expected_postcondition="signal_job_completed_with_validated_snapshot")
    assert reduce_continuation_event(plan, stale_task, facts={})["reason"] == "stale_task_version"


def test_foreign_owner_event_is_rejected() -> None:
    plan = _gate_plan("waiting_for_data", references=_references(strategy_version=STRATEGY))
    foreign = _event("user_resume", plan, owner_principal="intruder",
                     expected_postcondition="signal_job_completed_with_validated_snapshot")
    with pytest.raises(ValueError):
        reduce_continuation_event(plan, foreign, facts={})


# --------------------------------------------------------------------------- #
# Approval binds the exact command
# --------------------------------------------------------------------------- #

def test_approved_execute_gate_advances_with_the_exact_bound_approval() -> None:
    references = _references(backtest_task=BACKTEST_TASK)
    plan = _gate_plan("waiting_for_task_execute_approval", references=references,
                      approval=_approval("backtest_execute", "backtest_task", BACKTEST_TASK, plan=1))
    event = _event("plan_approval", plan, source_identity="agent_approval_1", decision="approved",
                   expected_postcondition="backtest_job_queued",
                   references=references, params_digest=APPROVAL_DIGEST)
    decision = reduce_continuation_event(plan, event, facts={})
    assert decision["outcome"] == "advance"
    assert decision["next_stage"] == "ready_to_execute_backtest_task"
    assert decision["status"] == "active"
    assert decision["expected_postcondition"] == "backtest_job_queued"
    approval = decision["approval"]
    assert approval == {
        "action": "backtest_execute", "resource_kind": "backtest_task", "resource_id": BACKTEST_TASK,
        "plan_version": plan["plan_version"] + 1, "task_version": plan["task_version"],
        "params_digest": APPROVAL_DIGEST,
    }


def test_rejected_approval_stably_stays_and_expired_revoked_need_attention() -> None:
    references = _references(backtest_task=BACKTEST_TASK)
    plan = _gate_plan("waiting_for_task_execute_approval", references=references,
                      approval=_approval("backtest_execute", "backtest_task", BACKTEST_TASK, plan=1))
    for decision_value, expected in (("rejected", "stay"), ("expired", "needs_attention"),
                                     ("revoked", "needs_attention")):
        event = _event("plan_approval", plan, source_identity=f"decision_{decision_value}",
                       decision=decision_value, expected_postcondition="backtest_job_queued",
                       references=references)
        result = reduce_continuation_event(plan, event, facts={})
        assert result["outcome"] == expected
        assert result["next_stage"] is None


def test_approval_must_match_pending_action_resource_and_params_digest() -> None:
    references = _references(backtest_task=BACKTEST_TASK)
    plan = _gate_plan("waiting_for_task_execute_approval", references=references,
                      approval=_approval("backtest_execute", "backtest_task", BACKTEST_TASK, plan=1))
    # A tampered plan whose pending approval no longer matches its gate is
    # rejected outright (closed contract), never silently re-routed.
    wrong_plan = {**plan, "approval": _approval("strategy_approve", "strategy_version",
                                                BACKTEST_TASK, plan=1)}
    mismatched = _event("plan_approval", plan, decision="approved",
                        expected_postcondition="backtest_job_queued", references=references)
    with pytest.raises(ValueError):
        reduce_continuation_event(wrong_plan, mismatched, facts={})
    bad_digest = _event("plan_approval", plan, decision="approved",
                        expected_postcondition="backtest_job_queued", references=references,
                        params_digest=_digest("different"))
    assert reduce_continuation_event(plan, bad_digest, facts={})["reason"] == "approval_params_digest_mismatch"


def test_approval_event_outside_a_gate_needs_attention() -> None:
    plan = _gate_plan("waiting_for_data", references=_references(strategy_version=STRATEGY))
    event = _event("plan_approval", plan, decision="approved",
                   expected_postcondition="signal_job_completed_with_validated_snapshot")
    assert reduce_continuation_event(plan, event, facts={})["outcome"] == "needs_attention"


# --------------------------------------------------------------------------- #
# data_ready uses the authoritative identity only
# --------------------------------------------------------------------------- #

def test_data_ready_advances_using_authoritative_backtest_task_identity() -> None:
    plan = _gate_plan("waiting_for_data",
                      references=_references(strategy_version=STRATEGY, signal_producer_job=SIGNAL_JOB))
    references = {**plan["references"], "backtest_task": {"backtest_task": BACKTEST_TASK},
                  "signal_snapshot": {"signal_snapshot": SNAPSHOT}}
    facts = {"backtest_task_id": BACKTEST_TASK, "phase": "data_ready", "next_action": "execute",
             "signal_snapshot_id": SNAPSHOT}
    event = _event("data_ready", plan, source_identity=SNAPSHOT,
                   expected_postcondition="backtest_execute_approval_requested",
                   references=references, params_digest=_digest("snapshot"))
    decision = reduce_continuation_event(plan, event, facts=facts)
    assert decision["outcome"] == "advance"
    assert decision["next_stage"] == "waiting_for_task_execute_approval"
    assert decision["approval"]["resource_id"] == BACKTEST_TASK


def test_data_ready_rejects_mismatched_or_non_executable_facts() -> None:
    plan = _gate_plan("waiting_for_data", references=_references(strategy_version=STRATEGY))
    references = {**plan["references"], "backtest_task": {"backtest_task": BACKTEST_TASK},
                  "signal_snapshot": {"signal_snapshot": SNAPSHOT}}
    facts = {"backtest_task_id": BACKTEST_TASK, "phase": "data_ready", "next_action": "execute",
             "signal_snapshot_id": SNAPSHOT}
    event = _event("data_ready", plan, source_identity=SNAPSHOT,
                   expected_postcondition="backtest_execute_approval_requested",
                   references=references, params_digest=_digest("snapshot"))
    wrong = {**facts, "backtest_task_id": "backtesttask_" + "9" * 32}
    assert reduce_continuation_event(plan, event, facts=wrong)["reason"] == "data_ready_backtest_task_mismatch"
    waiting_facts = {**facts, "next_action": "wait"}
    assert reduce_continuation_event(plan, event, facts=waiting_facts)["outcome"] == "stay"


# --------------------------------------------------------------------------- #
# backtest_completed only accepts a bound terminal
# --------------------------------------------------------------------------- #

def _waiting_job_plan() -> dict:
    references = {**_references(strategy_version=STRATEGY),
                  "backtest_task": {"backtest_task": BACKTEST_TASK},
                  "backtest_job": {"backtest_job": BACKTEST_JOB}}
    return _gate_plan("waiting_for_backtest_job", references=references)


def _completion_event(plan: dict, *, references: dict, expected="backtest_result_analysed",
                      source_identity: str = BACKTEST_JOB):
    return _event("backtest_completed", plan, source_identity=source_identity,
                  expected_postcondition=expected, references=references,
                  params_digest=_digest("result"))


def test_backtest_completed_advances_only_for_a_bound_terminal_completed_result() -> None:
    plan = _waiting_job_plan()
    references = {**plan["references"], "backtest_result": {"backtest_result": RESULT}}
    event = _completion_event(plan, references=references)
    facts = {"backtest_job_id": BACKTEST_JOB, "backtest_result_id": RESULT,
             "terminal_status": "completed", "next_action": "review_result"}
    decision = reduce_continuation_event(plan, event, facts=facts)
    assert decision["outcome"] == "advance" and decision["next_stage"] == "backtest_analysis"


def test_backtest_completed_rejects_non_terminal_failed_and_unbound_results() -> None:
    plan = _waiting_job_plan()
    references = {**plan["references"], "backtest_result": {"backtest_result": RESULT}}
    event = _completion_event(plan, references=references)
    non_terminal = {"backtest_job_id": BACKTEST_JOB, "backtest_result_id": RESULT,
                    "terminal_status": "running", "next_action": "wait"}
    assert reduce_continuation_event(plan, event, facts=non_terminal)["reason"] == "backtest_job_not_terminal"
    failed = {"backtest_job_id": BACKTEST_JOB, "backtest_result_id": RESULT,
              "terminal_status": "failed", "next_action": "review_failure"}
    assert reduce_continuation_event(plan, event, facts=failed)["outcome"] == "needs_attention"
    unbound = {**event, "references": plan["references"]}
    unbound["request_hash"] = event_request_hash(unbound)
    assert reduce_continuation_event(plan, unbound, facts={
        "backtest_job_id": BACKTEST_JOB, "backtest_result_id": RESULT,
        "terminal_status": "completed", "next_action": "review_result",
    })["reason"] == "backtest_result_missing"


def test_late_backtest_completed_for_a_non_waiting_stage_needs_attention() -> None:
    plan = _gate_plan("waiting_for_data", references=_references(strategy_version=STRATEGY))
    event = _event("backtest_completed", plan, source_identity=BACKTEST_JOB,
                   expected_postcondition="backtest_result_available",
                   references={**plan["references"], "backtest_job": {"backtest_job": BACKTEST_JOB},
                               "backtest_result": {"backtest_result": RESULT}})
    facts = {"backtest_job_id": BACKTEST_JOB, "backtest_result_id": RESULT,
             "terminal_status": "completed", "next_action": "review_result"}
    assert reduce_continuation_event(plan, event, facts=facts)["reason"] == "backtest_completed_not_applicable"


# --------------------------------------------------------------------------- #
# user_resume / recovery retry the current exact action with no new identity
# --------------------------------------------------------------------------- #

def _strategy_draft_plan() -> dict:
    return new_plan(task_id=TASK, owner_principal="alice", workspace_id=WORKSPACE,
                    conversation_id=CONVERSATION, task_version=1, idempotency_key="plan-1")


def test_user_resume_only_retries_the_current_exact_action() -> None:
    plan = _strategy_draft_plan()
    event = _event("user_resume", plan, source_identity="session_resume_1")

    decision = reduce_continuation_event(plan, event, facts={})
    assert decision["outcome"] == "retry_current_action"
    assert decision["retry_action"] == plan["next_action"] == "draft_strategy"
    assert decision["retry_identity"] == plan["idempotency_key"]
    assert decision["next_stage"] is None  # no new plan version


def test_recovery_waits_out_a_human_gate_and_never_mints_a_new_identity() -> None:
    references = _references(strategy_version=STRATEGY)
    plan = _gate_plan("waiting_for_strategy_approval", references=references,
                      approval=_approval("strategy_approve", "strategy_version", STRATEGY, plan=1))
    event = _event("recovery", plan, source_identity="lost_run_1")
    decision = reduce_continuation_event(plan, event, facts={})
    assert decision["outcome"] == "stay"
    assert decision["reason"] == "recovery_waiting_for_human_decision"
    assert decision["retry_identity"] is None


def test_recovery_retries_the_current_action_for_a_deterministic_stage() -> None:
    references = _references(strategy_version=STRATEGY)
    plan = _gate_plan("waiting_for_data", references=references)
    event = _event("recovery", plan, source_identity="lost_run_2",
                   expected_postcondition="signal_job_completed_with_validated_snapshot")
    decision = reduce_continuation_event(plan, event, facts={})
    assert decision["outcome"] == "retry_current_action"
    assert decision["retry_action"] == "wait_for_data"
    assert decision["retry_identity"] == plan["idempotency_key"]


def test_terminal_plan_cannot_be_resumed_or_recovered() -> None:
    plan = _strategy_draft_plan()
    cancelled = advance(plan, expected_plan_version=1, expected_task_version=1,
                        next_stage="completed", iteration=1, status="cancelled",
                        expected_postcondition="research_cancelled",
                        idempotency_key="plan-cancel", last_progress_identity=None)
    event = _event("user_resume", cancelled, source_identity="session_resume_2",
                   expected_postcondition="research_cancelled")
    assert reduce_continuation_event(cancelled, event, facts={})["outcome"] == "needs_attention"


# --------------------------------------------------------------------------- #
# Zero model calls / closed outputs
# --------------------------------------------------------------------------- #

def test_outcomes_and_result_statuses_are_closed() -> None:
    assert OUTCOMES == {"advance", "stay", "needs_attention", "retry_current_action"}
    assert RESULT_STATUSES == {"advanced", "settled", "needs_attention", "pending"}
    assert event_result_status("advance") == "advanced"
    assert event_result_status("needs_attention") == "needs_attention"
    # A retry is a durable PENDING intent, never a fake settled receipt.
    assert event_result_status("retry_current_action") == "pending"
    with pytest.raises(ValueError):
        event_result_status("model_turn")


def test_command_digest_is_server_derived_and_version_bound() -> None:
    references = _references(backtest_task=BACKTEST_TASK)
    plan = _gate_plan("waiting_for_task_execute_approval", references=references,
                      approval=_approval("backtest_execute", "backtest_task", BACKTEST_TASK, plan=1))
    digest = plan_command_digest(plan, action="backtest_execute", resource_kind="backtest_task",
                                 resource_id=BACKTEST_TASK)
    assert digest.startswith("sha256:")
    assert digest == plan_command_digest(
        plan, action="backtest_execute", resource_kind="backtest_task", resource_id=BACKTEST_TASK)
    # A different exact resource yields a different digest.
    other_task = "backtesttask_" + "9" * 32
    assert digest != plan_command_digest(
        plan, action="backtest_execute", resource_kind="backtest_task", resource_id=other_task)
    bound = bind_command_digest(plan)
    assert bound["approval"]["params_digest"] == digest
    # An approval-free plan is returned unchanged.
    draft = _strategy_draft_plan()
    assert bind_command_digest(draft) == draft


def test_plan_command_idempotency_key_and_action_maps_are_closed() -> None:
    references = _references(backtest_task=BACKTEST_TASK)
    plan = _gate_plan("waiting_for_task_execute_approval", references=references,
                      approval=_approval("backtest_execute", "backtest_task", BACKTEST_TASK, plan=1))
    key = plan_command_idempotency_key(
        plan, action="backtest_execute", resource_kind="backtest_task", resource_id=BACKTEST_TASK)
    assert key.startswith("plancmd_") and len(key) == len("plancmd_") + 32
    assert key == plan_command_idempotency_key(
        plan, action="backtest_execute", resource_kind="backtest_task", resource_id=BACKTEST_TASK)
    assert PLAN_APPROVAL_ACTION == {
        "strategy_approve": "byq_strategy_approve",
        "backtest_task_create": "byq_backtest_task_create",
        "backtest_execute": "byq_backtest_task_execute",
        "create_paper_account": "byq_paper_account_create",
    }
    assert AGENT_APPROVAL_PLAN_ACTION == {
        agent_action: plan_action for plan_action, agent_action in PLAN_APPROVAL_ACTION.items()
    }


def test_data_ready_and_backtest_stale_source_binding_never_advances() -> None:
    plan = _gate_plan("waiting_for_data", references=_references(
        strategy_version=STRATEGY, signal_producer_job=SIGNAL_JOB))
    other_job = "signaljob_" + "9" * 32
    references = {**plan["references"], "backtest_task": {"backtest_task": BACKTEST_TASK},
                  "signal_snapshot": {"signal_snapshot": SNAPSHOT},
                  "signal_producer_job": {"signal_producer_job": other_job}}
    facts = {"backtest_task_id": BACKTEST_TASK, "phase": "data_ready", "next_action": "execute",
             "signal_snapshot_id": SNAPSHOT}
    event = _event("data_ready", plan, source_identity=SNAPSHOT,
                   expected_postcondition="backtest_execute_approval_requested",
                   references=references, params_digest=_digest("snapshot"))
    assert reduce_continuation_event(plan, event, facts=facts)["reason"] == "data_ready_stale_signal_job"

    job_plan = _waiting_job_plan()
    other_backtest = "backtest_" + "9" * 32
    job_refs = {**job_plan["references"], "backtest_result": {"backtest_result": RESULT},
                "backtest_job": {"backtest_job": other_backtest}}
    completion = _event("backtest_completed", job_plan, source_identity=other_backtest,
                        expected_postcondition="backtest_result_analysed", references=job_refs,
                        params_digest=_digest("result"))
    job_facts = {"backtest_job_id": other_backtest, "backtest_result_id": RESULT,
                 "terminal_status": "completed", "next_action": "review_result"}
    assert reduce_continuation_event(job_plan, completion, facts=job_facts)["reason"] == \
        "backtest_completed_stale_job"


def test_reducer_contract_has_no_model_or_runtime_dependency() -> None:
    import inspect

    import packages.contracts.research_continuation_event as module

    source = inspect.getsource(module).lower()
    for marker in ("import openai", "deepseek", "runtime-adapter", "runtime_adapter",
                   "__import__(\"dsh", "subprocess", "requests", "httpx", "socket"):
        assert marker not in source, marker
    # The reducer is a pure function over persisted facts: it imports no runtime.
    reducer_globals = reduce_continuation_event.__globals__
    assert not {"inspect", "subprocess", "requests", "httpx"}.intersection(reducer_globals)
