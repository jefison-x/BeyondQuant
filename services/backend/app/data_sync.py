"""Tushare-only durable sync jobs and coverage audit for Phase 39.

The module owns BYQ job state and normalized PostgreSQL market-data writes. It
does not expose provider credentials, arbitrary provider endpoints, raw
Tushare envelopes, or Community storage/runtime assumptions.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .data_provider import (
    DailyRequest,
    ProviderAuthorizationError,
    ProviderCredentialsMissing,
    ProviderError,
    ProviderProtocolError,
    ProviderRateLimited,
    ProviderUnavailable,
    TushareProvider,
)
from .db import PgStoreMixin, execute, fetch_one
from .market_data import MarketDataStore
from .pg_import import KEEP_NEW


class DataSyncError(RuntimeError):
    pass


class DataSyncNotFound(DataSyncError):
    pass


class DataSyncConflict(DataSyncError):
    pass


class DataSyncPersistenceError(DataSyncError):
    pass


_SYMBOL = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MODES = {"range", "incremental"}
_TERMINAL = {"completed", "partial", "failed"}
MAX_EXPLICIT_SYMBOLS = 500
MAX_ORCHESTRATED_SYMBOLS = 6_000
MAX_RANGE_DAYS = 366
MAX_PUBLIC_SYMBOLS = 100
MAX_PUBLIC_RESULTS = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _date(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must use YYYYMMDD")
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"{field} must be a calendar date in YYYYMMDD") from error
    return parsed.strftime("%Y%m%d")


def _safe_provider_error(error: Exception) -> tuple[str, str]:
    if isinstance(error, ProviderCredentialsMissing):
        return "credentials_missing", "Tushare credentials are not configured"
    if isinstance(error, ProviderAuthorizationError):
        return "authorization_failed", "Tushare rejected the configured credentials"
    if isinstance(error, ProviderRateLimited):
        return "rate_limited", "Tushare request was rate limited"
    if isinstance(error, ProviderProtocolError):
        return "provider_protocol_error", "Tushare returned invalid market data"
    if isinstance(error, ProviderUnavailable):
        return "provider_unavailable", "Tushare is unavailable"
    return "sync_failed", "market-data synchronization failed"


class DataSyncStore(PgStoreMixin):
    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS data_sync_jobs (
            job_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            mode TEXT NOT NULL,
            symbols_json JSONB NOT NULL,
            selection_json JSONB NOT NULL DEFAULT '{"type":"explicit"}'::jsonb,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            status TEXT NOT NULL,
            progress INTEGER NOT NULL,
            rows_received BIGINT NOT NULL DEFAULT 0,
            rows_inserted BIGINT NOT NULL DEFAULT 0,
            rows_kept BIGINT NOT NULL DEFAULT 0,
            symbol_results_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            error_code TEXT,
            error_message TEXT,
            requested_by TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_sha256 TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        ALTER TABLE data_sync_jobs
            ADD COLUMN IF NOT EXISTS selection_json JSONB NOT NULL DEFAULT '{"type":"explicit"}'::jsonb
        """,
        """
        CREATE INDEX IF NOT EXISTS data_sync_jobs_created_idx
            ON data_sync_jobs(created_at DESC, job_id DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS data_sync_audit (
            audit_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES data_sync_jobs(job_id),
            actor_principal TEXT NOT NULL,
            action TEXT NOT NULL,
            outcome TEXT NOT NULL,
            detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS data_sync_audit_created_idx
            ON data_sync_audit(created_at DESC, audit_id DESC)
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as error:
            raise DataSyncPersistenceError("data synchronization storage is unavailable") from error

    def create_job(self, payload: object, *, actor: object) -> tuple[dict[str, object], bool]:
        if not isinstance(payload, dict):
            raise ValueError("sync job request must be an object")
        allowed = {"mode", "symbols", "selection", "start_date", "end_date", "idempotency_key"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"sync job request has unknown fields: {', '.join(unknown)}")
        actor_text = str(actor).strip()
        if not actor_text or len(actor_text) > 128:
            raise ValueError("actor principal is invalid")
        mode = payload.get("mode", "range")
        if mode not in _MODES:
            raise ValueError("sync mode must be range or incremental")
        raw_symbols = payload.get("symbols")
        selection = payload.get("selection") or {"type": "explicit"}
        if not isinstance(selection, dict):
            raise ValueError("selection must be an object")
        selection_type = selection.get("type")
        if selection_type not in {"explicit", "selected", "security_master", "stock_pool"}:
            raise ValueError("selection.type is invalid")
        max_symbols = MAX_ORCHESTRATED_SYMBOLS if selection_type in {"security_master", "stock_pool"} else MAX_EXPLICIT_SYMBOLS
        if not isinstance(raw_symbols, list) or not raw_symbols or len(raw_symbols) > max_symbols:
            raise ValueError(f"symbols must contain 1 to {max_symbols} items")
        symbols = sorted({str(item).upper() for item in raw_symbols})
        if len(symbols) != len(raw_symbols) or any(not _SYMBOL.fullmatch(item) for item in symbols):
            raise ValueError("symbols must be unique canonical A-share symbols")
        start_date = _date(payload.get("start_date"), field="start_date")
        end_date = _date(payload.get("end_date"), field="end_date")
        start = datetime.strptime(start_date, "%Y%m%d")
        end = datetime.strptime(end_date, "%Y%m%d")
        if start > end:
            raise ValueError("start_date must not be after end_date")
        if (end - start).days + 1 > MAX_RANGE_DAYS:
            raise ValueError(f"sync date range must not exceed {MAX_RANGE_DAYS} days")
        idempotency_key = payload.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY.fullmatch(idempotency_key):
            raise ValueError("idempotency_key is invalid")
        request = {
            "provider": "tushare",
            "mode": mode,
            "symbols": symbols,
            "selection": selection,
            "start_date": start_date,
            "end_date": end_date,
        }
        request_sha256 = _canonical_hash(request)
        job_id = f"sync_{uuid.uuid4().hex}"
        now = _now()
        try:
            with self._transaction() as connection:
                existing = fetch_one(
                    connection,
                    "SELECT * FROM data_sync_jobs WHERE idempotency_key = :key",
                    {"key": idempotency_key},
                )
                if existing is not None:
                    if existing["request_sha256"] != request_sha256:
                        raise DataSyncConflict("sync idempotency key was reused")
                    return self._public_job(existing), False
                execute(
                    connection,
                    """INSERT INTO data_sync_jobs
                    (job_id, provider, mode, symbols_json, selection_json, start_date, end_date,
                     status, progress, requested_by, idempotency_key,
                     request_sha256, created_at, updated_at)
                    VALUES (:job_id, 'tushare', :mode, :symbols, :selection, :start_date,
                            :end_date, 'queued', 0, :actor, :idempotency_key,
                            :request_sha256, :now, :now)""",
                    {
                        "job_id": job_id,
                        "mode": mode,
                        "symbols": symbols,
                        "selection": selection,
                        "start_date": start_date,
                        "end_date": end_date,
                        "actor": actor_text,
                        "idempotency_key": idempotency_key,
                        "request_sha256": request_sha256,
                        "now": now,
                    },
                )
                self._audit(connection, job_id, actor_text, "created", "queued", {
                    "mode": mode, "symbol_count": len(symbols), "selection_type": selection_type,
                })
        except IntegrityError as error:
            raise DataSyncConflict("sync job conflicts with existing state") from error
        return self.get_job(job_id), True

    def run_job(
        self,
        job_id: object,
        *,
        provider_factory: Callable[[], TushareProvider],
        market_store: MarketDataStore,
    ) -> dict[str, object]:
        job_id = str(job_id)
        with self._transaction() as connection:
            row = fetch_one(
                connection,
                "SELECT * FROM data_sync_jobs WHERE job_id = :job_id FOR UPDATE",
                {"job_id": job_id},
            )
            if row is None:
                raise DataSyncNotFound("sync job not found")
            if row["status"] in _TERMINAL:
                return self._public_job(row)
            if row["status"] != "queued":
                raise DataSyncConflict("sync job is already running")
            execute(
                connection,
                """UPDATE data_sync_jobs SET status = 'running', started_at = :now,
                   updated_at = :now WHERE job_id = :job_id""",
                {"job_id": job_id, "now": _now()},
            )

        results: list[dict[str, object]] = []
        received = inserted = kept = 0
        try:
            provider = provider_factory()
        except (ProviderError, ValueError) as error:
            code, message = _safe_provider_error(error)
            return self._finish(job_id, [], 0, 0, 0, "failed", code, message)

        symbols = list(row["symbols_json"])
        for index, symbol in enumerate(symbols, start=1):
            try:
                effective_start = str(row["start_date"])
                if row["mode"] == "incremental":
                    latest = market_store.latest_trade_date(symbol)
                    if latest is not None:
                        next_date = (datetime.strptime(latest, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
                        effective_start = max(effective_start, next_date)
                    if effective_start > str(row["end_date"]):
                        results.append({
                            "symbol": symbol,
                            "status": "completed",
                            "rows_received": 0,
                            "rows_inserted": 0,
                            "rows_kept": 0,
                            "date_min": None,
                            "date_max": None,
                            "message": "already_current",
                        })
                        self._set_progress(job_id, round(index * 100 / len(symbols)), results, received, inserted, kept)
                        continue
                request = DailyRequest(
                    ts_code=symbol,
                    start_date=effective_start,
                    end_date=str(row["end_date"]),
                )
                result = provider.fetch_daily(request)
                normalized = self._normalize_bars(
                    symbol,
                    result,
                    start_date=effective_start,
                    end_date=str(row["end_date"]),
                )
                report = market_store.import_bars(normalized, conflict_policy=KEEP_NEW)
                received += len(normalized)
                inserted += int(report["inserted"])
                kept += int(report["kept"])
                results.append({
                    "symbol": symbol,
                    "status": "completed",
                    "rows_received": len(normalized),
                    "rows_inserted": int(report["inserted"]),
                    "rows_kept": int(report["kept"]),
                    "date_min": min((item["trade_date"] for item in normalized), default=None),
                    "date_max": max((item["trade_date"] for item in normalized), default=None),
                })
            except (ProviderError, ValueError, SQLAlchemyError) as error:
                code, message = _safe_provider_error(error)
                results.append({"symbol": symbol, "status": "failed", "error_code": code, "message": message})
            self._set_progress(job_id, round(index * 100 / len(symbols)), results, received, inserted, kept)

        failures = sum(item["status"] == "failed" for item in results)
        status = "failed" if failures == len(results) else "partial" if failures else "completed"
        error_code = "symbol_failures" if failures else None
        error_message = f"{failures} symbol(s) failed" if failures else None
        return self._finish(job_id, results, received, inserted, kept, status, error_code, error_message)

    def list_jobs(self, *, limit: int = 50) -> list[dict[str, object]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return [self._public_job(row) for row in self._execute(
            """SELECT * FROM data_sync_jobs
               ORDER BY created_at DESC, job_id DESC LIMIT :limit""",
            {"limit": limit},
        )]

    def get_job(self, job_id: object) -> dict[str, object]:
        job = self._fetch_one(
            "SELECT * FROM data_sync_jobs WHERE job_id = :job_id",
            {"job_id": str(job_id)},
        )
        if job is None:
            raise DataSyncNotFound("sync job not found")
        return self._public_job(job)

    def coverage_audit(self, *, limit: int = 100) -> dict[str, object]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        with self._transaction() as connection:
            totals = fetch_one(
                connection,
                """SELECT totals.row_count, symbols.symbol_count,
                          totals.date_min, totals.date_max,
                          totals.source_issues, totals.ohlc_issues
                   FROM market_daily_coverage_totals totals
                   CROSS JOIN (
                       SELECT COUNT(*)::bigint AS symbol_count
                       FROM market_daily_symbol_coverage
                   ) symbols
                   WHERE totals.projection_key = 1""",
            ) or {}
            groups = execute(
                connection,
                """SELECT data_source, asset_type, SUM(row_count)::bigint AS row_count,
                          COUNT(*)::bigint AS symbol_count,
                          MIN(date_min) AS date_min, MAX(date_max) AS date_max
                   FROM market_daily_group_symbol_coverage GROUP BY data_source, asset_type
                   ORDER BY data_source, asset_type LIMIT 50""",
            )
            symbols = execute(
                connection,
                """SELECT symbol, row_count, date_min, date_max
                   FROM market_daily_symbol_coverage ORDER BY symbol LIMIT :limit""",
                {"limit": limit},
            )
        row_count = int(totals.get("row_count") or 0)
        issues = int(totals.get("source_issues") or 0) + int(totals.get("ohlc_issues") or 0)
        return {
            "checked_at": _now(),
            "provider": "tushare",
            "scope": "persisted_observations",
            "quality": "empty" if not row_count else "issues" if issues else "observed",
            "completeness_claimed": False,
            "row_count": row_count,
            "symbol_count": int(totals.get("symbol_count") or 0),
            "date_min": totals.get("date_min"),
            "date_max": totals.get("date_max"),
            "source_issues": int(totals.get("source_issues") or 0),
            "ohlc_issues": int(totals.get("ohlc_issues") or 0),
            "groups": groups,
            "symbols": symbols,
        }

    @staticmethod
    def _normalize_bars(
        symbol: str | None,
        result,
        *,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for bar in result.bars:
            if (symbol is not None and bar.ts_code != symbol) or not _SYMBOL.fullmatch(bar.ts_code):
                raise ProviderProtocolError("provider returned an unexpected symbol")
            trade_date = _date(bar.trade_date, field="trade_date")
            if not start_date <= trade_date <= end_date:
                raise ProviderProtocolError("provider returned a bar outside the requested range")
            key = (bar.ts_code, bar.trade_date)
            if key in seen:
                raise ProviderProtocolError("provider returned duplicate daily bars")
            seen.add(key)
            prices = (bar.open, bar.high, bar.low, bar.close)
            if any(value is None for value in prices):
                raise ProviderProtocolError("provider returned incomplete OHLC values")
            open_, high, low, close = (float(value) for value in prices)
            if not all(math.isfinite(value) for value in (open_, high, low, close)):
                raise ProviderProtocolError("provider returned non-finite OHLC values")
            if high < low or low < 0 or not low <= open_ <= high or not low <= close <= high:
                raise ProviderProtocolError("provider returned invalid OHLC relationships")
            volume = None if bar.vol is None else float(bar.vol)
            amount = None if bar.amount is None else float(bar.amount)
            pre_close = None if bar.pre_close is None else float(bar.pre_close)
            if any(value is not None and (not math.isfinite(value) or value < 0) for value in (volume, amount)):
                raise ProviderProtocolError("provider returned invalid volume or amount")
            if pre_close is not None and (not math.isfinite(pre_close) or pre_close < 0):
                raise ProviderProtocolError("provider returned invalid previous close")
            rows.append({
                "symbol": bar.ts_code,
                "trade_date": bar.trade_date,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "pre_close": pre_close,
                "volume": volume,
                "amount": amount,
                "adjust": "none",
                "asset_type": "stock",
                "data_source": "tushare",
                "volume_unit": "lots",
                "amount_unit": "thousand_cny",
                "provenance": result.provenance.as_dict(),
            })
        return sorted(rows, key=lambda item: (str(item["symbol"]), str(item["trade_date"])))

    def _set_progress(
        self,
        job_id: str,
        progress: int,
        results: list[dict[str, object]],
        received: int,
        inserted: int,
        kept: int,
    ) -> None:
        self._execute(
            """UPDATE data_sync_jobs SET progress = :progress,
               symbol_results_json = :results, rows_received = :received,
               rows_inserted = :inserted, rows_kept = :kept, updated_at = :now
               WHERE job_id = :job_id""",
            {
                "job_id": job_id,
                "progress": progress,
                "results": results,
                "received": received,
                "inserted": inserted,
                "kept": kept,
                "now": _now(),
            },
        )

    def _finish(
        self,
        job_id: str,
        results: list[dict[str, object]],
        received: int,
        inserted: int,
        kept: int,
        status: str,
        error_code: str | None,
        error_message: str | None,
    ) -> dict[str, object]:
        now = _now()
        with self._transaction() as connection:
            row = fetch_one(connection, "SELECT * FROM data_sync_jobs WHERE job_id = :job_id", {"job_id": job_id})
            if row is None:
                raise DataSyncNotFound("sync job not found")
            execute(
                connection,
                """UPDATE data_sync_jobs SET status = :status, progress = 100,
                   rows_received = :received, rows_inserted = :inserted,
                   rows_kept = :kept, symbol_results_json = :results,
                   error_code = :error_code, error_message = :error_message,
                   completed_at = :now, updated_at = :now WHERE job_id = :job_id""",
                {
                    "job_id": job_id,
                    "status": status,
                    "received": received,
                    "inserted": inserted,
                    "kept": kept,
                    "results": results,
                    "error_code": error_code,
                    "error_message": error_message,
                    "now": now,
                },
            )
            self._audit(connection, job_id, str(row["requested_by"]), "finished", status, {
                "rows_received": received,
                "rows_inserted": inserted,
                "failed_symbols": sum(item.get("status") == "failed" for item in results),
            })
        return self.get_job(job_id)

    @staticmethod
    def _audit(connection, job_id: str, actor: str, action: str, outcome: str, detail: dict[str, object]) -> None:
        execute(
            connection,
            """INSERT INTO data_sync_audit
            (audit_id, job_id, actor_principal, action, outcome, detail_json, created_at)
            VALUES (:audit_id, :job_id, :actor, :action, :outcome, :detail, :now)""",
            {
                "audit_id": f"syncaudit_{uuid.uuid4().hex}",
                "job_id": job_id,
                "actor": actor,
                "action": action,
                "outcome": outcome,
                "detail": detail,
                "now": _now(),
            },
        )

    @staticmethod
    def _public_job(row: dict[str, object]) -> dict[str, object]:
        symbols = list(row["symbols_json"])
        results = list(row["symbol_results_json"])
        return {
            "job_id": row["job_id"],
            "provider": row["provider"],
            "mode": row["mode"],
            "symbols": symbols[:MAX_PUBLIC_SYMBOLS],
            "symbol_count": len(symbols),
            "symbols_truncated": len(symbols) > MAX_PUBLIC_SYMBOLS,
            "selection": row.get("selection_json") or {"type": "explicit"},
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "status": row["status"],
            "progress": row["progress"],
            "rows_received": row["rows_received"],
            "rows_inserted": row["rows_inserted"],
            "rows_kept": row["rows_kept"],
            "symbol_results": results[:MAX_PUBLIC_RESULTS],
            "result_count": len(results),
            "results_truncated": len(results) > MAX_PUBLIC_RESULTS,
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "requested_by": row["requested_by"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "updated_at": row["updated_at"],
        }
