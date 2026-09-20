"""BYQ Data Plane storage, incremental sync and readiness for index daily indicators.

Phase 100-B owns the authoritative ``index_dailybasic`` dataset: canonical
index/date identity, typed valuation/capital values with their Tushare units
recorded explicitly, per-row provenance/content hashes, an idempotent import
path, and bounded incremental sync jobs keyed by an idempotency key. It never
connects to Community storage and never exposes raw Tushare envelopes or
credentials outside Backend.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .data_provider import (
    INDEX_DAILY_BASIC_FIELDS,
    INDEX_DAILY_BASIC_UNITS,
    IndexDailyBasicRequest,
    ProviderAuthorizationError,
    ProviderCredentialsMissing,
    ProviderError,
    ProviderProtocolError,
    ProviderRateLimited,
    ProviderUnavailable,
    TushareProvider,
)
from .db import PgStoreMixin, execute, fetch_one
from .pg_import import CONFLICT_POLICIES, KEEP_NEW, REPORT_MISMATCH, VERIFY_EQUAL


SCHEMA_VERSION = "index-daily-basic.v1"
MAX_RANGE_DAYS = 400
MAX_READINESS_INDEXES = 32
_MAX_READINESS_SESSIONS = 400
VALUE_FIELDS = tuple(
    field for field in INDEX_DAILY_BASIC_FIELDS if field not in {"ts_code", "trade_date"}
)
_INDEX_SYMBOL = re.compile(r"^[0-9A-Z]{6,12}\.(?:SH|SZ|CSI)$")
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MODES = {"range", "incremental"}
_TERMINAL = {"completed", "failed"}


class IndexIndicatorError(RuntimeError):
    pass


class IndexIndicatorNotFound(IndexIndicatorError):
    pass


class IndexIndicatorConflict(IndexIndicatorError):
    pass


class IndexIndicatorPersistenceError(IndexIndicatorError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _date(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError(f"{field} must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"{field} must be a calendar date in YYYYMMDD") from error
    return value


def _index_symbol(value: object) -> str:
    symbol = str(value).strip().upper()
    if not _INDEX_SYMBOL.fullmatch(symbol):
        raise ValueError("index_symbol has invalid format")
    return symbol


def _provider_error(error: Exception) -> tuple[str, str]:
    if isinstance(error, ProviderCredentialsMissing):
        return "credentials_missing", "Tushare credentials are not configured"
    if isinstance(error, ProviderAuthorizationError):
        return "authorization_failed", "Tushare rejected the configured credentials"
    if isinstance(error, ProviderRateLimited):
        return "rate_limited", "Tushare request was rate limited"
    if isinstance(error, ProviderProtocolError):
        return "provider_protocol_error", "Tushare returned invalid index daily basic data"
    if isinstance(error, ProviderUnavailable):
        return "provider_unavailable", "Tushare is unavailable"
    return "sync_failed", "index daily basic synchronization failed"


def _content_sha256(row: dict[str, Any]) -> str:
    return _canonical_hash({
        key: row[key]
        for key in sorted(row)
        if key not in {"content_sha256", "imported_at", "provenance", "provenance_json"}
    })


class IndexIndicatorStore(PgStoreMixin):
    """Canonical durable index-indicator store with bounded incremental sync."""

    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS market_index_daily_basic (
            index_symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            total_mv DOUBLE PRECISION,
            float_mv DOUBLE PRECISION,
            total_share DOUBLE PRECISION,
            float_share DOUBLE PRECISION,
            free_share DOUBLE PRECISION,
            turnover_rate DOUBLE PRECISION,
            turnover_rate_f DOUBLE PRECISION,
            pe DOUBLE PRECISION,
            pe_ttm DOUBLE PRECISION,
            pb DOUBLE PRECISION,
            units_json JSONB NOT NULL,
            data_source TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            provenance_json JSONB NOT NULL,
            imported_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (index_symbol, trade_date)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS market_index_daily_basic_date_idx
            ON market_index_daily_basic(trade_date)
        """,
        """
        CREATE TABLE IF NOT EXISTS index_indicator_sync_jobs (
            job_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            index_symbol TEXT NOT NULL,
            mode TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            status TEXT NOT NULL,
            progress INTEGER NOT NULL,
            rows_received BIGINT NOT NULL DEFAULT 0,
            rows_inserted BIGINT NOT NULL DEFAULT 0,
            rows_kept BIGINT NOT NULL DEFAULT 0,
            effective_start_date TEXT,
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
        CREATE INDEX IF NOT EXISTS index_indicator_sync_jobs_created_idx
            ON index_indicator_sync_jobs(created_at DESC, job_id DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS index_indicator_sync_audit (
            audit_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES index_indicator_sync_jobs(job_id),
            actor_principal TEXT NOT NULL,
            action TEXT NOT NULL,
            outcome TEXT NOT NULL,
            detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS index_indicator_sync_audit_created_idx
            ON index_indicator_sync_audit(created_at DESC, audit_id DESC)
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as error:
            raise IndexIndicatorPersistenceError("index indicator storage is unavailable") from error

    @classmethod
    def from_env(cls) -> "IndexIndicatorStore":
        return cls()

    @staticmethod
    def _normalize_rows(index_symbol: str, rows: list[object], provenance: dict[str, object]) -> list[dict[str, Any]]:
        if not isinstance(provenance, dict):
            raise ValueError("provenance must be an object")
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in rows:
            symbol = str(getattr(item, "ts_code", "")).strip().upper()
            if symbol != index_symbol:
                raise ProviderProtocolError("provider returned index daily basic for another index")
            trade_date = _date(str(getattr(item, "trade_date", "")), field="trade_date")
            values = getattr(item, "values", None)
            if not isinstance(values, dict) or any(field not in values for field in VALUE_FIELDS):
                raise ProviderProtocolError("provider omitted index daily basic fields")
            if trade_date in seen:
                raise ProviderProtocolError("provider returned duplicate index daily basic rows")
            seen.add(trade_date)
            row: dict[str, Any] = {
                "index_symbol": symbol,
                "trade_date": trade_date,
                "units": dict(INDEX_DAILY_BASIC_UNITS),
                "data_source": "tushare",
                "provenance": provenance,
            }
            for field in VALUE_FIELDS:
                value = values[field]
                if value is not None:
                    value = float(value)
                    if not math.isfinite(value):
                        raise ProviderProtocolError("provider returned non-finite index daily basic values")
                row[field] = value
            row["content_sha256"] = _content_sha256(row)
            normalized.append(row)
        return sorted(normalized, key=lambda item: item["trade_date"])

    def import_rows(
        self,
        index_symbol: object,
        rows: list[object],
        *,
        provenance: dict[str, object],
        conflict_policy: str = KEEP_NEW,
    ) -> dict[str, Any]:
        """Idempotent import of provider-translated index-indicator rows."""
        symbol = _index_symbol(index_symbol)
        if conflict_policy not in CONFLICT_POLICIES:
            raise ValueError(f"conflict_policy must be one of {sorted(CONFLICT_POLICIES)}")
        normalized = self._normalize_rows(symbol, rows, provenance)
        inserted = kept = 0
        mismatches: list[dict[str, Any]] = []
        with self._transaction() as connection:
            for row in normalized:
                existing = fetch_one(
                    connection,
                    """SELECT content_sha256 FROM market_index_daily_basic
                       WHERE index_symbol=:index_symbol AND trade_date=:trade_date FOR UPDATE""",
                    {"index_symbol": symbol, "trade_date": row["trade_date"]},
                )
                if existing is not None:
                    if conflict_policy in {VERIFY_EQUAL, REPORT_MISMATCH} and existing["content_sha256"] != row["content_sha256"]:
                        mismatches.append({
                            "index_symbol": symbol,
                            "trade_date": row["trade_date"],
                            "reason": "verify_equal_mismatch" if conflict_policy == VERIFY_EQUAL else "conflict_reported",
                        })
                    kept += 1
                    continue
                execute(connection, """INSERT INTO market_index_daily_basic
                    (index_symbol, trade_date, total_mv, float_mv, total_share, float_share,
                     free_share, turnover_rate, turnover_rate_f, pe, pe_ttm, pb, units_json,
                     data_source, content_sha256, provenance_json, imported_at)
                    VALUES (:index_symbol, :trade_date, :total_mv, :float_mv, :total_share,
                            :float_share, :free_share, :turnover_rate, :turnover_rate_f,
                            :pe, :pe_ttm, :pb, :units, :data_source, :content_sha256,
                            :provenance, now())""", row)
                inserted += 1
        return {"inserted": inserted, "kept": kept, "reported": len(mismatches), "mismatches": mismatches}

    def latest_trade_date(self, index_symbol: object) -> str | None:
        symbol = _index_symbol(index_symbol)
        row = self._fetch_one(
            "SELECT MAX(trade_date) AS trade_date FROM market_index_daily_basic WHERE index_symbol=:index_symbol",
            {"index_symbol": symbol},
        )
        return None if row is None or row.get("trade_date") is None else str(row["trade_date"])

    def persisted_fingerprint(self, index_symbol: object | None = None) -> dict[str, Any]:
        """Deterministic identity/content digest of persisted rows.

        Lets callers prove that a terminal sync rerun neither refetched nor
        reinserted anything: the digest is unchanged across the rerun.
        """
        params: dict[str, Any] = {}
        clause = ""
        if index_symbol is not None:
            clause = " WHERE index_symbol=:index_symbol"
            params["index_symbol"] = _index_symbol(index_symbol)
        rows = self._execute(
            f"""SELECT index_symbol, trade_date, content_sha256
                FROM market_index_daily_basic{clause}
                ORDER BY index_symbol, trade_date""",
            params,
        )
        canonical = [[str(row["index_symbol"]), str(row["trade_date"]), str(row["content_sha256"])] for row in rows]
        return {"row_count": len(canonical), "content_sha256": _canonical_hash(canonical)}

    def coverage(self) -> dict[str, Any]:
        """Coverage and quality derived from persisted rows, never from a pull."""
        totals = self._fetch_one(
            """SELECT COUNT(*)::bigint AS row_count,
                      COUNT(DISTINCT index_symbol)::bigint AS index_count,
                      MIN(trade_date) AS date_min, MAX(trade_date) AS date_max
               FROM market_index_daily_basic"""
        ) or {}
        groups = self._execute(
            """SELECT index_symbol, COUNT(*)::bigint AS row_count,
                      MIN(trade_date) AS date_min, MAX(trade_date) AS date_max,
                      COUNT(*) FILTER (WHERE total_mv < 0 OR float_mv < 0
                        OR total_share < 0 OR float_share < 0 OR free_share < 0
                        OR turnover_rate < 0 OR turnover_rate_f < 0)::bigint AS negative_issues
               FROM market_index_daily_basic GROUP BY index_symbol ORDER BY index_symbol LIMIT 64"""
        )
        row_count = int(totals.get("row_count") or 0)
        issues = sum(int(group["negative_issues"]) for group in groups)
        return {
            "schema_version": SCHEMA_VERSION,
            "provider": "tushare",
            "endpoint": "index_dailybasic",
            "scope": "persisted_observations",
            "completeness_claimed": False,
            "quality": "empty" if not row_count else "issues" if issues else "observed",
            "row_count": row_count,
            "index_count": int(totals.get("index_count") or 0),
            "date_min": totals.get("date_min"),
            "date_max": totals.get("date_max"),
            "issue_count": issues,
            "units": dict(INDEX_DAILY_BASIC_UNITS),
            "groups": groups,
        }

    def readiness(
        self,
        *,
        index_symbols: object,
        start_date: object,
        end_date: object,
        fields: object,
    ) -> dict[str, Any]:
        """Exact-session readiness from the authoritative store, fail-closed on gaps."""
        if not isinstance(index_symbols, list) or not index_symbols:
            raise ValueError("index_symbols must be a non-empty list")
        symbols = sorted({_index_symbol(symbol) for symbol in index_symbols})
        if len(symbols) != len(index_symbols):
            raise ValueError("index_symbols must be unique canonical index codes")
        if len(symbols) > MAX_READINESS_INDEXES:
            raise ValueError(f"index_symbols exceeds {MAX_READINESS_INDEXES} entries")
        start = _date(start_date, field="start_date")
        end = _date(end_date, field="end_date")
        if start > end:
            raise ValueError("start_date must not be after end_date")
        if (datetime.strptime(end, "%Y%m%d") - datetime.strptime(start, "%Y%m%d")).days + 1 > _MAX_READINESS_SESSIONS:
            raise ValueError(f"readiness range must not exceed {_MAX_READINESS_SESSIONS} days")
        if not isinstance(fields, list) or not fields:
            raise ValueError("fields must be a non-empty list")
        normalized_fields = list(dict.fromkeys(fields))
        if any(field not in VALUE_FIELDS for field in normalized_fields):
            raise ValueError("fields contains an unsupported index daily basic field")
        sessions = [str(row["trade_date"]) for row in self._execute(
            """SELECT trade_date FROM market_trading_sessions
               WHERE is_open=TRUE AND trade_date BETWEEN :start AND :end ORDER BY trade_date""",
            {"start": start, "end": end},
        )]
        selected = ", ".join(normalized_fields)
        rows = self._execute(
            f"""SELECT index_symbol, trade_date, {selected}, data_source, content_sha256, provenance_json
                FROM market_index_daily_basic
                WHERE index_symbol IN (SELECT jsonb_array_elements_text(:symbols))
                  AND trade_date BETWEEN :start AND :end
                ORDER BY trade_date, index_symbol LIMIT :query_limit""",
            {
                "symbols": symbols,
                "start": start,
                "end": end,
                "query_limit": MAX_READINESS_INDEXES * _MAX_READINESS_SESSIONS + 1,
            },
        )
        if len(rows) > MAX_READINESS_INDEXES * _MAX_READINESS_SESSIONS:
            raise ValueError("index daily basic readiness window exceeds bounded rows")
        by_key = {(str(row["index_symbol"]), str(row["trade_date"])): row for row in rows}
        missing: list[dict[str, str]] = []
        missing_fields: list[dict[str, object]] = []
        for symbol in symbols:
            for session in sessions:
                if (symbol, session) not in by_key:
                    missing.append({"index_symbol": symbol, "trade_date": session, "reason": "index_daily_basic_unavailable"})
        evidence: list[dict[str, Any]] = []
        for row in rows:
            null_fields = [field for field in normalized_fields if row[field] is None]
            if null_fields:
                missing_fields.append({"index_symbol": row["index_symbol"], "trade_date": row["trade_date"], "fields": null_fields})
            evidence.append({
                "index_symbol": str(row["index_symbol"]),
                "trade_date": str(row["trade_date"]),
                "values": {field: row[field] for field in normalized_fields},
                "data_source": str(row["data_source"]),
                "content_sha256": str(row["content_sha256"]),
                "provenance": row.get("provenance_json") or {},
            })
        calendar_verified = bool(sessions)
        return {
            "schema_version": "index-daily-basic-readiness.v1",
            "index_symbols": symbols,
            "start_date": start,
            "end_date": end,
            "fields": normalized_fields,
            "units": {field: INDEX_DAILY_BASIC_UNITS[field] for field in normalized_fields},
            "rows": evidence,
            "coverage": {
                "usable": calendar_verified and not missing and not missing_fields,
                "calendar_verified": calendar_verified,
                "requested_sessions": sessions,
                "returned_rows": len(evidence),
                "missing": missing[:200],
                "missing_fields": missing_fields[:200],
            },
        }

    def create_sync_job(self, payload: object, *, actor: object) -> tuple[dict[str, Any], bool]:
        if not isinstance(payload, dict):
            raise ValueError("index indicator sync request must be an object")
        allowed = {"index_symbol", "mode", "start_date", "end_date", "idempotency_key"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"index indicator sync request has unknown fields: {', '.join(unknown)}")
        actor_text = str(actor).strip()
        if not actor_text or len(actor_text) > 128:
            raise ValueError("actor principal is invalid")
        index_symbol = _index_symbol(payload.get("index_symbol"))
        mode = payload.get("mode", "incremental")
        if mode not in _MODES:
            raise ValueError("index indicator sync mode must be range or incremental")
        start = _date(payload.get("start_date"), field="start_date")
        end = _date(payload.get("end_date"), field="end_date")
        if start > end:
            raise ValueError("start_date must not be after end_date")
        if (datetime.strptime(end, "%Y%m%d") - datetime.strptime(start, "%Y%m%d")).days > MAX_RANGE_DAYS:
            raise ValueError(f"index indicator sync range must not exceed {MAX_RANGE_DAYS} days")
        idempotency_key = payload.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY.fullmatch(idempotency_key):
            raise ValueError("idempotency_key is invalid")
        request = {
            "provider": "tushare", "index_symbol": index_symbol, "mode": mode,
            "start_date": start, "end_date": end,
        }
        request_sha256 = _canonical_hash(request)
        job_id = f"indexsync_{uuid.uuid4().hex}"
        now = _now()
        try:
            with self._transaction() as connection:
                existing = fetch_one(
                    connection,
                    "SELECT * FROM index_indicator_sync_jobs WHERE idempotency_key=:key",
                    {"key": idempotency_key},
                )
                if existing is not None:
                    if existing["request_sha256"] != request_sha256:
                        raise IndexIndicatorConflict("index indicator idempotency key was reused")
                    return self._public_job(existing), False
                execute(connection, """INSERT INTO index_indicator_sync_jobs
                    (job_id, provider, index_symbol, mode, start_date, end_date, status,
                     progress, requested_by, idempotency_key, request_sha256, created_at, updated_at)
                    VALUES (:job_id, 'tushare', :index_symbol, :mode, :start_date, :end_date,
                            'queued', 0, :actor, :idempotency_key, :request_sha256, :now, :now)""", {
                    "job_id": job_id,
                    "index_symbol": index_symbol,
                    "mode": mode,
                    "start_date": start,
                    "end_date": end,
                    "actor": actor_text,
                    "idempotency_key": idempotency_key,
                    "request_sha256": request_sha256,
                    "now": now,
                })
                self._audit(connection, job_id, actor_text, "created", "queued", {
                    "mode": mode, "index_symbol": index_symbol,
                })
        except IntegrityError as error:
            raise IndexIndicatorConflict("index indicator sync conflicts with existing state") from error
        return self.get_sync_job(job_id), True

    def run_sync_job(
        self,
        job_id: object,
        *,
        provider_factory: Callable[[], TushareProvider],
    ) -> dict[str, Any]:
        job_id = str(job_id)
        with self._transaction() as connection:
            row = fetch_one(
                connection,
                "SELECT * FROM index_indicator_sync_jobs WHERE job_id=:job_id FOR UPDATE",
                {"job_id": job_id},
            )
            if row is None:
                raise IndexIndicatorNotFound("index indicator sync job not found")
            if row["status"] in _TERMINAL:
                return self._public_job(row)
            if row["status"] != "queued":
                raise IndexIndicatorConflict("index indicator sync job is already running")
            execute(connection, """UPDATE index_indicator_sync_jobs
                SET status='running', progress=10, started_at=:now, updated_at=:now
                WHERE job_id=:job_id""", {"job_id": job_id, "now": _now()})

        index_symbol = str(row["index_symbol"])
        effective_start = str(row["start_date"])
        if row["mode"] == "incremental":
            latest = self.latest_trade_date(index_symbol)
            if latest is not None:
                next_date = (datetime.strptime(latest, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
                effective_start = max(effective_start, next_date)
        if effective_start > str(row["end_date"]):
            return self._finish_job(
                job_id, status="completed", symbol=index_symbol, effective_start=effective_start,
                received=0, inserted=0, kept=0,
            )
        try:
            provider = provider_factory()
        except (ProviderError, ValueError) as error:
            code, message = _provider_error(error)
            return self._finish_job(
                job_id, status="failed", symbol=index_symbol, effective_start=effective_start,
                received=0, inserted=0, kept=0, error_code=code, error_message=message,
            )
        try:
            result = provider.fetch_index_daily_basic(IndexDailyBasicRequest(
                ts_code=index_symbol, start_date=effective_start, end_date=str(row["end_date"]),
            ))
            report = self.import_rows(index_symbol, list(result.rows), provenance=result.provenance.as_dict())
        except (ProviderError, ValueError, SQLAlchemyError) as error:
            code, message = _provider_error(error)
            return self._finish_job(
                job_id, status="failed", symbol=index_symbol, effective_start=effective_start,
                received=0, inserted=0, kept=0, error_code=code, error_message=message,
            )
        return self._finish_job(
            job_id, status="completed", symbol=index_symbol, effective_start=effective_start,
            received=len(result.rows), inserted=int(report["inserted"]), kept=int(report["kept"]),
        )

    def list_sync_jobs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return [self._public_job(row) for row in self._execute(
            """SELECT * FROM index_indicator_sync_jobs
               ORDER BY created_at DESC, job_id DESC LIMIT :limit""",
            {"limit": limit},
        )]

    def get_sync_job(self, job_id: object) -> dict[str, Any]:
        row = self._fetch_one(
            "SELECT * FROM index_indicator_sync_jobs WHERE job_id=:job_id",
            {"job_id": str(job_id)},
        )
        if row is None:
            raise IndexIndicatorNotFound("index indicator sync job not found")
        return self._public_job(row)

    def _finish_job(
        self, job_id: str, *, status: str, symbol: str, effective_start: str,
        received: int, inserted: int, kept: int,
        error_code: str | None = None, error_message: str | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with self._transaction() as connection:
            row = fetch_one(connection, "SELECT * FROM index_indicator_sync_jobs WHERE job_id=:job_id", {"job_id": job_id})
            if row is None:
                raise IndexIndicatorNotFound("index indicator sync job not found")
            execute(connection, """UPDATE index_indicator_sync_jobs SET
                status=:status, progress=100, rows_received=:received, rows_inserted=:inserted,
                rows_kept=:kept, effective_start_date=:effective_start, error_code=:error_code,
                error_message=:error_message, completed_at=:now, updated_at=:now
                WHERE job_id=:job_id""", {
                "job_id": job_id, "status": status, "received": received, "inserted": inserted,
                "kept": kept, "effective_start": effective_start, "error_code": error_code,
                "error_message": error_message, "now": now,
            })
            self._audit(connection, job_id, str(row["requested_by"]), "finished", status, {
                "index_symbol": symbol, "effective_start_date": effective_start,
                "rows_received": received, "rows_inserted": inserted, "rows_kept": kept,
            })
        return self.get_sync_job(job_id)

    @staticmethod
    def _audit(connection, job_id: str, actor: str, action: str, outcome: str, detail: dict[str, object]) -> None:
        execute(connection, """INSERT INTO index_indicator_sync_audit
            (audit_id, job_id, actor_principal, action, outcome, detail_json, created_at)
            VALUES (:audit_id, :job_id, :actor, :action, :outcome, :detail, :now)""", {
            "audit_id": f"indexaudit_{uuid.uuid4().hex}",
            "job_id": job_id, "actor": actor, "action": action, "outcome": outcome,
            "detail": detail, "now": _now(),
        })

    @staticmethod
    def _public_job(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "provider": row["provider"],
            "index_symbol": row["index_symbol"],
            "mode": row["mode"],
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "status": row["status"],
            "progress": row["progress"],
            "rows_received": row["rows_received"],
            "rows_inserted": row["rows_inserted"],
            "rows_kept": row["rows_kept"],
            "effective_start_date": row["effective_start_date"],
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "requested_by": row["requested_by"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "updated_at": row["updated_at"],
        }
