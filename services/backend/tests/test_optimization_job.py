"""Contract and isolated PostgreSQL checks for completed-candidate search."""

from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import main
from app.backtest import BacktestConflict, BacktestJobStore, BacktestWorker, LocalObjectStore
from app.optimization_job import (
    OptimizationConflict,
    OptimizationJobStore,
    OptimizationLeaseLost,
    OptimizationValidationError,
    OptimizationWorker,
    normalize_optimization_request,
    rank_completed_candidates,
)
from app.business_job import project_business_job
from app.research import ResearchStore
from tests.test_backtest_api import _create_strategy_chain, _owner_headers, _snapshot_input, _strategy


TASK_ID = "task_" + "a" * 32
BACKTEST_A = "backtest_" + "a" * 32
BACKTEST_B = "backtest_" + "b" * 32


def _request(*, objective: str = "total_return") -> dict[str, object]:
    return {
        "task_id": TASK_ID,
        "trace_id": "trace-1",
        "idempotency_key": "optimization-1",
        "objective": objective,
        "candidates": [
            {"backtest_job_id": BACKTEST_B, "parameters": {"window": 20}},
            {"backtest_job_id": BACKTEST_A, "parameters": {"window": 10}},
        ],
    }


def test_normalize_request_sorts_candidate_ids_and_freezes_explicit_parameters() -> None:
    normalized = normalize_optimization_request(_request())

    assert normalized["task_id"] == TASK_ID
    assert [row["backtest_job_id"] for row in normalized["candidates"]] == [BACKTEST_A, BACKTEST_B]
    assert normalized["candidates"][0]["parameters"] == {"window": 10}


def test_public_projection_has_stable_identity_and_frozen_input_reference() -> None:
    row = {
        "job_id": "optimizationjob_" + "c" * 32,
        "workspace_id": "workspace_" + "d" * 32,
        "task_id": TASK_ID,
        "request_json": _request(),
        "request_hash": "f" * 64,
        "status": "completed",
        "result_artifact_id": "artifact_" + "e" * 32,
        "created_at": "2026-09-28T00:00:00+00:00",
    }

    public = OptimizationJobStore._public_row(row)
    business_job = project_business_job("OPTIMIZATION", public)

    assert public["input_ref"] == f"optimization-request-sha256:{'f' * 64}"
    assert business_job["job_id"] == row["job_id"]
    assert business_job["input_ref"] == public["input_ref"]
    assert business_job["result_ref"] == row["result_artifact_id"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update(extra="not allowed"),
        lambda body: body.update(objective="unsupported"),
        lambda body: body.update(candidates=[body["candidates"][0]]),
        lambda body: body.update(candidates=[
            {"backtest_job_id": BACKTEST_A, "parameters": {"window": 10}},
            {"backtest_job_id": BACKTEST_B, "parameters": {"period": 20}},
        ]),
    ],
)
def test_normalize_request_rejects_invalid_or_incomparable_inputs(mutate) -> None:
    payload = _request()
    mutate(payload)

    with pytest.raises(OptimizationValidationError):
        normalize_optimization_request(payload)


@pytest.mark.parametrize(
    ("objective", "values", "winner", "direction"),
    [
        ("total_return", [0.1, 0.3], BACKTEST_B, "maximize"),
        ("sharpe_ratio", [-0.2, 0.1], BACKTEST_B, "maximize"),
        ("max_drawdown", [0.2, 0.05], BACKTEST_B, "minimize"),
    ],
)
def test_rank_completed_candidates_uses_objective_direction(objective, values, winner, direction) -> None:
    result = rank_completed_candidates(
        [
            {"backtest_job_id": BACKTEST_A, "parameters": {"window": 10}, "metric_value": values[0]},
            {"backtest_job_id": BACKTEST_B, "parameters": {"window": 20}, "metric_value": values[1]},
        ],
        objective=objective,
    )

    assert result["winner_backtest_job_id"] == winner
    assert result["objective"] == {"name": objective, "direction": direction}
    assert result["reran_backtests"] is False


