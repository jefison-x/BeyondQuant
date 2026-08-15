from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .auth import AuthenticationUnavailable, Principal, authenticate_bearer
from .trace_store import TraceStore


SERVICE = "byq-gateway"
VERSION = "0.1.0"
app = FastAPI(title="BeyondQuant Gateway", version=VERSION)
RUNTIME_ADAPTER_URL = os.environ.get("BYQ_RUNTIME_ADAPTER_URL", "http://runtime-adapter:8400")
PRODUCT_TOKEN = os.environ.get("BYQ_PRODUCT_TOKEN")
PRODUCT_PRINCIPAL = os.environ.get("BYQ_PRODUCT_PRINCIPAL", "product-user")
trace_store = TraceStore(os.environ.get("BYQ_WORKFLOW_TRACE_ROOT", "/tmp/byq-workflow-traces"))


class RuntimeSessionRequest(BaseModel):
    session_id: str
    trace_id: str


class PromptRequest(BaseModel):
    content: str


class ProductPromptRequest(BaseModel):
    content: str = Field(min_length=1, max_length=12_000)


class ProductCancelRequest(BaseModel):
    mode: str = Field(default="hard", pattern="^(soft|hard)$")


@dataclass(slots=True)
class ProductSession:
    session_id: str
    trace_id: str
    principal: Principal
    released: bool = False


class ProductSessionRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, ProductSession] = {}

    def add(self, session: ProductSession) -> None:
        with self._lock:
            if session.session_id in self._sessions:
                raise RuntimeError("generated session identifier collision")
            self._sessions[session.session_id] = session

    def get_owned(self, session_id: str, principal: Principal) -> ProductSession:
        with self._lock:
            session = self._sessions.get(session_id)
        # Do not reveal whether another principal owns a session.
        if session is None or session.principal.subject != principal.subject:
            raise HTTPException(status_code=404, detail="product session not found")
        if session.released:
            raise HTTPException(status_code=409, detail="product session is closed")
        return session

    def mark_released(self, session_id: str, principal: Principal) -> ProductSession:
        session = self.get_owned(session_id, principal)
        with self._lock:
            session.released = True
        return session


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
                    trace_store.append(event)
                except (ValueError, TypeError, json.JSONDecodeError):
                    # The adapter is the only producer. Invalid data is not
                    # persisted or reflected to the product client.
                    continue
    except httpx.HTTPError:
        return
    finally:
        if session.released:
            trace_store.close(session.session_id)


def _product_session(request: Request, session_id: str) -> ProductSession:
    principal = _authenticate(request.headers.get("authorization"))
    return product_sessions.get_owned(session_id, principal)


@app.post("/v1/agent/sessions", status_code=201)
def create_product_session(request: Request) -> dict[str, object]:
    principal = _authenticate(request.headers.get("authorization"))
    session_id = f"byq-session-{uuid.uuid4().hex}"
    trace_id = f"byq-trace-{uuid.uuid4().hex}"
    body = _adapter_post(
        "/internal/runtime/sessions",
        payload={"session_id": session_id, "trace_id": trace_id},
    )
    session = ProductSession(session_id=session_id, trace_id=trace_id, principal=principal)
    product_sessions.add(session)
    _start_trace_collector(session)
    return {
        "session_id": session_id,
        "trace_id": trace_id,
        "status": body.get("status", "ready"),
    }


@app.post("/v1/agent/sessions/{session_id}/turns", status_code=202)
def submit_product_turn(
    session_id: str,
    request: ProductPromptRequest,
    http_request: Request,
) -> dict[str, object]:
    session = _product_session(http_request, session_id)
    body = _adapter_post(
        f"/internal/runtime/sessions/{session.session_id}/prompt",
        payload={"content": request.content, "require_model_key": True},
        timeout=5.0,
    )
    return {
        "accepted": True,
        "session_id": session.session_id,
        "trace_id": session.trace_id,
        "run_id": body.get("run_id"),
    }


@app.post("/v1/agent/sessions/{session_id}/resume")
def resume_product_session(session_id: str, request: Request) -> dict[str, object]:
    session = _product_session(request, session_id)
    body = _adapter_post(f"/internal/runtime/sessions/{session.session_id}/resume")
    return {
        "session_id": session.session_id,
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
        "session_id": session.session_id,
        "trace_id": session.trace_id,
        "status": body.get("status"),
        "active_prompt": body.get("active_prompt"),
    }


@app.delete("/v1/agent/sessions/{session_id}")
def release_product_session(session_id: str, request: Request) -> dict[str, object]:
    principal = _authenticate(request.headers.get("authorization"))
    session = product_sessions.get_owned(session_id, principal)
    body = _adapter_post(f"/internal/runtime/sessions/{session.session_id}/release", timeout=5.0)
    product_sessions.mark_released(session.session_id, principal)
    return {
        "session_id": session.session_id,
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
            yield (
                f"id: {event['sequence']}\n"
                f"event: workflow-trace\n"
                f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
            ).encode()

    return StreamingResponse(stream(), media_type="text/event-stream")


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
