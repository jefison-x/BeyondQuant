from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import main
from app.operations import OperationsConflict, OperationsForbidden, OperationsStore


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


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
    serialized = str(projection).lower()
    assert "ciphertext" not in serialized
    assert "api_key" not in serialized
    store.close()


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

    invalid = client.put(
        "/v1/operations/budget",
        headers={"x-byq-actor-role": "admin", "x-byq-actor-principal": "admin-user"},
        json={"enabled": True, "alert_total_tokens": 1},
    )
    assert invalid.status_code == 422
    store.close()
