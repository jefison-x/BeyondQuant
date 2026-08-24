#!/usr/bin/env python3
"""Seed only the external prerequisites for the Phase 48 isolated-stack journey."""

from __future__ import annotations

import os

from app.market_data import MarketDataStore
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
    print(f"Phase 48 prerequisites ready: user={username}, bars={len(rows)}")


if __name__ == "__main__":
    main()
