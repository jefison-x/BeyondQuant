"""Owner-scoped durable product conversations (ADR-0024)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin


_PRINCIPAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_STATUSES = {"active", "archived"}


class ConversationError(RuntimeError):
    pass


class ConversationNotFound(ConversationError):
    pass


class ConversationConflict(ConversationError):
    pass


class ConversationPersistenceError(ConversationError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return normalized


def _owner(value: object) -> str:
    normalized = _text(value, field="owner_principal", maximum=128)
    if _PRINCIPAL.fullmatch(normalized) is None:
        raise ValueError("owner_principal is invalid")
    return normalized


def _identifier(value: object, field: str) -> str:
    normalized = _text(value, field=field, maximum=128)
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise ValueError(f"{field} is invalid")
    return normalized


def deterministic_title(content: object) -> str:
    """Return a stable, bounded title without invoking a model."""

    normalized = _text(content, field="content", maximum=12_000)
    return normalized if len(normalized) <= 48 else f"{normalized[:47]}…"


class ConversationCatalogStore(PgStoreMixin):
    SCHEMA_DDL = [
        """
        CREATE TABLE IF NOT EXISTS product_conversations (
            conversation_id TEXT PRIMARY KEY,
            owner_principal TEXT NOT NULL,
            runtime_session_id TEXT NOT NULL UNIQUE,
            trace_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            pinned BOOLEAN NOT NULL DEFAULT FALSE,
            message_count INTEGER NOT NULL DEFAULT 0,
            last_message_preview TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS product_conversations_owner_catalog
            ON product_conversations(owner_principal, status, pinned DESC, updated_at DESC, conversation_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS product_conversation_messages (
            message_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES product_conversations(conversation_id),
            owner_principal TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE(conversation_id, sequence)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS product_conversation_messages_replay
            ON product_conversation_messages(owner_principal, conversation_id, sequence)
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError("conversation catalog is unavailable") from exc

    def create(self, owner: object, runtime_session_id: object, trace_id: object) -> dict[str, object]:
        owner = _owner(owner)
        runtime_session_id = _identifier(runtime_session_id, "runtime_session_id")
        trace_id = _identifier(trace_id, "trace_id")
        conversation_id = f"conversation_{uuid.uuid4().hex}"
        now = _now()
        try:
            row = self._fetch_one(
                """INSERT INTO product_conversations
                (conversation_id, owner_principal, runtime_session_id, trace_id, title, status,
                 pinned, message_count, last_message_preview, created_at, updated_at)
                VALUES (:conversation_id, :owner, :runtime_session_id, :trace_id, '新投研对话',
                        'active', FALSE, 0, '', :now, :now)
                RETURNING *""",
                {"conversation_id": conversation_id, "owner": owner,
                 "runtime_session_id": runtime_session_id, "trace_id": trace_id, "now": now},
            )
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError("conversation could not be created") from exc
        assert row is not None
        return self._public(row)

    def get(self, owner: object, conversation_id: object) -> dict[str, object]:
        owner = _owner(owner)
        conversation_id = _identifier(conversation_id, "conversation_id")
        row = self._fetch_one(
            "SELECT * FROM product_conversations WHERE owner_principal = :owner AND conversation_id = :id",
            {"owner": owner, "id": conversation_id},
        )
        if row is None:
            raise ConversationNotFound("conversation not found")
        return self._public(row)

    def get_by_runtime_session(self, owner: object, session_id: object) -> dict[str, object]:
        owner = _owner(owner)
        session_id = _identifier(session_id, "session_id")
        row = self._fetch_one(
            "SELECT * FROM product_conversations WHERE owner_principal = :owner AND runtime_session_id = :id",
            {"owner": owner, "id": session_id},
        )
        if row is None:
            raise ConversationNotFound("conversation not found")
        return self._public(row)

    def list(self, owner: object, *, status: object = "active", search: object = "", limit: object = 20, offset: object = 0) -> dict[str, object]:
        owner = _owner(owner)
        if status not in _STATUSES:
            raise ValueError("status must be active or archived")
        if not isinstance(search, str):
            raise ValueError("search must be a string")
        search = " ".join(search.split())[:120]
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 or offset > 10_000:
            raise ValueError("offset must be between 0 and 10000")
        params = {"owner": owner, "status": status, "search": f"%{search}%", "limit": limit, "offset": offset}
        where = "owner_principal = :owner AND status = :status AND (:search = '%%' OR title ILIKE :search OR last_message_preview ILIKE :search)"
        rows = self._execute(
            f"SELECT * FROM product_conversations WHERE {where} ORDER BY pinned DESC, updated_at DESC, conversation_id LIMIT :limit OFFSET :offset",
            params,
        )
        total = self._fetch_one(f"SELECT COUNT(*) AS total FROM product_conversations WHERE {where}", params)
        return {"conversations": [self._public(row) for row in rows], "total": int((total or {}).get("total", 0)), "limit": limit, "offset": offset}

    def append_user_message(self, owner: object, conversation_id: object, content: object) -> dict[str, object]:
        owner = _owner(owner)
        conversation_id = _identifier(conversation_id, "conversation_id")
        content = _text(content, field="content", maximum=12_000)
        now = _now()
        with self._transaction() as connection:
            row = connection.execute(
                text("SELECT * FROM product_conversations WHERE owner_principal = :owner AND conversation_id = :id FOR UPDATE"),
                {"owner": owner, "id": conversation_id},
            ).mappings().first()
            if row is None:
                raise ConversationNotFound("conversation not found")
            if row["status"] != "active":
                raise ConversationConflict("archived conversation cannot receive messages")
            sequence = int(row["message_count"]) + 1
            title = deterministic_title(content) if sequence == 1 else str(row["title"])
            preview = content if len(content) <= 120 else f"{content[:119]}…"
            message_id = f"message_{uuid.uuid4().hex}"
            connection.execute(
                text(
                    """INSERT INTO product_conversation_messages
                    (message_id, conversation_id, owner_principal, sequence, role, content, created_at)
                    VALUES (:message_id, :conversation_id, :owner, :sequence, 'user', :content, :now)"""
                ),
                {"message_id": message_id, "conversation_id": conversation_id, "owner": owner,
                 "sequence": sequence, "content": content, "now": now},
            )
            connection.execute(
                text(
                    """UPDATE product_conversations SET title = :title, message_count = :sequence,
                    last_message_preview = :preview, updated_at = :now WHERE conversation_id = :conversation_id"""
                ),
                {"title": title, "sequence": sequence, "preview": preview,
                 "now": now, "conversation_id": conversation_id},
            )
        return {"message_id": message_id, "sequence": sequence, "role": "user", "content": content, "created_at": now}

    def messages(self, owner: object, conversation_id: object, *, limit: object = 200) -> list[dict[str, object]]:
        self.get(owner, conversation_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        return self._execute(
            """SELECT message_id, sequence, role, content, created_at
            FROM product_conversation_messages WHERE owner_principal = :owner AND conversation_id = :id
            ORDER BY sequence LIMIT :limit""",
            {"owner": _owner(owner), "id": conversation_id, "limit": limit},
        )

    def update(self, owner: object, conversation_id: object, payload: object) -> dict[str, object]:
        current = self.get(owner, conversation_id)
        if not isinstance(payload, dict):
            raise ValueError("conversation update must be an object")
        if set(payload) - {"title", "pinned", "status"} or not payload:
            raise ValueError("conversation update has unsupported or empty fields")
        title = current["title"] if "title" not in payload else _text(payload["title"], field="title", maximum=80)
        pinned = current["pinned"] if "pinned" not in payload else payload["pinned"]
        status = current["status"] if "status" not in payload else payload["status"]
        if not isinstance(pinned, bool):
            raise ValueError("pinned must be boolean")
        if status not in _STATUSES:
            raise ValueError("status must be active or archived")
        row = self._fetch_one(
            """UPDATE product_conversations SET title = :title, pinned = :pinned, status = :status,
            updated_at = :now WHERE owner_principal = :owner AND conversation_id = :id RETURNING *""",
            {"title": title, "pinned": pinned, "status": status, "now": _now(),
             "owner": _owner(owner), "id": conversation_id},
        )
        if row is None:
            raise ConversationNotFound("conversation not found")
        return self._public(row)

    @staticmethod
    def _public(row: dict[str, object]) -> dict[str, object]:
        result = dict(row)
        result["pinned"] = bool(result["pinned"])
        return result
