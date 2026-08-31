"""Durable daily market synchronization scheduler and worker contracts.

The Backend owns configuration and public projections.  A separate trusted
Data Plane worker refreshes the trading calendar, creates one idempotent job
per open session, and imports one full-market Tushare ``daily`` snapshot.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError

from .data_provider import (
    DailyRequest,
    ProviderError,
    ProviderProtocolError,
    TradingCalendarRequest,
    TushareProvider,
)
from .data_sync import DataSyncStore, _safe_provider_error
from .db import PgStoreMixin, execute, fetch_one
from .market_data import MarketDataStore
from .index_catalog import INDEX_WEIGHT_LOOKBACK_DAYS, SUPPORTED_INDEXES
from .market_readiness import MarketReadinessStore
from .pg_import import KEEP_NEW


TIMEZONE = "Asia/Shanghai"
DEFAULT_SCHEDULE_TIME = "18:30"
DEFAULT_CATCHUP_DAYS = 7
MAX_CATCHUP_DAYS = 30
MAX_ATTEMPTS = 4
LEASE_SECONDS = 900
CORE_BENCHMARK = "000300.SH"
_TIME = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class MarketAutomationError(RuntimeError):
    pass


class MarketAutomationConflict(MarketAutomationError):
    pass


class MarketAutomationNotFound(MarketAutomationError):
    pass


class MarketAutomationPersistenceError(MarketAutomationError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _local_now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(ZoneInfo(TIMEZONE))


def _iso_timestamp(value: object) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


class MarketAutomationStore(PgStoreMixin):
    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS market_sync_config (
            config_id TEXT PRIMARY KEY,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            schedule_time TEXT NOT NULL DEFAULT '18:30',
            timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
            catchup_days INTEGER NOT NULL DEFAULT 7,
            security_master_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            version INTEGER NOT NULL DEFAULT 1,
            updated_by TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        INSERT INTO market_sync_config
            (config_id, enabled, schedule_time, timezone, catchup_days,
             security_master_enabled, version, updated_by, updated_at)
        VALUES ('default', FALSE, '18:30', 'Asia/Shanghai', 7, TRUE, 1, 'system', now())
        ON CONFLICT (config_id) DO NOTHING
        """,
        """
        CREATE TABLE IF NOT EXISTS market_sync_config_requests (
            idempotency_key TEXT PRIMARY KEY,
            request_sha256 TEXT NOT NULL,
            result_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS market_trading_sessions (
            trade_date TEXT PRIMARY KEY,
            exchange TEXT NOT NULL,
            is_open BOOLEAN NOT NULL,
            previous_open_date TEXT,
            data_source TEXT NOT NULL,
            request_fingerprint TEXT NOT NULL,
            retrieved_at TIMESTAMPTZ NOT NULL,
            content_sha256 TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS market_trading_sessions_open_idx
            ON market_trading_sessions(is_open, trade_date DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS market_session_sync_jobs (
            job_id TEXT PRIMARY KEY,
            trade_date TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 4,
            rows_received BIGINT NOT NULL DEFAULT 0,
            rows_inserted BIGINT NOT NULL DEFAULT 0,
            rows_kept BIGINT NOT NULL DEFAULT 0,
            dataset_sha256 TEXT,
            error_code TEXT,
            error_message TEXT,
            scheduled_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ,
            next_attempt_at TIMESTAMPTZ,
            lease_until TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS market_session_sync_jobs_claim_idx
            ON market_session_sync_jobs(status, next_attempt_at, trade_date)
        """,
        """
        CREATE TABLE IF NOT EXISTS market_session_completeness (
            trade_date TEXT PRIMARY KEY REFERENCES market_trading_sessions(trade_date),
            state TEXT NOT NULL,
            row_count BIGINT NOT NULL,
            dataset_sha256 TEXT NOT NULL,
            request_fingerprint TEXT NOT NULL,
            verified_at TIMESTAMPTZ NOT NULL,
            job_id TEXT NOT NULL REFERENCES market_session_sync_jobs(job_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS market_sync_worker_state (
            worker_id TEXT PRIMARY KEY,
            heartbeat_at TIMESTAMPTZ NOT NULL,
            last_scheduler_check_at TIMESTAMPTZ,
            last_calendar_refresh_at TIMESTAMPTZ,
            last_job_id TEXT,
            last_scheduled_date TEXT,
            last_error TEXT,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        ALTER TABLE market_sync_worker_state
            ADD COLUMN IF NOT EXISTS last_scheduled_date TEXT
        """,
        """
        CREATE TABLE IF NOT EXISTS market_sync_run_requests (
            request_id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            claimed_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            result_json JSONB,
            error_message TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS market_data_repair_requests (
            request_id TEXT PRIMARY KEY,
            requirement_sha256 TEXT NOT NULL UNIQUE,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            requirement_json JSONB NOT NULL,
            status TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            claimed_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            error_message TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS market_index_catalog_sync_runs (
            run_id TEXT PRIMARY KEY,
            requested_as_of TEXT NOT NULL,
            status TEXT NOT NULL,
            result_json JSONB NOT NULL,
            requested_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS market_index_catalog_sync_runs_date_idx
            ON market_index_catalog_sync_runs(requested_as_of DESC, created_at DESC)
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as error:
            raise MarketAutomationPersistenceError("market automation storage is unavailable") from error

    def get_config(self) -> dict[str, object]:
        row = self._fetch_one("SELECT * FROM market_sync_config WHERE config_id = 'default'")
        if row is None:
            raise MarketAutomationNotFound("market sync configuration not found")
        return self._public_config(row)

    def update_config(self, payload: object, *, actor: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("market sync configuration must be an object")
        allowed = {
            "enabled", "schedule_time", "catchup_days", "security_master_enabled",
            "expected_version", "idempotency_key",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"market sync configuration has unknown fields: {', '.join(unknown)}")
        if not isinstance(payload.get("enabled"), bool):
            raise ValueError("enabled must be boolean")
        schedule_time = payload.get("schedule_time")
        if not isinstance(schedule_time, str) or not _TIME.fullmatch(schedule_time):
            raise ValueError("schedule_time must use HH:MM")
        catchup_days = payload.get("catchup_days")
        if isinstance(catchup_days, bool) or not isinstance(catchup_days, int) or not 1 <= catchup_days <= MAX_CATCHUP_DAYS:
            raise ValueError(f"catchup_days must be between 1 and {MAX_CATCHUP_DAYS}")
        if not isinstance(payload.get("security_master_enabled"), bool):
            raise ValueError("security_master_enabled must be boolean")
        expected_version = payload.get("expected_version")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1:
            raise ValueError("expected_version must be a positive integer")
        key = payload.get("idempotency_key")
        if not isinstance(key, str) or not _IDEMPOTENCY.fullmatch(key):
            raise ValueError("idempotency_key is invalid")
        actor_text = str(actor).strip()
        if not actor_text or len(actor_text) > 128:
            raise ValueError("actor principal is invalid")
        request = {
            "enabled": payload["enabled"],
            "schedule_time": schedule_time,
            "catchup_days": catchup_days,
            "security_master_enabled": payload["security_master_enabled"],
            "expected_version": expected_version,
        }
        request_sha = _hash(request)
        with self._transaction() as connection:
            replay = fetch_one(
                connection,
                "SELECT * FROM market_sync_config_requests WHERE idempotency_key = :key",
                {"key": key},
            )
            if replay is not None:
                if replay["request_sha256"] != request_sha:
                    raise MarketAutomationConflict("market sync configuration idempotency key was reused")
                return dict(replay["result_json"])
            current = fetch_one(
                connection,
                "SELECT * FROM market_sync_config WHERE config_id = 'default' FOR UPDATE",
            )
            if current is None:
                raise MarketAutomationNotFound("market sync configuration not found")
            if int(current["version"]) != expected_version:
                raise MarketAutomationConflict("market sync configuration version conflict")
            now = _now()
            execute(
                connection,
                """UPDATE market_sync_config SET enabled = :enabled,
                   schedule_time = :schedule_time, catchup_days = :catchup_days,
                   security_master_enabled = :security_master_enabled,
                   version = version + 1, updated_by = :actor, updated_at = :now
                   WHERE config_id = 'default'""",
                {**request, "actor": actor_text, "now": now},
            )
            updated = fetch_one(connection, "SELECT * FROM market_sync_config WHERE config_id = 'default'")
            assert updated is not None
            result = self._public_config(updated)
            execute(
                connection,
                """INSERT INTO market_sync_config_requests
                   (idempotency_key, request_sha256, result_json, created_at)
                   VALUES (:key, :sha, :result, :now)""",
                {"key": key, "sha": request_sha, "result": result, "now": now},
            )
        return result

    def refresh_calendar(
        self,
        provider: TushareProvider,
        *,
        start_date: str,
        end_date: str,
    ) -> dict[str, object]:
        result = provider.fetch_trading_calendar(TradingCalendarRequest(start_date, end_date))
        if not result.sessions:
            raise ProviderProtocolError("provider returned an empty trading calendar")
        now = _now()
        with self._transaction() as connection:
            for session in result.sessions:
                content = session.as_dict()
                execute(
                    connection,
                    """INSERT INTO market_trading_sessions
                       (trade_date, exchange, is_open, previous_open_date, data_source,
                        request_fingerprint, retrieved_at, content_sha256, updated_at)
                       VALUES (:trade_date, :exchange, :is_open, :previous_open_date,
                               'tushare', :request_fingerprint, :retrieved_at, :sha, :now)
                       ON CONFLICT (trade_date) DO UPDATE SET
                         exchange = excluded.exchange, is_open = excluded.is_open,
                         previous_open_date = excluded.previous_open_date,
                         data_source = excluded.data_source,
                         request_fingerprint = excluded.request_fingerprint,
                         retrieved_at = excluded.retrieved_at,
                         content_sha256 = excluded.content_sha256,
                         updated_at = excluded.updated_at""",
                    {
                        **content,
                        "request_fingerprint": result.provenance.request_fingerprint,
                        "retrieved_at": result.provenance.retrieved_at,
                        "sha": _hash(content),
                        "now": now,
                    },
                )
        return {
            "start_date": start_date,
            "end_date": end_date,
            "row_count": len(result.sessions),
            "open_count": sum(item.is_open for item in result.sessions),
            "request_fingerprint": result.provenance.request_fingerprint,
        }

    def request_run_now(self, payload: object, *, actor: object) -> tuple[dict[str, object], bool]:
        if not isinstance(payload, dict) or set(payload) != {"idempotency_key"}:
            raise ValueError("run-now request must contain exactly idempotency_key")
        key = payload.get("idempotency_key")
        if not isinstance(key, str) or not _IDEMPOTENCY.fullmatch(key):
            raise ValueError("idempotency_key is invalid")
        actor_text = str(actor).strip()
        if not actor_text or len(actor_text) > 128:
            raise ValueError("actor principal is invalid")
        with self._transaction() as connection:
            existing = fetch_one(
                connection,
                "SELECT * FROM market_sync_run_requests WHERE idempotency_key = :key",
                {"key": key},
            )
            if existing is not None:
                return self._public_run_request(existing), False
            request_id = f"market_run_{uuid.uuid4().hex}"
            execute(
                connection,
                """INSERT INTO market_sync_run_requests
                   (request_id, idempotency_key, status, requested_by, created_at)
                   VALUES (:request_id, :key, 'queued', :actor, :now)""",
                {"request_id": request_id, "key": key, "actor": actor_text, "now": _now()},
            )
        return self.get_run_request(request_id), True

    def claim_run_request(self) -> dict[str, object] | None:
        with self._transaction() as connection:
            row = fetch_one(
                connection,
                """SELECT * FROM market_sync_run_requests WHERE status = 'queued'
                   ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1""",
            )
            if row is None:
                return None
            execute(
                connection,
                """UPDATE market_sync_run_requests SET status = 'running', claimed_at = :now
                   WHERE request_id = :request_id""",
                {"request_id": row["request_id"], "now": _now()},
            )
        return self.get_run_request(row["request_id"])

    def complete_run_request(
        self,
        request_id: object,
        *,
        result: list[dict[str, object]] | None = None,
        error: str | None = None,
    ) -> dict[str, object]:
        self._execute(
            """UPDATE market_sync_run_requests SET status = :status,
               completed_at = :now, result_json = :result, error_message = :error
               WHERE request_id = :request_id""",
            {
                "request_id": str(request_id),
                "status": "failed" if error else "completed",
                "now": _now(),
                "result": result or [],
                "error": error,
            },
        )
        return self.get_run_request(request_id)

    def get_run_request(self, request_id: object) -> dict[str, object]:
        row = self._fetch_one(
            "SELECT * FROM market_sync_run_requests WHERE request_id = :request_id",
            {"request_id": str(request_id)},
        )
        if row is None:
            raise MarketAutomationNotFound("market sync run request not found")
        return self._public_run_request(row)

    def enqueue_due_sessions(
        self,
        *,
        now: datetime | None = None,
        force: bool = False,
        scheduled_by: str = "scheduler",
    ) -> list[dict[str, object]]:
        local = _local_now(now)
        config = self.get_config()
        if not force:
            if not config["enabled"] or local.strftime("%H:%M") < config["schedule_time"]:
                return []
        first = (local.date() - timedelta(days=int(config["catchup_days"]) - 1)).strftime("%Y%m%d")
        last = local.strftime("%Y%m%d")
        sessions = self._execute(
            """SELECT trade_date FROM market_trading_sessions
               WHERE is_open = TRUE AND trade_date BETWEEN :first AND :last
               ORDER BY trade_date""",
            {"first": first, "last": last},
        )
        created: list[dict[str, object]] = []
        for session in sessions:
            trade_date = str(session["trade_date"])
            with self._transaction() as connection:
                existing = fetch_one(
                    connection,
                    "SELECT * FROM market_session_sync_jobs WHERE trade_date = :trade_date FOR UPDATE",
                    {"trade_date": trade_date},
                )
                now_text = _now()
                if existing is None:
                    job_id = f"market_session_{uuid.uuid4().hex}"
                    execute(
                        connection,
                        """INSERT INTO market_session_sync_jobs
                           (job_id, trade_date, status, scheduled_by, created_at, updated_at)
                           VALUES (:job_id, :trade_date, 'queued', :scheduled_by, :now, :now)""",
                        {
                            "job_id": job_id,
                            "trade_date": trade_date,
                            "scheduled_by": scheduled_by,
                            "now": now_text,
                        },
                    )
                elif force and existing["status"] == "failed":
                    job_id = str(existing["job_id"])
                    execute(
                        connection,
                        """UPDATE market_session_sync_jobs SET status = 'queued', attempts = 0,
                           next_attempt_at = NULL, lease_until = NULL, error_code = NULL,
                           error_message = NULL, completed_at = NULL, updated_at = :now
                           WHERE job_id = :job_id""",
                        {"job_id": job_id, "now": now_text},
                    )
                else:
                    continue
            created.append(self.get_job(job_id))
        return created

    def enqueue_dates(
        self,
        trade_dates: list[str],
        *,
        scheduled_by: str,
        force_completed: bool = False,
    ) -> list[dict[str, object]]:
        """Queue a bounded, calendar-verified repair without broad provider access."""
        dates = sorted(set(str(value) for value in trade_dates))
        if len(dates) > 250:
            raise ValueError("data repair exceeds 250 trading sessions")
        created: list[dict[str, object]] = []
        for trade_date in dates:
            session = self._fetch_one(
                "SELECT is_open FROM market_trading_sessions WHERE trade_date=:date", {"date": trade_date},
            )
            if session is None or not session["is_open"]:
                raise ValueError("data repair date is not a known open trading session")
            with self._transaction() as connection:
                existing = fetch_one(connection,
                    "SELECT * FROM market_session_sync_jobs WHERE trade_date=:date FOR UPDATE",
                    {"date": trade_date})
                if existing is None:
                    job_id, now = f"market_session_{uuid.uuid4().hex}", _now()
                    execute(connection, """INSERT INTO market_session_sync_jobs
                        (job_id,trade_date,status,scheduled_by,created_at,updated_at)
                        VALUES (:job_id,:date,'queued',:by,:now,:now)""",
                        {"job_id": job_id, "date": trade_date, "by": scheduled_by, "now": now})
                elif existing["status"] == "failed" or (
                    existing["status"] == "completed" and (
                        force_completed
                        or self._fetch_one("""SELECT state FROM market_session_completeness
                            WHERE trade_date=:date AND state='provider_snapshot_with_declared_inputs_complete'""",
                            {"date": trade_date}) is None
                    )
                ):
                    job_id, now = str(existing["job_id"]), _now()
                    execute(connection, """UPDATE market_session_sync_jobs SET status='queued',attempts=0,
                        next_attempt_at=NULL,lease_until=NULL,error_code=NULL,error_message=NULL,
                        completed_at=NULL,updated_at=:now WHERE job_id=:job_id""",
                        {"job_id": job_id, "now": now})
                else:
                    continue
            created.append(self.get_job(job_id))
        return created

    def request_data_repair(
        self, *, requirement: dict[str, object], requested_by: str,
    ) -> dict[str, object]:
        requirement_sha256 = str(requirement["requirement_sha256"])
        start_date, end_date = str(requirement["start_date"]), str(requirement["end_date"])
        existing = self._fetch_one("SELECT * FROM market_data_repair_requests WHERE requirement_sha256=:sha",
                                   {"sha": requirement_sha256})
        if existing is not None:
            if existing["status"] in {"completed", "failed"}:
                self._execute("""UPDATE market_data_repair_requests
                    SET status='queued',claimed_at=NULL,completed_at=NULL,error_message=NULL,
                        requested_by=:by WHERE request_id=:id""",
                    {"id": existing["request_id"], "by": requested_by})
                existing = self._fetch_one(
                    "SELECT * FROM market_data_repair_requests WHERE request_id=:id",
                    {"id": existing["request_id"]},
                )
            return dict(existing)
        request_id, now = f"datarepair_{uuid.uuid4().hex}", _now()
        self._execute("""INSERT INTO market_data_repair_requests
            (request_id,requirement_sha256,start_date,end_date,requirement_json,status,requested_by,created_at)
            VALUES (:id,:sha,:start,:end,:requirement,'queued',:by,:now)""",
            {"id": request_id, "sha": requirement_sha256, "start": start_date,
             "end": end_date, "requirement": requirement, "by": requested_by, "now": now})
        return dict(self._fetch_one("SELECT * FROM market_data_repair_requests WHERE request_id=:id",
                                    {"id": request_id}) or {})

    def claim_data_repair(self) -> dict[str, object] | None:
        with self._transaction() as connection:
            row = fetch_one(connection, """SELECT * FROM market_data_repair_requests
                WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1""")
            if row is None:
                return None
            execute(connection, """UPDATE market_data_repair_requests SET status='running',claimed_at=:now
                WHERE request_id=:id""", {"id": row["request_id"], "now": _now()})
        return dict(row)

    def complete_data_repair(self, request_id: str, *, error: str | None = None) -> None:
        self._execute("""UPDATE market_data_repair_requests SET status=:status,completed_at=:now,error_message=:error
            WHERE request_id=:id""", {"id": request_id, "status": "failed" if error else "completed",
                                      "now": _now(), "error": error})

    def defer_data_repair(self, request_id: object) -> dict[str, object]:
        rows = self._execute("""UPDATE market_data_repair_requests
            SET status='waiting_for_sessions',completed_at=NULL,error_message=NULL
            WHERE request_id=:id AND status='running' RETURNING *""", {"id": str(request_id)})
        if not rows:
            raise MarketAutomationConflict("data repair is not running")
        return dict(rows[0])

    def retry_data_repair(self, request_id: object) -> dict[str, object]:
        rows = self._execute("""UPDATE market_data_repair_requests
            SET status='queued',claimed_at=NULL,completed_at=NULL,error_message=NULL
            WHERE request_id=:id AND status IN ('completed','failed') RETURNING *""",
            {"id": str(request_id)})
        if not rows:
            raise MarketAutomationConflict("data repair is not retryable")
        return dict(rows[0])

    def reconcile_data_repairs(self, readiness_store: MarketReadinessStore) -> dict[str, int]:
        outcomes = {"completed": 0, "failed": 0}
        rows = self._execute("""SELECT * FROM market_data_repair_requests
            WHERE status='waiting_for_sessions' ORDER BY created_at LIMIT 32""")
        for row in rows:
            try:
                assessment = readiness_store.assess(dict(row["requirement_json"]))
                if assessment.get("state") == "ready":
                    self.complete_data_repair(str(row["request_id"]))
                    outcomes["completed"] += 1
                    continue
                counts = self.session_job_counts(list(assessment.get("missing_trade_dates", [])))
                if counts["queued"] + counts["running"]:
                    continue
                error = "session_repair_failed" if counts["failed"] else "readiness_not_satisfied"
                self.complete_data_repair(str(row["request_id"]), error=error)
                outcomes["failed"] += 1
            except Exception:
                self.complete_data_repair(
                    str(row["request_id"]), error="readiness_assessment_failed",
                )
                outcomes["failed"] += 1
        return outcomes

    def get_data_repairs(self, request_ids: list[str]) -> list[dict[str, object]]:
        """Return bounded repair coordinator state for a BYQ-owned facade."""
        ids = sorted({str(value) for value in request_ids if str(value)})
        if not ids or len(ids) > 16:
            raise ValueError("data repair request ids must contain between 1 and 16 entries")
        return [dict(row) for row in self._execute(
            """SELECT request_id,status,error_message,created_at,claimed_at,completed_at
               FROM market_data_repair_requests
               WHERE request_id IN (SELECT jsonb_array_elements_text(:ids))
               ORDER BY created_at,request_id""",
            {"ids": ids},
        )]

    def session_job_counts(self, trade_dates: list[str]) -> dict[str, int]:
        """Summarize trusted per-session work without exposing worker payloads."""
        dates = sorted({str(value) for value in trade_dates if str(value)})
        if not dates:
            return {"queued": 0, "running": 0, "completed": 0, "failed": 0}
        if len(dates) > 1_300:
            raise ValueError("data demand exceeds session progress bounds")
        rows = self._execute(
            """SELECT status,COUNT(*)::integer AS count FROM market_session_sync_jobs
               WHERE trade_date IN (SELECT jsonb_array_elements_text(:dates))
               GROUP BY status""",
            {"dates": dates},
        )
        counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0}
        for row in rows:
            status = str(row["status"])
            if status in counts:
                counts[status] = int(row["count"])
        return counts

    def claim_next_job(
        self, *, worker_id: str, now: datetime | None = None,
    ) -> dict[str, object] | None:
        claimed_at = now or datetime.now(timezone.utc)
        if claimed_at.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        local = claimed_at.astimezone(ZoneInfo("Asia/Shanghai"))
        config = self.get_config()
        eligible_date = local.date()
        if local.strftime("%H:%M") < str(config["schedule_time"]):
            eligible_date -= timedelta(days=1)
        eligible_through = eligible_date.strftime("%Y%m%d")
        lease = claimed_at + timedelta(seconds=LEASE_SECONDS)
        with self._transaction() as connection:
            row = fetch_one(
                connection,
                """SELECT * FROM market_session_sync_jobs
                   WHERE status = 'queued'
                     AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
                     AND trade_date <= :eligible_through
                   ORDER BY trade_date, created_at
                   FOR UPDATE SKIP LOCKED LIMIT 1""",
                {"now": claimed_at.isoformat(), "eligible_through": eligible_through},
            )
            if row is None:
                return None
            execute(
                connection,
                """UPDATE market_session_sync_jobs SET status = 'running',
                   attempts = attempts + 1, started_at = COALESCE(started_at, :now),
                   lease_until = :lease, error_code = NULL, error_message = NULL,
                   updated_at = :now WHERE job_id = :job_id""",
                {"job_id": row["job_id"], "now": claimed_at.isoformat(), "lease": lease.isoformat()},
            )
        self.heartbeat(worker_id, last_job_id=str(row["job_id"]))
        return self.get_job(row["job_id"])

    def execute_job(
        self,
        job: dict[str, object],
        *,
        provider: TushareProvider,
        market_store: MarketDataStore,
        readiness_store: MarketReadinessStore | None = None,
    ) -> dict[str, object]:
        trade_date = str(job["trade_date"])
        try:
            result = provider.fetch_daily(DailyRequest(trade_date=trade_date))
            rows = DataSyncStore._normalize_bars(
                None, result, start_date=trade_date, end_date=trade_date,
            )
            if not rows:
                raise ProviderProtocolError("provider returned no rows for an open trading session")
            daily_symbols = {str(row["symbol"]) for row in rows}
            limits = provider.fetch_price_limits(
                trade_date, symbols=daily_symbols,
            ) if readiness_store is not None else None
            suspensions = provider.fetch_suspensions(trade_date) if readiness_store is not None else None
            factors = provider.fetch_adjustment_factors(trade_date) if readiness_store is not None else None
            actions = provider.fetch_corporate_actions(trade_date) if readiness_store is not None else None
            daily_basic = provider.fetch_daily_basic(trade_date) if readiness_store is not None else None
            benchmark = provider.fetch_index_daily(CORE_BENCHMARK, trade_date, trade_date) if readiness_store is not None else None
            weights = provider.fetch_index_weights(
                CORE_BENCHMARK, f"{trade_date[:6]}01", trade_date,
            ) if readiness_store is not None else None
            dataset_sha = _hash([
                {key: row[key] for key in sorted(row) if key != "provenance"}
                for row in rows
            ])
            report = market_store.import_bars(
                rows, conflict_policy=KEEP_NEW, replace_non_authoritative=True,
            )
            completeness_state = "provider_snapshot_complete"
            if readiness_store is not None:
                assert all(item is not None for item in (
                    limits, suspensions, factors, actions, daily_basic, benchmark, weights,
                ))
                readiness_store.import_session_status(
                    trade_date,
                    daily_symbols=daily_symbols,
                    limits=list(limits.limits),
                    suspensions=list(suspensions.suspensions),
                    provenance={
                        "daily": result.provenance.as_dict(),
                        "price_limits": limits.provenance.as_dict(),
                        "suspensions": suspensions.provenance.as_dict(),
                    },
                )
                readiness_store.import_session_supplements(
                    trade_date,
                    factors=list(factors.factors), actions=list(actions.actions),
                    provenance={
                        "adjustment_factors": factors.provenance.as_dict(),
                        "corporate_actions": actions.provenance.as_dict(),
                    },
                )
                readiness_store.import_daily_basic(
                    trade_date, list(daily_basic.rows), daily_basic.provenance.as_dict(),
                )
                readiness_store.import_index_daily(
                    CORE_BENCHMARK, list(benchmark.bars), benchmark.provenance.as_dict(),
                )
                readiness_store.import_index_weights(
                    CORE_BENCHMARK, trade_date[:6], list(weights.weights), weights.provenance.as_dict(),
                )
                completeness_state = "provider_snapshot_with_declared_inputs_complete"
            now = _now()
            with self._transaction() as connection:
                execute(
                    connection,
                    """INSERT INTO market_session_completeness
                       (trade_date, state, row_count, dataset_sha256,
                        request_fingerprint, verified_at, job_id)
                       VALUES (:trade_date, :state, :row_count,
                               :dataset_sha, :fingerprint, :now, :job_id)
                       ON CONFLICT (trade_date) DO UPDATE SET
                         state = excluded.state, row_count = excluded.row_count,
                         dataset_sha256 = excluded.dataset_sha256,
                         request_fingerprint = excluded.request_fingerprint,
                         verified_at = excluded.verified_at, job_id = excluded.job_id""",
                    {
                        "trade_date": trade_date,
                        "state": completeness_state,
                        "row_count": len(rows),
                        "dataset_sha": dataset_sha,
                        "fingerprint": result.provenance.request_fingerprint,
                        "now": now,
                        "job_id": job["job_id"],
                    },
                )
                execute(
                    connection,
                    """UPDATE market_session_sync_jobs SET status = 'completed',
                       rows_received = :received, rows_inserted = :inserted,
                       rows_kept = :kept, dataset_sha256 = :dataset_sha,
                       lease_until = NULL, next_attempt_at = NULL,
                       completed_at = :now, updated_at = :now
                       WHERE job_id = :job_id""",
                    {
                        "job_id": job["job_id"],
                        "received": len(rows),
                        "inserted": int(report["inserted"]),
                        "kept": int(report["kept"]),
                        "dataset_sha": dataset_sha,
                        "now": now,
                    },
                )
            return self.get_job(job["job_id"])
        except (ProviderError, ValueError, SQLAlchemyError) as error:
            return self.fail_job(job["job_id"], error)

    def fail_job(self, job_id: object, error: Exception) -> dict[str, object]:
        code, message = _safe_provider_error(error)
        with self._transaction() as connection:
            row = fetch_one(
                connection,
                "SELECT * FROM market_session_sync_jobs WHERE job_id = :job_id FOR UPDATE",
                {"job_id": str(job_id)},
            )
            if row is None:
                raise MarketAutomationNotFound("market session sync job not found")
            attempts = int(row["attempts"])
            terminal = attempts >= int(row["max_attempts"])
            now = datetime.now(timezone.utc)
            next_attempt = None if terminal else now + timedelta(minutes=5 * (3 ** max(0, attempts - 1)))
            execute(
                connection,
                """UPDATE market_session_sync_jobs SET status = :status,
                   next_attempt_at = :next_attempt, lease_until = NULL,
                   error_code = :code, error_message = :message,
                   completed_at = :completed_at, updated_at = :now
                   WHERE job_id = :job_id""",
                {
                    "job_id": str(job_id),
                    "status": "failed" if terminal else "queued",
                    "next_attempt": None if next_attempt is None else next_attempt.isoformat(),
                    "code": code,
                    "message": message,
                    "completed_at": now.isoformat() if terminal else None,
                    "now": now.isoformat(),
                },
            )
        return self.get_job(job_id)

    def recover_stale_jobs(self) -> int:
        rows = self._execute(
            """UPDATE market_session_sync_jobs SET status = 'queued', lease_until = NULL,
               next_attempt_at = now(), error_code = 'stale_lease_recovered',
               error_message = 'worker lease expired; job recovered', updated_at = now()
               WHERE status = 'running' AND lease_until < now()
            RETURNING job_id""",
        )
        repairs = self._execute("""UPDATE market_data_repair_requests
            SET status='queued',claimed_at=NULL,error_message=NULL
            WHERE status='running' RETURNING request_id""")
        return len(rows) + len(repairs)

    def heartbeat(
        self,
        worker_id: str,
        *,
        scheduler_checked: bool = False,
        calendar_refreshed: bool = False,
        last_job_id: str | None = None,
        scheduled_date: str | None = None,
        last_error: str | None = None,
    ) -> None:
        now = _now()
        self._execute(
            """INSERT INTO market_sync_worker_state
               (worker_id, heartbeat_at, last_scheduler_check_at,
                last_calendar_refresh_at, last_job_id, last_scheduled_date,
                last_error, updated_at)
               VALUES (:worker_id, :now, :scheduler_at, :calendar_at,
                       :last_job_id, :scheduled_date, :last_error, :now)
               ON CONFLICT (worker_id) DO UPDATE SET
                 heartbeat_at = excluded.heartbeat_at,
                 last_scheduler_check_at = COALESCE(excluded.last_scheduler_check_at,
                                                    market_sync_worker_state.last_scheduler_check_at),
                 last_calendar_refresh_at = COALESCE(excluded.last_calendar_refresh_at,
                                                     market_sync_worker_state.last_calendar_refresh_at),
                 last_job_id = COALESCE(excluded.last_job_id,
                                        market_sync_worker_state.last_job_id),
                 last_scheduled_date = COALESCE(:scheduled_date,
                                                market_sync_worker_state.last_scheduled_date),
                 last_error = excluded.last_error,
                 updated_at = excluded.updated_at""",
            {
                "worker_id": worker_id,
                "now": now,
                "scheduler_at": now if scheduler_checked else None,
                "calendar_at": now if calendar_refreshed else None,
                "last_job_id": last_job_id,
                "scheduled_date": scheduled_date,
                "last_error": last_error,
            },
        )

    def get_job(self, job_id: object) -> dict[str, object]:
        row = self._fetch_one(
            "SELECT * FROM market_session_sync_jobs WHERE job_id = :job_id",
            {"job_id": str(job_id)},
        )
        if row is None:
            raise MarketAutomationNotFound("market session sync job not found")
        return self._public_job(row)

    def list_jobs(self, *, limit: int = 30) -> list[dict[str, object]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return [self._public_job(row) for row in self._execute(
            """SELECT * FROM market_session_sync_jobs
               ORDER BY trade_date DESC, created_at DESC LIMIT :limit""",
            {"limit": limit},
        )]

    def status(self) -> dict[str, object]:
        config = self.get_config()
        latest_open = self._fetch_one(
            "SELECT MAX(trade_date) AS trade_date FROM market_trading_sessions WHERE is_open = TRUE",
        ) or {}
        latest_complete = self._fetch_one(
            """SELECT trade_date, row_count, dataset_sha256, verified_at
               FROM market_session_completeness
               WHERE state IN ('provider_snapshot_complete', 'provider_snapshot_with_status_complete',
                               'provider_snapshot_with_research_complete',
                               'provider_snapshot_with_declared_inputs_complete')
               ORDER BY trade_date DESC LIMIT 1""",
        )
        worker = self._fetch_one(
            "SELECT * FROM market_sync_worker_state ORDER BY heartbeat_at DESC LIMIT 1",
        )
        healthy = False
        if worker is not None:
            heartbeat = datetime.fromisoformat(str(worker["heartbeat_at"]))
            if heartbeat.tzinfo is None:
                heartbeat = heartbeat.replace(tzinfo=timezone.utc)
            healthy = datetime.now(timezone.utc) - heartbeat.astimezone(timezone.utc) <= timedelta(minutes=2)
        local = _local_now()
        next_run = datetime.combine(
            local.date(),
            datetime.strptime(str(config["schedule_time"]), "%H:%M").time(),
            tzinfo=ZoneInfo(TIMEZONE),
        )
        if next_run <= local:
            next_run += timedelta(days=1)
        return {
            "schema_version": "market-sync-automation.v1",
            "config": config,
            "worker": {
                "healthy": healthy,
                "heartbeat_at": None if worker is None else worker["heartbeat_at"],
                "last_scheduler_check_at": None if worker is None else worker["last_scheduler_check_at"],
                "last_calendar_refresh_at": None if worker is None else worker["last_calendar_refresh_at"],
                "last_job_id": None if worker is None else worker["last_job_id"],
                "last_scheduled_date": None if worker is None else worker["last_scheduled_date"],
                "last_error": None if worker is None else worker["last_error"],
            },
            "latest_calendar_open_date": latest_open.get("trade_date"),
            "latest_complete_session": latest_complete,
            "next_run_at": next_run.isoformat(),
            "jobs": self.list_jobs(limit=30),
            "run_requests": [self._public_run_request(row) for row in self._execute(
                """SELECT * FROM market_sync_run_requests
                   ORDER BY created_at DESC LIMIT 10""",
            )],
            "index_catalog_sync_runs": self._execute(
                """SELECT run_id,requested_as_of,status,result_json,requested_by,created_at,completed_at
                   FROM market_index_catalog_sync_runs ORDER BY created_at DESC LIMIT 10""",
            ),
        }

    def market_session_context(self, *, now: datetime | None = None) -> dict[str, object]:
        """Project today's verified SSE session and latest durable data cutoff.

        This is deliberately narrower than the administrator automation status:
        Agent research receives no worker, job, configuration, error, or content-
        hash details and this read never calls a Provider.
        """

        local = _local_now(now)
        current_date = local.strftime("%Y%m%d")
        current_session = self._fetch_one(
            """SELECT trade_date, is_open, previous_open_date, retrieved_at
               FROM market_trading_sessions WHERE trade_date = :trade_date""",
            {"trade_date": current_date},
        )
        latest_calendar = self._fetch_one(
            """SELECT trade_date FROM market_trading_sessions
               WHERE trade_date <= :trade_date ORDER BY trade_date DESC LIMIT 1""",
            {"trade_date": current_date},
        )
        latest_complete = self._fetch_one(
            """SELECT trade_date, row_count, verified_at
               FROM market_session_completeness
               WHERE trade_date <= :trade_date
                 AND state IN ('provider_snapshot_complete',
                               'provider_snapshot_with_status_complete',
                               'provider_snapshot_with_research_complete',
                               'provider_snapshot_with_declared_inputs_complete')
               ORDER BY trade_date DESC LIMIT 1""",
            {"trade_date": current_date},
        )
        session_state = (
            "unknown" if current_session is None
            else "open" if bool(current_session["is_open"])
            else "closed"
        )
        return {
            "schema_version": "market-session-context.v1",
            "exchange": "SSE",
            "timezone": TIMEZONE,
            "evaluated_at": local.isoformat(),
            "current_date": current_date,
            "current_session": {
                "state": session_state,
                "calendar_verified": current_session is not None,
                "previous_open_date": (
                    None if current_session is None else current_session["previous_open_date"]
                ),
                "calendar_retrieved_at": (
                    None
                    if current_session is None
                    else _iso_timestamp(current_session["retrieved_at"])
                ),
            },
            "calendar_through_date": (
                None if latest_calendar is None else latest_calendar["trade_date"]
            ),
            "latest_complete_session": (
                None
                if latest_complete is None
                else {
                    "trade_date": latest_complete["trade_date"],
                    "row_count": int(latest_complete["row_count"]),
                    "verified_at": _iso_timestamp(latest_complete["verified_at"]),
                }
            ),
            "source": "persisted_byq",
            "live_provider_called": False,
        }

    @staticmethod
    def _public_config(row: dict[str, object]) -> dict[str, object]:
        return {
            "enabled": bool(row["enabled"]),
            "schedule_time": row["schedule_time"],
            "timezone": TIMEZONE,
            "catchup_days": int(row["catchup_days"]),
            "security_master_enabled": bool(row["security_master_enabled"]),
            "datasets": ["trade_calendar", "stock_daily", "trading_status", "price_limits",
                         "adjustment_factors", "corporate_actions", "daily_basic",
                         "index_daily", "index_weights", "declared_financial_indicators"],
            "version": int(row["version"]),
            "updated_by": row["updated_by"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _public_job(row: dict[str, object]) -> dict[str, object]:
        return {
            key: row.get(key)
            for key in (
                "job_id", "trade_date", "status", "attempts", "max_attempts",
                "rows_received", "rows_inserted", "rows_kept", "dataset_sha256",
                "error_code", "error_message", "scheduled_by", "created_at",
                "started_at", "next_attempt_at", "completed_at", "updated_at",
            )
        }

    @staticmethod
    def _public_run_request(row: dict[str, object]) -> dict[str, object]:
        return {
            key: row.get(key)
            for key in (
                "request_id", "status", "requested_by", "created_at", "claimed_at",
                "completed_at", "result_json", "error_message",
            )
        }


def sync_session_supplements(
    trade_dates: list[str], *, provider: TushareProvider,
    readiness_store: MarketReadinessStore,
) -> dict[str, int]:
    """Repair factor/action evidence without redownloading validated daily bars."""
    dates = sorted({str(value) for value in trade_dates if str(value)})
    if len(dates) > 250:
        raise ValueError("session supplement repair exceeds 250 trading sessions")
    counts = {"sessions": 0, "factors": 0, "corporate_actions": 0}
    for trade_date in dates:
        factors = provider.fetch_adjustment_factors(trade_date)
        actions = provider.fetch_corporate_actions(trade_date)
        result = readiness_store.import_session_supplements(
            trade_date,
            factors=list(factors.factors),
            actions=list(actions.actions),
            provenance={
                "adjustment_factors": factors.provenance.as_dict(),
                "corporate_actions": actions.provenance.as_dict(),
            },
        )
        counts["sessions"] += 1
        counts["factors"] += int(result["factor_count"])
        counts["corporate_actions"] += int(result["corporate_action_count"])
    return counts


def sync_declared_inputs(
    requirement: dict[str, object], *, provider: TushareProvider,
    readiness_store: MarketReadinessStore,
) -> dict[str, int]:
    """Fill only the bounded optional inputs frozen by a strategy version."""
    declared = requirement.get("declared", {})
    if not isinstance(declared, dict):
        raise ValueError("declared data requirement is invalid")
    counts = {"benchmark": 0, "index_weights": 0, "daily_basic": 0, "financial": 0}
    benchmark_symbol = declared.get("benchmark")
    if benchmark_symbol:
        cursor = datetime.strptime(str(requirement["start_date"]), "%Y%m%d")
        end = datetime.strptime(str(requirement["end_date"]), "%Y%m%d")
        while cursor <= end:
            chunk_end = min(end, cursor + timedelta(days=400))
            result = provider.fetch_index_daily(
                str(benchmark_symbol), cursor.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d"),
            )
            counts["benchmark"] += readiness_store.import_index_daily(
                str(benchmark_symbol), list(result.bars), result.provenance.as_dict(),
            )
            cursor = chunk_end + timedelta(days=1)
    index_universe = declared.get("index_universe")
    if index_universe:
        for period in list(requirement.get("index_weight_periods", [])):
            year, month = int(str(period)[:4]), int(str(period)[4:6])
            start = f"{period}01"
            end = f"{period}{monthrange(year, month)[1]:02d}"
            result = provider.fetch_index_weights(str(index_universe), start, end)
            counts["index_weights"] += readiness_store.import_index_weights(
                str(index_universe), str(period), list(result.weights), result.provenance.as_dict(),
            )
    if declared.get("daily_basic"):
        sessions = readiness_store._execute(
            """SELECT trade_date FROM market_trading_sessions
               WHERE is_open=TRUE AND trade_date BETWEEN :start AND :end ORDER BY trade_date""",
            {"start": requirement["start_date"], "end": requirement["end_date"]},
        )
        for row in sessions:
            trade_date = str(row["trade_date"])
            if readiness_store._fetch_one(
                "SELECT trade_date FROM market_daily_basic_completeness WHERE trade_date=:date",
                {"date": trade_date},
            ) is not None:
                continue
            result = provider.fetch_daily_basic(trade_date)
            counts["daily_basic"] += readiness_store.import_daily_basic(
                trade_date, list(result.rows), result.provenance.as_dict(),
            )
    if declared.get("fundamentals"):
        report_start = str(requirement["financial_report_start_date"])
        report_end = str(requirement["financial_report_end_date"])
        for symbol in list(requirement["symbols"]):
            if readiness_store._fetch_one(
                """SELECT symbol FROM market_financial_indicator_completeness
                   WHERE symbol=:symbol AND report_start_date=:start AND report_end_date=:end""",
                {"symbol": symbol, "start": report_start, "end": report_end},
            ) is not None:
                continue
            result = provider.fetch_financial_indicators(str(symbol), report_start, report_end)
            counts["financial"] += readiness_store.import_financial_indicators(
                str(symbol), report_start, report_end, list(result.rows), result.provenance.as_dict(),
            )
    return counts


def sync_supported_index_catalog(
    as_of_date: str, *, provider: TushareProvider, readiness_store: MarketReadinessStore,
) -> dict[str, object]:
    """Refresh the closed canonical index set without widening Provider access."""
    end = datetime.strptime(str(as_of_date), "%Y%m%d")
    start = end - timedelta(days=INDEX_WEIGHT_LOOKBACK_DAYS)
    items: list[dict[str, object]] = []
    for definition in SUPPORTED_INDEXES:
        symbol = definition["index_symbol"]
        try:
            result = provider.fetch_index_weights(symbol, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
            by_period: dict[str, list[object]] = {}
            for weight in result.weights:
                by_period.setdefault(str(weight.trade_date)[:6], []).append(weight)
            imported = 0
            for period, weights in sorted(by_period.items()):
                imported += readiness_store.import_index_weights(
                    symbol, period, weights, result.provenance.as_dict(),
                )
            latest = readiness_store._fetch_one(
                """SELECT snapshot_date,member_count,content_sha256,verified_at
                   FROM market_index_weight_snapshots
                   WHERE index_symbol=:symbol AND status='verified' AND snapshot_date<=:date
                   ORDER BY snapshot_date DESC LIMIT 1""",
                {"symbol": symbol, "date": as_of_date},
            )
            items.append({
                "index_symbol": symbol,
                "name": definition["name"],
                "status": "ready" if latest is not None else "waiting_for_data",
                "rows_imported": imported,
                "latest_snapshot_date": None if latest is None else latest["snapshot_date"],
                "member_count": 0 if latest is None else int(latest["member_count"]),
            })
        except Exception as error:
            existing = readiness_store._fetch_one(
                """SELECT snapshot_date,member_count FROM market_index_weight_snapshots
                   WHERE index_symbol=:symbol AND status='verified' AND snapshot_date<=:date
                   ORDER BY snapshot_date DESC LIMIT 1""",
                {"symbol": symbol, "date": as_of_date},
            )
            items.append({
                "index_symbol": symbol,
                "name": definition["name"],
                "status": "stale" if existing is not None else "failed",
                "rows_imported": 0,
                "latest_snapshot_date": None if existing is None else existing["snapshot_date"],
                "member_count": 0 if existing is None else int(existing["member_count"]),
                "error_code": type(error).__name__,
            })
    ready = sum(item["status"] == "ready" for item in items)
    return {
        "schema_version": "index-catalogue-sync.v1",
        "requested_as_of": as_of_date,
        "status": "completed" if ready == len(items) else "partial" if ready else "failed",
        "ready_count": ready,
        "total": len(items),
        "items": items,
    }


def run_scheduler_cycle(
    store: MarketAutomationStore,
    *,
    provider_factory: Callable[[], TushareProvider],
    worker_id: str,
    now: datetime | None = None,
    force: bool = False,
    readiness_store: MarketReadinessStore | None = None,
) -> list[dict[str, object]]:
    local = _local_now(now)
    config = store.get_config()
    if not force and (not config["enabled"] or local.strftime("%H:%M") < config["schedule_time"]):
        store.heartbeat(worker_id, scheduler_checked=True)
        return []
    worker = store._fetch_one(
        "SELECT last_scheduled_date FROM market_sync_worker_state WHERE worker_id = :worker_id",
        {"worker_id": worker_id},
    )
    local_date = local.strftime("%Y%m%d")
    if not force and worker is not None and worker.get("last_scheduled_date") == local_date:
        store.heartbeat(worker_id, scheduler_checked=True)
        return []
    first = (local.date() - timedelta(days=int(config["catchup_days"]) - 1)).strftime("%Y%m%d")
    last = local.strftime("%Y%m%d")
    provider = provider_factory()
    store.refresh_calendar(provider, start_date=first, end_date=last)
    if readiness_store is not None:
        started = _now()
        index_result = sync_supported_index_catalog(
            local_date, provider=provider, readiness_store=readiness_store,
        )
        store._execute(
            """INSERT INTO market_index_catalog_sync_runs
               (run_id,requested_as_of,status,result_json,requested_by,created_at,completed_at)
               VALUES (:run,:date,:status,:result,:by,:created,:completed)""",
            {
                "run": f"index_catalog_sync_{uuid.uuid4().hex}",
                "date": local_date,
                "status": index_result["status"],
                "result": index_result,
                "by": "run-now" if force else "scheduler",
                "created": started,
                "completed": _now(),
            },
        )
    created = store.enqueue_due_sessions(now=local, force=force)
    store.heartbeat(
        worker_id,
        scheduler_checked=True,
        calendar_refreshed=True,
        scheduled_date=local_date,
    )
    return created
