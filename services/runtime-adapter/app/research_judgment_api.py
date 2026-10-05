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
import re
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
    # This route launches its own DSH process outside RuntimeAdapter's session
    # methods, so it shares the same startup authority gate explicitly.
    from .main import adapter
    from .runtime import RuntimeAuthorityUnavailable

    try:
        adapter.require_current_backend_authority()
    except RuntimeAuthorityUnavailable as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "runtime_authority_unavailable"},
        ) from error
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
    # This bounded judgment runner launches its own read-only DSH harness rather
    # than using _build_harness; carry the same Adapter process identity into it.
    dsh_environment = dict(os.environ)
    dsh_environment["BYQ_RUNTIME_BOOT_ID"] = adapter.boot_id
    try:
        receipt = run_stage_judgment(
            task_id=task_id, call_identity=call_identity, attempt=attempt,
            backend_url=os.environ.get("BYQ_BACKEND_URL", "http://backend:8000"),
            trusted_headers=trusted_headers, identity=identity,
            provider=os.environ.get("BYQ_DSH_PROVIDER", "deepseek-official"),
            model=os.environ.get("BYQ_DSH_MODEL", "deepseek-v4-flash"),
            session_root=str(session_root),
            compatibility=compatibility_for_release(release),
            environment=dsh_environment)
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


@router.post("/internal/runtime/research-judgment/{task_id}/acp-root/run")
def run_acp_judgment_root(task_id: str, request: Request) -> dict:
    """Fail closed until the dedicated ACP root has a complete terminal path.

    ADR-0097 requires persisted Backend root admission and AgentRun registration
    before MCP identity, followed by exact result, close, and terminal ACK. The
    current Backend slice does not qualify the latter lifecycle yet, so this
    opt-in route deliberately stops before any Backend request, ACP process, or
    provider dispatch. The retained ``/run`` SDK route remains available as the
    rollback path.
    """

    try:
        require_service_token(request.headers)
        identity, trusted_headers = trusted_context(request.headers)
        attempt = require_attempt(request.headers)
    except BoundaryError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    if re.fullmatch(r"task_[0-9a-f]{32}", task_id) is None:
        raise HTTPException(status_code=422, detail="exact research task identity required")
    # The dedicated ACP judgment lifecycle is opt-in and defaults to protected
    # until its full lifecycle and isolation qualification passes; the ordinary
    # Public/Product entry is never enabled by accident.
    from .research_judgment_entry import (
        judgment_acp_lifecycle_enabled,
        run_acp_judgment_root as run_acp_judgment_root_lifecycle,
    )

    if not judgment_acp_lifecycle_enabled(dict(os.environ)):
        raise HTTPException(
            status_code=503,
            detail={"code": "research_judgment_acp_lifecycle_unqualified"},
        )
    from .main import adapter
    from .runtime import RuntimeAuthorityUnavailable

    try:
        adapter.require_current_backend_authority()
    except RuntimeAuthorityUnavailable as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "runtime_authority_unavailable"},
        ) from error
    call_identity = derive_call_identity(task_id, attempt)
    authority_headers = {
        **trusted_headers,
        "authorization": f"Bearer {os.environ.get('BYQ_RUNTIME_AUTHORITY_TOKEN', '')}",
        "x-byq-runtime-boot-id": adapter.boot_id,
    }
    try:
        return run_acp_judgment_root_lifecycle(
            task_id=task_id, identity=identity, attempt=attempt,
            call_identity=call_identity, trusted_headers=authority_headers,
            environment=dict(os.environ))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - fail closed, never leak model payload
        raise HTTPException(
            status_code=503,
            detail={"code": "research_judgment_acp_failed_closed",
                    "kind": type(exc).__name__}) from exc


# Kept importable for the targeted route test without starting a real carrier.
_run_stage_judgment = run_stage_judgment
