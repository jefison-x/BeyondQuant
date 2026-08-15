"""BYQ-owned, deterministic factor-research input and computation contracts.

This module deliberately accepts normalized domain snapshots rather than a
provider-specific frame.  It is the boundary at which lifecycle, calendar,
coverage, point-in-time, and data-quality invariants become enforceable.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime
from typing import Any


MAX_SECURITIES = 64
MAX_SESSIONS = 512
MAX_BARS = 2048
MAX_STATUSES = 4096
MAX_SNAPSHOTS = 64
MAX_SOURCES = 64
MAX_OBSERVATIONS_IN_ARTIFACT = 512
_DATE_PATTERN = re.compile(r"^[0-9]{8}$")
_SYMBOL_PATTERN = re.compile(r"^[0-9]{6}\.(SH|SZ|BJ)$")
_EXCHANGES = {"SH", "SZ", "BJ"}
_ASSET_TYPES = {"stock", "etf"}
_FACTOR_NAMES = {"daily_return", "momentum"}
_STATUS_VALUES = {"trading", "suspended"}
_SECURITY_FIELDS = {"symbol", "exchange", "asset_type", "list_date", "delist_date"}
_SESSION_FIELDS = {"trade_date", "is_open"}
_STATUS_FIELDS = {"symbol", "trade_date", "state", "reason"}
_BAR_FIELDS = {"symbol", "trade_date", "open", "high", "low", "close"}
_SOURCE_FIELDS = {
    "provider",
    "endpoint",
    "request_fingerprint",
    "dataset_id",
    "announcement_date",
    "effective_date",
}
_SNAPSHOT_FIELDS = {"snapshot_date", "symbols"}


class FactorValidationError(ValueError):
    """Raised when a factor input violates a BYQ-owned domain invariant."""


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FactorValidationError(f"{field} must be an object")
    return value


def _fields(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FactorValidationError(f"{field} has unknown fields: {', '.join(unknown)}")


def _text(value: object, field: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FactorValidationError(f"{field} must be a non-empty string")
    result = value.strip()
    if len(result) > maximum:
        raise FactorValidationError(f"{field} exceeds {maximum} characters")
    return result


def _date(value: object, field: str) -> str:
    result = _text(value, field, 8)
    if not _DATE_PATTERN.fullmatch(result):
        raise FactorValidationError(f"{field} must use YYYYMMDD")
    try:
        datetime.strptime(result, "%Y%m%d")
    except ValueError as error:
        raise FactorValidationError(f"{field} is not a calendar date") from error
    return result


def _optional_date(value: object, field: str) -> str | None:
    return None if value is None else _date(value, field)


def normalize_symbol(value: object, *, exchange: object | None = None, field: str = "symbol") -> str:
    """Require explicit exchange for bare symbols; never guess from prefixes."""

    symbol = _text(value, field, 16).upper()
    explicit_exchange = None if exchange is None else _text(exchange, f"{field}.exchange", 2).upper()
    if "." in symbol:
        if _SYMBOL_PATTERN.fullmatch(symbol) is None:
            raise FactorValidationError(f"{field} must be NNNNNN.SH, NNNNNN.SZ, or NNNNNN.BJ")
        if explicit_exchange is not None and explicit_exchange != symbol[-2:]:
            raise FactorValidationError(f"{field} exchange does not match symbol")
        return symbol
    if not re.fullmatch(r"[0-9]{6}", symbol):
        raise FactorValidationError(f"{field} must contain a six-digit code and explicit exchange")
    if explicit_exchange not in _EXCHANGES:
        raise FactorValidationError(f"{field} requires an explicit SH, SZ, or BJ exchange")
    return f"{symbol}.{explicit_exchange}"


def _finite_number(value: object, field: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool):
        raise FactorValidationError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise FactorValidationError(f"{field} must be numeric") from error
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise FactorValidationError(f"{field} must be finite{', non-negative' if nonnegative else ''}")
    return result


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise FactorValidationError("factor input must be JSON-serializable") from error


def _sorted_unique_dates(values: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    dates = [row[field] for row in values]
    if len(set(dates)) != len(dates):
        raise FactorValidationError(f"duplicate {field} entries are not allowed")
    return sorted(values, key=lambda row: row[field])


def _security(value: object) -> dict[str, Any]:
    row = _object(value, "securities entry")
    _fields(row, _SECURITY_FIELDS, "security")
    symbol = normalize_symbol(row.get("symbol"), exchange=row.get("exchange"))
    exchange = symbol[-2:]
    asset_type = _text(row.get("asset_type"), "security.asset_type", 16).lower()
    if asset_type not in _ASSET_TYPES:
        raise FactorValidationError("security.asset_type must be stock or etf")
    list_date = _optional_date(row.get("list_date"), "security.list_date")
    delist_date = _optional_date(row.get("delist_date"), "security.delist_date")
    if list_date and delist_date and list_date > delist_date:
        raise FactorValidationError("security.list_date must not be after delist_date")
    return {
        "symbol": symbol,
        "exchange": exchange,
        "asset_type": asset_type,
        "list_date": list_date,
        "delist_date": delist_date,
    }


def _session(value: object) -> dict[str, Any]:
    row = _object(value, "sessions entry")
    _fields(row, _SESSION_FIELDS, "session")
    if not isinstance(row.get("is_open"), bool):
        raise FactorValidationError("session.is_open must be boolean")
    return {"trade_date": _date(row.get("trade_date"), "session.trade_date"), "is_open": row["is_open"]}


def _status(value: object) -> dict[str, Any]:
    row = _object(value, "statuses entry")
    _fields(row, _STATUS_FIELDS, "status")
    state = _text(row.get("state"), "status.state", 16).lower()
    if state not in _STATUS_VALUES:
        raise FactorValidationError("status.state must be trading or suspended")
    return {
        "symbol": normalize_symbol(row.get("symbol")),
        "trade_date": _date(row.get("trade_date"), "status.trade_date"),
        "state": state,
        "reason": None if row.get("reason") is None else _text(row["reason"], "status.reason", 256),
    }


def _bar(value: object) -> dict[str, Any]:
    row = _object(value, "bars entry")
    _fields(row, _BAR_FIELDS, "bar")
    numbers = {name: _finite_number(row.get(name), f"bar.{name}") for name in ("open", "high", "low", "close")}
    if numbers["low"] > numbers["high"]:
        raise FactorValidationError("bar.low must not exceed bar.high")
    if numbers["high"] < max(numbers["open"], numbers["close"]):
        raise FactorValidationError("bar.high must cover open and close")
    if numbers["low"] > min(numbers["open"], numbers["close"]):
        raise FactorValidationError("bar.low must cover open and close")
    if any(value <= 0 for value in numbers.values()):
        raise FactorValidationError("OHLC values must be positive")
    return {
        "symbol": normalize_symbol(row.get("symbol")),
        "trade_date": _date(row.get("trade_date"), "bar.trade_date"),
        **numbers,
    }


def _source(value: object, as_of_date: str) -> dict[str, Any]:
    row = _object(value, "sources entry")
    _fields(row, _SOURCE_FIELDS, "source")
    result = {
        "provider": _text(row.get("provider"), "source.provider"),
        "endpoint": _text(row.get("endpoint"), "source.endpoint"),
        "request_fingerprint": _text(row.get("request_fingerprint"), "source.request_fingerprint"),
        "dataset_id": _text(row.get("dataset_id"), "source.dataset_id"),
        "announcement_date": _optional_date(row.get("announcement_date"), "source.announcement_date"),
        "effective_date": _optional_date(row.get("effective_date"), "source.effective_date"),
    }
    for field in ("announcement_date", "effective_date"):
        if result[field] and result[field] > as_of_date:
            raise FactorValidationError(f"source.{field} is after as_of_date; look-ahead rejected")
    return result


def _snapshot(value: object) -> dict[str, Any]:
    row = _object(value, "universe snapshot")
    _fields(row, _SNAPSHOT_FIELDS, "universe snapshot")
    symbols = row.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise FactorValidationError("universe snapshot.symbols must be a non-empty list")
    normalized = sorted({normalize_symbol(symbol, field="universe.symbol") for symbol in symbols})
    return {"snapshot_date": _date(row.get("snapshot_date"), "universe.snapshot_date"), "symbols": normalized}


def _factor(value: object) -> dict[str, Any]:
    row = _object(value, "factor")
    allowed = {"name", "version", "lookback"}
    _fields(row, allowed, "factor")
    name = _text(row.get("name"), "factor.name", 32).lower()
    if name not in _FACTOR_NAMES:
        raise FactorValidationError("factor.name must be daily_return or momentum")
    version = _text(row.get("version"), "factor.version", 32)
    lookback = row.get("lookback", 1)
    if isinstance(lookback, bool) or not isinstance(lookback, int) or not 1 <= lookback <= 252:
        raise FactorValidationError("factor.lookback must be an integer between 1 and 252")
    if name == "daily_return" and lookback != 1:
        raise FactorValidationError("daily_return requires lookback=1")
    return {"name": name, "version": version, "lookback": lookback}


def _count_coverage(coverage: list[dict[str, str]]) -> dict[str, int]:
    counts = Counter(row["status"] for row in coverage)
    return {key: counts.get(key, 0) for key in ("present", "missing", "not_listed", "delisted", "suspended", "non_trading")}


def prepare_factor_input(payload: object) -> dict[str, Any]:
    request = _object(payload, "factor request")
    allowed = {
        "task_id", "experiment_id", "trace_id", "idempotency_key", "as_of_date", "factor",
        "securities", "sessions", "statuses", "bars", "universe_snapshots", "sources",
    }
    _fields(request, allowed, "factor request")
    as_of_date = _date(request.get("as_of_date"), "as_of_date")
    factor = _factor(request.get("factor"))

    securities_raw = request.get("securities")
    if not isinstance(securities_raw, list) or not securities_raw or len(securities_raw) > MAX_SECURITIES:
        raise FactorValidationError(f"securities must contain 1-{MAX_SECURITIES} entries")
    securities = sorted((_security(row) for row in securities_raw), key=lambda row: row["symbol"])
    security_by_symbol = {row["symbol"]: row for row in securities}
    if len(security_by_symbol) != len(securities):
        raise FactorValidationError("duplicate securities are not allowed")

    sessions_raw = request.get("sessions")
    if not isinstance(sessions_raw, list) or not sessions_raw or len(sessions_raw) > MAX_SESSIONS:
        raise FactorValidationError(f"sessions must contain 1-{MAX_SESSIONS} entries")
    sessions = _sorted_unique_dates([_session(row) for row in sessions_raw], "trade_date")
    if any(row["trade_date"] > as_of_date for row in sessions):
        raise FactorValidationError("sessions after as_of_date are not allowed")
    open_dates = [row["trade_date"] for row in sessions if row["is_open"]]
    if not open_dates:
        raise FactorValidationError("sessions must contain an open trading session")

    statuses_raw = request.get("statuses", [])
    if not isinstance(statuses_raw, list) or len(statuses_raw) > MAX_STATUSES:
        raise FactorValidationError(f"statuses must contain at most {MAX_STATUSES} entries")
    statuses = sorted((_status(row) for row in statuses_raw), key=lambda row: (row["symbol"], row["trade_date"]))
    status_keys = [(row["symbol"], row["trade_date"]) for row in statuses]
    if len(set(status_keys)) != len(status_keys):
        raise FactorValidationError("duplicate status entries are not allowed")
    if any(row["trade_date"] > as_of_date for row in statuses):
        raise FactorValidationError("statuses after as_of_date are not allowed")
    unknown_status_symbols = sorted({row["symbol"] for row in statuses} - set(security_by_symbol))
    if unknown_status_symbols:
        raise FactorValidationError("status references an unknown security")

    bars_raw = request.get("bars")
    if not isinstance(bars_raw, list) or len(bars_raw) > MAX_BARS:
        raise FactorValidationError(f"bars must contain at most {MAX_BARS} entries")
    bars = sorted((_bar(row) for row in bars_raw), key=lambda row: (row["symbol"], row["trade_date"]))
    bar_keys = [(row["symbol"], row["trade_date"]) for row in bars]
    if len(set(bar_keys)) != len(bar_keys):
        raise FactorValidationError("duplicate daily bars for the same symbol and trade_date are not allowed")
    unknown_bar_symbols = sorted({row["symbol"] for row in bars} - set(security_by_symbol))
    if unknown_bar_symbols:
        raise FactorValidationError("bar references an unknown security")
    if any(row["trade_date"] > as_of_date for row in bars):
        raise FactorValidationError("bars after as_of_date are not allowed")
    open_date_set = set(open_dates)
    status_by_key = {(row["symbol"], row["trade_date"]): row["state"] for row in statuses}
    for row in bars:
        if row["trade_date"] not in open_date_set:
            raise FactorValidationError("bar exists on a non-trading session")
        security = security_by_symbol[row["symbol"]]
        if security["list_date"] and row["trade_date"] < security["list_date"]:
            raise FactorValidationError("bar exists before security listing date")
        if security["delist_date"] and row["trade_date"] > security["delist_date"]:
            raise FactorValidationError("bar exists after security delisting date")
        if status_by_key.get((row["symbol"], row["trade_date"])) == "suspended":
            raise FactorValidationError("suspended session must not contain a daily bar")

    snapshots_raw = request.get("universe_snapshots")
    if not isinstance(snapshots_raw, list) or not snapshots_raw or len(snapshots_raw) > MAX_SNAPSHOTS:
        raise FactorValidationError(f"universe_snapshots must contain 1-{MAX_SNAPSHOTS} entries")
    snapshots = _sorted_unique_dates([_snapshot(row) for row in snapshots_raw], "snapshot_date")
    visible = [row for row in snapshots if row["snapshot_date"] <= as_of_date]
    if not visible:
        raise FactorValidationError("no universe snapshot is visible at as_of_date; look-ahead rejected")
    selected_snapshot = visible[-1]
    unknown_universe_symbols = sorted(set(selected_snapshot["symbols"]) - set(security_by_symbol))
    if unknown_universe_symbols:
        raise FactorValidationError("universe snapshot references an unknown security")

    sources_raw = request.get("sources")
    if not isinstance(sources_raw, list) or not sources_raw or len(sources_raw) > MAX_SOURCES:
        raise FactorValidationError(f"sources must contain 1-{MAX_SOURCES} entries")
    sources = sorted((_source(row, as_of_date) for row in sources_raw), key=lambda row: (row["provider"], row["endpoint"], row["dataset_id"]))

    coverage: list[dict[str, str]] = []
    bar_by_key = {(row["symbol"], row["trade_date"]): row for row in bars}
    selected_symbols = selected_snapshot["symbols"]
    for symbol in selected_symbols:
        security = security_by_symbol[symbol]
        for session in sessions:
            trade_date = session["trade_date"]
            key = (symbol, trade_date)
            if security["list_date"] and trade_date < security["list_date"]:
                status = "not_listed"
            elif security["delist_date"] and trade_date > security["delist_date"]:
                status = "delisted"
            elif not session["is_open"]:
                status = "non_trading"
            elif status_by_key.get(key) == "suspended":
                status = "suspended"
            elif key in bar_by_key:
                status = "present"
            else:
                status = "missing"
            coverage.append({"symbol": symbol, "trade_date": trade_date, "status": status})
    coverage_counts = _count_coverage(coverage)
    if coverage_counts["missing"]:
        raise FactorValidationError("factor input has missing bars inside an active tradable lifecycle")

    normalized = {
        "as_of_date": as_of_date,
        "factor": factor,
        "securities": securities,
        "sessions": sessions,
        "statuses": statuses,
        "bars": bars,
        "universe_snapshots": snapshots,
        "selected_universe": selected_snapshot,
        "sources": sources,
    }
    manifest_json = _canonical_json(normalized)
    manifest_id = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()
    return {
        "request": request,
        "normalized": normalized,
        "manifest_id": manifest_id,
        "coverage": coverage,
        "coverage_counts": coverage_counts,
        "bar_by_key": bar_by_key,
        "status_by_key": status_by_key,
        "open_dates": open_dates,
    }


def compute_factor(payload: object) -> dict[str, Any]:
    prepared = prepare_factor_input(payload)
    normalized = prepared["normalized"]
    factor = normalized["factor"]
    bars = prepared["bar_by_key"]
    statuses = prepared["status_by_key"]
    selected_symbols = normalized["selected_universe"]["symbols"]
    open_dates = prepared["open_dates"]
    lookback = factor["lookback"]
    observations: list[dict[str, Any]] = []
    for symbol in selected_symbols:
        for index, trade_date in enumerate(open_dates):
            current = bars.get((symbol, trade_date))
            if current is None or statuses.get((symbol, trade_date)) == "suspended":
                continue
            previous_index = index - lookback
            if previous_index < 0:
                continue
            previous_date = open_dates[previous_index]
            previous = bars.get((symbol, previous_date))
            if previous is None or statuses.get((symbol, previous_date)) == "suspended":
                continue
            value = current["close"] / previous["close"] - 1.0
            if not math.isfinite(value):
                raise FactorValidationError("factor result is not finite")
            observations.append({"symbol": symbol, "trade_date": trade_date, "value": value})
    if len(observations) > MAX_OBSERVATIONS_IN_ARTIFACT:
        raise FactorValidationError("factor result exceeds the bounded Artifact result limit")
    observations.sort(key=lambda row: (row["symbol"], row["trade_date"]))
    values = [row["value"] for row in observations]
    evaluation = {
        "count": len(values),
        "mean": sum(values) / len(values) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }
    result = {
        "factor": factor,
        "computation": {
            "engine": "byq-native-factor",
            "engine_version": "1",
            "algorithm": "close_to_close",
        },
        "as_of_date": normalized["as_of_date"],
        "input_manifest_id": prepared["manifest_id"],
        "selected_universe_snapshot_date": normalized["selected_universe"]["snapshot_date"],
        "coverage": prepared["coverage_counts"],
        "evaluation": evaluation,
        "reproducibility": "reproducible",
        "observations": observations,
    }
    return {
        "factor": result,
        "input_manifest": {
            "id": prepared["manifest_id"],
            "schema_version": "factor-input-v1",
            "as_of_date": normalized["as_of_date"],
            "source_count": len(normalized["sources"]),
            "row_count": len(normalized["bars"]),
        },
        "coverage": prepared["coverage_counts"],
        "artifact_content": result,
        "artifact_lineage": [{"kind": "factor_input", "id": prepared["manifest_id"]}],
    }
