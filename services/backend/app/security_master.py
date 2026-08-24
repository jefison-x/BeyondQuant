"""Platform-scoped A-share security master and atomic Tushare sync jobs.

The store owns normalized current catalogue rows and immutable snapshots. It
never connects to Community storage and never exposes raw Tushare envelopes or
credentials outside Backend.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .data_provider import (
    ProviderAuthorizationError,
    ProviderCredentialsMissing,
    ProviderError,
    ProviderProtocolError,
    ProviderRateLimited,
    ProviderUnavailable,
    SecurityMasterRequest,
    SecurityMasterResult,
    TushareProvider,
)
from .db import PgStoreMixin, execute, fetch_one


class SecurityMasterError(RuntimeError):
    pass


class SecurityMasterNotFound(SecurityMasterError):
    pass


class SecurityMasterConflict(SecurityMasterError):
    pass


class SecurityMasterPersistenceError(SecurityMasterError):
    pass


_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SYMBOL = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
_STATUSES = ("L", "P", "D")
_EXCHANGES = ("SSE", "SZSE", "BSE")


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _provider_error(error: Exception) -> tuple[str, str]:
    if isinstance(error, ProviderCredentialsMissing):
        return "credentials_missing", "Tushare credentials are not configured"
    if isinstance(error, ProviderAuthorizationError):
        return "authorization_failed", "Tushare rejected the configured credentials"
    if isinstance(error, ProviderRateLimited):
        return "rate_limited", "Tushare request was rate limited"
    if isinstance(error, ProviderProtocolError):
        return "provider_protocol_error", "Tushare returned invalid security-master data"
    if isinstance(error, ProviderUnavailable):
        return "provider_unavailable", "Tushare is unavailable"
    return "security_master_sync_failed", "security-master synchronization failed"


class SecurityMasterStore(PgStoreMixin):
    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS security_master_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            dataset_id TEXT NOT NULL UNIQUE,
            request_fingerprint TEXT NOT NULL,
            statuses_json JSONB NOT NULL,
            row_count BIGINT NOT NULL,
            retrieved_at TIMESTAMPTZ NOT NULL,
            requested_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS security_master_snapshots_latest_idx
            ON security_master_snapshots(retrieved_at DESC, created_at DESC, snapshot_id DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS market_securities (
            symbol TEXT PRIMARY KEY,
            local_symbol TEXT NOT NULL,
            name TEXT NOT NULL,
            area TEXT,
            industry TEXT,
            market TEXT,
            exchange TEXT NOT NULL,
            list_status TEXT NOT NULL,
            list_date TEXT NOT NULL,
            delist_date TEXT,
            is_hs TEXT,
            asset_type TEXT NOT NULL,
            data_source TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            first_seen_snapshot_id TEXT NOT NULL REFERENCES security_master_snapshots(snapshot_id),
            latest_seen_snapshot_id TEXT NOT NULL REFERENCES security_master_snapshots(snapshot_id),
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS market_securities_catalog_idx
            ON market_securities(list_status, exchange, symbol)
        """,
        """
        CREATE INDEX IF NOT EXISTS market_securities_name_idx
            ON market_securities(name, symbol)
        """,
        """
        CREATE TABLE IF NOT EXISTS security_master_snapshot_members (
            snapshot_id TEXT NOT NULL REFERENCES security_master_snapshots(snapshot_id),
            symbol TEXT NOT NULL,
            local_symbol TEXT NOT NULL,
            name TEXT NOT NULL,
            area TEXT,
            industry TEXT,
            market TEXT,
            exchange TEXT NOT NULL,
            list_status TEXT NOT NULL,
            list_date TEXT NOT NULL,
            delist_date TEXT,
            is_hs TEXT,
            asset_type TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            PRIMARY KEY (snapshot_id, symbol)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS security_master_members_catalog_idx
            ON security_master_snapshot_members(snapshot_id, list_status, exchange, symbol)
        """,
        """
        CREATE TABLE IF NOT EXISTS security_master_sync_jobs (
            job_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            statuses_json JSONB NOT NULL,
            status TEXT NOT NULL,
            progress INTEGER NOT NULL,
            records_received BIGINT NOT NULL DEFAULT 0,
            records_imported BIGINT NOT NULL DEFAULT 0,
            snapshot_id TEXT REFERENCES security_master_snapshots(snapshot_id),
            dataset_id TEXT,
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
        CREATE INDEX IF NOT EXISTS security_master_sync_jobs_created_idx
            ON security_master_sync_jobs(created_at DESC, job_id DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS security_master_sync_audit (
            audit_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES security_master_sync_jobs(job_id),
            actor_principal TEXT NOT NULL,
            action TEXT NOT NULL,
            outcome TEXT NOT NULL,
            detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as error:
            raise SecurityMasterPersistenceError("security master storage is unavailable") from error

    def create_sync_job(self, payload: object, *, actor: object) -> tuple[dict[str, object], bool]:
        if not isinstance(payload, dict):
            raise ValueError("security-master sync request must be an object")
        if set(payload) - {"idempotency_key"}:
            raise ValueError("security-master sync request has unknown fields")
        actor_text = str(actor).strip()
        if not actor_text or len(actor_text) > 128:
            raise ValueError("actor principal is invalid")
        key = payload.get("idempotency_key")
        if not isinstance(key, str) or not _IDEMPOTENCY.fullmatch(key):
            raise ValueError("idempotency_key is invalid")
        request = {"provider": "tushare", "endpoint": "stock_basic", "statuses": list(_STATUSES)}
        request_sha256 = _canonical_hash(request)
        job_id = f"securitysync_{uuid.uuid4().hex}"
        try:
            with self._transaction() as connection:
                existing = fetch_one(
                    connection,
                    "SELECT * FROM security_master_sync_jobs WHERE idempotency_key = :key",
                    {"key": key},
                )
                if existing is not None:
                    if existing["request_sha256"] != request_sha256:
                        raise SecurityMasterConflict("security-master idempotency key was reused")
                    return self._public_job(existing), False
                execute(connection, """INSERT INTO security_master_sync_jobs
                    (job_id, provider, statuses_json, status, progress, requested_by,
                     idempotency_key, request_sha256, created_at, updated_at)
                    VALUES (:job_id, 'tushare', :statuses, 'queued', 0, :actor,
                            :key, :request_sha256, now(), now())""", {
                    "job_id": job_id,
                    "statuses": list(_STATUSES),
                    "actor": actor_text,
                    "key": key,
                    "request_sha256": request_sha256,
                })
                self._audit(connection, job_id, actor_text, "created", "queued", {"statuses": list(_STATUSES)})
        except IntegrityError as error:
            raise SecurityMasterConflict("security-master sync conflicts with existing state") from error
        return self.get_sync_job(job_id), True

    def run_sync_job(
        self,
        job_id: object,
        *,
        provider_factory: Callable[[], TushareProvider],
    ) -> dict[str, object]:
        job_id = str(job_id)
        with self._transaction() as connection:
            row = fetch_one(
                connection,
                "SELECT * FROM security_master_sync_jobs WHERE job_id = :job_id FOR UPDATE",
                {"job_id": job_id},
            )
            if row is None:
                raise SecurityMasterNotFound("security-master sync job not found")
            if row["status"] in {"completed", "failed"}:
                return self._public_job(row)
            if row["status"] != "queued":
                raise SecurityMasterConflict("security-master sync job is already running")
            execute(connection, """UPDATE security_master_sync_jobs
                SET status = 'running', progress = 10, started_at = now(), updated_at = now()
                WHERE job_id = :job_id""", {"job_id": job_id})
        try:
            result = provider_factory().fetch_security_master(SecurityMasterRequest())
            snapshot, created = self.import_result(result, actor=str(row["requested_by"]))
        except (ProviderError, ValueError, SQLAlchemyError) as error:
            code, message = _provider_error(error)
            return self._finish_job(job_id, status="failed", error_code=code, error_message=message)
        return self._finish_job(
            job_id,
            status="completed",
            result=result,
            snapshot=snapshot,
            records_imported=len(result.records) if created else 0,
        )

    def import_result(self, result: SecurityMasterResult, *, actor: str) -> tuple[dict[str, object], bool]:
        if tuple(result.statuses) != _STATUSES:
            raise ValueError("a complete security-master snapshot requires L, P, and D")
        canonical_records = [record.as_dict() for record in result.records]
        if not canonical_records:
            raise ValueError("security-master snapshot must not be empty")
        dataset_id = _canonical_hash(canonical_records)
        if dataset_id != result.dataset_id:
            raise ValueError("security-master dataset fingerprint does not match records")
        snapshot_id = f"securitysnapshot_{dataset_id[:32]}"
        with self._transaction() as connection:
            existing = fetch_one(
                connection,
                "SELECT * FROM security_master_snapshots WHERE dataset_id = :dataset_id",
                {"dataset_id": dataset_id},
            )
            if existing is not None:
                return self._public_snapshot(existing), False
            execute(connection, """INSERT INTO security_master_snapshots
                (snapshot_id, provider, endpoint, dataset_id, request_fingerprint,
                 statuses_json, row_count, retrieved_at, requested_by)
                VALUES (:snapshot_id, 'tushare', 'stock_basic', :dataset_id,
                        :request_fingerprint, :statuses, :row_count, :retrieved_at, :actor)""", {
                "snapshot_id": snapshot_id,
                "dataset_id": dataset_id,
                "request_fingerprint": result.provenance.request_fingerprint,
                "statuses": list(result.statuses),
                "row_count": len(canonical_records),
                "retrieved_at": result.provenance.retrieved_at,
                "actor": actor,
            })
            for record in canonical_records:
                content_sha256 = _canonical_hash(record)
                params = {
                    **record,
                    "snapshot_id": snapshot_id,
                    "content_sha256": content_sha256,
                    "data_source": "tushare",
                }
                execute(connection, """INSERT INTO security_master_snapshot_members
                    (snapshot_id, symbol, local_symbol, name, area, industry, market,
                     exchange, list_status, list_date, delist_date, is_hs, asset_type,
                     content_sha256)
                    VALUES (:snapshot_id, :symbol, :local_symbol, :name, :area, :industry,
                            :market, :exchange, :list_status, :list_date, :delist_date,
                            :is_hs, :asset_type, :content_sha256)""", params)
                execute(connection, """INSERT INTO market_securities
                    (symbol, local_symbol, name, area, industry, market, exchange,
                     list_status, list_date, delist_date, is_hs, asset_type,
                     data_source, content_sha256, first_seen_snapshot_id,
                     latest_seen_snapshot_id, updated_at)
                    VALUES (:symbol, :local_symbol, :name, :area, :industry, :market,
                            :exchange, :list_status, :list_date, :delist_date, :is_hs,
                            :asset_type, :data_source, :content_sha256, :snapshot_id,
                            :snapshot_id, now())
                    ON CONFLICT (symbol) DO UPDATE SET
                        local_symbol = EXCLUDED.local_symbol, name = EXCLUDED.name,
                        area = EXCLUDED.area, industry = EXCLUDED.industry,
                        market = EXCLUDED.market, exchange = EXCLUDED.exchange,
                        list_status = EXCLUDED.list_status, list_date = EXCLUDED.list_date,
                        delist_date = EXCLUDED.delist_date, is_hs = EXCLUDED.is_hs,
                        asset_type = EXCLUDED.asset_type, data_source = EXCLUDED.data_source,
                        content_sha256 = EXCLUDED.content_sha256,
                        latest_seen_snapshot_id = EXCLUDED.latest_seen_snapshot_id,
                        updated_at = now()""", params)
            execute(
                connection,
                "DELETE FROM market_securities WHERE latest_seen_snapshot_id <> :snapshot_id",
                {"snapshot_id": snapshot_id},
            )
        return self.get_snapshot(snapshot_id), True

    def get_sync_job(self, job_id: object) -> dict[str, object]:
        row = self._fetch_one(
            "SELECT * FROM security_master_sync_jobs WHERE job_id = :job_id",
            {"job_id": str(job_id)},
        )
        if row is None:
            raise SecurityMasterNotFound("security-master sync job not found")
        return self._public_job(row)

    def list_sync_jobs(self, *, limit: int = 20) -> list[dict[str, object]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        return [self._public_job(row) for row in self._execute(
            """SELECT * FROM security_master_sync_jobs
               ORDER BY created_at DESC, job_id DESC LIMIT :limit""",
            {"limit": limit},
        )]

    def get_snapshot(self, snapshot_id: object) -> dict[str, object]:
        row = self._fetch_one(
            "SELECT * FROM security_master_snapshots WHERE snapshot_id = :snapshot_id",
            {"snapshot_id": str(snapshot_id)},
        )
        if row is None:
            raise SecurityMasterNotFound("security-master snapshot not found")
        return self._public_snapshot(row)

    def latest_snapshot(self) -> dict[str, object] | None:
        row = self._fetch_one("""SELECT * FROM security_master_snapshots
            ORDER BY retrieved_at DESC, created_at DESC, snapshot_id DESC LIMIT 1""")
        return None if row is None else self._public_snapshot(row)

    def catalogue_status(self) -> dict[str, object]:
        snapshot = self.latest_snapshot()
        if snapshot is None:
            return {
                "schema_version": "security-master.v1",
                "quality": "empty",
                "latest_snapshot": None,
                "total": 0,
                "status_counts": {status: 0 for status in _STATUSES},
                "exchange_counts": {exchange: 0 for exchange in _EXCHANGES},
            }
        rows = self._execute("""SELECT list_status, exchange, COUNT(*)::bigint AS count
            FROM security_master_snapshot_members WHERE snapshot_id = :snapshot_id
            GROUP BY list_status, exchange ORDER BY list_status, exchange""", {
            "snapshot_id": snapshot["snapshot_id"],
        })
        status_counts = {status: 0 for status in _STATUSES}
        exchange_counts = {exchange: 0 for exchange in _EXCHANGES}
        for row in rows:
            status_counts[str(row["list_status"])] += int(row["count"])
            exchange_counts[str(row["exchange"])] += int(row["count"])
        return {
            "schema_version": "security-master.v1",
            "quality": "ready",
            "latest_snapshot": snapshot,
            "total": int(snapshot["row_count"]),
            "status_counts": status_counts,
            "exchange_counts": exchange_counts,
        }

    def list_securities(
        self,
        *,
        query: str = "",
        statuses: tuple[str, ...] = (),
        exchanges: tuple[str, ...] = (),
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be non-negative")
        query = str(query).strip()
        if len(query) > 80:
            raise ValueError("query must not exceed 80 characters")
        normalized_statuses = tuple(dict.fromkeys(status.upper() for status in statuses if status))
        normalized_exchanges = tuple(dict.fromkeys(exchange.upper() for exchange in exchanges if exchange))
        if any(status not in _STATUSES for status in normalized_statuses):
            raise ValueError("statuses must contain only L, P, or D")
        if any(exchange not in _EXCHANGES for exchange in normalized_exchanges):
            raise ValueError("exchanges must contain only SSE, SZSE, or BSE")
        snapshot = self.latest_snapshot()
        if snapshot is None:
            return {"securities": [], "total": 0, "limit": limit, "offset": offset, "snapshot": None}
        clauses = ["snapshot_id = :snapshot_id"]
        params: dict[str, Any] = {"snapshot_id": snapshot["snapshot_id"], "limit": limit, "offset": offset}
        if query:
            clauses.append("(symbol ILIKE :query OR local_symbol ILIKE :query OR name ILIKE :query)")
            params["query"] = f"%{query}%"
        if normalized_statuses:
            clauses.append("list_status IN (SELECT jsonb_array_elements_text(:statuses))")
            params["statuses"] = list(normalized_statuses)
        if normalized_exchanges:
            clauses.append("exchange IN (SELECT jsonb_array_elements_text(:exchanges))")
            params["exchanges"] = list(normalized_exchanges)
        where = " AND ".join(clauses)
        rows = self._execute(f"""SELECT symbol, local_symbol, name, area, industry,
            market, exchange, list_status, list_date, delist_date, is_hs, asset_type
            FROM security_master_snapshot_members WHERE {where}
            ORDER BY symbol LIMIT :limit OFFSET :offset""", params)
        total = self._fetch_one(
            f"SELECT COUNT(*)::bigint AS total FROM security_master_snapshot_members WHERE {where}",
            {key: value for key, value in params.items() if key not in {"limit", "offset"}},
        )
        return {
            "securities": rows,
            "total": int(total["total"] if total else 0),
            "limit": limit,
            "offset": offset,
            "snapshot": snapshot,
        }

    def resolve_symbols(
        self,
        *,
        statuses: tuple[str, ...] = ("L",),
        exchanges: tuple[str, ...] = (),
        query: str = "",
        limit: int = 6_000,
    ) -> tuple[list[str], dict[str, object]]:
        if not 1 <= limit <= 6_000:
            raise ValueError("security-master selection limit must be between 1 and 6000")
        page = self.list_securities(
            query=query, statuses=statuses, exchanges=exchanges, limit=min(limit, 200), offset=0,
        )
        # The public list is capped at 200, while server-side orchestration may
        # resolve the complete frozen selection through the same validated filters.
        snapshot = page["snapshot"]
        if snapshot is None:
            raise SecurityMasterNotFound("security master has not been synchronized")
        normalized_statuses = tuple(dict.fromkeys(status.upper() for status in statuses if status))
        normalized_exchanges = tuple(dict.fromkeys(exchange.upper() for exchange in exchanges if exchange))
        clauses = ["snapshot_id = :snapshot_id"]
        params: dict[str, Any] = {"snapshot_id": snapshot["snapshot_id"], "limit": limit + 1}
        if query:
            clauses.append("(symbol ILIKE :query OR local_symbol ILIKE :query OR name ILIKE :query)")
            params["query"] = f"%{str(query).strip()}%"
        if normalized_statuses:
            clauses.append("list_status IN (SELECT jsonb_array_elements_text(:statuses))")
            params["statuses"] = list(normalized_statuses)
        if normalized_exchanges:
            clauses.append("exchange IN (SELECT jsonb_array_elements_text(:exchanges))")
            params["exchanges"] = list(normalized_exchanges)
        rows = self._execute(f"""SELECT symbol FROM security_master_snapshot_members
            WHERE {' AND '.join(clauses)} ORDER BY symbol LIMIT :limit""", params)
        if len(rows) > limit:
            raise ValueError(f"security-master selection exceeds {limit} symbols")
        symbols = [str(row["symbol"]) for row in rows]
        if not symbols:
            raise ValueError("security-master selection is empty")
        return symbols, {
            "type": "security_master",
            "snapshot_id": snapshot["snapshot_id"],
            "dataset_id": snapshot["dataset_id"],
            "statuses": list(normalized_statuses),
            "exchanges": list(normalized_exchanges),
            "query": str(query).strip() or None,
        }

    def resolve_selected_symbols(
        self,
        symbols: object,
        *,
        snapshot_id: object | None = None,
    ) -> tuple[list[str], dict[str, object]]:
        if not isinstance(symbols, list) or not symbols or len(symbols) > 500:
            raise ValueError("selected securities must contain 1 to 500 symbols")
        normalized = sorted({str(symbol).strip().upper() for symbol in symbols})
        if len(normalized) != len(symbols) or any(not _SYMBOL.fullmatch(symbol) for symbol in normalized):
            raise ValueError("selected securities must be unique canonical symbols")
        latest = self.latest_snapshot()
        if latest is None:
            raise SecurityMasterNotFound("security master has not been synchronized")
        if snapshot_id is not None and str(snapshot_id) != latest["snapshot_id"]:
            raise SecurityMasterConflict("selected securities use a stale security-master snapshot")
        rows = self._execute("""SELECT symbol FROM security_master_snapshot_members
            WHERE snapshot_id = :snapshot_id
              AND symbol IN (SELECT jsonb_array_elements_text(:symbols))
            ORDER BY symbol""", {"snapshot_id": latest["snapshot_id"], "symbols": normalized})
        resolved = [str(row["symbol"]) for row in rows]
        if resolved != normalized:
            raise ValueError("selected securities contain symbols outside the latest catalogue")
        return resolved, {
            "type": "selected",
            "snapshot_id": latest["snapshot_id"],
            "dataset_id": latest["dataset_id"],
        }

    def _finish_job(
        self,
        job_id: str,
        *,
        status: str,
        result: SecurityMasterResult | None = None,
        snapshot: dict[str, object] | None = None,
        records_imported: int = 0,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, object]:
        with self._transaction() as connection:
            row = fetch_one(connection, "SELECT * FROM security_master_sync_jobs WHERE job_id = :job_id", {"job_id": job_id})
            if row is None:
                raise SecurityMasterNotFound("security-master sync job not found")
            execute(connection, """UPDATE security_master_sync_jobs SET
                status = :status, progress = 100, records_received = :received,
                records_imported = :imported, snapshot_id = :snapshot_id,
                dataset_id = :dataset_id, error_code = :error_code,
                error_message = :error_message, completed_at = now(), updated_at = now()
                WHERE job_id = :job_id""", {
                "job_id": job_id,
                "status": status,
                "received": len(result.records) if result else 0,
                "imported": records_imported,
                "snapshot_id": snapshot.get("snapshot_id") if snapshot else None,
                "dataset_id": result.dataset_id if result else None,
                "error_code": error_code,
                "error_message": error_message,
            })
            self._audit(connection, job_id, str(row["requested_by"]), "finished", status, {
                "records_received": len(result.records) if result else 0,
                "records_imported": records_imported,
                "snapshot_id": snapshot.get("snapshot_id") if snapshot else None,
            })
        return self.get_sync_job(job_id)

    @staticmethod
    def _audit(connection, job_id: str, actor: str, action: str, outcome: str, detail: dict[str, object]) -> None:
        execute(connection, """INSERT INTO security_master_sync_audit
            (audit_id, job_id, actor_principal, action, outcome, detail_json, created_at)
            VALUES (:audit_id, :job_id, :actor, :action, :outcome, :detail, now())""", {
            "audit_id": f"securityaudit_{uuid.uuid4().hex}",
            "job_id": job_id,
            "actor": actor,
            "action": action,
            "outcome": outcome,
            "detail": detail,
        })

    @staticmethod
    def _public_snapshot(row: dict[str, object]) -> dict[str, object]:
        return {
            "snapshot_id": row["snapshot_id"],
            "provider": row["provider"],
            "endpoint": row["endpoint"],
            "dataset_id": row["dataset_id"],
            "request_fingerprint": row["request_fingerprint"],
            "statuses": row["statuses_json"],
            "row_count": row["row_count"],
            "retrieved_at": row["retrieved_at"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _public_job(row: dict[str, object]) -> dict[str, object]:
        return {
            "job_id": row["job_id"],
            "provider": row["provider"],
            "statuses": row["statuses_json"],
            "status": row["status"],
            "progress": row["progress"],
            "records_received": row["records_received"],
            "records_imported": row["records_imported"],
            "snapshot_id": row["snapshot_id"],
            "dataset_id": row["dataset_id"],
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "requested_by": row["requested_by"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "updated_at": row["updated_at"],
        }
