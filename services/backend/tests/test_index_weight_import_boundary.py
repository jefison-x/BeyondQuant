"""Reject misrouted historical input before any destructive import transaction."""

import pytest

from app.data_provider import IndexWeight
from app.market_readiness import MarketReadinessStore


@pytest.mark.parametrize("index,period,item", [
    ("000300.SH", "202401", IndexWeight("000905.SH", "000001.SZ", "20240131", 100)),
    ("000300.SH", "202401", IndexWeight("000300.SH", "000001.SZ", "20240201", 100)),
    ("000300.SH", "202402", IndexWeight("000300.SH", "000001.SZ", "20240230", 100)),
    ("000300.SH", "20241", IndexWeight("000300.SH", "000001.SZ", "20240131", 100)),
    ("000300.SH", "202400", IndexWeight("000300.SH", "000001.SZ", "20240131", 100)),
    ("000300.SH", "202401", IndexWeight("000300.SH", "000001.SZ", "2024-01-31", 100)),
])
def test_wrong_index_or_month_never_reaches_storage(monkeypatch, index, period, item) -> None:
    store = MarketReadinessStore.__new__(MarketReadinessStore)

    def forbidden_transaction():
        pytest.fail("invalid index input reached a storage transaction")

    monkeypatch.setattr(store, "_transaction", forbidden_transaction)
    with pytest.raises(ValueError, match="index weight"):
        store.import_index_weights(index, period, [item], {"provider": "tushare"})
