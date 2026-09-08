"""BYQ task-scoped human permission ledger; no model dispatch capability."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from .db import execute, fetch_one


def _positive(value: object, name: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"invalid {name}")
    return value


def _request(payload: object) -> dict:
    required = {"idempotency_key", "token_limit", "confirmed_artifact_ids"}
    optional = {"max_turns", "valid_seconds", "turn_timeout_seconds"}
    if not isinstance(payload, dict) or not required <= payload.keys() or payload.keys() - required - optional:
        raise ValueError("invalid continuation permission fields")
    key = payload["idempotency_key"]
    if not isinstance(key, str) or not key.strip() or len(key) > 128:
        raise ValueError("invalid continuation idempotency key")
    artifacts = payload["confirmed_artifact_ids"]
    if (not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 16
            or any(not isinstance(item, str) or len(item) > 64 for item in artifacts)
            or len(set(artifacts)) != len(artifacts)):
        raise ValueError("explicit artifact confirmation required")
    return {"idempotency_key": key, "confirmed_artifact_ids": sorted(artifacts),
            "token_limit": _positive(payload["token_limit"], "token limit", 2**53 - 1),
            "max_turns": _positive(payload.get("max_turns", 8), "turn limit", 8),
            "valid_seconds": _positive(payload.get("valid_seconds", 86400), "validity", 86400),
            "turn_timeout_seconds": _positive(payload.get("turn_timeout_seconds", 900), "turn timeout", 900)}


class ResearchContinuationMixin:
    """Stored on the original task row, serialized with task transitions.

    First version permits one immutable grant per task. It intentionally cannot
    renew a grant, settle spend or admit an execution until enforcement qualifies.
    """

    @staticmethod
    def _continuation_task(connection, task_id: str, context: dict, *, human: bool):
        owner, workspace = context.get("owner_principal"), context.get("workspace_id")
        if not owner or not workspace or (human and context.get("actor_principal") != owner):
            raise ValueError("continuation requires its authenticated human owner")
        identity = fetch_one(connection, """SELECT u.user_id FROM users u
            JOIN workspaces w ON w.owner_user_id = u.user_id
            JOIN workspace_memberships m ON m.workspace_id = w.workspace_id AND m.user_id = u.user_id
            WHERE u.username = :owner AND w.workspace_id = :workspace
              AND u.status = 'active' AND w.status = 'active' AND m.status = 'active' AND m.role = 'owner'
            FOR SHARE OF u, w, m""", {"owner": owner, "workspace": workspace})
        if identity is None:
            raise ValueError("continuation owner is unavailable")
        # Lock conversation before task, matching research task creation.
        conversation = fetch_one(connection, """SELECT c.* FROM product_conversations c
            JOIN research_tasks t ON t.conversation_id = c.conversation_id
            WHERE t.task_id = :task AND t.owner_principal = :owner AND t.workspace_id = :workspace
              AND c.owner_principal = :owner AND c.workspace_id = :workspace
            FOR SHARE OF c""", {"task": task_id, "owner": owner, "workspace": workspace})
        if conversation is None:
            raise ValueError("continuation requires the original bound conversation")
        task = fetch_one(connection, """SELECT * FROM research_tasks WHERE task_id = :task
            AND owner_principal = :owner AND workspace_id = :workspace FOR UPDATE""",
            {"task": task_id, "owner": owner, "workspace": workspace})
        if task is None or task["conversation_id"] != conversation["conversation_id"]:
            raise ValueError("continuation task binding changed")
        return task, conversation

    @staticmethod
    def _continuation_view(task, conversation):
        ledger = task.get("continuation_permission")
        if ledger is None:
            return {"schema_version": "task-continuation-permission.v1", "task_id": task["task_id"],
                    "permission": None, "can_start": False, "blocked_reason": "permission_missing"}
        public = {key: value for key, value in ledger.items() if key not in {"idempotency_key", "request_sha256"}}
        now = datetime.now(timezone.utc)
        reason = "budget_enforcement_unqualified"
        if ledger["revoked_at"] is not None:
            reason = "permission_revoked"
        elif task["status"] in {"completed", "cancelled", "failed"}:
            reason = "task_terminal"
        elif conversation["status"] != "active":
            reason = "conversation_inactive"
        elif datetime.fromisoformat(ledger["expires_at"]) <= now:
            reason = "permission_expired"
        return {"schema_version": "task-continuation-permission.v1", "task_id": task["task_id"],
                "permission": public, "can_start": False, "blocked_reason": reason}

    def create_continuation_permission(self, task_id: str, payload: object, *, trusted_context: dict) -> dict:
        from .research import IdempotencyConflict

        request = _request(payload)
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self._transaction() as connection:
            task, conversation = self._continuation_task(connection, task_id, trusted_context, human=True)
            existing = task.get("continuation_permission")
            if existing is not None:
                if existing["idempotency_key"] != request["idempotency_key"] or existing["request_sha256"] != digest:
                    raise IdempotencyConflict("continuation permission cannot be replaced or replenished")
                return self._continuation_view(task, conversation)
            if task["status"] not in {"planned", "running"} or conversation["status"] != "active":
                raise ValueError("continuation task or conversation is inactive")
            confirmed_artifacts = []
            for artifact_id in request["confirmed_artifact_ids"]:
                artifact = fetch_one(connection, """SELECT artifact_id, content_sha256 FROM artifacts
                    WHERE artifact_id = :artifact AND task_id = :task AND owner_principal = :owner
                      AND workspace_id = :workspace AND status = 'validated' FOR SHARE""",
                    {"artifact": artifact_id, "task": task_id, "owner": task["owner_principal"],
                     "workspace": task["workspace_id"]})
                if artifact is None:
                    raise ValueError("confirmed artifact must be validated and belong to the exact task")
                confirmed_artifacts.append(artifact)
            now = datetime.now(timezone.utc)
            ledger = {**request, "request_sha256": digest, "grant_version": 1,
                      "confirmed_artifacts": confirmed_artifacts,
                      "owner_principal": task["owner_principal"], "workspace_id": task["workspace_id"],
                      "conversation_id": task["conversation_id"], "confirmed_by": trusted_context["actor_principal"],
                      "created_at": now.isoformat(), "expires_at": (now + timedelta(seconds=request["valid_seconds"])).isoformat(),
                      "revoked_at": None, "revoked_by": None}
            execute(connection, """UPDATE research_tasks SET continuation_permission = :ledger
                WHERE task_id = :task""", {"ledger": ledger, "task": task_id})
            task["continuation_permission"] = ledger
            return self._continuation_view(task, conversation)

    def get_continuation_permission(self, task_id: str, *, trusted_context: dict) -> dict:
        with self._transaction() as connection:
            task, conversation = self._continuation_task(connection, task_id, trusted_context, human=True)
            return self._continuation_view(task, conversation)

    def revoke_continuation_permission(self, task_id: str, *, grant_version: int, trusted_context: dict) -> dict:
        _positive(grant_version, "grant version", 2**53 - 1)
        with self._transaction() as connection:
            task, conversation = self._continuation_task(connection, task_id, trusted_context, human=True)
            ledger = task.get("continuation_permission")
            if ledger is None or ledger["grant_version"] != grant_version:
                raise ValueError("exact continuation grant version required")
            if ledger["revoked_at"] is None:
                ledger = {**ledger, "revoked_at": datetime.now(timezone.utc).isoformat(),
                          "revoked_by": trusted_context["actor_principal"]}
                execute(connection, "UPDATE research_tasks SET continuation_permission = :ledger WHERE task_id = :task",
                        {"ledger": ledger, "task": task_id})
                task["continuation_permission"] = ledger
            return self._continuation_view(task, conversation)
