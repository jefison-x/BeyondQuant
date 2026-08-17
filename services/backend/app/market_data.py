"""BYQ durable market-data target (ADR-0013) on PostgreSQL.

Owns canonical daily-bar rows with provenance. Imports reuse the ADR-0016 /
ADR-0013 conflict policy (KEEP_NEW / VERIFY_EQUAL / REPORT_MISMATCH) so existing
BYQ records are never overwritten by last-write-wins. Community PostgreSQL is
never a source here; imports consume validated read-only audit snapshots.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, execute, fetch_one
from .pg_import import KEEP_NEW, VERIFY_EQUAL, REPORT_MISMATCH, CONFLICT_POLICIES


class MarketDataError(RuntimeError):
    pass


class MarketDataConflict(MarketDataError):
    pass


class MarketDataPersistenceError(MarketDataError):
    pass


class MarketDataStore(PgStoreMixin):
    """Canonical durable daily-bar store with migration conflict policy."""

    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS market_daily_bars (
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            open DOUBLE PRECISION NOT NULL,
            high DOUBLE PRECISION NOT NULL,
            low DOUBLE PRECISION NOT NULL,
            close DOUBLE PRECISION NOT NULL,
            volume DOUBLE PRECISION,
            amount DOUBLE PRECISION,
            adjust TEXT NOT NULL DEFAULT 'none',
            asset_type TEXT NOT NULL,
            data_source TEXT NOT NULL,
            volume_unit TEXT,
            amount_unit TEXT,
            content_sha256 TEXT NOT NULL,
            provenance_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            imported_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (symbol, trade_date)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS market_daily_bars_date_idx
            ON market_daily_bars(trade_date)
        """,
        """
        CREATE INDEX IF NOT EXISTS market_daily_bars_source_idx
            ON market_daily_bars(data_source)
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as error:
            raise MarketDataPersistenceError("market data storage is unavailable") from error

    @classmethod
    def from_env(cls) -> "MarketDataStore":
        return cls()

    @staticmethod
    def _content_sha256(row: dict[str, Any]) -> str:
        canonical = json.dumps(
            {key: row[key] for key in sorted(row) if key not in {"content_sha256", "imported_at", "provenance_json"}},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def import_bars(self, rows: list[dict[str, Any]], *, conflict_policy: str = KEEP_NEW) -> dict[str, Any]:
        """Idempotent import of validated daily-bar rows (never last-write-wins)."""
        if conflict_policy not in CONFLICT_POLICIES:
            raise ValueError(f"conflict_policy must be one of {sorted(CONFLICT_POLICIES)}")
        inserted = 0
        kept = 0
        mismatches: list[dict[str, Any]] = []
        with self._transaction() as connection:
            for row in rows:
                symbol = row["symbol"]
                trade_date = row["trade_date"]
                content_sha256 = self._content_sha256(row)
                existing = fetch_one(
                    connection,
                    "SELECT content_sha256 FROM market_daily_bars WHERE symbol = :symbol AND trade_date = :trade_date",
                    {"symbol": symbol, "trade_date": trade_date},
                )
                if existing is not None:
                    if conflict_policy in {VERIFY_EQUAL, REPORT_MISMATCH} and existing["content_sha256"] != content_sha256:
                        mismatches.append({
                            "symbol": symbol,
                            "trade_date": trade_date,
                            "reason": "verify_equal_mismatch" if conflict_policy == VERIFY_EQUAL else "conflict_reported",
                        })
                    kept += 1
                    continue
                provenance = row.get("provenance") or {}
                if not isinstance(provenance, dict):
                    raise ValueError("provenance must be an object")
                execute(
                    connection,
                    """INSERT INTO market_daily_bars
                    (symbol, trade_date, open, high, low, close, volume, amount,
                     adjust, asset_type, data_source, volume_unit, amount_unit,
                     content_sha256, provenance_json, imported_at)
                    VALUES (:symbol, :trade_date, :open, :high, :low, :close, :volume, :amount,
                            :adjust, :asset_type, :data_source, :volume_unit, :amount_unit,
                            :content_sha256, :provenance_json, now())""",
                    {
                        "symbol": symbol,
                        "trade_date": trade_date,
                        "open": row["open"],
                        "high": row["high"],
                        "low": row["low"],
                        "close": row["close"],
                        "volume": row.get("volume"),
                        "amount": row.get("amount"),
                        "adjust": row.get("adjust", "none"),
                        "asset_type": row["asset_type"],
                        "data_source": row["data_source"],
                        "volume_unit": row.get("volume_unit"),
                        "amount_unit": row.get("amount_unit"),
                        "content_sha256": content_sha256,
                        "provenance_json": provenance,
                    },
                )
                inserted += 1
        return {"inserted": inserted, "kept": kept, "reported": len(mismatches), "mismatches": mismatches}

    def get_bar(self, symbol: object, trade_date: object) -> dict[str, Any] | None:
        row = self._fetch_one(
            "SELECT * FROM market_daily_bars WHERE symbol = :symbol AND trade_date = :trade_date",
            {"symbol": str(symbol), "trade_date": str(trade_date)},
        )
        if row is None:
            return None
        result = dict(row)
        result["provenance"] = result.pop("provenance_json") or {}
        return result

    def coverage(self) -> dict[str, Any]:
        rows = self._execute(
            """SELECT data_source, asset_type, COUNT(*) AS row_count, MIN(trade_date) AS date_min,
                      MAX(trade_date) AS date_max, COUNT(DISTINCT symbol) AS symbol_count
               FROM market_daily_bars GROUP BY data_source, asset_type ORDER BY data_source, asset_type"""
        )
        return {"groups": rows}
