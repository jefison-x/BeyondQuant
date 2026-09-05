"""BYQ-owned Phase 15 EngineeringTask contracts.

The Engineering Plane is separate from the Product Plane. This module records
auditable engineering tasks and their required evidence, but never performs
Git or GitHub mutations. Engineering DSH/Codex performs isolated work and
reports evidence through the Engineering Plane API.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, execute, fetch_one


MAX_JSON_BYTES = 32 * 1024
_ID_PATTERN = re.compile(r"^(?:engineering_task)_[0-9a-f]{32}$")
_TRACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_PRINCIPAL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")
_BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_DEFAULT_WORKTREE_ROOT = "/home/jefison/projects/.byq-worktrees"


def validate_worktree_path(value: str) -> str:
    """Validate declared host path, not host filesystem (never mounted in Backend)."""
    root = PurePosixPath(os.environ.get("BYQ_ENGINEERING_WORKTREE_ROOT", _DEFAULT_WORKTREE_ROOT))
    path = PurePosixPath(value)
    if (not root.is_absolute() or ".." in root.parts or len(root.parts) < 3
            or len(root.parts) == 3 and root.parts[1] == "home"
            or str(root) in {"/var/tmp", "/home/jefison", "/home/jefison/projects"}
            or root.name in {"BeyondQuant", "BeyondQuant-community", "BeyondQuant-legacy"}):
        raise ValueError("invalid dedicated BYQ worktree root configuration")
    if not path.is_absolute() or ".." in path.parts or path == root or not path.is_relative_to(root):
        raise ValueError("worktree_path must be under the BYQ disposable worktree root")
    return str(path)


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

ENGINEERING_TRANSITIONS = {
    "proposed": {"proposed", "approved", "rejected", "cancelled"},
    "approved": {"approved", "in_progress", "cancelled"},
    "in_progress": {"in_progress", "review_required", "cancelled"},
    "review_required": {"review_required", "completed", "rejected", "cancelled"},
    "completed": {"completed"},
    "rejected": {"rejected"},
    "cancelled": {"cancelled"},
}


class EngineeringError(RuntimeError):
    """Safe base class for Engineering Plane domain failures."""


class EngineeringNotFound(EngineeringError):
    pass


class EngineeringUnauthorized(EngineeringError):
    pass


class EngineeringForbidden(EngineeringError):
    pass


class EngineeringConflict(EngineeringError):
    pass


class EngineeringPersistenceError(EngineeringError):
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


def _principal(value: object, *, field: str) -> str:
    normalized = _text(value, field=field, max_length=128)
    if _PRINCIPAL_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field} is not a valid BYQ principal")
    return normalized


def _trace(value: object, *, field: str = "trace_id") -> str:
    normalized = _text(value, field=field, max_length=64)
    if _TRACE_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field} is not a valid BYQ identifier")
    return normalized


def _idempotency(value: object) -> str:
    return _text(value, field="idempotency_key", max_length=128)


def _task_id(value: object) -> str:
    normalized = _text(value, field="task_id", max_length=64)
    if normalized.startswith("engineering_task_") and re.fullmatch(
        r"engineering_task_[0-9a-f]{32}", normalized
    ):
        return normalized
    raise ValueError("task_id is not a valid BYQ engineering task identifier")


def _reject_unknown(payload: dict[str, object], allowed: set[str]) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(unknown)}")


def _reject_secret_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            if any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS):
                raise ValueError("engineering payload must not contain credential fields")
            _reject_secret_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_secret_keys(nested)


def _json_object(value: object, *, field: str) -> tuple[dict[str, object], str]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    _reject_secret_keys(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be JSON-serializable") from exc
    if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError(f"{field} exceeds {MAX_JSON_BYTES} bytes")
    return value, encoded


def _hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _loads(value: str, *, field: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise EngineeringPersistenceError(f"stored {field} is invalid") from exc


class EngineeringTaskStore(PgStoreMixin):
    """Durable BYQ store for isolated EngineeringTask records (ADR-0016 PG)."""

    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS engineering_tasks (
            task_id TEXT PRIMARY KEY,
            owner_principal TEXT NOT NULL,
            actor_principal TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            status TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            scope TEXT NOT NULL,
            worktree_path TEXT,
            branch_name TEXT,
            draft_pr_number INTEGER,
            ci_status TEXT,
            self_review BOOLEAN,
            architecture_evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            merge_status TEXT NOT NULL DEFAULT 'not_merged',
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            version INTEGER NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS engineering_tasks_idempotency
            ON engineering_tasks(owner_principal, idempotency_key)
        """,
        """
        CREATE TABLE IF NOT EXISTS engineering_history (
            history_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES engineering_tasks(task_id),
            from_status TEXT NOT NULL,
            to_status TEXT NOT NULL,
            actor_principal TEXT NOT NULL,
            decision TEXT NOT NULL,
            rationale TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS engineering_history_task
            ON engineering_history(task_id, created_at, history_id)
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as exc:
            raise EngineeringPersistenceError("engineering storage is unavailable") from exc

    @classmethod
    def from_env(cls) -> "EngineeringTaskStore":
        return cls()

    def create_task(
        self,
        payload: object,
        *,
        trusted_owner: str | None = None,
        trusted_actor: str | None = None,
    ) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("engineering task request must be an object")
        _reject_unknown(payload, {"title", "description", "scope", "trace_id", "idempotency_key"})
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        actor = _principal(trusted_actor, field="actor_principal") if trusted_actor else owner
        if owner is None or actor is None:
            raise EngineeringUnauthorized("engineering task requires trusted owner and actor")
        title = _text(payload.get("title"), field="title", max_length=200)
        description = _text(payload.get("description"), field="description", max_length=4000)
        scope = _text(payload.get("scope"), field="scope", max_length=2000)
        trace_id = _trace(payload.get("trace_id"), field="trace_id")
        key = _idempotency(payload.get("idempotency_key"))
        request = {
            "owner_principal": owner,
            "actor_principal": actor,
            "title": title,
            "description": description,
            "scope": scope,
            "trace_id": trace_id,
            "idempotency_key": key,
        }
        request_hash = _hash(request)
        with self._transaction() as connection:
            existing = fetch_one(
                connection,
                "SELECT * FROM engineering_tasks WHERE owner_principal = :owner AND idempotency_key = :key",
                {"owner": owner, "key": key},
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise EngineeringConflict("engineering task idempotency key was reused")
                return self._task_row(existing)
            now = _now()
            task_id = _new_id("engineering_task")
            execute(
                connection,
                """INSERT INTO engineering_tasks
                (task_id, owner_principal, actor_principal, trace_id, status,
                 title, description, scope, worktree_path, branch_name,
                 draft_pr_number, ci_status, self_review,
                 architecture_evidence_json, merge_status,
                 idempotency_key, request_hash, created_at, updated_at, version)
                VALUES (:task_id, :owner, :actor, :trace_id, 'proposed', :title, :description, :scope,
                        NULL, NULL, NULL, NULL, NULL, '{}', 'not_merged',
                        :key, :request_hash, :created_at, :updated_at, 1)""",
                {"task_id": task_id, "owner": owner, "actor": actor, "trace_id": trace_id,
                 "title": title, "description": description, "scope": scope,
                 "key": key, "request_hash": request_hash, "created_at": now, "updated_at": now},
            )
            row = fetch_one(connection, "SELECT * FROM engineering_tasks WHERE task_id = :task_id", {"task_id": task_id})
        assert row is not None
        return self._task_row(row)

    def get_task(self, task_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        task_id = _task_id(task_id)
        row = self._fetch_one("SELECT * FROM engineering_tasks WHERE task_id = :task_id", {"task_id": task_id})
        if row is None:
            raise EngineeringNotFound("engineering task not found")
        if trusted_owner and row["owner_principal"] != trusted_owner:
            raise EngineeringUnauthorized("engineering task is not owned by this principal")
        return self._task_with_history(row)

    def list_tasks(self, *, trusted_owner: str | None = None) -> dict[str, object]:
        if trusted_owner:
            rows = self._execute(
                "SELECT * FROM engineering_tasks WHERE owner_principal = :owner_principal ORDER BY created_at DESC, task_id DESC",
                {"owner_principal": trusted_owner},
            )
        else:
            rows = self._execute("SELECT * FROM engineering_tasks ORDER BY created_at DESC, task_id DESC")
        return {"tasks": [self._task_row(row) for row in rows]}

    def transition(
        self,
        payload: object,
        *,
        trusted_owner: str | None = None,
        trusted_actor: str | None = None,
    ) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("engineering transition request must be an object")
        _reject_unknown(payload, {"task_id", "target_status", "idempotency_key"})
        task_id = _task_id(payload.get("task_id"))
        target = _text(payload.get("target_status"), field="target_status", max_length=32)
        key = _idempotency(payload.get("idempotency_key"))
        with self._transaction() as connection:
            row = fetch_one(connection, "SELECT * FROM engineering_tasks WHERE task_id = :task_id", {"task_id": task_id})
            if row is None:
                raise EngineeringNotFound("engineering task not found")
            self._check_access(row, trusted_owner=trusted_owner, trusted_actor=trusted_actor)
            current = row["status"]
            if target not in ENGINEERING_TRANSITIONS[current]:
                raise EngineeringForbidden(f"cannot transition engineering task from {current} to {target}")
            self._enforce_transition_evidence(row, target)
            now = _now()
            if target != current:
                execute(
                    connection,
                    "UPDATE engineering_tasks SET status = :status, updated_at = :updated_at, version = version + 1 WHERE task_id = :task_id",
                    {"status": target, "updated_at": now, "task_id": task_id},
                )
                decision = target if target in {"approved", "rejected", "completed"} else "transition"
                self._record_history(connection, task_id, current, target, trusted_actor or row["actor_principal"], decision, "")
                row = fetch_one(connection, "SELECT * FROM engineering_tasks WHERE task_id = :task_id", {"task_id": task_id})
                assert row is not None
            return self._task_with_history(row)

    def report_evidence(
        self,
        payload: object,
        *,
        trusted_owner: str | None = None,
        trusted_actor: str | None = None,
    ) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("engineering evidence request must be an object")
        _reject_unknown(
            payload,
            {"task_id", "worktree_path", "branch_name", "draft_pr_number", "ci_status", "self_review", "architecture_evidence", "idempotency_key"},
        )
        task_id = _task_id(payload.get("task_id"))
        with self._transaction() as connection:
            row = fetch_one(connection, "SELECT * FROM engineering_tasks WHERE task_id = :task_id", {"task_id": task_id})
            if row is None:
                raise EngineeringNotFound("engineering task not found")
            self._check_access(row, trusted_owner=trusted_owner, trusted_actor=trusted_actor)

            worktree_path = row["worktree_path"]
            if "worktree_path" in payload:
                worktree_path = (
                    _text(payload["worktree_path"], field="worktree_path", max_length=512)
                    if payload["worktree_path"]
                    else None
                )
                if worktree_path is not None:
                    worktree_path = validate_worktree_path(worktree_path)

            branch_name = row["branch_name"]
            if "branch_name" in payload:
                branch_name = (
                    _text(payload["branch_name"], field="branch_name", max_length=128)
                    if payload["branch_name"]
                    else None
                )
                if branch_name is not None:
                    if _BRANCH_PATTERN.fullmatch(branch_name) is None:
                        raise ValueError("branch_name is not a valid BYQ branch name")
                    if branch_name in {"main", "master"}:
                        raise ValueError("engineering branch must not be main or master")

            draft_pr_number = row["draft_pr_number"]
            if "draft_pr_number" in payload:
                draft_pr_number = payload["draft_pr_number"]
                if draft_pr_number is not None and (
                    not isinstance(draft_pr_number, int)
                    or isinstance(draft_pr_number, bool)
                    or draft_pr_number < 1
                ):
                    raise ValueError("draft_pr_number must be a positive integer")

            ci_status = row["ci_status"]
            if "ci_status" in payload:
                ci_status = (
                    _text(payload["ci_status"], field="ci_status", max_length=16)
                    if payload["ci_status"]
                    else None
                )
                if ci_status is not None and ci_status not in {"pending", "success", "failure"}:
                    raise ValueError("ci_status must be pending, success, or failure")

            self_review = row["self_review"]
            if "self_review" in payload:
                self_review = payload["self_review"]
                if self_review is not None and not isinstance(self_review, bool):
                    raise ValueError("self_review must be a boolean")

            evidence_value = row["architecture_evidence_json"]
            if "architecture_evidence" in payload:
                evidence_value, _ = _json_object(payload.get("architecture_evidence", {}), field="architecture_evidence")

            now = _now()
            execute(
                connection,
                """UPDATE engineering_tasks
                SET worktree_path = :worktree_path, branch_name = :branch_name, draft_pr_number = :draft_pr_number,
                    ci_status = :ci_status, self_review = :self_review, architecture_evidence_json = :architecture_evidence_json,
                    updated_at = :updated_at, version = version + 1
                WHERE task_id = :task_id""",
                {"worktree_path": worktree_path, "branch_name": branch_name, "draft_pr_number": draft_pr_number,
                 "ci_status": ci_status, "self_review": self_review, "architecture_evidence_json": evidence_value,
                 "updated_at": now, "task_id": task_id},
            )
            updated = fetch_one(connection, "SELECT * FROM engineering_tasks WHERE task_id = :task_id", {"task_id": task_id})
        assert updated is not None
        return self._task_with_history(updated)

    def record_human_merge(
        self,
        payload: object,
        *,
        trusted_owner: str | None = None,
        trusted_actor: str | None = None,
    ) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("engineering merge record must be an object")
        _reject_unknown(payload, {"task_id", "decision", "rationale", "idempotency_key"})
        task_id = _task_id(payload.get("task_id"))
        reviewer = _principal(trusted_actor, field="reviewer_principal") if trusted_actor else None
        if reviewer is None:
            raise EngineeringUnauthorized("engineering merge record requires a trusted reviewer")
        decision = _text(payload.get("decision"), field="decision", max_length=16)
        if decision not in {"merged", "rejected"}:
            raise ValueError("decision must be merged or rejected")
        rationale = _text(payload.get("rationale") or "", field="rationale", max_length=2000) if payload.get("rationale") else ""
        key = _idempotency(payload.get("idempotency_key"))
        with self._transaction() as connection:
            row = fetch_one(connection, "SELECT * FROM engineering_tasks WHERE task_id = :task_id", {"task_id": task_id})
            if row is None:
                raise EngineeringNotFound("engineering task not found")
            if trusted_owner and row["owner_principal"] != trusted_owner:
                raise EngineeringUnauthorized("engineering task is not owned by this principal")
            if reviewer == row["actor_principal"]:
                raise EngineeringForbidden("the initiating actor cannot record their own human merge")
            if row["status"] != "completed":
                raise EngineeringForbidden("only a completed engineering task may record a human merge")
            if row["merge_status"] != "not_merged":
                return self._task_with_history(row)
            now = _now()
            execute(
                connection,
                "UPDATE engineering_tasks SET merge_status = :merge_status, updated_at = :updated_at, version = version + 1 WHERE task_id = :task_id",
                {"merge_status": decision, "updated_at": now, "task_id": task_id},
            )
            self._record_history(connection, task_id, "completed", "completed", reviewer, f"merge_{decision}", rationale)
            updated = fetch_one(connection, "SELECT * FROM engineering_tasks WHERE task_id = :task_id", {"task_id": task_id})
        assert updated is not None
        return self._task_with_history(updated)

    def _check_access(self, row: dict[str, Any], *, trusted_owner: str | None, trusted_actor: str | None) -> None:
        if trusted_owner and row["owner_principal"] != trusted_owner:
            raise EngineeringUnauthorized("engineering task is not owned by this principal")

    @staticmethod
    def _enforce_transition_evidence(row: dict[str, Any], target: str) -> None:
        if target == "in_progress" and row["status"] != "approved":
            raise EngineeringForbidden("only an approved engineering task may start work")
        if target == "review_required":
            if not row["worktree_path"] or not row["branch_name"]:
                raise EngineeringForbidden("review requires an isolated worktree path and non-main branch")
        if target == "completed":
            if not row["worktree_path"] or not row["branch_name"]:
                raise EngineeringForbidden("completion requires an isolated worktree path and non-main branch")
            if row["draft_pr_number"] is None:
                raise EngineeringForbidden("completion requires a draft PR number")
            if row["ci_status"] != "success":
                raise EngineeringForbidden("completion requires successful CI status")
            if row["self_review"] is not True:
                raise EngineeringForbidden("completion requires an explicit self-review")
            if not row["architecture_evidence_json"]:
                raise EngineeringForbidden("completion requires non-empty architecture evidence")
            if row["merge_status"] != "not_merged":
                raise EngineeringForbidden("completion requires an unmerged human merge state")

    def _record_history(
        self,
        connection: Any,
        task_id: str,
        from_status: str,
        to_status: str,
        actor: str,
        decision: str,
        rationale: str,
    ) -> None:
        history_id = _new_id("engineering_history")
        execute(
            connection,
            """INSERT INTO engineering_history
            (history_id, task_id, from_status, to_status, actor_principal, decision, rationale, created_at)
            VALUES (:history_id, :task_id, :from_status, :to_status, :actor_principal, :decision, :rationale, :created_at)""",
            {"history_id": history_id, "task_id": task_id, "from_status": from_status, "to_status": to_status,
             "actor_principal": actor, "decision": decision, "rationale": rationale, "created_at": _now()},
        )

    @staticmethod
    def _task_row(row: dict[str, Any]) -> dict[str, object]:
        result = dict(row)
        result.pop("idempotency_key", None)
        result.pop("request_hash", None)
        result["architecture_evidence"] = result.pop("architecture_evidence_json") or {}
        result["self_review"] = bool(result["self_review"]) if result["self_review"] is not None else None
        return result

    def _task_with_history(self, row: dict[str, Any]) -> dict[str, object]:
        task = self._task_row(row)
        rows = self._execute(
            """SELECT * FROM engineering_history
            WHERE task_id = :task_id ORDER BY created_at ASC, history_id ASC""",
            {"task_id": task["task_id"]},
        )
        task["history"] = [dict(item) for item in rows]
        return task
