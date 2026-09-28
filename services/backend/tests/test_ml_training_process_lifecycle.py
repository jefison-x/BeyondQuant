"""Phase 11 TrainingJob process recovery; this is not Phase 16 GPU checkpoint evidence."""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
from queue import Empty
from typing import Any

import pytest

from app.backtest import LocalObjectStore
from app.ml_training import MLTrainingCoordinator, MLTrainingRunStore, build_feature_snapshot
from app.research import ResearchStore
from tests.test_ml_training import FakeTrainer, feature_input
from tests.workspace_helpers import trusted_agent_context


def _run_coordinator_once(
    database_url: str,
    object_root: str,
    worker_id: str,
    messages: Any,
    started: Any | None = None,
    continue_training: Any | None = None,
) -> None:
    """Run one real Coordinator claim in a separate OS process with synthetic training."""
    runs = MLTrainingRunStore(database_url)
    research = ResearchStore(database_url)

    class ProcessTrainer:
        def train(self, feature_snapshot: dict[str, object], strategy: dict[str, object]) -> dict[str, object]:
            if started is not None:
                started.put({"event": "training_started", "pid": os.getpid()})
            if continue_training is not None:
                continue_training.wait()
            return FakeTrainer().train(feature_snapshot, strategy)

    try:
        completed = MLTrainingCoordinator(
            runs, research, LocalObjectStore(object_root), ProcessTrainer(), worker_id=worker_id,
        ).run_next()
        messages.put({
            "event": "finished",
            "training_run_id": None if completed is None else completed.get("training_run_id"),
            "status": None if completed is None else completed.get("status"),
            "attempt_count": None if completed is None else completed.get("attempt_count"),
            "model_artifact_id": None if completed is None else completed.get("model_artifact_id"),
        })
    except Exception as error:
        messages.put({"event": "error", "error": f"{type(error).__name__}: {error}"})
        raise
    finally:
        runs.close()
        research.close()


def _receive(process: multiprocessing.Process, messages: Any, timeout: float = 45.0) -> dict[str, object]:
    try:
        message = messages.get(timeout=timeout)
    except Empty:
        exit_code = process.exitcode
        pytest.fail(f"worker process produced no lifecycle message (exit code {exit_code})")
    assert isinstance(message, dict)
    assert message.get("event") != "error", message
    return message


