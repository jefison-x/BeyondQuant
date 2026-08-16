from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_JSON_BYTES = 64 * 1024
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


def _canonical_json(value: object, *, field: str) -> tuple[object, str]:
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
    if len(encoded) > MAX_JSON_BYTES:
        raise ValueError(f"{field} exceeds {MAX_JSON_BYTES} bytes")
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


def _row_dict(row: sqlite3.Row) -> dict[str, object]:
    return dict(row)


class ResearchStore:
    """Backend-owned durable repository for Phase 9 business entities."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = sqlite3.connect(
                self.path,
                timeout=10.0,
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 10000")
            self._create_schema()
        except sqlite3.Error as error:
            raise ResearchPersistenceError("research storage is unavailable") from error

    @classmethod
    def from_env(cls) -> "ResearchStore":
        return cls(os.getenv("BYQ_DOMAIN_DB_PATH", "/tmp/byq-domain.sqlite3"))

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
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
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS research_tasks_idempotency
                    ON research_tasks(owner_principal, idempotency_key);

                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES research_tasks(task_id),
                    owner_principal TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_snapshot TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS experiments_idempotency
                    ON experiments(task_id, idempotency_key);

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES research_tasks(task_id),
                    experiment_id TEXT REFERENCES experiments(experiment_id),
                    owner_principal TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    lineage TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS artifacts_idempotency
                    ON artifacts(task_id, idempotency_key);

                CREATE TABLE IF NOT EXISTS research_transitions (
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    target_status TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY(entity_type, entity_id, idempotency_key)
                );
                """
            )
            transition_columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(research_transitions)").fetchall()
            }
            if "result_json" not in transition_columns:
                self._connection.execute(
                    "ALTER TABLE research_transitions ADD COLUMN result_json TEXT NOT NULL DEFAULT '{}'"
                )

    def create_task(self, payload: object) -> dict[str, object]:
        data = self._task_payload(payload)
        request_hash = _hash_request(data)
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT * FROM research_tasks WHERE owner_principal = ? AND idempotency_key = ?",
                (data["owner_principal"], data["idempotency_key"]),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict("research task idempotency key was reused")
                return self._task_row(existing)

            now = _now()
            task_id = _new_id("task")
            self._connection.execute(
                """INSERT INTO research_tasks
                (task_id, owner_principal, title, objective, status, trace_id,
                 idempotency_key, request_hash, created_at, updated_at, version)
                VALUES (?, ?, ?, ?, 'planned', ?, ?, ?, ?, ?, 1)""",
                (
                    task_id,
                    data["owner_principal"],
                    data["title"],
                    data["objective"],
                    data["trace_id"],
                    data["idempotency_key"],
                    request_hash,
                    now,
                    now,
                ),
            )
            return self.get_task(task_id)

    def get_task(self, task_id: object) -> dict[str, object]:
        task_id = _identifier(task_id, field="task_id")
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM research_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise ResearchNotFound("research task not found")
        return self._task_row(row)

    def list_tasks(self, *, owner_principal: str | None = None) -> dict[str, object]:
        with self._lock:
            if owner_principal:
                rows = self._connection.execute(
                    "SELECT * FROM research_tasks WHERE owner_principal = ? ORDER BY created_at DESC, task_id DESC LIMIT 200",
                    (owner_principal,),
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT * FROM research_tasks ORDER BY created_at DESC, task_id DESC LIMIT 200"
                ).fetchall()
        return {"tasks": [self._task_row(row) for row in rows]}

    def create_experiment(self, payload: object) -> dict[str, object]:
        data = self._experiment_payload(payload)
        request_hash = _hash_request(data)
        with self._lock, self._connection:
            task = self._connection.execute(
                "SELECT * FROM research_tasks WHERE task_id = ?", (data["task_id"],)
            ).fetchone()
            if task is None:
                raise ResearchNotFound("research task not found")
            existing = self._connection.execute(
                "SELECT * FROM experiments WHERE task_id = ? AND idempotency_key = ?",
                (data["task_id"], data["idempotency_key"]),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict("experiment idempotency key was reused")
                return self._experiment_row(existing)

            now = _now()
            experiment_id = _new_id("experiment")
            self._connection.execute(
                """INSERT INTO experiments
                (experiment_id, task_id, owner_principal, name, status,
                 input_snapshot, trace_id, idempotency_key, request_hash,
                 created_at, updated_at, version)
                VALUES (?, ?, ?, ?, 'planned', ?, ?, ?, ?, ?, ?, 1)""",
                (
                    experiment_id,
                    data["task_id"],
                    task["owner_principal"],
                    data["name"],
                    data["input_snapshot_json"],
                    data["trace_id"],
                    data["idempotency_key"],
                    request_hash,
                    now,
                    now,
                ),
            )
            return self.get_experiment(experiment_id)

    def get_experiment(self, experiment_id: object) -> dict[str, object]:
        experiment_id = _identifier(experiment_id, field="experiment_id")
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
        if row is None:
            raise ResearchNotFound("experiment not found")
        return self._experiment_row(row)

    def list_experiments(self, *, owner_principal: str | None = None) -> dict[str, object]:
        with self._lock:
            if owner_principal:
                rows = self._connection.execute(
                    "SELECT * FROM experiments WHERE owner_principal = ? ORDER BY created_at DESC, experiment_id DESC LIMIT 200",
                    (owner_principal,),
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT * FROM experiments ORDER BY created_at DESC, experiment_id DESC LIMIT 200"
                ).fetchall()
        return {"experiments": [self._experiment_row(row) for row in rows]}

    def create_artifact(self, payload: object) -> dict[str, object]:
        data = self._artifact_payload(payload)
        request_hash = _hash_request(data)
        with self._lock, self._connection:
            task = self._connection.execute(
                "SELECT * FROM research_tasks WHERE task_id = ?", (data["task_id"],)
            ).fetchone()
            if task is None:
                raise ResearchNotFound("research task not found")
            experiment_id = data["experiment_id"]
            if experiment_id is not None:
                experiment = self._connection.execute(
                    "SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,)
                ).fetchone()
                if experiment is None or experiment["task_id"] != data["task_id"]:
                    raise ResearchNotFound("experiment does not belong to research task")
            lineage = [{"kind": "research_task", "id": data["task_id"]}]
            if experiment_id is not None:
                lineage.append({"kind": "experiment", "id": experiment_id})
            lineage.extend(data["lineage"])
            lineage, lineage_json = _lineage(lineage)
            data["lineage_json"] = lineage_json
            request_hash = _hash_request(data)
            existing = self._connection.execute(
                "SELECT * FROM artifacts WHERE task_id = ? AND idempotency_key = ?",
                (data["task_id"], data["idempotency_key"]),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict("artifact idempotency key was reused")
                return self._artifact_row(existing)

            now = _now()
            artifact_id = _new_id("artifact")
            self._connection.execute(
                """INSERT INTO artifacts
                (artifact_id, task_id, experiment_id, owner_principal, kind,
                 status, content, content_sha256, lineage, trace_id,
                 idempotency_key, request_hash, created_at, updated_at, version)
                VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    artifact_id,
                    data["task_id"],
                    experiment_id,
                    task["owner_principal"],
                    data["kind"],
                    data["content_json"],
                    data["content_sha256"],
                    lineage_json,
                    data["trace_id"],
                    data["idempotency_key"],
                    request_hash,
                    now,
                    now,
                ),
            )
            return self.get_artifact(artifact_id)

    def get_artifact(self, artifact_id: object) -> dict[str, object]:
        artifact_id = _identifier(artifact_id, field="artifact_id")
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
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
        with self._lock:
            row = self._connection.execute(
                """SELECT * FROM artifacts
                WHERE task_id = ? AND kind = ? AND content_sha256 = ?
                ORDER BY created_at ASC, artifact_id ASC LIMIT 1""",
                (task_id, kind, fingerprint),
            ).fetchone()
        return None if row is None else self._artifact_row(row)

    def list_artifacts(self, *, owner_principal: str | None = None) -> dict[str, object]:
        with self._lock:
            if owner_principal:
                rows = self._connection.execute(
                    "SELECT * FROM artifacts WHERE owner_principal = ? ORDER BY created_at DESC, artifact_id DESC LIMIT 200",
                    (owner_principal,),
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT * FROM artifacts ORDER BY created_at DESC, artifact_id DESC LIMIT 200"
                ).fetchall()
        return {"artifacts": [self._artifact_row(row) for row in rows]}

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
        with self._lock, self._connection:
            row = self._connection.execute(
                f"SELECT * FROM {table} WHERE {self._id_column(entity_type)} = ?",
                (entity_id,),
            ).fetchone()
            if row is None:
                raise ResearchNotFound(f"{entity_type} not found")
            existing = self._connection.execute(
                """SELECT * FROM research_transitions
                WHERE entity_type = ? AND entity_id = ? AND idempotency_key = ?""",
                (entity_type, entity_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict("transition idempotency key was reused")
                result = _loads(existing["result_json"], field="transition_result")
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
                self._connection.execute(
                    """INSERT INTO research_transitions
                    (entity_type, entity_id, idempotency_key, request_hash, target_status, result_json)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (entity_type, entity_id, idempotency_key, request_hash, target_status, _result_json(result)),
                )
                return result
            now = _now()
            self._connection.execute(
                f"UPDATE {table} SET status = ?, updated_at = ?, version = version + 1 WHERE {self._id_column(entity_type)} = ?",
                (target_status, now, entity_id),
            )
            updated = self._connection.execute(
                f"SELECT * FROM {table} WHERE {self._id_column(entity_type)} = ?",
                (entity_id,),
            ).fetchone()
            assert updated is not None
            result = row_mapper(updated)
            self._connection.execute(
                """INSERT INTO research_transitions
                (entity_type, entity_id, idempotency_key, request_hash, target_status, result_json)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    entity_type,
                    entity_id,
                    idempotency_key,
                    request_hash,
                    target_status,
                    _result_json(result),
                ),
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
        snapshot, snapshot_json = _snapshot(payload.get("input_snapshot"))
        return {
            "task_id": _identifier(payload.get("task_id"), field="task_id"),
            "name": _text(payload.get("name"), field="name", max_length=200),
            "input_snapshot": snapshot,
            "input_snapshot_json": snapshot_json,
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
        content, content_json = _canonical_json(
            _object(payload.get("content"), field="content"), field="content"
        )
        lineage, _ = _lineage(payload.get("lineage", []))
        return {
            "task_id": _identifier(payload.get("task_id"), field="task_id"),
            "experiment_id": (
                _identifier(payload["experiment_id"], field="experiment_id")
                if payload.get("experiment_id") is not None
                else None
            ),
            "kind": _text(payload.get("kind"), field="kind", max_length=64),
            "content": content,
            "content_json": content_json,
            "content_sha256": hashlib.sha256(content_json.encode("utf-8")).hexdigest(),
            "lineage": lineage,
            "trace_id": _trace_id(payload.get("trace_id")),
            "idempotency_key": _idempotency_key(payload.get("idempotency_key")),
        }

    @staticmethod
    def _task_row(row: sqlite3.Row) -> dict[str, object]:
        result = _row_dict(row)
        result.pop("idempotency_key", None)
        result.pop("request_hash", None)
        return result

    @staticmethod
    def _experiment_row(row: sqlite3.Row) -> dict[str, object]:
        result = _row_dict(row)
        result.pop("idempotency_key", None)
        result.pop("request_hash", None)
        result["input_snapshot"] = _loads(result.pop("input_snapshot"), field="input_snapshot")
        return result

    @staticmethod
    def _artifact_row(row: sqlite3.Row) -> dict[str, object]:
        result = _row_dict(row)
        result.pop("idempotency_key", None)
        result.pop("request_hash", None)
        result["content"] = _loads(result.pop("content"), field="content")
        result["lineage"] = _loads(result.pop("lineage"), field="lineage")
        return result
