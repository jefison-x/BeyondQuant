"""Minimal BYQ-owned workflow trace envelope.

DSH notifications are translated into this framework-neutral shape inside the
runtime adapter. Gateway and frontend code must not depend on DSH wire types.
"""

from __future__ import annotations

from datetime import datetime
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
