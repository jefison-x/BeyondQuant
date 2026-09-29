"""Focused Phase 12 approval-policy and cancellation boundary tests."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agent_research import AgentResearchStore, ROLE_CATALOG
from packages.contracts.approval_policy import approval_level_for_tool
from tests.workspace_helpers import trusted_agent_context


def test_policy_is_closed_over_current_agent_tools_and_preserves_stronger_gates() -> None:
    known_tools = frozenset(tool for role in ROLE_CATALOG for tool in role.allowed_tools)
    levels = {tool: approval_level_for_tool(tool, known_tools=known_tools) for tool in known_tools}

    assert set(levels.values()) == {"AUTO", "DECISION", "ACTION"}
    assert {
        tool for tool, level in levels.items() if level == "ACTION"
    } == {
        "byq_backtest_task_cancel",
        "byq_feedback_submit",
        "byq_ml_strategy_approve",
        "byq_ml_training_cancel",
        "byq_strategy_approve",
    }
    existing_approval_gates = {
        action for role in ROLE_CATALOG for action in role.approval_required_actions
    }
    assert {
        "byq_backtest_task_cancel",
        "byq_ml_training_cancel",
        "byq_backtest_task_create",
        "byq_backtest_task_execute",
        "byq_ml_training_create",
        "byq_ml_prediction_create",
    } <= existing_approval_gates
    # Compute remains AUTO by policy level; the existing contextual grant still
    # blocks it until its exact domain approval is present.
    assert levels["byq_backtest_task_create"] == "AUTO"
    assert levels["byq_backtest_task_execute"] == "AUTO"
    assert levels["byq_ml_training_create"] == "AUTO"
    assert levels["byq_ml_prediction_create"] == "AUTO"

    with pytest.raises(ValueError, match="unknown Agent tool"):
        approval_level_for_tool("byq_unregistered_tool", known_tools=known_tools)


def test_agent_domain_approval_also_binds_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    approval = {
        "status": "approved",
        "execution_outcome": "authorized",
        "action": "byq_backtest_task_cancel",
        "resource_type": "backtest_task",
        "resource_id": "backtesttask_" + "a" * 32,
        "actor_principal": "phase12-owner",
        "source_session_id": "phase12-session",
        "run_workspace": "workspace-source",
        "decision_by": "phase12-reviewer",
    }

    class FakeApprovalStore:
        def get_approval(self, approval_id: object, *, trusted_owner: str) -> dict[str, object]:
            assert approval_id == "agent_approval_" + "a" * 32
            assert trusted_owner == "phase12-owner"
            return approval

    monkeypatch.setattr(main, "agent_store", FakeApprovalStore())
    context = {
        "owner_principal": "phase12-owner",
        "actor_principal": "phase12-owner",
        "session_id": "phase12-session",
        "workspace_id": "workspace-other",
    }
    with pytest.raises(ValueError, match="exact domain action"):
        main._approved_agent_domain_request(
            "agent_approval_" + "a" * 32,
            expected_action="byq_backtest_task_cancel",
            expected_resource_type="backtest_task",
            expected_resource_id="backtesttask_" + "a" * 32,
            context=context,
        )


def _decided_approval(
    client: TestClient,
    *,
    headers: dict[str, str],
    run_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    decision: str,
    key: str,
) -> str:
    requested = client.post(
        "/v1/agents/approvals",
        headers=headers,
        json={
            "run_id": run_id,
            "action": action,
            "reason": "Phase 12 exact cancellation boundary",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "idempotency_key": key,
        },
    )
    assert requested.status_code == 201, requested.text
    approval_id = requested.json()["approval"]["approval_id"]
    reviewer_headers = {**headers, "x-byq-actor-principal": "phase12-independent-reviewer"}
    decided = client.post(
        f"/v1/agents/approvals/{approval_id}/decision",
        headers=reviewer_headers,
        json={"decision": decision, "rationale": "Phase 12 focused test"},
    )
    assert decided.status_code == 200, decided.text
    return approval_id


@pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set")
@pytest.mark.parametrize(
    ("kind", "role_id", "action", "resource_type", "resource_id", "other_resource_id"),
    [
        (
            "backtest",
            "quant_orchestrator",
            "byq_backtest_task_cancel",
            "backtest_task",
            "backtesttask_" + "a" * 32,
            "backtesttask_" + "b" * 32,
        ),
        (
            "training",
            "ml_researcher",
            "byq_ml_training_cancel",
            "training_run",
            "mlrun_" + "c" * 32,
            "mlrun_" + "d" * 32,
        ),
    ],
)
def test_agent_cancellation_requires_approved_exact_grant(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    role_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    other_resource_id: str,
) -> None:
    owner = f"phase12-cancel-{kind}"
    headers = trusted_agent_context(
        owner,
        trace_id=f"phase12-{kind}-trace",
        session_id=f"phase12-{kind}-session",
        dsh_run_id=f"phase12-{kind}-dsh",
    )
    store = AgentResearchStore()
    monkeypatch.setattr(main, "agent_store", store)
    client = TestClient(main.app)
    started = client.post(
        "/v1/agents/runs",
        headers=headers,
        json={"role_id": role_id, "idempotency_key": f"phase12-{kind}-run"},
    )
    assert started.status_code == 201, started.text
    run_id = started.json()["run"]["run_id"]

    authorization = client.post(
        "/v1/agents/authorize",
        headers=headers,
        json={
            "run_id": run_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
        },
    )
    assert authorization.status_code == 200, authorization.text
    assert authorization.json()["authorization"]["authorized"] is False
    assert authorization.json()["authorization"]["decision"] == "approval_required"
    assert authorization.json()["authorization"]["approval_level"] == "ACTION"

    compute_action = "byq_backtest_task_create" if kind == "backtest" else "byq_ml_training_create"
    compute_authorization = client.post(
        "/v1/agents/authorize",
        headers=headers,
        json={"run_id": run_id, "action": compute_action},
    )
    assert compute_authorization.status_code == 200, compute_authorization.text
    assert compute_authorization.json()["authorization"]["authorized"] is False
    assert compute_authorization.json()["authorization"]["decision"] == "approval_required"
    assert compute_authorization.json()["authorization"]["approval_level"] == "AUTO"

    approved_id = _decided_approval(
        client,
        headers=headers,
        run_id=run_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        decision="approved",
        key=f"phase12-{kind}-approved",
    )
    rejected_id = _decided_approval(
        client,
        headers=headers,
        run_id=run_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        decision="rejected",
        key=f"phase12-{kind}-rejected",
    )
    other_target_id = _decided_approval(
        client,
        headers=headers,
        run_id=run_id,
        action=action,
        resource_type=resource_type,
        resource_id=other_resource_id,
        decision="approved",
        key=f"phase12-{kind}-other-target",
    )

    cancel_calls: list[str] = []
    if kind == "backtest":
        from app.backtest_task import signal_job_id_from_task

        def fake_get(job_id: str, *, trusted_owner: str) -> dict[str, object]:
            return {"job_id": job_id, "owner_principal": trusted_owner}

        def fake_cancel(job_id: str, *, trusted_owner: str) -> dict[str, object]:
            cancel_calls.append(job_id)
            return {"job_id": job_id, "owner_principal": trusted_owner}

        monkeypatch.setattr(main.signal_job_store, "get", fake_get)
        monkeypatch.setattr(main.signal_job_store, "cancel", fake_cancel)
        monkeypatch.setattr(
            main,
            "_backtest_task_view",
            lambda _job, *, owner_principal: {"backtest_task_id": resource_id, "references": {}},
        )
        endpoint = f"/v1/research/backtest-tasks/{resource_id}/cancel"
    else:
        def fake_cancel(
            run_id: str, *, trusted_workspace: str, trusted_owner: str,
        ) -> dict[str, object]:
            cancel_calls.append(run_id)
            return {
                "training_run_id": run_id,
                "status": "cancelled",
                "owner_principal": trusted_owner,
                "workspace_id": trusted_workspace,
            }

        monkeypatch.setattr(main.ml_training_store, "cancel", fake_cancel)
        monkeypatch.setattr(main, "project_business_job", lambda *_args: {"status": "CANCELLED"})
        endpoint = f"/v1/research/ml/training-runs/{resource_id}/cancel"

    other_owner_headers = trusted_agent_context(f"{owner}-other")
    different_actor_headers = {**headers, "x-byq-actor-principal": f"{owner}-other-actor"}
    different_session_headers = {**headers, "x-byq-session-id": f"{owner}-other-session"}
    attempts = [
        (headers, {}, resource_id),
        (headers, {"agent_approval_id": "agent_approval_" + "f" * 32}, resource_id),
        (headers, {"agent_approval_id": rejected_id}, resource_id),
        (headers, {"agent_approval_id": other_target_id}, resource_id),
        (other_owner_headers, {"agent_approval_id": approved_id}, resource_id),
        (different_actor_headers, {"agent_approval_id": approved_id}, resource_id),
        (different_session_headers, {"agent_approval_id": approved_id}, resource_id),
        (headers, {"agent_approval_id": approved_id, "unexpected": True}, resource_id),
    ]
    for request_headers, payload, target_id in attempts:
        denied_endpoint = endpoint.replace(resource_id, target_id)
        response = client.post(denied_endpoint, headers=request_headers, json=payload)
        assert response.status_code in {403, 422}, response.text
        assert cancel_calls == []

    accepted = client.post(
        endpoint,
        headers=headers,
        json={"agent_approval_id": approved_id},
    )
    assert accepted.status_code == 200, accepted.text
    assert len(cancel_calls) == 1
    assert cancel_calls[0] == (
        signal_job_id_from_task(resource_id) if kind == "backtest" else resource_id
    )
    store.close()


@pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set")
def test_product_browser_cancel_uses_separate_owner_path_and_agent_context_cannot_spoof_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = "phase12-browser-cancel"
    browser_headers = trusted_agent_context(
        owner, session_id="durable-product-session", dsh_run_id="browser",
    )
    store = AgentResearchStore()
    monkeypatch.setattr(main, "agent_store", store)
    cancel_calls: list[str] = []

    def fake_cancel(
        run_id: str, *, trusted_workspace: str, trusted_owner: str,
    ) -> dict[str, object]:
        cancel_calls.append(run_id)
        return {
            "training_run_id": run_id,
            "status": "cancelled",
            "owner_principal": trusted_owner,
            "workspace_id": trusted_workspace,
        }

    monkeypatch.setattr(main.ml_training_store, "cancel", fake_cancel)
    monkeypatch.setattr(main, "project_business_job", lambda *_args: {"status": "CANCELLED"})
    client = TestClient(main.app)
    run_id = "mlrun_" + "e" * 32
    endpoint = f"/v1/research/ml/training-runs/{run_id}/cancel"

    browser_response = client.post(endpoint, headers=browser_headers)
    assert browser_response.status_code == 200, browser_response.text
    assert len(cancel_calls) == 1 and cancel_calls[0] == run_id

    agent_session = "phase12-agent-browser-spoof"
    agent_headers = trusted_agent_context(
        owner,
        actor=f"byq-product-agent-{agent_session}",
        session_id=agent_session,
        dsh_run_id="browser",
    )
    spoof_response = client.post(endpoint, headers=agent_headers)
    assert spoof_response.status_code in {401, 422}, spoof_response.text
    assert len(cancel_calls) == 1
    store.close()
