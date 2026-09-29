from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import uuid4

import pytest

from app.audit_event import AuditEmitter
from app.factor_job import FactorJobStore
from app import factor_job as factor_job_module
from app.factor_research import compute_factor
from app.factor_submission import submit_factor
from app.research import IdempotencyConflict, InvalidTransition, ResearchStore
from tests.test_factor_research import factor_payload
from tests.workspace_helpers import trusted_agent_context
from workers.factor.worker import FactorWorker


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


@pytest.fixture
def factor_job_case():
    owner = f"factor-job-{uuid4().hex[:12]}"
    headers = trusted_agent_context(owner, trace_id=f"trace-{uuid4().hex[:12]}")
    context = {key.removeprefix("x-byq-").replace("-", "_"): value for key, value in headers.items()}
    research = ResearchStore()
    task = research.create_task(
        {
            "owner_principal": owner,
            "title": "Factor Job test",
            "objective": "Exercise durable factor Job behavior.",
            "trace_id": context["trace_id"],
            "idempotency_key": f"task-{uuid4().hex}",
        },
        trusted_context=context,
    )
    jobs = FactorJobStore()
    payload = {
        **factor_payload(),
        "task_id": task["task_id"],
        "trace_id": context["trace_id"],
        "idempotency_key": f"factor-{uuid4().hex}",
    }
    try:
        yield jobs, research, context, payload
    finally:
        jobs.close()
        research.close()


def _create_experiment(research: ResearchStore, task_id: str, trace_id: str) -> str:
    result = research.create_experiment(
        {
            "task_id": task_id,
            "name": "Factor Job input",
            "input_snapshot": {
                "sources": [{
                    "provider": "tushare",
                    "endpoint": "daily",
                    "request_fingerprint": f"factor-job-{uuid4().hex}",
                }]
            },
            "trace_id": trace_id,
            "idempotency_key": f"experiment-{uuid4().hex}",
        }
    )
    return str(result["experiment_id"])


def _create(jobs, context, payload):
    return jobs.create(
        payload,
        trusted_owner=context["owner_principal"],
        trusted_workspace=context["workspace_id"],
    )


def test_factor_job_idempotency_normalizes_input_and_binds_trace_and_experiment(factor_job_case):
    jobs, research, context, payload = factor_job_case
    task_id = str(payload["task_id"])
    experiment_a = _create_experiment(research, task_id, str(payload["trace_id"]))
    experiment_b = _create_experiment(research, task_id, str(payload["trace_id"]))
    request = {**payload, "experiment_id": experiment_a}

    first = _create(jobs, context, request)
    reordered = _create(
        jobs,
        context,
        {
            **request,
            "bars": list(reversed(request["bars"])),
            "sessions": list(reversed(request["sessions"])),
        },
    )
    assert first["job_id"] == reordered["job_id"]
    assert first["status"] == "QUEUED"
    assert first["input_ref"]
    assert "request_json" not in first
    assert "owner_principal" not in first

    with pytest.raises(IdempotencyConflict):
        _create(jobs, context, {**request, "trace_id": "different-trace"})
    with pytest.raises(IdempotencyConflict):
        _create(jobs, context, {**request, "experiment_id": experiment_b})


def test_factor_job_rejects_artifact_key_collision(factor_job_case):
    jobs, research, context, payload = factor_job_case
    research.create_artifact(
        {
            "task_id": payload["task_id"],
            "kind": "factor_result",
            "content": {"source": "already-used"},
            "trace_id": payload["trace_id"],
            "idempotency_key": payload["idempotency_key"],
        },
        trusted_owner=context["owner_principal"],
        trusted_workspace=context["workspace_id"],
    )
    with pytest.raises(IdempotencyConflict):
        _create(jobs, context, payload)


