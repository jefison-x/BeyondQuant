from __future__ import annotations

import os

import pytest

from fastapi.testclient import TestClient

from app import main
from app.user_policy import UserPolicyConflict, UserPolicyNotFound, UserPolicyStore
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


def test_user_policy_defaults_and_update() -> None:
    store = UserPolicyStore()
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


def test_user_policy_endpoints_are_owner_scoped(monkeypatch) -> None:
    headers = trusted_agent_context(
        "product-user", trace_id="byq-trace-policy-api", session_id="byq-session-policy-api",
        dsh_run_id="byq-run-policy-api",
    )
    store = UserPolicyStore()
    monkeypatch.setattr(main, "user_policy_store", store)
    client = TestClient(main.app)
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


def test_policy_rule_crud_is_owner_scoped_and_changes_authorization() -> None:
    store = UserPolicyStore()
    store.update(
        "alice",
        {
            "automation_enabled": True,
            "paused": False,
            "default_decision_mode": "manual",
            "max_auto_executions_per_hour": 20,
            "max_auto_failures_per_hour": 3,
        },
    )
    rule = store.create_rule(
        "alice",
        {
            "name": "拒绝回测",
            "description": "人工设置",
            "action": "byq_backtest_run",
            "agent_id": "*",
            "decision_mode": "auto_deny",
            "risk_level": "high",
            "priority": 10,
            "enabled": True,
        },
        actor="alice",
    )
    effective = store.evaluate_authorization(
        "alice",
        {
            "authorized": False,
            "decision": "approval_required",
            "run_id": "agent_run_test",
            "role_id": "chief_quant_researcher",
            "action": "byq_backtest_run",
        },
    )
    assert effective["decision"] == "policy_denied"
    assert effective["policy_rule_id"] == rule["rule_id"]
    facade_effective = store.evaluate_authorization(
        "alice",
        {
            "authorized": False,
            "decision": "approval_required",
            "run_id": "agent_run_test",
            "role_id": "chief_quant_researcher",
            "action": "byq_backtest_task_execute",
        },
    )
    assert facade_effective["decision"] == "policy_denied"
    assert facade_effective["policy_rule_id"] == rule["rule_id"]

    with pytest.raises(UserPolicyNotFound):
        store.get_rule(rule["rule_id"], owner="bob")
    with pytest.raises(UserPolicyConflict):
        store.update_rule(
            rule["rule_id"],
            "alice",
            {**{key: value for key, value in rule.items() if key in {
                "name", "description", "action", "agent_id", "decision_mode",
                "risk_level", "priority", "enabled",
            }}, "expected_version": 99},
            actor="alice",
        )
    deleted = store.delete_rule(
        rule["rule_id"],
        "alice",
        actor="alice",
        expected_version=1,
    )
    assert deleted["deleted"] is True
    assert [event["action"] for event in store.list_audit("alice")] == [
        "rule.deleted", "rule.created",
    ]
    store.close()


def test_policy_preset_replaces_rules_and_rejects_vectorbt_semantics() -> None:
    store = UserPolicyStore()
    applied = store.apply_preset("alice", "deny_backtests", actor="alice")
    assert applied["policy"]["automation_enabled"] is True
    assert len(applied["rules"]) == 2
    assert {item["decision_mode"] for item in applied["rules"]} == {"auto_deny"}
    with pytest.raises(ValueError, match="action"):
        store.create_rule(
            "alice",
            {
                "name": "旧引擎",
                "action": "vectorbt_run",
                "agent_id": "*",
                "decision_mode": "auto_approve",
                "risk_level": "low",
            },
            actor="alice",
        )
    store.close()


def test_policy_rule_product_endpoints(monkeypatch) -> None:
    headers = trusted_agent_context(
        "alice", trace_id="trace-policy-rules", session_id="session-policy-rules",
        dsh_run_id="run-policy-rules",
    )
    store = UserPolicyStore()
    monkeypatch.setattr(main, "user_policy_store", store)
    client = TestClient(main.app)
    created = client.post(
        "/v1/users/agent-policy/rules",
        headers=headers,
        json={
            "name": "拒绝执行",
            "description": "",
            "action": "byq_backtest_run",
            "agent_id": "*",
            "decision_mode": "auto_deny",
            "risk_level": "high",
            "priority": 10,
            "enabled": True,
        },
    )
    assert created.status_code == 201
    rule = created.json()["rule"]
    bundle = client.get("/v1/users/agent-policy", headers=headers)
    assert bundle.json()["rules"][0]["rule_id"] == rule["rule_id"]
    deleted = client.post(
        f"/v1/users/agent-policy/rules/{rule['rule_id']}/delete",
        headers=headers,
        json={"expected_version": rule["version"]},
    )
    assert deleted.status_code == 200
    store.close()
