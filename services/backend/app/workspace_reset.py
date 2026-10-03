"""Transactional personal Product reset with seven-day archive (ADR-0091).

Same identity, static ownership and closed history only; no shared schema/data
reset, Agent recovery or unknown external replay. Binary collection is separate.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, execute
from .workspace_reset_scope import RESET_SCOPE, SCOPE_BY_TABLE, RETIRED_KEY_FIELDS


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
_DELETE_PLAN = tuple((table, f"DELETE FROM {table} r WHERE {predicate}")
                     for table, predicate in RESET_SCOPE)
_DELETE_TABLES = frozenset(SCOPE_BY_TABLE)
_DELETE_ORDER = {table: index for index, (table, _sql) in enumerate(_DELETE_PLAN)}
_REQUIRED_TABLES = tuple(dict.fromkeys((*_REQUIRED_TABLES, *SCOPE_BY_TABLE,
    "workspace_reset_archives", "workspace_reset_retired_keys", "workspace_reset_expired_objects")))
MAX_ARCHIVE_ROWS = 100000
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024


class WorkspaceResetError(RuntimeError):
    """Safe base for workspace reset failures."""


class WorkspaceNotFound(WorkspaceResetError):
    """The exact active personal workspace ownership binding was not found."""


class WorkspaceResetBlocked(WorkspaceResetError):
    """Reset would cross an active job, authority, audit, or FK boundary."""


class WorkspaceResetPersistenceError(WorkspaceResetError):
    """The reset transaction could not be completed."""


class WorkspaceResetStore(PgStoreMixin):
    """Archive and delete one workspace's explicitly classified closed personal data."""

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
        targets = tuple(sorted(SCOPE_BY_TABLE))
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

            child_columns = list(row["child_columns"] or [])
            parent_columns = list(row["parent_columns"] or [])
            if not child_columns or len(child_columns) != len(parent_columns):
                raise WorkspaceResetBlocked(
                    f"foreign-key constraint {row['constraint_name']} cannot be classified"
                )
            joins = " AND ".join(
                f"childrow.{quote(str(child_column))}=target.{quote(str(parent_column))}"
                for child_column, parent_column in zip(child_columns, parent_columns)
            )
            # A known child is safe only when the referencing row is also
            # selected, and deletes first (or in the same self-FK DELETE).
            predicate = SCOPE_BY_TABLE[parent].replace("r.", "target.")
            selected_child = SCOPE_BY_TABLE.get(child)
            child_filter = ""
            if child_order is not None and parent_order is not None and child_order <= parent_order:
                child_filter = " AND (" + selected_child.replace("r.", "childrow.") + ") IS NOT TRUE"
            referenced = connection.execute(text(f"""
                SELECT 1 FROM {quote(child)} childrow JOIN {quote(parent)} target ON {joins}
                 WHERE ({predicate}) {child_filter} LIMIT 1
            """), {"workspace":workspace, "owner":owner,
                   "user_id": connection.execute(text("SELECT user_id FROM users WHERE username=:owner"),
                      {"owner":owner}).scalar_one()}).first()
            if referenced is not None:
                raise WorkspaceResetBlocked(
                    f"foreign-key constraint {row['constraint_name']} retains out-of-scope rows; reset was not started")

        for child,foreign,parent,key in (
            ('ml_training_runs','task_id','research_tasks','task_id'),
            ('ml_training_runs','stock_pool_snapshot_id','stock_pool_snapshots','snapshot_id'),
            ('ml_prediction_runs','task_id','research_tasks','task_id'),
            ('ml_prediction_runs','stock_pool_snapshot_id','stock_pool_snapshots','snapshot_id'),
            ('backtest_jobs','task_id','research_tasks','task_id'),
            ('optimization_jobs','task_id','research_tasks','task_id'),
            ('factor_jobs','task_id','research_tasks','task_id'),
            ('paper_accounts','bound_pool_id','stock_pools','pool_id'),
            ('paper_accounts','bound_snapshot_id','stock_pool_snapshots','snapshot_id'),
            ('paper_orders','pool_id','stock_pools','pool_id'),
            ('paper_orders','stock_pool_snapshot_id','stock_pool_snapshots','snapshot_id'),
            ('stock_pool_domain_references','pool_id','stock_pools','pool_id'),
            ('stock_pool_domain_references','snapshot_id','stock_pool_snapshots','snapshot_id'),
            ('learning_runs','task_id','research_tasks','task_id'),
            ('evaluation_signals','task_id','research_tasks','task_id'),
            ('evaluation_signals','source_artifact_id','artifacts','artifact_id'),
            ('lessons','task_id','research_tasks','task_id'),
        ):
            left=SCOPE_BY_TABLE[child].replace('r.','c.')
            right=SCOPE_BY_TABLE[parent].replace('r.','target.')
            row=connection.execute(text(f"""SELECT 1 FROM {child} c JOIN {parent} target
              ON c.{foreign}=target.{key} WHERE (({left}) IS TRUE AND ({right}) IS NOT TRUE)
                OR (({right}) IS TRUE AND ({left}) IS NOT TRUE) LIMIT 1"""),
                {'owner':owner,'workspace':workspace}).first()
            if row is not None:
                raise WorkspaceResetBlocked('cross-Workspace domain reference prevents reset')

        # New Workspace tables are not implicitly swept into the reset contract.
        columns = connection.execute(text("""SELECT table_name FROM information_schema.columns
          WHERE table_schema=current_schema() AND column_name='workspace_id'""")).scalars().all()
        excluded = {"workspaces","workspace_memberships","workspace_reset_receipts",
                    "workspace_reset_archives","workspace_reset_retired_keys","strategy_approval_fact_archive"}
        for table in columns:
            if table not in SCOPE_BY_TABLE and table not in excluded:
                if connection.execute(text(f"SELECT 1 FROM {quote(table)} WHERE workspace_id=:workspace LIMIT 1"),
                                      {"workspace":workspace}).first() is not None:
                    raise WorkspaceResetBlocked(f"unclassified personal table {table} prevents reset")

    @staticmethod
    def _first_row(connection, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
        row = connection.execute(text(sql), params).mappings().first()
        return None if row is None else dict(row)

    @staticmethod
    def _content_digest(content: object) -> str | None:
        if not isinstance(content, dict):
            return None
        try:
            body = json.dumps(content, ensure_ascii=False, allow_nan=False,
                              sort_keys=True, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError):
            return None
        return hashlib.sha256(body).hexdigest()

    @staticmethod
    def _strategy_approval_archive_candidates(connection, *, owner: str, workspace: str) -> list[dict[str, Any]]:
        params = {"owner": owner, "workspace": workspace}
        count = int(connection.execute(text("""
            SELECT COUNT(*) FROM artifacts WHERE owner_principal=:owner AND workspace_id=:workspace
              AND kind IN ('strategy_approval','ml_strategy_approval')
        """), params).scalar_one())
        if count == 0:
            return []

        rows = connection.execute(text("""
            SELECT a.artifact_id, a.task_id, a.experiment_id, a.owner_principal, a.workspace_id, a.kind, a.status,
                   a.content, a.content_sha256, a.lineage, a.created_at, to_jsonb(a) AS snapshot,
                   t.owner_principal AS task_owner, t.workspace_id AS task_workspace,
                   v.artifact_id AS version_artifact_id, v.task_id AS version_task,
                   v.owner_principal AS version_owner, v.workspace_id AS version_workspace,
                   v.kind AS version_kind, v.status AS version_status, v.content AS version_content,
                   v.content_sha256 AS version_hash, v.created_at AS version_created,
                   to_jsonb(v) AS version_snapshot
              FROM artifacts a JOIN research_tasks t ON t.task_id=a.task_id
              LEFT JOIN artifacts v ON v.artifact_id=CASE a.kind
                   WHEN 'strategy_approval' THEN a.content->>'strategy_version_artifact_id'
                   WHEN 'ml_strategy_approval' THEN a.content->>'ml_strategy_artifact_id' END
             WHERE a.owner_principal=:owner AND a.workspace_id=:workspace
               AND a.kind IN ('strategy_approval','ml_strategy_approval')
             ORDER BY a.artifact_id
        """), params).mappings().all()
        if len(rows) != count:
            raise WorkspaceResetBlocked("strategy approval archive source count is incomplete; reset was not started")

        candidates = []
        for source in rows:
            row = dict(source)
            if row["kind"] == "strategy_approval":
                target_field, version_field, version_kind, schema = (
                    "strategy_version_artifact_id", "strategy_version_id", "strategy_version", "strategy-approval-v1")
            elif row["kind"] == "ml_strategy_approval":
                target_field, version_field, version_kind, schema = (
                    "ml_strategy_artifact_id", "ml_strategy_version_id", "ml_strategy_version", "ml-strategy-approval.v1")
            else:
                raise WorkspaceResetBlocked("unknown strategy approval kind prevents workspace reset")
            content, version = row["content"], row["version_content"]
            fields = {"schema_version", target_field, version_field, "decision", "reviewer_principal",
                      "rationale", "execution_authorized", "execution_outcome"}
            target_id = content.get(target_field) if isinstance(content, dict) else None
            digest = WorkspaceResetStore._content_digest(content)
            version_digest = WorkspaceResetStore._content_digest(version)
            expected_lineage = [{"kind": "research_task", "id": row["task_id"]}]
            if row["experiment_id"] is not None:
                expected_lineage.append({"kind": "experiment", "id": row["experiment_id"]})
            expected_lineage.append({"kind": "artifact", "id": target_id})
            if (row["status"] != "validated" or not isinstance(content, dict) or set(content) != fields
                    or content.get("schema_version") != schema or content.get("decision") not in {"approved", "rejected"}
                    or type(content.get("execution_authorized")) is not bool
                    or content["execution_authorized"] != (content["decision"] == "approved")
                    or content.get("execution_outcome") != "not_started"
                    or not isinstance(content.get("reviewer_principal"), str) or not content["reviewer_principal"].strip()
                    or len(content["reviewer_principal"]) > 128
                    or not isinstance(content.get("rationale"), str) or len(content["rationale"]) > 4000
                    or digest is None or row["content_sha256"] != digest
                    or not isinstance(target_id, str) or row["version_artifact_id"] != target_id
                    or row["version_kind"] != version_kind or row["version_status"] != "validated"
                    or row["task_id"] != row["version_task"]
                    or row["owner_principal"] != owner or row["workspace_id"] != workspace
                    or row["version_owner"] != owner or row["version_workspace"] != workspace
                    or row["task_owner"] != owner or row["task_workspace"] != workspace
                    or row["created_at"] is None or row["version_created"] is None
                    or version_digest is None or row["version_hash"] != version_digest
                    or not isinstance(row["snapshot"], dict) or not isinstance(row["version_snapshot"], dict)
                    or row["lineage"] != expected_lineage):
                raise WorkspaceResetBlocked("strategy approval fact is incomplete or has a bad/cross-Workspace version reference; reset was not started")
            try:
                if row["kind"] == "strategy_approval":
                    from .strategy_artifact import validate_version_content
                    validated_version = validate_version_content(version)
                else:
                    from .ml_strategy import validate_ml_strategy_version
                    validated_version = validate_ml_strategy_version(version)
            except Exception as error:
                raise WorkspaceResetBlocked("strategy approval version failed validation; reset was not started") from error
            if (not isinstance(validated_version, dict)
                    or validated_version.get("version_id") != content.get(version_field)):
                raise WorkspaceResetBlocked("strategy approval version identity is inconsistent; reset was not started")
            row["target_id"] = target_id
            candidates.append(row)
        return candidates

    @staticmethod
    def _preflight(connection, *, owner: str, workspace: str,
                   allow_active_agent_roots: bool = False) -> None:
        params = {"owner": owner, "workspace": workspace}

        if not allow_active_agent_roots:
            root = WorkspaceResetStore._first_row(connection, """
                SELECT root_run_id FROM agent_runtime_turns
                 WHERE owner_principal=:owner AND workspace_id=:workspace
                   AND (status='active' OR authority_status <> 'closed')
                 ORDER BY root_run_id LIMIT 1
            """, params)
            if root is not None:
                raise WorkspaceResetBlocked("active or unconfirmed Agent root prevents workspace reset")

            run = WorkspaceResetStore._first_row(connection, """
                SELECT run_id FROM agent_runs
                 WHERE owner_principal=:owner AND workspace_id=:workspace
                   AND (status IN ('active','pending_binding') OR authority_status <> 'closed')
                 ORDER BY run_id LIMIT 1
            """, params)
            if run is not None:
                raise WorkspaceResetBlocked("active or unconfirmed Agent run prevents workspace reset")

        claim = WorkspaceResetStore._first_row(connection, """
            SELECT c.claim_id FROM agent_domain_call_claims c
              JOIN agent_domain_correction_buckets b
                ON b.root_run_id=c.root_run_id AND b.task_id=c.task_id AND b.action=c.action
             WHERE b.owner_principal=:owner AND b.workspace_id=:workspace
               AND c.status IN ('claimed','executing')
             ORDER BY c.claim_id LIMIT 1
        """, params)
        if claim is not None:
            raise WorkspaceResetBlocked("unresolved external domain action prevents workspace reset")

        unknown_approval = WorkspaceResetStore._first_row(connection, """
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
            row = WorkspaceResetStore._first_row(connection, f"""
                SELECT {identity_column} AS identity FROM {table}
                 WHERE owner_principal=:owner AND workspace_id=:workspace
                   AND status NOT IN ({placeholders})
                 ORDER BY {identity_column} LIMIT 1
            """, job_params)
            if row is not None:
                raise WorkspaceResetBlocked(f"active or unclassified {table} row prevents workspace reset")

        admitted = WorkspaceResetStore._first_row(connection, """
            SELECT c.call_identity FROM research_judgment_stage_calls c
              JOIN research_tasks t ON t.task_id=c.task_id
             WHERE t.owner_principal=:owner AND t.workspace_id=:workspace AND c.status='admitted'
             ORDER BY c.call_identity LIMIT 1
        """, params)
        if admitted is not None:
            raise WorkspaceResetBlocked("admitted research judgment call prevents workspace reset")

        receipt = WorkspaceResetStore._first_row(connection, """
            SELECT watch_id FROM research_receipt_watches
             WHERE owner_principal=:owner AND workspace_id=:workspace
               AND state NOT IN ('confirmed','conflict')
             ORDER BY watch_id LIMIT 1
        """, params)
        if receipt is not None:
            raise WorkspaceResetBlocked("unresolved research submission receipt prevents workspace reset")

        # A prepared preview has no submission. A rejection is closed only if
        # the frozen key has no receipt; a confirmation must name the exact
        # terminal Job. Unknown or contradictory watch states remain blocked.
        ml_watch = WorkspaceResetStore._first_row(connection, """
            SELECT w.watch_id FROM ml_training_receipt_watches w
             WHERE w.workspace_id=:workspace AND w.owner_principal=:owner
               AND (CASE
                 WHEN w.state IN ('prepared','rejected') THEN
                   w.training_run_id IS NULL
                   AND (w.state='rejected' OR w.check_count=0)
                   AND NOT EXISTS (SELECT 1 FROM ml_training_submission_keys k
                     WHERE k.workspace_id=w.workspace_id AND k.owner_principal=w.owner_principal
                       AND k.idempotency_key=w.idempotency_key)
                   AND NOT EXISTS (SELECT 1 FROM ml_training_runs r
                     WHERE r.workspace_id=w.workspace_id AND r.owner_principal=w.owner_principal
                       AND r.idempotency_key=w.idempotency_key)
                 WHEN w.state='confirmed' THEN
                   EXISTS (SELECT 1 FROM ml_training_runs r
                     WHERE r.training_run_id=w.training_run_id
                       AND r.workspace_id=w.workspace_id AND r.owner_principal=w.owner_principal
                       AND r.status IN ('completed','failed','cancelled')
                       AND jsonb_build_object('workspace_id',r.workspace_id,
                         'owner_principal',r.owner_principal,'task_id',r.task_id,
                         'experiment_id',r.experiment_id,
                         'ml_strategy_artifact_id',r.ml_strategy_artifact_id,
                         'stock_pool_snapshot_id',r.stock_pool_snapshot_id)=w.identity_json
                       AND (r.idempotency_key=w.idempotency_key OR EXISTS
                         (SELECT 1 FROM ml_training_submission_keys k
                          WHERE k.workspace_id=w.workspace_id AND k.owner_principal=w.owner_principal
                            AND k.idempotency_key=w.idempotency_key
                            AND k.training_run_id=r.training_run_id)))
                   AND NOT EXISTS (SELECT 1 FROM ml_training_submission_keys k
                     WHERE k.workspace_id=w.workspace_id AND k.owner_principal=w.owner_principal
                       AND k.idempotency_key=w.idempotency_key AND k.training_run_id<>w.training_run_id)
                   AND NOT EXISTS (SELECT 1 FROM ml_training_runs r
                     WHERE r.workspace_id=w.workspace_id AND r.owner_principal=w.owner_principal
                       AND r.idempotency_key=w.idempotency_key AND r.training_run_id<>w.training_run_id)
                 ELSE false END) IS NOT TRUE
             ORDER BY w.watch_id LIMIT 1
        """, params)
        if ml_watch is not None:
            raise WorkspaceResetBlocked("unresolved ml_training_receipt_watches prevents workspace reset")

        WorkspaceResetStore._strategy_approval_archive_candidates(connection, owner=owner, workspace=workspace)
        for table, predicate in (
            ("learning_runs", "status NOT IN ('completed','failed','cancelled')"),
            ("stock_pool_materialization_runs", "status NOT IN ('succeeded','failed','cancelled')"),
            ("research_task_actions", "status IN ('pending','waiting_for_agent','needs_attention')"),
        ):
            row = WorkspaceResetStore._first_row(connection,
                f"SELECT 1 FROM {table} WHERE workspace_id=:workspace AND {predicate} LIMIT 1", params)
            if row is not None:
                raise WorkspaceResetBlocked(f"unresolved {table} prevents workspace reset")
        # Keep both Hub and legacy local-publication checks until their rows
        # are separately classified. failed_terminal is not evidence that an
        # external create had no effect; lost-response outcomes remain unknown.
        checks = (
            ("product_feedback_outbox", """r.lease_owner IS NOT NULL OR r.lease_expires_at IS NOT NULL
               OR (r.state='published' AND NOT EXISTS (SELECT 1 FROM product_feedback_publications p
                   WHERE p.publication_id=r.publication_id AND p.github_issue_number IS NOT NULL
                     AND p.provider_identity IS NOT NULL AND p.published_at IS NOT NULL))
               OR (r.state='failed_terminal' AND r.create_started)
               OR r.state NOT IN ('published','failed_terminal')"""),
            ("product_feedback_hub_outbox", """r.lease_owner IS NOT NULL OR r.lease_expires_at IS NOT NULL
               OR (r.state IN ('published','rejected','duplicate') AND r.receipt_id IS NULL)
               OR (r.state IN ('failed_terminal','cancelled') AND r.attempt>0)
               OR r.state NOT IN ('published','rejected','duplicate','failed_terminal','cancelled')"""),
        )
        for table,unresolved in checks:
            row = WorkspaceResetStore._first_row(connection,f"""SELECT 1 FROM {table} r
              JOIN product_feedback f ON f.feedback_id=r.feedback_id
              WHERE f.workspace_id=:workspace AND ({unresolved}) LIMIT 1""",params)
            if row is not None:
                raise WorkspaceResetBlocked('unresolved feedback delivery prevents workspace reset')
        tasks = connection.execute(text("""SELECT task_id,continuation_permission,continuation_budget
          FROM research_tasks WHERE owner_principal=:owner AND workspace_id=:workspace"""), params).mappings()
        for task in tasks:
            ledger = task['continuation_budget']
            if ledger is not None and (not isinstance(ledger,list) or any(
                not isinstance(r,dict) or r.get('status') not in {'settled','rejected'} for r in ledger)):
                raise WorkspaceResetBlocked("unresolved continuation reservation prevents workspace reset")
            permission = task['continuation_permission']
            if permission is not None and not isinstance(permission,dict):
                raise WorkspaceResetBlocked("unclassified continuation permission prevents workspace reset")
            if permission and not allow_active_agent_roots:
                expiry = permission.get('expires_at')
                try:
                    expired = datetime.fromisoformat(expiry).astimezone(timezone.utc) <= datetime.now(timezone.utc)
                except (TypeError, ValueError):
                    expired = False
                if permission.get('revoked_at') is None and not expired:
                    raise WorkspaceResetBlocked("active continuation permission prevents workspace reset")

    @staticmethod
    def preflight_in_connection(
        connection,
        *,
        owner_principal: str,
        workspace_id: str,
        expected_status: str = "active",
        allow_active_agent_roots: bool = False,
    ) -> None:
        """Run the complete scoped reset preflight on a caller-owned transaction.

        Product reset uses this at begin (while allowing roots that this explicit
        operation will revoke) and again during finalize after those roots have
        been closed. The offline reset keeps the default active Workspace check.
        """
        owner = WorkspaceResetStore._identity(owner_principal, "owner_principal")
        workspace = WorkspaceResetStore._identity(workspace_id, "workspace_id")
        if expected_status not in {"active", "disabled"}:
            raise ValueError("expected_status must be active or disabled")
        WorkspaceResetStore._required_schema(connection)
        params = {"owner": owner, "workspace": workspace, "status": expected_status}
        workspace_row = connection.execute(text("""
            SELECT w.workspace_id FROM workspaces w
              JOIN users u ON u.user_id=w.owner_user_id
              JOIN workspace_memberships m ON m.workspace_id=w.workspace_id AND m.user_id=u.user_id
             WHERE w.workspace_id=:workspace AND u.username=:owner
               AND w.kind='personal' AND w.status=:status AND u.status='active'
               AND m.role='owner' AND m.status='active'
             FOR UPDATE OF w
        """), params).first()
        if workspace_row is None:
            raise WorkspaceNotFound("active personal workspace ownership is required")
        WorkspaceResetStore._check_unknown_foreign_keys(connection, owner=owner, workspace=workspace)
        WorkspaceResetStore._preflight(connection, owner=owner, workspace=workspace,
                                       allow_active_agent_roots=allow_active_agent_roots)

    @staticmethod
    def revoke_continuation_in_connection(connection, *, owner: str, workspace: str) -> None:
        execute(connection, """UPDATE research_tasks SET continuation_permission=
          continuation_permission || jsonb_build_object('revoked_at',now()::text,'revoked_by',:owner)
          WHERE owner_principal=:owner AND workspace_id=:workspace
            AND continuation_permission IS NOT NULL
            AND continuation_permission->>'revoked_at' IS NULL""", {'owner':owner,'workspace':workspace})

    @staticmethod
    def _archive_in_connection(connection, *, owner: str, workspace: str, reset_id: str,
                               now: datetime) -> tuple[dict[str,int], dict[str,object]]:
        user_id = connection.execute(text('SELECT user_id FROM users WHERE username=:owner'),
                                     {'owner':owner}).scalar_one()
        params = {'owner':owner,'workspace':workspace,'user_id':user_id}
        snapshots = {}; counts = {}; total = 0; encoded_size = 0
        references = {}
        def collect(value):
            if isinstance(value,dict):
                if 'namespace' in value and 'object_id' in value:
                    ref = WorkspaceResetStore._object_reference(value)
                    if ref is None:
                        raise WorkspaceResetBlocked('malformed archived object reference prevents reset')
                    key=(ref['namespace'],ref['object_id'])
                    if key in references and references[key] != ref:
                        raise WorkspaceResetBlocked('conflicting archived object reference prevents reset')
                    references[key]=ref
                for v in value.values(): collect(v)
            elif isinstance(value,list):
                for v in value: collect(v)
        for table,predicate in RESET_SCOPE:
            count = int(connection.execute(text(f'SELECT count(*) FROM {table} r WHERE {predicate}'),params).scalar_one())
            total += count
            if total > MAX_ARCHIVE_ROWS:
                raise WorkspaceResetBlocked('personal archive exceeds row limit; data retained')
            rows = connection.execute(text(f'SELECT to_jsonb(r) AS snapshot FROM {table} r WHERE {predicate}'),params).scalars().all()
            if len(rows) != count:
                raise WorkspaceResetBlocked('archive source count changed; data retained')
            for row in rows:
                if table=='product_feedback_hub_outbox' and row.get('status_token'):
                    row['status_token_sha256']=hashlib.sha256(row.pop('status_token').encode('utf8')).hexdigest()
            encoded = [json.dumps(row,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')) for row in rows]
            encoded.sort(); encoded_size += sum(len(row.encode('utf8')) for row in encoded)
            if encoded_size > MAX_ARCHIVE_BYTES:
                raise WorkspaceResetBlocked('personal archive exceeds byte limit; data retained')
            snapshots[table] = [json.loads(row) for row in encoded]; counts[table] = count
            collect(rows)
        profile = connection.execute(text("""SELECT jsonb_build_object('preferences',preferences,
          'default_prompt',default_prompt,'preferences_version',preferences_version)
          FROM users WHERE user_id=:user_id"""),params).scalar_one()
        payload = {'schema_version':'personal-reset-archive.v1','tables':snapshots,'profile_defaults':profile}
        encoded = json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf8')
        if len(encoded) > MAX_ARCHIVE_BYTES:
            raise WorkspaceResetBlocked('personal archive exceeds byte limit; data retained')
        digest = hashlib.sha256(encoded).hexdigest(); expires=now+timedelta(days=7)
        refs = [references[key] for key in sorted(references)]
        execute(connection, """INSERT INTO workspace_reset_archives
          (reset_id,workspace_id,owner_principal,created_at,expires_at,payload_json,
           payload_sha256,counts_json,object_references_json)
          VALUES (:reset_id,:workspace,:owner,:now,:expires,CAST(:payload AS jsonb),:digest,
                  CAST(:counts AS jsonb),CAST(:refs AS jsonb))""",
          params|{'reset_id':reset_id,'now':now,'expires':expires,'payload':payload,'digest':digest,'counts':counts,'refs':refs})
        saved = connection.execute(text('SELECT payload_json,counts_json FROM workspace_reset_archives WHERE reset_id=:id'),
                                   {'id':reset_id}).mappings().one()
        if WorkspaceResetStore._content_digest(saved['payload_json']) != digest or saved['counts_json'] != counts:
            raise WorkspaceResetBlocked('archive verification failed; data retained')
        for table,fields in RETIRED_KEY_FIELDS.items():
            predicate = SCOPE_BY_TABLE[table]
            field_sql = ','.join(f"'{field}',to_jsonb(r)->'{field}'" for field in fields)
            nonnull = ' AND '.join(f"to_jsonb(r)->>'{field}' IS NOT NULL" for field in fields)
            execute(connection, f"""INSERT INTO workspace_reset_retired_keys
              (source_table,identity_sha256,reset_id,workspace_id)
              SELECT :table,encode(sha256(convert_to(jsonb_build_object({field_sql})::text,'UTF8')),'hex'),
                     :reset_id,:workspace FROM {table} r WHERE ({predicate}) AND {nonnull}
              ON CONFLICT(source_table,identity_sha256) DO NOTHING""", params|{'table':table,'reset_id':reset_id})
        return counts, {'reset_id':reset_id,'created_at':now.isoformat(),'expires_at':expires.isoformat(),
                        'retention_days':7,'row_count':total,'payload_sha256':digest}

    @staticmethod
    def reset_in_connection(connection, *, owner_principal: str, workspace_id: str,
                            reset_id: str | None = None, now: datetime | None = None) -> dict[str,object]:
        owner = WorkspaceResetStore._identity(owner_principal,'owner_principal')
        workspace = WorkspaceResetStore._identity(workspace_id,'workspace_id')
        reset_id = reset_id or uuid.uuid4().hex; now = now or datetime.now(timezone.utc)
        params = {'owner':owner,'workspace':workspace,
                  'user_id':connection.execute(text('SELECT user_id FROM users WHERE username=:owner'),{'owner':owner}).scalar_one()}
        counts, archive = WorkspaceResetStore._archive_in_connection(
            connection,owner=owner,workspace=workspace,reset_id=reset_id,now=now)
        execute(connection,"SELECT set_config('byq.personal_reset_id',:id,true)",{'id':reset_id})
        deleted = {}
        for table,sql in _DELETE_PLAN:
            result = connection.execute(text(sql),params)
            deleted[table] = max(0,int(result.rowcount or 0))
            if deleted[table] != counts[table]:
                raise WorkspaceResetBlocked('archive/delete count mismatch; transaction rolled back')
        execute(connection,"""UPDATE users SET preferences=NULL,default_prompt=NULL,
          preferences_version=preferences_version+1,updated_at=:now WHERE user_id=:user_id""",params|{'now':now})
        return {'deleted':deleted,'archive':archive}

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
        """Archive and reset one exact personal Product scope with the same identity.

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
                self.preflight_in_connection(
                    connection, owner_principal=owner, workspace_id=workspace,
                )
                candidate_refs = self._object_candidates(connection, owner=owner, workspace=workspace)

                if preview:
                    return {"schema_version": "workspace-reset-preview.v1",
                            "workspace_id": workspace, "ready": True,
                            "candidate_object_references": candidate_refs}

                reset_id=uuid.uuid4().hex
                self.revoke_continuation_in_connection(connection,owner=owner,workspace=workspace)
                execute(connection,"""UPDATE workspaces SET status='disabled',reset_kind='workspace',reset_id=:id
                  WHERE workspace_id=:workspace""",params|{'id':reset_id})
                result = self.reset_in_connection(connection, owner_principal=owner, workspace_id=workspace,reset_id=reset_id)
                execute(connection,"""UPDATE workspaces SET status='active',reset_kind=NULL,reset_id=NULL
                  WHERE workspace_id=:workspace""",params)
                deleted = result['deleted']
                archive = result['archive']
                execute(connection,"""INSERT INTO workspace_reset_receipts
                  (workspace_id,request_key,reset_id,receipt_json,released_sessions_json,created_at)
                  VALUES (:workspace,:key,:id,CAST(:receipt AS jsonb),'[]'::jsonb,now())""",
                  params|{'key':str(uuid.uuid4()),'id':reset_id,'receipt':{'status':'reset','workspace_id':workspace,
                   'deleted':deleted,'already_empty':not any(deleted.values()),'archive':archive}})

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
                    UNION ALL
                    SELECT value AS reference FROM workspace_reset_archives,
                      jsonb_array_elements(object_references_json) WHERE expires_at>now()
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
            "archive": archive,
            "candidate_object_references": candidate_refs,
            "unreferenced_object_references": safe_object_refs,
            "retained_object_references": retained_object_refs,
            "object_cleanup_complete": not candidate_refs,
            "blockers": blockers,
        }
