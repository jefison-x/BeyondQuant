"""Narrow, transactional BYQ workspace reset (ADR-004 / Phase 13).

This store deletes only the enumerated workspace research graph and terminal
specialized Job records. It never bootstraps other stores, resets a schema, or
touches Agent authority/audit, financial facts, users, feedback, shared data, or
object files. Object references are returned for a caller-owned global GC pass.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin


_RESET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")

# These tables must exist before reset can prove the relevant ownership and
# lifecycle boundaries. This store has no schema DDL; application startup owns
# schema creation through the domain stores.
_REQUIRED_TABLES = (
    "users", "workspaces", "workspace_memberships",
    "product_conversations", "product_conversation_messages",
    "research_tasks", "experiments", "artifacts", "artifact_submission_receipts",
    "research_transitions", "research_execution_plans", "research_execution_plan_receipts",
    "research_task_actions", "research_judgment_stage_calls", "research_receipt_watches",
    "data_demands", "factor_jobs", "signal_producer_jobs", "backtest_jobs",
    "optimization_jobs", "ml_training_runs", "ml_training_submission_keys",
    "ml_training_receipt_watches", "ml_prediction_runs",
    "agent_runs", "agent_runtime_turns", "agent_domain_call_claims",
    "agent_domain_correction_buckets", "agent_approvals", "agent_audit",
    "learning_runs", "evaluation_signals", "lessons", "learning_history",
)

_JOB_TERMINAL_STATES: dict[str, tuple[str, tuple[str, ...]]] = {
    "data_demands": ("demand_id", ("ready", "partial", "failed", "cancelled")),
    "factor_jobs": ("job_id", ("completed", "failed", "cancelled")),
    "signal_producer_jobs": ("job_id", ("completed", "failed", "cancelled")),
    "backtest_jobs": ("job_id", ("completed", "failed", "cancelled")),
    "optimization_jobs": ("job_id", ("completed", "failed", "cancelled")),
    "ml_training_runs": ("training_run_id", ("completed", "failed", "cancelled")),
    "ml_prediction_runs": ("prediction_run_id", ("completed", "failed", "cancelled")),
}

# Only the FK children listed here are deleted as part of this bounded graph.
# PostgreSQL catalog preflight below verifies that inbound references either
# delete earlier in the explicit order or do not contain rows for this workspace.
_DELETE_TABLES = frozenset({
    "product_conversation_messages", "research_receipt_watches",
    "ml_training_submission_keys", "ml_training_receipt_watches",
    "data_demands", "factor_jobs", "signal_producer_jobs", "backtest_jobs",
    "optimization_jobs", "ml_prediction_runs", "ml_training_runs",
    "research_judgment_stage_calls", "research_execution_plan_receipts",
    "research_execution_plans", "artifact_submission_receipts",
    "research_transitions", "artifacts", "experiments", "research_tasks",
    "product_conversations",
})

# Explicit dependency-first SQL. Parent ownership is checked again on every
# statement; child rows without a direct owner are joined through their parent.
_DELETE_PLAN: tuple[tuple[str, str], ...] = (
    ("product_conversation_messages", "DELETE FROM product_conversation_messages WHERE owner_principal=:owner AND workspace_id=:workspace"),
    ("research_receipt_watches", "DELETE FROM research_receipt_watches WHERE owner_principal=:owner AND workspace_id=:workspace"),
    ("ml_training_submission_keys", "DELETE FROM ml_training_submission_keys WHERE owner_principal=:owner AND workspace_id=:workspace"),
    ("ml_training_receipt_watches", "DELETE FROM ml_training_receipt_watches WHERE owner_principal=:owner AND workspace_id=:workspace"),
    ("data_demands", "DELETE FROM data_demands WHERE owner_principal=:owner AND workspace_id=:workspace"),
    ("factor_jobs", "DELETE FROM factor_jobs WHERE owner_principal=:owner AND workspace_id=:workspace"),
    ("signal_producer_jobs", "DELETE FROM signal_producer_jobs WHERE owner_principal=:owner AND workspace_id=:workspace"),
    ("backtest_jobs", "DELETE FROM backtest_jobs WHERE owner_principal=:owner AND workspace_id=:workspace"),
    ("optimization_jobs", "DELETE FROM optimization_jobs WHERE owner_principal=:owner AND workspace_id=:workspace"),
    ("ml_prediction_runs", "DELETE FROM ml_prediction_runs WHERE owner_principal=:owner AND workspace_id=:workspace"),
    ("ml_training_runs", "DELETE FROM ml_training_runs WHERE owner_principal=:owner AND workspace_id=:workspace"),
    ("research_judgment_stage_calls", "DELETE FROM research_judgment_stage_calls c USING research_tasks t WHERE c.task_id=t.task_id AND t.owner_principal=:owner AND t.workspace_id=:workspace"),
    ("research_execution_plan_receipts", "DELETE FROM research_execution_plan_receipts c USING research_tasks t WHERE c.task_id=t.task_id AND t.owner_principal=:owner AND t.workspace_id=:workspace"),
    ("research_execution_plans", "DELETE FROM research_execution_plans WHERE owner_principal=:owner AND workspace_id=:workspace"),
    ("artifact_submission_receipts", "DELETE FROM artifact_submission_receipts c USING research_tasks t WHERE c.task_id=t.task_id AND t.owner_principal=:owner AND t.workspace_id=:workspace"),
    ("research_transitions", "DELETE FROM research_transitions WHERE workspace_id=:workspace"),
    ("artifacts", "DELETE FROM artifacts WHERE owner_principal=:owner AND workspace_id=:workspace"),
    ("experiments", "DELETE FROM experiments WHERE owner_principal=:owner AND workspace_id=:workspace"),
    ("research_tasks", "DELETE FROM research_tasks WHERE owner_principal=:owner AND workspace_id=:workspace"),
    ("product_conversations", "DELETE FROM product_conversations WHERE owner_principal=:owner AND workspace_id=:workspace"),
)
_DELETE_ORDER = {table: index for index, (table, _sql) in enumerate(_DELETE_PLAN)}


class WorkspaceResetError(RuntimeError):
    """Safe base for workspace reset failures."""


class WorkspaceNotFound(WorkspaceResetError):
    """The exact active personal workspace ownership binding was not found."""


class WorkspaceResetBlocked(WorkspaceResetError):
    """Reset would cross an active job, authority, audit, or FK boundary."""


class WorkspaceResetPersistenceError(WorkspaceResetError):
    """The reset transaction could not be completed."""


class WorkspaceResetStore(PgStoreMixin):
    """Delete one workspace's explicitly classified disposable research data."""

    SCHEMA_DDL: list[str] = []

    @staticmethod
    def _identity(value: object, field: str) -> str:
        if not isinstance(value, str) or _RESET_ID.fullmatch(value) is None:
            raise ValueError(f"{field} is invalid")
        return value

    @staticmethod
    def _required_schema(connection) -> None:
        missing = []
        for table in _REQUIRED_TABLES:
            found = connection.execute(text("SELECT to_regclass(:name)"), {"name": table}).scalar_one()
            if found is None:
                missing.append(table)
        if missing:
            raise WorkspaceResetBlocked(
                "workspace reset safety schema is incomplete: " + ", ".join(missing)
            )

    @staticmethod
    def _check_unknown_foreign_keys(connection, *, owner: str, workspace: str) -> None:
        targets = tuple(sorted({
            "product_conversations", "research_tasks", "experiments", "artifacts",
            "ml_training_runs",
        }))
        rows = connection.execute(text("""
            SELECT child.relname AS child_table, parent.relname AS parent_table,
                   constraint_row.conname AS constraint_name,
                   ARRAY(SELECT child_attribute.attname
                           FROM unnest(constraint_row.conkey) WITH ORDINALITY key_column(attnum, position)
                           JOIN pg_attribute child_attribute
                             ON child_attribute.attrelid=child.oid AND child_attribute.attnum=key_column.attnum
                          ORDER BY key_column.position) AS child_columns,
                   ARRAY(SELECT parent_attribute.attname
                           FROM unnest(constraint_row.confkey) WITH ORDINALITY key_column(attnum, position)
                           JOIN pg_attribute parent_attribute
                             ON parent_attribute.attrelid=parent.oid AND parent_attribute.attnum=key_column.attnum
                          ORDER BY key_column.position) AS parent_columns
              FROM pg_constraint constraint_row
              JOIN pg_class child ON child.oid=constraint_row.conrelid
              JOIN pg_namespace child_ns ON child_ns.oid=child.relnamespace
              JOIN pg_class parent ON parent.oid=constraint_row.confrelid
              JOIN pg_namespace parent_ns ON parent_ns.oid=parent.relnamespace
             WHERE constraint_row.contype='f'
               AND child_ns.nspname=current_schema()
               AND parent_ns.nspname=current_schema()
               AND parent.relname = ANY(:targets)
        """), {"targets": list(targets)}).mappings().all()
        quote = connection.dialect.identifier_preparer.quote
        for row in rows:
            child = str(row["child_table"])
            parent = str(row["parent_table"])
            child_order = _DELETE_ORDER.get(child)
            parent_order = _DELETE_ORDER.get(parent)
            if child_order is not None and parent_order is not None and child_order < parent_order:
                continue
            child_columns = list(row["child_columns"] or [])
            parent_columns = list(row["parent_columns"] or [])
            if not child_columns or len(child_columns) != len(parent_columns):
                raise WorkspaceResetBlocked(
                    f"foreign-key constraint {row['constraint_name']} cannot be classified"
                )
            joins = " AND ".join(
                f"c.{quote(str(child_column))}=p.{quote(str(parent_column))}"
                for child_column, parent_column in zip(child_columns, parent_columns)
            )
            referenced = connection.execute(text(f"""
                SELECT 1 FROM {quote(child)} c
                  JOIN {quote(parent)} p ON {joins}
                 WHERE p.workspace_id=:workspace AND p.owner_principal=:owner
                 LIMIT 1
            """), {"workspace": workspace, "owner": owner}).first()
            if referenced is not None:
                raise WorkspaceResetBlocked(
                    f"foreign-key constraint {row['constraint_name']} retains workspace rows; reset was not started"
                )

    @staticmethod
    def _first_row(connection, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
        row = connection.execute(text(sql), params).mappings().first()
        return None if row is None else dict(row)

    def _preflight(self, connection, *, owner: str, workspace: str) -> None:
        params = {"owner": owner, "workspace": workspace}

        root = self._first_row(connection, """
            SELECT root_run_id FROM agent_runtime_turns
             WHERE owner_principal=:owner AND workspace_id=:workspace
               AND (status='active' OR authority_status <> 'closed')
             ORDER BY root_run_id LIMIT 1
        """, params)
        if root is not None:
            raise WorkspaceResetBlocked("active or unconfirmed Agent root prevents workspace reset")

        run = self._first_row(connection, """
            SELECT run_id FROM agent_runs
             WHERE owner_principal=:owner AND workspace_id=:workspace
               AND (status IN ('active','pending_binding') OR authority_status <> 'closed')
             ORDER BY run_id LIMIT 1
        """, params)
        if run is not None:
            raise WorkspaceResetBlocked("active or unconfirmed Agent run prevents workspace reset")

        claim = self._first_row(connection, """
            SELECT c.claim_id FROM agent_domain_call_claims c
              JOIN agent_domain_correction_buckets b
                ON b.root_run_id=c.root_run_id AND b.task_id=c.task_id AND b.action=c.action
             WHERE b.owner_principal=:owner AND b.workspace_id=:workspace
               AND c.status IN ('claimed','executing')
             ORDER BY c.claim_id LIMIT 1
        """, params)
        if claim is not None:
            raise WorkspaceResetBlocked("unresolved external domain action prevents workspace reset")

        unknown_approval = self._first_row(connection, """
            SELECT approval_id FROM agent_approvals
             WHERE owner_principal=:owner AND workspace_id=:workspace
               AND (continuation_status='outcome_unknown'
                    OR execution_outcome='outcome_unknown')
             ORDER BY approval_id LIMIT 1
        """, params)
        if unknown_approval is not None:
            raise WorkspaceResetBlocked("unknown approval continuation outcome prevents workspace reset")

        for table, (identity_column, terminal) in _JOB_TERMINAL_STATES.items():
            placeholders = ", ".join(f":terminal_{index}" for index in range(len(terminal)))
            job_params = params | {f"terminal_{index}": state for index, state in enumerate(terminal)}
            row = self._first_row(connection, f"""
                SELECT {identity_column} AS identity FROM {table}
                 WHERE owner_principal=:owner AND workspace_id=:workspace
                   AND status NOT IN ({placeholders})
                 ORDER BY {identity_column} LIMIT 1
            """, job_params)
            if row is not None:
                raise WorkspaceResetBlocked(f"active or unclassified {table} row prevents workspace reset")

        admitted = self._first_row(connection, """
            SELECT c.call_identity FROM research_judgment_stage_calls c
              JOIN research_tasks t ON t.task_id=c.task_id
             WHERE t.owner_principal=:owner AND t.workspace_id=:workspace AND c.status='admitted'
             ORDER BY c.call_identity LIMIT 1
        """, params)
        if admitted is not None:
            raise WorkspaceResetBlocked("admitted research judgment call prevents workspace reset")

        receipt = self._first_row(connection, """
            SELECT watch_id FROM research_receipt_watches
             WHERE owner_principal=:owner AND workspace_id=:workspace
               AND state NOT IN ('confirmed','conflict')
             ORDER BY watch_id LIMIT 1
        """, params)
        if receipt is not None:
            raise WorkspaceResetBlocked("unresolved research submission receipt prevents workspace reset")

        action = self._first_row(connection, """
            SELECT action_id FROM research_task_actions
             WHERE owner_principal=:owner AND workspace_id=:workspace
             ORDER BY action_id LIMIT 1
        """, params)
        if action is not None:
            raise WorkspaceResetBlocked(
                "retained approval decision references a ResearchTask; reset would remove an authoritative fact"
            )

        approval_artifact = self._first_row(connection, """
            SELECT artifact_id FROM artifacts
             WHERE owner_principal=:owner AND workspace_id=:workspace
               AND kind IN ('strategy_approval','ml_strategy_approval')
             ORDER BY artifact_id LIMIT 1
        """, params)
        if approval_artifact is not None:
            raise WorkspaceResetBlocked(
                "retained strategy approval Artifact references a ResearchTask; reset would remove an authoritative fact"
            )

        retained_approval = self._first_row(connection, """
            SELECT a.approval_id FROM agent_approvals a
              JOIN agent_runs r ON r.run_id=a.run_id
              JOIN artifacts target ON target.artifact_id=a.resource_id
             WHERE r.owner_principal=:owner AND r.workspace_id=:workspace
               AND target.owner_principal=:owner AND target.workspace_id=:workspace
             ORDER BY a.approval_id LIMIT 1
        """, params)
        if retained_approval is not None:
            raise WorkspaceResetBlocked(
                "Agent approval references a workspace Artifact; reset would remove an authoritative fact"
            )

        retained_audit = self._first_row(connection, """
            SELECT a.audit_id FROM agent_audit a
              JOIN agent_runs r ON r.run_id=a.run_id
              JOIN artifacts target ON target.artifact_id=a.resource_id
             WHERE r.owner_principal=:owner AND r.workspace_id=:workspace
               AND target.owner_principal=:owner AND target.workspace_id=:workspace
             ORDER BY a.audit_id LIMIT 1
        """, params)
        if retained_audit is not None:
            raise WorkspaceResetBlocked(
                "Agent audit references a workspace Artifact; reset would remove an authoritative fact"
            )

        retained_task_approval = self._first_row(connection, """
            SELECT a.approval_id FROM agent_approvals a
              JOIN agent_runs r ON r.run_id=a.run_id
              JOIN research_tasks t ON t.task_id=a.plan_task_id
             WHERE r.owner_principal=:owner AND r.workspace_id=:workspace
               AND t.owner_principal=:owner AND t.workspace_id=:workspace
             ORDER BY a.approval_id LIMIT 1
        """, params)
        if retained_task_approval is not None:
            raise WorkspaceResetBlocked(
                "Agent approval references a ResearchTask; reset would remove an authoritative fact"
            )

        retained_task_audit = self._first_row(connection, """
            SELECT a.audit_id FROM agent_audit a
              JOIN agent_runs r ON r.run_id=a.run_id
              JOIN research_tasks t ON t.task_id=a.resource_id
             WHERE r.owner_principal=:owner AND r.workspace_id=:workspace
               AND t.owner_principal=:owner AND t.workspace_id=:workspace
               AND a.resource_type='research_task'
             ORDER BY a.audit_id LIMIT 1
        """, params)
        if retained_task_audit is not None:
            raise WorkspaceResetBlocked(
                "Agent audit references a ResearchTask; reset would remove an authoritative fact"
            )

        # This first slice does not classify the separate learning subsystem.
        for table, identity_column in (
            ("learning_runs", "learning_run_id"),
            ("evaluation_signals", "signal_id"),
            ("lessons", "lesson_id"),
            ("learning_history", "history_id"),
        ):
            learning_row = self._first_row(connection, f"""
                SELECT {identity_column} FROM {table}
                 WHERE workspace_id=:workspace ORDER BY {identity_column} LIMIT 1
            """, params)
            if learning_row is not None:
                raise WorkspaceResetBlocked(
                    f"workspace contains unclassified {table} records; reset was not started"
                )

    @staticmethod
    def _object_reference(value: object) -> dict[str, object] | None:
        if not isinstance(value, dict):
            return None
        namespace = value.get("namespace")
        object_id = value.get("object_id")
        digest = value.get("sha256")
        size = value.get("size")
        media_type = value.get("media_type")
        if (not isinstance(namespace, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", namespace) is None
                or not isinstance(object_id, str) or re.fullmatch(r"[a-f0-9]{64}", object_id) is None
                or digest != object_id or isinstance(size, bool) or not isinstance(size, int) or size < 0
                or not isinstance(media_type, str) or not media_type or len(media_type) > 128):
            return None
        return {"namespace": namespace, "object_id": object_id, "sha256": digest,
                "size": size, "media_type": media_type}

    @staticmethod
    def _object_candidates(connection, *, owner: str, workspace: str) -> list[dict[str, object]]:
        params = {"owner": owner, "workspace": workspace}
        raw: list[object] = []
        rows = connection.execute(text("""
            SELECT content->'object_reference' AS reference
              FROM artifacts
             WHERE owner_principal=:owner AND workspace_id=:workspace
               AND content->'object_reference' IS NOT NULL
            UNION ALL
            SELECT content->'result_reference' AS reference
              FROM artifacts
             WHERE owner_principal=:owner AND workspace_id=:workspace
               AND content->'result_reference' IS NOT NULL
            UNION ALL
            SELECT result_reference_json AS reference FROM backtest_jobs
             WHERE owner_principal=:owner AND workspace_id=:workspace
               AND result_reference_json IS NOT NULL
        """), params).mappings().all()
        raw.extend(row["reference"] for row in rows)
        if any(WorkspaceResetStore._object_reference(item) is None for item in raw):
            raise WorkspaceResetBlocked(
                "workspace contains an unrecognized object reference; object cleanup cannot be proven safe"
            )
        unique: dict[tuple[str, str], dict[str, object]] = {}
        for item in raw:
            reference = WorkspaceResetStore._object_reference(item)
            assert reference is not None
            unique[(str(reference["namespace"]), str(reference["object_id"]))] = reference
        return [unique[key] for key in sorted(unique)]

    def reset_workspace(self, *, owner_principal: str, workspace_id: str,
                        preview: bool = False) -> dict[str, object]:
        """Delete one exact personal workspace's disposable research graph.

        The method is idempotent. It raises before any committed deletion when
        a durable Job, Agent authority, approval fact, or unresolved external
        action pins the graph. Object files are never deleted here; validated
        CAS references are returned for an offline global-reference GC pass.
        """
        owner = self._identity(owner_principal, "owner_principal")
        workspace = self._identity(workspace_id, "workspace_id")
        if type(preview) is not bool:
            raise ValueError("preview must be a boolean")
        params = {"owner": owner, "workspace": workspace}
        deleted: dict[str, int] = {}
        candidate_refs: list[dict[str, object]] = []

        try:
            with self._lock, self.engine.begin() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '5s'"))
                connection.execute(text("SET LOCAL statement_timeout = '120s'"))
                connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                                   {"scope": f"workspace-reset|{workspace}"})
                self._required_schema(connection)
                workspace_row = connection.execute(text("""
                    SELECT w.workspace_id FROM workspaces w
                      JOIN users u ON u.user_id=w.owner_user_id
                      JOIN workspace_memberships m ON m.workspace_id=w.workspace_id AND m.user_id=u.user_id
                     WHERE w.workspace_id=:workspace AND u.username=:owner
                       AND w.kind='personal' AND w.status='active' AND u.status='active'
                       AND m.role='owner' AND m.status='active'
                     FOR UPDATE OF w
                """), params).first()
                if workspace_row is None:
                    raise WorkspaceNotFound("active personal workspace ownership is required")

                self._check_unknown_foreign_keys(connection, owner=owner, workspace=workspace)
                self._preflight(connection, owner=owner, workspace=workspace)
                candidate_refs = self._object_candidates(connection, owner=owner, workspace=workspace)

                if preview:
                    return {"schema_version": "workspace-reset-preview.v1",
                            "workspace_id": workspace, "ready": True,
                            "candidate_object_references": candidate_refs}

                for table, sql in _DELETE_PLAN:
                    result = connection.execute(text(sql), params)
                    deleted[table] = max(0, int(result.rowcount or 0))

                # Identify CAS objects which have no remaining database row
                # reference. The caller still performs the filesystem check and
                # delete; no shared blob is removed in this transaction.
                global_rows = connection.execute(text("""
                    SELECT content->'object_reference' AS reference FROM artifacts
                     WHERE content->'object_reference' IS NOT NULL
                    UNION ALL
                    SELECT content->'result_reference' AS reference FROM artifacts
                     WHERE content->'result_reference' IS NOT NULL
                    UNION ALL
                    SELECT result_reference_json AS reference FROM backtest_jobs
                     WHERE result_reference_json IS NOT NULL
                """)).mappings().all()
                live = set()
                global_scan_complete = True
                for row in global_rows:
                    reference = self._object_reference(row["reference"])
                    if reference is None:
                        global_scan_complete = False
                        continue
                    live.add((reference["namespace"], reference["object_id"]))
                safe_object_refs = [ref for ref in candidate_refs
                    if global_scan_complete and (ref["namespace"], ref["object_id"]) not in live]
                retained_object_refs = [ref for ref in candidate_refs
                    if (ref["namespace"], ref["object_id"]) in live]
        except (WorkspaceNotFound, WorkspaceResetBlocked):
            raise
        except SQLAlchemyError as error:
            constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            if constraint:
                raise WorkspaceResetBlocked(
                    f"foreign-key constraint {constraint} pins workspace data; transaction rolled back"
                ) from error
            raise WorkspaceResetPersistenceError("workspace reset transaction failed and was rolled back") from error

        blockers = []
        if candidate_refs and not global_scan_complete:
            blockers.append("database contains unrecognized global object references; CAS deletion is not authorized")
        return {
            "schema_version": "workspace-reset.v1",
            "workspace_id": workspace,
            "deleted": deleted,
            "already_empty": not any(deleted.values()),
            "candidate_object_references": candidate_refs,
            "unreferenced_object_references": safe_object_refs,
            "retained_object_references": retained_object_refs,
            "object_cleanup_complete": not candidate_refs,
            "blockers": blockers,
        }
