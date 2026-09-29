"""Personal-workspace identity and tenant-write enforcement."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, ensure_column, execute, fetch_one


CONTRACT_VERSION = "personal-workspace.v1"

IDENTITY_SCHEMA_DDL = [
    """
    CREATE TABLE IF NOT EXISTS workspaces (
        workspace_id TEXT PRIMARY KEY,
        kind TEXT NOT NULL CHECK (kind = 'personal'),
        owner_user_id TEXT NOT NULL UNIQUE REFERENCES users(user_id),
        display_name TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
        reset_id TEXT,
        reset_kind TEXT,
        reset_request_key TEXT,
        reset_sessions_json JSONB,
        last_reset_id TEXT,
        last_reset_receipt_json JSONB,
        last_reset_released_sessions_json JSONB,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workspace_memberships (
        membership_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
        user_id TEXT NOT NULL REFERENCES users(user_id),
        role TEXT NOT NULL CHECK (role = 'owner'),
        status TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        UNIQUE(workspace_id, user_id)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS workspace_personal_owner_membership
        ON workspace_memberships(user_id) WHERE role = 'owner' AND status = 'active'
    """,
    """
    CREATE TABLE IF NOT EXISTS workspace_reset_receipts (
        workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
        request_key TEXT NOT NULL,
        reset_id TEXT NOT NULL,
        receipt_json JSONB NOT NULL,
        released_sessions_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (workspace_id, request_key)
    )
    """,
]

# User credentials/preferences/policy, platform data/operations, and Engineering
# Plane resources remain outside Workspace tenancy.
WORKSPACE_TABLES = (
    "product_conversations", "product_conversation_messages",
    "research_tasks", "experiments", "artifacts", "research_transitions",
    "research_execution_plans", "research_execution_plan_receipts",
    "research_task_actions",
    "agent_runs", "agent_audit", "agent_approvals",
    "data_demands",
    "signal_producer_jobs", "ml_training_runs", "backtest_jobs", "optimization_jobs",
    "paper_accounts", "stock_pools", "stock_pool_snapshots",
    "stock_pool_snapshot_members", "stock_pool_lifecycle_audit",
    "stock_pool_write_idempotency", "stock_pool_domain_references",
    "stock_pool_producer_definitions", "stock_pool_materialization_runs",
    "stock_pool_producer_idempotency",
    "paper_positions", "paper_orders", "paper_fills", "paper_account_controls",
    "paper_ledger_entries", "paper_account_snapshots", "paper_account_audit",
    "paper_transfer_audit", "learning_runs", "learning_iterations",
    "evaluation_signals", "lessons", "learning_history",
    "product_feedback", "product_feedback_revisions", "product_feedback_audit",
)

DIRECT_OWNER_TABLES: dict[str, tuple[str, ...]] = {
    "product_conversations": ("conversation_id",),
    "product_conversation_messages": ("message_id",),
    "research_tasks": ("task_id",), "experiments": ("experiment_id",),
    "artifacts": ("artifact_id",), "agent_runs": ("run_id",),
    "agent_audit": ("audit_id",), "agent_approvals": ("approval_id",),
    "data_demands": ("demand_id",),
    "signal_producer_jobs": ("job_id",), "ml_training_runs": ("training_run_id",),
    "backtest_jobs": ("job_id",), "optimization_jobs": ("job_id",),
    "paper_accounts": ("account_id",), "stock_pools": ("pool_id",),
    "stock_pool_lifecycle_audit": ("audit_id",),
    "stock_pool_write_idempotency": ("owner_principal", "idempotency_key"),
    "stock_pool_domain_references": ("domain", "reference_id"),
    "paper_account_audit": ("audit_id",),
    "paper_transfer_audit": ("transfer_id",),
    "learning_runs": ("learning_run_id",), "lessons": ("lesson_id",),
    "product_feedback": ("feedback_id",),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def provision_personal_workspace(connection: Connection, user: dict[str, Any]) -> dict[str, Any]:
    """Idempotently provision exactly one personal workspace + owner membership."""
    now = _now()
    workspace = fetch_one(
        connection, "SELECT * FROM workspaces WHERE owner_user_id = :user_id FOR UPDATE",
        {"user_id": user["user_id"]},
    )
    if workspace is None:
        workspace_id = f"workspace_{uuid.uuid4().hex}"
        execute(connection, """INSERT INTO workspaces
            (workspace_id, kind, owner_user_id, display_name, status, created_at, updated_at)
            VALUES (:workspace_id, 'personal', :user_id, :display_name, 'active', :now, :now)""",
            {"workspace_id": workspace_id, "user_id": user["user_id"],
             "display_name": f"{user['display_name']}的个人工作区", "now": now})
        workspace = fetch_one(connection, "SELECT * FROM workspaces WHERE workspace_id = :id", {"id": workspace_id})
    assert workspace is not None
    execute(connection, """INSERT INTO workspace_memberships
        (membership_id, workspace_id, user_id, role, status, created_at, updated_at)
        VALUES (:membership_id, :workspace_id, :user_id, 'owner', 'active', :now, :now)
        ON CONFLICT (workspace_id, user_id) DO NOTHING""",
        {"membership_id": f"membership_{uuid.uuid4().hex}", "workspace_id": workspace["workspace_id"],
         "user_id": user["user_id"], "now": now})
    membership = fetch_one(connection, """SELECT * FROM workspace_memberships
        WHERE workspace_id = :workspace_id AND user_id = :user_id""",
        {"workspace_id": workspace["workspace_id"], "user_id": user["user_id"]})
    return {"workspace": workspace, "membership": membership}


class WorkspaceTenancyStore(PgStoreMixin):
    SCHEMA_DDL = IDENTITY_SCHEMA_DDL

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
            self.provision_all_users()
        except SQLAlchemyError as exc:
            raise RuntimeError("workspace tenancy storage is unavailable") from exc

    def bootstrap_schema(self) -> None:
        from .db import schema_bootstrap_lock
        super().bootstrap_schema()
        with self.engine.begin() as connection:
            schema_bootstrap_lock(connection)
            ensure_column(connection, "workspaces", "reset_id", "TEXT")
            ensure_column(connection, "workspaces", "reset_kind", "TEXT")
            ensure_column(connection, "workspaces", "reset_request_key", "TEXT")
            ensure_column(connection, "workspaces", "reset_sessions_json", "JSONB")
            ensure_column(connection, "workspaces", "last_reset_id", "TEXT")
            ensure_column(connection, "workspaces", "last_reset_receipt_json", "JSONB")
            ensure_column(connection, "workspaces", "last_reset_released_sessions_json", "JSONB")
            for table_name in WORKSPACE_TABLES:
                exists = connection.execute(text("SELECT to_regclass(:table)"), {"table": table_name}).scalar()
                if exists is None:
                    continue
                ensure_column(connection, table_name, "workspace_id", "TEXT REFERENCES workspaces(workspace_id)")
                connection.execute(text(
                    f"CREATE INDEX IF NOT EXISTS {table_name}_workspace ON {table_name}(workspace_id)"
                ))
            self._install_write_triggers(connection)

    def provision_all_users(self) -> dict[str, int]:
        created = 0
        with self._transaction() as connection:
            users = execute(connection, "SELECT user_id, display_name FROM users ORDER BY user_id")
            for user in users:
                before = fetch_one(connection, "SELECT workspace_id FROM workspaces WHERE owner_user_id = :id", {"id": user["user_id"]})
                provision_personal_workspace(connection, user)
                created += int(before is None)
        return {"users": len(users), "created": created}

    def get_personal_workspace(self, user_id: str) -> dict[str, Any] | None:
        return self._fetch_one("""SELECT w.*, m.membership_id, m.role AS membership_role,
            m.status AS membership_status FROM workspaces w JOIN workspace_memberships m
              ON m.workspace_id = w.workspace_id AND m.user_id = w.owner_user_id
            WHERE w.owner_user_id = :user_id AND w.kind = 'personal'""", {"user_id": user_id})

    def public_workspace(self, user_id: str) -> dict[str, str]:
        row = self.get_personal_workspace(user_id)
        reset_pending = row is not None and row["status"] == "disabled" and bool(row.get("reset_id"))
        if (row is None or (row["status"] != "active" and not reset_pending)
                or row["membership_status"] != "active"):
            raise ValueError("active personal workspace membership is required")
        return {
            "contract": CONTRACT_VERSION,
            "workspace_id": str(row["workspace_id"]),
            "kind": "personal",
            "display_name": str(row["display_name"]),
            "role": "owner",
        }

    def resolve_context(self, owner_principal: str | None, workspace_id: str | None) -> dict[str, str]:
        if not owner_principal or not workspace_id:
            raise ValueError("trusted workspace context is required")
        row = self._fetch_one("""SELECT w.workspace_id, w.kind, w.owner_user_id,
                m.role, u.username AS actor_principal
            FROM workspaces w
            JOIN workspace_memberships m ON m.workspace_id = w.workspace_id
            JOIN users u ON u.user_id = m.user_id
            WHERE w.workspace_id = :workspace_id AND u.username = :owner
              AND w.status = 'active' AND m.status = 'active' AND u.status = 'active'
              AND w.kind = 'personal' AND m.role = 'owner'""",
            {"workspace_id": workspace_id, "owner": owner_principal})
        if row is None:
            raise ValueError("trusted workspace context is invalid")
        return {
            "contract": CONTRACT_VERSION,
            "workspace_id": str(row["workspace_id"]),
            "workspace_kind": str(row["kind"]),
            "membership_role": str(row["role"]),
            "owner_user_id": str(row["owner_user_id"]),
            "actor_principal": str(row["actor_principal"]),
        }

    @staticmethod
    def _install_write_triggers(connection: Connection) -> None:
        connection.execute(text("""CREATE OR REPLACE FUNCTION byq_workspace_from_owner()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE resolved TEXT;
            BEGIN
              IF TG_TABLE_NAME = 'agent_runs' AND TG_OP = 'UPDATE' THEN
                IF NEW.owner_principal IS DISTINCT FROM OLD.owner_principal
                    OR (OLD.workspace_id IS NOT NULL AND NEW.workspace_id IS DISTINCT FROM OLD.workspace_id) THEN
                  RAISE EXCEPTION 'agent run ownership is immutable';
                END IF;
              END IF;
              SELECT w.workspace_id INTO resolved FROM users u JOIN workspaces w
                ON w.owner_user_id = u.user_id JOIN workspace_memberships m
                ON m.workspace_id = w.workspace_id AND m.user_id = u.user_id
                WHERE u.username = NEW.owner_principal AND u.status = 'active'
                  AND w.status = 'active' AND m.status = 'active'
                FOR SHARE OF w;
              -- ADR-0063: no generic bypass. Only an immutable, already-bound
              -- run may follow its trusted persisted root into a terminal state.
              IF resolved IS NULL AND TG_TABLE_NAME = 'agent_runs' AND TG_OP = 'UPDATE' THEN
                IF OLD.status IN ('active', 'pending_binding')
                    AND NEW.status IN ('completed', 'failed', 'cancelled', 'interrupted')
                    AND OLD.authority_status IN ('active','authority_revoked_unconfirmed')
                    AND NEW.authority_status = 'closed'
                    AND NEW.version = OLD.version + 1
                    AND (to_jsonb(NEW) - ARRAY['status','authority_status','updated_at','version']) =
                        (to_jsonb(OLD) - ARRAY['status','authority_status','updated_at','version']) THEN
                  SELECT w.workspace_id INTO resolved FROM users u
                    JOIN workspaces w ON w.owner_user_id = u.user_id
                    JOIN workspace_memberships m ON m.workspace_id = w.workspace_id AND m.user_id = u.user_id
                    JOIN agent_runtime_turns r ON r.root_run_id = OLD.root_run_id
                    WHERE u.username = OLD.owner_principal AND w.kind = 'personal' AND m.role = 'owner'
                      AND w.workspace_id = OLD.workspace_id
                      AND r.owner_principal = OLD.owner_principal AND r.workspace_id = OLD.workspace_id
                      AND r.session_id = OLD.session_id AND r.trace_id = OLD.trace_id
                      AND r.status = NEW.status AND r.authority_status = 'closed'
                      AND ((OLD.authority_status = 'active' AND r.terminal_sequence IS NOT NULL)
                        OR (OLD.authority_status = 'authority_revoked_unconfirmed'
                          AND NEW.status = 'interrupted' AND w.status = 'disabled'
                          AND w.reset_id IS NOT NULL AND r.terminal_sequence IS NULL
                          AND r.terminal_event_sha256 IS NULL
                          AND EXISTS (SELECT 1 FROM jsonb_array_elements(w.reset_sessions_json) reset_session
                            WHERE reset_session->>'session_id'=r.session_id
                              AND reset_session->>'trace_id'=r.trace_id)));
                  IF resolved IS NULL AND OLD.root_run_id IS NULL
                      AND OLD.authority_status = 'authority_revoked_unconfirmed'
                      AND NEW.status = 'interrupted' THEN
                    SELECT w.workspace_id INTO resolved FROM users u
                      JOIN workspaces w ON w.owner_user_id = u.user_id
                      JOIN workspace_memberships m ON m.workspace_id = w.workspace_id AND m.user_id = u.user_id
                      WHERE u.username = OLD.owner_principal AND w.kind = 'personal' AND m.role = 'owner'
                        AND w.workspace_id = OLD.workspace_id AND w.status = 'disabled'
                        AND w.reset_id IS NOT NULL
                        AND EXISTS (SELECT 1 FROM jsonb_array_elements(w.reset_sessions_json) reset_session
                          WHERE reset_session->>'session_id'=OLD.session_id
                            AND reset_session->>'trace_id'=OLD.trace_id);
                  END IF;
                END IF;
              END IF;
              IF resolved IS NULL AND TG_TABLE_NAME = 'product_conversations' AND TG_OP = 'UPDATE' THEN
                IF OLD.status = 'active' AND NEW.status = 'archived'
                    AND (to_jsonb(NEW) - ARRAY['status','updated_at']) =
                        (to_jsonb(OLD) - ARRAY['status','updated_at']) THEN
                  SELECT w.workspace_id INTO resolved FROM users u
                    JOIN workspaces w ON w.owner_user_id = u.user_id
                    JOIN workspace_memberships m ON m.workspace_id = w.workspace_id AND m.user_id = u.user_id
                    WHERE u.username = OLD.owner_principal AND u.status = 'active'
                      AND m.status = 'active' AND m.role = 'owner'
                      AND w.kind = 'personal' AND w.workspace_id = OLD.workspace_id
                      AND w.status = 'disabled' AND w.reset_id IS NOT NULL
                      AND EXISTS (SELECT 1 FROM jsonb_array_elements(w.reset_sessions_json) reset_session
                        WHERE reset_session->>'conversation_id'=OLD.conversation_id
                          AND reset_session->>'session_id'=OLD.runtime_session_id
                          AND reset_session->>'trace_id'=OLD.trace_id);
                END IF;
              END IF;
              IF resolved IS NULL THEN RAISE EXCEPTION 'trusted workspace owner is unresolved'; END IF;
              IF NEW.workspace_id IS NOT NULL AND NEW.workspace_id <> resolved THEN
                RAISE EXCEPTION 'workspace owner mismatch';
              END IF;
              NEW.workspace_id := resolved;
              RETURN NEW;
            END $$"""))
        for table_name in DIRECT_OWNER_TABLES:
            trigger_name = f"{table_name}_workspace_write"
            connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}"))
            connection.execute(text(f"""CREATE TRIGGER {trigger_name} BEFORE INSERT OR UPDATE
                ON {table_name} FOR EACH ROW EXECUTE FUNCTION byq_workspace_from_owner()"""))

        connection.execute(text("""CREATE OR REPLACE FUNCTION byq_workspace_from_parent()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE resolved TEXT; owner_resolved TEXT; parent_key TEXT;
            BEGIN
              parent_key := to_jsonb(NEW) ->> TG_ARGV[2];
              EXECUTE format('SELECT workspace_id FROM %I WHERE %I = $1', TG_ARGV[0], TG_ARGV[1])
                INTO resolved USING parent_key;
              IF resolved IS NULL THEN RAISE EXCEPTION 'trusted parent workspace is unresolved'; END IF;
              IF to_jsonb(NEW) ? 'owner_principal' THEN
                SELECT w.workspace_id INTO owner_resolved FROM users u JOIN workspaces w
                  ON w.owner_user_id = u.user_id JOIN workspace_memberships m
                  ON m.workspace_id = w.workspace_id AND m.user_id = u.user_id
                  WHERE u.username = to_jsonb(NEW) ->> 'owner_principal'
                    AND u.status = 'active' AND w.status = 'active' AND m.status = 'active'
                  FOR SHARE OF w;
                IF owner_resolved IS NULL AND TG_TABLE_NAME = 'agent_audit' AND TG_OP = 'INSERT' THEN
                  SELECT w.workspace_id INTO owner_resolved FROM users u
                    JOIN workspaces w ON w.owner_user_id = u.user_id
                    JOIN workspace_memberships m ON m.workspace_id = w.workspace_id AND m.user_id = u.user_id
                    JOIN agent_runs a ON a.run_id = NEW.run_id AND a.workspace_id = w.workspace_id
                    JOIN agent_runtime_turns r ON r.root_run_id = a.root_run_id
                    WHERE u.username = NEW.owner_principal AND w.kind = 'personal' AND m.role = 'owner'
                      AND a.owner_principal = NEW.owner_principal AND a.actor_principal = NEW.actor_principal
                      AND r.owner_principal = a.owner_principal AND r.workspace_id = a.workspace_id
                      AND r.session_id = a.session_id AND r.trace_id = a.trace_id
                      AND r.status IN ('completed','failed','cancelled','interrupted')
                      AND a.status = r.status AND NEW.outcome = a.status AND r.terminal_sequence IS NOT NULL
                      AND NEW.action = 'runtime_turn_binding' AND NEW.resource_type = 'runtime_turn'
                      AND NEW.resource_id = r.root_run_id
                      AND NEW.detail_json = jsonb_build_object('root_run_id', r.root_run_id,
                                                              'terminal_sequence', r.terminal_sequence);
                END IF;
                IF owner_resolved IS NULL OR owner_resolved <> resolved THEN
                  RAISE EXCEPTION 'parent workspace owner mismatch';
                END IF;
              END IF;
              IF NEW.workspace_id IS NOT NULL AND NEW.workspace_id <> resolved THEN
                RAISE EXCEPTION 'parent workspace mismatch';
              END IF;
              NEW.workspace_id := resolved;
              RETURN NEW;
            END $$"""))
        parent_triggers = {
            "product_conversation_messages": ("product_conversations", "conversation_id", "conversation_id"),
            "experiments": ("research_tasks", "task_id", "task_id"),
            "artifacts": ("research_tasks", "task_id", "task_id"),
            "research_execution_plans": ("research_tasks", "task_id", "task_id"),
            "research_execution_plan_receipts": ("research_tasks", "task_id", "task_id"),
            "agent_audit": ("agent_runs", "run_id", "run_id"),
            "agent_approvals": ("agent_runs", "run_id", "run_id"),
            "signal_producer_jobs": ("research_tasks", "task_id", "task_id"),
            "backtest_jobs": ("research_tasks", "task_id", "task_id"),
            "stock_pool_snapshots": ("stock_pools", "pool_id", "pool_id"),
            "stock_pool_snapshot_members": ("stock_pool_snapshots", "snapshot_id", "snapshot_id"),
            "stock_pool_producer_definitions": ("stock_pools", "pool_id", "pool_id"),
            "stock_pool_materialization_runs": ("stock_pools", "pool_id", "pool_id"),
            "stock_pool_producer_idempotency": ("stock_pools", "pool_id", "pool_id"),
            "stock_pool_lifecycle_audit": ("stock_pools", "pool_id", "pool_id"),
            "stock_pool_domain_references": ("stock_pools", "pool_id", "pool_id"),
            "paper_positions": ("paper_accounts", "account_id", "account_id"),
            "paper_orders": ("paper_accounts", "account_id", "account_id"),
            "paper_fills": ("paper_accounts", "account_id", "account_id"),
            "paper_account_controls": ("paper_accounts", "account_id", "account_id"),
            "paper_ledger_entries": ("paper_accounts", "account_id", "account_id"),
            "paper_account_snapshots": ("paper_accounts", "account_id", "account_id"),
            "paper_account_audit": ("paper_accounts", "account_id", "account_id"),
            "paper_transfer_audit": ("paper_accounts", "account_id", "account_id"),
            "learning_iterations": ("learning_runs", "learning_run_id", "learning_run_id"),
            "evaluation_signals": ("research_tasks", "task_id", "task_id"),
            "lessons": ("research_tasks", "task_id", "task_id"),
            "product_feedback_revisions": ("product_feedback", "feedback_id", "feedback_id"),
            "product_feedback_audit": ("product_feedback", "feedback_id", "feedback_id"),
        }
        for table_name, arguments in parent_triggers.items():
            trigger_name = f"{table_name}_workspace_write"
            connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}"))
            connection.execute(text(f"""CREATE TRIGGER {trigger_name} BEFORE INSERT OR UPDATE
                ON {table_name} FOR EACH ROW EXECUTE FUNCTION byq_workspace_from_parent(
                '{arguments[0]}', '{arguments[1]}', '{arguments[2]}')"""))
        connection.execute(text("""CREATE OR REPLACE FUNCTION byq_workspace_from_research_entity()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE resolved TEXT;
            BEGIN
              IF NEW.entity_type = 'research_task' THEN
                SELECT workspace_id INTO resolved FROM research_tasks WHERE task_id = NEW.entity_id;
              ELSIF NEW.entity_type = 'experiment' THEN
                SELECT workspace_id INTO resolved FROM experiments WHERE experiment_id = NEW.entity_id;
              ELSIF NEW.entity_type = 'artifact' THEN
                SELECT workspace_id INTO resolved FROM artifacts WHERE artifact_id = NEW.entity_id;
              END IF;
              IF resolved IS NULL THEN RAISE EXCEPTION 'research entity workspace is unresolved'; END IF;
              IF NEW.workspace_id IS NOT NULL AND NEW.workspace_id <> resolved THEN
                RAISE EXCEPTION 'research entity workspace mismatch';
              END IF;
              NEW.workspace_id := resolved;
              RETURN NEW;
            END $$"""))
        connection.execute(text("DROP TRIGGER IF EXISTS research_transitions_workspace_write ON research_transitions"))
        connection.execute(text("""CREATE TRIGGER research_transitions_workspace_write BEFORE INSERT OR UPDATE
            ON research_transitions FOR EACH ROW EXECUTE FUNCTION byq_workspace_from_research_entity()"""))
        connection.execute(text("""CREATE OR REPLACE FUNCTION byq_workspace_from_learning_entity()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE resolved TEXT;
            BEGIN
              IF NEW.entity_type = 'learning_run' THEN
                SELECT workspace_id INTO resolved FROM learning_runs
                  WHERE learning_run_id = NEW.entity_id;
              ELSIF NEW.entity_type = 'lesson' THEN
                SELECT workspace_id INTO resolved FROM lessons WHERE lesson_id = NEW.entity_id;
              END IF;
              IF resolved IS NULL THEN RAISE EXCEPTION 'learning entity workspace is unresolved'; END IF;
              IF NEW.workspace_id IS NOT NULL AND NEW.workspace_id <> resolved THEN
                RAISE EXCEPTION 'learning entity workspace mismatch';
              END IF;
              NEW.workspace_id := resolved;
              RETURN NEW;
            END $$"""))
        connection.execute(text("DROP TRIGGER IF EXISTS learning_history_workspace_write ON learning_history"))
        connection.execute(text("""CREATE TRIGGER learning_history_workspace_write BEFORE INSERT OR UPDATE
            ON learning_history FOR EACH ROW EXECUTE FUNCTION byq_workspace_from_learning_entity()"""))
