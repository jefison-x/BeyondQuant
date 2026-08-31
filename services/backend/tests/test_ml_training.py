from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.backtest import LocalObjectStore
from app.ml_strategy import normalize_ml_strategy
from app.ml_training import (
    MLTrainingConflict,
    MLTrainingCoordinator,
    MLTrainingNotFound,
    MLTrainingRunStore,
    aggregate_ml_readiness,
    build_feature_snapshot,
    promote_waiting_training_runs,
)
from app.research import ResearchStore
from tests.test_ml_strategy import valid_strategy
from tests.workspace_helpers import trusted_agent_context


def compact_strategy() -> dict[str, object]:
    dates = [(date(2024, 1, 1) + timedelta(days=index)).isoformat() for index in range(80)]
    strategy = valid_strategy()
    strategy["split"] = {
        "train": {"start": dates[0], "end": dates[39]},
        "validation": {"start": dates[40], "end": dates[59]},
        "prediction": {"start": dates[60], "end": dates[-1]},
    }
    return normalize_ml_strategy(strategy)


def feature_input() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    strategy = compact_strategy()
    bars = []
    for symbol_offset, symbol in enumerate(("000001.SZ", "000002.SZ")):
        for index in range(80):
            session = (date(2024, 1, 1) + timedelta(days=index)).isoformat()
            close = 10.0 + symbol_offset + index * 0.05 + (index % 3) * 0.01
            bars.append({
                "symbol": symbol, "trade_date": session, "close": close,
                "volume": 1000.0 + index * 10 + symbol_offset,
                "is_universe_member": not (symbol == "000002.SZ" and index == 45),
            })
    universe = {
        "membership_mode": "point_in_time", "stock_pool_id": "stock_pool_test",
        "stock_pool_snapshot_id": "snapshot_test", "membership_fingerprint": "membership-test",
        "symbols": ["000001.SZ", "000002.SZ"], "index_symbol": "000300.SH",
    }
    ready = {"research_bars": bars, "research_view_sha256": "a" * 64}
    return strategy, universe, ready


def test_feature_snapshot_is_deterministic_and_never_labels_prediction_rows() -> None:
    strategy, universe, ready = feature_input()
    readiness = {"ready_input_sha256": "b" * 64}
    first = build_feature_snapshot(
        strategy=strategy, universe=universe, ready_input=ready, readiness=readiness
    )
    second = build_feature_snapshot(
        strategy=strategy, universe=universe, ready_input=ready, readiness=readiness
    )
    assert first == second
    assert first["counts"]["train"] >= 20
    assert first["counts"]["validation"] >= 5
    for row in first["rows"]:
        assert row["feature_as_of"] == row["session"]
        if row["split"] == "prediction":
            assert "target" not in row and "label_end_date" not in row
        else:
            assert row["label_end_date"] <= strategy["split"][row["split"]]["end"]
    assert not any(row["symbol"] == "000002.SZ" and row["session"] == "2024-02-15" for row in first["rows"])


def test_bad_waiting_run_is_isolated_from_following_preparation() -> None:
    class Runs:
        def __init__(self) -> None:
            self.failed: list[str] = []
            self.updated: list[str] = []

        def list_waiting(self):
            return [
                {"training_run_id": "mlrun_bad", "requirement_json": {"bad": True},
                 "preparation_json": {"requirements": [{"bad": True}]}},
                {"training_run_id": "mlrun_waiting", "requirement_json": {"bad": False},
                 "preparation_json": {"requirements": [{"bad": False}]}},
            ]

        def fail_waiting(self, run_id, code, detail):
            self.failed.append(run_id)

        def update_readiness(self, run_id, readiness):
            self.updated.append(run_id)

    class Readiness:
        def assess(self, requirement):
            if requirement["bad"]:
                raise ValueError("oversized legacy request")
            return {"state": "missing", "required_cell_count": 10, "missing_count": 10}

    runs = Runs()
    assert promote_waiting_training_runs(runs, Readiness()) == 0
    assert runs.failed == ["mlrun_bad"]
    assert runs.updated == ["mlrun_waiting"]


