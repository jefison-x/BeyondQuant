import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.conversation_catalog import ConversationCatalogStore
from app.research import IdempotencyConflict, ResearchStore
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")


def setup_permission():
    headers = trusted_agent_context("budget-user", session_id="budget-session", trace_id="budget-trace")
    context = {key.removeprefix("x-byq-").replace("-", "_"): value for key, value in headers.items()}
    catalog = ConversationCatalogStore()
    catalog.create("budget-user", "budget-session", "budget-trace")
    catalog.close()
    store = ResearchStore()
    task = store.create_task({"owner_principal": "budget-user", "title": "Synthetic permission",
        "objective": "No execution", "trace_id": "budget-trace", "idempotency_key": "budget-task"},
        trusted_context=context)
    artifact = store.create_artifact({"task_id": task["task_id"], "kind": "research_note", "content": {"synthetic": True},
        "lineage": [], "trace_id": "budget-trace", "idempotency_key": "budget-artifact"})
    store.transition("artifact", artifact["artifact_id"], "validated", "budget-validate")
    return store, task["task_id"], context, {"idempotency_key": "budget-confirm",
        "token_limit": 1000, "confirmed_artifact_ids": [artifact["artifact_id"]]}


def test_permission_persists_without_enabling_execution_or_refreshing_expiry():
    store, task, context, payload = setup_permission()
    result = store.create_continuation_permission(task, payload, trusted_context=context)
    assert result["can_start"] is False
    assert result["blocked_reason"] == "budget_enforcement_unqualified"
    assert result["permission"]["max_turns"] == 8
    assert result["permission"]["valid_seconds"] == 86400
    assert result["permission"]["turn_timeout_seconds"] == 900
    assert "idempotency_key" not in result["permission"]
    assert "continuation_permission" not in store.get_task(task)
    store.close()
    reopened = ResearchStore()
    try:
        assert reopened.get_continuation_permission(task, trusted_context=context) == result
        assert reopened.create_continuation_permission(task, payload, trusted_context=context) == result
        revoked = reopened.revoke_continuation_permission(task, grant_version=1, trusted_context=context)
        assert revoked["blocked_reason"] == "permission_revoked"
        assert reopened.revoke_continuation_permission(task, grant_version=1, trusted_context=context) == revoked
        assert reopened.create_continuation_permission(task, payload, trusted_context=context) == revoked
        with pytest.raises(IdempotencyConflict):
            reopened.create_continuation_permission(task, {**payload, "idempotency_key": "new-key"}, trusted_context=context)
    finally:
        reopened.close()


@pytest.mark.parametrize("change", [{"token_limit": True}, {"token_limit": 0}, {"token_limit": 1.5},
    {"max_turns": 9}, {"valid_seconds": 86401}, {"turn_timeout_seconds": 901},
    {"confirmed_artifact_ids": []}, {"qualified": True}, {"cost_limit": 1},
    {"confirmed_artifact_ids": ["artifact_" + "0" * 32]}])
def test_permission_rejects_invalid_or_unverified_budget_without_writing(change):
    store, task, context, payload = setup_permission()
    try:
        with pytest.raises(ValueError):
            store.create_continuation_permission(task, {**payload, **change}, trusted_context=context)
        assert store.get_continuation_permission(task, trusted_context=context)["permission"] is None
    finally:
        store.close()


def test_permission_rejects_agent_actor_foreign_owner_and_disabled_identity():
    store, task, context, payload = setup_permission()
    try:
        for change in ({"actor_principal": "byq-product-agent-budget-session"}, {"owner_principal": "foreign"},
                       {"workspace_id": "workspace-foreign"}):
            with pytest.raises(ValueError):
                store.create_continuation_permission(task, payload, trusted_context={**context, **change})
        store._execute("UPDATE users SET status = 'disabled' WHERE username = 'budget-user'")
        with pytest.raises(ValueError):
            store.create_continuation_permission(task, payload, trusted_context=context)
    finally:
        store.close()


def test_competing_connections_create_one_immutable_permission():
    store, task, context, payload = setup_permission()
    other = ResearchStore()
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(instance.create_continuation_permission, task, payload, trusted_context=context)
                       for instance in (store, other)]
            assert futures[0].result() == futures[1].result()
        with pytest.raises(IdempotencyConflict):
            store.create_continuation_permission(task, {**payload, "token_limit": 1001}, trusted_context=context)
        store.transition("research_task", task, "cancelled", "budget-cancel")
        assert store.get_continuation_permission(task, trusted_context=context)["blocked_reason"] == "task_terminal"
    finally:
        store.close()
        other.close()


def test_expired_permission_cannot_be_refreshed_and_wrong_revoke_version_is_rejected():
    store, task, context, payload = setup_permission()
    try:
        store.create_continuation_permission(task, payload, trusted_context=context)
        store._execute("""UPDATE research_tasks SET continuation_permission =
            jsonb_set(continuation_permission, '{expires_at}', '"2000-01-01T00:00:00+00:00"'::jsonb)
            WHERE task_id = :task""", {"task": task})
        expired = store.create_continuation_permission(task, payload, trusted_context=context)
        assert expired["blocked_reason"] == "permission_expired"
        with pytest.raises(ValueError):
            store.revoke_continuation_permission(task, grant_version=True, trusted_context=context)
        with pytest.raises(ValueError):
            store.revoke_continuation_permission(task, grant_version=2, trusted_context=context)
    finally:
        store.close()


def test_permission_backend_api_exact_identity_and_closed_fields(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    store, task, context, payload = setup_permission()
    monkeypatch.setattr(main, "research_store", store)
    headers = {"x-byq-" + key.replace("_", "-"): value for key, value in context.items()}
    client = TestClient(main.app)
    path = f"/v1/research/tasks/{task}/continuation-permission"
    try:
        assert client.post(path, json=payload).status_code == 401
        assert client.post(path, headers={**headers, "x-byq-actor-principal": "byq-product-agent-budget-session"},
                           json=payload).status_code == 422
        response = client.post(path, headers=headers, json=payload)
        assert response.status_code == 201
        assert response.json()["can_start"] is False
        assert client.get(path, headers=headers).json() == response.json()
        assert client.post(path + "/revoke", headers=headers, json={"grant_version": 1, "qualified": True}).status_code == 422
        assert client.post(path + "/revoke", headers=headers, json={"grant_version": 1}).json()["blocked_reason"] == "permission_revoked"
    finally:
        store.close()
