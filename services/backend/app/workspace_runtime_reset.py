"""Workspace-scoped fence and proof boundary for runtime reset."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from .conversation_catalog import ConversationCatalogStore
from .db import PgStoreMixin, execute, fetch_one, transaction
from .workspace_reset import WorkspaceResetBlocked, WorkspaceResetStore


MAX_RESET_SESSIONS = 1000
_RESET_ID = re.compile(r"^[0-9a-f]{32}$")
_RUNTIME_WRITER_GATE = "runtime-authority:agent-writers"


class WorkspaceRuntimeResetError(RuntimeError):
    """Safe base error for the private Workspace runtime reset API."""


class WorkspaceRuntimeResetNotFound(WorkspaceRuntimeResetError):
    """The exact owner and personal Workspace binding was not found."""


class WorkspaceRuntimeResetConflict(WorkspaceRuntimeResetError):
    """The reset state or Gateway release proof does not match."""


class WorkspaceRuntimeResetPersistenceError(WorkspaceRuntimeResetError):
    """Runtime reset state could not be read or committed safely."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _identity(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"{field} is invalid")
    return value


def _reset_id(value: object) -> str:
    if not isinstance(value, str) or _RESET_ID.fullmatch(value) is None:
        raise ValueError("reset_id must be 32 lowercase hexadecimal characters")
    return value


