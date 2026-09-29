from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main
from app.trace_store import TraceStore


WORKSPACE_ID = "workspace-alice"
RESET_ID = "a" * 32
COOKIE = {"byq_session": "durable-auth-session"}
REQUEST_KEY = "66aebeb6-247d-48e5-bb0f-137a2befa5f2"


def session_row(conversation_id: str, session_id: str, trace_id: str) -> dict[str, str]:
    return {"conversation_id": conversation_id, "session_id": session_id, "trace_id": trace_id}


def begin_receipt(workspace_id: str = WORKSPACE_ID, sessions=None) -> dict[str, object]:
    return {
        "schema_version": main.WORKSPACE_RUNTIME_RESET_BEGIN_SCHEMA,
        "workspace_id": workspace_id,
        "reset_id": RESET_ID,
        "sessions": list(sessions or []),
    }


def finalize_receipt(workspace_id: str, conversations: list[str]) -> dict[str, object]:
    return {
        "schema_version": main.WORKSPACE_RUNTIME_RESET_FINALIZE_SCHEMA,
        "workspace_id": workspace_id,
        "reset_id": RESET_ID,
        "status": "finalized",
        "archived_conversation_ids": conversations,
    }


def workspace_begin_receipt(sessions=None) -> dict[str, object]:
    return {"schema_version": main.WORKSPACE_RESET_BEGIN_SCHEMA, "workspace_id": WORKSPACE_ID,
            "reset_id": RESET_ID, "status": "pending", "sessions": list(sessions or [])}


def workspace_finalize_receipt() -> dict[str, object]:
    return {"schema_version": main.WORKSPACE_RESET_FINALIZE_SCHEMA,
            "workspace_id": WORKSPACE_ID, "reset_id": RESET_ID,
            "status": "reset", "deleted": {"research_tasks": 2}, "already_empty": False}


@pytest.fixture
def gateway(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "resolve_user", lambda _request: {
        "username": "alice", "user_id": "user-alice",
        "_workspace": {"workspace_id": WORKSPACE_ID},
    })
    monkeypatch.setattr(main, "PRODUCT_TOKEN", "bootstrap-product-token")
    monkeypatch.setenv("BYQ_RUNTIME_AUTHORITY_TOKEN", "runtime-authority-secret")
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "trace_store", TraceStore(tmp_path / "traces"))
    sidecars = tmp_path / "sidecars"
    sidecars.mkdir()
    monkeypatch.setattr(main, "answer_delivery", SimpleNamespace(root=sidecars, suffix="answers"))
    monkeypatch.setattr(main, "domain_call_delivery", SimpleNamespace(root=sidecars, suffix="domain-calls"))
    monkeypatch.setattr(main, "task_continuation_delivery", SimpleNamespace(root=sidecars))
    return TestClient(main.app), sidecars


def add_live_session(conversation_id: str, session_id: str, trace_id: str) -> main.ProductSession:
    session = main.ProductSession(
        conversation_id=conversation_id,
        session_id=session_id,
        trace_id=trace_id,
        principal=main.Principal(subject="alice"),
        workspace_id=WORKSPACE_ID,
    )
    main.product_sessions.add(session)
    return session


