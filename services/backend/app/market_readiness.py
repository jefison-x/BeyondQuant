"""Typed, lifecycle-aware market-input readiness contracts (ADR-0028)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from .data_provider import DAILY_BASIC_FIELDS, FINANCIAL_INDICATOR_FIELDS
from .db import PgStoreMixin, execute


SCHEMA_VERSION = "market-data-requirement.v3"
RESEARCH_SCHEMA_VERSION = "market-data-requirement.v2"
LEGACY_SCHEMA_VERSION = "market-data-requirement.v1"
REQUIRED_DATASETS = (
    "stock_daily", "trading_status", "price_limits", "adjustment_factors",
    "corporate_actions",
)
MAX_REQUIRED_CELLS = 50_000
MAX_AGENT_RESEARCH_SYMBOLS = 20
_CANONICAL_A_SHARE = re.compile(r"^(?:[03]\d{5}\.SZ|6\d{5}\.SH)$")


class MarketReadinessPersistenceError(RuntimeError):
    pass


def _research_date(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be YYYYMMDD")
    normalized = value.replace("-", "")
    try:
        parsed = datetime.strptime(normalized, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"{field} must be a valid YYYYMMDD date") from error
    if parsed.strftime("%Y%m%d") != normalized:
        raise ValueError(f"{field} must be a valid YYYYMMDD date")
    return normalized


def _research_symbols(values: object) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ValueError("symbols must be a non-empty list")
    symbols = sorted({str(value).strip().upper() for value in values})
    if len(symbols) > MAX_AGENT_RESEARCH_SYMBOLS:
        raise ValueError(f"symbols exceeds {MAX_AGENT_RESEARCH_SYMBOLS} entries")
    if any(not _CANONICAL_A_SHARE.fullmatch(symbol) for symbol in symbols):
        raise ValueError("symbols must contain canonical A-share codes")
    return symbols


def _research_fields(values: object, allowed: tuple[str, ...], field: str) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{field} must be a non-empty list")
    if len(values) > 12 or any(not isinstance(value, str) for value in values):
        raise ValueError(f"{field} must contain at most 12 supported fields")
    fields = list(dict.fromkeys(values))
    if any(value not in allowed for value in fields):
        raise ValueError(f"{field} contains an unsupported field")
    return fields


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
        """
        CREATE TABLE IF NOT EXISTS market_index_daily (
            index_symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            open DOUBLE PRECISION NOT NULL,
            high DOUBLE PRECISION NOT NULL,
            low DOUBLE PRECISION NOT NULL,
            close DOUBLE PRECISION NOT NULL,
            pre_close DOUBLE PRECISION,
            volume DOUBLE PRECISION,
            amount DOUBLE PRECISION,
            data_source TEXT NOT NULL,
            provenance_json JSONB NOT NULL,
            content_sha256 TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (index_symbol, trade_date)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS market_index_weights (
            index_symbol TEXT NOT NULL,
            constituent_symbol TEXT NOT NULL,
            snapshot_date TEXT NOT NULL,
            weight DOUBLE PRECISION NOT NULL,
            data_source TEXT NOT NULL,
            provenance_json JSONB NOT NULL,
            content_sha256 TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (index_symbol, constituent_symbol, snapshot_date)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS market_index_weight_completeness (
            index_symbol TEXT NOT NULL,
            period TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            content_sha256 TEXT NOT NULL,
            provenance_json JSONB NOT NULL,
            verified_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (index_symbol, period)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS market_daily_basic (
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            values_json JSONB NOT NULL,
            data_source TEXT NOT NULL,
            provenance_json JSONB NOT NULL,
            content_sha256 TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (symbol, trade_date)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS market_daily_basic_completeness (
            trade_date TEXT PRIMARY KEY,
            row_count INTEGER NOT NULL,
            content_sha256 TEXT NOT NULL,
            provenance_json JSONB NOT NULL,
            verified_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS market_financial_indicators (
            symbol TEXT NOT NULL,
            end_date TEXT NOT NULL,
            announcement_date TEXT NOT NULL,
            effective_date TEXT NOT NULL,
            values_json JSONB NOT NULL,
            update_flag TEXT,
            data_source TEXT NOT NULL,
            provenance_json JSONB NOT NULL,
            content_sha256 TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (symbol, end_date, announcement_date)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS market_financial_indicator_completeness (
            symbol TEXT NOT NULL,
            report_start_date TEXT NOT NULL,
            report_end_date TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            content_sha256 TEXT NOT NULL,
            provenance_json JSONB NOT NULL,
            verified_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (symbol, report_start_date, report_end_date)
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
        data_requirements: dict[str, object] | None = None,
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
        declared = data_requirements or {}
        if not isinstance(declared, dict):
            raise ValueError("data_requirements must be an object")
        document: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "symbols": normalized,
            "start_date": start,
            "end_date": end,
            "datasets": list(REQUIRED_DATASETS),
            "calendar": "SSE",
            "membership_fingerprint": membership_fingerprint,
            "security_master_snapshot_id": security_master_snapshot_id,
            "declared": declared,
        }
        if declared.get("index_universe"):
            cursor = datetime.strptime(start, "%Y%m%d").replace(day=1) - timedelta(days=1)
            final = datetime.strptime(end, "%Y%m%d").replace(day=1)
            periods: list[str] = []
            cursor = cursor.replace(day=1)
            while cursor <= final:
                periods.append(cursor.strftime("%Y%m"))
                cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
            document["index_weight_periods"] = periods
        if declared.get("fundamentals"):
            document["financial_report_start_date"] = (
                datetime.strptime(start, "%Y%m%d") - timedelta(days=550)
            ).strftime("%Y%m%d")
            document["financial_report_end_date"] = end
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

    def import_index_daily(self, index_symbol: str, bars: list[object], provenance: dict[str, object]) -> int:
        with self._transaction() as connection:
            for item in bars:
                row = {
                    "index_symbol": index_symbol, "trade_date": str(getattr(item, "trade_date")),
                    "open": float(getattr(item, "open")), "high": float(getattr(item, "high")),
                    "low": float(getattr(item, "low")), "close": float(getattr(item, "close")),
                    "pre_close": getattr(item, "pre_close"), "volume": getattr(item, "vol"),
                    "amount": getattr(item, "amount"), "data_source": "tushare",
                    "provenance": provenance,
                }
                row["content_sha256"] = _hash(row)
                execute(connection, """INSERT INTO market_index_daily
                    (index_symbol,trade_date,open,high,low,close,pre_close,volume,amount,
                     data_source,provenance_json,content_sha256,updated_at)
                    VALUES (:index_symbol,:trade_date,:open,:high,:low,:close,:pre_close,:volume,:amount,
                            :data_source,:provenance,:content_sha256,now())
                    ON CONFLICT (index_symbol,trade_date) DO UPDATE SET open=excluded.open,
                      high=excluded.high,low=excluded.low,close=excluded.close,
                      pre_close=excluded.pre_close,volume=excluded.volume,amount=excluded.amount,
                      data_source=excluded.data_source,provenance_json=excluded.provenance_json,
                      content_sha256=excluded.content_sha256,updated_at=excluded.updated_at""", row)
        return len(bars)

    def import_index_weights(
        self, index_symbol: str, period: str, weights: list[object], provenance: dict[str, object],
    ) -> int:
        rows = []
        for item in weights:
            row = {
                "index_symbol": index_symbol,
                "constituent_symbol": str(getattr(item, "constituent_symbol")),
                "snapshot_date": str(getattr(item, "trade_date")),
                "weight": float(getattr(item, "weight")), "data_source": "tushare",
                "provenance": provenance,
            }
            row["content_sha256"] = _hash(row)
            rows.append(row)
        identity = _hash([row["content_sha256"] for row in rows])
        with self._transaction() as connection:
            execute(connection, """DELETE FROM market_index_weights
                WHERE index_symbol=:index_symbol AND substring(snapshot_date,1,6)=:period""",
                {"index_symbol": index_symbol, "period": period})
            for row in rows:
                execute(connection, """INSERT INTO market_index_weights
                    (index_symbol,constituent_symbol,snapshot_date,weight,data_source,
                     provenance_json,content_sha256,updated_at)
                    VALUES (:index_symbol,:constituent_symbol,:snapshot_date,:weight,:data_source,
                            :provenance,:content_sha256,now())""", row)
            execute(connection, """INSERT INTO market_index_weight_completeness
                (index_symbol,period,row_count,content_sha256,provenance_json,verified_at)
                VALUES (:index_symbol,:period,:count,:identity,:provenance,now())
                ON CONFLICT (index_symbol,period) DO UPDATE SET row_count=excluded.row_count,
                  content_sha256=excluded.content_sha256,provenance_json=excluded.provenance_json,
                  verified_at=excluded.verified_at""",
                {"index_symbol": index_symbol, "period": period, "count": len(rows),
                 "identity": identity, "provenance": provenance})
        return len(rows)

    def import_daily_basic(self, trade_date: str, rows: list[object], provenance: dict[str, object]) -> int:
        normalized = []
        for item in rows:
            row = {
                "symbol": str(getattr(item, "ts_code")), "trade_date": trade_date,
                "values": dict(getattr(item, "values")), "data_source": "tushare",
                "provenance": provenance,
            }
            row["content_sha256"] = _hash(row)
            normalized.append(row)
        identity = _hash([row["content_sha256"] for row in normalized])
        with self._transaction() as connection:
            execute(connection, "DELETE FROM market_daily_basic WHERE trade_date=:trade_date",
                    {"trade_date": trade_date})
            for row in normalized:
                execute(connection, """INSERT INTO market_daily_basic
                    (symbol,trade_date,values_json,data_source,provenance_json,content_sha256,updated_at)
                    VALUES (:symbol,:trade_date,:values,:data_source,:provenance,:content_sha256,now())""", row)
            execute(connection, """INSERT INTO market_daily_basic_completeness
                (trade_date,row_count,content_sha256,provenance_json,verified_at)
                VALUES (:trade_date,:count,:identity,:provenance,now())
                ON CONFLICT (trade_date) DO UPDATE SET row_count=excluded.row_count,
                  content_sha256=excluded.content_sha256,provenance_json=excluded.provenance_json,
                  verified_at=excluded.verified_at""",
                {"trade_date": trade_date, "count": len(normalized), "identity": identity,
                 "provenance": provenance})
        return len(normalized)

    def import_financial_indicators(
        self, symbol: str, report_start_date: str, report_end_date: str,
        rows: list[object], provenance: dict[str, object],
    ) -> int:
        normalized = []
        for item in rows:
            announcement_date = str(getattr(item, "announcement_date"))
            effective_date = (datetime.strptime(announcement_date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
            row = {
                "symbol": symbol, "end_date": str(getattr(item, "end_date")),
                "announcement_date": announcement_date, "effective_date": effective_date,
                "values": dict(getattr(item, "values")), "update_flag": getattr(item, "update_flag"),
                "data_source": "tushare", "provenance": provenance,
            }
            row["content_sha256"] = _hash(row)
            normalized.append(row)
        identity = _hash([row["content_sha256"] for row in normalized])
        with self._transaction() as connection:
            execute(connection, """DELETE FROM market_financial_indicators
                WHERE symbol=:symbol AND end_date BETWEEN :start AND :end""",
                {"symbol": symbol, "start": report_start_date, "end": report_end_date})
            for row in normalized:
                execute(connection, """INSERT INTO market_financial_indicators
                    (symbol,end_date,announcement_date,effective_date,values_json,update_flag,
                     data_source,provenance_json,content_sha256,updated_at)
                    VALUES (:symbol,:end_date,:announcement_date,:effective_date,:values,:update_flag,
                            :data_source,:provenance,:content_sha256,now())""", row)
            execute(connection, """INSERT INTO market_financial_indicator_completeness
                (symbol,report_start_date,report_end_date,row_count,content_sha256,provenance_json,verified_at)
                VALUES (:symbol,:start,:end,:count,:identity,:provenance,now())
                ON CONFLICT (symbol,report_start_date,report_end_date) DO UPDATE SET
                  row_count=excluded.row_count,content_sha256=excluded.content_sha256,
                  provenance_json=excluded.provenance_json,verified_at=excluded.verified_at""",
                {"symbol": symbol, "start": report_start_date, "end": report_end_date,
                 "count": len(normalized), "identity": identity, "provenance": provenance})
        return len(normalized)

    def research_valuation(
        self, *, symbols: object, trade_date: object, fields: object,
    ) -> dict[str, object]:
        """Return bounded exact-session valuation evidence from durable BYQ data only."""

        normalized_symbols = _research_symbols(symbols)
        normalized_date = _research_date(trade_date, "trade_date")
        normalized_fields = _research_fields(fields, DAILY_BASIC_FIELDS, "fields")
        completeness = self._fetch_one(
            """SELECT row_count,content_sha256,provenance_json,verified_at
               FROM market_daily_basic_completeness WHERE trade_date=:trade_date""",
            {"trade_date": normalized_date},
        )
        rows = self._execute(
            """SELECT symbol,trade_date,values_json,data_source,content_sha256
               FROM market_daily_basic
               WHERE trade_date=:trade_date
                 AND symbol IN (SELECT jsonb_array_elements_text(:symbols))
               ORDER BY symbol""",
            {"trade_date": normalized_date, "symbols": normalized_symbols},
        )
        by_symbol = {str(row["symbol"]): row for row in rows}
        missing = [symbol for symbol in normalized_symbols if symbol not in by_symbol]
        evidence = []
        missing_fields: list[dict[str, object]] = []
        for symbol in normalized_symbols:
            row = by_symbol.get(symbol)
            if row is None:
                continue
            values = row.get("values_json") if isinstance(row.get("values_json"), dict) else {}
            selected_values = {field: values.get(field) for field in normalized_fields}
            null_fields = [field for field, value in selected_values.items() if value is None]
            if null_fields:
                missing_fields.append({"symbol": symbol, "fields": null_fields})
            evidence.append({
                "symbol": symbol,
                "trade_date": str(row["trade_date"]),
                "values": selected_values,
                "data_source": str(row["data_source"]),
                "content_sha256": str(row["content_sha256"]),
            })
        complete = completeness is not None
        usable = complete and not missing and not missing_fields
        return {
            "schema_version": "market-valuation-research.v1",
            "trade_date": normalized_date,
            "fields": normalized_fields,
            "rows": evidence,
            "coverage": {
                "complete": complete,
                "usable": usable,
                "requested_symbols": len(normalized_symbols),
                "returned_symbols": len(evidence),
                "missing_symbols": missing,
                "missing_fields": missing_fields,
                "dataset_row_count": int(completeness["row_count"]) if completeness else None,
                "dataset_sha256": str(completeness["content_sha256"]) if completeness else None,
                "verified_at": str(completeness["verified_at"]) if completeness else None,
            },
        }

    def research_fundamentals(
        self, *, symbols: object, as_of_date: object, fields: object,
    ) -> dict[str, object]:
        """Return the latest announcement-visible report for each requested symbol."""

        normalized_symbols = _research_symbols(symbols)
        normalized_date = _research_date(as_of_date, "as_of_date")
        normalized_fields = _research_fields(fields, FINANCIAL_INDICATOR_FIELDS, "fields")
        evidence: list[dict[str, object]] = []
        missing: list[dict[str, object]] = []
        coverage: list[dict[str, object]] = []
        for symbol in normalized_symbols:
            completeness = self._fetch_one(
                """SELECT report_start_date,report_end_date,row_count,content_sha256,verified_at
                   FROM market_financial_indicator_completeness
                   WHERE symbol=:symbol AND report_start_date<=:as_of_date
                   ORDER BY report_end_date DESC,report_start_date ASC LIMIT 1""",
                {"symbol": symbol, "as_of_date": normalized_date},
            )
            coverage.append({
                "symbol": symbol,
                "complete": completeness is not None,
                "report_start_date": str(completeness["report_start_date"]) if completeness else None,
                "report_end_date": str(completeness["report_end_date"]) if completeness else None,
                "dataset_row_count": int(completeness["row_count"]) if completeness else None,
                "dataset_sha256": str(completeness["content_sha256"]) if completeness else None,
                "verified_at": str(completeness["verified_at"]) if completeness else None,
            })
            if completeness is None:
                missing.append({"symbol": symbol, "reason": "coverage_unverified"})
                continue
            row = self._fetch_one(
                """SELECT symbol,end_date,announcement_date,effective_date,values_json,
                          data_source,content_sha256
                   FROM market_financial_indicators
                   WHERE symbol=:symbol AND effective_date<=:as_of_date
                     AND end_date BETWEEN :report_start_date AND :report_end_date
                   ORDER BY end_date DESC,announcement_date DESC LIMIT 1""",
                {
                    "symbol": symbol,
                    "as_of_date": normalized_date,
                    "report_start_date": str(completeness["report_start_date"]),
                    "report_end_date": str(completeness["report_end_date"]),
                },
            )
            if row is None:
                missing.append({"symbol": symbol, "reason": "no_visible_report"})
                continue
            values = row.get("values_json") if isinstance(row.get("values_json"), dict) else {}
            selected_values = {field: values.get(field) for field in normalized_fields}
            null_fields = [field for field, value in selected_values.items() if value is None]
            if null_fields:
                missing.append({"symbol": symbol, "reason": "field_values_missing", "fields": null_fields})
            evidence.append({
                "symbol": symbol,
                "report_period": str(row["end_date"]),
                "announcement_date": str(row["announcement_date"]),
                "effective_date": str(row["effective_date"]),
                "values": selected_values,
                "data_source": str(row["data_source"]),
                "content_sha256": str(row["content_sha256"]),
            })
        return {
            "schema_version": "market-fundamentals-research.v1",
            "as_of_date": normalized_date,
            "fields": normalized_fields,
            "rows": evidence,
            "coverage": {
                "usable": not missing,
                "requested_symbols": len(normalized_symbols),
                "returned_symbols": len(evidence),
                "missing": missing,
                "datasets": coverage,
            },
        }

    def assess(self, requirement: dict[str, object]) -> dict[str, object]:
        if requirement.get("schema_version") not in {SCHEMA_VERSION, RESEARCH_SCHEMA_VERSION, LEGACY_SCHEMA_VERSION}:
            raise ValueError("unsupported market data requirement")
        requires_research_inputs = requirement.get("schema_version") in {SCHEMA_VERSION, RESEARCH_SCHEMA_VERSION}
        declared = requirement.get("declared", {}) if requirement.get("schema_version") == SCHEMA_VERSION else {}
        if not isinstance(declared, dict):
            raise ValueError("declared data requirement is invalid")
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
               AND trade_date BETWEEN :start AND :end AND data_source='tushare'""",
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
               AND trade_date BETWEEN :start AND :end AND data_source='tushare'""",
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
        benchmark_symbol = declared.get("benchmark")
        benchmark_rows = self._execute(
            """SELECT trade_date,content_sha256 FROM market_index_daily
               WHERE index_symbol=:symbol AND trade_date BETWEEN :start AND :end""",
            {"symbol": benchmark_symbol, "start": requirement["start_date"], "end": requirement["end_date"]},
        ) if benchmark_symbol else []
        benchmark_map = {str(row["trade_date"]): row for row in benchmark_rows}
        daily_basic_fields = list(declared.get("daily_basic", []))
        daily_basic_rows = self._execute(
            """SELECT symbol,trade_date,content_sha256 FROM market_daily_basic
               WHERE symbol IN (SELECT jsonb_array_elements_text(:symbols))
                 AND trade_date BETWEEN :start AND :end""",
            {"symbols": symbols, "start": requirement["start_date"], "end": requirement["end_date"]},
        ) if daily_basic_fields else []
        daily_basic_map = {(str(row["symbol"]), str(row["trade_date"])): row for row in daily_basic_rows}
        basic_complete = {
            str(row["trade_date"]): row for row in self._execute(
                """SELECT trade_date,content_sha256 FROM market_daily_basic_completeness
                   WHERE trade_date BETWEEN :start AND :end""",
                {"start": requirement["start_date"], "end": requirement["end_date"]},
            )
        } if daily_basic_fields else {}
        index_universe = declared.get("index_universe")
        weight_periods = list(requirement.get("index_weight_periods", []))
        weight_completeness = {
            str(row["period"]): row for row in self._execute(
                """SELECT period,content_sha256 FROM market_index_weight_completeness
                   WHERE index_symbol=:symbol AND period IN
                     (SELECT jsonb_array_elements_text(:periods))""",
                {"symbol": index_universe, "periods": weight_periods},
            )
        } if index_universe else {}
        weight_rows = self._execute(
            """SELECT constituent_symbol,snapshot_date,content_sha256 FROM market_index_weights
               WHERE index_symbol=:symbol AND snapshot_date<=:end ORDER BY snapshot_date,constituent_symbol""",
            {"symbol": index_universe, "end": requirement["end_date"]},
        ) if index_universe else []
        fundamental_fields = list(declared.get("fundamentals", []))
        financial_complete = {
            str(row["symbol"]): row for row in self._execute(
                """SELECT symbol,content_sha256 FROM market_financial_indicator_completeness
                   WHERE symbol IN (SELECT jsonb_array_elements_text(:symbols))
                     AND report_start_date=:start AND report_end_date=:end""",
                {"symbols": symbols, "start": requirement.get("financial_report_start_date"),
                 "end": requirement.get("financial_report_end_date")},
            )
        } if fundamental_fields else {}
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
        if benchmark_symbol:
            for trade_date in dates:
                if trade_date not in benchmark_map:
                    missing.append({"symbol": str(benchmark_symbol), "trade_date": trade_date, "dataset": "index_daily"})
                    missing_dates.add(trade_date)
        if index_universe:
            for period in weight_periods:
                if period not in weight_completeness:
                    missing.append({"symbol": str(index_universe), "trade_date": period, "dataset": "index_weights"})
            snapshots = sorted({str(row["snapshot_date"]) for row in weight_rows})
            for trade_date in dates:
                if not any(snapshot <= trade_date for snapshot in snapshots):
                    missing.append({"symbol": str(index_universe), "trade_date": trade_date, "dataset": "index_membership"})
                    missing_dates.add(trade_date)
        if fundamental_fields:
            for symbol in symbols:
                if symbol not in financial_complete:
                    missing.append({"symbol": symbol, "trade_date": "*", "dataset": "financial_indicators"})
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
                if daily_basic_fields and not status["is_suspended"] and (
                    trade_date not in basic_complete or (symbol, trade_date) not in daily_basic_map
                ):
                    missing.append({"symbol": symbol, "trade_date": trade_date, "dataset": "daily_basic"})
                    missing_dates.add(trade_date)
                    continue
                ready_cells.append({
                    "symbol": symbol, "trade_date": trade_date,
                    "status_sha256": status["content_sha256"],
                    "bar_sha256": bar_hashes.get((symbol, trade_date)),
                    "factor_sha256": factor.get("content_sha256") if factor else None,
                    "supplement_sha256": supplement.get("content_sha256") if supplement else None,
                    "daily_basic_sha256": (
                        daily_basic_map[(symbol, trade_date)]["content_sha256"]
                        if (symbol, trade_date) in daily_basic_map else None
                    ),
                })
        if not calendar_complete:
            missing.insert(0, {"symbol": "*", "trade_date": "*", "dataset": "trading_calendar"})
        state = "ready" if not missing else "missing" if not ready_cells else "partial"
        ready_identity = None if missing else _hash({
            "requirement_sha256": requirement["requirement_sha256"], "cells": ready_cells,
            "corporate_actions": [str(row["content_sha256"]) for row in action_rows],
            "benchmark": [str(row["content_sha256"]) for row in benchmark_rows],
            "index_weights": [str(row["content_sha256"]) for row in weight_rows],
            "financial_completeness": [str(row["content_sha256"]) for row in financial_complete.values()],
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
                      s.is_suspended, s.up_limit, s.down_limit, f.adj_factor,
                      db.values_json AS daily_basic_values
               FROM market_daily_bars b JOIN market_daily_status s
                 ON s.symbol=b.symbol AND s.trade_date=b.trade_date
               LEFT JOIN market_adjustment_factors f
                 ON f.symbol=b.symbol AND f.trade_date=b.trade_date
               LEFT JOIN market_daily_basic db
                 ON db.symbol=b.symbol AND db.trade_date=b.trade_date
               WHERE b.symbol IN (SELECT jsonb_array_elements_text(:symbols))
                 AND b.trade_date BETWEEN :start AND :end
               ORDER BY b.trade_date, b.symbol LIMIT 50001""",
            {"symbols": requirement["symbols"], "start": requirement["start_date"], "end": requirement["end_date"]},
        )

    def build_ready_input(self, requirement: dict[str, object]) -> dict[str, object]:
        rows = self.list_ready_bars(requirement)
        legacy = requirement.get("schema_version") == LEGACY_SCHEMA_VERSION
        declared = requirement.get("declared", {}) if requirement.get("schema_version") == SCHEMA_VERSION else {}
        if not isinstance(declared, dict):
            declared = {}
        daily_basic_fields = list(declared.get("daily_basic", []))
        fundamental_fields = list(declared.get("fundamentals", []))
        index_universe = declared.get("index_universe")
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
            basic_values = row.get("daily_basic_values")
            if not isinstance(basic_values, dict):
                basic_values = {}
            for field in daily_basic_fields:
                adjusted[f"daily_basic__{field}"] = basic_values.get(field)
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
        weight_rows = self._execute(
            """SELECT constituent_symbol,snapshot_date,weight,content_sha256
               FROM market_index_weights WHERE index_symbol=:symbol AND snapshot_date<=:end
               ORDER BY snapshot_date,constituent_symbol""",
            {"symbol": index_universe, "end": requirement["end_date"]},
        ) if index_universe else []
        snapshots: dict[str, set[str]] = {}
        for row in weight_rows:
            snapshots.setdefault(str(row["snapshot_date"]), set()).add(str(row["constituent_symbol"]))
        snapshot_dates = sorted(snapshots)
        financial_rows = self._execute(
            """SELECT symbol,end_date,announcement_date,effective_date,values_json,content_sha256
               FROM market_financial_indicators
               WHERE symbol IN (SELECT jsonb_array_elements_text(:symbols))
                 AND effective_date<=:end ORDER BY symbol,effective_date,end_date,announcement_date""",
            {"symbols": requirement["symbols"], "end": requirement["end_date"]},
        ) if fundamental_fields else []
        financial_by_symbol: dict[str, list[dict[str, Any]]] = {}
        for row in financial_rows:
            financial_by_symbol.setdefault(str(row["symbol"]), []).append(row)
        for adjusted in research_bars:
            compact_date = str(adjusted["trade_date"]).replace("-", "")
            if index_universe:
                candidates = [date for date in snapshot_dates if date <= compact_date]
                snapshot_date = candidates[-1] if candidates else ""
                adjusted["is_universe_member"] = bool(
                    snapshot_date and str(adjusted["symbol"]) in snapshots[snapshot_date]
                )
            if fundamental_fields:
                candidates = [
                    row for row in financial_by_symbol.get(str(adjusted["symbol"]), [])
                    if str(row["effective_date"]) <= compact_date
                ]
                chosen = max(
                    candidates,
                    key=lambda row: (str(row["end_date"]), str(row["announcement_date"])),
                    default=None,
                )
                values = chosen.get("values_json", {}) if chosen is not None else {}
                if not isinstance(values, dict):
                    values = {}
                for field in fundamental_fields:
                    adjusted[f"fina_indicator__{field}"] = values.get(field)
        benchmark_symbol = declared.get("benchmark")
        benchmark_rows = self._execute(
            """SELECT index_symbol,trade_date,open,high,low,close,pre_close,volume,amount,content_sha256
               FROM market_index_daily WHERE index_symbol=:symbol
                 AND trade_date BETWEEN :start AND :end ORDER BY trade_date""",
            {"symbol": benchmark_symbol, "start": requirement["start_date"], "end": requirement["end_date"]},
        ) if benchmark_symbol else []
        benchmark = [
            {
                "symbol": str(row["index_symbol"]),
                "trade_date": f"{str(row['trade_date'])[:4]}-{str(row['trade_date'])[4:6]}-{str(row['trade_date'])[6:8]}",
                "open": row["open"], "high": row["high"], "low": row["low"],
                "close": row["close"], "prev_close": row.get("pre_close"),
                "volume": row.get("volume") or 0, "amount": row.get("amount") or 0,
            }
            for row in benchmark_rows
        ]
        identity = _hash({
            "raw_bars": raw_bars, "research_bars": research_bars,
            "adjustment_factors": [
                {"symbol": str(row["symbol"]), "trade_date": str(row["trade_date"]),
                 "adj_factor": float(row.get("adj_factor") or 1.0)}
                for row in rows
            ],
            "corporate_actions": normalized_actions,
            "declared": declared, "research_bars_with_declared_inputs": research_bars,
            "benchmark": benchmark,
            "index_weight_hashes": [str(row["content_sha256"]) for row in weight_rows],
            "financial_hashes": [str(row["content_sha256"]) for row in financial_rows],
        })
        return {"bars": raw_bars, "research_bars": research_bars,
                "corporate_actions": normalized_actions, "benchmark": benchmark,
                "declared": declared, "research_view_sha256": identity}
