"""Owner-scoped facade over existing market repair and readiness jobs (ADR-0045)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .db import PgStoreMixin, execute, fetch_one


class DataDemandError(RuntimeError):
    pass


class DataDemandNotFound(DataDemandError):
    pass


class DataDemandConflict(DataDemandError):
    pass


class DataDemandPersistenceError(DataDemandError):
    pass


_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PURPOSES = {"research", "backtest", "machine_learning"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


class DataDemandStore(PgStoreMixin):
    SCHEMA_DDL = [
        """
        CREATE TABLE IF NOT EXISTS data_demands (
            demand_id TEXT PRIMARY KEY,
            owner_principal TEXT NOT NULL,
            workspace_id TEXT,
            actor_principal TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            purpose TEXT NOT NULL,
            stock_pool_snapshot_id TEXT NOT NULL,
            scope_json JSONB NOT NULL,
            requirements_json JSONB NOT NULL,
            repair_request_ids_json JSONB NOT NULL,
            status TEXT NOT NULL,
            progress_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            idempotency_key TEXT NOT NULL,
            request_sha256 TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS data_demands_workspace_idempotency
            ON data_demands(workspace_id,idempotency_key)
        """,
        """
        CREATE INDEX IF NOT EXISTS data_demands_session_status
            ON data_demands(owner_principal,session_id,status,created_at DESC)
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as error:
            raise DataDemandPersistenceError("data demand storage is unavailable") from error

    @classmethod
    def from_env(cls) -> "DataDemandStore":
        return cls()

    def create(
        self, payload: object, *, context: dict[str, str], scope: dict[str, object],
        requirements: list[dict[str, object]], repair_request_ids: list[str],
    ) -> tuple[dict[str, object], bool]:
        if not isinstance(payload, dict):
            raise ValueError("data demand request must be an object")
        allowed = {"purpose", "stock_pool_snapshot_id", "start_date", "end_date", "data_requirements", "idempotency_key"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"data demand request has unknown fields: {', '.join(unknown)}")
        purpose = str(payload.get("purpose", "")).strip()
        if purpose not in _PURPOSES:
            raise ValueError("data demand purpose is invalid")
        key = payload.get("idempotency_key")
        if not isinstance(key, str) or _IDEMPOTENCY.fullmatch(key) is None:
            raise ValueError("idempotency_key is invalid")
        if not requirements or len(requirements) > 16 or len(requirements) != len(repair_request_ids):
            raise ValueError("data demand partition plan is invalid")
        request_sha256 = self._request_sha256(payload, scope=scope, requirements=requirements)
        demand_id = f"datademand_{uuid.uuid4().hex}"
        now = _now()
        try:
            with self._transaction() as connection:
                existing = fetch_one(connection, """SELECT * FROM data_demands
                    WHERE workspace_id=:workspace AND idempotency_key=:key""",
                    {"workspace": context["workspace_id"], "key": key})
                if existing is not None:
                    if existing["request_sha256"] != request_sha256:
                        raise DataDemandConflict("data demand idempotency key was reused")
                    return self._public(existing), False
                execute(connection, """INSERT INTO data_demands
                    (demand_id,owner_principal,workspace_id,actor_principal,trace_id,session_id,
                     purpose,stock_pool_snapshot_id,scope_json,requirements_json,
                     repair_request_ids_json,status,progress_json,idempotency_key,request_sha256,
                     created_at,updated_at)
                    VALUES (:id,:owner,:workspace,:actor,:trace,:session,:purpose,:snapshot,
                            :scope,:requirements,:repairs,'queued',:progress,:key,:sha,:now,:now)""", {
                    "id": demand_id, "owner": context["owner_principal"],
                    "workspace": context["workspace_id"], "actor": context["actor_principal"],
                    "trace": context["trace_id"], "session": context["session_id"],
                    "purpose": purpose, "snapshot": str(payload.get("stock_pool_snapshot_id")),
                    "scope": scope, "requirements": requirements, "repairs": repair_request_ids,
                    "progress": {"partition_count": len(requirements), "ready_partitions": 0},
                    "key": key, "sha": request_sha256, "now": now,
                })
        except IntegrityError as error:
            raise DataDemandConflict("data demand conflicts with existing state") from error
        return self.get(demand_id, trusted_owner=context["owner_principal"]), True

    def find_idempotent(
        self, payload: object, *, context: dict[str, str], scope: dict[str, object],
        requirements: list[dict[str, object]],
    ) -> dict[str, object] | None:
        """Resolve an existing request before repair jobs gain any side effects."""
        if not isinstance(payload, dict):
            raise ValueError("data demand request must be an object")
        allowed = {"purpose", "stock_pool_snapshot_id", "start_date", "end_date", "data_requirements", "idempotency_key"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"data demand request has unknown fields: {', '.join(unknown)}")
        if str(payload.get("purpose", "")).strip() not in _PURPOSES:
            raise ValueError("data demand purpose is invalid")
        key = payload.get("idempotency_key")
        if not isinstance(key, str) or _IDEMPOTENCY.fullmatch(key) is None:
            raise ValueError("idempotency_key is invalid")
        if not requirements or len(requirements) > 16:
            raise ValueError("data demand partition plan is invalid")
        row = self._fetch_one(
            "SELECT * FROM data_demands WHERE workspace_id=:workspace AND idempotency_key=:key",
            {"workspace": context["workspace_id"], "key": key},
        )
        if row is None:
            return None
        if row["owner_principal"] != context["owner_principal"] or row["request_sha256"] != self._request_sha256(
            payload, scope=scope, requirements=requirements,
        ):
            raise DataDemandConflict("data demand idempotency key was reused")
        return self._public(row)

    @staticmethod
    def _request_sha256(
        payload: dict[str, object], *, scope: dict[str, object], requirements: list[dict[str, object]],
    ) -> str:
        return _hash({
            "purpose": str(payload.get("purpose", "")).strip(),
            "stock_pool_snapshot_id": str(payload.get("stock_pool_snapshot_id")),
            "start_date": str(payload.get("start_date")),
            "end_date": str(payload.get("end_date")),
            "data_requirements": payload.get("data_requirements") or {},
            "scope": scope,
            "requirements": requirements,
        })

    def get(self, demand_id: object, *, trusted_owner: str) -> dict[str, object]:
        row = self._fetch_one("SELECT * FROM data_demands WHERE demand_id=:id", {"id": str(demand_id)})
        if row is None or row["owner_principal"] != trusted_owner:
            raise DataDemandNotFound("data demand not found")
        return self._public(row)

    def refresh(self, demand_id: object, *, trusted_owner: str, readiness_store: Any, automation_store: Any) -> dict[str, object]:
        row = self._fetch_one("SELECT * FROM data_demands WHERE demand_id=:id", {"id": str(demand_id)})
        if row is None or row["owner_principal"] != trusted_owner:
            raise DataDemandNotFound("data demand not found")
        requirements = list(row["requirements_json"])
        assessments = [readiness_store.assess(dict(item)) for item in requirements]
        repairs = automation_store.get_data_repairs(list(row["repair_request_ids_json"]))
        missing_dates = sorted({
            str(date) for assessment in assessments
            for date in list(assessment.get("missing_trade_dates", []))
        })
        session_jobs = automation_store.session_job_counts(missing_dates)
        ready_count = sum(item.get("state") == "ready" for item in assessments)
        any_ready_cells = any(int(item.get("required_cell_count") or 0) > int(item.get("missing_count") or 0) for item in assessments)
        repair_failed = any(item.get("status") == "failed" for item in repairs)
        active = any(item.get("status") in {"queued", "running"} for item in repairs) or session_jobs["queued"] + session_jobs["running"] > 0
        if ready_count == len(assessments):
            status = "ready"
        elif repair_failed or (repairs and all(item.get("status") == "completed" for item in repairs) and not active and session_jobs["failed"]):
            status = "partial" if any_ready_cells else "failed"
        elif repairs and all(item.get("status") == "queued" for item in repairs) and not any(session_jobs.values()):
            status = "queued"
        else:
            status = "syncing"
        progress = {
            "partition_count": len(assessments), "ready_partitions": ready_count,
            "missing_items": sum(int(item.get("missing_count") or 0) for item in assessments),
            "session_jobs": session_jobs,
        }
        terminal = status in {"ready", "partial", "failed"}
        self._execute("""UPDATE data_demands SET status=:status,progress_json=:progress,
            completed_at=CASE WHEN :terminal THEN COALESCE(completed_at,now()) ELSE NULL END,
            updated_at=now() WHERE demand_id=:id""",
            {"status": status, "progress": progress, "terminal": terminal, "id": str(demand_id)})
        updated = self._fetch_one("SELECT * FROM data_demands WHERE demand_id=:id", {"id": str(demand_id)})
        assert updated is not None
        return self._public(updated)

    def list_for_session(self, *, trusted_owner: str, session_id: str, limit: int = 8) -> list[dict[str, object]]:
        rows = self._execute("""SELECT * FROM data_demands
            WHERE owner_principal=:owner AND session_id=:session
            ORDER BY created_at DESC,demand_id DESC LIMIT :limit""",
            {"owner": trusted_owner, "session": session_id, "limit": limit})
        return [self._public(row) for row in rows]

    def list_recent(self, *, limit: int = 50) -> list[dict[str, object]]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return [self._public(row) for row in self._execute(
            "SELECT * FROM data_demands ORDER BY created_at DESC,demand_id DESC LIMIT :limit",
            {"limit": limit},
        )]

    @staticmethod
    def _public(row: dict[str, object]) -> dict[str, object]:
        scope = dict(row.get("scope_json") or {})
        progress = dict(row.get("progress_json") or {})
        return {
            "schema_version": "data-demand.v1", "demand_id": row["demand_id"],
            "purpose": row["purpose"], "status": row["status"], "scope": scope,
            "progress": progress, "requested_by": row["actor_principal"],
            "session_id": row["session_id"], "trace_id": row["trace_id"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "completed_at": row.get("completed_at"),
            "notification": (
                "数据已准备妥当，可以继续研究" if row["status"] == "ready"
                else "数据仅部分准备完成，请检查缺失项" if row["status"] == "partial"
                else "数据准备失败，请检查数据中心" if row["status"] == "failed"
                else "数据中心正在按需准备数据"
            ),
        }
