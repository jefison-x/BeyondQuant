"""ADR-0085 P2 durable continuation ledger tests (authoritative adapters).

These exercise the INTERNAL Backend seam used by the deterministic reducer:
named adapters that load authoritative records, at-most-once open admission,
task/plan CAS, replay/key-reuse conflict, stale/late events, durable pending
retry intents (claim/settle across restart), owner/workspace isolation and
bounded projections. There is no agent-facing HTTP/MCP write route for a plan
or an event.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.agent_research import AgentResearchStore
from app.conversation_catalog import ConversationCatalogStore
from app.research import IdempotencyConflict, ResearchNotFound, ResearchStore
from app.research_continuation_ledger import (
    ContinuationClaimConflict,
    ContinuationInProgress,
    ContinuationTriggerRequired,
    project_continuation_event,
)
from packages.contracts.research_execution_plan import plan_at_stage
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")

TASK = "task_" + "a" * 32
STRATEGY = "artifact_" + "d" * 32
BACKTEST_TASK = "backtesttask_" + "f" * 32
BACKTEST_JOB = "backtest_" + "3" * 32
RESULT = "artifact_" + "4" * 32
APPROVAL_DIGEST = "sha256:" + "a" * 64


def _setup(owner: str = "ledger-user", session: str = "ledger-session", trace: str = "ledger-trace"):
    headers = trusted_agent_context(owner, session_id=session, trace_id=trace)
    context = {key.removeprefix("x-byq-").replace("-", "_"): value for key, value in headers.items()}
    catalog = ConversationCatalogStore()
    catalog.create(owner, session, trace)
    catalog.close()
    store = ResearchStore()
    task = store.create_task(
        {"owner_principal": owner, "title": "Ledger task", "objective": "No execution",
         "trace_id": trace, "idempotency_key": f"{owner}-task"},
        trusted_context=context,
    )
    return store, task["task_id"], context


def _task_row(store, task):
    return store._fetch_one("SELECT * FROM research_tasks WHERE task_id = :task", {"task": task})


def _references(**extra: str):
    return {kind: {kind: identity} for kind, identity in extra.items()}


def _approval(action: str, resource_kind: str, resource_id: str, *, plan: int = 1, task: int = 1,
               params_digest: str | None = APPROVAL_DIGEST):
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


def _execute_gate_plan(store, task, context):
    references = _references(backtest_task=BACKTEST_TASK)
    return _seed_plan(store, task, context, "waiting_for_task_execute_approval", references,
                      approval=_approval("backtest_execute", "backtest_task", BACKTEST_TASK, plan=1))


def _create_artifact(store, task, *, kind: str, key: str):
    return store.create_artifact({
        "task_id": task, "kind": kind, "content": {"synthetic": key}, "lineage": [],
        "trace_id": _task_row(store, task)["trace_id"], "idempotency_key": key})


def _agent_approval(owner: str, session: str, trace: str, *, action: str, resource_type: str,
                    resource_id: str, decision: str = "approved", key: str = "agent-approval"):
    agent = AgentResearchStore()
    try:
        run = agent.start_run({
            "owner_principal": owner, "actor_principal": owner, "role_id": "quant_orchestrator",
            "trace_id": trace, "session_id": session, "dsh_run_id": session + "-dsh",
            "idempotency_key": key + "-run"})
        approval = agent.create_approval({
            "run_id": run["run_id"], "action": action, "reason": "review",
            "resource_type": resource_type, "resource_id": resource_id,
            "idempotency_key": key})
        if decision is not None:
            agent.decide_approval({"approval_id": approval["approval_id"], "decision": decision},
                                  trusted_owner=owner, trusted_actor="human-reviewer")
        return approval["approval_id"]
    finally:
        agent.close()


# --------------------------------------------------------------------------- #
# plan_approval: real agent decision, exact binding
# --------------------------------------------------------------------------- #

def test_plan_approval_adapter_advances_from_the_real_agent_decision():
    store, task, context = _setup()
    try:
        artifact = _create_artifact(store, task, kind="strategy_version", key="strategy-v1")
        references = _references(strategy_version=artifact["artifact_id"])
        _seed_plan(store, task, context, "waiting_for_strategy_approval", references,
                   approval=_approval("strategy_approve", "strategy_version",
                                      artifact["artifact_id"], plan=1, params_digest=None))
        approval_id = _agent_approval(context["owner_principal"], context["session_id"],
                                      context["trace_id"], action="byq_strategy_approve",
                                      resource_type="strategy_version",
                                      resource_id=artifact["artifact_id"])
        first = store.record_plan_approval_event(task, approval_id, trusted_context=context)
        assert first["status"] == "advanced" and first["outcome"] == "advance"
        assert first["next_stage"] == "waiting_for_task_create_approval"
        plan = store.get_execution_plan(task, trusted_context=context)
        assert plan["stage"] == "waiting_for_task_create_approval" and plan["plan_version"] == 2
        # The next gate carries a BYQ-derived command digest, not a caller value.
        assert plan["approval"]["params_digest"].startswith("sha256:")
        # Exact replay is served from the durable ledger row, no second advance.
        assert store.record_plan_approval_event(task, approval_id, trusted_context=context) == first
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == 2
    finally:
        store.close()


def test_plan_approval_adapter_refuses_pending_foreign_and_digest_forged():
    store, task, context = _setup()
    try:
        artifact = _create_artifact(store, task, kind="strategy_version", key="strategy-v2")
        references = _references(strategy_version=artifact["artifact_id"])
        _seed_plan(store, task, context, "waiting_for_strategy_approval", references,
                   approval=_approval("strategy_approve", "strategy_version",
                                      artifact["artifact_id"], plan=1, params_digest=None))
        # An undecided approval can never advance the plan.
        pending_id = _agent_approval(context["owner_principal"], context["session_id"],
                                     context["trace_id"], action="byq_strategy_approve",
                                     resource_type="strategy_version",
                                     resource_id=artifact["artifact_id"], decision=None,
                                     key="pending-approval")
        with pytest.raises(ValueError):
            store.record_plan_approval_event(task, pending_id, trusted_context=context)
        # An approval owned by another principal cannot advance this task.
        other, _other_task, other_context = _setup(
            owner="ledger-intruder", session="ledger-session-x", trace="ledger-trace-x")
        try:
            foreign_id = _agent_approval(
                other_context["owner_principal"], other_context["session_id"],
                other_context["trace_id"], action="byq_strategy_approve",
                resource_type="strategy_version", resource_id=artifact["artifact_id"],
                key="foreign-approval")
            with pytest.raises(ValueError):
                store.record_plan_approval_event(task, foreign_id, trusted_context=context)
        finally:
            other.close()
        # A plan whose persisted digest was tampered with fails closed.
        store._execute("""UPDATE research_execution_plans SET plan = jsonb_set(
                plan, '{approval,params_digest}', to_jsonb('sha256:' || repeat('0', 64)::text))
            WHERE task_id = :task""", {"task": task})
        forged_id = _agent_approval(context["owner_principal"], context["session_id"],
                                    context["trace_id"], action="byq_strategy_approve",
                                    resource_type="strategy_version",
                                    resource_id=artifact["artifact_id"], key="forged-approval")
        with pytest.raises(ValueError):
            store.record_plan_approval_event(task, forged_id, trusted_context=context)
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == 1
    finally:
        store.close()


def _plan_gate(store, task, context, *, key="strategy-gate"):
    artifact = _create_artifact(store, task, kind="strategy_version", key=key)
    references = _references(strategy_version=artifact["artifact_id"])
    plan = _seed_plan(store, task, context, "waiting_for_strategy_approval", references,
                      approval=_approval("strategy_approve", "strategy_version",
                                         artifact["artifact_id"], plan=1, params_digest=None))
    return artifact, plan


def _approval_binding(store, approval_id):
    return store._fetch_one("""SELECT plan_task_id, plan_workspace_id, plan_version,
        plan_task_version, plan_action, plan_resource_kind, plan_resource_id,
        plan_params_digest, plan_idempotency_key
        FROM agent_approvals WHERE approval_id = :id""", {"id": approval_id})


def test_plan_approval_binding_is_frozen_at_request_time_and_never_unlocks_a_newer_plan():
    store, task, context = _setup()
    try:
        artifact, _plan = _plan_gate(store, task, context)
        approval_id = _agent_approval(
            context["owner_principal"], context["session_id"], context["trace_id"],
            action="byq_strategy_approve", resource_type="strategy_version",
            resource_id=artifact["artifact_id"], decision=None, key="frozen-1")
        binding = _approval_binding(store, approval_id)
        assert binding["plan_task_id"] == task and binding["plan_version"] == 1
        assert binding["plan_task_version"] == 1 and binding["plan_action"] == "strategy_approve"
        assert binding["plan_params_digest"].startswith("sha256:")
        assert binding["plan_idempotency_key"].startswith("plancmd_")
        # Advance the plan to v2 while the v1 approval is still unused.
        store.advance_execution_plan(task, {
            "expected_plan_version": 1, "expected_task_version": 1,
            "next_stage": "waiting_for_task_create_approval", "iteration": 1, "status": "waiting",
            "expected_postcondition": "next_round_task_create_approval_requested",
            "idempotency_key": "plan-v2",
            "references": _references(strategy_version=artifact["artifact_id"]),
            "approval": _approval("backtest_task_create", "strategy_version",
                                  artifact["artifact_id"], plan=2, params_digest=None)},
            trusted_context=context)
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == 2
        agent = AgentResearchStore()
        try:
            agent.decide_approval({"approval_id": approval_id, "decision": "approved"},
                                  trusted_owner=context["owner_principal"],
                                  trusted_actor="human-reviewer")
        finally:
            agent.close()
        # The stale v1 approval must NOT unlock v2.
        with pytest.raises(ValueError):
            store.record_plan_approval_event(task, approval_id, trusted_context=context)
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == 2
    finally:
        store.close()


def test_plan_approval_binding_rejects_an_altered_command_parameter():
    import json

    store, task, context = _setup()
    try:
        artifact, _plan = _plan_gate(store, task, context)
        approval_id = _agent_approval(
            context["owner_principal"], context["session_id"], context["trace_id"],
            action="byq_strategy_approve", resource_type="strategy_version",
            resource_id=artifact["artifact_id"], key="alter-1")
        # Keep action/resource and plan version, but alter a referenced command
        # parameter; the frozen parameter digest must no longer match.
        extra = json.dumps({"stock_pool_snapshot": "poolsnap_" + "a" * 32})
        store._execute("""UPDATE research_execution_plans
            SET plan = jsonb_set(plan, '{references,stock_pool_snapshot}', CAST(:extra AS jsonb))
            WHERE task_id = :task""", {"extra": extra, "task": task})
        with pytest.raises(ValueError):
            store.record_plan_approval_event(task, approval_id, trusted_context=context)
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == 1
    finally:
        store.close()


def test_plan_approval_binding_rejects_wrong_task_workspace_version_digest_and_key():
    store, task, context = _setup()
    try:
        artifact, _plan = _plan_gate(store, task, context)
        corruptions = (
            ("plan_task_id", "task_" + "9" * 32),
            ("plan_workspace_id", "workspace_" + "9" * 32),
            ("plan_version", 99),
            ("plan_params_digest", "sha256:" + "0" * 64),
            ("plan_idempotency_key", "plancmd_" + "0" * 32),
        )
        for index, (field, value) in enumerate(corruptions):
            approval_id = _agent_approval(
                context["owner_principal"], context["session_id"], context["trace_id"],
                action="byq_strategy_approve", resource_type="strategy_version",
                resource_id=artifact["artifact_id"], key=f"corrupt-{index}")
            store._execute(
                f"UPDATE agent_approvals SET {field} = :value WHERE approval_id = :id",
                {"value": value, "id": approval_id})
            with pytest.raises(ValueError):
                store.record_plan_approval_event(task, approval_id, trusted_context=context)
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == 1
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# data_ready: exact signal job identity, no recency
# --------------------------------------------------------------------------- #

def test_data_ready_adapter_uses_exact_job_identity(monkeypatch, tmp_path):
    from tests.test_data_ready_continuation import setup_ready
    import app.research_continuation_ledger as ledger_module

    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, context = fixture["store"], fixture["payload"]["task_id"], fixture["context"]
    derived_task = "backtesttask_" + "b" * 32
    monkeypatch.setattr(ledger_module, "_data_ready_executable", lambda connection, task_row, job: {
        "backtest_task_id": derived_task, "phase": "ready", "next_action": "execute",
        "references": {"signal_snapshot_artifact_id": fixture["artifact_id"],
                       "signal_producer_job_id": fixture["job_id"]},
    })
    try:
        _seed_plan(store, task, context, "waiting_for_data",
                   _references(strategy_version=STRATEGY,
                               signal_producer_job=fixture["job_id"]))
        event = store.record_data_ready_event(task, fixture["job_id"], trusted_context=context)
        assert event["status"] == "advanced"
        plan = store.get_execution_plan(task, trusted_context=context)
        assert plan["stage"] == "waiting_for_task_execute_approval"
        assert plan["approval"]["resource_id"] == derived_task
        # A job that does not belong to this task is refused outright.
        with pytest.raises(ValueError):
            store.record_data_ready_event(task, "signaljob_" + "9" * 32, trusted_context=context)
    finally:
        store.close()
        fixture["backtests"].close()
        fixture["jobs"].close()


def test_data_ready_adapter_never_selects_the_latest_job(monkeypatch, tmp_path):
    from tests.test_data_ready_continuation import setup_ready, add_ready_event
    import app.research_continuation_ledger as ledger_module

    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, context = fixture["store"], fixture["payload"]["task_id"], fixture["context"]
    other_job, other_artifact = add_ready_event(fixture, key="second-ready", content={"n": 2})
    derived = {fixture["job_id"]: "backtesttask_" + "1" * 32,
               other_job: "backtesttask_" + "2" * 32}
    monkeypatch.setattr(ledger_module, "_data_ready_executable",
                        lambda connection, task_row, job: {
                            "backtest_task_id": derived[job["job_id"]], "phase": "ready",
                            "next_action": "execute",
                            "references": {"signal_snapshot_artifact_id": job["result_artifact_id"],
                                           "signal_producer_job_id": job["job_id"]}})
    try:
        # The plan waits on the FIRST exact job; the newer job is a late source.
        _seed_plan(store, task, context, "waiting_for_data",
                   _references(strategy_version=STRATEGY, signal_producer_job=fixture["job_id"]))
        late = store.record_data_ready_event(task, other_job, trusted_context=context)
        assert late["status"] == "needs_attention"
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == 1
        exact = store.record_data_ready_event(task, fixture["job_id"], trusted_context=context)
        assert exact["status"] == "advanced"
    finally:
        store.close()
        fixture["backtests"].close()
        fixture["jobs"].close()


# --------------------------------------------------------------------------- #
# backtest_completed: exact backtest job identity, no recency
# --------------------------------------------------------------------------- #

def _insert_backtest_job(store, task, context, *, job_id: str, status: str, result_id: str | None,
                         key: str):
    store._execute("""INSERT INTO backtest_jobs
        (job_id, task_id, owner_principal, status, request_json, request_hash,
         input_manifest_id, input_manifest_json, strategy_version_artifact_id,
         approval_artifact_id, idempotency_key, attempts, max_attempts, result_artifact_id,
         created_at, updated_at)
        VALUES (:job, :task, :owner, :status, '{}'::jsonb, 'hash', 'manifest', '{}'::jsonb,
                :strategy, :approval, :key, 1, 3, :result, now(), now())""",
        {"job": job_id, "task": task, "owner": context["owner_principal"], "status": status,
         "strategy": STRATEGY, "approval": "artifact_" + "9" * 32, "key": key, "result": result_id})


def test_backtest_completed_adapter_uses_exact_job_identity():
    store, task, context = _setup()
    try:
        references = {**_references(backtest_task=BACKTEST_TASK),
                      "backtest_job": {"backtest_job": BACKTEST_JOB}}
        _seed_plan(store, task, context, "waiting_for_backtest_job", references)
        _insert_backtest_job(store, task, context, job_id=BACKTEST_JOB, status="completed",
                             result_id=RESULT, key="bt-completed")
        event = store.record_backtest_completed_event(task, BACKTEST_JOB, trusted_context=context)
        assert event["status"] == "advanced"
        assert store.get_execution_plan(task, trusted_context=context)["stage"] == "backtest_analysis"
    finally:
        store.close()


def test_backtest_completed_adapter_never_selects_the_latest_job():
    store, task, context = _setup()
    try:
        references = {**_references(backtest_task=BACKTEST_TASK),
                      "backtest_job": {"backtest_job": BACKTEST_JOB}}
        _seed_plan(store, task, context, "waiting_for_backtest_job", references)
        _insert_backtest_job(store, task, context, job_id=BACKTEST_JOB, status="completed",
                             result_id=RESULT, key="bt-exact")
        newer = "backtest_" + "7" * 32
        _insert_backtest_job(store, task, context, job_id=newer, status="failed",
                             result_id=None, key="bt-newer")
        # A newer, different terminal job cannot advance a plan bound to the
        # exact first job, and a failed terminal needs attention.
        late = store.record_backtest_completed_event(task, newer, trusted_context=context)
        assert late["status"] == "needs_attention"
        assert store.get_execution_plan(task, trusted_context=context)["stage"] == "waiting_for_backtest_job"
        exact = store.record_backtest_completed_event(task, BACKTEST_JOB, trusted_context=context)
        assert exact["status"] == "advanced"
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# user_resume / recovery: durable triggers and durable pending intents
# --------------------------------------------------------------------------- #

def _register_user_resume(store, task, context, content="resume now"):
    catalog = ConversationCatalogStore()
    try:
        message = catalog.append_user_message(
            context["owner_principal"], _task_row(store, task)["conversation_id"], content)
    finally:
        catalog.close()
    return store.register_continuation_trigger(
        task, {"kind": "user_resume", "source_identity": message["message_id"]},
        trusted_context=context)["trigger_id"]


def _register_recovery(store, task, context, run_id="run_" + "1" * 32):
    row = _task_row(store, task)
    conversation = store._fetch_one(
        "SELECT * FROM product_conversations WHERE conversation_id = :conversation",
        {"conversation": row["conversation_id"]})
    store._execute("""INSERT INTO agent_runtime_turns
        (root_run_id, owner_principal, workspace_id, session_id, trace_id, status,
         created_at, updated_at)
        VALUES (:run, :owner, :workspace, :session, :trace, 'interrupted', now(), now())""",
        {"run": run_id, "owner": row["owner_principal"], "workspace": row["workspace_id"],
         "session": conversation["runtime_session_id"], "trace": conversation["trace_id"]})
    return store.register_continuation_trigger(
        task, {"kind": "recovery", "source_identity": run_id},
        trusted_context=context)["trigger_id"]


def test_user_resume_persists_a_durable_pending_intent_claimable_across_restart():
    store, task, context = _setup()
    try:
        plan = store.create_execution_plan(task, {"idempotency_key": "plan-1"},
                                           trusted_context=context)
        trigger_id = _register_user_resume(store, task, context)
        first = store.record_user_resume_event(task, trigger_id, trusted_context=context)
        assert first["status"] == "pending" and first["outcome"] == "retry_current_action"
        assert first["retry_action"] == plan["next_action"] == "draft_strategy"
        store.close()
        restarted = ResearchStore()
        try:
            # The open intent survives a restart and is idempotently claimable.
            listing = restarted.list_continuation_events(task, trusted_context=context)
            assert len(listing["events"]) == 1 and listing["events"][0]["status"] == "pending"
            claimed = restarted.claim_continuation_intent(
                task, first["event_id"], claimant="worker-1", trusted_context=context)
            assert claimed["status"] == "claimed" and claimed["retry_identity"] == "plan-1"
            assert restarted.claim_continuation_intent(
                task, first["event_id"], claimant="worker-1", trusted_context=context) == claimed
            settled = restarted.settle_continuation_intent(
                task, first["event_id"], "consumed", claimant="worker-1", trusted_context=context)
            assert settled["status"] == "settled"
            assert restarted.settle_continuation_intent(
                task, first["event_id"], "consumed", claimant="worker-1",
                trusted_context=context) == settled
            # An exact replay is served from the durable ledger (current settled
            # state), never a second intent.
            replay = restarted.record_user_resume_event(task, trigger_id, trusted_context=context)
            assert replay["event_id"] == first["event_id"]
            assert replay["status"] == "settled" and replay["outcome"] == "consumed"
            # The plan itself never changed: a retry is not a plan advance.
            assert restarted.get_execution_plan(task, trusted_context=context)["plan_version"] == 1
        finally:
            restarted.close()
    finally:
        pass


def test_user_resume_requires_a_durable_trigger_and_rejects_late_binding():
    store, task, context = _setup()
    try:
        store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        with pytest.raises(ResearchNotFound):
            store.record_user_resume_event(
                task, "continuation_trigger_" + "a" * 32, trusted_context=context)
        with pytest.raises(ContinuationTriggerRequired):
            store.register_continuation_trigger(
                task, {"kind": "user_resume", "source_identity": "message_" + "b" * 32},
                trusted_context=context)
        # A trigger observed at v1 is provably stale once the plan advances.
        trigger_id = _register_user_resume(store, task, context)
        store.advance_execution_plan(task, {
            "expected_plan_version": 1, "expected_task_version": 1,
            "next_stage": "waiting_for_strategy_approval", "iteration": 1, "status": "waiting",
            "expected_postcondition": "strategy_approval_requested", "idempotency_key": "plan-2",
            "references": _references(strategy_version=STRATEGY),
            "approval": _approval("strategy_approve", "strategy_version", STRATEGY, plan=2)},
            trusted_context=context)
        late = store.record_user_resume_event(task, trigger_id, trusted_context=context)
        assert late["status"] == "needs_attention" and late["reason"] == "stale_event"
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == 2
    finally:
        store.close()


def test_recovery_adapter_retries_current_action_and_waits_out_a_gate():
    store, task, context = _setup()
    try:
        store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        trigger_id = _register_recovery(store, task, context)
        event = store.record_recovery_event(task, trigger_id, trusted_context=context)
        assert event["status"] == "pending" and event["outcome"] == "retry_current_action"
        assert event["retry_action"] == "draft_strategy"
    finally:
        store.close()


def test_at_most_one_open_intent_per_task():
    store, task, context = _setup()
    try:
        store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        resume_trigger = _register_user_resume(store, task, context)
        recovery_trigger = _register_recovery(store, task, context)
        first = store.record_user_resume_event(task, resume_trigger, trusted_context=context)
        assert first["status"] == "pending"
        with pytest.raises(ContinuationInProgress):
            store.record_recovery_event(task, recovery_trigger, trusted_context=context)
        # Settling the open intent releases the slot for the distinct event.
        store.claim_continuation_intent(task, first["event_id"], claimant="worker-1",
                                        trusted_context=context)
        store.settle_continuation_intent(task, first["event_id"], "consumed", claimant="worker-1",
                                         trusted_context=context)
        second = store.record_recovery_event(task, recovery_trigger, trusted_context=context)
        assert second["status"] == "pending"
    finally:
        store.close()


def test_claim_is_exclusive_and_settlement_requires_the_same_claimant():
    store, task, context = _setup()
    try:
        store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        trigger_id = _register_user_resume(store, task, context)
        first = store.record_user_resume_event(task, trigger_id, trusted_context=context)
        claimed = store.claim_continuation_intent(task, first["event_id"], claimant="worker-1",
                                                  trusted_context=context)
        assert claimed["status"] == "claimed" and claimed["claimed_by"] == "worker-1"
        # A distinct consumer can never receive or steal the claim.
        with pytest.raises(ContinuationClaimConflict):
            store.claim_continuation_intent(task, first["event_id"], claimant="worker-2",
                                            trusted_context=context)
        # Settlement is owned by the same claimant.
        with pytest.raises(ContinuationClaimConflict):
            store.settle_continuation_intent(task, first["event_id"], "consumed",
                                             claimant="worker-2", trusted_context=context)
        # An exact replay by the same claimant is idempotent.
        assert store.claim_continuation_intent(task, first["event_id"], claimant="worker-1",
                                               trusted_context=context) == claimed
        settled = store.settle_continuation_intent(task, first["event_id"], "consumed",
                                                   claimant="worker-1", trusted_context=context)
        assert settled["status"] == "settled"
        with pytest.raises((ValueError, ContinuationClaimConflict)):
            store.claim_continuation_intent(task, first["event_id"], claimant="worker-2",
                                            trusted_context=context)
        with pytest.raises(ContinuationClaimConflict):
            store.settle_continuation_intent(task, first["event_id"], "consumed",
                                             claimant="worker-2", trusted_context=context)
    finally:
        store.close()


def test_concurrent_claimants_only_one_claims_the_intent():
    store, task, context = _setup()
    other = ResearchStore()
    try:
        store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        trigger_id = _register_user_resume(store, task, context)
        first = store.record_user_resume_event(task, trigger_id, trusted_context=context)

        def claim(instance, claimant):
            try:
                return instance.claim_continuation_intent(
                    task, first["event_id"], claimant=claimant, trusted_context=context)
            except Exception as error:  # noqa: BLE001 - one racer must be refused
                return {"error": type(error).__name__}

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda pair: claim(*pair),
                                    ((store, "worker-a"), (other, "worker-b"))))
        claimed = [item for item in results if item.get("status") == "claimed"]
        refused = [item for item in results if item.get("error") == "ContinuationClaimConflict"]
        assert len(claimed) == 1 and len(refused) == 1, results
        assert claimed[0]["claimed_by"] in {"worker-a", "worker-b"}
    finally:
        store.close()
        other.close()


def test_claim_ownership_survives_restart_and_blocks_another_claimant():
    store, task, context = _setup()
    try:
        store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        trigger_id = _register_user_resume(store, task, context)
        first = store.record_user_resume_event(task, trigger_id, trusted_context=context)
        store.claim_continuation_intent(task, first["event_id"], claimant="worker-1",
                                        trusted_context=context)
        store.close()
        restarted = ResearchStore()
        try:
            assert restarted.claim_continuation_intent(
                task, first["event_id"], claimant="worker-1",
                trusted_context=context)["status"] == "claimed"
            with pytest.raises(ContinuationClaimConflict):
                restarted.claim_continuation_intent(
                    task, first["event_id"], claimant="worker-2", trusted_context=context)
            with pytest.raises(ContinuationClaimConflict):
                restarted.settle_continuation_intent(
                    task, first["event_id"], "consumed", claimant="worker-2",
                    trusted_context=context)
            settled = restarted.settle_continuation_intent(
                task, first["event_id"], "consumed", claimant="worker-1", trusted_context=context)
            assert settled["status"] == "settled"
        finally:
            restarted.close()
    finally:
        pass


# --------------------------------------------------------------------------- #
# Isolation, concurrency, projections
# --------------------------------------------------------------------------- #

def test_database_constraint_allows_at_most_one_open_continuation():
    store, task, context = _setup()
    try:
        _execute_gate_plan(store, task, context)
        store._execute("""INSERT INTO research_continuation_events
            (task_id, event_id, event_type, event_version, source_identity, owner_principal,
             workspace_id, plan_version, task_version, status, outcome, admitted, request_hash,
             result_json, created_at, updated_at)
            VALUES (:task, :event, 'user_resume', 1, :source, :owner, :workspace, 1, 1,
                    'pending', 'retry_current_action', TRUE, :hash, '{}'::jsonb, now(), now())""",
            {"task": task, "event": "continuation_event_" + "1" * 32,
             "source": "source_" + "1" * 16, "owner": context["owner_principal"],
             "workspace": context["workspace_id"], "hash": "sha256:" + "1" * 64})
        with pytest.raises(Exception):
            store._execute("""INSERT INTO research_continuation_events
                (task_id, event_id, event_type, event_version, source_identity, owner_principal,
                 workspace_id, plan_version, task_version, status, outcome, admitted, request_hash,
                 result_json, created_at, updated_at)
                VALUES (:task, :event, 'user_resume', 1, :source, :owner, :workspace, 1, 1,
                        'pending', 'retry_current_action', TRUE, :hash, '{}'::jsonb, now(), now())""",
                {"task": task, "event": "continuation_event_" + "2" * 32,
                 "source": "source_" + "2" * 16, "owner": context["owner_principal"],
                 "workspace": context["workspace_id"], "hash": "sha256:" + "2" * 64})
    finally:
        store.close()


def test_concurrent_distinct_events_never_double_open():
    store, task, context = _setup()
    other = ResearchStore()
    try:
        store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        resume_trigger = _register_user_resume(store, task, context)
        recovery_trigger = _register_recovery(store, task, context)

        def record(instance, fn):
            try:
                return fn(instance)
            except Exception as error:  # noqa: BLE001 - one racer may be refused
                return {"error": type(error).__name__}

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda pair: record(*pair), (
                (store, lambda s: s.record_user_resume_event(task, resume_trigger, trusted_context=context)),
                (other, lambda s: s.record_recovery_event(task, recovery_trigger, trusted_context=context)),
            )))
        assert all(item.get("status") == "pending"
                   or item.get("error") == "ContinuationInProgress" for item in results)
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == 1
    finally:
        store.close()
        other.close()


def test_foreign_owner_cannot_record_or_read_events():
    store, task, context = _setup()
    other, other_task, other_context = _setup(owner="ledger-intruder", session="ledger-session-x",
                                              trace="ledger-trace-x")
    try:
        store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        trigger_id = _register_user_resume(store, task, context)
        with pytest.raises(ResearchNotFound):
            store.record_user_resume_event(task, trigger_id, trusted_context=other_context)
        with pytest.raises(ResearchNotFound):
            store.list_continuation_events(task, trusted_context=other_context)
    finally:
        store.close()
        other.close()


def test_event_projection_is_bounded_and_listing_is_owner_scoped():
    store, task, context = _setup()
    try:
        store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        trigger_id = _register_user_resume(store, task, context)
        store.record_user_resume_event(task, trigger_id, trusted_context=context)
        listing = store.list_continuation_events(task, trusted_context=context)
        assert listing["task_id"] == task and len(listing["events"]) == 1
        event = listing["events"][0]
        assert set(event) == {"event_id", "event_type", "event_version", "status", "outcome",
                              "plan_version", "task_version", "next_stage", "reason", "retry_action"}
        for internal in ("source_identity", "owner_principal", "workspace_id", "request_hash",
                         "params_digest", "decision", "retry_identity"):
            assert internal not in event
        with pytest.raises(ValueError):
            store.list_continuation_events(task, trusted_context=context, limit=0)
        with pytest.raises(ValueError):
            project_continuation_event({"status": "made_up"})
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# Compat approval path must be exactly bound, never session-wide
# --------------------------------------------------------------------------- #

def _continuation_status(approval_id, owner):
    agent = AgentResearchStore()
    try:
        return agent.get_approval(approval_id, trusted_owner=owner)["continuation_status"]
    finally:
        agent.close()


def test_compat_approval_guard_blocks_the_exact_plan_binding_only():
    store, task, context = _setup()
    try:
        artifact, _plan = _plan_gate(store, task, context, key="compat-strategy")
        # An unrelated RESOURCE (no matching plan requirement) is not blocked.
        unrelated_resource = _agent_approval(
            context["owner_principal"], context["session_id"], context["trace_id"],
            action="byq_strategy_approve", resource_type="strategy_version",
            resource_id="artifact_" + "e" * 32, key="unrelated-resource")
        assert _continuation_status(unrelated_resource, context["owner_principal"]) == "queued"
        # An unrelated ACTION sharing the same resource is not blocked.
        unrelated_action = _agent_approval(
            context["owner_principal"], context["session_id"], context["trace_id"],
            action="byq_backtest_task_create", resource_type="strategy_version",
            resource_id=artifact["artifact_id"], key="unrelated-action")
        assert _continuation_status(unrelated_action, context["owner_principal"]) == "queued"
        # A foreign owner sharing the resource is not blocked.
        other, _other_task, other_context = _setup(
            owner="guard-intruder", session="guard-session-x", trace="guard-trace-x")
        try:
            foreign = _agent_approval(
                other_context["owner_principal"], other_context["session_id"],
                other_context["trace_id"], action="byq_strategy_approve",
                resource_type="strategy_version", resource_id=artifact["artifact_id"],
                key="foreign-guard")
            assert _continuation_status(foreign, other_context["owner_principal"]) == "queued"
        finally:
            other.close()
        # The EXACT plan-bound approval is blocked from the generic compat turn.
        exact = _agent_approval(
            context["owner_principal"], context["session_id"], context["trace_id"],
            action="byq_strategy_approve", resource_type="strategy_version",
            resource_id=artifact["artifact_id"], key="exact-approval")
        assert _continuation_status(exact, context["owner_principal"]) == "blocked"
    finally:
        store.close()
