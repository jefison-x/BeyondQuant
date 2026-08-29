#!/usr/bin/env python3
"""Seed validated canonical index weights for the isolated Phase 67 browser journey."""

from app.market_readiness import MarketReadinessStore


def main() -> None:
    store = MarketReadinessStore.from_env()
    for symbol, weight in (("000001.SZ", 60.0), ("600000.SH", 40.0)):
        store._execute("""INSERT INTO market_index_weights
            (index_symbol,constituent_symbol,snapshot_date,weight,data_source,provenance_json,
             content_sha256,updated_at) VALUES
            ('000300.SH',:symbol,'20260828',:weight,'tushare',:provenance,:hash,now())
            ON CONFLICT(index_symbol,constituent_symbol,snapshot_date) DO UPDATE SET
              weight=excluded.weight,provenance_json=excluded.provenance_json,
              content_sha256=excluded.content_sha256,updated_at=excluded.updated_at""",
            {"symbol": symbol, "weight": weight,
             "provenance": {"purpose": "phase67_browser_evidence", "provider": "tushare"},
             "hash": f"phase67-20260828-{symbol}"})
    store._execute("""INSERT INTO market_index_weight_completeness
        (index_symbol,period,row_count,content_sha256,provenance_json,verified_at)
        VALUES ('000300.SH','202608',2,'phase67-index-complete',:provenance,now())
        ON CONFLICT(index_symbol,period) DO UPDATE SET row_count=excluded.row_count,
          content_sha256=excluded.content_sha256,provenance_json=excluded.provenance_json,
          verified_at=excluded.verified_at""",
        {"provenance": {"purpose": "phase67_browser_evidence", "provider": "tushare"}})
    store.close()
    print("Phase 67 validated index weights ready: 000300.SH@20260828 rows=2")


if __name__ == "__main__":
    main()
