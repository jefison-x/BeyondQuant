from __future__ import annotations

import io
import json

import pandas as pd
import pytest

import runner
from bars_frame import encode_bars_frame, encode_research_frame, is_bars_frame

STRATEGY = (
    "class CustomStrategy:\n"
    "    def generate_signals(self, data, parameters=None):\n"
    "        result = {}\n"
    "        for symbol in parameters['symbols']:\n"
    "            index = data.xs(symbol, level='symbol').index\n"
    "            result[symbol] = pd.Series([1] * len(index), index=index)\n"
    "        return result\n"
)

DECLARED: dict[str, object] = {"daily_basic": ["pe_ttm"], "index_universe": None}


def _panel() -> tuple[list[dict[str, object]], list[dict[str, object]], list[float]]:
    bars: list[dict[str, object]] = []
    research: list[dict[str, object]] = []
    multipliers: list[float] = []
    for symbol, offset in (("000001.SZ", 0.0), ("000002.SZ", 1.0)):
        factor = 1.25
        for session in range(1, 6):
            close = round(10.0 + offset + session, 2)
            raw = {
                "symbol": symbol, "trade_date": f"2026-01-{session:02d}",
                "open": close, "high": round(close * 1.01, 2), "low": round(close * 0.99, 2),
                "close": close, "prev_close": round(close - 0.5, 2), "volume": 1000,
                "is_suspended": False, "up_limit": round(close * 1.1, 2),
                "down_limit": round(close * 0.9, 2),
            }
            adjusted = dict(raw)
            for field in ("open", "high", "low", "close", "prev_close", "up_limit", "down_limit"):
                adjusted[field] = round(float(adjusted[field]) * factor, 8)
            adjusted["daily_basic__pe_ttm"] = round(10.0 + session, 4)
            bars.append(raw)
            research.append(adjusted)
            multipliers.append(factor)
    return bars, research, multipliers


def _request(bars: object) -> dict[str, object]:
    return {
        "schema_version": "byq-signal-sandbox-request-v1",
        "profile": "byq-signal-python-v1",
        "runtime_lock": "python-3.13/pandas-2.3.3/numpy-2.3.3",
        "strategy": {"script": STRATEGY},
        "bars": bars,
        "declared": DECLARED,
        "parameters": {"symbols": ["000001.SZ", "000002.SZ"]},
    }


def _run(monkeypatch, payload: dict[str, object]) -> dict[str, object]:
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    monkeypatch.setattr(runner.sys, "stdin", stdin)
    monkeypatch.setattr(runner.sys, "stdout", stdout)
    assert runner.main() == 0
    return json.loads(stdout.getvalue())


def test_legacy_row_dict_document_still_decodes() -> None:
    _, research, _ = _panel()
    frame = runner.build_data(research, DECLARED)
    assert list(frame.index.names) == ["symbol", "trade_date"]
    assert len(frame) == 10
    assert "daily_basic__pe_ttm" in frame.columns


def test_research_frame_decodes_identically_to_legacy_rows() -> None:
    _, research, _ = _panel()
    legacy = runner.build_data(research, DECLARED)
    columnar = runner.build_data(encode_research_frame(research), DECLARED)
    pd.testing.assert_frame_equal(legacy, columnar, check_like=True)


def test_raw_frame_materializes_the_research_view() -> None:
    bars, research, multipliers = _panel()
    raw_frame = encode_bars_frame(bars=bars, research_bars=research, multipliers=multipliers)
    assert is_bars_frame(raw_frame)
    legacy = runner.build_data(research, DECLARED)
    decoded = runner.build_data(raw_frame, DECLARED)
    pd.testing.assert_frame_equal(legacy, decoded, check_like=True)


def test_research_frame_accepts_absolute_adjustment_factor_column() -> None:
    _, research, _ = _panel()
    for row in research:
        row["adjustment_factor"] = 1.25
    frame = runner.build_data(encode_research_frame(research), DECLARED)
    assert "adjustment_factor" in frame.columns
    assert frame["adjustment_factor"].tolist() == [1.25] * len(frame)


def test_research_frame_still_rejects_unknown_bar_columns() -> None:
    _, research, _ = _panel()
    for row in research:
        row["unexpected_column"] = 1.0
    with pytest.raises(runner.ProtocolError, match="bar columns do not match"):
        runner.build_data(encode_research_frame(research), DECLARED)


def test_end_to_end_signals_identical_for_legacy_and_columnar_documents(monkeypatch) -> None:
    bars, research, multipliers = _panel()
    legacy_response = _run(monkeypatch, _request(research))
    research_frame_response = _run(monkeypatch, _request(encode_research_frame(research)))
    raw_frame_response = _run(
        monkeypatch, _request(encode_bars_frame(bars=bars, research_bars=research, multipliers=multipliers))
    )
    assert legacy_response["ok"] is True
    assert legacy_response["signals"]
    assert legacy_response == research_frame_response == raw_frame_response


def _aggregate_panel(symbols: int = 300, sessions: int = 727) -> list[dict[str, object]]:
    from datetime import date, timedelta

    dates: list[str] = []
    cursor = date(2023, 1, 2)
    while len(dates) < sessions:
        if cursor.weekday() < 5:
            dates.append(cursor.isoformat())
        cursor += timedelta(days=1)
    rows: list[dict[str, object]] = []
    for symbol_index in range(symbols):
        symbol = f"{symbol_index:06d}.SZ"
        for trade_date in dates:
            rows.append({
                "symbol": symbol, "trade_date": trade_date, "open": 10.0, "high": 10.0,
                "low": 10.0, "close": 10.0, "volume": 1000,
            })
    return rows


def test_aggregate_300x727_columnar_frame_is_accepted_end_to_end(monkeypatch) -> None:
    rows = _aggregate_panel()
    assert len(rows) == 300 * 727
    parameters = {"symbols": [f"{index:06d}.SZ" for index in range(300)]}
    request = _request(encode_research_frame(rows))
    request["parameters"] = parameters
    response = _run(monkeypatch, request)
    assert response["ok"] is True, response
    assert len(response["signals"]) == 300 * 727


def test_oversized_bars_input_fails_closed(monkeypatch) -> None:
    _, research, _ = _panel()
    monkeypatch.setattr(runner, "MAX_BARS_ROWS", 3)
    response = _run(monkeypatch, _request(encode_research_frame(research)))
    assert response["ok"] is False
    assert response["error_code"] == "invalid_input"


def test_oversized_output_fails_closed(monkeypatch) -> None:
    _, research, _ = _panel()
    monkeypatch.setattr(runner, "MAX_SIGNALS", 3)
    response = _run(monkeypatch, _request(research))
    assert response["ok"] is False
    assert response["error_code"] == "invalid_output"
