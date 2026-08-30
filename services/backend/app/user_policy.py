"""BYQ-owned personal agent approval policy preferences (ADR-0016 PG)."""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, execute, fetch_one


_PRINCIPAL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")
_RULE_ID_PATTERN = re.compile(r"^policy_rule_[0-9a-f]{32}$")
_RULE_ACTIONS = {
    "byq_backtest_submit", "byq_backtest_run",
    "byq_backtest_task_create", "byq_backtest_task_execute",
}
_LEGACY_ACTION_ALIAS = {
    "byq_backtest_task_create": "byq_backtest_submit",
    "byq_backtest_task_execute": "byq_backtest_run",
}
_RULE_AGENTS = {"*", "chief_quant_researcher", "strategy_researcher"}
_RISK_LEVELS = {"low", "medium", "high", "critical"}
_PRESETS: tuple[dict[str, object], ...] = (
    {
        "preset_id": "manual_safe",
        "name": "全部人工确认",
        "description": "所有支持的执行动作保持人工审批，适合首次使用。",
        "settings": {
            "automation_enabled": False,
            "paused": False,
            "default_decision_mode": "manual",
            "max_auto_executions_per_hour": 20,
            "max_auto_failures_per_hour": 3,
        },
        "rules": [],
    },
    {
        "preset_id": "deny_backtests",
        "name": "禁止 Agent 发起回测",
        "description": "自动拒绝 Agent 的回测提交与执行授权。",
        "settings": {
            "automation_enabled": True,
            "paused": False,
            "default_decision_mode": "manual",
            "max_auto_executions_per_hour": 20,
            "max_auto_failures_per_hour": 3,
        },
        "rules": [
            {
                "name": "拒绝回测提交",
                "description": "不允许 Agent 提交回测。",
                "action": "byq_backtest_submit",
                "agent_id": "*",
                "decision_mode": "auto_deny",
                "risk_level": "high",
                "priority": 10,
                "enabled": True,
            },
            {
                "name": "拒绝回测执行",
                "description": "不允许 Agent 执行回测。",
                "action": "byq_backtest_run",
                "agent_id": "*",
                "decision_mode": "auto_deny",
                "risk_level": "high",
                "priority": 20,
                "enabled": True,
            },
        ],
    },
)


class UserPolicyError(RuntimeError):
    pass


class UserPolicyPersistenceError(UserPolicyError):
    pass


class UserPolicyNotFound(UserPolicyError):
    pass


