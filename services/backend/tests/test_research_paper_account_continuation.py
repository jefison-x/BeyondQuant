"""ADR-0087 deterministic paper-account approval and creation contract tests.

These exercise the closed plan/approval/action path that closes the P4-B
blocker: final selection enters `waiting_for_paper_account_approval`; the exact
plan-command-bound `paper_account_create` approval is minted server-side; the
human decision advances the plan to `ready_to_create_paper_account`; BYQ derives
the deterministic account parameters; the trusted consumer creates the account
through the real Product API boundary; and the deterministic action CAS commits
the account reference and completes the ResearchTask.

Fail-closed: missing/wrong/stale/denied approval, foreign owner/workspace, a
foreign account, and duplicate creation all refuse and never complete.
"""

import os

import pytest

from app.agent_research import AgentResearchStore
from app.paper_trading import PaperTradingStore
from app.research import InvalidTransition, ResearchStore
from packages.contracts.research_continuation_event import (
    plan_command_digest,
    plan_command_idempotency_key,
)
from tests.test_research_continuation_ledger import (
    _approval,
    _references,
    _seed_plan,
    _setup,
    _task_row,
)

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"),
                                reason="isolated PostgreSQL required")


def _start_bound_run(owner, session, trace, *, key):
    agent = AgentResearchStore()
    agent.start_run({
        "owner_principal": owner, "actor_principal": f"byq-product-agent-{session}",
        "role_id": "quant_orchestrator", "trace_id": trace, "session_id": session,
        "dsh_run_id": session + "-dsh", "idempotency_key": key + "-run"})
    return agent


def _gate_approval(store, task, stage="waiting_for_paper_account_approval"):
    return _approval("create_paper_account", "research_task", task, plan=1,
                     task=_task_row(store, task)["version"], params_digest=None)


def _seed_gate(store, task, context, *, extra_references=None):
    refs = _references(research_task=task)
    if extra_references:
        refs.update(extra_references)
    return _seed_plan(
        store, task, context, "waiting_for_paper_account_approval",
        refs, approval=_gate_approval(store, task))


def _validated_result_artifact(store, task, *, key):
    row = _task_row(store, task)
    artifact = store.create_artifact({
        "task_id": task, "kind": "backtest_result", "content": {"synthetic": key},
        "lineage": [], "trace_id": row["trace_id"], "idempotency_key": key})
    store.transition("artifact", artifact["artifact_id"], "validated", key + "-validate")
    return artifact["artifact_id"]


def _decide_and_advance(store, agent, context, approval_id, decision="approved"):
    agent.decide_approval(
        {"approval_id": approval_id, "decision": decision},
        trusted_owner=context["owner_principal"], trusted_actor="human-reviewer")
    target = agent.plan_bound_approval_target(
        approval_id, trusted_owner=context["owner_principal"])
    if decision == "approved":
        store.record_plan_approval_event(
            target["task_id"], approval_id,
            trusted_context={"owner_principal": target["owner_principal"],
                             "workspace_id": target["workspace_id"]})


def _create_account(store, task, *, key, name=None):
    row = _task_row(store, task)
    pt = PaperTradingStore()
    try:
        return pt.create_account(
            {"name": name or f"test-{task[-8:]}", "cash": "100000", "idempotency_key": key},
            trusted_owner=row["owner_principal"], trusted_workspace=row["workspace_id"])
    finally:
        pt.close()


