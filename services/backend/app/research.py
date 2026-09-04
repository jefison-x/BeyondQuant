from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, ensure_column, execute, fetch_one
from .web_research import normalize_web_research_evidence, validate_web_research_evidence


MAX_JSON_BYTES = 64 * 1024
MAX_ARTIFACT_JSON_BYTES = 32 * 1024 * 1024
MAX_SOURCES = 64
MAX_LINEAGE = 64
_ID_PATTERN = re.compile(r"^(?:task|experiment|artifact)_[0-9a-f]{32}$")
_TRACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

TASK_TRANSITIONS = {
    "planned": {"planned", "running", "cancelled"},
    "running": {"running", "completed", "failed", "cancelled"},
    "completed": {"completed"},
    "failed": {"failed"},
    "cancelled": {"cancelled"},
}
EXPERIMENT_TRANSITIONS = TASK_TRANSITIONS
ARTIFACT_TRANSITIONS = {
    "draft": {"draft", "validated", "superseded"},
    "validated": {"validated", "superseded"},
    "superseded": {"superseded"},
}

_SECRET_KEY_FRAGMENTS = (
    "token",
    "password",
    "secret",
    "apikey",
    "accesskey",
    "privatekey",
    "credential",
    "authorization",
)


class ResearchError(RuntimeError):
    """Safe base class for BYQ research-domain failures."""


class ResearchNotFound(ResearchError):
    pass


class IdempotencyConflict(ResearchError):
    pass


class InvalidTransition(ResearchError):
    pass


class ResearchPersistenceError(ResearchError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object, *, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _identifier(value: object, *, field: str) -> str:
    normalized = _text(value, field=field, max_length=64)
    if _ID_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field} is not a valid BYQ entity identifier")
    return normalized


def _trace_id(value: object) -> str:
    normalized = _text(value, field="trace_id", max_length=64)
    if _TRACE_PATTERN.fullmatch(normalized) is None:
        raise ValueError("trace_id is not a valid BYQ identifier")
    return normalized


def _idempotency_key(value: object) -> str:
    return _text(value, field="idempotency_key", max_length=128)


def _reject_unknown(payload: dict[str, object], allowed: set[str]) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(unknown)}")


def _reject_secret_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            if any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS):
                raise ValueError("research payload must not contain credential fields")
            _reject_secret_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_secret_keys(nested)


def _canonical_json(
    value: object, *, field: str, max_bytes: int = MAX_JSON_BYTES
) -> tuple[object, str]:
    _reject_secret_keys(value)
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be JSON-serializable") from error
    if len(encoded) > max_bytes:
        raise ValueError(f"{field} exceeds {max_bytes} bytes")
    return value, encoded.decode("utf-8")


def _object(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    normalized, _ = _canonical_json(value, field=field)
    return normalized  # type: ignore[return-value]


def _snapshot(value: object) -> tuple[dict[str, object], str]:
    snapshot = _object(value, field="input_snapshot")
    sources = snapshot.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("input_snapshot.sources must be a non-empty list")
    if len(sources) > MAX_SOURCES:
        raise ValueError(f"input_snapshot.sources exceeds {MAX_SOURCES} entries")
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("input_snapshot.sources entries must be objects")
        for field in ("provider", "endpoint", "request_fingerprint"):
            _text(source.get(field), field=f"source.{field}", max_length=256)
    _, encoded = _canonical_json(snapshot, field="input_snapshot")
    return snapshot, encoded


def _lineage(value: object) -> tuple[list[dict[str, str]], str]:
    if not isinstance(value, list) or len(value) > MAX_LINEAGE:
        raise ValueError(f"lineage must be a list of at most {MAX_LINEAGE} entries")
    result: list[dict[str, str]] = []
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"kind", "id"}:
            raise ValueError("lineage entries must contain exactly kind and id")
        result.append(
            {
                "kind": _text(entry["kind"], field="lineage.kind", max_length=64),
                "id": _text(entry["id"], field="lineage.id", max_length=128),
            }
        )
    _, encoded = _canonical_json(result, field="lineage")
    return result, encoded


