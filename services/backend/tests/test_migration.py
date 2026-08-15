from __future__ import annotations

from app.migration import dry_run_market_data_migration


def test_migration_dry_run_emits_manifest_and_quarantine() -> None:
    rows = [
        {
            "symbol": "000001.SZ",
            "trade_date": "20240102",
            "data_source": "tushare",
            "adjust": "none",
            "asset_type": "stock",
            "open": 10.0,
            "high": 11.0,
            "low": 9.8,
            "close": 10.5,
            "volume": 1000,
            "amount": 10500,
            "volume_unit": "lots",
            "amount_unit": "thousand_cny",
        },
        {
            "symbol": "000001",
            "trade_date": "20240102",
            "data_source": "tushare",
            "adjust": "none",
            "asset_type": "stock",
            "open": 10.0,
            "high": 11.0,
            "low": 9.8,
            "close": 10.5,
        },
        {
            "symbol": "000001.SZ",
            "trade_date": "20240102",
            "data_source": "tushare",
            "adjust": "none",
            "asset_type": "stock",
            "open": 10.0,
            "high": 9.0,
            "low": 9.8,
            "close": 10.5,
        },
    ]
    result = dry_run_market_data_migration(
        rows,
        source_repository="BeyondQuant-community",
        source_table="market_data_daily",
        source_filter="data_source = tushare",
        target_dataset="daily_bars",
    )
    assert result["manifest"]["source_row_count"] == 3
    assert result["manifest"]["accepted_row_count"] == 1
    assert result["manifest"]["rejected_row_count"] == 2
    assert result["manifest"]["date_min"] == "20240102"
    assert result["manifest"]["date_max"] == "20240102"
    assert len(result["quarantine"]) == 2


def test_migration_dry_run_rejects_secret_and_non_finite_material() -> None:
    rows = [
        {
            "symbol": "000001.SZ",
            "trade_date": "20240102",
            "data_source": "tushare",
            "adjust": "none",
            "asset_type": "stock",
            "open": float("nan"),
            "high": 11.0,
            "low": 9.8,
            "close": 10.5,
        }
    ]
    result = dry_run_market_data_migration(
        rows,
        source_repository="BeyondQuant-community",
        source_table="market_data_daily",
        source_filter="data_source = tushare",
        target_dataset="daily_bars",
    )
    assert result["manifest"]["accepted_row_count"] == 0
    assert any("finite" in reason for item in result["quarantine"] for reason in item["reasons"])
