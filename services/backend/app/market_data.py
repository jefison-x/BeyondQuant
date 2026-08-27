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
            pre_close DOUBLE PRECISION,
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
        ALTER TABLE market_daily_bars
            ADD COLUMN IF NOT EXISTS pre_close DOUBLE PRECISION
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
                     pre_close,
                     adjust, asset_type, data_source, volume_unit, amount_unit,
                     content_sha256, provenance_json, imported_at)
                    VALUES (:symbol, :trade_date, :open, :high, :low, :close, :volume, :amount,
                            :pre_close,
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
                        "pre_close": row.get("pre_close"),
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

    def latest_trade_date(self, symbol: object) -> str | None:
        normalized = str(symbol).strip().upper()
        row = self._fetch_one(
            "SELECT MAX(trade_date) AS trade_date FROM market_daily_bars WHERE symbol = :symbol",
            {"symbol": normalized},
        )
        return None if row is None or row.get("trade_date") is None else str(row["trade_date"])

    def list_bars(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        *,
        limit: int = 50_000,
    ) -> list[dict[str, Any]]:
        """Read a bounded canonical bar window for an already-frozen universe.

        This is intentionally a direct Data Plane query, not a provider fallback:
        signal jobs must freeze durable BYQ rows before any strategy source runs.
        """
        normalized_symbols = sorted({str(value).strip().upper() for value in symbols if str(value).strip()})
        if not normalized_symbols:
            raise ValueError("symbols must be a non-empty list")
        if len(normalized_symbols) > 2_000:
            raise ValueError("symbols exceeds 2000 entries")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 50_000:
            raise ValueError("limit must be between 1 and 50000")
        if not isinstance(start_date, str) or not isinstance(end_date, str):
            raise ValueError("start_date and end_date must be strings")
        start = start_date.replace("-", "")
        end = end_date.replace("-", "")
        if len(start) != 8 or not start.isdigit() or len(end) != 8 or not end.isdigit() or start > end:
            raise ValueError("date range must be valid YYYY-MM-DD or YYYYMMDD values")
        rows = self._execute(
            """SELECT symbol, trade_date, open, high, low, close, pre_close, volume, amount,
                      adjust, asset_type, data_source, volume_unit, amount_unit,
                      content_sha256, provenance_json
               FROM market_daily_bars
               WHERE symbol IN (SELECT jsonb_array_elements_text(:symbols_json))
                 AND trade_date >= :start_date AND trade_date <= :end_date
               ORDER BY trade_date, symbol
               LIMIT :query_limit""",
            {
                "symbols_json": normalized_symbols,
                "start_date": start,
                "end_date": end,
                "query_limit": limit + 1,
            },
        )
        if len(rows) > limit:
            raise ValueError(f"market bar window exceeds {limit} rows")
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["provenance"] = item.pop("provenance_json") or {}
            result.append(item)
        return result

    def research_daily(self, request: object) -> dict[str, Any]:
        """Read one bounded durable series without a provider fallback."""
        normalized = request.normalized()
        start = normalized.trade_date or normalized.start_date
        end = normalized.trade_date or normalized.end_date
        assert start is not None and end is not None
        params: dict[str, Any] = {"start": start, "end": end}
        symbol_clause = ""
        if normalized.ts_code:
            symbol_clause = " AND symbol=:symbol"
            params["symbol"] = normalized.ts_code
        rows = self._execute(
            f"""SELECT symbol,trade_date,open,high,low,close,pre_close,volume,amount,
                       data_source,content_sha256,provenance_json
                FROM market_daily_bars
                WHERE trade_date BETWEEN :start AND :end{symbol_clause}
                  AND data_source='tushare'
                ORDER BY trade_date,symbol LIMIT 6001""",
            params,
        )
        if len(rows) > 6000:
            raise ValueError("daily research result exceeds 6000 rows")
        sessions = [str(row["trade_date"]) for row in self._execute(
            """SELECT trade_date FROM market_trading_sessions
               WHERE is_open=TRUE AND trade_date BETWEEN :start AND :end ORDER BY trade_date""",
            {"start": start, "end": end},
        )]
        statuses = self._execute(
            f"""SELECT symbol,trade_date,is_suspended FROM market_daily_status
                WHERE trade_date BETWEEN :start AND :end{symbol_clause}""",
            params,
        )
        status_map = {(str(row["symbol"]), str(row["trade_date"])): bool(row["is_suspended"]) for row in statuses}
        symbols = [normalized.ts_code] if normalized.ts_code else sorted({str(row["symbol"]) for row in rows})
        bar_keys = {(str(row["symbol"]), str(row["trade_date"])) for row in rows}
        missing: list[dict[str, str]] = []
        for symbol in symbols:
            if symbol is None:
                continue
            for trade_date in sessions:
                if (symbol, trade_date) in bar_keys or status_map.get((symbol, trade_date)) is True:
                    continue
                missing.append({"symbol": symbol, "trade_date": trade_date, "reason": "daily_bar_unavailable"})
        data: list[dict[str, Any]] = []
        for row in rows:
            pre_close = row.get("pre_close")
            change = None if pre_close is None else float(row["close"]) - float(pre_close)
            pct_chg = None if pre_close in {None, 0} else change / float(pre_close) * 100
            data.append({
                "ts_code": str(row["symbol"]), "trade_date": str(row["trade_date"]),
                "open": row["open"], "high": row["high"], "low": row["low"], "close": row["close"],
                "pre_close": pre_close, "change": change, "pct_chg": pct_chg,
                "vol": row.get("volume"), "amount": row.get("amount"),
                "content_sha256": str(row["content_sha256"]),
            })
        latest = max((str(row["trade_date"]) for row in rows), default=None)
        return {
            "schema_version": "market-daily-research.v1",
            "data": data,
            "provenance": {
                "source": "persisted_byq", "provider": "tushare", "endpoint": "durable_daily",
                "requested_start_date": start, "requested_end_date": end,
                "latest_trade_date": latest, "row_count": len(data), "live_provider_called": False,
            },
            "coverage": {
                "usable": bool(sessions) and not missing,
                "calendar_verified": bool(sessions), "requested_sessions": sessions,
                "returned_rows": len(data), "missing": missing[:200],
            },
        }

    def coverage(self) -> dict[str, Any]:
        rows = self._execute(
            """SELECT data_source, asset_type, COUNT(*) AS row_count, MIN(trade_date) AS date_min,
                      MAX(trade_date) AS date_max, COUNT(DISTINCT symbol) AS symbol_count
               FROM market_daily_bars GROUP BY data_source, asset_type ORDER BY data_source, asset_type"""
        )
        return {"groups": rows}