def test_single_partition_keeps_existing_frozen_readiness_identity() -> None:
    readiness = aggregate_ml_readiness([{
        "state": "ready", "required_cell_count": 178, "missing_count": 0,
        "ready_input_sha256": "a" * 64,
    }])
    assert readiness["ready_input_sha256"] == "a" * 64
    assert readiness["state"] == "ready"


def test_aggregate_readiness_exposes_bounded_missing_dataset_diagnostics() -> None:
    readiness = aggregate_ml_readiness([
        {
            "state": "partial", "required_cell_count": 100, "missing_count": 3,
            "ready_input_sha256": None,
            "missing_by_dataset": {"corporate_actions": 2, "stock_daily": 1},
            "missing": [
                {"symbol": "*", "trade_date": "20240102", "dataset": "corporate_actions"},
                {"symbol": "000001.SZ", "trade_date": "20240103", "dataset": "stock_daily"},
            ],
        },
        {
            "state": "partial", "required_cell_count": 50, "missing_count": 1,
            "ready_input_sha256": None,
            "missing_by_dataset": {"corporate_actions": 1},
            "missing": [
                {"symbol": "*", "trade_date": "20240201", "dataset": "corporate_actions"},
            ],
        },
    ])

    assert readiness["missing_by_dataset"] == {"corporate_actions": 3, "stock_daily": 1}
    assert readiness["missing_sample"] == [
        {"symbol": "*", "trade_date": "20240102", "dataset": "corporate_actions"},
        {"symbol": "000001.SZ", "trade_date": "20240103", "dataset": "stock_daily"},
        {"symbol": "*", "trade_date": "20240201", "dataset": "corporate_actions"},
    ]


class FakeTrainer:
    def train(self, feature_snapshot, strategy):
        return {
            "model_text": "tree\nversion=v4\n",
            "best_iteration": 3,
            "effective_parameters": {"objective": "regression", "num_threads": 1},
            "metrics": {"validation_rmse": 0.01, "validation_rank_ic": 0.2},
            "runtime_identity": "lightgbm-4.7.0-python-3.13-linux-cpu-single-thread",
            "image_identity": "byq-ml-worker-v1-test",
        }


