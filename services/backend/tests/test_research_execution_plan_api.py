"""ADR-0085 P1 / ADR-0108 Backend execution-plan API tests.

The read surface is ``GET /v1/research/tasks/{task_id}/execution-plan``. ADR-0108
adds exactly one foreground write surface, ``POST /v1/research/tasks/{task_id}/
execution-plan``, which accepts only the trusted owner/workspace context plus the
closed create request; it is not an arbitrary plan/proposal write. These exercise
the real FastAPI app against isolated PostgreSQL.
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


STAGE_INPUT_FIELDS = {
    "schema_version", "task_id", "plan_version", "task_version", "stage", "iteration",
    "status", "objective", "stage_instruction", "proposal_kinds", "evidence",
    "allowed_tools", "model_call_limit", "escalation_allowed",
}


def test_get_stage_input_is_read_only_and_bounded(monkeypatch):
    store, task, context = _setup("stage-api-owner", "stage-api-s", "stage-api-t", with_plan=True)
    client = _client(monkeypatch, store)
    headers = {"x-byq-" + key.replace("_", "-"): value for key, value in context.items()}
    try:
        response = client.get(f"/v1/research/tasks/{task}/stage-input", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert set(body) == STAGE_INPUT_FIELDS
        assert body["stage"] == "strategy_draft" and body["model_call_limit"] == 2
        for internal in ("owner_principal", "workspace_id", "conversation_id",
                         "idempotency_key", "next_action", "references"):
            assert internal not in body
        for raw in ("bars_frame", "date_index", "signal_snapshot_rows", "raw_signal_snapshot"):
            assert raw not in response.text
        # No write route exists for a plan or a proposal.
        path = f"/v1/research/tasks/{task}/stage-input"
        assert client.post(path, headers=headers, json={}).status_code in {404, 405}
        assert client.put(path, headers=headers, json={}).status_code in {404, 405}
        assert client.delete(path, headers=headers).status_code in {404, 405}
    finally:
        store.close()


def test_get_stage_input_refuses_a_deterministic_stage(monkeypatch):
    store, task, context = _setup("stage-api-det", "stage-api-d-s", "stage-api-d-t", with_plan=True)
    client = _client(monkeypatch, store)
    headers = {"x-byq-" + key.replace("_", "-"): value for key, value in context.items()}
    try:
        # A first call without durable progress moves the plan to needs_attention
        # (a deterministic stage), which must refuse a model turn.
        store.admit_research_stage_call(task, {"call_identity": "det-fence"}, trusted_context=context)
        store.record_research_stage_progress(
            task, {"call_identity": "det-fence", "durable_evidence": {"kind": "none"}},
            trusted_context=context)
        assert client.get(f"/v1/research/tasks/{task}/stage-input",
                          headers=headers).status_code == 422
    finally:
        store.close()


def test_get_stage_input_requires_trusted_context(monkeypatch):
    store, task, context = _setup("stage-api-ctx", "stage-api-c-s", "stage-api-c-t", with_plan=True)
    client = _client(monkeypatch, store)
    try:
        assert client.get(f"/v1/research/tasks/{task}/stage-input").status_code == 401
    finally:
        store.close()


def test_execution_plan_create_is_foreground_only(monkeypatch):
    # ADR-0108 adds one foreground Product create route. It requires the trusted
    # context and the closed create request; it is not an arbitrary write, and
    # PUT/DELETE stay absent.
    store, task, context = _setup("plan-api-fg", "plan-api-fg-s", "plan-api-fg-t", with_plan=False)
    client = _client(monkeypatch, store)
    headers = {"x-byq-" + key.replace("_", "-"): value for key, value in context.items()}
    try:
        path = f"/v1/research/tasks/{task}/execution-plan"
        # Trusted context + closed create request -> exactly one plan.
        assert client.post(path, headers=headers, json={"idempotency_key": "fg-api-1"}).status_code == 201
        # An exact replay is idempotent.
        assert client.post(path, headers=headers, json={"idempotency_key": "fg-api-1"}).status_code == 201
        # A second, different key cannot add a second plan.
        assert client.post(path, headers=headers, json={"idempotency_key": "fg-api-2"}).status_code == 409
        # No trusted context -> 401.
        assert client.post(path, json={"idempotency_key": "fg-api-3"}).status_code == 401
        # The closed create request refuses an unknown field.
        assert client.post(path, headers=headers,
                           json={"idempotency_key": "fg-api-4", "owner_principal": "x"}).status_code == 422
        # No arbitrary update/delete route exists.
        assert client.put(path, headers=headers, json={}).status_code in {404, 405}
        assert client.delete(path, headers=headers).status_code in {404, 405}
    finally:
        store.close()


def test_execution_plan_create_rejects_a_continuation_consumer_identity(monkeypatch):
    # ADR-0108 foreground-only, proven at the HTTP entry: the create route
    # requires the FULL trusted agent context. A background continuation-consumer
    # identity (owner + actor + workspace only, no runtime session/trace) cannot
    # create a plan, so a continuation grant is never accepted as a foreground
    # creator even though the store seam itself defaults require_active_grant=False.
    store, task, context = _setup("plan-api-cont", "plan-api-cont-s", "plan-api-cont-t",
                                  with_plan=False)
    client = _client(monkeypatch, store)
    consumer_headers = {
        "x-byq-owner-principal": context["owner_principal"],
        "x-byq-actor-principal": context["owner_principal"],
        "x-byq-workspace-id": context["workspace_id"],
    }
    headers = {"x-byq-" + key.replace("_", "-"): value for key, value in context.items()}
    try:
        path = f"/v1/research/tasks/{task}/execution-plan"
        assert client.post(path, headers=consumer_headers,
                           json={"idempotency_key": "cont-1"}).status_code == 401
        # The refusal left no plan behind.
        assert client.get(path, headers=headers).status_code == 404
    finally:
        store.close()
