"""Phase 16 logical market-data migration dry-run contract.

This module validates a bounded read-only audit snapshot and emits a
secret-free manifest plus quarantine report. It never connects to Community
PostgreSQL or performs an import.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any


SYMBOL_PATTERN = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
TRADE_DATE_PATTERN = re.compile(r"^\d{8}$")
SUPPORTED_ASSET_TYPES = {"stock", "etf"}
ALLOWED_SOURCES = {"tushare"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finite_number(value: object, *, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    return result


def _validate_row(row: object) -> tuple[dict[str, object] | None, list[str]]:
    if not isinstance(row, dict):
        return None, ["row must be an object"]
    reasons: list[str] = []

    symbol = row.get("symbol")
    if not isinstance(symbol, str) or SYMBOL_PATTERN.fullmatch(symbol.strip()) is None:
        reasons.append("symbol must be canonical NNNNNN.SH/SZ/BJ")
    else:
        symbol = symbol.strip().upper()

    trade_date = row.get("trade_date")
    if not isinstance(trade_date, str) or TRADE_DATE_PATTERN.fullmatch(trade_date) is None:
        reasons.append("trade_date must be YYYYMMDD")
    else:
        try:
            date.fromisoformat(f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}")
        except ValueError:
            reasons.append("trade_date is not a real calendar date")

    source = row.get("data_source")
    if source not in ALLOWED_SOURCES:
        reasons.append("data_source must be tushare")

    adjust = row.get("adjust")
    if adjust != "none":
        reasons.append("adjust must be none for raw daily bars")

    asset_type = row.get("asset_type")
    if asset_type not in SUPPORTED_ASSET_TYPES:
        reasons.append("asset_type must be stock or etf")

    try:
        open_ = _finite_number(row.get("open"), field="open")
        high = _finite_number(row.get("high"), field="high")
        low = _finite_number(row.get("low"), field="low")
        close = _finite_number(row.get("close"), field="close")
        if high < max(open_, close) or low > min(open_, close):
            reasons.append("OHLC relationship is invalid")
    except ValueError as exc:
        reasons.append(str(exc))

    volume = row.get("volume")
    if volume is not None:
        try:
            volume = _finite_number(volume, field="volume")
            if volume < 0:
                reasons.append("volume must be non-negative")
        except ValueError as exc:
            reasons.append(str(exc))

    amount = row.get("amount")
    if amount is not None:
        try:
            amount = _finite_number(amount, field="amount")
            if amount < 0:
                reasons.append("amount must be non-negative")
        except ValueError as exc:
            reasons.append(str(exc))

    volume_unit = row.get("volume_unit")
    if volume_unit is not None and volume_unit != "lots":
        reasons.append("volume_unit must be lots")
    amount_unit = row.get("amount_unit")
    if amount_unit is not None and amount_unit != "thousand_cny":
        reasons.append("amount_unit must be thousand_cny")

    if reasons:
        return None, reasons
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "data_source": source,
        "adjust": adjust,
        "asset_type": asset_type,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "amount": amount,
        "volume_unit": volume_unit,
        "amount_unit": amount_unit,
    }, []


def dry_run_market_data_migration(
    rows: object,
    *,
    source_repository: str,
    source_table: str,
    source_filter: str,
    target_dataset: str,
) -> dict[str, object]:
    """Validate a read-only market-data audit snapshot."""

    if not isinstance(rows, list):
        raise ValueError("rows must be a list")
    if not isinstance(source_repository, str) or not source_repository:
        raise ValueError("source_repository must be a non-empty string")
    if not isinstance(source_table, str) or not source_table:
        raise ValueError("source_table must be a non-empty string")
    if not isinstance(source_filter, str) or not source_filter:
        raise ValueError("source_filter must be a non-empty string")
    if not isinstance(target_dataset, str) or not target_dataset:
        raise ValueError("target_dataset must be a non-empty string")

    accepted: list[dict[str, object]] = []
    quarantine: list[dict[str, object]] = []
    seen: dict[tuple[str, str], int] = {}
    source_row_count = len(rows)

    for index, row in enumerate(rows):
        normalized, reasons = _validate_row(row)
        if normalized is None:
            quarantine.append({"row_index": index, "reasons": reasons})
            continue
        key = (str(normalized["symbol"]), str(normalized["trade_date"]))
        previous = seen.get(key)
        if previous is not None:
            quarantine.append(
                {
                    "row_index": index,
                    "reasons": [f"duplicate of row {previous}"],
                }
            )
            continue
        seen[key] = index
        accepted.append(normalized)

    accepted.sort(key=lambda item: (str(item["symbol"]), str(item["trade_date"])))
    canonical = json.dumps(accepted, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    accepted_sha256 = hashlib.sha256(canonical).hexdigest()
    dates = [str(item["trade_date"]) for item in accepted]
    date_min = min(dates) if dates else None
    date_max = max(dates) if dates else None
    manifest = {
        "schema_version": "market-data-migration-v1",
        "migration_id": uuid.uuid4().hex,
        "source_repository": source_repository,
        "source_table": source_table,
        "source_filter": source_filter,
        "target_dataset": target_dataset,
        "source_row_count": source_row_count,
        "accepted_row_count": len(accepted),
        "rejected_row_count": len(quarantine),
        "duplicate_row_count": sum(
            1 for item in quarantine if any("duplicate" in reason for reason in item["reasons"])
        ),
        "date_min": date_min,
        "date_max": date_max,
        "symbol_count": len({str(item["symbol"]) for item in accepted}),
        "accepted_content_sha256": accepted_sha256,
        "started_at": _now(),
        "completed_at": _now(),
    }
    return {
        "manifest": manifest,
        "accepted": accepted,
        "quarantine": quarantine,
    }
