from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.backtest import LocalObjectStore
from app.ml_prediction import (
    MLPredictionCoordinator,
    MLPredictionRunStore,
    build_prediction_snapshot,
)
from app.ml_strategy import FEATURE_ORDER, normalize_ml_strategy, content_sha256
from app.ml_training import FEATURE_SCHEMA, MODEL_SCHEMA, RUNTIME_IDENTITY
from app.main import app
from app.research import ResearchStore
from tests.test_ml_strategy import valid_strategy
from tests.workspace_helpers import trusted_agent_context


def strategy_value() -> dict[str, object]:
    value = valid_strategy()
    value["signal_policy"] = {"kind": "top_n_equal_weight", "top_n": 1, "rebalance": "daily"}
    value["split"] = {
        "train": {"start": "2024-01-01", "end": "2024-01-31"},
        "validation": {"start": "2024-02-01", "end": "2024-02-29"},
        "prediction": {"start": "2024-03-01", "end": "2024-03-04"},
    }
    return normalize_ml_strategy(value)


def feature_value() -> dict[str, object]:
    rows = []
    for offset in range(3):
        session = (date(2024, 3, 1) + timedelta(days=offset)).isoformat()
        for symbol_index, symbol in enumerate(("000001.SZ", "000002.SZ")):
            rows.append({
                "session": session, "symbol": symbol, "split": "prediction",
                "feature_as_of": session,
                "features": {name: float(offset + symbol_index + index) / 100 for index, name in enumerate(FEATURE_ORDER)},
            })
    value: dict[str, object] = {
        "schema_version": FEATURE_SCHEMA, "feature_set": "price-volume-basic-v1",
        "feature_order": FEATURE_ORDER, "target": {"kind": "forward_return", "horizon_sessions": 5},
        "split": strategy_value()["split"],
        "universe": {"symbols": ["000001.SZ", "000002.SZ"]}, "rows": rows,
        "counts": {"train": 20, "validation": 5, "prediction": 6},
        "symbol_counts": {"train": 2, "validation": 2, "prediction": 2},
        "coverage": {"usable_rows": 31, "candidate_rows": 31, "usable_ratio": 1.0},
        "excluded": {}, "source": {"ready_input_sha256": "b" * 64, "research_view_sha256": "d" * 64},
    }
    value["content_sha256"] = content_sha256(value)
    return value


def ready_input() -> dict[str, object]:
    bars = []
    for offset in range(4):
        session = (date(2024, 3, 1) + timedelta(days=offset)).isoformat()
        for symbol_index, symbol in enumerate(("000001.SZ", "000002.SZ")):
            close = 10.0 + symbol_index + offset / 10
            bars.append({"symbol": symbol, "trade_date": session, "open": close, "high": close + 0.1,
                         "low": close - 0.1, "close": close, "volume": 1000, "is_suspended": False})
    return {"bars": bars, "corporate_actions": [], "benchmark": [], "research_view_sha256": "d" * 64}


class FakePredictor:
    def predict(self, model_text, rows, *, best_iteration):
        assert model_text == "tree\ntrusted\n" and best_iteration == 3
        # Tie on day one proves symbol ASC tie breaking; leadership changes on day two.
        return [0.5, 0.5, 0.1, 0.9, 0.8, 0.2]


def test_prediction_ranking_is_deterministic_and_rows_never_expose_labels() -> None:
    feature = feature_value()
    model = {"content_sha256": "a" * 64, "feature_snapshot_sha256": feature["content_sha256"],
             "split": strategy_value()["split"]}
    rows = feature["rows"]
    snapshot = build_prediction_snapshot(
        scores=FakePredictor().predict("tree\ntrusted\n", rows, best_iteration=3),
        prediction_rows=rows, model=model, feature_artifact_id="artifact_feature",
        model_artifact_id="artifact_model", stock_pool_snapshot_id="snapshot_pool",
    )
    first = [row for row in snapshot["rows"] if row["session"] == "2024-03-01"]
    assert [(row["symbol"], row["rank"]) for row in first] == [("000001.SZ", 1), ("000002.SZ", 2)]
    assert all(set(row) == {"session", "symbol", "score", "rank"} for row in snapshot["rows"])
    leaked = [dict(row) for row in rows]
    leaked[0]["target"] = 0.99
    with pytest.raises(ValueError, match="must not contain labels"):
        build_prediction_snapshot(
            scores=[0.1] * len(leaked), prediction_rows=leaked, model=model,
            feature_artifact_id="artifact_feature", model_artifact_id="artifact_model",
            stock_pool_snapshot_id="snapshot_pool",
        )