def test_training_run_creates_immutable_feature_and_model_artifacts(tmp_path) -> None:
    context = trusted_agent_context("ml-owner")
    research = ResearchStore()
    runs = MLTrainingRunStore()
    try:
        task = research.create_task({
            "owner_principal": "ml-owner", "title": "ML", "objective": "Train model",
            "trace_id": "trace-ml", "idempotency_key": "ml-task",
        })
        strategy = compact_strategy()
        strategy_artifact = research.create_artifact({
            "task_id": task["task_id"], "kind": "ml_strategy_version", "content": strategy,
            "lineage": [], "trace_id": "trace-ml", "idempotency_key": "ml-strategy",
        })
        strategy_artifact = research.transition(
            "artifact", strategy_artifact["artifact_id"], "validated", "ml-strategy-valid"
        )
        strategy_value, universe, ready = feature_input()
        feature = build_feature_snapshot(
            strategy=strategy_value, universe=universe, ready_input=ready,
            readiness={"ready_input_sha256": "b" * 64},
        )
        run = runs.create_waiting(
            workspace_id=context["x-byq-workspace-id"], owner_principal="ml-owner",
            task_id=task["task_id"], experiment_id=None,
            ml_strategy_artifact_id=strategy_artifact["artifact_id"],
            stock_pool_snapshot_id="snapshot_test", preparation={"strategy": strategy_value, "universe": universe},
            requirement={"requirement_sha256": "c" * 64}, readiness={"state": "ready"},
            trace_id="trace-ml", idempotency_key="train-1",
        )
        runs.promote_ready(str(run["training_run_id"]), feature)
        coordinator = MLTrainingCoordinator(
            runs, research, LocalObjectStore(tmp_path), FakeTrainer(), worker_id="worker-test"
        )
        completed = coordinator.run_next()
        assert completed is not None and completed["status"] == "completed"
        feature_artifact = research.get_artifact(completed["feature_artifact_id"])
        model_artifact = research.get_artifact(completed["model_artifact_id"])
        assert feature_artifact["status"] == model_artifact["status"] == "validated"
        assert model_artifact["content"]["target"] == strategy_value["target"]
        assert model_artifact["content"]["split"] == strategy_value["split"]
        assert model_artifact["content"]["counts"]["symbols"]["train"] == 2
        assert model_artifact["content"]["image_identity"] == "byq-ml-worker-v1-test"
        reference = model_artifact["content"]["object_reference"]
        assert LocalObjectStore(tmp_path).get(reference) == b"tree\nversion=v4\n"
        with pytest.raises(MLTrainingNotFound):
            runs.get(str(run["training_run_id"]), trusted_workspace="workspace_other", trusted_owner="ml-owner")
        with pytest.raises(MLTrainingConflict):
            runs.create_waiting(
                workspace_id=context["x-byq-workspace-id"], owner_principal="ml-owner",
                task_id=task["task_id"], experiment_id=None,
                ml_strategy_artifact_id=strategy_artifact["artifact_id"],
                stock_pool_snapshot_id="snapshot_other", preparation={"strategy": strategy_value, "universe": universe},
                requirement={"requirement_sha256": "c" * 64}, readiness={"state": "ready"},
                trace_id="trace-ml", idempotency_key="train-1",
            )
        cancellable = runs.create_waiting(
            workspace_id=context["x-byq-workspace-id"], owner_principal="ml-owner",
            task_id=task["task_id"], experiment_id=None,
            ml_strategy_artifact_id=strategy_artifact["artifact_id"],
            stock_pool_snapshot_id="snapshot_test", preparation={"strategy": strategy_value, "universe": universe},
            requirement={"requirement_sha256": "c" * 64}, readiness={"state": "waiting_for_data"},
            trace_id="trace-ml", idempotency_key="train-cancel",
        )
        cancelled = runs.cancel(
            cancellable["training_run_id"], trusted_workspace=context["x-byq-workspace-id"],
            trusted_owner="ml-owner",
        )
        assert cancelled["status"] == "cancelled"
        with pytest.raises(MLTrainingConflict):
            runs.cancel(
                cancelled["training_run_id"], trusted_workspace=context["x-byq-workspace-id"],
                trusted_owner="ml-owner",
            )
        fenced = runs.create_waiting(
            workspace_id=context["x-byq-workspace-id"], owner_principal="ml-owner",
            task_id=task["task_id"], experiment_id=None,
            ml_strategy_artifact_id=strategy_artifact["artifact_id"],
            stock_pool_snapshot_id="snapshot_test", preparation={"strategy": strategy_value, "universe": universe},
            requirement={"requirement_sha256": "c" * 64}, readiness={"state": "ready"},
            trace_id="trace-ml", idempotency_key="train-fence",
        )
        runs.promote_ready(str(fenced["training_run_id"]), feature)
        first_claim = runs.claim_next("worker-old")
        assert first_claim is not None
        runs._execute(
            "UPDATE ml_training_runs SET lease_expires_at=now()-interval '1 second' "
            "WHERE training_run_id=:id",
            {"id": fenced["training_run_id"]},
        )
        second_claim = runs.claim_next("worker-new")
        assert second_claim is not None and second_claim["attempt_count"] == 2
        stale_result = runs.fail(
            str(fenced["training_run_id"]), "stale", "stale worker",
            worker_id="worker-old", attempt_count=1,
        )
        assert stale_result["status"] == "running" and stale_result["worker_id"] == "worker-new"
        current_result = runs.fail(
            str(fenced["training_run_id"]), "expected", "current worker",
            worker_id="worker-new", attempt_count=2,
        )
        assert current_result["status"] == "failed" and current_result["error_code"] == "expected"
    finally:
        runs.close()
        research.close()
