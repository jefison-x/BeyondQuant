from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import uuid4

import pytest

from app.factor_job import FactorJobStore
from app import factor_job as factor_job_module
from app.factor_research import compute_factor
from app.factor_submission import submit_factor
from app.research import IdempotencyConflict, InvalidTransition, ResearchStore
from test_factor_research import factor_payload
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


def test_expired_attempt_loses_completion_fence(factor_job_case):
    jobs, research, context, payload = factor_job_case
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
    current_claim = jobs.claim_next("worker-current")
    assert current_claim is not None and current_claim["attempt"] == 2
    assert not jobs.complete(public["job_id"], 1, artifact["artifact_id"])
    assert not jobs.complete(public["job_id"], 2, unrelated["artifact_id"])
    assert jobs.complete(public["job_id"], 2, artifact["artifact_id"])

    completed = jobs.get(
        job_id=public["job_id"],
        trusted_owner=context["owner_principal"],
        trusted_workspace=context["workspace_id"],
    )
    assert completed is not None
    assert completed["status"] == "SUCCEEDED"
    assert completed["result_ref"] == artifact["artifact_id"]


def test_expired_final_attempt_recovers_validated_artifact(factor_job_case):
    jobs, research, context, payload = factor_job_case
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
