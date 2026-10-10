"""ADR-0085 P1 / ADR-0108 Gateway execution-plan projection tests.

The browser may read the bounded plan projection through the Product API. ADR-0108
adds exactly one Product write surface, ``POST /research/tasks/{id}/execution-plan``,
which derives owner/workspace from the durable user identity; there is no Product
route for an arbitrary plan/proposal write.
"""

import httpx
from fastapi.testclient import TestClient

from app import main, product_api, user_session


def _session(monkeypatch, calls):
    resolved = {"username": "synthetic-user", "_workspace": {"workspace_id": "synthetic-workspace"}}
    # ``_trusted_agent_headers`` resolves the session user through the
    # ``user_session`` module, so both namespaces are patched.
    monkeypatch.setattr(product_api, "resolve_user", lambda request: resolved)
    monkeypatch.setattr(user_session, "resolve_user", lambda request: resolved)

    def transport(method, url, **kwargs):
        calls.append((method, url, kwargs))
        status = 201 if method.upper() == "POST" else 200
        return httpx.Response(status, json={"stage": "strategy_draft",
                                            "next_action": "draft_strategy"},
                              request=httpx.Request(method, url))

    monkeypatch.setattr(product_api.httpx, "request", transport)
    client = TestClient(main.app)
    client.cookies.set("byq_session", "synthetic-session")
    return client


def test_execution_plan_get_requires_personal_login(monkeypatch):
    calls = []
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api.httpx, "request",
                        lambda *args, **kwargs: calls.append((args, kwargs)) or None)
    client = TestClient(main.app)
    # No session cookie and no bearer credentials -> unauthenticated.
    assert client.get("/api/product/research/tasks/task_synthetic/execution-plan").status_code == 401
    assert calls == []


def test_execution_plan_get_forwards_trusted_headers_and_quotes_task_id(monkeypatch):
    calls = []
    client = _session(monkeypatch, calls)
    task = "task_" + "a" * 32
    response = client.get(f"/api/product/research/tasks/{task}/execution-plan")
    assert response.status_code == 200
    assert response.json() == {"stage": "strategy_draft", "next_action": "draft_strategy"}
    method, url, kwargs = calls[-1]
    assert method == "GET"
    assert url.endswith(f"/v1/research/tasks/{task}/execution-plan")
    headers = kwargs["headers"]
    assert headers["x-byq-owner-principal"] == "synthetic-user"
    assert headers["x-byq-workspace-id"] == "synthetic-workspace"
    # A task id is passed through the path with URL quoting (no path injection).
    calls.clear()
    client.get("/api/product/research/tasks/task%20space/execution-plan")
    assert calls[-1][1].endswith("/v1/research/tasks/task%20space/execution-plan")


def test_execution_plan_create_forwards_the_durable_user_and_ignores_a_forged_body(monkeypatch):
    calls = []
    client = _session(monkeypatch, calls)
    task = "task_" + "b" * 32
    # A forged body owner/workspace/actor must never become the trusted identity,
    # and a cross-user attempt must still be forwarded under the session user.
    forged = {"idempotency_key": "create-1", "owner_principal": "attacker",
              "workspace_id": "attacker-workspace", "actor_principal": "attacker"}
    response = client.post(f"/api/product/research/tasks/{task}/execution-plan", json=forged)
    assert response.status_code == 201
    method, url, kwargs = calls[-1]
    assert method == "POST"
    assert url.endswith(f"/v1/research/tasks/{task}/execution-plan")
    headers = kwargs["headers"]
    assert headers["x-byq-owner-principal"] == "synthetic-user"
    assert headers["x-byq-workspace-id"] == "synthetic-workspace"
    # The body is forwarded unchanged; the Backend is the authority that rejects a
    # forged owner/context, so the Gateway never rewrites identity from the body.
    assert kwargs["json"] == forged


def test_execution_plan_create_requires_personal_login(monkeypatch):
    calls = []
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api.httpx, "request",
                        lambda *args, **kwargs: calls.append((args, kwargs)) or None)
    client = TestClient(main.app)
    path = "/api/product/research/tasks/task_synthetic/execution-plan"
    # No session cookie and no bearer credentials -> unauthenticated, no call.
    assert client.post(path, json={"idempotency_key": "create-1"}).status_code == 401
    assert calls == []


def test_execution_plan_has_no_arbitrary_write_route(monkeypatch):
    calls = []
    client = _session(monkeypatch, calls)
    path = "/api/product/research/tasks/task_synthetic/execution-plan"
    # PUT/DELETE (and any non-create verb) stay absent.
    assert client.put(path, json={}).status_code in {404, 405}
    assert client.delete(path).status_code in {404, 405}
    assert calls == []