def test_legal_paper_account_approval_creates_once_and_completes():
    store, task, context = _setup(owner="pa-user", session="pa-s", trace="pa-t")
    agent = None
    try:
        agent = _start_bound_run(context["owner_principal"], "pa-s", "pa-t", key="pa")
        store.transition("research_task", task, "running", "pa-running")
        artifact_id = _validated_result_artifact(store, task, key="pa-result")
        plan = _seed_gate(store, task, context, extra_references={
            "backtest_result": {"backtest_result": artifact_id}})
        request = store.request_plan_approval(task, trusted_context=context)
        assert request["action"] == "byq_paper_account_create"
        assert request["resource_type"] == "research_task"
        approval = store._fetch_one("SELECT * FROM agent_approvals WHERE approval_id = :id",
                                    {"id": request["approval_id"]})
        assert approval["plan_action"] == "create_paper_account"
        assert approval["plan_resource_kind"] == "research_task"
        assert approval["plan_resource_id"] == task
        assert approval["plan_params_digest"] == plan_command_digest(
            plan, action="create_paper_account", resource_kind="research_task", resource_id=task)
        assert approval["plan_idempotency_key"] == plan_command_idempotency_key(
            plan, action="create_paper_account", resource_kind="research_task", resource_id=task)
        _decide_and_advance(store, agent, context, request["approval_id"])
        assert store.get_execution_plan(task, trusted_context=context)["stage"] == \
            "ready_to_create_paper_account"

        params = store.paper_account_create_parameters(task, trusted_context=context)
        assert params["action"] == "create_paper_account"
        assert params["resource_kind"] == "research_task" and params["resource_id"] == task
        assert params["name"].startswith("research-paper-") and params["cash"] == "100000.0000"
        # ADR-0087 exact freeze: the executed params digest/key EQUAL the approved
        # frozen binding, even though the plan advanced one plan_version.
        assert params["params_digest"] == approval["plan_params_digest"]
        assert params["idempotency_key"] == approval["plan_idempotency_key"]
        assert params["approval_id"] == request["approval_id"]
        assert params["approval_plan_version"] + 1 == params["plan_version"]
        assert params["idempotency_key"].startswith("plancmd_")

        # Real Product API / PaperTradingStore idempotent creation.
        account = _create_account(store, task, key=params["idempotency_key"], name=params["name"])
        replay = _create_account(store, task, key=params["idempotency_key"], name=params["name"])
        assert account["account_id"] == replay["account_id"]
        assert store._fetch_one("SELECT COUNT(*) AS c FROM paper_accounts")["c"] == 1

        advanced = store.apply_deterministic_action_result(
            task, {"paper_account_id": account["account_id"]}, trusted_context=context)
        assert advanced["stage"] == "completed" and advanced["status"] == "completed"
        persisted = store._fetch_one(
            "SELECT plan FROM research_execution_plans WHERE task_id = :t", {"t": task})["plan"]
        assert persisted["references"]["paper_account"]["paper_account"] == account["account_id"]
        replay_apply = store.apply_deterministic_action_result(
            task, {"paper_account_id": account["account_id"]}, trusted_context=context)
        assert replay_apply["plan_version"] == advanced["plan_version"]
        row = _task_row(store, task)
        assert row["status"] == "completed"
        assert row["progress"]["stage"] == "completed"
        # No orders/positions/fills are created by account creation.
        for table in ("paper_orders", "paper_positions", "paper_fills"):
            assert store._fetch_one(f"SELECT COUNT(*) AS c FROM {table}")["c"] == 0
    finally:
        store.close()
        if agent is not None:
            agent.close()


def test_denied_paper_account_approval_never_advances():
    store, task, context = _setup(owner="pa-deny", session="pa-s2", trace="pa-t2")
    agent = None
    try:
        agent = _start_bound_run(context["owner_principal"], "pa-s2", "pa-t2", key="pa2")
        plan = _seed_gate(store, task, context)
        request = store.request_plan_approval(task, trusted_context=context)
        _decide_and_advance(store, agent, context, request["approval_id"], decision="rejected")
        assert _task_row(store, task)["status"] != "completed"
        # The gate stays waiting; no account can be derived.
        assert store._fetch_one("SELECT COUNT(*) AS c FROM paper_accounts")["c"] == 0
        with pytest.raises(InvalidTransition):
            store.paper_account_create_parameters(task, trusted_context=context)
    finally:
        store.close()
        if agent is not None:
            agent.close()


def test_foreign_owner_or_workspace_cannot_request_or_create():
    store, task, context = _setup(owner="pa-owner", session="pa-s3", trace="pa-t3")
    try:
        _seed_gate(store, task, context)
        foreign = {"owner_principal": "someone-else", "workspace_id": context["workspace_id"]}
        with pytest.raises(Exception):
            store.request_plan_approval(task, trusted_context=foreign)
        with pytest.raises(Exception):
            store.paper_account_create_parameters(task, trusted_context=foreign)
    finally:
        store.close()


def test_stale_approval_binding_is_rejected():
    store, task, context = _setup(owner="pa-stale", session="pa-s4", trace="pa-t4")
    agent = None
    try:
        agent = _start_bound_run(context["owner_principal"], "pa-s4", "pa-t4", key="pa4")
        plan = _seed_gate(store, task, context)
        request = store.request_plan_approval(task, trusted_context=context)
        # Advance the plan underneath the approval (simulated stale binding).
        store._execute("UPDATE research_execution_plans SET plan_version = plan_version + 1"
                       " WHERE task_id = :task", {"task": task})
        agent.decide_approval(
            {"approval_id": request["approval_id"], "decision": "approved"},
            trusted_owner=context["owner_principal"], trusted_actor="human-reviewer")
        with pytest.raises(Exception):
            store.record_plan_approval_event(
                task, request["approval_id"],
                trusted_context={"owner_principal": context["owner_principal"],
                                 "workspace_id": context["workspace_id"]})
        assert _task_row(store, task)["status"] != "completed"
    finally:
        store.close()
        if agent is not None:
            agent.close()


