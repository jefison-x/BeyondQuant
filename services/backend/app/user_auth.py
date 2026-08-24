"""BYQ-owned durable user identity and authentication contracts (ADR-0016 PG)."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, ensure_column, execute, fetch_one


_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{2,63}$")
_ID_PATTERN = re.compile(r"^user_[0-9a-f]{32}$")
_SESSION_ID_PATTERN = re.compile(r"^session_[0-9a-f]{32}$")
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_UI_PREFERENCES_SCHEMA = "ui-preferences.v1"
_COLOR_MODES = {"system", "light", "dark"}
_ACCENT_THEMES = {"emerald", "ocean", "indigo", "amber", "graphite"}


class UserAuthError(RuntimeError):
    pass


class UserNotFound(UserAuthError):
    pass


class UserConflict(UserAuthError):
    pass


class UserForbidden(UserAuthError):
    pass


class UserAuthPersistenceError(UserAuthError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: object, *, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _optional_text(value: object, *, field: str, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string or null")
    normalized = value.strip()
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _username(value: object) -> str:
    normalized = _text(value, field="username", max_length=64)
    if _USERNAME_PATTERN.fullmatch(normalized) is None:
        raise ValueError("username is not valid")
    return normalized


def _user_id(value: object) -> str:
    normalized = _text(value, field="user_id", max_length=64)
    if _ID_PATTERN.fullmatch(normalized) is None:
        raise ValueError("user_id is not valid")
    return normalized


def _password_hash(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = encoded.split("$")
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class UserAuthStore(PgStoreMixin):
    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            email TEXT,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            last_login_at TIMESTAMPTZ,
            password_changed_at TIMESTAMPTZ,
            preferences TEXT,
            default_prompt TEXT,
            preferences_version INTEGER NOT NULL DEFAULT 1
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS auth_sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(user_id),
            created_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS auth_sessions_user
            ON auth_sessions(user_id, expires_at)
        """,
        """
        CREATE TABLE IF NOT EXISTS user_ui_preferences (
            user_id TEXT PRIMARY KEY REFERENCES users(user_id),
            schema_version TEXT NOT NULL CHECK (schema_version = 'ui-preferences.v1'),
            color_mode TEXT NOT NULL CHECK (color_mode IN ('system', 'light', 'dark')),
            accent_theme TEXT NOT NULL CHECK (accent_theme IN ('emerald', 'ocean', 'indigo', 'amber', 'graphite')),
            version INTEGER NOT NULL CHECK (version > 0),
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as exc:
            raise UserAuthPersistenceError("user storage is unavailable") from exc

    def bootstrap_schema(self) -> None:
        super().bootstrap_schema()
        # Column back-migration parity with the former SQLite schema.
        with self.engine.begin() as connection:
            ensure_column(connection, "users", "preferences", "TEXT")
            ensure_column(connection, "users", "default_prompt", "TEXT")

    @classmethod
    def from_env(cls) -> "UserAuthStore":
        return cls()

    def create_user(self, payload: object, *, actor_role: str | None = None) -> dict[str, object]:
        if actor_role not in {"admin"}:
            raise UserForbidden("only admin may create users")
        if not isinstance(payload, dict):
            raise ValueError("user request must be an object")
        username = _username(payload.get("username"))
        email = _text(payload["email"], field="email", max_length=254) if payload.get("email") else None
        display_name = _text(payload.get("display_name"), field="display_name", max_length=128)
        password = _text(payload.get("password"), field="password", max_length=256)
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        role = _text(payload.get("role", "user"), field="role", max_length=16)
        if role not in {"admin", "user"}:
            raise ValueError("role must be admin or user")
        now = _now().isoformat()
        user_id = _new_id("user")
        self._execute(
            """INSERT INTO users
            (user_id, username, email, display_name, password_hash, status, role,
             created_at, updated_at, last_login_at, password_changed_at, preferences_version)
            VALUES (:user_id, :username, :email, :display_name, :password_hash, 'active',
                    :role, :created_at, :updated_at, NULL, :password_changed_at, 1)""",
            {
                "user_id": user_id,
                "username": username,
                "email": email,
                "display_name": display_name,
                "password_hash": _password_hash(password),
                "role": role,
                "created_at": now,
                "updated_at": now,
                "password_changed_at": now,
            },
        )
        return self.get_user(user_id)

    def ensure_bootstrap_admin(self, username: str, password: str) -> dict[str, object]:
        existing = self._fetch_one("SELECT user_id FROM users LIMIT 1")
        if existing is not None:
            return self.get_user(existing["user_id"])
        return self.create_user(
            {"username": username, "password": password, "display_name": "Bootstrap Admin", "role": "admin"},
            actor_role="admin",
        )

    def get_user(self, user_id: object) -> dict[str, object]:
        user_id = _user_id(user_id)
        row = self._fetch_one("SELECT * FROM users WHERE user_id = :user_id", {"user_id": user_id})
        if row is None:
            raise UserNotFound("user not found")
        return self._user_row(row)

    def update_profile(self, user_id: object, payload: object) -> dict[str, object]:
        user_id = _user_id(user_id)
        if not isinstance(payload, dict):
            raise ValueError("profile request must be an object")
        allowed = {"display_name", "preferences", "default_prompt"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"profile request has unknown fields: {', '.join(unknown)}")

        updates: list[str] = []
        params: dict[str, object] = {}
        if "display_name" in payload:
            updates.append("display_name = :display_name")
            params["display_name"] = _text(payload.get("display_name"), field="display_name", max_length=128)
        if "preferences" in payload:
            updates.append("preferences = :preferences")
            params["preferences"] = _optional_text(payload.get("preferences"), field="preferences", max_length=2000)
        if "default_prompt" in payload:
            updates.append("default_prompt = :default_prompt")
            params["default_prompt"] = _optional_text(payload.get("default_prompt"), field="default_prompt", max_length=2000)

        if not updates:
            return self.get_user(user_id)

        updates.append("updated_at = :updated_at")
        params["updated_at"] = _now().isoformat()
        params["user_id"] = user_id
        with self._transaction() as connection:
            row = fetch_one(connection, "SELECT * FROM users WHERE user_id = :user_id", {"user_id": user_id})
            if row is None:
                raise UserNotFound("user not found")
            execute(connection, f"UPDATE users SET {', '.join(updates)} WHERE user_id = :user_id", params)
            updated = fetch_one(connection, "SELECT * FROM users WHERE user_id = :user_id", {"user_id": user_id})
        assert updated is not None
        return self._user_row(updated)

    def get_ui_preferences(self, user_id: object) -> dict[str, object]:
        user_id = _user_id(user_id)
        if self._fetch_one("SELECT user_id FROM users WHERE user_id = :user_id", {"user_id": user_id}) is None:
            raise UserNotFound("user not found")
        row = self._fetch_one(
            "SELECT * FROM user_ui_preferences WHERE user_id = :user_id",
            {"user_id": user_id},
        )
        if row is None:
            return {
                "schema_version": _UI_PREFERENCES_SCHEMA,
                "color_mode": "system",
                "accent_theme": "emerald",
                "version": 0,
                "updated_at": None,
            }
        return self._ui_preferences_row(row)

    def update_ui_preferences(self, user_id: object, payload: object) -> dict[str, object]:
        user_id = _user_id(user_id)
        if not isinstance(payload, dict):
            raise ValueError("UI preferences request must be an object")
        allowed = {"schema_version", "color_mode", "accent_theme", "expected_version"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"UI preferences request has unknown fields: {', '.join(unknown)}")
        if payload.get("schema_version") != _UI_PREFERENCES_SCHEMA:
            raise ValueError(f"schema_version must be {_UI_PREFERENCES_SCHEMA}")
        color_mode = _text(payload.get("color_mode"), field="color_mode", max_length=16)
        if color_mode not in _COLOR_MODES:
            raise ValueError("color_mode must be system, light, or dark")
        accent_theme = _text(payload.get("accent_theme"), field="accent_theme", max_length=16)
        if accent_theme not in _ACCENT_THEMES:
            raise ValueError("accent_theme is not supported")
        expected_version = payload.get("expected_version")
        if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 0:
            raise ValueError("expected_version must be a non-negative integer")

        now = _now().isoformat()
        with self._transaction() as connection:
            user = fetch_one(connection, "SELECT user_id FROM users WHERE user_id = :user_id", {"user_id": user_id})
            if user is None:
                raise UserNotFound("user not found")
            current = fetch_one(
                connection,
                "SELECT * FROM user_ui_preferences WHERE user_id = :user_id FOR UPDATE",
                {"user_id": user_id},
            )
            current_version = int(current["version"]) if current is not None else 0
            if expected_version != current_version:
                raise UserConflict("UI preferences version is stale")
            next_version = current_version + 1
            if current is None:
                execute(
                    connection,
                    """INSERT INTO user_ui_preferences
                    (user_id, schema_version, color_mode, accent_theme, version, updated_at)
                    VALUES (:user_id, :schema_version, :color_mode, :accent_theme, :version, :updated_at)""",
                    {
                        "user_id": user_id,
                        "schema_version": _UI_PREFERENCES_SCHEMA,
                        "color_mode": color_mode,
                        "accent_theme": accent_theme,
                        "version": next_version,
                        "updated_at": now,
                    },
                )
            else:
                execute(
                    connection,
                    """UPDATE user_ui_preferences
                    SET color_mode = :color_mode, accent_theme = :accent_theme,
                        version = :version, updated_at = :updated_at
                    WHERE user_id = :user_id""",
                    {
                        "user_id": user_id,
                        "color_mode": color_mode,
                        "accent_theme": accent_theme,
                        "version": next_version,
                        "updated_at": now,
                    },
                )
            updated = fetch_one(
                connection,
                "SELECT * FROM user_ui_preferences WHERE user_id = :user_id",
                {"user_id": user_id},
            )
        assert updated is not None
        return self._ui_preferences_row(updated)

    def list_users(self, *, actor_role: str | None = None) -> dict[str, object]:
        if actor_role not in {"admin"}:
            raise UserForbidden("only admin may list users")
        rows = self._execute("SELECT * FROM users ORDER BY created_at ASC")
        return {"users": [self._user_row(row) for row in rows]}

    def disable_user(self, user_id: object, *, actor_role: str | None = None) -> dict[str, object]:
        if actor_role not in {"admin"}:
            raise UserForbidden("only admin may disable users")
        user_id = _user_id(user_id)
        with self._transaction() as connection:
            row = fetch_one(connection, "SELECT * FROM users WHERE user_id = :user_id", {"user_id": user_id})
            if row is None:
                raise UserNotFound("user not found")
            execute(
                connection,
                "UPDATE users SET status = 'disabled', updated_at = :updated_at WHERE user_id = :user_id",
                {"updated_at": _now().isoformat(), "user_id": user_id},
            )
            execute(connection, "DELETE FROM auth_sessions WHERE user_id = :user_id", {"user_id": user_id})
            updated = fetch_one(connection, "SELECT * FROM users WHERE user_id = :user_id", {"user_id": user_id})
        assert updated is not None
        return self._user_row(updated)

    def login(self, username: object, password: object) -> dict[str, object]:
        username = _username(username)
        password = _text(password, field="password", max_length=256)
        with self._transaction() as connection:
            row = fetch_one(connection, "SELECT * FROM users WHERE username = :username", {"username": username})
            if row is None or not _verify_password(password, row["password_hash"]):
                raise UserForbidden("invalid username or password")
            if row["status"] != "active":
                raise UserForbidden("user account is disabled")
            now = _now()
            session_id = _new_id("session")
            expires_at = (now + timedelta(hours=12)).isoformat()
            execute(
                connection,
                "INSERT INTO auth_sessions (session_id, user_id, created_at, expires_at) VALUES (:session_id, :user_id, :created_at, :expires_at)",
                {"session_id": session_id, "user_id": row["user_id"], "created_at": now.isoformat(), "expires_at": expires_at},
            )
            execute(
                connection,
                "UPDATE users SET last_login_at = :last_login_at WHERE user_id = :user_id",
                {"last_login_at": now.isoformat(), "user_id": row["user_id"]},
            )
        return {"user": self._user_row(row), "session_id": session_id}

    def logout(self, session_id: object) -> None:
        session_id = self._session_id(session_id)
        self._execute("DELETE FROM auth_sessions WHERE session_id = :session_id", {"session_id": session_id})

    def get_session_user(self, session_id: object) -> dict[str, object]:
        session_id = self._session_id(session_id)
        row = self._fetch_one(
            """SELECT u.*, s.expires_at AS session_expires_at
            FROM auth_sessions s JOIN users u ON u.user_id = s.user_id
            WHERE s.session_id = :session_id""",
            {"session_id": session_id},
        )
        if row is None or row["session_expires_at"] < _now().isoformat() or row["status"] != "active":
            raise UserForbidden("session is not valid")
        return self._user_row(row)

    @staticmethod
    def _session_id(value: object) -> str:
        normalized = _text(value, field="session_id", max_length=64)
        if _SESSION_ID_PATTERN.fullmatch(normalized) is None:
            raise ValueError("session_id is not valid")
        return normalized

    @staticmethod
    def _user_row(row: dict[str, Any]) -> dict[str, object]:
        result = dict(row)
        result.pop("password_hash", None)
        return result

    @staticmethod
    def _ui_preferences_row(row: dict[str, Any]) -> dict[str, object]:
        return {
            "schema_version": row["schema_version"],
            "color_mode": row["color_mode"],
            "accent_theme": row["accent_theme"],
            "version": int(row["version"]),
            "updated_at": row["updated_at"],
        }
