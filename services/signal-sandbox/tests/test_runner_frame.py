from __future__ import annotations

import io
import json

import pandas as pd

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
