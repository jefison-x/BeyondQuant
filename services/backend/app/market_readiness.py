"""Typed, lifecycle-aware market-input readiness contracts (ADR-0028)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, execute


SCHEMA_VERSION = "market-data-requirement.v1"
REQUIRED_DATASETS = ("stock_daily", "trading_status", "price_limits")
MAX_REQUIRED_CELLS = 50_000


class MarketReadinessPersistenceError(RuntimeError):
    pass


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


class MarketReadinessStore(PgStoreMixin):
    SCHEMA_DDL = [
        """
        CREATE TABLE IF NOT EXISTS market_daily_status (
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            is_suspended BOOLEAN NOT NULL,
            suspend_timing TEXT,
            pre_close DOUBLE PRECISION,
            up_limit DOUBLE PRECISION,
            down_limit DOUBLE PRECISION,
            data_source TEXT NOT NULL,
            provenance_json JSONB NOT NULL,
            content_sha256 TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (symbol, trade_date)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS market_daily_status_date_idx
            ON market_daily_status(trade_date, symbol)
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as error:
            raise MarketReadinessPersistenceError("market readiness storage is unavailable") from error

    @classmethod
    def from_env(cls) -> "MarketReadinessStore":
        return cls()

    @staticmethod
    def requirement(
        *, symbols: list[str], start_date: str, end_date: str,
        membership_fingerprint: str, security_master_snapshot_id: str,
    ) -> dict[str, object]:
        normalized = sorted({str(item).strip().upper() for item in symbols if str(item).strip()})
        if not normalized or len(normalized) > 2_000:
            raise ValueError("data requirement symbols must contain between 1 and 2000 entries")
        start, end = start_date.replace("-", ""), end_date.replace("-", "")
        try:
            if datetime.strptime(start, "%Y%m%d") > datetime.strptime(end, "%Y%m%d"):
                raise ValueError
        except ValueError as error:
            raise ValueError("data requirement date range is invalid") from error
        document: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "symbols": normalized,
            "start_date": start,
            "end_date": end,
            "datasets": list(REQUIRED_DATASETS),
            "calendar": "SSE",
            "membership_fingerprint": membership_fingerprint,
            "security_master_snapshot_id": security_master_snapshot_id,
        }
        document["requirement_sha256"] = _hash(document)
        return document

    def import_session_status(
        self, trade_date: str, *, daily_symbols: set[str], limits: list[object],
        suspensions: list[object], provenance: dict[str, object],
    ) -> int:
        limit_map = {str(getattr(item, "ts_code")): item for item in limits}
        suspended = {
            str(getattr(item, "ts_code")): item
            for item in suspensions if str(getattr(item, "suspend_type")) == "S"
        }
        # A resume record is not a suspension. Daily/limit rows prove active trading;
        # S rows prove an intentional absence of a bar.
        symbols = sorted(set(daily_symbols) | set(limit_map) | set(suspended))
        with self._transaction() as connection:
            for symbol in symbols:
                limit = limit_map.get(symbol)
                suspension = suspended.get(symbol)
                row = {
                    "symbol": symbol, "trade_date": trade_date,
                    "is_suspended": suspension is not None,
                    "suspend_timing": getattr(suspension, "suspend_timing", None),
                    "pre_close": getattr(limit, "pre_close", None),
                    "up_limit": getattr(limit, "up_limit", None),
                    "down_limit": getattr(limit, "down_limit", None),
                    "data_source": "tushare", "provenance": provenance,
                }
                content_sha256 = _hash(row)
                execute(connection, """INSERT INTO market_daily_status
                    (symbol, trade_date, is_suspended, suspend_timing, pre_close,
                     up_limit, down_limit, data_source, provenance_json, content_sha256, updated_at)
                    VALUES (:symbol, :trade_date, :is_suspended, :suspend_timing, :pre_close,
                            :up_limit, :down_limit, :data_source, :provenance, :content_sha256, now())
                    ON CONFLICT (symbol, trade_date) DO UPDATE SET
                      is_suspended=excluded.is_suspended, suspend_timing=excluded.suspend_timing,
                      pre_close=excluded.pre_close, up_limit=excluded.up_limit,
                      down_limit=excluded.down_limit, data_source=excluded.data_source,
                      provenance_json=excluded.provenance_json,
                      content_sha256=excluded.content_sha256, updated_at=excluded.updated_at""",
                    {**row, "content_sha256": content_sha256},
                )
        return len(symbols)

    def assess(self, requirement: dict[str, object]) -> dict[str, object]:
        if requirement.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported market data requirement")
        symbols = list(requirement["symbols"])
        sessions = self._execute(
            """SELECT trade_date FROM market_trading_sessions
               WHERE is_open=TRUE AND trade_date BETWEEN :start AND :end ORDER BY trade_date""",
            {"start": requirement["start_date"], "end": requirement["end_date"]},
        )
        dates = [str(row["trade_date"]) for row in sessions]
        calendar_edges = self._fetch_one(
            """SELECT MIN(trade_date) AS first, MAX(trade_date) AS last, COUNT(*) AS count
               FROM market_trading_sessions WHERE trade_date BETWEEN :start AND :end""",
            {"start": requirement["start_date"], "end": requirement["end_date"]},
        ) or {}
        expected_calendar_days = (
            datetime.strptime(str(requirement["end_date"]), "%Y%m%d")
            - datetime.strptime(str(requirement["start_date"]), "%Y%m%d")
        ).days + 1
        calendar_complete = bool(
            calendar_edges.get("first") and calendar_edges.get("last")
            and str(calendar_edges["first"]) == str(requirement["start_date"])
            and str(calendar_edges["last"]) == str(requirement["end_date"])
            and int(calendar_edges["count"]) == expected_calendar_days
        )
        if len(symbols) * len(dates) > MAX_REQUIRED_CELLS:
            raise ValueError("market data requirement exceeds 50000 symbol-session cells")
        lifecycles = self._execute(
            """SELECT symbol, list_date, delist_date FROM security_master_snapshot_members
               WHERE snapshot_id=:snapshot AND symbol IN
                 (SELECT jsonb_array_elements_text(:symbols))""",
            {"snapshot": requirement["security_master_snapshot_id"], "symbols": symbols},
        )
        lifecycle = {str(row["symbol"]): row for row in lifecycles}
        bars = self._execute(
            """SELECT symbol, trade_date, content_sha256 FROM market_daily_bars WHERE symbol IN
                 (SELECT jsonb_array_elements_text(:symbols))
               AND trade_date BETWEEN :start AND :end""",
            {"symbols": symbols, "start": requirement["start_date"], "end": requirement["end_date"]},
        )
        bar_keys = {(str(row["symbol"]), str(row["trade_date"])) for row in bars}
        bar_hashes = {
            (str(row["symbol"]), str(row["trade_date"])): str(row["content_sha256"]) for row in bars
        }
        statuses = self._execute(
            """SELECT symbol, trade_date, is_suspended, pre_close, up_limit, down_limit,
                      content_sha256 FROM market_daily_status WHERE symbol IN
                 (SELECT jsonb_array_elements_text(:symbols))
               AND trade_date BETWEEN :start AND :end""",
            {"symbols": symbols, "start": requirement["start_date"], "end": requirement["end_date"]},
        )
        status_map = {(str(row["symbol"]), str(row["trade_date"])): row for row in statuses}
        missing_dates: set[str] = set()
        missing: list[dict[str, str]] = []
        ready_cells: list[dict[str, object]] = []
        for symbol in symbols:
            life = lifecycle.get(symbol)
            if life is None:
                missing.append({"symbol": symbol, "trade_date": "*", "dataset": "security_lifecycle"})
                continue
            for trade_date in dates:
                if trade_date < str(life["list_date"]) or (life.get("delist_date") and trade_date > str(life["delist_date"])):
                    continue
                status = status_map.get((symbol, trade_date))
                if status is None:
                    missing.append({"symbol": symbol, "trade_date": trade_date, "dataset": "trading_status"})
                    missing_dates.add(trade_date)
                    continue
                if not status["is_suspended"] and (symbol, trade_date) not in bar_keys:
                    missing.append({"symbol": symbol, "trade_date": trade_date, "dataset": "stock_daily"})
                    missing_dates.add(trade_date)
                    continue
                if not status["is_suspended"] and (status["up_limit"] is None or status["down_limit"] is None):
                    missing.append({"symbol": symbol, "trade_date": trade_date, "dataset": "price_limits"})
                    missing_dates.add(trade_date)
                    continue
                ready_cells.append({
                    "symbol": symbol, "trade_date": trade_date,
                    "status_sha256": status["content_sha256"],
                    "bar_sha256": bar_hashes.get((symbol, trade_date)),
                })
        if not calendar_complete:
            missing.insert(0, {"symbol": "*", "trade_date": "*", "dataset": "trading_calendar"})
        state = "ready" if not missing else "missing" if not ready_cells else "partial"
        ready_identity = None if missing else _hash({
            "requirement_sha256": requirement["requirement_sha256"], "cells": ready_cells,
        })
        return {
            "schema_version": "market-data-readiness.v1", "state": state,
            "required_session_count": len(dates), "required_cell_count": len(ready_cells) + len(missing),
            "missing_count": len(missing), "missing": missing[:200],
            "missing_trade_dates": sorted(missing_dates),
            "calendar_complete": calendar_complete,
            "ready_input_sha256": ready_identity,
        }

    def list_ready_bars(self, requirement: dict[str, object]) -> list[dict[str, Any]]:
        return self._execute(
            """SELECT b.symbol, b.trade_date, b.open, b.high, b.low, b.close,
                      COALESCE(b.pre_close, s.pre_close) AS pre_close, b.volume, b.amount,
                      s.is_suspended, s.up_limit, s.down_limit
               FROM market_daily_bars b JOIN market_daily_status s
                 ON s.symbol=b.symbol AND s.trade_date=b.trade_date
               WHERE b.symbol IN (SELECT jsonb_array_elements_text(:symbols))
                 AND b.trade_date BETWEEN :start AND :end
               ORDER BY b.trade_date, b.symbol LIMIT 50001""",
            {"symbols": requirement["symbols"], "start": requirement["start_date"], "end": requirement["end_date"]},
        )
