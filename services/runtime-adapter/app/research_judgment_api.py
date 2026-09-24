"""ADR-0085 P4: the minimal trusted Runtime Adapter HTTP entry for one bounded
research-judgment turn.

This is the production seam the P4 driver probes. It is an INTERNAL endpoint and
it is AUTHENTICATED: the caller must present the shared runtime service token
(``x-byq-runtime-judgment-token`` == ``BYQ_RUNTIME_JUDGMENT_TOKEN``, compared in
constant time by ``research_judgment_boundary``). Path privacy and network
isolation alone are NOT treated as authentication.

The trusted caller supplies only the exact ``task_id`` plus the BYQ context
headers. The adapter derives the call identity and the real DSH generation id
server-side (never from a request header) and delegates to the real
``run_bounded_research_judgment`` flow. The authoritative task/owner/workspace/
stage binding is enforced by the Backend admission transaction (``_plan_task``),
which runs BEFORE any model call. The request body is ignored so a caller can
never supply a model result, a next action, an approval or a routing decision.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from .research_judgment_boundary import (
    BoundaryError,
    derive_call_identity,
    require_attempt,
    require_service_token,
    trusted_context,
    valid_task_identity,
)
from .research_judgment import ResearchJudgmentInProgress
from .research_judgment_entry import run_stage_judgment

router = APIRouter()


@router.get("/internal/runtime/research-judgment/healthz")
def judgment_healthz() -> dict:
    from .research_judgment_turn import resolve_judgment_composition

    return {
        "status": "ok",
        "schema_version": "byq-research-judgment-entry.v1",
        "authenticated": bool(os.environ.get("BYQ_RUNTIME_JUDGMENT_TOKEN")),
        "composition": resolve_judgment_composition(dict(os.environ)),
    }


@router.post("/internal/runtime/research-judgment/{task_id}/run")
def run_judgment(task_id: str, request: Request) -> dict:
    try:
        require_service_token(request.headers)
        identity, trusted_headers = trusted_context(request.headers)
        attempt = require_attempt(request.headers)
    except BoundaryError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    if not valid_task_identity(task_id):
        raise HTTPException(status_code=422, detail="exact research task identity required")
    from .compat import compatibility_for_release

    release = os.environ.get("BYQ_DSH_COMPATIBILITY_RELEASE", "dsh-0.1.5rc1")
    # Retry-stable, authoritative: the durable stage-call identity is derived from
    # the exact task and the persisted plan's version/stage/iteration, NOT from any
    # per-request random value or caller-chosen id. A retry after an interrupted
    # admission+result therefore reuses the same admission instead of consuming a
    # second model-call slot.
    call_identity = derive_call_identity(task_id, attempt)
    # Each named judgment request gets its OWN DSH home, so a later request for a
    # different stage never collides with an existing DSH session.
    session_root = Path(os.environ.get("DSH_SESSION_ROOT", "/var/lib/byq/dsh-sessions")) \
        / "research-judgment" / task_id / call_identity
    # The adapter invocation id is an adapter-local label for this DSH process. It
    # is NOT claimed to be, or mapped to, a persisted RuntimeGeneration.
    adapter_invocation_id = "byq-adapter-" + uuid.uuid4().hex
    identity["dsh_run_id"] = adapter_invocation_id
    trusted_headers["x-byq-dsh-run-id"] = adapter_invocation_id
    try:
        receipt = run_stage_judgment(
            task_id=task_id, call_identity=call_identity, attempt=attempt,
            backend_url=os.environ.get("BYQ_BACKEND_URL", "http://backend:8000"),
            trusted_headers=trusted_headers, identity=identity,
            provider=os.environ.get("BYQ_DSH_PROVIDER", "deepseek-official"),
            model=os.environ.get("BYQ_DSH_MODEL", "deepseek-v4-flash"),
            session_root=str(session_root),
            compatibility=compatibility_for_release(release),
            environment=dict(os.environ))
    except HTTPException:
        raise
    except ResearchJudgmentInProgress as exc:
        # A duplicate/concurrent request must not terminate the live turn.
        raise HTTPException(
            status_code=409,
            detail={"code": "research_judgment_in_progress"}) from exc
    except Exception as exc:  # noqa: BLE001
        # A bounded judgment turn failed closed; a caller must never see a
        # fabricated success or a raw model/provider payload.
        raise HTTPException(
            status_code=503,
            detail={"code": "research_judgment_failed_closed",
                    "kind": type(exc).__name__}) from exc
    return {
        "receipt": receipt,
        "adapter_invocation": {
            "id": adapter_invocation_id,
            "call_identity": call_identity,
            "attempt": attempt,
        },
        # Honest: no real RuntimeGeneration mapping is available yet.
        "dsh_generation": {"status": "not_available", "id": None,
                           "note": "adapter invocation id is not a persisted runtime generation"},
    }


# Kept importable for the targeted route test without starting a real carrier.
_run_stage_judgment = run_stage_judgment
