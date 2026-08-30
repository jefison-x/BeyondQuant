"""BYQ-owned contracts for Phase 13 quant research agents.

DSH supplies generic role composition and subagent lifecycle. This module owns
the business-facing role catalogue, authorization, human approval, and audit
records. It deliberately stores bounded summaries rather than DSH event or
session schemas.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, execute, fetch_one


MAX_DETAIL_BYTES = 16 * 1024
_ID_PATTERN = re.compile(r"^(?:agent_run|agent_approval|agent_audit)_[0-9a-f]{32}$")
_TRACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_PRINCIPAL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")
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


class AgentResearchError(RuntimeError):
    """Safe base class for Phase 13 domain failures."""


class AgentNotFound(AgentResearchError):
    pass


class AgentUnauthorized(AgentResearchError):
    pass


class AgentForbidden(AgentResearchError):
    pass


class AgentConflict(AgentResearchError):
    pass


class AgentPersistenceError(AgentResearchError):
    pass


@dataclass(frozen=True, slots=True)
class AgentRole:
    role_id: str
    version: str
    description: str
    allowed_tools: tuple[str, ...]
    delegate_to: tuple[str, ...]
    approval_required_actions: tuple[str, ...]
    evidence_kinds: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self) | {
            "allowed_tools": list(self.allowed_tools),
            "delegate_to": list(self.delegate_to),
            "approval_required_actions": list(self.approval_required_actions),
            "evidence_kinds": list(self.evidence_kinds),
        }


ROLE_CATALOG: tuple[AgentRole, ...] = (
    AgentRole(
        role_id="quant_orchestrator",
        version="1.6.0",
        description="Coordinates bounded research hand-offs and explicit owner-scoped domain actions.",
        allowed_tools=(
            "byq_product_help_query",
            "byq_agent_context",
            "byq_agent_run_start",
            "byq_agent_authorize",
            "byq_agent_audit",
            "byq_agent_approval_request",
            "byq_agent_approval_get",
            "byq_agent_approval_decide",
            "byq_agent_roles",
            "byq_market_session_context",
            "byq_market_daily",
            "byq_market_valuation",
            "byq_market_fundamentals",
            "byq_pool_list",
            "byq_pool_get",
            "byq_pool_create",
            "byq_factor_compute",
            "byq_research_task_create",
            "byq_research_get",
            "byq_research_transition",
            "byq_experiment_create",
            "byq_artifact_create",
            "byq_web_evidence_create",
            "byq_strategy_validate",
            "byq_strategy_version_create",
            "byq_strategy_approve",
            "byq_strategy_export",
            "byq_backtest_task_prepare",
            "byq_backtest_task_create",
            "byq_backtest_task_get",
            "byq_backtest_task_execute",
            "byq_backtest_task_cancel",
            "byq_learning_run_start",
            "byq_learning_run_get",
            "byq_learning_iteration_record",
            "byq_learning_iteration_list",
            "byq_learning_run_review",
            "byq_evaluation_signal_create",
            "byq_evaluation_signal_get",
            "byq_experiment_compare",
            "byq_lesson_propose",
            "byq_lesson_get",
            "byq_lesson_review",
        ),
        delegate_to=(
            "market_researcher",
            "factor_researcher",
            "strategy_researcher",
            "backtest_analyst",
        ),
        approval_required_actions=(
            "byq_strategy_approve",
            "byq_backtest_task_create",
            "byq_backtest_task_execute",
            "byq_backtest_task_cancel",
        ),
        evidence_kinds=("research_evidence", "web_research_evidence", "stock_pool", "factor_result", "strategy_version", "backtest_result"),
    ),
    AgentRole(
        role_id="market_researcher",
        version="1.4.0",
        description="Collects normalized market evidence and records bounded research artifacts.",
        allowed_tools=(
            "byq_agent_context",
            "byq_agent_run_start",
            "byq_agent_authorize",
            "byq_agent_audit",
            "byq_agent_roles",
            "byq_market_session_context",
            "byq_market_daily",
            "byq_market_valuation",
            "byq_market_fundamentals",
            "byq_research_task_create",
            "byq_research_get",
            "byq_experiment_create",
            "byq_artifact_create",
            "byq_web_evidence_create",
        ),
        delegate_to=(),
        approval_required_actions=(),
        evidence_kinds=("research_evidence", "web_research_evidence"),
    ),
    AgentRole(
        role_id="factor_researcher",
        version="1.0.0",
        description="Computes reproducible BYQ factors and records their input lineage.",
        allowed_tools=(
            "byq_agent_context",
            "byq_agent_run_start",
            "byq_agent_authorize",
            "byq_agent_audit",
            "byq_agent_roles",
            "byq_market_daily",
            "byq_factor_compute",
            "byq_research_get",
            "byq_experiment_create",
            "byq_artifact_create",
            "byq_evaluation_signal_create",
            "byq_experiment_compare",
        ),
        delegate_to=(),
        approval_required_actions=(),
        evidence_kinds=("factor_result",),
    ),
    AgentRole(
        role_id="strategy_researcher",
        version="1.2.0",
        description="Designs and validates strategy artifacts without approving or executing them.",
        allowed_tools=(
            "byq_agent_context",
            "byq_agent_run_start",
            "byq_agent_authorize",
            "byq_agent_audit",
            "byq_agent_roles",
            "byq_research_task_create",
            "byq_research_get",
            "byq_experiment_create",
            "byq_artifact_create",
            "byq_strategy_validate",
            "byq_strategy_version_create",
            "byq_strategy_export",
        ),
        delegate_to=(),
        approval_required_actions=(),
        evidence_kinds=("strategy_draft", "strategy_version"),
    ),
    AgentRole(
        role_id="backtest_analyst",
        version="1.1.0",
        description="Reviews authorized deterministic backtest jobs and result artifacts.",
        allowed_tools=(
            "byq_agent_context",
            "byq_agent_run_start",
            "byq_agent_authorize",
            "byq_agent_audit",
            "byq_agent_roles",
            "byq_research_get",
            "byq_backtest_task_prepare",
            "byq_backtest_task_create",
            "byq_backtest_task_get",
            "byq_backtest_task_execute",
            "byq_backtest_task_cancel",
            "byq_evaluation_signal_create",
            "byq_experiment_compare",
        ),
        delegate_to=(),
        approval_required_actions=(
            "byq_backtest_task_create",
            "byq_backtest_task_execute",
            "byq_backtest_task_cancel",
        ),
        evidence_kinds=("backtest_result",),
    ),
)
ROLE_BY_ID = {role.role_id: role for role in ROLE_CATALOG}


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


def _entity_id(value: object, *, field: str, prefix: str) -> str:
    normalized = _text(value, field=field, max_length=64)
    if normalized.startswith(f"{prefix}_") and re.fullmatch(rf"{prefix}_[0-9a-f]{{32}}", normalized):
        return normalized
    raise ValueError(f"{field} is not a valid BYQ identifier")


def _json_object(value: object, *, field: str) -> tuple[dict[str, object], str]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    _reject_secret_keys(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be JSON-serializable") from exc
    if len(encoded.encode("utf-8")) > MAX_DETAIL_BYTES:
        raise ValueError(f"{field} exceeds {MAX_DETAIL_BYTES} bytes")
    return value, encoded


def _reject_secret_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            if any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS):
                raise ValueError("agent audit detail must not contain credential fields")
            _reject_secret_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_secret_keys(nested)


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _loads(value: str, *, field: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise AgentPersistenceError(f"stored {field} is invalid") from exc


def role_catalog() -> list[dict[str, object]]:
    return [role.as_dict() for role in ROLE_CATALOG]


class AgentResearchStore(PgStoreMixin):
    """Durable BYQ store for agent runs, approvals, and bounded audit events (ADR-0016 PG)."""

    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS agent_runs (
            run_id TEXT PRIMARY KEY,
            owner_principal TEXT NOT NULL,
            actor_principal TEXT NOT NULL,
            role_id TEXT NOT NULL,
            role_version TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            dsh_run_id TEXT NOT NULL,
            parent_run_id TEXT,
            status TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            version INTEGER NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS agent_runs_idempotency
            ON agent_runs(owner_principal, idempotency_key)
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_audit (
            audit_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
            owner_principal TEXT NOT NULL,
            actor_principal TEXT NOT NULL,
            action TEXT NOT NULL,
            outcome TEXT NOT NULL,
            resource_type TEXT,
            resource_id TEXT,
            detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS agent_audit_run ON agent_audit(run_id, created_at, audit_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_approvals (
            approval_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
            owner_principal TEXT NOT NULL,
            actor_principal TEXT NOT NULL,
            action TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL,
            decision_by TEXT,
            decision_reason TEXT,
            execution_outcome TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS agent_approvals_idempotency
            ON agent_approvals(run_id, idempotency_key)
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as exc:
            raise AgentPersistenceError("agent research storage is unavailable") from exc

    @classmethod
    def from_env(cls) -> "AgentResearchStore":
        return cls()

    def start_run(self, payload: object, *, trusted_owner: str | None = None, trusted_actor: str | None = None) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("agent run request must be an object")
        allowed = {"owner_principal", "actor_principal", "role_id", "trace_id", "session_id", "dsh_run_id", "parent_run_id", "idempotency_key"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"agent run request has unknown fields: {', '.join(unknown)}")
        owner = _principal(trusted_owner or payload.get("owner_principal"), field="owner_principal")
        actor = _principal(trusted_actor or payload.get("actor_principal") or owner, field="actor_principal")
        if trusted_owner and payload.get("owner_principal") not in {None, trusted_owner}:
            raise AgentUnauthorized("agent owner does not match trusted product context")
        if trusted_actor and payload.get("actor_principal") not in {None, trusted_actor}:
            raise AgentUnauthorized("agent actor does not match trusted product context")
        role_id = _text(payload.get("role_id"), field="role_id", max_length=64)
        role = ROLE_BY_ID.get(role_id)
        if role is None:
            raise ValueError("unknown agent role")
        trace_id = _trace(payload.get("trace_id"), field="trace_id")
        session_id = _trace(payload.get("session_id"), field="session_id")
        dsh_run_id = _trace(payload.get("dsh_run_id") or session_id, field="dsh_run_id")
        parent_run_id = payload.get("parent_run_id")
        if parent_run_id is not None:
            parent_run_id = _entity_id(parent_run_id, field="parent_run_id", prefix="agent_run")
        key = _idempotency(payload.get("idempotency_key"))
        request = {
            "owner_principal": owner,
            "actor_principal": actor,
            "role_id": role_id,
            "role_version": role.version,
            "trace_id": trace_id,
            "session_id": session_id,
            "dsh_run_id": dsh_run_id,
            "parent_run_id": parent_run_id,
            "idempotency_key": key,
        }
        request_hash = _hash(request)
        with self._transaction() as connection:
            existing = fetch_one(
                connection,
                "SELECT * FROM agent_runs WHERE owner_principal = :owner AND idempotency_key = :key",
                {"owner": owner, "key": key},
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise AgentConflict("agent run idempotency key was reused")
                return self._run_row(existing)
            if parent_run_id:
                parent = fetch_one(connection, "SELECT * FROM agent_runs WHERE run_id = :parent_run_id", {"parent_run_id": parent_run_id})
                if parent is None or parent["owner_principal"] != owner:
                    raise AgentForbidden("parent agent run is not owned by this principal")
                parent_role = ROLE_BY_ID[parent["role_id"]]
                if role_id not in parent_role.delegate_to:
                    raise AgentForbidden("parent role is not authorized to delegate to this role")
            now = _now()
            run_id = _new_id("agent_run")
            execute(
                connection,
                """INSERT INTO agent_runs
                (run_id, owner_principal, actor_principal, role_id, role_version,
                 trace_id, session_id, dsh_run_id, parent_run_id, status,
                 idempotency_key, request_hash, created_at, updated_at, version)
                VALUES (:run_id, :owner, :actor, :role_id, :role_version,
                        :trace_id, :session_id, :dsh_run_id, :parent_run_id, 'active',
                        :key, :request_hash, :created_at, :updated_at, 1)""",
                {"run_id": run_id, "owner": owner, "actor": actor, "role_id": role_id, "role_version": role.version,
                 "trace_id": trace_id, "session_id": session_id, "dsh_run_id": dsh_run_id, "parent_run_id": parent_run_id,
                 "key": key, "request_hash": request_hash, "created_at": now, "updated_at": now},
            )
            row = fetch_one(connection, "SELECT * FROM agent_runs WHERE run_id = :run_id", {"run_id": run_id})
        assert row is not None
        return self._run_row(row)

    def authorize(self, payload: object, *, trusted_owner: str | None = None, trusted_actor: str | None = None) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("agent authorization request must be an object")
        allowed = {"run_id", "action", "resource_type", "resource_id"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"agent authorization request has unknown fields: {', '.join(unknown)}")
        run_id = _entity_id(payload.get("run_id"), field="run_id", prefix="agent_run")
        action = _text(payload.get("action"), field="action", max_length=128)
        resource_type = payload.get("resource_type")
        resource_id = payload.get("resource_id")
        row = self._fetch_one("SELECT * FROM agent_runs WHERE run_id = :run_id", {"run_id": run_id})
        if row is None:
            raise AgentNotFound("agent run not found")
        self._check_run_access(row, trusted_owner=trusted_owner, trusted_actor=trusted_actor)
        role = ROLE_BY_ID[row["role_id"]]
        if action not in role.allowed_tools:
            self._record_audit_row(row, action=action, outcome="denied", resource_type=resource_type, resource_id=resource_id, detail={"reason": "role_tool_not_allowed"})
            raise AgentForbidden("agent role is not authorized for this domain action")
        requires_approval = action in role.approval_required_actions
        result = {
            "authorized": not requires_approval,
            "decision": "approval_required" if requires_approval else "allowed",
            "run_id": run_id,
            "role_id": row["role_id"],
            "action": action,
        }
        self._record_audit_row(row, action=action, outcome="approval_required" if requires_approval else "authorized", resource_type=resource_type, resource_id=resource_id, detail=result)
        return result

    def record_audit(self, payload: object, *, trusted_owner: str | None = None, trusted_actor: str | None = None) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("agent audit request must be an object")
        allowed = {"run_id", "action", "outcome", "resource_type", "resource_id", "detail"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"agent audit request has unknown fields: {', '.join(unknown)}")
        run_id = _entity_id(payload.get("run_id"), field="run_id", prefix="agent_run")
        action = _text(payload.get("action"), field="action", max_length=128)
        outcome = _text(payload.get("outcome"), field="outcome", max_length=64)
        detail, _ = _json_object(payload.get("detail", {}), field="detail")
        row = self._fetch_one("SELECT * FROM agent_runs WHERE run_id = :run_id", {"run_id": run_id})
        if row is None:
            raise AgentNotFound("agent run not found")
        self._check_run_access(row, trusted_owner=trusted_owner, trusted_actor=trusted_actor)
        return self._record_audit_row(row, action=action, outcome=outcome, resource_type=payload.get("resource_type"), resource_id=payload.get("resource_id"), detail=detail)

    def list_audit(self, run_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        run_id = _entity_id(run_id, field="run_id", prefix="agent_run")
        run = self._fetch_one("SELECT * FROM agent_runs WHERE run_id = :run_id", {"run_id": run_id})
        if run is None:
            raise AgentNotFound("agent run not found")
        if trusted_owner and run["owner_principal"] != trusted_owner:
            raise AgentUnauthorized("agent run is not owned by this principal")
        rows = self._execute(
            "SELECT * FROM agent_audit WHERE run_id = :run_id ORDER BY created_at ASC, audit_id ASC",
            {"run_id": run_id},
        )
        return {"run": self._run_row(run), "events": [self._audit_row(row) for row in rows]}

    def create_approval(self, payload: object, *, trusted_owner: str | None = None, trusted_actor: str | None = None) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("agent approval request must be an object")
        allowed = {"run_id", "action", "reason", "idempotency_key"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"agent approval request has unknown fields: {', '.join(unknown)}")
        run_id = _entity_id(payload.get("run_id"), field="run_id", prefix="agent_run")
        action = _text(payload.get("action"), field="action", max_length=128)
        reason = _text(payload.get("reason"), field="reason", max_length=2000)
        key = _idempotency(payload.get("idempotency_key"))
        with self._transaction() as connection:
            run = fetch_one(connection, "SELECT * FROM agent_runs WHERE run_id = :run_id", {"run_id": run_id})
            if run is None:
                raise AgentNotFound("agent run not found")
            self._check_run_access(run, trusted_owner=trusted_owner, trusted_actor=trusted_actor)
            role = ROLE_BY_ID[run["role_id"]]
            if action not in role.approval_required_actions:
                raise AgentForbidden("agent action does not require or support this approval boundary")
            request = {"run_id": run_id, "action": action, "reason": reason, "idempotency_key": key}
            request_hash = _hash(request)
            existing = fetch_one(
                connection,
                "SELECT * FROM agent_approvals WHERE run_id = :run_id AND idempotency_key = :key",
                {"run_id": run_id, "key": key},
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise AgentConflict("agent approval idempotency key was reused")
                return self._approval_row(existing)
            now = _now()
            approval_id = _new_id("agent_approval")
            execute(
                connection,
                """INSERT INTO agent_approvals
                (approval_id, run_id, owner_principal, actor_principal, action, reason,
                 status, decision_by, decision_reason, execution_outcome,
                 idempotency_key, request_hash, created_at, updated_at)
                VALUES (:approval_id, :run_id, :owner_principal, :actor_principal, :action, :reason,
                        'pending', NULL, NULL, 'not_started', :key, :request_hash, :created_at, :updated_at)""",
                {"approval_id": approval_id, "run_id": run_id, "owner_principal": run["owner_principal"],
                 "actor_principal": run["actor_principal"], "action": action, "reason": reason,
                 "key": key, "request_hash": request_hash, "created_at": now, "updated_at": now},
            )
            row = fetch_one(connection, "SELECT * FROM agent_approvals WHERE approval_id = :approval_id", {"approval_id": approval_id})
            assert row is not None
            self._record_audit_row(run, action="approval.request", outcome="pending", resource_type="agent_approval", resource_id=approval_id, detail={"action": action}, connection=connection)
        return self._approval_row(row)

    def decide_approval(self, payload: object, *, trusted_owner: str | None = None, trusted_actor: str | None = None) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("agent approval decision must be an object")
        allowed = {"approval_id", "decision", "rationale"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"agent approval decision has unknown fields: {', '.join(unknown)}")
        approval_id = _entity_id(payload.get("approval_id"), field="approval_id", prefix="agent_approval")
        decision = _text(payload.get("decision"), field="decision", max_length=16)
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        rationale = _text(payload.get("rationale") or "", field="rationale", max_length=2000) if payload.get("rationale") else ""
        reviewer = _principal(trusted_actor, field="reviewer_principal") if trusted_actor else None
        if reviewer is None:
            raise AgentUnauthorized("human approval requires a trusted reviewer principal")
        with self._transaction() as connection:
            row = fetch_one(connection, "SELECT * FROM agent_approvals WHERE approval_id = :approval_id", {"approval_id": approval_id})
            if row is None:
                raise AgentNotFound("agent approval not found")
            if trusted_owner and row["owner_principal"] != trusted_owner:
                raise AgentUnauthorized("agent approval is not owned by this principal")
            if reviewer == row["actor_principal"]:
                raise AgentForbidden("agent actor cannot self-approve a consequential action")
            if row["status"] != "pending":
                return self._approval_row(row)
            now = _now()
            status = "approved" if decision == "approved" else "rejected"
            outcome = "authorized" if status == "approved" else "not_authorized"
            execute(
                connection,
                "UPDATE agent_approvals SET status = :status, decision_by = :decision_by, decision_reason = :decision_reason, execution_outcome = :execution_outcome, updated_at = :updated_at WHERE approval_id = :approval_id",
                {"status": status, "decision_by": reviewer, "decision_reason": rationale, "execution_outcome": outcome, "updated_at": now, "approval_id": approval_id},
            )
            updated = fetch_one(connection, "SELECT * FROM agent_approvals WHERE approval_id = :approval_id", {"approval_id": approval_id})
            assert updated is not None
            run = fetch_one(connection, "SELECT * FROM agent_runs WHERE run_id = :run_id", {"run_id": row["run_id"]})
            assert run is not None
            self._record_audit_row(run, action="approval.decision", outcome=status, resource_type="agent_approval", resource_id=approval_id, detail={"reviewer": reviewer, "decision": decision}, connection=connection)
        return self._approval_row(updated)

    def get_approval(self, approval_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        approval_id = _entity_id(approval_id, field="approval_id", prefix="agent_approval")
        row = self._fetch_one("SELECT * FROM agent_approvals WHERE approval_id = :approval_id", {"approval_id": approval_id})
        if row is None:
            raise AgentNotFound("agent approval not found")
        if trusted_owner and row["owner_principal"] != trusted_owner:
            raise AgentUnauthorized("agent approval is not owned by this principal")
        return self._approval_row(row)

    def list_approvals(self, *, trusted_owner: str | None = None) -> dict[str, object]:
        if trusted_owner:
            rows = self._execute(
                "SELECT * FROM agent_approvals WHERE owner_principal = :owner_principal ORDER BY created_at DESC, approval_id DESC LIMIT 200",
                {"owner_principal": trusted_owner},
            )
        else:
            rows = self._execute("SELECT * FROM agent_approvals ORDER BY created_at DESC, approval_id DESC LIMIT 200")
        return {"approvals": [self._approval_row(row) for row in rows]}

    def _check_run_access(self, row: dict[str, Any], *, trusted_owner: str | None, trusted_actor: str | None) -> None:
        if trusted_owner and row["owner_principal"] != trusted_owner:
            raise AgentUnauthorized("agent run is not owned by this principal")
        if trusted_actor and row["actor_principal"] != trusted_actor:
            raise AgentUnauthorized("agent actor does not match the active run")
        if row["status"] != "active":
            raise AgentForbidden("agent run is not active")

    def _record_audit_row(self, run: dict[str, Any], *, action: object, outcome: object, resource_type: object, resource_id: object, detail: object, connection: Any = None) -> dict[str, object]:
        action_text = _text(action, field="action", max_length=128)
        outcome_text = _text(outcome, field="outcome", max_length=64)
        resource_type_text = _text(resource_type, field="resource_type", max_length=64) if resource_type is not None else None
        resource_id_text = _text(resource_id, field="resource_id", max_length=128) if resource_id is not None else None
        detail_value, _ = _json_object(detail, field="detail")
        audit_id = _new_id("agent_audit")
        created_at = _now()
        params = {
            "audit_id": audit_id,
            "run_id": run["run_id"],
            "owner_principal": run["owner_principal"],
            "actor_principal": run["actor_principal"],
            "action": action_text,
            "outcome": outcome_text,
            "resource_type": resource_type_text,
            "resource_id": resource_id_text,
            "detail_json": detail_value,
            "created_at": created_at,
        }
        sql = """INSERT INTO agent_audit
            (audit_id, run_id, owner_principal, actor_principal, action, outcome,
             resource_type, resource_id, detail_json, created_at)
            VALUES (:audit_id, :run_id, :owner_principal, :actor_principal, :action, :outcome,
                    :resource_type, :resource_id, :detail_json, :created_at)"""
        if connection is None:
            with self._transaction() as tx_connection:
                execute(tx_connection, sql, params)
        else:
            execute(connection, sql, params)
        return {
            "audit_id": audit_id,
            "run_id": run["run_id"],
            "owner_principal": run["owner_principal"],
            "actor_principal": run["actor_principal"],
            "action": action_text,
            "outcome": outcome_text,
            "resource_type": resource_type_text,
            "resource_id": resource_id_text,
            "detail": detail_value,
            "created_at": created_at,
        }

    @staticmethod
    def _run_row(row: dict[str, Any]) -> dict[str, object]:
        result = dict(row)
        result.pop("idempotency_key", None)
        result.pop("request_hash", None)
        return result

    @staticmethod
    def _audit_row(row: dict[str, Any]) -> dict[str, object]:
        result = dict(row)
        result["detail"] = result.pop("detail_json") or {}
        return result

    @staticmethod
    def _approval_row(row: dict[str, Any]) -> dict[str, object]:
        result = dict(row)
        result.pop("idempotency_key", None)
        result.pop("request_hash", None)
        return result
