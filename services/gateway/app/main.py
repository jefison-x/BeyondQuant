from __future__ import annotations

import json
import hashlib
import logging
import os
import asyncio
import threading
import time
import uuid
import re
from datetime import datetime, timezone
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from packages.contracts.conversation_rehydration import (
    MAX_REHYDRATION_MESSAGE_CHARS,
    MAX_REHYDRATION_MESSAGES,
    MAX_REHYDRATION_TOTAL_CHARS,
    ConversationContextMessage,
)
from packages.operations.admission import AdmissionClosed, chat_admission
from packages.contracts.prompt_rejection import matches_credential_rejection
from packages.contracts.continuation_request import (
    RESERVATION_SCHEMA_VERSION, validate_profile_binding, validate_limits, validate_request_usage,
)

from .auth import AuthenticationUnavailable, Principal, authenticate_bearer
from .auth_api import router as auth_router
from .product_api import (
    ProductError, _backend_request, _trusted_agent_headers, router as product_router,
)
from .pooled_http import pooled_http as httpx
from .user_session import SESSION_COOKIE, ProductAuthError, resolve_principal, resolve_user
from .trace_store import TraceConflict, TraceStore
from .session_containment import (
    containment_match,
    preservation_projection,
    project_containment,
)
from .workflow_projection import project_workflow_event
from .agent_lifecycle_delivery import LifecycleDelivery
from .task_continuation import TaskContinuationDelivery
from packages.contracts.agent_run_lifecycle import lifecycle_receipt, project_lifecycle_event
from packages.contracts.domain_call_admission import call_evidence_receipt


SERVICE = "byq-gateway"
VERSION = "0.1.0"
logger = logging.getLogger('uvicorn.error')
TRACE_LIFECYCLE_SEND_ATTEMPTS = 3
TRACE_RETRY_DELAY_SECONDS = 0.05
TRACE_RETRY_MAX_DELAY_SECONDS = 5.0


@asynccontextmanager
async def lifespan(app):
    try:
        _sync_runtime_authority()
    except Exception:
        _set_runtime_authority_state(ready=False)
    answer_delivery.start()
    domain_call_delivery.start()
    task_continuation_delivery.start()
    try:
        yield
    finally:
        task_continuation_delivery.close()
        answer_delivery.close()
        domain_call_delivery.close()


app = FastAPI(title="BeyondQuant Gateway", version=VERSION, lifespan=lifespan)
app.include_router(product_router)
app.include_router(auth_router)
RUNTIME_ADAPTER_URL = os.environ.get("BYQ_RUNTIME_ADAPTER_URL", "http://runtime-adapter:8400")
RUNTIME_SESSION_IDLE_SECONDS = max(5.0, float(os.environ.get("BYQ_RUNTIME_SESSION_IDLE_SECONDS", "30")))
BACKEND_URL = os.environ.get("BYQ_BACKEND_URL", "http://backend:8000")
PRODUCT_TOKEN = os.environ.get("BYQ_PRODUCT_TOKEN")
PRODUCT_PRINCIPAL = os.environ.get("BYQ_PRODUCT_PRINCIPAL", "product-user")
trace_store = TraceStore(os.environ.get("BYQ_WORKFLOW_TRACE_ROOT", "/tmp/byq-workflow-traces"))

RUNTIME_ADAPTER_AUTHORITY_PATH = "/internal/runtime/authority"
RUNTIME_AUTHORITY_BOOT_SCHEMA = "byq-runtime-authority-boot.v1"
RUNTIME_AUTHORITY_RECEIPT_SCHEMA = "byq-runtime-authority-receipt.v1"
RUNTIME_AUTHORITY_CURRENT_SCHEMA = "byq-runtime-authority-current.v1"
RUNTIME_TERMINAL_EVIDENCE_SCHEMA = "byq-runtime-terminal-evidence.v1"
RUNTIME_ROOT_CLOSE_SCHEMA = "byq-runtime-root-close.v1"
WORKSPACE_RUNTIME_RESET_BEGIN_SCHEMA = "workspace-runtime-reset-begin.v1"
WORKSPACE_RUNTIME_RESET_FINALIZE_SCHEMA = "workspace-runtime-reset-finalize.v1"
WORKSPACE_RESET_BEGIN_SCHEMA = "workspace-reset-begin.v1"
WORKSPACE_RESET_FINALIZE_SCHEMA = "workspace-reset-finalize.v1"
_runtime_authority_lock = threading.RLock()
_runtime_authority_sync_lock = threading.Lock()
_runtime_authority_state: dict[str, object] = {
    "ready": False,
    "boot_id": None,
    "authority_epoch": None,
}


def _valid_runtime_boot_id(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) is not None


def _set_runtime_authority_state(*, ready: bool, boot_id: str | None = None,
                                 authority_epoch: int | None = None) -> None:
    with _runtime_authority_lock:
        _runtime_authority_state.update({
            "ready": ready,
            "boot_id": boot_id if ready else None,
            "authority_epoch": authority_epoch if ready else None,
        })


def _runtime_authority_snapshot() -> dict[str, object]:
    with _runtime_authority_lock:
        return dict(_runtime_authority_state)


def require_runtime_authority() -> None:
    try:
        _sync_runtime_authority()
        if _runtime_authority_snapshot().get("ready") is not True:
            raise RuntimeError("runtime authority was not established")
    except Exception as exc:
        _set_runtime_authority_state(ready=False)
        raise HTTPException(status_code=503, detail="Agent runtime authority is not ready") from exc


def _adapter_authority() -> dict[str, object]:
    try:
        response = httpx.get(f"{RUNTIME_ADAPTER_URL}{RUNTIME_ADAPTER_AUTHORITY_PATH}", timeout=3.0)
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPError as exc:
        raise RuntimeError("runtime adapter authority is unavailable") from exc
    except ValueError as exc:
        raise RuntimeError("runtime adapter authority returned invalid JSON") from exc
    if (not isinstance(body, dict) or set(body) != {"schema_version", "boot_id", "status"}
            or body.get("schema_version") != "byq-runtime-adapter-authority.v1"
            or not _valid_runtime_boot_id(body.get("boot_id")) or body.get("status") != "ready"):
        raise RuntimeError("runtime adapter authority receipt is invalid")
    return body


def _backend_runtime_authority_request(method: str, path: str,
                                      payload: dict[str, object] | None = None,
                                      scope: ProductSession | None = None) -> dict[str, object]:
    headers: dict[str, str] = {}
    if path != "/internal/runtime-authority/current":
        token = os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
        if not token:
            raise RuntimeError("Gateway runtime authority credential is missing")
        headers["Authorization"] = f"Bearer {token}"
    if scope is not None:
        headers.update({"x-byq-owner-principal": scope.principal.subject,
                        "x-byq-workspace-id": scope.workspace_id,
                        "x-byq-trace-id": scope.trace_id})
    try:
        response = httpx.request(
            method,
            f"{BACKEND_URL}{path}",
            json=payload,
            headers=headers,
            timeout=5.0,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("Backend runtime authority request failed") from exc
    if not isinstance(body, dict):
        raise RuntimeError("Backend runtime authority response is invalid")
    return body


def _workspace_runtime_reset_backend_request(
    method: str,
    path: str,
    payload: dict[str, object],
    principal: Principal,
    workspace_id: str,
) -> dict[str, object]:
    """Call the private, owner-scoped Backend workspace runtime-reset contract."""
    token = os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
    if not token:
        raise HTTPException(status_code=503, detail="Workspace runtime reset is unavailable")
    headers = {
        "Authorization": f"Bearer {token}",
        "x-byq-owner-principal": principal.subject,
        "x-byq-workspace-id": workspace_id,
    }
    try:
        response = httpx.request(
            method,
            f"{BACKEND_URL}{path}",
            json=payload,
            headers=headers,
            timeout=8.0,
        )
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if 400 <= status < 500:
            raise HTTPException(status_code=status, detail="Workspace runtime reset was rejected") from exc
        raise HTTPException(status_code=503, detail="Workspace runtime reset is unavailable") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Workspace runtime reset is unavailable") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="Backend workspace reset receipt is invalid")
    return body


def _workspace_reset_identifier(value: object) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= 256 and value.strip() == value
            and re.fullmatch(r"[A-Za-z0-9_-]+", value) is not None)


def _validate_workspace_runtime_reset_begin(
    body: object, *, workspace_id: str,
) -> tuple[str, list[dict[str, str]]]:
    if (not isinstance(body, dict)
            or set(body) != {"schema_version", "workspace_id", "reset_id", "sessions"}
            or body.get("schema_version") != WORKSPACE_RUNTIME_RESET_BEGIN_SCHEMA
            or body.get("workspace_id") != workspace_id
            or not isinstance(body.get("reset_id"), str)
            or re.fullmatch(r"[0-9a-f]{32}", body["reset_id"]) is None
            or not isinstance(body.get("sessions"), list)
            or len(body["sessions"]) > 1000):
        raise HTTPException(status_code=502, detail="Backend workspace reset receipt is invalid")

    sessions: list[dict[str, str]] = []
    conversation_ids: list[str] = []
    seen_session_ids: set[str] = set()
    seen_trace_ids: set[str] = set()
    for row in body["sessions"]:
        if (not isinstance(row, dict)
                or set(row) != {"conversation_id", "session_id", "trace_id"}
                or any(not _workspace_reset_identifier(row.get(key))
                       for key in ("conversation_id", "session_id", "trace_id"))):
            raise HTTPException(status_code=502, detail="Backend workspace reset receipt is invalid")
        conversation_id = row["conversation_id"]
        session_id = row["session_id"]
        trace_id = row["trace_id"]
        try:
            # Session IDs become local trace and delivery filenames below.
            trace_store._path(session_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=502, detail="Backend workspace reset receipt is invalid") from None
        if (conversation_id in conversation_ids or session_id in seen_session_ids
                or trace_id in seen_trace_ids):
            raise HTTPException(status_code=502, detail="Backend workspace reset receipt is invalid")
        conversation_ids.append(conversation_id)
        seen_session_ids.add(session_id)
        seen_trace_ids.add(trace_id)
        sessions.append({"conversation_id": conversation_id, "session_id": session_id, "trace_id": trace_id})
    if conversation_ids != sorted(conversation_ids):
        raise HTTPException(status_code=502, detail="Backend workspace reset receipt is invalid")
    return body["reset_id"], sessions


def _validate_workspace_runtime_reset_finalize(
    body: object, *, workspace_id: str, reset_id: str, expected_conversation_ids: list[str],
) -> None:
    if (not isinstance(body, dict)
            or set(body) != {"schema_version", "workspace_id", "reset_id", "status", "archived_conversation_ids"}
            or body.get("schema_version") != WORKSPACE_RUNTIME_RESET_FINALIZE_SCHEMA
            or body.get("workspace_id") != workspace_id
            or body.get("reset_id") != reset_id
            or body.get("status") != "finalized"
            or body.get("archived_conversation_ids") != expected_conversation_ids):
        raise HTTPException(status_code=502, detail="Backend workspace reset receipt is invalid")


def _validate_workspace_reset_receipt(
    body: object, *, workspace_id: str, allow_blocked: bool = False,
) -> dict[str, object]:
    if (allow_blocked and isinstance(body, dict) and set(body) == {"status", "workspace_id", "reason"}
            and body.get("status") == "blocked" and body.get("workspace_id") == workspace_id
            and isinstance(body.get("reason"), str) and body["reason"]):
        return body
    if (not isinstance(body, dict) or set(body) != {
        "status", "workspace_id", "deleted", "already_empty",
    } or body.get("status") != "reset" or body.get("workspace_id") != workspace_id
            or type(body.get("already_empty")) is not bool or not isinstance(body.get("deleted"), dict)
            or any(not isinstance(table, str) or type(count) is not int or count < 0
                   for table, count in body["deleted"].items())):
        raise HTTPException(status_code=502, detail="Backend workspace reset receipt is invalid")
    return body