def _workspace_reset_request_key(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Idempotency-Key must be an RFC 4122 UUID")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError("Idempotency-Key must be an RFC 4122 UUID") from error
    if parsed.variant != uuid.RFC_4122 or str(parsed) != value.lower():
        raise ValueError("Idempotency-Key must be an RFC 4122 UUID")
    return str(parsed)


def _normalized_scope(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_RESET_SESSIONS:
        raise WorkspaceRuntimeResetPersistenceError("stored reset session scope is invalid")
    result: list[dict[str, str]] = []
    seen_conversations: set[str] = set()
    seen_sessions: set[str] = set()
    seen_traces: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"conversation_id", "session_id", "trace_id"}:
            raise WorkspaceRuntimeResetPersistenceError("stored reset session scope is invalid")
        conversation_id = _identity(item["conversation_id"], "conversation_id")
        session_id = _identity(item["session_id"], "session_id")
        trace_id = _identity(item["trace_id"], "trace_id")
        if (conversation_id in seen_conversations or session_id in seen_sessions or trace_id in seen_traces):
            raise WorkspaceRuntimeResetPersistenceError("stored reset session scope contains duplicates")
        seen_conversations.add(conversation_id)
        seen_sessions.add(session_id)
        seen_traces.add(trace_id)
        result.append({"conversation_id": conversation_id, "session_id": session_id, "trace_id": trace_id})
    if result != sorted(result, key=lambda row: row["conversation_id"]):
        raise WorkspaceRuntimeResetPersistenceError("stored reset session scope is not canonical")
    return result


class WorkspaceRuntimeResetStore(PgStoreMixin):
    """Fence one Workspace, then finalize only after Gateway releases its scope."""

    SCHEMA_DDL: list[str] = []

    def __init__(self, database_url: str | None = None) -> None:
        super().__init__(database_url)
        self.runtime_authority_guard_engine = create_engine(
            self.database_url,
            pool_size=8,
            max_overflow=0,
            pool_timeout=0.25,
            pool_pre_ping=True,
            future=True,
        )

    def close(self) -> None:
        self.runtime_authority_guard_engine.dispose()
        super().close()

    def _writer_gate(self):
        return transaction(self.runtime_authority_guard_engine)

    @staticmethod
    def _advisory_lock(connection, key: str) -> None:
        execute(connection, "SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))", {"key": key})

    @staticmethod
    def _workspace(connection, *, owner: str, workspace: str):
        return fetch_one(connection, """SELECT w.*, u.status AS user_status,
                m.status AS membership_status
            FROM workspaces w
            JOIN users u ON u.user_id=w.owner_user_id
            JOIN workspace_memberships m ON m.workspace_id=w.workspace_id AND m.user_id=u.user_id
            WHERE w.workspace_id=:workspace AND u.username=:owner AND w.owner_user_id=u.user_id
              AND w.kind='personal' AND m.role='owner'
            FOR UPDATE OF w""", {"owner": owner, "workspace": workspace})

    @staticmethod
    def _require_schema(connection) -> None:
        columns = execute(connection, """SELECT column_name FROM information_schema.columns
            WHERE table_schema=current_schema() AND table_name='workspaces'""")
        available = {row["column_name"] for row in columns}
        required = {
            "reset_id", "reset_kind", "reset_request_key", "reset_sessions_json", "last_reset_id",
            "last_reset_receipt_json", "last_reset_released_sessions_json",
        }
        if not required.issubset(available):
            raise WorkspaceRuntimeResetPersistenceError("Workspace runtime reset schema is unavailable")

    @staticmethod
    def _require_workspace_reset_receipts(connection) -> None:
        if execute(connection, "SELECT to_regclass('workspace_reset_receipts') AS table_name")[0]["table_name"] is None:
            raise WorkspaceRuntimeResetPersistenceError("Workspace reset idempotency schema is unavailable")

    @staticmethod
    def _assert_live_identity(row: dict[str, Any] | None) -> dict[str, Any]:
        if row is None:
            raise WorkspaceRuntimeResetNotFound("exact active personal Workspace owner binding is required")
        if row["user_status"] != "active" or row["membership_status"] != "active":
            raise WorkspaceRuntimeResetNotFound("exact active personal Workspace owner binding is required")
        return row

    @staticmethod
    def _begin_receipt(workspace_id: str, reset_id: str, sessions: list[dict[str, str]]) -> dict[str, object]:
        return {
            "schema_version": "workspace-runtime-reset-begin.v1",
            "workspace_id": workspace_id,
            "reset_id": reset_id,
            "sessions": sessions,
        }

    def begin(self, *, owner_principal: object, workspace_id: object) -> dict[str, object]:
        owner = _identity(owner_principal, "owner_principal")
        workspace = _identity(workspace_id, "workspace_id")
        try:
            # Match Product Agent admission's exclusive transaction lock. This
            # drains in-flight requests before the workspace row is disabled.
            with self._writer_gate() as gate_connection:
                self._advisory_lock(gate_connection, _RUNTIME_WRITER_GATE)
                with self._lock, self.engine.begin() as connection:
                    execute(connection, "SET LOCAL lock_timeout = '5s'")
                    self._advisory_lock(connection, "runtime-authority:current")
                    self._require_schema(connection)
                    row = self._assert_live_identity(self._workspace(
                        connection, owner=owner, workspace=workspace))
                    if (row["status"] == "disabled" and row.get("reset_id")
                            and row.get("reset_kind") in (None, "runtime")):
                        reset_id = _reset_id(row["reset_id"])
                        sessions = _normalized_scope(row.get("reset_sessions_json"))
                        return self._begin_receipt(workspace, reset_id, sessions)
                    if row["status"] != "active" or row.get("reset_id") is not None:
                        raise WorkspaceRuntimeResetConflict("Workspace is not available for runtime reset")

                    sessions = ConversationCatalogStore.workspace_reset_sessions(
                        connection, owner=owner, workspace=workspace,
                        limit=MAX_RESET_SESSIONS + 1,
                    )
                    if len(sessions) > MAX_RESET_SESSIONS:
                        raise WorkspaceRuntimeResetConflict("Workspace runtime session scope exceeds its bound")
                    sessions = _normalized_scope(sessions)
                    session_trace_pairs = {(item["session_id"], item["trace_id"]) for item in sessions}
                    active_roots = execute(connection, """SELECT root_run_id, session_id, trace_id
                        FROM agent_runtime_turns
                        WHERE owner_principal=:owner AND workspace_id=:workspace
                          AND status='active' AND authority_status IN ('active','authority_revoked_unconfirmed')
                        ORDER BY root_run_id""", {"owner": owner, "workspace": workspace})
                    active_runs = execute(connection, """SELECT run_id, session_id, trace_id,
                            runtime_registration_fingerprint
                        FROM agent_runs
                        WHERE owner_principal=:owner AND workspace_id=:workspace
                          AND status IN ('active','pending_binding')
                          AND authority_status IN ('active','authority_revoked_unconfirmed')
                        ORDER BY run_id""", {"owner": owner, "workspace": workspace})
                    if any((root["session_id"], root["trace_id"]) not in session_trace_pairs for root in active_roots):
                        raise WorkspaceRuntimeResetConflict("active Agent root has no exact Product conversation session")
                    if any((run["session_id"], run["trace_id"]) not in session_trace_pairs for run in active_runs):
                        raise WorkspaceRuntimeResetConflict("active Agent run has no exact Product conversation session")

                    for root in active_roots:
                        self._advisory_lock(connection, "root:" + root["root_run_id"])
                    fingerprints = execute(connection, """SELECT DISTINCT registration_fingerprint
                        FROM agent_runtime_registrations
                        WHERE root_run_id IN (
                            SELECT root_run_id FROM agent_runtime_turns
                            WHERE owner_principal=:owner AND workspace_id=:workspace AND status='active'
                        ) ORDER BY registration_fingerprint""", {"owner": owner, "workspace": workspace})
                    for registration in fingerprints:
                        self._advisory_lock(connection, "registration:" + registration["registration_fingerprint"])
                    for run in active_runs:
                        fingerprint = run.get("runtime_registration_fingerprint")
                        if fingerprint:
                            self._advisory_lock(connection, "registration:" + fingerprint)

                    reset_id = uuid.uuid4().hex
                    now = _now()
                    execute(connection, """UPDATE agent_runtime_turns
                        SET authority_status='authority_revoked_unconfirmed', updated_at=:now
                        WHERE owner_principal=:owner AND workspace_id=:workspace
                          AND status='active' AND authority_status='active'""",
                        {"owner": owner, "workspace": workspace, "now": now})
                    execute(connection, """UPDATE agent_runs
                        SET authority_status='authority_revoked_unconfirmed', updated_at=:now,
                            version=version+1
                        WHERE owner_principal=:owner AND workspace_id=:workspace
                          AND status IN ('active','pending_binding') AND authority_status='active'""",
                        {"owner": owner, "workspace": workspace, "now": now})
                    execute(connection, """UPDATE workspaces
                        SET status='disabled', reset_id=:reset_id, reset_kind='runtime',
                            reset_request_key=NULL,
                            reset_sessions_json=CAST(:sessions AS jsonb),
                            last_reset_id=NULL, last_reset_receipt_json=NULL,
                            last_reset_released_sessions_json=NULL, updated_at=:now
                        WHERE workspace_id=:workspace""",
                        {"reset_id": reset_id, "sessions": sessions, "now": now,
                         "workspace": workspace})
                    return self._begin_receipt(workspace, reset_id, sessions)
        except (WorkspaceRuntimeResetNotFound, WorkspaceRuntimeResetConflict):
            raise
        except SQLAlchemyError as error:
            raise WorkspaceRuntimeResetPersistenceError("Workspace runtime reset could not be started safely") from error

    def finalize(self, *, owner_principal: object, workspace_id: object, reset_id: object,
                 released_sessions: object) -> dict[str, object]:
        owner = _identity(owner_principal, "owner_principal")
        workspace = _identity(workspace_id, "workspace_id")
        requested_reset_id = _reset_id(reset_id)
        if not isinstance(released_sessions, list) or len(released_sessions) > MAX_RESET_SESSIONS:
            raise ValueError("released_sessions must be a bounded array")
        supplied_sessions = [_identity(value, "released session id") for value in released_sessions]
        if len(set(supplied_sessions)) != len(supplied_sessions):
            raise ValueError("released_sessions must not contain duplicates")
        supplied_sessions = sorted(supplied_sessions)
        try:
            with self._writer_gate() as gate_connection:
                self._advisory_lock(gate_connection, _RUNTIME_WRITER_GATE)
                with self._lock, self.engine.begin() as connection:
                    execute(connection, "SET LOCAL lock_timeout = '5s'")
                    self._advisory_lock(connection, "runtime-authority:current")
                    self._require_schema(connection)
                    row = self._assert_live_identity(self._workspace(
                        connection, owner=owner, workspace=workspace))
                    if row["status"] == "active" and row.get("last_reset_id") == requested_reset_id:
                        prior_released = row.get("last_reset_released_sessions_json")
                        receipt = row.get("last_reset_receipt_json")
                        if (not isinstance(prior_released, list)
                                or sorted(prior_released) != supplied_sessions
                                or not isinstance(receipt, dict)):
                            raise WorkspaceRuntimeResetConflict("finalize retry does not match its exact proof")
                        return receipt
                    if (row["status"] != "disabled" or row.get("reset_id") != requested_reset_id
                            or row.get("reset_kind") not in (None, "runtime")
                            or row.get("reset_sessions_json") is None):
                        raise WorkspaceRuntimeResetConflict("reset_id does not name the pending Workspace reset")
                    sessions = _normalized_scope(row["reset_sessions_json"])
                    expected_sessions = sorted(item["session_id"] for item in sessions)
                    if supplied_sessions != expected_sessions:
                        raise WorkspaceRuntimeResetConflict("Gateway release proof does not match the exact reset scope")

                    now = _now()
                    # Revoke status is a BYQ interruption fact only. External
                    # claims, approvals, and outcomes remain untouched.
                    execute(connection, """UPDATE agent_runtime_turns
                        SET status='interrupted', authority_status='closed', updated_at=:now,
                            terminal_sequence=NULL, terminal_event_sha256=NULL
                        WHERE owner_principal=:owner AND workspace_id=:workspace
                          AND status='active' AND authority_status='authority_revoked_unconfirmed'""",
                        {"owner": owner, "workspace": workspace, "now": now})
                    execute(connection, """UPDATE agent_runs
                        SET status='interrupted', authority_status='closed', updated_at=:now,
                            version=version+1
                        WHERE owner_principal=:owner AND workspace_id=:workspace
                          AND status IN ('active','pending_binding')
                          AND authority_status='authority_revoked_unconfirmed'""",
                        {"owner": owner, "workspace": workspace, "now": now})
                    archived_ids = ConversationCatalogStore.archive_workspace_reset_sessions(
                        connection, owner=owner, workspace=workspace,
                        sessions=sessions, now=now,
                    )
                    expected_conversations = [item["conversation_id"] for item in sessions]
                    if archived_ids != expected_conversations:
                        raise WorkspaceRuntimeResetConflict("conversation scope changed before reset finalization")
                    receipt: dict[str, object] = {
                        "schema_version": "workspace-runtime-reset-finalize.v1",
                        "workspace_id": workspace,
                        "reset_id": requested_reset_id,
                        "status": "finalized",
                        "archived_conversation_ids": archived_ids,
                    }
                    execute(connection, """UPDATE workspaces
                        SET status='active', reset_id=NULL, reset_kind=NULL,
                            reset_request_key=NULL, reset_sessions_json=NULL,
                            last_reset_id=:reset_id, last_reset_receipt_json=CAST(:receipt AS jsonb),
                            last_reset_released_sessions_json=CAST(:released_sessions AS jsonb),
                            updated_at=:now
                        WHERE workspace_id=:workspace AND status='disabled' AND reset_id=:reset_id""",
                        {"reset_id": requested_reset_id, "receipt": receipt,
                         "released_sessions": supplied_sessions, "now": now,
                         "workspace": workspace})
                    return receipt
        except (WorkspaceRuntimeResetNotFound, WorkspaceRuntimeResetConflict):
            raise
        except SQLAlchemyError as error:
            raise WorkspaceRuntimeResetPersistenceError("Workspace runtime reset could not be finalized safely") from error

    @staticmethod
    def _workspace_reset_begin_receipt(
        workspace_id: str, reset_id: str, sessions: list[dict[str, str]],
    ) -> dict[str, object]:
        return {"schema_version": "workspace-reset-begin.v1", "workspace_id": workspace_id,
                "reset_id": reset_id, "status": "pending", "sessions": sessions}

    @staticmethod
    def _workspace_reset_completed_receipt(
        workspace_id: str, receipt: dict[str, object],
    ) -> dict[str, object]:
        return {"schema_version": "workspace-reset-begin.v1", "workspace_id": workspace_id,
                "status": "completed", "receipt": receipt}

    @staticmethod
    def _save_workspace_reset_receipt(
        connection, *, workspace: str, request_key: str, reset_id: str,
        receipt: dict[str, object], released_sessions: list[str], now: datetime,
    ) -> None:
        execute(connection, """INSERT INTO workspace_reset_receipts
            (workspace_id,request_key,reset_id,receipt_json,released_sessions_json,created_at)
            VALUES (:workspace,:request_key,:reset_id,CAST(:receipt AS jsonb),
                    CAST(:released_sessions AS jsonb),:now)""",
            {"workspace": workspace, "request_key": request_key, "reset_id": reset_id,
             "receipt": receipt, "released_sessions": released_sessions, "now": now})

    def begin_workspace_reset(
        self, *, owner_principal: object, workspace_id: object, idempotency_key: object,
    ) -> dict[str, object]:
        """Preflight, revoke live Agent roots, and fence one exact Workspace."""
        owner = _identity(owner_principal, "owner_principal")
        workspace = _identity(workspace_id, "workspace_id")
        request_key = _workspace_reset_request_key(idempotency_key)
        try:
            with self._writer_gate() as gate_connection:
                self._advisory_lock(gate_connection, _RUNTIME_WRITER_GATE)
                with self._lock, self.engine.begin() as connection:
                    execute(connection, "SET LOCAL lock_timeout = '5s'")
                    execute(connection, "SET LOCAL statement_timeout = '120s'")
                    self._advisory_lock(connection, "runtime-authority:current")
                    self._advisory_lock(connection, f"workspace-reset|{workspace}")
                    self._require_schema(connection)
                    self._require_workspace_reset_receipts(connection)
                    row = self._assert_live_identity(self._workspace(
                        connection, owner=owner, workspace=workspace))
                    prior = fetch_one(connection, """SELECT receipt_json FROM workspace_reset_receipts
                        WHERE workspace_id=:workspace AND request_key=:request_key""",
                        {"workspace": workspace, "request_key": request_key})
                    if prior is not None:
                        receipt = prior.get("receipt_json")
                        if not isinstance(receipt, dict):
                            raise WorkspaceRuntimeResetPersistenceError("stored Workspace reset receipt is invalid")
                        return self._workspace_reset_completed_receipt(workspace, receipt)
                    if (row["status"] == "disabled" and row.get("reset_kind") == "workspace"
                            and row.get("reset_request_key") == request_key and row.get("reset_id")):
                        return self._workspace_reset_begin_receipt(
                            workspace, _reset_id(row["reset_id"]),
                            _normalized_scope(row.get("reset_sessions_json")))
                    if row["status"] != "active" or row.get("reset_id") is not None:
                        raise WorkspaceRuntimeResetConflict("Workspace is not available for reset")

                    # Existing reset classification runs before the fence; only
                    # active Agent roots/runs are revoked by this operation.
                    WorkspaceResetStore.preflight_in_connection(
                        connection, owner_principal=owner, workspace_id=workspace,
                        expected_status="active", allow_active_agent_roots=True)
                    sessions = ConversationCatalogStore.workspace_reset_sessions(
                        connection, owner=owner, workspace=workspace,
                        limit=MAX_RESET_SESSIONS + 1)
                    if len(sessions) > MAX_RESET_SESSIONS:
                        raise WorkspaceRuntimeResetConflict("Workspace reset session scope exceeds its bound")
                    sessions = _normalized_scope(sessions)
                    exact_pairs = {(item["session_id"], item["trace_id"]) for item in sessions}
                    roots = execute(connection, """SELECT root_run_id,session_id,trace_id
                        FROM agent_runtime_turns WHERE owner_principal=:owner AND workspace_id=:workspace
                          AND status='active' AND authority_status IN ('active','authority_revoked_unconfirmed')
                        ORDER BY root_run_id""", {"owner": owner, "workspace": workspace})
                    runs = execute(connection, """SELECT run_id,session_id,trace_id,runtime_registration_fingerprint
                        FROM agent_runs WHERE owner_principal=:owner AND workspace_id=:workspace
                          AND status IN ('active','pending_binding')
                          AND authority_status IN ('active','authority_revoked_unconfirmed')
                        ORDER BY run_id""", {"owner": owner, "workspace": workspace})
                    if any((item["session_id"], item["trace_id"]) not in exact_pairs for item in roots + runs):
                        raise WorkspaceRuntimeResetConflict(
                            "active Agent authority has no exact Product conversation session")
                    for root in roots:
                        self._advisory_lock(connection, "root:" + root["root_run_id"])
                    registrations = execute(connection, """SELECT DISTINCT registration_fingerprint
                        FROM agent_runtime_registrations WHERE root_run_id IN (
                            SELECT root_run_id FROM agent_runtime_turns
                            WHERE owner_principal=:owner AND workspace_id=:workspace AND status='active'
                        ) ORDER BY registration_fingerprint""", {"owner": owner, "workspace": workspace})
                    for item in registrations:
                        self._advisory_lock(connection, "registration:" + item["registration_fingerprint"])
                    for run in runs:
                        if run.get("runtime_registration_fingerprint"):
                            self._advisory_lock(connection, "registration:" + run["runtime_registration_fingerprint"])

                    reset_id = uuid.uuid4().hex
                    now = _now()
                    execute(connection, """UPDATE agent_runtime_turns
                        SET authority_status='authority_revoked_unconfirmed',updated_at=:now
                        WHERE owner_principal=:owner AND workspace_id=:workspace
                          AND status='active' AND authority_status='active'""",
                        {"owner": owner, "workspace": workspace, "now": now})
                    execute(connection, """UPDATE agent_runs
                        SET authority_status='authority_revoked_unconfirmed',updated_at=:now,version=version+1
                        WHERE owner_principal=:owner AND workspace_id=:workspace
                          AND status IN ('active','pending_binding') AND authority_status='active'""",
                        {"owner": owner, "workspace": workspace, "now": now})
                    execute(connection, """UPDATE workspaces
                        SET status='disabled',reset_id=:reset_id,reset_kind='workspace',
                            reset_request_key=:request_key,reset_sessions_json=CAST(:sessions AS jsonb),updated_at=:now
                        WHERE workspace_id=:workspace AND status='active'""",
                        {"reset_id": reset_id, "request_key": request_key, "sessions": sessions,
                         "now": now, "workspace": workspace})
                    return self._workspace_reset_begin_receipt(workspace, reset_id, sessions)
        except (WorkspaceRuntimeResetNotFound, WorkspaceRuntimeResetConflict,
                WorkspaceRuntimeResetPersistenceError):
            raise
        except WorkspaceResetBlocked as error:
            raise WorkspaceRuntimeResetConflict(str(error)) from error
        except SQLAlchemyError as error:
            raise WorkspaceRuntimeResetPersistenceError("Workspace reset could not be started safely") from error

    @staticmethod
    def _workspace_reset_finalize_envelope(
        workspace: str, reset_id: str, receipt: dict[str, object],
    ) -> dict[str, object]:
        return {"schema_version": "workspace-reset-finalize.v1", "workspace_id": workspace,
                "reset_id": reset_id, **receipt}

    def finalize_workspace_reset(
        self, *, owner_principal: object, workspace_id: object, reset_id: object,
        idempotency_key: object, released_sessions: object,
    ) -> dict[str, object]:
        """Delete the classified graph atomically after exact session release."""
        owner = _identity(owner_principal, "owner_principal")
        workspace = _identity(workspace_id, "workspace_id")
        requested_reset_id = _reset_id(reset_id)
        request_key = _workspace_reset_request_key(idempotency_key)
        if not isinstance(released_sessions, list) or len(released_sessions) > MAX_RESET_SESSIONS:
            raise ValueError("released_sessions must be a bounded array")
        supplied = [_identity(value, "released session id") for value in released_sessions]
        if len(set(supplied)) != len(supplied):
            raise ValueError("released_sessions must not contain duplicates")
        supplied = sorted(supplied)
        try:
            with self._writer_gate() as gate_connection:
                self._advisory_lock(gate_connection, _RUNTIME_WRITER_GATE)
                with self._lock, self.engine.begin() as connection:
                    execute(connection, "SET LOCAL lock_timeout = '5s'")
                    execute(connection, "SET LOCAL statement_timeout = '120s'")
                    self._advisory_lock(connection, "runtime-authority:current")
                    self._advisory_lock(connection, f"workspace-reset|{workspace}")
                    self._require_schema(connection)
                    self._require_workspace_reset_receipts(connection)
                    row = self._assert_live_identity(self._workspace(
                        connection, owner=owner, workspace=workspace))
                    prior = fetch_one(connection, """SELECT reset_id,receipt_json,released_sessions_json
                        FROM workspace_reset_receipts WHERE workspace_id=:workspace
                          AND request_key=:request_key""",
                        {"workspace": workspace, "request_key": request_key})
                    if prior is not None:
                        if (prior.get("reset_id") != requested_reset_id
                                or sorted(prior.get("released_sessions_json") or []) != supplied
                                or not isinstance(prior.get("receipt_json"), dict)):
                            raise WorkspaceRuntimeResetConflict("finalize retry does not match its exact proof")
                        return self._workspace_reset_finalize_envelope(
                            workspace, requested_reset_id, prior["receipt_json"])
                    if (row["status"] != "disabled" or row.get("reset_id") != requested_reset_id
                            or row.get("reset_kind") != "workspace"
                            or row.get("reset_request_key") != request_key
                            or row.get("reset_sessions_json") is None):
                        raise WorkspaceRuntimeResetConflict("reset_id does not name the pending Workspace reset")
                    sessions = _normalized_scope(row["reset_sessions_json"])
                    if supplied != sorted(item["session_id"] for item in sessions):
                        raise WorkspaceRuntimeResetConflict(
                            "Gateway release proof does not match the exact reset scope")

                    now = _now()
                    execute(connection, """UPDATE agent_runtime_turns AS r
                        SET status='interrupted',authority_status='closed',updated_at=:now,
                            terminal_sequence=NULL,terminal_event_sha256=NULL
                        WHERE r.owner_principal=:owner AND r.workspace_id=:workspace
                          AND r.status='active' AND r.authority_status='authority_revoked_unconfirmed'
                          AND EXISTS (SELECT 1 FROM jsonb_array_elements(
                            (SELECT reset_sessions_json FROM workspaces WHERE workspace_id=:workspace)
                          ) AS reset_session(value) WHERE reset_session.value->>'session_id'=r.session_id
                            AND reset_session.value->>'trace_id'=r.trace_id)""",
                        {"owner": owner, "workspace": workspace, "now": now})
                    execute(connection, """UPDATE agent_runs AS r
                        SET status='interrupted',authority_status='closed',updated_at=:now,version=version+1
                        WHERE r.owner_principal=:owner AND r.workspace_id=:workspace
                          AND r.status IN ('active','pending_binding')
                          AND r.authority_status='authority_revoked_unconfirmed'
                          AND EXISTS (SELECT 1 FROM jsonb_array_elements(
                            (SELECT reset_sessions_json FROM workspaces WHERE workspace_id=:workspace)
                          ) AS reset_session(value) WHERE reset_session.value->>'session_id'=r.session_id
                            AND reset_session.value->>'trace_id'=r.trace_id)""",
                        {"owner": owner, "workspace": workspace, "now": now})

                    blocked = False
                    try:
                        WorkspaceResetStore.preflight_in_connection(
                            connection, owner_principal=owner, workspace_id=workspace,
                            expected_status="disabled")
                    except WorkspaceResetBlocked:
                        blocked = True
                    archived_ids = ConversationCatalogStore.archive_workspace_reset_sessions(
                        connection, owner=owner, workspace=workspace, sessions=sessions, now=now)
                    expected_ids = [item["conversation_id"] for item in sessions]
                    if archived_ids != expected_ids:
                        raise WorkspaceRuntimeResetConflict("conversation scope changed before reset finalization")

                    if blocked:
                        # Gateway proved the DSH sessions are released. Reopen
                        # safely without deleting data if a blocker appeared late.
                        receipt: dict[str, object] = {
                            "status": "blocked", "workspace_id": workspace,
                            "reason": "Workspace state changed after reset began; business data was retained",
                        }
                    else:
                        deleted = WorkspaceResetStore.reset_in_connection(
                            connection, owner_principal=owner, workspace_id=workspace)
                        receipt = {"status": "reset", "workspace_id": workspace,
                                   "deleted": deleted, "already_empty": not any(deleted.values())}

                    result = connection.execute(text("""UPDATE workspaces
                        SET status='active',reset_id=NULL,reset_kind=NULL,reset_request_key=NULL,
                            reset_sessions_json=NULL,updated_at=:now
                        WHERE workspace_id=:workspace AND status='disabled'
                          AND reset_id=:reset_id AND reset_kind='workspace'
                          AND reset_request_key=:request_key"""),
                        {"workspace": workspace, "reset_id": requested_reset_id,
                         "request_key": request_key, "now": now})
                    if result.rowcount != 1:
                        raise WorkspaceRuntimeResetConflict("pending Workspace reset changed before activation")
                    self._save_workspace_reset_receipt(
                        connection, workspace=workspace, request_key=request_key,
                        reset_id=requested_reset_id, receipt=receipt,
                        released_sessions=supplied, now=now)
                    return self._workspace_reset_finalize_envelope(workspace, requested_reset_id, receipt)
        except (WorkspaceRuntimeResetNotFound, WorkspaceRuntimeResetConflict,
                WorkspaceRuntimeResetPersistenceError):
            raise
        except SQLAlchemyError as error:
            raise WorkspaceRuntimeResetPersistenceError("Workspace reset could not be finalized safely") from error
