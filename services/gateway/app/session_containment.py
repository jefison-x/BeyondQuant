"""ADR-0084 Product-visible containment and recovery *classification*.

The Gateway derives containment strictly from the normalized BYQ WorkflowTrace
plus the durable, fenced adapter containment summary. It never reads a raw DSH
event, a DSH session id, or the business database directly.

This module is deliberately **read-only**. Automatic rescheduling requires
server-side authoritative action/workflow step-safety and budget metadata. That
metadata does not exist yet, so the classification fails closed to
``paused``/``needs_confirmation`` and no new prompt is ever submitted. There is no
attempt ledger, no ``/tmp`` authority and no second session store.

Business state (conversation, authorization, approval, artifacts, jobs,
receipts, budget, cancel) stays in the Domain Plane; the preservation projection
reports a value as ``preserved`` only when an existing authoritative catalog/job/
receipt read proves it, otherwise ``unknown``/``unavailable``.
"""

from __future__ import annotations

import re

from packages.contracts.session_failure_containment import (
    BOUNDARY_INVARIANT,
    CONTAINMENT_VERSION,
    LOSS_CAUSES,
    PRESERVED_FIELDS,
    PRESERVATION_SCHEMA_VERSION,
    classify_recovery,
    validate_preservation,
)

TERMINAL_KINDS = frozenset({
    "session.result", "session.failed", "session.cancelled",
    "session.result.discarded", "session.closed",
})
COMPLETED = "session.result"
CANCELLED = "session.cancelled"
INTERRUPTED = "interrupted"
_RUN = re.compile(r"[0-9a-f]{32}")
_ORDINARY = {
    "session.failed": "failed",
    "session.result.discarded": "discarded",
    "session.closed": "closed",
}


def _owned(events: object, session_id: str, trace_id: str) -> list[dict]:
    if not isinstance(events, list):
        return []
    return sorted(
        (event for event in events if isinstance(event, dict)
         and event.get("session_id") == session_id and event.get("trace_id") == trace_id
         # Only normalized BYQ projections; a raw DSH event is never a source.
         and event.get("source") in {"runtime-adapter", "byq-domain"}),
        key=lambda event: event.get("sequence", 0),
    )


def _terminal_run(event: dict) -> str | None:
    payload = event.get("payload")
    run = payload.get("run_id") if isinstance(payload, dict) else None
    return run if isinstance(run, str) and _RUN.fullmatch(run) else None


def containment_match(adapter_containment: object, session_id: str, trace_id: str) -> dict | None:
    """Return the fenced containment record only when it binds this session/trace.

    The adapter summary is the authoritative loss evidence. A record for another
    session/trace, a missing run identity or an unknown loss cause is not
    evidence and must not turn an ordinary failure into an interruption.
    """

    if not isinstance(adapter_containment, dict) or not adapter_containment.get("contained"):
        return None
    if adapter_containment.get("session_id") not in (None, session_id):
        return None
    latest = adapter_containment.get("latest")
    if not isinstance(latest, dict) or latest.get("trace_id") != trace_id:
        return None
    run = latest.get("interrupted_run_id")
    if not isinstance(run, str) or _RUN.fullmatch(run) is None:
        return None
    if latest.get("loss_cause") not in LOSS_CAUSES:
        return None
    return latest


def loss_from_evidence(
    events: object, session_id: str, trace_id: str, adapter_containment: object = None,
) -> dict:
    """Derive the truthful terminal status from trace + fenced loss evidence.

    ``interrupted`` is projected **only** when the adapter's fenced containment
    record matches this session/trace and the exact terminal run. An ordinary
    model/tool failure stays ``failed``; a cancel stays ``cancelled``; a
    discarded result keeps its existing semantics; an unproven close stays
    ``closed``.
    """

    owned = _owned(events, session_id, trace_id)
    terminals = [event for event in owned if event.get("kind") in TERMINAL_KINDS]
    last = terminals[-1] if terminals else None
    match = containment_match(adapter_containment, session_id, trace_id)
    base = {
        "status": "active", "interrupted": False, "cancelled": False,
        "interrupted_run_id": None, "loss_cause": None, "last_terminal_sequence": None,
    }
    if last is None:
        if match is not None:
            return {**base, "status": INTERRUPTED, "interrupted": True,
                    "interrupted_run_id": match["interrupted_run_id"],
                    "loss_cause": match["loss_cause"]}
        return base
    kind = last.get("kind")
    run = _terminal_run(last)
    sequence = last.get("sequence")
    if kind == COMPLETED:
        return {**base, "status": "completed", "last_terminal_sequence": sequence}
    if kind == CANCELLED:
        return {**base, "status": "cancelled", "cancelled": True, "last_terminal_sequence": sequence}
    if match is not None and (run is None or run == match["interrupted_run_id"]):
        return {**base, "status": INTERRUPTED, "interrupted": True,
                "interrupted_run_id": match["interrupted_run_id"],
                "loss_cause": match["loss_cause"], "last_terminal_sequence": sequence}
    return {**base, "status": _ORDINARY.get(kind, "failed"), "last_terminal_sequence": sequence}