def _validate_workspace_reset_begin(
    body: object, *, workspace_id: str,
) -> tuple[str | None, list[dict[str, str]], dict[str, object] | None]:
    if (not isinstance(body, dict) or body.get("schema_version") != WORKSPACE_RESET_BEGIN_SCHEMA
            or body.get("workspace_id") != workspace_id):
        raise HTTPException(status_code=502, detail="Backend workspace reset receipt is invalid")
    if body.get("status") == "completed" and set(body) == {
        "schema_version", "workspace_id", "status", "receipt",
    }:
        return None, [], _validate_workspace_reset_receipt(body["receipt"], workspace_id=workspace_id,
                                                          allow_blocked=True)
    if body.get("status") != "pending" or set(body) != {
        "schema_version", "workspace_id", "reset_id", "status", "sessions",
    }:
        raise HTTPException(status_code=502, detail="Backend workspace reset receipt is invalid")
    runtime_shape = {
        "schema_version": WORKSPACE_RUNTIME_RESET_BEGIN_SCHEMA,
        "workspace_id": workspace_id,
        "reset_id": body["reset_id"],
        "sessions": body["sessions"],
    }
    reset_id, sessions = _validate_workspace_runtime_reset_begin(runtime_shape, workspace_id=workspace_id)
    return reset_id, sessions, None


def _validate_workspace_reset_finalize(
    body: object, *, workspace_id: str, reset_id: str,
) -> dict[str, object]:
    if (not isinstance(body, dict) or body.get("schema_version") != WORKSPACE_RESET_FINALIZE_SCHEMA
            or body.get("workspace_id") != workspace_id or body.get("reset_id") != reset_id):
        raise HTTPException(status_code=502, detail="Backend workspace reset receipt is invalid")
    return _validate_workspace_reset_receipt(
        {key: value for key, value in body.items() if key not in {"schema_version", "reset_id"}},
        workspace_id=workspace_id, allow_blocked=True,
    )


