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
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from packages.contracts.agent_run_lifecycle import registration_fingerprint, validate_lifecycle_event, lifecycle_receipt
from packages.contracts.research_plan_approval import (
    AGENT_APPROVAL_PLAN_ACTION,
    PLAN_APPROVAL_ACTION,
    approval_plan_binding,
    plan_command_digest,
    plan_command_idempotency_key,
)

from .db import PgStoreMixin, execute, fetch_one, transaction
from .domain_call_admission import DomainCallEvidenceMixin, DOMAIN_CALL_DDL
from .research_task_actions import (
    approval_decision_digest,
    approval_source_digest,
    insert_pending_approval_action,
    project_research_task_action,
)


APPROVAL_RESOURCE_TYPES = {
    "byq_strategy_approve": "strategy_version",
    "byq_ml_strategy_approve": "ml_strategy_version",
    "byq_feedback_submit": "product_feedback",
}

MAX_DETAIL_BYTES = 16 * 1024
_ID_PATTERN = re.compile(r"^(?:agent_run|agent_approval|agent_audit)_[0-9a-f]{32}$")
_TRACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_RUNTIME_BOOT_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
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
_PLAN_BINDING_FIELDS = (
    "plan_task_id", "plan_workspace_id", "plan_version", "plan_task_version",
    "plan_action", "plan_resource_kind", "plan_resource_id", "plan_params_digest",
    "plan_idempotency_key",
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
        version="2.1.0",
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
            "byq_data_demand_create",
            "byq_data_demand_get",
            "byq_feedback_options",
            "byq_feedback_list",
            "byq_feedback_get",
            "byq_feedback_create_draft",
            "byq_feedback_update_draft",
            "byq_feedback_preview",
            "byq_feedback_submit",
            "byq_pool_list",
            "byq_pool_get",
            "byq_pool_create",
            "byq_index_pool_catalog",
            "byq_index_pool_create",
            "byq_index_pool_status",
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
            "ml_researcher",
        ),
        approval_required_actions=(
            "byq_feedback_submit",
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
        version="1.2.0",
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
            "byq_backtest_analysis_get",
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
    AgentRole(
        role_id="ml_researcher",
        version="1.2.0",
        description="Creates closed-profile ML research, materializes exact human-authorized approvals, manages trusted training/prediction, and executes derived backtest tasks without accessing model objects.",
        allowed_tools=(
            "byq_agent_context",
            "byq_agent_run_start",
            "byq_agent_authorize",
            "byq_agent_audit",
            "byq_agent_roles",
            "byq_research_task_create",
            "byq_research_get",
            "byq_ml_capabilities",
            "byq_ml_workspace_get",
            "byq_ml_strategy_create",
            "byq_ml_strategy_approve",
            "byq_ml_training_create",
            "byq_ml_training_get",
            "byq_ml_training_cancel",
            "byq_ml_prediction_create",
            "byq_ml_prediction_get",
            "byq_backtest_task_get",
            "byq_backtest_task_execute",
            "byq_backtest_task_cancel",
        ),
        delegate_to=(),
        approval_required_actions=(
            "byq_ml_strategy_approve", "byq_ml_training_create", "byq_ml_training_cancel",
            "byq_ml_prediction_create", "byq_backtest_task_execute", "byq_backtest_task_cancel",
        ),
        evidence_kinds=(
            "ml_strategy_version", "ml_training_run", "ml_model_metadata",
            "ml_prediction_snapshot", "signal_snapshot", "backtest_result",
        ),
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


def _runtime_boot_id(value: object) -> str:
    if not isinstance(value, str) or _RUNTIME_BOOT_PATTERN.fullmatch(value) is None:
        raise ValueError("runtime boot id must be 32 lowercase hexadecimal characters")
    return value


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


class AgentResearchStore(DomainCallEvidenceMixin, PgStoreMixin):
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
            authority_status TEXT NOT NULL DEFAULT 'active'
                CHECK (authority_status IN ('active','authority_revoked_unconfirmed','closed')),
            authority_boot_id TEXT,
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
        """CREATE TABLE IF NOT EXISTS agent_runtime_turns (
            root_run_id TEXT PRIMARY KEY, owner_principal TEXT NOT NULL, workspace_id TEXT NOT NULL,
            session_id TEXT NOT NULL, trace_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('active','completed','failed','cancelled','interrupted')),
            authority_status TEXT NOT NULL DEFAULT 'active'
                CHECK (authority_status IN ('active','authority_revoked_unconfirmed','closed')),
            authority_boot_id TEXT,
            terminal_sequence BIGINT, terminal_event_sha256 TEXT,
            created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS agent_runtime_authority_current (
            authority_key TEXT PRIMARY KEY CHECK (authority_key = 'current'),
            boot_id TEXT NOT NULL,
            epoch BIGINT NOT NULL CHECK (epoch > 0),
            receipt_json JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS agent_runtime_authority_boot_receipts (
            boot_id TEXT PRIMARY KEY,
            epoch BIGINT NOT NULL UNIQUE,
            receipt_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS agent_runtime_registrations (
            registration_fingerprint TEXT PRIMARY KEY,
            root_run_id TEXT NOT NULL REFERENCES agent_runtime_turns(root_run_id)
        )""",
        "CREATE INDEX IF NOT EXISTS agent_runtime_registrations_root ON agent_runtime_registrations(root_run_id)",
        """CREATE TABLE IF NOT EXISTS agent_runtime_receipts (
            owner_principal TEXT NOT NULL, workspace_id TEXT NOT NULL, session_id TEXT NOT NULL,
            trace_id TEXT NOT NULL, sequence BIGINT NOT NULL, receipt_json JSONB NOT NULL,
            PRIMARY KEY (owner_principal, workspace_id, session_id, sequence)
        )""",
        "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS root_run_id TEXT REFERENCES agent_runtime_turns(root_run_id)",
        "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS runtime_registration_fingerprint TEXT",
        "CREATE INDEX IF NOT EXISTS agent_runs_runtime_registration ON agent_runs(runtime_registration_fingerprint)",
        "CREATE INDEX IF NOT EXISTS agent_runs_root ON agent_runs(root_run_id)",
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
        "ALTER TABLE agent_approvals ADD COLUMN IF NOT EXISTS resource_type TEXT",
        "ALTER TABLE agent_approvals ADD COLUMN IF NOT EXISTS resource_id TEXT",
        "ALTER TABLE agent_approvals ADD COLUMN IF NOT EXISTS continuation_status TEXT NOT NULL DEFAULT 'not_requested'",
        "ALTER TABLE agent_approvals ADD COLUMN IF NOT EXISTS continuation_attempt INTEGER NOT NULL DEFAULT 0",
        # ADR-0085 §3/P2: a plan-bound human approval durably binds the EXACT plan
        # command at request time (plan/task version, action, resource, parameter
        # digest and BYQ idempotency key). A compat approval leaves these NULL.
        "ALTER TABLE agent_approvals ADD COLUMN IF NOT EXISTS plan_task_id TEXT",
        "ALTER TABLE agent_approvals ADD COLUMN IF NOT EXISTS plan_workspace_id TEXT",
        "ALTER TABLE agent_approvals ADD COLUMN IF NOT EXISTS plan_version INTEGER",
        "ALTER TABLE agent_approvals ADD COLUMN IF NOT EXISTS plan_task_version INTEGER",
        "ALTER TABLE agent_approvals ADD COLUMN IF NOT EXISTS plan_action TEXT",
        "ALTER TABLE agent_approvals ADD COLUMN IF NOT EXISTS plan_resource_kind TEXT",
        "ALTER TABLE agent_approvals ADD COLUMN IF NOT EXISTS plan_resource_id TEXT",
        "ALTER TABLE agent_approvals ADD COLUMN IF NOT EXISTS plan_params_digest TEXT",
        "ALTER TABLE agent_approvals ADD COLUMN IF NOT EXISTS plan_idempotency_key TEXT",
        """
        CREATE INDEX IF NOT EXISTS agent_approvals_owner_pending
            ON agent_approvals(owner_principal, status, created_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS agent_approvals_plan_task
            ON agent_approvals(plan_task_id) WHERE plan_task_id IS NOT NULL
        """,
    ]

    SCHEMA_DDL = SCHEMA_DDL + DOMAIN_CALL_DDL

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
            self.runtime_authority_guard_engine = create_engine(
                self.database_url,
                pool_size=8,
                max_overflow=0,
                pool_timeout=0.25,
                pool_pre_ping=True,
                future=True,
            )
        except SQLAlchemyError as exc:
            raise AgentPersistenceError("agent research storage is unavailable") from exc

    def close(self) -> None:
        guard_engine = getattr(self, "runtime_authority_guard_engine", None)
        if guard_engine is not None:
            guard_engine.dispose()
        super().close()

    @classmethod
    def from_env(cls) -> "AgentResearchStore":
        return cls()

    def start_run(self, payload: object, *, trusted_owner: str | None = None, trusted_actor: str | None = None,
                  trusted_workspace: str | None = None, trusted_boot_id: str | None = None,
                  require_runtime_binding: bool = False) -> dict[str, object]:
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
        if require_runtime_binding and not trusted_workspace:
            raise AgentUnauthorized("runtime binding requires a trusted workspace")
        if trusted_boot_id is not None:
            trusted_boot_id = _runtime_boot_id(trusted_boot_id)
        fingerprint = (registration_fingerprint(owner, trusted_workspace, actor, trace_id, session_id, dsh_run_id, key)
                       if trusted_workspace else None)
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
            authority = None
            if require_runtime_binding or trusted_boot_id is not None:
                self._lifecycle_lock(connection, "runtime-authority:current")
                authority = self._require_current_runtime_boot(
                    connection, trusted_boot_id, required=require_runtime_binding)
            if trusted_workspace:
                self._require_lifecycle_workspace(connection, owner, trusted_workspace)
            # Serialize a registration receipt with its independently observed
            # binding. No root row lock here: root consumers lock root then key.
            if fingerprint:
                self._lifecycle_lock(connection, "registration:" + fingerprint)
            self._lifecycle_lock(connection, "agent-key:" + _hash([owner, key]))
            existing = fetch_one(
                connection,
                "SELECT * FROM agent_runs WHERE owner_principal = :owner AND idempotency_key = :key",
                {"owner": owner, "key": key},
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise AgentConflict("agent run idempotency key was reused")
                if authority is not None and existing.get("authority_boot_id") != authority["boot_id"]:
                    raise AgentConflict("agent run belongs to a superseded runtime boot")
                return self._run_row(existing)
            binding = fetch_one(connection, """SELECT t.* FROM agent_runtime_registrations r
                JOIN agent_runtime_turns t ON t.root_run_id=r.root_run_id
                WHERE r.registration_fingerprint=:fingerprint""", {"fingerprint": fingerprint}) if fingerprint else None
            if binding and (binding["owner_principal"], binding["workspace_id"], binding["session_id"], binding["trace_id"]) != (owner, trusted_workspace, session_id, trace_id):
                raise AgentUnauthorized("runtime registration does not match trusted context")
            root_run_id = binding["root_run_id"] if binding else None
            status = binding["status"] if binding else ("pending_binding" if require_runtime_binding else "active")
            if binding and authority is not None and (
                    binding["authority_status"] == "authority_revoked_unconfirmed"
                    or binding["authority_boot_id"] != authority["boot_id"]):
                raise AgentConflict("runtime registration belongs to a superseded boot")
            if parent_run_id:
                parent = fetch_one(connection, "SELECT * FROM agent_runs WHERE run_id = :parent_run_id", {"parent_run_id": parent_run_id})
                if parent is None or parent["owner_principal"] != owner:
                    raise AgentForbidden("parent agent run is not owned by this principal")
                if (parent["status"] != "active" or parent.get("authority_status", "active") != "active"
                        or (authority is not None and parent.get("authority_boot_id") != authority["boot_id"])
                        or parent["actor_principal"] != actor
                        or parent["session_id"] != session_id or parent["dsh_run_id"] != dsh_run_id
                        or (root_run_id is not None and parent.get("root_run_id") != root_run_id)
                        or (not require_runtime_binding and parent.get("root_run_id") != root_run_id)):
                    raise AgentForbidden("parent agent run does not belong to this active runtime context")
                parent_role = ROLE_BY_ID[parent["role_id"]]
                if role_id not in parent_role.delegate_to:
                    raise AgentForbidden("parent role is not authorized to delegate to this role")
            now = _now()
            run_id = _new_id("agent_run")
            execute(
                connection,
                """INSERT INTO agent_runs
                (run_id, owner_principal, actor_principal, role_id, role_version,
                 trace_id, session_id, dsh_run_id, parent_run_id, status, authority_status, authority_boot_id,
                 idempotency_key, request_hash, created_at, updated_at, version,
                 root_run_id, runtime_registration_fingerprint)
                VALUES (:run_id, :owner, :actor, :role_id, :role_version,
                        :trace_id, :session_id, :dsh_run_id, :parent_run_id, :status, :authority_status, :authority_boot_id,
                        :key, :request_hash, :created_at, :updated_at, 1, :root_run_id, :fingerprint)""",
                {"run_id": run_id, "owner": owner, "actor": actor, "role_id": role_id, "role_version": role.version,
                 "trace_id": trace_id, "session_id": session_id, "dsh_run_id": dsh_run_id, "parent_run_id": parent_run_id,
                 "authority_status": binding["authority_status"] if binding else "active",
                 "authority_boot_id": authority["boot_id"] if authority is not None else None,
                 "key": key, "request_hash": request_hash, "created_at": now, "updated_at": now,
                 "status": status, "root_run_id": root_run_id, "fingerprint": fingerprint},
            )
            row = fetch_one(connection, "SELECT * FROM agent_runs WHERE run_id = :run_id", {"run_id": run_id})
            if binding and row:
                self._record_runtime_binding_audit(connection, row, binding)
        assert row is not None
        return self._run_row(row)

    @staticmethod
    def _lifecycle_lock(connection: Any, key: str) -> None:
        execute(connection, "SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))", {"key": key})

    def current_runtime_authority(self) -> dict[str, object] | None:
        """Return only the non-secret current boot identity for readiness checks."""
        row = self._fetch_one("""SELECT boot_id, epoch FROM agent_runtime_authority_current
            WHERE authority_key='current'""")
        if row is None:
            return None
        return {"schema_version": "byq-runtime-authority-current.v1",
                "boot_id": row["boot_id"], "authority_epoch": row["epoch"], "status": "current"}

    @staticmethod
    def _current_authority_row(connection, *, for_update: bool = False):
        suffix = " FOR UPDATE" if for_update else ""
        return fetch_one(connection, """SELECT boot_id, epoch, receipt_json
            FROM agent_runtime_authority_current WHERE authority_key='current'""" + suffix)

    def _require_current_runtime_boot(self, connection, trusted_boot_id: str | None,
                                      *, required: bool = False):
        """Fence a runtime mutation to the current Backend-issued boot receipt.

        Callers take the runtime-authority advisory lock before calling this and
        retain it until the transaction commits, serializing authority changes
        with the write they admit.
        """
        if trusted_boot_id is not None:
            trusted_boot_id = _runtime_boot_id(trusted_boot_id)
        authority = self._current_authority_row(connection)
        if authority is None:
            if required or trusted_boot_id is not None:
                raise AgentConflict("runtime authority is not initialized")
            return None
        if trusted_boot_id is None or trusted_boot_id != authority["boot_id"]:
            raise AgentUnauthorized("runtime boot does not match current Backend authority")
        return authority

    def rotate_runtime_authority(self, boot_id: object) -> dict[str, object]:
        """Atomically publish one new boot and revoke the previous boot's roots.

        Runtime status and unresolved domain-call claims are deliberately left
        intact: revocation is a business-authority fact, not evidence that an
        external action completed or failed.
        """
        boot_id = _runtime_boot_id(boot_id)
        # Take the exclusive request gate before _transaction() acquires the
        # store's process lock. Product Agent requests take the shared gate
        # before any handler reaches a store lock; this prevents lock inversion
        # while rotation drains in-flight requests.
        with transaction(self.runtime_authority_guard_engine) as gate_connection:
            self._lifecycle_lock(gate_connection, "runtime-authority:agent-writers")
            return self._rotate_runtime_authority_under_gate(boot_id)

    def _rotate_runtime_authority_under_gate(self, boot_id: str) -> dict[str, object]:
        with self._transaction() as connection:
            self._lifecycle_lock(connection, "runtime-authority:current")
            current = self._current_authority_row(connection, for_update=True)
            prior = fetch_one(connection, """SELECT receipt_json FROM agent_runtime_authority_boot_receipts
                WHERE boot_id=:boot_id""", {"boot_id": boot_id})
            if current is not None and current["boot_id"] == boot_id:
                return current["receipt_json"]
            if prior is not None:
                raise AgentConflict("runtime boot id was already superseded")

            roots = execute(connection, """SELECT root_run_id FROM agent_runtime_turns
                WHERE status='active' AND authority_status='active' ORDER BY root_run_id""")
            for root in roots:
                self._lifecycle_lock(connection, "root:" + root["root_run_id"])
                registrations = execute(connection, """SELECT registration_fingerprint
                    FROM agent_runtime_registrations WHERE root_run_id=:root
                    ORDER BY registration_fingerprint""", {"root": root["root_run_id"]})
                for registration in registrations:
                    self._lifecycle_lock(connection, "registration:" + registration["registration_fingerprint"])
            pending = execute(connection, """SELECT DISTINCT runtime_registration_fingerprint AS fingerprint
                FROM agent_runs WHERE status='pending_binding'
                  AND authority_status='active' AND runtime_registration_fingerprint IS NOT NULL
                ORDER BY runtime_registration_fingerprint""")
            for registration in pending:
                self._lifecycle_lock(connection, "registration:" + registration["fingerprint"])

            now = _now()
            revoked_roots = execute(connection, """UPDATE agent_runtime_turns
                SET authority_status='authority_revoked_unconfirmed',updated_at=:now
                WHERE status='active' AND authority_status='active' RETURNING root_run_id""", {"now": now})
            revoked_runs = execute(connection, """UPDATE agent_runs r
                SET authority_status='authority_revoked_unconfirmed',updated_at=:now,version=version+1
                WHERE r.authority_status='active' AND r.status IN ('active','pending_binding')
                  AND (r.status='pending_binding' OR r.root_run_id IN (SELECT root_run_id FROM agent_runtime_turns
                        WHERE authority_status='authority_revoked_unconfirmed')
                  )
                RETURNING r.run_id""", {"now": now})
            epoch = 1 if current is None else current["epoch"] + 1
            receipt = {"schema_version": "byq-runtime-authority-receipt.v1",
                       "boot_id": boot_id, "authority_epoch": epoch,
                       "revoked_root_count": len(revoked_roots),
                       "revoked_agent_run_count": len(revoked_runs), "status": "current"}
            encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
            execute(connection, """INSERT INTO agent_runtime_authority_boot_receipts
                (boot_id,epoch,receipt_json,created_at)
                VALUES (:boot_id,:epoch,CAST(:receipt AS jsonb),:now)""",
                {"boot_id": boot_id, "epoch": epoch, "receipt": encoded, "now": now})
            execute(connection, """INSERT INTO agent_runtime_authority_current
                (authority_key,boot_id,epoch,receipt_json,updated_at)
                VALUES ('current',:boot_id,:epoch,CAST(:receipt AS jsonb),:now)
                ON CONFLICT (authority_key) DO UPDATE SET boot_id=EXCLUDED.boot_id,
                    epoch=EXCLUDED.epoch,receipt_json=EXCLUDED.receipt_json,updated_at=EXCLUDED.updated_at""",
                {"boot_id": boot_id, "epoch": epoch, "receipt": encoded, "now": now})
        return receipt

    def close_runtime_root(self, root_run_id: object, *, boot_id: object, sequence: object,
                           outcome: object, event_sha256: object) -> dict[str, object]:
        """Close exactly the root and terminal event proven by Adapter evidence."""
        if not isinstance(root_run_id, str) or re.fullmatch(r"[0-9a-f]{32}", root_run_id) is None:
            raise ValueError("invalid exact root run identity")
        boot_id = _runtime_boot_id(boot_id)
        if type(sequence) is not int or not 1 <= sequence <= 2**63 - 1:
            raise ValueError("invalid runtime lifecycle sequence")
        if outcome not in {"completed", "failed", "cancelled", "interrupted"}:
            raise ValueError("invalid runtime lifecycle outcome")
        if not isinstance(event_sha256, str) or _SHA256_PATTERN.fullmatch(event_sha256) is None:
            raise ValueError("event_sha256 must be 64 lowercase hexadecimal characters")
        receipt = {"schema_version": "agent-run-lifecycle-receipt.v1", "sequence": sequence,
                   "root_run_id": root_run_id, "event_sha256": event_sha256}
        with self._transaction() as connection:
            self._lifecycle_lock(connection, "runtime-authority:current")
            self._lifecycle_lock(connection, "root:" + root_run_id)
            root = fetch_one(connection, "SELECT * FROM agent_runtime_turns WHERE root_run_id=:id",
                             {"id": root_run_id})
            if root is None:
                raise AgentNotFound("runtime root not found")
            if root["status"] != "active":
                if (root["status"], root["terminal_sequence"], root["terminal_event_sha256"]) == (
                        outcome, sequence, event_sha256):
                    return receipt
                raise AgentConflict("runtime root already has different terminal evidence")
            authority = self._require_current_runtime_boot(connection, boot_id, required=True)
            if (root["authority_status"] != "active" or root["authority_boot_id"] != authority["boot_id"]):
                raise AgentConflict("runtime root no longer has current business authority")
            registrations = execute(connection, """SELECT registration_fingerprint
                FROM agent_runtime_registrations WHERE root_run_id=:root
                ORDER BY registration_fingerprint""", {"root": root_run_id})
            for registration in registrations:
                self._lifecycle_lock(connection, "registration:" + registration["registration_fingerprint"])
            now = _now()
            execute(connection, """UPDATE agent_runtime_turns SET status=:outcome,authority_status='closed',
                terminal_sequence=:sequence,terminal_event_sha256=:digest,updated_at=:now
                WHERE root_run_id=:root AND status='active' AND authority_status='active'""",
                {"outcome": outcome, "sequence": sequence, "digest": event_sha256,
                 "now": now, "root": root_run_id})
            execute(connection, """UPDATE agent_runs SET status=:outcome,authority_status='closed',
                updated_at=:now,version=version+1 WHERE root_run_id=:root
                AND status IN ('active','pending_binding') AND authority_status='active'""",
                {"outcome": outcome, "now": now, "root": root_run_id})
        return receipt

    @staticmethod
    def _require_lifecycle_workspace(connection: Any, owner: str, workspace: str,
                                     *, terminal_cleanup: bool = False) -> bool:
        match = fetch_one(connection, """SELECT w.workspace_id,
                (w.status='active' AND m.status='active' AND u.status='active') AS active
            FROM workspaces w
            JOIN workspace_memberships m ON m.workspace_id=w.workspace_id
            JOIN users u ON u.user_id=m.user_id
            WHERE w.workspace_id=:workspace AND u.username=:owner
              AND w.owner_user_id=u.user_id AND w.kind='personal' AND m.role='owner'
            FOR SHARE OF w, m, u""",
            {"workspace": workspace, "owner": owner})
        if match is None or (not match["active"] and not terminal_cleanup):
            raise AgentUnauthorized("runtime lifecycle workspace does not match its owner")
        return bool(match["active"])

    def _record_runtime_binding_audit(self, connection: Any, run: dict, root: dict) -> None:
        self._record_audit_row(run, action="runtime_turn_binding", outcome=run["status"],
            resource_type="runtime_turn", resource_id=root["root_run_id"],
            detail={"root_run_id": root["root_run_id"], "terminal_sequence": root["terminal_sequence"]},
            connection=connection)

    def consume_runtime_lifecycle_event(self, event: object, **context: str) -> dict:
        event = validate_lifecycle_event(event)
        receipt = lifecycle_receipt(event)
        trusted_boot_id = context.get("trusted_boot_id")
        params = {"owner": context["trusted_owner"], "workspace": context["trusted_workspace"],
                  "session": context["trusted_session_id"], "trace": context["trusted_trace_id"],
                  "sequence": receipt["sequence"]}
        with self._transaction() as connection:
            self._lifecycle_lock(connection, "runtime-authority:current")
            self._require_lifecycle_workspace(connection, params["owner"], params["workspace"],
                                              terminal_cleanup=event["outcome"] != "active")
            self._lifecycle_lock(connection, "receipt:" + json.dumps(params, sort_keys=True))
            existing = fetch_one(connection, """SELECT * FROM agent_runtime_receipts WHERE
                owner_principal=:owner AND workspace_id=:workspace AND session_id=:session AND sequence=:sequence""", params)
            if existing:
                if existing["trace_id"] != params["trace"] or existing["receipt_json"] != receipt:
                    raise AgentConflict("runtime sequence conflicts with its durable receipt")
                return receipt
            self._require_current_runtime_boot(connection, trusted_boot_id)
            self.apply_runtime_lifecycle_event(event, **context, _connection=connection)
            execute(connection, """INSERT INTO agent_runtime_receipts
                (owner_principal,workspace_id,session_id,trace_id,sequence,receipt_json)
                VALUES (:owner,:workspace,:session,:trace,:sequence,CAST(:receipt AS jsonb))""",
                {**params, "receipt": json.dumps(receipt)})
        return receipt

    def registration_receipt(self, key: str, **context: str) -> dict:
        key = _idempotency(key)
        row = self._fetch_one("SELECT * FROM agent_runs WHERE owner_principal=:owner AND idempotency_key=:key",
                              {"owner": context["owner_principal"], "key": key})
        if row is None or any(row[field] != context[field] for field in (
                "workspace_id", "actor_principal", "session_id", "trace_id", "dsh_run_id")):
            raise AgentNotFound("exact agent registration not found")
        return self._run_row(row)

    def apply_runtime_lifecycle_event(self, event: object, *, trusted_owner: str, trusted_workspace: str,
                                     trusted_session_id: str, trusted_trace_id: str,
                                     trusted_boot_id: str | None = None, _connection=None) -> dict[str, object]:
        """Consume only a trusted BYQ projection; not a Product/model command.

        Terminal receipt, bindings, AgentRun updates and audits share one
        transaction. A delayed registration can never reopen a terminal root.
        """
        event = validate_lifecycle_event(event)
        owner = _principal(trusted_owner, field="owner_principal")
        workspace = _trace(trusted_workspace, field="workspace_id")
        session = _trace(trusted_session_id, field="session_id")
        trace = _trace(trusted_trace_id, field="trace_id")
        if trusted_boot_id is not None:
            trusted_boot_id = _runtime_boot_id(trusted_boot_id)
        root_id, outcome = event["root_run_id"], event["outcome"]
        fingerprint = event.get("registration_fingerprint")
        with (nullcontext(_connection) if _connection is not None else self._transaction()) as connection:
            self._lifecycle_lock(connection, "runtime-authority:current")
            authority = self._require_current_runtime_boot(connection, trusted_boot_id)
            active_identity = self._require_lifecycle_workspace(connection, owner, workspace,
                                                               terminal_cleanup=outcome != "active")
            self._lifecycle_lock(connection, "root:" + root_id)
            root = fetch_one(connection, "SELECT * FROM agent_runtime_turns WHERE root_run_id=:id", {"id": root_id})
            if root and (root["owner_principal"], root["workspace_id"], root["session_id"], root["trace_id"]) != (owner, workspace, session, trace):
                raise AgentUnauthorized("runtime root does not match trusted context")
            if root and authority is not None:
                if root["authority_status"] == "authority_revoked_unconfirmed" or root["authority_boot_id"] != authority["boot_id"]:
                    raise AgentConflict("runtime root belongs to a superseded boot")
                # An exact same-boot terminal replay is checked against its
                # original receipt below. Closing business authority must not
                # make that idempotent acknowledgement impossible.
            if root is None:
                if not active_identity:
                    raise AgentUnauthorized("disabled identity cannot create a runtime root")
                execute(connection, """INSERT INTO agent_runtime_turns
                    (root_run_id, owner_principal, workspace_id, session_id, trace_id, status,
                     authority_status,authority_boot_id,created_at,updated_at)
                    VALUES (:id,:owner,:workspace,:session,:trace,'active','active',:boot_id,:now,:now)""",
                    {"id": root_id, "owner": owner, "workspace": workspace, "session": session,
                     "trace": trace, "boot_id": authority["boot_id"] if authority is not None else None,
                     "now": _now()})
                root = fetch_one(connection, "SELECT * FROM agent_runtime_turns WHERE root_run_id=:id", {"id": root_id})
            assert root is not None
            if outcome == "active" and fingerprint is None:
                # A plain Agent turn opens its exact root before any domain
                # AgentRun registration. It grants no AgentRun business call.
                if root["status"] != "active" or root["authority_status"] != "active":
                    raise AgentConflict("runtime root is no longer active")
                return dict(root)
            if fingerprint:
                self._lifecycle_lock(connection, "registration:" + fingerprint)
                previous = fetch_one(connection, "SELECT * FROM agent_runtime_registrations WHERE registration_fingerprint=:fp", {"fp": fingerprint})
                if previous and previous["root_run_id"] != root_id:
                    raise AgentConflict("runtime registration cannot move to another root")
                execute(connection, """INSERT INTO agent_runtime_registrations (registration_fingerprint,root_run_id)
                    VALUES (:fp,:id) ON CONFLICT (registration_fingerprint) DO NOTHING""", {"fp": fingerprint, "id": root_id})
                changed = execute(connection, """UPDATE agent_runs r SET root_run_id=:id,
                        status=CASE WHEN r.parent_run_id IS NOT NULL AND NOT EXISTS (
                            SELECT 1 FROM agent_runs p WHERE p.run_id=r.parent_run_id AND p.root_run_id=:id
                        ) THEN 'failed' ELSE :status END,
                        authority_status=CASE WHEN :authority_status='closed' THEN 'closed' ELSE r.authority_status END,
                        authority_boot_id=COALESCE(:boot_id,r.authority_boot_id),
                        updated_at=:now,version=version+1
                    WHERE runtime_registration_fingerprint=:fp AND owner_principal=:owner AND workspace_id=:workspace
                      AND session_id=:session AND trace_id=:trace AND root_run_id IS NULL
                      AND authority_status='active' AND status IN ('pending_binding','active') RETURNING *""",
                    {"id": root_id, "status": root["status"], "authority_status": root["authority_status"],
                     "now": _now(), "fp": fingerprint,
                     "boot_id": authority["boot_id"] if authority is not None else None,
                     "owner": owner, "workspace": workspace, "session": session, "trace": trace})
            else:
                if root["status"] != "active":
                    if (root["status"] != outcome or root["terminal_sequence"] != event["sequence"]
                            or (root.get("terminal_event_sha256") is not None
                                and root["terminal_event_sha256"] != lifecycle_receipt(event)["event_sha256"])):
                        raise AgentConflict("runtime terminal evidence conflicts with its original receipt")
                    return dict(root)
                # Freeze registrations against concurrent start_run inserts.
                bindings = execute(connection, """SELECT registration_fingerprint FROM agent_runtime_registrations
                    WHERE root_run_id=:id ORDER BY registration_fingerprint""", {"id": root_id})
                for binding in bindings:
                    self._lifecycle_lock(connection, "registration:" + binding["registration_fingerprint"])
                execute(connection, """UPDATE agent_runtime_turns SET status=:status,authority_status='closed',
                    terminal_sequence=:sequence,terminal_event_sha256=:digest,updated_at=:now
                    WHERE root_run_id=:id""",
                    {"status": outcome, "sequence": event["sequence"], "digest": lifecycle_receipt(event)["event_sha256"],
                     "now": _now(), "id": root_id})
                root = fetch_one(connection, "SELECT * FROM agent_runtime_turns WHERE root_run_id=:id", {"id": root_id})
                changed = execute(connection, """UPDATE agent_runs SET status=:status,authority_status='closed',
                    updated_at=:now,version=version+1
                    WHERE root_run_id=:id AND authority_status='active' AND status IN ('active','pending_binding') RETURNING *""",
                    {"status": outcome, "now": _now(), "id": root_id})
            for run in changed:
                self._record_runtime_binding_audit(connection, run, root)
        return dict(root)

    def _check_agent_run_authority(self, connection, row: dict[str, Any], authority,
                                   trusted_boot_id: str | None) -> None:
        if row.get("authority_status", "active") != "active":
            raise AgentForbidden("agent run business authority is no longer active")
        if authority is None:
            return
        if row.get("authority_boot_id") != authority["boot_id"]:
            raise AgentForbidden("agent run belongs to a superseded runtime boot")
        root_id = row.get("root_run_id")
        if root_id is not None:
            root = fetch_one(connection, "SELECT * FROM agent_runtime_turns WHERE root_run_id=:id",
                             {"id": root_id})
            if (root is None or root["status"] != "active" or root["authority_status"] != "active"
                    or root["authority_boot_id"] != authority["boot_id"]):
                raise AgentForbidden("agent run root no longer has current business authority")

    def authorize(self, payload: object, *, trusted_owner: str | None = None, trusted_actor: str | None = None,
                  trusted_session_id: str | None = None, trusted_dsh_run_id: str | None = None,
                  trusted_boot_id: str | None = None) -> dict[str, object]:
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
        if trusted_boot_id is not None:
            trusted_boot_id = _runtime_boot_id(trusted_boot_id)
        with self._transaction() as connection:
            self._lifecycle_lock(connection, "runtime-authority:current")
            authority = self._require_current_runtime_boot(connection, trusted_boot_id)
            row = fetch_one(connection, "SELECT * FROM agent_runs WHERE run_id = :run_id", {"run_id": run_id})
            if row is None:
                raise AgentNotFound("agent run not found")
            self._check_run_access(row, trusted_owner=trusted_owner, trusted_actor=trusted_actor)
            self._check_agent_run_authority(connection, row, authority, trusted_boot_id)
            self._check_runtime_context(row, trusted_session_id, trusted_dsh_run_id)
            role = ROLE_BY_ID[row["role_id"]]
            index_action = action in {"byq_index_pool_catalog", "byq_index_pool_create", "byq_index_pool_status"}
            if action not in role.allowed_tools or (index_action and row["role_version"] != "2.1.0"):
                self._record_audit_row(row, action=action, outcome="denied", resource_type=resource_type,
                    resource_id=resource_id, detail={"reason": "role_tool_not_allowed"}, connection=connection)
                raise AgentForbidden("agent role is not authorized for this domain action")
            requires_approval = action in role.approval_required_actions
            result = {
                "authorized": not requires_approval,
                "decision": "approval_required" if requires_approval else "allowed",
                "run_id": run_id,
                "role_id": row["role_id"],
                "action": action,
            }
            self._record_audit_row(row, action=action,
                outcome="approval_required" if requires_approval else "authorized",
                resource_type=resource_type, resource_id=resource_id, detail=result, connection=connection)
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

    def create_approval(self, payload: object, *, trusted_owner: str | None = None, trusted_actor: str | None = None,
                        trusted_session_id: str | None = None, trusted_dsh_run_id: str | None = None,
                        trusted_boot_id: str | None = None) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("agent approval request must be an object")
        allowed = {"run_id", "action", "reason", "resource_type", "resource_id", "idempotency_key"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"agent approval request has unknown fields: {', '.join(unknown)}")
        run_id = _entity_id(payload.get("run_id"), field="run_id", prefix="agent_run")
        action = _text(payload.get("action"), field="action", max_length=128)
        reason = _text(payload.get("reason"), field="reason", max_length=2000)
        resource_type = (
            _text(payload.get("resource_type"), field="resource_type", max_length=64)
            if payload.get("resource_type") is not None else None
        )
        resource_id = (
            _text(payload.get("resource_id"), field="resource_id", max_length=128)
            if payload.get("resource_id") is not None else None
        )
        if (resource_type is None) != (resource_id is None):
            raise ValueError("resource_type and resource_id must be provided together")
        # Approval and execution must agree before asking a human to approve.
        # Never reinterpret existing approvals or weaken execution-time binding.
        expected_resource = APPROVAL_RESOURCE_TYPES.get(action)
        if expected_resource and (resource_type != expected_resource or resource_id is None):
            raise ValueError(f"{action} requires resource_type={expected_resource} and resource_id")
        key = _idempotency(payload.get("idempotency_key"))
        if trusted_boot_id is not None:
            trusted_boot_id = _runtime_boot_id(trusted_boot_id)
        with self._transaction() as connection:
            self._lifecycle_lock(connection, "runtime-authority:current")
            authority = self._require_current_runtime_boot(connection, trusted_boot_id)
            run = fetch_one(connection, "SELECT * FROM agent_runs WHERE run_id = :run_id", {"run_id": run_id})
            if run is None:
                raise AgentNotFound("agent run not found")
            self._check_run_access(run, trusted_owner=trusted_owner, trusted_actor=trusted_actor)
            self._check_agent_run_authority(connection, run, authority, trusted_boot_id)
            self._check_runtime_context(run, trusted_session_id, trusted_dsh_run_id)
            role = ROLE_BY_ID[run["role_id"]]
            if action not in role.approval_required_actions:
                raise AgentForbidden("agent action does not require or support this approval boundary")
            request = {
                "run_id": run_id, "action": action, "reason": reason,
                "resource_type": resource_type, "resource_id": resource_id,
                "idempotency_key": key,
            }
            request_hash = _hash(request)
            existing = fetch_one(
                connection,
                """SELECT approvals.*, runs.session_id AS source_session_id
                   FROM agent_approvals approvals JOIN agent_runs runs ON runs.run_id=approvals.run_id
                   WHERE approvals.run_id = :run_id AND approvals.idempotency_key = :key""",
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
                 resource_type, resource_id,
                 status, decision_by, decision_reason, execution_outcome,
                 continuation_status, idempotency_key, request_hash, created_at, updated_at)
                VALUES (:approval_id, :run_id, :owner_principal, :actor_principal, :action, :reason,
                        :resource_type, :resource_id,
                        'pending', NULL, NULL, 'not_started', 'not_requested',
                        :key, :request_hash, :created_at, :updated_at)""",
                {"approval_id": approval_id, "run_id": run_id, "owner_principal": run["owner_principal"],
                 "actor_principal": run["actor_principal"], "action": action, "reason": reason,
                 "resource_type": resource_type, "resource_id": resource_id,
                 "key": key, "request_hash": request_hash, "created_at": now, "updated_at": now},
            )
            row = fetch_one(
                connection,
                """SELECT approvals.*, runs.session_id AS source_session_id
                   FROM agent_approvals approvals JOIN agent_runs runs ON runs.run_id=approvals.run_id
                   WHERE approvals.approval_id=:approval_id FOR UPDATE OF approvals""",
                {"approval_id": approval_id},
            )
            assert row is not None
            # ADR-0085 §3: mint the exact plan-command binding SERVER-SIDE, now, if
            # this approval is the current gate of an existing plan. The binding
            # is never supplied by the caller and is frozen at request time, so an
            # unused older approval can never authorize a later changed plan.
            binding = self._mint_plan_command_binding(connection, row)
            if binding is not None:
                execute(connection, """UPDATE agent_approvals SET
                    plan_task_id=:task, plan_workspace_id=:workspace, plan_version=:plan_version,
                    plan_task_version=:task_version, plan_action=:action,
                    plan_resource_kind=:resource_kind, plan_resource_id=:resource_id,
                    plan_params_digest=:digest, plan_idempotency_key=:key
                    WHERE approval_id=:approval_id""", {**binding, "approval_id": approval_id})
                row = fetch_one(
                    connection,
                    """SELECT approvals.*, runs.session_id AS source_session_id
                       FROM agent_approvals approvals JOIN agent_runs runs ON runs.run_id=approvals.run_id
                       WHERE approvals.approval_id=:approval_id""",
                    {"approval_id": approval_id},
                )
                assert row is not None
            self._record_audit_row(run, action="approval.request", outcome="pending", resource_type="agent_approval", resource_id=approval_id, detail={"action": action}, connection=connection)
        return self._approval_row(row)

    def decide_approval(self, payload: object, *, trusted_owner: str | None = None,
                        trusted_actor: str | None = None,
                        trusted_workspace: str | None = None) -> dict[str, object]:
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

        # Binding presence is checked before decision eligibility. A stale or
        # partial frozen plan binding is never allowed to fall through to the
        # generic approval continuation path.
        pre_row = self._fetch_one(
            """SELECT approvals.*, runs.session_id AS source_session_id,
                      runs.owner_principal AS run_owner,
                      to_jsonb(approvals)->>'workspace_id' AS approval_workspace,
                      to_jsonb(runs)->>'workspace_id' AS run_workspace
               FROM agent_approvals approvals JOIN agent_runs runs ON runs.run_id=approvals.run_id
               WHERE approvals.approval_id=:approval_id""", {"approval_id": approval_id})
        if pre_row is None:
            raise AgentNotFound("agent approval not found")
        if trusted_owner and pre_row["owner_principal"] != trusted_owner:
            raise AgentUnauthorized("agent approval is not owned by this principal")
        is_plan_bound = any(pre_row.get(field) is not None for field in _PLAN_BINDING_FIELDS)
        if is_plan_bound:
            frozen = approval_plan_binding(pre_row)
            if frozen is None:
                raise AgentConflict("frozen plan approval binding is incomplete")
            if (pre_row.get("approval_workspace") != frozen["workspace"]
                    or pre_row.get("run_workspace") != frozen["workspace"]
                    or (trusted_workspace and trusted_workspace != frozen["workspace"])):
                raise AgentUnauthorized("agent approval is not bound to this workspace")
            if not self._research_task_actions_available():
                raise AgentConflict("frozen plan approval business-action storage is unavailable")
            return self._decide_plan_bound_approval(
                approval_id, decision, rationale, reviewer, trusted_owner,
                trusted_workspace, pre_row, frozen)
        if trusted_workspace and any(
            workspace is not None and workspace != trusted_workspace
            for workspace in (pre_row.get("approval_workspace"), pre_row.get("run_workspace"))
        ):
            raise AgentUnauthorized("agent approval is not in this workspace")

        with self._transaction() as connection:
            row = fetch_one(
                connection,
                """SELECT approvals.*, runs.session_id AS source_session_id,
                          runs.owner_principal AS run_owner,
                          to_jsonb(approvals)->>'workspace_id' AS approval_workspace,
                          to_jsonb(runs)->>'workspace_id' AS run_workspace
                   FROM agent_approvals approvals JOIN agent_runs runs ON runs.run_id=approvals.run_id
                   WHERE approvals.approval_id=:approval_id FOR UPDATE OF approvals""",
                {"approval_id": approval_id},
            )
            if row is None:
                raise AgentNotFound("agent approval not found")
            if trusted_owner and row["owner_principal"] != trusted_owner:
                raise AgentUnauthorized("agent approval is not owned by this principal")
            if any(row.get(field) is not None for field in _PLAN_BINDING_FIELDS):
                raise AgentConflict("approval acquired a frozen plan binding while locking")
            if trusted_workspace and any(
                workspace is not None and workspace != trusted_workspace
                for workspace in (row.get("approval_workspace"), row.get("run_workspace"))
            ):
                raise AgentUnauthorized("agent approval is not in this workspace")
            if reviewer == row["actor_principal"]:
                raise AgentForbidden("agent actor cannot self-approve a consequential action")
            if row["status"] != "pending":
                if row["status"] != decision or (row.get("decision_reason") or "") != rationale:
                    raise AgentConflict("approval decision replay conflicts with the recorded decision")
                return self._approval_row(row)
            now = _now()
            status = "approved" if decision == "approved" else "rejected"
            outcome = "authorized" if status == "approved" else "not_authorized"
            execute(
                connection,
                "UPDATE agent_approvals SET status = :status, decision_by = :decision_by, decision_reason = :decision_reason, execution_outcome = :execution_outcome, continuation_status = 'queued', updated_at = :updated_at WHERE approval_id = :approval_id",
                {"status": status, "decision_by": reviewer, "decision_reason": rationale, "execution_outcome": outcome, "updated_at": now, "approval_id": approval_id},
            )
            updated = fetch_one(
                connection,
                """SELECT approvals.*, runs.session_id AS source_session_id
                   FROM agent_approvals approvals JOIN agent_runs runs ON runs.run_id=approvals.run_id
                   WHERE approvals.approval_id=:approval_id""",
                {"approval_id": approval_id},
            )
            assert updated is not None
            run = fetch_one(connection, "SELECT * FROM agent_runs WHERE run_id = :run_id", {"run_id": row["run_id"]})
            assert run is not None
            self._record_audit_row(run, action="approval.decision", outcome=status, resource_type="agent_approval", resource_id=approval_id, detail={"reviewer": reviewer, "decision": decision}, connection=connection)
        return self._approval_row(updated)

    def _decide_plan_bound_approval(
        self, approval_id: str, decision: str, rationale: str, reviewer: str,
        trusted_owner: str | None, trusted_workspace: str | None,
        pre_row: dict, frozen: dict,
    ) -> dict[str, object]:
        with self._transaction() as connection:
            task = fetch_one(connection, """SELECT * FROM research_tasks
                WHERE task_id = :task AND owner_principal = :owner
                  AND workspace_id = :workspace FOR UPDATE""",
                {"task": frozen["task_id"], "owner": pre_row["owner_principal"],
                 "workspace": frozen["workspace"]})
            if task is None:
                raise AgentConflict("frozen plan approval task no longer exists")
            plan_row = fetch_one(connection, """SELECT * FROM research_execution_plans
                WHERE task_id = :task FOR UPDATE""", {"task": frozen["task_id"]})
            row = fetch_one(connection, """SELECT approvals.*, runs.session_id AS source_session_id,
                      runs.owner_principal AS run_owner,
                      to_jsonb(approvals)->>'workspace_id' AS approval_workspace,
                      to_jsonb(runs)->>'workspace_id' AS run_workspace
                FROM agent_approvals approvals JOIN agent_runs runs ON runs.run_id=approvals.run_id
                WHERE approvals.approval_id=:approval_id FOR UPDATE OF approvals""",
                {"approval_id": approval_id})
            if row is None:
                raise AgentNotFound("agent approval not found")
            if (row["owner_principal"] != pre_row["owner_principal"]
                    or row["run_owner"] != row["owner_principal"]
                    or row.get("approval_workspace") != frozen["workspace"]
                    or row.get("run_workspace") != frozen["workspace"]
                    or (trusted_workspace and frozen["workspace"] != trusted_workspace)
                    or (trusted_owner and row["owner_principal"] != trusted_owner)):
                raise AgentUnauthorized("agent approval is not owned by this principal")
            if any(row.get(field) != pre_row.get(field) for field in _PLAN_BINDING_FIELDS):
                raise AgentConflict("frozen plan approval binding changed while acquiring locks")
            locked_binding = approval_plan_binding(row)
            if locked_binding is None or locked_binding != frozen:
                raise AgentConflict("frozen plan approval binding is incomplete or changed")
            existing = fetch_one(connection, """SELECT * FROM research_task_actions
                WHERE source_approval_id = :approval FOR UPDATE""", {"approval": approval_id})
            if reviewer == row["actor_principal"]:
                raise AgentForbidden("agent actor cannot self-approve a consequential action")

            if row["status"] != "pending":
                if row["status"] != decision or (row.get("decision_reason") or "") != rationale:
                    raise AgentConflict("approval decision replay conflicts with the recorded decision")
                if row["status"] not in {"approved", "rejected"} or existing is None:
                    raise AgentConflict("decided plan approval has no exact business action")
                if (existing["source_digest"] != approval_source_digest(row)
                        or existing["request_digest"] != approval_decision_digest(
                            approval_id, decision, rationale)
                        or existing["decision"] != decision):
                    raise AgentConflict("approval source or canonical request digest changed")
                return self._approval_with_action(row, existing)

            if existing is not None:
                raise AgentConflict("pending plan approval already has a business action")
            if not self._validate_plan_approval_binding(connection, row, task, plan_row, locked_binding):
                raise AgentConflict("frozen plan approval binding is stale or does not match its gate")

            now = _now()
            status = "approved" if decision == "approved" else "rejected"
            outcome = "authorized" if status == "approved" else "not_authorized"
            execute(connection, """UPDATE agent_approvals SET status = :status,
                decision_by = :decision_by, decision_reason = :decision_reason,
                execution_outcome = :execution_outcome, continuation_status = 'blocked',
                updated_at = :updated_at WHERE approval_id = :approval_id""", {
                "status": status, "decision_by": reviewer, "decision_reason": rationale,
                "execution_outcome": outcome, "updated_at": now, "approval_id": approval_id,
            })
            updated = fetch_one(connection, """SELECT approvals.*, runs.session_id AS source_session_id,
                      runs.owner_principal AS run_owner,
                      runs.workspace_id AS run_workspace
                FROM agent_approvals approvals JOIN agent_runs runs ON runs.run_id=approvals.run_id
                WHERE approvals.approval_id=:approval_id""", {"approval_id": approval_id})
            assert updated is not None
            action = insert_pending_approval_action(
                connection, updated, binding=locked_binding, decision=status,
                rationale=rationale, now=now)
            run = fetch_one(connection, "SELECT * FROM agent_runs WHERE run_id = :run_id",
                            {"run_id": row["run_id"]})
            assert run is not None
            self._record_audit_row(run, action="approval.decision", outcome=status,
                resource_type="agent_approval", resource_id=approval_id,
                detail={"reviewer": reviewer, "decision": decision,
                        "business_action_id": action["action_id"]}, connection=connection)
            return self._approval_with_action(updated, action)

    @staticmethod
    def _validate_plan_approval_binding(connection, approval, task, plan_row, binding) -> bool:
        if plan_row is None or approval["run_owner"] != task["owner_principal"]:
            return False
        if (task["workspace_id"] != binding["workspace"]
                or approval["owner_principal"] != task["owner_principal"]
                or plan_row["owner_principal"] != task["owner_principal"]
                or plan_row["workspace_id"] != task["workspace_id"]):
            return False
        from packages.contracts.research_execution_plan import validate_plan
        plan = validate_plan(plan_row["plan"])
        if (plan["task_id"] != task["task_id"] or plan["owner_principal"] != task["owner_principal"]
                or plan["workspace_id"] != task["workspace_id"]
                or int(plan["task_version"]) != int(task["version"])
                or int(plan_row["plan_version"]) != int(plan["plan_version"])
                or int(plan_row["task_version"]) != int(plan["task_version"])
                or plan_row["stage"] != plan["stage"]
                or (binding["plan_version"], binding["task_version"])
                    != (plan["plan_version"], plan["task_version"])):
            return False
        pending = plan.get("approval")
        if (not isinstance(pending, dict)
                or (binding["action"], binding["resource_kind"], binding["resource_id"])
                   != (pending.get("action"), pending.get("resource_kind"), pending.get("resource_id"))
                or approval.get("action") != PLAN_APPROVAL_ACTION.get(binding["action"])
                or approval.get("resource_type") != binding["resource_kind"]
                or approval.get("resource_id") != binding["resource_id"]):
            return False
        reference = (plan.get("references") or {}).get(binding["resource_kind"])
        if not isinstance(reference, dict) or reference.get(binding["resource_kind"]) != binding["resource_id"]:
            return False
        if binding["resource_kind"] in {"strategy_version", "strategy_approval"}:
            artifact = fetch_one(connection, """SELECT artifact_id FROM artifacts
                WHERE artifact_id = :id AND task_id = :task AND owner_principal = :owner
                  AND workspace_id = :workspace""", {
                "id": binding["resource_id"], "task": task["task_id"],
                "owner": task["owner_principal"], "workspace": task["workspace_id"],
            })
            if artifact is None:
                return False
        try:
            digest = plan_command_digest(plan, action=binding["action"],
                resource_kind=binding["resource_kind"], resource_id=binding["resource_id"])
            key = plan_command_idempotency_key(plan, action=binding["action"],
                resource_kind=binding["resource_kind"], resource_id=binding["resource_id"])
        except ValueError:
            return False
        return binding["params_digest"] == digest and binding["idempotency_key"] == key

    def get_approval(self, approval_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        approval_id = _entity_id(approval_id, field="approval_id", prefix="agent_approval")
        row = self._fetch_one(
            """SELECT approvals.*, runs.session_id AS source_session_id,
                      runs.owner_principal AS run_owner,
                      to_jsonb(approvals)->>'workspace_id' AS approval_workspace,
                      to_jsonb(runs)->>'workspace_id' AS run_workspace
               FROM agent_approvals approvals
               JOIN agent_runs runs ON runs.run_id = approvals.run_id
               WHERE approvals.approval_id = :approval_id""",
            {"approval_id": approval_id},
        )
        if row is None:
            raise AgentNotFound("agent approval not found")
        if trusted_owner and row["owner_principal"] != trusted_owner:
            raise AgentUnauthorized("agent approval is not owned by this principal")
        return self._approval_with_action(row, self._read_approval_business_action(row))

    def _research_task_actions_available(self) -> bool:
        relation = self._fetch_one(
            "SELECT to_regclass('research_task_actions') IS NOT NULL AS available")
        return bool(relation and relation.get("available"))

    def _read_approval_business_action(self, approval: dict[str, Any]) -> dict | None:
        """Read an action only for a complete, frozen plan-bound approval."""

        has_frozen_binding = any(
            approval.get(field) is not None for field in _PLAN_BINDING_FIELDS)
        if not has_frozen_binding:
            return None
        binding = approval_plan_binding(approval)
        if binding is None:
            raise AgentConflict("frozen plan approval binding is incomplete")
        if (approval.get("approval_workspace") != binding["workspace"]
                or approval.get("run_workspace") != binding["workspace"]
                or approval.get("run_owner") != approval.get("owner_principal")):
            raise AgentConflict("frozen plan approval owner or workspace binding is inconsistent")
        if not self._research_task_actions_available():
            raise AgentPersistenceError(
                "frozen plan approval business-action storage is unavailable")
        action = self._fetch_one("""SELECT * FROM research_task_actions
            WHERE source_approval_id = :approval AND owner_principal = :owner""",
            {"approval": approval["approval_id"], "owner": approval["owner_principal"]})
        if action is None:
            if approval.get("status") != "pending":
                raise AgentConflict("decided plan approval has no exact business action")
            return None
        expected = {
            "task_id": binding["task_id"], "workspace_id": binding["workspace"],
            "plan_version": binding["plan_version"], "task_version": binding["task_version"],
            "action": binding["action"], "resource_kind": binding["resource_kind"],
            "resource_id": binding["resource_id"], "params_digest": binding["params_digest"],
            "idempotency_key": binding["idempotency_key"],
            "source_digest": approval_source_digest(approval),
        }
        if any(action.get(field) != value for field, value in expected.items()):
            raise AgentConflict("business action does not match its frozen approval")
        if (approval.get("status") not in {"approved", "rejected"}
                or action.get("decision") != approval.get("status")
                or action.get("request_digest") != approval_decision_digest(
                    approval["approval_id"], approval["status"],
                    approval.get("decision_reason") or "")):
            raise AgentConflict("business action does not match the recorded approval decision")
        return action

    def list_approvals(
        self, *, trusted_owner: str | None = None, status: str | None = None,
        limit: int = 50, offset: int = 0,
    ) -> dict[str, object]:
        if status not in {None, "pending", "approved", "rejected"}:
            raise ValueError("approval status is invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("approval limit must be between 1 and 100")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 10_000:
            raise ValueError("approval offset must be between 0 and 10000")
        clauses: list[str] = []
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if trusted_owner:
            clauses.append("approvals.owner_principal = :owner_principal")
            params["owner_principal"] = trusted_owner
        if status:
            clauses.append("approvals.status = :status")
            params["status"] = status
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._execute(
            f"""SELECT approvals.*, runs.session_id AS source_session_id,
                       runs.owner_principal AS run_owner,
                       to_jsonb(approvals)->>'workspace_id' AS approval_workspace,
                       to_jsonb(runs)->>'workspace_id' AS run_workspace
                FROM agent_approvals approvals
                JOIN agent_runs runs ON runs.run_id = approvals.run_id
                {where}
                ORDER BY approvals.created_at DESC, approvals.approval_id DESC
                LIMIT :limit OFFSET :offset""",
            params,
        )
        total_row = self._fetch_one(
            f"SELECT COUNT(*) AS total FROM agent_approvals approvals {where}", params,
        )
        pending_clauses = [clause for clause in clauses if "approvals.status" not in clause]
        pending_clauses.append("approvals.status = 'pending'")
        pending_where = f"WHERE {' AND '.join(pending_clauses)}"
        pending_row = self._fetch_one(
            f"SELECT COUNT(*) AS total FROM agent_approvals approvals {pending_where}", params,
        )
        return {
            "approvals": [self._approval_with_action(
                row, self._read_approval_business_action(row)) for row in rows],
            "total": int((total_row or {}).get("total", 0)),
            "pending_count": int((pending_row or {}).get("total", 0)),
            "limit": limit,
            "offset": offset,
        }

    def set_continuation_status(
        self, approval_id: object, status: object, *, trusted_owner: str, expected_attempt: int | None = None,
    ) -> dict[str, object]:
        approval_id = _entity_id(approval_id, field="approval_id", prefix="agent_approval")
        next_status = _text(status, field="continuation_status", max_length=32)
        if next_status not in {"submitting", "submitted", "failed", "outcome_unknown"}:
            raise ValueError("continuation status is invalid")
        if next_status != "submitting" and (type(expected_attempt) is not int or expected_attempt < 1):
            raise ValueError("continuation completion requires its claimed attempt")
        with self._transaction() as connection:
            row = fetch_one(
                connection,
                "SELECT * FROM agent_approvals WHERE approval_id = :approval_id FOR UPDATE",
                {"approval_id": approval_id},
            )
            if row is None:
                raise AgentNotFound("agent approval not found")
            if row["owner_principal"] != trusted_owner:
                raise AgentUnauthorized("agent approval is not owned by this principal")
            current = str(row.get("continuation_status") or "not_requested")
            updated_at = row.get("updated_at")
            stale_submission = False
            if current == "submitting" and next_status == "submitting":
                if isinstance(updated_at, str):
                    try:
                        updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    except ValueError:
                        updated_at = None
                if isinstance(updated_at, datetime):
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=timezone.utc)
                    stale_submission = (
                        datetime.now(timezone.utc) - updated_at.astimezone(timezone.utc)
                    ).total_seconds() >= 30
            allowed = {
                "submitting": {"queued", "failed"},
                "submitted": {"submitting", "outcome_unknown"},
                "failed": {"submitting"},
                "outcome_unknown": {"submitting"},
            }
            # Expiry proves the caller disappeared, not that the prompt was
            # never accepted. Do not reclaim and potentially execute twice.
            blocked_state = None
            if stale_submission:
                blocked_state = "outcome_unknown"
            elif next_status == "submitting" and current in {"queued", "failed"} and int(row.get("continuation_attempt") or 0) >= 8:
                blocked_state = "needs_attention"
            expected_resource = APPROVAL_RESOURCE_TYPES.get(row['action'])
            invalid_binding = (next_status == 'submitting' and current in {'queued', 'failed'}
                and row['status'] == 'approved' and expected_resource is not None
                and (row.get('resource_type') != expected_resource or not row.get('resource_id')))
            if invalid_binding:
                blocked_state = 'needs_attention'
                self._record_approval_binding_blocker(connection, row, expected_resource)
            if blocked_state:
                execute(connection, "UPDATE agent_approvals SET continuation_status=:status,updated_at=:now WHERE approval_id=:id",
                        {"status": blocked_state, "now": _now(), "id": approval_id})
            changed = current in allowed[next_status] and blocked_state is None
            if next_status != "submitting" and expected_attempt != int(row.get("continuation_attempt") or 0):
                changed = False
            if changed:
                attempt = int(row.get("continuation_attempt") or 0) + (1 if next_status == "submitting" else 0)
                execute(
                    connection,
                    "UPDATE agent_approvals SET continuation_status=:status, continuation_attempt=:attempt, updated_at=:updated_at WHERE approval_id=:approval_id",
                    {"status": next_status, "attempt": attempt, "updated_at": _now(), "approval_id": approval_id},
                )
            updated = fetch_one(
                connection,
                """SELECT approvals.*, runs.session_id AS source_session_id
                   FROM agent_approvals approvals JOIN agent_runs runs ON runs.run_id=approvals.run_id
                   WHERE approvals.approval_id=:approval_id""",
                {"approval_id": approval_id},
            )
            assert updated is not None
        return {**self._approval_row(updated), "continuation_changed": changed}

    @staticmethod
    def _mint_plan_command_binding(connection, approval):
        """Mint the exact plan-command binding for a plan-gate approval.

        ADR-0085 §3/P2: a plan-bound human approval must bind the EXACT plan
        command at request time. This resolves the SINGLE current plan whose
        approval requirement exactly matches the approval's action/resource and
        returns a version-, parameter- and idempotency-bound record. An approval
        that does not match exactly one current plan requirement is a compat
        approval and gets no binding. The binding is never caller-supplied.
        """

        plan_action = AGENT_APPROVAL_PLAN_ACTION.get(approval.get("action"))
        resource_type = approval.get("resource_type")
        resource_id = approval.get("resource_id")
        if plan_action is None or not isinstance(resource_type, str) or not isinstance(resource_id, str):
            return None
        rows = execute(connection, """SELECT p.task_id, p.workspace_id, p.plan
            FROM research_execution_plans p
            JOIN research_tasks t ON t.task_id = p.task_id
            WHERE p.owner_principal = :owner AND t.owner_principal = :owner
              AND p.plan -> 'approval' ->> 'action' = :plan_action
              AND p.plan -> 'approval' ->> 'resource_kind' = :resource_type
              AND p.plan -> 'approval' ->> 'resource_id' = :resource_id
              AND p.plan -> 'references' -> CAST(:resource_type AS text)
                    ->> CAST(:resource_type AS text) = :resource_id
            LIMIT 2""",
            {"owner": approval["owner_principal"], "plan_action": plan_action,
             "resource_type": resource_type, "resource_id": resource_id})
        if not rows or len(rows) != 1:
            return None
        plan = rows[0]["plan"]
        try:
            digest = plan_command_digest(
                plan, action=plan_action, resource_kind=resource_type, resource_id=resource_id)
            key = plan_command_idempotency_key(
                plan, action=plan_action, resource_kind=resource_type, resource_id=resource_id)
        except ValueError:
            return None
        return {
            "task": rows[0]["task_id"], "workspace": rows[0]["workspace_id"],
            "plan_version": plan["plan_version"], "task_version": plan["task_version"],
            "action": plan_action, "resource_kind": resource_type, "resource_id": resource_id,
            "digest": digest, "key": key,
        }

    def _record_approval_binding_blocker(self, connection, approval, expected_resource):
        # Only the explicitly linked task waiting on this same resource is
        # affected. Never choose a task by recency or rewrite a domain status.
        if expected_resource not in {'strategy_version', 'ml_strategy_version'}:
            return
        execute(connection, """UPDATE research_tasks t
            SET progress = t.progress || CAST(:checkpoint AS jsonb), updated_at=:now, version=t.version+1
            FROM artifacts a, agent_runs r, product_conversations c
            WHERE a.artifact_id=:resource AND a.kind=:kind AND a.task_id=t.task_id
              AND a.owner_principal=t.owner_principal AND a.workspace_id=t.workspace_id
              AND r.run_id=:run AND r.owner_principal=t.owner_principal AND r.workspace_id=t.workspace_id
              AND t.owner_principal=:owner AND t.conversation_id=c.conversation_id
              AND c.owner_principal=t.owner_principal AND c.workspace_id=t.workspace_id
              AND c.runtime_session_id=r.session_id AND c.trace_id=r.trace_id
              AND t.status IN ('planned','running') AND t.progress->>'stage'='approval'
              AND t.progress->'linked_objects' @> CAST(:linked AS jsonb)""",
            {'resource': approval.get('resource_id'), 'kind': expected_resource,
             'run': approval['run_id'], 'owner': approval['owner_principal'], 'now': _now(),
             'linked': json.dumps([{'kind': 'artifact', 'id': approval.get('resource_id')}]),
             'checkpoint': json.dumps({'stage': 'blocked',
                 'blocked_reason': '审批资源类型与执行动作不匹配，尚未执行策略审批。',
                 'next_action': '按准确的策略版本重新申请审批；旧审批不能作为执行授权。'})})
        run = fetch_one(connection, 'SELECT * FROM agent_runs WHERE run_id=:id', {'id': approval['run_id']})
        self._record_audit_row(run, action='approval.continuation', outcome='blocked',
            resource_type='agent_approval', resource_id=approval['approval_id'],
            detail={'reason': 'approval_resource_mismatch'}, connection=connection)

    @staticmethod
    def _check_runtime_context(row: dict[str, Any], session_id: str | None, generation_id: str | None) -> None:
        if ((session_id is not None and row["session_id"] != session_id)
                or (generation_id is not None and row["dsh_run_id"] != generation_id)):
            raise AgentForbidden("agent run does not belong to this runtime context")

    def _check_run_access(self, row: dict[str, Any], *, trusted_owner: str | None, trusted_actor: str | None) -> None:
        if trusted_owner and row["owner_principal"] != trusted_owner:
            raise AgentUnauthorized("agent run is not owned by this principal")
        if trusted_actor and row["actor_principal"] != trusted_actor:
            raise AgentUnauthorized("agent actor does not match the active run")
        if row["status"] != "active" or row.get("authority_status", "active") != "active":
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
        result.pop("runtime_registration_fingerprint", None)
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
        result.pop("run_owner", None)
        result.pop("business_action_task_id", None)
        result.pop("business_action_id", None)
        result.pop("business_action_status", None)
        # The plan-command binding is internal execution authority; it is never
        # projected to the agent/Product surface (ADR-0085 §3/P2).
        for field in ("plan_task_id", "plan_workspace_id", "plan_version", "plan_task_version",
                      "plan_action", "plan_resource_kind", "plan_resource_id",
                      "plan_params_digest", "plan_idempotency_key"):
            result.pop(field, None)
        return result

    @staticmethod
    def _approval_with_action(row: dict[str, Any], action: dict | None = None) -> dict[str, object]:
        if action is None and row.get("business_action_id") is not None:
            action = {
                "task_id": row.get("business_action_task_id"),
                "action_id": row.get("business_action_id"),
                "status": row.get("business_action_status"),
            }
        result = AgentResearchStore._approval_row(row)
        result["business_action"] = (
            project_research_task_action(action) if isinstance(action, dict) else None
        )
        return result
