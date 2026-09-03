from __future__ import annotations

import copy

import pytest

from app.ml_strategy import (
    FORCED_PARAMETERS,
    RUNTIME_LOCK,
    effective_lightgbm_parameters,
    normalize_ml_strategy,
    validate_ml_strategy_version,
)
from app.ml_capabilities import public_registry, validate_registry


def valid_strategy() -> dict[str, object]:
    return {
        "schema_version": "ml-strategy-version.v1",
        "name": "HS300 LightGBM",
        "learner": {"kind": "lightgbm_regression", "profile": "byq-lightgbm-cpu-v1"},
        "feature_set": {"id": "price-volume-basic-v1"},
        "target": {"kind": "forward_return", "horizon_sessions": 5},
        "split": {
            "train": {"start": "2020-01-01", "end": "2023-12-31"},
            "validation": {"start": "2024-01-01", "end": "2024-12-31"},
            "prediction": {"start": "2025-01-01", "end": "2025-06-30"},
        },
        "learner_parameters": {"num_leaves": 15, "learning_rate": 0.03},
        "signal_policy": {"kind": "top_n_equal_weight", "top_n": 20, "rebalance": "weekly"},
    }


def valid_strategy_v2(*, learner: str = "byq-ridge-cpu-v1") -> dict[str, object]:
    parameters = {"alpha": 1.0, "fit_intercept": True} if learner == "byq-ridge-cpu-v1" else {}
    return {
        "schema_version": "ml-strategy-version.v2",
        "name": "Walk-forward baseline",
        "feature_set": {"id": "price-volume-basic-v1", "parameters": {}},
        "target": {"id": "forward-return-v1", "parameters": {"horizon_sessions": 5}},
        "validation_plan": {"id": "walk-forward-purged-v1", "parameters": {
            "mode": "expanding", "train_sessions": 60, "validation_sessions": 10,
            "step_sessions": 10, "folds": 2, "purge_sessions": 5, "embargo_sessions": 0,
        }},
        "learner": {"profile": learner, "parameters": parameters},
        "portfolio_policy": {"id": "top-n-equal-weight-v1", "parameters": {
            "top_n": 10, "rebalance": "weekly",
        }},
        "development_window": {"start": "2024-01-01", "end": "2024-06-30"},
        "prediction_window": {"start": "2024-07-01", "end": "2024-08-31"},
    }


def test_ml_strategy_version_is_content_addressed_and_round_trips() -> None:
    first = normalize_ml_strategy(valid_strategy())
    second = normalize_ml_strategy(copy.deepcopy(valid_strategy()))
    assert first == second
    assert str(first["version_id"]).startswith("ml_strategy_")
    assert first["runtime_lock"] == RUNTIME_LOCK
    assert validate_ml_strategy_version(first) == first
    effective = effective_lightgbm_parameters(first)
    assert all(effective[key] == value for key, value in FORCED_PARAMETERS.items())
    assert effective["num_leaves"] == 15


@pytest.mark.parametrize(
    "mutation,message",
    [
        (lambda value: value.update({"python": "print('unsafe')"}), "unknown fields"),
        (lambda value: value["learner_parameters"].update({"objective": "custom"}), "unknown fields"),
        (lambda value: value["split"]["validation"].update({"start": "2023-01-01"}), "chronological"),
        (lambda value: value["target"].update({"horizon_sessions": 21}), "between 1 and 20"),
    ],
)
def test_ml_strategy_rejects_open_or_leaky_contracts(mutation, message: str) -> None:
    candidate = valid_strategy()
    mutation(candidate)
    with pytest.raises(ValueError, match=message):
        normalize_ml_strategy(candidate)


def test_ml_strategy_rejects_tampered_identity() -> None:
    version = normalize_ml_strategy(valid_strategy())
    version["version_id"] = "ml_strategy_tampered"
    with pytest.raises(ValueError, match="identity"):
        validate_ml_strategy_version(version)


def test_v2_registry_and_strategy_are_content_addressed_and_closed() -> None:
    registry = public_registry()
    assert validate_registry() == registry
    assert registry["schema_version"] == "ml-capability-registry.v2"
    assert registry["content_sha256"]
    components = {item["id"]: item for item in registry["components"]}
    assert components["byq-ridge-cpu-v1"]["output_contract"] == "ridge-linear-json-v1"
    assert components["walk-forward-purged-v1"]["status"] == "qualified"
    assert all("module" not in item and "class" not in item for item in components.values())

    first = normalize_ml_strategy(valid_strategy_v2())
    second = normalize_ml_strategy(copy.deepcopy(valid_strategy_v2()))
    assert first == second
    assert first["runtime_lock"].endswith("ridge-cpu-single-thread")
    assert first["capability_lock"]["content_sha256"]
    assert validate_ml_strategy_version(first) == first


@pytest.mark.parametrize(
    "mutation,message",
    [
        (lambda value: value["learner"].update({"module": "evil"}), "unknown fields"),
        (lambda value: value["learner"]["parameters"].update({"alpha": float("inf")}), "finite"),
        (lambda value: value["target"]["parameters"].update({"horizon_sessions": 10}), "purge"),
        (lambda value: value["validation_plan"]["parameters"].update({"step_sessions": 9}), "step"),
        (lambda value: value.update({"prediction_window": {"start": "2024-06-01", "end": "2024-08-31"}}), "development_window"),
    ],
)
def test_v2_strategy_rejects_unqualified_or_leaky_configuration(mutation, message: str) -> None:
    candidate = valid_strategy_v2()
    mutation(candidate)
    with pytest.raises(ValueError, match=message):
        normalize_ml_strategy(candidate)
