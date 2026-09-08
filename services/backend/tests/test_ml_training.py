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
    generate_walk_forward_folds,
    load_feature_snapshot,
    promote_waiting_training_runs,
)
from app.research import ResearchStore
from tests.test_ml_strategy import valid_regime_strategy_v2, valid_strategy, valid_strategy_v2
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


def feature_input_v2() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    dates = [(date(2024, 1, 1) + timedelta(days=index)).isoformat() for index in range(125)]
    candidate = valid_strategy_v2()
    candidate["development_window"] = {"start": dates[0], "end": dates[99]}
    candidate["prediction_window"] = {"start": dates[100], "end": dates[-1]}
    strategy = normalize_ml_strategy(candidate)
    bars = []
    for symbol_offset, symbol in enumerate(("000001.SZ", "000002.SZ")):
        for index, session in enumerate(dates):
            bars.append({
                "symbol": symbol, "trade_date": session,
                "close": 10.0 + symbol_offset + index * 0.03 + (index % 4) * 0.01,
                "volume": 2000.0 + index * 7 + symbol_offset,
                "is_universe_member": True,
            })
    universe = {
        "membership_mode": "fixed_snapshot", "stock_pool_id": "stock_pool_v2",
        "stock_pool_snapshot_id": "snapshot_v2", "membership_fingerprint": "membership-v2",
        "symbols": ["000001.SZ", "000002.SZ"], "index_symbol": None,
    }
    return strategy, universe, {"research_bars": bars, "research_view_sha256": "c" * 64}


def regime_feature_input_v2() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    dates = [(date(2023, 10, 1) + timedelta(days=index)).isoformat() for index in range(220)]
    candidate = valid_regime_strategy_v2()
    candidate["development_window"] = {"start": dates[80], "end": dates[179]}
    candidate["prediction_window"] = {"start": dates[180], "end": dates[204]}
    strategy = normalize_ml_strategy(candidate)
    bars = []
    for symbol_offset, symbol in enumerate(("000001.SZ", "000002.SZ")):
        for index, session in enumerate(dates):
            bars.append({
                "symbol": symbol, "trade_date": session,
                "close": 10.0 + symbol_offset + index * 0.03 + (index % 4) * 0.01,
                "volume": 2000.0 + index * 7 + symbol_offset,
                "is_universe_member": True,
            })
    benchmark = [
        {"symbol": "000300.SH", "trade_date": session, "close": 100.0 * (1.001 ** index)}
        for index, session in enumerate(dates)
    ]
    universe = {
        "membership_mode": "fixed_snapshot", "stock_pool_id": "stock_pool_regime",
        "stock_pool_snapshot_id": "snapshot_regime", "membership_fingerprint": "membership-regime",
        "symbols": ["000001.SZ", "000002.SZ"], "index_symbol": None,
    }
    return strategy, universe, {
        "research_bars": bars, "benchmark": benchmark,
        "research_view_sha256": "9" * 64,
    }


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


def test_v2_feature_snapshot_freezes_purged_walk_forward_manifest() -> None:
    strategy, universe, ready = feature_input_v2()
    snapshot = build_feature_snapshot(
        strategy=strategy, universe=universe, ready_input=ready,
        readiness={"ready_input_sha256": "d" * 64},
    )
    assert snapshot["schema_version"] == "ml-feature-snapshot.v2"
    assert len(snapshot["folds"]) == 2
    assert snapshot["folds"][0]["train"]["end"] < snapshot["folds"][0]["validation"]["start"]
    assert snapshot["folds"][0]["purge"]["sessions"] == 5
    assert all("target" not in row for row in snapshot["rows"] if row["split"] == "prediction")
    assert all(row["label_end_date"] <= strategy["development_window"]["end"] for row in snapshot["rows"] if row["split"] == "development")
    assert snapshot == build_feature_snapshot(
        strategy=strategy, universe=universe, ready_input=ready,
        readiness={"ready_input_sha256": "d" * 64},
    )


