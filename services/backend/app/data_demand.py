"""Owner-scoped facade over existing market repair and readiness jobs (ADR-0045)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .db import PgStoreMixin, execute, fetch_one
from .task_progress import progress_percent


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


def _allowed_fields(payload):
    if payload.get("scope_kind") == "index_snapshot":
        return {"purpose", "scope_kind", "index_symbol", "requested_as_of", "idempotency_key"}
    return {"purpose", "stock_pool_snapshot_id", "start_date", "end_date", "data_requirements", "idempotency_key"}


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
            stock_pool_snapshot_id TEXT,
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

    SCHEMA_DDL.append("ALTER TABLE data_demands ALTER COLUMN stock_pool_snapshot_id DROP NOT NULL")

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
        requirements: list[dict[str, object]], repair_request_ids: list[str], _connection=None,
    ) -> tuple[dict[str, object], bool]:
        if not isinstance(payload, dict):
            raise ValueError("data demand request must be an object")
        allowed = _allowed_fields(payload)
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
            with (self._transaction() if _connection is None else nullcontext(_connection)) as connection:
                existing = fetch_one(connection, """SELECT * FROM data_demands
                    WHERE workspace_id=:workspace AND idempotency_key=:key""",
                    {"workspace": context["workspace_id"], "key": key})
                if existing is not None:
                    if existing["owner_principal"] != context["owner_principal"] or existing["request_sha256"] != request_sha256:
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
                    "purpose": purpose, "snapshot": None if payload.get("scope_kind") == "index_snapshot" else str(payload.get("stock_pool_snapshot_id")),
                    "scope": scope, "requirements": requirements, "repairs": repair_request_ids,
                    "progress": {"partition_count": len(requirements), "ready_partitions": 0,
                                 "completed_units": 0, "total_units": 0, "percent": 0,
                                 "unit": "index_snapshots" if scope.get("kind") == "index_snapshot" else "symbol_session_cells", "stage": "queued"},
                    "key": key, "sha": request_sha256, "now": now,
                })
                inserted = fetch_one(connection, "SELECT * FROM data_demands WHERE demand_id=:id", {"id": demand_id})
        except IntegrityError as error:
            raise DataDemandConflict("data demand conflicts with existing state") from error
        return self._public(inserted), True

    def submit(self, payload, *, context, planner, automation_store):
        """Freeze demand and repair references atomically before workers can claim."""
        if not isinstance(payload, dict):
            raise ValueError("data demand request must be an object")
        key = payload.get("idempotency_key")
        if not isinstance(key, str) or _IDEMPOTENCY.fullmatch(key) is None:
            raise ValueError("idempotency_key is invalid")
        with self._transaction() as connection:
            execute(connection, "SET LOCAL lock_timeout = '2s'")
            execute(connection, "SELECT pg_advisory_xact_lock(hashtext(:scope))",
                    {"scope": f"data-demand|{context['workspace_id']}|{key}"})
            previous = fetch_one(connection,
                "SELECT * FROM data_demands WHERE workspace_id=:workspace AND idempotency_key=:key",
                {"workspace": context["workspace_id"], "key": key})
            if previous is not None:
                # Reuse the frozen original plan even when market state changed.
                scope, requirements = previous["scope_json"], previous["requirements_json"]
            else:
                scope, requirements = planner(payload, context)
            # Validate the closed request before adding any repair side effect.
            existing = self.find_idempotent(payload, context=context, scope=scope, requirements=requirements)
            if existing is not None:
                return existing, False
            repairs = [automation_store.request_data_repair(requirement=item,
                requested_by=f"agent-data-demand:{context['owner_principal']}",
                _connection=connection) for item in requirements]
            return self.create(payload, context=context, scope=scope, requirements=requirements,
                repair_request_ids=[str(item["request_id"]) for item in repairs], _connection=connection)

    def reconcile_submission(self, key, *, trusted_owner, trusted_workspace):
        if not isinstance(key, str) or _IDEMPOTENCY.fullmatch(key) is None:
            raise ValueError("idempotency_key is invalid")
        row = self._fetch_one("""SELECT * FROM data_demands WHERE workspace_id=:workspace
            AND owner_principal=:owner AND idempotency_key=:key""",
            {"workspace": trusted_workspace, "owner": trusted_owner, "key": key})
        return {"state": "confirmed", "demand": self._public(row)} if row else {"state": "not_found"}

    def find_idempotent(
        self, payload: object, *, context: dict[str, str], scope: dict[str, object],
        requirements: list[dict[str, object]],
    ) -> dict[str, object] | None:
        """Resolve an existing request before repair jobs gain any side effects."""
        if not isinstance(payload, dict):
            raise ValueError("data demand request must be an object")
        allowed = _allowed_fields(payload)
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
        if payload.get("scope_kind") == "index_snapshot":
            return _hash({"request": payload | {"idempotency_key": None}, "scope": scope, "requirements": requirements})
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
        active = (
            any(item.get("status") in {"queued", "running", "waiting_for_sessions"} for item in repairs)
            or session_jobs["queued"] + session_jobs["running"] > 0
        )
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
        total_units = sum(int(item.get("required_cell_count") or 0) for item in assessments)
        completed_units = max(0, total_units - int(progress["missing_items"]))
        progress.update({
            "completed_units": completed_units, "total_units": total_units,
            "percent": progress_percent(completed_units, total_units),
            "unit": "index_snapshots" if row["scope_json"].get("kind") == "index_snapshot" else "symbol_session_cells",
            "stage": "verified" if status == "ready" else "failed" if status in {"failed", "partial"}
                     else "synchronizing" if active else "queued",
        })
        if row["scope_json"].get("kind") == "index_snapshot":
            progress["missing_periods"] = sorted({period for item in assessments for period in item.get("missing_periods", [])})
            progress["verified_snapshot_date"] = (assessments[0].get("snapshot") or {}).get("snapshot_date")
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

    def refresh_recent(self, *, readiness_store: Any, automation_store: Any, limit: int = 50) -> list[dict[str, object]]:
        rows = self._execute(
            "SELECT * FROM data_demands ORDER BY created_at DESC,demand_id DESC LIMIT :limit",
            {"limit": limit},
        )
        return [
            self.refresh(
                row["demand_id"], trusted_owner=str(row["owner_principal"]),
                readiness_store=readiness_store, automation_store=automation_store,
            ) if row["status"] in {"queued", "syncing"} else self._public(row)
            for row in rows
        ]

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
                "该时点指数成分已验证，可创建固定历史快照；不表示历史调仓序列或行情已就绪" if row["status"] == "ready" and scope.get("kind") == "index_snapshot"
                else "数据已准备妥当，可以继续研究" if row["status"] == "ready"
                else "数据仅部分准备完成，请检查缺失项" if row["status"] == "partial"
                else "数据准备失败，请检查数据中心" if row["status"] == "failed"
                else "数据中心正在按需准备数据"
            ),
        }
