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
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, execute, fetch_one


SCHEMA_VERSION = "product-feedback.v1"
PREVIEW_SCHEMA = "feedback-publication-preview.v1"
PUBLICATION_SCHEMA = "feedback-publication.v1"
OUTBOX_SCHEMA = "feedback-outbox.v1"
HUB_DELIVERY_SCHEMA = "feedback-hub-delivery.v1"
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
MAX_PUBLICATION_ATTEMPTS = 6
MAX_HUB_DELIVERY_ATTEMPTS = 8
PUBLISHER_ERROR_CATEGORIES = (
    "transport_ambiguous", "rate_limited", "provider_unavailable",
    "authentication_failed", "permission_denied", "repository_unavailable",
    "issues_disabled", "validation_rejected", "reconciliation_conflict",
)
TERMINAL_PUBLISHER_ERRORS = {
    "authentication_failed", "permission_denied", "repository_unavailable",
    "issues_disabled", "validation_rejected", "reconciliation_conflict",
}
_DEFAULT_HUB_INSTALLATION_ID = f"byq-installation-{uuid.uuid4().hex}"

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
        "ALTER TABLE product_feedback DROP CONSTRAINT IF EXISTS product_feedback_publication_status_check",
        """ALTER TABLE product_feedback ADD CONSTRAINT product_feedback_publication_status_check
            CHECK (publication_status IN ('not_queued','publisher_unconfigured','queued','publishing','retry_wait','published','failed_terminal'))""",
        "ALTER TABLE product_feedback_outbox DROP CONSTRAINT IF EXISTS product_feedback_outbox_state_check",
        """ALTER TABLE product_feedback_outbox ADD CONSTRAINT product_feedback_outbox_state_check
            CHECK (state IN ('queued','publishing','retry_wait','published','failed_terminal'))""",
        "ALTER TABLE product_feedback_publications ADD COLUMN IF NOT EXISTS github_repository TEXT",
        "ALTER TABLE product_feedback_publications ADD COLUMN IF NOT EXISTS github_issue_number INTEGER",
        "ALTER TABLE product_feedback_publications ADD COLUMN IF NOT EXISTS github_html_url TEXT",
        "ALTER TABLE product_feedback_publications ADD COLUMN IF NOT EXISTS provider_identity TEXT",
        "ALTER TABLE product_feedback_publications ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ",
        """
        CREATE TABLE IF NOT EXISTS product_feedback_publisher_state (
            destination_key TEXT PRIMARY KEY CHECK (destination_key = 'github_primary'),
            configured BOOLEAN NOT NULL,
            credential_kind TEXT CHECK (credential_kind IN ('github_app','fine_grained_token')),
            repository TEXT,
            worker_version TEXT NOT NULL,
            last_heartbeat_at TIMESTAMPTZ NOT NULL,
            last_success_at TIMESTAMPTZ,
            last_error_category TEXT
        )
        """,
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
        """
        CREATE TABLE IF NOT EXISTS product_feedback_hub_state (
            state_key TEXT PRIMARY KEY CHECK (state_key = 'central'),
            installation_id TEXT NOT NULL UNIQUE,
            configured BOOLEAN NOT NULL DEFAULT FALSE,
            hub_origin TEXT,
            worker_version TEXT,
            last_heartbeat_at TIMESTAMPTZ,
            last_success_at TIMESTAMPTZ,
            last_error_category TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS product_feedback_hub_outbox (
            event_id TEXT PRIMARY KEY,
            feedback_id TEXT NOT NULL UNIQUE REFERENCES product_feedback(feedback_id),
            schema_version TEXT NOT NULL CHECK (schema_version = 'feedback-hub-delivery.v1'),
            snapshot_json JSONB NOT NULL,
            snapshot_hash TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('queued','delivering','retry_wait','received','triaged','accepted','rejected','duplicate','publishing','published','failed_terminal','cancelled')),
            attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
            next_attempt_at TIMESTAMPTZ NOT NULL,
            lease_owner TEXT,
            lease_expires_at TIMESTAMPTZ,
            lease_fence INTEGER NOT NULL DEFAULT 0 CHECK (lease_fence >= 0),
            receipt_id TEXT,
            status_token TEXT,
            github_repository TEXT,
            github_issue_number INTEGER,
            github_html_url TEXT,
            last_error_category TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS product_feedback_hub_outbox_due ON product_feedback_hub_outbox(state,next_attempt_at,event_id)",
        f"""INSERT INTO product_feedback_hub_state (state_key,installation_id,configured)
            VALUES ('central','{_DEFAULT_HUB_INSTALLATION_ID}',FALSE) ON CONFLICT(state_key) DO NOTHING""",
    ]

    def __init__(self, database_url: str | None = None) -> None:
        self.product_version = os.environ.get("BYQ_PRODUCT_VERSION", "0.1.0")
        self.deployment_kind = os.environ.get("BYQ_DEPLOYMENT_KIND", "self_hosted")
        try:
            super().__init__(database_url)
        except SQLAlchemyError as exc:
            raise FeedbackPersistenceError("feedback storage is unavailable") from exc

    @staticmethod
    def options(*, publisher_configured: bool = False, publisher_status: str | None = None) -> dict[str, object]:
        return {
            "schema_version": "product-feedback-options.v1",
            "categories": list(CATEGORIES), "components": list(COMPONENTS), "severities": list(SEVERITIES),
            "limits": {"title": 160, "description": 8000, "steps": MAX_STEPS, "request_bytes": MAX_REQUEST_BYTES},
            "privacy": {
                "preview_required": True, "explicit_confirmation_required": True,
                "attachments_supported": False, "security_reports_public": False,
                "normal_user_github_configuration": False,
            },
            "publisher": {"configured": publisher_configured,
                          "status": publisher_status or ("ready" if publisher_configured else "unconfigured")},
        }

    def public_options(self) -> dict[str, object]:
        state = self._fetch_one("""SELECT configured,last_heartbeat_at FROM product_feedback_publisher_state
            WHERE destination_key=:destination""", {"destination": DESTINATION_KEY})
        configured = bool(state and state["configured"])
        fresh = self._publisher_fresh(state)
        result = self.options(publisher_configured=configured,
                              publisher_status="ready" if configured and fresh else "stale" if configured else "unconfigured")
        hub = self._fetch_one("SELECT configured,last_heartbeat_at FROM product_feedback_hub_state WHERE state_key='central'")
        hub_fresh = self._publisher_fresh(hub)
        result["central_hub"] = {
            "configured": bool(hub and hub["configured"]),
            "status": "ready" if hub and hub["configured"] and hub_fresh else "stale" if hub and hub["configured"] else "unconfigured",
        }
        return result

    @staticmethod
    def _publisher_fresh(state: dict[str, object] | None) -> bool:
        if not state or not state.get("last_heartbeat_at"):
            return False
        try:
            heartbeat = datetime.fromisoformat(str(state["last_heartbeat_at"]))
        except ValueError:
            return False
        return heartbeat >= datetime.now(timezone.utc) - timedelta(seconds=120)

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
        hub_state = row.get("hub_delivery_state")
        hub_issue = (
            {"repository": row["hub_github_repository"], "issue_number": row["hub_github_issue_number"],
             "html_url": row["hub_github_html_url"]}
            if hub_state == "published" and row.get("hub_github_issue_number") else None
        )
        result: dict[str, object] = {
            "schema_version": SCHEMA_VERSION, "feedback_id": row["feedback_id"], "status": row["status"],
            "category": row["category"], "component": row["component"], "severity": row["severity"],
            "title": row["title"], "version": row["version"], "current_revision": row["current_revision"],
            "publication_status": row["publication_status"], "github_issue": hub_issue or (
                {"repository": row["github_repository"], "issue_number": row["github_issue_number"],
                 "html_url": row["github_html_url"]}
                if row.get("publication_status") == "published" and row.get("github_issue_number") else None
            ),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }
        result["central_hub"] = (
            {"status": hub_state, "receipt_id": row.get("hub_receipt_id"), "last_error_category": row.get("hub_last_error_category")}
            if hub_state else None
        )
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
            "github_issue": ({"repository": row["github_repository"], "issue_number": row["github_issue_number"],
                              "html_url": row["github_html_url"]}
                             if row.get("publication_status") == "published" and row.get("github_issue_number") else None),
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
        joined_where = where.replace("workspace_id", "f.workspace_id").replace("status=:status", "f.status=:status").replace(
            "category=:category", "f.category=:category").replace("(title ILIKE", "(f.title ILIKE").replace(
            "OR component ILIKE", "OR f.component ILIKE")
        rows = self._execute(f"""SELECT f.*,p.github_repository,p.github_issue_number,p.github_html_url,
            h.state AS hub_delivery_state,h.receipt_id AS hub_receipt_id,h.last_error_category AS hub_last_error_category,
            h.github_repository AS hub_github_repository,h.github_issue_number AS hub_github_issue_number,
            h.github_html_url AS hub_github_html_url
            FROM product_feedback f LEFT JOIN product_feedback_publications p ON p.feedback_id=f.feedback_id
            LEFT JOIN product_feedback_hub_outbox h ON h.feedback_id=f.feedback_id
            WHERE {joined_where} ORDER BY f.updated_at DESC,f.feedback_id DESC LIMIT :limit OFFSET :offset""", params)
        total = int(count["count"] if count else 0)
        return {"schema_version": "product-feedback-catalog.v1", "items": [self._owner_projection(row) for row in rows],
                "total": total, "limit": limit, "offset": offset, "has_more": offset + len(rows) < total}

    def get_owner(self, feedback_id: object, *, trusted_workspace: str) -> dict[str, object]:
        identity = _feedback_id(feedback_id)
        row = self._fetch_one("""SELECT f.*,p.github_repository,p.github_issue_number,p.github_html_url,
            h.state AS hub_delivery_state,h.receipt_id AS hub_receipt_id,h.last_error_category AS hub_last_error_category,
            h.github_repository AS hub_github_repository,h.github_issue_number AS hub_github_issue_number,
            h.github_html_url AS hub_github_html_url
            FROM product_feedback f LEFT JOIN product_feedback_publications p ON p.feedback_id=f.feedback_id
            LEFT JOIN product_feedback_hub_outbox h ON h.feedback_id=f.feedback_id
            WHERE f.feedback_id=:feedback AND f.workspace_id=:workspace""",
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
            hub_event_id = _new_id("feedback_hub_event")
            execute(connection, """UPDATE product_feedback SET status='submitted',submitted_snapshot_json=:snapshot,
                submitted_snapshot_hash=:hash,version=version+1,updated_at=:now WHERE feedback_id=:feedback""",
                {"snapshot": snapshot, "hash": snapshot_hash, "now": now, "feedback": identity})
            execute(connection, """INSERT INTO product_feedback_hub_outbox
                (event_id,feedback_id,schema_version,snapshot_json,snapshot_hash,state,attempt,next_attempt_at,
                 lease_fence,created_at,updated_at)
                VALUES (:event,:feedback,:schema,:snapshot,:hash,'queued',0,:now,0,:now,:now)""",
                {"event": hub_event_id, "feedback": identity, "schema": HUB_DELIVERY_SCHEMA,
                 "snapshot": snapshot, "hash": snapshot_hash, "now": now})
            row = fetch_one(connection, "SELECT * FROM product_feedback WHERE feedback_id=:feedback", {"feedback": identity})
            assert row is not None
            row["hub_delivery_state"] = "queued"
            row["hub_receipt_id"] = None
            row["hub_last_error_category"] = None
            self._audit(connection, row=row, action="submit", actor=trusted_actor, role="owner", from_status="draft",
                        to_status="submitted", detail={"snapshot_hash": snapshot_hash, "hub_event_id": hub_event_id}, now=now)
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
            if target == "withdrawn":
                execute(connection, """UPDATE product_feedback_hub_outbox SET state='cancelled',updated_at=:now
                    WHERE feedback_id=:feedback AND state IN ('queued','retry_wait')""",
                    {"now": now, "feedback": identity})
            row = fetch_one(connection, "SELECT * FROM product_feedback WHERE feedback_id=:feedback", {"feedback": identity})
            assert row is not None
            self._audit(connection, row=row, action=action, actor=trusted_actor, role="owner", from_status=allowed_from,
                        to_status=target, now=now)
            result = {"feedback": self._owner_projection(row)}
            self._record_command(connection, scope=trusted_workspace, actor=trusted_actor, operation=operation, key=key,
                                 request_hash=request_hash, result=result, now=now)
            return result

    @staticmethod
    def _hub_origin(value: object) -> str:
        if not isinstance(value, str) or len(value) > 240:
            raise ValueError("central feedback hub origin is invalid")
        normalized = value.rstrip("/")
        allow_http = os.environ.get("BYQ_FEEDBACK_HUB_ALLOW_HTTP") == "1"
        if not normalized.startswith("https://") and not (allow_http and normalized.startswith("http://")):
            raise ValueError("central feedback hub must use HTTPS")
        return normalized

    def hub_relay_heartbeat(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("feedback hub relay heartbeat must be an object")
        _reject_unknown(payload, {"configured", "hub_origin", "worker_version"})
        configured = payload.get("configured")
        if not isinstance(configured, bool):
            raise ValueError("feedback hub relay configured must be a boolean")
        origin = self._hub_origin(payload.get("hub_origin")) if configured else None
        worker_version = _text(payload.get("worker_version"), field="worker_version", minimum=1, maximum=40)
        now = _now()
        self._execute("""UPDATE product_feedback_hub_state SET configured=:configured,hub_origin=:origin,
            worker_version=:version,last_heartbeat_at=:now WHERE state_key='central'""",
            {"configured": configured, "origin": origin, "version": worker_version, "now": now})
        return {"schema_version": "feedback-hub-relay-heartbeat.v1", "accepted": True, "configured": configured}

    def claim_hub_deliveries(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("feedback hub delivery claim must be an object")
        _reject_unknown(payload, {"worker_id", "limit", "lease_seconds"})
        worker = _text(payload.get("worker_id"), field="worker_id", minimum=3, maximum=80)
        limit = min(_positive_int(payload.get("limit", 5), field="limit"), 10)
        lease_seconds = min(max(_positive_int(payload.get("lease_seconds", 60), field="lease_seconds"), 15), 300)
        now_dt = datetime.now(timezone.utc)
        now, expiry = now_dt.isoformat(), (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        with self._transaction() as connection:
            state = fetch_one(connection, "SELECT * FROM product_feedback_hub_state WHERE state_key='central'")
            if state is None or not state["configured"]:
                return {"schema_version": "feedback-hub-relay-claim.v1", "events": []}
            rows = execute(connection, """SELECT h.* FROM product_feedback_hub_outbox h
                JOIN product_feedback f ON f.feedback_id=h.feedback_id
                WHERE f.status IN ('submitted','triaged','accepted') AND
                (((h.state IN ('queued','retry_wait')) AND h.next_attempt_at <= :now)
                 OR (h.state='delivering' AND h.lease_expires_at < :now))
                ORDER BY h.next_attempt_at,h.event_id FOR UPDATE OF h SKIP LOCKED LIMIT :limit""",
                {"now": now, "limit": limit})
            events: list[dict[str, object]] = []
            for row in rows:
                attempt, fence = int(row["attempt"]) + 1, int(row["lease_fence"]) + 1
                execute(connection, """UPDATE product_feedback_hub_outbox SET state='delivering',attempt=:attempt,
                    lease_owner=:worker,lease_expires_at=:expiry,lease_fence=:fence,updated_at=:now WHERE event_id=:event""",
                    {"attempt": attempt, "worker": worker, "expiry": expiry, "fence": fence, "now": now, "event": row["event_id"]})
                events.append({
                    "event_id": row["event_id"], "installation_id": state["installation_id"],
                    "snapshot_hash": row["snapshot_hash"], "snapshot": row["snapshot_json"],
                    "attempt": attempt, "lease_fence": fence, "lease_expires_at": expiry,
                })
        return {"schema_version": "feedback-hub-relay-claim.v1", "events": events}

    @staticmethod
    def _hub_leased_row(connection: Any, event_id: str, worker: str, fence: int) -> dict[str, object]:
        row = fetch_one(connection, "SELECT * FROM product_feedback_hub_outbox WHERE event_id=:event FOR UPDATE", {"event": event_id})
        if row is None:
            raise FeedbackNotFound("feedback hub delivery not found")
        if row["state"] != "delivering" or row["lease_owner"] != worker or int(row["lease_fence"]) != fence:
            raise FeedbackConflict("feedback hub delivery lease is stale")
        return row

    def complete_hub_delivery(self, event_id: object, payload: object) -> dict[str, object]:
        if not isinstance(event_id, str) or re.fullmatch(r"feedback_hub_event_[0-9a-f]{32}", event_id) is None:
            raise ValueError("feedback hub event id is invalid")
        if not isinstance(payload, dict):
            raise ValueError("feedback hub delivery completion must be an object")
        _reject_unknown(payload, {"worker_id", "lease_fence", "receipt_id", "status_token"})
        worker = _text(payload.get("worker_id"), field="worker_id", minimum=3, maximum=80)
        fence = _positive_int(payload.get("lease_fence"), field="lease_fence")
        receipt = _text(payload.get("receipt_id"), field="receipt_id", minimum=20, maximum=96)
        token = _text(payload.get("status_token"), field="status_token", minimum=32, maximum=256)
        now = _now()
        with self._transaction() as connection:
            row = self._hub_leased_row(connection, event_id, worker, fence)
            execute(connection, """UPDATE product_feedback_hub_outbox SET state='received',receipt_id=:receipt,
                status_token=:token,lease_owner=NULL,lease_expires_at=NULL,last_error_category=NULL,updated_at=:now
                WHERE event_id=:event""", {"receipt": receipt, "token": token, "now": now, "event": event_id})
            execute(connection, """UPDATE product_feedback_hub_state SET last_success_at=:now,last_error_category=NULL
                WHERE state_key='central'""", {"now": now})
        return {"schema_version": "feedback-hub-relay-result.v1", "status": "received", "receipt_id": receipt}

    def retry_hub_delivery(self, event_id: object, payload: object) -> dict[str, object]:
        if not isinstance(event_id, str) or re.fullmatch(r"feedback_hub_event_[0-9a-f]{32}", event_id) is None:
            raise ValueError("feedback hub event id is invalid")
        if not isinstance(payload, dict):
            raise ValueError("feedback hub delivery retry must be an object")
        _reject_unknown(payload, {"worker_id", "lease_fence", "error_category", "retry_after_seconds"})
        worker = _text(payload.get("worker_id"), field="worker_id", minimum=3, maximum=80)
        fence = _positive_int(payload.get("lease_fence"), field="lease_fence")
        category = _text(payload.get("error_category"), field="error_category", minimum=1, maximum=64)
        retry_after = min(max(_positive_int(payload.get("retry_after_seconds", 30), field="retry_after_seconds"), 5), 3600)
        now_dt = datetime.now(timezone.utc); now = now_dt.isoformat()
        with self._transaction() as connection:
            row = self._hub_leased_row(connection, event_id, worker, fence)
            terminal = int(row["attempt"]) >= MAX_HUB_DELIVERY_ATTEMPTS or category in {"validation_rejected", "authentication_failed"}
            target = "failed_terminal" if terminal else "retry_wait"
            execute(connection, """UPDATE product_feedback_hub_outbox SET state=:state,next_attempt_at=:next,
                lease_owner=NULL,lease_expires_at=NULL,last_error_category=:category,updated_at=:now WHERE event_id=:event""",
                {"state": target, "next": (now_dt + timedelta(seconds=retry_after)).isoformat(),
                 "category": category, "now": now, "event": event_id})
            execute(connection, "UPDATE product_feedback_hub_state SET last_error_category=:category WHERE state_key='central'",
                    {"category": category})
        return {"schema_version": "feedback-hub-relay-result.v1", "status": target, "attempt": int(row["attempt"])}

    def hub_status_candidates(self, *, limit: int = 10) -> dict[str, object]:
        bounded = min(max(limit, 1), 20)
        rows = self._execute("""SELECT event_id,receipt_id,status_token FROM product_feedback_hub_outbox
            WHERE state IN ('received','triaged','accepted','publishing') AND receipt_id IS NOT NULL
            ORDER BY updated_at,event_id LIMIT :limit""", {"limit": bounded})
        return {"schema_version": "feedback-hub-status-candidates.v1", "items": rows}

    def update_hub_status(self, event_id: object, payload: object) -> dict[str, object]:
        if not isinstance(event_id, str) or re.fullmatch(r"feedback_hub_event_[0-9a-f]{32}", event_id) is None:
            raise ValueError("feedback hub event id is invalid")
        if not isinstance(payload, dict):
            raise ValueError("feedback hub status must be an object")
        _reject_unknown(payload, {"schema_version", "receipt_id", "status", "github_issue"})
        if payload.get("schema_version") != "central-feedback-status.v1":
            raise ValueError("feedback hub status schema is invalid")
        status = _enum(payload.get("status"), field="status", allowed=("received","triaged","accepted","rejected","duplicate","publishing","published"))
        receipt = _text(payload.get("receipt_id"), field="receipt_id", minimum=20, maximum=96)
        issue = payload.get("github_issue")
        repository = number = url = None
        if status == "published":
            if not isinstance(issue, dict):
                raise ValueError("published feedback hub status requires github_issue")
            repository = self._publisher_repository(issue.get("repository"))
            number = _positive_int(issue.get("issue_number"), field="issue_number")
            url = f"https://github.com/{repository}/issues/{number}"
            if issue.get("html_url") != url:
                raise ValueError("feedback hub GitHub URL is not canonical")
        now = _now()
        with self._transaction() as connection:
            row = fetch_one(connection, "SELECT receipt_id FROM product_feedback_hub_outbox WHERE event_id=:event FOR UPDATE", {"event": event_id})
            if row is None or row["receipt_id"] != receipt:
                raise FeedbackConflict("feedback hub receipt does not match delivery")
            execute(connection, """UPDATE product_feedback_hub_outbox SET state=:status,github_repository=:repository,
                github_issue_number=:number,github_html_url=:url,updated_at=:now WHERE event_id=:event""",
                {"status": status, "repository": repository, "number": number, "url": url, "now": now, "event": event_id})
        return {"schema_version": "feedback-hub-status-result.v1", "status": status}

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
        joined_where = where.replace("status ", "f.status ").replace("status=", "f.status=").replace(
            "submitted_snapshot_json", "f.submitted_snapshot_json").replace("category=:category", "f.category=:category").replace(
            "(title ILIKE", "(f.title ILIKE").replace("OR component ILIKE", "OR f.component ILIKE")
        rows = self._execute(f"""SELECT f.*,p.github_repository,p.github_issue_number,p.github_html_url
            FROM product_feedback f LEFT JOIN product_feedback_publications p ON p.feedback_id=f.feedback_id
            WHERE {joined_where} ORDER BY f.updated_at,f.feedback_id LIMIT :limit OFFSET :offset""", params)
        total = int(count["count"] if count else 0)
        return {"schema_version": "feedback-moderation-catalog.v1", "items": [self._moderator_projection(row) for row in rows],
                "total": total, "limit": limit, "offset": offset, "has_more": offset + len(rows) < total}

    def get_moderation(self, feedback_id: object, *, actor_role: str) -> dict[str, object]:
        self._require_moderator(actor_role)
        identity = _feedback_id(feedback_id)
        row = self._fetch_one("""SELECT f.*,p.github_repository,p.github_issue_number,p.github_html_url
            FROM product_feedback f LEFT JOIN product_feedback_publications p ON p.feedback_id=f.feedback_id
            WHERE f.feedback_id=:feedback AND f.status <> 'draft'""",
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
        queue_rows = self._execute("""SELECT state,COUNT(*) AS count FROM product_feedback_outbox
            GROUP BY state ORDER BY state""")
        queue = {state: 0 for state in ("queued", "publishing", "retry_wait", "published", "failed_terminal")}
        for row in queue_rows:
            queue[str(row["state"])] = int(row["count"])
        state = self._fetch_one("SELECT * FROM product_feedback_publisher_state WHERE destination_key=:destination",
                                {"destination": DESTINATION_KEY})
        configured = bool(state and state["configured"])
        fresh = self._publisher_fresh(state)
        return {"schema_version": "feedback-publisher-status.v1", "configured": configured,
                "status": "ready" if configured and fresh else "stale" if configured else "unconfigured",
                "repository": state["repository"] if configured and state else None,
                "credential_kind": state["credential_kind"] if configured and state else None,
                "queue": queue, "last_error_category": state["last_error_category"] if state else None,
                "last_heartbeat_at": state["last_heartbeat_at"] if state else None,
                "last_success_at": state["last_success_at"] if state else None}

    @staticmethod
    def _publisher_repository(value: object) -> str:
        if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", value) is None:
            raise ValueError("publisher repository is invalid")
        return value

    @staticmethod
    def _publisher_kind(value: object) -> str:
        if value not in {"github_app", "fine_grained_token"}:
            raise ValueError("publisher credential kind is invalid")
        return str(value)

    def publisher_heartbeat(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("publisher heartbeat must be an object")
        _reject_unknown(payload, {"configured", "credential_kind", "repository", "worker_version"})
        configured = payload.get("configured")
        if not isinstance(configured, bool):
            raise ValueError("publisher configured must be a boolean")
        repository = self._publisher_repository(payload.get("repository")) if configured else None
        credential_kind = self._publisher_kind(payload.get("credential_kind")) if configured else None
        worker_version = _text(payload.get("worker_version"), field="worker_version", minimum=1, maximum=40)
        now = _now()
        with self._transaction() as connection:
            execute(connection, """INSERT INTO product_feedback_publisher_state
                (destination_key,configured,credential_kind,repository,worker_version,last_heartbeat_at)
                VALUES (:destination,:configured,:kind,:repository,:version,:now)
                ON CONFLICT(destination_key) DO UPDATE SET configured=EXCLUDED.configured,
                credential_kind=EXCLUDED.credential_kind,repository=EXCLUDED.repository,
                worker_version=EXCLUDED.worker_version,last_heartbeat_at=EXCLUDED.last_heartbeat_at""",
                {"destination": DESTINATION_KEY, "configured": configured, "kind": credential_kind,
                 "repository": repository, "version": worker_version, "now": now})
            execute(connection, """UPDATE product_feedback f SET publication_status=:status,updated_at=:now
                FROM product_feedback_outbox o WHERE o.feedback_id=f.feedback_id AND o.state='queued'
                AND f.publication_status IN ('publisher_unconfigured','queued')""",
                {"status": "queued" if configured else "publisher_unconfigured", "now": now})
        return {"schema_version": "feedback-publisher-heartbeat.v1", "accepted": True, "configured": configured}

    def claim_publications(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("publisher claim must be an object")
        _reject_unknown(payload, {"worker_id", "limit", "lease_seconds"})
        worker = _text(payload.get("worker_id"), field="worker_id", minimum=3, maximum=80)
        limit = min(_positive_int(payload.get("limit", 5), field="limit"), 10)
        lease_seconds = min(max(_positive_int(payload.get("lease_seconds", 60), field="lease_seconds"), 15), 300)
        now_dt = datetime.now(timezone.utc)
        now, expiry = now_dt.isoformat(), (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        with self._transaction() as connection:
            publisher = fetch_one(connection, """SELECT configured FROM product_feedback_publisher_state
                WHERE destination_key=:destination""", {"destination": DESTINATION_KEY})
            if publisher is None or not publisher["configured"]:
                return {"schema_version": "feedback-publisher-claim.v1", "events": []}
            rows = execute(connection, """SELECT o.*,p.snapshot_json FROM product_feedback_outbox o
                JOIN product_feedback_publications p ON p.publication_id=o.publication_id
                WHERE ((o.state IN ('queued','retry_wait') AND o.next_attempt_at <= :now)
                    OR (o.state='publishing' AND o.lease_expires_at < :now))
                ORDER BY o.next_attempt_at,o.event_id FOR UPDATE OF o SKIP LOCKED LIMIT :limit""",
                {"now": now, "limit": limit})
            events: list[dict[str, object]] = []
            for row in rows:
                fence = int(row["lease_fence"]) + 1
                attempt = int(row["attempt"]) + 1
                execute(connection, """UPDATE product_feedback_outbox SET state='publishing',attempt=:attempt,
                    lease_owner=:worker,lease_expires_at=:expiry,lease_fence=:fence,updated_at=:now
                    WHERE event_id=:event""", {"attempt": attempt, "worker": worker, "expiry": expiry,
                    "fence": fence, "now": now, "event": row["event_id"]})
                execute(connection, "UPDATE product_feedback SET publication_status='publishing',updated_at=:now WHERE feedback_id=:feedback",
                        {"now": now, "feedback": row["feedback_id"]})
                events.append({"event_id": row["event_id"], "feedback_id": row["feedback_id"],
                    "publication_id": row["publication_id"], "snapshot_hash": row["snapshot_hash"],
                    "snapshot": row["snapshot_json"], "attempt": attempt, "lease_fence": fence,
                    "lease_expires_at": expiry})
        return {"schema_version": "feedback-publisher-claim.v1", "events": events}

    @staticmethod
    def _leased_row(connection: Any, event_id: str, worker: str, fence: int) -> dict[str, object]:
        row = fetch_one(connection, """SELECT * FROM product_feedback_outbox WHERE event_id=:event FOR UPDATE""",
                        {"event": event_id})
        if row is None:
            raise FeedbackNotFound("publication event not found")
        if row["state"] != "publishing" or row["lease_owner"] != worker or int(row["lease_fence"]) != fence:
            raise FeedbackConflict("publication lease is stale")
        return row

    def complete_publication(self, event_id: object, payload: object) -> dict[str, object]:
        if not isinstance(event_id, str) or re.fullmatch(r"feedback_outbox_[0-9a-f]{32}", event_id) is None:
            raise ValueError("publication event id is invalid")
        if not isinstance(payload, dict):
            raise ValueError("publisher completion must be an object")
        _reject_unknown(payload, {"worker_id", "lease_fence", "repository", "issue_number", "html_url", "provider_identity"})
        worker = _text(payload.get("worker_id"), field="worker_id", minimum=3, maximum=80)
        fence = _positive_int(payload.get("lease_fence"), field="lease_fence")
        repository = self._publisher_repository(payload.get("repository"))
        issue_number = _positive_int(payload.get("issue_number"), field="issue_number")
        expected_url = f"https://github.com/{repository}/issues/{issue_number}"
        if payload.get("html_url") != expected_url:
            raise ValueError("publisher issue URL is not canonical")
        provider_identity = _text(payload.get("provider_identity"), field="provider_identity", minimum=1, maximum=120)
        now = _now()
        with self._transaction() as connection:
            state = fetch_one(connection, "SELECT * FROM product_feedback_publisher_state WHERE destination_key=:destination",
                              {"destination": DESTINATION_KEY})
            if state is None or not state["configured"] or state["repository"] != repository:
                raise FeedbackConflict("publisher destination is not registered")
            row = self._leased_row(connection, event_id, worker, fence)
            execute(connection, """UPDATE product_feedback_publications SET github_repository=:repository,
                github_issue_number=:number,github_html_url=:url,provider_identity=:provider,published_at=:now
                WHERE publication_id=:publication""", {"repository": repository, "number": issue_number,
                "url": expected_url, "provider": provider_identity, "now": now, "publication": row["publication_id"]})
            execute(connection, """UPDATE product_feedback_outbox SET state='published',lease_owner=NULL,
                lease_expires_at=NULL,last_error_category=NULL,updated_at=:now WHERE event_id=:event""",
                {"now": now, "event": event_id})
            execute(connection, """UPDATE product_feedback SET publication_status='published',updated_at=:now
                WHERE feedback_id=:feedback""", {"now": now, "feedback": row["feedback_id"]})
            execute(connection, """UPDATE product_feedback_publisher_state SET last_success_at=:now,
                last_error_category=NULL WHERE destination_key=:destination""", {"now": now, "destination": DESTINATION_KEY})
        return {"schema_version": "feedback-publisher-result.v1", "status": "published",
                "issue_number": issue_number, "html_url": expected_url}

    def retry_publication(self, event_id: object, payload: object) -> dict[str, object]:
        if not isinstance(event_id, str) or re.fullmatch(r"feedback_outbox_[0-9a-f]{32}", event_id) is None:
            raise ValueError("publication event id is invalid")
        if not isinstance(payload, dict):
            raise ValueError("publisher retry must be an object")
        _reject_unknown(payload, {"worker_id", "lease_fence", "error_category", "retry_after_seconds"})
        worker = _text(payload.get("worker_id"), field="worker_id", minimum=3, maximum=80)
        fence = _positive_int(payload.get("lease_fence"), field="lease_fence")
        category = _enum(payload.get("error_category"), field="error_category", allowed=PUBLISHER_ERROR_CATEGORIES)
        retry_after = min(max(_positive_int(payload.get("retry_after_seconds", 30), field="retry_after_seconds"), 5), 3600)
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        with self._transaction() as connection:
            row = self._leased_row(connection, event_id, worker, fence)
            terminal = category in TERMINAL_PUBLISHER_ERRORS or int(row["attempt"]) >= MAX_PUBLICATION_ATTEMPTS
            target = "failed_terminal" if terminal else "retry_wait"
            next_attempt = (now_dt + timedelta(seconds=retry_after)).isoformat()
            execute(connection, """UPDATE product_feedback_outbox SET state=:state,next_attempt_at=:next,
                lease_owner=NULL,lease_expires_at=NULL,last_error_category=:category,updated_at=:now
                WHERE event_id=:event""", {"state": target, "next": next_attempt, "category": category,
                "now": now, "event": event_id})
            execute(connection, """UPDATE product_feedback SET publication_status=:state,updated_at=:now
                WHERE feedback_id=:feedback""", {"state": target, "now": now, "feedback": row["feedback_id"]})
            execute(connection, """UPDATE product_feedback_publisher_state SET last_error_category=:category
                WHERE destination_key=:destination""", {"category": category, "destination": DESTINATION_KEY})
        return {"schema_version": "feedback-publisher-result.v1", "status": target,
                "error_category": category, "attempt": int(row["attempt"])}