def _workspace_runtime_reset_adapter_session(session_id: str, trace_id: str) -> None:
    """Cancel a live prompt, then release the exact Backend-fenced Adapter session."""
    try:
        cancelled = _adapter_post(
            f"/internal/runtime/sessions/{session_id}/cancel?mode=hard", timeout=5.0,
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            # Backend begin already fenced the workspace; an absent ephemeral
            # Adapter record cannot still have an active prompt.
            pass
        elif (exc.status_code == 409
              and getattr(exc, "adapter_conflict_detail", None) == f"session {session_id} has no active prompt"):
            pass
        else:
            raise
    else:
        if (cancelled.get("session_id") != session_id or cancelled.get("trace_id") != trace_id
                or cancelled.get("active_prompt") is not False or cancelled.get("status") != "interrupted"):
            raise HTTPException(status_code=503, detail="Runtime session cancellation is unconfirmed")

    try:
        released = _adapter_post(f"/internal/runtime/sessions/{session_id}/release", timeout=5.0)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    else:
        if (released.get("session_id") != session_id or released.get("trace_id") != trace_id
                or released.get("active_prompt") is not False or released.get("status") != "closed"):
            raise HTTPException(status_code=503, detail="Runtime session release is unconfirmed")


def _delete_workspace_runtime_sidecars(session_id: str) -> None:
    """Delete only files keyed by the exact, Backend-fenced runtime session."""
    import fcntl
    from pathlib import Path

    trace_store.delete(session_id)
    paths: list[tuple[Path, Path]] = []
    for delivery in (answer_delivery, domain_call_delivery):
        sidecar = Path(delivery.root) / f"{session_id}.{delivery.suffix}.json"
        paths.append((sidecar, sidecar.with_suffix(".lock")))
    continuation_root = Path(task_continuation_delivery.root)
    continuation = continuation_root / f"{session_id}.continuation.json"
    paths.append((continuation, continuation_root / f"{session_id}.continuation.lock"))
    paths.append((continuation.with_suffix(".receipt-backoff.json"), continuation_root / f"{session_id}.continuation.lock"))

    for sidecar, lock_path in paths:
        if not sidecar.exists():
            continue
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                sidecar.unlink(missing_ok=True)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def _reset_workspace_runtime_sessions(
    sessions: list[dict[str, str]], principal: Principal, workspace_id: str,
) -> None:
    for item in sessions:
        live = product_sessions.find_owned(item["conversation_id"], principal)
        if live is not None and (
                live.workspace_id != workspace_id or live.session_id != item["session_id"]
                or live.trace_id != item["trace_id"]):
            raise HTTPException(status_code=502, detail="Gateway session binding does not match Backend reset receipt")
        _workspace_runtime_reset_adapter_session(item["session_id"], item["trace_id"])
        # Both registry eviction and local projection cleanup happen only after
        # the Adapter confirms release (or confirms the already-fenced session is absent).
        product_sessions.remove_owned(item["conversation_id"], principal)
        _delete_workspace_runtime_sidecars(item["session_id"])


def _validate_runtime_authority_receipt(body: object, boot_id: str) -> int:
    if not isinstance(body, dict) or set(body) != {"receipt"}:
        raise RuntimeError("Backend runtime authority receipt is invalid")
    receipt = body["receipt"]
    if (not isinstance(receipt, dict)
            or set(receipt) != {"schema_version", "boot_id", "authority_epoch", "revoked_root_count",
                               "revoked_agent_run_count", "status"}
            or receipt.get("schema_version") != RUNTIME_AUTHORITY_RECEIPT_SCHEMA
            or receipt.get("boot_id") != boot_id or receipt.get("status") != "current"
            or type(receipt.get("authority_epoch")) is not int or receipt["authority_epoch"] < 1
            or type(receipt.get("revoked_root_count")) is not int or receipt["revoked_root_count"] < 0
            or type(receipt.get("revoked_agent_run_count")) is not int
            or receipt["revoked_agent_run_count"] < 0):
        raise RuntimeError("Backend runtime authority receipt is invalid")
    return receipt["authority_epoch"]


def _validate_runtime_authority_current(body: object, boot_id: str, authority_epoch: int) -> None:
    if (not isinstance(body, dict)
            or set(body) != {"schema_version", "boot_id", "authority_epoch", "status"}
            or body.get("schema_version") != RUNTIME_AUTHORITY_CURRENT_SCHEMA
            or body.get("boot_id") != boot_id or body.get("authority_epoch") != authority_epoch
            or body.get("status") != "current"):
        raise RuntimeError("Backend runtime authority does not match the Adapter boot")


def _sync_runtime_authority() -> dict[str, object]:
    """Fence the Adapter process boot in Backend before Agent mutations are admitted."""
    with _runtime_authority_sync_lock:
        try:
            adapter = _adapter_authority()
            boot_id = adapter["boot_id"]
            previous = _runtime_authority_snapshot()
            if previous.get("ready") is True and previous.get("boot_id") == boot_id:
                current = _backend_runtime_authority_request("GET", "/internal/runtime-authority/current")
                _validate_runtime_authority_current(
                    current, boot_id, previous["authority_epoch"],
                )
                return {"boot_id": boot_id, "authority_epoch": previous["authority_epoch"]}
            response = _backend_runtime_authority_request("POST", "/internal/runtime-authority/boot", {
                "schema_version": RUNTIME_AUTHORITY_BOOT_SCHEMA,
                "boot_id": boot_id,
            })
            authority_epoch = _validate_runtime_authority_receipt(response, boot_id)
            current = _backend_runtime_authority_request("GET", "/internal/runtime-authority/current")
            _validate_runtime_authority_current(current, boot_id, authority_epoch)
        except Exception:
            _set_runtime_authority_state(ready=False)
            raise
        _set_runtime_authority_state(ready=True, boot_id=boot_id, authority_epoch=authority_epoch)
        return {"boot_id": boot_id, "authority_epoch": authority_epoch}


def _require_session_runtime_authority(session: ProductSession) -> str:
    snapshot = _runtime_authority_snapshot()
    if (snapshot.get("ready") is not True or not _valid_runtime_boot_id(session.boot_id)
            or session.boot_id != snapshot.get("boot_id")):
        raise HTTPException(status_code=503, detail="Agent session authority is not current")
    return session.boot_id


def _continuation_adapter_get(path: str, params=None) -> dict:
    response = httpx.get(f'{RUNTIME_ADAPTER_URL}{path}', params=params, timeout=5.0)
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError('invalid continuation adapter receipt')
    return value


def _adapter_containment(runtime_session_id: str) -> dict | None:
    """Adapter process loss has no durable containment evidence to fetch."""

    return None


def _session_containment_projection(
    request: Request,
    *,
    conversation_id: str,
    runtime_session_id: str,
    trace_id: str,
    principal_subject: str,
    workspace_id: str,
    conversation: object,
    events: object,
    fetch_adapter: bool = True,
) -> dict:
    """Read-only containment projection with independently verified authority.

    No prompt is submitted and no attempt is created. When the authority cannot
    be verified the projection pauses and, unless ``fetch_adapter`` is set, does
    not even read the adapter.
    """

    authority = _recovery_authority(
        request, principal_subject=principal_subject, workspace_id=workspace_id,
        conversation=conversation)
    preservation = preservation_projection(
        conversation_known=isinstance(conversation, dict) and bool(conversation.get("conversation_id")),
        trace_known=isinstance(events, list), authority=authority)
    return project_containment(
        events, session_id=runtime_session_id, trace_id=trace_id,
        conversation_id=conversation_id,
        adapter_containment=_adapter_containment(runtime_session_id) if fetch_adapter else None,
        authority=authority, preservation=preservation,
    )


def _recovery_authority(
    request: Request, *, principal_subject: str, workspace_id: str, conversation: object,
) -> dict:
    """Verify recovery authority from existing authoritative components.

    Each item is tri-state: ``True`` verified, ``False`` authoritatively denied,
    ``None`` unknown/unavailable. Missing or ambiguous authority is never
    treated as allowed. No new authority is introduced: owner/workspace come from
    the owner-scoped Product catalog and the durable Backend auth session.
    """

    result: dict[str, object] = {
        "owner_matches": None, "workspace_matches": None,
        "authorization_current": None, "budget_available": None,
        "source": "unavailable",
    }
    owner = conversation.get("owner_principal") if isinstance(conversation, dict) else None
    if isinstance(owner, str):
        result["owner_matches"] = owner == principal_subject
    if "byq_session" in request.cookies:
        try:
            user = resolve_user(request)
        except ProductAuthError:
            result["authorization_current"] = False
            result["workspace_matches"] = False
            result["source"] = "backend-auth-session"
        else:
            workspace = user.get("_workspace")
            current_workspace = workspace.get("workspace_id") if isinstance(workspace, dict) else None
            result["authorization_current"] = user.get("status") == "active"
            result["workspace_matches"] = (
                isinstance(current_workspace, str) and current_workspace == workspace_id)
            result["source"] = "backend-auth-session"
    # An arbitrary unanswered turn has no authoritative task/budget binding, so
    # budget availability is unknown and must never be defaulted to allowed.
    result["budget_available"] = None
    return result


def _consume_task_continuation(context):
    try:
        require_runtime_authority()
    except HTTPException:
        return
    with chat_admission():
        _consume_admitted_task_continuation(context)


def _attach_continuation_observer(context):
    principal = Principal(subject=context['owner'])
    try:
        return product_sessions.get_owned(context['conversation_id'], principal)
    except HTTPException:
        pass
    # Observe an existing original Runtime after a Gateway restart. Do not
    # create a replacement process merely to reconcile an uncertain receipt.
    state = _continuation_adapter_get(
        f"/internal/runtime/sessions/{context['session_id']}/continuation-qualification")
    if state.get('reason') == 'session_missing':
        return None
    product_sessions.remove_owned(context['conversation_id'], principal)
    return _restore_product_session(context['conversation_id'], principal, context['workspace_id'])


def _consume_admitted_task_continuation(context):
    principal = Principal(subject=context['owner'])
    conversation = context['conversation_id']
    workspace = context['workspace_id']
    def backend(suffix, payload=None, task=None):
        return _catalog_request('POST', f'/internal/task-continuation/{task or conversation}/{suffix}',
            principal, workspace, payload=payload)
    intent = backend('peek')
    if intent.get('status') == 'eligible':
        try:
            session = product_sessions.get_owned(conversation, principal)
        except HTTPException:
            product_sessions.remove_owned(conversation, principal)
            session = _restore_product_session(conversation, principal, workspace)
        if session.session_id != context['session_id']:
            raise ValueError('continuation original session identity mismatch')
        qualification = _continuation_adapter_get(
            f'/internal/runtime/sessions/{session.session_id}/continuation-qualification')
        # A lost original Runtime is unqualified. Live-only Gateway attachment
        # may observe an existing process; it never grants a replacement turn.
        if qualification.get('qualified') is not True:
            backend('block', {'reason': 'model_or_executor_unqualified'}, task=intent['task_id'])
            return
        intent = backend('claim')
    if intent.get('status') != 'intent':
        return
    if (intent.get('conversation_id'), intent.get('session_id'), intent.get('trace_id')) != (
            conversation, context['session_id'], context['trace_id']):
        raise ValueError('continuation conversation identity changed')
    reservation, receipt = intent['reservation'], intent['receipt']
    if not isinstance(reservation, dict):
        raise ValueError('invalid continuation reservation')
    identity = reservation['reservation_id']
    task = intent['task_id']
    if (receipt.get('reservation_id') != identity or reservation.get('task_id') != task
            or reservation.get('owner') != context['owner']
            or reservation.get('workspace_id') != workspace):
        raise ValueError('continuation reservation identity mismatch')
    observer = _attach_continuation_observer(context)
    if observer is not None:
        if observer.session_id != intent['session_id']:
            raise ValueError('continuation original session identity mismatch')
        _require_session_runtime_authority(observer)
    if observer is not None:
        if not product_sessions.hold_continuation(observer, identity, reservation['expires_at']):
            return
        generation = product_sessions.idle_release_generation(observer)
        if generation is not None:
            _schedule_idle_release(observer, generation)
    def mark(status, **fields):
        return backend('receipt', {'reservation_id': identity, 'status': status, **fields}, task=task)
    settled = _continuation_adapter_get(
        f"/internal/runtime/sessions/{intent['session_id']}/continuation-receipt/{identity}")
    if settled.get('reservation_id') != identity:
        raise ValueError('continuation settlement identity mismatch')
    if settled.get('status') == 'settled':
        if not _valid_prompt_run_id(settled.get('run_id')):
            raise ValueError('invalid continuation settlement run identity')
        if reservation.get('schema_version') == RESERVATION_SCHEMA_VERSION:
            usage = validate_request_usage(settled.get('request_usage'))
            validate_profile_binding(reservation.get('execution_profile'))
            validate_limits(reservation.get('request_limits'))
            if usage['execution_profile'] != reservation['execution_profile']:
                raise ValueError('continuation settlement profile mismatch')
            fields = {'request_usage': usage}
        else:
            # Historical liabilities remain reconcilable, never dispatchable.
            fields = {'charged_tokens': settled['charged_tokens']}
        mark('accepted', run_id=settled['run_id'])
        mark('settled', **fields, settlement_sha256=settled['settlement_sha256'],
            outcome=settled['outcome'])
        if observer is not None:
            product_sessions.finish_continuation(observer, identity)
            generation = product_sessions.idle_release_generation(observer)
            if generation is not None:
                _schedule_idle_release(observer, generation)
        return
    if (reservation.get('schema_version') != RESERVATION_SCHEMA_VERSION
            and settled.get('status') == 'accepted' and type(settled.get('charged_tokens')) is int
            and receipt.get('status') != 'settled' and receipt.get('run_id')):
        # Bind the Adapter's exact durable guard charge for the lost original
        # attempt before any recovery decision; an unreadable guard stays unknown.
        mark('accepted', run_id=receipt['run_id'], charged_tokens=settled['charged_tokens'])
    instruction = receipt['instruction']
    identity_content = json.dumps({'content': instruction, 'reservation': reservation}, sort_keys=True, separators=(',', ':'))
    original = _continuation_adapter_get(f"/internal/runtime/sessions/{intent['session_id']}/prompts/reconcile",
        params={'idempotency_key': identity, 'content_sha256': hashlib.sha256(identity_content.encode()).hexdigest()})
    if original.get('state') == 'accepted':
        mark('accepted', run_id=original['run_id'])
        return
    # Interrupted accepted turns stay unresolved after exact reconciliation.
    # A stale carrier from an earlier Gateway recovery path is not prompt authority.
    if reservation.get('schema_version') != RESERVATION_SCHEMA_VERSION or 'recovery_attempt' in reservation:
        return
    if receipt['status'] != 'reserved' or intent.get('may_dispatch') is not True:
        return
    validate_profile_binding(reservation.get('execution_profile'))
    validate_limits(reservation.get('request_limits'))
    try:
        session = product_sessions.get_owned(conversation, principal)
    except HTTPException:
        product_sessions.remove_owned(conversation, principal)
        session = _restore_product_session(conversation, principal, workspace)
    if session.session_id != intent['session_id']:
        raise ValueError('continuation original session identity mismatch')
    _require_session_runtime_authority(session)
    if observer is not session:
        if not product_sessions.hold_continuation(session, identity, reservation['expires_at']):
            return
        observer = session
        generation = product_sessions.idle_release_generation(observer)
        if generation is not None:
            _schedule_idle_release(observer, generation)
    payload = {'content': instruction, 'require_model_key': True, 'idempotency_key': identity,
        'continuation_budget': reservation, **_runtime_conversation_payload(session)}
    if backend('dispatch', {'reservation_id': identity}, task=task).get('dispatch') is not True:
        return
    require_runtime_authority()
    _require_session_runtime_authority(session)
    try:
        accepted = _adapter_post(f'/internal/runtime/sessions/{session.session_id}/prompt', payload=payload, timeout=5.0)
    except HTTPException as exc:
        # Original identity is checked before Runtime's admission conflicts.
        # A definite pre-accept conflict is recorded. Backend's one-shot request
        # never reopens this dispatched identity for another prompt.
        # Ambiguous transport failures remain unknown and are only reconciled.
        if exc.status_code == 409:
            detail = getattr(exc, 'adapter_conflict_detail', '')
            category = ('domain_cleanup' if detail == 'previous turn domain cleanup is not yet acknowledged'
                else 'process_cleanup' if detail == 'previous runtime process cleanup is not complete'
                else 'running' if detail == f'session {session.session_id} cannot accept a prompt in state running'
                else 'other')
            logger.warning('task continuation prompt rejected: category=%s', category)
            # Unknown categories include reused identity conflicts: a prior
            # run may already exist. Preserve liability and only reconcile.
            if category == 'other':
                return
            mark('rejected')
            if observer is not None:
                product_sessions.finish_continuation(observer, identity)
                generation = product_sessions.idle_release_generation(observer)
                if generation is not None:
                    _schedule_idle_release(observer, generation)
        return
    if accepted.get('accepted') is not True or not _valid_prompt_run_id(accepted.get('run_id')):
        return
    mark('accepted', run_id=accepted['run_id'])


def _send_agent_lifecycle(context, event, *, expected_boot_id=None):
    require_runtime_authority()
    snapshot = _runtime_authority_snapshot()
    if (expected_boot_id is not None
            and (not _valid_runtime_boot_id(expected_boot_id)
                 or snapshot.get("boot_id") != expected_boot_id)):
        raise RuntimeError("lifecycle event belongs to a superseded Adapter boot")
    if event["outcome"] == "active":
        # Active registration still uses the existing Backend business path;
        # it opens the exact root for domain-call admission. A durable old
        # event has no authority to re-open a root after its Adapter boot was
        # fenced, so require the original in-process session boot binding.
        session = product_sessions.find_owned(
            context["conversation_id"], Principal(subject=context["owner"]),
        )
        if (session is None or not _valid_runtime_boot_id(session.boot_id)
                or session.boot_id != snapshot.get("boot_id")):
            raise RuntimeError("active lifecycle event has no current Adapter boot binding")
        reply = _catalog_request("POST", f"/internal/agent-lifecycle/{context['conversation_id']}",
            Principal(subject=context["owner"]), context["workspace_id"], payload={
                "session_id": context["session_id"], "trace_id": context["trace_id"],
                "event": event}, runtime_boot_id=session.boot_id)
        if reply != {"receipt": lifecycle_receipt(event)}:
            raise ValueError("lifecycle receipt mismatch")
        return reply

    session = product_sessions.find_owned(
        context["conversation_id"], Principal(subject=context["owner"]),
    )
    boot_id = expected_boot_id or (session.boot_id if session is not None else snapshot.get("boot_id"))
    if snapshot.get("ready") is not True or not _valid_runtime_boot_id(boot_id):
        raise RuntimeError("runtime authority is unavailable for terminal close")
    if session is not None and session.boot_id != snapshot.get("boot_id"):
        raise RuntimeError("terminal belongs to a superseded Adapter boot")

    evidence = _adapter_get(
        f"/internal/runtime/sessions/{context['session_id']}/terminal-evidence",
        params={"root_run_id": event["root_run_id"], "boot_id": boot_id},
        timeout=5.0,
    )
    receipt = evidence.get("receipt") if isinstance(evidence, dict) else None
    if (not isinstance(evidence, dict)
            or set(evidence) != {"schema_version", "session_id", "boot_id", "root_run_id", "sequence",
                                 "outcome", "receipt"}
            or evidence.get("schema_version") != RUNTIME_TERMINAL_EVIDENCE_SCHEMA
            or evidence.get("session_id") != context["session_id"]
            or evidence.get("boot_id") != boot_id
            or evidence.get("root_run_id") != event["root_run_id"]
            or evidence.get("sequence") != event["sequence"]
            or evidence.get("outcome") != event["outcome"]
            or receipt != lifecycle_receipt(event)):
        raise ValueError("Adapter terminal evidence does not match the exact lifecycle event")

    closed = _backend_runtime_authority_request(
        "POST",
        f"/internal/runtime-authority/roots/{event['root_run_id']}/close",
        {
            "schema_version": RUNTIME_ROOT_CLOSE_SCHEMA,
            "boot_id": boot_id,
            "sequence": event["sequence"],
            "outcome": event["outcome"],
            "event_sha256": receipt["event_sha256"],
        },
    )
    if closed != {"receipt": receipt}:
        raise ValueError("Backend root close receipt does not match Adapter terminal evidence")

    # The Adapter barrier is released only after Backend has confirmed the
    # exact event digest. Retry this exact receipt in place: replaying the
    # whole close after a lost ACK response may outlive Adapter's live record.
    for attempt in range(TRACE_LIFECYCLE_SEND_ATTEMPTS):
        try:
            authority = _adapter_authority()
        except RuntimeError:
            if attempt + 1 >= TRACE_LIFECYCLE_SEND_ATTEMPTS:
                raise
        else:
            if authority["boot_id"] != boot_id:
                raise RuntimeError("terminal belongs to a superseded Adapter boot")
            try:
                acknowledged = _adapter_post(
                    f"/internal/runtime/sessions/{context['session_id']}/terminal-receipt",
                    payload=closed, timeout=5.0)
            except HTTPException as exc:
                retryable = exc.status_code in {408, 429} or exc.status_code >= 500
                if not retryable or attempt + 1 >= TRACE_LIFECYCLE_SEND_ATTEMPTS:
                    raise
            except httpx.HTTPError:
                if attempt + 1 >= TRACE_LIFECYCLE_SEND_ATTEMPTS:
                    raise
            else:
                if acknowledged != closed:
                    raise ValueError("runtime terminal acknowledgement mismatch")
                return closed
        if attempt + 1 < TRACE_LIFECYCLE_SEND_ATTEMPTS:
            time.sleep(TRACE_RETRY_DELAY_SECONDS * (attempt + 1))
    raise RuntimeError("runtime terminal acknowledgement remains unconfirmed")


def _reconcile_research_receipts(context):
    return _catalog_request('POST', f"/internal/research-receipts/{context['conversation_id']}/reconcile",
        Principal(subject=context['owner']), context['workspace_id'],
        payload={'session_id':context['session_id'],'trace_id':context['trace_id']})


task_continuation_delivery = TaskContinuationDelivery(
    os.environ.get("BYQ_WORKFLOW_TRACE_ROOT", "/tmp/byq-workflow-traces"), _consume_task_continuation,
    reconcile=_reconcile_research_receipts)


def _send_owned_answer(context, event):
    session = ProductSession(conversation_id=context["conversation_id"], session_id=context["session_id"],
        trace_id=context["trace_id"], principal=Principal(subject=context["owner"]), workspace_id=context["workspace_id"])
    if not _persist_projected_answer(session, {"kind": "agent.output.delta", "sequence": event["sequence"],
                                              "payload": {"delta": event["content"]}}):
        raise ValueError("public answer persistence remains unconfirmed")
    return {"receipt": answer_delivery.receipt(event)}


answer_delivery = LifecycleDelivery(
    os.environ.get("BYQ_WORKFLOW_TRACE_ROOT", "/tmp/byq-workflow-traces"), trace_store, _send_owned_answer, answers=True)


def _read_domain_calls(context, cursor):
    return _adapter_post(f"/internal/runtime/sessions/{context['session_id']}/domain-call-evidence", payload={
        "trace_id": context["trace_id"], "owner": context["owner"], "workspace_id": context["workspace_id"],
        "after_sequence": cursor}, timeout=5.0)


def _send_domain_call(context, event):
    require_runtime_authority()
    session = product_sessions.find_owned(
        context["conversation_id"], Principal(subject=context["owner"]),
    )
    if session is None:
        raise RuntimeError("domain call evidence has no current Adapter session")
    boot_id = _require_session_runtime_authority(session)
    reply = _catalog_request("POST", f"/internal/domain-call-evidence/{context['conversation_id']}",
        Principal(subject=context["owner"]), context["workspace_id"], payload={
            "session_id": context["session_id"], "trace_id": context["trace_id"], "event": event},
        runtime_boot_id=boot_id)
    expected = {"receipt": call_evidence_receipt(event)}
    if reply != expected:
        raise ValueError("Backend private evidence receipt mismatch")
    acknowledged = _adapter_post(
        f"/internal/runtime/sessions/{context['session_id']}/domain-call-receipt",
        payload={"trace_id": context["trace_id"], "owner": context["owner"],
                 "workspace_id": context["workspace_id"], "receipt": reply["receipt"]},
        timeout=5.0)
    if acknowledged != expected:
        raise ValueError("Adapter private evidence acknowledgement mismatch")
    return reply


domain_call_delivery = LifecycleDelivery(
    os.environ.get("BYQ_WORKFLOW_TRACE_ROOT", "/tmp/byq-workflow-traces"), trace_store,
    _send_domain_call, private_source=_read_domain_calls)


def require_chat_admission():
    with chat_admission():
        yield


@app.exception_handler(AdmissionClosed)
async def admission_closed_handler(request: Request, exc: AdmissionClosed) -> JSONResponse:
    return JSONResponse(status_code=503, headers={"Retry-After": "30"}, content={"error": {
        "code": "chat_maintenance", "message": "小巴正在维护，输入已保留，请稍后重试。",
        "request_id": uuid.uuid4().hex,
    }})


@app.exception_handler(ProductError)
async def product_error_handler(request: Request, exc: ProductError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": exc.request_id,
            }
        },
    )


