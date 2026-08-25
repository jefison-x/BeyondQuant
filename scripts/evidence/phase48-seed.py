#!/usr/bin/env python3
"""Seed only the external prerequisites for the Phase 48 isolated-stack journey."""

from __future__ import annotations

import os

from app.market_data import MarketDataStore
from app.market_automation import MarketAutomationStore
from app.market_readiness import MarketReadinessStore
from app.security_master import SecurityMasterStore
from app.user_auth import UserAuthStore


def main() -> None:
    username = os.environ.get("BYQ_GOLDEN_OTHER_USERNAME", "p48-user")
    password = os.environ.get("BYQ_GOLDEN_OTHER_PASSWORD", "P48UserPass123")
    users = UserAuthStore.from_env()
    listed = users.list_users(actor_role="admin")
    existing = next((item for item in listed["users"] if item["username"] == username), None)
    if existing is None:
        users.create_user(
            {
                "username": username,
                "password": password,
                "display_name": "Phase 48 Secondary User",
                "role": "user",
            },
            actor_role="admin",
        )

    rows = []
    for trade_date, values in (
        ("20260105", (10.0, 10.3, 9.9, 10.1)),
        ("20260106", (10.1, 10.7, 10.0, 10.6)),
        ("20260107", (10.6, 10.9, 10.4, 10.8)),
    ):
        open_price, high, low, close = values
        rows.append(
            {
                "symbol": "000001.SZ",
                "trade_date": trade_date,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1_000_000,
                "amount": 10_500_000,
                "adjust": "none",
                "asset_type": "stock",
                "data_source": "phase48_fixture",
                "volume_unit": "share",
                "amount_unit": "CNY",
                "provenance": {
                    "purpose": "isolated_product_golden_journey",
                    "synthetic": True,
                    "phase": 48,
                },
            }
        )
    MarketDataStore.from_env().import_bars(rows)
    securities = SecurityMasterStore.from_env()
    securities._execute("""INSERT INTO security_master_snapshots
        (snapshot_id,provider,endpoint,dataset_id,request_fingerprint,statuses_json,row_count,
         retrieved_at,requested_by) VALUES ('sms_phase48','fixture','stock_basic','phase48-master',
         'phase48-master-request','[\"L\"]',1,now(),'phase48-evidence')
        ON CONFLICT (dataset_id) DO NOTHING""")
    securities._execute("""INSERT INTO security_master_snapshot_members
        (snapshot_id,symbol,local_symbol,name,exchange,list_status,list_date,asset_type,content_sha256)
        VALUES ('sms_phase48','000001.SZ','000001','平安银行','SZSE','L','19910403','stock','phase48-member')
        ON CONFLICT (snapshot_id,symbol) DO NOTHING""")
    automation = MarketAutomationStore.from_env()
    readiness = MarketReadinessStore.from_env()
    previous = {"20260105": 9.8, "20260106": 10.1, "20260107": 10.6}
    for trade_date in ("20260105", "20260106", "20260107"):
        automation._execute("""INSERT INTO market_trading_sessions
            (trade_date,exchange,is_open,data_source,request_fingerprint,retrieved_at,
             content_sha256,updated_at) VALUES (:date,'SSE',TRUE,'fixture','phase48-calendar',
             now(),:sha,now()) ON CONFLICT (trade_date) DO NOTHING""",
             {"date": trade_date, "sha": f"phase48-calendar-{trade_date}"})
        readiness._execute("""INSERT INTO market_daily_status
            (symbol,trade_date,is_suspended,pre_close,up_limit,down_limit,data_source,
             provenance_json,content_sha256,updated_at)
            VALUES ('000001.SZ',:date,FALSE,:previous,:up,:down,'fixture',
                    '{\"purpose\":\"phase48_golden\"}',:sha,now())
            ON CONFLICT (symbol,trade_date) DO NOTHING""",
            {"date": trade_date, "previous": previous[trade_date],
             "up": round(previous[trade_date] * 1.1, 2), "down": round(previous[trade_date] * .9, 2),
             "sha": f"phase48-status-{trade_date}"})
    print(f"Phase 48 prerequisites ready: user={username}, bars={len(rows)}")


if __name__ == "__main__":
    main()
