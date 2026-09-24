"""ADR-0085 P4 plan-continuation production seam tests.

These exercise the INTERNAL trusted Backend seam that closes the gap left by
P0-P3: creating the single plan for a granted compound task, the bounded
read-only dispatch descriptor, the server-side plan-command-bound approval
request, the deterministic READY-action result CAS, and the wiring that advances
the plan from a real human approval decision. There is no agent-facing write
route for a plan, an event or an approval request.
"""

import os

import pytest

from app.agent_research import AgentResearchStore
from app.research import InvalidTransition, ResearchStore
from packages.contracts.research_continuation_event import (
    plan_command_digest,
    plan_command_idempotency_key,
)
from tests.test_research_continuation_ledger import (
    BACKTEST_JOB,
    BACKTEST_TASK,
    STRATEGY,
    _approval,
    _insert_backtest_job,
    _references,
    _seed_plan,
    _setup,
    _task_row,
)

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"),
                                reason="isolated PostgreSQL required")


def _validated_strategy(store, task):
    row = _task_row(store, task)
    artifact = store.create_artifact({
        "task_id": task, "kind": "strategy_version", "content": {"synthetic": "strategy"},
        "lineage": [], "trace_id": row["trace_id"], "idempotency_key": "p4-strategy"})
    store.transition("artifact", artifact["artifact_id"], "validated", "p4-strategy-validate")
    return artifact["artifact_id"]


def _grant(store, task, context, *, artifact_id, key="p4-grant"):
    return store.create_continuation_permission(task, {
        "idempotency_key": key, "token_limit": 8 * (1048576 + 8192), "max_turns": 8,
        "confirmed_artifact_ids": [artifact_id]}, trusted_context=context)


def _start_bound_run(owner, session, trace, *, key):
    agent = AgentResearchStore()
    run = agent.start_run({
        "owner_principal": owner, "actor_principal": owner, "role_id": "quant_orchestrator",
        "trace_id": trace, "session_id": session, "dsh_run_id": session + "-dsh",
        "idempotency_key": key + "-run"})
    return agent, run


def test_grant_creates_one_current_plan_and_bounded_dispatch():
    store, task, context = _setup(owner="p4-user", session="p4-session", trace="p4-trace")
    try:
        artifact_id = _validated_strategy(store, task)
        _grant(store, task, context, artifact_id=artifact_id)
        plan = store.get_execution_plan(task, trusted_context=context)
        assert plan["stage"] == "strategy_draft"
        dispatch = store.plan_continuation_dispatch(task, trusted_context=context)
        assert dispatch["kind"] == "judgment_turn"
        assert dispatch["stage"] == "strategy_draft"
        assert dispatch["model_call_limit"] == 2
        assert dispatch["bounded_projection_only"] is True
        # The bounded judgment role exposes only read-only tools.
        assert all(tool.startswith("byq_") for tool in dispatch["allowed_tools"])
        assert not any(tool.endswith(("_create", "_execute", "_approve", "_transition"))
                       for tool in dispatch["allowed_tools"])
        # Replaying the grant does not create a second plan.
        _grant(store, task, context, artifact_id=artifact_id)
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == 1
    finally:
        store.close()


def test_plan_requires_an_active_grant_and_is_owner_scoped():
    store, task, context = _setup(owner="p4-owner", session="p4-s2", trace="p4-t2")
    try:
        with pytest.raises(InvalidTransition):
            store.ensure_execution_plan(task, trusted_context=context)
        other = {"owner_principal": "p4-other", "workspace_id": context["workspace_id"]}
        with pytest.raises(Exception):
            store.plan_continuation_dispatch(task, trusted_context=other)
    finally:
        store.close()


