from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from app import main
from app.user_policy import UserPolicyStore


def test_user_policy_defaults_and_update(tmp_path) -> None:
    store = UserPolicyStore(tmp_path / "policy.sqlite3")
    defaults = store.get("alice")
    assert defaults["automation_enabled"] is False
    assert defaults["default_decision_mode"] == "manual"

    updated = store.update(
        "alice",
        {
            "automation_enabled": True,
            "paused": False,
            "default_decision_mode": "auto_approve",
            "max_auto_executions_per_hour": 50,
            "max_auto_failures_per_hour": 5,
        },
    )
    assert updated["automation_enabled"] is True
    assert updated["default_decision_mode"] == "auto_approve"
    assert updated["max_auto_executions_per_hour"] == 50

    with pytest.raises(ValueError):
        store.update("alice", {"default_decision_mode": "invalid"})
    store.close()


def test_user_policy_endpoints_are_owner_scoped(monkeypatch, tmp_path) -> None:
    store = UserPolicyStore(tmp_path / "policy.sqlite3")
    monkeypatch.setattr(main, "user_policy_store", store)
    client = TestClient(main.app)
    headers = {
        "x-byq-owner-principal": "product-user",
        "x-byq-actor-principal": "product-user",
        "x-byq-trace-id": "byq-trace-policy-api",
        "x-byq-session-id": "byq-session-policy-api",
        "x-byq-dsh-run-id": "byq-run-policy-api",
    }
    response = client.get("/v1/users/agent-policy", headers=headers)
    assert response.status_code == 200
    assert response.json()["policy"]["owner_principal"] == "product-user"

    updated = client.put(
        "/v1/users/agent-policy",
        headers=headers,
        json={"automation_enabled": True, "default_decision_mode": "auto_deny"},
    )
    assert updated.status_code == 200
    assert updated.json()["policy"]["automation_enabled"] is True
    store.close()
