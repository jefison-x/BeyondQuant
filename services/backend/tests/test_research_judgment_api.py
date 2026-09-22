"""ADR-0085 P3 internal research-judgment invocation (isolated PostgreSQL).

The only concrete internal invocation path is the trusted runtime-adapter
consumer: admit a bounded call, submit the CLOSED model result, and let the
named seam commit the proposal and record the authoritative progress receipt.
The agent-facing surface stays read-only; there is no generic write route.
"""

import os

import pytest

from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchStore
from packages.contracts.research_execution_plan import plan_at_stage
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")


def _setup(owner: str = "judgment-api", session: str = "judgment-api-s", trace: str = "judgment-api-t"):
    headers = trusted_agent_context(owner, session_id=session, trace_id=trace)
    context = {key.removeprefix("x-byq-").replace("-", "_"): value for key, value in headers.items()}
    catalog = ConversationCatalogStore()
    catalog.create(owner, session, trace)
    catalog.close()
    store = ResearchStore()
    task = store.create_task(
        {"owner_principal": owner, "title": "Judgment API", "objective": "No execution",
         "trace_id": trace, "idempotency_key": f"{owner}-task"},
        trusted_context=context)
    return store, task["task_id"], context


def _seed_plan(store, task, stage, *, iteration=1, references=None):
    row = store._fetch_one("SELECT * FROM research_tasks WHERE task_id = :task", {"task": task})
    plan = plan_at_stage(
        task_id=task, owner_principal=row["owner_principal"], workspace_id=row["workspace_id"],
        conversation_id=row["conversation_id"], task_version=row["version"], stage=stage,
        idempotency_key="seed-plan", iteration=iteration, references=references)
    store._execute("""INSERT INTO research_execution_plans
        (task_id, owner_principal, workspace_id, conversation_id, plan_version, task_version,
         stage, iteration, status, next_action, plan, idempotency_key, request_hash,
         legacy_reason, created_at, updated_at)
        VALUES (:task, :owner, :workspace, :conversation, :plan_version, :task_version, :stage,
                :iteration, :status, :next_action, :plan, :idempotency_key, 'seed', NULL, now(), now())""",
        {"task": task, "owner": row["owner_principal"], "workspace": row["workspace_id"],
         "conversation": row["conversation_id"], "plan_version": plan["plan_version"],
         "task_version": plan["task_version"], "stage": plan["stage"],
         "iteration": plan["iteration"], "status": plan["status"],
         "next_action": plan["next_action"], "plan": plan,
         "idempotency_key": plan["idempotency_key"]})
    return plan


def _client(monkeypatch, store):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main, "research_store", store)
    return TestClient(main.app)


def _headers(context):
    return {"x-byq-" + key.replace("_", "-"): value for key, value in context.items()}


def test_internal_admit_then_result_commits_through_the_named_seam(monkeypatch):
    store, task, context = _setup()
    client = _client(monkeypatch, store)
    headers = _headers(context)
    try:
        _seed_plan(store, task, "backtest_analysis")
        admitted = client.post(f"/internal/research-judgment/{task}/admit",
                               headers=headers, json={"call_identity": "turn-a"})
        assert admitted.status_code == 200, admitted.text
        admission = admitted.json()
        assert admission["call_index"] == 1 and admission["model_call_limit"] == 2
        stage_input = admission["stage_input"]

        result = client.post(f"/internal/research-judgment/{task}/result", headers=headers, json={
            "call_identity": "turn-a",
            "durable_evidence": {"kind": "none"},
            "proposal": {
                "schema_version": "research-proposal.v1", "task_id": task,
                "plan_version": stage_input["plan_version"], "task_version": stage_input["task_version"],
                "stage": stage_input["stage"], "iteration": stage_input["iteration"],
                "proposal_kind": "backtest_analysis", "evidence_sufficient": True,
                "escalate": False, "summary": "bounded judgment"}})
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["schema_version"] == "research-judgment-result-receipt.v1"
        assert body["proposal"]["stage"] == "iteration_comparison"
        assert body["progress"]["progress_identity"].startswith("sha256:")
        plan = store._fetch_one("SELECT stage FROM research_execution_plans WHERE task_id = :task",
                                {"task": task})
        assert plan["stage"] == "iteration_comparison"

        # The committed plan is a new revision: it has its own two-call bound.
        assert client.post(f"/internal/research-judgment/{task}/admit", headers=headers,
                           json={"call_identity": "turn-b"}).json()["call_index"] == 1
        assert client.post(f"/internal/research-judgment/{task}/admit", headers=headers,
                           json={"call_identity": "turn-c"}).json()["call_index"] == 2
        blocked = client.post(f"/internal/research-judgment/{task}/admit", headers=headers,
                              json={"call_identity": "turn-d"})
        assert blocked.status_code == 409
    finally:
        store.close()


def test_internal_result_without_progress_fences_plan_and_task(monkeypatch):
    store, task, context = _setup("judgment-api-fence", "judgment-api-f", "judgment-api-ft")
    client = _client(monkeypatch, store)
    headers = _headers(context)
    try:
        _seed_plan(store, task, "backtest_analysis")
        client.post(f"/internal/research-judgment/{task}/admit", headers=headers,
                    json={"call_identity": "turn-a"})
        result = client.post(f"/internal/research-judgment/{task}/result", headers=headers,
                             json={"call_identity": "turn-a", "durable_evidence": {"kind": "none"}})
        assert result.status_code == 200, result.text
        assert result.json()["progress"]["plan_moved_to_needs_attention"] is True
        plan = store._fetch_one("SELECT stage, status FROM research_execution_plans WHERE task_id = :task",
                                {"task": task})
        assert plan["stage"] == "needs_attention" and plan["status"] == "blocked"
        row = store._fetch_one("SELECT progress FROM research_tasks WHERE task_id = :task", {"task": task})
        assert row["progress"]["blocked_reason"] == "no_durable_progress"
    finally:
        store.close()


def test_internal_judgment_requires_the_trusted_consumer(monkeypatch):
    store, task, context = _setup("judgment-api-auth", "judgment-api-a", "judgment-api-at")
    client = _client(monkeypatch, store)
    try:
        _seed_plan(store, task, "backtest_analysis")
        assert client.post(f"/internal/research-judgment/{task}/admit",
                           json={"call_identity": "turn-a"}).status_code == 401
        # An actor that is not the owner is rejected.
        headers = _headers(context)
        headers["x-byq-actor-principal"] = "someone-else"
        assert client.post(f"/internal/research-judgment/{task}/admit",
                           headers=headers, json={"call_identity": "turn-a"}).status_code == 403
    finally:
        store.close()
