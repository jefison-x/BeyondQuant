#!/usr/bin/env python3
"""Seed complete point-in-time inputs for the isolated Phase 68 browser journey."""

from datetime import datetime, timezone

from app.stock_pool_producer import StockPoolProducerStore


def main() -> None:
    store = StockPoolProducerStore.from_env()
    retrieved = datetime(2026, 8, 28, 8, tzinfo=timezone.utc)
    store._execute("""INSERT INTO security_master_snapshots
        (snapshot_id,provider,endpoint,dataset_id,request_fingerprint,statuses_json,row_count,
         quarantined_count,retrieved_at,requested_by,created_at)
        VALUES ('phase68-security','tushare','stock_basic','phase68-security-dataset','phase68-request',
                :statuses,3,0,:retrieved,'phase68-evidence',:retrieved)
        ON CONFLICT(snapshot_id) DO NOTHING""", {"statuses": ["L"], "retrieved": retrieved})
    rows = (
        ("000001.SZ", "SZSE", "银行", 1850.0, 1.1),
        ("600000.SH", "SSE", "银行", 1250.0, 0.7),
        ("300750.SZ", "SZSE", "电池", 9800.0, 4.6),
    )
    for symbol, exchange, industry, total_mv, pb in rows:
        store._execute("""INSERT INTO security_master_snapshot_members
            (snapshot_id,symbol,local_symbol,name,area,industry,market,exchange,list_status,list_date,
             delist_date,is_hs,asset_type,content_sha256)
            VALUES ('phase68-security',:symbol,substring(:symbol,1,6),:symbol,'中国',:industry,'主板',
                    :exchange,'L','20000101',NULL,'N','stock',:hash)
            ON CONFLICT(snapshot_id,symbol) DO NOTHING""",
            {"symbol": symbol, "industry": industry, "exchange": exchange, "hash": f"phase68-security-{symbol}"})
        store._execute("""INSERT INTO market_daily_basic
            (symbol,trade_date,values_json,data_source,provenance_json,content_sha256,updated_at)
            VALUES (:symbol,'20260828',:values,'tushare',:provenance,:hash,now())
            ON CONFLICT(symbol,trade_date) DO UPDATE SET values_json=excluded.values_json,
              provenance_json=excluded.provenance_json,content_sha256=excluded.content_sha256,updated_at=excluded.updated_at""",
            {"symbol": symbol, "values": {"total_mv": total_mv, "pb": pb},
             "provenance": {"purpose": "phase68_browser_evidence", "provider": "tushare"},
             "hash": f"phase68-basic-{symbol}"})
    store._execute("""INSERT INTO market_trading_sessions
        (trade_date,exchange,is_open,previous_open_date,data_source,request_fingerprint,retrieved_at,
         content_sha256,updated_at) VALUES ('20260828','SSE',TRUE,'20260827','tushare','phase68-calendar',
         now(),'phase68-calendar-20260828',now()) ON CONFLICT(trade_date) DO UPDATE SET
         is_open=TRUE,content_sha256=excluded.content_sha256,updated_at=excluded.updated_at""")
    store._execute("""INSERT INTO market_daily_basic_completeness
        (trade_date,row_count,content_sha256,provenance_json,verified_at)
        VALUES ('20260828',3,'phase68-basic-complete',:provenance,now())
        ON CONFLICT(trade_date) DO UPDATE SET row_count=excluded.row_count,
          content_sha256=excluded.content_sha256,provenance_json=excluded.provenance_json,
          verified_at=excluded.verified_at""",
        {"provenance": {"purpose": "phase68_browser_evidence", "provider": "tushare"}})
    store.close()
    print("Phase 68 dynamic inputs ready: 20260828 rows=3")


if __name__ == "__main__":
    main()