def test_rank_allows_total_loss_and_breaks_ties_by_backtest_id() -> None:
    result = rank_completed_candidates(
        [
            {"backtest_job_id": BACKTEST_B, "parameters": {"window": 20}, "metric_value": -1},
            {"backtest_job_id": BACKTEST_A, "parameters": {"window": 10}, "metric_value": -1.0},
        ],
        objective="total_return",
    )

    assert [item["backtest_job_id"] for item in result["ranking"]] == [BACKTEST_A, BACKTEST_B]
    assert result["ranking"][0]["metric_value"] == -1


@pytest.mark.parametrize(
    ("objective", "value"),
    [
        ("total_return", -1.0001),
        ("max_drawdown", -0.01),
        ("max_drawdown", 1.01),
        ("sharpe_ratio", math.nan),
        ("sharpe_ratio", math.inf),
        ("sharpe_ratio", True),
    ],
)
def test_rank_rejects_invalid_candidate_metrics(objective, value) -> None:
    with pytest.raises(OptimizationValidationError):
        rank_completed_candidates(
            [
                {"backtest_job_id": BACKTEST_A, "parameters": {"window": 10}, "metric_value": value},
                {"backtest_job_id": BACKTEST_B, "parameters": {"window": 20}, "metric_value": 0.1},
            ],
            objective=objective,
        )


def _candidate_fact(job_id: str, parameters: dict[str, int]) -> dict[str, object]:
    return {
        "job_id": job_id,
        "status": "completed",
        "valid_strategy_artifact": True,
        "same_strategy_template": True,
        "strategy_parameters": parameters,
        "valid_result_artifact": True,
        "same_universe": True,
        "same_bars": True,
        "same_corporate_actions": True,
        "same_benchmark": True,
        "same_execution": True,
        "same_environment": True,
        "result_reference_json": {"object_id": "immutable-result"},
        "universe": {"symbols": ["000001.SZ"]},
        "execution": {"initial_capital": 100_000},
    }


def test_candidate_facts_bind_supplied_parameters_to_validated_strategy_versions() -> None:
    candidates = [
        {"backtest_job_id": BACKTEST_A, "parameters": {"window": 10}},
        {"backtest_job_id": BACKTEST_B, "parameters": {"window": 20}},
    ]
    facts = [_candidate_fact(BACKTEST_A, {"window": 10}), _candidate_fact(BACKTEST_B, {"window": 20})]

    OptimizationJobStore._validate_candidate_facts(facts, candidates)

    facts[1]["strategy_parameters"] = {"window": 21}
    with pytest.raises(OptimizationConflict, match="parameters"):
        OptimizationJobStore._validate_candidate_facts(facts, candidates)


@pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set")
def test_optimization_job_worker_commits_artifact_atomically_and_fences_cancelled_attempt(
    monkeypatch, tmp_path,
) -> None:
    research = ResearchStore()
    backtests = BacktestJobStore()
    jobs = OptimizationJobStore()
    objects = LocalObjectStore(tmp_path / "optimization-objects")
    monkeypatch.setattr(main, "research_store", research)
    monkeypatch.setattr(main, "backtest_store", backtests)
    monkeypatch.setattr(main, "optimization_job_store", jobs)
    monkeypatch.setattr(main, "backtest_objects", objects)
    client = TestClient(main.app)
    client.headers.update(_owner_headers("product-user"))
    worker = OptimizationWorker(jobs, research, objects, worker_id="optimization-test-worker")
    try:
        chain = _create_strategy_chain(client, key=f"optimization-{uuid4().hex[:12]}")
        task_id = chain["task"]["task_id"]
        trace_id = "byq-trace-product-user"

        # A second validated version changes only its explicit strategy parameters.
        parameters = {**_strategy(), "parameters": {"lookback": 10}}
        second_draft = client.post("/v1/research/strategies/validate", json={
            "task_id": task_id, "strategy": parameters, "trace_id": trace_id,
            "idempotency_key": f"optimization-draft-{uuid4().hex}",
        })
        assert second_draft.status_code == 201, second_draft.text
        second_version = client.post("/v1/research/strategies/versions", json={
            "task_id": task_id, "draft_artifact_id": second_draft.json()["artifact"]["artifact_id"],
            "trace_id": trace_id, "idempotency_key": f"optimization-version-{uuid4().hex}",
        })
        assert second_version.status_code == 201, second_version.text
        second_approval = client.post("/v1/research/strategies/approvals", json={
            "task_id": task_id,
            "strategy_version_artifact_id": second_version.json()["artifact"]["artifact_id"],
            "reviewer_principal": "product-user", "decision": "approved", "trace_id": trace_id,
            "idempotency_key": f"optimization-approval-{uuid4().hex}",
        })
        assert second_approval.status_code == 201, second_approval.text

        snapshot = _snapshot_input()
        backtest_rows = [
            (chain["version"]["artifact"]["artifact_id"], chain["approval"]["artifact"]["artifact_id"], {"lookback": 20}),
            (second_version.json()["artifact"]["artifact_id"], second_approval.json()["artifact"]["artifact_id"], {"lookback": 10}),
        ]
        backtest_ids: list[str] = []
        for index, (version_id, approval_id, _parameters) in enumerate(backtest_rows):
            submitted = client.post("/v1/research/backtests", json={
                "task_id": task_id, "strategy_version_artifact_id": version_id,
                "approval_artifact_id": approval_id, "trace_id": trace_id,
                "idempotency_key": f"optimization-backtest-{uuid4().hex}-{index}",
                **snapshot,
            })
            assert submitted.status_code == 202, submitted.text
            job_id = submitted.json()["job"]["job_id"]
            backtest_ids.append(job_id)
            completed = BacktestWorker(backtests, research, objects).run_once(job_id)
            assert completed["status"] == "completed"

        request = {
            "task_id": task_id, "objective": "total_return",
            "idempotency_key": f"optimization-submit-{uuid4().hex}",
            "candidates": [
                {"backtest_job_id": backtest_ids[0], "parameters": backtest_rows[0][2]},
                {"backtest_job_id": backtest_ids[1], "parameters": backtest_rows[1][2]},
            ],
        }
        # Submission holds source rows until its Job exists. A concurrent
        # delete must wait, then reject the durable reference.
        source_locked, release_submission = Event(), Event()
        original_lock = jobs._lock_candidate_rows

        def pause_after_source_lock(connection, submitted_request):
            original_lock(connection, submitted_request)
            source_locked.set()
            assert release_submission.wait(10)

        monkeypatch.setattr(jobs, "_lock_candidate_rows", pause_after_source_lock)
        with ThreadPoolExecutor(max_workers=2) as pool:
            creating = pool.submit(jobs.create, {**request, "trace_id": trace_id},
                                   trusted_owner="product-user",
                                   trusted_workspace=client.headers["x-byq-workspace-id"])
            assert source_locked.wait(10)
            deleting = pool.submit(backtests.delete, backtest_ids[0], owner_principal="product-user")
            release_submission.set()
            created = creating.result(timeout=15)
            with pytest.raises(BacktestConflict, match="referenced"):
                deleting.result(timeout=15)
        monkeypatch.setattr(jobs, "_lock_candidate_rows", original_lock)

        submitted = client.post("/v1/research/optimization-jobs", json=request)
        assert submitted.status_code == 202, submitted.text
        queued = submitted.json()["job"]
        assert queued["job_id"] == created["job_id"]
        assert queued["status"] == "QUEUED"
        assert "request_json" not in queued and "owner_principal" not in queued
        repeated = client.post("/v1/research/optimization-jobs", json=request)
        assert repeated.status_code == 202 and repeated.json()["job"]["job_id"] == queued["job_id"]
        conflict = client.post("/v1/research/optimization-jobs", json={**request, "objective": "max_drawdown"})
        assert conflict.status_code == 409

        foreign = TestClient(main.app)
        foreign.headers.update(_owner_headers("other-user"))
        assert foreign.get(f"/v1/research/optimization-jobs/{queued['job_id']}").status_code == 404

        assert worker.run_once() is True
        completed = client.get(f"/v1/research/optimization-jobs/{queued['job_id']}").json()["job"]
        assert completed["status"] == "SUCCEEDED"
        assert completed["result_artifact_id"] == completed["result_ref"]
        artifact = research.get_artifact(completed["result_artifact_id"])
        assert artifact["kind"] == "optimization_comparison"
        assert artifact["status"] == "validated"
        assert artifact["content"]["evaluation"] == "completed_backtest_parameter_search"
        assert artifact["content"]["reran_backtests"] is False
        assert artifact["content"]["candidate_count"] == 2
        assert {row["parameters"]["lookback"] for row in artifact["content"]["ranking"]} == {10, 20}
        with pytest.raises(BacktestConflict, match="referenced"):
            backtests.delete(backtest_ids[1], owner_principal="product-user")

        # Pause after immutable source facts are loaded but before the atomic commit.
        # Cancellation fences the claimed attempt; it must not leave a comparison Artifact.
        cancelled_request = {**request, "idempotency_key": f"optimization-cancel-{uuid4().hex}"}
        cancelled_response = client.post("/v1/research/optimization-jobs", json=cancelled_request)
        assert cancelled_response.status_code == 202, cancelled_response.text
        cancelled_id = cancelled_response.json()["job"]["job_id"]
        facts_loaded, release_worker = Event(), Event()
        original_facts = jobs.candidate_facts

        def pause_after_facts(claim):
            result = original_facts(claim)
            facts_loaded.set()
            assert release_worker.wait(10)
            return result

        monkeypatch.setattr(jobs, "candidate_facts", pause_after_facts)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker.run_once)
            assert facts_loaded.wait(10)
            cancelled = client.post(f"/v1/research/optimization-jobs/{cancelled_id}/cancel")
            assert cancelled.status_code == 200
            assert cancelled.json()["job"]["status"] == "CANCELLED"
            release_worker.set()
            assert future.result(timeout=15) is True
        artifact_count = research._fetch_one(
            "SELECT COUNT(*) AS count FROM artifacts WHERE kind='optimization_comparison' AND content->>'optimization_job_id'=:job",
            {"job": cancelled_id},
        )
        assert artifact_count is not None and artifact_count["count"] == 0
        assert jobs.get(job_id=cancelled_id,
            trusted_owner="product-user", trusted_workspace=queued["workspace_id"])["status"] == "CANCELLED"

        # Reclaiming an expired worker attempt changes the fence token; the
        # former process cannot turn its result into a completed Job.
        stale = jobs.create({**request, "trace_id": trace_id,
                             "idempotency_key": f"optimization-stale-{uuid4().hex}"},
                            trusted_owner="product-user", trusted_workspace=queued["workspace_id"])
        first_claim = jobs.claim_next("old-optimization-worker")
        assert first_claim is not None and first_claim["job_id"] == stale["job_id"]
        jobs._execute("""UPDATE optimization_jobs
            SET claimed_at=now()-interval '10 minutes' WHERE job_id=:job""",
            {"job": stale["job_id"]})
        next_claim = jobs.claim_next("new-optimization-worker")
        assert next_claim is not None and next_claim["job_id"] == stale["job_id"]
        assert next_claim["attempt"] == first_claim["attempt"] + 1
        with jobs._transaction() as connection, pytest.raises(OptimizationLeaseLost):
            jobs.require_execution_claim(connection, stale["job_id"], first_claim["attempt"])
    finally:
        client.close()
        jobs.close()
        backtests.close()
        research.close()
