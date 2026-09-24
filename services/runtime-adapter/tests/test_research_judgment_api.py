"""ADR-0085 P4: the authenticated minimal Runtime Adapter judgment route.

Runs only where FastAPI is installed (the runtime-adapter image); skipped on the
plain host architecture lane. It proves the route rejects unauthenticated and
forged callers BEFORE any admission/model turn, and derives call/generation
identity server-side rather than from forgeable request headers.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # TestClient requires httpx

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import research_judgment_api as api  # noqa: E402

TOKEN = "p4-runtime-service-token"
ATTEMPT = "3:backtest_analysis:1"
HEADERS = {
    "x-byq-runtime-judgment-token": TOKEN,
    "x-byq-judgment-attempt": ATTEMPT,
    "x-byq-owner-principal": "owner", "x-byq-workspace-id": "workspace",
    "x-byq-actor-principal": "owner", "x-byq-trace-id": "trace",
    "x-byq-session-id": "runtime-session", "x-byq-dsh-run-id": "caller-supplied-generation",
}
TASK = "task_" + "a" * 32


def _client(monkeypatch) -> TestClient:
    monkeypatch.setenv("BYQ_RUNTIME_JUDGMENT_TOKEN", TOKEN)
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def _spy(monkeypatch):
    calls: list[dict] = []

    def fake_run_stage_judgment(**kwargs):
        calls.append(kwargs)
        return {"schema_version": "research-judgment-result-receipt.v1",
                "call_identity": kwargs["call_identity"], "progress": {"continue": False}}

    monkeypatch.setattr(api, "run_stage_judgment", fake_run_stage_judgment)
    return calls


def test_healthz_reports_the_bounded_authenticated_entry(monkeypatch):
    body = _client(monkeypatch).get("/internal/runtime/research-judgment/healthz").json()
    assert body["status"] == "ok"
    assert body["authenticated"] is True


def test_no_credentials_can_never_reach_admission_or_the_model(monkeypatch):
    client = _client(monkeypatch)
    calls = _spy(monkeypatch)
    # No service token: forged identity headers alone must not trigger anything.
    forged = {k: v for k, v in HEADERS.items() if k != "x-byq-runtime-judgment-token"}
    response = client.post(f"/internal/runtime/research-judgment/{TASK}/run",
                           headers=forged, json={"model_result": "forged"})
    assert response.status_code == 401
    assert calls == []


def test_forged_service_token_is_rejected(monkeypatch):
    client = _client(monkeypatch)
    calls = _spy(monkeypatch)
    response = client.post(f"/internal/runtime/research-judgment/{TASK}/run",
                           headers={**HEADERS, "x-byq-runtime-judgment-token": "wrong-token"},
                           json={})
    assert response.status_code == 401
    assert calls == []


def test_disabled_entry_fails_closed(monkeypatch):
    monkeypatch.delenv("BYQ_RUNTIME_JUDGMENT_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(api.router)
    response = TestClient(app).post(f"/internal/runtime/research-judgment/{TASK}/run",
                                    headers=HEADERS, json={})
    assert response.status_code == 503


def test_authenticated_but_incomplete_context_is_rejected(monkeypatch):
    client = _client(monkeypatch)
    calls = _spy(monkeypatch)
    partial = {k: v for k, v in HEADERS.items() if k != "x-byq-workspace-id"}
    response = client.post(f"/internal/runtime/research-judgment/{TASK}/run",
                           headers=partial, json={})
    assert response.status_code == 401
    assert calls == []


def test_missing_attempt_binding_never_reaches_admission(monkeypatch):
    client = _client(monkeypatch)
    calls = _spy(monkeypatch)
    no_attempt = {k: v for k, v in HEADERS.items() if k != "x-byq-judgment-attempt"}
    response = client.post(f"/internal/runtime/research-judgment/{TASK}/run",
                           headers=no_attempt, json={})
    assert response.status_code == 422
    assert calls == []


def test_run_derives_non_forgeable_identity_and_ignores_the_body(monkeypatch):
    client = _client(monkeypatch)
    calls = _spy(monkeypatch)
    response = client.post(
        f"/internal/runtime/research-judgment/{TASK}/run", headers=HEADERS,
        json={"model_result": "must be ignored", "next_action": "execute",
              "call_identity": "caller-chosen"})
    assert response.status_code == 200
    invocation = response.json()["adapter_invocation"]
    # The durable call identity is the authoritative attempt-derived value, never a
    # caller header/body value.
    assert invocation["call_identity"] == calls[0]["call_identity"]
    assert invocation["call_identity"].startswith("byq-judgment-")
    assert invocation["call_identity"] != "caller-chosen"
    assert invocation["attempt"] == ATTEMPT
    assert invocation["id"].startswith("byq-adapter-")
    assert invocation["id"] != HEADERS["x-byq-dsh-run-id"]
    assert calls[0]["identity"]["dsh_run_id"] == invocation["id"]
    assert calls[0]["trusted_headers"]["x-byq-workspace-id"] == "workspace"
    # Honest: no real runtime-generation mapping is claimed.
    assert response.json()["dsh_generation"]["status"] == "not_available"


def test_retry_reuses_the_same_stable_call_identity(monkeypatch):
    client = _client(monkeypatch)
    calls = _spy(monkeypatch)
    first = client.post(f"/internal/runtime/research-judgment/{TASK}/run",
                        headers=HEADERS, json={}).json()
    # A retry of the SAME authoritative attempt (e.g. after an adapter restart)
    # uses the SAME durable identity, so the Backend admission is replayed instead
    # of consuming a second model-call slot.
    retry = client.post(f"/internal/runtime/research-judgment/{TASK}/run",
                        headers=HEADERS, json={}).json()
    assert first["adapter_invocation"]["call_identity"] == \
        retry["adapter_invocation"]["call_identity"]
    # A legitimate new stage/iteration gets a new identity.
    other = client.post(f"/internal/runtime/research-judgment/{TASK}/run",
                        headers={**HEADERS, "x-byq-judgment-attempt": "4:iteration_comparison:1"},
                        json={}).json()
    assert other["adapter_invocation"]["call_identity"] != \
        first["adapter_invocation"]["call_identity"]
    assert calls[0]["call_identity"] == calls[1]["call_identity"]


def test_non_task_identity_is_rejected_after_authentication(monkeypatch):
    client = _client(monkeypatch)
    calls = _spy(monkeypatch)
    response = client.post("/internal/runtime/research-judgment/not-a-task/run",
                           headers=HEADERS, json={})
    assert response.status_code == 422
    assert calls == []