def test_factor_job_claim_is_single_and_failure_retries_stop_at_three(factor_job_case):
    jobs, _research, context, payload = factor_job_case
    first = _create(jobs, context, payload)

    def claim(worker_id: int):
        other = FactorJobStore()
        try:
            return other.claim_next(f"worker-{worker_id}")
        finally:
            other.close()

    with ThreadPoolExecutor(max_workers=3) as pool:
        claims = list(pool.map(claim, range(3)))
    claimed = [item for item in claims if item is not None]
    assert len(claimed) == 1
    assert claimed[0]["job_id"] == first["job_id"]
    assert claimed[0]["attempt"] == 1

    assert jobs.fail(first["job_id"], 1, "factor_execution_failed", "factor computation failed")
    second = jobs.claim_next("worker-retry-2")
    assert second is not None and second["attempt"] == 2
    assert jobs.fail(first["job_id"], 2, "factor_execution_failed", "factor computation failed")
    third = jobs.claim_next("worker-retry-3")
    assert third is not None and third["attempt"] == 3
    assert jobs.fail(first["job_id"], 3, "factor_execution_failed", "factor computation failed")
    assert jobs.claim_next("worker-exhausted") is None

    public = jobs.get(
        job_id=first["job_id"],
        trusted_owner=context["owner_principal"],
        trusted_workspace=context["workspace_id"],
    )
    assert public is not None and public["status"] == "FAILED"
    assert public["error"]["code"] == "factor_execution_failed"
    row = jobs._fetch_one("SELECT attempts FROM factor_jobs WHERE job_id=:job", {"job": first["job_id"]})
    assert row is not None and row["attempts"] == 3


def test_factor_job_cancel_is_idempotent_and_only_changes_active_jobs(factor_job_case):
    jobs, research, context, payload = factor_job_case
    queued = _create(jobs, context, payload)
    assert jobs.cancel(queued["job_id"], trusted_owner="someone-else",
        trusted_workspace=context["workspace_id"]) is None
    assert jobs.cancel(queued["job_id"], trusted_owner=context["owner_principal"],
        trusted_workspace="workspace_not_owned") is None
    first = jobs.cancel(queued["job_id"], trusted_owner=context["owner_principal"],
        trusted_workspace=context["workspace_id"])
    assert first is not None and first["status"] == "CANCELLED"
    assert first["error"]["code"] == "cancelled"
    assert jobs.cancel(queued["job_id"], trusted_owner=context["owner_principal"],
        trusted_workspace=context["workspace_id"]) == first
    assert jobs.claim_next("after-cancel") is None

    completed = _create(jobs, context, {**payload, "idempotency_key": f"completed-{uuid4().hex}"})
    assert FactorWorker(jobs, research, worker_id="factor-completion-test").run_once()
    before_completed_cancel = jobs.get(job_id=completed["job_id"],
        trusted_owner=context["owner_principal"], trusted_workspace=context["workspace_id"])
    assert before_completed_cancel is not None and before_completed_cancel["status"] == "SUCCEEDED"
    assert jobs.cancel(completed["job_id"], trusted_owner=context["owner_principal"],
        trusted_workspace=context["workspace_id"]) == before_completed_cancel

    failed = _create(jobs, context, {**payload, "idempotency_key": f"failed-{uuid4().hex}"})
    claim = jobs.claim_next("factor-failure-test")
    assert claim is not None and claim["job_id"] == failed["job_id"]
    assert jobs.fail(failed["job_id"], claim["attempt"], "factor_execution_failed",
        "factor computation failed", retryable=False)
    before_failed_cancel = jobs.get(job_id=failed["job_id"],
        trusted_owner=context["owner_principal"], trusted_workspace=context["workspace_id"])
    assert before_failed_cancel is not None and before_failed_cancel["status"] == "FAILED"
    assert jobs.cancel(failed["job_id"], trusted_owner=context["owner_principal"],
        trusted_workspace=context["workspace_id"]) == before_failed_cancel


