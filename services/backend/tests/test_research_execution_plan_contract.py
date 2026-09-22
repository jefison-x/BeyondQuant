"""ADR-0085 P1 contract tests: closed schema, gates, transitions, CAS, legacy."""

from __future__ import annotations

import pytest

from packages.contracts.research_execution_plan import (
    ACTION_APPROVAL,
    ACTION_CAPABILITIES,
    APPROVAL_WAIT_STAGES,
    ITERATIONS,
    MAX_ROUNDS,
    NEXT_ACTIONS,
    P0_ACTION_EQUIVALENTS,
    POSTCONDITIONS,
    PREREQUISITES,
    RESOURCE_KINDS,
    SCHEMA_VERSION,
    STAGE_ACTION,
    STAGE_STATUS,
    STAGES,
    advance,
    assert_transition,
    can_transition,
    classify_legacy_task,
    is_deterministic_action,
    new_plan,
    plan_at_stage,
    validate_plan,
)

TASK = "task_" + "a" * 32
WORKSPACE = "workspace_" + "b" * 32
CONVERSATION = "conversation_" + "c" * 32
STRATEGY = "artifact_" + "d" * 32
TASK_CREATE_APPROVAL = "artifact_" + "e" * 32
BACKTEST_TASK = "backtesttask_" + "f" * 32
EXECUTE_APPROVAL = "artifact_" + "0" * 32
SIGNAL_JOB = "signaljob_" + "1" * 32
SNAPSHOT = "artifact_" + "2" * 32
BACKTEST_JOB = "backtest_" + "3" * 32
RESULT = "artifact_" + "4" * 32


def _new(**overrides: object):
    return new_plan(
        task_id=TASK, owner_principal="alice", workspace_id=WORKSPACE,
        conversation_id=CONVERSATION, task_version=1,
        idempotency_key="plan-create-1", last_progress_identity=None, **overrides,
    )


def _approval(action: str, resource_kind: str, resource_id: str, *, plan=1, task=1):
    return {"action": action, "resource_kind": resource_kind, "resource_id": resource_id,
            "plan_version": plan, "task_version": task}


def _references(**extra: str):
    references = {
        "research_task": {"research_task": TASK},
        "conversation": {"conversation": CONVERSATION},
    }
    references.update({kind: {kind: identity} for kind, identity in extra.items()})
    return references


# --------------------------------------------------------------------------- #
# Closed vocabulary and schema
# --------------------------------------------------------------------------- #

def test_vocabulary_is_closed_and_self_consistent() -> None:
    assert SCHEMA_VERSION == "research-execution-plan.v1"
    assert ITERATIONS == {1, 2, 3} and MAX_ROUNDS == 3
    assert set(STAGE_ACTION) == set(STAGES)
    # Every stage action is a real action; the approval-wait and cancel actions
    # are additionally reachable but are not stage-default actions.
    assert set(STAGE_ACTION.values()) <= set(NEXT_ACTIONS)
    assert {"execute_backtest_task_approval_wait", "cancel_research"} <= set(NEXT_ACTIONS)
    assert set(ACTION_CAPABILITIES) == set(NEXT_ACTIONS)
    assert set(ACTION_APPROVAL) <= set(NEXT_ACTIONS)
    assert APPROVAL_WAIT_STAGES <= set(STAGES)
    assert PREREQUISITES and POSTCONDITIONS and RESOURCE_KINDS


def test_p0_equivalents_are_explicit_and_subset_of_v1() -> None:
    assert set(P0_ACTION_EQUIVALENTS.values()) <= set(NEXT_ACTIONS)
    assert P0_ACTION_EQUIVALENTS["create"] == "create_backtest_task"
    assert P0_ACTION_EQUIVALENTS["execute"] == "execute_backtest_task"


def test_new_plan_is_valid_and_starts_at_strategy_draft() -> None:
    plan = _new()
    assert plan["stage"] == "strategy_draft" and plan["status"] == "active"
    assert plan["plan_version"] == 1 and plan["iteration"] == 1
    assert plan["next_action"] == "draft_strategy" and plan["approval"] is None
    validate_plan(plan)


def test_unknown_and_missing_keys_fail_closed() -> None:
    with pytest.raises(ValueError):
        validate_plan({**_new(), "llm_next_action": "do_something"})
    missing = _new(); missing.pop("idempotency_key")
    with pytest.raises(ValueError):
        validate_plan(missing)
    with pytest.raises(ValueError):
        validate_plan({**_new(), "stage": "free_text_stage"})


