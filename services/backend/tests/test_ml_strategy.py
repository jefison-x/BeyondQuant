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
