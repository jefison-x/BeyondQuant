"""Deterministic columnar encoding for frozen signal bars (ADR-0023/ADR-0029).

The durable signal-producer job document and the ``byq-signal-sandbox-request-v1``
payload must stay inside ADR-0023's bounded 32 MiB isolation envelope without
raising ``MAX_JOB_BYTES``/``MAX_REQUEST_BYTES`` or relaxing the sandbox resource
limits. Embedding both the raw execution bars and the adjusted research view as
lists of per-row mappings duplicated every key and repeated the shared index on
every row, which overflowed the bound for a 300 x 727 panel.

``bars_frame.v1`` is a framework-neutral, JSON-serializable columnar encoding of
the frozen bar panel:

``schema_version``
    Always ``"bars_frame.v1"``.
``basis``
    ``"raw"`` means the ``columns`` hold the raw execution panel and every
    adjusted field is materialized as ``round(raw * multiplier, 8)``; ``"research"``
    means ``columns`` already hold the adjusted research view the strategy sees.
``symbols`` / ``dates``
    Canonically sorted unique symbols and ISO trade dates.
``symbol_index`` / ``date_index``
    Per-row integer indices into ``symbols``/``dates``. Rows are ordered by
    ``(symbol, date)`` so the encoding is byte-for-byte deterministic.
``columns``
    One primitive array per field, aligned with the row index. Floats are finite
    (no NaN/Infinity); integer index arrays stay integers.
``bars_fields`` / ``research_fields``
    The field names that belong to the raw execution panel and to the research
    panel respectively (the research panel may add declared-factor fields).
``adjustment_multiplier``
    Present only for ``basis == "raw"``: the per-row factor applied to the
    adjusted OHLC/limit fields, exactly as the readiness builder computed it.

Decoding a raw frame reproduces the research panel produced by
``MarketReadinessStore.build_ready_input`` field-for-field, so the coordinator
keeps constructing the adjusted research view (ADR-0029 decision 4) while the
job document stores the raw panel only once. Legacy row-dict documents remain
decodable by the sandbox and coordinator.
"""

from __future__ import annotations

import math
from typing import Any

BARS_FRAME_SCHEMA_VERSION = "bars_frame.v1"

_ADJUSTED_FIELDS = ("open", "high", "low", "close", "prev_close", "up_limit", "down_limit")


def _finite(value: object, field: str) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"bars frame field {field} must contain only finite numbers")
    return value


def _row_symbol(row: dict[str, object]) -> str:
    return str(row["symbol"])


def _row_date(row: dict[str, object]) -> str:
    return str(row["trade_date"])


def _ordered_indices(rows: list[dict[str, object]]) -> tuple[list[str], list[str], list[int]]:
    symbols = sorted({_row_symbol(row) for row in rows})
    dates = sorted({_row_date(row) for row in rows})
    symbol_index = {symbol: index for index, symbol in enumerate(symbols)}
    date_index = {date: index for index, date in enumerate(dates)}
    order = sorted(range(len(rows)), key=lambda index: (symbol_index[_row_symbol(rows[index])], date_index[_row_date(rows[index])]))
    keys = {(symbol_index[_row_symbol(rows[index])], date_index[_row_date(rows[index])]) for index in order}
    if len(keys) != len(rows):
        raise ValueError("bars frame rows contain duplicate symbol/date pairs")
    return symbols, dates, order


def encode_bars_frame(
    *,
    bars: list[dict[str, object]],
    research_bars: list[dict[str, object]],
    basis: str = "raw",
    multipliers: list[float] | None = None,
) -> dict[str, object]:
    """Encode one raw execution panel plus its adjusted research view.

    ``bars`` and ``research_bars`` are parallel row lists in the readiness
    builder's order. When ``basis == "raw"`` the raw panel is stored and the
    per-row ``multipliers`` are preserved so the research view is reconstructed
    deterministically; the encoder verifies the reconstruction exactly matches
    ``research_bars`` before accepting the frame.
    """
    if basis not in {"raw", "research"}:
        raise ValueError("bars frame basis must be raw or research")
    if len(bars) != len(research_bars):
        raise ValueError("bars frame raw and research panels must have equal length")
    rows = list(bars)
    research_rows = list(research_bars)
    count = len(rows)
    factors = [1.0] * count if multipliers is None else [float(value) for value in multipliers]
    if len(factors) != count:
        raise ValueError("bars frame adjustment multipliers must align with rows")
    if any(not math.isfinite(factor) for factor in factors):
        raise ValueError("bars frame adjustment multipliers must be finite")

    symbols, dates, order = _ordered_indices(rows)
    symbol_lookup = {symbol: index for index, symbol in enumerate(symbols)}
    date_lookup = {date: index for index, date in enumerate(dates)}

    raw_fields = sorted({field for row in rows for field in row} - {"symbol", "trade_date"})
    research_fields = sorted({field for row in research_rows for field in row} - {"symbol", "trade_date"})
    all_fields = sorted(set(raw_fields) | set(research_fields))

    columns: dict[str, list[object]] = {}
    for field in all_fields:
        column: list[object] = []
        for index in order:
            if basis == "research":
                value = research_rows[index].get(field)
            elif field in _ADJUSTED_FIELDS:
                value = rows[index].get(field)
            else:
                value = rows[index].get(field, research_rows[index].get(field))
            _finite(value, field)
            column.append(value)
        columns[field] = column

    if basis == "raw":
        for position, index in enumerate(order):
            raw = rows[index]
            adjusted = research_rows[index]
            factor = factors[index]
            for field in _ADJUSTED_FIELDS:
                raw_value = raw.get(field)
                adjusted_value = adjusted.get(field)
                if field not in raw:
                    if adjusted_value is not None:
                        raise ValueError(
                            f"bars frame cannot reproduce {field} at row {position} without raw input"
                        )
                    continue
                expected = None if raw_value is None else round(float(raw_value) * factor, 8)
                if expected != adjusted_value:
                    raise ValueError(
                        f"bars frame cannot reproduce {field} at row {position} from its adjustment multiplier"
                    )

    frame: dict[str, object] = {
        "schema_version": BARS_FRAME_SCHEMA_VERSION,
        "basis": basis,
        "symbols": symbols,
        "dates": dates,
        "symbol_index": [symbol_lookup[_row_symbol(rows[index])] for index in order],
        "date_index": [date_lookup[_row_date(rows[index])] for index in order],
        "bars_fields": raw_fields,
        "research_fields": research_fields,
        "columns": columns,
    }
    if basis == "raw":
        frame["adjustment_multiplier"] = [factors[index] for index in order]
    return frame