def test_references_must_be_closed_kind_id_pairs() -> None:
    with pytest.raises(ValueError):
        validate_plan(_new(references={"unknown_kind": {"unknown_kind": "x"}}))
    with pytest.raises(ValueError):
        validate_plan(_new(references={"backtest_task": {"backtest_task": "x", "extra": 1}}))
    validate_plan(_new(references={"backtest_task": {"backtest_task": BACKTEST_TASK}}))


def test_prerequisites_and_postcondition_are_closed() -> None:
    with pytest.raises(ValueError):
        validate_plan({**_new(), "prerequisites": ["do_something_freeform"]})
    with pytest.raises(ValueError):
        validate_plan({**_new(), "expected_postcondition": "made_up"})


def test_next_action_must_match_stage_and_capabilities() -> None:
    with pytest.raises(ValueError):
        validate_plan({**_new(), "next_action": "execute_backtest_task"})
    with pytest.raises(ValueError):
        validate_plan({**_new(), "allowed_capabilities": ["byq_everything"]})


# --------------------------------------------------------------------------- #
# Human gate vs execution separation (ADR-0085 §2.3)
# --------------------------------------------------------------------------- #

def test_approval_gate_stages_expose_no_write_capability() -> None:
    for stage in sorted(APPROVAL_WAIT_STAGES):
        action = STAGE_ACTION[stage]
        capabilities = ACTION_CAPABILITIES[action]
        assert not any(cap.endswith(("_create", "_execute", "_approve")) for cap in capabilities), stage
    # The two write actions still carry their own explicit tool.
    assert "byq_backtest_task_create" in ACTION_CAPABILITIES["create_backtest_task"]
    assert "byq_backtest_task_execute" in ACTION_CAPABILITIES["execute_backtest_task"]
    # An agent capability to approve the strategy does not exist anywhere.
    assert all("byq_strategy_approve" not in caps for caps in ACTION_CAPABILITIES.values())


def test_execution_requires_the_bound_approval_and_matching_resource() -> None:
    plan = _new()
    plan = advance(plan, expected_plan_version=1, expected_task_version=1,
                   next_stage="waiting_for_strategy_approval", iteration=1, status="waiting",
                   expected_postcondition="strategy_approval_requested",
                   idempotency_key="p-2",
                   references=_references(strategy_version=STRATEGY),
                   approval=_approval("strategy_approve", "strategy_version", STRATEGY, plan=2),
                   last_progress_identity=None)
    assert plan["approval"]["action"] == "strategy_approve"
    # Wrong action/resource on the gate is rejected.
    with pytest.raises(ValueError):
        advance(plan, expected_plan_version=2, expected_task_version=1,
                next_stage="ready_to_create_backtest_task", iteration=1, status="active",
                expected_postcondition="backtest_task_created", idempotency_key="p-3",
                references=_references(strategy_version=STRATEGY),
                approval=_approval("backtest_execute", "backtest_task", BACKTEST_TASK),
                last_progress_identity=None)
    ready = advance(plan, expected_plan_version=2, expected_task_version=1,
                    next_stage="ready_to_create_backtest_task", iteration=1, status="active",
                    expected_postcondition="backtest_task_created", idempotency_key="p-3",
                    references=_references(strategy_version=STRATEGY),
                    approval=_approval("backtest_task_create", "strategy_version", STRATEGY, plan=3),
                    last_progress_identity=None)
    assert ready["next_action"] == "create_backtest_task"
    assert "byq_backtest_task_create" in ready["allowed_capabilities"]


def test_approval_must_bind_exact_plan_task_version_and_resource() -> None:
    base = _new()
    plan = advance(base, expected_plan_version=1, expected_task_version=1,
                   next_stage="waiting_for_strategy_approval", iteration=1, status="waiting",
                   expected_postcondition="strategy_approval_requested", idempotency_key="p-2",
                   references=_references(strategy_version=STRATEGY),
                   approval=_approval("strategy_approve", "strategy_version", STRATEGY, plan=2),
                   last_progress_identity=None)
    assert plan["plan_version"] == 2 and plan["task_version"] == 1
    # A stale/future plan_version on the approval is refused.
    with pytest.raises(ValueError):
        validate_plan({**plan, "approval": _approval("strategy_approve", "strategy_version",
                                                     STRATEGY, plan=1)})
    with pytest.raises(ValueError):
        validate_plan({**plan, "approval": _approval("strategy_approve", "strategy_version",
                                                     STRATEGY, plan=3)})
    # A mismatched task_version is refused.
    with pytest.raises(ValueError):
        validate_plan({**plan, "approval": _approval("strategy_approve", "strategy_version",
                                                     STRATEGY, plan=2, task=2)})
    # The approved resource id must equal the plan reference for that kind.
    with pytest.raises(ValueError):
        validate_plan({**plan, "approval": _approval("strategy_approve", "strategy_version",
                                                     "artifact_" + "9" * 32, plan=2)})
    with pytest.raises(ValueError):
        validate_plan({**plan, "references": _references()})
    # The exact bound approval still validates.
    validate_plan(plan)


