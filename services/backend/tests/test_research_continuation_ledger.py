"""ResearchTask business-action cutover contracts.

The former continuation-event ledger was current workflow state. These tests
exercise its replacement: an exact approval and pending action commit
atomically, then reconcile only by the action identity after commit.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.agent_research import AgentConflict, AgentResearchStore
from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchNotFound, ResearchPersistenceError, ResearchStore
from packages.contracts.research_execution_plan import plan_at_stage
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")

TASK = "task_" + "a" * 32
STRATEGY = "artifact_" + "d" * 32
BACKTEST_TASK = "backtesttask_" + "f" * 32
BACKTEST_JOB = "backtest_" + "3" * 32
RESULT = "artifact_" + "4" * 32
APPROVAL_DIGEST = "sha256:" + "a" * 64


def _setup(owner: str = "action-user", session: str = "action-session", trace: str = "action-trace"):
    headers = trusted_agent_context(owner, session_id=session, trace_id=trace)
    context = {key.removeprefix("x-byq-").replace("-", "_"): value for key, value in headers.items()}
    catalog = ConversationCatalogStore()
    catalog.create(owner, session, trace)
    catalog.close()
    store = ResearchStore()
    task = store.create_task(
        {"owner_principal": owner, "title": "Action task", "objective": "No execution",
         "trace_id": trace, "idempotency_key": f"{owner}-task"},
        trusted_context=context,
    )
    return store, task["task_id"], context


def _task_row(store, task):
    return store._fetch_one("SELECT * FROM research_tasks WHERE task_id = :task", {"task": task})


def _references(**extra: str):
    return {kind: {kind: identity} for kind, identity in extra.items()}


def _approval(action: str, resource_kind: str, resource_id: str, *, plan: int = 1,
               task: int = 1, params_digest: str | None = APPROVAL_DIGEST):
    approval = {"action": action, "resource_kind": resource_kind, "resource_id": resource_id,
                "plan_version": plan, "task_version": task}
    if params_digest is not None:
        approval["params_digest"] = params_digest
    return approval


def _seed_plan(store, task, context, stage, references, approval=None, iteration=1):
    row = _task_row(store, task)
    plan = plan_at_stage(
        task_id=task, owner_principal=row["owner_principal"], workspace_id=row["workspace_id"],
        conversation_id=row["conversation_id"], task_version=row["version"], stage=stage,
        idempotency_key="seed-plan", references=references, approval=approval, iteration=iteration,
    )
    store._execute("""INSERT INTO research_execution_plans
        (task_id, owner_principal, workspace_id, conversation_id, plan_version, task_version,
         stage, iteration, status, next_action, plan, idempotency_key, request_hash,
         legacy_reason, created_at, updated_at)
        VALUES (:task, :owner, :workspace, :conversation, :plan_version, :task_version, :stage,
                :iteration, :status, :next_action, :plan, :idempotency_key, 'seed', NULL, now(), now())""",
        {"task": task, "owner": row["owner_principal"], "workspace": row["workspace_id"],
         "conversation": row["conversation_id"], "plan_version": plan["plan_version"],
         "task_version": plan["task_version"], "stage": plan["stage"],
         "iteration": plan["iteration"], "status": plan["status"],
         "next_action": plan["next_action"], "plan": plan,
         "idempotency_key": plan["idempotency_key"]})
    return plan


def _create_artifact(store, task, *, kind: str, key: str):
    artifact = store.create_artifact({
        "task_id": task, "kind": kind, "content": {"synthetic": key}, "lineage": [],
        "trace_id": _task_row(store, task)["trace_id"], "idempotency_key": key})
    return artifact["artifact_id"]


def _insert_backtest_job(store, task, context, *, job_id: str, status: str,
                         result_id: str | None, key: str):
    store._execute("""INSERT INTO backtest_jobs
        (job_id, task_id, owner_principal, status, request_json, request_hash,
         input_manifest_id, input_manifest_json, strategy_version_artifact_id,
         approval_artifact_id, idempotency_key, attempts, max_attempts, result_artifact_id,
         created_at, updated_at)
        VALUES (:job, :task, :owner, :status, '{}'::jsonb, 'hash', 'manifest', '{}'::jsonb,
                :strategy, :approval, :key, 1, 3, :result, now(), now())""",
        {"job": job_id, "task": task, "owner": context["owner_principal"], "status": status,
         "strategy": STRATEGY, "approval": "artifact_" + "9" * 32,
         "key": key, "result": result_id})


def _approval_case(owner="action-bound", session="action-bound-session", trace="action-bound-trace"):
    store, task, context = _setup(owner=owner, session=session, trace=trace)
    agent = AgentResearchStore()
    run = agent.start_run({
        "owner_principal": owner, "actor_principal": f"agent-{owner}",
        "role_id": "quant_orchestrator", "trace_id": trace, "session_id": session,
        "dsh_run_id": session + "-dsh", "idempotency_key": owner + "-run"})
    strategy = _create_artifact(store, task, kind="strategy_version", key=owner + "-strategy")
    plan = _seed_plan(store, task, context, "waiting_for_strategy_approval",
        _references(strategy_version=strategy),
        approval=_approval("strategy_approve", "strategy_version", strategy,
                           task=_task_row(store, task)["version"], params_digest=None))
    request = store.request_plan_approval(task, trusted_context=context)
    assert request["action"] == "byq_strategy_approve"
    return store, agent, task, context, plan, request


def _decide(agent, context, approval_id, *, decision="approved", rationale=""):
    return agent.decide_approval(
        {"approval_id": approval_id, "decision": decision, "rationale": rationale},
        trusted_owner=context["owner_principal"], trusted_actor="human-reviewer",
        trusted_workspace=context["workspace_id"])


def _reconcile(store, task, context, action):
    return store.reconcile_research_task_action(
        task, action["action_id"], trusted_context={
            "owner_principal": context["owner_principal"],
            "workspace_id": context["workspace_id"],
        })


def test_approval_decision_and_action_roll_back_together(monkeypatch):
    import app.agent_research as agent_module

    store, agent, task, context, plan, request = _approval_case()
    try:
        def fail_insert(*_args, **_kwargs):
            raise RuntimeError("injected action insert failure")

        monkeypatch.setattr(agent_module, "insert_pending_approval_action", fail_insert)
        with pytest.raises(RuntimeError, match="injected action insert failure"):
            _decide(agent, context, request["approval_id"])
        approval = agent.get_approval(request["approval_id"], trusted_owner=context["owner_principal"])
        assert approval["status"] == "pending"
        assert approval["business_action"] is None
        assert store._fetch_one(
            "SELECT COUNT(*) AS n FROM research_task_actions WHERE task_id = :task", {"task": task})["n"] == 0
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == plan["plan_version"]
    finally:
        agent.close()
        store.close()


def test_exact_replay_recovers_crash_after_atomic_commit_before_plan_cas():
    store, agent, task, context, plan, request = _approval_case(owner="action-crash")
    try:
        first = _decide(agent, context, request["approval_id"], rationale="approve exact strategy")
        action = first["business_action"]
        assert action["status"] == "pending"
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == plan["plan_version"]

        # Model a process death after the approval/action transaction committed:
        # the identical POST returns the same action without duplicating it.
        replay = _decide(agent, context, request["approval_id"], rationale="approve exact strategy")
        assert replay["business_action"] == action
        assert store._fetch_one(
            "SELECT COUNT(*) AS n FROM research_task_actions WHERE task_id = :task", {"task": task})["n"] == 1

        resolved = _reconcile(store, task, context, action)
        assert resolved["status"] == "applied"
        assert store.get_execution_plan(task, trusted_context=context)["stage"] == "waiting_for_task_create_approval"
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == plan["plan_version"] + 1

        # A further identical POST/reconciliation returns the durable result and
        # cannot apply the plan CAS a second time.
        final = _decide(agent, context, request["approval_id"], rationale="approve exact strategy")
        assert final["business_action"]["status"] == "applied"
        assert _reconcile(store, task, context, action)["status"] == "applied"
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == plan["plan_version"] + 1
    finally:
        agent.close()
        store.close()


def test_conflicting_decision_rationale_or_source_is_rejected_before_redrive():
    store, agent, task, context, plan, request = _approval_case(owner="action-conflict")
    try:
        decided = _decide(agent, context, request["approval_id"], rationale="approved")
        with pytest.raises(AgentConflict):
            _decide(agent, context, request["approval_id"], decision="rejected", rationale="approved")
        with pytest.raises(AgentConflict):
            _decide(agent, context, request["approval_id"], rationale="changed rationale")

        # Altering an immutable source fact must conflict before the pending
        # action can be re-driven.
        agent._execute("UPDATE agent_approvals SET resource_id = :resource WHERE approval_id = :id", {
            "resource": "artifact_" + "b" * 32, "id": request["approval_id"]})
        with pytest.raises(AgentConflict):
            _decide(agent, context, request["approval_id"], rationale="approved")
        assert decided["business_action"]["status"] == "pending"
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == plan["plan_version"]
    finally:
        agent.close()
        store.close()


def test_decided_plan_approval_without_its_action_cannot_fall_back_to_compatibility():
    store, agent, task, context, _plan, request = _approval_case(owner="action-missing-row")
    try:
        action = _decide(agent, context, request["approval_id"])["business_action"]
        assert action["status"] == "pending"
        store._execute("DELETE FROM research_task_actions WHERE task_id = :task AND action_id = :action",
                       {"task": task, "action": action["action_id"]})
        with pytest.raises(AgentConflict, match="no exact business action"):
            agent.get_approval(request["approval_id"], trusted_owner=context["owner_principal"])
        with pytest.raises(AgentConflict, match="no exact business action"):
            agent.list_approvals(trusted_owner=context["owner_principal"])
    finally:
        agent.close()
        store.close()


def test_partial_and_stale_frozen_bindings_fail_closed_before_decision():
    store, agent, task, context, _plan, request = _approval_case(owner="action-partial")
    try:
        agent._execute("UPDATE agent_approvals SET plan_params_digest = NULL WHERE approval_id = :id",
                       {"id": request["approval_id"]})
        with pytest.raises(AgentConflict, match="incomplete"):
            _decide(agent, context, request["approval_id"])
        assert agent._fetch_one("SELECT status FROM agent_approvals WHERE approval_id = :id",
                                {"id": request["approval_id"]})["status"] == "pending"
        with pytest.raises(AgentConflict, match="incomplete"):
            agent.get_approval(request["approval_id"], trusted_owner=context["owner_principal"])
    finally:
        agent.close()
        store.close()

    store, agent, task, context, _plan, request = _approval_case(
        owner="action-stale", session="action-stale-session", trace="action-stale-trace")
    try:
        store.advance_execution_plan(task, {
            "expected_plan_version": 1, "expected_task_version": 1,
            "next_stage": "waiting_for_task_create_approval", "iteration": 1, "status": "waiting",
            "expected_postcondition": "next_round_task_create_approval_requested",
            "idempotency_key": "make-stale-plan",
            "references": _references(strategy_version=request["resource_id"]),
            "approval": _approval("backtest_task_create", "strategy_version", request["resource_id"],
                                  plan=2, params_digest=None)}, trusted_context=context)
        with pytest.raises(AgentConflict, match="stale"):
            _decide(agent, context, request["approval_id"])
        assert agent.get_approval(request["approval_id"], trusted_owner=context["owner_principal"])["status"] == "pending"
        assert store._fetch_one(
            "SELECT COUNT(*) AS n FROM research_task_actions WHERE task_id = :task", {"task": task})["n"] == 0
    finally:
        agent.close()
        store.close()


def test_concurrent_decision_and_reconcile_share_one_action_and_one_plan_cas():
    store, agent, task, context, plan, request = _approval_case(owner="action-race")
    decision_stores = [AgentResearchStore(), AgentResearchStore()]
    reconcile_stores = [ResearchStore(), ResearchStore()]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            decisions = list(pool.map(
                lambda local: _decide(local, context, request["approval_id"], rationale="same request"),
                decision_stores))
        actions = [item["business_action"] for item in decisions]
        assert actions[0] == actions[1]
        assert actions[0]["status"] == "pending"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda local: _reconcile(local, task, context, actions[0]), reconcile_stores))
        assert [item["status"] for item in results] == ["applied", "applied"]
        assert store._fetch_one(
            "SELECT COUNT(*) AS n FROM research_task_actions WHERE task_id = :task", {"task": task})["n"] == 1
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == plan["plan_version"] + 1
    finally:
        for local in decision_stores + reconcile_stores:
            local.close()
        agent.close()
        store.close()


def test_action_reconcile_is_owner_and_workspace_scoped():
    store, agent, task, context, _plan, request = _approval_case(owner="action-tenant")
    try:
        action = _decide(agent, context, request["approval_id"])["business_action"]
        for wrong in (
            {"owner_principal": "other-owner", "workspace_id": context["workspace_id"]},
            {"owner_principal": context["owner_principal"], "workspace_id": "workspace_other"},
        ):
            with pytest.raises(ResearchNotFound):
                store.reconcile_research_task_action(task, action["action_id"], trusted_context=wrong)
        assert agent.get_approval(request["approval_id"], trusted_owner=context["owner_principal"])[
            "business_action"]["status"] == "pending"
        assert _reconcile(store, task, context, action)["status"] == "applied"
    finally:
        agent.close()
        store.close()


def test_one_open_action_is_a_database_invariant():
    store, agent, task, context, _plan, request = _approval_case(owner="action-one-open")
    try:
        action = _decide(agent, context, request["approval_id"])["business_action"]
        row = store._fetch_one("SELECT * FROM research_task_actions WHERE task_id = :task",
                               {"task": task})
        with pytest.raises(ResearchPersistenceError):
            store._execute("""INSERT INTO research_task_actions
                (task_id, action_id, source_approval_id, owner_principal, workspace_id,
                 plan_version, task_version, action, resource_kind, resource_id, params_digest,
                 idempotency_key, source_digest, request_digest, decision, status, result_json,
                 created_at, updated_at)
                VALUES (:task, :action, :approval, :owner, :workspace, :plan_version, :task_version,
                        :action_name, :kind, :resource, :params_digest, :key, :source, :request,
                        'approved', 'pending', '{}'::jsonb, now(), now())""", {
                "task": task, "action": "research_action_" + "f" * 32,
                "approval": "agent_approval_" + "f" * 32, "owner": row["owner_principal"],
                "workspace": row["workspace_id"], "plan_version": row["plan_version"],
                "task_version": row["task_version"], "action_name": row["action"],
                "kind": row["resource_kind"], "resource": row["resource_id"],
                "params_digest": row["params_digest"], "key": "second-open-key",
                "source": row["source_digest"], "request": row["request_digest"],
            })
        assert store._fetch_one(
            "SELECT COUNT(*) AS n FROM research_task_actions WHERE task_id = :task", {"task": task})["n"] == 1
        assert _reconcile(store, task, context, action)["status"] == "applied"
    finally:
        agent.close()
        store.close()


def test_waiting_for_agent_stays_open_and_has_no_worker_claim_or_settle_path():
    from app.research_task_actions import ResearchTaskActionMixin

    store, agent, task, context, plan, request = _approval_case(owner="action-agent-wait")
    try:
        action = _decide(agent, context, request["approval_id"])["business_action"]
        store._execute("UPDATE research_task_actions SET status = 'waiting_for_agent'"
                       " WHERE task_id = :task AND action_id = :action",
                       {"task": task, "action": action["action_id"]})
        waiting = _reconcile(store, task, context, action)
        assert waiting["status"] == "waiting_for_agent"
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == plan["plan_version"]
        assert not any(hasattr(ResearchTaskActionMixin, name) for name in (
            "claim_research_task_action", "settle_research_task_action"))
    finally:
        agent.close()
        store.close()


def test_deterministic_job_action_requires_exact_terminal_job_and_validated_artifact():
    store, task, context = _setup(owner="action-job-proof")
    try:
        _seed_plan(store, task, context, "ready_to_execute_backtest_task",
                   _references(backtest_task=BACKTEST_TASK),
                   approval=_approval("backtest_execute", "backtest_task", BACKTEST_TASK,
                                      task=_task_row(store, task)["version"], params_digest=None))
        _insert_backtest_job(store, task, context, job_id=BACKTEST_JOB, status="queued",
                             result_id=None, key="job-proof")
        with pytest.raises(Exception, match="exact completed backtest job"):
            store.apply_deterministic_action_result(
                task, {"backtest_job_id": BACKTEST_JOB}, trusted_context=context)
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == 1

        result_id = _create_artifact(store, task, kind="backtest_result", key="job-proof-result")
        store.transition("artifact", result_id, "validated", "job-proof-result-validate")
        store._execute("UPDATE backtest_jobs SET status = 'completed', result_artifact_id = :result"
                       " WHERE job_id = :job", {"result": result_id, "job": BACKTEST_JOB})
        advanced = store.apply_deterministic_action_result(
            task, {"backtest_job_id": BACKTEST_JOB}, trusted_context=context)
        assert advanced["stage"] == "waiting_for_backtest_job" and advanced["plan_version"] == 2
        replay = store.apply_deterministic_action_result(
            task, {"backtest_job_id": BACKTEST_JOB}, trusted_context=context)
        assert replay["plan_version"] == 2
    finally:
        store.close()
