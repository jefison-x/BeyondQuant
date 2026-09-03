"""Workspace-owned Product Feedback domain (ADR-0049, Phase 88).

This module owns feedback lifecycle, immutable revisions, safe publication
previews, moderation and the transactional publication outbox. It deliberately
contains no GitHub client and accepts no publisher credential or destination.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, execute, fetch_one


SCHEMA_VERSION = "product-feedback.v1"
PREVIEW_SCHEMA = "feedback-publication-preview.v1"
PUBLICATION_SCHEMA = "feedback-publication.v1"
OUTBOX_SCHEMA = "feedback-outbox.v1"
FINGERPRINT_SCHEMA = "feedback_fingerprint.v1"
CATEGORIES = ("bug", "feature", "performance", "usability", "other")
COMPONENTS = (
    "xiaoba", "stock_pool", "strategy", "model_research", "backtest",
    "data_center", "system_settings", "auth", "runtime", "other",
)
SEVERITIES = ("low", "normal", "high")
OWNER_STATUSES = ("draft", "submitted", "triaged", "accepted", "rejected", "duplicate", "withdrawn")
MODERATION_STATUSES = ("submitted", "triaged", "accepted", "rejected", "duplicate")
MAX_REQUEST_BYTES = 24 * 1024
MAX_STEPS = 12
OWNER_PAGE_LIMIT = 100
DETAIL_PAGE_LIMIT = 50
CREATE_LIMIT_PER_HOUR = 10
SUBMIT_LIMIT_PER_HOUR = 6
DESTINATION_KEY = "github_primary"

_ID = re.compile(r"^feedback_[0-9a-f]{32}$")
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DANGEROUS_MARKDOWN = re.compile(r"!\[|\]\(|<\s*(?:script|img|iframe|object|embed)\b", re.I)
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret|authorization)"
    r"\s*[:=]\s*[^\s,;]{4,}"
)
_TOKEN_SHAPE = re.compile(
    r"(?:gh[oprsu]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})"
)
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_SECURITY_REPORT = re.compile(
    r"(?i)(security vulnerability|credential leak|token leak|account takeover|remote code execution|"
    r"安全漏洞|凭据泄露|令牌泄露|账号被盗|远程代码执行)"
)


class FeedbackError(RuntimeError):
    pass


class FeedbackNotFound(FeedbackError):
    pass


class FeedbackForbidden(FeedbackError):
    pass


class FeedbackConflict(FeedbackError):
    pass


class FeedbackUnsafe(FeedbackError):
    pass


class FeedbackRateLimited(FeedbackError):
    pass


class FeedbackPersistenceError(FeedbackError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _reject_unknown(payload: dict[str, object], allowed: set[str], *, field: str = "feedback request") -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"{field} has unknown fields: {', '.join(unknown)}")


def _text(value: object, *, field: str, minimum: int, maximum: int, multiline: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.strip()
    if not multiline:
        normalized = " ".join(normalized.split())
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ValueError(f"{field} must contain {minimum} to {maximum} characters")
    if _CONTROL.search(normalized):
        raise ValueError(f"{field} contains unsupported control characters")
    return normalized


def _optional_text(value: object, *, field: str, maximum: int) -> str:
    if value in {None, ""}:
        return ""
    return _text(value, field=field, minimum=1, maximum=maximum, multiline=True)


def _enum(value: object, *, field: str, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{field} must be one of: {', '.join(allowed)}")
    return value


def _positive_int(value: object, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _idempotency(value: object) -> str:
    if not isinstance(value, str) or _IDEMPOTENCY.fullmatch(value) is None:
        raise ValueError("idempotency_key is not valid")
    return value


def _feedback_id(value: object) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError("feedback_id is not valid")
    return value


def _assert_safe_public_text(value: str) -> None:
    if _SECURITY_REPORT.search(value):
        raise FeedbackUnsafe("suspected security reports must use the private security channel")
    if _SECRET_ASSIGNMENT.search(value) or _TOKEN_SHAPE.search(value) or _PRIVATE_KEY.search(value):
        raise FeedbackUnsafe("feedback contains credential-shaped content")
    if _EMAIL.search(value):
        raise FeedbackUnsafe("feedback contains an email address")
    if _URL.search(value) or _DANGEROUS_MARKDOWN.search(value):
        raise FeedbackUnsafe("feedback contains an external URL or unsupported markup")


def _normalize_diagnostics(value: object) -> dict[str, bool]:
    allowed = {
        "include_product_version", "include_deployment_kind", "include_browser_family",
        "include_os_family", "include_performance_summary",
    }
    if value is None:
        return {key: False for key in sorted(allowed)}
    if not isinstance(value, dict):
        raise ValueError("diagnostics must be an object")
    _reject_unknown(value, allowed, field="diagnostics")
    result: dict[str, bool] = {}
    for key in sorted(allowed):
        item = value.get(key, False)
        if not isinstance(item, bool):
            raise ValueError(f"diagnostics.{key} must be a boolean")
        result[key] = item
    return result


def normalize_content(payload: object, *, update: bool = False) -> tuple[dict[str, object], str]:
    if not isinstance(payload, dict):
        raise ValueError("feedback request must be an object")
    allowed = {
        "schema_version", "category", "component", "title", "description",
        "reproduction_steps", "expected_behavior", "actual_behavior", "severity", "diagnostics",
    }
    _reject_unknown(payload, allowed | ({"idempotency_key"} if not update else set()))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
    steps_value = payload.get("reproduction_steps", [])
    if not isinstance(steps_value, list) or len(steps_value) > MAX_STEPS:
        raise ValueError(f"reproduction_steps must contain at most {MAX_STEPS} items")
    steps = [
        _text(item, field=f"reproduction_steps[{index}]", minimum=1, maximum=500, multiline=True)
        for index, item in enumerate(steps_value)
    ]
    content: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "category": _enum(payload.get("category"), field="category", allowed=CATEGORIES),
        "component": _enum(payload.get("component"), field="component", allowed=COMPONENTS),
        "title": _text(payload.get("title"), field="title", minimum=4, maximum=160),
        "description": _text(payload.get("description"), field="description", minimum=1, maximum=8000, multiline=True),
        "reproduction_steps": steps,
        "expected_behavior": _optional_text(payload.get("expected_behavior"), field="expected_behavior", maximum=2000),
        "actual_behavior": _optional_text(payload.get("actual_behavior"), field="actual_behavior", maximum=2000),
        "severity": _enum(payload.get("severity", "normal"), field="severity", allowed=SEVERITIES),
        "diagnostics": _normalize_diagnostics(payload.get("diagnostics")),
    }
    encoded = _canonical(content)
    if len(encoded.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise ValueError(f"feedback request exceeds {MAX_REQUEST_BYTES} bytes")
    for value in [content["title"], content["description"], content["expected_behavior"], content["actual_behavior"], *steps]:
        _assert_safe_public_text(str(value))
    return content, _hash(content)


def _fingerprint(content: dict[str, object], product_version: str) -> str:
    semantics = "\n".join(str(item).lower() for item in content["reproduction_steps"])
    digest = _hash({
        "schema": FINGERPRINT_SCHEMA,
        "category": content["category"], "component": content["component"],
        "title": str(content["title"]).casefold(), "semantics": semantics,
        "product_version": product_version,
    })
    return f"{FINGERPRINT_SCHEMA}:{digest}"


def _environment_value(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not re.fullmatch(r"[A-Za-z0-9._ -]{1,80}", normalized):
        return "unavailable"
    return normalized


def publication_preview(
    content: dict[str, object], *, product_version: str, deployment_kind: str,
    browser_family: str = "unavailable", os_family: str = "unavailable",
) -> dict[str, object]:
    diagnostics = content["diagnostics"]
    assert isinstance(diagnostics, dict)
    environment: dict[str, str] = {}
    optional = {
        "include_product_version": ("product_version", product_version),
        "include_deployment_kind": ("deployment_kind", deployment_kind),
        "include_browser_family": ("browser_family", browser_family),
        "include_os_family": ("os_family", os_family),
    }
    for opt_in, (key, value) in optional.items():
        if diagnostics.get(opt_in) is True:
            environment[key] = _environment_value(value)
    if diagnostics.get("include_performance_summary") is True:
        environment["performance_summary"] = "not_collected"
    public_content = {
        "category": content["category"], "component": content["component"],
        "severity": content["severity"], "title": content["title"],
        "description": content["description"], "reproduction_steps": content["reproduction_steps"],
        "expected_behavior": content["expected_behavior"], "actual_behavior": content["actual_behavior"],
        "environment": environment,
    }
    preview_hash = _hash({"schema_version": PREVIEW_SCHEMA, "public_content": public_content})
    return {
        "schema_version": PREVIEW_SCHEMA,
        "public_content": public_content,
        "redactions": {"categories": [], "count": 0},
        "disclosure": "提交后该脱敏快照将由平台反馈审核员读取，获批准后可能公开到 GitHub Issue。",
        "preview_hash": preview_hash,
    }


class ProductFeedbackStore(PgStoreMixin):
    SCHEMA_DDL = [
        """
        CREATE TABLE IF NOT EXISTS product_feedback (
            feedback_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
            owner_principal TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('draft','submitted','triaged','accepted','rejected','duplicate','withdrawn')),
            category TEXT NOT NULL CHECK (category IN ('bug','feature','performance','usability','other')),
            component TEXT NOT NULL CHECK (component IN ('xiaoba','stock_pool','strategy','model_research','backtest','data_center','system_settings','auth','runtime','other')),
            severity TEXT NOT NULL CHECK (severity IN ('low','normal','high')),
            title TEXT NOT NULL,
            current_revision INTEGER NOT NULL CHECK (current_revision > 0),
            fingerprint TEXT NOT NULL,
            submitted_snapshot_json JSONB,
            submitted_snapshot_hash TEXT,
            canonical_feedback_id TEXT REFERENCES product_feedback(feedback_id),
            publication_status TEXT NOT NULL DEFAULT 'not_queued' CHECK (publication_status IN ('not_queued','publisher_unconfigured')),
            version INTEGER NOT NULL CHECK (version > 0),
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS product_feedback_owner_page ON product_feedback(workspace_id, updated_at DESC, feedback_id DESC)",
        "CREATE INDEX IF NOT EXISTS product_feedback_moderation_page ON product_feedback(status, updated_at, feedback_id)",
        "CREATE INDEX IF NOT EXISTS product_feedback_fingerprint ON product_feedback(fingerprint)",
        """
        CREATE TABLE IF NOT EXISTS product_feedback_revisions (
            revision_id TEXT PRIMARY KEY,
            feedback_id TEXT NOT NULL REFERENCES product_feedback(feedback_id),
            workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
            revision_number INTEGER NOT NULL CHECK (revision_number > 0),
            content_json JSONB NOT NULL,
            content_hash TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE(feedback_id, revision_number)
        )
        """,
        "CREATE INDEX IF NOT EXISTS product_feedback_revisions_page ON product_feedback_revisions(feedback_id, revision_number DESC)",
        """
        CREATE TABLE IF NOT EXISTS product_feedback_audit (
            audit_id TEXT PRIMARY KEY,
            feedback_id TEXT NOT NULL REFERENCES product_feedback(feedback_id),
            workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
            action TEXT NOT NULL,
            actor_principal TEXT NOT NULL,
            actor_role TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT NOT NULL,
            rationale TEXT NOT NULL,
            detail_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS product_feedback_audit_page ON product_feedback_audit(feedback_id, created_at DESC, audit_id DESC)",
        "CREATE INDEX IF NOT EXISTS product_feedback_rate ON product_feedback_audit(workspace_id, action, created_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS product_feedback_publications (
            publication_id TEXT PRIMARY KEY,
            feedback_id TEXT NOT NULL UNIQUE REFERENCES product_feedback(feedback_id),
            schema_version TEXT NOT NULL CHECK (schema_version = 'feedback-publication.v1'),
            snapshot_json JSONB NOT NULL,
            snapshot_hash TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS product_feedback_outbox (
            event_id TEXT PRIMARY KEY,
            feedback_id TEXT NOT NULL UNIQUE REFERENCES product_feedback(feedback_id),
            publication_id TEXT NOT NULL UNIQUE REFERENCES product_feedback_publications(publication_id),
            schema_version TEXT NOT NULL CHECK (schema_version = 'feedback-outbox.v1'),
            snapshot_hash TEXT NOT NULL,
            destination_key TEXT NOT NULL CHECK (destination_key = 'github_primary'),
            state TEXT NOT NULL CHECK (state = 'queued'),
            attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
            next_attempt_at TIMESTAMPTZ NOT NULL,
            lease_owner TEXT,
            lease_expires_at TIMESTAMPTZ,
            lease_fence INTEGER NOT NULL DEFAULT 0 CHECK (lease_fence >= 0),
            last_error_category TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS product_feedback_outbox_due ON product_feedback_outbox(state, next_attempt_at, event_id)",
        """
        CREATE TABLE IF NOT EXISTS product_feedback_commands (
            command_id TEXT PRIMARY KEY,
            scope_key TEXT NOT NULL,
            actor_principal TEXT NOT NULL,
            operation TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            result_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE(scope_key, actor_principal, operation, idempotency_key)
        )
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        self.product_version = os.environ.get("BYQ_PRODUCT_VERSION", "0.1.0")
        self.deployment_kind = os.environ.get("BYQ_DEPLOYMENT_KIND", "self_hosted")
        try:
            super().__init__(database_url)
        except SQLAlchemyError as exc:
            raise FeedbackPersistenceError("feedback storage is unavailable") from exc

    @staticmethod
    def options(*, publisher_configured: bool = False) -> dict[str, object]:
        return {
            "schema_version": "product-feedback-options.v1",
            "categories": list(CATEGORIES), "components": list(COMPONENTS), "severities": list(SEVERITIES),
            "limits": {"title": 160, "description": 8000, "steps": MAX_STEPS, "request_bytes": MAX_REQUEST_BYTES},
            "privacy": {
                "preview_required": True, "explicit_confirmation_required": True,
                "attachments_supported": False, "security_reports_public": False,
                "normal_user_github_configuration": False,
            },
            "publisher": {"configured": publisher_configured, "status": "unconfigured" if not publisher_configured else "ready"},
        }

    def _replay(self, connection: Any, *, scope: str, actor: str, operation: str, key: str, request_hash: str) -> dict[str, object] | None:
        row = fetch_one(connection, """SELECT request_hash, result_json FROM product_feedback_commands
            WHERE scope_key=:scope AND actor_principal=:actor AND operation=:operation AND idempotency_key=:key""",
            {"scope": scope, "actor": actor, "operation": operation, "key": key})
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise FeedbackConflict("feedback idempotency key was reused with different content")
        result = row["result_json"]
        if not isinstance(result, dict):
            raise FeedbackPersistenceError("stored feedback command result is invalid")
        return result

    def _record_command(self, connection: Any, *, scope: str, actor: str, operation: str, key: str,
                        request_hash: str, result: dict[str, object], now: str) -> None:
        execute(connection, """INSERT INTO product_feedback_commands
            (command_id, scope_key, actor_principal, operation, idempotency_key, request_hash, result_json, created_at)
            VALUES (:id,:scope,:actor,:operation,:key,:hash,:result,:now)""",
            {"id": _new_id("feedback_command"), "scope": scope, "actor": actor, "operation": operation,
             "key": key, "hash": request_hash, "result": result, "now": now})

    @staticmethod
    def _audit(connection: Any, *, row: dict[str, object], action: str, actor: str, role: str,
               from_status: str | None, to_status: str, rationale: str = "", detail: dict[str, object] | None = None,
               now: str) -> None:
        execute(connection, """INSERT INTO product_feedback_audit
            (audit_id,feedback_id,workspace_id,action,actor_principal,actor_role,from_status,to_status,rationale,detail_json,created_at)
            VALUES (:id,:feedback,:workspace,:action,:actor,:role,:from_status,:to_status,:rationale,:detail,:now)""",
            {"id": _new_id("feedback_audit"), "feedback": row["feedback_id"], "workspace": row["workspace_id"],
             "action": action, "actor": actor, "role": role, "from_status": from_status, "to_status": to_status,
             "rationale": rationale, "detail": detail or {}, "now": now})

    @staticmethod
    def _rate_limit(connection: Any, *, workspace: str, action: str, limit: int) -> None:
        row = fetch_one(connection, """SELECT COUNT(*) AS count FROM product_feedback_audit
            WHERE workspace_id=:workspace AND action=:action AND created_at >= NOW() - INTERVAL '1 hour'""",
            {"workspace": workspace, "action": action})
        if row and int(row["count"]) >= limit:
            raise FeedbackRateLimited("feedback rate limit reached; try again later")

    @staticmethod
    def _revision(connection: Any, feedback_id: str, revision_number: int) -> dict[str, object]:
        row = fetch_one(connection, """SELECT * FROM product_feedback_revisions
            WHERE feedback_id=:feedback AND revision_number=:revision""",
            {"feedback": feedback_id, "revision": revision_number})
        if row is None or not isinstance(row.get("content_json"), dict):
            raise FeedbackPersistenceError("feedback revision is unavailable")
        return row

    @staticmethod
    def _owner_row(connection: Any, feedback_id: str, workspace: str) -> dict[str, object]:
        row = fetch_one(connection, """SELECT * FROM product_feedback
            WHERE feedback_id=:feedback AND workspace_id=:workspace FOR UPDATE""",
            {"feedback": feedback_id, "workspace": workspace})
        if row is None:
            raise FeedbackNotFound("feedback not found")
        return row

    @staticmethod
    def _moderator_row(connection: Any, feedback_id: str) -> dict[str, object]:
        row = fetch_one(connection, "SELECT * FROM product_feedback WHERE feedback_id=:feedback FOR UPDATE",
                        {"feedback": feedback_id})
        if row is None or row["status"] == "draft":
            raise FeedbackNotFound("submitted feedback not found")
        return row

    @staticmethod
    def _owner_projection(row: dict[str, object], content: dict[str, object] | None = None) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": SCHEMA_VERSION, "feedback_id": row["feedback_id"], "status": row["status"],
            "category": row["category"], "component": row["component"], "severity": row["severity"],
            "title": row["title"], "version": row["version"], "current_revision": row["current_revision"],
            "publication_status": row["publication_status"], "github_issue": None,
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }
        if content is not None:
            result["content"] = content
        if row.get("canonical_feedback_id"):
            result["duplicate_of_public_issue"] = None
        return result

    @staticmethod
    def _moderator_projection(row: dict[str, object]) -> dict[str, object]:
        snapshot = row.get("submitted_snapshot_json")
        if not isinstance(snapshot, dict):
            raise FeedbackPersistenceError("submitted feedback snapshot is unavailable")
        return {
            "schema_version": "feedback-moderation.v1", "feedback_id": row["feedback_id"],
            "status": row["status"], "category": row["category"], "component": row["component"],
            "severity": row["severity"], "title": row["title"], "version": row["version"],
            "submitted_snapshot": snapshot, "publication_status": row["publication_status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def create(self, payload: object, *, trusted_workspace: str, trusted_owner: str, trusted_actor: str) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("feedback request must be an object")
        content, content_hash = normalize_content(payload)
        key = _idempotency(payload.get("idempotency_key"))
        request_hash = _hash({"content": content, "workspace": trusted_workspace, "owner": trusted_owner})
        now = _now()
        with self._transaction() as connection:
            replay = self._replay(connection, scope=trusted_workspace, actor=trusted_actor, operation="create", key=key, request_hash=request_hash)
            if replay is not None:
                return replay
            self._rate_limit(connection, workspace=trusted_workspace, action="create", limit=CREATE_LIMIT_PER_HOUR)
            feedback_id = _new_id("feedback")
            row_values = {
                "feedback_id": feedback_id, "workspace_id": trusted_workspace, "owner_principal": trusted_owner,
                "status": "draft", "category": content["category"], "component": content["component"],
                "severity": content["severity"], "title": content["title"], "fingerprint": _fingerprint(content, self.product_version),
                "version": 1, "current_revision": 1, "created_at": now, "updated_at": now,
            }
            execute(connection, """INSERT INTO product_feedback
                (feedback_id,workspace_id,owner_principal,status,category,component,severity,title,current_revision,
                 fingerprint,publication_status,version,created_at,updated_at)
                VALUES (:feedback_id,:workspace_id,:owner_principal,:status,:category,:component,:severity,:title,
                 :current_revision,:fingerprint,'not_queued',:version,:created_at,:updated_at)""", row_values)
            execute(connection, """INSERT INTO product_feedback_revisions
                (revision_id,feedback_id,workspace_id,revision_number,content_json,content_hash,created_by,created_at)
                VALUES (:revision,:feedback,:workspace,1,:content,:hash,:actor,:now)""",
                {"revision": _new_id("feedback_revision"), "feedback": feedback_id, "workspace": trusted_workspace,
                 "content": content, "hash": content_hash, "actor": trusted_actor, "now": now})
            row = fetch_one(connection, "SELECT * FROM product_feedback WHERE feedback_id=:id", {"id": feedback_id})
            assert row is not None
            self._audit(connection, row=row, action="create", actor=trusted_actor, role="owner", from_status=None,
                        to_status="draft", now=now)
            result = {"feedback": self._owner_projection(row, content)}
            self._record_command(connection, scope=trusted_workspace, actor=trusted_actor, operation="create", key=key,
                                 request_hash=request_hash, result=result, now=now)
            return result

    def list_owner(self, *, trusted_workspace: str, status: str = "all", category: str = "all",
                   query: str = "", limit: int = 20, offset: int = 0) -> dict[str, object]:
        limit, offset = self._page(limit, offset, OWNER_PAGE_LIMIT)
        if status != "all":
            _enum(status, field="status", allowed=OWNER_STATUSES)
        if category != "all":
            _enum(category, field="category", allowed=CATEGORIES)
        query = _optional_text(query, field="query", maximum=80)
        filters = ["workspace_id=:workspace"]
        params: dict[str, object] = {"workspace": trusted_workspace, "limit": limit, "offset": offset}
        if status != "all":
            filters.append("status=:status"); params["status"] = status
        if category != "all":
            filters.append("category=:category"); params["category"] = category
        if query:
            filters.append("(title ILIKE :query OR component ILIKE :query)"); params["query"] = f"%{query}%"
        where = " AND ".join(filters)
        count = self._fetch_one(f"SELECT COUNT(*) AS count FROM product_feedback WHERE {where}", params)
        rows = self._execute(f"""SELECT * FROM product_feedback WHERE {where}
            ORDER BY updated_at DESC, feedback_id DESC LIMIT :limit OFFSET :offset""", params)
        total = int(count["count"] if count else 0)
        return {"schema_version": "product-feedback-catalog.v1", "items": [self._owner_projection(row) for row in rows],
                "total": total, "limit": limit, "offset": offset, "has_more": offset + len(rows) < total}

    def get_owner(self, feedback_id: object, *, trusted_workspace: str) -> dict[str, object]:
        identity = _feedback_id(feedback_id)
        row = self._fetch_one("SELECT * FROM product_feedback WHERE feedback_id=:feedback AND workspace_id=:workspace",
                              {"feedback": identity, "workspace": trusted_workspace})
        if row is None:
            raise FeedbackNotFound("feedback not found")
        revision = self._fetch_one("""SELECT content_json FROM product_feedback_revisions
            WHERE feedback_id=:feedback AND revision_number=:revision""",
            {"feedback": identity, "revision": row["current_revision"]})
        if revision is None or not isinstance(revision.get("content_json"), dict):
            raise FeedbackPersistenceError("feedback revision is unavailable")
        return {"feedback": self._owner_projection(row, revision["content_json"])}

    def list_revisions(self, feedback_id: object, *, trusted_workspace: str, limit: int = 20, offset: int = 0) -> dict[str, object]:
        identity = _feedback_id(feedback_id)
        self.get_owner(identity, trusted_workspace=trusted_workspace)
        limit, offset = self._page(limit, offset, DETAIL_PAGE_LIMIT)
        count = self._fetch_one("SELECT COUNT(*) AS count FROM product_feedback_revisions WHERE feedback_id=:feedback",
                                {"feedback": identity})
        rows = self._execute("""SELECT revision_id,revision_number,content_hash,created_at FROM product_feedback_revisions
            WHERE feedback_id=:feedback ORDER BY revision_number DESC LIMIT :limit OFFSET :offset""",
            {"feedback": identity, "limit": limit, "offset": offset})
        total = int(count["count"] if count else 0)
        return {"schema_version": "product-feedback-revisions.v1", "revisions": rows, "total": total,
                "limit": limit, "offset": offset, "has_more": offset + len(rows) < total}

    @staticmethod
    def _page(limit: object, offset: object, maximum: int) -> tuple[int, int]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > maximum:
            raise ValueError(f"limit must be between 1 and {maximum}")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        return limit, offset

    def update(self, feedback_id: object, payload: object, *, trusted_workspace: str, trusted_actor: str) -> dict[str, object]:
        identity = _feedback_id(feedback_id)
        if not isinstance(payload, dict):
            raise ValueError("feedback update must be an object")
        _reject_unknown(payload, {"content", "expected_version", "idempotency_key"})
        content, content_hash = normalize_content(payload.get("content"), update=True)
        expected = _positive_int(payload.get("expected_version"), field="expected_version")
        key = _idempotency(payload.get("idempotency_key"))
        request_hash = _hash({"feedback_id": identity, "content": content, "expected_version": expected})
        now = _now()
        with self._transaction() as connection:
            replay = self._replay(connection, scope=trusted_workspace, actor=trusted_actor, operation=f"update:{identity}", key=key, request_hash=request_hash)
            if replay is not None:
                return replay
            row = self._owner_row(connection, identity, trusted_workspace)
            if row["status"] != "draft":
                raise FeedbackForbidden("only draft feedback can be updated")
            if int(row["version"]) != expected:
                raise FeedbackConflict("feedback version changed")
            revision_number = int(row["current_revision"]) + 1
            execute(connection, """INSERT INTO product_feedback_revisions
                (revision_id,feedback_id,workspace_id,revision_number,content_json,content_hash,created_by,created_at)
                VALUES (:revision,:feedback,:workspace,:number,:content,:hash,:actor,:now)""",
                {"revision": _new_id("feedback_revision"), "feedback": identity, "workspace": trusted_workspace,
                 "number": revision_number, "content": content, "hash": content_hash, "actor": trusted_actor, "now": now})
            execute(connection, """UPDATE product_feedback SET category=:category,component=:component,severity=:severity,
                title=:title,current_revision=:revision,fingerprint=:fingerprint,version=version+1,updated_at=:now
                WHERE feedback_id=:feedback""",
                {"category": content["category"], "component": content["component"], "severity": content["severity"],
                 "title": content["title"], "revision": revision_number, "fingerprint": _fingerprint(content, self.product_version),
                 "now": now, "feedback": identity})
            row = fetch_one(connection, "SELECT * FROM product_feedback WHERE feedback_id=:feedback", {"feedback": identity})
            assert row is not None
            self._audit(connection, row=row, action="update", actor=trusted_actor, role="owner", from_status="draft",
                        to_status="draft", detail={"revision_number": revision_number}, now=now)
            result = {"feedback": self._owner_projection(row, content)}
            self._record_command(connection, scope=trusted_workspace, actor=trusted_actor, operation=f"update:{identity}", key=key,
                                 request_hash=request_hash, result=result, now=now)
            return result

    def preview(self, feedback_id: object, *, trusted_workspace: str, expected_version: object,
                browser_family: str = "unavailable", os_family: str = "unavailable") -> dict[str, object]:
        identity = _feedback_id(feedback_id)
        expected = _positive_int(expected_version, field="expected_version")
        with self._transaction() as connection:
            row = self._owner_row(connection, identity, trusted_workspace)
            if row["status"] != "draft":
                raise FeedbackForbidden("only draft feedback can be previewed")
            if int(row["version"]) != expected:
                raise FeedbackConflict("feedback version changed")
            revision = self._revision(connection, identity, int(row["current_revision"]))
            return publication_preview(revision["content_json"], product_version=self.product_version,
                                       deployment_kind=self.deployment_kind, browser_family=browser_family, os_family=os_family)

    def submit(self, feedback_id: object, payload: object, *, trusted_workspace: str, trusted_actor: str,
               browser_family: str = "unavailable", os_family: str = "unavailable") -> dict[str, object]:
        identity = _feedback_id(feedback_id)
        if not isinstance(payload, dict):
            raise ValueError("feedback submit request must be an object")
        _reject_unknown(payload, {"expected_version", "preview_hash", "disclosure_confirmed", "idempotency_key"})
        expected = _positive_int(payload.get("expected_version"), field="expected_version")
        preview_hash = _text(payload.get("preview_hash"), field="preview_hash", minimum=64, maximum=64)
        if payload.get("disclosure_confirmed") is not True:
            raise FeedbackForbidden("feedback disclosure must be explicitly confirmed")
        key = _idempotency(payload.get("idempotency_key"))
        request_hash = _hash({"feedback_id": identity, "version": expected, "preview_hash": preview_hash, "confirmed": True})
        now = _now()
        with self._transaction() as connection:
            replay = self._replay(connection, scope=trusted_workspace, actor=trusted_actor, operation=f"submit:{identity}", key=key, request_hash=request_hash)
            if replay is not None:
                return replay
            self._rate_limit(connection, workspace=trusted_workspace, action="submit", limit=SUBMIT_LIMIT_PER_HOUR)
            row = self._owner_row(connection, identity, trusted_workspace)
            if row["status"] != "draft":
                raise FeedbackForbidden("only draft feedback can be submitted")
            if int(row["version"]) != expected:
                raise FeedbackConflict("feedback version changed")
            revision = self._revision(connection, identity, int(row["current_revision"]))
            preview = publication_preview(revision["content_json"], product_version=self.product_version,
                                          deployment_kind=self.deployment_kind, browser_family=browser_family, os_family=os_family)
            if preview["preview_hash"] != preview_hash:
                raise FeedbackConflict("feedback preview changed; review it again")
            snapshot = {"schema_version": "submitted-feedback-snapshot.v1", "public_content": preview["public_content"],
                        "redactions": preview["redactions"], "preview_hash": preview_hash}
            snapshot_hash = _hash(snapshot)
            execute(connection, """UPDATE product_feedback SET status='submitted',submitted_snapshot_json=:snapshot,
                submitted_snapshot_hash=:hash,version=version+1,updated_at=:now WHERE feedback_id=:feedback""",
                {"snapshot": snapshot, "hash": snapshot_hash, "now": now, "feedback": identity})
            row = fetch_one(connection, "SELECT * FROM product_feedback WHERE feedback_id=:feedback", {"feedback": identity})
            assert row is not None
            self._audit(connection, row=row, action="submit", actor=trusted_actor, role="owner", from_status="draft",
                        to_status="submitted", detail={"snapshot_hash": snapshot_hash}, now=now)
            result = {"feedback": self._owner_projection(row)}
            self._record_command(connection, scope=trusted_workspace, actor=trusted_actor, operation=f"submit:{identity}", key=key,
                                 request_hash=request_hash, result=result, now=now)
            return result

    def withdraw(self, feedback_id: object, payload: object, *, trusted_workspace: str, trusted_actor: str) -> dict[str, object]:
        return self._owner_transition(feedback_id, payload, trusted_workspace=trusted_workspace, trusted_actor=trusted_actor,
                                      action="withdraw", allowed_from="submitted", target="withdrawn")

    def _owner_transition(self, feedback_id: object, payload: object, *, trusted_workspace: str, trusted_actor: str,
                          action: str, allowed_from: str, target: str) -> dict[str, object]:
        identity = _feedback_id(feedback_id)
        if not isinstance(payload, dict):
            raise ValueError(f"feedback {action} request must be an object")
        _reject_unknown(payload, {"expected_version", "idempotency_key"})
        expected = _positive_int(payload.get("expected_version"), field="expected_version")
        key = _idempotency(payload.get("idempotency_key"))
        request_hash = _hash({"feedback_id": identity, "version": expected, "target": target})
        now = _now()
        with self._transaction() as connection:
            operation = f"{action}:{identity}"
            replay = self._replay(connection, scope=trusted_workspace, actor=trusted_actor, operation=operation, key=key, request_hash=request_hash)
            if replay is not None:
                return replay
            row = self._owner_row(connection, identity, trusted_workspace)
            if row["status"] != allowed_from:
                raise FeedbackForbidden(f"feedback cannot transition from {row['status']} using {action}")
            if int(row["version"]) != expected:
                raise FeedbackConflict("feedback version changed")
            execute(connection, "UPDATE product_feedback SET status=:target,version=version+1,updated_at=:now WHERE feedback_id=:feedback",
                    {"target": target, "now": now, "feedback": identity})
            row = fetch_one(connection, "SELECT * FROM product_feedback WHERE feedback_id=:feedback", {"feedback": identity})
            assert row is not None
            self._audit(connection, row=row, action=action, actor=trusted_actor, role="owner", from_status=allowed_from,
                        to_status=target, now=now)
            result = {"feedback": self._owner_projection(row)}
            self._record_command(connection, scope=trusted_workspace, actor=trusted_actor, operation=operation, key=key,
                                 request_hash=request_hash, result=result, now=now)
            return result

    @staticmethod
    def _require_moderator(role: str) -> None:
        if role != "admin":
            raise FeedbackForbidden("feedback moderator role required")

    def list_moderation(self, *, actor_role: str, status: str = "submitted", category: str = "all",
                        query: str = "", limit: int = 20, offset: int = 0) -> dict[str, object]:
        self._require_moderator(actor_role)
        limit, offset = self._page(limit, offset, OWNER_PAGE_LIMIT)
        if status != "all": _enum(status, field="status", allowed=MODERATION_STATUSES)
        if category != "all": _enum(category, field="category", allowed=CATEGORIES)
        query = _optional_text(query, field="query", maximum=80)
        filters = ["status <> 'draft'", "submitted_snapshot_json IS NOT NULL"]
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if status != "all": filters.append("status=:status"); params["status"] = status
        if category != "all": filters.append("category=:category"); params["category"] = category
        if query: filters.append("(title ILIKE :query OR component ILIKE :query)"); params["query"] = f"%{query}%"
        where = " AND ".join(filters)
        count = self._fetch_one(f"SELECT COUNT(*) AS count FROM product_feedback WHERE {where}", params)
        rows = self._execute(f"""SELECT * FROM product_feedback WHERE {where}
            ORDER BY updated_at,feedback_id LIMIT :limit OFFSET :offset""", params)
        total = int(count["count"] if count else 0)
        return {"schema_version": "feedback-moderation-catalog.v1", "items": [self._moderator_projection(row) for row in rows],
                "total": total, "limit": limit, "offset": offset, "has_more": offset + len(rows) < total}

    def get_moderation(self, feedback_id: object, *, actor_role: str) -> dict[str, object]:
        self._require_moderator(actor_role)
        identity = _feedback_id(feedback_id)
        row = self._fetch_one("SELECT * FROM product_feedback WHERE feedback_id=:feedback AND status <> 'draft'",
                              {"feedback": identity})
        if row is None:
            raise FeedbackNotFound("submitted feedback not found")
        return {"feedback": self._moderator_projection(row)}

    def list_audit(self, feedback_id: object, *, actor_role: str, limit: int = 20, offset: int = 0) -> dict[str, object]:
        self._require_moderator(actor_role)
        identity = _feedback_id(feedback_id)
        self.get_moderation(identity, actor_role=actor_role)
        limit, offset = self._page(limit, offset, DETAIL_PAGE_LIMIT)
        count = self._fetch_one("SELECT COUNT(*) AS count FROM product_feedback_audit WHERE feedback_id=:feedback",
                                {"feedback": identity})
        rows = self._execute("""SELECT audit_id,action,actor_role,from_status,to_status,rationale,detail_json,created_at
            FROM product_feedback_audit WHERE feedback_id=:feedback
            ORDER BY created_at DESC,audit_id DESC LIMIT :limit OFFSET :offset""",
            {"feedback": identity, "limit": limit, "offset": offset})
        safe_rows = []
        for row in rows:
            raw_detail = row.get("detail_json") if isinstance(row.get("detail_json"), dict) else {}
            detail: dict[str, object] = {}
            if isinstance(raw_detail.get("revision_number"), int):
                detail["revision_number"] = raw_detail["revision_number"]
            if raw_detail.get("canonical_feedback_id"):
                detail["duplicate_linked"] = True
            if raw_detail.get("publication_id"):
                detail["publication_queued"] = True
            safe_rows.append({
                "audit_id": row["audit_id"], "action": row["action"], "actor_role": row["actor_role"],
                "from_status": row["from_status"], "to_status": row["to_status"],
                "rationale": row["rationale"], "detail": detail, "created_at": row["created_at"],
            })
        total = int(count["count"] if count else 0)
        return {"schema_version": "feedback-moderation-audit.v1", "audit": safe_rows, "total": total,
                "limit": limit, "offset": offset, "has_more": offset + len(rows) < total}

    def moderate(self, feedback_id: object, action: str, payload: object, *, trusted_actor: str, actor_role: str) -> dict[str, object]:
        self._require_moderator(actor_role)
        identity = _feedback_id(feedback_id)
        if action not in {"triage", "accept", "reject", "duplicate"}:
            raise ValueError("moderation action is invalid")
        if not isinstance(payload, dict):
            raise ValueError("moderation request must be an object")
        allowed = {"expected_version", "idempotency_key", "rationale"}
        if action == "duplicate": allowed.add("canonical_feedback_id")
        _reject_unknown(payload, allowed)
        expected = _positive_int(payload.get("expected_version"), field="expected_version")
        key = _idempotency(payload.get("idempotency_key"))
        rationale = _text(payload.get("rationale"), field="rationale", minimum=2, maximum=1000, multiline=True)
        _assert_safe_public_text(rationale)
        canonical = _feedback_id(payload.get("canonical_feedback_id")) if action == "duplicate" else None
        request_hash = _hash({"feedback_id": identity, "action": action, "version": expected,
                              "rationale": rationale, "canonical_feedback_id": canonical})
        now = _now()
        with self._transaction() as connection:
            operation = f"moderate:{action}:{identity}"
            replay = self._replay(connection, scope="platform-feedback", actor=trusted_actor, operation=operation, key=key, request_hash=request_hash)
            if replay is not None: return replay
            row = self._moderator_row(connection, identity)
            expected_from = "submitted" if action == "triage" else "triaged"
            target = {"triage": "triaged", "accept": "accepted", "reject": "rejected", "duplicate": "duplicate"}[action]
            if row["status"] != expected_from:
                raise FeedbackForbidden(f"feedback cannot transition from {row['status']} using {action}")
            if int(row["version"]) != expected:
                raise FeedbackConflict("feedback version changed")
            if canonical is not None:
                target_row = fetch_one(connection, "SELECT feedback_id,status FROM product_feedback WHERE feedback_id=:feedback",
                                       {"feedback": canonical})
                if target_row is None or target_row["feedback_id"] == identity or target_row["status"] not in {"triaged", "accepted"}:
                    raise FeedbackConflict("canonical feedback is not available")
            publication_status = "publisher_unconfigured" if action == "accept" else str(row["publication_status"])
            execute(connection, """UPDATE product_feedback SET status=:target,canonical_feedback_id=:canonical,
                publication_status=:publication_status,version=version+1,updated_at=:now WHERE feedback_id=:feedback""",
                {"target": target, "canonical": canonical, "publication_status": publication_status,
                 "now": now, "feedback": identity})
            row = fetch_one(connection, "SELECT * FROM product_feedback WHERE feedback_id=:feedback", {"feedback": identity})
            assert row is not None
            detail: dict[str, object] = {}
            if canonical is not None: detail["canonical_feedback_id"] = canonical
            if action == "accept":
                submitted = row["submitted_snapshot_json"]
                assert isinstance(submitted, dict)
                snapshot = {"schema_version": PUBLICATION_SCHEMA, "public_content": submitted["public_content"],
                            "redactions": submitted["redactions"]}
                snapshot_hash = _hash(snapshot)
                publication_id, event_id = _new_id("feedback_publication"), _new_id("feedback_outbox")
                execute(connection, """INSERT INTO product_feedback_publications
                    (publication_id,feedback_id,schema_version,snapshot_json,snapshot_hash,created_by,created_at)
                    VALUES (:publication,:feedback,:schema,:snapshot,:hash,:actor,:now)""",
                    {"publication": publication_id, "feedback": identity, "schema": PUBLICATION_SCHEMA,
                     "snapshot": snapshot, "hash": snapshot_hash, "actor": trusted_actor, "now": now})
                execute(connection, """INSERT INTO product_feedback_outbox
                    (event_id,feedback_id,publication_id,schema_version,snapshot_hash,destination_key,state,attempt,
                     next_attempt_at,lease_fence,created_at,updated_at)
                    VALUES (:event,:feedback,:publication,:schema,:hash,:destination,'queued',0,:now,0,:now,:now)""",
                    {"event": event_id, "feedback": identity, "publication": publication_id, "schema": OUTBOX_SCHEMA,
                     "hash": snapshot_hash, "destination": DESTINATION_KEY, "now": now})
                detail = {"publication_id": publication_id, "outbox_event_id": event_id, "snapshot_hash": snapshot_hash}
            self._audit(connection, row=row, action=action, actor=trusted_actor, role="moderator", from_status=expected_from,
                        to_status=target, rationale=rationale, detail=detail, now=now)
            result = {"feedback": self._moderator_projection(row)}
            self._record_command(connection, scope="platform-feedback", actor=trusted_actor, operation=operation, key=key,
                                 request_hash=request_hash, result=result, now=now)
            return result

    def outbox_summary(self, *, actor_role: str) -> dict[str, object]:
        self._require_moderator(actor_role)
        row = self._fetch_one("SELECT COUNT(*) AS queued FROM product_feedback_outbox WHERE state='queued'")
        return {"schema_version": "feedback-publisher-status.v1", "configured": False,
                "status": "unconfigured", "repository": None, "credential_kind": None,
                "queue": {"queued": int(row["queued"] if row else 0)}, "last_error_category": None}
