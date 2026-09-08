from fastapi.testclient import TestClient

from app import main, product_api


def test_permission_requires_personal_login_confirmation_and_closed_identity(monkeypatch):
    calls = []
    monkeypatch.setattr(product_api, "resolve_user", lambda request: {
        "username": "synthetic-user", "_workspace": {"workspace_id": "synthetic-workspace"}})
    monkeypatch.setattr(product_api, "_backend_request", lambda method, path, payload=None, **kwargs:
        calls.append((method, path, payload, kwargs)) or {"can_start": False, "blocked_reason": "budget_enforcement_unqualified"})
    client = TestClient(main.app)
    path = "/api/product/research/tasks/task_synthetic/continuation-permission"
    payload = {"idempotency_key": "synthetic-confirm", "token_limit": 1000, "confirmed_artifact_ids": ["artifact_synthetic"]}
    assert client.get(path, headers={"Authorization": "Bearer product-token"}).status_code == 401
    assert calls == []
    client.cookies.set("byq_session", "synthetic-session")
    assert client.post(path, json=payload).status_code == 403
    headers = {"x-byq-continuation-confirmation": "v1"}
    assert client.post(path, headers={**headers, "sec-fetch-site": "cross-site"}, json=payload).status_code == 403
    assert client.post(path, headers=headers, json={**payload, "owner_principal": "other"}).status_code == 422
    assert calls == []
    result = client.post(path, headers={**headers, "x-byq-owner-principal": "forged"}, json=payload)
    assert result.status_code == 201
    assert result.json()["can_start"] is False
    assert calls[-1][3]["headers"]["x-byq-owner-principal"] == "synthetic-user"
    assert calls[-1][2] == payload
    assert client.get(path).status_code == 200
    assert client.post(path + "/revoke", headers=headers, json={"grant_version": 1}).status_code == 200
    assert calls[-1][1].endswith("/continuation-permission/revoke")
