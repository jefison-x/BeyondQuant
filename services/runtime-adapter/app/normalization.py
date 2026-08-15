from __future__ import annotations

from typing import Any

from deepseek_harness import Notification

from .contracts import WorkflowTraceEvent, make_workflow_trace_event


def normalize_dsh_notification(
    notification: Notification,
    *,
    trace_id: str,
    session_id: str,
    sequence: int,
) -> WorkflowTraceEvent | None:
    """Translate the two rc.6 SDK notification families into BYQ events.

    Only selected semantic fields cross the adapter boundary. The raw DSH
    notification and raw ``session.event`` object never leave this module.
    """

    payload = notification.payload
    related_session_id = payload.get("sessionId")
    if related_session_id != session_id:
        return None

    if notification.method == "session.status":
        status = payload.get("status")
        if not isinstance(status, str):
            return None
        return make_workflow_trace_event(
            trace_id=trace_id,
            session_id=session_id,
            sequence=sequence,
            kind="session.status",
            source="dsh",
            payload={"status": status},
        )

    if notification.method != "session.event":
        return None

    event = payload.get("event")
    if not isinstance(event, dict):
        return None
    event_type = event.get("type")
    if not isinstance(event_type, str):
        return None

    kind, normalized_payload = _normalize_session_event(event_type, event.get("data"))
    return make_workflow_trace_event(
        trace_id=trace_id,
        session_id=session_id,
        sequence=sequence,
        kind=kind,
        source="dsh",
        payload=normalized_payload,
    )


def _normalize_session_event(event_type: str, data: Any) -> tuple[str, dict[str, Any]]:
    if event_type == "agent/inbox/spliced":
        inserted = data.get("inserted") if isinstance(data, dict) else None
        message_count = len(inserted) if isinstance(inserted, list) else 0
        return "session.input.accepted", {"message_count": message_count}
    if event_type == "turn/end":
        reason = data.get("reason") if isinstance(data, dict) else None
        reason_kind = reason.get("kind") if isinstance(reason, dict) else None
        return "turn.completed", {"reason": reason_kind if isinstance(reason_kind, str) else "unknown"}
    if event_type == "assistant/message":
        message = data.get("message") if isinstance(data, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        text_bytes = sum(
            len(str(block.get("text") or ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ) if isinstance(content, list) else 0
        return "agent.output.delta", {"text_bytes": text_bytes}
    return "session.progress", {"event_kind": event_type}
