"""ADR-0066 private evidence; never a WorkflowTrace or model-facing payload.

Both observer and domain writer hash the same bounded JSON representation.
This module proves no authority by itself: root ownership comes from the Adapter,
and admission additionally requires Backend registration/task/identity checks.
"""
from __future__ import annotations

import hashlib
import json
import math
import re


ACTIONS = frozenset({"byq_strategy_validate", "byq_ml_strategy_create", "byq_factor_compute", "byq_strategy_version_create"})
MAX_INPUT_BYTES = 256 * 1024
MAX_NODES = 8192
MAX_DEPTH = 24
MAX_SAFE_INTEGER = 2**53 - 1


def _text(value: object, maximum: int = 128) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= maximum
            or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("invalid private call identity")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("invalid private call identity") from exc
    return value


def _limits(action=None):
    # Factor snapshots contain bounded tabular rows, unlike strategy definitions.
    return (4 * 1024 * 1024, 131072) if action == "byq_factor_compute" else (MAX_INPUT_BYTES, MAX_NODES)


def _canonical(value: object, *, action=None) -> bytes:
    max_bytes, max_nodes = _limits(action)
    nodes = 0

    def visit(item, depth):
        nonlocal nodes
        nodes += 1
        if nodes > max_nodes or depth > MAX_DEPTH:
            raise ValueError("private call input exceeds structural bound")
        if item is None:
            return ["null"]
        if type(item) is bool:
            return ["bool", item]
        if type(item) in {int, float}:
            if (not math.isfinite(item) or abs(item) > MAX_SAFE_INTEGER):
                raise ValueError("private call number cannot be represented safely")
            # JS serializes 1.0 as 1 and -0 as 0. Preserve IEEE-754 value, not
            # incidental JSON spelling; bool is deliberately a different type.
            return ["number", float(item if item else 0).hex()]
        if isinstance(item, str):
            item.encode("utf-8")  # Reject unpaired surrogates, never replace.
            return ["string", item]
        if isinstance(item, list):
            return ["array", [visit(child, depth + 1) for child in item]]
        if isinstance(item, dict) and all(isinstance(key, str) for key in item):
            return ["object", [[visit(key, depth + 1), visit(item[key], depth + 1)] for key in sorted(item)]]
        raise ValueError("private call input is not JSON")

    try:
        raw = json.dumps(visit(value, 0), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (OverflowError, UnicodeError, RecursionError) as exc:
        raise ValueError("private call input cannot be represented safely") from exc
    if len(raw) > max_bytes:
        raise ValueError("private call input exceeds byte bound")
    return raw


def parse_observed_arguments(arguments: object, *, action=None) -> dict:
    if not isinstance(arguments, str):
        raise ValueError("official call arguments must be JSON text")
    try:
        if len(arguments.encode("utf-8")) > _limits(action)[0]:
            raise ValueError("official call arguments exceed byte bound")
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate official call field")
                result[key] = value
            return result
        value = json.loads(arguments, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite input")))
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("official call arguments cannot be represented safely") from exc
    if not isinstance(value, dict):
        raise ValueError("official call arguments must be an object")
    _canonical(value, action=action)
    return value


def request_evidence(action: str, payload: object, *, trace_id: str) -> dict:
    """Compute input evidence, not an execution permission or business validation.

    Schema-invalid strategies are intentionally hashable when their task/run/key
    references are complete. They still must fail the unchanged MCP schema.
    """
    if not isinstance(action, str) or action not in ACTIONS or not isinstance(payload, dict):
        raise ValueError("unsupported domain call")
    required = {"task_id", "agent_run_id", "idempotency_key", "strategy"}
    allowed = required | {"experiment_id", "trace_id"}
    if action == "byq_factor_compute":
        required = {"task_id", "agent_run_id", "idempotency_key", "as_of_date", "factor",
                    "securities", "sessions", "bars", "universe_snapshots", "sources"}
        allowed = required | {"experiment_id", "trace_id", "statuses"}
    if action == "byq_strategy_version_create":
        required = {"task_id", "agent_run_id", "idempotency_key", "draft_artifact_id"}
        allowed = required | {"experiment_id", "trace_id"}
    if not required <= payload.keys() or payload.keys() - allowed:
        raise ValueError("exact domain call references required")
    task, run, key = (_text(payload[name]) for name in ("task_id", "agent_run_id", "idempotency_key"))
    trace = _text(trace_id)
    effective = {**payload, "trace_id": trace}
    request_hash = hashlib.sha256(_canonical([action, effective], action=action)).hexdigest()
    # Run/key are replay identities, not progress. Changing child or key cannot
    # turn the exact same failed strategy input into a correction.
    content = {name: value for name, value in effective.items() if name not in {"agent_run_id", "idempotency_key"}}
    input_hash = hashlib.sha256(_canonical([action, content], action=action)).hexdigest()
    return {"action": action, "task_id": task, "agent_run_id": run, "idempotency_key": key,
            "request_sha256": request_hash, "input_sha256": input_hash}


def validate_call_evidence(value: object) -> dict:
    keys = {"schema_version", "sequence", "root_run_id", "generation", "call_id", "action", "task_id",
            "agent_run_id", "idempotency_key", "request_sha256", "input_sha256"}
    if (not isinstance(value, dict) or set(value) != keys
            or value["schema_version"] != "domain-call-observed.v1"
            or not isinstance(value["action"], str) or value["action"] not in ACTIONS):
        raise ValueError("invalid private domain call evidence")
    if type(value["sequence"]) is not int or not 1 <= value["sequence"] < 2**63:
        raise ValueError("invalid private evidence sequence")
    for name, length in (("root_run_id", 32), ("request_sha256", 64), ("input_sha256", 64)):
        if not isinstance(value[name], str) or re.fullmatch(f"[0-9a-f]{{{length}}}", value[name]) is None:
            raise ValueError("invalid private evidence digest or root")
    for name in ("generation", "call_id", "task_id", "agent_run_id", "idempotency_key"):
        _text(value[name])
    return dict(value)


def call_evidence_receipt(value: object) -> dict:
    evidence = validate_call_evidence(value)
    return {"schema_version": "domain-call-receipt.v1", "sequence": evidence["sequence"],
            "root_run_id": evidence["root_run_id"],
            "event_sha256": hashlib.sha256(_canonical(evidence)).hexdigest()}
