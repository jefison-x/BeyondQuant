"""ADR-0085 P3 bounded research-judgment seam tests (isolated PostgreSQL).

These exercise the named server-side seams only: a READ-ONLY bounded stage input,
the named proposal commit through plan compare-and-swap, and the durable-progress
fence that stops a stage as ``needs_attention/no_durable_progress``. There is no
generic plan/proposal write route.
"""

import os

import pytest

from app.conversation_catalog import ConversationCatalogStore
from app.research import InvalidTransition, ResearchNotFound, ResearchStore
from app.research_judgment import ModelTurnNotAllowed
from packages.contracts.research_execution_plan import plan_at_stage
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")

STRATEGY = "artifact_" + "d" * 32
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def _setup(owner: str = "judgment-user", session: str = "judgment-session", trace: str = "judgment-trace"):
    headers = trusted_agent_context(owner, session_id=session, trace_id=trace)
    context = {key.removeprefix("x-byq-").replace("-", "_"): value for key, value in headers.items()}
    catalog = ConversationCatalogStore()
    catalog.create(owner, session, trace)
    catalog.close()
    store = ResearchStore()
    task = store.create_task(
        {"owner_principal": owner, "title": "Judgment task", "objective": "Judge within bounds",
         "trace_id": trace, "idempotency_key": f"{owner}-task"},
        trusted_context=context,
    )
    return store, task["task_id"], context


def _task_row(store, task):
    return store._fetch_one("SELECT * FROM research_tasks WHERE task_id = :task", {"task": task})