class UserPolicyConflict(UserPolicyError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _principal(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if _PRINCIPAL_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field} is not a valid BYQ principal")
    return normalized


def _bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be boolean")
    return value


def _mode(value: object, *, field: str) -> str:
    if value not in {"manual", "auto_deny", "auto_approve"}:
        raise ValueError(f"{field} must be manual, auto_deny, or auto_approve")
    return str(value)


def _int(value: object, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return value


def _text(value: object, *, field: str, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return normalized


def _rule_id(value: object) -> str:
    normalized = _text(value, field="rule_id", maximum=64)
    if _RULE_ID_PATTERN.fullmatch(normalized) is None:
        raise ValueError("rule_id is not valid")
    return normalized


class UserPolicyStore(PgStoreMixin):
    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS user_agent_policy (
            owner_principal TEXT PRIMARY KEY,
            automation_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            paused BOOLEAN NOT NULL DEFAULT FALSE,
            default_decision_mode TEXT NOT NULL DEFAULT 'manual',
            max_auto_executions_per_hour INTEGER NOT NULL DEFAULT 20,
            max_auto_failures_per_hour INTEGER NOT NULL DEFAULT 3,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS user_agent_policy_rules (
            rule_id TEXT PRIMARY KEY,
            owner_principal TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            action TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            decision_mode TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            priority INTEGER NOT NULL,
            enabled BOOLEAN NOT NULL,
            version INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS user_agent_policy_rules_owner
            ON user_agent_policy_rules(owner_principal, priority, created_at, rule_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS user_agent_policy_audit (
            audit_id TEXT PRIMARY KEY,
            owner_principal TEXT NOT NULL,
            actor_principal TEXT NOT NULL,
            action TEXT NOT NULL,
            resource_id TEXT,
            detail_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as exc:
            raise UserPolicyPersistenceError("user policy storage is unavailable") from exc

    @classmethod
    def from_env(cls) -> "UserPolicyStore":
        return cls()

    def get(self, owner: object) -> dict[str, object]:
        owner = _principal(owner, field="owner_principal")
        defaults = {
            "owner_principal": owner,
            "automation_enabled": False,
            "paused": False,
            "default_decision_mode": "manual",
            "max_auto_executions_per_hour": 20,
            "max_auto_failures_per_hour": 3,
        }
        row = self._fetch_one(
            "SELECT * FROM user_agent_policy WHERE owner_principal = :owner_principal",
            {"owner_principal": owner},
        )
        if row is None:
            return defaults
        result = dict(row)
        result["automation_enabled"] = bool(result["automation_enabled"])
        result["paused"] = bool(result["paused"])
        return result

    def update(self, owner: object, payload: object) -> dict[str, object]:
        owner = _principal(owner, field="owner_principal")
        if not isinstance(payload, dict):
            raise ValueError("agent policy request must be an object")
        allowed = {
            "automation_enabled", "paused", "default_decision_mode",
            "max_auto_executions_per_hour", "max_auto_failures_per_hour",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"agent policy request has unknown fields: {', '.join(unknown)}")
        automation_enabled = _bool(payload.get("automation_enabled", False), field="automation_enabled")
        paused = _bool(payload.get("paused", False), field="paused")
        mode = _mode(payload.get("default_decision_mode", "manual"), field="default_decision_mode")
        max_executions = _int(
            payload.get("max_auto_executions_per_hour", 20),
            field="max_auto_executions_per_hour",
            minimum=1,
            maximum=1000,
        )
        max_failures = _int(
            payload.get("max_auto_failures_per_hour", 3),
            field="max_auto_failures_per_hour",
            minimum=1,
            maximum=100,
        )
        now = _now()
        self._execute(
            """INSERT INTO user_agent_policy
            (owner_principal, automation_enabled, paused, default_decision_mode,
             max_auto_executions_per_hour, max_auto_failures_per_hour, updated_at)
            VALUES (:owner_principal, :automation_enabled, :paused, :mode,
                    :max_executions, :max_failures, :updated_at)
            ON CONFLICT(owner_principal) DO UPDATE SET
                automation_enabled = excluded.automation_enabled,
                paused = excluded.paused,
                default_decision_mode = excluded.default_decision_mode,
                max_auto_executions_per_hour = excluded.max_auto_executions_per_hour,
                max_auto_failures_per_hour = excluded.max_auto_failures_per_hour,
                updated_at = excluded.updated_at""",
            {
                "owner_principal": owner,
                "automation_enabled": automation_enabled,
                "paused": paused,
                "mode": mode,
                "max_executions": max_executions,
                "max_failures": max_failures,
                "updated_at": now,
            },
        )
        return self.get(owner)

    @staticmethod
    def list_presets() -> list[dict[str, object]]:
        return [dict(preset) for preset in _PRESETS]

    def list_rules(self, owner: object) -> list[dict[str, object]]:
        owner = _principal(owner, field="owner_principal")
        rows = self._execute(
            """SELECT * FROM user_agent_policy_rules
               WHERE owner_principal = :owner
               ORDER BY priority ASC, created_at ASC, rule_id ASC""",
            {"owner": owner},
        )
        return [self._rule_row(row) for row in rows]

    def create_rule(
        self,
        owner: object,
        payload: object,
        *,
        actor: object,
    ) -> dict[str, object]:
        owner = _principal(owner, field="owner_principal")
        actor = _principal(actor, field="actor_principal")
        rule = self._rule_payload(payload)
        rule_id = f"policy_rule_{uuid.uuid4().hex}"
        now = _now()
        with self._transaction() as connection:
            execute(
                connection,
                """INSERT INTO user_agent_policy_rules
                (rule_id, owner_principal, name, description, action, agent_id,
                 decision_mode, risk_level, priority, enabled, version,
                 created_at, updated_at)
                VALUES (:rule_id, :owner, :name, :description, :action, :agent_id,
                        :decision_mode, :risk_level, :priority, :enabled, 1,
                        :created_at, :updated_at)""",
                {
                    "rule_id": rule_id,
                    "owner": owner,
                    **rule,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            self._audit(connection, owner, actor, "rule.created", rule_id, {"version": 1})
        return self.get_rule(rule_id, owner=owner)

    def get_rule(self, rule_id: object, *, owner: object) -> dict[str, object]:
        rule_id = _rule_id(rule_id)
        owner = _principal(owner, field="owner_principal")
        row = self._fetch_one(
            """SELECT * FROM user_agent_policy_rules
               WHERE rule_id = :rule_id AND owner_principal = :owner""",
            {"rule_id": rule_id, "owner": owner},
        )
        if row is None:
            raise UserPolicyNotFound("policy rule not found")
        return self._rule_row(row)

    def update_rule(
        self,
        rule_id: object,
        owner: object,
        payload: object,
        *,
        actor: object,
    ) -> dict[str, object]:
        rule_id = _rule_id(rule_id)
        owner = _principal(owner, field="owner_principal")
        actor = _principal(actor, field="actor_principal")
        if not isinstance(payload, dict):
            raise ValueError("policy rule request must be an object")
        expected = _int(payload.get("expected_version"), field="expected_version", minimum=1, maximum=1_000_000)
        rule = self._rule_payload({key: value for key, value in payload.items() if key != "expected_version"})
        with self._transaction() as connection:
            current = fetch_one(
                connection,
                """SELECT * FROM user_agent_policy_rules
                   WHERE rule_id = :rule_id AND owner_principal = :owner FOR UPDATE""",
                {"rule_id": rule_id, "owner": owner},
            )
            if current is None:
                raise UserPolicyNotFound("policy rule not found")
            if current["version"] != expected:
                raise UserPolicyConflict("policy rule version conflict")
            version = expected + 1
            execute(
                connection,
                """UPDATE user_agent_policy_rules SET
                   name = :name, description = :description, action = :action,
                   agent_id = :agent_id, decision_mode = :decision_mode,
                   risk_level = :risk_level, priority = :priority,
                   enabled = :enabled, version = :version, updated_at = :updated_at
                   WHERE rule_id = :rule_id""",
                {
                    "rule_id": rule_id,
                    **rule,
                    "version": version,
                    "updated_at": _now(),
                },
            )
            self._audit(connection, owner, actor, "rule.updated", rule_id, {"version": version})
        return self.get_rule(rule_id, owner=owner)

    def delete_rule(
        self,
        rule_id: object,
        owner: object,
        *,
        actor: object,
        expected_version: object,
    ) -> dict[str, object]:
        rule_id = _rule_id(rule_id)
        owner = _principal(owner, field="owner_principal")
        actor = _principal(actor, field="actor_principal")
        expected = _int(expected_version, field="expected_version", minimum=1, maximum=1_000_000)
        with self._transaction() as connection:
            current = fetch_one(
                connection,
                """SELECT * FROM user_agent_policy_rules
                   WHERE rule_id = :rule_id AND owner_principal = :owner FOR UPDATE""",
                {"rule_id": rule_id, "owner": owner},
            )
            if current is None:
                raise UserPolicyNotFound("policy rule not found")
            if current["version"] != expected:
                raise UserPolicyConflict("policy rule version conflict")
            execute(
                connection,
                "DELETE FROM user_agent_policy_rules WHERE rule_id = :rule_id",
                {"rule_id": rule_id},
            )
            self._audit(connection, owner, actor, "rule.deleted", rule_id, {"version": expected})
        return {"rule_id": rule_id, "deleted": True}

    def apply_preset(
        self,
        owner: object,
        preset_id: object,
        *,
        actor: object,
    ) -> dict[str, object]:
        owner = _principal(owner, field="owner_principal")
        actor = _principal(actor, field="actor_principal")
        preset_key = _text(preset_id, field="preset_id", maximum=64)
        preset = next((item for item in _PRESETS if item["preset_id"] == preset_key), None)
        if preset is None:
            raise UserPolicyNotFound("policy preset not found")
        settings = dict(preset["settings"])
        with self._transaction() as connection:
            now = _now()
            execute(
                connection,
                """INSERT INTO user_agent_policy
                (owner_principal, automation_enabled, paused, default_decision_mode,
                 max_auto_executions_per_hour, max_auto_failures_per_hour, updated_at)
                VALUES (:owner, :automation_enabled, :paused, :default_decision_mode,
                        :max_auto_executions_per_hour, :max_auto_failures_per_hour, :updated_at)
                ON CONFLICT(owner_principal) DO UPDATE SET
                    automation_enabled = excluded.automation_enabled,
                    paused = excluded.paused,
                    default_decision_mode = excluded.default_decision_mode,
                    max_auto_executions_per_hour = excluded.max_auto_executions_per_hour,
                    max_auto_failures_per_hour = excluded.max_auto_failures_per_hour,
                    updated_at = excluded.updated_at""",
                {"owner": owner, **settings, "updated_at": now},
            )
            execute(
                connection,
                "DELETE FROM user_agent_policy_rules WHERE owner_principal = :owner",
                {"owner": owner},
            )
            for payload in preset["rules"]:
                rule = self._rule_payload(payload)
                execute(
                    connection,
                    """INSERT INTO user_agent_policy_rules
                    (rule_id, owner_principal, name, description, action, agent_id,
                     decision_mode, risk_level, priority, enabled, version,
                     created_at, updated_at)
                    VALUES (:rule_id, :owner, :name, :description, :action, :agent_id,
                            :decision_mode, :risk_level, :priority, :enabled, 1,
                            :created_at, :updated_at)""",
                    {
                        "rule_id": f"policy_rule_{uuid.uuid4().hex}",
                        "owner": owner,
                        **rule,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            self._audit(connection, owner, actor, "preset.applied", preset_key, {"rule_count": len(preset["rules"])})
        return {
            "preset_id": preset_key,
            "policy": public_policy(self.get(owner)),
            "rules": self.list_rules(owner),
        }

    def evaluate_authorization(
        self,
        owner: object,
        authorization: dict[str, object],
    ) -> dict[str, object]:
        owner = _principal(owner, field="owner_principal")
        result = dict(authorization)
        if result.get("authorized") is False and result.get("decision") != "approval_required":
            return result
        settings = self.get(owner)
        if settings["paused"] or not settings["automation_enabled"]:
            return result
        action = str(result.get("action", ""))
        compatible_actions = {action, _LEGACY_ACTION_ALIAS.get(action, action)}
        role_id = str(result.get("role_id", ""))
        matching = [
            rule for rule in self.list_rules(owner)
            if rule["enabled"]
            and rule["action"] in compatible_actions
            and rule["agent_id"] in {"*", role_id}
        ]
        decision = (
            matching[0]["decision_mode"]
            if matching
            else settings["default_decision_mode"]
        )
        if decision == "auto_deny":
            return {
                **result,
                "authorized": False,
                "decision": "policy_denied",
                "policy_rule_id": matching[0]["rule_id"] if matching else None,
            }
        # The platform policy remains manual in Phase 37. A personal
        # auto-approve rule cannot bypass the existing Approval boundary.
        if result.get("decision") == "approval_required":
            return {
                **result,
                "authorized": False,
                "decision": "approval_required",
                "policy_rule_id": matching[0]["rule_id"] if matching else None,
            }
        return result

    def list_audit(self, owner: object, *, limit: int = 100) -> list[dict[str, object]]:
        owner = _principal(owner, field="owner_principal")
        limit = _int(limit, field="limit", minimum=1, maximum=200)
        return self._execute(
            """SELECT audit_id, owner_principal, actor_principal, action,
                      resource_id, detail_json AS detail, created_at
               FROM user_agent_policy_audit
               WHERE owner_principal = :owner
               ORDER BY created_at DESC, audit_id DESC LIMIT :limit""",
            {"owner": owner, "limit": limit},
        )

    @staticmethod
    def _rule_payload(payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("policy rule request must be an object")
        allowed = {
            "name", "description", "action", "agent_id", "decision_mode",
            "risk_level", "priority", "enabled",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"policy rule request has unknown fields: {', '.join(unknown)}")
        action = _text(payload.get("action"), field="action", maximum=128)
        agent_id = _text(payload.get("agent_id", "*"), field="agent_id", maximum=64)
        decision_mode = _mode(payload.get("decision_mode", "manual"), field="decision_mode")
        risk_level = _text(payload.get("risk_level", "medium"), field="risk_level", maximum=16)
        if action not in _RULE_ACTIONS:
            raise ValueError("policy rule action is not supported")
        if agent_id not in _RULE_AGENTS:
            raise ValueError("policy rule agent is not supported")
        if risk_level not in _RISK_LEVELS:
            raise ValueError("policy rule risk_level is not supported")
        return {
            "name": _text(payload.get("name"), field="name", maximum=160),
            "description": _text(payload.get("description", ""), field="description", maximum=1000, allow_empty=True),
            "action": action,
            "agent_id": agent_id,
            "decision_mode": decision_mode,
            "risk_level": risk_level,
            "priority": _int(payload.get("priority", 100), field="priority", minimum=1, maximum=1000),
            "enabled": _bool(payload.get("enabled", True), field="enabled"),
        }

    @staticmethod
    def _rule_row(row: dict[str, object]) -> dict[str, object]:
        return {
            "rule_id": row["rule_id"],
            "owner_principal": row["owner_principal"],
            "name": row["name"],
            "description": row["description"],
            "action": row["action"],
            "agent_id": row["agent_id"],
            "decision_mode": row["decision_mode"],
            "risk_level": row["risk_level"],
            "priority": row["priority"],
            "enabled": bool(row["enabled"]),
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _audit(
        connection,
        owner: str,
        actor: str,
        action: str,
        resource_id: str | None,
        detail: dict[str, object],
    ) -> None:
        execute(
            connection,
            """INSERT INTO user_agent_policy_audit
            (audit_id, owner_principal, actor_principal, action,
             resource_id, detail_json, created_at)
            VALUES (:audit_id, :owner, :actor, :action, :resource_id,
                    :detail, :created_at)""",
            {
                "audit_id": f"policy_audit_{uuid.uuid4().hex}",
                "owner": owner,
                "actor": actor,
                "action": action,
                "resource_id": resource_id,
                "detail": detail,
                "created_at": _now(),
            },
        )


def public_policy(value: dict[str, object]) -> dict[str, object]:
    return {
        key: value[key]
        for key in (
            "owner_principal",
            "automation_enabled",
            "paused",
            "default_decision_mode",
            "max_auto_executions_per_hour",
            "max_auto_failures_per_hour",
        )
        if key in value
    }