def test_waiting_execute_stage_cannot_write_and_ready_stage_can() -> None:
    # The execute approval gate is a distinct action with read-only capability.
    wait_action = STAGE_ACTION["waiting_for_task_execute_approval"]
    assert wait_action == "execute_backtest_task_approval_wait"
    assert ACTION_CAPABILITIES[wait_action] == frozenset({"byq_research_get"})
    # Only the READY stage exposes the execute write capability.
    assert ACTION_CAPABILITIES[STAGE_ACTION["ready_to_execute_backtest_task"]] == frozenset(
        {"byq_research_get", "byq_backtest_task_execute"})


# --------------------------------------------------------------------------- #
# Stage/status invariants and transitions
# --------------------------------------------------------------------------- #

def test_status_is_constrained_per_stage() -> None:
    # active is invalid for a waiting approval gate.
    with pytest.raises(ValueError):
        validate_plan({**_new(), "stage": "waiting_for_strategy_approval",
                       "next_action": "request_strategy_approval", "status": "active",
                       "prerequisites": sorted(PREREQUISITES & {"strategy_draft_validated"}),
                       "expected_postcondition": "strategy_approval_requested",
                       "references": _references(strategy_version=STRATEGY),
                       "allowed_capabilities": sorted(ACTION_CAPABILITIES["request_strategy_approval"]),
                       "approval": _approval("strategy_approve", "strategy_version", STRATEGY)})
    # needs_attention must be blocked, not active.
    with pytest.raises(ValueError):
        validate_plan({**_new(), "stage": "needs_attention", "next_action": "resolve_blockers",
                       "status": "active", "expected_postcondition": "blocks_resolved_or_confirmed",
                       "prerequisites": [], "allowed_capabilities": ["byq_research_get"]})


def test_cancellation_is_a_terminal_transition() -> None:
    plan = _new()
    cancelled = advance(plan, expected_plan_version=1, expected_task_version=1,
                        next_stage="completed", iteration=1, status="cancelled",
                        expected_postcondition="research_cancelled", idempotency_key="p-cancel",
                        last_progress_identity=None)
    assert cancelled["status"] == "cancelled"
    assert cancelled["next_action"] == "cancel_research"
    assert not can_transition("completed", "strategy_draft")


def test_illegal_transitions_are_rejected() -> None:
    assert can_transition("strategy_draft", "waiting_for_strategy_approval")
    assert can_transition("waiting_for_strategy_approval", "ready_to_create_backtest_task")
    # Terminal is reachable for cancellation, but completed->anything is not.
    assert can_transition("strategy_draft", "completed")
    assert not can_transition("completed", "strategy_draft")
    with pytest.raises(ValueError):
        assert_transition("strategy_draft", "backtest_analysis")
    with pytest.raises(ValueError):
        assert_transition("strategy_draft", "not_a_stage")


def test_needs_attention_does_not_guess_a_recovery_stage() -> None:
    # It may return to explicit planning/waiting stages, never straight into a
    # terminal or write-ready stage.
    assert can_transition("needs_attention", "strategy_draft")
    assert can_transition("needs_attention", "waiting_for_data")
    assert not can_transition("needs_attention", "completed")
    assert not can_transition("needs_attention", "final_selection")


def test_final_selection_requires_round_three() -> None:
    plan = _new(iteration=2)
    # Build a legal path is unnecessary: the invariant is enforced directly.
    with pytest.raises(ValueError):
        validate_plan({**plan, "stage": "final_selection", "iteration": 2, "status": "active",
                       "next_action": "select_best_iteration",
                       "expected_postcondition": "best_iteration_selected",
                       "prerequisites": ["previous_iteration_settled"],
                       "allowed_capabilities": ["byq_research_get"]})