def test_factor_cancel_route_is_owner_scoped_and_replayable(factor_job_case, monkeypatch):
    from fastapi.testclient import TestClient

    from app import main

    jobs, _research, context, payload = factor_job_case
    public = _create(jobs, context, payload)
    monkeypatch.setattr(main, "factor_job_store", jobs)
    client = TestClient(main.app)
    path = f"/v1/research/factor-jobs/{public['job_id']}/cancel"
    owner_headers = {f"x-byq-{key.replace('_', '-')}": value for key, value in context.items()}

    foreign = trusted_agent_context(f"factor-foreign-{uuid4().hex[:8]}")
    denied = client.post(path, headers=foreign, json={})
    assert denied.status_code == 404
    still_queued = jobs.get(job_id=public["job_id"], trusted_owner=context["owner_principal"],
        trusted_workspace=context["workspace_id"])
    assert still_queued is not None and still_queued["status"] == "QUEUED"

    cancelled = client.post(path, headers=owner_headers, json={})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["job"]["status"] == "CANCELLED"
    replay = client.post(path, headers=owner_headers, json={})
    assert replay.status_code == 200 and replay.json() == cancelled.json()


def test_factor_cancel_fences_claimed_worker_before_artifact_commit(factor_job_case, monkeypatch):
    jobs, research, context, payload = factor_job_case
    public = _create(jobs, context, payload)
    entered, release = Event(), Event()
    require_claim = jobs.require_execution_claim

    def pause_before_execution_lock(connection, job_id, attempt):
        entered.set()
        assert release.wait(5)
        return require_claim(connection, job_id, attempt)

    monkeypatch.setattr(jobs, "require_execution_claim", pause_before_execution_lock)
    worker = FactorWorker(jobs, research, compute=lambda _value: pytest.fail("cancelled worker must not compute"),
        worker_id="cancelled-factor-worker")
    canceller = FactorJobStore()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker.run_once)
            assert entered.wait(5)
            cancelled = canceller.cancel(public["job_id"], trusted_owner=context["owner_principal"],
                trusted_workspace=context["workspace_id"])
            assert cancelled is not None and cancelled["status"] == "CANCELLED"
            release.set()
            assert future.result(timeout=10)
    finally:
        release.set()
        canceller.close()

    assert not jobs.complete(public["job_id"], 1, "artifact_" + "0" * 32)
    current = jobs.get(job_id=public["job_id"], trusted_owner=context["owner_principal"],
        trusted_workspace=context["workspace_id"])
    assert current is not None and current["status"] == "CANCELLED"
    assert research._fetch_one("SELECT COUNT(*) AS n FROM artifacts WHERE task_id=:task AND kind='factor_result'",
        {"task": payload["task_id"]})["n"] == 0


