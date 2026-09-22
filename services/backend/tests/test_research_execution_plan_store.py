"""ADR-0085 P1 persistence tests: one-current-plan, task/plan CAS, legacy policy.

These exercise the INTERNAL Backend store seam used by the deterministic
reducer. There is no agent-facing HTTP/MCP write route for a plan.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.conversation_catalog import ConversationCatalogStore
from app.research import (
    IdempotencyConflict,
    InvalidTransition,
    ResearchNotFound,
    ResearchStore,
)
from app.research_execution_plan import project_execution_plan
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")

STRATEGY = "artifact_" + "d" * 32

_REQUIRED_PLAN_FIELDS = {
    "schema_version", "task_id", "plan_version", "task_version",
    "owner_principal", "workspace_id", "conversation_id",
    "stage", "iteration", "status", "next_action",
    "references", "prerequisites", "expected_postcondition",
    "approval", "idempotency_key", "allowed_capabilities",
    "last_progress_identity",
}


def _raw_plan(store, task: str) -> dict:
    """Read the full persisted plan object (internal seam, not the projection)."""
    row = store._fetch_one(
        "SELECT plan FROM research_execution_plans WHERE task_id = :task", {"task": task})
    return row["plan"]


def _setup(owner: str = "plan-user", session: str = "plan-session", trace: str = "plan-trace"):
    headers = trusted_agent_context(owner, session_id=session, trace_id=trace)
    context = {key.removeprefix("x-byq-").replace("-", "_"): value for key, value in headers.items()}
    catalog = ConversationCatalogStore()
    catalog.create(owner, session, trace)
    catalog.close()
    store = ResearchStore()
    task = store.create_task(
        {"owner_principal": owner, "title": "Synthetic plan", "objective": "No execution",
         "trace_id": trace, "idempotency_key": f"{owner}-task"},
        trusted_context=context,
    )
    return store, task["task_id"], context


def _approval(action: str, resource_kind: str, resource_id: str, *, plan: int, task: int = 1):
    return {"action": action, "resource_kind": resource_kind, "resource_id": resource_id,
            "plan_version": plan, "task_version": task}


def _references(**extra: str):
    return {kind: {kind: identity} for kind, identity in extra.items()}


def _strategy_gate_payload(*, key: str, plan: int = 2, **overrides: object):
    payload = {
        "expected_plan_version": 1, "expected_task_version": 1,
        "next_stage": "waiting_for_strategy_approval", "iteration": 1, "status": "waiting",
        "expected_postcondition": "strategy_approval_requested", "idempotency_key": key,
        "references": _references(strategy_version=STRATEGY),
        "approval": _approval("strategy_approve", "strategy_version", STRATEGY, plan=plan),
    }
    payload.update(overrides)
    return payload


def _legacy_progress(stage: str):
    return {"schema_version": "research-progress.v1", "stage": stage, "next_action": "继续",
            "blocked_reason": "legacy_blocker" if stage == "blocked" else None,
            "linked_objects": [], "completion_evidence": []}


def test_create_and_get_is_one_current_plan_per_task():
    store, task, context = _setup()
    try:
        plan = store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        assert plan["schema_version"] == "research-execution-plan.v1"
        assert plan["plan_version"] == 1 and plan["task_version"] == 1
        assert plan["stage"] == "strategy_draft" and plan["next_action"] == "draft_strategy"
        assert store.get_execution_plan(task, trusted_context=context) == plan
        # An exact replay is idempotent; a different key cannot add a second plan.
        assert store.create_execution_plan(task, {"idempotency_key": "plan-1"},
                                           trusted_context=context) == plan
        with pytest.raises(IdempotencyConflict):
            store.create_execution_plan(task, {"idempotency_key": "plan-2"}, trusted_context=context)
    finally:
        store.close()


def test_projection_is_bounded_and_hides_internal_execution_authority():
    store, task, context = _setup()
    try:
        plan = store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        assert set(plan) == {
            "schema_version", "task_id", "plan_version", "task_version", "stage",
            "iteration", "status", "next_action", "expected_postcondition", "approval",
        }
        for internal in ("owner_principal", "workspace_id", "conversation_id", "idempotency_key",
                         "allowed_capabilities", "references", "prerequisites",
                         "last_progress_identity"):
            assert internal not in plan
    finally:
        store.close()


def test_advance_compare_and_swaps_plan_and_task_versions():
    store, task, context = _setup()
    try:
        store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        payload = _strategy_gate_payload(key="plan-2")
        advanced = store.advance_execution_plan(task, payload, trusted_context=context)
        assert advanced["plan_version"] == 2 and advanced["task_version"] == 1
        assert advanced["stage"] == "waiting_for_strategy_approval"
        assert advanced["status"] == "waiting"
        assert advanced["next_action"] == "request_strategy_approval"
        # Stale plan version is refused.
        with pytest.raises(InvalidTransition):
            store.advance_execution_plan(task, _strategy_gate_payload(key="plan-3"),
                                         trusted_context=context)
        # Stale task version is refused even with the current plan version.
        with pytest.raises(InvalidTransition):
            store.advance_execution_plan(
                task, _strategy_gate_payload(key="plan-4", expected_task_version=9),
                trusted_context=context)
        # The persisted row is unchanged by the refused writes.
        assert store.get_execution_plan(task, trusted_context=context) == advanced
    finally:
        store.close()


def test_advance_is_at_most_once_and_key_reuse_conflicts():
    store, task, context = _setup()
    try:
        store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        payload = _strategy_gate_payload(key="plan-2")
        advanced = store.advance_execution_plan(task, payload, trusted_context=context)
        # Same command replays from the durable receipt without a second write.
        assert store.advance_execution_plan(task, payload, trusted_context=context) == advanced
        # The same key with a different body is a conflict, not a replay.
        with pytest.raises(IdempotencyConflict):
            store.advance_execution_plan(task, {**payload, "next_stage": "needs_attention",
                                                "status": "blocked",
                                                "expected_postcondition": "blocks_resolved_or_confirmed"},
                                         trusted_context=context)
    finally:
        store.close()


def test_advance_replay_survives_a_later_task_version_change():
    store, task, context = _setup()
    try:
        store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        payload = _strategy_gate_payload(key="plan-2")
        advanced = store.advance_execution_plan(task, payload, trusted_context=context)
        # A later, unrelated task transition moves research_tasks.version.
        store.transition("research_task", task, "running", "task-run-1")
        # The exact same advance request still replays deterministically.
        assert store.advance_execution_plan(task, payload, trusted_context=context) == advanced
    finally:
        store.close()


def test_advance_rejects_approval_not_bound_to_plan_version_or_resource():
    store, task, context = _setup()
    try:
        store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        # approval.plan_version must equal the advanced plan version (2).
        with pytest.raises(InvalidTransition):
            store.advance_execution_plan(
                task, _strategy_gate_payload(key="plan-bad-1", plan=3), trusted_context=context)
        # approval.task_version must equal the plan task version (1).
        with pytest.raises(InvalidTransition):
            store.advance_execution_plan(
                task, _strategy_gate_payload(
                    key="plan-bad-2",
                    approval=_approval("strategy_approve", "strategy_version", STRATEGY,
                                       plan=2, task=2)),
                trusted_context=context)
        # approval.resource_id must equal the plan reference for that kind.
        with pytest.raises(InvalidTransition):
            store.advance_execution_plan(
                task, _strategy_gate_payload(
                    key="plan-bad-3",
                    references=_references(strategy_version="artifact_" + "9" * 32)),
                trusted_context=context)
        # A missing reference for the approved kind is refused.
        with pytest.raises(InvalidTransition):
            store.advance_execution_plan(
                task, _strategy_gate_payload(key="plan-bad-4", references=_references()),
                trusted_context=context)
        # No partial write happened.
        assert store.get_execution_plan(task, trusted_context=context)["plan_version"] == 1
    finally:
        store.close()


def test_illegal_stage_transition_is_rejected():
    store, task, context = _setup()
    try:
        store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        with pytest.raises(InvalidTransition):
            store.advance_execution_plan(task, {
                "expected_plan_version": 1, "expected_task_version": 1,
                "next_stage": "backtest_analysis", "iteration": 1, "status": "active",
                "expected_postcondition": "backtest_result_analysed",
                "idempotency_key": "plan-illegal"}, trusted_context=context)
    finally:
        store.close()


def test_terminal_task_cannot_start_a_plan():
    store, task, context = _setup()
    try:
        store.transition("research_task", task, "cancelled", "cancel-1")
        with pytest.raises(InvalidTransition):
            store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
    finally:
        store.close()


def test_all_legacy_tasks_enter_needs_attention_from_persisted_facts_only():
    # No persisted plan facts can uniquely prove a closed stage/action in P1, so
    # even a coarse data_preparation/comparison progress enters needs_attention.
    for stage in ("data_preparation", "comparison", "strategy", "backtest", "blocked"):
        store, task, context = _setup(owner=f"legacy-{stage}", session=f"legacy-s-{stage}",
                                      trace=f"legacy-t-{stage}")
        try:
            store.transition("research_task", task, "running", "legacy-progress",
                             progress=_legacy_progress(stage))
            plan = store.adopt_legacy_execution_plan(task, trusted_context=context)
            assert plan["stage"] == "needs_attention", stage
            assert plan["status"] == "blocked" and plan["next_action"] == "resolve_blockers"
            # Adoption is one-shot; a second call replays the existing plan.
            assert store.adopt_legacy_execution_plan(task, trusted_context=context) == plan
        finally:
            store.close()


def test_legacy_task_without_progress_enters_needs_attention():
    store, task, context = _setup()
    try:
        plan = store.adopt_legacy_execution_plan(task, trusted_context=context)
        assert plan["stage"] == "needs_attention" and plan["status"] == "blocked"
    finally:
        store.close()


def test_foreign_owner_cannot_read_or_advance_a_plan():
    store, task, context = _setup()
    other, other_task, other_context = _setup(owner="plan-intruder", session="plan-session-x",
                                              trace="plan-trace-x")
    try:
        store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        with pytest.raises(ResearchNotFound):
            store.get_execution_plan(task, trusted_context=other_context)
        with pytest.raises(ResearchNotFound):
            store.advance_execution_plan(task, _strategy_gate_payload(key="plan-x"),
                                         trusted_context=other_context)
    finally:
        store.close()
        other.close()


def test_projection_fails_closed_for_corrupt_or_tampered_plan():
    store, task, context = _setup()
    try:
        projection = store.create_execution_plan(task, {"idempotency_key": "plan-1"},
                                                 trusted_context=context)
        # The raw persisted plan is the full closed object; the projection is the
        # bounded public shape. Reconstruct a full plan from a fresh validated one.
        raw = _raw_plan(store, task)
        assert set(raw) == _REQUIRED_PLAN_FIELDS
    finally:
        store.close()
    # Unknown key, missing key, invalid stage and invalid approval all fail closed.
    missing_stage = dict(raw)
    del missing_stage["stage"]
    for corrupt in (
        {**raw, "llm_next_action": "do_something"},
        missing_stage,
        {**raw, "stage": "free_text_stage"},
        {**raw, "approval": {"action": "strategy_approve"}},
    ):
        with pytest.raises(ValueError):
            project_execution_plan(corrupt)
    with pytest.raises(ValueError):
        project_execution_plan("not-a-plan")
    with pytest.raises(ValueError):
        project_execution_plan(None)
    # The genuine plan still projects to the bounded shape.
    assert project_execution_plan(raw) == projection


def test_receipt_replay_also_fails_closed_when_the_receipt_is_corrupt():
    store, task, context = _setup()
    try:
        store.create_execution_plan(task, {"idempotency_key": "plan-1"}, trusted_context=context)
        payload = _strategy_gate_payload(key="plan-2")
        advanced = store.advance_execution_plan(task, payload, trusted_context=context)
        # Corrupt the durable receipt body directly; replay must not project it.
        store._execute("""UPDATE research_execution_plan_receipts
            SET result_json = result_json || '{"stage": "free_text_stage"}'::jsonb
            WHERE task_id = :task AND idempotency_key = :key""",
            {"task": task, "key": "plan-2"})
        with pytest.raises(ValueError):
            store.advance_execution_plan(task, payload, trusted_context=context)
        # The current plan row is untouched.
        assert store.get_execution_plan(task, trusted_context=context) == advanced
    finally:
        store.close()


def test_competing_connections_create_exactly_one_current_plan():
    store, task, context = _setup()
    other = ResearchStore()
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(instance.create_execution_plan, task,
                                       {"idempotency_key": "plan-race"}, trusted_context=context)
                       for instance in (store, other)]
            results = [future.result() for future in futures]
        assert results[0] == results[1]
        assert results[0]["plan_version"] == 1
    finally:
        store.close()
        other.close()
