"""Frozen point-in-time regime evidence and deterministic expert routing."""

from __future__ import annotations

import math
import statistics

from .ml_capabilities import content_sha256


REGIME_SCHEMA = "ml-regime-snapshot.v1"
BUNDLE_SCHEMA = "ml-model-bundle.v1"
ROUTING_POLICY = "regime-expert-map-v1"
BENCHMARK_SYMBOL = "000300.SH"
REGIME_STATES = {"risk_on", "neutral", "risk_off", "unknown"}
EXPERT_KEYS = {"risk_on", "neutral", "risk_off"}


def _verify_hash(document: dict[str, object], field: str) -> str:
    supplied = document.get("content_sha256")
    body = {key: value for key, value in document.items() if key != "content_sha256"}
    if not isinstance(supplied, str) or supplied != content_sha256(body):
        raise ValueError(f"{field} identity does not match content")
    return supplied


def classify_regime(metrics: dict[str, float], parameters: dict[str, object]) -> str:
    """Apply the frozen inclusive boundary order: risk-off, risk-on, neutral."""
    if (
        metrics["return_20"] <= float(parameters["risk_off_return_20_max"])
        or metrics["volatility_20"] >= float(parameters["risk_off_volatility_20_min"])
        or metrics["ma_distance_60"] <= float(parameters["risk_off_ma_distance_60_max"])
    ):
        return "risk_off"
    if (
        metrics["return_60"] >= float(parameters["risk_on_return_60_min"])
        and metrics["ma_distance_60"] >= float(parameters["risk_on_ma_distance_60_min"])
    ):
        return "risk_on"
    return "neutral"


def build_regime_snapshot(
    *, strategy: dict[str, object], sessions: list[str], benchmark_rows: object,
    ready_input_sha256: object,
) -> dict[str, object]:
    regime = strategy.get("regime")
    if not isinstance(regime, dict) or regime.get("enabled") is not True:
        raise ValueError("ML regime configuration is unavailable")
    if regime.get("definition") != "hs300-trend-volatility-v1":
        raise ValueError("ML regime definition is unsupported")
    parameters = regime.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError("ML regime parameters are unavailable")
    if not isinstance(benchmark_rows, list) or len(benchmark_rows) > 2500:
        raise ValueError("frozen HS300 benchmark evidence is invalid")
    by_session: dict[str, float] = {}
    for raw in benchmark_rows:
        if not isinstance(raw, dict) or raw.get("symbol") != BENCHMARK_SYMBOL:
            raise ValueError("regime evidence must contain only frozen HS300 rows")
        session = str(raw.get("trade_date"))
        if session in by_session:
            raise ValueError("regime evidence contains duplicate benchmark sessions")
        close = raw.get("close")
        if isinstance(close, bool) or not isinstance(close, (int, float)) or not math.isfinite(float(close)) or float(close) <= 0:
            raise ValueError("regime evidence contains an invalid benchmark close")
        by_session[session] = float(close)
    ordered = sorted(by_session)
    positions = {session: index for index, session in enumerate(ordered)}
    rows: list[dict[str, object]] = []
    for session in sorted(set(sessions)):
        index = positions.get(session)
        if index is None:
            rows.append({"session": session, "as_of": session, "state": "unknown", "reason": "benchmark_missing"})
            continue
        if index < 60:
            rows.append({"session": session, "as_of": session, "state": "unknown", "reason": "warmup_incomplete"})
            continue
        closes = [by_session[ordered[offset]] for offset in range(index - 60, index + 1)]
        returns = [closes[offset] / closes[offset - 1] - 1.0 for offset in range(41, 61)]
        mean_60 = sum(closes[1:]) / 60.0
        metrics = {
            "return_20": closes[-1] / closes[-21] - 1.0,
            "return_60": closes[-1] / closes[0] - 1.0,
            "volatility_20": statistics.pstdev(returns),
            "ma_distance_60": closes[-1] / mean_60 - 1.0,
        }
        if not all(math.isfinite(value) for value in metrics.values()):
            raise ValueError("regime calculation returned non-finite metrics")
        rows.append({
            "session": session, "as_of": session,
            "state": classify_regime(metrics, parameters),
            "metrics": metrics,
        })
    document: dict[str, object] = {
        "schema_version": REGIME_SCHEMA,
        "definition": {"id": regime["definition"], "parameters": parameters},
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "lookback_sessions": 60,
        "source": {
            "ready_input_sha256": ready_input_sha256,
            "benchmark_sha256": content_sha256(benchmark_rows),
        },
        "rows": rows,
        "counts": {
            state: sum(row["state"] == state for row in rows)
            for state in sorted(REGIME_STATES)
        },
    }
    document["content_sha256"] = content_sha256(document)
    return document


def validate_regime_snapshot(document: object) -> dict[str, object]:
    if not isinstance(document, dict) or document.get("schema_version") != REGIME_SCHEMA:
        raise ValueError("regime snapshot schema is unsupported")
    _verify_hash(document, "regime snapshot")
    if document.get("benchmark_symbol") != BENCHMARK_SYMBOL:
        raise ValueError("regime snapshot benchmark is unsupported")
    rows = document.get("rows")
    if not isinstance(rows, list) or len(rows) > 2500:
        raise ValueError("regime snapshot rows are invalid")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) not in (
            {"session", "as_of", "state", "reason"},
            {"session", "as_of", "state", "metrics"},
        ):
            raise ValueError("regime snapshot row contract is invalid")
        session = row.get("session")
        if not isinstance(session, str) or row.get("as_of") != session or session in seen:
            raise ValueError("regime snapshot row identity is invalid")
        seen.add(session)
        state = row.get("state")
        if state not in REGIME_STATES:
            raise ValueError("regime snapshot state is invalid")
        if state == "unknown" and row.get("reason") not in {"benchmark_missing", "warmup_incomplete"}:
            raise ValueError("unknown regime state requires a safe reason")
        if state != "unknown":
            metrics = row.get("metrics")
            if not isinstance(metrics, dict) or set(metrics) != {
                "return_20", "return_60", "volatility_20", "ma_distance_60",
            } or any(
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))
                for value in metrics.values()
            ):
                raise ValueError("regime snapshot metrics are invalid")
    return document


def validate_model_bundle(document: object) -> dict[str, object]:
    if not isinstance(document, dict) or document.get("schema_version") != BUNDLE_SCHEMA:
        raise ValueError("model bundle schema is unsupported")
    _verify_hash(document, "model bundle")
    experts = document.get("experts")
    routing = document.get("routing_policy")
    if not isinstance(experts, list) or not 2 <= len(experts) <= 4 or not isinstance(routing, dict):
        raise ValueError("model bundle expert map is invalid")
    keys: set[str] = set()
    for expert in experts:
        if not isinstance(expert, dict) or set(expert) != {
            "key", "training_regimes", "model_artifact_id", "model_content_sha256",
            "learner_profile", "folds_sha256",
        }:
            raise ValueError("model bundle expert entry is invalid")
        key = expert.get("key")
        if key not in EXPERT_KEYS or key in keys:
            raise ValueError("model bundle expert key is invalid")
        keys.add(str(key))
    if routing.get("id") != ROUTING_POLICY or routing.get("fallback") not in keys:
        raise ValueError("model bundle fallback is invalid")
    return document


def expert_key_for(regime_state: str, bundle: dict[str, object]) -> str:
    validate_model_bundle(bundle)
    keys = {str(item["key"]) for item in bundle["experts"]}
    if regime_state in keys:
        return regime_state
    return str(bundle["routing_policy"]["fallback"])