def test_foreign_account_is_refused_and_never_completes():
    store, task, context = _setup(owner="pa-acct", session="pa-s5", trace="pa-t5")
    other = None
    try:
        store.transition("research_task", task, "running", "pa5-run")
        _seed_plan(store, task, context, "ready_to_create_paper_account",
                   _references(research_task=task), approval=_gate_approval(store, task))
        # An account owned by a different owner must be refused.
        other_store, other_task, other_context = _setup(
            owner="pa-other", session="pa-s5b", trace="pa-t5b")
        other = other_store
        foreign = _create_account(other_store, other_task, key="pa-foreign-account")
        with pytest.raises(InvalidTransition):
            store.apply_deterministic_action_result(
                task, {"paper_account_id": foreign["account_id"]}, trusted_context=context)
        assert _task_row(store, task)["status"] != "completed"
    finally:
        if other is not None:
            other.close()
        store.close()


def test_tampered_plan_frozen_digest_is_rejected():
    store, task, context = _setup(owner="pa-tamper", session="pa-s7", trace="pa-t7")
    agent = None
    try:
        agent = _start_bound_run(context["owner_principal"], "pa-s7", "pa-t7", key="pa7")
        store.transition("research_task", task, "running", "pa7-run")
        _seed_gate(store, task, context)
        request = store.request_plan_approval(task, trusted_context=context)
        _decide_and_advance(store, agent, context, request["approval_id"])
        assert store.paper_account_create_parameters(
            task, trusted_context=context)["approval_id"] == request["approval_id"]
        # A tampered plan digest (another legal sha256) fails closed.
        store._execute(
            "UPDATE research_execution_plans SET plan = jsonb_set(plan,"
            " '{approval,params_digest}', to_jsonb(('sha256:' || repeat('f',64))::text))"
            " WHERE task_id = :task", {"task": task})
        with pytest.raises(InvalidTransition):
            store.paper_account_create_parameters(task, trusted_context=context)
    finally:
        store.close()
        if agent is not None:
            agent.close()


def test_tampered_approval_row_digest_or_key_is_rejected():
    store, task, context = _setup(owner="pa-tamper2", session="pa-s8", trace="pa-t8")
    agent = None
    try:
        agent = _start_bound_run(context["owner_principal"], "pa-s8", "pa-t8", key="pa8")
        store.transition("research_task", task, "running", "pa8-run")
        _seed_gate(store, task, context)
        request = store.request_plan_approval(task, trusted_context=context)
        _decide_and_advance(store, agent, context, request["approval_id"])
        # Tamper the approval row's digest.
        store._execute(
            "UPDATE agent_approvals SET plan_params_digest = 'sha256:' || repeat('a',64)"
            " WHERE approval_id = :id", {"id": request["approval_id"]})
        with pytest.raises(InvalidTransition):
            store.paper_account_create_parameters(task, trusted_context=context)
    finally:
        store.close()
        if agent is not None:
            agent.close()


def test_paper_account_segment_makes_zero_model_calls():
    store, task, context = _setup(owner="pa-zero", session="pa-s6", trace="pa-t6")
    agent = None
    try:
        agent = _start_bound_run(context["owner_principal"], "pa-s6", "pa-t6", key="pa6")
        store.transition("research_task", task, "running", "pa6-run")
        artifact_id = _validated_result_artifact(store, task, key="pa6-result")
        _seed_gate(store, task, context, extra_references={
            "backtest_result": {"backtest_result": artifact_id}})
        request = store.request_plan_approval(task, trusted_context=context)
        _decide_and_advance(store, agent, context, request["approval_id"])
        params = store.paper_account_create_parameters(task, trusted_context=context)
        account = _create_account(store, task, key=params["idempotency_key"], name=params["name"])
        store.apply_deterministic_action_result(
            task, {"paper_account_id": account["account_id"]}, trusted_context=context)
        # No research-judgment stage call / model turn happened in this segment.
        assert store._fetch_one(
            "SELECT COUNT(*) AS c FROM research_judgment_stage_calls")["c"] == 0
    finally:
        store.close()
        if agent is not None:
            agent.close()