def test_expired_attempt_loses_completion_fence(factor_job_case):
    jobs, research, context, payload = factor_job_case
    events = []
    committed = []

    def collect_after_commit(event):
        events.append(event)
        current = jobs._fetch_one(
            "SELECT status FROM factor_jobs WHERE job_id=:job", {"job": event["job_id"]}
        )
        artifact = research._fetch_one(
            "SELECT status FROM artifacts WHERE artifact_id=:artifact",
            {"artifact": event["metadata"]["artifact_id"]},
        )
        committed.append((current["status"], artifact["status"]))

    jobs.audit_emitter = AuditEmitter(collect_after_commit)
    public = _create(jobs, context, payload)
    old_claim = jobs.claim_next("worker-old")
    assert old_claim is not None and old_claim["attempt"] == 1
    unrelated = research.create_artifact(
        {"task_id": payload["task_id"], "kind": "factor_result",
         "content": {"source": "unrelated"}, "trace_id": payload["trace_id"],
         "idempotency_key": f"fence-unrelated-{uuid4().hex}"},
        trusted_owner=context["owner_principal"], trusted_workspace=context["workspace_id"],
    )
    unrelated = research.transition(
        "artifact", unrelated["artifact_id"], "validated", f"fence-unrelated-validation-{uuid4().hex}"
    )
    artifact = submit_factor(research, {**payload,
        "idempotency_key": f"factor-result-{public['job_id']}"}, context, compute_factor)["artifact"]
    artifact = research.transition(
        "artifact", artifact["artifact_id"], "validated", f"factor-validation-{public['job_id']}"
    )
    jobs._execute(
        "UPDATE factor_jobs SET claimed_at=:expired WHERE job_id=:job",
        {"expired": datetime.now(timezone.utc) - timedelta(minutes=10), "job": public["job_id"]},
    )
    assert not jobs.complete(public["job_id"], 1, artifact["artifact_id"])
    assert events == []
    current_claim = jobs.claim_next("worker-current")
    assert current_claim is not None and current_claim["attempt"] == 2
    assert not jobs.complete(public["job_id"], 1, artifact["artifact_id"])
    assert not jobs.complete(public["job_id"], 2, unrelated["artifact_id"])
    assert events == []
    assert jobs.complete(public["job_id"], 2, artifact["artifact_id"])

    completed = jobs.get(
        job_id=public["job_id"],
        trusted_owner=context["owner_principal"],
        trusted_workspace=context["workspace_id"],
    )
    assert completed is not None
    assert completed["status"] == "SUCCEEDED"
    assert completed["result_ref"] == artifact["artifact_id"]
    assert committed == [("completed", "validated")]
    assert len(events) == 1
    assert events[0] == {
        "schema_version": "audit-event.v1",
        "event_id": events[0]["event_id"],
        "occurred_at": events[0]["occurred_at"],
        "workspace_id": context["workspace_id"],
        "owner_principal": context["owner_principal"],
        "actor_principal": "byq.factor_worker",
        "action": "job.completed",
        "resource_type": "job",
        "resource_id": public["job_id"],
        "result": "success",
        "request_id": None,
        "job_id": public["job_id"],
        "metadata": {"artifact_id": artifact["artifact_id"], "trace_id": payload["trace_id"]},
    }


def test_failed_factor_attempt_does_not_emit_completion_observation(factor_job_case):
    jobs, research, context, payload = factor_job_case
    events = []
    jobs.audit_emitter = AuditEmitter(events.append)
    public = _create(jobs, context, payload)
    claim = jobs.claim_next("failed-factor-worker")
    assert claim is not None

    assert jobs.fail(public["job_id"], claim["attempt"], "factor_execution_failed", "failed", retryable=False)
    assert events == []


def test_external_job_transaction_defers_completion_event_until_commit(factor_job_case):
    jobs, research, context, payload = factor_job_case
    events = []
    jobs.audit_emitter = AuditEmitter(events.append)
    public = _create(jobs, context, payload)
    claim = jobs.claim_next("external-transaction-worker")
    assert claim is not None
    artifact = submit_factor(
        research,
        {**payload, "idempotency_key": f"factor-result-{public['job_id']}"},
        context,
        compute_factor,
    )["artifact"]
    artifact = research.transition(
        "artifact", artifact["artifact_id"], "validated", f"factor-validation-{public['job_id']}"
    )

    with jobs._transaction() as connection:
        assert jobs.complete(public["job_id"], claim["attempt"], artifact["artifact_id"], _connection=connection)
        assert events == []

    assert len(events) == 1
    assert jobs.get(
        job_id=public["job_id"], trusted_owner=context["owner_principal"],
        trusted_workspace=context["workspace_id"],
    )["status"] == "SUCCEEDED"