def test_current_workspace_runtime_reset_cancels_releases_and_cleans_exact_state(monkeypatch, gateway):
    client, sidecars = gateway
    sessions = [
        session_row("conversation-a", "runtime-a", "trace-a"),
        session_row("conversation-b", "runtime-b", "trace-b"),
    ]
    add_live_session("conversation-a", "runtime-a", "trace-a")
    add_live_session("conversation-b", "runtime-b", "trace-b")
    for item in sessions:
        trace_path = main.trace_store._path(item["session_id"])
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text("trace", encoding="utf-8")
        for suffix in ("answers", "domain-calls", "continuation", "continuation.receipt-backoff"):
            (sidecars / f"{item['session_id']}.{suffix}.json").write_text("{}", encoding="utf-8")

    backend_calls: list[tuple[str, str, dict[str, object], str, str]] = []

    def backend(method, path, payload, principal, workspace_id):
        backend_calls.append((method, path, payload, principal.subject, workspace_id))
        if path.endswith("/begin"):
            return begin_receipt(sessions=sessions)
        return finalize_receipt(workspace_id, ["conversation-a", "conversation-b"])

    adapter_calls: list[str] = []

    def adapter(path, *, payload=None, timeout=20.0):
        adapter_calls.append(path)
        session_id = "runtime-a" if "runtime-a" in path else "runtime-b"
        trace_id = "trace-a" if session_id == "runtime-a" else "trace-b"
        if path.endswith("/cancel?mode=hard") and session_id == "runtime-b":
            error = HTTPException(status_code=409, detail="runtime session is not available for this operation")
            error.adapter_conflict_detail = f"session {session_id} has no active prompt"
            raise error
        if path.endswith("/cancel?mode=hard"):
            return {"session_id": session_id, "trace_id": trace_id,
                    "status": "interrupted", "active_prompt": False}
        return {"session_id": session_id, "trace_id": trace_id,
                "status": "closed", "active_prompt": False}

    monkeypatch.setattr(main, "_workspace_runtime_reset_backend_request", backend)
    monkeypatch.setattr(main, "_adapter_post", adapter)

    response = client.post("/v1/workspaces/current/runtime-reset", cookies=COOKIE)

    assert response.status_code == 200
    assert response.json() == {
        "status": "reset", "workspace_id": WORKSPACE_ID,
        "archived_conversation_count": 2,
    }
    assert backend_calls == [
        ("POST", "/internal/workspace-runtime-reset/begin",
         {"schema_version": main.WORKSPACE_RUNTIME_RESET_BEGIN_SCHEMA}, "alice", WORKSPACE_ID),
        ("POST", "/internal/workspace-runtime-reset/finalize", {
            "schema_version": main.WORKSPACE_RUNTIME_RESET_FINALIZE_SCHEMA,
            "reset_id": RESET_ID,
            "released_sessions": ["runtime-a", "runtime-b"],
        }, "alice", WORKSPACE_ID),
    ]
    assert adapter_calls == [
        "/internal/runtime/sessions/runtime-a/cancel?mode=hard",
        "/internal/runtime/sessions/runtime-a/release",
        "/internal/runtime/sessions/runtime-b/cancel?mode=hard",
        "/internal/runtime/sessions/runtime-b/release",
    ]
    for item in sessions:
        assert main.trace_store.read(item["session_id"]) == []
        assert main.product_sessions.find_owned(item["conversation_id"], main.Principal(subject="alice")) is None
        for suffix in ("answers", "domain-calls", "continuation", "continuation.receipt-backoff"):
            assert not (sidecars / f"{item['session_id']}.{suffix}.json").exists()


def test_backend_workspace_denial_stops_before_adapter_or_finalize(monkeypatch, gateway):
    client, _sidecars = gateway
    calls = []

    def backend(method, path, _payload, principal, workspace_id):
        calls.append((method, path, principal.subject, workspace_id))
        raise HTTPException(status_code=404, detail="Workspace runtime reset was rejected")

    monkeypatch.setattr(main, "_workspace_runtime_reset_backend_request", backend)
    monkeypatch.setattr(main, "_adapter_post", lambda *_args, **_kwargs: pytest.fail("adapter must not be touched"))

    response = client.post("/v1/workspaces/current/runtime-reset", cookies=COOKIE)

    assert response.status_code == 404
    assert calls == [("POST", "/internal/workspace-runtime-reset/begin", "alice", WORKSPACE_ID)]


def test_release_failure_keeps_backend_fence_and_gateway_state_for_retry(monkeypatch, gateway):
    client, sidecars = gateway
    row = session_row("conversation-a", "runtime-a", "trace-a")
    session = add_live_session(**row)
    trace_path = main.trace_store._path("runtime-a")
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text("trace", encoding="utf-8")
    answer_sidecar = sidecars / "runtime-a.answers.json"
    answer_sidecar.write_text("{}", encoding="utf-8")
    backend_paths: list[str] = []

    def backend(_method, path, _payload, _principal, workspace_id):
        backend_paths.append(path)
        if path.endswith("/begin"):
            return begin_receipt(sessions=[row])
        return finalize_receipt(workspace_id, ["conversation-a"])

    def adapter(path, *, payload=None, timeout=20.0):
        if path.endswith("/cancel?mode=hard"):
            return {"session_id": "runtime-a", "trace_id": "trace-a",
                    "status": "interrupted", "active_prompt": False}
        raise HTTPException(status_code=503, detail="runtime adapter unavailable")

    monkeypatch.setattr(main, "_workspace_runtime_reset_backend_request", backend)
    monkeypatch.setattr(main, "_adapter_post", adapter)

    response = client.post("/v1/workspaces/current/runtime-reset", cookies=COOKIE)

    assert response.status_code == 503
    assert backend_paths == ["/internal/workspace-runtime-reset/begin"]
    assert session.released is False
    assert main.product_sessions.find_owned("conversation-a", main.Principal(subject="alice")) is session
    assert trace_path.exists()
    assert answer_sidecar.exists()


