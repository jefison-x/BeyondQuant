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

from .business_job import project_business_job
from .db import PgStoreMixin, execute, fetch_one
from .research import InvalidTransition, ResearchNotFound
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
_TASK_ID = re.compile(r"^task_[0-9a-f]{32}$")
_PURPOSES = {"research", "backtest", "machine_learning"}


def _allowed_fields(payload):
    if payload.get("scope_kind") == "index_snapshot":
        return {"purpose", "scope_kind", "index_symbol", "requested_as_of", "idempotency_key", "task_id"}
    return {"purpose", "stock_pool_snapshot_id", "start_date", "end_date", "data_requirements", "idempotency_key", "task_id"}


def _task_id(payload: dict[str, object]) -> str | None:
    value = payload.get("task_id")
    if value is None:
        return None
    if not isinstance(value, str) or _TASK_ID.fullmatch(value) is None:
        raise ValueError("task_id is invalid")
    return value


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
            task_id TEXT,
            result_artifact_id TEXT,
            error_code TEXT,
            error_message TEXT,
            started_at TIMESTAMPTZ,
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

    SCHEMA_DDL.extend([
        "ALTER TABLE data_demands ALTER COLUMN stock_pool_snapshot_id DROP NOT NULL",
        "ALTER TABLE data_demands ADD COLUMN IF NOT EXISTS task_id TEXT",
        "ALTER TABLE data_demands ADD COLUMN IF NOT EXISTS result_artifact_id TEXT",
        "ALTER TABLE data_demands ADD COLUMN IF NOT EXISTS error_code TEXT",
        "ALTER TABLE data_demands ADD COLUMN IF NOT EXISTS error_message TEXT",
        "ALTER TABLE data_demands ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ",
        "CREATE INDEX IF NOT EXISTS data_demands_task_status ON data_demands(task_id,status,created_at) WHERE task_id IS NOT NULL",
    ])

    @staticmethod
    def _assert_task_binding(connection, payload: dict[str, object], context: dict[str, str]) -> str | None:
        task_id = _task_id(payload)
        if task_id is None:
            return None
        task = fetch_one(connection, """SELECT owner_principal,workspace_id FROM research_tasks
            WHERE task_id=:task FOR SHARE""", {"task": task_id})
        if (task is None or task["owner_principal"] != context["owner_principal"]
                or task["workspace_id"] != context["workspace_id"]):
            raise DataDemandNotFound("research task not found")
        return task_id

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
        task_id = _task_id(payload)
        request_sha256 = self._request_sha256(payload, scope=scope, requirements=requirements)
        demand_id = f"datademand_{uuid.uuid4().hex}"
        now = _now()
        try:
            with (self._transaction() if _connection is None else nullcontext(_connection)) as connection:
                if task_id is not None and _connection is None:
                    task = fetch_one(connection, """SELECT owner_principal,workspace_id FROM research_tasks
                        WHERE task_id=:task FOR SHARE""", {"task": task_id})
                    if (task is None or task["owner_principal"] != context["owner_principal"]
                            or task["workspace_id"] != context["workspace_id"]):
                        raise DataDemandNotFound("research task not found")
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
                     repair_request_ids_json,task_id,result_artifact_id,error_code,error_message,started_at,
                     status,progress_json,idempotency_key,request_sha256,
                     created_at,updated_at)
                    VALUES (:id,:owner,:workspace,:actor,:trace,:session,:purpose,:snapshot,
                            :scope,:requirements,:repairs,:task,NULL,NULL,NULL,NULL,
                            'queued',:progress,:key,:sha,:now,:now)""", {
                    "id": demand_id, "owner": context["owner_principal"],
                    "workspace": context["workspace_id"], "actor": context["actor_principal"],
                    "trace": context["trace_id"], "session": context["session_id"],
                    "purpose": purpose, "snapshot": None if payload.get("scope_kind") == "index_snapshot" else str(payload.get("stock_pool_snapshot_id")),
                    "scope": scope, "requirements": requirements, "repairs": repair_request_ids,
                    "task": task_id,
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
        task_id = _task_id(payload)
        with self._transaction() as connection:
            execute(connection, "SET LOCAL lock_timeout = '2s'")
            execute(connection, "SELECT pg_advisory_xact_lock(hashtext(:scope))",
                    {"scope": f"data-demand|{context['workspace_id']}|{key}"})
            if task_id is not None:
                self._assert_task_binding(connection, payload, context)
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
        _task_id(payload)
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
        request = {
            "purpose": str(payload.get("purpose", "")).strip(),
            "stock_pool_snapshot_id": str(payload.get("stock_pool_snapshot_id")),
            "start_date": str(payload.get("start_date")),
            "end_date": str(payload.get("end_date")),
            "data_requirements": payload.get("data_requirements") or {},
            "scope": scope,
            "requirements": requirements,
        }
        if payload.get("task_id") is not None:
            request["task_id"] = _task_id(payload)
        return _hash(request)

    def get(
        self, demand_id: object, *, trusted_owner: str, trusted_workspace: str | None = None,
    ) -> dict[str, object]:
        row = self._fetch_one("SELECT * FROM data_demands WHERE demand_id=:id", {"id": str(demand_id)})
        if (row is None or row["owner_principal"] != trusted_owner
                or row.get("task_id") is not None and row.get("workspace_id") != trusted_workspace):
            raise DataDemandNotFound("data demand not found")
        return self._public(row)

    def cancel(self, demand_id: object, *, trusted_owner: str, trusted_workspace: str) -> dict[str, object]:
        """Cancel only this task-bound Job; shared market repairs continue independently."""
        with self._transaction() as connection:
            execute(connection, "SET LOCAL lock_timeout = '2s'")
            row = fetch_one(connection, "SELECT * FROM data_demands WHERE demand_id=:id FOR UPDATE",
                {"id": str(demand_id)})
            if (row is None or row.get("task_id") is None
                    or row["owner_principal"] != trusted_owner
                    or row["workspace_id"] != trusted_workspace):
                raise DataDemandNotFound("data import job not found")
            if row["status"] in {"ready", "partial", "failed", "cancelled"}:
                return self._public(row)
            progress = {**dict(row.get("progress_json") or {}), "stage": "cancelled"}
            execute(connection, """UPDATE data_demands SET status='cancelled',progress_json=:progress,
                completed_at=now(),updated_at=now() WHERE demand_id=:id""",
                {"id": str(demand_id), "progress": progress})
            updated = fetch_one(connection, "SELECT * FROM data_demands WHERE demand_id=:id",
                {"id": str(demand_id)})
            assert updated is not None
            return self._public(updated)

    def refresh(
        self, demand_id: object, *, trusted_owner: str, readiness_store: Any,
        automation_store: Any, trusted_workspace: str | None = None,
    ) -> dict[str, object]:
        row = self._fetch_one("SELECT * FROM data_demands WHERE demand_id=:id", {"id": str(demand_id)})
        if (row is None or row["owner_principal"] != trusted_owner
                or row.get("task_id") is not None and row.get("workspace_id") != trusted_workspace):
            raise DataDemandNotFound("data demand not found")
        # Task-bound DataImportJobs are advanced by the trusted Data Worker.
        # Agent reads only observe this persisted projection.
        if row.get("task_id") is not None:
            return self._public(row)
        status, progress, _ = self._evaluate(row, readiness_store=readiness_store,
            automation_store=automation_store)
        terminal = status in {"ready", "partial", "failed"}
        self._execute("""UPDATE data_demands SET status=:status,progress_json=:progress,
            completed_at=CASE WHEN :terminal THEN COALESCE(completed_at,now()) ELSE NULL END,
            updated_at=now() WHERE demand_id=:id""",
            {"status": status, "progress": progress, "terminal": terminal, "id": str(demand_id)})
        updated = self._fetch_one("SELECT * FROM data_demands WHERE demand_id=:id", {"id": str(demand_id)})
        assert updated is not None
        return self._public(updated)

    @staticmethod
    def _evaluate(row, *, readiness_store: Any, automation_store: Any):
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
        return status, progress, assessments

    def list_pending_task_bound(self, *, limit: int = 1) -> list[str]:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        rows = self._execute("""SELECT demand_id FROM data_demands
            WHERE task_id IS NOT NULL AND status NOT IN ('ready','partial','failed','cancelled')
            ORDER BY updated_at,created_at,demand_id LIMIT :limit""", {"limit": limit})
        return [str(row["demand_id"]) for row in rows]

    def process_task_bound(
        self, demand_id: object, *, readiness_store: Any, automation_store: Any,
        research_store: Any,
    ) -> dict[str, object] | None:
        """Persist one worker-derived DataImport state; commit its Artifact atomically."""
        try:
            with self._transaction() as connection:
                execute(connection, "SET LOCAL lock_timeout = '2s'")
                current = fetch_one(connection,
                    "SELECT * FROM data_demands WHERE demand_id=:id FOR UPDATE SKIP LOCKED",
                    {"id": str(demand_id)})
                if current is None or current.get("task_id") is None:
                    return None
                if current["status"] in {"ready", "partial", "failed", "cancelled"}:
                    return self._public(current)
                status, progress, assessments = self._evaluate(
                    current, readiness_store=readiness_store, automation_store=automation_store,
                )
                artifact_id = None
                error_code = None
                error_message = None
                artifact_payload = None
                if status == "ready":
                    artifact_payload = self._readiness_artifact_payload(current, assessments)
                elif status == "partial":
                    error_code = "data_preparation_partial"
                    error_message = "data requirements remain partially ready after bounded repair attempts"
                elif status == "failed":
                    error_code = "data_preparation_failed"
                    error_message = "data requirements could not be verified after bounded repair attempts"
                if status == "ready":
                    assert artifact_payload is not None
                    try:
                        artifact = research_store.create_artifact(
                            artifact_payload,
                            trusted_owner=str(current["owner_principal"]),
                            trusted_workspace=str(current["workspace_id"]),
                            _connection=connection,
                        )
                    except (ResearchNotFound, InvalidTransition):
                        # A task or frozen pool that no longer accepts a new
                        # reference cannot become ready on later polling.
                        # Keep transient Artifact write errors retryable.
                        status = "failed"
                        progress = {**progress, "stage": "failed"}
                        error_code = "data_source_unavailable"
                        error_message = "data import source reference is unavailable"
                    else:
                        validated = research_store.transition(
                            "artifact", artifact["artifact_id"], "validated",
                            f"data-import-validate-{current['demand_id']}",
                            _connection=connection,
                        )
                        artifact_id = str(validated["artifact_id"])
                terminal = status in {"ready", "partial", "failed"}
                execute(connection, """UPDATE data_demands SET status=:status,progress_json=:progress,
                    result_artifact_id=:artifact,error_code=:error_code,error_message=:error_message,
                    started_at=CASE WHEN :started THEN COALESCE(started_at,now()) ELSE started_at END,
                    completed_at=CASE WHEN :terminal THEN COALESCE(completed_at,now()) ELSE NULL END,
                    updated_at=now() WHERE demand_id=:id""", {
                    "status": status, "progress": progress, "artifact": artifact_id,
                    "error_code": error_code, "error_message": error_message,
                    "started": status != "queued", "terminal": terminal, "id": str(demand_id),
                })
                updated = fetch_one(connection, "SELECT * FROM data_demands WHERE demand_id=:id", {"id": str(demand_id)})
                assert updated is not None
                return self._public(updated)
        except IntegrityError as error:
            raise DataDemandConflict("data import Artifact conflicts with existing state") from error

    @staticmethod
    def _readiness_artifact_payload(row, assessments: list[dict[str, object]]) -> dict[str, object]:
        scope = dict(row["scope_json"] or {})
        requirements = list(row["requirements_json"] or [])
        coverage = []
        for requirement, assessment in zip(requirements, assessments, strict=True):
            symbols = requirement.get("symbols")
            coverage.append({
                "partition": requirement.get("partition"),
                "requirement_sha256": requirement.get("requirement_sha256"),
                "start_date": requirement.get("start_date"),
                "end_date": requirement.get("end_date"),
                "datasets": requirement.get("datasets", []),
                "symbol_count": len(symbols) if isinstance(symbols, list) else None,
                "membership_fingerprint": requirement.get("membership_fingerprint"),
                "security_master_snapshot_id": requirement.get("security_master_snapshot_id"),
                "state": assessment.get("state"),
                "ready_identity": assessment.get("ready_identity"),
                "required_cell_count": assessment.get("required_cell_count"),
                "missing_count": assessment.get("missing_count"),
                "verified_snapshot": assessment.get("snapshot"),
            })
        return {
            "task_id": row["task_id"], "kind": "data_readiness",
            "content": {
                "schema_version": "data-readiness.v1",
                "job_id": row["demand_id"],
                "demand_id": row["demand_id"],
                "request_sha256": row["request_sha256"],
                "scope": scope,
                "coverage": coverage,
                "verified_at": _now(),
                "provenance": {
                    "store": "BYQ Data Plane",
                    "source": "persisted market-data readiness assessment",
                },
            },
            "lineage": (
                [{"kind": "stock_pool_snapshot", "id": str(row["stock_pool_snapshot_id"])}]
                if row.get("stock_pool_snapshot_id") is not None else []
            ), "trace_id": row["trace_id"],
            "idempotency_key": f"data-import-readiness-{row['demand_id']}",
        }

    def list_for_session(
        self, *, trusted_owner: str, session_id: str, trusted_workspace: str | None = None,
        limit: int = 8,
    ) -> list[dict[str, object]]:
        workspace_clause = " AND workspace_id=:workspace" if trusted_workspace is not None else ""
        parameters: dict[str, object] = {"owner": trusted_owner, "session": session_id, "limit": limit}
        if trusted_workspace is not None:
            parameters["workspace"] = trusted_workspace
        rows = self._execute(f"""SELECT * FROM data_demands
            WHERE owner_principal=:owner AND session_id=:session{workspace_clause}
            ORDER BY created_at DESC,demand_id DESC LIMIT :limit""",
            parameters)
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
            ) if row.get("task_id") is None and row["status"] in {"queued", "syncing"} else self._public(row)
            for row in rows
        ]

    @staticmethod
    def _public(row: dict[str, object]) -> dict[str, object]:
        scope = dict(row.get("scope_json") or {})
        progress = dict(row.get("progress_json") or {})
        public = {
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
                else "数据准备请求已取消" if row["status"] == "cancelled"
                else "数据中心正在按需准备数据"
            ),
        }
        if row.get("task_id") is not None:
            public.update({
                "task_id": row["task_id"],
                "result_artifact_id": row.get("result_artifact_id"),
                "job": project_business_job("DATA_IMPORT", row),
            })
        return public