def test_transaction_rollback_discards_deferred_completion_event(factor_job_case):
    jobs, research, context, payload = factor_job_case
    events = []
    jobs.audit_emitter = AuditEmitter(events.append)
    public = _create(jobs, context, payload)
    claim = jobs.claim_next("rollback-transaction-worker")
    assert claim is not None
    artifact = submit_factor(
        research,
        {**payload, "idempotency_key": f"factor-result-{public['job_id']}"},
        context,
        compute_factor,
    )["artifact"]
    artifact = research.transition(
        "artifact", artifact["artifact_id"], "validated", f"factor-validation-{public['job_id']}"
    )

    with pytest.raises(RuntimeError, match="rollback completion"):
        with jobs._transaction() as connection:
            assert jobs.complete(public["job_id"], claim["attempt"], artifact["artifact_id"], _connection=connection)
            assert events == []
            raise RuntimeError("rollback completion")

    assert events == []
    current = jobs.get(
        job_id=public["job_id"], trusted_owner=context["owner_principal"],
        trusted_workspace=context["workspace_id"],
    )
    assert current is not None and current["status"] == "RUNNING" and current["result_ref"] is None


def test_audit_sink_failure_cannot_change_successful_factor_job(factor_job_case, caplog):
    jobs, research, context, payload = factor_job_case

    def broken_sink(_event):
        raise RuntimeError("api_key=must-not-be-logged")

    jobs.audit_emitter = AuditEmitter(broken_sink)
    public = _create(jobs, context, payload)
    worker = FactorWorker(jobs, research, worker_id="audit-sink-failure-worker")

    assert worker.run_once()
    completed = jobs.get(
        job_id=public["job_id"],
        trusted_owner=context["owner_principal"],
        trusted_workspace=context["workspace_id"],
    )
    assert completed is not None and completed["status"] == "SUCCEEDED"
    assert completed["result_ref"]
    assert "audit event sink failed" in caplog.text
    assert "must-not-be-logged" not in caplog.text


def test_expired_final_attempt_recovers_validated_artifact(factor_job_case):
    jobs, research, context, payload = factor_job_case
    events = []
    observed_statuses = []

    def collect_after_commit(event):
        events.append(event)
        current = jobs._fetch_one(
            "SELECT status FROM factor_jobs WHERE job_id=:job", {"job": event["job_id"]}
        )
        observed_statuses.append(current["status"])

    jobs.audit_emitter = AuditEmitter(collect_after_commit)
    public = _create(jobs, context, payload)
    for attempt in (1, 2):
        claim = jobs.claim_next(f"worker-{attempt}")
        assert claim is not None and claim["attempt"] == attempt
        assert jobs.fail(public["job_id"], attempt, "factor_execution_failed", "retry")
    final = jobs.claim_next("worker-3")
    assert final is not None and final["attempt"] == 3
    artifact = submit_factor(research, {**payload,
        "idempotency_key": f"factor-result-{public['job_id']}"}, context, compute_factor)["artifact"]
    artifact = research.transition(
        "artifact", artifact["artifact_id"], "validated", f"factor-validation-{public['job_id']}"
    )
    jobs._execute("UPDATE factor_jobs SET claimed_at=:expired WHERE job_id=:job",
        {"expired": datetime.now(timezone.utc) - timedelta(minutes=10), "job": public["job_id"]})
    assert jobs.claim_next("recovery-worker") is None
    recovered = jobs.get(job_id=public["job_id"],
        trusted_owner=context["owner_principal"], trusted_workspace=context["workspace_id"])
    assert recovered is not None and recovered["status"] == "SUCCEEDED"
    assert recovered["result_ref"] == artifact["artifact_id"]
    assert observed_statuses == ["completed"]
    assert len(events) == 1
    assert events[0]["job_id"] == public["job_id"]
    assert events[0]["metadata"] == {
        "artifact_id": artifact["artifact_id"], "trace_id": payload["trace_id"]
    }


