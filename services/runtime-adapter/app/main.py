from __future__ import annotations

import asyncio
import json
import queue
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .runtime import RuntimeAdapter, SessionConflict


class CreateSessionRequest(BaseModel):
    session_id: str
    trace_id: str


class PromptRequest(BaseModel):
    content: str


adapter = RuntimeAdapter()
app = FastAPI(title="BeyondQuant DSH Runtime Adapter", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"service": "byq-dsh-runtime-adapter", "status": "ok", "version": "0.1.0"}


@app.get("/readyz")
def readyz() -> dict[str, object]:
    return {"service": "byq-dsh-runtime-adapter", "status": "ok", **adapter.readiness()}


@app.post("/internal/runtime/sessions", status_code=201)
def create_session(request: CreateSessionRequest) -> dict[str, object]:
    try:
        return adapter.create_session(request.session_id, request.trace_id)
    except SessionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="DSH runtime failed to initialize") from exc


@app.post("/internal/runtime/sessions/{session_id}/prompt", status_code=202)
def submit_prompt(session_id: str, request: PromptRequest) -> dict[str, object]:
    try:
        run_id = adapter.submit_prompt(session_id, request.content)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"accepted": True, "session_id": session_id, "run_id": run_id}


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
async def events(session_id: str) -> StreamingResponse:
    try:
        subscriber = adapter.subscribe(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def stream() -> AsyncIterator[bytes]:
        try:
            while True:
                try:
                    item = await asyncio.to_thread(subscriber.get, True, 15.0)
                except queue.Empty:
                    yield b": heartbeat\n\n"
                    continue
                if item is None:
                    return
                yield f"event: workflow-trace\ndata: {json.dumps(item, separators=(',', ':'))}\n\n".encode()
        finally:
            adapter.unsubscribe(session_id, subscriber)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.on_event("shutdown")
def shutdown() -> None:
    adapter.close()
