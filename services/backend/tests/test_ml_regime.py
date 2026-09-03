from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest

from app.ml_regime import (
    build_regime_snapshot,
    classify_regime,
    expert_key_for,
    validate_model_bundle,
    validate_regime_snapshot,
)
from app.ml_strategy import content_sha256, normalize_ml_strategy
from tests.test_ml_strategy import valid_regime_strategy_v2


def benchmark_rows(count: int = 90, *, start: float = 100.0, daily_change: float = 0.001):
    rows = []
    value = start
    for offset in range(count):
        session = (date(2024, 1, 1) + timedelta(days=offset)).isoformat()
        rows.append({"symbol": "000300.SH", "trade_date": session, "close": value})
        value *= 1.0 + daily_change
    return rows


def test_regime_snapshot_is_point_in_time_content_addressed_and_warmup_safe() -> None:
    strategy = normalize_ml_strategy(valid_regime_strategy_v2())
    benchmark = benchmark_rows()
    sessions = [row["trade_date"] for row in benchmark[58:65]]
    snapshot = build_regime_snapshot(
        strategy=strategy, sessions=sessions, benchmark_rows=benchmark,
        ready_input_sha256="a" * 64,
    )
    assert validate_regime_snapshot(snapshot) == snapshot
    assert [row["state"] for row in snapshot["rows"][:2]] == ["unknown", "unknown"]
    assert snapshot["rows"][2]["state"] == "risk_on"
    # Future benchmark changes cannot affect an earlier session.
    changed = copy.deepcopy(benchmark)
    changed[-1]["close"] *= 0.1
    repeated = build_regime_snapshot(
        strategy=strategy, sessions=[sessions[2]], benchmark_rows=changed,
        ready_input_sha256="b" * 64,
    )
    assert repeated["rows"][0]["metrics"] == snapshot["rows"][2]["metrics"]


def test_regime_boundaries_are_inclusive_and_risk_off_precedes_risk_on() -> None:
    parameters = normalize_ml_strategy(valid_regime_strategy_v2())["regime"]["parameters"]
    assert classify_regime({
        "return_20": -0.03, "return_60": 0.05,
        "volatility_20": 0.01, "ma_distance_60": 0.03,
    }, parameters) == "risk_off"
    assert classify_regime({
        "return_20": 0.01, "return_60": 0.02,
        "volatility_20": 0.01, "ma_distance_60": 0.0,
    }, parameters) == "risk_on"


def test_regime_snapshot_rejects_wrong_benchmark_missing_row_is_unknown() -> None:
    strategy = normalize_ml_strategy(valid_regime_strategy_v2())
    with pytest.raises(ValueError, match="HS300"):
        build_regime_snapshot(
            strategy=strategy, sessions=["2024-03-01"],
            benchmark_rows=[{"symbol": "000905.SH", "trade_date": "2024-03-01", "close": 100.0}],
            ready_input_sha256="a" * 64,
        )
    snapshot = build_regime_snapshot(
        strategy=strategy, sessions=["2025-01-01"], benchmark_rows=benchmark_rows(),
        ready_input_sha256="a" * 64,
    )
    assert snapshot["rows"][0] == {
        "session": "2025-01-01", "as_of": "2025-01-01",
        "state": "unknown", "reason": "benchmark_missing",
    }


def bundle_value() -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "ml-model-bundle.v1",
        "strategy_version_artifact_id": "artifact_strategy",
        "feature_snapshot_artifact_id": "artifact_feature",
        "regime_snapshot_artifact_id": "artifact_regime",
        "stock_pool_snapshot_id": "snapshot_pool",
        "routing_policy": {"id": "regime-expert-map-v1", "fallback": "neutral"},
        "experts": [
            {"key": "neutral", "training_regimes": ["neutral"],
             "model_artifact_id": "artifact_neutral", "model_content_sha256": "a" * 64,
             "learner_profile": "byq-ridge-cpu-v1", "folds_sha256": "b" * 64},
            {"key": "risk_on", "training_regimes": ["risk_on"],
             "model_artifact_id": "artifact_risk_on", "model_content_sha256": "c" * 64,
             "learner_profile": "byq-lightgbm-cpu-v1", "folds_sha256": "d" * 64},
        ],
    }
    document["content_sha256"] = content_sha256(document)
    return document


def test_bundle_router_is_deterministic_and_tamper_closed() -> None:
    bundle = bundle_value()
    assert validate_model_bundle(bundle) == bundle
    assert expert_key_for("risk_on", bundle) == "risk_on"
    assert expert_key_for("risk_off", bundle) == "neutral"
    assert expert_key_for("unknown", bundle) == "neutral"
    tampered = copy.deepcopy(bundle)
    tampered["routing_policy"]["fallback"] = "risk_on"
    with pytest.raises(ValueError, match="identity"):
        validate_model_bundle(tampered)
