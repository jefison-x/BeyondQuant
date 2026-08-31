"""Admin-only, secret-safe operations projections for Phase 38.

The store exposes aggregate PostgreSQL/domain state and one bounded monitoring
threshold write. It never returns connection strings, encrypted envelopes,
provider secrets, raw DSH events, or unrestricted SQL/control capabilities.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, execute, fetch_one


class OperationsError(RuntimeError):
    pass


class OperationsForbidden(OperationsError):
    pass


class OperationsConflict(OperationsError):
    pass


class OperationsPersistenceError(OperationsError):
    pass


_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_BUDGET_FIELDS = {
    "enabled",
    "alert_total_tokens",
    "alert_requests",
    "expected_version",
    "idempotency_key",
}


class OperationsStore(PgStoreMixin):
    """Own aggregate operations reads and auditable monitoring thresholds."""

    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS operations_budget_policy (
            policy_id TEXT PRIMARY KEY,
            enabled BOOLEAN NOT NULL,
            alert_total_tokens BIGINT NOT NULL,
            alert_requests BIGINT NOT NULL,
            version INTEGER NOT NULL,
            updated_by TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS operations_audit (
            audit_id TEXT PRIMARY KEY,
            actor_principal TEXT NOT NULL,
            action TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            outcome TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_sha256 TEXT NOT NULL,
            detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            response_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS operations_audit_created_idx
            ON operations_audit(created_at DESC, audit_id DESC)
        """,
        """
        INSERT INTO operations_budget_policy
            (policy_id, enabled, alert_total_tokens, alert_requests, version,
             updated_by, updated_at)
        VALUES ('product-agent', FALSE, 400000, 48, 1, 'system-bootstrap', now())
        ON CONFLICT (policy_id) DO NOTHING
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as error:
            raise OperationsPersistenceError("operations storage is unavailable") from error

    def overview(self, *, actor_role: object) -> dict[str, object]:
        self._require_admin(actor_role)
        try:
            with self._transaction() as connection:
                database = fetch_one(
                    connection,
                    """SELECT current_setting('server_version') AS server_version,
                              pg_database_size(current_database()) AS size_bytes""",
                ) or {}
                table_stats = fetch_one(
                    connection,
                    """SELECT COUNT(*)::bigint AS table_count,
                              COALESCE(SUM(n_live_tup), 0)::bigint AS estimated_rows
                       FROM pg_stat_user_tables""",
                ) or {}
                market_cache_exists = bool((fetch_one(
                    connection,
                    "SELECT to_regclass('public.market_daily_bars') IS NOT NULL AS present",
                ) or {}).get("present"))
                domain_counts = execute(
                    connection,
                    """SELECT 'research_tasks' AS resource, COUNT(*)::bigint AS count FROM research_tasks
                       UNION ALL SELECT 'artifacts', COUNT(*)::bigint FROM artifacts
                       UNION ALL SELECT 'backtests', COUNT(*)::bigint FROM backtest_jobs
                       UNION ALL SELECT 'stock_pools', COUNT(*)::bigint FROM stock_pools
                       UNION ALL SELECT 'paper_accounts', COUNT(*)::bigint FROM paper_accounts
                       UNION ALL SELECT 'users', COUNT(*)::bigint FROM users
                       UNION ALL SELECT 'agent_runs', COUNT(*)::bigint FROM agent_runs""",
                )
                if market_cache_exists:
                    cache_groups = execute(
                        connection,
                        """SELECT data_source, asset_type, SUM(row_count)::bigint AS row_count,
                                  COUNT(*)::bigint AS symbol_count,
                                  MIN(date_min) AS date_min, MAX(date_max) AS date_max
                           FROM market_daily_group_symbol_coverage
                           GROUP BY data_source, asset_type
                           ORDER BY data_source, asset_type LIMIT 50""",
                    )
                    market_bar_count = int((fetch_one(
                        connection,
                        """SELECT row_count AS count FROM market_daily_coverage_totals
                           WHERE projection_key = 1""",
                    ) or {}).get("count") or 0)
                else:
                    cache_groups = []
                    market_bar_count = 0
                model_credentials = execute(
                    connection,
                    """SELECT provider AS provider_key, scope, status, COUNT(*)::bigint AS count
                       FROM credentials WHERE purpose = 'model_api_key'
                       GROUP BY provider, scope, status
                       ORDER BY provider, scope, status LIMIT 50""",
                )
                source_credentials = execute(
                    connection,
                    """SELECT provider AS provider_key, scope, status, COUNT(*)::bigint AS count
                       FROM credentials WHERE purpose = 'tushare_token'
                       GROUP BY provider, scope, status
                       ORDER BY provider, scope, status LIMIT 20""",
                )
                model_counts = fetch_one(
                    connection,
                    """SELECT (SELECT COUNT(*) FROM model_profiles)::bigint AS profiles,
                              (SELECT COUNT(*) FROM agent_model_bindings)::bigint AS bindings""",
                ) or {}
                agent_status = execute(
                    connection,
                    """SELECT role_id, status, COUNT(*)::bigint AS count
                       FROM agent_runs GROUP BY role_id, status
                       ORDER BY role_id, status LIMIT 100""",
                )
                recent_runs = execute(
                    connection,
                    """SELECT run_id, role_id, role_version, status, trace_id,
                              session_id, parent_run_id, created_at, updated_at
                       FROM agent_runs ORDER BY created_at DESC, run_id DESC LIMIT 30""",
                )
                access_counts = execute(
                    connection,
                    """SELECT role, status, COUNT(*)::bigint AS count
                       FROM users GROUP BY role, status ORDER BY role, status""",
                )
                agent_audit = execute(
                    connection,
                    """SELECT audit_id, actor_principal, action, outcome,
                              resource_type, resource_id, created_at
                       FROM agent_audit ORDER BY created_at DESC, audit_id DESC LIMIT 30""",
                )
                operations_audit = execute(
                    connection,
                    """SELECT audit_id, actor_principal, action, outcome,
                              resource_type, resource_id, detail_json, created_at
                       FROM operations_audit
                       ORDER BY created_at DESC, audit_id DESC LIMIT 30""",
                )
                stock_pool_producers = execute(
                    connection,
                    """SELECT producer_kind,status,COUNT(*)::bigint AS count
                       FROM stock_pool_producer_definitions
                       GROUP BY producer_kind,status ORDER BY producer_kind,status""",
                )
                stock_pool_runs = execute(
                    connection,
                    """SELECT status,COUNT(*)::bigint AS count
                       FROM stock_pool_materialization_runs GROUP BY status ORDER BY status""",
                )
                recent_stock_pool_failures = execute(
                    connection,
                    """SELECT run_id,pool_id,status,error_code,error_message,finished_at
                       FROM stock_pool_materialization_runs
                       WHERE status IN ('waiting_for_data','failed','cancelled')
                       ORDER BY created_at DESC,run_id DESC LIMIT 20""",
                )
                budget = fetch_one(
                    connection,
                    """SELECT policy_id, enabled, alert_total_tokens, alert_requests,
                              version, updated_by, updated_at
                       FROM operations_budget_policy WHERE policy_id = 'product-agent'""",
                ) or {}
        except SQLAlchemyError as error:
            raise OperationsPersistenceError("operations projection is unavailable") from error

        cache_rows = sum(int(row.get("row_count") or 0) for row in cache_groups)
        domain_counts.append({"resource": "market_bars", "count": market_bar_count})
        return {
            "schema_version": "operations.v1",
            "database": {
                "engine": "postgresql",
                "status": "ready",
                "name": "byq_domain",
                "server_version": str(database.get("server_version") or ""),
                "size_bytes": int(database.get("size_bytes") or 0),
                "table_count": int(table_stats.get("table_count") or 0),
                "estimated_rows": int(table_stats.get("estimated_rows") or 0),
                "domain_counts": domain_counts,
                "migration": {
                    "single_domain_store": "complete",
                    "legacy_sqlite_runtime": False,
                },
            },
            "cache": {
                "kind": "postgresql_market_data",
                "status": "ready" if cache_rows else "empty",
                "row_count": cache_rows,
                "groups": cache_groups,
                "redis": "not_used",
            },
            "models": {
                "credential_metadata": model_credentials,
                "profiles": int(model_counts.get("profiles") or 0),
                "bindings": int(model_counts.get("bindings") or 0),
                "secrets_exposed": False,
            },
            "sources": {
                "provider": "tushare",
                "credential_metadata": source_credentials,
                "configuration_scope": "phase_39",
                "legacy_providers": [],
                "secrets_exposed": False,
            },
            "agents": {
                "status_groups": agent_status,
                "recent_runs": recent_runs,
            },
            "graphs": {
                "projection": "normalized_agent_runs",
                "recent_runs": recent_runs,
                "raw_dsh_events": False,
            },
            "stock_pool_producers": {
                "definitions": stock_pool_producers,
                "runs": stock_pool_runs,
                "recent_non_success": recent_stock_pool_failures,
                "raw_worker_payload": False,
            },
            "access": {
                "principal_groups": access_counts,
                "agent_audit": agent_audit,
                "operations_audit": operations_audit,
            },
            "budget": budget,
        }

    def update_budget(
        self,
        payload: object,
        *,
        actor_principal: object,
        actor_role: object,
    ) -> dict[str, object]:
        self._require_admin(actor_role)
        if not isinstance(payload, dict):
            raise ValueError("operations budget request must be an object")
        unknown = set(payload) - _BUDGET_FIELDS
        if unknown:
            raise ValueError(f"operations budget request has unknown fields: {', '.join(sorted(unknown))}")
        actor = self._text(actor_principal, "actor_principal", 128)
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        total_tokens = self._integer(payload.get("alert_total_tokens"), "alert_total_tokens", 1000, 100_000_000)
        requests = self._integer(payload.get("alert_requests"), "alert_requests", 1, 1_000_000)
        expected_version = self._integer(payload.get("expected_version"), "expected_version", 1, 2_147_483_647)
        key = self._text(payload.get("idempotency_key"), "idempotency_key", 128)
        if not _IDEMPOTENCY.fullmatch(key):
            raise ValueError("idempotency_key has an invalid format")
        canonical = {
            "enabled": enabled,
            "alert_total_tokens": total_tokens,
            "alert_requests": requests,
            "expected_version": expected_version,
        }
        request_hash = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

        try:
            with self._transaction() as connection:
                prior = fetch_one(
                    connection,
                    "SELECT request_sha256, response_json FROM operations_audit WHERE idempotency_key = :key",
                    {"key": key},
                )
                if prior is not None:
                    if prior["request_sha256"] != request_hash:
                        raise OperationsConflict("idempotency key was reused with a different request")
                    response = prior.get("response_json")
                    if not isinstance(response, dict):
                        raise OperationsPersistenceError("stored operations response is invalid")
                    return response

                current = fetch_one(
                    connection,
                    """SELECT policy_id, enabled, alert_total_tokens, alert_requests,
                              version, updated_by, updated_at
                       FROM operations_budget_policy
                       WHERE policy_id = 'product-agent' FOR UPDATE""",
                )
                if current is None:
                    raise OperationsPersistenceError("operations budget policy is missing")
                if int(current["version"]) != expected_version:
                    raise OperationsConflict("operations budget version conflict")
                new_version = expected_version + 1
                execute(
                    connection,
                    """UPDATE operations_budget_policy
                       SET enabled = :enabled, alert_total_tokens = :tokens,
                           alert_requests = :requests, version = :version,
                           updated_by = :actor, updated_at = now()
                       WHERE policy_id = 'product-agent'""",
                    {"enabled": enabled, "tokens": total_tokens, "requests": requests,
                     "version": new_version, "actor": actor},
                )
                result = fetch_one(
                    connection,
                    """SELECT policy_id, enabled, alert_total_tokens, alert_requests,
                              version, updated_by, updated_at
                       FROM operations_budget_policy WHERE policy_id = 'product-agent'""",
                ) or {}
                response: dict[str, object] = {"budget": result}
                execute(
                    connection,
                    """INSERT INTO operations_audit
                       (audit_id, actor_principal, action, resource_type,
                        resource_id, outcome, idempotency_key, request_sha256,
                        detail_json, response_json, created_at)
                       VALUES (:audit_id, :actor, 'budget.threshold.updated',
                               'operations_budget', 'product-agent', 'allowed',
                               :key, :request_hash, :detail, :response, now())""",
                    {
                        "audit_id": f"ops_audit_{uuid.uuid4().hex}",
                        "actor": actor,
                        "key": key,
                        "request_hash": request_hash,
                        "detail": {"version": new_version, "enabled": enabled},
                        "response": response,
                    },
                )
                return response
        except OperationsError:
            raise
        except SQLAlchemyError as error:
            raise OperationsPersistenceError("operations budget update failed") from error

    @staticmethod
    def _require_admin(role: object) -> None:
        if role != "admin":
            raise OperationsForbidden("admin role required")

    @staticmethod
    def _text(value: object, field: str, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
            raise ValueError(f"{field} must be a non-empty string up to {maximum} characters")
        return value.strip()

    @staticmethod
    def _integer(value: object, field: str, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"{field} must be an integer between {minimum} and {maximum}")
        return value
