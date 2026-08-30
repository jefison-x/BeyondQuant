"""BYQ-owned deterministic backtest input, execution, and job contracts.

This module deliberately accepts a frozen signal snapshot instead of executing
strategy source.  Strategy source is validated and authorized in Phase 11;
running generated Python belongs to a future, separately isolated execution
boundary.  The Phase 12 worker therefore has a small, auditable input surface:
bars, signals, a frozen universe, and explicit execution rules.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, execute, fetch_one


BACKTEST_SCHEMA_VERSION = "backtest-input-v1"
ENGINE_CONTRACT_VERSION = "native-a-share-v1"
RESULT_SCHEMA_VERSION = "backtest-result-v1"
MAX_BARS = 50_000
MAX_SIGNALS = 50_000
MAX_ACTIONS = 10_000
MAX_BENCHMARK_BARS = 5_000
MAX_RESULT_BYTES = 32 * 1024 * 1024
SIGNAL_SNAPSHOT_SCHEMA_VERSION = "signal-snapshot-v1"
MAX_SNAPSHOT_BYTES = MAX_RESULT_BYTES
MAX_LOG_ENTRIES = 500
JOB_ID_PATTERN = re.compile(r"^backtest_[0-9a-f]{32}$")
SYMBOL_PATTERN = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
INDEX_SYMBOL_PATTERN = re.compile(r"^[0-9A-Z]{6,12}\.(?:SH|SZ|CSI)$")
DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
TRACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class BacktestError(RuntimeError):
    """Base class for safe BYQ backtest-domain failures."""


class BacktestNotFound(BacktestError):
    pass


class BacktestConflict(BacktestError):
    pass


class BacktestStorageError(BacktestError):
    pass


class BacktestResourceExceeded(BacktestError):
    pass


class ObjectIntegrityError(BacktestError):
    pass


def _canonical(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("backtest input must be finite JSON") from error


def _sha256(value: bytes | str) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def _text(value: object, *, field: str, max_length: int = 256) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _entity_id(value: object, *, field: str, prefix: str) -> str:
    normalized = _text(value, field=field, max_length=64)
    if re.fullmatch(rf"{re.escape(prefix)}_[0-9a-f]{{32}}", normalized) is None:
        raise ValueError(f"{field} is not a valid BYQ {prefix} identifier")
    return normalized


def _trace_id(value: object) -> str:
    normalized = _text(value, field="trace_id", max_length=64)
    if TRACE_PATTERN.fullmatch(normalized) is None:
        raise ValueError("trace_id is not a valid BYQ identifier")
    return normalized


def _idempotency_key(value: object) -> str:
    return _text(value, field="idempotency_key", max_length=128)


def _date(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be YYYY-MM-DD")
    normalized = value.strip()
    if re.fullmatch(r"[0-9]{8}", normalized):
        normalized = f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:]}"
    if DATE_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field} must be YYYY-MM-DD")
    try:
        datetime.strptime(normalized, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError(f"{field} is not a real calendar date") from error
    return normalized


def _number(value: object, *, field: str, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{field} must be finite{' and positive' if positive else ''}")
    return result


def _integer(value: object, *, field: str, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        bound = f" between {minimum} and {maximum}" if maximum is not None else f" at least {minimum}"
        raise ValueError(f"{field} must be{bound}")
    return value


def _reject_unknown(payload: dict[str, object], allowed: set[str], *, field: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"{field} has unknown fields: {', '.join(unknown)}")


_SECRET_FRAGMENTS = (
    "token",
    "password",
    "secret",
    "apikey",
    "accesskey",
    "privatekey",
    "credential",
    "authorization",
)


def _reject_secret_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            if any(fragment in normalized for fragment in _SECRET_FRAGMENTS):
                raise ValueError("backtest input must not contain credential fields")
            _reject_secret_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_secret_keys(nested)


def normalize_symbol(value: object, *, field: str = "symbol") -> str:
    normalized = _text(value, field=field, max_length=16).upper()
    if SYMBOL_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field} must be a canonical A-share symbol")
    return normalized


def membership_fingerprint(symbols: Iterable[str]) -> str:
    return _sha256(_canonical(sorted(set(symbols))))


def _normalize_universe(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("universe must be an object")
    _reject_unknown(value, {"universe_id", "version_id", "membership_fingerprint", "symbols"}, field="universe")
    universe_id = _text(value.get("universe_id", "frozen-universe"), field="universe.universe_id", max_length=128)
    version_id = _text(value.get("version_id"), field="universe.version_id", max_length=128)
    supplied_fingerprint = _text(
        value.get("membership_fingerprint"),
        field="universe.membership_fingerprint",
        max_length=64,
    )
    if re.fullmatch(r"[a-f0-9]{64}", supplied_fingerprint) is None:
        raise ValueError("universe.membership_fingerprint must be SHA-256")
    symbols = value.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("universe.symbols must be a non-empty list")
    normalized = sorted({normalize_symbol(item, field="universe.symbol") for item in symbols})
    if supplied_fingerprint != membership_fingerprint(normalized):
        raise ValueError("universe membership fingerprint does not match symbols")
    return {
        "universe_id": universe_id,
        "version_id": version_id,
        "membership_fingerprint": supplied_fingerprint,
        "symbols": normalized,
    }


def _normalize_bars(value: object, universe_symbols: set[str]) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise ValueError("bars must be a non-empty list")
    if len(value) > MAX_BARS:
        raise BacktestResourceExceeded(f"bars exceeds {MAX_BARS} rows")
    allowed = {
        "symbol", "trade_date", "open", "high", "low", "close", "volume", "prev_close",
        "is_suspended", "suspended", "status", "up_limit", "down_limit",
    }
    normalized: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"bars[{index}] must be an object")
        _reject_unknown(item, allowed, field=f"bars[{index}]")
        symbol = normalize_symbol(item.get("symbol"), field=f"bars[{index}].symbol")
        if symbol not in universe_symbols:
            raise ValueError(f"bar symbol {symbol} is outside frozen universe")
        trade_date = _date(item.get("trade_date"), field=f"bars[{index}].trade_date")
        key = (symbol, trade_date)
        if key in seen:
            raise ValueError(f"duplicate bar for {symbol} on {trade_date}")
        seen.add(key)
        prices = {
            name: _number(item.get(name), field=f"bars[{index}].{name}", positive=True)
            for name in ("open", "high", "low", "close")
        }
        if prices["high"] < max(prices["open"], prices["close"], prices["low"]):
            raise ValueError(f"bars[{index}] high violates OHLC envelope")
        if prices["low"] > min(prices["open"], prices["close"], prices["high"]):
            raise ValueError(f"bars[{index}] low violates OHLC envelope")
        status = item.get("status")
        if status is not None and status not in {"trading", "suspended"}:
            raise ValueError(f"bars[{index}].status must be trading or suspended")
        suspended = bool(item.get("is_suspended", item.get("suspended", False))) or status == "suspended"
        if not isinstance(item.get("is_suspended", item.get("suspended", False)), bool):
            raise ValueError(f"bars[{index}].suspended must be boolean")
        row: dict[str, object] = {
            "symbol": symbol,
            "trade_date": trade_date,
            **prices,
            "volume": _number(item.get("volume", 0), field=f"bars[{index}].volume"),
            "is_suspended": suspended,
        }
        for name in ("prev_close", "up_limit", "down_limit"):
            if name in item and item[name] is not None:
                row[name] = _number(item[name], field=f"bars[{index}].{name}", positive=True)
        normalized.append(row)
    normalized.sort(key=lambda row: (str(row["trade_date"]), str(row["symbol"])))
    by_symbol: dict[str, list[dict[str, object]]] = {}
    for row in normalized:
        by_symbol.setdefault(str(row["symbol"]), []).append(row)
    for rows in by_symbol.values():
        previous: float | None = None
        for row in rows:
            supplied = row.get("prev_close")
            if supplied is not None and previous is not None and not math.isclose(float(supplied), previous, rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError(f"{row['symbol']} {row['trade_date']} prev_close is inconsistent")
            if supplied is None and previous is not None:
                row["prev_close"] = previous
            previous = float(row["close"])
    return normalized


def _normalize_signals(value: object, universe_symbols: set[str], bar_dates: set[str]) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("signals must be a list")
    if len(value) > MAX_SIGNALS:
        raise BacktestResourceExceeded(f"signals exceeds {MAX_SIGNALS} rows")
    allowed = {"symbol", "trade_date", "side", "action", "signal", "quantity"}
    normalized: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"signals[{index}] must be an object")
        _reject_unknown(item, allowed, field=f"signals[{index}]")
        symbol = normalize_symbol(item.get("symbol"), field=f"signals[{index}].symbol")
        if symbol not in universe_symbols:
            raise ValueError(f"signal symbol {symbol} is outside frozen universe")
        trade_date = _date(item.get("trade_date"), field=f"signals[{index}].trade_date")
        if trade_date not in bar_dates:
            raise ValueError(f"signal date {trade_date} is not in the frozen trading input")
        key = (symbol, trade_date)
        if key in seen:
            raise ValueError(f"duplicate signal for {symbol} on {trade_date}")
        seen.add(key)
        raw = item.get("side", item.get("action", item.get("signal")))
        if raw in {"buy", "BUY", 1}:
            direction = 1
        elif raw in {"sell", "SELL", -1}:
            direction = -1
        elif raw in {None, 0, "hold", "HOLD"}:
            direction = 0
        else:
            raise ValueError(f"signals[{index}] side must be buy, sell, or hold")
        quantity = item.get("quantity")
        normalized_row: dict[str, object] = {"symbol": symbol, "trade_date": trade_date, "direction": direction}
        if quantity is not None:
            normalized_row["quantity"] = _integer(quantity, field=f"signals[{index}].quantity", minimum=1, maximum=10_000_000)
        normalized.append(normalized_row)
    return sorted(normalized, key=lambda row: (str(row["trade_date"]), str(row["symbol"])))


def _normalize_execution(value: object) -> dict[str, object]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("execution must be an object")
    allowed = {
        "initial_capital", "commission_rate", "stamp_tax_rate", "slippage_rate", "lot_size",
        "max_positions", "limit_threshold", "a_share_rules", "max_runtime_seconds", "max_attempts",
    }
    _reject_unknown(value, allowed, field="execution")
    initial_capital = _number(value.get("initial_capital", 100_000.0), field="execution.initial_capital", positive=True)
    rates = {
        name: _number(value.get(name, default), field=f"execution.{name}")
        for name, default in (("commission_rate", 0.0003), ("stamp_tax_rate", 0.001), ("slippage_rate", 0.0), ("limit_threshold", 0.10))
    }
    if any(rate < 0 or rate > 1 for rate in rates.values()):
        raise ValueError("execution rates must be between 0 and 1")
    a_share_rules = value.get("a_share_rules", True)
    if not isinstance(a_share_rules, bool):
        raise ValueError("execution.a_share_rules must be boolean")
    max_runtime_seconds = _number(
        value.get("max_runtime_seconds", 10.0),
        field="execution.max_runtime_seconds",
        positive=True,
    )
    if max_runtime_seconds > 300:
        raise ValueError("execution.max_runtime_seconds must not exceed 300 seconds")
    return {
        "initial_capital": initial_capital,
        **rates,
        "lot_size": _integer(value.get("lot_size", 100), field="execution.lot_size", minimum=1, maximum=100_000),
        "max_positions": _integer(value.get("max_positions", 10), field="execution.max_positions", minimum=1, maximum=10_000),
        "a_share_rules": a_share_rules,
        "max_runtime_seconds": max_runtime_seconds,
        "max_attempts": _integer(value.get("max_attempts", 2), field="execution.max_attempts", minimum=1, maximum=3),
    }


def normalize_execution_profile(value: object) -> dict[str, object]:
    """Public closed execution-profile normalizer for trusted signal producers."""
    return _normalize_execution(value)


def _normalize_actions(value: object, universe_symbols: set[str]) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("corporate_actions must be a list")
    if len(value) > MAX_ACTIONS:
        raise BacktestResourceExceeded(f"corporate_actions exceeds {MAX_ACTIONS} rows")
    allowed = {
        "symbol", "end_date", "announcement_date", "implementation_announcement_date",
        "record_date", "ex_date", "pay_date", "share_listing_date",
        "cash_dividend_per_share", "cash_dividend_gross", "share_ratio", "content_sha256",
    }
    normalized: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"corporate_actions[{index}] must be an object")
        _reject_unknown(item, allowed, field=f"corporate_actions[{index}]")
        symbol = normalize_symbol(item.get("symbol"), field=f"corporate_actions[{index}].symbol")
        if symbol not in universe_symbols:
            raise ValueError(f"corporate action symbol {symbol} is outside frozen universe")
        ex_date = _date(item.get("ex_date"), field=f"corporate_actions[{index}].ex_date")
        end_date = (
            _date(item["end_date"], field=f"corporate_actions[{index}].end_date")
            if item.get("end_date") else ""
        )
        key = (symbol, end_date, ex_date)
        if key in seen:
            raise ValueError(f"duplicate corporate action for {symbol} on {ex_date} and period {end_date or 'unspecified'}")
        seen.add(key)
        cash = _number(item.get("cash_dividend_per_share", 0), field=f"corporate_actions[{index}].cash_dividend_per_share")
        ratio = _number(item.get("share_ratio", 0), field=f"corporate_actions[{index}].share_ratio")
        if cash < 0 or ratio < 0 or ratio > 100:
            raise ValueError(f"corporate_actions[{index}] contains invalid non-negative values")
        normalized_row: dict[str, object] = {
            "symbol": symbol, "ex_date": ex_date,
            "cash_dividend_per_share": cash, "share_ratio": ratio,
        }
        if end_date:
            normalized_row["end_date"] = end_date
        for field in ("announcement_date", "implementation_announcement_date", "record_date", "pay_date", "share_listing_date"):
            if item.get(field):
                normalized_row[field] = _date(item[field], field=f"corporate_actions[{index}].{field}")
        if item.get("cash_dividend_gross") is not None:
            normalized_row["cash_dividend_gross"] = _number(
                item["cash_dividend_gross"], field=f"corporate_actions[{index}].cash_dividend_gross"
            )
        if item.get("content_sha256") is not None:
            normalized_row["content_sha256"] = _text(
                item["content_sha256"], field=f"corporate_actions[{index}].content_sha256", max_length=64
            )
        normalized.append(normalized_row)
    return sorted(normalized, key=lambda row: (str(row["ex_date"]), str(row["symbol"])))


def _normalize_benchmark(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_BENCHMARK_BARS:
        raise ValueError("benchmark must be a bounded list")
    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    symbol_seen: str | None = None
    allowed = {"symbol", "trade_date", "open", "high", "low", "close", "prev_close", "volume", "amount"}
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"benchmark[{index}] must be an object")
        _reject_unknown(item, allowed, field=f"benchmark[{index}]")
        symbol = _text(item.get("symbol"), field=f"benchmark[{index}].symbol", max_length=24).upper()
        if INDEX_SYMBOL_PATTERN.fullmatch(symbol) is None:
            raise ValueError("benchmark symbol has invalid format")
        if symbol_seen is not None and symbol != symbol_seen:
            raise ValueError("benchmark must contain exactly one index symbol")
        symbol_seen = symbol
        trade_date = _date(item.get("trade_date"), field=f"benchmark[{index}].trade_date")
        if trade_date in seen:
            raise ValueError("benchmark contains a duplicate date")
        seen.add(trade_date)
        prices = {
            field: _number(item.get(field), field=f"benchmark[{index}].{field}", positive=True)
            for field in ("open", "high", "low", "close")
        }
        if prices["high"] < max(prices.values()) or prices["low"] > min(prices.values()):
            raise ValueError("benchmark OHLC envelope is invalid")
        row: dict[str, object] = {
            "symbol": symbol, "trade_date": trade_date, **prices,
            "volume": _number(item.get("volume", 0), field=f"benchmark[{index}].volume"),
            "amount": _number(item.get("amount", 0), field=f"benchmark[{index}].amount"),
        }
        if item.get("prev_close") is not None:
            row["prev_close"] = _number(
                item["prev_close"], field=f"benchmark[{index}].prev_close", positive=True,
            )
        normalized.append(row)
    return sorted(normalized, key=lambda row: str(row["trade_date"]))


def normalize_backtest_request(payload: object, *, strategy_version_artifact_id: object, approval_artifact_id: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("backtest request must be an object")
    allowed = {
        "task_id", "experiment_id", "strategy_version_artifact_id", "approval_artifact_id",
        "trace_id", "idempotency_key", "universe", "bars", "signals", "execution", "corporate_actions", "benchmark",
    }
    _reject_unknown(payload, allowed, field="backtest request")
    task_id = _entity_id(payload.get("task_id"), field="task_id", prefix="task")
    experiment_id = payload.get("experiment_id")
    if experiment_id is not None:
        experiment_id = _entity_id(experiment_id, field="experiment_id", prefix="experiment")
    version_id = _entity_id(strategy_version_artifact_id, field="strategy_version_artifact_id", prefix="artifact")
    approval_id = _entity_id(approval_artifact_id, field="approval_artifact_id", prefix="artifact")
    trace_id = _trace_id(payload.get("trace_id"))
    idempotency_key = _idempotency_key(payload.get("idempotency_key"))
    universe = _normalize_universe(payload.get("universe"))
    symbols = set(universe["symbols"])
    bars = _normalize_bars(payload.get("bars"), symbols)
    bar_dates = {str(item["trade_date"]) for item in bars}
    signals = _normalize_signals(payload.get("signals", []), symbols, bar_dates)
    execution = _normalize_execution(payload.get("execution"))
    actions = _normalize_actions(payload.get("corporate_actions"), symbols)
    benchmark = _normalize_benchmark(payload.get("benchmark"))
    _reject_secret_keys({"universe": universe, "bars": bars, "signals": signals, "execution": execution, "corporate_actions": actions, "benchmark": benchmark})
    manifest = {
        "schema_version": BACKTEST_SCHEMA_VERSION,
        "strategy": {"strategy_version_artifact_id": version_id},
        "approval": {"approval_artifact_id": approval_id},
        "universe": universe,
        "bars": bars,
        "signals": signals,
        "corporate_actions": actions,
        "benchmark": benchmark,
        "execution": execution,
        "environment": {
            "engine": "native",
            "engine_contract_version": ENGINE_CONTRACT_VERSION,
            "reproducibility": "reproducible",
        },
    }
    manifest, input_manifest_id = build_manifest(
        strategy_version_artifact_id=version_id,
        approval_artifact_id=approval_id,
        universe=universe,
        bars=bars,
        signals=signals,
        corporate_actions=actions,
        benchmark=benchmark,
        execution=execution,
    )
    return {
        "task_id": task_id,
        "experiment_id": experiment_id,
        "strategy_version_artifact_id": version_id,
        "approval_artifact_id": approval_id,
        "trace_id": trace_id,
        "idempotency_key": idempotency_key,
        "manifest": manifest,
        "input_manifest_id": input_manifest_id,
    }


def build_manifest(
    *,
    strategy_version_artifact_id: str,
    approval_artifact_id: str,
    universe: dict[str, object],
    bars: list[dict[str, object]],
    signals: list[dict[str, object]],
    corporate_actions: list[dict[str, object]],
    execution: dict[str, object],
    benchmark: list[dict[str, object]] | None = None,
) -> tuple[dict[str, object], str]:
    """Build a backtest input manifest from already-normalized inputs.

    Used both by ``normalize_backtest_request`` (after inline normalization)
    and by the ADR-0017 signal_snapshot submit path, which consumes a
    validated snapshot's frozen, already-normalized inputs directly without
    re-normalizing them.
    """
    manifest = {
        "schema_version": BACKTEST_SCHEMA_VERSION,
        "strategy": {"strategy_version_artifact_id": strategy_version_artifact_id},
        "approval": {"approval_artifact_id": approval_artifact_id},
        "universe": universe,
        "bars": bars,
        "signals": signals,
        "corporate_actions": corporate_actions,
        "benchmark": benchmark or [],
        "execution": execution,
        "environment": {
            "engine": "native",
            "engine_contract_version": ENGINE_CONTRACT_VERSION,
            "reproducibility": "reproducible",
        },
    }
    encoded = _canonical(manifest)
    return manifest, _sha256(encoded)


def normalize_signal_snapshot(
    payload: object,
    *,
    strategy_version_artifact_id: object,
    strategy_version_id: object,
) -> dict[str, object]:
    """Normalize a frozen signal-snapshot artifact document (ADR-0017).

    Reuses the same bar/signal/universe/execution/action normalization as
    backtest requests so the snapshot can later feed the backtest input
    boundary without double validation. Returns a secret-free, immutable,
    content-addressed document body; the caller owns artifact idempotency and
    status.
    """
    if not isinstance(payload, dict):
        raise ValueError("signal snapshot must be an object")
    allowed = {"universe", "bars", "signals", "execution", "corporate_actions", "benchmark", "source"}
    _reject_unknown(payload, allowed, field="signal snapshot")
    version_artifact = _entity_id(
        strategy_version_artifact_id, field="strategy_version_artifact_id", prefix="artifact"
    )
    version_id = _text(strategy_version_id, field="strategy_version_id", max_length=128)
    universe = _normalize_universe(payload.get("universe"))
    symbols = set(universe["symbols"])
    bars = _normalize_bars(payload.get("bars"), symbols)
    bar_dates = {str(item["trade_date"]) for item in bars}
    signals = _normalize_signals(payload.get("signals", []), symbols, bar_dates)
    execution = _normalize_execution(payload.get("execution"))
    actions = _normalize_actions(payload.get("corporate_actions"), symbols)
    benchmark = _normalize_benchmark(payload.get("benchmark"))
    _reject_secret_keys(
        {
            "universe": universe,
            "bars": bars,
            "signals": signals,
            "execution": execution,
            "corporate_actions": actions,
            "benchmark": benchmark,
        }
    )
    source = payload.get("source")
    if source is None:
        source = {}
    if not isinstance(source, dict):
        raise ValueError("signal snapshot source must be an object")
    _reject_unknown(
        source, {"producer", "note", "data_readiness", "ml_lineage"},
        field="signal snapshot source",
    )
    producer = _text(source.get("producer", "keyless-import"), field="source.producer", max_length=64)
    data_readiness = source.get("data_readiness", {})
    if not isinstance(data_readiness, dict):
        raise ValueError("source.data_readiness must be an object")
    _reject_unknown(data_readiness, {
        "requirement_sha256", "ready_input_sha256", "research_view_sha256",
    }, field="source.data_readiness")
    normalized_readiness = {}
    for key, value in data_readiness.items():
        normalized_readiness[key] = _text(value, field=f"source.data_readiness.{key}", max_length=64)
    ml_lineage = source.get("ml_lineage")
    normalized_ml_lineage: dict[str, str] = {}
    if ml_lineage is not None:
        if not isinstance(ml_lineage, dict):
            raise ValueError("source.ml_lineage must be an object")
        allowed_ml_lineage = {
            "ml_strategy_artifact_id", "ml_strategy_approval_artifact_id", "model_artifact_id",
            "feature_snapshot_artifact_id", "prediction_snapshot_artifact_id",
            "stock_pool_snapshot_id", "policy_sha256",
        }
        _reject_unknown(ml_lineage, allowed_ml_lineage, field="source.ml_lineage")
        if set(ml_lineage) != allowed_ml_lineage:
            raise ValueError("source.ml_lineage is incomplete")
        for key in sorted(allowed_ml_lineage):
            normalized_ml_lineage[key] = _text(
                ml_lineage[key], field=f"source.ml_lineage.{key}", max_length=128
            )
    document = {
        "schema_version": SIGNAL_SNAPSHOT_SCHEMA_VERSION,
        "strategy": {
            "strategy_version_artifact_id": version_artifact,
            "strategy_version_id": version_id,
        },
        "universe": universe,
        "bars": bars,
        "signals": signals,
        "corporate_actions": actions,
        "benchmark": benchmark,
        "execution": execution,
        "source": {
            "producer": producer,
            **({"data_readiness": normalized_readiness} if normalized_readiness else {}),
            **({"ml_lineage": normalized_ml_lineage} if normalized_ml_lineage else {}),
        },
    }
    encoded = _canonical(document)
    if len(encoded.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise BacktestResourceExceeded("signal snapshot exceeds object size limit")
    document["source"]["content_sha256"] = _sha256(encoded)
    return document


def signal_snapshot_content_sha256(document: dict[str, object]) -> str:
    """Return the content-addressed fingerprint of a normalized snapshot."""
    encoded = _canonical(document)
    return _sha256(encoded)


def _money(value: float) -> float:
    return round(float(value), 10)


def _limit_state(bar: dict[str, object], threshold: float) -> str | None:
    previous = bar.get("prev_close")
    if previous is None:
        return None
    up = float(bar.get("up_limit", round(float(previous) * (1 + threshold), 2)))
    down = float(bar.get("down_limit", round(float(previous) * (1 - threshold), 2)))
    price = float(bar["open"])
    if price >= up - 1e-8:
        return "limit_up"
    if price <= down + 1e-8:
        return "limit_down"
    return None


def run_native_backtest(manifest: dict[str, object]) -> dict[str, object]:
    """Run the deterministic signal-snapshot engine.

    Signals observed on a session are executed at the next available session's
    open.  All orders are processed in symbol order, sells before buys, and
    every rejected trade emits a stable reason code.
    """
    if manifest.get("schema_version") != BACKTEST_SCHEMA_VERSION:
        raise ValueError("unsupported backtest input manifest")
    started = time.monotonic()
    execution = manifest["execution"]
    if not isinstance(execution, dict):
        raise ValueError("backtest execution manifest is invalid")
    max_runtime = float(execution["max_runtime_seconds"])
    bars = manifest.get("bars")
    signals = manifest.get("signals")
    actions = manifest.get("corporate_actions")
    benchmark = manifest.get("benchmark", [])
    if (
        not isinstance(bars, list) or not isinstance(signals, list)
        or not isinstance(actions, list) or not isinstance(benchmark, list)
    ):
        raise ValueError("backtest input manifest is incomplete")
    by_date: dict[str, dict[str, dict[str, object]]] = {}
    for row in bars:
        by_date.setdefault(str(row["trade_date"]), {})[str(row["symbol"])] = row
    dates = sorted(by_date)
    signal_by_date: dict[str, list[dict[str, object]]] = {}
    for row in signals:
        if int(row["direction"]) != 0:
            signal_by_date.setdefault(str(row["trade_date"]), []).append(row)
    for rows in signal_by_date.values():
        rows.sort(key=lambda row: str(row["symbol"]))
    actions_by_date: dict[str, list[dict[str, object]]] = {}
    for action in actions:
        actions_by_date.setdefault(str(action["ex_date"]), []).append(action)
    for rows in actions_by_date.values():
        rows.sort(key=lambda row: str(row["symbol"]))

    cash = float(execution["initial_capital"])
    initial = cash
    positions: dict[str, list[dict[str, object]]] = {}
    trades: list[dict[str, object]] = []
    blocked: list[dict[str, object]] = []
    corporate_events: list[dict[str, object]] = []
    pending_entitlements: list[dict[str, object]] = []
    equity_curve: list[dict[str, object]] = []
    daily_positions: list[dict[str, object]] = []
    daily_returns: list[dict[str, object]] = []
    logs: list[dict[str, object]] = []
    log_truncated = False
    log_counter = 0

    def log(level: str, message: str, **fields: object) -> None:
        nonlocal log_counter, log_truncated
        log_counter += 1
        if len(logs) >= MAX_LOG_ENTRIES:
            log_truncated = True
            return
        entry: dict[str, object] = {"seq": log_counter, "level": level, "message": message}
        entry.update({key: value for key, value in fields.items() if value is not None})
        logs.append(entry)

    lot_size = int(execution["lot_size"])
    a_share_rules = bool(execution["a_share_rules"])
    threshold = float(execution["limit_threshold"])

    def block(symbol: str, trade_date: str, side: str, reason_code: str, detail: str) -> None:
        blocked.append({"symbol": symbol, "trade_date": trade_date, "side": side, "reason_code": reason_code, "detail": detail})
        log("warn", "order_blocked", symbol=symbol, trade_date=trade_date, side=side, reason_code=reason_code)

    def available(symbol: str, current_date: str) -> int:
        lots = positions.get(symbol, [])
        if not a_share_rules:
            return sum(int(lot["quantity"]) for lot in lots)
        return sum(int(lot["quantity"]) for lot in lots if str(lot["entry_date"]) < current_date)

    def apply_actions(current_date: str) -> None:
        for action in actions_by_date.get(current_date, []):
            symbol = str(action["symbol"])
            lots = positions.get(symbol, [])
            if not lots:
                continue
            old_quantity = sum(int(lot["quantity"]) for lot in lots)
            cash_dividend = old_quantity * float(action["cash_dividend_per_share"])
            share_quantity = int(round(old_quantity * float(action["share_ratio"])))
            entitlement = {
                "symbol": symbol,
                "ex_date": current_date,
                "old_quantity": old_quantity,
                "new_quantity": old_quantity + share_quantity,
                "cash_dividend": _money(cash_dividend),
                "share_quantity": share_quantity,
                "pay_date": str(action.get("pay_date") or current_date),
                "share_listing_date": str(action.get("share_listing_date") or current_date),
                "cash_settled": cash_dividend <= 0,
                "shares_settled": share_quantity <= 0,
            }
            pending_entitlements.append(entitlement)
            corporate_events.append(entitlement)
            log("info", "corporate_action_entitlement", symbol=symbol, ex_date=current_date,
                cash_dividend=_money(cash_dividend), share_quantity=share_quantity)

    def settle_actions(current_date: str) -> None:
        for entitlement in pending_entitlements:
            symbol = str(entitlement["symbol"])
            if not entitlement["cash_settled"] and current_date >= str(entitlement["pay_date"]):
                cash_nonlocal[0] += float(entitlement["cash_dividend"])
                entitlement["cash_settled"] = True
                log("info", "cash_dividend_settled", symbol=symbol, trade_date=current_date,
                    cash_dividend=entitlement["cash_dividend"])
            if not entitlement["shares_settled"] and current_date >= str(entitlement["share_listing_date"]):
                quantity = int(entitlement["share_quantity"])
                lots = positions.get(symbol, [])
                current_quantity = sum(int(lot["quantity"]) for lot in lots)
                if lots and current_quantity > 0:
                    remaining = quantity
                    for position_index, lot in enumerate(lots):
                        if position_index == len(lots) - 1:
                            addition = remaining
                        else:
                            addition = int(round(quantity * int(lot["quantity"]) / current_quantity))
                            remaining -= addition
                        old_lot_quantity = int(lot["quantity"])
                        lot["quantity"] = old_lot_quantity + addition
                        if int(lot["quantity"]) > 0:
                            lot["cost_per_share"] = float(lot["cost_per_share"]) * old_lot_quantity / int(lot["quantity"])
                entitlement["shares_settled"] = True
                log("info", "stock_dividend_settled", symbol=symbol, trade_date=current_date,
                    share_quantity=quantity)

    # A mutable cell keeps the nested corporate-action function explicit and
    # avoids hidden global state in the worker.
    cash_nonlocal = [cash]
    log("info", "backtest_started", engine="native", schema_version=str(manifest.get("schema_version")))
    for index, current_date in enumerate(dates):
        if time.monotonic() - started > max_runtime:
            raise BacktestResourceExceeded("backtest exceeded its wall-clock limit")
        cash = cash_nonlocal[0]
        apply_actions(current_date)
        settle_actions(current_date)
        cash = cash_nonlocal[0]
        orders = signal_by_date.get(dates[index - 1], []) if index > 0 else []
        for side_direction in (-1, 1):
            for signal in orders:
                if int(signal["direction"]) != side_direction:
                    continue
                symbol = str(signal["symbol"])
                bar = by_date[current_date].get(symbol)
                side = "sell" if side_direction < 0 else "buy"
                if bar is None:
                    block(symbol, current_date, side, "missing_execution_bar", "no frozen bar for execution session")
                    continue
                if a_share_rules and bool(bar.get("is_suspended", False)):
                    block(symbol, current_date, side, "suspended", "execution bar is suspended")
                    continue
                limit_state = _limit_state(bar, threshold) if a_share_rules else None
                if (side == "buy" and limit_state == "limit_up") or (side == "sell" and limit_state == "limit_down"):
                    block(symbol, current_date, side, limit_state, "A-share price limit blocks this order")
                    continue
                requested = int(signal.get("quantity", lot_size))
                if a_share_rules:
                    requested = requested // lot_size * lot_size
                if requested <= 0:
                    block(symbol, current_date, side, "lot_size", "quantity is below the minimum lot")
                    continue
                open_price = float(bar["open"])
                slippage = float(execution["slippage_rate"])
                execution_price = open_price * (1 + slippage) if side == "buy" else open_price * (1 - slippage)
                commission_rate = float(execution["commission_rate"])
                tax_rate = float(execution["stamp_tax_rate"]) if side == "sell" else 0.0
                if side == "sell":
                    sellable = available(symbol, current_date)
                    if sellable <= 0:
                        block(symbol, current_date, side, "t_plus_one", "no prior-session lot is sellable")
                        continue
                    quantity = min(requested, sellable)
                    if a_share_rules:
                        quantity = quantity // lot_size * lot_size
                    if quantity <= 0:
                        block(symbol, current_date, side, "lot_size", "sellable quantity is below the minimum lot")
                        continue
                    amount = execution_price * quantity
                    commission = amount * commission_rate
                    tax = amount * tax_rate
                    realized = 0.0
                    remaining = quantity
                    new_lots: list[dict[str, object]] = []
                    for lot in positions.get(symbol, []):
                        lot_quantity = int(lot["quantity"])
                        sell_from_lot = min(lot_quantity, remaining) if (not a_share_rules or str(lot["entry_date"]) < current_date) else 0
                        if sell_from_lot:
                            realized += (execution_price - float(lot["cost_per_share"])) * sell_from_lot
                            lot_quantity -= sell_from_lot
                            remaining -= sell_from_lot
                        if lot_quantity:
                            retained = dict(lot)
                            retained["quantity"] = lot_quantity
                            new_lots.append(retained)
                    positions[symbol] = new_lots
                    cash += amount - commission - tax
                    trade = {
                        "symbol": symbol, "order_type": "sell", "timestamp": current_date,
                        "price": _money(execution_price), "quantity": quantity, "amount": _money(amount),
                        "commission": _money(commission), "tax": _money(tax),
                        "realized_pnl": _money(realized - commission - tax),
                    }
                    trades.append(trade)
                    log("info", "order_filled", symbol=symbol, side="sell", quantity=quantity, price=_money(execution_price))
                    if quantity < requested:
                        block(symbol, current_date, side, "t_plus_one_partial", "same-session lots remain unavailable")
                else:
                    if symbol not in positions and len([key for key, value in positions.items() if sum(int(lot["quantity"]) for lot in value) > 0]) >= int(execution["max_positions"]):
                        block(symbol, current_date, side, "max_positions", "maximum active positions reached")
                        continue
                    amount = execution_price * requested
                    commission = amount * commission_rate
                    if cash + 1e-9 < amount + commission:
                        block(symbol, current_date, side, "insufficient_capital", "cash cannot fund the requested lot")
                        continue
                    cash -= amount + commission
                    positions.setdefault(symbol, []).append({
                        "entry_date": current_date,
                        "quantity": requested,
                        "cost_per_share": (amount + commission) / requested,
                    })
                    trades.append({
                        "symbol": symbol, "order_type": "buy", "timestamp": current_date,
                        "price": _money(execution_price), "quantity": requested, "amount": _money(amount),
                        "commission": _money(commission), "tax": 0.0, "realized_pnl": None,
                    })
                    log("info", "order_filled", symbol=symbol, side="buy", quantity=requested, price=_money(execution_price))
        cash_nonlocal[0] = cash
        equity = cash
        position_count = 0
        for symbol, lots in positions.items():
            quantity = sum(int(lot["quantity"]) for lot in lots)
            if quantity <= 0:
                continue
            position_count += 1
            valuation_bar = by_date[current_date].get(symbol)
            if valuation_bar is not None:
                equity += quantity * float(valuation_bar["close"])
        # Rights already established on the ex-date remain economic assets even
        # before the provider-declared payment/listing date. This avoids a false
        # drawdown while keeping settlement cash and shares out of tradable lots.
        for entitlement in pending_entitlements:
            if not entitlement["cash_settled"]:
                equity += float(entitlement["cash_dividend"])
            if not entitlement["shares_settled"]:
                valuation_bar = by_date[current_date].get(str(entitlement["symbol"]))
                if valuation_bar is not None:
                    equity += int(entitlement["share_quantity"]) * float(valuation_bar["close"])
        equity_curve.append({"trade_date": current_date, "equity": _money(equity), "cash": _money(cash), "positions_count": position_count})
        daily_positions.append({
            "trade_date": current_date,
            "positions": [
                {
                    "symbol": symbol,
                    "quantity": sum(int(lot["quantity"]) for lot in lots),
                    "entry_date": str(lots[0]["entry_date"]) if lots else None,
                    "cost_per_share": _money(float(lots[0]["cost_per_share"])) if lots else None,
                }
                for symbol, lots in positions.items()
                if sum(int(lot["quantity"]) for lot in lots) > 0
            ],
        })
        previous_equity = float(equity_curve[-2]["equity"]) if len(equity_curve) > 1 else initial
        daily_returns.append({
            "trade_date": current_date,
            "daily_return": _money(equity / previous_equity - 1) if previous_equity else 0.0,
        })
        log("info", "session_processed", trade_date=current_date, cash=_money(cash), equity=_money(equity), positions_count=position_count)

    values = [float(row["equity"]) for row in equity_curve]
    peak = initial
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, (peak - value) / peak if peak else 0.0)
    final_value = values[-1] if values else initial
    benchmark_symbol = str(benchmark[0]["symbol"]) if benchmark else None
    benchmark_by_date = {str(row["trade_date"]): float(row["close"]) for row in benchmark}
    benchmark_curve: list[dict[str, object]] = []
    benchmark_base = next((benchmark_by_date[date] for date in dates if date in benchmark_by_date), None)
    if benchmark_base is not None:
        for date in dates:
            if date in benchmark_by_date:
                benchmark_curve.append({
                    "trade_date": date,
                    "value": _money(initial * benchmark_by_date[date] / benchmark_base),
                    "close": _money(benchmark_by_date[date]),
                })
    benchmark_return = (
        _money(benchmark_curve[-1]["value"] / initial - 1) if benchmark_curve else None
    )
    total_return = _money(final_value / initial - 1)
    excess_return = _money(total_return - benchmark_return) if benchmark_return is not None else None
    log("info", "backtest_completed", final_value=_money(final_value), total_return=_money(final_value / initial - 1), max_drawdown=_money(max_drawdown), trade_count=len(trades))
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "engine": "native",
        "engine_contract_version": ENGINE_CONTRACT_VERSION,
        "final_value": _money(final_value),
        "total_return": total_return,
        "benchmark_symbol": benchmark_symbol,
        "benchmark_return": benchmark_return,
        "excess_return": excess_return,
        "benchmark_curve": benchmark_curve,
        "max_drawdown": _money(max_drawdown),
        "trade_count": len(trades),
        "blocked_trade_count": len(blocked),
        "trades": trades,
        "blocked_trades": blocked,
        "corporate_action_events": corporate_events,
        "equity_curve": equity_curve,
        "daily_positions": daily_positions,
        "daily_returns": daily_returns,
        "logs": logs,
        "log_truncated": log_truncated,
        "reproducibility": "reproducible",
    }


def _new_job_id() -> str:
    return f"backtest_{uuid.uuid4().hex}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BacktestJobStore(PgStoreMixin):
    """Durable BYQ job state with strict same-key/different-input conflicts (ADR-0016 PG)."""

    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS backtest_jobs (
            job_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            experiment_id TEXT,
            owner_principal TEXT NOT NULL,
            status TEXT NOT NULL,
            request_json JSONB NOT NULL,
            request_hash TEXT NOT NULL,
            input_manifest_id TEXT NOT NULL,
            input_manifest_json JSONB NOT NULL,
            strategy_version_artifact_id TEXT NOT NULL,
            approval_artifact_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            attempts INTEGER NOT NULL,
            max_attempts INTEGER NOT NULL,
            result_reference_json JSONB,
            result_artifact_id TEXT,
            summary_json JSONB,
            error_code TEXT,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS backtest_jobs_idempotency
            ON backtest_jobs(task_id, idempotency_key)
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as error:
            raise BacktestStorageError("backtest job storage is unavailable") from error

    @classmethod
    def from_env(cls) -> "BacktestJobStore":
        return cls()

    @staticmethod
    def _request_hash(request: dict[str, object]) -> str:
        return _sha256(_canonical({key: value for key, value in request.items() if key != "idempotency_key"}))

    def create(self, request: dict[str, object], *, owner_principal: str) -> dict[str, object]:
        manifest = request.get("manifest")
        if not isinstance(manifest, dict):
            raise ValueError("backtest request has no input manifest")
        owner = _text(owner_principal, field="owner_principal", max_length=128)
        max_attempts = _integer(manifest["execution"].get("max_attempts", 2) if isinstance(manifest.get("execution"), dict) else 2, field="max_attempts", minimum=1, maximum=3)
        request_hash = self._request_hash(request)
        existing = self._fetch_one(
            "SELECT * FROM backtest_jobs WHERE task_id = :task_id AND idempotency_key = :idempotency_key",
            {"task_id": request["task_id"], "idempotency_key": request["idempotency_key"]},
        )
        if existing is not None:
            if existing["request_hash"] != request_hash:
                raise BacktestConflict("backtest idempotency key was reused")
            return self._public(existing)
        now = _now()
        job_id = _new_job_id()
        self._execute(
            """INSERT INTO backtest_jobs
            (job_id, task_id, experiment_id, owner_principal, status, request_json,
             request_hash, input_manifest_id, input_manifest_json,
             strategy_version_artifact_id, approval_artifact_id, idempotency_key,
             attempts, max_attempts, created_at, updated_at)
            VALUES (:job_id, :task_id, :experiment_id, :owner_principal, 'queued', :request_json,
                    :request_hash, :input_manifest_id, :input_manifest_json,
                    :strategy_version_artifact_id, :approval_artifact_id, :idempotency_key,
                    0, :max_attempts, :created_at, :updated_at)""",
            {
                "job_id": job_id,
                "task_id": request["task_id"],
                "experiment_id": request.get("experiment_id"),
                "owner_principal": owner,
                "request_json": request,
                "request_hash": request_hash,
                "input_manifest_id": request["input_manifest_id"],
                "input_manifest_json": manifest,
                "strategy_version_artifact_id": request["strategy_version_artifact_id"],
                "approval_artifact_id": request["approval_artifact_id"],
                "idempotency_key": request["idempotency_key"],
                "max_attempts": max_attempts,
                "created_at": now,
                "updated_at": now,
            },
        )
        return self.get(job_id)

    def get(self, job_id: object) -> dict[str, object]:
        job_id = _text(job_id, field="job_id", max_length=64)
        if JOB_ID_PATTERN.fullmatch(job_id) is None:
            raise ValueError("job_id is not a valid backtest identifier")
        row = self._fetch_one("SELECT * FROM backtest_jobs WHERE job_id = :job_id", {"job_id": job_id})
        if row is None:
            raise BacktestNotFound("backtest job not found")
        return self._public(row)

    def list_backtests(self, *, owner_principal: str | None = None) -> dict[str, object]:
        if owner_principal:
            rows = self._execute(
                "SELECT * FROM backtest_jobs WHERE owner_principal = :owner_principal ORDER BY created_at DESC, job_id DESC LIMIT 200",
                {"owner_principal": owner_principal},
            )
        else:
            rows = self._execute("SELECT * FROM backtest_jobs ORDER BY created_at DESC, job_id DESC LIMIT 200")
        return {"backtests": [self._public(row) for row in rows]}

    def find_by_signal_snapshot(
        self, *, owner_principal: str, signal_snapshot_artifact_id: str
    ) -> dict[str, object] | None:
        """Resolve the job already created for a facade's frozen signal input."""
        row = self._fetch_one(
            """SELECT * FROM backtest_jobs
               WHERE owner_principal = :owner
                 AND request_json->>'signal_snapshot_artifact_id' = :snapshot
               ORDER BY created_at DESC, job_id DESC LIMIT 1""",
            {"owner": owner_principal, "snapshot": signal_snapshot_artifact_id},
        )
        return None if row is None else self._public(row)

    def count_by_strategy_versions(self, version_artifact_ids: Sequence[str]) -> dict[str, int]:
        """Return backtest job counts per strategy_version_artifact_id.

        Uses one grouped query so counts stay exact beyond the historical
        generic-artifact 200-row projection limit.
        """
        identities = [str(value) for value in dict.fromkeys(version_artifact_ids)]
        if not identities:
            return {}
        rows = self._execute(
            """SELECT strategy_version_artifact_id, COUNT(*) AS n FROM backtest_jobs
               WHERE strategy_version_artifact_id IN (
                   SELECT jsonb_array_elements_text(:version_ids)
               ) GROUP BY strategy_version_artifact_id""",
            {"version_ids": identities},
        )
        observed = {str(row["strategy_version_artifact_id"]): int(row["n"]) for row in rows}
        counts = {identity: observed.get(identity, 0) for identity in identities}
        return counts

    def all_result_references(self) -> list[dict[str, object]]:
        """Return every stored backtest result reference across all owners.

        Result objects are content-addressed and may be shared between jobs,
        so the deletion-GC live set must be queried across owner scopes.
        """
        rows = self._execute(
            "SELECT result_reference_json FROM backtest_jobs WHERE result_reference_json IS NOT NULL"
        )
        references: list[dict[str, object]] = []
        for row in rows:
            reference = row.get("result_reference_json")
            if isinstance(reference, dict):
                references.append(reference)
        return references

    def request(self, job_id: object) -> dict[str, object]:
        job_id = _text(job_id, field="job_id", max_length=64)
        row = self._fetch_one("SELECT request_json FROM backtest_jobs WHERE job_id = :job_id", {"job_id": job_id})
        if row is None:
            raise BacktestNotFound("backtest job not found")
        return row["request_json"]

    def claim(self, job_id: object) -> dict[str, object] | None:
        job_id = _text(job_id, field="job_id", max_length=64)
        now = _now()
        with self._transaction() as connection:
            row = fetch_one(connection, "SELECT status FROM backtest_jobs WHERE job_id = :job_id", {"job_id": job_id})
            if row is None:
                raise BacktestNotFound("backtest job not found")
            if row["status"] != "queued":
                return None
            execute(
                connection,
                "UPDATE backtest_jobs SET status = 'running', attempts = attempts + 1, updated_at = :updated_at, error_code = NULL, error_message = NULL WHERE job_id = :job_id",
                {"updated_at": now, "job_id": job_id},
            )
        return self.get(job_id)

    def complete(self, job_id: object, *, result_reference: dict[str, object], result_artifact_id: str, summary: dict[str, object]) -> dict[str, object]:
        job_id = _text(job_id, field="job_id", max_length=64)
        with self._transaction() as connection:
            row = fetch_one(connection, "SELECT status FROM backtest_jobs WHERE job_id = :job_id", {"job_id": job_id})
            if row is None:
                raise BacktestNotFound("backtest job not found")
            if row["status"] != "running":
                raise BacktestConflict("backtest job is not running")
            now = _now()
            execute(
                connection,
                """UPDATE backtest_jobs SET status = 'completed', result_reference_json = :result_reference,
                result_artifact_id = :result_artifact_id, summary_json = :summary,
                updated_at = :updated_at, finished_at = :finished_at
                WHERE job_id = :job_id""",
                {"result_reference": result_reference, "result_artifact_id": result_artifact_id, "summary": summary, "updated_at": now, "finished_at": now, "job_id": job_id},
            )
        return self.get(job_id)

    def retry_or_fail(self, job_id: object, *, error_code: str, error_message: str) -> dict[str, object]:
        job_id = _text(job_id, field="job_id", max_length=64)
        safe_message = _text(error_message, field="error_message", max_length=512)
        with self._transaction() as connection:
            row = fetch_one(connection, "SELECT status, attempts, max_attempts FROM backtest_jobs WHERE job_id = :job_id", {"job_id": job_id})
            if row is None:
                raise BacktestNotFound("backtest job not found")
            if row["status"] != "running":
                return self.get(job_id)
            terminal = int(row["attempts"]) >= int(row["max_attempts"])
            status = "failed" if terminal else "queued"
            now = _now()
            execute(
                connection,
                "UPDATE backtest_jobs SET status = :status, error_code = :error_code, error_message = :error_message, updated_at = :updated_at, finished_at = :finished_at WHERE job_id = :job_id",
                {"status": status, "error_code": _text(error_code, field="error_code", max_length=64), "error_message": safe_message, "updated_at": now, "finished_at": now if terminal else None, "job_id": job_id},
            )
        return self.get(job_id)

    def requeue_stale(self, *, older_than_seconds: int = 300) -> int:
        cutoff = datetime.now(timezone.utc).timestamp() - max(1, int(older_than_seconds))
        changed = 0
        with self._transaction() as connection:
            rows = execute(connection, "SELECT job_id, updated_at FROM backtest_jobs WHERE status = 'running'")
            for row in rows:
                try:
                    updated = datetime.fromisoformat(row["updated_at"]).timestamp()
                except ValueError:
                    updated = 0
                if updated < cutoff:
                    execute(
                        connection,
                        "UPDATE backtest_jobs SET status = 'queued', error_code = 'worker_restart', error_message = 'stale running job requeued', updated_at = :updated_at WHERE job_id = :job_id",
                        {"updated_at": _now(), "job_id": row["job_id"]},
                    )
                    changed += 1
        return changed

    def cancel(self, job_id: object) -> dict[str, object]:
        job_id = _text(job_id, field="job_id", max_length=64)
        with self._transaction() as connection:
            row = fetch_one(connection, "SELECT status FROM backtest_jobs WHERE job_id = :job_id", {"job_id": job_id})
            if row is None:
                raise BacktestNotFound("backtest job not found")
            if row["status"] in {"queued", "running"}:
                now = _now()
                execute(
                    connection,
                    "UPDATE backtest_jobs SET status = 'cancelled', error_code = 'cancelled', error_message = 'cancelled by owner', updated_at = :updated_at, finished_at = :finished_at WHERE job_id = :job_id",
                    {"updated_at": now, "finished_at": now, "job_id": job_id},
                )
        return self.get(job_id)

    def delete(self, job_id: object, *, owner_principal: str) -> dict[str, object]:
        job_id = _text(job_id, field="job_id", max_length=64)
        if JOB_ID_PATTERN.fullmatch(job_id) is None:
            raise ValueError("job_id is not a valid backtest identifier")
        if not owner_principal:
            raise BacktestConflict("backtest deletion requires an owner principal")
        with self._transaction() as connection:
            row = fetch_one(connection, "SELECT * FROM backtest_jobs WHERE job_id = :job_id", {"job_id": job_id})
            if row is None:
                raise BacktestNotFound("backtest job not found")
            if row["owner_principal"] != owner_principal:
                raise BacktestConflict("backtest deletion requires matching owner scope")
            if row["status"] in {"queued", "running"}:
                raise BacktestConflict("cannot delete an active backtest; cancel it first")
            deleted = self._public(row)
            execute(connection, "DELETE FROM backtest_jobs WHERE job_id = :job_id", {"job_id": job_id})
        return deleted

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, object]:
        result: dict[str, object] = {
            "job_id": row["job_id"], "task_id": row["task_id"], "experiment_id": row["experiment_id"],
            "owner_principal": row["owner_principal"], "status": row["status"],
            "input_manifest_id": row["input_manifest_id"], "strategy_version_artifact_id": row["strategy_version_artifact_id"],
            "approval_artifact_id": row["approval_artifact_id"], "attempts": row["attempts"], "max_attempts": row["max_attempts"],
            "result_artifact_id": row["result_artifact_id"], "error_code": row["error_code"], "error_message": row["error_message"],
            "created_at": row["created_at"], "updated_at": row["updated_at"], "finished_at": row["finished_at"],
            "input_manifest": row["input_manifest_json"],
        }
        if row["result_reference_json"]:
            result["result_reference"] = row["result_reference_json"]
        if row["summary_json"]:
            result["summary"] = row["summary_json"]
        return result


