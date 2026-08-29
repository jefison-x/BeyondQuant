"""Closed ML strategy-version contract for the ADR-0043 LightGBM profile."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any


SCHEMA_VERSION = "ml-strategy-version.v1"
EXECUTION_PROFILE = "byq-lightgbm-cpu-v1"
FEATURE_SET = "price-volume-basic-v1"
FEATURE_ORDER = ["return_1", "return_5", "return_20", "volatility_20", "volume_ratio_5"]
RUNTIME_LOCK = "python-3.13/lightgbm-4.7.0/numpy-2.3.3/cpu-single-thread"
FORCED_PARAMETERS: dict[str, object] = {
    "objective": "regression",
    "metric": "l2",
    "device_type": "cpu",
    "deterministic": True,
    "force_col_wise": True,
    "seed": 20260829,
    "num_threads": 1,
    "verbosity": -1,
}
PARAMETER_RULES: dict[str, tuple[type, float, float]] = {
    "num_leaves": (int, 2, 255),
    "learning_rate": (float, 0.001, 0.5),
    "max_depth": (int, -1, 32),
    "min_data_in_leaf": (int, 5, 10_000),
    "feature_fraction": (float, 0.1, 1.0),
    "bagging_fraction": (float, 0.1, 1.0),
    "num_boost_round": (int, 10, 2_000),
    "early_stopping_rounds": (int, 1, 200),
}
DEFAULT_PARAMETERS: dict[str, object] = {
    "num_leaves": 31,
    "learning_rate": 0.05,
    "max_depth": -1,
    "min_data_in_leaf": 20,
    "feature_fraction": 1.0,
    "bagging_fraction": 1.0,
    "num_boost_round": 200,
    "early_stopping_rounds": 20,
}


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("ML strategy must be finite JSON") from error


def content_sha256(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _object(value: object, *, field: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{field} has unknown fields: {', '.join(unknown)}")
    return value


def _text(value: object, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{field} must be a non-empty string of at most {maximum} characters")
    return value.strip()


def _date(value: object, *, field: str) -> str:
    normalized = _text(value, field=field, maximum=10)
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as error:
        raise ValueError(f"{field} must be YYYY-MM-DD") from error


def _integer(value: object, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{field} must be an integer between {minimum} and {maximum}")
    return value


def _parameters(value: object) -> dict[str, object]:
    supplied = _object(value, field="learner_parameters", allowed=set(PARAMETER_RULES))
    result = dict(DEFAULT_PARAMETERS)
    for name, raw in supplied.items():
        expected, minimum, maximum = PARAMETER_RULES[name]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"learner_parameters.{name} must be numeric")
        if expected is int and not isinstance(raw, int):
            raise ValueError(f"learner_parameters.{name} must be an integer")
        normalized = int(raw) if expected is int else float(raw)
        if not math.isfinite(float(normalized)) or not minimum <= normalized <= maximum:
            raise ValueError(
                f"learner_parameters.{name} must be between {minimum:g} and {maximum:g}"
            )
        result[name] = normalized
    return result


def normalize_ml_strategy(value: object) -> dict[str, object]:
    data = _object(
        value,
        field="ml_strategy",
        allowed={
            "schema_version", "name", "learner", "feature_set", "target", "split",
            "learner_parameters", "signal_policy",
        },
    )
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported ML strategy schema")
    learner = _object(data.get("learner"), field="learner", allowed={"kind", "profile"})
    if learner != {"kind": "lightgbm_regression", "profile": EXECUTION_PROFILE}:
        raise ValueError("only the closed LightGBM regression profile is supported")
    feature_set = _object(data.get("feature_set"), field="feature_set", allowed={"id"})
    if feature_set.get("id") != FEATURE_SET:
        raise ValueError("unsupported feature set")
    target = _object(data.get("target"), field="target", allowed={"kind", "horizon_sessions"})
    if target.get("kind") != "forward_return":
        raise ValueError("only forward_return target is supported")
    horizon = _integer(
        target.get("horizon_sessions"), field="target.horizon_sessions", minimum=1, maximum=20
    )
    split = _object(data.get("split"), field="split", allowed={"train", "validation", "prediction"})
    normalized_split: dict[str, dict[str, str]] = {}
    for name in ("train", "validation", "prediction"):
        window = _object(split.get(name), field=f"split.{name}", allowed={"start", "end"})
        start = _date(window.get("start"), field=f"split.{name}.start")
        end = _date(window.get("end"), field=f"split.{name}.end")
        if start > end:
            raise ValueError(f"split.{name}.start must not be after end")
        normalized_split[name] = {"start": start, "end": end}
    if not (
        normalized_split["train"]["end"] < normalized_split["validation"]["start"]
        and normalized_split["validation"]["end"] < normalized_split["prediction"]["start"]
    ):
        raise ValueError("ML strategy splits must be chronological and non-overlapping")
    policy = _object(data.get("signal_policy"), field="signal_policy", allowed={"kind", "top_n", "rebalance"})
    if policy.get("kind") != "top_n_equal_weight" or policy.get("rebalance") not in {"daily", "weekly", "monthly"}:
        raise ValueError("unsupported ML signal policy")
    top_n = _integer(policy.get("top_n"), field="signal_policy.top_n", minimum=1, maximum=100)
    snapshot: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "name": _text(data.get("name"), field="name", maximum=128),
        "learner": {"kind": "lightgbm_regression", "profile": EXECUTION_PROFILE},
        "feature_set": {"id": FEATURE_SET, "feature_order": FEATURE_ORDER},
        "target": {"kind": "forward_return", "horizon_sessions": horizon},
        "split": normalized_split,
        "learner_parameters": _parameters(data.get("learner_parameters", {})),
        "signal_policy": {
            "kind": "top_n_equal_weight", "top_n": top_n, "rebalance": policy["rebalance"]
        },
        "runtime_lock": RUNTIME_LOCK,
    }
    snapshot["version_id"] = f"ml_strategy_{content_sha256(snapshot)[:32]}"
    return snapshot


def validate_ml_strategy_version(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("ML strategy version must be an object")
    source = {key: nested for key, nested in value.items() if key not in {"version_id", "runtime_lock"}}
    feature_set = source.get("feature_set")
    if isinstance(feature_set, dict):
        source["feature_set"] = {"id": feature_set.get("id")}
    normalized = normalize_ml_strategy(source)
    if not isinstance(value, dict) or value.get("version_id") != normalized["version_id"]:
        raise ValueError("ML strategy version identity does not match content")
    if value.get("runtime_lock") != RUNTIME_LOCK:
        raise ValueError("ML strategy runtime lock is unsupported")
    return normalized


def effective_lightgbm_parameters(strategy: dict[str, object]) -> dict[str, object]:
    supplied = strategy.get("learner_parameters")
    if not isinstance(supplied, dict):
        raise ValueError("ML strategy learner parameters are invalid")
    return {**supplied, **FORCED_PARAMETERS}
