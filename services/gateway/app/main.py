from collections.abc import Iterator
import os

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


SERVICE = "byq-gateway"
VERSION = "0.1.0"
app = FastAPI(title="BeyondQuant Gateway", version=VERSION)
RUNTIME_ADAPTER_URL = os.environ.get("BYQ_RUNTIME_ADAPTER_URL", "http://runtime-adapter:8400")


class RuntimeSessionRequest(BaseModel):
    session_id: str
    trace_id: str


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
    }


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
    """Prototype-only internal session seam; public chat is still out of scope."""

    try:
        response = httpx.post(
            f"{RUNTIME_ADAPTER_URL}/internal/runtime/sessions",
            json=request.model_dump(),
            timeout=20.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="runtime adapter unavailable") from exc
    return response.json()


@app.post("/internal/runtime/sessions/{session_id}/cancel")
def cancel_runtime_session(session_id: str, mode: str = "hard") -> dict[str, object]:
    try:
        response = httpx.post(
            f"{RUNTIME_ADAPTER_URL}/internal/runtime/sessions/{session_id}/cancel",
            params={"mode": mode},
            timeout=5.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="runtime adapter unavailable") from exc
    return response.json()


@app.get("/internal/workflows/{session_id}/events")
def workflow_events(session_id: str) -> StreamingResponse:
    """Internal SSE bridge carrying only BYQ WorkflowTraceEvent envelopes."""

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