def test_next_round_must_advance_iteration_by_one() -> None:
    strategy_refs = _references(strategy_version=STRATEGY)
    task_refs = _references(backtest_task=BACKTEST_TASK)
    plan = _new()
    plan = _advance(plan, "waiting_for_strategy_approval", "waiting",
                    "strategy_approval_requested", references=strategy_refs,
                    approval=_approval("strategy_approve", "strategy_version", STRATEGY, plan=2))
    plan = _advance(plan, "ready_to_create_backtest_task", "active", "backtest_task_created",
                    references=strategy_refs,
                    approval=_approval("backtest_task_create", "strategy_version", STRATEGY, plan=3))
    plan = _advance(plan, "waiting_for_data", "waiting",
                    "signal_job_completed_with_validated_snapshot")
    plan = _advance(plan, "waiting_for_task_execute_approval", "waiting",
                    "backtest_execute_approval_requested", references=task_refs,
                    approval=_approval("backtest_execute", "backtest_task", BACKTEST_TASK, plan=5))
    plan = _advance(plan, "ready_to_execute_backtest_task", "active", "backtest_job_queued",
                    references=task_refs,
                    approval=_approval("backtest_execute", "backtest_task", BACKTEST_TASK, plan=6))
    plan = _advance(plan, "waiting_for_backtest_job", "waiting", "backtest_result_available")
    plan = _advance(plan, "backtest_analysis", "active", "backtest_result_analysed")
    plan = _advance(plan, "iteration_comparison", "active", "iteration_compared")
    with pytest.raises(ValueError):
        advance(plan, expected_plan_version=plan["plan_version"], expected_task_version=1,
                next_stage="waiting_for_task_create_approval", iteration=3, status="waiting",
                expected_postcondition="next_round_task_create_approval_requested",
                idempotency_key="p-r2", last_progress_identity=None, references=strategy_refs,
                approval=_approval("backtest_task_create", "strategy_version", STRATEGY,
                                   plan=plan["plan_version"] + 1))
    round2 = advance(plan, expected_plan_version=plan["plan_version"], expected_task_version=1,
                     next_stage="waiting_for_task_create_approval", iteration=2, status="waiting",
                     expected_postcondition="next_round_task_create_approval_requested",
                     idempotency_key="p-r2", last_progress_identity=None, references=strategy_refs,
                     approval=_approval("backtest_task_create", "strategy_version", STRATEGY,
                                        plan=plan["plan_version"] + 1))
    assert round2["iteration"] == 2


# --------------------------------------------------------------------------- #
# CAS (pure) — the atomic guarantee is the store's responsibility
# --------------------------------------------------------------------------- #

def test_stale_plan_and_task_versions_are_rejected() -> None:
    plan = _new()
    with pytest.raises(ValueError):
        advance(plan, expected_plan_version=0, expected_task_version=1,
                next_stage="waiting_for_strategy_approval", iteration=1, status="waiting",
                expected_postcondition="strategy_approval_requested", idempotency_key="k",
                last_progress_identity=None, references=_references(strategy_version=STRATEGY),
                approval=_approval("strategy_approve", "strategy_version", STRATEGY))
    with pytest.raises(ValueError):
        advance(plan, expected_plan_version=1, expected_task_version=5,
                next_stage="waiting_for_strategy_approval", iteration=1, status="waiting",
                expected_postcondition="strategy_approval_requested", idempotency_key="k",
                last_progress_identity=None, references=_references(strategy_version=STRATEGY),
                approval=_approval("strategy_approve", "strategy_version", STRATEGY))


def test_advance_bumps_plan_version_once_and_old_version_cannot_advance() -> None:
    plan = _new()
    advanced = advance(plan, expected_plan_version=1, expected_task_version=1,
                       next_stage="waiting_for_strategy_approval", iteration=1, status="waiting",
                       expected_postcondition="strategy_approval_requested", idempotency_key="p-2",
                       last_progress_identity=None, references=_references(strategy_version=STRATEGY),
                       approval=_approval("strategy_approve", "strategy_version", STRATEGY, plan=2))
    assert advanced["plan_version"] == 2
    # A caller holding the CURRENT plan (v2) but passing stale expected=1 fails.
    with pytest.raises(ValueError):
        advance(advanced, expected_plan_version=1, expected_task_version=1,
                next_stage="ready_to_create_backtest_task", iteration=1, status="active",
                expected_postcondition="backtest_task_created", idempotency_key="p-3",
                last_progress_identity=None, references=_references(strategy_version=STRATEGY),
                approval=_approval("backtest_task_create", "strategy_version", STRATEGY, plan=3))