def test_request_plan_approval_mints_exact_binding_and_replays():
    store, task, context = _setup(owner="p4-gate", session="p4-s3", trace="p4-t3")
    agent = None
    try:
        row = _task_row(store, task)
        agent, _ = _start_bound_run(context["owner_principal"], "p4-s3", "p4-t3", key="p4-gate")
        plan = _seed_plan(store, task, context, "waiting_for_strategy_approval",
                          _references(strategy_version=STRATEGY),
                          approval=_approval("strategy_approve", "strategy_version", STRATEGY, plan=1,
                              params_digest=None))
        assert plan["plan_version"] == 1
        request = store.request_plan_approval(task, trusted_context=context)
        assert request["action"] == "byq_strategy_approve"
        assert request["resource_id"] == STRATEGY
        # The persisted row carries the exact server-derived binding.
        approval = store._fetch_one("SELECT * FROM agent_approvals WHERE approval_id = :id",
                                    {"id": request["approval_id"]})
        assert approval["plan_task_id"] == task
        assert approval["plan_version"] == 1 and approval["plan_task_version"] == row["version"]
        assert approval["plan_params_digest"] == plan_command_digest(
            plan, action="strategy_approve", resource_kind="strategy_version", resource_id=STRATEGY)
        assert approval["plan_idempotency_key"] == plan_command_idempotency_key(
            plan, action="strategy_approve", resource_kind="strategy_version", resource_id=STRATEGY)
        # An exact replay returns the same approval row.
        replay = store.request_plan_approval(task, trusted_context=context)
        assert replay["approval_id"] == request["approval_id"]
        assert store._fetch_one("SELECT COUNT(*) AS c FROM agent_approvals")["c"] == 1
    finally:
        store.close()
        if agent is not None:
            agent.close()


def test_human_approval_decision_advances_the_plan_through_the_ledger():
    store, task, context = _setup(owner="p4-approve", session="p4-s4", trace="p4-t4")
    agent = None
    try:
        strategy = _validated_strategy(store, task)
        agent, _ = _start_bound_run(context["owner_principal"], "p4-s4", "p4-t4", key="p4-approve")
        _seed_plan(store, task, context, "waiting_for_strategy_approval",
                   _references(strategy_version=strategy),
                   approval=_approval("strategy_approve", "strategy_version", strategy, plan=1,
                              params_digest=None))
        request = store.request_plan_approval(task, trusted_context=context)
        decided = agent.decide_approval(
            {"approval_id": request["approval_id"], "decision": "approved"},
            trusted_owner=context["owner_principal"], trusted_actor="human-reviewer")
        # The compat free-text path is blocked for a plan-bound approval.
        assert decided["continuation_status"] == "blocked"
        # The trusted route consumer records the deterministic plan approval event.
        target = agent.plan_bound_approval_target(
            request["approval_id"], trusted_owner=context["owner_principal"])
        assert target["task_id"] == task and target["decision"] == "approved"
        store.record_plan_approval_event(
            target["task_id"], request["approval_id"],
            trusted_context={"owner_principal": target["owner_principal"],
                             "workspace_id": target["workspace_id"]})
        plan = store.get_execution_plan(task, trusted_context=context)
        assert plan["stage"] == "waiting_for_task_create_approval"
        events = store.list_continuation_events(task, trusted_context=context)
        assert len(events["events"]) == 1
        assert events["events"][0]["event_type"] == "plan_approval"
        assert events["events"][0]["status"] == "advanced"
    finally:
        store.close()
        if agent is not None:
            agent.close()


def test_deterministic_action_result_advances_and_replays():
    store, task, context = _setup(owner="p4-exec", session="p4-s5", trace="p4-t5")
    try:
        _seed_plan(store, task, context, "ready_to_execute_backtest_task",
                   _references(backtest_task=BACKTEST_TASK),
                   approval=_approval("backtest_execute", "backtest_task", BACKTEST_TASK, plan=1,
                              params_digest=None))
        _insert_backtest_job(store, task, context, job_id=BACKTEST_JOB, status="queued",
                             result_id=None, key="p4-bt")
        advanced = store.apply_deterministic_action_result(
            task, {"backtest_job_id": BACKTEST_JOB}, trusted_context=context)
        assert advanced["stage"] == "waiting_for_backtest_job"
        assert advanced["plan_version"] == 2
        replay = store.apply_deterministic_action_result(
            task, {"backtest_job_id": BACKTEST_JOB}, trusted_context=context)
        assert replay["plan_version"] == 2 and replay["stage"] == "waiting_for_backtest_job"
        with pytest.raises(InvalidTransition):
            store.apply_deterministic_action_result(
                task, {"signal_job_id": "signaljob_" + "1" * 32}, trusted_context=context)
        with pytest.raises(InvalidTransition):
            store.apply_deterministic_action_result(
                task, {"backtest_job_id": "backtest_" + "9" * 32}, trusted_context=context)
    finally:
        store.close()


def test_dispatch_at_terminal_and_waiting_stages():
    store, task, context = _setup(owner="p4-disp", session="p4-s6", trace="p4-t6")
    try:
        _seed_plan(store, task, context, "waiting_for_data",
                   _references(strategy_version=STRATEGY))
        assert store.plan_continuation_dispatch(task, trusted_context=context)["kind"] == "waiting"
    finally:
        store.close()
