"""ADR-0085 P0: bounded Product-Agent signal-snapshot projection."""

from __future__ import annotations

import json

import pytest

from packages.contracts.signal_snapshot_summary import (
    FORBIDDEN_FIELDS,
    MAX_SUMMARY_BYTES,
    assert_summary_bounded,
    summarize_signal_snapshot,
)

SCRIPT = "def generate_signals(data, parameters):\n    return {}\n" * 40


def _artifact(**overrides: object) -> dict:
    artifact = {
        "artifact_id": "artifact_" + "a" * 32,
        "kind": "signal_snapshot",
        "status": "validated",
        "content_sha256": "b" * 64,
        "task_id": "task_" + "c" * 32,
        "experiment_id": None,
        "created_at": "2026-09-22T00:00:00+00:00",
        "updated_at": "2026-09-22T00:00:00+00:00",
        "version": 1,
        "lineage": [{"kind": "artifact", "id": "artifact_" + "d" * 32}],
    }
    artifact.update(overrides)
    return artifact


def _document(bar_count: int = 6, signal_count: int = 4) -> dict:
    """A realistically shaped signal-snapshot-v2 document (with raw payloads)."""

    symbols = [f"{index:06d}.SZ" for index in range(3)]
    dates = [f"2026-09-{day:02d}" for day in range(1, 4)]
    symbol_index = [position % 3 for position in range(bar_count)]
    date_index = [(position // 3) % 3 for position in range(bar_count)]
    columns = {
        field: [10.0 + position for position in range(bar_count)]
        for field in ("open", "high", "low", "close")
    }
    return {
        "schema_version": "signal-snapshot-v2",
        "strategy": {
            "strategy_version_artifact_id": "artifact_" + "e" * 32,
            "strategy_version_id": "version_" + "f" * 32,
            "source_fingerprint": "g" * 64,
            "script": SCRIPT,
            "snapshot": {"script": SCRIPT, "parameters": {"fast": 20, "slow": 60}},
        },
        "universe": {
            "universe_id": "stock_pool_" + "h" * 32,
            "version_id": "stock_pool_snapshot_" + "i" * 64,
            "membership_fingerprint": "j" * 64,
            "symbols": symbols,
        },
        "bars_frame": {
            "schema_version": "bars_frame.v1",
            "basis": "research",
            "symbols": symbols,
            "dates": dates,
            "symbol_index": symbol_index,
            "date_index": date_index,
            "columns": columns,
            "research_fields": ["open", "high", "low", "close"],
        },
        "signals": [
            {"symbol": symbols[position % 3], "trade_date": dates[0], "direction": 1}
            for position in range(signal_count)
        ],
        "corporate_actions": [
            {"symbol": symbols[0], "ex_date": dates[0], "cash_div": 0.5}
        ],
        "benchmark": [
            {"symbol": "000300.SH", "trade_date": date, "close": 4000.0} for date in dates
        ],
        "execution": {"initial_capital": 1_000_000, "lot_size": 100},
        "source": {
            "producer": "byq-signal-python-v1",
            "content_sha256": "k" * 64,
            "data_readiness": {"ready_input_sha256": "l" * 64},
        },
    }


def test_summary_excludes_script_and_raw_execution_payloads() -> None:
    summary = summarize_signal_snapshot(_artifact(), _document())
    encoded = json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    assert SCRIPT not in encoded
    assert "def generate_signals" not in encoded
    for forbidden in FORBIDDEN_FIELDS:
        assert f'"{forbidden}"' not in encoded, forbidden
    # The strategy block is a closed identity summary only.
    strategy = summary["snapshot"]["strategy"]
    assert strategy["strategy_version_artifact_id"] == "artifact_" + "e" * 32
    assert strategy["source_fingerprint"] == "g" * 64
    assert "script" not in strategy and "snapshot" not in strategy


def test_summary_is_closed_and_bounded_for_a_large_panel() -> None:
    document = _document(bar_count=2_500, signal_count=1_200)
    document["corporate_actions"] = [
        {"symbol": "000001.SZ", "ex_date": "2026-09-01", "cash_div": 0.5}
        for _ in range(900)
    ]
    summary = summarize_signal_snapshot(_artifact(), document)
    encoded = json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    assert len(encoded.encode("utf-8")) <= MAX_SUMMARY_BYTES
    assert summary["snapshot"]["counts"]["bar_count"] == 2_500
    assert summary["snapshot"]["counts"]["signal_count"] == 1_200
    # Assert the guard itself is real: an oversized payload fails closed.
    assert_summary_bounded(summary)
    oversized = dict(summary)
    oversized["diagnostic_samples"] = {"blob": "x" * (MAX_SUMMARY_BYTES + 1)}
    with pytest.raises(ValueError):
        assert_summary_bounded(oversized)