def test_deterministic_actions_never_need_a_model_turn() -> None:
    for action in ("create_backtest_task", "wait_for_data", "execute_backtest_task",
                   "wait_for_backtest_job", "resolve_blockers", "notify_user", "cancel_research"):
        assert is_deterministic_action(action) is True
    for action in ("draft_strategy", "analyse_backtest_result", "compare_iterations",
                   "select_best_iteration", "request_strategy_approval",
                   "execute_backtest_task_approval_wait"):
        assert is_deterministic_action(action) is False
    assert is_deterministic_action("cancel_research") is True
    with pytest.raises(ValueError):
        is_deterministic_action("unknown_action")


# --------------------------------------------------------------------------- #
# Legacy migration policy
# --------------------------------------------------------------------------- #

def test_legacy_migration_requires_a_unique_closed_mapping() -> None:
    assert classify_legacy_task(task_terminal=False, stage_hint="waiting_for_data",
                                next_action_hint="wait_for_data",
                                has_unique_plan_object=True)["status"] == "migratable"
    asserts = [
        dict(task_terminal=False, stage_hint=None, next_action_hint="wait_for_data",
             has_unique_plan_object=True),
        dict(task_terminal=False, stage_hint="waiting_for_data",
             next_action_hint="draft_strategy", has_unique_plan_object=True),
        dict(task_terminal=False, stage_hint="waiting_for_data",
             next_action_hint="wait_for_data", has_unique_plan_object=False),
        dict(task_terminal=True, stage_hint="waiting_for_data",
             next_action_hint="wait_for_data", has_unique_plan_object=True),
        dict(task_terminal=False, stage_hint="研究进行中", next_action_hint="继续",
             has_unique_plan_object=True),
        dict(task_terminal=False, stage_hint="completed", next_action_hint="notify_user",
             has_unique_plan_object=True),
    ]
    for case in asserts:
        assert classify_legacy_task(**case)["status"] == "needs_attention"


def test_plan_at_stage_builds_the_stage_defaults() -> None:
    waiting = plan_at_stage(
        task_id=TASK, owner_principal="alice", workspace_id=WORKSPACE,
        conversation_id=CONVERSATION, task_version=1, stage="waiting_for_data",
        idempotency_key="legacy-1",
    )
    assert waiting["status"] == "waiting"
    assert waiting["next_action"] == STAGE_ACTION["waiting_for_data"]
    assert waiting["expected_postcondition"] == "signal_job_completed_with_validated_snapshot"
    assert waiting["approval"] is None
    blocked = plan_at_stage(
        task_id=TASK, owner_principal="alice", workspace_id=WORKSPACE,
        conversation_id=CONVERSATION, task_version=1, stage="needs_attention",
        idempotency_key="legacy-2",
    )
    assert blocked["status"] == STAGE_STATUS["needs_attention"] == "blocked"
    assert blocked["next_action"] == "resolve_blockers"
    validate_plan(blocked)


def test_plan_at_stage_requires_a_write_ready_approval_and_closed_stage() -> None:
    with pytest.raises(ValueError):
        plan_at_stage(
            task_id=TASK, owner_principal="alice", workspace_id=WORKSPACE,
            conversation_id=CONVERSATION, task_version=1,
            stage="ready_to_create_backtest_task", idempotency_key="legacy-3",
        )
    ready = plan_at_stage(
        task_id=TASK, owner_principal="alice", workspace_id=WORKSPACE,
        conversation_id=CONVERSATION, task_version=1,
        stage="ready_to_create_backtest_task", idempotency_key="legacy-4",
        references=_references(strategy_version=STRATEGY),
        approval=_approval("backtest_task_create", "strategy_version", STRATEGY),
    )
    assert ready["next_action"] == "create_backtest_task"
    assert "byq_backtest_task_create" in ready["allowed_capabilities"]
    with pytest.raises(ValueError):
        plan_at_stage(
            task_id=TASK, owner_principal="alice", workspace_id=WORKSPACE,
            conversation_id=CONVERSATION, task_version=1, stage="free_text",
            idempotency_key="legacy-5",
        )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _advance(plan, next_stage, status, postcondition, *, approval=None, iteration=None,
             idempotency_key="p-n", references=None):
    return advance(
        plan, expected_plan_version=plan["plan_version"],
        expected_task_version=plan["task_version"], next_stage=next_stage,
        iteration=iteration if iteration is not None else plan["iteration"],
        status=status, expected_postcondition=postcondition,
        idempotency_key=idempotency_key, references=references, approval=approval,
        last_progress_identity=None,
    )
