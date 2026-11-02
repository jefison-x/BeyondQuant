from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import main
from app.operations import OperationsConflict, OperationsForbidden, OperationsStore
from app.workspace_tenancy import WorkspaceTenancyStore
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


@pytest.fixture(autouse=True)
def _bootstrap_workspace_columns_after_test_schema_reset(_byq_reset_schema):
    tenancy = WorkspaceTenancyStore()
    try:
        yield
    finally:
        tenancy.close()


def test_operations_projection_is_admin_only_bounded_and_postgresql_native() -> None:
    store = OperationsStore()
    with pytest.raises(OperationsForbidden):
        store.overview(actor_role="user")

    projection = store.overview(actor_role="admin")
    assert projection["schema_version"] == "operations.v1"
    assert projection["database"]["engine"] == "postgresql"
    assert projection["database"]["migration"]["legacy_sqlite_runtime"] is False
    assert projection["cache"]["redis"] == "not_used"
    assert projection["graphs"]["raw_dsh_events"] is False
    assert projection["models"]["secrets_exposed"] is False
    usage = projection["usage"]
    assert usage["schema_version"] == "operations-usage.v1"
    assert usage["scope"] == "persisted_continuation_requests"
    assert usage["source"] == "backend_validated_request_receipts"
    assert usage["completeness"] == "partial"
    assert usage["uncovered_sources"] == ["ordinary_product_roots", "research_judgment"]
    assert usage["truncated"] is False
    assert usage["request_count"] == (
        usage["known_requests"] + usage["unknown_requests"] + usage["invalid_requests"]
    )
    serialized = str(projection).lower()
    assert "ciphertext" not in serialized
    assert "api_key" not in serialized
    store.close()


def test_operations_usage_overview_projects_a_persisted_known_receipt() -> None:
    from app.conversation_catalog import ConversationCatalogStore
    from app.research import ResearchStore
    from tests.test_operations_usage import _actual, _entry

    owner = "operations-usage-overview-owner"
    session_id = "operations-usage-overview-session"
    trace_id = "operations-usage-overview-trace"
    trusted_headers = trusted_agent_context(owner, session_id=session_id, trace_id=trace_id)
    catalog = ConversationCatalogStore()
    conversation = catalog.create(owner, session_id, trace_id)
    context = {
        key.removeprefix("x-byq-").replace("-", "_"): value
        for key, value in trusted_headers.items()
    }
    research = ResearchStore()
    task = research.create_task(
        {"owner_principal": owner, "title": "Operations usage fixture",
         "objective": "Persist one synthetic validated usage receipt",
         "trace_id": trace_id, "idempotency_key": "operations-usage-overview-task"},
        trusted_context=context,
    )
    entry = _entry(
        100, provider="deepseek-official",
        actual=_actual(input_tokens=47_589, cache_read_tokens=319_232,
                       output_tokens=1_539, provider_attempts=8),
        owner=owner, workspace=trusted_headers["x-byq-workspace-id"],
        task_id=task["task_id"], conversation_id=conversation["conversation_id"],
    )
    research._execute(
        "UPDATE research_tasks SET continuation_budget=:budget WHERE task_id=:task",
        {"budget": [entry], "task": task["task_id"]},
    )
    stored_before = research._fetch_one(
        "SELECT continuation_budget FROM research_tasks WHERE task_id=:task",
        {"task": task["task_id"]},
    )["continuation_budget"]

    operations = OperationsStore()
    usage = operations.overview(actor_role="admin")["usage"]

    assert usage["request_count"] == usage["known_requests"] == 1
    assert usage["unknown_requests"] == usage["invalid_requests"] == 0
    assert usage["known_totals"] == {
        "input_tokens": 47_589,
        "cache_read_tokens": 319_232,
        "output_tokens": 1_539,
        "provider_attempts": 8,
        "total_tokens": 368_360,
    }
    stored_after = research._fetch_one(
        "SELECT continuation_budget FROM research_tasks WHERE task_id=:task",
        {"task": task["task_id"]},
    )["continuation_budget"]
    assert stored_after == stored_before

    operations.close()
    research.close()
    catalog.close()


def test_operations_projection_treats_unprovisioned_market_cache_as_empty() -> None:
    store = OperationsStore()
    with store.engine.begin() as connection:
        connection.execute(text("DROP TABLE market_daily_bars"))

    projection = store.overview(actor_role="admin")

    assert projection["cache"]["status"] == "empty"
    assert projection["cache"]["groups"] == []
    assert {row["resource"]: row["count"] for row in projection["database"]["domain_counts"]}["market_bars"] == 0
    store.close()


def test_budget_threshold_write_is_versioned_idempotent_and_audited() -> None:
    store = OperationsStore()
    payload = {
        "enabled": True,
        "alert_total_tokens": 500000,
        "alert_requests": 60,
        "expected_version": 1,
        "idempotency_key": "phase38-budget-1",
    }
    updated = store.update_budget(
        payload,
        actor_principal="admin-user",
        actor_role="admin",
    )
    assert updated["budget"]["version"] == 2
    assert updated["budget"]["alert_total_tokens"] == 500000
    assert store.update_budget(
        payload,
        actor_principal="admin-user",
        actor_role="admin",
    ) == updated

    with pytest.raises(OperationsConflict):
        store.update_budget(
            {**payload, "alert_requests": 61},
            actor_principal="admin-user",
            actor_role="admin",
        )

    overview = store.overview(actor_role="admin")
    audit = overview["access"]["operations_audit"]
    assert len(audit) == 1
    assert audit[0]["action"] == "budget.threshold.updated"
    assert audit[0]["actor_principal"] == "admin-user"
    store.close()


def test_operations_api_rejects_non_admin_and_exposes_no_control_surface(monkeypatch) -> None:
    store = OperationsStore()
    monkeypatch.setattr(main, "operations_store", store)
    client = TestClient(main.app)

    denied = client.get("/v1/operations/overview", headers={"x-byq-actor-role": "user"})
    assert denied.status_code == 403

    allowed = client.get(
        "/v1/operations/overview",
        headers={"x-byq-actor-role": "admin", "x-byq-actor-principal": "admin-user"},
    )
    assert allowed.status_code == 200
    assert "connection_string" not in allowed.text.lower()
    assert "execute_sql" not in allowed.text.lower()
    assert allowed.json()["usage"]["schema_version"] == "operations-usage.v1"

    invalid = client.put(
        "/v1/operations/budget",
        headers={"x-byq-actor-role": "admin", "x-byq-actor-principal": "admin-user"},
        json={"enabled": True, "alert_total_tokens": 1},
    )
    assert invalid.status_code == 422
    store.close()
