from __future__ import annotations

import pytest

from app.market_readiness import MarketReadinessStore


@pytest.mark.parametrize("dividend_value", [4.6398, None])
def test_valuation_evidence_separates_one_requested_stock_from_dataset_size(dividend_value) -> None:
    store = object.__new__(MarketReadinessStore)
    store._fetch_one = lambda *_: {
        "row_count": 5573, "content_sha256": "dataset", "verified_at": "2026-11-18T01:20:00Z",
    }
    store._execute = lambda *_: [{
        "symbol": "600036.SH", "trade_date": "20261117", "data_source": "tushare",
        "content_sha256": "row", "values_json": {"pe_ttm": 7.1675, "dv_ttm": dividend_value},
    }]

    result = store.research_valuation(
        symbols=["600036.SH"], trade_date="2026-11-17", fields=["pe_ttm", "dv_ttm"],
    )

    # Keep the existing complete=dataset-present contract; usable checks the selection.
    assert result["coverage"]["complete"] is True
    assert result["coverage"]["usable"] is (dividend_value is not None)
    assert result["coverage"]["dataset_row_count"] == 5573
    assert result["coverage"]["complete_scope"] == "date_dataset_snapshot_present"
    assert result["coverage"]["usable_scope"] == "requested_symbols_and_fields"
    scope = result["evidence_scope"]
    assert scope["requested_symbols"] == ["600036.SH"]
    assert scope["requested_fields"] == ["pe_ttm", "dv_ttm"]
    assert scope["outside_requested_symbols_checked"] is False
    assert scope["all_market_field_completeness_verified"] is False
    assert scope["dataset_row_count_basis"] == "stored_rows_not_non_null_field_count"
    semantics = result["field_semantics"]["dv_ttm"]
    assert semantics["label"] == "股息率（TTM）"
    assert semantics["unit"] == "percent"
    assert semantics["calculation_basis"] == "unverified"
    assert semantics["implemented_distributions"] == "unverified"
    assert semantics["payout_ratio"] is False
    assert result["rows"][0]["values"]["dv_ttm"] == dividend_value


def test_valuation_evidence_does_not_add_unrequested_dividend_fields() -> None:
    store = object.__new__(MarketReadinessStore)
    store._fetch_one = lambda *_: None
    store._execute = lambda *_: []
    result = store.research_valuation(
        symbols=["600036.SH"], trade_date="20261117", fields=["pb"],
    )
    assert result["coverage"]["complete"] is False
    assert result["coverage"]["usable"] is False
    assert result["coverage"]["missing_symbols"] == ["600036.SH"]
    assert result["field_semantics"] == {}
    assert result["evidence_scope"]["requested_fields"] == ["pb"]
