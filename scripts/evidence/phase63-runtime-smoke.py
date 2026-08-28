#!/usr/bin/env python3
"""Keyless Phase 63 Runtime Adapter/DSH composition smoke."""

from __future__ import annotations

import json
import uuid
from urllib.request import Request, urlopen


ROOT = "http://127.0.0.1:8400"
RUNTIME = f"{ROOT}/internal/runtime"


def get(path: str) -> dict[str, object]:
    with urlopen(ROOT + path, timeout=20) as response:
        assert response.status == 200
        return json.load(response)


def post(path: str, payload: dict[str, object] | None = None) -> tuple[int, dict[str, object]]:
    body = None if payload is None else json.dumps(payload).encode()
    request = Request(
        RUNTIME + path,
        data=body,
        headers={"content-type": "application/json"} if body else {},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        return response.status, json.load(response)


readiness = get("/readyz")
assert readiness["sdk"] == "deepseek-harness-sdk==0.1.1rc1"
assert readiness["runtime_bin"] == "deepseek-harness-runtime-bin==0.1.1rc1"
assert readiness["plugin_profile"] == "research"
assert readiness["enabled_plugin_ids"] == ["compaction", "guard", "web-search"]
assert str(readiness["composition_hash"]).startswith("sha256:")
public_readiness = json.dumps(readiness).lower()
assert "deepseek_api_key" not in public_readiness
assert "authorization" not in public_readiness

session_id = f"phase63-{uuid.uuid4().hex}"
status, created = post(
    "/sessions",
    {"session_id": session_id, "trace_id": f"trace-{uuid.uuid4().hex}"},
)
assert status == 201
assert created["status"] == "ready"
assert created["process_ownership"] == "dedicated"

operations = get("/internal/runtime/operations")
runtime = operations["runtime"]
assert isinstance(runtime, dict)
assert runtime["plugin_profile"] == "research"
assert runtime["composition_hash"] == readiness["composition_hash"]
assert runtime["enabled_plugin_ids"] == readiness["enabled_plugin_ids"]
assert operations["sessions"]["active"] == 1

status, released = post(f"/sessions/{session_id}/release")
assert status == 200
assert released["status"] == "closed"
assert get("/internal/runtime/operations")["sessions"]["active"] == 0

print(json.dumps({
    "composition_hash": readiness["composition_hash"],
    "enabled_plugin_ids": readiness["enabled_plugin_ids"],
    "plugin_profile": readiness["plugin_profile"],
    "runtime_bin": readiness["runtime_bin"],
    "sdk": readiness["sdk"],
    "session_lifecycle": "created-and-released",
}, sort_keys=True))