@app.exception_handler(ProductAuthError)
async def product_auth_error_handler(request: Request, exc: ProductAuthError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": uuid.uuid4().hex,
            }
        },
    )


class ProductPromptRequest(BaseModel):
    content: str = Field(min_length=1, max_length=12_000)


class ProductCancelRequest(BaseModel):
    mode: str = Field(default="hard", pattern="^(soft|hard)$")


class ProductSessionUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)
    pinned: bool | None = None
    status: str | None = Field(default=None, pattern="^(active|archived)$")


@dataclass(slots=True)
class ProductSession:
    conversation_id: str
    session_id: str
    trace_id: str
    principal: Principal
    workspace_id: str = "workspace_bootstrap_unresolved"
    boot_id: str | None = None
    released: bool = False
    public_streams: int = 0
    release_generation: int = 0
    release_timer: threading.Timer | None = None
    continuation_reservation: str | None = None
    continuation_deadline: float = 0


class ProductSessionRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, ProductSession] = {}

    def add(self, session: ProductSession) -> None:
        with self._lock:
            if session.conversation_id in self._sessions:
                raise RuntimeError("generated session identifier collision")
            self._sessions[session.conversation_id] = session

    def get_owned(self, conversation_id: str, principal: Principal) -> ProductSession:
        with self._lock:
            session = self._sessions.get(conversation_id)
        # Do not reveal whether another principal owns a session.
        if session is None or session.principal.subject != principal.subject:
            raise HTTPException(status_code=404, detail="product session not found")
        if session.released:
            raise HTTPException(status_code=409, detail="product session is closed")
        return session

    def begin_stream(self, session: ProductSession) -> None:
        with self._lock:
            session.release_generation += 1
            session.public_streams += 1
            if session.release_timer is not None:
                session.release_timer.cancel()
                session.release_timer = None

    def end_stream(self, session: ProductSession) -> int | None:
        with self._lock:
            session.public_streams = max(0, session.public_streams - 1)
            if session.released or session.public_streams:
                return None
            session.release_generation += 1
            return session.release_generation

    def idle_release_generation(self, session: ProductSession) -> int | None:
        """Background completion does not decrement a browser stream lease."""
        with self._lock:
            if session.released or session.public_streams:
                return None
            if session.release_timer is not None:
                session.release_timer.cancel()
                session.release_timer = None
            session.release_generation += 1
            return session.release_generation

    def hold_continuation(self, session: ProductSession, reservation_id: str, expires_at: str) -> bool:
        """Keep the original session through its fixed admitted turn deadline.

        This is only an idle-release lease, not spend or execution authority.
        Receipt polling cannot extend a reservation's monotonic lease.
        """
        expiry = datetime.fromisoformat(expires_at)
        if expiry.tzinfo is None:
            raise ValueError('continuation expiry requires a timezone')
        remaining = max(0, min(86400, (expiry - datetime.now(timezone.utc)).total_seconds()))
        with self._lock:
            if session.released:
                return False
            if session.continuation_reservation != reservation_id:
                session.continuation_reservation = reservation_id
                session.continuation_deadline = time.monotonic() + remaining + 5
            session.release_generation += 1
            if session.release_timer is not None:
                session.release_timer.cancel()
                session.release_timer = None
            return True

    def finish_continuation(self, session: ProductSession, reservation_id: str) -> None:
        with self._lock:
            if session.continuation_reservation == reservation_id:
                session.continuation_reservation = None
                session.continuation_deadline = 0

    def idle_release_delay(self, session: ProductSession) -> float:
        with self._lock:
            if session.continuation_reservation is not None:
                return max(0, session.continuation_deadline + RUNTIME_SESSION_IDLE_SECONDS - time.monotonic())
            return RUNTIME_SESSION_IDLE_SECONDS

    def attach_release_timer(self, session: ProductSession, generation: int, timer: threading.Timer) -> bool:
        with self._lock:
            if session.released or session.public_streams or session.release_generation != generation:
                return False
            session.release_timer = timer
            return True

    def claim_idle_release(self, session: ProductSession, generation: int) -> bool:
        with self._lock:
            if (session.released or session.public_streams or session.release_generation != generation
                    or session.continuation_deadline > time.monotonic()):
                return False
            session.released = True
            session.release_timer = None
            return True

    def restore_failed_release(self, session: ProductSession) -> int | None:
        with self._lock:
            session.released = False
            if session.public_streams:
                return None
            session.release_generation += 1
            return session.release_generation

    def mark_released(self, conversation_id: str, principal: Principal) -> ProductSession:
        session = self.get_owned(conversation_id, principal)
        with self._lock:
            session.released = True
        return session

    def find_owned(self, conversation_id: str, principal: Principal) -> ProductSession | None:
        with self._lock:
            session = self._sessions.get(conversation_id)
        if session is None or session.principal.subject != principal.subject:
            return None
        return session

    def remove_owned(self, conversation_id: str, principal: Principal) -> None:
        with self._lock:
            session = self._sessions.get(conversation_id)
            if session is None or session.principal.subject != principal.subject:
                return
            session.released = True
            if session.release_timer is not None:
                session.release_timer.cancel()
            del self._sessions[conversation_id]

    def list_owned(self, principal: Principal) -> list[ProductSession]:
        with self._lock:
            return [
                session
                for session in self._sessions.values()
                if session.principal.subject == principal.subject and not session.released
            ]


product_sessions = ProductSessionRegistry()


class _AsyncTraceBridge:
    """Forward the blocking TraceStore iterator without consuming an AnyIO worker token."""

    def __init__(self, events: Iterator[dict[str, object] | None]) -> None:
        self._events = events
        self._loop = asyncio.get_running_loop()
        self._end = object()
        self._items: asyncio.Queue[object] = asyncio.Queue()
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._pump, name="byq-public-sse", daemon=True)
        self._thread.start()

    def _put(self, item: object) -> None:
        try:
            self._loop.call_soon_threadsafe(self._items.put_nowait, item)
        except RuntimeError:
            return

    def _pump(self) -> None:
        try:
            for item in self._events:
                if self._stopped.is_set():
                    return
                self._put(item)
        except BaseException as exc:
            self._put(exc)
        finally:
            self._put(self._end)

    async def get(self) -> tuple[bool, dict[str, object] | None]:
        item = await self._items.get()
        if item is self._end:
            return False, None
        if isinstance(item, BaseException):
            raise item
        return True, item if isinstance(item, dict) else None

    def close(self) -> None:
        self._stopped.set()


def _schedule_idle_release(session: ProductSession, generation: int | None = None) -> None:
    if generation is None:
        generation = product_sessions.end_stream(session)
    if generation is None:
        return

    def release() -> None:
        if not product_sessions.claim_idle_release(session, generation):
            return
        try:
            _adapter_post(f"/internal/runtime/sessions/{session.session_id}/release", timeout=5.0)
        except HTTPException as exc:
            if exc.status_code == 404:
                product_sessions.remove_owned(session.conversation_id, session.principal)
                trace_store.close(session.session_id)
                return
            retry_generation = product_sessions.restore_failed_release(session)
            if retry_generation is not None:
                _schedule_idle_release(session, retry_generation)
            return
        product_sessions.remove_owned(session.conversation_id, session.principal)

    timer = threading.Timer(product_sessions.idle_release_delay(session), release)
    timer.daemon = True
    if product_sessions.attach_release_timer(session, generation, timer):
        timer.start()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {
        "service": SERVICE,
        "status": "ok",
        "version": VERSION,
    }


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {
        "service": SERVICE,
        "status": "ok",
        "version": VERSION,
        "dsh_runtime_integration": "runtime-adapter",
        "product_authentication": "configured" if PRODUCT_TOKEN else "missing",
    }


@app.get("/agent-readyz")
def agent_readyz() -> dict[str, str]:
    require_runtime_authority()
    return {"service": SERVICE, "status": "ready"}


def _authenticate(authorization: str | None) -> Principal:
    try:
        return authenticate_bearer(
            authorization,
            configured_token=PRODUCT_TOKEN,
            subject=PRODUCT_PRINCIPAL,
        )
    except AuthenticationUnavailable as exc:
        raise HTTPException(status_code=503, detail="product authentication is unavailable") from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=401,
            detail="product authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _authenticate_request(request: Request) -> Principal:
    if "byq_session" in request.cookies:
        try:
            return resolve_principal(request)
        except ProductAuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _authenticate(request.headers.get("authorization"))


