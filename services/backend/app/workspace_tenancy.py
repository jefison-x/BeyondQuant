"""Personal-workspace identity and additive ownership migration (ADR-0025)."""

from __future__ import annotations

import hashlib
import json
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
]

MIGRATION_SCHEMA_DDL = [
    """
    CREATE TABLE IF NOT EXISTS workspace_migration_runs (
        run_id TEXT PRIMARY KEY,
        contract_version TEXT NOT NULL,
        status TEXT NOT NULL,
        manifest_sha256 TEXT NOT NULL,
        report_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        finished_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workspace_migration_quarantine (
        quarantine_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES workspace_migration_runs(run_id),
        table_name TEXT NOT NULL,
        record_key_json JSONB NOT NULL,
        owner_principal TEXT,
        reason TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
]

# User credentials/preferences/policy, platform data/operations, and Engineering
# Plane resources are deliberately absent (ADR-0025 resource matrix).
WORKSPACE_TABLES = (
    "product_conversations", "product_conversation_messages",
    "research_tasks", "experiments", "artifacts", "research_transitions",
    "agent_runs", "agent_audit", "agent_approvals",
    "data_demands",
    "signal_producer_jobs", "ml_training_runs", "backtest_jobs",
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
    "backtest_jobs": ("job_id",),
    "paper_accounts": ("account_id",), "stock_pools": ("pool_id",),
    "stock_pool_lifecycle_audit": ("audit_id",),
    "stock_pool_write_idempotency": ("owner_principal", "idempotency_key"),
    "stock_pool_domain_references": ("domain", "reference_id"),
    "paper_account_audit": ("audit_id",),
    "paper_transfer_audit": ("transfer_id",),
    "learning_runs": ("learning_run_id",), "lessons": ("lesson_id",),
    "product_feedback": ("feedback_id",),
}

INHERITED_TABLES: dict[str, tuple[tuple[str, ...], str, str]] = {
    "research_transitions": (
        ("entity_type", "entity_id", "idempotency_key"),
        "LEFT JOIN research_tasks rt ON c.entity_type = 'research_task' AND rt.task_id = c.entity_id "
        "LEFT JOIN experiments ex ON c.entity_type = 'experiment' AND ex.experiment_id = c.entity_id "
        "LEFT JOIN artifacts ar ON c.entity_type = 'artifact' AND ar.artifact_id = c.entity_id",
        "COALESCE(rt.workspace_id, ex.workspace_id, ar.workspace_id)",
    ),
    "stock_pool_snapshots": (("snapshot_id",), "LEFT JOIN stock_pools p ON p.pool_id = c.pool_id", "p.workspace_id"),
    "stock_pool_snapshot_members": (("snapshot_id", "symbol"), "LEFT JOIN stock_pool_snapshots p ON p.snapshot_id = c.snapshot_id", "p.workspace_id"),
    "stock_pool_producer_definitions": (("definition_id",), "LEFT JOIN stock_pools p ON p.pool_id = c.pool_id", "p.workspace_id"),
    "stock_pool_materialization_runs": (("run_id",), "LEFT JOIN stock_pools p ON p.pool_id = c.pool_id", "p.workspace_id"),
    "stock_pool_producer_idempotency": (("owner_principal", "idempotency_key"), "LEFT JOIN stock_pools p ON p.pool_id = c.pool_id", "p.workspace_id"),
    "paper_positions": (("account_id", "symbol"), "LEFT JOIN paper_accounts p ON p.account_id = c.account_id", "p.workspace_id"),
    "paper_orders": (("order_id",), "LEFT JOIN paper_accounts p ON p.account_id = c.account_id", "p.workspace_id"),
    "paper_fills": (("fill_id",), "LEFT JOIN paper_accounts p ON p.account_id = c.account_id", "p.workspace_id"),
    "paper_account_controls": (("account_id",), "LEFT JOIN paper_accounts p ON p.account_id = c.account_id", "p.workspace_id"),
    "paper_ledger_entries": (("entry_id",), "LEFT JOIN paper_accounts p ON p.account_id = c.account_id", "p.workspace_id"),
    "paper_account_snapshots": (("snapshot_id",), "LEFT JOIN paper_accounts p ON p.account_id = c.account_id", "p.workspace_id"),
    "learning_iterations": (("iteration_id",), "LEFT JOIN learning_runs p ON p.learning_run_id = c.learning_run_id", "p.workspace_id"),
    "evaluation_signals": (("signal_id",), "LEFT JOIN research_tasks p ON p.task_id = c.task_id", "p.workspace_id"),
    "learning_history": (
        ("history_id",),
        "LEFT JOIN learning_runs lr ON c.entity_type = 'learning_run' AND lr.learning_run_id = c.entity_id "
        "LEFT JOIN lessons le ON c.entity_type = 'lesson' AND le.lesson_id = c.entity_id",
        "COALESCE(lr.workspace_id, le.workspace_id)",
    ),
    "product_feedback_revisions": (
        ("revision_id",), "LEFT JOIN product_feedback p ON p.feedback_id = c.feedback_id", "p.workspace_id",
    ),
    "product_feedback_audit": (
        ("audit_id",), "LEFT JOIN product_feedback p ON p.feedback_id = c.feedback_id", "p.workspace_id",
    ),
}

WORKSPACE_UNIQUE_INDEXES = {
    "research_tasks_workspace_idempotency": ("research_tasks", "workspace_id, idempotency_key"),
    "agent_runs_workspace_idempotency": ("agent_runs", "workspace_id, idempotency_key"),
    "data_demands_workspace_idempotency": ("data_demands", "workspace_id, idempotency_key"),
    "signal_jobs_workspace_idempotency": ("signal_producer_jobs", "workspace_id, idempotency_key"),
    "ml_training_workspace_idempotency": ("ml_training_runs", "workspace_id, idempotency_key"),
    "learning_runs_workspace_idempotency": ("learning_runs", "workspace_id, idempotency_key"),
    "paper_accounts_workspace_name": ("paper_accounts", "workspace_id, name"),
    "stock_pool_writes_workspace_idempotency": (
        "stock_pool_write_idempotency", "workspace_id, idempotency_key"
    ),
}

RELATION_CHECKS = {
    "conversation_message": "SELECT COUNT(*) AS count FROM product_conversation_messages c JOIN product_conversations p ON p.conversation_id=c.conversation_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "experiment_task": "SELECT COUNT(*) AS count FROM experiments c JOIN research_tasks p ON p.task_id=c.task_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "artifact_task": "SELECT COUNT(*) AS count FROM artifacts c JOIN research_tasks p ON p.task_id=c.task_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "agent_audit_run": "SELECT COUNT(*) AS count FROM agent_audit c JOIN agent_runs p ON p.run_id=c.run_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "agent_approval_run": "SELECT COUNT(*) AS count FROM agent_approvals c JOIN agent_runs p ON p.run_id=c.run_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "signal_task": "SELECT COUNT(*) AS count FROM signal_producer_jobs c JOIN research_tasks p ON p.task_id=c.task_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "ml_training_task": "SELECT COUNT(*) AS count FROM ml_training_runs c JOIN research_tasks p ON p.task_id=c.task_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "ml_training_pool": "SELECT COUNT(*) AS count FROM ml_training_runs c JOIN stock_pool_snapshots p ON p.snapshot_id=c.stock_pool_snapshot_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "backtest_task": "SELECT COUNT(*) AS count FROM backtest_jobs c JOIN research_tasks p ON p.task_id=c.task_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "pool_snapshot": "SELECT COUNT(*) AS count FROM stock_pool_snapshots c JOIN stock_pools p ON p.pool_id=c.pool_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "pool_member": "SELECT COUNT(*) AS count FROM stock_pool_snapshot_members c JOIN stock_pool_snapshots p ON p.snapshot_id=c.snapshot_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "pool_producer_definition": "SELECT COUNT(*) AS count FROM stock_pool_producer_definitions c JOIN stock_pools p ON p.pool_id=c.pool_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "pool_materialization_run": "SELECT COUNT(*) AS count FROM stock_pool_materialization_runs c JOIN stock_pools p ON p.pool_id=c.pool_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "pool_producer_idempotency": "SELECT COUNT(*) AS count FROM stock_pool_producer_idempotency c JOIN stock_pools p ON p.pool_id=c.pool_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "paper_position": "SELECT COUNT(*) AS count FROM paper_positions c JOIN paper_accounts p ON p.account_id=c.account_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "paper_order": "SELECT COUNT(*) AS count FROM paper_orders c JOIN paper_accounts p ON p.account_id=c.account_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "paper_fill": "SELECT COUNT(*) AS count FROM paper_fills c JOIN paper_accounts p ON p.account_id=c.account_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "paper_ledger": "SELECT COUNT(*) AS count FROM paper_ledger_entries c JOIN paper_accounts p ON p.account_id=c.account_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "learning_iteration": "SELECT COUNT(*) AS count FROM learning_iterations c JOIN learning_runs p ON p.learning_run_id=c.learning_run_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "evaluation_task": "SELECT COUNT(*) AS count FROM evaluation_signals c JOIN research_tasks p ON p.task_id=c.task_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "pool_lifecycle": "SELECT COUNT(*) AS count FROM stock_pool_lifecycle_audit c JOIN stock_pools p ON p.pool_id=c.pool_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "pool_domain_reference": "SELECT COUNT(*) AS count FROM stock_pool_domain_references c JOIN stock_pools p ON p.pool_id=c.pool_id JOIN stock_pool_snapshots s ON s.snapshot_id=c.snapshot_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id OR c.workspace_id IS DISTINCT FROM s.workspace_id",
    "paper_audit": "SELECT COUNT(*) AS count FROM paper_account_audit c JOIN paper_accounts p ON p.account_id=c.account_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "paper_transfer": "SELECT COUNT(*) AS count FROM paper_transfer_audit c JOIN paper_accounts p ON p.account_id=c.account_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "lesson_task": "SELECT COUNT(*) AS count FROM lessons c JOIN research_tasks p ON p.task_id=c.task_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "learning_history_run": "SELECT COUNT(*) AS count FROM learning_history c JOIN learning_runs p ON c.entity_type='learning_run' AND p.learning_run_id=c.entity_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "learning_history_lesson": "SELECT COUNT(*) AS count FROM learning_history c JOIN lessons p ON c.entity_type='lesson' AND p.lesson_id=c.entity_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "feedback_revision": "SELECT COUNT(*) AS count FROM product_feedback_revisions c JOIN product_feedback p ON p.feedback_id=c.feedback_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
    "feedback_audit": "SELECT COUNT(*) AS count FROM product_feedback_audit c JOIN product_feedback p ON p.feedback_id=c.feedback_id WHERE c.workspace_id IS DISTINCT FROM p.workspace_id",
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
    SCHEMA_DDL = [*IDENTITY_SCHEMA_DDL, *MIGRATION_SCHEMA_DDL]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
            self.provision_all_users()
        except SQLAlchemyError as exc:
            raise RuntimeError("workspace tenancy storage is unavailable") from exc

    def bootstrap_schema(self) -> None:
        super().bootstrap_schema()
        with self.engine.begin() as connection:
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
        if row is None or row["status"] != "active" or row["membership_status"] != "active":
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
              SELECT w.workspace_id INTO resolved FROM users u JOIN workspaces w
                ON w.owner_user_id = u.user_id JOIN workspace_memberships m
                ON m.workspace_id = w.workspace_id AND m.user_id = u.user_id
                WHERE u.username = NEW.owner_principal AND u.status = 'active'
                  AND w.status = 'active' AND m.status = 'active';
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
                    AND u.status = 'active' AND w.status = 'active' AND m.status = 'active';
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

    def backfill(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Map exact username owners to workspaces; never guess unmatched rows."""
        run_id = f"workspace_migration_{uuid.uuid4().hex}"
        report: dict[str, Any] = {"contract": CONTRACT_VERSION, "dry_run": dry_run, "tables": {}, "quarantine": []}
        with self._lock, self.engine.connect() as connection:
            transaction = connection.begin()
            self._backfill_direct(connection, report, dry_run=False)
            self._backfill_inherited(connection, report, dry_run=False)
            report["relation_checks"] = {
                name: int(fetch_one(connection, sql)["count"]) for name, sql in RELATION_CHECKS.items()
            }
            manifest_body = {"contract": CONTRACT_VERSION, "tables": report["tables"], "quarantine": report["quarantine"]}
            manifest = hashlib.sha256(json.dumps(manifest_body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            report["manifest_sha256"] = manifest
            report["verified"] = (
                all(item["pending"] == 0 and item["mismatched"] == 0 for item in report["tables"].values())
                and not report["quarantine"]
                and all(count == 0 for count in report["relation_checks"].values())
            )
            if not dry_run:
                now = _now()
                execute(connection, """INSERT INTO workspace_migration_runs
                    (run_id, contract_version, status, manifest_sha256, report_json, created_at, finished_at)
                    VALUES (:run_id, :contract, :status, :manifest, :report, :now, :now)""",
                    {"run_id": run_id, "contract": CONTRACT_VERSION,
                     "status": "verified" if report["verified"] else "quarantined",
                     "manifest": manifest, "report": report, "now": now})
                for item in report["quarantine"]:
                    execute(connection, """INSERT INTO workspace_migration_quarantine
                        (quarantine_id, run_id, table_name, record_key_json, owner_principal, reason, created_at)
                        VALUES (:id, :run_id, :table, :key, :owner, :reason, :now)""",
                        {"id": f"quarantine_{uuid.uuid4().hex}", "run_id": run_id,
                         "table": item["table"], "key": item["key"], "owner": item["owner_principal"],
                         "reason": item["reason"], "now": now})
                transaction.commit()
            else:
                transaction.rollback()
        report["run_id"] = None if dry_run else run_id
        return report

    def enforce_contract(self) -> dict[str, Any]:
        """Verify, then make every classified workspace key mandatory."""

        verification = self.backfill(dry_run=True)
        if not verification["verified"]:
            raise ValueError("workspace contract verification failed")
        with self._transaction() as connection:
            for table_name in WORKSPACE_TABLES:
                if connection.execute(text("SELECT to_regclass(:table)"), {"table": table_name}).scalar() is None:
                    continue
                pending = int(connection.execute(text(
                    f"SELECT COUNT(*) FROM {table_name} WHERE workspace_id IS NULL"
                )).scalar_one())
                if pending:
                    raise ValueError(f"{table_name} still has unassigned workspace rows")
                connection.execute(text(
                    f"ALTER TABLE {table_name} ALTER COLUMN workspace_id SET NOT NULL"
                ))
            for index_name, (table_name, columns) in WORKSPACE_UNIQUE_INDEXES.items():
                if connection.execute(text("SELECT to_regclass(:table)"), {"table": table_name}).scalar() is None:
                    continue
                connection.execute(text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table_name}({columns})"
                ))
        return {
            "contract": CONTRACT_VERSION,
            "status": "enforced",
            "tables": len(verification["tables"]),
            "manifest_sha256": verification["manifest_sha256"],
            "relation_checks": verification["relation_checks"],
        }

    def _backfill_direct(self, connection: Connection, report: dict[str, Any], *, dry_run: bool) -> None:
        for table_name, keys in DIRECT_OWNER_TABLES.items():
            if connection.execute(text("SELECT to_regclass(:table)"), {"table": table_name}).scalar() is None:
                continue
            rows = execute(connection, f"""SELECT t.*, w.workspace_id AS resolved_workspace_id
                FROM {table_name} t LEFT JOIN users u ON u.username = t.owner_principal
                LEFT JOIN workspaces w ON w.owner_user_id = u.user_id""")
            counts = {"scanned": len(rows), "mapped": 0, "already_mapped": 0, "pending": 0, "mismatched": 0}
            for row in rows:
                key = {column: row[column] for column in keys}
                resolved = row.get("resolved_workspace_id")
                current = row.get("workspace_id")
                if resolved is None:
                    counts["pending"] += 1
                    report["quarantine"].append({"table": table_name, "key": key,
                        "owner_principal": row.get("owner_principal"), "reason": "owner_has_no_exact_durable_user_workspace"})
                elif current not in {None, resolved}:
                    counts["mismatched"] += 1
                    report["quarantine"].append({"table": table_name, "key": key,
                        "owner_principal": row.get("owner_principal"), "reason": "existing_workspace_mismatch"})
                elif current == resolved:
                    counts["already_mapped"] += 1
                else:
                    counts["mapped"] += 1
                    if not dry_run:
                        where = " AND ".join(f"{column} = :key_{index}" for index, column in enumerate(keys))
                        params = {f"key_{index}": row[column] for index, column in enumerate(keys)}
                        params["workspace_id"] = resolved
                        execute(connection, f"UPDATE {table_name} SET workspace_id = :workspace_id WHERE {where}", params)
            report["tables"][table_name] = counts

    def _backfill_inherited(self, connection: Connection, report: dict[str, Any], *, dry_run: bool) -> None:
        for table_name, (keys, joins, resolved_expression) in INHERITED_TABLES.items():
            if connection.execute(text("SELECT to_regclass(:table)"), {"table": table_name}).scalar() is None:
                continue
            rows = execute(connection, f"""SELECT c.*, {resolved_expression} AS resolved_workspace_id
                FROM {table_name} c {joins}""")
            counts = {"scanned": len(rows), "mapped": 0, "already_mapped": 0, "pending": 0, "mismatched": 0}
            for row in rows:
                key = {column: row[column] for column in keys}
                resolved = row.get("resolved_workspace_id")
                current = row.get("workspace_id")
                if resolved is None:
                    counts["pending"] += 1
                    report["quarantine"].append({"table": table_name, "key": key,
                        "owner_principal": None, "reason": "parent_workspace_unresolved"})
                elif current not in {None, resolved}:
                    counts["mismatched"] += 1
                    report["quarantine"].append({"table": table_name, "key": key,
                        "owner_principal": None, "reason": "parent_workspace_mismatch"})
                elif current == resolved:
                    counts["already_mapped"] += 1
                else:
                    counts["mapped"] += 1
                    if not dry_run:
                        where = " AND ".join(f"{column} = :key_{index}" for index, column in enumerate(keys))
                        params = {f"key_{index}": row[column] for index, column in enumerate(keys)}
                        params["workspace_id"] = resolved
                        execute(connection, f"UPDATE {table_name} SET workspace_id = :workspace_id WHERE {where}", params)
            report["tables"][table_name] = counts
