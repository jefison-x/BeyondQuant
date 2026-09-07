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


def lifecycle_receipt(event: object) -> dict:
    event = validate_lifecycle_event(event)
    digest = hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"schema_version": "agent-run-lifecycle-receipt.v1", "sequence": event["sequence"],
            "root_run_id": event["root_run_id"], "event_sha256": digest}


def project_lifecycle_event(event: dict, session_id: str, trace_id: str) -> dict | None:
    if (event.get("session_id"), event.get("trace_id"), event.get("source")) != (session_id, trace_id, "runtime-adapter"):
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    kind = event.get("kind")
    outcomes = {"session.result": "completed", "session.failed": "failed",
                "session.cancelled": "cancelled", "session.closed": "interrupted"}
    if kind != "agent.run.registration" and kind not in outcomes:
        return None
    if "run_id" not in payload:  # idle close/startup failure has no exact turn
        return None
    value = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": payload["run_id"],
             "sequence": event.get("sequence"), "outcome": outcomes.get(kind, "active")}
    if kind == "agent.run.registration":
        if (set(payload) != {"schema_version", "run_id", "registration_fingerprint"}
                or payload.get("schema_version") != "agent-run-registration-observed.v1"):
            raise ValueError("invalid observed registration")
        value["registration_fingerprint"] = payload["registration_fingerprint"]
    return validate_lifecycle_event(value)