class LocalObjectStore:
    """Small immutable object store used by the worker result boundary."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "LocalObjectStore":
        return cls(os.getenv("BYQ_BACKTEST_OBJECT_ROOT", "/tmp/byq-backtest-objects"))

    def _path(self, namespace: str, object_id: str) -> Path:
        namespace = _text(namespace, field="namespace", max_length=64)
        object_id = _text(object_id, field="object_id", max_length=128)
        if re.fullmatch(r"[A-Za-z0-9_-]+", namespace) is None or re.fullmatch(r"[a-f0-9]{64}", object_id) is None:
            raise ObjectIntegrityError("object reference contains an unsafe path")
        return self.root / namespace / object_id

    def put(self, namespace: str, payload: bytes, *, media_type: str) -> dict[str, object]:
        if len(payload) > MAX_RESULT_BYTES:
            raise BacktestResourceExceeded("backtest result exceeds object size limit")
        object_id = _sha256(payload)
        path = self._path(namespace, object_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            fd, temporary = tempfile.mkstemp(prefix=".byq-", dir=str(path.parent))
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(payload)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return {"namespace": namespace, "object_id": object_id, "media_type": _text(media_type, field="media_type", max_length=128), "size": len(payload), "sha256": object_id}

    def get(self, reference: dict[str, object]) -> bytes:
        namespace = reference.get("namespace")
        object_id = reference.get("object_id")
        expected_hash = reference.get("sha256")
        if not isinstance(expected_hash, str) or expected_hash != object_id:
            raise ObjectIntegrityError("object reference hash is invalid")
        path = self._path(namespace, object_id)  # type: ignore[arg-type]
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise ObjectIntegrityError("backtest result object is unavailable") from error
        if _sha256(payload) != expected_hash or len(payload) != int(reference.get("size", -1)):
            raise ObjectIntegrityError("backtest result object failed integrity check")
        return payload

    def exists(self, reference: dict[str, object]) -> bool:
        try:
            return self._path(reference.get("namespace"), reference.get("object_id")).is_file()  # type: ignore[arg-type]
        except (BacktestError, ValueError):
            return False

    def delete_if_unreferenced(
        self,
        reference: dict[str, object],
        *,
        live_references: Iterable[dict[str, object]],
        actor_scope: str,
        owner_scope: str,
    ) -> bool:
        if not actor_scope or actor_scope != owner_scope:
            raise BacktestConflict("object deletion requires matching owner scope")
        candidate = (reference.get("namespace"), reference.get("object_id"))
        if any((item.get("namespace"), item.get("object_id")) == candidate for item in live_references):
            return False
        path = self._path(reference.get("namespace"), reference.get("object_id"))  # type: ignore[arg-type]
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True


class BacktestWorker:
    """Claim and execute one bounded signal-snapshot job."""

    def __init__(self, jobs: BacktestJobStore, research_store: Any, objects: LocalObjectStore) -> None:
        self.jobs = jobs
        self.research_store = research_store
        self.objects = objects

    def run_once(self, job_id: object) -> dict[str, object]:
        claimed = self.jobs.claim(job_id)
        if claimed is None:
            return self.jobs.get(job_id)
        job = self.jobs.get(job_id)
        try:
            request = self.jobs.request(job_id)
            manifest = request["manifest"]
            if not isinstance(manifest, dict):
                raise ValueError("stored backtest input manifest is invalid")
            result = run_native_backtest(manifest)
            result["job_id"] = job["job_id"]
            result["input_manifest_id"] = job["input_manifest_id"]
            result["strategy_version_artifact_id"] = job["strategy_version_artifact_id"]
            result["approval_artifact_id"] = job["approval_artifact_id"]
            payload = _canonical(result).encode("utf-8")
            reference = self.objects.put("backtest-results", payload, media_type="application/json")
            summary = {
                "final_value": result["final_value"], "total_return": result["total_return"],
                "max_drawdown": result["max_drawdown"], "trade_count": result["trade_count"],
                "blocked_trade_count": result["blocked_trade_count"], "reproducibility": result["reproducibility"],
                "benchmark_symbol": result["benchmark_symbol"],
                "benchmark_return": result["benchmark_return"],
                "excess_return": result["excess_return"],
            }
            artifact_content = {
                "schema_version": "backtest-result-artifact-v1",
                "job_id": job["job_id"],
                "input_manifest_id": job["input_manifest_id"],
                "strategy_version_artifact_id": job["strategy_version_artifact_id"],
                "approval_artifact_id": job["approval_artifact_id"],
                "result_reference": reference,
                "summary": summary,
                "execution_outcome": "completed",
            }
            artifact = self.research_store.create_artifact({
                "task_id": job["task_id"],
                "experiment_id": job["experiment_id"],
                "kind": "backtest_result",
                "content": artifact_content,
                "lineage": [
                    {"kind": "artifact", "id": job["strategy_version_artifact_id"]},
                    {"kind": "artifact", "id": job["approval_artifact_id"]},
                    {"kind": "backtest_input", "id": job["input_manifest_id"]},
                ],
                "trace_id": request["trace_id"],
                "idempotency_key": f"backtest-result-{job['job_id']}",
            })
            if artifact["status"] == "draft":
                artifact = self.research_store.transition(
                    "artifact", artifact["artifact_id"], "validated", f"backtest-result-validate-{job['job_id']}"
                )
            return self.jobs.complete(
                job_id,
                result_reference=reference,
                result_artifact_id=str(artifact["artifact_id"]),
                summary=summary,
            )
        except BacktestResourceExceeded as error:
            return self.jobs.retry_or_fail(job_id, error_code="resource_limit", error_message=str(error))
        except (ValueError, BacktestError) as error:
            return self.jobs.retry_or_fail(job_id, error_code="execution_error", error_message=str(error))
        except Exception as error:  # pragma: no cover - defensive worker boundary
            return self.jobs.retry_or_fail(job_id, error_code="worker_error", error_message="backtest worker failed")


def load_result(objects: LocalObjectStore, reference: dict[str, object]) -> dict[str, object]:
    payload = objects.get(reference)
    try:
        result = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ObjectIntegrityError("backtest result object is not JSON") from error
    if not isinstance(result, dict):
        raise ObjectIntegrityError("backtest result object is not an object")
    return result
