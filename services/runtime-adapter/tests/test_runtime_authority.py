from __future__ import annotations

import os
import re
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.runtime as runtime_module
from app import main
from app.runtime import RuntimeAdapter
from .test_process_cleanup import FakeHarness, release_compatibility, wait_for_status


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    """Keep authority tests independent of the image's root-turn selector."""

    FakeHarness.reset()
    monkeypatch.setenv("BYQ_DSH_PROCESS_OWNERSHIP", "session")
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("BYQ_DSH_RUN_TIMEOUT_SECONDS", "3600")
    monkeypatch.setenv("BYQ_DSH_SUBAGENT_TIMEOUT_SECONDS", "3600")
    monkeypatch.setenv("BYQ_DSH_NO_PROGRESS_TIMEOUT_SECONDS", "3600")
    monkeypatch.delenv("BYQ_CREDENTIAL_RESOLVER_TOKEN", raising=False)
    runtime = RuntimeAdapter(release_compatibility(tmp_path))
    try:
        yield runtime
    finally:
        runtime.close()
        for harness in FakeHarness.instances:
            harness.close()


def _current_response(boot_id: str, **overrides):
    body = {
        "schema_version": "byq-runtime-authority-current.v1",
        "boot_id": boot_id,
        "authority_epoch": 1,
        "status": "current",
    }
    body.update(overrides)
    return SimpleNamespace(
        status_code=200,
        json=lambda: body,
        raise_for_status=lambda: None,
    )


def _stub_current(monkeypatch, boot_id: str, calls: list | None = None):
    def get(url, **kwargs):
        if calls is not None:
            calls.append((url, kwargs))
        assert url.endswith("/internal/runtime-authority/current")
        return _current_response(boot_id)

    monkeypatch.setattr(runtime_module.httpx, "get", get)


