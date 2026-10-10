"""Authenticated internal routes for the dedicated research-judgment runtime.

The former Python-SDK route is closed with an authenticated 503. Dedicated ACP
root execution and recovery remain separately gated and fail closed.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading

from fastapi import APIRouter, HTTPException, Request

from .research_judgment_boundary import (
    BoundaryError,
    derive_call_identity,
    require_attempt,
    require_service_token,
    trusted_context,
    valid_task_identity,
)
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
    """Retire the pre-ACP SDK entry without dispatching work.

    Callers must use the accepted dedicated ACP root route. This endpoint remains
    authenticated so old internal callers receive a clear, non-secret migration
    response instead of invoking the Python SDK or fabricating ACP semantics.
    """

    try:
        require_service_token(request.headers)
        trusted_context(request.headers)
        require_attempt(request.headers)
    except BoundaryError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    if not valid_task_identity(task_id):
        raise HTTPException(status_code=422, detail="exact research task identity required")
    raise HTTPException(
        status_code=503,
        detail={
            "code": "research_judgment_sdk_route_disabled",
            "replacement_route": (
                f"/internal/runtime/research-judgment/{task_id}/acp-root/run"
            ),
        },
    )


@router.post("/internal/runtime/research-judgment/{task_id}/acp-root/run")
async def run_acp_judgment_root(task_id: str, request: Request) -> dict:
    """Run the dedicated ACP judgment root, aborting on client disconnect.

    ADR-0097 requires persisted Backend root admission and AgentRun registration
    before MCP identity, followed by exact result, close, and terminal ACK. The
    lifecycle is opt-in and defaults to protected. A client disconnect aborts the
    live turn (cancel_event), which then settles fail-closed from the durable
    journal and any owner cancel receipt.
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
    cancel_event = threading.Event()

    def _worker() -> dict:
        return run_acp_judgment_root_lifecycle(
            task_id=task_id, identity=identity, attempt=attempt,
            call_identity=call_identity, trusted_headers=authority_headers,
            environment=dict(os.environ), cancel_event=cancel_event)

    loop = asyncio.get_running_loop()
    running = loop.run_in_executor(None, _worker)
    try:
        while not running.done():
            if await request.is_disconnected():
                cancel_event.set()
                break
            await asyncio.sleep(0.2)
        return await running
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - fail closed, never leak model payload
        raise HTTPException(
            status_code=503,
            detail={"code": "research_judgment_acp_failed_closed",
                    "kind": type(exc).__name__}) from exc


@router.post("/internal/runtime/research-judgment/{task_id}/acp-root/recover")
def recover_acp_judgment_root(task_id: str, request: Request) -> dict:
    """Reconcile one in-flight dedicated ACP judgment root after a restart.

    The durable journal decides the outcome; a prompt that may have dispatched
    is settled ``outcome_unknown`` without replay. Opt-in and authenticated like
    the run route; the production entry stays protected without the flag.
    """

    try:
        require_service_token(request.headers)
        identity, trusted_headers = trusted_context(request.headers)
        attempt = require_attempt(request.headers)
    except BoundaryError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    if re.fullmatch(r"task_[0-9a-f]{32}", task_id) is None:
        raise HTTPException(status_code=422, detail="exact research task identity required")
    from .research_judgment_entry import (
        judgment_acp_lifecycle_enabled,
        recover_acp_judgment_root as recover_acp_judgment_root_lifecycle,
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
    authority_headers = {
        **trusted_headers,
        "authorization": f"Bearer {os.environ.get('BYQ_RUNTIME_AUTHORITY_TOKEN', '')}",
        "x-byq-runtime-boot-id": adapter.boot_id,
    }
    try:
        return recover_acp_judgment_root_lifecycle(
            task_id=task_id, identity=identity,
            call_identity=derive_call_identity(task_id, attempt),
            trusted_headers=authority_headers, environment=dict(os.environ))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - fail closed
        raise HTTPException(
            status_code=503,
            detail={"code": "research_judgment_acp_failed_closed",
                    "kind": type(exc).__name__}) from exc
