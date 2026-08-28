"""Durable, admin-only DSH plugin governance projection.

The Product Plane may request policy changes, but it never installs packages,
writes the Git-managed registry, or controls a running DSH process.  A request
therefore stops at ``awaiting_generation`` until the trusted deployment lane
publishes and deploys a deterministic composition.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, execute, fetch_one


class PluginCenterError(RuntimeError):
    pass


class PluginCenterForbidden(PluginCenterError):
    pass


class PluginCenterNotFound(PluginCenterError):
    pass


class PluginCenterConflict(PluginCenterError):
    pass


class PluginCenterPersistenceError(PluginCenterError):
    pass


_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ACTIONS = {"enable", "disable", "assign"}
_MUTATION_FIELDS = {"action", "plugin_id", "allowed_agents", "expected_version", "idempotency_key", "reason"}
_QUALIFICATION_FIELDS = {"plugin_id", "version", "expected_version", "idempotency_key", "reason"}
_PROHIBITED = {"filesystem_write", "shell", "terminal", "code_execution", "git", "database", "subprocess", "runtime_mutation"}
_DEPLOYMENT_TRANSITIONS = {
    "awaiting_generation": {"generated", "failed"},
    "generated": {"deploying", "failed"},
    "deploying": {"active", "failed", "rolled_back"},
    "failed": {"rolled_back"},
}
_QUALIFICATION_TRANSITIONS = {"queued": {"succeeded", "failed"}}
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")


def _registry_path() -> Path:
    configured = os.environ.get("BYQ_PLUGIN_REGISTRY_PATH")
    if configured:
        return Path(configured)
    bundled = Path("/app/plugin-registry/plugins.json")
    if bundled.is_file():
        return bundled
    source = Path(__file__).resolve()
    for parent in source.parents:
        candidate = parent / "plugins/dsh-byq/registry/plugins.json"
        if candidate.is_file():
            return candidate
    return bundled


def _load_registry() -> dict[str, Any]:
    try:
        value = json.loads(_registry_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PluginCenterPersistenceError("plugin registry projection is unavailable") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "dsh-plugin-registry.v1":
        raise PluginCenterPersistenceError("plugin registry projection is invalid")
    return value


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _public_evidence(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    # Evidence IDs are deliberately not filesystem paths.
    return [Path(item).name for item in value if isinstance(item, str) and item]


class PluginCenterStore(PgStoreMixin):
    """Persist desired policy and append-only deployment/qualification requests."""

    SCHEMA_DDL = [
        """
        CREATE TABLE IF NOT EXISTS plugin_product_policy (
            policy_id TEXT PRIMARY KEY,
            enabled_plugin_ids_json JSONB NOT NULL,
            agent_assignments_json JSONB NOT NULL,
            version INTEGER NOT NULL,
            updated_by TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS plugin_change_requests (
            request_id TEXT PRIMARY KEY,
            request_kind TEXT NOT NULL,
            plugin_id TEXT NOT NULL,
            requested_version TEXT,
            status TEXT NOT NULL,
            deployment_state TEXT NOT NULL,
            actor_principal TEXT NOT NULL,
            reason TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_sha256 TEXT NOT NULL,
            old_policy_version INTEGER NOT NULL,
            new_policy_version INTEGER NOT NULL,
            desired_policy_hash TEXT NOT NULL,
            target_composition_hash TEXT,
            bounded_result TEXT,
            request_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS plugin_change_requests_created_idx
            ON plugin_change_requests(created_at DESC, request_id DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS plugin_governance_audit (
            audit_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            actor_principal TEXT NOT NULL,
            action TEXT NOT NULL,
            plugin_id TEXT NOT NULL,
            outcome TEXT NOT NULL,
            old_policy_version INTEGER NOT NULL,
            new_policy_version INTEGER NOT NULL,
            detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        self.registry = _load_registry()
        self.plugins = {item["id"]: item for item in self.registry.get("plugins", []) if isinstance(item, dict)}
        try:
            super().__init__(database_url)
            self._bootstrap_policy()
        except SQLAlchemyError as exc:
            raise PluginCenterPersistenceError("plugin governance storage is unavailable") from exc

    def _bootstrap_policy(self) -> None:
        enabled = sorted(
            plugin_id for plugin_id, plugin in self.plugins.items()
            if (plugin.get("product_policy") or {}).get("enabled") is True
        )
        assignments = {
            plugin_id: sorted((plugin.get("agents") or {}).get("allowed", []))
            for plugin_id, plugin in self.plugins.items()
            if plugin_id in enabled
        }
        with self._transaction() as connection:
            execute(connection, """INSERT INTO plugin_product_policy
                (policy_id, enabled_plugin_ids_json, agent_assignments_json, version, updated_by, updated_at)
                VALUES ('product', :enabled, :assignments, 1, 'registry-bootstrap', now())
                ON CONFLICT (policy_id) DO NOTHING""", {"enabled": enabled, "assignments": assignments})

    @staticmethod
    def _require_admin(role: object) -> None:
        if role != "admin":
            raise PluginCenterForbidden("admin role required")

    @staticmethod
    def _text(value: object, field: str, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
            raise ValueError(f"{field} must be a non-empty string up to {maximum} characters")
        return value.strip()

    @staticmethod
    def _version(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("expected_version must be a positive integer")
        return value

    def _policy(self, connection: Any) -> dict[str, Any]:
        row = fetch_one(connection, "SELECT * FROM plugin_product_policy WHERE policy_id = 'product'")
        if row is None:
            raise PluginCenterPersistenceError("plugin Product policy is missing")
        return row

    def _plugin(self, plugin_id: object) -> tuple[str, dict[str, Any]]:
        normalized = self._text(plugin_id, "plugin_id", 64)
        plugin = self.plugins.get(normalized)
        if plugin is None:
            raise PluginCenterNotFound("registered plugin was not found")
        return normalized, plugin

    def projection(self, *, actor_role: object) -> dict[str, object]:
        self._require_admin(actor_role)
        try:
            with self._transaction() as connection:
                policy = self._policy(connection)
                requests = execute(connection, """SELECT request_id, request_kind, plugin_id, requested_version,
                    status, deployment_state, actor_principal, reason, old_policy_version, new_policy_version,
                    desired_policy_hash, target_composition_hash, bounded_result, created_at, updated_at
                    FROM plugin_change_requests ORDER BY created_at DESC, request_id DESC LIMIT 50""")
                audit = execute(connection, """SELECT audit_id, request_id, actor_principal, action, plugin_id,
                    outcome, old_policy_version, new_policy_version, detail_json, created_at
                    FROM plugin_governance_audit ORDER BY created_at DESC, audit_id DESC LIMIT 50""")
        except SQLAlchemyError as exc:
            raise PluginCenterPersistenceError("plugin governance projection is unavailable") from exc
        enabled = set(policy["enabled_plugin_ids_json"])
        assignments = policy["agent_assignments_json"]
        catalog = [self._public_plugin(plugin, enabled, assignments) for plugin in self.plugins.values()]
        catalog.sort(key=lambda item: item["id"])
        counts = {state: 0 for state in ("AVAILABLE", "QUALIFIED", "ENABLED", "BLOCKED", "REJECTED", "DEPRECATED")}
        for item in catalog:
            state = item["qualification_state"]
            counts[state] = counts.get(state, 0) + 1
            if item["desired_enabled"]:
                counts["ENABLED"] += 1
        return {
            "schema_version": "plugin-center.v1",
            "runtime_baseline": self.registry["runtime_baseline"],
            "policy": {
                "version": policy["version"], "enabled_plugin_ids": sorted(enabled),
                "agent_assignments": assignments, "updated_by": policy["updated_by"],
                "updated_at": policy["updated_at"],
            },
            "counts": counts,
            "plugins": catalog,
            "requests": requests,
            "audit": audit,
            "boundaries": {"online_install": False, "runtime_mutation": False, "secrets_exposed": False},
        }

    def detail(self, plugin_id: object, *, actor_role: object) -> dict[str, object]:
        projection = self.projection(actor_role=actor_role)
        normalized, _plugin = self._plugin(plugin_id)
        item = next(value for value in projection["plugins"] if value["id"] == normalized)
        recent = [request for request in projection["requests"] if request["plugin_id"] == normalized][:10]
        return {"schema_version": "plugin-center-detail.v1", "plugin": item, "recent_requests": recent}

    def _public_plugin(self, plugin: dict[str, Any], enabled: set[str], assignments: dict[str, Any]) -> dict[str, Any]:
        packages = plugin.get("packages") or []
        qualification = plugin.get("qualification") or {}
        credentials = plugin.get("credentials") or {}
        capabilities = plugin.get("capabilities") or {}
        return {
            "id": plugin["id"], "display_name": plugin.get("display_name", ""),
            "description": plugin.get("description", ""), "publisher": (plugin.get("source") or {}).get("publisher", ""),
            "packages": [{"name": item.get("name"), "version": item.get("version")} for item in packages],
            "qualified_version": packages[0].get("version") if packages else None,
            "upstream_latest_observed": self.registry["runtime_baseline"].get("upstream_latest_observed"),
            "qualification_state": qualification.get("state"), "qualification_reason": qualification.get("reason", ""),
            "qualification_checks": qualification.get("checks", {}), "evidence_refs": _public_evidence(qualification.get("evidence")),
            "compatibility": plugin.get("compatibility", {}), "risk": plugin.get("risk", {}),
            "capabilities": sorted(key for key, value in capabilities.items() if value is True),
            "tools": sorted((plugin.get("tools") or {}).get("exposed", [])),
            "allowed_agents": sorted((plugin.get("agents") or {}).get("allowed", [])),
            "denied_agents": sorted((plugin.get("agents") or {}).get("denied", [])),
            "desired_agents": sorted(assignments.get(plugin["id"], [])),
            "desired_enabled": plugin["id"] in enabled,
            "credential_required": credentials.get("required") is True,
            "credential_configured": False,
        }

    def request_change(self, payload: object, *, actor_principal: object, actor_role: object) -> dict[str, object]:
        self._require_admin(actor_role)
        if not isinstance(payload, dict):
            raise ValueError("plugin change request must be an object")
        unknown = set(payload) - _MUTATION_FIELDS
        if unknown:
            raise ValueError(f"plugin change request has unknown fields: {', '.join(sorted(unknown))}")
        action = self._text(payload.get("action"), "action", 16)
        if action not in _ACTIONS:
            raise ValueError("action must be enable, disable, or assign")
        plugin_id, plugin = self._plugin(payload.get("plugin_id"))
        actor = self._text(actor_principal, "actor_principal", 128)
        reason = self._text(payload.get("reason"), "reason", 500)
        expected = self._version(payload.get("expected_version"))
        key = self._text(payload.get("idempotency_key"), "idempotency_key", 128)
        if not _IDEMPOTENCY.fullmatch(key):
            raise ValueError("idempotency_key has an invalid format")
        requested_agents = payload.get("allowed_agents", [])
        if action == "assign":
            if not isinstance(requested_agents, list) or not all(isinstance(item, str) for item in requested_agents):
                raise ValueError("allowed_agents must be a string array")
            if len(requested_agents) != len(set(requested_agents)):
                raise ValueError("allowed_agents must not contain duplicates")
            ceiling = set((plugin.get("agents") or {}).get("allowed", []))
            if not set(requested_agents) <= ceiling:
                raise ValueError("Agent assignment exceeds the registered allowlist")
        elif "allowed_agents" in payload:
            raise ValueError("allowed_agents is only valid for assign")
        if action in {"enable", "assign"}:
            qualification = (plugin.get("qualification") or {}).get("state")
            risk = (plugin.get("risk") or {}).get("level")
            capabilities = plugin.get("capabilities") or {}
            if qualification != "QUALIFIED" or risk in {"HIGH", "PROHIBITED"}:
                raise ValueError("plugin is not policy-safe and QUALIFIED")
            if any(capabilities.get(name) is True for name in _PROHIBITED):
                raise ValueError("plugin has a prohibited Product capability")
        canonical = {"action": action, "plugin_id": plugin_id, "allowed_agents": requested_agents if action == "assign" else None,
                     "expected_version": expected, "reason": reason}
        request_hash = hashlib.sha256(_canonical(canonical).encode()).hexdigest()
        try:
            with self._transaction() as connection:
                prior = fetch_one(connection, "SELECT * FROM plugin_change_requests WHERE idempotency_key = :key", {"key": key})
                if prior is not None:
                    if prior["request_sha256"] != request_hash:
                        raise PluginCenterConflict("idempotency key was reused with a different request")
                    return {"request": self._public_request(prior)}
                policy = fetch_one(connection, "SELECT * FROM plugin_product_policy WHERE policy_id = 'product' FOR UPDATE")
                if policy is None:
                    raise PluginCenterPersistenceError("plugin Product policy is missing")
                if policy["version"] != expected:
                    raise PluginCenterConflict("plugin policy version conflict")
                enabled = set(policy["enabled_plugin_ids_json"])
                assignments = dict(policy["agent_assignments_json"])
                if action == "enable":
                    enabled.add(plugin_id)
                    assignments.setdefault(plugin_id, sorted((plugin.get("agents") or {}).get("allowed", [])))
                elif action == "disable":
                    enabled.discard(plugin_id)
                    assignments.pop(plugin_id, None)
                else:
                    if plugin_id not in enabled:
                        raise ValueError("disabled plugin cannot receive an Agent assignment")
                    assignments[plugin_id] = sorted(requested_agents)
                new_version = expected + 1
                desired = {"enabled_plugin_ids": sorted(enabled), "agent_assignments": assignments, "policy_version": new_version}
                deployment_policy = {"schema_version": "plugin-deployment-policy.v1", **desired}
                desired_hash = "sha256:" + hashlib.sha256(_canonical(desired).encode()).hexdigest()
                execute(connection, """UPDATE plugin_product_policy SET enabled_plugin_ids_json=:enabled,
                    agent_assignments_json=:assignments, version=:version, updated_by=:actor, updated_at=now()
                    WHERE policy_id='product'""", {"enabled": sorted(enabled), "assignments": assignments,
                    "version": new_version, "actor": actor})
                request_id = f"plugin_request_{uuid.uuid4().hex}"
                execute(connection, """INSERT INTO plugin_change_requests
                    (request_id, request_kind, plugin_id, status, deployment_state, actor_principal, reason,
                     idempotency_key, request_sha256, old_policy_version, new_policy_version, desired_policy_hash,
                     request_json, created_at, updated_at)
                    VALUES (:id, :kind, :plugin, 'validated', 'awaiting_generation', :actor, :reason, :key,
                     :sha, :old, :new, :desired_hash, :request, now(), now())""",
                    {"id": request_id, "kind": action, "plugin": plugin_id, "actor": actor, "reason": reason,
                     "key": key, "sha": request_hash, "old": expected, "new": new_version,
                     "desired_hash": desired_hash,
                     "request": {**canonical, "desired_policy": deployment_policy}})
                execute(connection, """INSERT INTO plugin_governance_audit
                    (audit_id, request_id, actor_principal, action, plugin_id, outcome, old_policy_version,
                     new_policy_version, detail_json, created_at)
                    VALUES (:audit, :request, :actor, :action, :plugin, 'validated', :old, :new, :detail, now())""",
                    {"audit": f"plugin_audit_{uuid.uuid4().hex}", "request": request_id, "actor": actor,
                     "action": action, "plugin": plugin_id, "old": expected, "new": new_version,
                     "detail": {"desired_policy_hash": desired_hash, "deployment_state": "awaiting_generation"}})
                row = fetch_one(connection, "SELECT * FROM plugin_change_requests WHERE request_id=:id", {"id": request_id}) or {}
                return {"request": self._public_request(row)}
        except PluginCenterError:
            raise
        except SQLAlchemyError as exc:
            raise PluginCenterPersistenceError("plugin change request failed") from exc

    def request_qualification(self, payload: object, *, actor_principal: object, actor_role: object) -> dict[str, object]:
        self._require_admin(actor_role)
        if not isinstance(payload, dict):
            raise ValueError("qualification request must be an object")
        unknown = set(payload) - _QUALIFICATION_FIELDS
        if unknown:
            raise ValueError(f"qualification request has unknown fields: {', '.join(sorted(unknown))}")
        plugin_id, plugin = self._plugin(payload.get("plugin_id"))
        versions = {item.get("version") for item in plugin.get("packages", [])}
        version = self._text(payload.get("version"), "version", 64)
        if version not in versions:
            raise ValueError("qualification version must be the exact registered version")
        translated = {"action": "qualify", "plugin_id": plugin_id, "expected_version": payload.get("expected_version"),
                      "idempotency_key": payload.get("idempotency_key"), "reason": payload.get("reason")}
        # Qualification is deliberately queued without changing Product policy.
        actor = self._text(actor_principal, "actor_principal", 128)
        expected = self._version(payload.get("expected_version"))
        key = self._text(payload.get("idempotency_key"), "idempotency_key", 128)
        reason = self._text(payload.get("reason"), "reason", 500)
        if not _IDEMPOTENCY.fullmatch(key):
            raise ValueError("idempotency_key has an invalid format")
        canonical = {**translated, "version": version}
        request_hash = hashlib.sha256(_canonical(canonical).encode()).hexdigest()
        try:
            with self._transaction() as connection:
                prior = fetch_one(connection, "SELECT * FROM plugin_change_requests WHERE idempotency_key=:key", {"key": key})
                if prior:
                    if prior["request_sha256"] != request_hash:
                        raise PluginCenterConflict("idempotency key was reused with a different request")
                    return {"request": self._public_request(prior)}
                policy = self._policy(connection)
                if policy["version"] != expected:
                    raise PluginCenterConflict("plugin policy version conflict")
                request_id = f"plugin_request_{uuid.uuid4().hex}"
                desired = {"enabled_plugin_ids": policy["enabled_plugin_ids_json"], "agent_assignments": policy["agent_assignments_json"], "policy_version": expected}
                desired_hash = "sha256:" + hashlib.sha256(_canonical(desired).encode()).hexdigest()
                execute(connection, """INSERT INTO plugin_change_requests
                    (request_id, request_kind, plugin_id, requested_version, status, deployment_state,
                     actor_principal, reason, idempotency_key, request_sha256, old_policy_version,
                     new_policy_version, desired_policy_hash, request_json, created_at, updated_at)
                    VALUES (:id, 'qualify', :plugin, :version, 'queued', 'not_applicable', :actor, :reason,
                     :key, :sha, :policy, :policy, :desired, :request, now(), now())""",
                    {"id": request_id, "plugin": plugin_id, "version": version, "actor": actor, "reason": reason,
                     "key": key, "sha": request_hash, "policy": expected, "desired": desired_hash, "request": canonical})
                execute(connection, """INSERT INTO plugin_governance_audit
                    (audit_id, request_id, actor_principal, action, plugin_id, outcome, old_policy_version,
                     new_policy_version, detail_json, created_at)
                    VALUES (:audit, :request, :actor, 'qualify', :plugin, 'queued', :policy, :policy, :detail, now())""",
                    {"audit": f"plugin_audit_{uuid.uuid4().hex}", "request": request_id, "actor": actor,
                     "plugin": plugin_id, "policy": expected, "detail": {"requested_version": version}})
                row = fetch_one(connection, "SELECT * FROM plugin_change_requests WHERE request_id=:id", {"id": request_id}) or {}
                return {"request": self._public_request(row)}
        except PluginCenterError:
            raise
        except SQLAlchemyError as exc:
            raise PluginCenterPersistenceError("qualification request failed") from exc

    def deployment_input(self, request_id: object, *, service_token: object) -> dict[str, object]:
        self._require_deployment_token(service_token)
        normalized = self._text(request_id, "request_id", 96)
        try:
            with self._transaction() as connection:
                row = fetch_one(connection, "SELECT * FROM plugin_change_requests WHERE request_id=:id", {"id": normalized})
                if row is None:
                    raise PluginCenterNotFound("plugin governance request was not found")
                policy = self._policy(connection)
                request_json = row.get("request_json") if isinstance(row, dict) else None
                policy_snapshot = request_json.get("desired_policy") if isinstance(request_json, dict) else None
                if not isinstance(policy_snapshot, dict):
                    # Backward-compatible fallback for requests created before
                    # immutable desired-policy snapshots were introduced.
                    policy_snapshot = {
                        "schema_version": "plugin-deployment-policy.v1",
                        "policy_version": policy["version"],
                        "enabled_plugin_ids": policy["enabled_plugin_ids_json"],
                        "agent_assignments": policy["agent_assignments_json"],
                    }
                return {
                    "schema_version": "plugin-deployment-input.v1",
                    "request": self._public_request(row),
                    "policy": policy_snapshot,
                    "runtime_baseline": self.registry["runtime_baseline"],
                }
        except PluginCenterError:
            raise
        except SQLAlchemyError as exc:
            raise PluginCenterPersistenceError("plugin deployment input is unavailable") from exc

    def record_result(self, request_id: object, payload: object, *, service_token: object) -> dict[str, object]:
        self._require_deployment_token(service_token)
        normalized = self._text(request_id, "request_id", 96)
        if not isinstance(payload, dict):
            raise ValueError("plugin deployment result must be an object")
        unknown = set(payload) - {"state", "composition_hash", "result"}
        if unknown:
            raise ValueError(f"plugin deployment result has unknown fields: {', '.join(sorted(unknown))}")
        state = self._text(payload.get("state"), "state", 32)
        result = self._text(payload.get("result"), "result", 500)
        digest = payload.get("composition_hash")
        if digest is not None and (not isinstance(digest, str) or not _HASH.fullmatch(digest)):
            raise ValueError("composition_hash must be an exact sha256 identity")
        try:
            with self._transaction() as connection:
                row = fetch_one(connection, "SELECT * FROM plugin_change_requests WHERE request_id=:id FOR UPDATE", {"id": normalized})
                if row is None:
                    raise PluginCenterNotFound("plugin governance request was not found")
                qualification = row["request_kind"] == "qualify"
                current = row["status"] if qualification else row["deployment_state"]
                allowed = _QUALIFICATION_TRANSITIONS.get(current, set()) if qualification else _DEPLOYMENT_TRANSITIONS.get(current, set())
                if state not in allowed:
                    raise PluginCenterConflict(f"invalid plugin governance transition: {current} -> {state}")
                if not qualification and state in {"generated", "deploying", "active"} and digest is None:
                    raise ValueError("generated/deploying/active result requires composition_hash")
                new_status = state if qualification else ("completed" if state == "active" else "failed" if state in {"failed", "rolled_back"} else "validated")
                new_deployment = row["deployment_state"] if qualification else state
                execute(connection, """UPDATE plugin_change_requests SET status=:status, deployment_state=:deployment,
                    target_composition_hash=COALESCE(:digest, target_composition_hash), bounded_result=:result,
                    updated_at=now() WHERE request_id=:id""", {"status": new_status, "deployment": new_deployment,
                    "digest": digest, "result": result, "id": normalized})
                execute(connection, """INSERT INTO plugin_governance_audit
                    (audit_id, request_id, actor_principal, action, plugin_id, outcome, old_policy_version,
                     new_policy_version, detail_json, created_at)
                    VALUES (:audit, :request, 'plugin-deployment-lane', :action, :plugin, :outcome, :old, :new, :detail, now())""",
                    {"audit": f"plugin_audit_{uuid.uuid4().hex}", "request": normalized,
                     "action": f"{row['request_kind']}.result", "plugin": row["plugin_id"], "outcome": state,
                     "old": row["old_policy_version"], "new": row["new_policy_version"],
                     "detail": {"composition_hash": digest, "bounded_result": result}})
                updated = fetch_one(connection, "SELECT * FROM plugin_change_requests WHERE request_id=:id", {"id": normalized}) or {}
                return {"request": self._public_request(updated)}
        except PluginCenterError:
            raise
        except SQLAlchemyError as exc:
            raise PluginCenterPersistenceError("plugin deployment result failed") from exc

    @staticmethod
    def _require_deployment_token(value: object) -> None:
        expected = os.environ.get("BYQ_PLUGIN_DEPLOYMENT_TOKEN")
        if not expected or not isinstance(value, str) or value != expected:
            raise PluginCenterForbidden("trusted plugin deployment identity required")

    @staticmethod
    def _public_request(row: dict[str, Any]) -> dict[str, Any]:
        fields = ("request_id", "request_kind", "plugin_id", "requested_version", "status", "deployment_state",
                  "actor_principal", "reason", "old_policy_version", "new_policy_version", "desired_policy_hash",
                  "target_composition_hash", "bounded_result", "created_at", "updated_at")
        return {field: row.get(field) for field in fields}