def _trusted_request_identity(request: Request) -> tuple[Principal, str]:
    if "byq_session" in request.cookies:
        try:
            user = resolve_user(request)
        except ProductAuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        workspace = user.get("_workspace")
        if not isinstance(workspace, dict) or not isinstance(workspace.get("workspace_id"), str):
            raise HTTPException(status_code=401, detail="personal workspace context required")
        principal = Principal(subject=str(user.get("username") or user.get("user_id")))
        return principal, workspace["workspace_id"]
    return _authenticate_request(request), os.environ.get(
        "BYQ_PRODUCT_WORKSPACE_ID", "workspace_bootstrap_unresolved"
    )


class PromptAdmissionRejected(HTTPException):
    """Only constructed after checking an exact Runtime pre-admission receipt."""


def _adapter_post(path: str, *, payload: dict[str, object] | None = None, timeout: float = 20.0) -> dict[str, object]:
    try:
        response = httpx.post(
            f"{RUNTIME_ADAPTER_URL}{path}",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        detail = "runtime adapter rejected the request"
        if status == 409:
            detail = "runtime session is not available for this operation"
            # Keep the private adapter reason off the product response, but
            # retain it so a transient new-root race can be retried instead of
            # being reported as a terminal continuation failure.
            try:
                rejected_conflict = exc.response.json()
            except ValueError:
                rejected_conflict = None
            if isinstance(rejected_conflict, dict) and isinstance(rejected_conflict.get("detail"), str):
                error = HTTPException(status_code=status, detail=detail)
                error.adapter_conflict_detail = rejected_conflict["detail"]
                raise error from exc
        elif status == 503:
            detail = "product model is unavailable"
            prefix = "/internal/runtime/sessions/"
            if (path.startswith(prefix) and path.endswith("/prompt") and isinstance(payload, dict)
                    and payload.get("require_model_key") is True):
                try:
                    rejected = exc.response.json()
                except ValueError:
                    rejected = None
                if (isinstance(rejected, dict) and set(rejected) == {"detail"}
                        and matches_credential_rejection(rejected["detail"], path[len(prefix):-len("/prompt")],
                            payload.get("idempotency_key"), payload.get("content"))):
                    raise PromptAdmissionRejected(status_code=503, detail=detail) from exc
        raise HTTPException(status_code=status, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="runtime adapter unavailable") from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="runtime adapter returned an invalid response") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="runtime adapter returned an invalid response")
    return body


def _adapter_get(path: str, *, params: dict[str, object] | None = None,
                 timeout: float = 20.0) -> dict[str, object]:
    try:
        response = httpx.get(f"{RUNTIME_ADAPTER_URL}{path}", params=params, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code,
                            detail="runtime adapter evidence is unavailable") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="runtime adapter unavailable") from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="runtime adapter returned an invalid response") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="runtime adapter returned an invalid response")
    return body


def _valid_prompt_run_id(value: object) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 128 and value.strip() == value and bool(value.strip())


def _adapter_prompt_receipt(session_id: str, key: str, content: str) -> dict[str, object] | None:
    """One exact read; missing ephemeral state is unknown, never resubmit permission."""
    try:
        response = httpx.get(f"{RUNTIME_ADAPTER_URL}/internal/runtime/sessions/{session_id}/prompts/reconcile",
            params={"idempotency_key": key, "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()},
            timeout=2.0)
        response.raise_for_status()
        body = response.json()
        if (isinstance(body, dict) and body.get("schema_version") == "prompt-receipt.v1"
                and body.get("state") == "accepted" and _valid_prompt_run_id(body.get("run_id"))):
            return body
    except (httpx.HTTPError, ValueError):
        pass
    return None


def _start_trace_collector(session: ProductSession) -> None:
    task_continuation_delivery.register(session)
    domain_call_delivery.register(session)
    _register_answer_delivery(session)
    thread = threading.Thread(
        target=_collect_trace,
        args=(session,),
        name=f"byq-workflow-trace-{session.session_id}",
        daemon=True,
    )
    thread.start()


def _collect_trace(session: ProductSession) -> None:
    """Persist only the adapter's BYQ event envelopes for this product session."""

    persisted = trace_store.read(session.session_id)
    cursor = max((event["sequence"] for event in persisted), default=0)
    lifecycle_context = {
        "session_id": session.session_id, "trace_id": session.trace_id,
        "conversation_id": session.conversation_id,
        "workspace_id": session.workspace_id, "owner": session.principal.subject,
    }
    # A rebind after an idle release or restart must be able to append the
    # Runtime's continuation at exactly persisted+1. Reopen the durable trace
    # so a prior close cannot suppress the rehydrated stream.
    trace_store.reopen(session.session_id)
    # Delivery to the conversation catalog is independent of SSE ingestion.
    # Retry the durable BYQ projection even if the adapter has lost this session
    # or no longer replays its old events. Backend deduplicates workflow_sequence.
    _register_answer_delivery(session)
    try:
        _collect_trace_events(session, lifecycle_context, cursor)
    finally:
        if session.released:
            trace_store.close(session.session_id)


def _collect_trace_events(session: ProductSession, lifecycle_context: dict[str, str], cursor: int) -> None:
    endpoint = f"{RUNTIME_ADAPTER_URL}/internal/runtime/sessions/{session.session_id}/events"
    reconnect = 0
    last_sent_lifecycle_sequence = 0
    while not session.released:
        reconnect_required = False
        try:
            if session.released:
                return
            authority = _adapter_authority()
            if (not _valid_runtime_boot_id(session.boot_id)
                    or authority["boot_id"] != session.boot_id):
                return
            with httpx.stream(
                "GET", endpoint, params={"replay": "true"}, timeout=None,
            ) as response:
                if response.status_code != 200:
                    if response.status_code in {408, 429} or response.status_code >= 500:
                        reconnect_required = True
                    else:
                        return
                else:
                    for line in response.iter_lines():
                        if isinstance(line, bytes):
                            line = line.decode("utf-8")
                        if not line.startswith("data: "):
                            continue
                        try:
                            event = json.loads(line[6:])
                            if (not isinstance(event, dict) or event.get("session_id") != session.session_id
                                    or event.get("trace_id") != session.trace_id):
                                continue
                            sequence = event.get("sequence")
                            if type(sequence) is not int:
                                continue
                            if sequence > cursor:
                                projected = project_workflow_event(
                                    event,
                                    backend_get=lambda path: _domain_get(path, session),
                                    revision_for=lambda card_id: trace_store.next_card_revision(
                                        session.session_id,
                                        card_id,
                                    ),
                                )
                                try:
                                    trace_store.append(projected)
                                except TraceConflict:
                                    return
                                cursor = sequence
                            # Lifecycle send is tied to this live Adapter stream,
                            # even when a Gateway restart already persisted the trace.
                            lifecycle = project_lifecycle_event(event, session.session_id, session.trace_id)
                        except (ValueError, TypeError, json.JSONDecodeError):
                            # Invalid Adapter data is neither persisted nor reflected to clients.
                            continue
                        if lifecycle is None:
                            continue
                        if sequence <= last_sent_lifecycle_sequence:
                            continue
                        sent = False
                        for attempt in range(TRACE_LIFECYCLE_SEND_ATTEMPTS):
                            try:
                                _send_agent_lifecycle(
                                    lifecycle_context, lifecycle, expected_boot_id=session.boot_id,
                                )
                                sent = True
                                last_sent_lifecycle_sequence = sequence
                                break
                            except (HTTPException, ValueError, RuntimeError, httpx.HTTPError):
                                if session.released:
                                    return
                                if attempt + 1 < TRACE_LIFECYCLE_SEND_ATTEMPTS:
                                    time.sleep(TRACE_RETRY_DELAY_SECONDS * (attempt + 1))
                        if not sent:
                            # Replay only from the still-live Adapter stream. The
                            # authority check in the sender fences a replaced boot.
                            reconnect_required = True
                            break
                    if not session.released:
                        # A live event stream should remain open for the next
                        # root. Reopen a prematurely ended subscription within
                        # this same Adapter boot.
                        reconnect_required = True
        except (HTTPException, RuntimeError, httpx.HTTPError, OSError):
            reconnect_required = True
        if session.released or not reconnect_required:
            return
        delay = min(TRACE_RETRY_MAX_DELAY_SECONDS,
                    TRACE_RETRY_DELAY_SECONDS * (2 ** min(reconnect, 16)))
        time.sleep(delay)
        reconnect += 1


def _register_answer_delivery(session: ProductSession) -> None:
    try:
        answer_delivery.register(session)
    except (OSError, ValueError, KeyError, TypeError):
        # Keep collecting durable projections. Never reset a damaged ledger or
        # turn storage failure into an uncharged direct catalog retry.
        pass


def _persist_projected_answer(session: ProductSession, event: dict[str, object]) -> bool:
    if event.get("kind") != "agent.output.delta":
        return True
    payload = event.get("payload")
    sequence = event.get("sequence")
    if not isinstance(payload, dict) or not isinstance(payload.get("delta"), str):
        return True
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        return True
    try:
        reply = _catalog_request(
            "POST",
            f"/v1/product/conversations/{session.conversation_id}/messages",
            session.principal,
            session.workspace_id,
            payload={
                "role": "assistant",
                "content": payload["delta"],
                "workflow_sequence": sequence,
            },
        )
        message = reply.get("message")
        if (not isinstance(message, dict)
                or type(message.get("workflow_sequence")) is not int
                or message["workflow_sequence"] != sequence
                or message.get("role") != "assistant"
                or message.get("content") != payload["delta"].strip()
                or not isinstance(message.get("message_id"), str) or not message["message_id"].strip()
                or type(message.get("sequence")) is not int or message["sequence"] < 1):
            raise ValueError("projected answer receipt does not match")
    except (HTTPException, ValueError):
        # WorkflowTrace remains the replay source when the durable catalog is
        # temporarily unavailable, including a malformed/lost catalog response.
        # A collector restart retries from this projection, not raw adapter data.
        return False
    return True


def _domain_get(path: str, session: ProductSession) -> dict[str, object]:
    headers = {
        "x-byq-workspace-id": session.workspace_id,
        "x-byq-owner-principal": session.principal.subject,
        "x-byq-actor-principal": session.principal.subject,
        "x-byq-trace-id": session.trace_id,
        "x-byq-session-id": session.session_id,
        "x-byq-dsh-run-id": session.session_id,
    }
    try:
        response = httpx.get(f"{BACKEND_URL}{path}", headers=headers, timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {408, 429} or exc.response.status_code >= 500:
            raise HTTPException(status_code=503, detail="owner-scoped card hydration is unavailable") from exc
        raise RuntimeError("owner-scoped card hydration failed") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="owner-scoped card hydration is unavailable") from exc
    try:
        body = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError("owner-scoped card hydration returned invalid JSON") from exc
    if not isinstance(body, dict):
        raise RuntimeError("owner-scoped card hydration returned an invalid response")
    return body


def _catalog_request(
    method: str,
    path: str,
    principal: Principal,
    workspace_id: str,
    *,
    payload: dict[str, object] | None = None,
    params: dict[str, object] | None = None,
    runtime_boot_id: str | None = None,
) -> dict[str, object]:
    headers = {
        "x-byq-workspace-id": workspace_id,
        "x-byq-owner-principal": principal.subject,
        "x-byq-actor-principal": principal.subject,
    }
    if runtime_boot_id is not None:
        if not _valid_runtime_boot_id(runtime_boot_id):
            raise HTTPException(status_code=503, detail="runtime boot identity is invalid")
        headers["x-byq-runtime-boot-id"] = runtime_boot_id
    try:
        response = httpx.request(
            method, f"{BACKEND_URL}{path}", json=payload, params=params, headers=headers, timeout=8.0
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in {400, 404, 409, 422}:
            raise HTTPException(status_code=status, detail="conversation request was rejected") from exc
        raise HTTPException(status_code=503, detail="conversation catalog unavailable") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="conversation catalog unavailable") from exc
    body = response.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="conversation catalog returned an invalid response")
    return body


