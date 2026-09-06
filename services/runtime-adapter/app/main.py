from __future__ import annotations

import asyncio
import json
import queue
import threading
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from packages.contracts.conversation_rehydration import ConversationContextMessage
from packages.operations.admission import AdmissionClosed, chat_admission

from .runtime import ModelCredentialUnavailable, RuntimeAdapter, SessionConflict


class CreateSessionRequest(BaseModel):
    session_id: str
    trace_id: str
    workspace_id: str | None = None
    owner_principal: str | None = None
    initial_sequence: int = 0
    conversation_context: list[ConversationContextMessage] = Field(default_factory=list)


class ResumeSessionRequest(BaseModel):
    conversation_context: list[ConversationContextMessage] = Field(default_factory=list)


class PromptRequest(BaseModel):
    content: str
    require_model_key: bool = False
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


adapter = RuntimeAdapter()
app = FastAPI(title="BeyondQuant DSH Runtime Adapter", version="0.1.0")


def require_chat_admission():
    with chat_admission():
        yield


@app.exception_handler(AdmissionClosed)
async def admission_closed_handler(request, exc: AdmissionClosed):
    return JSONResponse(status_code=503, content={"detail": "chat maintenance; retry later"})


class _AsyncSubscriberBridge:
    """Forward a blocking runtime subscriber without using the shared executor."""

    def __init__(self, subscriber: queue.Queue[dict[str, object] | None]) -> None:
        self._subscriber = subscriber
        self._loop = asyncio.get_running_loop()
        self._items: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._pump, name="byq-runtime-sse", daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        while not self._stopped.is_set():
            try:
                item = self._subscriber.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self._loop.call_soon_threadsafe(self._items.put_nowait, item)
            except RuntimeError:
                return
            if item is None:
                return

    async def get(self) -> dict[str, object] | None:
        return await asyncio.wait_for(self._items.get(), timeout=15.0)

    def close(self) -> None:
        self._stopped.set()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"service": "byq-dsh-runtime-adapter", "status": "ok", "version": "0.1.0"}


@app.get("/readyz")
def readyz() -> dict[str, object]:
    return {"service": "byq-dsh-runtime-adapter", "status": "ok", **adapter.readiness()}


@app.get("/internal/runtime/operations")
def runtime_operations() -> dict[str, object]:
    return adapter.operations_snapshot()


@app.post("/internal/runtime/sessions", status_code=201, dependencies=[Depends(require_chat_admission)])
def create_session(request: CreateSessionRequest) -> dict[str, object]:
    try:
        return adapter.create_session(
            request.session_id, request.trace_id, request.owner_principal, request.workspace_id,
            request.initial_sequence, request.conversation_context,
        )
    except SessionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="DSH runtime failed to initialize") from exc


@app.post("/internal/runtime/sessions/{session_id}/prompt", status_code=202, dependencies=[Depends(require_chat_admission)])
def submit_prompt(session_id: str, request: PromptRequest) -> dict[str, object]:
    try:
        run_id = adapter.submit_prompt(
            session_id,
            request.content,
            require_model_key=request.require_model_key,
            idempotency_key=request.idempotency_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ModelCredentialUnavailable as exc:
        raise HTTPException(status_code=503, detail="configured model provider is unavailable") from exc
    return {"accepted": True, "session_id": session_id, "run_id": run_id}


@app.post("/internal/runtime/sessions/{session_id}/resume", dependencies=[Depends(require_chat_admission)])
def resume_session(session_id: str, request: ResumeSessionRequest | None = None) -> dict[str, object]:
    try:
        return adapter.resume_session(
            session_id,
            conversation_context=[] if request is None else request.conversation_context,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="DSH runtime failed to resume") from exc


@app.post("/internal/runtime/sessions/{session_id}/cancel")
def cancel_session(session_id: str, mode: str = Query("hard")) -> dict[str, object]:
    try:
        return adapter.cancel_session(session_id, mode)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/internal/runtime/sessions/{session_id}/release")
def release_session(session_id: str) -> dict[str, object]:
    try:
        return adapter.release_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.delete("/internal/runtime/sessions/{session_id}")
def close_session(session_id: str) -> dict[str, object]:
    return release_session(session_id)


@app.get("/internal/runtime/sessions/{session_id}/events")
async def events(session_id: str, replay: bool = False) -> StreamingResponse:
    try:
        subscriber = adapter.subscribe(session_id, replay=replay)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    bridge = _AsyncSubscriberBridge(subscriber)

    async def stream() -> AsyncIterator[bytes]:
        try:
            while True:
                try:
                    item = await bridge.get()
                except TimeoutError:
                    yield b": heartbeat\n\n"
                    continue
                if item is None:
                    return
                yield f"event: workflow-trace\ndata: {json.dumps(item, separators=(',', ':'))}\n\n".encode()
        finally:
            bridge.close()
            adapter.unsubscribe(session_id, subscriber)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.on_event("shutdown")
def shutdown() -> None:
    adapter.close()
