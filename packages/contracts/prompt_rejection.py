"""Exact BYQ pre-admission rejection; not a generic classification of HTTP 5xx."""
from __future__ import annotations

import hashlib


def credential_rejection(session_id: str, key: str, content: str) -> dict:
    if (not isinstance(session_id, str) or not 1 <= len(session_id) <= 128
            or session_id.strip() != session_id or "/" in session_id
            or not isinstance(key, str) or not 8 <= len(key) <= 128 or key.strip() != key
            or not isinstance(content, str)):
        raise ValueError("exact prompt rejection identity required")
    return {"schema_version": "prompt-rejection.v1", "code": "model_credentials_unavailable",
            "accepted": False, "session_id": session_id, "idempotency_key": key,
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}


def matches_credential_rejection(value: object, session_id: str, key: str, content: str) -> bool:
    try:
        expected = credential_rejection(session_id, key, content)
    except ValueError:
        return False
    return isinstance(value, dict) and value.get("accepted") is False and value == expected
