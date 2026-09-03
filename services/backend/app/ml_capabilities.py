"""Closed, code-owned ML capability registry (ADR-0048).

The registry is data, not dynamic Python discovery. Runtime dispatch uses exact
identities below and never imports a client-supplied module or class name.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any


REGISTRY_SCHEMA = "ml-capability-registry.v2"
STRATEGY_SCHEMA = "ml-strategy-version.v2"
FEATURE_ORDER = ["return_1", "return_5", "return_20", "volatility_20", "volume_ratio_5"]
LIGHTGBM_RUNTIME_LOCK = "python-3.13/lightgbm-4.7.0/numpy-2.3.3/cpu-single-thread"
LIGHTGBM_RUNTIME_IDENTITY = "lightgbm-4.7.0-python-3.13-linux-cpu-single-thread"
RIDGE_RUNTIME_LOCK = "python-3.13/numpy-2.3.3/ridge-cpu-single-thread"
RIDGE_RUNTIME_IDENTITY = "ridge-numpy-2.3.3-python-3.13-linux-cpu-single-thread"


def canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("ML capability input must be finite JSON") from error


def content_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


_COMPONENTS: tuple[dict[str, object], ...] = (
    {
        "id": "price-volume-basic-v1", "kind": "feature_set", "contract_version": "feature-set.v1",
        "display_name": "基础价量特征", "status": "qualified", "parameters": {},
        "input_contract": "adjusted-research-bars.v1", "output_contract": "finite-feature-panel.v1",
        "limits": {"features": 5, "rows": 2_000_000}, "runtime_profile": "byq-feature-builder-v1",
        "qualification": "phase-72-and-84-regression",
    },
    {
        "id": "forward-return-v1", "kind": "target", "contract_version": "target-definition.v1",
        "display_name": "未来交易日收益", "status": "qualified",
        "parameters": {"horizon_sessions": {"type": "integer", "min": 1, "max": 20, "default": 5}},
        "input_contract": "adjusted-research-bars.v1", "output_contract": "finite-regression-target.v1",
        "limits": {"horizon_sessions": 20}, "runtime_profile": "byq-feature-builder-v1",
        "qualification": "phase-72-and-84-no-look-ahead",
    },
    {
        "id": "single-chronological-v1", "kind": "validation_plan",
        "contract_version": "validation-plan.v1", "display_name": "单次时间顺序切分", "status": "qualified",
        "parameters": {}, "input_contract": "explicit-three-window.v1",
        "output_contract": "single-validation-result.v1", "limits": {"folds": 1},
        "runtime_profile": "byq-validation-v1", "qualification": "phase-72-v1-compat",
    },
    {
        "id": "walk-forward-purged-v1", "kind": "validation_plan",
        "contract_version": "validation-plan.v1", "display_name": "净化走步验证", "status": "qualified",
        "parameters": {
            "mode": {"type": "enum", "values": ["expanding", "rolling"], "default": "expanding"},
            "train_sessions": {"type": "integer", "min": 60, "max": 1500, "default": 480},
            "validation_sessions": {"type": "integer", "min": 10, "max": 250, "default": 60},
            "step_sessions": {"type": "integer", "min": 10, "max": 250, "default": 60},
            "folds": {"type": "integer", "min": 2, "max": 12, "default": 4},
            "purge_sessions": {"type": "integer", "min": 1, "max": 20, "default": 5},
            "embargo_sessions": {"type": "integer", "min": 0, "max": 20, "default": 0},
        },
        "input_contract": "development-feature-panel.v1", "output_contract": "fold-manifest.v1",
        "limits": {"folds": 12, "sessions": 2500}, "runtime_profile": "byq-validation-v2",
        "qualification": "phase-84-purged-walk-forward",
    },
    {
        "id": "byq-lightgbm-cpu-v1", "kind": "learner_profile",
        "contract_version": "learner-profile.v1", "display_name": "LightGBM CPU", "status": "qualified",
        "parameters": {
            "num_leaves": {"type": "integer", "min": 2, "max": 255, "default": 31},
            "learning_rate": {"type": "number", "min": 0.001, "max": 0.5, "default": 0.05},
            "max_depth": {"type": "integer", "min": -1, "max": 32, "default": -1},
            "min_data_in_leaf": {"type": "integer", "min": 5, "max": 10000, "default": 20},
            "feature_fraction": {"type": "number", "min": 0.1, "max": 1.0, "default": 1.0},
            "bagging_fraction": {"type": "number", "min": 0.1, "max": 1.0, "default": 1.0},
            "num_boost_round": {"type": "integer", "min": 10, "max": 2000, "default": 200},
            "early_stopping_rounds": {"type": "integer", "min": 1, "max": 200, "default": 20},
        },
        "input_contract": "finite-regression-matrix.v1", "output_contract": "lightgbm-text-v1",
        "limits": {"threads": 1, "model_bytes": 33_554_432}, "runtime_profile": LIGHTGBM_RUNTIME_LOCK,
        "qualification": "phase-72-and-84-worker-probe",
    },
    {
        "id": "byq-ridge-cpu-v1", "kind": "learner_profile", "contract_version": "learner-profile.v1",
        "display_name": "Ridge 线性基线", "status": "qualified",
        "parameters": {
            "alpha": {"type": "number", "min": 0.000001, "max": 1000000.0, "default": 1.0},
            "fit_intercept": {"type": "boolean", "default": True},
        },
        "input_contract": "finite-regression-matrix.v1", "output_contract": "ridge-linear-json-v1",
        "limits": {"threads": 1, "model_bytes": 65536}, "runtime_profile": RIDGE_RUNTIME_LOCK,
        "qualification": "phase-84-worker-probe",
    },
    {
        "id": "hs300-trend-volatility-v1", "kind": "regime_definition",
        "contract_version": "regime-definition.v1", "display_name": "沪深300趋势波动状态",
        "status": "qualified",
        "parameters": {
            "risk_on_return_60_min": {"type": "number", "min": -0.2, "max": 0.3, "default": 0.02},
            "risk_on_ma_distance_60_min": {"type": "number", "min": -0.1, "max": 0.2, "default": 0.0},
            "risk_off_return_20_max": {"type": "number", "min": -0.3, "max": 0.1, "default": -0.03},
            "risk_off_volatility_20_min": {"type": "number", "min": 0.005, "max": 0.1, "default": 0.025},
            "risk_off_ma_distance_60_max": {"type": "number", "min": -0.2, "max": 0.05, "default": -0.02},
        },
        "input_contract": "frozen-hs300-index-daily.v1",
        "output_contract": "ml-regime-snapshot.v1",
        "limits": {"benchmark": "000300.SH", "lookback_sessions": 60, "states": 4},
        "runtime_profile": "byq-regime-builder-v1",
        "qualification": "phase-85-point-in-time-boundary-suite",
    },
    {
        "id": "regime-expert-map-v1", "kind": "routing_policy",
        "contract_version": "routing-policy.v1", "display_name": "市场状态专家映射",
        "status": "qualified", "parameters": {},
        "input_contract": "ml-regime-snapshot.v1+ml-model-bundle.v1",
        "output_contract": "routed-prediction.v1",
        "limits": {"experts": 4, "fallbacks": 1},
        "runtime_profile": "byq-deterministic-router-v1",
        "qualification": "phase-85-route-tamper-suite",
    },
    {
        "id": "top-n-equal-weight-v1", "kind": "portfolio_policy",
        "contract_version": "portfolio-policy.v1", "display_name": "Top-N 等权", "status": "qualified",
        "parameters": {
            "top_n": {"type": "integer", "min": 1, "max": 100, "default": 20},
            "rebalance": {"type": "enum", "values": ["daily", "weekly", "monthly"], "default": "weekly"},
        },
        "input_contract": "ranked-prediction.v1", "output_contract": "signal-snapshot.v1",
        "limits": {"top_n": 100}, "runtime_profile": "byq-portfolio-v1",
        "qualification": "phase-73-v1-compat",
    },
)


def _component_with_hash(component: dict[str, object]) -> dict[str, object]:
    result = json.loads(json.dumps(component))
    result["content_sha256"] = content_sha256(result)
    return result


COMPONENTS = tuple(_component_with_hash(item) for item in _COMPONENTS)
BY_ID = {str(item["id"]): item for item in COMPONENTS}


def public_registry() -> dict[str, object]:
    components = [json.loads(json.dumps(item)) for item in COMPONENTS]
    document: dict[str, object] = {"schema_version": REGISTRY_SCHEMA, "components": components}
    document["content_sha256"] = content_sha256(document)
    return document


def validate_registry() -> dict[str, object]:
    registry = public_registry()
    seen: set[str] = set()
    allowed_kinds = {
        "feature_set", "target", "validation_plan", "learner_profile", "regime_definition",
        "routing_policy", "portfolio_policy",
    }
    for component in registry["components"]:
        identity = str(component.get("id"))
        if identity in seen:
            raise ValueError("ML capability registry contains a duplicate identity")
        seen.add(identity)
        if component.get("kind") not in allowed_kinds or component.get("status") not in {"qualified", "disabled", "blocked"}:
            raise ValueError("ML capability registry contains invalid metadata")
        supplied_hash = component.get("content_sha256")
        body = {key: value for key, value in component.items() if key != "content_sha256"}
        if supplied_hash != content_sha256(body):
            raise ValueError("ML capability registry component hash is invalid")
        if any(key in component for key in ("module", "class", "command", "path")):
            raise ValueError("ML capability registry contains executable dispatch metadata")
    body = {key: value for key, value in registry.items() if key != "content_sha256"}
    if registry.get("content_sha256") != content_sha256(body):
        raise ValueError("ML capability registry hash is invalid")
    return registry


def _object(value: object, field: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{field} has unknown fields: {', '.join(unknown)}")
    return value


def _text(value: object, field: str, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{field} must be a non-empty string of at most {maximum} characters")
    return value.strip()


def _date(value: object, field: str) -> str:
    normalized = _text(value, field, 10)
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as error:
        raise ValueError(f"{field} must be YYYY-MM-DD") from error


def _window(value: object, field: str) -> dict[str, str]:
    raw = _object(value, field, {"start", "end"})
    start, end = _date(raw.get("start"), f"{field}.start"), _date(raw.get("end"), f"{field}.end")
    if start > end:
        raise ValueError(f"{field}.start must not be after end")
    return {"start": start, "end": end}


def _parameters(component_id: str, value: object, field: str) -> dict[str, object]:
    component = BY_ID.get(component_id)
    if component is None or component.get("status") != "qualified":
        raise ValueError(f"{field} references an unknown or unavailable capability")
    rules = component.get("parameters")
    if not isinstance(rules, dict):
        raise ValueError(f"{field} capability metadata is invalid")
    supplied = _object(value, field, set(rules))
    result: dict[str, object] = {}
    for name, raw_rule in rules.items():
        if not isinstance(raw_rule, dict):
            raise ValueError(f"{field}.{name} capability metadata is invalid")
        raw = supplied.get(name, raw_rule.get("default"))
        kind = raw_rule.get("type")
        if kind == "integer":
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise ValueError(f"{field}.{name} must be an integer")
        elif kind == "number":
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
                raise ValueError(f"{field}.{name} must be a finite number")
            raw = float(raw)
        elif kind == "boolean":
            if not isinstance(raw, bool):
                raise ValueError(f"{field}.{name} must be a boolean")
        elif kind == "enum":
            if raw not in raw_rule.get("values", []):
                raise ValueError(f"{field}.{name} has an unsupported value")
        else:
            raise ValueError(f"{field}.{name} capability metadata is invalid")
        if kind in {"integer", "number"} and not float(raw_rule["min"]) <= float(raw) <= float(raw_rule["max"]):
            raise ValueError(f"{field}.{name} is outside the qualified range")
        result[name] = raw
    return result


def _reference(value: object, field: str, expected_kind: str) -> tuple[str, dict[str, object]]:
    raw = _object(value, field, {"id", "profile", "parameters"})
    if ("id" in raw) == ("profile" in raw):
        raise ValueError(f"{field} must provide exactly one capability identity")
    identity = raw.get("id", raw.get("profile"))
    identity = _text(identity, f"{field}.id")
    component = BY_ID.get(identity)
    if component is None or component.get("kind") != expected_kind or component.get("status") != "qualified":
        raise ValueError(f"{field} references an unknown or unavailable {expected_kind}")
    return identity, _parameters(identity, raw.get("parameters", {}), f"{field}.parameters")


def normalize_ml_strategy_v2(value: object) -> dict[str, object]:
    data = _object(value, "ml_strategy", {
        "schema_version", "name", "feature_set", "target", "validation_plan", "learner",
        "portfolio_policy", "development_window", "prediction_window", "regime",
        "routing_policy", "experts",
    })
    if data.get("schema_version") != STRATEGY_SCHEMA:
        raise ValueError("unsupported ML strategy schema")
    feature_id, feature_parameters = _reference(data.get("feature_set"), "feature_set", "feature_set")
    target_id, target_parameters = _reference(data.get("target"), "target", "target")
    validation_id, validation_parameters = _reference(
        data.get("validation_plan"), "validation_plan", "validation_plan"
    )
    learner_id, learner_parameters = _reference(data.get("learner"), "learner", "learner_profile")
    portfolio_id, portfolio_parameters = _reference(
        data.get("portfolio_policy"), "portfolio_policy", "portfolio_policy"
    )
    if validation_id != "walk-forward-purged-v1":
        raise ValueError("v2 requires walk-forward-purged-v1")
    if int(validation_parameters["purge_sessions"]) < int(target_parameters["horizon_sessions"]):
        raise ValueError("validation purge must cover the target horizon")
    if int(validation_parameters["step_sessions"]) < (
        int(validation_parameters["validation_sessions"]) + int(validation_parameters["embargo_sessions"])
    ):
        raise ValueError("validation step must cover validation and embargo sessions")
    development = _window(data.get("development_window"), "development_window")
    prediction = _window(data.get("prediction_window"), "prediction_window")
    if development["end"] >= prediction["start"]:
        raise ValueError("development_window must end before prediction_window starts")
    resolved = [BY_ID[item] for item in (feature_id, target_id, validation_id, learner_id, portfolio_id)]
    regime_config: dict[str, object] | None = None
    routing_config: dict[str, object] | None = None
    expert_configs: list[dict[str, object]] | None = None
    if data.get("regime") is not None:
        regime_raw = _object(data.get("regime"), "regime", {"definition", "parameters", "enabled"})
        if regime_raw.get("enabled") is not True:
            raise ValueError("regime.enabled must be true when regime is configured")
        regime_id = _text(regime_raw.get("definition"), "regime.definition")
        regime_component = BY_ID.get(regime_id)
        if regime_component is None or regime_component.get("kind") != "regime_definition" or regime_component.get("status") != "qualified":
            raise ValueError("regime references an unknown or unavailable regime_definition")
        regime_parameters = _parameters(regime_id, regime_raw.get("parameters", {}), "regime.parameters")
        routing_raw = _object(data.get("routing_policy"), "routing_policy", {"id", "fallback"})
        routing_id = _text(routing_raw.get("id"), "routing_policy.id")
        routing_component = BY_ID.get(routing_id)
        if routing_component is None or routing_component.get("kind") != "routing_policy" or routing_component.get("status") != "qualified":
            raise ValueError("routing_policy references an unknown or unavailable routing_policy")
        fallback = _text(routing_raw.get("fallback"), "routing_policy.fallback", 32)
        raw_experts = data.get("experts")
        if not isinstance(raw_experts, list) or not 2 <= len(raw_experts) <= 4:
            raise ValueError("experts must contain between 2 and 4 entries")
        expert_configs = []
        seen_keys: set[str] = set()
        allowed_states = {"risk_on", "neutral", "risk_off"}
        trainable_states = allowed_states
        for index, raw_expert in enumerate(raw_experts):
            expert = _object(raw_expert, f"experts[{index}]", {"key", "learner", "training_regimes"})
            key = _text(expert.get("key"), f"experts[{index}].key", 32)
            if key not in allowed_states or key in seen_keys:
                raise ValueError("expert keys must be unique registered regime states")
            seen_keys.add(key)
            expert_learner_id, expert_parameters = _reference(
                expert.get("learner"), f"experts[{index}].learner", "learner_profile"
            )
            raw_training_regimes = expert.get("training_regimes")
            if (
                not isinstance(raw_training_regimes, list)
                or not raw_training_regimes
                or len(raw_training_regimes) > 3
                or any(item not in trainable_states for item in raw_training_regimes)
            ):
                raise ValueError("expert training_regimes must contain registered trainable states")
            training_regimes = sorted(set(str(item) for item in raw_training_regimes))
            if len(training_regimes) != len(raw_training_regimes):
                raise ValueError("expert training_regimes must be unique")
            expert_configs.append({
                "key": key,
                "learner": {"profile": expert_learner_id, "parameters": expert_parameters},
                "training_regimes": training_regimes,
            })
            resolved.append(BY_ID[expert_learner_id])
        expert_configs.sort(key=lambda item: str(item["key"]))
        if fallback not in seen_keys:
            raise ValueError("routing_policy.fallback must reference a configured expert")
        regime_config = {"definition": regime_id, "parameters": regime_parameters, "enabled": True}
        routing_config = {"id": routing_id, "fallback": fallback}
        resolved.extend((regime_component, routing_component))
    elif data.get("routing_policy") is not None or data.get("experts") is not None:
        raise ValueError("routing_policy and experts require a configured regime")
    unique_resolved: list[dict[str, object]] = []
    seen_resolved: set[str] = set()
    for item in resolved:
        identity = str(item["id"])
        if identity not in seen_resolved:
            unique_resolved.append(item)
            seen_resolved.add(identity)
    capability_lock = {
        "registry_schema": REGISTRY_SCHEMA,
        "components": [
            {"id": item["id"], "content_sha256": item["content_sha256"]}
            for item in unique_resolved
        ],
        "runtime_lock": BY_ID[learner_id]["runtime_profile"],
    }
    capability_lock["content_sha256"] = content_sha256(capability_lock)
    snapshot: dict[str, object] = {
        "schema_version": STRATEGY_SCHEMA,
        "name": _text(data.get("name"), "name"),
        "feature_set": {"id": feature_id, "parameters": feature_parameters, "feature_order": FEATURE_ORDER},
        "target": {"id": target_id, "parameters": target_parameters},
        "validation_plan": {"id": validation_id, "parameters": validation_parameters},
        "learner": {"profile": learner_id, "parameters": learner_parameters},
        "portfolio_policy": {"id": portfolio_id, "parameters": portfolio_parameters},
        "development_window": development,
        "prediction_window": prediction,
        "capability_lock": capability_lock,
        "runtime_lock": capability_lock["runtime_lock"],
    }
    if regime_config is not None and routing_config is not None and expert_configs is not None:
        snapshot.update({
            "regime": regime_config,
            "routing_policy": routing_config,
            "experts": expert_configs,
        })
    snapshot["version_id"] = f"ml_strategy_{content_sha256(snapshot)[:32]}"
    return snapshot


def validate_ml_strategy_v2(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("ML strategy version must be an object")
    source = {key: nested for key, nested in value.items() if key not in {"version_id", "runtime_lock", "capability_lock"}}
    for field in ("feature_set", "target", "validation_plan", "learner", "portfolio_policy"):
        item = source.get(field)
        if isinstance(item, dict):
            allowed = {"id", "profile", "parameters"}
            source[field] = {key: nested for key, nested in item.items() if key in allowed}
    experts = source.get("experts")
    if isinstance(experts, list):
        source["experts"] = [
            {
                **{key: nested for key, nested in item.items() if key in {"key", "training_regimes"}},
                **({"learner": {
                    key: nested for key, nested in item.get("learner", {}).items()
                    if key in {"profile", "parameters"}
                }} if isinstance(item, dict) and isinstance(item.get("learner"), dict) else {}),
            }
            if isinstance(item, dict) else item
            for item in experts
        ]
    normalized = normalize_ml_strategy_v2(source)
    if value.get("version_id") != normalized["version_id"]:
        raise ValueError("ML strategy version identity does not match content")
    if value.get("runtime_lock") != normalized["runtime_lock"]:
        raise ValueError("ML strategy runtime lock is unsupported")
    if value.get("capability_lock") != normalized["capability_lock"]:
        raise ValueError("ML strategy capability lock does not match the qualified registry")
    return normalized


def strategy_data_window(strategy: dict[str, object]) -> tuple[str, str]:
    if strategy.get("schema_version") == STRATEGY_SCHEMA:
        return str(strategy["development_window"]["start"]), str(strategy["prediction_window"]["end"])
    return str(strategy["split"]["train"]["start"]), str(strategy["split"]["prediction"]["end"])


def learner_profile(strategy: dict[str, object]) -> str:
    if strategy.get("schema_version") == STRATEGY_SCHEMA:
        return str(strategy["learner"]["profile"])
    return "byq-lightgbm-cpu-v1"


def expected_runtime_identity(strategy: dict[str, object]) -> str:
    return RIDGE_RUNTIME_IDENTITY if learner_profile(strategy) == "byq-ridge-cpu-v1" else LIGHTGBM_RUNTIME_IDENTITY


def runtime_lock_for_profile(profile: str) -> str:
    component = BY_ID.get(profile)
    if component is None or component.get("kind") != "learner_profile" or component.get("status") != "qualified":
        raise ValueError("learner profile runtime is unavailable")
    return str(component["runtime_profile"])


def model_size_limit_for_profile(profile: str) -> int:
    component = BY_ID.get(profile)
    limits = component.get("limits") if isinstance(component, dict) else None
    value = limits.get("model_bytes") if isinstance(limits, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("learner profile model size limit is unavailable")
    return value