def test_training_run_recovers_after_worker_process_kill_and_new_agent_reads_artifact(tmp_path: Path) -> None:
    database_url = os.environ.get("BYQ_DATABASE_URL")
    if not database_url:
        pytest.skip("BYQ_DATABASE_URL is not set; PostgreSQL-backed lifecycle test is skipped")
    if "byq_domain_test" not in database_url:
        raise RuntimeError("lifecycle test requires the disposable byq_domain_test database")

    owner = "ml-process-restart-owner"
    submitted_context = trusted_agent_context(owner, session_id="session-before-worker-restart")
    workspace_id = submitted_context["x-byq-workspace-id"]
    research = ResearchStore(database_url)
    runs = MLTrainingRunStore(database_url)
    process_context = multiprocessing.get_context("spawn")
    object_root = str(tmp_path / "ml-objects")
    old_worker_messages = process_context.Queue()
    old_worker_started = process_context.Queue()
    hold_old_worker = process_context.Event()
    old_worker: multiprocessing.Process | None = None
    new_worker: multiprocessing.Process | None = None

    try:
        task = research.create_task({
            "owner_principal": owner,
            "title": "Process recovery",
            "objective": "Recover the durable training job after a worker is killed",
            "trace_id": "trace-ml-process-restart",
            "idempotency_key": "ml-process-restart-task",
        })
        strategy, universe, ready_input = feature_input()
        strategy_artifact = research.create_artifact({
            "task_id": task["task_id"], "kind": "ml_strategy_version", "content": strategy,
            "lineage": [], "trace_id": "trace-ml-process-restart",
            "idempotency_key": "ml-process-restart-strategy",
        })
        strategy_artifact = research.transition(
            "artifact", strategy_artifact["artifact_id"], "validated", "ml-process-restart-strategy-valid",
        )
        feature = build_feature_snapshot(
            strategy=strategy, universe=universe, ready_input=ready_input,
            readiness={"ready_input_sha256": "b" * 64},
        )
        run = runs.create_waiting(
            workspace_id=workspace_id, owner_principal=owner,
            task_id=task["task_id"], experiment_id=None,
            ml_strategy_artifact_id=strategy_artifact["artifact_id"],
            stock_pool_snapshot_id=str(universe["stock_pool_snapshot_id"]),
            preparation={"strategy": strategy, "universe": universe},
            requirement={"requirement_sha256": "c" * 64}, readiness={"state": "ready"},
            trace_id="trace-ml-process-restart", idempotency_key="ml-process-restart-training",
        )
        run_id = str(run["training_run_id"])
        runs.promote_ready(run_id, feature)

        old_worker = process_context.Process(
            target=_run_coordinator_once,
            args=(database_url, object_root, "ml-worker-before-kill", old_worker_messages,
                  old_worker_started, hold_old_worker),
        )
        old_worker.start()
        _receive(old_worker, old_worker_started)

        claimed = runs.get(run_id, trusted_workspace=workspace_id, trusted_owner=owner)
        assert claimed["status"] == "running"
        assert claimed["worker_id"] == "ml-worker-before-kill"
        assert claimed["attempt_count"] == 1

        # Interrupt the independent worker while its trainer is active.
        old_worker.kill()
        old_worker.join(timeout=10)
        assert not old_worker.is_alive()
        assert old_worker.exitcode != 0

        interrupted = runs.get(run_id, trusted_workspace=workspace_id, trusted_owner=owner)
        assert interrupted["status"] == "running"
        assert interrupted["model_artifact_id"] is None
        runs._execute(
            "UPDATE ml_training_runs SET lease_expires_at=now()-interval '1 second' WHERE training_run_id=:id",
            {"id": run_id},
        )

        new_worker = process_context.Process(
            target=_run_coordinator_once,
            args=(database_url, object_root, "ml-worker-after-restart", old_worker_messages),
        )
        new_worker.start()
        completed_message = _receive(new_worker, old_worker_messages)
        new_worker.join(timeout=10)
        assert not new_worker.is_alive()
        assert new_worker.exitcode == 0
        assert completed_message["event"] == "finished"
        assert completed_message["training_run_id"] == run_id
        assert completed_message["status"] == "completed"
        assert completed_message["attempt_count"] == 2
        model_artifact_id = str(completed_message["model_artifact_id"])

        # A genuinely new authorized session reads the persisted Job and its model Artifact.
        from fastapi.testclient import TestClient

        from app.main import app

        new_session = trusted_agent_context(
            owner,
            session_id="session-after-worker-restart",
            dsh_run_id="dsh-run-after-worker-restart",
            trace_id="trace-after-worker-restart",
        )
        assert new_session["x-byq-workspace-id"] == workspace_id
        client = TestClient(app)
        fetched_run = client.get(f"/v1/research/ml/training-runs/{run_id}", headers=new_session)
        assert fetched_run.status_code == 200, fetched_run.text
        run_body = fetched_run.json()
        assert run_body["training_run"]["training_run_id"] == run_id
        assert run_body["business_job"]["job_id"] == run_id
        assert run_body["business_job"]["status"] == "SUCCEEDED"
        assert run_body["business_job"]["result_ref"] == model_artifact_id

        fetched_artifact = client.get(f"/v1/research/artifacts/{model_artifact_id}", headers=new_session)
        assert fetched_artifact.status_code == 200, fetched_artifact.text
        artifact = fetched_artifact.json()
        assert artifact["artifact_id"] == model_artifact_id
        assert artifact["kind"] == "ml_model"
        assert artifact["status"] == "validated"
        assert artifact["content"]["training_run_id"] == run_id
        assert LocalObjectStore(object_root).get(artifact["content"]["object_reference"]) == b"tree\nversion=v4\n"
    finally:
        for process in (old_worker, new_worker):
            if process is not None and process.is_alive():
                process.kill()
                process.join(timeout=10)
        old_worker_messages.close()
        old_worker_started.close()
        runs.close()
        research.close()