def test_walk_forward_rejects_insufficient_sessions() -> None:
    strategy, _, _ = feature_input_v2()
    with pytest.raises(ValueError, match="requires"):
        generate_walk_forward_folds(
            ["2024-01-01"] * 10, strategy["validation_plan"], horizon_sessions=5
        )


class PreparationClaimsFake:
    def claim_preparation(self, run_id):
        return "synthetic-claim"

    def renew_preparation(self, run_id, claim):
        return True

    def release_preparation(self, run_id, claim):
        pass


def test_bad_waiting_run_is_isolated_from_following_preparation() -> None:
    class Runs(PreparationClaimsFake):
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

        def fail_waiting(self, run_id, code, detail, **kwargs):
            self.failed.append(run_id)

        def update_readiness(self, run_id, readiness, **kwargs):
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


def test_accepted_receipt_schedules_repairs_in_worker_without_retrying_terminal_repairs():
    calls = []
    class Runs(PreparationClaimsFake):
        def list_waiting(self):
            return [{"training_run_id": "accepted", "owner_principal": "owner",
                     "requirement_json": {"requirement_sha256": "a" * 64},
                     "preparation_json": {"receipt_version": "ml-training-submit.v2"}}]
        def update_readiness(self, run_id, readiness, **kwargs):
            calls.append(("assessed", run_id))
        def record_preparation_repairs(self, run_id, identities, **kwargs):
            calls.append(("linked", identities))
        def fail_waiting(self, run_id, code, detail, **kwargs):
            calls.append(("failed", code))
    class Readiness:
        def assess(self, requirement):
            return {"state": "missing"}
    class Repairs:
        status = "queued"
        def request_data_repair(self, **kwargs):
            assert kwargs["retry_terminal"] is False
            calls.append(("repair", kwargs["requested_by"]))
            return {"request_id": "repair-1", "status": self.status}
    repairs = Repairs()
    assert promote_waiting_training_runs(Runs(), Readiness(), repair_store=repairs) == 0
    assert calls == [("assessed", "accepted"), ("repair", "ml:owner"), ("linked", ["repair-1"])]
    repairs.status = "failed"
    promote_waiting_training_runs(Runs(), Readiness(), repair_store=repairs)
    assert calls[-1] == ("failed", "ml_data_repair_not_ready")


def test_waiting_promotion_persists_only_one_bounded_object_descriptor(tmp_path) -> None:
    strategy, universe, ready_input = feature_input()

    class Runs(PreparationClaimsFake):
        promoted: list[tuple[str, dict[str, object]]] = []

        def list_waiting(self):
            return [{
                "training_run_id": f"mlrun_{index}",
                "requirement_json": {"partition": index},
                "preparation_json": {
                    "requirements": [{"partition": index}],
                    "strategy": strategy,
                    "universe": universe,
                },
            } for index in range(2)]

        def update_readiness(self, _run_id, _readiness, **kwargs):
            return None

        def promote_ready(self, run_id, feature, **kwargs):
            self.promoted.append((run_id, feature))

        def fail_waiting(self, *_args, **kwargs):
            pytest.fail("ready preparation must not fail")

    class Readiness:
        def assess(self, _requirement):
            return {"state": "ready", "required_cell_count": 1, "missing_count": 0,
                    "ready_input_sha256": "b" * 64}

        def build_ready_input(self, _requirement):
            return ready_input

    runs = Runs()
    objects = LocalObjectStore(tmp_path)
    assert promote_waiting_training_runs(runs, Readiness(), objects) == 1
    assert len(runs.promoted) == 1
    run_id, descriptor = runs.promoted[0]
    assert run_id == "mlrun_0"
    assert descriptor["storage_format"] == "gzip-json-v1"
    assert descriptor["row_count"] > 0
    assert "rows" not in descriptor
    assert load_feature_snapshot(descriptor, objects)["rows"]


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


