"""Typed, lifecycle-aware market-input readiness contracts (ADR-0028)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, execute


SCHEMA_VERSION = "market-data-requirement.v2"
LEGACY_SCHEMA_VERSION = "market-data-requirement.v1"
REQUIRED_DATASETS = (
    "stock_daily", "trading_status", "price_limits", "adjustment_factors",
    "corporate_actions",
)
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
        """
        CREATE TABLE IF NOT EXISTS market_adjustment_factors (
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            adj_factor DOUBLE PRECISION NOT NULL,
            data_source TEXT NOT NULL,
            provenance_json JSONB NOT NULL,
            content_sha256 TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (symbol, trade_date)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS market_corporate_actions (
            symbol TEXT NOT NULL,
            end_date TEXT NOT NULL,
            ex_date TEXT NOT NULL,
            announcement_date TEXT,
            implementation_announcement_date TEXT,
            record_date TEXT,
            pay_date TEXT,
            share_listing_date TEXT,
            cash_dividend_per_share DOUBLE PRECISION NOT NULL,
            cash_dividend_gross DOUBLE PRECISION NOT NULL,
            share_ratio DOUBLE PRECISION NOT NULL,
            data_source TEXT NOT NULL,
            provenance_json JSONB NOT NULL,
            content_sha256 TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (symbol, end_date, ex_date)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS market_corporate_actions_date_idx
            ON market_corporate_actions(ex_date, symbol)
        """,
        """
        CREATE TABLE IF NOT EXISTS market_session_supplement_completeness (
            trade_date TEXT PRIMARY KEY,
            adjustment_complete BOOLEAN NOT NULL,
            corporate_actions_complete BOOLEAN NOT NULL,
            factor_row_count INTEGER NOT NULL,
            corporate_action_row_count INTEGER NOT NULL,
            content_sha256 TEXT NOT NULL,
            provenance_json JSONB NOT NULL,
            verified_at TIMESTAMPTZ NOT NULL
        )
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

    def import_session_supplements(
        self, trade_date: str, *, factors: list[object], actions: list[object],
        provenance: dict[str, object],
    ) -> dict[str, object]:
        factor_rows: list[dict[str, object]] = []
        action_rows: list[dict[str, object]] = []
        for item in factors:
            row = {
                "symbol": str(getattr(item, "ts_code")), "trade_date": trade_date,
                "adj_factor": float(getattr(item, "adj_factor")), "data_source": "tushare",
                "provenance": provenance.get("adjustment_factors", {}),
            }
            row["content_sha256"] = _hash(row)
            factor_rows.append(row)
        for item in actions:
            raw = dict(getattr(item, "as_dict")())
            row = {
                **raw, "data_source": "tushare",
                "provenance": provenance.get("corporate_actions", {}),
            }
            row["content_sha256"] = _hash(row)
            action_rows.append(row)
        identity = _hash({
            "trade_date": trade_date,
            "factors": [row["content_sha256"] for row in sorted(factor_rows, key=lambda item: str(item["symbol"]))],
            "actions": [row["content_sha256"] for row in sorted(action_rows, key=lambda item: (str(item["symbol"]), str(item["end_date"])))],
            "provenance": provenance,
        })
        with self._transaction() as connection:
            execute(connection, "DELETE FROM market_adjustment_factors WHERE trade_date=:trade_date",
                    {"trade_date": trade_date})
            execute(connection, "DELETE FROM market_corporate_actions WHERE ex_date=:trade_date",
                    {"trade_date": trade_date})
            for row in factor_rows:
                execute(connection, """INSERT INTO market_adjustment_factors
                    (symbol, trade_date, adj_factor, data_source, provenance_json, content_sha256, updated_at)
                    VALUES (:symbol, :trade_date, :adj_factor, :data_source, :provenance, :content_sha256, now())
                    ON CONFLICT (symbol, trade_date) DO UPDATE SET
                      adj_factor=excluded.adj_factor, data_source=excluded.data_source,
                      provenance_json=excluded.provenance_json,
                      content_sha256=excluded.content_sha256, updated_at=excluded.updated_at""", row)
            for row in action_rows:
                execute(connection, """INSERT INTO market_corporate_actions
                    (symbol, end_date, ex_date, announcement_date, implementation_announcement_date,
                     record_date, pay_date, share_listing_date, cash_dividend_per_share,
                     cash_dividend_gross, share_ratio, data_source, provenance_json,
                     content_sha256, updated_at)
                    VALUES (:symbol, :end_date, :ex_date, :announcement_date,
                            :implementation_announcement_date, :record_date, :pay_date,
                            :share_listing_date, :cash_dividend_per_share,
                            :cash_dividend_gross, :share_ratio, :data_source, :provenance,
                            :content_sha256, now())
                    ON CONFLICT (symbol, end_date, ex_date) DO UPDATE SET
                      announcement_date=excluded.announcement_date,
                      implementation_announcement_date=excluded.implementation_announcement_date,
                      record_date=excluded.record_date, pay_date=excluded.pay_date,
                      share_listing_date=excluded.share_listing_date,
                      cash_dividend_per_share=excluded.cash_dividend_per_share,
                      cash_dividend_gross=excluded.cash_dividend_gross,
                      share_ratio=excluded.share_ratio, data_source=excluded.data_source,
                      provenance_json=excluded.provenance_json,
                      content_sha256=excluded.content_sha256, updated_at=excluded.updated_at""", row)
            execute(connection, """INSERT INTO market_session_supplement_completeness
                (trade_date, adjustment_complete, corporate_actions_complete, factor_row_count,
                 corporate_action_row_count, content_sha256, provenance_json, verified_at)
                VALUES (:trade_date, TRUE, TRUE, :factor_count, :action_count, :identity, :provenance, now())
                ON CONFLICT (trade_date) DO UPDATE SET adjustment_complete=TRUE,
                  corporate_actions_complete=TRUE, factor_row_count=excluded.factor_row_count,
                  corporate_action_row_count=excluded.corporate_action_row_count,
                  content_sha256=excluded.content_sha256, provenance_json=excluded.provenance_json,
                  verified_at=excluded.verified_at""", {
                    "trade_date": trade_date, "factor_count": len(factor_rows),
                    "action_count": len(action_rows), "identity": identity, "provenance": provenance,
                })
        return {"factor_count": len(factor_rows), "corporate_action_count": len(action_rows),
                "content_sha256": identity}

    def assess(self, requirement: dict[str, object]) -> dict[str, object]:
        if requirement.get("schema_version") not in {SCHEMA_VERSION, LEGACY_SCHEMA_VERSION}:
            raise ValueError("unsupported market data requirement")
        requires_research_inputs = requirement.get("schema_version") == SCHEMA_VERSION
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
        factors = self._execute(
            """SELECT symbol, trade_date, adj_factor, content_sha256
               FROM market_adjustment_factors WHERE symbol IN
                 (SELECT jsonb_array_elements_text(:symbols))
               AND trade_date BETWEEN :start AND :end""",
            {"symbols": symbols, "start": requirement["start_date"], "end": requirement["end_date"]},
        )
        factor_map = {(str(row["symbol"]), str(row["trade_date"])): row for row in factors}
        supplement_rows = self._execute(
            """SELECT trade_date, adjustment_complete, corporate_actions_complete, content_sha256
               FROM market_session_supplement_completeness
               WHERE trade_date BETWEEN :start AND :end""",
            {"start": requirement["start_date"], "end": requirement["end_date"]},
        )
        supplements = {str(row["trade_date"]): row for row in supplement_rows}
        action_rows = self._execute(
            """SELECT symbol, end_date, ex_date, content_sha256
               FROM market_corporate_actions WHERE symbol IN
                 (SELECT jsonb_array_elements_text(:symbols))
               AND ex_date BETWEEN :start AND :end ORDER BY ex_date, symbol, end_date""",
            {"symbols": symbols, "start": requirement["start_date"], "end": requirement["end_date"]},
        )
        missing_dates: set[str] = set()
        missing: list[dict[str, str]] = []
        ready_cells: list[dict[str, object]] = []
        incomplete_action_dates = {
            trade_date for trade_date in dates
            if supplements.get(trade_date) is None
            or not supplements[trade_date]["corporate_actions_complete"]
        } if requires_research_inputs else set()
        for trade_date in sorted(incomplete_action_dates):
            missing.append({"symbol": "*", "trade_date": trade_date, "dataset": "corporate_actions"})
            missing_dates.add(trade_date)
        for symbol in symbols:
            life = lifecycle.get(symbol)
            if life is None:
                missing.append({"symbol": symbol, "trade_date": "*", "dataset": "security_lifecycle"})
                continue
            for trade_date in dates:
                if trade_date < str(life["list_date"]) or (life.get("delist_date") and trade_date > str(life["delist_date"])):
                    continue
                status = status_map.get((symbol, trade_date))
                supplement = supplements.get(trade_date)
                if trade_date in incomplete_action_dates:
                    continue
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
                factor = factor_map.get((symbol, trade_date))
                if requires_research_inputs and not status["is_suspended"] and (
                    supplement is None or not supplement["adjustment_complete"] or factor is None
                ):
                    missing.append({"symbol": symbol, "trade_date": trade_date, "dataset": "adjustment_factors"})
                    missing_dates.add(trade_date)
                    continue
                ready_cells.append({
                    "symbol": symbol, "trade_date": trade_date,
                    "status_sha256": status["content_sha256"],
                    "bar_sha256": bar_hashes.get((symbol, trade_date)),
                    "factor_sha256": factor.get("content_sha256") if factor else None,
                    "supplement_sha256": supplement.get("content_sha256") if supplement else None,
                })
        if not calendar_complete:
            missing.insert(0, {"symbol": "*", "trade_date": "*", "dataset": "trading_calendar"})
        state = "ready" if not missing else "missing" if not ready_cells else "partial"
        ready_identity = None if missing else _hash({
            "requirement_sha256": requirement["requirement_sha256"], "cells": ready_cells,
            "corporate_actions": [str(row["content_sha256"]) for row in action_rows],
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
                      s.is_suspended, s.up_limit, s.down_limit, f.adj_factor
               FROM market_daily_bars b JOIN market_daily_status s
                 ON s.symbol=b.symbol AND s.trade_date=b.trade_date
               LEFT JOIN market_adjustment_factors f
                 ON f.symbol=b.symbol AND f.trade_date=b.trade_date
               WHERE b.symbol IN (SELECT jsonb_array_elements_text(:symbols))
                 AND b.trade_date BETWEEN :start AND :end
               ORDER BY b.trade_date, b.symbol LIMIT 50001""",
            {"symbols": requirement["symbols"], "start": requirement["start_date"], "end": requirement["end_date"]},
        )

    def build_ready_input(self, requirement: dict[str, object]) -> dict[str, object]:
        rows = self.list_ready_bars(requirement)
        legacy = requirement.get("schema_version") == LEGACY_SCHEMA_VERSION
        anchors: dict[str, float] = {}
        for row in rows:
            anchors[str(row["symbol"])] = float(row.get("adj_factor") or 1.0)
        raw_bars: list[dict[str, object]] = []
        research_bars: list[dict[str, object]] = []
        for row in rows:
            symbol = str(row["symbol"])
            date = str(row["trade_date"])
            rendered = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            raw = {
                "symbol": symbol, "trade_date": rendered,
                "open": row["open"], "high": row["high"], "low": row["low"], "close": row["close"],
                "prev_close": row.get("pre_close"), "volume": row.get("volume") or 0,
                "is_suspended": bool(row.get("is_suspended")),
                "up_limit": row.get("up_limit"), "down_limit": row.get("down_limit"),
            }
            raw_bars.append(raw)
            multiplier = 1.0 if legacy else float(row["adj_factor"]) / anchors[symbol]
            adjusted = dict(raw)
            for field in ("open", "high", "low", "close", "prev_close", "up_limit", "down_limit"):
                if adjusted.get(field) is not None:
                    adjusted[field] = round(float(adjusted[field]) * multiplier, 8)
            research_bars.append(adjusted)
        actions = self._execute(
            """SELECT symbol, end_date, announcement_date, implementation_announcement_date,
                      record_date, ex_date, pay_date, share_listing_date,
                      cash_dividend_per_share, cash_dividend_gross, share_ratio, content_sha256
               FROM market_corporate_actions WHERE symbol IN
                 (SELECT jsonb_array_elements_text(:symbols))
                 AND ex_date BETWEEN :start AND :end ORDER BY ex_date, symbol, end_date""",
            {"symbols": requirement["symbols"], "start": requirement["start_date"], "end": requirement["end_date"]},
        )
        normalized_actions = []
        for row in actions:
            item = dict(row)
            for field in ("announcement_date", "implementation_announcement_date", "record_date", "ex_date", "pay_date", "share_listing_date"):
                value = item.get(field)
                if value:
                    item[field] = f"{str(value)[:4]}-{str(value)[4:6]}-{str(value)[6:8]}"
            if not legacy:
                normalized_actions.append(item)
        identity = _hash({
            "raw_bars": raw_bars, "research_bars": research_bars,
            "adjustment_factors": [
                {"symbol": str(row["symbol"]), "trade_date": str(row["trade_date"]),
                 "adj_factor": float(row.get("adj_factor") or 1.0)}
                for row in rows
            ],
            "corporate_actions": normalized_actions,
        })
        return {"bars": raw_bars, "research_bars": research_bars,
                "corporate_actions": normalized_actions, "research_view_sha256": identity}
