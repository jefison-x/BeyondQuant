"""ADR-0085 P3 bounded research-judgment seam tests (isolated PostgreSQL).

These exercise the named server-side seams only: a READ-ONLY bounded stage input,
a durable per-stage model-call admission (caller cannot choose/reset the count;
concurrency never exceeds the bound; replay is free), authoritative durable
progress derived from persisted BYQ records (a fabricated digest fails closed),
the atomic first-check no-progress fence, the named proposal commit through plan
CAS, and atomic task/plan terminal convergence on ``final_selection``.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.conversation_catalog import ConversationCatalogStore
from app.research import InvalidTransition, ResearchNotFound, ResearchStore
from app.research_judgment import ModelTurnNotAllowed, StageModelCallLimitExceeded
from packages.contracts.research_execution_plan import plan_at_stage
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")

STRATEGY = "artifact_" + "d" * 32


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


def _artifact(store, task, *, kind="backtest_result", key="artifact"):
    return store.create_artifact({
        "task_id": task, "kind": kind, "content": {"synthetic": key}, "lineage": [],
        "trace_id": _task_row(store, task)["trace_id"], "idempotency_key": key})


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
        assert all(tool in {"byq_agent_context", "byq_research_get", "byq_research_stage_input_get",
                            "byq_backtest_task_get", "byq_backtest_analysis_get"}
                   for tool in value["allowed_tools"])
        assert "date_index" not in str(value) and "bars_frame" not in str(value)

        store._execute("DELETE FROM research_execution_plans WHERE task_id = :task", {"task": task})
        _seed_plan(store, task, "waiting_for_data")
        with pytest.raises(ModelTurnNotAllowed):
            store.get_research_stage_input(task, trusted_context=context)
        with pytest.raises(ModelTurnNotAllowed):
            store.admit_research_stage_call(task, {"call_identity": "det-1"}, trusted_context=context)
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# Durable admission: authoritative count, replay, bound, concurrency
# --------------------------------------------------------------------------- #

def test_admission_derives_count_and_rejects_the_third_call():
    store, task, context = _setup()
    try:
        _seed_plan(store, task, "backtest_analysis")
        first = store.admit_research_stage_call(task, {"call_identity": "turn-a"}, trusted_context=context)
        assert first["call_index"] == 1 and first["model_call_limit"] == 2
        assert first["stage_input"]["stage"] == "backtest_analysis"
        second = store.admit_research_stage_call(task, {"call_identity": "turn-b"}, trusted_context=context)
        assert second["call_index"] == 2
        with pytest.raises(StageModelCallLimitExceeded):
            store.admit_research_stage_call(task, {"call_identity": "turn-c"}, trusted_context=context)
    finally:
        store.close()


def test_admission_replay_is_free_and_identity_bound():
    store, task, context = _setup()
    try:
        _seed_plan(store, task, "backtest_analysis")
        first = store.admit_research_stage_call(task, {"call_identity": "turn-a"}, trusted_context=context)
        replay = store.admit_research_stage_call(task, {"call_identity": "turn-a"}, trusted_context=context)
        assert replay["call_index"] == first["call_index"] == 1
        count = store._fetch_one("""SELECT COUNT(*) AS count FROM research_judgment_stage_calls
            WHERE task_id = :task""", {"task": task})
        assert count["count"] == 1
    finally:
        store.close()


def test_concurrent_admission_never_exceeds_two():
    store, task, context = _setup()
    try:
        _seed_plan(store, task, "backtest_analysis")
        stores = [ResearchStore() for _ in range(4)]

        def _admit(index: int):
            try:
                return stores[index].admit_research_stage_call(
                    task, {"call_identity": f"turn-{index}"}, trusted_context=context)["call_index"]
            except StageModelCallLimitExceeded:
                return None
            finally:
                stores[index].close()

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(_admit, range(4)))
        assert sorted(item for item in results if item is not None) == [1, 2]
        assert sum(1 for item in results if item is None) == 2
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# Authoritative durable progress + first-check fence
# --------------------------------------------------------------------------- #

def test_fabricated_progress_is_rejected_and_none_is_the_only_no_progress():
    store, task, context = _setup()
    try:
        _seed_plan(store, task, "backtest_analysis")
        store.admit_research_stage_call(task, {"call_identity": "turn-a"}, trusted_context=context)
        # A caller-supplied digest is not even a legal evidence shape.
        with pytest.raises(ValueError):
            store.record_research_stage_progress(
                task, {"call_identity": "turn-a",
                       "durable_evidence": {"kind": "artifact", "id": "sha256:" + "a" * 64}},
                trusted_context=context)
        # A record that does not belong to the task is rejected, not accepted.
        with pytest.raises(ValueError):
            store.record_research_stage_progress(
                task, {"call_identity": "turn-a",
                       "durable_evidence": {"kind": "artifact", "id": "artifact_" + "e" * 32}},
                trusted_context=context)
        with pytest.raises(ValueError):
            store.record_research_stage_progress(
                task, {"call_identity": "turn-a",
                       "durable_evidence": {"kind": "backtest_job", "id": "backtest_" + "e" * 32}},
                trusted_context=context)
    finally:
        store.close()


def test_first_completed_check_without_progress_fences_atomically():
    store, task, context = _setup()
    try:
        _seed_plan(store, task, "backtest_analysis")
        store.admit_research_stage_call(task, {"call_identity": "turn-a"}, trusted_context=context)
        before = _task_row(store, task)
        outcome = store.record_research_stage_progress(
            task, {"call_identity": "turn-a", "durable_evidence": {"kind": "none"}},
            trusted_context=context)
        assert outcome["status"] == "stop" and outcome["reason"] == "no_durable_progress"
        assert outcome["plan_moved_to_needs_attention"] is True
        persisted = _plan_row(store, task)
        assert persisted["stage"] == "needs_attention" and persisted["status"] == "blocked"
        row = _task_row(store, task)
        assert row["progress"]["blocked_reason"] == "no_durable_progress"
        assert row["version"] == before["version"] + 1
        # Replay of the completed check is free and does not re-fence.
        replay = store.record_research_stage_progress(
            task, {"call_identity": "turn-a", "durable_evidence": {"kind": "none"}},
            trusted_context=context)
        assert replay["replayed"] is True
        assert _task_row(store, task)["version"] == before["version"] + 1
    finally:
        store.close()


def test_authoritative_artifact_progress_allows_the_second_call_then_stops():
    store, task, context = _setup()
    try:
        _seed_plan(store, task, "backtest_analysis")
        store.admit_research_stage_call(task, {"call_identity": "turn-a"}, trusted_context=context)
        artifact = _artifact(store, task, key="judgment-progress")
        first = store.record_research_stage_progress(
            task, {"call_identity": "turn-a",
                   "durable_evidence": {"kind": "artifact", "id": artifact["artifact_id"]}},
            trusted_context=context)
        assert first["continue"] is True and first["progress_identity"].startswith("sha256:")

        store.admit_research_stage_call(task, {"call_identity": "turn-b"}, trusted_context=context)
        second = store.record_research_stage_progress(
            task, {"call_identity": "turn-b", "durable_evidence": {"kind": "none"}},
            trusted_context=context)
        assert second["status"] == "stop" and second["outcome"] == "advance"
        assert second["plan_moved_to_needs_attention"] is False
        with pytest.raises(StageModelCallLimitExceeded):
            store.admit_research_stage_call(task, {"call_identity": "turn-c"}, trusted_context=context)
    finally:
        store.close()


def test_progress_for_an_unadmitted_call_fails_closed():
    store, task, context = _setup()
    try:
        _seed_plan(store, task, "backtest_analysis")
        with pytest.raises(InvalidTransition):
            store.record_research_stage_progress(
                task, {"call_identity": "never-admitted", "durable_evidence": {"kind": "none"}},
                trusted_context=context)
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
        assert committed["stage"] == "iteration_comparison" and committed["replayed"] is False
        advanced = _plan_row(store, task)
        assert advanced["plan_version"] == plan["plan_version"] + 1

        replay = store.commit_research_proposal(task, proposal, trusted_context=context)
        assert replay["replayed"] is True and replay["stage"] == "iteration_comparison"
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
        # A forged stage binding (a proposal valid for another stage) fails closed.
        forged_stage = _proposal(plan, "iteration_comparison", "select_iteration",
                                 iteration=3, selected_iteration=3)
        with pytest.raises(InvalidTransition):
            store.commit_research_proposal(task, forged_stage, trusted_context=context)
    finally:
        store.close()


def test_commit_to_approval_gate_requires_an_existing_exact_reference():
    store, task, context = _setup()
    try:
        _seed_plan(store, task, "strategy_draft")
        plan = _plan_row(store, task)["plan"]
        with pytest.raises(InvalidTransition):
            store.commit_research_proposal(
                task, _proposal(plan, "strategy_draft", "strategy_draft"), trusted_context=context)

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


def test_commit_escalation_stops_at_needs_attention():
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


# --------------------------------------------------------------------------- #
# Atomic trusted result operation
# --------------------------------------------------------------------------- #

def _receipt_count(store, task):
    row = store._fetch_one("""SELECT COUNT(*) AS count FROM research_execution_plan_receipts
        WHERE task_id = :task""", {"task": task})
    return int(row["count"])


def test_atomic_result_commits_then_replays_without_another_write():
    store, task, context = _setup()
    try:
        plan = _seed_plan(store, task, "backtest_analysis")
        store.admit_research_stage_call(task, {"call_identity": "turn-a"}, trusted_context=context)
        payload = {
            "call_identity": "turn-a", "durable_evidence": {"kind": "none"},
            "proposal": _proposal(plan, "backtest_analysis", "backtest_analysis")}
        first = store.record_research_judgment_result(task, payload, trusted_context=context)
        assert first["replayed"] is False
        assert first["proposal"]["stage"] == "iteration_comparison"
        assert first["progress"]["outcome"] == "advance"
        assert _plan_row(store, task)["stage"] == "iteration_comparison"
        receipts = _receipt_count(store, task)
        assert receipts == 1

        replay = store.record_research_judgment_result(task, payload, trusted_context=context)
        assert replay["replayed"] is True
        assert replay["proposal"] == first["proposal"]
        assert _receipt_count(store, task) == receipts
        assert _plan_row(store, task)["plan_version"] == 2
    finally:
        store.close()


def test_atomic_result_invalid_evidence_after_valid_proposal_changes_nothing():
    store, task, context = _setup()
    try:
        plan = _seed_plan(store, task, "backtest_analysis")
        before_task = _task_row(store, task)
        store.admit_research_stage_call(task, {"call_identity": "turn-a"}, trusted_context=context)
        payload = {
            "call_identity": "turn-a",
            "durable_evidence": {"kind": "artifact", "id": "artifact_" + "e" * 32},
            "proposal": _proposal(plan, "backtest_analysis", "backtest_analysis")}
        with pytest.raises(ValueError):
            store.record_research_judgment_result(task, payload, trusted_context=context)
        persisted = _plan_row(store, task)
        assert persisted["plan_version"] == plan["plan_version"]
        assert persisted["stage"] == "backtest_analysis"
        assert _receipt_count(store, task) == 0
        assert _task_row(store, task)["version"] == before_task["version"]
        call = store._fetch_one("""SELECT status, result_json FROM research_judgment_stage_calls
            WHERE task_id = :task AND call_identity = 'turn-a'""", {"task": task})
        assert call["status"] == "admitted" and call["result_json"] is None
    finally:
        store.close()


def test_atomic_result_injected_failure_rolls_back_everything():
    store, task, context = _setup()
    try:
        plan = _seed_plan(store, task, "backtest_analysis")
        before_task = _task_row(store, task)
        store.admit_research_stage_call(task, {"call_identity": "turn-a"}, trusted_context=context)

        def _explode(*args, **kwargs):
            raise RuntimeError("injected failure between proposal decision and call completion")

        store._complete_stage_call = _explode
        payload = {
            "call_identity": "turn-a", "durable_evidence": {"kind": "none"},
            "proposal": _proposal(plan, "backtest_analysis", "backtest_analysis")}
        with pytest.raises(RuntimeError):
            store.record_research_judgment_result(task, payload, trusted_context=context)
        persisted = _plan_row(store, task)
        assert persisted["plan_version"] == plan["plan_version"]
        assert persisted["stage"] == "backtest_analysis"
        assert _receipt_count(store, task) == 0
        assert _task_row(store, task)["version"] == before_task["version"]
        call = store._fetch_one("""SELECT status, result_json FROM research_judgment_stage_calls
            WHERE task_id = :task AND call_identity = 'turn-a'""", {"task": task})
        assert call["status"] == "admitted" and call["result_json"] is None
    finally:
        store.close()


def test_atomic_result_for_unadmitted_call_and_no_progress_fence():
    store, task, context = _setup()
    try:
        _seed_plan(store, task, "backtest_analysis")
        with pytest.raises(InvalidTransition):
            store.record_research_judgment_result(
                task, {"call_identity": "never-admitted", "durable_evidence": {"kind": "none"}},
                trusted_context=context)
        store.admit_research_stage_call(task, {"call_identity": "turn-a"}, trusted_context=context)
        fenced = store.record_research_judgment_result(
            task, {"call_identity": "turn-a", "durable_evidence": {"kind": "none"}},
            trusted_context=context)
        assert fenced["progress"]["plan_moved_to_needs_attention"] is True
        assert _plan_row(store, task)["stage"] == "needs_attention"
        assert _task_row(store, task)["progress"]["blocked_reason"] == "no_durable_progress"
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# Terminal convergence
# --------------------------------------------------------------------------- #

def test_final_selection_hands_off_to_the_paper_account_gate():
    store, task, context = _setup()
    try:
        store.transition("research_task", task, "running", "task-running")
        artifact = _artifact(store, task, key="final-result")
        store.transition("artifact", artifact["artifact_id"], "validated", "validate-final")
        plan = _seed_plan(store, task, "final_selection", iteration=3, references={
            "research_task": {"research_task": task},
            "backtest_result": {"backtest_result": artifact["artifact_id"]}})
        committed = store.commit_research_proposal(
            task, _proposal(plan, "final_selection", "select_iteration", iteration=3,
                            selected_iteration=2), trusted_context=context)
        # ADR-0087: final selection NEVER completes research directly; it enters
        # the explicit deterministic paper-account approval gate.
        assert committed["stage"] == "waiting_for_paper_account_approval"
        persisted = _plan_row(store, task)
        assert persisted["stage"] == "waiting_for_paper_account_approval"
        assert persisted["status"] == "waiting"
        row = _task_row(store, task)
        assert row["status"] != "completed"
        approval = persisted["plan"]["approval"]
        assert approval["action"] == "create_paper_account"
        assert approval["resource_kind"] == "research_task"
        assert approval["resource_id"] == task
    finally:
        store.close()


def test_final_selection_without_validated_evidence_defers_completion():
    # The final-selection commit only reaches the paper-account gate; the
    # validated-evidence requirement now applies at the deterministic completion
    # (covered by tests/test_research_paper_account_continuation.py).
    store, task, context = _setup()
    try:
        store.transition("research_task", task, "running", "task-running")
        plan = _seed_plan(store, task, "final_selection", iteration=3)
        committed = store.commit_research_proposal(
            task, _proposal(plan, "final_selection", "select_iteration", iteration=3,
                            selected_iteration=2), trusted_context=context)
        assert committed["stage"] == "waiting_for_paper_account_approval"
        assert _task_row(store, task)["status"] != "completed"
    finally:
        store.close()


def test_owner_isolation_on_all_seams():
    store, task, context = _setup()
    try:
        plan = _seed_plan(store, task, "backtest_analysis")
        other = trusted_agent_context("judgment-other", session_id="other-session", trace_id="other-trace")
        other_context = {key.removeprefix("x-byq-").replace("-", "_"): value for key, value in other.items()}
        with pytest.raises(ResearchNotFound):
            store.get_research_stage_input(task, trusted_context=other_context)
        with pytest.raises(ResearchNotFound):
            store.admit_research_stage_call(task, {"call_identity": "x"}, trusted_context=other_context)
        with pytest.raises(ResearchNotFound):
            store.commit_research_proposal(
                task, _proposal(plan, "backtest_analysis", "backtest_analysis"),
                trusted_context=other_context)
    finally:
        store.close()


def test_stage_call_retry_after_interruption_reuses_the_same_attempt_identity():
    """Fail-able repro: a retry must reuse the durable attempt identity.

    The old adapter generated a fresh call_identity per POST, so an admit that
    succeeded but lost its result (adapter restart/timeout) would create a second
    stage_call and consume the stage's second model-call slot. With the
    authoritative plan-derived identity, the retry is a free replay.
    """

    import hashlib

    store, task, context = _setup("retry-user", "retry-session", "retry-trace")
    try:
        _seed_plan(store, task, "backtest_analysis")
        plan = _plan_row(store, task)["plan"]
        attempt = f"{plan['plan_version']}:{plan['stage']}:{plan['iteration']}"
        # Mirrors services/runtime-adapter/app/research_judgment_boundary.derive_call_identity.
        identity = "byq-judgment-" + hashlib.sha256(
            f"{task}:{attempt}".encode()).hexdigest()[:32]
        first = store.admit_research_stage_call(
            task, {"call_identity": identity}, trusted_context=context)
        assert first["call_index"] == 1
        replay = store.admit_research_stage_call(
            task, {"call_identity": identity}, trusted_context=context)
        assert replay["call_index"] == 1
        count = store._fetch_one(
            "SELECT COUNT(*) AS c FROM research_judgment_stage_calls WHERE task_id = :t",
            {"t": task})["c"]
        assert count == 1
        # A fresh identity (the defect) would consume the second slot and a third
        # would be refused; this records the failure mode the retry-stable identity
        # avoids.
        second = store.admit_research_stage_call(
            task, {"call_identity": "byq-judgment-second"}, trusted_context=context)
        assert second["call_index"] == 2
        with pytest.raises(StageModelCallLimitExceeded):
            store.admit_research_stage_call(
                task, {"call_identity": "byq-judgment-third"}, trusted_context=context)
    finally:
        store.close()


def test_admit_exposes_created_and_replays_completed_with_receipt():
    import hashlib

    store, task, context = _setup("admit-user", "admit-session", "admit-trace")
    try:
        _seed_plan(store, task, "backtest_analysis")
        plan = _plan_row(store, task)["plan"]
        attempt = f"{plan['plan_version']}:{plan['stage']}:{plan['iteration']}"
        identity = "byq-judgment-" + hashlib.sha256(
            f"{task}:{attempt}".encode()).hexdigest()[:32]
        admission = store.admit_research_stage_call(
            task, {"call_identity": identity, "attempt_binding": attempt},
            trusted_context=context)
        assert admission["created"] is True and admission["status"] == "admitted"
        replay = store.admit_research_stage_call(
            task, {"call_identity": identity, "attempt_binding": attempt},
            trusted_context=context)
        assert replay["created"] is False and replay["status"] == "admitted"

        result = store.record_research_judgment_result(
            task, {"call_identity": identity, "durable_evidence": {"kind": "none"},
                   "proposal": _proposal(plan, "backtest_analysis", "backtest_analysis")},
            trusted_context=context)
        # The proposal actually advanced the plan (so the old attempt binding is
        # now stale). This is what makes the late-retry ordering test meaningful.
        advanced = _plan_row(store, task)
        assert advanced["plan_version"] == plan["plan_version"] + 1
        assert advanced["plan"]["stage"] == "iteration_comparison"
        before_count = store._fetch_one(
            "SELECT COUNT(*) AS c FROM research_judgment_stage_calls WHERE task_id = :t",
            {"t": task})["c"]

        # A retry whose response was lost returns the stored receipt and does NOT
        # report a fresh admission, even though the plan has advanced past the
        # attempt's stage and the old attempt binding no longer matches it.
        late = store.admit_research_stage_call(
            task, {"call_identity": identity, "attempt_binding": attempt},
            trusted_context=context)
        assert late["status"] == "completed" and late["created"] is False
        # The FIRST response only differs from the persisted receipt by the
        # transient `replayed` marker; compare EVERY persisted field.
        assert result["replayed"] is False
        persisted = {key: value for key, value in result.items() if key != "replayed"}
        assert late["receipt"] == persisted
        assert "replayed" not in late["receipt"]
        assert late["call_index"] == 1 and late["stage"] == "backtest_analysis"
        # No new stage call, no model call, and the plan is unchanged.
        after_count = store._fetch_one(
            "SELECT COUNT(*) AS c FROM research_judgment_stage_calls WHERE task_id = :t",
            {"t": task})["c"]
        assert after_count == before_count == 1
        unchanged = _plan_row(store, task)
        assert unchanged["plan_version"] == advanced["plan_version"]
        assert unchanged["plan"]["stage"] == "iteration_comparison"
    finally:
        store.close()


def test_forged_or_stale_attempt_binding_cannot_consume_budget():
    import hashlib

    store, task, context = _setup("attempt-user", "attempt-session", "attempt-trace")
    try:
        _seed_plan(store, task, "backtest_analysis")
        plan = _plan_row(store, task)["plan"]

        def identity(attempt: str) -> str:
            return "byq-judgment-" + hashlib.sha256(
                f"{task}:{attempt}".encode()).hexdigest()[:32]

        good = f"{plan['plan_version']}:{plan['stage']}:{plan['iteration']}"
        store.admit_research_stage_call(
            task, {"call_identity": identity(good), "attempt_binding": good},
            trusted_context=context)
        before = store._fetch_one(
            "SELECT COUNT(*) AS c FROM research_judgment_stage_calls WHERE task_id = :t",
            {"t": task})["c"]
        for bad in (f"{plan['plan_version'] + 9}:{plan['stage']}:{plan['iteration']}",
                    f"{plan['plan_version']}:iteration_comparison:{plan['iteration']}",
                    f"{plan['plan_version']}:{plan['stage']}:{plan['iteration'] + 9}"):
            with pytest.raises(InvalidTransition):
                store.admit_research_stage_call(
                    task, {"call_identity": identity(bad), "attempt_binding": bad},
                    trusted_context=context)
        after = store._fetch_one(
            "SELECT COUNT(*) AS c FROM research_judgment_stage_calls WHERE task_id = :t",
            {"t": task})["c"]
        assert after == before == 1
    finally:
        store.close()
