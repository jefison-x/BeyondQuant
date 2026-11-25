"""Frozen, bounded requirements for canonical broad-index history."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime


INDEX_HISTORY_REQUIREMENT_SCHEMA = "index-history-requirement.v1"
SUPPORTED_INDEX_HISTORY_SYMBOLS = frozenset({"000300.SH", "000905.SH"})
_DATE = re.compile(r"^(?:[0-9]{8}|[0-9]{4}-[0-9]{2}-[0-9]{2})$")


def _requirement_hash(requirement: dict[str, object]) -> str:
    canonical = {key: value for key, value in requirement.items() if key != "requirement_sha256"}
    return hashlib.sha256(json.dumps(
        canonical, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _date(value: object, field: str) -> date:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise ValueError(f"{field} must be YYYYMMDD or YYYY-MM-DD")
    normalized = value.replace("-", "")
    try:
        parsed = datetime.strptime(normalized, "%Y%m%d").date()
    except ValueError as error:
        raise ValueError(f"{field} must be a valid YYYYMMDD or YYYY-MM-DD date") from error
    if parsed.strftime("%Y%m%d") != normalized:
        raise ValueError(f"{field} must be a valid YYYYMMDD or YYYY-MM-DD date")
    return parsed


def build_index_history_requirement(
    symbols: object, start_date: object, end_date: object,
) -> dict[str, object]:
    """Build a hash-frozen single repair requirement for one or both supported indices."""
    if (not isinstance(symbols, list) or not 1 <= len(symbols) <= 2
            or any(not isinstance(symbol, str) for symbol in symbols)):
        raise ValueError("symbols must be a list of one or two supported index symbols")
    normalized = {symbol.strip().upper() for symbol in symbols}
    if len(normalized) != len(symbols) or not normalized <= SUPPORTED_INDEX_HISTORY_SYMBOLS:
        raise ValueError("symbols must contain only 000300.SH and 000905.SH")
    first, last = _date(start_date, "start_date"), _date(end_date, "end_date")
    if first > last:
        raise ValueError("start_date must not be after end_date")
    try:
        anniversary = first.replace(year=first.year + 10)
    except ValueError:
        # Feb 29 has no anniversary in a non-leap year.
        anniversary = first.replace(year=first.year + 10, day=28)
    if last > anniversary:
        raise ValueError("index history range must not exceed ten calendar years")
    requirement: dict[str, object] = {
        "schema_version": INDEX_HISTORY_REQUIREMENT_SCHEMA,
        "kind": "index_history",
        "symbols": sorted(normalized),
        "start_date": first.strftime("%Y%m%d"),
        "end_date": last.strftime("%Y%m%d"),
        "datasets": ["trade_calendar", "index_daily"],
        "declared": {},
    }
    requirement["requirement_sha256"] = _requirement_hash(requirement)
    return requirement


def validate_index_history_requirement(requirement: object) -> dict[str, object]:
    """Validate a persisted immutable requirement and return its canonical copy."""
    if not isinstance(requirement, dict):
        raise ValueError("index history requirement must be an object")
    try:
        expected = build_index_history_requirement(
            requirement.get("symbols"), requirement.get("start_date"), requirement.get("end_date"),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("index history requirement is invalid") from error
    if requirement != expected:
        raise ValueError("index history requirement does not match its frozen scope")
    return expected
