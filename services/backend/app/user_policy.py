"""BYQ-owned personal agent approval policy preferences (ADR-0016 PG)."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin


_PRINCIPAL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")


class UserPolicyError(RuntimeError):
    pass


class UserPolicyPersistenceError(UserPolicyError):
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
