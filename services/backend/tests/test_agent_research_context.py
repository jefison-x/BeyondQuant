"""Original task discovery must not fall back to a workspace's latest task."""
import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchStore
from tests.test_agent_run_lifecycle import apply
from tests.test_domain_call_evidence import observed, pytestmark


def context(headers):
    return {key.removeprefix("x-byq-").replace("-", "_"): value for key, value in headers.items()}


def task(research, headers, key, *, objective="中证500合成干扰任务"):
    ctx = context(headers)
    return research.create_task({"owner_principal": ctx["owner_principal"], "title": key,
        "objective": objective, "trace_id": ctx["trace_id"], "idempotency_key": key}, trusted_context=ctx)


def test_original_task_is_discoverable_after_failure_without_foreign_or_unbound_fallback(observed):
    agents, evidence, scope, headers = observed
    research, catalog = ResearchStore(), ConversationCatalogStore()
    other_headers = {**headers, "x-byq-session-id": "session-decoy", "x-byq-trace-id": "trace-decoy",
                     "x-byq-actor-principal": "byq-product-agent-session-decoy"}
    try:
        catalog.create("alice", "session-decoy", "trace-decoy")
        decoy = task(research, other_headers, "newer-other-conversation")
        unbound = research.create_task({"owner_principal": "alice", "title": "legacy unbound",
            "objective": "Do not guess a conversation", "trace_id": "legacy", "idempotency_key": "legacy"})
        apply(agents, headers, evidence["root_run_id"], outcome="failed", sequence=5)
        response = TestClient(main.app).get("/v1/agent/research-context", headers={
            **headers, "x-byq-dsh-run-id": "generation-followup"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["schema_version"] == "research-task-context.v1"
        assert body["status"] == "available" and body["has_more"] is False
        assert [item["task_id"] for item in body["tasks"]] == [evidence["task_id"]]
        assert body["tasks"][0]["status"] == "planned"
        assert decoy["task_id"] not in json.dumps(body) and unbound["task_id"] not in json.dumps(body)
        assert not any(key in json.dumps(body) for key in (
            "idempotency_key", "request_hash", "registration_fingerprint", "root_run_id", "continuation_permission"))
        assert agents._fetch_one("SELECT status FROM agent_runtime_turns")["status"] == "failed"
        assert research.get_task(evidence["task_id"])["status"] == "planned"
    finally:
        research.close()
        catalog.close()


@pytest.mark.parametrize("changed", [
    {"x-byq-session-id": "foreign-session"},
    {"x-byq-trace-id": "foreign-trace"},
    {"x-byq-actor-principal": "alice"},
])
def test_context_requires_exact_original_product_binding(observed, changed):
    headers = observed[3]
    response = TestClient(main.app).get("/v1/agent/research-context", headers={**headers, **changed})
    assert response.status_code == 404


def test_context_cannot_accept_a_model_selected_scope(observed):
    response = TestClient(main.app).get("/v1/agent/research-context?owner=bob", headers=observed[3])
    assert response.status_code == 422


def test_context_rejects_foreign_owner_and_workspace(observed):
    from tests.workspace_helpers import trusted_agent_context

    bob = trusted_agent_context("bob")
    client = TestClient(main.app)
    for changed in ({"x-byq-owner-principal": "bob", "x-byq-workspace-id": bob["x-byq-workspace-id"]},
                    {"x-byq-workspace-id": bob["x-byq-workspace-id"]}):
        response = client.get("/v1/agent/research-context", headers={**observed[3], **changed})
        assert response.status_code in (401, 403, 404)
        assert observed[1]["task_id"] not in response.text


def test_archived_conversation_cannot_supply_recovery_candidates(observed):
    catalog = ConversationCatalogStore()
    try:
        catalog.update("alice", observed[2]["conversation_id"], {"status": "archived"})
        response = TestClient(main.app).get("/v1/agent/research-context", headers=observed[3])
        assert response.status_code == 404
    finally:
        catalog.close()


def test_context_projects_persisted_checkpoint_without_linked_payloads(observed):
    research = ResearchStore()
    try:
        progress = {"schema_version": "research-progress.v1", "stage": "research",
                    "next_action": "review_report", "blocked_reason": None,
                    "linked_objects": [], "completion_evidence": []}
        research.transition("research_task", observed[1]["task_id"], "running", "context-checkpoint", progress=progress)
        research.close()
        response = TestClient(main.app).get("/v1/agent/research-context", headers=observed[3])
        assert response.status_code == 200, response.text
        summary = response.json()["tasks"][0]
        assert summary["status"] == "running" and summary["version"] == 2
        assert summary["stage"] == "research" and summary["next_action"] == "review_report"
        assert summary["blocked_reason"] is None
        assert "linked_objects" not in summary and "completion_evidence" not in summary
    finally:
        research.close()


def test_context_bounds_candidates_and_marks_truncated_objectives(observed):
    research = ResearchStore()
    try:
        for number in range(20):
            task(research, observed[3], f"candidate-{number}", objective="研究" * 400)
        response = TestClient(main.app).get("/v1/agent/research-context", headers=observed[3])
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["has_more"] is True and len(body["tasks"]) == 20
        assert "selected_task_id" not in body
        summaries = [item for item in body["tasks"] if item["task_id"] != observed[1]["task_id"]]
        assert all(len(item["objective_excerpt"]) == 400 and item["objective_truncated"] for item in summaries)
    finally:
        research.close()


def test_context_rejects_disabled_owner_and_reports_no_bound_tasks_honestly(observed):
    from app.user_auth import UserAuthStore

    catalog = ConversationCatalogStore()
    try:
        catalog.create("alice", "session-empty", "trace-empty")
        empty_headers = {**observed[3], "x-byq-session-id": "session-empty", "x-byq-trace-id": "trace-empty",
                         "x-byq-actor-principal": "byq-product-agent-session-empty"}
        response = TestClient(main.app).get("/v1/agent/research-context", headers=empty_headers)
        assert response.status_code == 200, response.text
        assert response.json() == {"schema_version": "research-task-context.v1", "status": "none_bound", "tasks": [], "has_more": False}
        users = UserAuthStore()
        try:
            user = users._fetch_one("SELECT user_id FROM users WHERE username='alice'")
            users.disable_user(user["user_id"], actor_role="admin")
        finally:
            users.close()
        assert TestClient(main.app).get("/v1/agent/research-context", headers=observed[3]).status_code == 401
    finally:
        catalog.close()
