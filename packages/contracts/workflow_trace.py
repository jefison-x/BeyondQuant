"""Minimal BYQ-owned workflow trace envelope.

DSH notifications are translated into this framework-neutral shape inside the
runtime adapter. Gateway and frontend code must not depend on DSH wire types.
"""

from __future__ import annotations

from datetime import datetime
from json import dumps
from typing import Any, Literal, TypedDict


class WorkflowTraceEvent(TypedDict):
    trace_id: str
    session_id: str
    sequence: int
    timestamp: str
    kind: str
    source: Literal["dsh", "runtime-adapter"]
    payload: dict[str, Any]


def make_workflow_trace_event(
    *,
    trace_id: str,
    session_id: str,
    sequence: int,
    kind: str,
    source: Literal["dsh", "runtime-adapter"],
    payload: dict[str, Any],
) -> WorkflowTraceEvent:
    return {
        "trace_id": trace_id,
        "session_id": session_id,
        "sequence": sequence,
        "timestamp": datetime.now().astimezone().isoformat(),
        "kind": kind,
        "source": source,
        "payload": payload,
    }


def validate_workflow_trace_event(event: object) -> WorkflowTraceEvent:
    """Validate the framework-neutral event before BYQ persists or streams it."""

    if not isinstance(event, dict):
        raise ValueError("workflow trace event must be an object")
    required = {"trace_id", "session_id", "sequence", "timestamp", "kind", "source", "payload"}
    if set(event) != required:
        raise ValueError("workflow trace event has an invalid field set")
    for field in ("trace_id", "session_id", "timestamp", "kind"):
        value = event[field]
        if not isinstance(value, str) or not value:
            raise ValueError(f"workflow trace {field} must be a non-empty string")
    if not isinstance(event["sequence"], int) or event["sequence"] < 1:
        raise ValueError("workflow trace sequence must be a positive integer")
    if event["source"] not in {"dsh", "runtime-adapter"}:
        raise ValueError("workflow trace source is not supported")
    if not isinstance(event["payload"], dict):
        raise ValueError("workflow trace payload must be an object")
    try:
        dumps(event["payload"], separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("workflow trace payload must be JSON-serializable") from exc
    return event  # type: ignore[return-value]