def test_live_final_attempt_cannot_publish_after_lease_expires(factor_job_case, monkeypatch):
    jobs, research, context, payload = factor_job_case
    public = _create(jobs, context, payload)
    for attempt in (1, 2):
        assert jobs.claim_next(f"earlier-{attempt}")["attempt"] == attempt
        assert jobs.fail(public["job_id"], attempt, "factor_execution_failed", "retry")
    monkeypatch.setattr(factor_job_module, "CLAIM_LEASE_SECONDS", 1)
    entered, release = Event(), Event()

    def paused_compute(value):
        entered.set()
        assert release.wait(5)
        return compute_factor(value)

    worker = FactorWorker(jobs, research, compute=paused_compute, worker_id="slow-final-worker")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker.run_once)
        assert entered.wait(5)
        time.sleep(1.1)
        # The live worker holds the Job row until its result transaction ends.
        concurrent = FactorJobStore()
        try:
            assert concurrent.claim_next("concurrent-recovery") is None
        finally:
            concurrent.close()
        release.set()
        assert future.result(timeout=5)
    assert research._fetch_one(
        "SELECT COUNT(*) AS n FROM artifacts WHERE task_id=:task AND kind='factor_result'",
        {"task": payload["task_id"]})["n"] == 0
    assert jobs.claim_next("after-worker-exit") is None
    final = jobs.get(job_id=public["job_id"], trusted_owner=context["owner_principal"],
        trusted_workspace=context["workspace_id"])
    assert final is not None and final["status"] == "FAILED"


def test_research_task_cannot_complete_while_factor_job_is_queued(factor_job_case):
    jobs, research, _context, payload = factor_job_case
    _create(jobs, _context, payload)
    report = research.create_artifact({
        "task_id": payload["task_id"], "kind": "research_report", "content": {"synthetic": True},
        "lineage": [], "trace_id": payload["trace_id"],
        "idempotency_key": f"factor-task-report-{uuid4().hex}",
    })
    research.transition("artifact", report["artifact_id"], "validated", f"factor-report-{uuid4().hex}")
    research.transition("research_task", payload["task_id"], "running", f"factor-task-run-{uuid4().hex}")
    progress = {"schema_version": "research-progress.v1", "stage": "completed",
        "next_action": None, "blocked_reason": None, "linked_objects": [],
        "completion_evidence": [report["artifact_id"]]}
    with pytest.raises(InvalidTransition, match="unfinished domain work"):
        research.transition("research_task", payload["task_id"], "completed",
            f"factor-task-complete-{uuid4().hex}", progress=progress,
            require_completion_evidence=True)


def test_worker_rolls_back_artifact_after_fenced_completion(factor_job_case, monkeypatch):
    jobs, research, context, payload = factor_job_case
    public = _create(jobs, context, payload)
    compute_calls = []

    def counted(value):
        compute_calls.append(1)
        return compute_factor(value)

    complete = jobs.complete
    monkeypatch.setattr(jobs, "complete", lambda *_args, **_kwargs: False)
    worker = FactorWorker(jobs, research, compute=counted, worker_id="factor-worker-test")
    assert worker.run_once()
    first_row = jobs._fetch_one("SELECT status, result_artifact_id FROM factor_jobs WHERE job_id=:job",
                                {"job": public["job_id"]})
    assert first_row is not None and first_row["status"] == "queued"
    assert research._fetch_one("SELECT COUNT(*) AS n FROM artifacts WHERE task_id=:task AND kind='factor_result'",
        {"task": payload["task_id"]})["n"] == 0
    monkeypatch.setattr(jobs, "complete", complete)
    assert worker.run_once()

    completed = jobs.get(
        job_id=public["job_id"],
        trusted_owner=context["owner_principal"],
        trusted_workspace=context["workspace_id"],
    )
    assert completed is not None and completed["status"] == "SUCCEEDED"
    assert completed["result_ref"]
    assert compute_calls == [1, 1]
    artifact = research.get_artifact(completed["result_ref"])
    assert artifact["kind"] == "factor_result"
    assert artifact["status"] == "validated"