class FakeV2Trainer:
    def train(self, feature_snapshot, strategy):
        return {
            "model_bytes": b'{"schema_version":"ridge-linear-json-v1"}',
            "model_format": "ridge-linear-json-v1",
            "media_type": "application/vnd.byq.ridge-model+json",
            "feature_order": ["return_1", "return_5", "return_20", "volatility_20", "volume_ratio_5"],
            "learner_profile": "byq-ridge-cpu-v1",
            "best_iteration": None,
            "effective_parameters": {"alpha": 1.0, "fit_intercept": True},
            "metrics": {"validation_rmse": 0.01, "validation_rmse_std": 0.001,
                        "validation_rmse_median": 0.01, "validation_rmse_worst": 0.011,
                        "validation_rank_ic": 0.2,
                        "valid_folds": 2},
            "folds": [{"fold_id": "fold-01", "model_sha256": "e" * 64}],
            "selection_rule": {"kind": "latest-valid-fold-v1", "selected_fold_id": "fold-01"},
            "runtime_identity": "ridge-numpy-2.3.3-python-3.13-linux-cpu-single-thread",
            "image_identity": "byq-ml-worker-v2-test",
        }


class FakeBundleTrainer:
    def train(self, feature_snapshot, strategy):
        results = []
        for expert in strategy["experts"]:
            profile = expert["learner"]["profile"]
            ridge = profile == "byq-ridge-cpu-v1"
            results.append({
                **({"model_bytes": b'{"schema_version":"ridge-linear-json-v1"}'} if ridge else {"model_text": "tree\ntrusted\n"}),
                "model_format": "ridge-linear-json-v1" if ridge else "lightgbm-text-v1",
                "media_type": "application/vnd.byq.ridge-model+json" if ridge else "text/x-lightgbm-model",
                "feature_order": ["return_1", "return_5", "return_20", "volatility_20", "volume_ratio_5"],
                "learner_profile": profile, "best_iteration": None if ridge else 3,
                "effective_parameters": expert["learner"]["parameters"],
                "metrics": {"validation_rmse": 0.01, "validation_rmse_std": 0.001,
                            "validation_rmse_median": 0.01, "validation_rmse_worst": 0.011,
                            "validation_rank_ic": 0.2, "valid_folds": 2},
                "folds": [{"fold_id": "fold-01", "model_sha256": "e" * 64}],
                "selection_rule": {"kind": "latest-valid-fold-v1", "selected_fold_id": "fold-01"},
                "runtime_identity": (
                    "ridge-numpy-2.3.3-python-3.13-linux-cpu-single-thread" if ridge
                    else "lightgbm-4.7.0-python-3.13-linux-cpu-single-thread"
                ),
                "image_identity": "byq-ml-worker-v2-test",
                "expert_key": expert["key"], "training_regimes": expert["training_regimes"],
            })
        return {"expert_results": results}


def test_regime_training_persists_snapshot_independent_experts_and_bundle(tmp_path) -> None:
    context = trusted_agent_context("ml-regime-owner")
    research, runs = ResearchStore(), MLTrainingRunStore()
    try:
        task = research.create_task({
            "owner_principal": "ml-regime-owner", "title": "ML regime", "objective": "Route experts",
            "trace_id": "trace-ml-regime", "idempotency_key": "ml-regime-task",
        })
        strategy, universe, ready = regime_feature_input_v2()
        strategy_artifact = research.create_artifact({
            "task_id": task["task_id"], "kind": "ml_strategy_version", "content": strategy,
            "lineage": [], "trace_id": "trace-ml-regime", "idempotency_key": "ml-regime-strategy",
        })
        strategy_artifact = research.transition(
            "artifact", strategy_artifact["artifact_id"], "validated", "ml-regime-strategy-valid"
        )
        feature = build_feature_snapshot(
            strategy=strategy, universe=universe, ready_input=ready,
            readiness={"ready_input_sha256": "8" * 64},
        )
        assert feature["regime_snapshot"]["counts"]["risk_on"] > 0
        run = runs.create_waiting(
            workspace_id=context["x-byq-workspace-id"], owner_principal="ml-regime-owner",
            task_id=task["task_id"], experiment_id=None,
            ml_strategy_artifact_id=strategy_artifact["artifact_id"],
            stock_pool_snapshot_id="snapshot_regime",
            preparation={"strategy": strategy, "universe": universe},
            requirement={"requirement_sha256": "7" * 64}, readiness={"state": "ready"},
            trace_id="trace-ml-regime", idempotency_key="ml-regime-train",
        )
        runs.promote_ready(str(run["training_run_id"]), feature)
        completed = MLTrainingCoordinator(
            runs, research, LocalObjectStore(tmp_path), FakeBundleTrainer(), worker_id="worker-regime"
        ).run_next()
        assert completed is not None and completed["status"] == "completed"
        bundle_artifact = research.get_artifact(completed["model_artifact_id"])
        assert bundle_artifact["kind"] == "ml_model_bundle"
        bundle = bundle_artifact["content"]
        assert bundle["schema_version"] == "ml-model-bundle.v1"
        assert len(bundle["experts"]) == 3
        assert bundle["routing_policy"]["fallback"] == "neutral"
        assert research.get_artifact(bundle["regime_snapshot_artifact_id"])["kind"] == "ml_regime_snapshot"
        for expert in bundle["experts"]:
            model = research.get_artifact(expert["model_artifact_id"])
            assert model["kind"] == "ml_model"
            assert model["content"]["expert_key"] == expert["key"]
    finally:
        runs.close()
        research.close()