def preservation_projection(
    *,
    conversation_known: bool,
    trace_known: bool,
    authority: object,
    catalog_source: str = "backend-product-catalog",
    trace_source: str = "gateway-trace-store",
) -> dict:
    """Separate the boundary assertion from actual before/after verification."""

    states = {field: "unknown" for field in PRESERVED_FIELDS}
    sources: dict[str, str] = {}
    if trace_known:
        states["workflow_trace"] = "preserved"
        sources["workflow_trace"] = trace_source
    if conversation_known:
        states["conversation"] = "preserved"
        sources["conversation"] = catalog_source
    auth = authority.get("authorization_current") if isinstance(authority, dict) else None
    if auth is True:
        states["authorization"] = "preserved"
        sources["authorization"] = (authority.get("source") if isinstance(authority, dict)
                                    else None) or "backend-auth-session"
    elif auth is False:
        states["authorization"] = "unavailable"
    if not sources:
        sources["boundary"] = "execution-boundary-assertion"
    return validate_preservation({
        "schema_version": PRESERVATION_SCHEMA_VERSION,
        "states": states,
        "boundary_invariant": BOUNDARY_INVARIANT,
        "boundary_verified": False,
        "sources": sources,
    })


def _tri(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def project_containment(
    events: object,
    *,
    session_id: str,
    trace_id: str,
    conversation_id: str | None = None,
    adapter_containment: object = None,
    authority: object = None,
    preservation: object = None,
) -> dict:
    """One fail-closed, framework-neutral containment + classification projection.

    No prompt is submitted and no attempt is created. An unverified authority or
    absent step-safety metadata always yields ``paused`` (or ``blocked`` for an
    authoritative denial), never ``eligible``.
    """

    loss = loss_from_evidence(events, session_id, trace_id, adapter_containment)
    authority = authority if isinstance(authority, dict) else {}
    recovery = None
    if loss["interrupted"] or loss["cancelled"]:
        # No authoritative step-safety metadata exists, so a step is never
        # declared safe here; a successful receipt is never claimed without an
        # exact read. The decision therefore fails closed to paused/blocked.
        decision = classify_recovery(
            cancelled=loss["cancelled"],
            authorization_current=_tri(authority.get("authorization_current")),
            owner_matches=_tri(authority.get("owner_matches")),
            workspace_matches=_tri(authority.get("workspace_matches")),
            budget_available=_tri(authority.get("budget_available")),
            success_receipt_present=False,
            receipt_queryable=False,
            step_declared_idempotent=False,
            step_result_verifiable=False,
            previous_run_id=loss["interrupted_run_id"],
        )
        recovery = decision.view()
    if preservation is None:
        preservation = preservation_projection(
            conversation_known=conversation_id is not None, trace_known=True, authority=authority)
    return {
        "schema_version": CONTAINMENT_VERSION,
        # Public conversation identity, never the internal runtime session id.
        "session_id": conversation_id or session_id,
        "conversation_id": conversation_id,
        "trace_id": trace_id,
        "status": loss["status"],
        "loss_cause": loss["loss_cause"],
        "interrupted_run_id": loss["interrupted_run_id"],
        "recovery": recovery,
        "preservation": validate_preservation(preservation),
        # Read-only: this endpoint never submits a prompt or records an attempt.
        "submission": "not_performed",
    }
