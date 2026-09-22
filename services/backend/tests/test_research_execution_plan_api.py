"""ADR-0085 P1 Backend read-only execution-plan API tests.

The only agent-facing surface is ``GET /v1/research/tasks/{task_id}/execution-plan``.
There is deliberately no plan write route. These exercise the real FastAPI app
against isolated PostgreSQL.
"""

import os

import pytest

from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchStore
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")

BOUNDED_FIELDS = {
    "schema_version", "task_id", "plan_version", "task_version", "stage",
    "iteration", "status", "next_action", "expected_postcondition", "approval",
}


def _setup(owner: str, session: str, trace: str, *, with_plan: bool):
    headers = trusted_agent_context(owner, session_id=session, trace_id=trace)
    context = {key.removeprefix("x-byq-").replace("-", "_"): value for key, value in headers.items()}
    catalog = ConversationCatalogStore()
    catalog.create(owner, session, trace)
    catalog.close()
    store = ResearchStore()
    task = store.create_task(
        {"owner_principal": owner, "title": "Synthetic plan", "objective": "No execution",
         "trace_id": trace, "idempotency_key": f"{owner}-task"},
        trusted_context=context,
    )
    if with_plan:
        store.create_execution_plan(task["task_id"], {"idempotency_key": f"{owner}-plan"},
                                    trusted_context=context)
    return store, task["task_id"], context


def _client(monkeypatch, store):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main, "research_store", store)
    return TestClient(main.app)


def test_get_execution_plan_returns_bounded_projection(monkeypatch):
    store, task, context = _setup("plan-api-owner", "plan-api-s", "plan-api-t", with_plan=True)
    client = _client(monkeypatch, store)
    headers = {"x-byq-" + key.replace("_", "-"): value for key, value in context.items()}
    try:
        response = client.get(f"/v1/research/tasks/{task}/execution-plan", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert set(body) == BOUNDED_FIELDS
        assert body["stage"] == "strategy_draft" and body["next_action"] == "draft_strategy"
        assert body["plan_version"] == 1
        for internal in ("allowed_capabilities", "references", "prerequisites",
                         "owner_principal", "workspace_id", "conversation_id", "idempotency_key"):
            assert internal not in body
    finally:
        store.close()


def test_get_execution_plan_requires_trusted_context(monkeypatch):
    store, task, context = _setup("plan-api-ctx", "plan-api-ctx-s", "plan-api-ctx-t", with_plan=True)
    client = _client(monkeypatch, store)
    headers = {"x-byq-" + key.replace("_", "-"): value for key, value in context.items()}
    try:
        assert client.get(f"/v1/research/tasks/{task}/execution-plan").status_code == 401
        # A header/body mismatch (no body here) with missing actor is rejected.
        assert client.get(f"/v1/research/tasks/{task}/execution-plan",
                          headers={"x-byq-owner-principal": "plan-api-ctx"}).status_code == 401
    finally:
        store.close()


def test_get_execution_plan_is_owner_scoped_and_404s(monkeypatch):
    store, task, context = _setup("plan-api-a", "plan-api-a-s", "plan-api-a-t", with_plan=True)
    _other, other_task, other_context = _setup("plan-api-b", "plan-api-b-s", "plan-api-b-t",
                                               with_plan=False)
    client = _client(monkeypatch, store)
    headers = {"x-byq-" + key.replace("_", "-"): value for key, value in context.items()}
    other_headers = {"x-byq-" + key.replace("_", "-"): value for key, value in other_context.items()}
    try:
        # Foreign owner cannot read this task's plan.
        assert client.get(f"/v1/research/tasks/{task}/execution-plan",
                          headers=other_headers).status_code == 404
        # A foreign task id is 404 even for the rightful owner of another task.
        assert client.get(f"/v1/research/tasks/{other_task}/execution-plan",
                          headers=headers).status_code == 404
        # No plan exists for the other task -> 404 envelope.
        assert client.get(f"/v1/research/tasks/{other_task}/execution-plan",
                          headers=other_headers).status_code == 404
    finally:
        store.close()


def test_execution_plan_has_no_write_route(monkeypatch):
    store, task, context = _setup("plan-api-write", "plan-api-w-s", "plan-api-w-t", with_plan=True)
    client = _client(monkeypatch, store)
    headers = {"x-byq-" + key.replace("_", "-"): value for key, value in context.items()}
    try:
        path = f"/v1/research/tasks/{task}/execution-plan"
        assert client.post(path, headers=headers, json={}).status_code in {404, 405}
        assert client.put(path, headers=headers, json={}).status_code in {404, 405}
        assert client.delete(path, headers=headers).status_code in {404, 405}
    finally:
        store.close()
