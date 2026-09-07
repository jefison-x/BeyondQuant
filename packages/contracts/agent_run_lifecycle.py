"""BYQ-only correlation of a domain registration to its observed runtime turn."""

from __future__ import annotations

import hashlib
import json
import re


def registration_fingerprint(owner: str, workspace: str, actor: str, trace: str,
                             session: str, generation: str, key: str) -> str:
    values = [owner, workspace, actor, trace, session, generation, key]
    if any(not isinstance(value, str) or not value.strip() or len(value.strip()) > 128 for value in values):
        raise ValueError("invalid runtime registration context")
    encoded = json.dumps(["agent-run-registration.v1", *[value.strip() for value in values]],
                         ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_lifecycle_event(value: object) -> dict:
    if not isinstance(value, dict) or set(value) - {
        "schema_version", "root_run_id", "sequence", "outcome", "registration_fingerprint",
    }:
        raise ValueError("invalid runtime lifecycle event")
    if value.get("schema_version") != "agent-run-lifecycle.v1":
        raise ValueError("unsupported runtime lifecycle schema")
    root = value.get("root_run_id")
    if not isinstance(root, str) or re.fullmatch(r"[0-9a-f]{32}", root) is None:
        raise ValueError("invalid exact root run identity")
    sequence = value.get("sequence")
    if type(sequence) is not int or not 1 <= sequence <= 2**63 - 1:
        raise ValueError("invalid runtime lifecycle sequence")
    outcome = value.get("outcome")
    if not isinstance(outcome, str) or outcome not in {"active", "completed", "failed", "cancelled", "interrupted"}:
        raise ValueError("invalid runtime lifecycle outcome")
    fingerprint = value.get("registration_fingerprint")
    if outcome == "active":
        if not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
            raise ValueError("registration requires an exact fingerprint")
    elif "registration_fingerprint" in value:
        raise ValueError("terminal events cannot register a new agent")
    return dict(value)