def _restore_product_session(conversation_id: str, principal: Principal, workspace_id: str) -> ProductSession:
    body = _catalog_request("GET", f"/v1/product/conversations/{conversation_id}", principal, workspace_id)
    conversation = body.get("conversation")
    if not isinstance(conversation, dict) or conversation.get("status") != "active":
        raise HTTPException(status_code=404, detail="product session not found")
    session = ProductSession(
        conversation_id=str(conversation["conversation_id"]),
        session_id=str(conversation["runtime_session_id"]),
        trace_id=str(conversation["trace_id"]),
        principal=principal,
        workspace_id=workspace_id,
    )
    persisted_events = trace_store.read(session.session_id)
    initial_sequence = max((event["sequence"] for event in persisted_events), default=0)
    try:
        attached = _adapter_post(
            "/internal/runtime/sessions",
            payload={
                "session_id": session.session_id,
                "trace_id": session.trace_id,
                "workspace_id": session.workspace_id,
                "owner_principal": session.principal.subject,
                "initial_sequence": initial_sequence,
                "attach_live_only": True,
            },
        )
        session.boot_id = _adopt_runtime_session_boot(attached)
    except HTTPException as exc:
        if _is_lost_runtime_session(exc):
            _raise_agent_session_interrupted()
        raise
    try:
        product_sessions.add(session)
    except RuntimeError:
        return product_sessions.get_owned(conversation_id, principal)
    trace_store.reopen(session.session_id)
    _start_trace_collector(session)
    return session


def _conversation_context(value: object) -> list[ConversationContextMessage]:
    """Bound a transcript that already contains only completed public turns."""

    if not isinstance(value, list):
        return []
    public: list[ConversationContextMessage] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue
        bounded = content[:MAX_REHYDRATION_MESSAGE_CHARS]
        public.append({"role": role, "content": bounded})

    if not public:
        return []
    selected: list[ConversationContextMessage] = []
    total = 0
    for item in reversed(public):
        if len(selected) >= MAX_REHYDRATION_MESSAGES:
            break
        if total + len(item["content"]) > MAX_REHYDRATION_TOTAL_CHARS:
            break
        selected.append(item)
        total += len(item["content"])
    return list(reversed(selected))


_FAILED_OR_CANCELLED_TERMINALS = {
    "session.failed", "session.cancelled", "session.closed",
}
_SHORT_CONTINUATIONS = frozenset({
    "继续", "继续吧", "请继续", "继续处理", "接着做", "接着研究", "重试", "再试一次",
    "continue", "continue please", "please continue", "go on", "retry", "try again",
})
_CONTINUATION_PUNCTUATION = "。！!？?.,，；;"


def _event_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _runtime_events(events: object, session_id: str, trace_id: str) -> list[dict[str, object]]:
    if not isinstance(events, list):
        return []
    return sorted((event for event in events if isinstance(event, dict)
                   and event.get("session_id") == session_id
                   and event.get("trace_id") == trace_id
                   and event.get("source") == "runtime-adapter"
                   and type(event.get("sequence")) is int),
                  key=lambda event: event["sequence"])


def _attested_runtime_events(events: list[dict[str, object]], session: ProductSession) -> list[dict[str, object]]:
    """Use trace only to correlate public output; Backend DB owns terminal truth."""
    terminals = {"session.result", "session.failed", "session.cancelled", "session.closed"}
    if not any(event.get("kind") in terminals for event in events):
        return events
    try:
        body = _backend_runtime_authority_request(
            "GET", f"/internal/runtime-authority/sessions/{session.session_id}/roots", scope=session,
        )
        if set(body) != {"schema_version", "roots"} or body["schema_version"] != "byq-business-root-status.v1":
            raise ValueError("invalid business root status response")
        roots = body["roots"]
        if not isinstance(roots, list) or len(roots) > 500:
            raise ValueError("invalid business root status list")
        indexed: dict[str, dict[str, object]] = {}
        for row in roots:
            if (not isinstance(row, dict) or set(row) != {"root_run_id", "status", "authority_status",
                                                        "terminal_sequence", "terminal_event_sha256"}
                    or not isinstance(row["root_run_id"], str) or row["root_run_id"] in indexed):
                raise ValueError("invalid business root status row")
            indexed[row["root_run_id"]] = row
        attested: list[dict[str, object]] = []
        for event in events:
            if event.get("kind") not in terminals:
                attested.append(event)
                continue
            lifecycle = project_lifecycle_event(event, session.session_id, session.trace_id)
            if lifecycle is None:
                continue
            receipt = lifecycle_receipt(lifecycle)
            row = indexed.get(lifecycle["root_run_id"])
            if (row is None or row["status"] != lifecycle["outcome"]
                    or row["authority_status"] != "closed"
                    or row["terminal_sequence"] != receipt["sequence"]
                    or row["terminal_event_sha256"] != receipt["event_sha256"]):
                raise ValueError("business root terminal is not confirmed")
            attested.append(event)
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="business root completion is unavailable") from exc
    return attested


def _successful_public_answers(
    events: list[dict[str, object]], session_id: str, trace_id: str,
) -> list[tuple[dict[str, object], dict[str, object]]]:
    """Pair public answer events with their completed root start events."""
    context = {"session_id": session_id, "trace_id": trace_id}
    successful: list[tuple[dict[str, object], dict[str, object]]] = []
    current_start: dict[str, object] | None = None
    current_answers: list[dict[str, object]] = []
    for event in events:
        kind = event.get("kind")
        if kind == "session.started":
            current_start = event
            current_answers = []
        elif kind == "agent.output.delta":
            answer = answer_delivery._project(event, context)
            if answer is not None and current_start is not None:
                current_answers.append(answer)
        elif kind in {
            "session.result", "session.failed", "session.cancelled", "session.result.discarded",
        }:
            start_payload = current_start.get("payload") if current_start is not None else None
            terminal_payload = event.get("payload")
            run_id = start_payload.get("run_id") if isinstance(start_payload, dict) else None
            if (kind == "session.result" and isinstance(start_payload, dict)
                    and isinstance(terminal_payload, dict)
                    and isinstance(run_id, str) and run_id
                    and run_id == terminal_payload.get("run_id")):
                successful.extend((current_start, answer) for answer in current_answers)
            current_start = None
            current_answers = []
    return successful


def _completed_public_messages(
    messages: object, events: object, session_id: str, trace_id: str,
) -> list[dict[str, object]]:
    """Keep only durable user/assistant rows belonging to completed answers."""
    if not isinstance(messages, list):
        return []
    owned = _runtime_events(events, session_id, trace_id)
    completed_answers = _successful_public_answers(owned, session_id, trace_id)
    by_workflow_sequence = {
        answer.get("sequence"): (start, answer)
        for start, answer in completed_answers
    }
    public = [message for message in messages if isinstance(message, dict)
              and message.get("role") in {"user", "assistant"}
              and isinstance(message.get("content"), str)
              and type(message.get("sequence")) is int]
    selected: dict[int, dict[str, object]] = {}
    for message in public:
        if message.get("role") != "assistant":
            continue
        workflow_sequence = message.get("workflow_sequence")
        if type(workflow_sequence) is not int:
            continue
        run = by_workflow_sequence.get(workflow_sequence)
        if run is None:
            continue
        start, answer = run
        if message.get("content", "").strip() != answer.get("content"):
            continue
        start_time = _event_time(start.get("timestamp"))
        if start_time is None:
            continue
        user_messages = [candidate for candidate in public if candidate.get("role") == "user"
                         and candidate["sequence"] < message["sequence"]
                         and (created := _event_time(candidate.get("created_at"))) is not None
                         and created <= start_time]
        if not user_messages:
            continue
        user = max(user_messages, key=lambda candidate: candidate["sequence"])
        selected[user["sequence"]] = user
        selected[message["sequence"]] = message
    return [selected[sequence] for sequence in sorted(selected)]


def _reject_ambiguous_continuation_after_failure(
    events: list[dict[str, object]], session_id: str, trace_id: str, content: str,
) -> None:
    normalized = content.strip().rstrip(_CONTINUATION_PUNCTUATION).casefold()
    if normalized not in _SHORT_CONTINUATIONS:
        return
    terminals = [event for event in _runtime_events(events, session_id, trace_id) if event.get("kind") in {
        "session.result", *_FAILED_OR_CANCELLED_TERMINALS,
    }]
    if terminals and terminals[-1].get("kind") in _FAILED_OR_CANCELLED_TERMINALS:
        raise ProductError(
            409,
            "agent_instruction_required",
            "请明确重述本次要执行的具体指令；上一次 Agent 回合失败或已取消，系统没有自动重试。",
        )


def _product_session(request: Request, session_id: str) -> ProductSession:
    principal, workspace_id = _trusted_request_identity(request)
    try:
        return product_sessions.get_owned(session_id, principal)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return _restore_product_session(session_id, principal, workspace_id)


def _adopt_runtime_session_boot(reply: object) -> str:
    boot_id = reply.get("boot_id") if isinstance(reply, dict) else None
    snapshot = _runtime_authority_snapshot()
    if (not _valid_runtime_boot_id(boot_id) or snapshot.get("ready") is not True
            or boot_id != snapshot.get("boot_id")):
        _set_runtime_authority_state(ready=False)
        raise HTTPException(status_code=503, detail="runtime session boot does not match Backend authority")
    return boot_id


_LOST_RUNTIME_SESSION_MARKER = "BYQ runtime session was interrupted"
_FAILED_RUNTIME_SESSION_MARKER = "BYQ runtime session failed; start a new Agent session"


def _is_lost_runtime_session(error: HTTPException) -> bool:
    detail = getattr(error, "adapter_conflict_detail", "")
    return error.status_code == 404 or (
        error.status_code == 409 and isinstance(detail, str)
        and _LOST_RUNTIME_SESSION_MARKER in detail
    )


def _raise_agent_session_interrupted() -> None:
    raise ProductError(
        409,
        "agent_session_interrupted",
        "This Agent session was interrupted when its runtime process ended. Start a new Agent session and query durable BYQ Jobs by job_id to continue.",
    )


def _raise_agent_session_failed() -> None:
    raise ProductError(
        409,
        "agent_session_failed",
        "This Agent session failed. Start a new Agent session and query durable BYQ Jobs by job_id to continue.",
    )


def _runtime_conversation_payload(
    session: ProductSession, *, current_message: str | None = None,
) -> dict[str, object]:
    """Fresh, bounded completed Product transcript for one newly admitted root."""
    catalog = _catalog_request("GET", f"/v1/product/conversations/{session.conversation_id}",
                               session.principal, session.workspace_id)
    if not isinstance(catalog.get("messages"), list):
        raise HTTPException(status_code=502, detail="conversation history projection is unavailable")
    events = trace_store.read(session.session_id)
    owned = _attested_runtime_events(
        _runtime_events(events, session.session_id, session.trace_id), session,
    )
    if current_message is not None:
        _reject_ambiguous_continuation_after_failure(
            owned, session.session_id, session.trace_id, current_message,
        )
    messages = catalog["messages"]
    for _start, answer in _successful_public_answers(owned, session.session_id, session.trace_id):
        if not any(isinstance(message, dict) and message.get("role") == "assistant"
                   and message.get("workflow_sequence") == answer.get("sequence")
                   and isinstance(message.get("content"), str)
                   and message["content"].strip() == answer.get("content")
                   for message in messages):
            raise HTTPException(status_code=503, detail="previous public answer persistence is pending")
    public_messages = _completed_public_messages(
        messages, owned, session.session_id, session.trace_id,
    )
    return {"conversation_context": _conversation_context(public_messages)}


TRANSIENT_ROOT_CONFLICTS = (
    "previous runtime process cleanup is not complete",
    "new root requires a fresh public conversation projection",
    "session closed during initialization",
    "is still initializing",
    "cannot accept a prompt in state running",
)


def _transient_root_conflict(error: HTTPException) -> bool:
    detail = getattr(error, "adapter_conflict_detail", None)
    return isinstance(detail, str) and any(marker in detail for marker in TRANSIENT_ROOT_CONFLICTS)


