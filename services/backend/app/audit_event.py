"""Structured BYQ audit observations; domain stores remain authoritative."""

from __future__ import annotations

import json
import logging
import math
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone


_LOGGER = logging.getLogger("byq.audit")
_SENSITIVE_KEY = re.compile(r"(?i)(secret|token|password|passwd|authorization|api[_-]?key|credential|cookie|private[_-]?key)")
_SECRET_VALUE = re.compile(
    r"(?i)\b(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"token|secret|password|passwd|private[_-]?key)(\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)|\b(Bearer)\s+[A-Za-z0-9._~+/-]+=*"
)
_MAX_METADATA_BYTES = 8192


def _sanitize(value: object, depth: int = 0) -> object:
    """Copy bounded JSON metadata while redacting secret-shaped content."""
    if depth > 8:
        raise ValueError("audit metadata is nested too deeply")
    if isinstance(value, Mapping):
        if len(value) > 128:
            raise ValueError("audit metadata has too many fields")
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 128:
                raise ValueError("audit metadata keys must be short strings")
            result[key] = "[REDACTED]" if _SENSITIVE_KEY.search(key) else _sanitize(item, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > 128:
            raise ValueError("audit metadata list is too long")
        return [_sanitize(item, depth + 1) for item in value]
    if isinstance(value, str):
        if len(value) > 4096:
            raise ValueError("audit metadata string is too long")
        return _SECRET_VALUE.sub(
            lambda match: f"{match.group(1) or match.group(3)}{match.group(2) or ' '}[REDACTED]",
            value,
        )
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("audit metadata must contain JSON values")


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Versioned structured observation; request_id is absent when unavailable."""

    workspace_id: str
    owner_principal: str
    actor_principal: str
    action: str
    resource_type: str
    resource_id: str
    result: str
    request_id: str | None = None
    job_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: f"audit_{uuid.uuid4().hex}")
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        for name in (
            "workspace_id", "owner_principal", "actor_principal", "action",
            "resource_type", "resource_id", "event_id", "occurred_at",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or len(value) > 256:
                raise ValueError(f"{name} is invalid")
        for name in ("request_id", "job_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value or len(value) > 256):
                raise ValueError(f"{name} is invalid")
        try:
            timestamp = datetime.fromisoformat(self.occurred_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("occurred_at must be an ISO-8601 timestamp") from error
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be an object")
        safe_metadata = _sanitize(self.metadata)
        serialized = json.dumps(safe_metadata, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > _MAX_METADATA_BYTES:
            raise ValueError("audit metadata is too large")
        object.__setattr__(self, "metadata", safe_metadata)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "audit-event.v1",
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "workspace_id": self.workspace_id,
            "owner_principal": self.owner_principal,
            "actor_principal": self.actor_principal,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "result": self.result,
            "request_id": self.request_id,
            "job_id": self.job_id,
            "metadata": _sanitize(self.metadata),
        }


AuditSink = Callable[[Mapping[str, object]], None]


def _log_sink(payload: Mapping[str, object]) -> None:
    _LOGGER.info("audit_event %s", json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


class AuditEmitter:
    """Small sink adapter; sink failures never become business failures."""

    def __init__(self, sink: AuditSink | None = None) -> None:
        self._sink = sink if sink is not None else _log_sink

    def emit(self, event: AuditEvent) -> bool:
        if not isinstance(event, AuditEvent):
            raise TypeError("event must be an AuditEvent")
        try:
            self._sink(event.to_dict())
        except Exception:
            _LOGGER.warning("audit event sink failed")
            return False
        return True
