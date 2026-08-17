"""BYQ-owned personal agent approval policy preferences."""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


class UserPolicyStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = sqlite3.connect(self.path, timeout=10.0, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA busy_timeout = 10000")
            self._create_schema()
        except sqlite3.Error as exc:
            raise UserPolicyPersistenceError("user policy storage is unavailable") from exc

    @classmethod
    def from_env(cls) -> "UserPolicyStore":
        return cls(os.getenv("BYQ_DOMAIN_DB_PATH", "/tmp/byq-domain.sqlite3"))

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_agent_policy (
                    owner_principal TEXT PRIMARY KEY,
                    automation_enabled INTEGER NOT NULL DEFAULT 0,
                    paused INTEGER NOT NULL DEFAULT 0,
                    default_decision_mode TEXT NOT NULL DEFAULT 'manual',
                    max_auto_executions_per_hour INTEGER NOT NULL DEFAULT 20,
                    max_auto_failures_per_hour INTEGER NOT NULL DEFAULT 3,
                    updated_at TEXT NOT NULL
                );
                """
            )

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
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM user_agent_policy WHERE owner_principal = ?",
                (owner,),
            ).fetchone()
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
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO user_agent_policy
                (owner_principal, automation_enabled, paused, default_decision_mode,
                 max_auto_executions_per_hour, max_auto_failures_per_hour, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_principal) DO UPDATE SET
                    automation_enabled = excluded.automation_enabled,
                    paused = excluded.paused,
                    default_decision_mode = excluded.default_decision_mode,
                    max_auto_executions_per_hour = excluded.max_auto_executions_per_hour,
                    max_auto_failures_per_hour = excluded.max_auto_failures_per_hour,
                    updated_at = excluded.updated_at""",
                (
                    owner,
                    int(automation_enabled),
                    int(paused),
                    mode,
                    max_executions,
                    max_failures,
                    now,
                ),
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
