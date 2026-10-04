"""A judgment cancellation intent comes from a logged-in user, never DSH."""

from fastapi.testclient import TestClient

from app import main, product_api


def test_cancel_intent_requires_cookie_confirmation_and_exact_user_scope(monkeypatch):
    calls = []
    monkeypatch.setattr(product_api, "GATEWAY_SERVICE_TOKEN", "synthetic-gateway-secret-at-least-32-bytes")
    monkeypatch.setattr(product_api, "resolve_user", lambda request: {
        "username": "alice", "_workspace": {"workspace_id": "workspace_alice"}})
    monkeypatch.setattr(product_api, "_backend_request", lambda method, path, payload=None, **kwargs:
                        calls.append((method, path, payload, kwargs)) or {
                            "schema_version": "byq-research-judgment-acp-cancel-intent-receipt.v1",
                            "intent_id": "byqcancel-" + "a" * 32})
    client = TestClient(main.app)
    path = "/api/product/research/tasks/task_" + "a" * 32 + "/acp-judgment/cancel-intent"
    body = {"idempotency_key": "cancel-this-root-1"}
    assert client.post(path, json=body, headers={"authorization": "Bearer product-token"}).status_code == 401
    client.cookies.set("byq_session", "synthetic-session")
    assert client.post(path, json=body).status_code == 403
    confirmed = {"x-byq-judgment-cancel-confirmation": "v1"}
    assert client.post(path, json=body, headers={**confirmed, "sec-fetch-site": "cross-site"}).status_code == 403
    assert client.post(path, json=body, headers={**confirmed, "origin": "https://other.example"}).status_code == 403
    assert client.post(path, json={**body, "root_run_id": "forged"}, headers=confirmed).status_code == 422
    assert client.post(path, json={"idempotency_key": "short"}, headers=confirmed).status_code == 422
    assert calls == []

    response = client.post(path, json=body, headers={**confirmed,
        "origin": "http://testserver", "x-byq-owner-principal": "mallory",
        "x-byq-workspace-id": "workspace_mallory"})
    assert response.status_code == 200
    method, backend_path, forwarded, kwargs = calls[0]
    assert method == "POST"
    assert backend_path.endswith("/acp-root/cancel-intent")
    assert forwarded == {
        "schema_version": "byq-research-judgment-acp-cancel-intent-request.v1",
        "idempotency_key": body["idempotency_key"]}
    assert kwargs["headers"]["x-byq-owner-principal"] == "alice"
    assert kwargs["headers"]["x-byq-workspace-id"] == "workspace_alice"
    assert kwargs["headers"]["authorization"] == "Bearer synthetic-gateway-secret-at-least-32-bytes"
    assert client.post(path, json=body, headers=confirmed).status_code == 200
    assert calls[-1][3]["headers"]["x-byq-workspace-id"] == "workspace_alice"


def test_cancel_intent_requires_private_gateway_service_credential(monkeypatch):
    monkeypatch.setattr(product_api, "GATEWAY_SERVICE_TOKEN", None)
    monkeypatch.setattr(product_api, "resolve_user", lambda request: {
        "username": "alice", "_workspace": {"workspace_id": "workspace_alice"}})
    client = TestClient(main.app)
    client.cookies.set("byq_session", "synthetic-session")
    response = client.post("/api/product/research/tasks/task_" + "a" * 32 + "/acp-judgment/cancel-intent",
                           json={"idempotency_key": "cancel-this-root-1"},
                           headers={"x-byq-judgment-cancel-confirmation": "v1"})
    assert response.status_code == 503
    monkeypatch.setattr(product_api, "GATEWAY_SERVICE_TOKEN", "synthetic-shared-token-at-least-32-bytes")
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "synthetic-shared-token-at-least-32-bytes")
    assert client.post("/api/product/research/tasks/task_" + "a" * 32 + "/acp-judgment/cancel-intent",
                       json={"idempotency_key": "cancel-this-root-1"},
                       headers={"x-byq-judgment-cancel-confirmation": "v1"}).status_code == 503