def test_v2_training_persists_qualified_model_and_fold_evidence(tmp_path) -> None:
    context = trusted_agent_context("ml-v2-owner")
    research, runs = ResearchStore(), MLTrainingRunStore()
    try:
        task = research.create_task({
            "owner_principal": "ml-v2-owner", "title": "ML v2", "objective": "Walk forward",
            "trace_id": "trace-ml-v2", "idempotency_key": "ml-v2-task",
        })
        strategy, universe, ready = feature_input_v2()
        strategy_artifact = research.create_artifact({
            "task_id": task["task_id"], "kind": "ml_strategy_version", "content": strategy,
            "lineage": [], "trace_id": "trace-ml-v2", "idempotency_key": "ml-v2-strategy",
        })
        strategy_artifact = research.transition(
            "artifact", strategy_artifact["artifact_id"], "validated", "ml-v2-strategy-valid"
        )
        feature = build_feature_snapshot(
            strategy=strategy, universe=universe, ready_input=ready,
            readiness={"ready_input_sha256": "f" * 64},
        )
        run = runs.create_waiting(
            workspace_id=context["x-byq-workspace-id"], owner_principal="ml-v2-owner",
            task_id=task["task_id"], experiment_id=None,
            ml_strategy_artifact_id=strategy_artifact["artifact_id"],
            stock_pool_snapshot_id="snapshot_v2", preparation={"strategy": strategy, "universe": universe},
            requirement={"requirement_sha256": "1" * 64}, readiness={"state": "ready"},
            trace_id="trace-ml-v2", idempotency_key="ml-v2-train",
        )
        runs.promote_ready(str(run["training_run_id"]), feature)
        completed = MLTrainingCoordinator(
            runs, research, LocalObjectStore(tmp_path), FakeV2Trainer(), worker_id="worker-v2"
        ).run_next()
        assert completed is not None and completed["status"] == "completed"
        model = research.get_artifact(completed["model_artifact_id"])["content"]
        assert model["schema_version"] == "ml-model-artifact.v2"
        assert model["model_format"] == "ridge-linear-json-v1"
        assert model["learner_profile"] == "byq-ridge-cpu-v1"
        assert model["folds"][0]["fold_id"] == "fold-01"
        assert model["capability_lock"] == strategy["capability_lock"]
        assert LocalObjectStore(tmp_path).get(model["object_reference"]).startswith(b'{"schema_version"')
    finally:
        runs.close()
        research.close()


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
        reconciled = runs.get_by_idempotency(
            "train-1", trusted_workspace=context["x-byq-workspace-id"],
            trusted_owner="ml-owner",
        )
        assert reconciled["training_run_id"] == run["training_run_id"]
        duplicate = runs.create_waiting(
            workspace_id=context["x-byq-workspace-id"], owner_principal="ml-owner",
            task_id=task["task_id"], experiment_id=None,
            ml_strategy_artifact_id=strategy_artifact["artifact_id"],
            stock_pool_snapshot_id="snapshot_test",
            preparation={"strategy": strategy_value, "universe": universe},
            requirement={"requirement_sha256": "c" * 64}, readiness={"state": "ready"},
            trace_id="trace-ml-duplicate", idempotency_key="train-duplicate-key",
        )
        assert duplicate["training_run_id"] == run["training_run_id"]
        runs.record_preparation_repairs(str(run["training_run_id"]), ["datarepair_synthetic"])
        restarted = MLTrainingRunStore()
        try:
            recovered = restarted.get_by_idempotency(
                "train-duplicate-key", trusted_workspace=context["x-byq-workspace-id"], trusted_owner="ml-owner",
            )
            assert recovered["training_run_id"] == run["training_run_id"]
            assert "preparation" not in recovered
            persisted = restarted._fetch_one("SELECT preparation_json FROM ml_training_runs WHERE training_run_id=:id",
                                              {"id": run["training_run_id"]})
            assert persisted["preparation_json"]["repair_request_ids"] == ["datarepair_synthetic"]
            with pytest.raises(MLTrainingNotFound):
                restarted.get_by_idempotency(
                    "train-duplicate-key", trusted_workspace=context["x-byq-workspace-id"], trusted_owner="other-owner",
                )
        finally:
            restarted.close()
        with pytest.raises(MLTrainingNotFound):
            runs.get_by_idempotency(
                "train-1", trusted_workspace="workspace_other", trusted_owner="ml-owner",
            )
        runs.promote_ready(str(run["training_run_id"]), feature)
        coordinator = MLTrainingCoordinator(
            runs, research, LocalObjectStore(tmp_path), FakeTrainer(), worker_id="worker-test"
        )
        completed = coordinator.run_next()
        assert completed is not None and completed["status"] == "completed"
        notifications = runs.list_agent_notifications(
            trusted_workspace=context["x-byq-workspace-id"], trusted_owner="ml-owner",
        )
        assert notifications[0]["training_run_id"] == run["training_run_id"]
        assert notifications[0]["kind"] == "ml_training_progress"
        assert notifications[0]["status"] == "completed"
        assert "rows" not in notifications[0]
        feature_artifact = research.get_artifact(completed["feature_artifact_id"])
        model_artifact = research.get_artifact(completed["model_artifact_id"])
        assert feature_artifact["status"] == model_artifact["status"] == "validated"
        assert feature_artifact["content"]["storage_format"] == "gzip-json-v1"
        assert "rows" not in feature_artifact["content"]
        restored = load_feature_snapshot(feature_artifact["content"], LocalObjectStore(tmp_path))
        assert restored["content_sha256"] == feature["content_sha256"]
        assert restored["rows"] == feature["rows"]
        assert model_artifact["content"]["target"] == strategy_value["target"]
        assert model_artifact["content"]["split"] == strategy_value["split"]
        assert model_artifact["content"]["counts"]["symbols"]["train"] == 2
        assert model_artifact["content"]["image_identity"] == "byq-ml-worker-v1-test"
        reference = model_artifact["content"]["object_reference"]
        assert LocalObjectStore(tmp_path).get(reference) == b"tree\nversion=v4\n"
        failed = runs.create_waiting(
            workspace_id=context["x-byq-workspace-id"], owner_principal="ml-owner",
            task_id=task["task_id"], experiment_id=None,
            ml_strategy_artifact_id=strategy_artifact["artifact_id"],
            stock_pool_snapshot_id="snapshot_test", preparation={"strategy": strategy_value, "universe": universe},
            requirement={"requirement_sha256": "d" * 64}, readiness={"state": "ready"},
            trace_id="trace-ml", idempotency_key="train-retry",
        )
        runs.promote_ready(str(failed["training_run_id"]), feature)
        claimed = runs.claim_next("worker-fail")
        assert claimed is not None
        runs.fail(str(failed["training_run_id"]), "ml_training_failed", "size boundary",
                  worker_id="worker-fail", attempt_count=int(claimed["attempt_count"]))
        assert runs.retry_failed(failed["training_run_id"])["status"] == "queued"
        runs.cancel(
            failed["training_run_id"],
            trusted_workspace=context["x-byq-workspace-id"], trusted_owner="ml-owner",
        )
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
        cancelled_claim = runs.claim_preparation(cancellable["training_run_id"])
        assert cancelled_claim is not None
        cancelled = runs.cancel(
            cancellable["training_run_id"], trusted_workspace=context["x-byq-workspace-id"],
            trusted_owner="ml-owner",
        )
        assert cancelled["status"] == "cancelled"
        assert not runs.renew_preparation(cancellable["training_run_id"], cancelled_claim)
        with pytest.raises(MLTrainingConflict):
            runs.promote_ready(cancellable["training_run_id"], feature, claim=cancelled_claim)
        runs.fail_waiting(cancellable["training_run_id"], "late", "late failure", claim=cancelled_claim)
        assert runs.get(cancellable["training_run_id"])["status"] == "cancelled"
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
        preparation_id = str(fenced["training_run_id"])
        old_preparation = runs.claim_preparation(preparation_id)
        assert old_preparation is not None
        assert not any(key.startswith("preparation_") for key in runs.get(preparation_id))
        assert runs.claim_preparation(preparation_id) is None
        assert all(item["training_run_id"] != preparation_id for item in runs.list_waiting())
        runs._execute("UPDATE ml_training_runs SET preparation_lease_expires_at=now()-interval '1 second' WHERE training_run_id=:id",
                      {"id": preparation_id})
        runs.close()
        runs = MLTrainingRunStore()
        new_preparation = runs.claim_preparation(preparation_id)
        assert new_preparation is not None and new_preparation != old_preparation
        assert not runs.renew_preparation(preparation_id, old_preparation)
        runs.update_readiness(preparation_id, {"state": "stale-writer"}, claim=old_preparation)
        runs.record_preparation_repairs(preparation_id, ["stale-repair"], claim=old_preparation)
        runs.fail_waiting(preparation_id, "stale", "late failure", claim=old_preparation)
        runs.release_preparation(preparation_id, old_preparation)
        assert runs.get(preparation_id)["status"] == "waiting_for_data"
        assert runs.get(preparation_id)["readiness"]["state"] == "ready"
        assert runs.renew_preparation(preparation_id, new_preparation)
        with pytest.raises(MLTrainingConflict):
            runs.promote_ready(preparation_id, feature, claim=old_preparation)
        runs.promote_ready(preparation_id, feature, claim=new_preparation)
        runs.release_preparation(preparation_id, new_preparation)
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
        exhausted = runs.create_waiting(
            workspace_id=context["x-byq-workspace-id"], owner_principal="ml-owner",
            task_id=task["task_id"], experiment_id=None,
            ml_strategy_artifact_id=strategy_artifact["artifact_id"],
            stock_pool_snapshot_id="snapshot_test", preparation={"strategy": strategy_value, "universe": universe},
            requirement={"requirement_sha256": "c" * 64}, readiness={"state": "ready"},
            trace_id="trace-ml", idempotency_key="preparation-budget",
        )
        for _ in range(3):
            expired_claim = runs.claim_preparation(exhausted["training_run_id"])
            assert expired_claim is not None
            runs._execute("UPDATE ml_training_runs SET preparation_lease_expires_at=now()-interval '1 second' WHERE training_run_id=:id",
                          {"id": exhausted["training_run_id"]})
            runs.release_preparation(exhausted["training_run_id"], expired_claim)
            runs.close()
            runs = MLTrainingRunStore()
        assert runs.claim_preparation(exhausted["training_run_id"]) is None
        assert runs.get(exhausted["training_run_id"])["status"] == "failed"
        assert runs.get(exhausted["training_run_id"])["error_code"] == "ml_preparation_recovery_exhausted"
    finally:
        runs.close()
        research.close()