def test_boot_identity_is_per_process_and_authority_route_is_exact(adapter, monkeypatch):
    monkeypatch.setattr(main, "adapter", adapter)
    same_process_adapter = RuntimeAdapter(adapter._compatibility)
    client = TestClient(main.app)
    try:
        assert adapter._root_scoped is False
        assert re.fullmatch(r"[0-9a-f]{32}", adapter.boot_id)
        assert same_process_adapter.boot_id == adapter.boot_id
        service_root = Path(__file__).resolve().parents[1]
        child_env = {key: os.environ[key] for key in ("PATH", "PYTHONPATH") if key in os.environ}
        child_id = subprocess.run(
            [sys.executable, "-c", "from app.runtime import _process_boot_id; print(_process_boot_id())"],
            cwd=service_root, env=child_env, check=True, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        assert re.fullmatch(r"[0-9a-f]{32}", child_id)
        assert child_id != adapter.boot_id
        response = client.get("/internal/runtime/authority")
        assert response.status_code == 200
        assert response.json() == {
            "schema_version": "byq-runtime-adapter-authority.v1",
            "boot_id": adapter.boot_id,
            "status": "ready",
        }

        def unavailable(*_args, **_kwargs):
            raise httpx.ConnectError("synthetic Backend outage")

        monkeypatch.setattr(runtime_module.httpx, "get", unavailable)
        assert client.get("/readyz").status_code == 200
    finally:
        same_process_adapter.close()
        adapter.close()


def test_session_creation_requires_exact_current_backend_boot(adapter, monkeypatch):
    monkeypatch.setattr(main, "adapter", adapter)
    calls: list = []
    _stub_current(monkeypatch, adapter.boot_id, calls)
    response = TestClient(main.app).post("/internal/runtime/sessions", json={
        "session_id": "authority-current",
        "trace_id": "authority-current-trace",
        "owner_principal": "alice",
        "workspace_id": "workspace_alice",
    })
    try:
        assert response.status_code == 201
        assert response.json()["boot_id"] == adapter.boot_id
        assert len(calls) == 1
        url, kwargs = calls[0]
        assert url.endswith("/internal/runtime-authority/current")
        assert "headers" not in kwargs
        assert len(FakeHarness.instances) == 1 and FakeHarness.instances[0].started
        assert FakeHarness.instances[0].config.env["BYQ_RUNTIME_BOOT_ID"] == adapter.boot_id
    finally:
        adapter.close()


@pytest.mark.parametrize("failure", ["mismatch", "unavailable", "invalid"])
def test_session_and_prompt_admission_fail_closed_before_dsh_traffic(adapter, monkeypatch, failure):
    monkeypatch.setattr(main, "adapter", adapter)
    client = TestClient(main.app)
    if failure == "mismatch":
        _stub_current(monkeypatch, "a" * 32)
    elif failure == "invalid":
        monkeypatch.setattr(runtime_module.httpx, "get", lambda *_a, **_k: _current_response(
            adapter.boot_id, authority_epoch=True))
    else:
        def unavailable(*_args, **_kwargs):
            raise httpx.ConnectError("synthetic Backend outage")
        monkeypatch.setattr(runtime_module.httpx, "get", unavailable)

    created = client.post("/internal/runtime/sessions", json={
        "session_id": "authority-blocked",
        "trace_id": "authority-blocked-trace",
        "owner_principal": "alice",
        "workspace_id": "workspace_alice",
    })
    try:
        assert created.status_code == 503
        assert created.json() == {"detail": {"code": "runtime_authority_unavailable"}}
        assert not FakeHarness.instances
    finally:
        adapter.close()


def test_prompt_admission_rechecks_current_backend_boot(adapter, monkeypatch):
    monkeypatch.setattr(main, "adapter", adapter)
    _stub_current(monkeypatch, adapter.boot_id)
    created = TestClient(main.app).post("/internal/runtime/sessions", json={
        "session_id": "authority-prompt",
        "trace_id": "authority-prompt-trace",
        "owner_principal": "alice",
        "workspace_id": "workspace_alice",
    })
    assert created.status_code == 201
    _stub_current(monkeypatch, "b" * 32)
    response = TestClient(main.app).post("/internal/runtime/sessions/authority-prompt/prompt",
                                        json={"content": "must not start"})
    try:
        assert response.status_code == 503
        assert adapter._get("authority-prompt").active_run is None
        assert FakeHarness.instances[0].run_count == 0
    finally:
        adapter.close()


def test_terminal_evidence_is_boot_root_sequence_and_digest_bound(adapter, monkeypatch):
    monkeypatch.setattr(main, "adapter", adapter)
    _stub_current(monkeypatch, adapter.boot_id)
    client = TestClient(main.app)
    adapter.create_session("authority-terminal", "authority-terminal-trace",
                           "alice", "workspace_alice")
    try:
        root = adapter.submit_prompt("authority-terminal", "synthetic terminal evidence")
        FakeHarness.allow_run.set()
        wait_for_status(adapter, "authority-terminal", "idle")
        expected_receipt = adapter._get("authority-terminal").terminal_receipts[root]
        response = client.get(
            f"/internal/runtime/sessions/authority-terminal/terminal-evidence",
            params={"root_run_id": root, "boot_id": adapter.boot_id},
        )
        assert response.status_code == 200
        evidence = response.json()
        assert set(evidence) == {
            "schema_version", "session_id", "boot_id", "root_run_id",
            "sequence", "outcome", "receipt",
        }
        assert evidence == {
            "schema_version": "byq-runtime-terminal-evidence.v1",
            "session_id": "authority-terminal",
            "boot_id": adapter.boot_id,
            "root_run_id": root,
            "sequence": expected_receipt["sequence"],
            "outcome": "completed",
            "receipt": expected_receipt,
        }
        wrong_boot = client.get(
            "/internal/runtime/sessions/authority-terminal/terminal-evidence",
            params={"root_run_id": root, "boot_id": "0" * 32},
        )
        assert wrong_boot.status_code == 409
        wrong_session = client.get(
            "/internal/runtime/sessions/other-session/terminal-evidence",
            params={"root_run_id": root, "boot_id": adapter.boot_id},
        )
        assert wrong_session.status_code == 409
        missing = client.get(
            "/internal/runtime/sessions/authority-terminal/terminal-evidence",
            params={"root_run_id": "f" * 32, "boot_id": adapter.boot_id},
        )
        assert missing.status_code == 404

        altered = {**expected_receipt, "event_sha256": "f" * 64}
        assert client.post("/internal/runtime/sessions/authority-terminal/terminal-receipt",
                           json={"receipt": altered}).status_code == 409
        ack = client.post("/internal/runtime/sessions/authority-terminal/terminal-receipt",
                          json={"receipt": evidence["receipt"]})
        assert ack.status_code == 200 and ack.json() == {"receipt": expected_receipt}
    finally:
        adapter.close()