def test_retry_reuses_fenced_receipt_and_tolerates_already_released_adapter(monkeypatch, gateway):
    client, sidecars = gateway
    row = session_row("conversation-a", "runtime-a", "trace-a")
    add_live_session(**row)
    trace_path = main.trace_store._path("runtime-a")
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text("trace", encoding="utf-8")
    (sidecars / "runtime-a.answers.json").write_text("{}", encoding="utf-8")
    backend_paths: list[str] = []
    adapter_attempt = 0

    def backend(_method, path, payload, _principal, workspace_id):
        backend_paths.append(path)
        if path.endswith("/begin"):
            return begin_receipt(sessions=[row])
        assert payload["reset_id"] == RESET_ID
        return finalize_receipt(workspace_id, ["conversation-a"])

    def adapter(path, *, payload=None, timeout=20.0):
        nonlocal adapter_attempt
        if path.endswith("/cancel?mode=hard"):
            adapter_attempt += 1
            if adapter_attempt == 1:
                return {"session_id": "runtime-a", "trace_id": "trace-a",
                        "status": "interrupted", "active_prompt": False}
            raise HTTPException(status_code=404, detail="runtime session not found")
        if adapter_attempt == 1:
            raise HTTPException(status_code=503, detail="runtime adapter unavailable")
        raise HTTPException(status_code=404, detail="runtime session not found")

    monkeypatch.setattr(main, "_workspace_runtime_reset_backend_request", backend)
    monkeypatch.setattr(main, "_adapter_post", adapter)

    first = client.post("/v1/workspaces/current/runtime-reset", cookies=COOKIE)
    second = client.post("/v1/workspaces/current/runtime-reset", cookies=COOKIE)

    assert first.status_code == 503
    assert second.status_code == 200
    assert second.json()["status"] == "reset"
    assert backend_paths == [
        "/internal/workspace-runtime-reset/begin",
        "/internal/workspace-runtime-reset/begin",
        "/internal/workspace-runtime-reset/finalize",
    ]
    assert main.trace_store.read("runtime-a") == []
    assert not (sidecars / "runtime-a.answers.json").exists()


def test_runtime_reset_rejects_duplicate_backend_sessions_before_adapter(monkeypatch, gateway):
    client, _sidecars = gateway
    duplicate = [
        session_row("conversation-a", "runtime-a", "trace-a"),
        session_row("conversation-b", "runtime-a", "trace-b"),
    ]
    paths = []

    def backend(_method, path, _payload, _principal, _workspace):
        paths.append(path)
        return begin_receipt(sessions=duplicate)

    monkeypatch.setattr(main, "_workspace_runtime_reset_backend_request", backend)
    monkeypatch.setattr(main, "_adapter_post", lambda *_args, **_kwargs: pytest.fail("invalid receipt must not release"))

    response = client.post("/v1/workspaces/current/runtime-reset", cookies=COOKIE)

    assert response.status_code == 502
    assert paths == ["/internal/workspace-runtime-reset/begin"]


def test_product_token_cannot_reset_workspace_runtime(monkeypatch, gateway):
    client, _sidecars = gateway
    monkeypatch.setattr(main, "_workspace_runtime_reset_backend_request",
                        lambda *_args, **_kwargs: pytest.fail("Product Token cannot reach Backend reset"))
    monkeypatch.setattr(main, "_adapter_post",
                        lambda *_args, **_kwargs: pytest.fail("Product Token cannot reach Adapter"))

    response = client.post(
        "/v1/workspaces/current/runtime-reset",
        headers={"Authorization": "Bearer bootstrap-product-token"},
    )

    assert response.status_code == 401


