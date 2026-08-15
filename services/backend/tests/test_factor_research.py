from __future__ import annotations

import pytest

from app.factor_research import FactorValidationError, compute_factor, prepare_factor_input


def factor_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "task_id": "task_0123456789abcdef0123456789abcdef",
        "trace_id": "byq-trace-factor-1",
        "idempotency_key": "factor-compute-1",
        "as_of_date": "20260815",
        "factor": {"name": "daily_return", "version": "1", "lookback": 1},
        "securities": [
            {"symbol": "000001.SZ", "asset_type": "stock", "list_date": "20200101"},
        ],
        "sessions": [
            {"trade_date": "20260812", "is_open": False},
            {"trade_date": "20260813", "is_open": True},
            {"trade_date": "20260814", "is_open": True},
            {"trade_date": "20260815", "is_open": True},
        ],
        "statuses": [],
        "bars": [
            {"symbol": "000001.SZ", "trade_date": "20260813", "open": 10, "high": 11, "low": 9, "close": 10},
            {"symbol": "000001.SZ", "trade_date": "20260814", "open": 10, "high": 12, "low": 9, "close": 11},
            {"symbol": "000001.SZ", "trade_date": "20260815", "open": 11, "high": 13, "low": 10, "close": 12},
        ],
        "universe_snapshots": [
            {"snapshot_date": "20260814", "symbols": ["000001.SZ"]},
            {"snapshot_date": "20260815", "symbols": ["000001.SZ"]},
        ],
        "sources": [
            {
                "provider": "tushare",
                "endpoint": "daily",
                "request_fingerprint": "daily-fixture-1",
                "dataset_id": "dataset-daily-1",
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_factor_is_deterministic_and_uses_latest_visible_universe() -> None:
    first = compute_factor(factor_payload())
    second_payload = factor_payload(
        bars=list(reversed(factor_payload()["bars"])),  # type: ignore[arg-type]
        sessions=list(reversed(factor_payload()["sessions"])),  # type: ignore[arg-type]
        sources=list(reversed(factor_payload()["sources"])),  # type: ignore[arg-type]
    )
    second = compute_factor(second_payload)

    assert first["input_manifest"] == second["input_manifest"]
    assert first["factor"]["input_manifest_id"] == second["factor"]["input_manifest_id"]
    assert first["factor"]["selected_universe_snapshot_date"] == "20260815"
    assert first["factor"]["computation"] == {
        "engine": "byq-native-factor",
        "engine_version": "1",
        "algorithm": "close_to_close",
    }
    assert first["factor"]["evaluation"]["count"] == 2
    assert first["factor"]["evaluation"]["mean"] == pytest.approx((0.1 + 1 / 11) / 2)
    assert [row["value"] for row in first["factor"]["observations"]] == pytest.approx([0.1, 1 / 11])


def test_missing_active_bar_is_not_silently_treated_as_suspension() -> None:
    payload = factor_payload(bars=factor_payload()["bars"][:-1])  # type: ignore[index]
    with pytest.raises(FactorValidationError, match="missing bars"):
        prepare_factor_input(payload)


def test_suspension_is_classified_and_does_not_count_as_missing() -> None:
    bars = factor_payload()["bars"][:-1]  # type: ignore[index]
    payload = factor_payload(
        bars=bars,
        statuses=[{"symbol": "000001.SZ", "trade_date": "20260815", "state": "suspended", "reason": "停牌"}],
    )
    result = compute_factor(payload)
    assert result["coverage"] == {
        "present": 2,
        "missing": 0,
        "not_listed": 0,
        "delisted": 0,
        "suspended": 1,
        "non_trading": 1,
    }


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"securities": [{"symbol": "000001", "asset_type": "stock"}]}, "explicit"),
        ({"bars": factor_payload()["bars"] + [factor_payload()["bars"][0]]}, "duplicate daily bars"),  # type: ignore[operator,index]
        ({"sources": [{**factor_payload()["sources"][0], "announcement_date": "20260816"}]}, "look-ahead"),  # type: ignore[index]
    ],
)
def test_factor_boundary_rejects_ambiguous_or_future_inputs(change: dict[str, object], message: str) -> None:
    with pytest.raises(FactorValidationError, match=message):
        prepare_factor_input({**factor_payload(), **change})


def test_ohlc_quality_and_future_universe_are_rejected() -> None:
    bad_bar = [
        {"symbol": "000001.SZ", "trade_date": "20260813", "open": 10, "high": 9, "low": 9, "close": 10},
    ]
    with pytest.raises(FactorValidationError, match="high"):
        prepare_factor_input(factor_payload(bars=bad_bar))
    with pytest.raises(FactorValidationError, match="look-ahead"):
        prepare_factor_input(factor_payload(universe_snapshots=[{"snapshot_date": "20260816", "symbols": ["000001.SZ"]}]))