def continue_approval_conversation(
    request: Request, conversation_id: str, approval_id: str, decision: str, action: str,
) -> dict[str, str]:
    try:
        with chat_admission():
            try:
                require_runtime_authority()
            except HTTPException:
                return {"status": "queued"}
            return _continue_approval_conversation(request, conversation_id, approval_id, decision, action)
    except AdmissionClosed:
        # The decision endpoint already durably queued the continuation. Do not
        # claim it, erase the decision, or manufacture a submitted model turn.
        return {"status": "queued"}


def _continue_approval_conversation(
    request: Request, conversation_id: str, approval_id: str, decision: str, action: str,
) -> dict[str, str]:
    """Submit one server-owned continuation turn for a durable approval decision."""
    headers = _trusted_agent_headers(request)
    claim_attempt: int | None = None

    def mark(status: str) -> dict[str, object]:
        return _backend_request(
            "POST", f"/v1/agents/approvals/{approval_id}/continuation",
            {"status": status, **({"expected_attempt": claim_attempt} if status != "submitting" else {})}, headers=headers,
        )

    claim = mark("submitting").get("approval")
    if not isinstance(claim, dict):
        return {"status": "failed"}
    if claim.get("continuation_changed") is not True:
        return {"status": str(claim.get("continuation_status") or "failed")}
    claim_attempt = claim.get("continuation_attempt")
    if type(claim_attempt) is not int or claim_attempt < 1:
        # An old or malformed Backend cannot provide a trustworthy claim.
        # Fail closed before submitting a model turn.
        return {"status": "failed"}

    instruction = (
        "BYQ trusted approval continuation. "
        f"The human decision for {approval_id} is {decision}. "
        "Re-read this exact approval through BeyondQuant MCP and re-check current domain state. "
        + (
            f"First execute the already approved action {action}; use its exact bound resource, "
            "do not request approval for the same action again, avoid duplicate writes, and report "
            "the authoritative domain outcome before proceeding. "
            "If approval was requested before the action was ever submitted, the action is not yet "
            "executed: submit it now with its original idempotency key. The original-key lookup "
            "recovers an execution whose response was not observed; an absent receipt is not proof "
            "that an unexecuted approved action was already performed. "
            "Then re-read the original research task through BeyondQuant MCP, using only the "
            "exact task/artifact lineage of this approval and the original conversation goal. "
            "Never substitute the latest task or infer missing bindings. Review the full objective, "
            "completed evidence and remaining steps; one approved action does not complete the mission. "
            "This approval grants no authority for other consequential actions or extra background turns. "
            "Request a separate approval when the next action requires it. If an outcome is unknown, "
            "reconcile the exact original operation before any retry. "
            "Before ending, persist task progress through the existing MCP contract when the task "
            "binding is confirmed, and report completed work, the next action and any blocker. "
            "Do not claim a job is running without its authoritative job identity, or promise automatic "
            "continuation without a confirmed queued delivery and valid task continuation permission. "
            "If no task binding or execution permission is available, explain what is missing; "
            "do not manufacture completion or start another turn."
            if decision == "approved"
            else "Do not execute the rejected action; explain the rejection briefly and offer a safe next step."
        )
    )
    prompt_attempted = False
    try:
        session = _product_session(request, conversation_id)
    except (ProductError, HTTPException):
        # The runtime session may have disappeared while this approval waited
        # for a human decision. No prompt was attempted, so close this claimed
        # continuation attempt without trying to recreate the Product session.
        mark("failed")
        return {"status": "failed"}

    try:
        _require_session_runtime_authority(session)
        require_runtime_authority()
        _require_session_runtime_authority(session)

        def continuation_payload() -> dict[str, object]:
            return {"content": instruction, "require_model_key": True,
                    "idempotency_key": f"approval-continuation-{approval_id}",
                    **_runtime_conversation_payload(session)}

        payload = continuation_payload()
        receipt = None
        conflict: HTTPException | None = None
        # A new DSH root can briefly reject its first prompt while the previous
        # root's process is still being released. The same original idempotency
        # key is reused, so a bounded retry cannot execute the turn twice.
        for delay in (0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0):
            if delay:
                time.sleep(delay)
            try:
                prompt_attempted = True
                receipt = _adapter_post(
                    f"/internal/runtime/sessions/{session.session_id}/prompt", payload=payload, timeout=5.0)
                break
            except HTTPException as exc:
                if _is_lost_runtime_session(exc):
                    mark("failed")
                    return {"status": "failed"}
                if exc.status_code == 409 and _transient_root_conflict(exc):
                    conflict = exc
                    continue
                raise
        if receipt is None:
            if conflict is not None:
                raise conflict
            raise HTTPException(status_code=502, detail="continuation prompt was not accepted")
        if not isinstance(receipt, dict) or receipt.get("accepted") is not True or not _valid_prompt_run_id(receipt.get("run_id")):
            raise HTTPException(status_code=502, detail="continuation receipt is unconfirmed")
    except HTTPException as error:
        state = "outcome_unknown" if (prompt_attempted and error.status_code >= 500
                                      and not isinstance(error, PromptAdmissionRejected)) else "failed"
        if state == "outcome_unknown" and _adapter_prompt_receipt(session.session_id, str(payload["idempotency_key"]), instruction) is not None:
            confirmed = mark("submitted").get("approval")
            return {"status": str(confirmed.get("continuation_status") if isinstance(confirmed, dict) else "outcome_unknown")}
        mark(state)
        return {"status": state}
    marked = mark("submitted").get("approval")
    return {
        "status": str(marked.get("continuation_status") if isinstance(marked, dict) else "submitted")
    }


@app.post("/v1/agent/sessions", status_code=201,
          dependencies=[Depends(require_chat_admission), Depends(require_runtime_authority)])
def create_product_session(request: Request) -> dict[str, object]:
    principal, workspace_id = _trusted_request_identity(request)
    session_id = f"byq-session-{uuid.uuid4().hex}"
    trace_id = f"byq-trace-{uuid.uuid4().hex}"
    body = _adapter_post(
        "/internal/runtime/sessions",
        payload={"session_id": session_id, "trace_id": trace_id,
                 "workspace_id": workspace_id, "owner_principal": principal.subject},
    )
    try:
        boot_id = _adopt_runtime_session_boot(body)
    except HTTPException:
        try:
            _adapter_post(f"/internal/runtime/sessions/{session_id}/release", timeout=5.0)
        except HTTPException:
            pass
        raise
    try:
        catalog = _catalog_request(
            "POST", "/v1/product/conversations", principal, workspace_id,
            payload={"runtime_session_id": session_id, "trace_id": trace_id},
        )
        conversation = catalog.get("conversation")
        if not isinstance(conversation, dict):
            raise HTTPException(status_code=502, detail="conversation catalog returned an invalid response")
    except Exception:
        # Runtime processes are ephemeral and must not leak when the durable
        # Product catalog transaction fails after process creation.
        try:
            _adapter_post(f"/internal/runtime/sessions/{session_id}/release", timeout=5.0)
        except HTTPException:
            pass
        raise
    session = ProductSession(
        conversation_id=str(conversation["conversation_id"]),
        session_id=session_id,
        trace_id=trace_id,
        principal=principal,
        workspace_id=workspace_id,
        boot_id=boot_id,
    )
    product_sessions.add(session)
    _start_trace_collector(session)
    return {
        "session_id": session.conversation_id,
        "trace_id": trace_id,
        "title": conversation.get("title"),
        "status": conversation.get("status", body.get("status", "ready")),
        # ADR-0079 R2: framework-neutral continuity, never a DSH/process schema.
        "continuity": body.get("continuity"),
    }


def _verified_public_runtime_boot() -> str | None:
    """Read current process and Backend authority before claiming Agent liveness."""
    cached = _runtime_authority_snapshot()
    if cached.get("ready") is not True or not _valid_runtime_boot_id(cached.get("boot_id")):
        return None
    try:
        adapter_boot = _adapter_authority()["boot_id"]
        backend = _backend_runtime_authority_request("GET", "/internal/runtime-authority/current")
        _validate_runtime_authority_current(backend, adapter_boot, cached.get("authority_epoch"))
    except (RuntimeError, KeyError, TypeError, ValueError):
        return None
    return adapter_boot if adapter_boot == cached["boot_id"] else None


def _public_conversation_status(conversation: dict, principal: Principal,
                                verified_boot: str | None) -> str:
    """Only a verified current Adapter binding can support an active claim."""
    stored = conversation.get("status")
    if stored != "active":
        return str(stored or "unknown")
    live = product_sessions.find_owned(str(conversation.get("conversation_id") or ""), principal)
    if (live is not None and not live.released
            and live.session_id == conversation.get("runtime_session_id")
            and live.trace_id == conversation.get("trace_id")
            and _valid_runtime_boot_id(live.boot_id)
            and verified_boot is not None):
        if live.boot_id == verified_boot:
            return "active"
        # The verified Backend boot rotation atomically revoked every active
        # root from the old boot. This classifies the Agent session only; any
        # in-flight external action retains its own unknown business outcome.
        return "interrupted"
    return "unknown"


@app.get("/v1/agent/sessions")
def list_product_sessions(
    request: Request,
    status: str = "active",
    search: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, object]:
    principal, workspace_id = _trusted_request_identity(request)
    catalog = _catalog_request(
        "GET", "/v1/product/conversations", principal, workspace_id,
        params={"status": status, "search": search, "limit": limit, "offset": offset},
    )
    conversations = catalog.get("conversations", [])
    verified_boot = _verified_public_runtime_boot()
    return {"sessions": [
        {
            "session_id": item["conversation_id"],
            "trace_id": item["trace_id"],
            "title": item["title"],
            "status": _public_conversation_status(item, principal, verified_boot),
            "pinned": item["pinned"],
            "message_count": item["message_count"],
            "last_message_preview": item["last_message_preview"],
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
        }
        for item in conversations if isinstance(item, dict)
    ], "total": catalog.get("total", 0), "limit": catalog.get("limit", limit), "offset": catalog.get("offset", offset)}


@app.get("/v1/agent/sessions/{session_id}")
def get_product_session(session_id: str, request: Request) -> dict[str, object]:
    principal, workspace_id = _trusted_request_identity(request)
    body = _catalog_request("GET", f"/v1/product/conversations/{session_id}", principal, workspace_id)
    conversation = body.get("conversation")
    if not isinstance(conversation, dict):
        raise HTTPException(status_code=502, detail="conversation catalog returned an invalid response")
    verified_boot = _verified_public_runtime_boot() if conversation.get("status") == "active" else None
    runtime_session_id = str(conversation.get("runtime_session_id", ""))
    messages = body.get("messages", [])
    persisted_answer_sequences = {
        item.get("workflow_sequence")
        for item in messages if isinstance(item, dict) and item.get("role") == "assistant"
        and isinstance(item.get("workflow_sequence"), int)
    } if isinstance(messages, list) else set()
    events = [
        {**event, "session_id": session_id}
        for event in trace_store.read(runtime_session_id)
        if event["kind"] != "agent.output.delta" or event["sequence"] not in persisted_answer_sequences
    ]
    public = {
        "session_id": session_id,
        "trace_id": conversation.get("trace_id"),
        "title": conversation.get("title"),
        "status": _public_conversation_status(conversation, principal, verified_boot),
        "pinned": conversation.get("pinned"),
        "message_count": conversation.get("message_count"),
        "last_message_preview": conversation.get("last_message_preview"),
        "created_at": conversation.get("created_at"),
        "updated_at": conversation.get("updated_at"),
    }
    containment = _session_containment_projection(
        request,
        conversation_id=session_id,
        runtime_session_id=runtime_session_id,
        trace_id=str(conversation.get("trace_id") or ""),
        principal_subject=principal.subject,
        workspace_id=workspace_id,
        conversation=conversation,
        events=trace_store.read(runtime_session_id),
    )
    if public["status"] == "unknown" and containment["status"] == "active":
        containment = {**containment, "status": "unknown"}
    elif public["status"] == "interrupted" and containment["status"] == "active":
        containment = {**containment, "status": "interrupted", "loss_cause": "runtime-loss"}
    return {"conversation": public, "messages": messages, "events": events,
            "containment": containment}


