"""BYQ-owned durable user identity and authentication contracts."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{2,63}$")
_ID_PATTERN = re.compile(r"^user_[0-9a-f]{32}$")
_SESSION_ID_PATTERN = re.compile(r"^session_[0-9a-f]{32}$")
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


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


class UserAuthStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = sqlite3.connect(self.path, timeout=10.0, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 10000")
            self._create_schema()
        except sqlite3.Error as exc:
            raise UserAuthPersistenceError("user storage is unavailable") from exc

    @classmethod
    def from_env(cls) -> "UserAuthStore":
        return cls(os.getenv("BYQ_DOMAIN_DB_PATH", "/tmp/byq-domain.sqlite3"))

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    email TEXT,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT,
                    password_changed_at TEXT,
                    preferences TEXT,
                    default_prompt TEXT,
                    preferences_version INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id),
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS auth_sessions_user
                    ON auth_sessions(user_id, expires_at);
                """
            )
        self._ensure_profile_columns()

    def _ensure_profile_columns(self) -> None:
        for column in ("preferences", "default_prompt"):
            try:
                self._connection.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")
            except sqlite3.OperationalError:
                pass

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
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO users
                (user_id, username, email, display_name, password_hash, status, role,
                 created_at, updated_at, last_login_at, password_changed_at, preferences_version)
                VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, NULL, ?, 1)""",
                (user_id, username, email, display_name, _password_hash(password), role, now, now, now),
            )
            return self.get_user(user_id)

    def ensure_bootstrap_admin(self, username: str, password: str) -> dict[str, object]:
        with self._lock:
            existing = self._connection.execute("SELECT user_id FROM users LIMIT 1").fetchone()
        if existing is not None:
            return self.get_user(existing["user_id"])
        return self.create_user(
            {"username": username, "password": password, "display_name": "Bootstrap Admin", "role": "admin"},
            actor_role="admin",
        )

    def get_user(self, user_id: object) -> dict[str, object]:
        user_id = _user_id(user_id)
        with self._lock:
            row = self._connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
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
        params: list[object] = []
        if "display_name" in payload:
            updates.append("display_name = ?")
            params.append(_text(payload.get("display_name"), field="display_name", max_length=128))
        if "preferences" in payload:
            updates.append("preferences = ?")
            params.append(_optional_text(payload.get("preferences"), field="preferences", max_length=2000))
        if "default_prompt" in payload:
            updates.append("default_prompt = ?")
            params.append(_optional_text(payload.get("default_prompt"), field="default_prompt", max_length=2000))

        if not updates:
            return self.get_user(user_id)

        updates.append("updated_at = ?")
        params.append(_now().isoformat())
        params.append(user_id)
        with self._lock, self._connection:
            row = self._connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                raise UserNotFound("user not found")
            self._connection.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?",
                params,
            )
            updated = self._connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            assert updated is not None
            return self._user_row(updated)

    def list_users(self, *, actor_role: str | None = None) -> dict[str, object]:
        if actor_role not in {"admin"}:
            raise UserForbidden("only admin may list users")
        with self._lock:
            rows = self._connection.execute("SELECT * FROM users ORDER BY created_at ASC").fetchall()
        return {"users": [self._user_row(row) for row in rows]}

    def disable_user(self, user_id: object, *, actor_role: str | None = None) -> dict[str, object]:
        if actor_role not in {"admin"}:
            raise UserForbidden("only admin may disable users")
        user_id = _user_id(user_id)
        with self._lock, self._connection:
            row = self._connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                raise UserNotFound("user not found")
            self._connection.execute(
                "UPDATE users SET status = 'disabled', updated_at = ? WHERE user_id = ?",
                (_now().isoformat(), user_id),
            )
            self._connection.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
            updated = self._connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            assert updated is not None
            return self._user_row(updated)

    def login(self, username: object, password: object) -> dict[str, object]:
        username = _username(username)
        password = _text(password, field="password", max_length=256)
        with self._lock, self._connection:
            row = self._connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if row is None or not _verify_password(password, row["password_hash"]):
                raise UserForbidden("invalid username or password")
            if row["status"] != "active":
                raise UserForbidden("user account is disabled")
            now = _now()
            session_id = _new_id("session")
            expires_at = (now + timedelta(hours=12)).isoformat()
            self._connection.execute(
                "INSERT INTO auth_sessions (session_id, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (session_id, row["user_id"], now.isoformat(), expires_at),
            )
            self._connection.execute(
                "UPDATE users SET last_login_at = ? WHERE user_id = ?",
                (now.isoformat(), row["user_id"]),
            )
            return {"user": self._user_row(row), "session_id": session_id}

    def logout(self, session_id: object) -> None:
        session_id = self._session_id(session_id)
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM auth_sessions WHERE session_id = ?", (session_id,))

    def get_session_user(self, session_id: object) -> dict[str, object]:
        session_id = self._session_id(session_id)
        with self._lock:
            row = self._connection.execute(
                """SELECT u.*, s.expires_at AS session_expires_at
                FROM auth_sessions s JOIN users u ON u.user_id = s.user_id
                WHERE s.session_id = ?""",
                (session_id,),
            ).fetchone()
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
    def _user_row(row: sqlite3.Row) -> dict[str, object]:
        result = dict(row)
        result.pop("password_hash", None)
        return result
