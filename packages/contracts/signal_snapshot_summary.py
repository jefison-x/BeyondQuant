"""ADR-0085 P0: bounded, safe Product-Agent projection of a signal snapshot.

The immutable ``signal-snapshot-v2`` artifact is a frozen *execution input* for
trusted Backend/Worker code. It can be tens of MiB (a production panel measured
~15.9 MiB / 220,803 frame rows). Handing that document to a Product Agent turn
lets a large payload enter the harness event/compaction path and, in the real
2026-09-22 failure, triggered massive context work before any model call.

This contract defines the ONLY shape a Product Agent may observe: a bounded
summary of at most 64 KiB of serialized JSON that carries identity, hash,
status, lineage, date range, universe/benchmark identifiers and counts,
signal/corporate-action/bar counts, an execution-parameter summary, a
readiness/integrity summary and a few bounded diagnostic samples.

It MUST NOT contain the full ``bars_frame``, per-day benchmark rows, per-symbol
indexes, the complete ``signals`` list or ``corporate_actions`` rows. The full
artifact stays available to trusted Backend/Worker consumers through the
unchanged internal artifact path.
"""

from __future__ import annotations

import json
from typing import Any

from packages.contracts.bars_frame import (
    frame_row_count,
    frame_snapshot_rows,
    is_bars_frame,
)

SIGNAL_SNAPSHOT_SUMMARY_SCHEMA_VERSION = "signal-snapshot-summary.v1"
MAX_SUMMARY_BYTES = 64 * 1024
MAX_LINEAGE = 16
MAX_SYMBOL_SAMPLES = 8
MAX_ROW_SAMPLES = 3

# Names that must never appear anywhere in a bounded Product-Agent projection.
# ``bars_frame``/``bars``/``signals``/``corporate_actions``/``benchmark`` are
# the raw execution rows; ``symbols``/``symbol_index``/``date_index``/``columns``
# are the columnar frame internals. The summary exposes only counts, bounded
# identifiers and a handful of diagnostic samples under a distinct schema.
FORBIDDEN_FIELDS = frozenset({
    "bars_frame", "bars", "signals", "corporate_actions", "benchmark",
    "symbols", "symbol_index", "date_index", "columns", "research_bars",
    "script",
})

# Keys that must never appear INSIDE the projected strategy identity block.
# ``snapshot`` is the frozen strategy payload (script + parameters) and is
# deliberately excluded there; the summary's own top-level ``snapshot`` block is
# unrelated and legitimate.
FORBIDDEN_STRATEGY_FIELDS = frozenset({"script", "snapshot", "parameters", "source"})

_STRATEGY_IDENTITY_FIELDS = (
    "strategy_version_artifact_id", "strategy_version_id", "source_fingerprint",
    "universe_id", "version_id",
)

_EXECUTION_FIELDS = (
    "initial_capital", "commission_rate", "stamp_tax_rate", "slippage_rate",
    "lot_size", "max_positions", "limit_threshold", "a_share_rules",
    "max_runtime_seconds", "max_attempts",
)


