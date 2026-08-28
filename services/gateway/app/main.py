from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .auth import AuthenticationUnavailable, Principal, authenticate_bearer
from .auth_api import router as auth_router
from .product_api import ProductError, router as product_router
from .user_session import ProductAuthError, resolve_principal, resolve_user
from .trace_store import TraceStore
from .workflow_projection import project_workflow_event


SERVICE = "byq-gateway"
VERSION = "0.1.0"
app = FastAPI(title="BeyondQuant Gateway", version=VERSION)
app.include_router(product_router)
app.include_router(auth_router)
RUNTIME_ADAPTER_URL = os.environ.get("BYQ_RUNTIME_ADAPTER_URL", "http://runtime-adapter:8400")
BACKEND_URL = os.environ.get("BYQ_BACKEND_URL", "http://backend:8000")
PRODUCT_TOKEN = os.environ.get("BYQ_PRODUCT_TOKEN")
PRODUCT_PRINCIPAL = os.environ.get("BYQ_PRODUCT_PRINCIPAL", "product-user")
trace_store = TraceStore(os.environ.get("BYQ_WORKFLOW_TRACE_ROOT", "/tmp/byq-workflow-traces"))


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


class RuntimeSessionRequest(BaseModel):
    session_id: str
    trace_id: str


class PromptRequest(BaseModel):
    content: str


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
    released: bool = False


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

    def mark_released(self, conversation_id: str, principal: Principal) -> ProductSession:
        session = self.get_owned(conversation_id, principal)
        with self._lock:
            session.released = True
        return session

    def list_owned(self, principal: Principal) -> list[ProductSession]:
        with self._lock:
            return [
                session
                for session in self._sessions.values()
                if session.principal.subject == principal.subject and not session.released
            ]


product_sessions = ProductSessionRegistry()


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
        elif status == 503:
            detail = "product model is unavailable"
        raise HTTPException(status_code=status, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="runtime adapter unavailable") from exc
    body = response.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="runtime adapter returned an invalid response")
    return body


def _start_trace_collector(session: ProductSession) -> None:
    thread = threading.Thread(
        target=_collect_trace,
        args=(session,),
        name=f"byq-workflow-trace-{session.session_id}",
        daemon=True,
    )
    thread.start()


def _collect_trace(session: ProductSession) -> None:
    """Persist only the adapter's BYQ event envelopes for this product session."""

    try:
        with httpx.stream(
            "GET",
            f"{RUNTIME_ADAPTER_URL}/internal/runtime/sessions/{session.session_id}/events",
            params={"replay": "true"},
            timeout=None,
        ) as response:
            if response.status_code != 200:
                return
            for line in response.iter_lines():
                if isinstance(line, bytes):
                    line = line.decode("utf-8")
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                    projected = project_workflow_event(
                        event,
                        backend_get=lambda path: _domain_get(path, session),
                        revision_for=lambda card_id: trace_store.next_card_revision(
                            session.session_id,
                            card_id,
                        ),
                    )
                    trace_store.append(projected)
                except (ValueError, TypeError, json.JSONDecodeError):
                    # The adapter is the only producer. Invalid data is not
                    # persisted or reflected to the product client.
                    continue
    except httpx.HTTPError:
        return
    finally:
        if session.released:
            trace_store.close(session.session_id)


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
        body = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise RuntimeError("owner-scoped card hydration failed") from exc
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
) -> dict[str, object]:
    headers = {
        "x-byq-workspace-id": workspace_id,
        "x-byq-owner-principal": principal.subject,
        "x-byq-actor-principal": principal.subject,
    }
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
        _adapter_post(
            "/internal/runtime/sessions",
            payload={
                "session_id": session.session_id,
                "trace_id": session.trace_id,
                "workspace_id": session.workspace_id,
                "owner_principal": session.principal.subject,
                "initial_sequence": initial_sequence,
            },
        )
    except HTTPException as exc:
        # A 409 means Gateway restarted while this adapter session survived.
        if exc.status_code != 409:
            raise
    try:
        product_sessions.add(session)
    except RuntimeError:
        return product_sessions.get_owned(conversation_id, principal)
    _start_trace_collector(session)
    return session