def test_backend_reset_request_uses_runtime_authority_and_exact_workspace_headers(monkeypatch):
    observed = {}

    class Response:
        def raise_for_status(self):
            return None

        @staticmethod
        def json():
            return {"accepted": True}

    def request(method, url, *, json, headers, timeout):
        observed.update(method=method, url=url, payload=json, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr(main.httpx, "request", request)
    monkeypatch.setenv("BYQ_RUNTIME_AUTHORITY_TOKEN", "runtime-authority-secret")

    receipt = main._workspace_runtime_reset_backend_request(
        "POST", "/internal/workspace-runtime-reset/begin",
        {"schema_version": main.WORKSPACE_RUNTIME_RESET_BEGIN_SCHEMA},
        main.Principal(subject="alice"), WORKSPACE_ID,
    )

    assert receipt == {"accepted": True}
    assert observed == {
        "method": "POST",
        "url": f"{main.BACKEND_URL}/internal/workspace-runtime-reset/begin",
        "payload": {"schema_version": main.WORKSPACE_RUNTIME_RESET_BEGIN_SCHEMA},
        "headers": {
            "Authorization": "Bearer runtime-authority-secret",
            "x-byq-owner-principal": "alice",
            "x-byq-workspace-id": WORKSPACE_ID,
        },
        "timeout": 8.0,
    }


def test_product_workspace_reset_releases_sessions_and_returns_scoped_receipt(monkeypatch, gateway):
    client, _sidecars = gateway
    session = session_row("conversation-a", "runtime-a", "trace-a")
    add_live_session(**session)
    calls = []

    def backend(_method, path, payload, _principal, _workspace):
        calls.append((path, payload))
        return workspace_begin_receipt([session]) if path.endswith("/begin") else workspace_finalize_receipt()

    def adapter(path, *, payload=None, timeout=20.0):
        return {"session_id": "runtime-a", "trace_id": "trace-a", "active_prompt": False,
                "status": "interrupted" if path.endswith("cancel?mode=hard") else "closed"}

    monkeypatch.setattr(main, "_workspace_runtime_reset_backend_request", backend)
    monkeypatch.setattr(main, "_adapter_post", adapter)
    response = client.post("/v1/workspaces/current/reset", cookies=COOKIE,
                           headers={"Idempotency-Key": REQUEST_KEY})
    assert response.status_code == 200
    assert response.json() == {"status": "reset", "workspace_id": WORKSPACE_ID,
                               "deleted": {"research_tasks": 2}, "already_empty": False}
    assert calls == [
        ("/internal/workspace-reset/begin", {"schema_version": main.WORKSPACE_RESET_BEGIN_SCHEMA,
                                             "request_key": REQUEST_KEY}),
        ("/internal/workspace-reset/finalize", {"schema_version": main.WORKSPACE_RESET_FINALIZE_SCHEMA,
                                                "reset_id": RESET_ID, "request_key": REQUEST_KEY,
                                                "released_sessions": ["runtime-a"]}),
    ]


def test_product_workspace_reset_completed_retry_skips_adapter(monkeypatch, gateway):
    client, _sidecars = gateway
    monkeypatch.setattr(main, "_workspace_runtime_reset_backend_request", lambda *_args: {
        "schema_version": main.WORKSPACE_RESET_BEGIN_SCHEMA, "workspace_id": WORKSPACE_ID,
        "status": "completed", "receipt": {"status": "reset", "workspace_id": WORKSPACE_ID,
                                         "deleted": {}, "already_empty": True},
    })
    monkeypatch.setattr(main, "_adapter_post", lambda *_args, **_kwargs: pytest.fail("no adapter retry"))
    response = client.post("/v1/workspaces/current/reset", cookies=COOKIE,
                           headers={"Idempotency-Key": REQUEST_KEY})
    assert response.status_code == 200
    assert response.json()["already_empty"] is True


def test_product_workspace_reset_blocked_receipt_is_terminal(monkeypatch, gateway):
    client, _sidecars = gateway
    monkeypatch.setattr(main, "_workspace_runtime_reset_backend_request", lambda *_args: {
        "schema_version": main.WORKSPACE_RESET_BEGIN_SCHEMA, "workspace_id": WORKSPACE_ID,
        "status": "completed", "receipt": {"status": "blocked", "workspace_id": WORKSPACE_ID,
                                         "reason": "active Job prevents reset"},
    })
    response = client.post("/v1/workspaces/current/reset", cookies=COOKIE,
                           headers={"Idempotency-Key": REQUEST_KEY})
    assert response.status_code == 409
    assert response.json() == {"detail": "active Job prevents reset", "reset_terminal": True}


def test_product_workspace_reset_requires_login_and_uuid(monkeypatch, gateway):
    client, _sidecars = gateway
    monkeypatch.setattr(main, "_workspace_runtime_reset_backend_request",
                        lambda *_args: pytest.fail("invalid request reached Backend"))
    assert client.post("/v1/workspaces/current/reset", headers={"Idempotency-Key": REQUEST_KEY}).status_code == 401
    assert client.post("/v1/workspaces/current/reset", cookies=COOKIE,
                       headers={"Idempotency-Key": "not-a-uuid"}).status_code == 422