@app.get("/v1/agent/sessions/{session_id}/answer-delivery")
def get_answer_delivery(session_id: str, request: Request) -> dict:
    principal, workspace_id = _trusted_request_identity(request)
    body = _catalog_request("GET", f"/v1/product/conversations/{session_id}", principal, workspace_id)
    conversation = body.get("conversation")
    if not isinstance(conversation, dict):
        raise HTTPException(status_code=502, detail="conversation catalog returned an invalid response")
    return answer_delivery.status({"conversation_id": session_id, "session_id": conversation["runtime_session_id"],
        "trace_id": conversation["trace_id"], "workspace_id": workspace_id, "owner": principal.subject})


@app.patch("/v1/agent/sessions/{session_id}")
def update_product_session(
    session_id: str,
    update: ProductSessionUpdateRequest,
    request: Request,
) -> dict[str, object]:
    principal, workspace_id = _trusted_request_identity(request)
    payload = update.model_dump(exclude_none=True)
    body = _catalog_request(
        "PATCH", f"/v1/product/conversations/{session_id}", principal, workspace_id, payload=payload
    )
    conversation = body.get("conversation")
    if not isinstance(conversation, dict):
        raise HTTPException(status_code=502, detail="conversation catalog returned an invalid response")
    return {"session": {
        "session_id": conversation["conversation_id"],
        **{key: value for key, value in conversation.items() if key not in {"conversation_id", "runtime_session_id"}},
    }}


@app.post("/v1/agent/sessions/{session_id}/turns", status_code=202,
          dependencies=[Depends(require_chat_admission), Depends(require_runtime_authority)])
def submit_product_turn(
    session_id: str,
    request: ProductPromptRequest,
    http_request: Request,
) -> dict[str, object]:
    session = _product_session(http_request, session_id)
    _require_session_runtime_authority(session)
    transcript_payload = _runtime_conversation_payload(session, current_message=request.content)
    persisted = _catalog_request(
        "POST", f"/v1/product/conversations/{session.conversation_id}/messages",
        session.principal, session.workspace_id, payload={"content": request.content},
    )
    prompt_payload = {"content": request.content, "require_model_key": True, **transcript_payload}
    persisted_message = persisted.get("message")
    message_id = persisted_message.get("message_id") if isinstance(persisted_message, dict) else None
    if not isinstance(message_id, str) or not 8 <= len(message_id) <= 128 or message_id.strip() != message_id:
        raise ProductError(502, "prompt_outcome_unknown",
                           "原消息的保存回执尚未确认，本次未启动模型；请先核对原会话。")
    prompt_payload["idempotency_key"] = message_id
    try:
        body = _adapter_post(
            f"/internal/runtime/sessions/{session.session_id}/prompt",
            payload=prompt_payload, timeout=5.0,
        )
        if not isinstance(body, dict) or body.get("accepted") is not True or not _valid_prompt_run_id(body.get("run_id")):
            raise HTTPException(status_code=502, detail="prompt receipt is unconfirmed")
    except HTTPException as exc:
        if _is_lost_runtime_session(exc):
            _raise_agent_session_interrupted()
        key = prompt_payload.get("idempotency_key")
        if isinstance(exc, PromptAdmissionRejected) or exc.status_code < 500 or not isinstance(key, str):
            raise
        receipt = _adapter_prompt_receipt(session.session_id, key, request.content)
        if receipt is None:
            raise ProductError(502, "prompt_outcome_unknown",
                               "本次消息的接收结果尚未确认；请先核对原会话，勿重复发送。") from exc
        body = receipt
    return {
        "accepted": True,
        "session_id": session.conversation_id,
        "trace_id": session.trace_id,
        "run_id": body.get("run_id"),
    }


@app.post("/v1/agent/sessions/{session_id}/resume",
          dependencies=[Depends(require_chat_admission), Depends(require_runtime_authority)])
def resume_product_session(session_id: str, request: Request) -> dict[str, object]:
    session = _product_session(request, session_id)
    _require_session_runtime_authority(session)
    resume_payload = _runtime_conversation_payload(session)
    try:
        body = _adapter_post(
            f"/internal/runtime/sessions/{session.session_id}/resume",
            payload=resume_payload,
        )
    except HTTPException as exc:
        if _is_lost_runtime_session(exc):
            _raise_agent_session_interrupted()
        if (exc.status_code == 409
                and getattr(exc, "adapter_conflict_detail", None) == _FAILED_RUNTIME_SESSION_MARKER):
            _raise_agent_session_failed()
        raise
    return {
        "session_id": session.conversation_id,
        "trace_id": session.trace_id,
        "status": body.get("status"),
        "resumed_from_run_id": body.get("resumed_from_run_id"),
        # ADR-0079 R2: framework-neutral continuity status for reattach vs
        # rehydrate vs interrupted; no DSH or process identity is projected.
        "continuity": body.get("continuity"),
    }


@app.post("/v1/agent/sessions/{session_id}/cancel", dependencies=[Depends(require_runtime_authority)])
def cancel_product_session(
    session_id: str,
    request: ProductCancelRequest,
    http_request: Request,
) -> dict[str, object]:
    session = _product_session(http_request, session_id)
    _require_session_runtime_authority(session)
    path = f"/internal/runtime/sessions/{session.session_id}/cancel"
    if request.mode != "hard":
        path += f"?mode={request.mode}"
    try:
        body = _adapter_post(path, payload=None, timeout=5.0)
    except HTTPException as exc:
        if _is_lost_runtime_session(exc):
            _raise_agent_session_interrupted()
        raise
    return {
        "session_id": session.conversation_id,
        "trace_id": session.trace_id,
        "status": body.get("status"),
        "active_prompt": body.get("active_prompt"),
    }


@app.delete("/v1/agent/sessions/{session_id}")
def delete_product_session(session_id: str, request: Request) -> dict[str, object]:
    principal, workspace_id = _trusted_request_identity(request)
    catalog = _catalog_request(
        "GET", f"/v1/product/conversations/{session_id}", principal, workspace_id,
    )
    conversation = catalog.get("conversation")
    if not isinstance(conversation, dict):
        raise HTTPException(status_code=502, detail="conversation catalog returned an invalid response")
    runtime_session_id = str(conversation.get("runtime_session_id", ""))
    trace_id = str(conversation.get("trace_id", ""))
    if not runtime_session_id:
        raise HTTPException(status_code=502, detail="conversation catalog returned an invalid response")
    try:
        _adapter_post(f"/internal/runtime/sessions/{runtime_session_id}/release", timeout=5.0)
    except HTTPException as exc:
        # Runtime processes are ephemeral. A missing process must not make an
        # otherwise owner-authorized durable conversation impossible to delete.
        if exc.status_code != 404:
            raise
    _catalog_request(
        "DELETE", f"/v1/product/conversations/{session_id}", principal, workspace_id,
    )
    product_sessions.remove_owned(session_id, principal)
    trace_store.delete(runtime_session_id)
    return {
        "session_id": session_id,
        "trace_id": trace_id,
        "status": "deleted",
    }


@app.post("/v1/workspaces/current/runtime-reset")
def reset_current_workspace_runtime(request: Request) -> dict[str, object]:
    # Runtime reset is a destructive workspace operation. The deployment
    # Product Token is only a bootstrap compatibility credential and cannot
    # identify the durable owner/workspace required by the Backend fence.
    if SESSION_COOKIE not in request.cookies:
        raise HTTPException(status_code=401, detail="product authentication required")
    principal, workspace_id = _trusted_request_identity(request)

    begin = _workspace_runtime_reset_backend_request(
        "POST",
        "/internal/workspace-runtime-reset/begin",
        {"schema_version": WORKSPACE_RUNTIME_RESET_BEGIN_SCHEMA},
        principal,
        workspace_id,
    )
    reset_id, sessions = _validate_workspace_runtime_reset_begin(begin, workspace_id=workspace_id)
    _reset_workspace_runtime_sessions(sessions, principal, workspace_id)

    conversation_ids = [item["conversation_id"] for item in sessions]
    finalized = _workspace_runtime_reset_backend_request(
        "POST",
        "/internal/workspace-runtime-reset/finalize",
        {
            "schema_version": WORKSPACE_RUNTIME_RESET_FINALIZE_SCHEMA,
            "reset_id": reset_id,
            "released_sessions": [item["session_id"] for item in sessions],
        },
        principal,
        workspace_id,
    )
    _validate_workspace_runtime_reset_finalize(
        finalized,
        workspace_id=workspace_id,
        reset_id=reset_id,
        expected_conversation_ids=conversation_ids,
    )
    return {
        "status": "reset",
        "workspace_id": workspace_id,
        "archived_conversation_count": len(conversation_ids),
    }


@app.post("/v1/workspaces/current/reset", response_model=None)
def reset_current_workspace(request: Request, idempotency_key: str | None = Header(
    default=None, alias="Idempotency-Key",
)) -> dict[str, object] | JSONResponse:
    # Browser-only, durable owner identity. A Product Token cannot authorize deletion.
    if SESSION_COOKIE not in request.cookies:
        raise HTTPException(status_code=401, detail="product authentication required")
    principal, workspace_id = _trusted_request_identity(request)
    try:
        key = uuid.UUID(idempotency_key or "")
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="Idempotency-Key must be an RFC 4122 UUID") from None
    if key.variant != uuid.RFC_4122 or str(key) != idempotency_key:
        raise HTTPException(status_code=422, detail="Idempotency-Key must be an RFC 4122 UUID")

    begin = _workspace_runtime_reset_backend_request(
        "POST", "/internal/workspace-reset/begin",
        {"schema_version": WORKSPACE_RESET_BEGIN_SCHEMA, "request_key": idempotency_key},
        principal, workspace_id,
    )
    reset_id, sessions, completed = _validate_workspace_reset_begin(begin, workspace_id=workspace_id)
    if completed is not None:
        if completed["status"] == "blocked":
            return JSONResponse(status_code=409, content={
                "detail": completed["reason"], "reset_terminal": True,
            })
        return completed
    assert reset_id is not None
    _reset_workspace_runtime_sessions(sessions, principal, workspace_id)
    finalized = _workspace_runtime_reset_backend_request(
        "POST", "/internal/workspace-reset/finalize",
        {"schema_version": WORKSPACE_RESET_FINALIZE_SCHEMA, "reset_id": reset_id,
         "request_key": idempotency_key,
         "released_sessions": [item["session_id"] for item in sessions]},
        principal, workspace_id,
    )
    receipt = _validate_workspace_reset_finalize(
        finalized, workspace_id=workspace_id, reset_id=reset_id,
    )
    if receipt["status"] == "blocked":
        return JSONResponse(status_code=409, content={
            "detail": receipt["reason"], "reset_terminal": True,
        })
    return receipt


@app.get("/v1/workflows/{session_id}/events")
def product_workflow_events(
    session_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    session = _product_session(request, session_id)
    try:
        after_sequence = max(0, int(last_event_id or "0"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer") from exc

    # Claim the consumer before returning the response so an old disconnect
    # timer cannot release the runtime during ASGI response startup.
    product_sessions.begin_stream(session)

    async def stream() -> AsyncIterator[bytes]:
        bridge = _AsyncTraceBridge(trace_store.stream(session.session_id, after_sequence=after_sequence))
        try:
            while True:
                available, event = await bridge.get()
                if not available:
                    return
                if event is None:
                    yield b": heartbeat\n\n"
                    continue
                public_event = {**event, "session_id": session.conversation_id}
                yield (
                    f"id: {public_event['sequence']}\n"
                    f"event: workflow-trace\n"
                    f"data: {json.dumps(public_event, separators=(',', ':'))}\n\n"
                ).encode()
        finally:
            bridge.close()
            _schedule_idle_release(session)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )
