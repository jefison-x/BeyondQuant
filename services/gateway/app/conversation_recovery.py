"""Derive recovery only from the owned Product catalog and normalized trace."""
from datetime import datetime

from packages.contracts.conversation_recovery import (
    FAILURE_CODES, MAX_UNANSWERED_CHARS, RECOVERY_VERSION,
    is_continuation, normalize_recovery, valid_identity,
)


def _time(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def project_recovery(messages, events, session_id, trace_id):
    """Return history candidates and an independent, fail-closed recovery section."""
    public = [m for m in messages if isinstance(m, dict)] if isinstance(messages, list) else []
    owned = sorted((e for e in events if e.get("session_id") == session_id and e.get("trace_id") == trace_id),
                   key=lambda e: e["sequence"])
    terminals = [e for e in owned if e["kind"] in {
        "session.result", "session.failed", "session.cancelled", "session.result.discarded"}]
    if not terminals or terminals[-1]["kind"] == "session.result":
        return public, None
    failure = terminals[-1]
    starts = [e for e in owned if e["kind"] == "session.started" and e["sequence"] < failure["sequence"]]
    start = starts[-1] if starts else None
    run_id = None if start is None else start.get("payload", {}).get("run_id")
    if not valid_identity(run_id):
        run_id = None
    code = {"session.cancelled": "cancelled", "session.result.discarded": "result-discarded"}.get(
        failure["kind"], failure.get("payload", {}).get("code", "unknown"))
    if not isinstance(code, str) or code not in FAILURE_CODES:
        code = "unknown"
    recovery = {"schema_version": RECOVERY_VERSION, "session_id": session_id, "trace_id": trace_id,
                "status": "needs_confirmation", "unanswered_turn": None,
                "failure": {"sequence": failure["sequence"], "run_id": run_id, "code": code}}
    # Partial answers from this failed run must not close the pending question.
    public = [m for m in public if not (
        m.get("role") == "assistant" and start is not None
        and type(m.get("workflow_sequence")) is int and m["workflow_sequence"] >= start["sequence"])]
    last_answer = max((i for i, m in enumerate(public) if m.get("role") == "assistant"), default=-1)
    cutoff = _time(start["timestamp"] if start is not None else failure["timestamp"])
    candidates = []
    ambiguous = cutoff is None or not isinstance(messages, list) or len(messages) > 200
    if not ambiguous:
        for m in public[last_answer + 1:]:
            if m.get("role") != "user":
                continue
            at = _time(m.get("created_at"))
            if at is None:
                ambiguous = True
                continue
            if at > cutoff:  # e.g. current prompt persisted before a lost-runtime retry
                continue
            content = m.get("content")
            if (not valid_identity(m.get("message_id")) or not isinstance(content, str)
                    or not content.strip() or len(content) > MAX_UNANSWERED_CHARS):
                ambiguous = True
                continue
            if not is_continuation(content):
                candidates.append({"message_id": m["message_id"], "content": content})
    distinct = {m["content"].strip() for m in candidates}
    if not ambiguous and len(distinct) == 1:
        recovery.update(status="resolved", unanswered_turn=candidates[0])
    return public, normalize_recovery(recovery, session_id, trace_id)
