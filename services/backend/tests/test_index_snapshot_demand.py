"""S3 single-as-of preparation is not a historical constituent series."""

from datetime import date

import pytest

from app.index_snapshot_demand import index_snapshot_scope


def test_scope_is_canonical_bounded_and_never_uses_current_date_for_history() -> None:
    scope = index_snapshot_scope("000905.SH", "2021-09-08", today=date(2026, 9, 8))
    assert scope == {
        "kind": "index_snapshot", "index_symbol": "000905.SH",
        "requested_as_of": "20210908", "start_date": "20210709", "end_date": "20210908",
        "datasets": ["index_weight"], "historical_series": False,
    }
    assert index_snapshot_scope("000905.SH", "20210908", today=date(2026, 9, 8)) == scope


@pytest.mark.parametrize("symbol", ["399905.SZ", "中证500", "000905.sh", "", None, ["000905.SH"]])
def test_rejects_aliases_and_unclosed_index_identity(symbol: object) -> None:
    with pytest.raises(ValueError, match="canonical index"):
        index_snapshot_scope(symbol, "20210908", today=date(2026, 9, 8))


@pytest.mark.parametrize("value", [None, "", "五年前", "2021098", "2021-9-08", "20210229", "2021/09/08", 20210908, True])
def test_requires_an_explicit_real_date_without_coercion(value: object) -> None:
    with pytest.raises(ValueError, match="requested_as_of"):
        index_snapshot_scope("000905.SH", value, today=date(2026, 9, 8))


def test_future_date_is_not_silently_clamped() -> None:
    with pytest.raises(ValueError, match="future"):
        index_snapshot_scope("000905.SH", "20260909", today=date(2026, 9, 8))


def test_inclusive_window_crosses_leap_day_without_exceeding_bound() -> None:
    scope = index_snapshot_scope("000300.SH", "20240301", today=date(2026, 9, 8))
    assert scope["start_date"] == "20231231"
    assert scope["end_date"] == "20240301"


def test_date_underflow_is_a_closed_validation_error() -> None:
    with pytest.raises(ValueError, match="requested_as_of"):
        index_snapshot_scope("000905.SH", "00010101", today=date(2026, 9, 8))


@pytest.mark.parametrize("requested", [None, "", "99991231"])
def test_historical_pool_needs_explicit_nonfuture_date(monkeypatch, requested) -> None:
    from app.stock_pool_producer import StockPoolProducerStore

    store = StockPoolProducerStore.__new__(StockPoolProducerStore)

    def forbidden():
        pytest.fail("invalid historical date reached storage")

    monkeypatch.setattr(store, "_transaction", forbidden)
    payload = {"index_symbol": "000905.SH", "tracking_mode": "historical_snapshot", "idempotency_key": "date-probe"}
    if requested is not None:
        payload["requested_as_of"] = requested
    with pytest.raises(ValueError, match="requested_as_of"):
        store.create_index_pool(payload, trusted_owner="alice", trusted_workspace="workspace-alice")


def test_default_tracking_date_uses_shanghai_not_utc(monkeypatch) -> None:
    from datetime import datetime, timezone
    from app import stock_pool_producer as producer

    class BoundaryClock:
        @staticmethod
        def now(tz):
            return datetime(2026, 9, 8, 16, 30, tzinfo=timezone.utc).astimezone(tz)

    seen = []

    def capture_date(value):
        seen.append(value)
        raise ValueError("date captured before storage")

    monkeypatch.setattr(producer, "datetime", BoundaryClock)
    monkeypatch.setattr(producer, "_date", capture_date)
    store = producer.StockPoolProducerStore.__new__(producer.StockPoolProducerStore)
    with pytest.raises(ValueError, match="date captured"):
        store.create_index_pool({"index_symbol": "000905.SH", "idempotency_key": "clock-probe"},
                                trusted_owner="alice", trusted_workspace="workspace-alice")
    assert seen == ["20260909"]
