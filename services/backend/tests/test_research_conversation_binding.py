import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchStore
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")


def test_product_task_binding_is_atomic_exact_and_restart_safe(monkeypatch):
    session, trace = "binding-session", "binding-trace"
    headers = trusted_agent_context("binding-user", actor=f"byq-product-agent-{session}", session_id=session, trace_id=trace)
    catalog = ConversationCatalogStore()
    conversation = catalog.create("binding-user", session, trace)
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)
    payload = {"owner_principal": "binding-user", "title": "Synthetic binding", "objective": "No execution",
               "trace_id": trace, "idempotency_key": "original-binding-key"}
    response = client.post("/v1/research/tasks", headers=headers, json=payload)
    assert response.status_code == 201
    task = response.json()
    assert task["conversation_id"] == conversation["conversation_id"]
    assert ResearchStore().get_task(task["task_id"])["conversation_id"] == conversation["conversation_id"]
    assert client.post("/v1/research/tasks", headers=headers, json=payload).json()["task_id"] == task["task_id"]
    other = catalog.create("binding-user", "other-session", "other-trace")
    foreign = {**headers, "x-byq-session-id": "other-session", "x-byq-trace-id": "other-trace",
               "x-byq-actor-principal": "byq-product-agent-other-session"}
    assert client.post("/v1/research/tasks", headers=foreign, json={**payload, "trace_id": "other-trace"}).status_code == 409
    assert store.get_task(task["task_id"])["conversation_id"] != other["conversation_id"]
    assert client.post("/v1/research/tasks", headers=headers,
                       json={**payload, "conversation_id": other["conversation_id"]}).status_code == 422


@pytest.mark.parametrize("case", ["missing", "foreign_owner", "wrong_trace", "archived", "payload_trace"])
def test_unproven_product_binding_creates_no_task(case):
    session, trace = "unproven-session", "unproven-trace"
    headers = trusted_agent_context("binding-user", actor=f"byq-product-agent-{session}", session_id=session, trace_id=trace)
    if case != "missing":
        owner = "other-user" if case == "foreign_owner" else "binding-user"
        trusted_agent_context(owner)
        catalog = ConversationCatalogStore()
        conversation = catalog.create(owner, session, "different-trace" if case == "wrong_trace" else trace)
        if case == "archived":
            catalog.update(owner, conversation["conversation_id"], {"status": "archived"})
    response = TestClient(main.app).post("/v1/research/tasks", headers=headers, json={
        "owner_principal": "binding-user", "title": "Synthetic", "objective": "No execution",
        "trace_id": "foreign-payload-trace" if case == "payload_trace" else trace, "idempotency_key": "unproven-binding-key"})
    assert response.status_code == 422
    assert ResearchStore().list_tasks(owner_principal="binding-user")["tasks"] == []


def test_old_unbound_task_is_not_retrospectively_assigned():
    session, trace = "old-session", "old-trace"
    headers = trusted_agent_context("binding-user", actor=f"byq-product-agent-{session}", session_id=session, trace_id=trace)
    payload = {"owner_principal": "binding-user", "title": "Old unbound", "objective": "No execution",
               "trace_id": trace, "idempotency_key": "old-binding-key"}
    store = ResearchStore()
    old = store.create_task(payload)
    ConversationCatalogStore().create("binding-user", session, trace)
    assert TestClient(main.app).post("/v1/research/tasks", headers=headers, json=payload).status_code == 409
    assert store.get_task(old["task_id"])["conversation_id"] is None


def test_ml_inbox_excludes_other_conversations_and_unbound_history():
    from app.ml_training import MLTrainingRunStore
    from tests.test_ml_training import feature_input

    store, runs = ResearchStore(), MLTrainingRunStore()
    strategy, universe, _ = feature_input()
    selected = None
    for label in ("current", "other", "legacy"):
        session, trace = f"session-{label}", f"trace-{label}"
        headers = trusted_agent_context("binding-user", actor=f"byq-product-agent-{session}", session_id=session, trace_id=trace)
        context = {key.removeprefix("x-byq-").replace("-", "_"): value for key, value in headers.items()}
        if label != "legacy":
            ConversationCatalogStore().create("binding-user", session, trace)
        task = store.create_task({"owner_principal": "binding-user", "title": label, "objective": "No execution",
            "trace_id": trace, "idempotency_key": f"task-{label}"}, trusted_context=context if label != "legacy" else None)
        artifact = store.create_artifact({"task_id": task["task_id"], "kind": "ml_strategy_version", "content": strategy,
            "lineage": [], "trace_id": trace, "idempotency_key": f"strategy-{label}"})
        store.transition("artifact", artifact["artifact_id"], "validated", f"validate-{label}")
        run = runs.create_waiting(workspace_id=headers["x-byq-workspace-id"], owner_principal="binding-user",
            task_id=task["task_id"], experiment_id=None, ml_strategy_artifact_id=artifact["artifact_id"],
            stock_pool_snapshot_id="snapshot_test", preparation={"strategy": strategy, "universe": universe},
            requirement={"requirement_sha256": "c" * 64}, readiness={"state": "missing"},
            trace_id=trace, idempotency_key=f"training-{label}")
        if label == "current":
            selected = run["training_run_id"]
    kwargs = {"trusted_workspace": headers["x-byq-workspace-id"], "trusted_owner": "binding-user",
              "trusted_session": "session-current", "trusted_trace": "trace-current", "limit": 1}
    assert [item["training_run_id"] for item in runs.list_agent_notifications(**kwargs)] == [selected]
    assert runs.list_agent_notifications(**{**kwargs, "trusted_trace": "trace-other"}) == []
    assert runs.list_agent_notifications(**{**kwargs, "trusted_owner": "other-user"}) == []