def test_prediction_run_creates_immutable_prediction_and_standard_signal(tmp_path) -> None:
    context = trusted_agent_context("ml-prediction-owner")
    research, runs = ResearchStore(), MLPredictionRunStore()
    try:
        task = research.create_task({"owner_principal": "ml-prediction-owner", "title": "ML prediction",
            "objective": "Freeze OOS signals", "trace_id": "trace-pred", "idempotency_key": "pred-task"})
        strategy = strategy_value()
        strategy_artifact = research.create_artifact({"task_id": task["task_id"], "kind": "ml_strategy_version",
            "content": strategy, "lineage": [], "trace_id": "trace-pred", "idempotency_key": "pred-strategy"})
        strategy_artifact = research.transition("artifact", strategy_artifact["artifact_id"], "validated", "pred-strategy-valid")
        approval = research.create_artifact({"task_id": task["task_id"], "kind": "ml_strategy_approval",
            "content": {"ml_strategy_artifact_id": strategy_artifact["artifact_id"], "decision": "approved",
                        "execution_authorized": True}, "lineage": [{"kind": "artifact", "id": strategy_artifact["artifact_id"]}],
            "trace_id": "trace-pred", "idempotency_key": "pred-approval"})
        approval = research.transition("artifact", approval["artifact_id"], "validated", "pred-approval-valid")
        feature = feature_value()
        feature_artifact = research.create_artifact({"task_id": task["task_id"], "kind": "ml_feature_snapshot",
            "content": feature, "lineage": [], "trace_id": "trace-pred", "idempotency_key": "pred-feature"})
        feature_artifact = research.transition("artifact", feature_artifact["artifact_id"], "validated", "pred-feature-valid")
        objects = LocalObjectStore(tmp_path)
        reference = objects.put("ml-models", b"tree\ntrusted\n", media_type="text/x-lightgbm-model")
        model: dict[str, object] = {"schema_version": MODEL_SCHEMA, "model_format": "lightgbm-text-v1",
            "object_reference": reference, "runtime_lock": "python-3.13/lightgbm-4.7.0/numpy-2.3.3/cpu-single-thread",
            "runtime_identity": RUNTIME_IDENTITY, "image_identity": "test-image", "feature_order": FEATURE_ORDER,
            "target": strategy["target"], "split": strategy["split"], "feature_snapshot_artifact_id": feature_artifact["artifact_id"],
            "feature_snapshot_sha256": feature["content_sha256"], "strategy_version_artifact_id": strategy_artifact["artifact_id"],
            "stock_pool_snapshot_id": "snapshot_pool", "training_run_id": "mlrun_test", "effective_parameters": {},
            "best_iteration": 3, "metrics": {}, "counts": {}, "coverage": {}}
        model["content_sha256"] = content_sha256(model)
        model_artifact = research.create_artifact({"task_id": task["task_id"], "kind": "ml_model", "content": model,
            "lineage": [], "trace_id": "trace-pred", "idempotency_key": "pred-model"})
        model_artifact = research.transition("artifact", model_artifact["artifact_id"], "validated", "pred-model-valid")
        run = runs.create(workspace_id=context["x-byq-workspace-id"], owner_principal="ml-prediction-owner",
            task_id=task["task_id"], experiment_id=None, ml_strategy_artifact_id=strategy_artifact["artifact_id"],
            approval_artifact_id=approval["artifact_id"], model_artifact_id=model_artifact["artifact_id"],
            feature_artifact_id=feature_artifact["artifact_id"], stock_pool_snapshot_id="snapshot_pool",
            input_document={"strategy": strategy, "model": model, "feature": feature, "ready_input": ready_input(),
                            "readiness": {"requirement_sha256": "c" * 64, "ready_input_sha256": "b" * 64},
                            "execution": {"initial_capital": 100000.0, "lot_size": 100}},
            trace_id="trace-pred", idempotency_key="prediction-1")
        completed = MLPredictionCoordinator(runs, research, objects, FakePredictor(), worker_id="worker-pred").run_next()
        assert completed is not None and completed["status"] == "completed"
        prediction = research.get_artifact(completed["prediction_artifact_id"])
        signal = research.get_artifact(completed["signal_artifact_id"])
        assert prediction["status"] == signal["status"] == "validated"
        assert all("target" not in row for row in prediction["content"]["rows"])
        assert [(row["trade_date"], row["symbol"], row["direction"]) for row in signal["content"]["signals"]] == [
            ("2024-03-01", "000001.SZ", 1), ("2024-03-02", "000001.SZ", -1),
            ("2024-03-02", "000002.SZ", 1), ("2024-03-03", "000001.SZ", 1),
            ("2024-03-03", "000002.SZ", -1),
        ]
        assert signal["content"]["source"]["ml_lineage"]["prediction_snapshot_artifact_id"] == prediction["artifact_id"]
        response = TestClient(app).post("/v1/research/backtests", headers=context, json={
            "task_id": task["task_id"], "strategy_version_artifact_id": strategy_artifact["artifact_id"],
            "approval_artifact_id": approval["artifact_id"], "signal_snapshot_artifact_id": signal["artifact_id"],
            "trace_id": "trace-ml-backtest", "idempotency_key": "ml-backtest-submit",
        })
        assert response.status_code == 202, response.text
        assert response.json()["job"]["strategy_version_artifact_id"] == strategy_artifact["artifact_id"]
        assert runs.create(workspace_id=context["x-byq-workspace-id"], owner_principal="ml-prediction-owner",
            task_id=task["task_id"], experiment_id=None, ml_strategy_artifact_id=strategy_artifact["artifact_id"],
            approval_artifact_id=approval["artifact_id"], model_artifact_id=model_artifact["artifact_id"],
            feature_artifact_id=feature_artifact["artifact_id"], stock_pool_snapshot_id="snapshot_pool",
            input_document={"strategy": strategy, "model": model, "feature": feature, "ready_input": ready_input(),
                            "readiness": {"requirement_sha256": "c" * 64, "ready_input_sha256": "b" * 64},
                            "execution": {"initial_capital": 100000.0, "lot_size": 100}},
            trace_id="trace-pred", idempotency_key="prediction-1")["prediction_run_id"] == run["prediction_run_id"]

        tampered_model = dict(model)
        tampered_model["best_iteration"] = 4
        tampered = runs.create(workspace_id=context["x-byq-workspace-id"], owner_principal="ml-prediction-owner",
            task_id=task["task_id"], experiment_id=None, ml_strategy_artifact_id=strategy_artifact["artifact_id"],
            approval_artifact_id=approval["artifact_id"], model_artifact_id=model_artifact["artifact_id"],
            feature_artifact_id=feature_artifact["artifact_id"], stock_pool_snapshot_id="snapshot_pool",
            input_document={"strategy": strategy, "model": tampered_model, "feature": feature, "ready_input": ready_input(),
                            "readiness": {"requirement_sha256": "c" * 64, "ready_input_sha256": "b" * 64},
                            "execution": {"initial_capital": 100000.0, "lot_size": 100}},
            trace_id="trace-pred", idempotency_key="prediction-tampered")
        failed = MLPredictionCoordinator(runs, research, objects, FakePredictor(), worker_id="worker-pred").run_next()
        assert failed is not None and failed["prediction_run_id"] == tampered["prediction_run_id"]
        assert failed["status"] == "failed" and "identity does not match" in failed["error_detail"]

        recoverable = runs.create(workspace_id=context["x-byq-workspace-id"], owner_principal="ml-prediction-owner",
            task_id=task["task_id"], experiment_id=None, ml_strategy_artifact_id=strategy_artifact["artifact_id"],
            approval_artifact_id=approval["artifact_id"], model_artifact_id=model_artifact["artifact_id"],
            feature_artifact_id=feature_artifact["artifact_id"], stock_pool_snapshot_id="snapshot_pool",
            input_document={"strategy": strategy, "model": model, "feature": feature, "ready_input": ready_input(),
                            "readiness": {"requirement_sha256": "c" * 64, "ready_input_sha256": "b" * 64},
                            "execution": {"initial_capital": 100000.0, "lot_size": 100}},
            trace_id="trace-pred", idempotency_key="prediction-restart")
        first_claim = runs.claim_next("worker-before-restart")
        assert first_claim is not None and first_claim["prediction_run_id"] == recoverable["prediction_run_id"]
        runs._execute("UPDATE ml_prediction_runs SET lease_expires_at=now()-interval '1 second' WHERE prediction_run_id=:id",
                      {"id": recoverable["prediction_run_id"]})
        restarted = MLPredictionRunStore()
        try:
            second_claim = restarted.claim_next("worker-after-restart")
            assert second_claim is not None and second_claim["attempt_count"] == 2
            stale = runs.fail(str(recoverable["prediction_run_id"]), "stale", "stale worker",
                              worker_id="worker-before-restart", attempt_count=1)
            assert stale["status"] == "running" and stale["worker_id"] == "worker-after-restart"
            current = restarted.fail(str(recoverable["prediction_run_id"]), "expected", "current worker",
                                     worker_id="worker-after-restart", attempt_count=2)
            assert current["status"] == "failed" and current["error_code"] == "expected"
        finally:
            restarted.close()
    finally:
        runs.close()
        research.close()
