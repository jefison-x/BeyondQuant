"""Focused authentication and retirement tests for the internal judgment routes."""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import research_judgment_api as api

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
    monkeypatch.setenv("BYQ_DSH_ACP_PROCESS_TRANSPORT", "local")
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def _forbid_legacy_dispatch(monkeypatch):
    calls: list[object] = []

    def forbidden(*_args, **_kwargs):
        calls.append((_args, _kwargs))
        pytest.fail("retired SDK judgment route attempted runtime dispatch")

    # Guard the historical call seams if a later edit accidentally reconnects
    # the retired route to the SDK runner or compatibility selector.
    monkeypatch.setattr(api, "run_stage_judgment", forbidden, raising=False)
    monkeypatch.setattr(api, "compatibility_for_release", forbidden, raising=False)
    from app import compat, research_judgment_entry
    monkeypatch.setattr(compat, "compatibility_for_release", forbidden)
    monkeypatch.setattr(research_judgment_entry, "run_stage_judgment", forbidden)
    return calls


def test_healthz_reports_the_authenticated_entry(monkeypatch):
    body = _client(monkeypatch).get("/internal/runtime/research-judgment/healthz").json()
    assert body["status"] == "ok"
    assert body["authenticated"] is True


def test_legacy_sdk_route_authenticates_then_returns_replacement_without_dispatch(monkeypatch):
    client = _client(monkeypatch)
    calls = _forbid_legacy_dispatch(monkeypatch)
    from app import main

    def forbidden_authority(*_args, **_kwargs):
        pytest.fail("retired SDK judgment route attempted Backend admission")

    monkeypatch.setattr(main.adapter, "require_current_backend_authority", forbidden_authority)
    monkeypatch.setenv("BYQ_DSH_COMPATIBILITY_RELEASE", "dsh-0.1.5rc1")
    response = client.post(
        f"/internal/runtime/research-judgment/{TASK}/run",
        headers=HEADERS,
        json={"model_result": {"proposal": {"forged": True}}, "call_identity": "forged"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "research_judgment_sdk_route_disabled",
        "replacement_route": f"/internal/runtime/research-judgment/{TASK}/acp-root/run",
    }
    assert calls == []


def test_no_credentials_can_never_reach_admission_or_the_model(monkeypatch):
    client = _client(monkeypatch)
    calls = _forbid_legacy_dispatch(monkeypatch)
    forged = {key: value for key, value in HEADERS.items()
              if key != "x-byq-runtime-judgment-token"}
    response = client.post(f"/internal/runtime/research-judgment/{TASK}/run",
                           headers=forged, json={"model_result": "forged"})
    assert response.status_code == 401
    assert calls == []


def test_forged_service_token_is_rejected(monkeypatch):
    client = _client(monkeypatch)
    calls = _forbid_legacy_dispatch(monkeypatch)
    response = client.post(
        f"/internal/runtime/research-judgment/{TASK}/run",
        headers={**HEADERS, "x-byq-runtime-judgment-token": "wrong-token"},
        json={},
    )
    assert response.status_code == 401
    assert calls == []


def test_disabled_entry_fails_closed(monkeypatch):
    monkeypatch.delenv("BYQ_RUNTIME_JUDGMENT_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(api.router)
    response = TestClient(app).post(
        f"/internal/runtime/research-judgment/{TASK}/run", headers=HEADERS, json={})
    assert response.status_code == 503


def test_authenticated_but_incomplete_context_is_rejected(monkeypatch):
    client = _client(monkeypatch)
    calls = _forbid_legacy_dispatch(monkeypatch)
    partial = {key: value for key, value in HEADERS.items()
               if key != "x-byq-workspace-id"}
    response = client.post(f"/internal/runtime/research-judgment/{TASK}/run",
                           headers=partial, json={})
    assert response.status_code == 401
    assert calls == []


def test_missing_attempt_binding_is_rejected(monkeypatch):
    client = _client(monkeypatch)
    calls = _forbid_legacy_dispatch(monkeypatch)
    no_attempt = {key: value for key, value in HEADERS.items()
                  if key != "x-byq-judgment-attempt"}
    response = client.post(f"/internal/runtime/research-judgment/{TASK}/run",
                           headers=no_attempt, json={})
    assert response.status_code == 422
    assert calls == []


def test_non_task_identity_is_rejected_after_authentication(monkeypatch):
    client = _client(monkeypatch)
    calls = _forbid_legacy_dispatch(monkeypatch)
    response = client.post(
        "/internal/runtime/research-judgment/not-a-task/run",
        headers=HEADERS, json={},
    )
    assert response.status_code == 422
    assert calls == []


def test_dedicated_judgment_uses_fixed_acp_family_despite_legacy_env(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app import compat, research_judgment_acp_journal as journal_module
    from app import research_judgment_acp_runner_client as runner_module
    from app import research_judgment_acp_turn as turn_module
    from app import research_judgment_entry as entry

    monkeypatch.setenv("BYQ_DSH_COMPATIBILITY_RELEASE", "dsh-0.1.5rc1")
    monkeypatch.setenv("BYQ_DSH_PROVIDER", "deepseek-official")
    monkeypatch.setenv("BYQ_DSH_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-provider-key")
    monkeypatch.setenv("BYQ_RUNTIME_AUTHORITY_TOKEN", "synthetic-authority")
    monkeypatch.setenv("BYQ_MCP_ACP_JUDGMENT_URL", "http://judgment-mcp")
    monkeypatch.setenv("BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY", "synthetic-signing-master")
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path))

    selected: list[str] = []
    captured: dict[str, str] = {}

    def select(family: str):
        selected.append(family)
        return SimpleNamespace(family=family)

    class FakeDriver:
        def __init__(self, *, compatibility, **_kwargs):
            self.compatibility = compatibility

    class FakeJournal:
        def __init__(self, *_args, **_kwargs):
            pass

    def run_root(**kwargs):
        captured["family"] = kwargs["acp"].compatibility.family
        return {"status": "synthetic"}

    monkeypatch.setattr(compat, "compatibility_for_release", select)
    monkeypatch.setattr(journal_module, "AcpJudgmentJournal", FakeJournal)
    monkeypatch.setattr(
        runner_module, "RunnerClient",
        SimpleNamespace(from_environment=lambda: object()),
    )
    monkeypatch.setattr(turn_module, "IsolatedJudgmentAcpDriver", FakeDriver)
    monkeypatch.setattr(turn_module, "run_judgment_acp_root", run_root)

    result = entry.run_acp_judgment_root(
        task_id=TASK,
        identity={
            "owner_principal": "owner", "workspace_id": "workspace",
            "actor_principal": "owner", "trace_id": "trace",
            "session_id": "runtime-session", "dsh_run_id": "adapter-root",
        },
        attempt=ATTEMPT,
        call_identity="byq-judgment-" + "b" * 32,
        trusted_headers={"x-byq-owner-principal": "owner"},
        environment=dict(__import__("os").environ),
    )

    assert result == {"status": "synthetic"}
    assert selected == ["dsh-v0.2.0-rc.2-acp"]
    assert captured["family"] == "dsh-v0.2.0-rc.2-acp"


def test_unqualified_acp_root_stays_disabled_before_backend_or_model_dispatch(monkeypatch):
    client = _client(monkeypatch)

    def forbidden(*_args, **_kwargs):
        pytest.fail("unqualified ACP judgment route attempted execution")

    from app import main
    from app.compat.dsh_acp import DshAcpCompatibility
    monkeypatch.setattr(main.adapter, "require_current_backend_authority", forbidden)
    monkeypatch.setattr(DshAcpCompatibility, "start", forbidden)
    response = client.post(
        f"/internal/runtime/research-judgment/{TASK}/acp-root/run",
        headers=HEADERS,
        json={"model_result": {"proposal": {"forged": True}}, "call_identity": "forged"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "research_judgment_acp_lifecycle_unqualified"


def test_acp_root_route_requires_runtime_authentication_and_exact_task(monkeypatch):
    client = _client(monkeypatch)
    no_service_token = {key: value for key, value in HEADERS.items()
                        if key != "x-byq-runtime-judgment-token"}
    denied = client.post(
        f"/internal/runtime/research-judgment/{TASK}/acp-root/run",
        headers=no_service_token, json={},
    )
    invalid_task = client.post(
        "/internal/runtime/research-judgment/task_bad/acp-root/run",
        headers=HEADERS, json={},
    )

    assert denied.status_code == 401
    assert invalid_task.status_code == 422