def _product_session(request: Request, session_id: str) -> ProductSession:
    principal, workspace_id = _trusted_request_identity(request)
    try:
        return product_sessions.get_owned(session_id, principal)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return _restore_product_session(session_id, principal, workspace_id)


@app.post("/v1/agent/sessions", status_code=201)
def create_product_session(request: Request) -> dict[str, object]:
    principal, workspace_id = _trusted_request_identity(request)
    session_id = f"byq-session-{uuid.uuid4().hex}"
    trace_id = f"byq-trace-{uuid.uuid4().hex}"
    body = _adapter_post(
        "/internal/runtime/sessions",
        payload={"session_id": session_id, "trace_id": trace_id,
                 "workspace_id": workspace_id, "owner_principal": principal.subject},
    )
    catalog = _catalog_request(
        "POST", "/v1/product/conversations", principal, workspace_id,
        payload={"runtime_session_id": session_id, "trace_id": trace_id},
    )
    conversation = catalog.get("conversation")
    if not isinstance(conversation, dict):
        raise HTTPException(status_code=502, detail="conversation catalog returned an invalid response")
    session = ProductSession(
        conversation_id=str(conversation["conversation_id"]),
        session_id=session_id,
        trace_id=trace_id,
        principal=principal,
        workspace_id=workspace_id,
    )
    product_sessions.add(session)
    _start_trace_collector(session)
    return {
        "session_id": session.conversation_id,
        "trace_id": trace_id,
        "title": conversation.get("title"),
        "status": conversation.get("status", body.get("status", "ready")),
    }


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
    return {"sessions": [
        {
            "session_id": item["conversation_id"],
            "trace_id": item["trace_id"],
            "title": item["title"],
            "status": item["status"],
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
    runtime_session_id = str(conversation.get("runtime_session_id", ""))
    events = [
        {**event, "session_id": session_id}
        for event in trace_store.read(runtime_session_id)
    ]
    public = {
        "session_id": session_id,
        "trace_id": conversation.get("trace_id"),
        "title": conversation.get("title"),
        "status": conversation.get("status"),
        "pinned": conversation.get("pinned"),
        "message_count": conversation.get("message_count"),
        "last_message_preview": conversation.get("last_message_preview"),
        "created_at": conversation.get("created_at"),
        "updated_at": conversation.get("updated_at"),
    }
    return {"conversation": public, "messages": body.get("messages", []), "events": events}


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


@app.post("/v1/agent/sessions/{session_id}/turns", status_code=202)
def submit_product_turn(
    session_id: str,
    request: ProductPromptRequest,
    http_request: Request,
) -> dict[str, object]:
    session = _product_session(http_request, session_id)
    _catalog_request(
        "POST", f"/v1/product/conversations/{session.conversation_id}/messages",
        session.principal, session.workspace_id, payload={"content": request.content},
    )
    body = _adapter_post(
        f"/internal/runtime/sessions/{session.session_id}/prompt",
        payload={"content": request.content, "require_model_key": True},
        timeout=5.0,
    )
    return {
        "accepted": True,
        "session_id": session.conversation_id,
        "trace_id": session.trace_id,
        "run_id": body.get("run_id"),
    }


@app.post("/v1/agent/sessions/{session_id}/resume")
def resume_product_session(session_id: str, request: Request) -> dict[str, object]:
    session = _product_session(request, session_id)
    body = _adapter_post(f"/internal/runtime/sessions/{session.session_id}/resume")
    return {
        "session_id": session.conversation_id,
        "trace_id": session.trace_id,
        "status": body.get("status"),
        "resumed_from_run_id": body.get("resumed_from_run_id"),
    }


@app.post("/v1/agent/sessions/{session_id}/cancel")
def cancel_product_session(
    session_id: str,
    request: ProductCancelRequest,
    http_request: Request,
) -> dict[str, object]:
    session = _product_session(http_request, session_id)
    path = f"/internal/runtime/sessions/{session.session_id}/cancel"
    if request.mode != "hard":
        path += f"?mode={request.mode}"
    body = _adapter_post(
        path,
        payload=None,
        timeout=5.0,
    )
    return {
        "session_id": session.conversation_id,
        "trace_id": session.trace_id,
        "status": body.get("status"),
        "active_prompt": body.get("active_prompt"),
    }


@app.delete("/v1/agent/sessions/{session_id}")
def release_product_session(session_id: str, request: Request) -> dict[str, object]:
    session = _product_session(request, session_id)
    principal = session.principal
    body = _adapter_post(f"/internal/runtime/sessions/{session.session_id}/release", timeout=5.0)
    _catalog_request(
        "PATCH", f"/v1/product/conversations/{session.conversation_id}",
        principal, session.workspace_id, payload={"status": "archived"},
    )
    product_sessions.mark_released(session.conversation_id, principal)
    return {
        "session_id": session.conversation_id,
        "trace_id": session.trace_id,
        "status": body.get("status"),
    }


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

    def stream() -> Iterator[bytes]:
        for event in trace_store.stream(session.session_id, after_sequence=after_sequence):
            if event is None:
                yield b": heartbeat\n\n"
                continue
            public_event = {**event, "session_id": session.conversation_id}
            yield (
                f"id: {public_event['sequence']}\n"
                f"event: workflow-trace\n"
                f"data: {json.dumps(public_event, separators=(',', ':'))}\n\n"
            ).encode()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


@app.get("/internal/runtime/health")
def runtime_health() -> dict[str, object]:
    """Internal adapter health seam; no DSH event or session schema crosses it."""

    try:
        response = httpx.get(f"{RUNTIME_ADAPTER_URL}/readyz", timeout=2.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return {"service": SERVICE, "status": "degraded", "runtime_adapter": str(exc)}
    return {"service": SERVICE, "status": "ok", "runtime_adapter": response.json()}


@app.post("/internal/runtime/sessions", status_code=201)
def create_runtime_session(request: RuntimeSessionRequest) -> dict[str, object]:
    """Private Phase 6 compatibility seam; product traffic uses /v1/agent."""

    return _adapter_post(
        "/internal/runtime/sessions",
        payload=request.model_dump(),
    )


@app.post("/internal/runtime/sessions/{session_id}/prompt", status_code=202)
def submit_runtime_prompt(session_id: str, request: PromptRequest) -> dict[str, object]:
    return _adapter_post(
        f"/internal/runtime/sessions/{session_id}/prompt",
        payload=request.model_dump(),
        timeout=5.0,
    )


@app.post("/internal/runtime/sessions/{session_id}/cancel")
def cancel_runtime_session(session_id: str, mode: str = "hard") -> dict[str, object]:
    return _adapter_post(
        f"/internal/runtime/sessions/{session_id}/cancel?mode={mode}",
        timeout=5.0,
    )


@app.post("/internal/runtime/sessions/{session_id}/release")
def release_runtime_session(session_id: str) -> dict[str, object]:
    return _adapter_post(
        f"/internal/runtime/sessions/{session_id}/release",
        timeout=5.0,
    )


@app.get("/internal/workflows/{session_id}/events")
def workflow_events(session_id: str) -> StreamingResponse:
    """Private Phase 6 SSE bridge carrying BYQ envelopes only."""

    def stream() -> Iterator[bytes]:
        try:
            with httpx.stream(
                "GET",
                f"{RUNTIME_ADAPTER_URL}/internal/runtime/sessions/{session_id}/events",
                timeout=None,
            ) as response:
                if response.status_code == 404:
                    return
                response.raise_for_status()
                yield from response.iter_bytes()
        except httpx.HTTPError:
            return

    return StreamingResponse(stream(), media_type="text/event-stream")