def _hash_request(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _loads(value: str, *, field: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise ResearchPersistenceError(f"stored {field} is invalid") from error


def _result_json(value: dict[str, object]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise ResearchPersistenceError("research result is not JSON-serializable") from error


def _row_dict(row: dict[str, Any]) -> dict[str, object]:
    return dict(row)


class ResearchStore(PgStoreMixin):
    """Backend-owned durable repository for Phase 9 business entities (ADR-0016 PG)."""

    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS research_tasks (
            task_id TEXT PRIMARY KEY,
            owner_principal TEXT NOT NULL,
            title TEXT NOT NULL,
            objective TEXT NOT NULL,
            status TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            version INTEGER NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS research_tasks_idempotency
            ON research_tasks(owner_principal, idempotency_key)
        """,
        """
        CREATE TABLE IF NOT EXISTS experiments (
            experiment_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES research_tasks(task_id),
            owner_principal TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            input_snapshot JSONB NOT NULL,
            trace_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            version INTEGER NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS experiments_idempotency
            ON experiments(task_id, idempotency_key)
        """,
        """
        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES research_tasks(task_id),
            experiment_id TEXT REFERENCES experiments(experiment_id),
            owner_principal TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            content JSONB NOT NULL,
            content_sha256 TEXT NOT NULL,
            lineage JSONB NOT NULL,
            trace_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            version INTEGER NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS artifacts_idempotency
            ON artifacts(task_id, idempotency_key)
        """,
        """
        CREATE INDEX IF NOT EXISTS artifacts_kind ON artifacts(kind)
        """,
        """
        CREATE TABLE IF NOT EXISTS research_transitions (
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            target_status TEXT NOT NULL,
            result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY(entity_type, entity_id, idempotency_key)
        )
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as error:
            raise ResearchPersistenceError("research storage is unavailable") from error

    def bootstrap_schema(self) -> None:
        super().bootstrap_schema()
        # Column back-migration parity with the former SQLite schema.
        with self.engine.begin() as connection:
            ensure_column(connection, "research_transitions", "result_json", "JSONB")

    @classmethod
    def from_env(cls) -> "ResearchStore":
        return cls()

    def create_task(self, payload: object) -> dict[str, object]:
        data = self._task_payload(payload)
        request_hash = _hash_request(data)
        with self._transaction() as connection:
            existing = fetch_one(
                connection,
                "SELECT * FROM research_tasks WHERE owner_principal = :owner_principal AND idempotency_key = :idempotency_key",
                {"owner_principal": data["owner_principal"], "idempotency_key": data["idempotency_key"]},
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict("research task idempotency key was reused")
                return self._task_row(existing)
            now = _now()
            task_id = _new_id("task")
            execute(
                connection,
                """INSERT INTO research_tasks
                (task_id, owner_principal, title, objective, status, trace_id,
                 idempotency_key, request_hash, created_at, updated_at, version)
                VALUES (:task_id, :owner_principal, :title, :objective, 'planned', :trace_id,
                        :idempotency_key, :request_hash, :created_at, :updated_at, 1)""",
                {"task_id": task_id, "owner_principal": data["owner_principal"], "title": data["title"],
                 "objective": data["objective"], "trace_id": data["trace_id"],
                 "idempotency_key": data["idempotency_key"], "request_hash": request_hash,
                 "created_at": now, "updated_at": now},
            )
        return self.get_task(task_id)

    def create_web_evidence_record(self, payload: object) -> dict[str, object]:
        """Atomically create the task and its normalized web-evidence Artifact."""

        if not isinstance(payload, dict):
            raise ValueError("web evidence record request must be an object")
        _reject_unknown(payload, {"owner_principal", "task", "content", "lineage", "trace_id", "idempotency_key"})
        task_input = _object(payload.get("task"), field="task")
        _reject_unknown(task_input, {"title", "objective"})
        owner = _text(payload.get("owner_principal"), field="owner_principal", max_length=128)
        trace_id = _trace_id(payload.get("trace_id"))
        record_key = _idempotency_key(payload.get("idempotency_key"))
        key_digest = hashlib.sha256(record_key.encode("utf-8")).hexdigest()[:32]
        content = normalize_web_research_evidence(payload.get("content"))
        lineage, _ = _lineage(payload.get("lineage", []))
        task_data = self._task_payload(
            {
                "owner_principal": owner,
                "title": task_input.get("title"),
                "objective": task_input.get("objective"),
                "trace_id": trace_id,
                "idempotency_key": f"web-record-task:{key_digest}",
            }
        )
        task_hash = _hash_request(task_data)

        with self._transaction() as connection:
            task_row = fetch_one(
                connection,
                "SELECT * FROM research_tasks WHERE owner_principal = :owner_principal AND idempotency_key = :idempotency_key",
                {"owner_principal": owner, "idempotency_key": task_data["idempotency_key"]},
            )
            if task_row is None:
                now = _now()
                task_id = _new_id("task")
                execute(
                    connection,
                    """INSERT INTO research_tasks
                    (task_id, owner_principal, title, objective, status, trace_id,
                     idempotency_key, request_hash, created_at, updated_at, version)
                    VALUES (:task_id, :owner_principal, :title, :objective, 'planned', :trace_id,
                            :idempotency_key, :request_hash, :created_at, :updated_at, 1)""",
                    {
                        **task_data,
                        "task_id": task_id,
                        "request_hash": task_hash,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                task_row = fetch_one(
                    connection, "SELECT * FROM research_tasks WHERE task_id = :task_id", {"task_id": task_id}
                )
            elif task_row["request_hash"] != task_hash:
                raise IdempotencyConflict("web evidence record idempotency key was reused")
            assert task_row is not None

            artifact_data = self._artifact_payload(
                {
                    "task_id": task_row["task_id"],
                    "kind": "web_research_evidence",
                    "content": content,
                    "lineage": lineage,
                    "trace_id": trace_id,
                    "idempotency_key": f"web-record-artifact:{key_digest}",
                }
            )
            artifact_lineage, _ = _lineage(
                [{"kind": "research_task", "id": str(task_row["task_id"])}] + artifact_data["lineage"]  # type: ignore[operator]
            )
            artifact_data["lineage"] = artifact_lineage
            artifact_hash = _hash_request(artifact_data)
            artifact_row = fetch_one(
                connection,
                "SELECT * FROM artifacts WHERE task_id = :task_id AND idempotency_key = :idempotency_key",
                {"task_id": task_row["task_id"], "idempotency_key": artifact_data["idempotency_key"]},
            )
            if artifact_row is None:
                now = _now()
                artifact_id = _new_id("artifact")
                execute(
                    connection,
                    """INSERT INTO artifacts
                    (artifact_id, task_id, experiment_id, owner_principal, kind,
                     status, content, content_sha256, lineage, trace_id,
                     idempotency_key, request_hash, created_at, updated_at, version)
                    VALUES (:artifact_id, :task_id, NULL, :owner_principal, :kind,
                            'draft', :content, :content_sha256, :lineage, :trace_id,
                            :idempotency_key, :request_hash, :created_at, :updated_at, 1)""",
                    {
                        **artifact_data,
                        "artifact_id": artifact_id,
                        "owner_principal": owner,
                        "request_hash": artifact_hash,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                artifact_row = fetch_one(
                    connection, "SELECT * FROM artifacts WHERE artifact_id = :artifact_id", {"artifact_id": artifact_id}
                )
            elif artifact_row["request_hash"] != artifact_hash:
                raise IdempotencyConflict("web evidence record idempotency key was reused")
            assert artifact_row is not None
            return {
                "record_status": "saved",
                "source_count": len(content["sources"]),  # type: ignore[arg-type]
                "task": self._task_row(task_row),
                "artifact": self._artifact_row(artifact_row),
            }

    def get_task(self, task_id: object) -> dict[str, object]:
        task_id = _identifier(task_id, field="task_id")
        row = self._fetch_one("SELECT * FROM research_tasks WHERE task_id = :task_id", {"task_id": task_id})
        if row is None:
            raise ResearchNotFound("research task not found")
        return self._task_row(row)

    def list_tasks(self, *, owner_principal: str | None = None) -> dict[str, object]:
        if owner_principal:
            rows = self._execute(
                "SELECT * FROM research_tasks WHERE owner_principal = :owner_principal ORDER BY created_at DESC, task_id DESC LIMIT 200",
                {"owner_principal": owner_principal},
            )
        else:
            rows = self._execute("SELECT * FROM research_tasks ORDER BY created_at DESC, task_id DESC LIMIT 200")
        return {"tasks": [self._task_row(row) for row in rows]}

    def create_experiment(self, payload: object) -> dict[str, object]:
        data = self._experiment_payload(payload)
        request_hash = _hash_request(data)
        with self._transaction() as connection:
            task = fetch_one(connection, "SELECT * FROM research_tasks WHERE task_id = :task_id", {"task_id": data["task_id"]})
            if task is None:
                raise ResearchNotFound("research task not found")
            existing = fetch_one(
                connection,
                "SELECT * FROM experiments WHERE task_id = :task_id AND idempotency_key = :idempotency_key",
                {"task_id": data["task_id"], "idempotency_key": data["idempotency_key"]},
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict("experiment idempotency key was reused")
                return self._experiment_row(existing)
            now = _now()
            experiment_id = _new_id("experiment")
            execute(
                connection,
                """INSERT INTO experiments
                (experiment_id, task_id, owner_principal, name, status,
                 input_snapshot, trace_id, idempotency_key, request_hash,
                 created_at, updated_at, version)
                VALUES (:experiment_id, :task_id, :owner_principal, :name, 'planned',
                        :input_snapshot, :trace_id, :idempotency_key, :request_hash,
                        :created_at, :updated_at, 1)""",
                {"experiment_id": experiment_id, "task_id": data["task_id"], "owner_principal": task["owner_principal"],
                 "name": data["name"], "input_snapshot": data["input_snapshot"], "trace_id": data["trace_id"],
                 "idempotency_key": data["idempotency_key"], "request_hash": request_hash,
                 "created_at": now, "updated_at": now},
            )
        return self.get_experiment(experiment_id)

    def get_experiment(self, experiment_id: object) -> dict[str, object]:
        experiment_id = _identifier(experiment_id, field="experiment_id")
        row = self._fetch_one("SELECT * FROM experiments WHERE experiment_id = :experiment_id", {"experiment_id": experiment_id})
        if row is None:
            raise ResearchNotFound("experiment not found")
        return self._experiment_row(row)

    def list_experiments(self, *, owner_principal: str | None = None) -> dict[str, object]:
        if owner_principal:
            rows = self._execute(
                "SELECT * FROM experiments WHERE owner_principal = :owner_principal ORDER BY created_at DESC, experiment_id DESC LIMIT 200",
                {"owner_principal": owner_principal},
            )
        else:
            rows = self._execute("SELECT * FROM experiments ORDER BY created_at DESC, experiment_id DESC LIMIT 200")
        return {"experiments": [self._experiment_row(row) for row in rows]}

    def create_artifact(self, payload: object) -> dict[str, object]:
        data = self._artifact_payload(payload)
        request_hash = _hash_request(data)
        with self._transaction() as connection:
            task = fetch_one(connection, "SELECT * FROM research_tasks WHERE task_id = :task_id", {"task_id": data["task_id"]})
            if task is None:
                raise ResearchNotFound("research task not found")
            experiment_id = data["experiment_id"]
            if experiment_id is not None:
                experiment = fetch_one(connection, "SELECT * FROM experiments WHERE experiment_id = :experiment_id", {"experiment_id": experiment_id})
                if experiment is None or experiment["task_id"] != data["task_id"]:
                    raise ResearchNotFound("experiment does not belong to research task")
            lineage = [{"kind": "research_task", "id": data["task_id"]}]
            if experiment_id is not None:
                lineage.append({"kind": "experiment", "id": experiment_id})
            lineage.extend(data["lineage"])
            lineage, _ = _lineage(lineage)
            data["lineage"] = lineage
            request_hash = _hash_request(data)
            existing = fetch_one(
                connection,
                "SELECT * FROM artifacts WHERE task_id = :task_id AND idempotency_key = :idempotency_key",
                {"task_id": data["task_id"], "idempotency_key": data["idempotency_key"]},
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict("artifact idempotency key was reused")
                return self._artifact_row(existing)
            now = _now()
            artifact_id = _new_id("artifact")
            execute(
                connection,
                """INSERT INTO artifacts
                (artifact_id, task_id, experiment_id, owner_principal, kind,
                 status, content, content_sha256, lineage, trace_id,
                 idempotency_key, request_hash, created_at, updated_at, version)
                VALUES (:artifact_id, :task_id, :experiment_id, :owner_principal, :kind,
                        'draft', :content, :content_sha256, :lineage, :trace_id,
                        :idempotency_key, :request_hash, :created_at, :updated_at, 1)""",
                {"artifact_id": artifact_id, "task_id": data["task_id"], "experiment_id": experiment_id,
                 "owner_principal": task["owner_principal"], "kind": data["kind"], "content": data["content"],
                 "content_sha256": data["content_sha256"], "lineage": lineage, "trace_id": data["trace_id"],
                 "idempotency_key": data["idempotency_key"], "request_hash": request_hash,
                 "created_at": now, "updated_at": now},
            )
        return self.get_artifact(artifact_id)

    def get_artifact(self, artifact_id: object) -> dict[str, object]:
        artifact_id = _identifier(artifact_id, field="artifact_id")
        row = self._fetch_one("SELECT * FROM artifacts WHERE artifact_id = :artifact_id", {"artifact_id": artifact_id})
        if row is None:
            raise ResearchNotFound("artifact not found")
        return self._artifact_row(row)

    def find_artifact_by_content(
        self,
        task_id: object,
        kind: object,
        content_sha256: object,
    ) -> dict[str, object] | None:
        """Resolve one immutable content-addressed artifact within a task."""
        task_id = _identifier(task_id, field="task_id")
        kind = _text(kind, field="kind", max_length=64)
        fingerprint = _text(content_sha256, field="content_sha256", max_length=64)
        if re.fullmatch(r"[a-f0-9]{64}", fingerprint) is None:
            raise ValueError("content_sha256 is not a valid SHA-256 fingerprint")
        row = self._fetch_one(
            """SELECT * FROM artifacts
            WHERE task_id = :task_id AND kind = :kind AND content_sha256 = :content_sha256
            ORDER BY created_at ASC, artifact_id ASC LIMIT 1""",
            {"task_id": task_id, "kind": kind, "content_sha256": fingerprint},
        )
        return None if row is None else self._artifact_row(row)

    def list_artifacts(self, *, owner_principal: str | None = None) -> dict[str, object]:
        if owner_principal:
            rows = self._execute(
                "SELECT * FROM artifacts WHERE owner_principal = :owner_principal ORDER BY created_at DESC, artifact_id DESC LIMIT 200",
                {"owner_principal": owner_principal},
            )
        else:
            rows = self._execute("SELECT * FROM artifacts ORDER BY created_at DESC, artifact_id DESC LIMIT 200")
        return {"artifacts": [self._artifact_row(row) for row in rows]}

    def list_ml_workspace_artifacts(
        self, *, owner_principal: str, workspace_id: str, limit: int = 200
    ) -> list[dict[str, object]]:
        """Return ML workspace metadata without materialising large row payloads."""
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        rows = self._execute(
            """SELECT artifact_id, task_id, experiment_id, owner_principal, workspace_id,
                      kind, status,
                      content - ARRAY['rows', 'signals', 'bars', 'universe']::text[] AS content,
                      content_sha256, lineage, trace_id, created_at, updated_at, version
               FROM artifacts
               WHERE owner_principal = :owner AND workspace_id = :workspace
                 AND kind IN ('ml_strategy_version', 'ml_strategy_approval', 'ml_model',
                              'ml_model_bundle', 'ml_regime_snapshot',
                              'ml_prediction_snapshot', 'signal_snapshot')
               ORDER BY created_at DESC, artifact_id DESC LIMIT :limit""",
            {"owner": owner_principal, "workspace": workspace_id, "limit": limit},
        )
        return [self._artifact_row(row) for row in rows]

    def list_ml_strategy_catalog(
        self, *, owner_principal: str, workspace_id: str, query: str = "",
        status: str = "all", limit: int = 20, offset: int = 0,
    ) -> dict[str, object]:
        """Page lightweight ML studies without materialising immutable artifacts."""
        owner = _text(owner_principal, field="owner_principal", max_length=128)
        # Workspace identities are durable UUIDs owned by the tenancy boundary,
        # not Research domain entity IDs (task_*/artifact_*).
        workspace = _text(workspace_id, field="workspace_id", max_length=64)
        needle = str(query or "").strip()
        if len(needle) > 100:
            raise ValueError("query must not exceed 100 characters")
        if status not in {"all", "active", "completed", "failed", "archived"}:
            raise ValueError("status must be all, active, completed, failed, or archived")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be non-negative")
        params: dict[str, object] = {
            "owner": owner, "workspace": workspace, "query": f"%{needle}%",
            "limit": limit, "offset": offset,
        }
        status_clause = {
            "all": "TRUE",
            "active": "stage NOT IN ('completed', 'failed')",
            "completed": "stage = 'completed'",
            "failed": "stage = 'failed'",
            "archived": "TRUE",
        }[status]
        lifecycle_clause = "a.status = 'archived'" if status == "archived" else "a.status NOT IN ('superseded', 'archived')"
        catalogue = """
            WITH base AS (
                SELECT a.artifact_id, a.task_id, a.status, a.created_at,
                       CASE WHEN a.status='archived' THEN 'archived' ELSE 'active' END AS lifecycle_status,
                       t.title AS task_title,
                       a.content ->> 'schema_version' AS schema_version,
                       a.content ->> 'name' AS name,
                       a.content -> 'learner' ->> 'profile' AS learner_profile,
                       COALESCE((a.content -> 'regime' ->> 'enabled')::boolean, FALSE) AS regime_enabled,
                       COALESCE(a.content -> 'target' -> 'parameters' ->> 'horizon_sessions',
                                a.content -> 'target' ->> 'horizon_sessions') AS horizon_sessions,
                       (SELECT r.status FROM ml_training_runs r
                        WHERE r.workspace_id=:workspace AND r.owner_principal=:owner
                          AND r.ml_strategy_artifact_id=a.artifact_id
                        ORDER BY r.created_at DESC, r.training_run_id DESC LIMIT 1) AS training_status,
                       (SELECT r.status FROM ml_prediction_runs r
                        WHERE r.workspace_id=:workspace AND r.owner_principal=:owner
                          AND r.ml_strategy_artifact_id=a.artifact_id
                        ORDER BY r.created_at DESC, r.prediction_run_id DESC LIMIT 1) AS prediction_status,
                       (SELECT r.status FROM backtest_jobs r
                        WHERE r.workspace_id=:workspace AND r.owner_principal=:owner
                          AND r.strategy_version_artifact_id=a.artifact_id
                        ORDER BY r.created_at DESC, r.job_id DESC LIMIT 1) AS backtest_status
                FROM artifacts a
                JOIN research_tasks t ON t.task_id=a.task_id
                WHERE a.owner_principal=:owner AND a.workspace_id=:workspace
                  AND a.kind='ml_strategy_version'
                  AND {lifecycle_clause}
                  AND (:query='%%' OR a.artifact_id ILIKE :query
                       OR a.content ->> 'name' ILIKE :query OR t.title ILIKE :query)
            ), staged AS (
                SELECT *, CASE
                    WHEN backtest_status='completed' THEN 'completed'
                    WHEN backtest_status IN ('failed','cancelled')
                      OR prediction_status IN ('failed','cancelled')
                      OR training_status IN ('failed','cancelled') THEN 'failed'
                    WHEN backtest_status IS NOT NULL THEN 'backtest'
                    WHEN prediction_status='completed' THEN 'signal'
                    WHEN prediction_status IS NOT NULL THEN 'prediction'
                    WHEN training_status='completed' THEN 'model'
                    WHEN training_status IS NOT NULL THEN 'training'
                    ELSE 'definition' END AS stage
                FROM base
            )
        """.format(lifecycle_clause=lifecycle_clause)
        rows = self._execute(
            catalogue + f"""SELECT * FROM staged WHERE {status_clause}
                ORDER BY created_at DESC, artifact_id DESC LIMIT :limit OFFSET :offset""",
            params,
        )
        total_row = self._fetch_one(
            catalogue + f"SELECT COUNT(*) AS total FROM staged WHERE {status_clause}", params,
        )
        return {
            "studies": [_row_dict(row) for row in rows],
            "total": int(total_row["total"] if total_row else 0),
            "limit": limit, "offset": offset,
            "has_more": offset + limit < int(total_row["total"] if total_row else 0),
        }

    def get_ml_study_management(
        self, artifact_id: object, *, owner_principal: str, workspace_id: str,
    ) -> dict[str, object]:
        """Return authoritative lifecycle actions for one visible ML study."""
        identity = _identifier(artifact_id, field="artifact_id")
        owner = _text(owner_principal, field="owner_principal", max_length=128)
        workspace = _text(workspace_id, field="workspace_id", max_length=64)
        with self._transaction() as connection:
            study = fetch_one(
                connection,
                """SELECT status FROM artifacts WHERE artifact_id=:artifact_id
                   AND owner_principal=:owner AND workspace_id=:workspace
                   AND kind='ml_strategy_version'""",
                {"artifact_id": identity, "owner": owner, "workspace": workspace},
            )
            if study is None or study["status"] == "superseded":
                raise ResearchNotFound("ML study not found")
            return self._ml_study_management_in_transaction(
                connection, identity=identity, owner=owner, workspace=workspace,
                study_status=str(study["status"]),
            )

    def set_ml_study_lifecycle(
        self, artifact_id: object, payload: object, *, owner_principal: str,
        workspace_id: str,
    ) -> dict[str, object]:
        """Archive or restore an executed study without rewriting its evidence."""
        if not isinstance(payload, dict):
            raise ValueError("ML study lifecycle request must be an object")
        if set(payload) != {"status", "idempotency_key"}:
            raise ValueError("ML study lifecycle request has invalid fields")
        identity = _identifier(artifact_id, field="artifact_id")
        owner = _text(owner_principal, field="owner_principal", max_length=128)
        workspace = _text(workspace_id, field="workspace_id", max_length=64)
        requested = _text(payload.get("status"), field="status", max_length=16)
        if requested not in {"active", "archived"}:
            raise ValueError("status must be active or archived")
        key = _idempotency_key(payload.get("idempotency_key"))
        target = "archived" if requested == "archived" else "validated"
        request_hash = _hash_request({
            "entity_type": "ml_study_lifecycle", "entity_id": identity,
            "target_status": target,
        })
        with self._transaction() as connection:
            execute(
                connection,
                "SELECT pg_advisory_xact_lock(hashtext(:study_lock))",
                {"study_lock": f"ml-study|{workspace}|{owner}|{identity}"},
            )
            study = fetch_one(
                connection,
                """SELECT * FROM artifacts WHERE artifact_id=:artifact_id
                   AND owner_principal=:owner AND workspace_id=:workspace
                   AND kind='ml_strategy_version' FOR UPDATE""",
                {"artifact_id": identity, "owner": owner, "workspace": workspace},
            )
            if study is None or study["status"] == "superseded":
                raise ResearchNotFound("ML study not found")
            existing = fetch_one(
                connection,
                """SELECT * FROM research_transitions WHERE entity_type='artifact'
                   AND entity_id=:entity_id AND idempotency_key=:key""",
                {"entity_id": identity, "key": key},
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict("ML study lifecycle idempotency key was reused")
                result = existing["result_json"]
                if not isinstance(result, dict):
                    raise ResearchPersistenceError("stored ML study lifecycle result is invalid")
                return result

            current = str(study["status"])
            if requested == "archived":
                if current not in {"validated", "archived"}:
                    raise InvalidTransition(f"cannot archive ML study from {current}")
                management = self._ml_study_management_in_transaction(
                    connection, identity=identity, owner=owner, workspace=workspace,
                    study_status=current,
                )
                if current != "archived" and not management["can_archive"]:
                    raise InvalidTransition(str(management["reason"]))
            elif current not in {"validated", "archived"}:
                raise InvalidTransition(f"cannot restore ML study from {current}")

            if current != target:
                execute(
                    connection,
                    """UPDATE artifacts SET status=:status, updated_at=:updated_at,
                       version=version+1 WHERE artifact_id=:artifact_id""",
                    {"status": target, "updated_at": _now(), "artifact_id": identity},
                )
                study = fetch_one(
                    connection, "SELECT * FROM artifacts WHERE artifact_id=:artifact_id",
                    {"artifact_id": identity},
                )
                assert study is not None
            management = self._ml_study_management_in_transaction(
                connection, identity=identity, owner=owner, workspace=workspace,
                study_status=str(study["status"]),
            )
            result = {"study": self._artifact_row(study), "management": management}
            execute(
                connection,
                """INSERT INTO research_transitions
                   (entity_type,entity_id,idempotency_key,request_hash,target_status,result_json)
                   VALUES ('artifact',:entity_id,:key,:request_hash,:target_status,:result_json)""",
                {"entity_id": identity, "key": key, "request_hash": request_hash,
                 "target_status": target, "result_json": result},
            )
            return result

    @staticmethod
    def _ml_study_management_in_transaction(
        connection: Any, *, identity: str, owner: str, workspace: str,
        study_status: str,
    ) -> dict[str, object]:
        counts = fetch_one(
            connection,
            """SELECT
               (SELECT COUNT(*) FROM ml_training_runs WHERE workspace_id=:workspace
                 AND owner_principal=:owner AND ml_strategy_artifact_id=:artifact_id) AS training_count,
               (SELECT COUNT(*) FROM ml_prediction_runs WHERE workspace_id=:workspace
                 AND owner_principal=:owner AND ml_strategy_artifact_id=:artifact_id) AS prediction_count,
               (SELECT COUNT(*) FROM backtest_jobs WHERE workspace_id=:workspace
                 AND owner_principal=:owner AND strategy_version_artifact_id=:artifact_id) AS backtest_count,
               (SELECT COUNT(*) FROM ml_training_runs WHERE workspace_id=:workspace
                 AND owner_principal=:owner AND ml_strategy_artifact_id=:artifact_id
                 AND status NOT IN ('completed','failed','cancelled')) AS active_training_count,
               (SELECT COUNT(*) FROM ml_prediction_runs WHERE workspace_id=:workspace
                 AND owner_principal=:owner AND ml_strategy_artifact_id=:artifact_id
                 AND status NOT IN ('completed','failed','cancelled')) AS active_prediction_count,
               (SELECT COUNT(*) FROM backtest_jobs WHERE workspace_id=:workspace
                 AND owner_principal=:owner AND strategy_version_artifact_id=:artifact_id
                 AND status NOT IN ('completed','failed','cancelled')) AS active_backtest_count""",
            {"artifact_id": identity, "owner": owner, "workspace": workspace},
        )
        assert counts is not None
        history_count = sum(int(counts[field]) for field in (
            "training_count", "prediction_count", "backtest_count",
        ))
        active_count = sum(int(counts[field]) for field in (
            "active_training_count", "active_prediction_count", "active_backtest_count",
        ))
        archived = study_status == "archived"
        if archived:
            reason = "研究已归档；全部运行与制品仍可审计，可恢复后继续使用"
        elif history_count == 0:
            reason = "尚未执行，可删除研究定义；删除不会物理移除审计记录"
        elif active_count:
            reason = "仍有训练、预测或回测任务进行中，结束后才可归档"
        else:
            reason = "已产生运行证据，只能归档；模型、预测、信号与回测结果会保留"
        return {
            "lifecycle_status": "archived" if archived else "active",
            "can_delete": not archived and history_count == 0,
            "can_archive": not archived and history_count > 0 and active_count == 0,
            "can_restore": archived,
            "history_count": history_count,
            "active_run_count": active_count,
            "reason": reason,
        }

    def supersede_unexecuted_ml_study(
        self, artifact_id: object, *, owner_principal: str, workspace_id: str,
    ) -> dict[str, object]:
        """Hide one never-executed ML study while preserving its audit history.

        Training, prediction and Backtest rows are immutable execution evidence.
        Once any such row exists, the study cannot be deleted.  A safe delete is
        therefore an atomic status transition for the strategy and every approval
        that authorized it, never a physical row deletion.
        """
        identity = _identifier(artifact_id, field="artifact_id")
        owner = _text(owner_principal, field="owner_principal", max_length=128)
        workspace = _text(workspace_id, field="workspace_id", max_length=64)
        with self._transaction() as connection:
            execute(
                connection,
                "SELECT pg_advisory_xact_lock(hashtext(:study_lock))",
                {"study_lock": f"ml-study|{workspace}|{owner}|{identity}"},
            )
            study = fetch_one(
                connection,
                """SELECT * FROM artifacts WHERE artifact_id=:artifact_id
                   AND owner_principal=:owner AND workspace_id=:workspace
                   AND kind='ml_strategy_version' FOR UPDATE""",
                {"artifact_id": identity, "owner": owner, "workspace": workspace},
            )
            if study is None:
                raise ResearchNotFound("ML study not found")

            approvals = execute(
                connection,
                """SELECT * FROM artifacts WHERE owner_principal=:owner
                   AND workspace_id=:workspace AND kind='ml_strategy_approval'
                   AND content ->> 'ml_strategy_artifact_id'=:artifact_id
                   ORDER BY created_at,artifact_id FOR UPDATE""",
                {"artifact_id": identity, "owner": owner, "workspace": workspace},
            )
            if study["status"] != "superseded":
                dependencies = fetch_one(
                    connection,
                    """SELECT
                       (SELECT COUNT(*) FROM ml_training_runs WHERE workspace_id=:workspace
                         AND owner_principal=:owner AND ml_strategy_artifact_id=:artifact_id) AS training_count,
                       (SELECT COUNT(*) FROM ml_prediction_runs WHERE workspace_id=:workspace
                         AND owner_principal=:owner AND ml_strategy_artifact_id=:artifact_id) AS prediction_count,
                       (SELECT COUNT(*) FROM backtest_jobs WHERE workspace_id=:workspace
                         AND owner_principal=:owner AND strategy_version_artifact_id=:artifact_id) AS backtest_count""",
                    {"artifact_id": identity, "owner": owner, "workspace": workspace},
                )
                assert dependencies is not None
                if any(int(dependencies[field]) > 0 for field in (
                    "training_count", "prediction_count", "backtest_count",
                )):
                    raise InvalidTransition(
                        "ML study with training, prediction, or backtest history cannot be deleted"
                    )

                targets = [study, *[row for row in approvals if row["status"] != "superseded"]]
                for row in targets:
                    current = str(row["status"])
                    if "superseded" not in ARTIFACT_TRANSITIONS.get(current, set()):
                        raise InvalidTransition(
                            f"cannot delete ML study artifact from {current}"
                        )
                now = _now()
                for row in targets:
                    target_id = str(row["artifact_id"])
                    execute(
                        connection,
                        """UPDATE artifacts SET status='superseded', updated_at=:updated_at,
                           version=version+1 WHERE artifact_id=:artifact_id""",
                        {"artifact_id": target_id, "updated_at": now},
                    )
                    updated = fetch_one(
                        connection, "SELECT * FROM artifacts WHERE artifact_id=:artifact_id",
                        {"artifact_id": target_id},
                    )
                    assert updated is not None
                    result = self._artifact_row(updated)
                    transition_key = f"ml-study-delete-{identity}-{target_id}"
                    request_hash = _hash_request({
                        "entity_type": "artifact", "entity_id": target_id,
                        "target_status": "superseded",
                    })
                    execute(
                        connection,
                        """INSERT INTO research_transitions
                           (entity_type,entity_id,idempotency_key,request_hash,target_status,result_json)
                           VALUES ('artifact',:entity_id,:idempotency_key,:request_hash,'superseded',:result_json)""",
                        {"entity_id": target_id, "idempotency_key": transition_key,
                         "request_hash": request_hash, "result_json": result},
                    )
                study = fetch_one(
                    connection, "SELECT * FROM artifacts WHERE artifact_id=:artifact_id",
                    {"artifact_id": identity},
                )
                assert study is not None

            return {
                "study": self._artifact_row(study),
                "invalidated_approval_ids": [str(row["artifact_id"]) for row in approvals],
            }

    def get_ml_artifact_metadata(
        self, artifact_id: object, *, owner_principal: str, workspace_id: str,
    ) -> dict[str, object]:
        """Read one ML artifact after stripping every potentially large row array in SQL."""
        identity = _identifier(artifact_id, field="artifact_id")
        row = self._fetch_one(
            """SELECT artifact_id, task_id, experiment_id, owner_principal, workspace_id,
                      kind, status,
                      content - ARRAY['rows', 'signals', 'bars', 'universe']::text[] AS content,
                      content_sha256, lineage, trace_id, created_at, updated_at, version
               FROM artifacts WHERE artifact_id=:artifact_id AND owner_principal=:owner
                 AND workspace_id=:workspace
                 AND kind IN ('ml_strategy_version', 'ml_strategy_approval', 'ml_model',
                              'ml_model_bundle', 'ml_regime_snapshot',
                              'ml_prediction_snapshot', 'signal_snapshot')""",
            {"artifact_id": identity, "owner": owner_principal, "workspace": workspace_id},
        )
        if row is None:
            raise ResearchNotFound("ML artifact not found")
        return self._artifact_row(row)

    def get_strategy_approval(
        self, *, owner_principal: str, strategy_version_artifact_id: str
    ) -> dict[str, object] | None:
        row = self._fetch_one(
            """SELECT * FROM artifacts
               WHERE owner_principal = :owner AND kind = 'strategy_approval'
                 AND content ->> 'strategy_version_artifact_id' = :version_id
               ORDER BY created_at DESC, artifact_id DESC LIMIT 1""",
            {"owner": owner_principal, "version_id": strategy_version_artifact_id},
        )
        return None if row is None else self._artifact_row(row)

    def get_ml_strategy_approval(
        self, *, owner_principal: str, workspace_id: str, ml_strategy_artifact_id: str
    ) -> dict[str, object] | None:
        row = self._fetch_one(
            """SELECT * FROM artifacts
               WHERE owner_principal = :owner AND workspace_id = :workspace
                 AND kind = 'ml_strategy_approval' AND status = 'validated'
                 AND content ->> 'ml_strategy_artifact_id' = :strategy_id
                 AND content ->> 'decision' = 'approved'
                 AND content ->> 'execution_authorized' = 'true'
               ORDER BY created_at DESC, artifact_id DESC LIMIT 1""",
            {"owner": owner_principal, "workspace": workspace_id, "strategy_id": ml_strategy_artifact_id},
        )
        return None if row is None else self._artifact_row(row)

    def list_ml_prediction_rows(
        self, *, artifact_id: str, owner_principal: str, workspace_id: str,
        query: str, limit: int, offset: int,
    ) -> dict[str, object]:
        """Filter and page a prediction JSON array inside PostgreSQL."""
        artifact = self._fetch_one(
            """SELECT artifact_id, jsonb_typeof(content -> 'rows') AS rows_type
               FROM artifacts WHERE artifact_id = :artifact_id AND owner_principal = :owner
                 AND workspace_id = :workspace AND kind = 'ml_prediction_snapshot'""",
            {"artifact_id": artifact_id, "owner": owner_principal, "workspace": workspace_id},
        )
        if artifact is None:
            raise ResearchNotFound("prediction artifact not found")
        if artifact.get("rows_type") != "array":
            raise ValueError("prediction artifact rows are invalid")
        escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        needle = f"%{escaped}%"
        rows = self._execute(
            """WITH matching AS (
                   SELECT value, ordinality
                   FROM artifacts a,
                        jsonb_array_elements(a.content -> 'rows') WITH ORDINALITY AS item(value, ordinality)
                   WHERE a.artifact_id = :artifact_id
                     AND (:query = '' OR concat_ws(' ', value ->> 'symbol', value ->> 'session',
                                                    value ->> 'rank') ILIKE :needle ESCAPE '\\')
               ), paged AS (
                   SELECT jsonb_strip_nulls(jsonb_build_object(
                       'session', value -> 'session', 'rank', value -> 'rank',
                       'symbol', value -> 'symbol', 'score', value -> 'score',
                       'regime', value -> 'regime', 'expert_key', value -> 'expert_key',
                       'model_artifact_id', value -> 'model_artifact_id'
                   )) AS row
                   FROM matching ORDER BY ordinality LIMIT :limit OFFSET :offset
               ), total AS (SELECT COUNT(*)::bigint AS count FROM matching)
               SELECT paged.row, total.count FROM total LEFT JOIN paged ON TRUE""",
            {
                "artifact_id": artifact_id, "query": query.strip(), "needle": needle,
                "limit": limit, "offset": offset,
            },
        )
        total = int(rows[0]["count"] if rows else 0)
        return {"rows": [row["row"] for row in rows if row.get("row") is not None], "total": total}

    def list_task_options(
        self, *, owner_principal: str, limit: int = 50
    ) -> list[dict[str, object]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        rows = self._execute(
            """SELECT task_id, title, status, created_at, updated_at
               FROM research_tasks WHERE owner_principal = :owner
               ORDER BY created_at DESC, task_id DESC LIMIT :limit""",
            {"owner": owner_principal, "limit": limit},
        )
        return [_row_dict(row) for row in rows]

    def list_strategy_artifacts(
        self,
        *,
        owner_principal: str,
        lifecycle: str = "active",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]:
        """Direct paginated strategy query; never truncates via generic artifact lists."""
        if lifecycle not in {"active", "superseded", "all"}:
            raise ValueError("lifecycle must be active, superseded, or all")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("offset must be non-negative")
        status_sql = "AND status <> 'superseded'" if lifecycle == "active" else (
            "AND status = 'superseded'" if lifecycle == "superseded" else ""
        )
        params = {"owner": owner_principal, "limit": limit, "offset": offset}
        rows = self._execute(
            f"""SELECT * FROM artifacts WHERE owner_principal = :owner
                 AND kind IN ('strategy_draft', 'strategy_version') {status_sql}
                 ORDER BY created_at DESC, artifact_id DESC LIMIT :limit OFFSET :offset""",
            params,
        )
        total = self._fetch_one(
            f"""SELECT COUNT(*) AS total FROM artifacts WHERE owner_principal = :owner
                 AND kind IN ('strategy_draft', 'strategy_version') {status_sql}""",
            {"owner": owner_principal},
        )
        return {
            "strategies": [self._artifact_row(row) for row in rows],
            "total": int(total["total"] if total else 0),
            "limit": limit,
            "offset": offset,
            "lifecycle": lifecycle,
        }

    def list_strategy_versions(
        self, *, owner_principal: str, strategy_id: str, limit: int = 1_000
    ) -> list[dict[str, object]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 10_000:
            raise ValueError("limit must be between 1 and 10000")
        rows = self._execute(
            """SELECT * FROM artifacts WHERE owner_principal = :owner
                 AND kind = 'strategy_version' AND content ->> 'strategy_id' = :strategy_id
                 ORDER BY created_at DESC, artifact_id DESC LIMIT :limit""",
            {"owner": owner_principal, "strategy_id": strategy_id, "limit": limit},
        )
        return [self._artifact_row(row) for row in rows]

    def list_strategy_approvals(
        self, *, owner_principal: str, limit: int = 10_000
    ) -> list[dict[str, object]]:
        rows = self._execute(
            """SELECT * FROM artifacts WHERE owner_principal = :owner
                 AND kind = 'strategy_approval' ORDER BY created_at DESC, artifact_id DESC
                 LIMIT :limit""",
            {"owner": owner_principal, "limit": limit},
        )
        return [self._artifact_row(row) for row in rows]

    def list_validated_strategy_versions(
        self, *, owner_principal: str, limit: int = 10_000
    ) -> list[dict[str, object]]:
        rows = self._execute(
            """SELECT * FROM artifacts WHERE owner_principal = :owner
                 AND kind = 'strategy_version' AND status = 'validated'
                 ORDER BY created_at DESC, artifact_id DESC LIMIT :limit""",
            {"owner": owner_principal, "limit": limit},
        )
        return [self._artifact_row(row) for row in rows]

    def transition(
        self,
        entity_type: object,
        entity_id: object,
        target_status: object,
        idempotency_key: object,
    ) -> dict[str, object]:
        entity_type = _text(entity_type, field="entity_type", max_length=32)
        entity_id = _identifier(entity_id, field="entity_id")
        target_status = _text(target_status, field="target_status", max_length=32)
        idempotency_key = _idempotency_key(idempotency_key)
        config = {
            "research_task": ("research_tasks", TASK_TRANSITIONS, self._task_row),
            "experiment": ("experiments", EXPERIMENT_TRANSITIONS, self._experiment_row),
            "artifact": ("artifacts", ARTIFACT_TRANSITIONS, self._artifact_row),
        }.get(entity_type)
        if config is None:
            raise ValueError("entity_type must be research_task, experiment, or artifact")
        table, transitions, row_mapper = config
        request_hash = _hash_request(
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "target_status": target_status,
            }
        )
        with self._transaction() as connection:
            row = fetch_one(
                connection,
                f"SELECT * FROM {table} WHERE {self._id_column(entity_type)} = :entity_id",
                {"entity_id": entity_id},
            )
            if row is None:
                raise ResearchNotFound(f"{entity_type} not found")
            existing = fetch_one(
                connection,
                """SELECT * FROM research_transitions
                WHERE entity_type = :entity_type AND entity_id = :entity_id AND idempotency_key = :idempotency_key""",
                {"entity_type": entity_type, "entity_id": entity_id, "idempotency_key": idempotency_key},
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict("transition idempotency key was reused")
                result = existing["result_json"]
                if not isinstance(result, dict):
                    raise ResearchPersistenceError("stored transition result is invalid")
                return result
            current = row["status"]
            if target_status not in transitions[current]:
                raise InvalidTransition(
                    f"cannot transition {entity_type} from {current} to {target_status}"
                )
            if target_status == current:
                result = row_mapper(row)
                execute(
                    connection,
                    """INSERT INTO research_transitions
                    (entity_type, entity_id, idempotency_key, request_hash, target_status, result_json)
                    VALUES (:entity_type, :entity_id, :idempotency_key, :request_hash, :target_status, :result_json)""",
                    {"entity_type": entity_type, "entity_id": entity_id, "idempotency_key": idempotency_key,
                     "request_hash": request_hash, "target_status": target_status, "result_json": result},
                )
                return result
            now = _now()
            execute(
                connection,
                f"UPDATE {table} SET status = :status, updated_at = :updated_at, version = version + 1 WHERE {self._id_column(entity_type)} = :entity_id",
                {"status": target_status, "updated_at": now, "entity_id": entity_id},
            )
            updated = fetch_one(
                connection,
                f"SELECT * FROM {table} WHERE {self._id_column(entity_type)} = :entity_id",
                {"entity_id": entity_id},
            )
            assert updated is not None
            result = row_mapper(updated)
            execute(
                connection,
                """INSERT INTO research_transitions
                (entity_type, entity_id, idempotency_key, request_hash, target_status, result_json)
                VALUES (:entity_type, :entity_id, :idempotency_key, :request_hash, :target_status, :result_json)""",
                {"entity_type": entity_type, "entity_id": entity_id, "idempotency_key": idempotency_key,
                 "request_hash": request_hash, "target_status": target_status, "result_json": result},
            )
            return result

    @staticmethod
    def _id_column(entity_type: str) -> str:
        return {
            "research_task": "task_id",
            "experiment": "experiment_id",
            "artifact": "artifact_id",
        }[entity_type]

    @staticmethod
    def _task_payload(payload: object) -> dict[str, str]:
        if not isinstance(payload, dict):
            raise ValueError("research task request must be an object")
        _reject_unknown(payload, {"owner_principal", "title", "objective", "trace_id", "idempotency_key"})
        return {
            "owner_principal": _text(payload.get("owner_principal"), field="owner_principal", max_length=128),
            "title": _text(payload.get("title"), field="title", max_length=200),
            "objective": _text(payload.get("objective"), field="objective", max_length=4000),
            "trace_id": _trace_id(payload.get("trace_id")),
            "idempotency_key": _idempotency_key(payload.get("idempotency_key")),
        }

    @staticmethod
    def _experiment_payload(payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("experiment request must be an object")
        _reject_unknown(payload, {"task_id", "name", "input_snapshot", "trace_id", "idempotency_key"})
        snapshot, _ = _snapshot(payload.get("input_snapshot"))
        return {
            "task_id": _identifier(payload.get("task_id"), field="task_id"),
            "name": _text(payload.get("name"), field="name", max_length=200),
            "input_snapshot": snapshot,
            "trace_id": _trace_id(payload.get("trace_id")),
            "idempotency_key": _idempotency_key(payload.get("idempotency_key")),
        }

    @staticmethod
    def _artifact_payload(payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("artifact request must be an object")
        _reject_unknown(
            payload,
            {"task_id", "experiment_id", "kind", "content", "lineage", "trace_id", "idempotency_key"},
        )
        kind = _text(payload.get("kind"), field="kind", max_length=64)
        raw_content = payload.get("content")
        if not isinstance(raw_content, dict):
            raise ValueError("content must be an object")
        if kind == "web_research_evidence":
            raw_content = validate_web_research_evidence(raw_content)
        content, content_json = _canonical_json(
            raw_content, field="content", max_bytes=MAX_ARTIFACT_JSON_BYTES
        )
        lineage, _ = _lineage(payload.get("lineage", []))
        return {
            "task_id": _identifier(payload.get("task_id"), field="task_id"),
            "experiment_id": (
                _identifier(payload["experiment_id"], field="experiment_id")
                if payload.get("experiment_id") is not None
                else None
            ),
            "kind": kind,
            "content": content,
            "content_sha256": hashlib.sha256(content_json.encode("utf-8")).hexdigest(),
            "lineage": lineage,
            "trace_id": _trace_id(payload.get("trace_id")),
            "idempotency_key": _idempotency_key(payload.get("idempotency_key")),
        }

    @staticmethod
    def _task_row(row: dict[str, Any]) -> dict[str, object]:
        result = _row_dict(row)
        result.pop("idempotency_key", None)
        result.pop("request_hash", None)
        return result

    @staticmethod
    def _experiment_row(row: dict[str, Any]) -> dict[str, object]:
        result = _row_dict(row)
        result.pop("idempotency_key", None)
        result.pop("request_hash", None)
        result["input_snapshot"] = result.pop("input_snapshot") or {}
        return result

    @staticmethod
    def _artifact_row(row: dict[str, Any]) -> dict[str, object]:
        result = _row_dict(row)
        result.pop("idempotency_key", None)
        result.pop("request_hash", None)
        result["content"] = result.pop("content") or {}
        result["lineage"] = result.pop("lineage") or []
        return result