def _bounded_text(value: object, *, limit: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    return value[:limit]


def _date_range_from_frame(frame: dict[str, object]) -> tuple[str | None, str | None]:
    dates = frame.get("dates")
    if not isinstance(dates, list) or not dates:
        return None, None
    ordered = sorted(str(item) for item in dates)
    return ordered[0], ordered[-1]


def _sample_frame_rows(frame: dict[str, object]) -> list[dict[str, object]]:
    """Read a bounded first-N diagnostic sample without returning frame internals."""

    symbols = frame.get("symbols")
    dates = frame.get("dates")
    symbol_index = frame.get("symbol_index")
    date_index = frame.get("date_index")
    columns = frame.get("columns")
    if not (isinstance(symbols, list) and isinstance(dates, list)
            and isinstance(symbol_index, list) and isinstance(date_index, list)
            and isinstance(columns, dict)):
        return []
    samples: list[dict[str, object]] = []
    for position in range(min(MAX_ROW_SAMPLES, len(symbol_index))):
        try:
            symbol = symbols[symbol_index[position]]
            trade_date = dates[date_index[position]]
        except (IndexError, TypeError):
            break
        row: dict[str, object] = {"symbol": symbol, "trade_date": trade_date}
        for field in ("open", "high", "low", "close"):
            column = columns.get(field)
            if isinstance(column, list) and position < len(column):
                row[field] = column[position]
        samples.append(row)
    return samples


def _bars_overview(document: dict[str, object]) -> dict[str, object]:
    frame = document.get("bars_frame")
    if is_bars_frame(frame):
        start, end = _date_range_from_frame(frame)
        return {
            "bar_count": frame_row_count(frame),
            "start_date": start,
            "end_date": end,
            "samples": _sample_frame_rows(frame),
        }
    bars = document.get("bars")
    if isinstance(bars, list):
        dates = sorted(str(row.get("trade_date")) for row in bars if isinstance(row, dict))
        samples = [
            {key: row.get(key) for key in ("symbol", "trade_date", "open", "high", "low", "close")}
            for row in bars[:MAX_ROW_SAMPLES] if isinstance(row, dict)
        ]
        return {
            "bar_count": len(bars),
            "start_date": dates[0] if dates else None,
            "end_date": dates[-1] if dates else None,
            "samples": samples,
        }
    return {"bar_count": 0, "start_date": None, "end_date": None, "samples": []}


def _benchmark_overview(document: dict[str, object]) -> dict[str, object] | None:
    benchmark = document.get("benchmark")
    if not isinstance(benchmark, list) or not benchmark:
        return None
    dates = sorted(str(row.get("trade_date")) for row in benchmark if isinstance(row, dict))
    symbol = next((row.get("symbol") for row in benchmark
                   if isinstance(row, dict) and isinstance(row.get("symbol"), str)), None)
    return {
        "symbol": symbol,
        "row_count": len(benchmark),
        "start_date": dates[0] if dates else None,
        "end_date": dates[-1] if dates else None,
    }


def _signal_overview(document: dict[str, object]) -> dict[str, object]:
    signals = document.get("signals")
    if not isinstance(signals, list):
        signals = []
    samples = [
        {"symbol": row.get("symbol"), "trade_date": row.get("trade_date"), "direction": row.get("direction")}
        for row in signals[:MAX_ROW_SAMPLES] if isinstance(row, dict)
    ]
    return {"count": len(signals), "samples": samples}


def _action_overview(document: dict[str, object]) -> dict[str, object]:
    actions = document.get("corporate_actions")
    if not isinstance(actions, list):
        actions = []
    samples = [
        {"symbol": row.get("symbol"), "ex_date": row.get("ex_date")}
        for row in actions[:MAX_ROW_SAMPLES] if isinstance(row, dict)
    ]
    return {"count": len(actions), "samples": samples}


def _execution_summary(document: dict[str, object]) -> dict[str, object]:
    execution = document.get("execution")
    if not isinstance(execution, dict):
        return {}
    return {field: execution[field] for field in _EXECUTION_FIELDS if field in execution}


def _readiness_summary(document: dict[str, object]) -> dict[str, object]:
    source = document.get("source")
    if not isinstance(source, dict):
        return {"producer": None, "content_sha256": None}
    summary: dict[str, object] = {"producer": _bounded_text(source.get("producer"), limit=64)}
    readiness = source.get("data_readiness")
    if isinstance(readiness, dict):
        summary["data_readiness"] = {
            key: _bounded_text(readiness[key], limit=64) for key in sorted(readiness)
        }
    constraints = source.get("selection_constraints")
    if isinstance(constraints, dict):
        summary["selection_constraints"] = {
            key: constraints[key] for key in sorted(constraints)
            if isinstance(constraints[key], int) and not isinstance(constraints[key], bool)
        }
    lineage = source.get("ml_lineage")
    if isinstance(lineage, dict):
        summary["ml_lineage"] = {
            key: _bounded_text(lineage[key], limit=128) for key in sorted(lineage)
        }
    summary["content_sha256"] = _bounded_text(source.get("content_sha256"), limit=64)
    return summary


def _artifact_identity(artifact: dict[str, object]) -> dict[str, object]:
    lineage = artifact.get("lineage")
    references = []
    if isinstance(lineage, list):
        for entry in lineage[:MAX_LINEAGE]:
            if not isinstance(entry, dict):
                continue
            kind, identity = entry.get("kind"), entry.get("id")
            if isinstance(kind, str) and isinstance(identity, str):
                references.append({"kind": kind, "id": identity})
    return {
        "artifact_id": artifact.get("artifact_id"),
        "kind": artifact.get("kind"),
        "status": artifact.get("status"),
        "content_sha256": artifact.get("content_sha256"),
        "task_id": artifact.get("task_id"),
        "experiment_id": artifact.get("experiment_id"),
        "created_at": artifact.get("created_at"),
        "updated_at": artifact.get("updated_at"),
        "version": artifact.get("version"),
        "lineage": references,
    }


def _universe_overview(document: dict[str, object]) -> dict[str, object]:
    universe = document.get("universe")
    if not isinstance(universe, dict):
        return {"universe_id": None, "version_id": None, "membership_fingerprint": None, "symbol_count": 0}
    symbols = universe.get("symbols")
    symbol_count = len(symbols) if isinstance(symbols, list) else 0
    return {
        "universe_id": _bounded_text(universe.get("universe_id"), limit=128),
        "version_id": _bounded_text(universe.get("version_id"), limit=128),
        "membership_fingerprint": _bounded_text(universe.get("membership_fingerprint"), limit=64),
        "symbol_count": symbol_count,
    }


def _strategy_identity(document: dict[str, object]) -> dict[str, object]:
    """Closed, length-bounded strategy identity; never the strategy source.

    ADR-0085 §5 allows only identity/lineage in the Product-Agent projection.
    The frozen snapshot's ``strategy`` block carries the full executable
    ``script`` and other nested payloads, so it MUST NOT be copied; only the
    explicit identifier fields below are projected.
    """

    strategy = document.get("strategy")
    if not isinstance(strategy, dict):
        return {}
    identity = {
        field: _bounded_text(strategy.get(field), limit=128)
        for field in _STRATEGY_IDENTITY_FIELDS
        if field in strategy
    }
    kind = strategy.get("kind")
    if isinstance(kind, str):
        identity["kind"] = kind[:64]
    return identity


def summarize_signal_snapshot(artifact: dict[str, Any], document: dict[str, Any]) -> dict[str, object]:
    """Return the bounded, safe Product-Agent projection of one snapshot.

    ``artifact`` is the artifact row (identity/status/hash/lineage) and
    ``document`` is its normalized snapshot content. The returned mapping is
    closed: it never carries the raw execution panel, benchmark rows, complete
    signals/corporate-action rows or columnar frame internals.
    """

    if not isinstance(artifact, dict) or not isinstance(document, dict):
        raise ValueError("signal snapshot summary requires artifact and content objects")
    bars = _bars_overview(document)
    universe = _universe_overview(document)
    signals = _signal_overview(document)
    actions = _action_overview(document)
    benchmark = _benchmark_overview(document)
    symbol_samples: list[str] = []
    frame_symbols = document.get("bars_frame")
    if is_bars_frame(frame_symbols) and isinstance(frame_symbols.get("symbols"), list):
        symbol_samples = [str(item) for item in frame_symbols["symbols"][:MAX_SYMBOL_SAMPLES]]
    elif isinstance(document.get("universe"), dict):
        universe_symbols = document["universe"].get("symbols")
        if isinstance(universe_symbols, list):
            symbol_samples = [str(item) for item in universe_symbols[:MAX_SYMBOL_SAMPLES]]

    summary = {
        "schema_version": SIGNAL_SNAPSHOT_SUMMARY_SCHEMA_VERSION,
        "artifact": _artifact_identity(artifact),
        "snapshot": {
            "schema_version": _bounded_text(document.get("schema_version"), limit=64),
            "strategy": _strategy_identity(document),
            "universe": universe,
            "date_range": {"start_date": bars["start_date"], "end_date": bars["end_date"]},
            "counts": {
                "bar_count": bars["bar_count"],
                "signal_count": signals["count"],
                "corporate_action_count": actions["count"],
                "benchmark_bar_count": benchmark["row_count"] if benchmark else 0,
            },
            "benchmark_summary": benchmark,
            "execution": _execution_summary(document),
            "readiness": _readiness_summary(document),
            "integrity": {
                "content_sha256": artifact.get("content_sha256"),
                "snapshot_content_sha256": _bounded_text(
                    (document.get("source") or {}).get("content_sha256")
                    if isinstance(document.get("source"), dict) else None, limit=64),
            },
        },
        "diagnostic_samples": {
            "symbol_sample": symbol_samples,
            "bar_sample": bars["samples"],
            "signal_sample": signals["samples"],
            "corporate_action_sample": actions["samples"],
        },
    }
    assert_summary_bounded(summary)
    return summary


def assert_summary_bounded(summary: dict[str, object]) -> None:
    """Fail closed when a projection exceeds the 64 KiB Product-Agent bound."""

    if not isinstance(summary, dict):
        raise ValueError("signal snapshot summary must be an object")
    if summary.get("schema_version") != SIGNAL_SNAPSHOT_SUMMARY_SCHEMA_VERSION:
        raise ValueError("signal snapshot summary schema is invalid")
    encoded = json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_SUMMARY_BYTES:
        raise ValueError("signal snapshot summary exceeds 64 KiB")
    for forbidden in FORBIDDEN_FIELDS:
        if _contains_key(summary, forbidden):
            raise ValueError(f"signal snapshot summary contains forbidden field {forbidden}")
    strategy = summary.get("snapshot", {}).get("strategy") if isinstance(summary.get("snapshot"), dict) else None
    if isinstance(strategy, dict):
        for forbidden in FORBIDDEN_STRATEGY_FIELDS:
            if forbidden in strategy:
                raise ValueError(f"signal snapshot summary strategy contains forbidden field {forbidden}")


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False
