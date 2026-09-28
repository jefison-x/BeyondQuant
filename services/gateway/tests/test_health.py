import os

from fastapi.testclient import TestClient

from app import auth_api, main


client = TestClient(main.app)


def test_healthz_is_local_and_stable() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "service": "byq-gateway",
        "status": "ok",
        "version": "0.1.0",
    }


def test_readyz_reports_runtime_adapter_integration() -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "service": "byq-gateway",
        "status": "ok",
        "version": "0.1.0",
        "dsh_runtime_integration": "runtime-adapter",
        "product_authentication": "configured" if os.environ.get("BYQ_PRODUCT_TOKEN") else "missing",
    }


def test_legacy_gateway_runtime_proxy_routes_are_absent() -> None:
    missing_routes = (
        ("GET", "/internal/runtime/health", None),
        ("POST", "/internal/runtime/sessions", {"session_id": "synthetic", "trace_id": "synthetic"}),
        ("POST", "/internal/runtime/sessions/synthetic/prompt", {"content": "synthetic"}),
        ("POST", "/internal/runtime/sessions/synthetic/cancel", None),
        ("POST", "/internal/runtime/sessions/synthetic/release", None),
        ("GET", "/internal/workflows/synthetic/events", None),
    )

    for method, path, payload in missing_routes:
        response = client.request(method, path, json=payload)
        assert response.status_code == 404, (method, path, response.text)


def test_browser_session_exposes_only_bounded_personal_workspace(monkeypatch) -> None:
    workspace = {
        "contract": "personal-workspace.v1",
        "workspace_id": "workspace_alice",
        "kind": "personal",
        "display_name": "Alice 的个人工作区",
        "role": "owner",
        "owner_user_id": "must-not-leak",
        "membership_id": "must-not-leak",
    }
    monkeypatch.setattr(auth_api, "resolve_user", lambda _request: {
        "user_id": "user_alice",
        "username": "alice",
        "display_name": "量化小周",
        "role": "user",
        "_workspace": workspace,
    })
    browser = TestClient(main.app)
    browser.cookies.set("byq_session", "session_alice")
    response = browser.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json() == {
        "subject": "alice",
        "display_name": "量化小周",
        "role": "user",
        "workspace": {
            "contract": "personal-workspace.v1",
            "workspace_id": "workspace_alice",
            "kind": "personal",
            "display_name": "Alice 的个人工作区",
            "role": "owner",
        },
    }
    assert "owner_user_id" not in response.text
    assert "membership_id" not in response.text


def test_browser_login_requires_and_returns_bounded_workspace(monkeypatch) -> None:
    monkeypatch.setattr(auth_api, "login_user", lambda _username, _password: {
        "session_id": "session_alice",
        "user": {"username": "alice", "role": "user"},
        "workspace": {
            "contract": "personal-workspace.v1",
            "workspace_id": "workspace_alice",
            "kind": "personal",
            "display_name": "Alice 的个人工作区",
            "role": "owner",
        },
    })
    response = client.post("/api/auth/login", json={"username": "alice", "password": "password123"})
    assert response.status_code == 200
    assert response.json()["workspace"]["workspace_id"] == "workspace_alice"
    assert response.cookies.get("byq_session") == "session_alice"