def _seed_plan(store, task, stage, *, references=None, iteration=1):
    row = _task_row(store, task)
    plan = plan_at_stage(
        task_id=task, owner_principal=row["owner_principal"], workspace_id=row["workspace_id"],
        conversation_id=row["conversation_id"], task_version=row["version"], stage=stage,
        idempotency_key="seed-plan", references=references, iteration=iteration,
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


def _plan_row(store, task):
    return store._fetch_one("SELECT * FROM research_execution_plans WHERE task_id = :task", {"task": task})


def _proposal(plan, stage, kind, *, iteration=None, task_id=None, **overrides):
    value = {
        "schema_version": "research-proposal.v1", "task_id": plan["task_id"] if task_id is None else task_id,
        "plan_version": plan["plan_version"], "task_version": plan["task_version"],
        "stage": stage, "iteration": plan["iteration"] if iteration is None else iteration,
        "proposal_kind": kind, "evidence_sufficient": True, "escalate": False,
        "summary": "bounded judgment",
    }
    value.update(overrides)
    return value


# --------------------------------------------------------------------------- #
# Read-only bounded stage input
# --------------------------------------------------------------------------- #

def test_stage_input_is_read_only_bounded_and_refuses_deterministic_stages():
    store, task, context = _setup()
    try:
        _seed_plan(store, task, "backtest_analysis",
                   references={"backtest_result": {"backtest_result": "artifact_" + "c" * 32}})
        value = store.get_research_stage_input(task, trusted_context=context)
        assert value["stage"] == "backtest_analysis"
        assert value["model_call_limit"] == 2
        assert value["allowed_tools"]
        assert all(tool in {"byq_agent_context", "byq_research_get", "byq_research_stage_input_get",
                            "byq_backtest_task_get", "byq_backtest_analysis_get"}
                   for tool in value["allowed_tools"])
        assert "date_index" not in str(value)
        assert "bars_frame" not in str(value)

        store._execute("DELETE FROM research_execution_plans WHERE task_id = :task", {"task": task})
        _seed_plan(store, task, "waiting_for_data")
        with pytest.raises(ModelTurnNotAllowed):
            store.get_research_stage_input(task, trusted_context=context)
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# Named proposal commit through plan CAS
# --------------------------------------------------------------------------- #

def test_commit_advances_through_cas_and_replays_idempotently():
    store, task, context = _setup()
    try:
        plan = _seed_plan(store, task, "backtest_analysis")
        proposal = _proposal(plan, "backtest_analysis", "backtest_analysis")
        committed = store.commit_research_proposal(task, proposal, trusted_context=context)
        assert committed["stage"] == "iteration_comparison"
        assert committed["replayed"] is False
        assert committed["proposal_identity"].startswith("research_proposal_")
        advanced = _plan_row(store, task)
        assert advanced["plan_version"] == plan["plan_version"] + 1

        replay = store.commit_research_proposal(task, proposal, trusted_context=context)
        assert replay["replayed"] is True
        assert replay["stage"] == "iteration_comparison"
        assert _plan_row(store, task)["plan_version"] == plan["plan_version"] + 1

        mutated = _proposal(plan, "backtest_analysis", "backtest_analysis", summary="changed")
        with pytest.raises(InvalidTransition):
            store.commit_research_proposal(task, mutated, trusted_context=context)
    finally:
        store.close()


def test_commit_rejects_forged_routing_raw_payloads_and_stale_versions():
    store, task, context = _setup()
    try:
        plan = _seed_plan(store, task, "backtest_analysis")
        for forged in (
            _proposal(plan, "backtest_analysis", "backtest_analysis", next_action="execute_backtest_task"),
            _proposal(plan, "backtest_analysis", "backtest_analysis", idempotency_key="forged"),
            _proposal(plan, "backtest_analysis", "backtest_analysis", object_id="forged"),
            _proposal(plan, "backtest_analysis", "backtest_analysis", state={"date_index": [1, 2, 3]}),
        ):
            with pytest.raises(ValueError):
                store.commit_research_proposal(task, forged, trusted_context=context)

        stale_plan = _proposal(plan, "backtest_analysis", "backtest_analysis")
        stale_plan["plan_version"] = plan["plan_version"] + 5
        with pytest.raises(InvalidTransition):
            store.commit_research_proposal(task, stale_plan, trusted_context=context)
        stale_task = _proposal(plan, "backtest_analysis", "backtest_analysis")
        stale_task["task_version"] = plan["task_version"] + 5
        with pytest.raises(InvalidTransition):
            store.commit_research_proposal(task, stale_task, trusted_context=context)
        wrong_task = _proposal(plan, "backtest_analysis", "backtest_analysis", task_id="task_" + "b" * 32)
        with pytest.raises(InvalidTransition):
            store.commit_research_proposal(task, wrong_task, trusted_context=context)
    finally:
        store.close()


def test_commit_to_approval_gate_requires_an_existing_exact_reference():
    store, task, context = _setup()
    try:
        _seed_plan(store, task, "strategy_draft")
        plan = _plan_row(store, task)["plan"]
        missing = _proposal(plan, "strategy_draft", "strategy_draft")
        with pytest.raises(InvalidTransition):
            store.commit_research_proposal(task, missing, trusted_context=context)

        store._execute("DELETE FROM research_execution_plans WHERE task_id = :task", {"task": task})
        seeded = _seed_plan(store, task, "strategy_draft",
                            references={"strategy_version": {"strategy_version": STRATEGY}})
        committed = store.commit_research_proposal(
            task, _proposal(seeded, "strategy_draft", "strategy_draft"), trusted_context=context)
        assert committed["stage"] == "waiting_for_strategy_approval"
        persisted = _plan_row(store, task)["plan"]
        assert persisted["approval"]["resource_id"] == STRATEGY
        assert persisted["approval"]["params_digest"].startswith("sha256:")
    finally:
        store.close()


def test_commit_escalation_and_insufficient_evidence_stop_at_needs_attention():
    store, task, context = _setup()
    try:
        plan = _seed_plan(store, task, "backtest_analysis")
        escalated = store.commit_research_proposal(
            task, _proposal(plan, "backtest_analysis", "backtest_analysis", escalate=True),
            trusted_context=context)
        assert escalated["stage"] == "needs_attention"
        assert escalated["reason"] == "escalation_requested"
        assert _task_row(store, task)["progress"]["blocked_reason"] == "escalation_requested"
    finally:
        store.close()

    store, task, context = _setup(owner="judgment-user-2", session="judgment-session-2",
                                  trace="judgment-trace-2")
    try:
        plan = _seed_plan(store, task, "backtest_analysis")
        insufficient = store.commit_research_proposal(
            task, _proposal(plan, "backtest_analysis", "backtest_analysis", evidence_sufficient=False),
            trusted_context=context)
        assert insufficient["stage"] == "needs_attention"
        assert insufficient["reason"] == "insufficient_evidence"
        assert _task_row(store, task)["progress"]["blocked_reason"] == "insufficient_evidence"
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# Durable-progress fence and two-call bound
# --------------------------------------------------------------------------- #

def test_first_call_without_durable_progress_fences_atomically():
    store, task, context = _setup()
    try:
        plan = _seed_plan(store, task, "backtest_analysis")
        before = _task_row(store, task)
        outcome = store.record_research_stage_progress(
            task, {"call_index": 1, "durable_progress_identity": None}, trusted_context=context)
        assert outcome["status"] == "stop"
        assert outcome["reason"] == "no_durable_progress"
        assert outcome["plan_moved_to_needs_attention"] is True
        persisted = _plan_row(store, task)
        assert persisted["stage"] == "needs_attention"
        assert persisted["status"] == "blocked"
        row = _task_row(store, task)
        assert row["progress"]["blocked_reason"] == "no_durable_progress"
        assert row["version"] == before["version"] + 1
        with pytest.raises(ModelTurnNotAllowed):
            store.record_research_stage_progress(
                task, {"call_index": 2, "durable_progress_identity": DIGEST_B}, trusted_context=context)
    finally:
        store.close()


def test_two_call_bound_and_zero_calls_for_deterministic_stages():
    store, task, context = _setup()
    try:
        _seed_plan(store, task, "iteration_comparison", iteration=1)
        first = store.record_research_stage_progress(
            task, {"call_index": 1, "durable_progress_identity": DIGEST_A}, trusted_context=context)
        assert first["continue"] is True
        second = store.record_research_stage_progress(
            task, {"call_index": 2, "durable_progress_identity": DIGEST_B}, trusted_context=context)
        assert second["continue"] is False

        store._execute("DELETE FROM research_execution_plans WHERE task_id = :task", {"task": task})
        _seed_plan(store, task, "waiting_for_data")
        with pytest.raises(ModelTurnNotAllowed):
            store.record_research_stage_progress(
                task, {"call_index": 1, "durable_progress_identity": DIGEST_A}, trusted_context=context)
    finally:
        store.close()


def test_owner_isolation_on_both_seams():
    store, task, context = _setup()
    try:
        plan = _seed_plan(store, task, "backtest_analysis")
        other = trusted_agent_context("judgment-other", session_id="other-session", trace_id="other-trace")
        other_context = {key.removeprefix("x-byq-").replace("-", "_"): value for key, value in other.items()}
        with pytest.raises(ResearchNotFound):
            store.get_research_stage_input(task, trusted_context=other_context)
        with pytest.raises(ResearchNotFound):
            store.commit_research_proposal(
                task, _proposal(plan, "backtest_analysis", "backtest_analysis"),
                trusted_context=other_context)
    finally:
        store.close()
