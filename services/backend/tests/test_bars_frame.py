from __future__ import annotations

import json
import math
import random

import pytest

from packages.contracts.bars_frame import (
    BARS_FRAME_SCHEMA_VERSION,
    decode_bars_frame,
    encode_bars_frame,
    encode_research_frame,
    frame_raw_rows,
    frame_research_rows,
    frame_row_count,
    is_bars_frame,
)

MI_BYTES = 1024 * 1024


def _panel(symbols: int, sessions: int) -> tuple[list[dict[str, object]], list[dict[str, object]], list[float]]:
    rng = random.Random(20260918)
    bars: list[dict[str, object]] = []
    research: list[dict[str, object]] = []
    multipliers: list[float] = []
    for symbol_index in range(symbols):
        symbol = f"{symbol_index:06d}.SZ"
        factor = round(rng.uniform(0.9, 1.1), 6)
        for session in range(sessions):
            trade_date = f"2023-{1 + session // 28:02d}-{1 + session % 28:02d}"
            close = round(rng.uniform(5.0, 80.0), 2)
            raw = {
                "symbol": symbol, "trade_date": trade_date,
                "open": round(close * 0.99, 2), "high": round(close * 1.01, 2),
                "low": round(close * 0.98, 2), "close": close,
                "prev_close": round(close * 0.995, 2),
                "volume": rng.randint(1_000, 5_000_000), "is_suspended": False,
                "up_limit": round(close * 1.1, 2), "down_limit": round(close * 0.9, 2),
            }
            adjusted = dict(raw)
            for field in ("open", "high", "low", "close", "prev_close", "up_limit", "down_limit"):
                adjusted[field] = round(float(adjusted[field]) * factor, 8)
            adjusted["daily_basic__pe_ttm"] = round(rng.uniform(5.0, 50.0), 4)
            adjusted["is_universe_member"] = bool(session % 2)
            bars.append(raw)
            research.append(adjusted)
            multipliers.append(factor)
    return bars, research, multipliers


def test_raw_frame_round_trips_both_panels() -> None:
    bars, research, multipliers = _panel(3, 5)
    frame = encode_bars_frame(bars=bars, research_bars=research, multipliers=multipliers)
    assert frame["schema_version"] == BARS_FRAME_SCHEMA_VERSION
    assert frame["basis"] == "raw"
    assert frame_row_count(frame) == len(bars)
    assert frame_raw_rows(frame) == sorted(bars, key=lambda row: (row["symbol"], row["trade_date"]))
    assert frame_research_rows(frame) == sorted(research, key=lambda row: (row["symbol"], row["trade_date"]))


def test_raw_frame_excludes_research_only_fields_from_raw_panel() -> None:
    bars, research, multipliers = _panel(2, 3)
    frame = encode_bars_frame(bars=bars, research_bars=research, multipliers=multipliers)
    raw_keys = {field for row in frame_raw_rows(frame) for field in row}
    research_keys = {field for row in frame_research_rows(frame) for field in row}
    assert "daily_basic__pe_ttm" not in raw_keys
    assert "daily_basic__pe_ttm" in research_keys
    assert raw_keys <= research_keys


def test_research_frame_decodes_to_input_panel() -> None:
    bars, research, _ = _panel(3, 4)
    frame = encode_research_frame(research)
    assert frame["basis"] == "research"
    assert frame_research_rows(frame) == sorted(research, key=lambda row: (row["symbol"], row["trade_date"]))
    with pytest.raises(ValueError):
        frame_raw_rows(frame)


def test_encoding_is_deterministic_across_row_order() -> None:
    bars, research, multipliers = _panel(4, 6)
    shuffled = list(range(len(bars)))
    random.Random(7).shuffle(shuffled)
    shuffled_bars = [bars[index] for index in shuffled]
    shuffled_research = [research[index] for index in shuffled]
    shuffled_multipliers = [multipliers[index] for index in shuffled]
    first = encode_bars_frame(bars=bars, research_bars=research, multipliers=multipliers)
    second = encode_bars_frame(
        bars=shuffled_bars, research_bars=shuffled_research, multipliers=shuffled_multipliers,
    )
    assert first == second
    canonical = lambda value: json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    assert canonical(first) == canonical(second)


def test_encoder_fails_closed_when_multiplier_cannot_reproduce_research() -> None:
    bars, research, multipliers = _panel(2, 3)
    research = [dict(row) for row in research]
    research[0]["close"] = float(research[0]["close"]) + 1.0
    with pytest.raises(ValueError, match="cannot reproduce close"):
        encode_bars_frame(bars=bars, research_bars=research, multipliers=multipliers)


def test_frame_rejects_non_finite_values() -> None:
    bars, research, multipliers = _panel(1, 2)
    bars = [dict(row) for row in bars]
    bars[0]["close"] = math.inf
    with pytest.raises(ValueError, match="finite"):
        encode_bars_frame(bars=bars, research_bars=research, multipliers=multipliers)


def test_large_panel_encoded_frame_is_under_input_bound() -> None:
    bars, research, multipliers = _panel(300, 727)
    raw_frame = encode_bars_frame(bars=bars, research_bars=research, multipliers=multipliers)
    research_frame = encode_research_frame(research)
    raw_bytes = len(json.dumps(raw_frame, allow_nan=False, sort_keys=True, separators=(",", ":")).encode())
    research_bytes = len(
        json.dumps(research_frame, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    )
    legacy_bytes = len(
        json.dumps(
            {"bars": bars, "research_bars": research},
            allow_nan=False, sort_keys=True, separators=(",", ":"),
        ).encode()
    )
    assert frame_row_count(raw_frame) == 300 * 727
    assert raw_bytes < 32 * MI_BYTES
    assert research_bytes < 32 * MI_BYTES
    assert raw_bytes < legacy_bytes
    print(
        f"\nlarge panel rows={frame_row_count(raw_frame)} "
        f"legacy={legacy_bytes / MI_BYTES:.2f}MiB raw_frame={raw_bytes / MI_BYTES:.2f}MiB "
        f"research_frame={research_bytes / MI_BYTES:.2f}MiB"
    )


def test_legacy_document_shape_is_not_mistaken_for_a_frame() -> None:
    assert not is_bars_frame([{"symbol": "000001.SZ"}])
    assert not is_bars_frame({"schema_version": "byq-signal-sandbox-request-v1"})
    assert is_bars_frame(encode_research_frame(_panel(1, 1)[1]))