def encode_research_frame(rows: list[dict[str, object]]) -> dict[str, object]:
    """Encode an already-adjusted research panel for the sandbox request."""
    return encode_bars_frame(bars=rows, research_bars=rows, basis="research")


def _validated(frame: object) -> tuple[dict[str, object], int]:
    if not isinstance(frame, dict) or frame.get("schema_version") != BARS_FRAME_SCHEMA_VERSION:
        raise ValueError("unsupported bars frame schema")
    if frame.get("basis") not in {"raw", "research"}:
        raise ValueError("bars frame basis is invalid")
    symbols = frame.get("symbols")
    dates = frame.get("dates")
    columns = frame.get("columns")
    symbol_index = frame.get("symbol_index")
    date_index = frame.get("date_index")
    if not isinstance(symbols, list) or not all(isinstance(item, str) for item in symbols):
        raise ValueError("bars frame symbols are invalid")
    if not isinstance(dates, list) or not all(isinstance(item, str) for item in dates):
        raise ValueError("bars frame dates are invalid")
    if not isinstance(columns, dict) or not columns:
        raise ValueError("bars frame columns are invalid")
    if not isinstance(symbol_index, list) or not isinstance(date_index, list) or len(symbol_index) != len(date_index):
        raise ValueError("bars frame row indices are invalid")
    count = len(symbol_index)
    for field, column in columns.items():
        if not isinstance(column, list) or len(column) != count:
            raise ValueError(f"bars frame column {field} is misaligned")
        for value in column:
            _finite(value, str(field))
    for value in symbol_index:
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < len(symbols):
            raise ValueError("bars frame symbol index is out of range")
    for value in date_index:
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < len(dates):
            raise ValueError("bars frame date index is out of range")
    if frame.get("basis") == "raw":
        multipliers = frame.get("adjustment_multiplier")
        if not isinstance(multipliers, list) or len(multipliers) != count:
            raise ValueError("bars frame adjustment multipliers are invalid")
        for value in multipliers:
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError("bars frame adjustment multipliers must be finite numbers")
    return frame, count


def frame_row_count(frame: object) -> int:
    _, count = _validated(frame)
    return count


def decode_bars_frame(frame: object, *, basis: str | None = None) -> list[dict[str, object]]:
    """Expand a frame back to canonical row mappings for the requested panel."""
    validated, count = _validated(frame)
    target = validated["basis"] if basis is None else basis
    if target not in {"raw", "research"}:
        raise ValueError("bars frame decode basis must be raw or research")
    if target == "raw" and validated["basis"] != "raw":
        raise ValueError("raw panel is unavailable for a research frame")
    symbols = validated["symbols"]
    dates = validated["dates"]
    symbol_index = validated["symbol_index"]
    date_index = validated["date_index"]
    columns = validated["columns"]
    fields = validated["bars_fields"] if target == "raw" else validated["research_fields"]
    if not isinstance(fields, list):
        raise ValueError("bars frame panel fields are invalid")
    rows: list[dict[str, object]] = []
    for position in range(count):
        row: dict[str, object] = {
            "symbol": symbols[symbol_index[position]],
            "trade_date": dates[date_index[position]],
        }
        for field in fields:
            if field in columns:
                row[field] = columns[field][position]
        rows.append(row)
    if target == "research" and validated["basis"] == "raw":
        multipliers = validated["adjustment_multiplier"]
        for position, row in enumerate(rows):
            factor = float(multipliers[position])
            for field in _ADJUSTED_FIELDS:
                if field in row and row[field] is not None:
                    row[field] = round(float(row[field]) * factor, 8)
    return rows


def frame_research_rows(frame: object) -> list[dict[str, object]]:
    """Return the adjusted research panel a strategy consumes."""
    return decode_bars_frame(frame, basis="research")


def frame_raw_rows(frame: object) -> list[dict[str, object]]:
    """Return the raw execution panel preserved for the signal snapshot."""
    return decode_bars_frame(frame, basis="raw")


def is_bars_frame(value: Any) -> bool:
    return isinstance(value, dict) and value.get("schema_version") == BARS_FRAME_SCHEMA_VERSION
