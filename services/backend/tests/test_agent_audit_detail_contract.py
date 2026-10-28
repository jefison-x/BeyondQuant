from __future__ import annotations

from contextlib import nullcontext

import pytest

from app import agent_research
from app.agent_research import AgentResearchStore, MAX_DETAIL_BYTES, _audit_detail_object, _json_object


def _fake_audit_store(monkeypatch: pytest.MonkeyPatch):
    store = AgentResearchStore.__new__(AgentResearchStore)
    run = {
        "run_id": "agent_run_" + "a" * 32,
        "owner_principal": "audit-owner",
        "actor_principal": "audit-agent",
        "status": "active",
        "authority_status": "active",
    }
    connection = object()
    statements: list[tuple[object, str, dict[str, object]]] = []
    monkeypatch.setattr(store, "_fetch_one", lambda _sql, _params=None: dict(run))
    monkeypatch.setattr(store, "_transaction", lambda: nullcontext(connection))
    monkeypatch.setattr(
        agent_research,
        "execute",
        lambda conn, sql, params: statements.append((conn, sql, params)),
    )
    return store, statements, run


@pytest.mark.parametrize(
    ("action", "resource_type", "resource_id", "detail"),
    [
        (
            "byq_research_get",
            "research_task",
            "task_" + "b" * 32,
            {
                "approval_level": "AUTO",
                "authorization_decision": "allowed",
                "handoff_reason": "read projection",
                "handoff_state": "conversation_active",
                "progress": None,
                "status": "planned",
                "version": 1,
            },
        ),
        (
            "byq_backtest_task_get",
            "backtest_task",
            "backtesttask_" + "c" * 32,
            {
                "approval_level": "AUTO",
                "authorization_decision": "allowed",
                "backtest_executed": False,
                "backtest_job_id": None,
                "blockers": [],
                "market_readiness_state": "ready",
                "next_action": "execute",
                "phase": "ready_to_execute",
                "result_artifact_id": None,
                "signal_attempts": 1,
                "signal_producer_job_id": "signaljob_" + "b" * 32,
                "signal_snapshot_artifact_id": "artifact_" + "d" * 32,
                "signal_status": "completed",
            },
        ),
    ],
)
def test_record_audit_accepts_native_authorization_decision_payloads(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    resource_type: str,
    resource_id: str,
    detail: dict[str, object],
) -> None:
    store, statements, run = _fake_audit_store(monkeypatch)

    audit = store.record_audit(
        {
            "run_id": run["run_id"],
            "action": action,
            "outcome": "success",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "detail": detail,
        },
        trusted_owner="audit-owner",
        trusted_actor="audit-agent",
    )

    assert len(statements) == 1
    _connection, sql, params = statements[0]
    assert "INSERT INTO agent_audit" in sql
    assert params["detail_json"] == detail
    assert audit["detail"] == detail


@pytest.mark.parametrize("decision", ["allowed", "denied", "approval_required"])
def test_audit_detail_accepts_only_the_closed_authorization_decision_enum(decision: str) -> None:
    detail = {"authorization_decision": decision, "status": "observed"}

    value, encoded = _audit_detail_object(detail)

    assert value is detail
    assert '"authorization_decision":"' + decision + '"' in encoded


@pytest.mark.parametrize(
    "detail",
    [
        {"Authorization_Decision": "allowed"},
        {"authorizationDecision": "allowed"},
        {"nested": {"authorization_decision": "allowed"}},
        {"nested": [{"api-key": "synthetic"}]},
        {"authorization": "synthetic"},
    ],
)
def test_audit_detail_rejects_credential_key_lookalikes_and_nested_credentials(
    detail: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="credential"):
        _audit_detail_object(detail)


@pytest.mark.parametrize(
    "detail",
    [
        {"authorization_decision": "allowed", "api-key": "synthetic"},
        {"authorization_decision": "allowed", "nested": {"api_key": "synthetic"}},
    ],
)
def test_record_audit_rejects_secret_siblings_even_with_allowed_decision(
    monkeypatch: pytest.MonkeyPatch,
    detail: dict[str, object],
) -> None:
    store, statements, run = _fake_audit_store(monkeypatch)

    with pytest.raises(ValueError, match="credential"):
        store.record_audit(
            {
                "run_id": run["run_id"],
                "action": "byq_research_get",
                "outcome": "success",
                "resource_type": "research_task",
                "resource_id": "task_" + "b" * 32,
                "detail": detail,
            },
            trusted_owner="audit-owner",
            trusted_actor="audit-agent",
        )

    assert statements == []


@pytest.mark.parametrize(
    "detail",
    [
        {"authorization_decision": "policy_denied"},
        {"authorization_decision": True},
        {
            "authorization_decision": "allowed",
            "text": "é" * (MAX_DETAIL_BYTES // 2 + 32),
        },
    ],
)
def test_audit_detail_rejects_unknown_values_wrong_types_and_oversized_utf8(
    detail: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _audit_detail_object(detail)


@pytest.mark.parametrize(
    "detail",
    [
        {"authorization_decision": "allowed", "not_json": object()},
        {"authorization_decision": "allowed", "not_finite": float("nan")},
    ],
)
def test_audit_detail_reuses_json_and_nonfinite_value_rejection(
    detail: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="JSON-serializable"):
        _audit_detail_object(detail)


def test_generic_json_object_does_not_allow_audit_decision_key() -> None:
    with pytest.raises(ValueError, match="credential"):
        _json_object({"authorization_decision": "allowed"}, field="generic")


def test_record_audit_keeps_reserved_acp_control_rejection_before_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, statements, run = _fake_audit_store(monkeypatch)

    with pytest.raises(ValueError, match="reserved ACP control"):
        store.record_audit(
            {
                "run_id": run["run_id"],
                "action": "byq_agent_audit",
                "outcome": "success",
                "detail": {
                    "authorization_decision": "allowed",
                    "acp_control": {"mcp_request_id": "f" * 32},
                },
            },
            trusted_owner="audit-owner",
            trusted_actor="audit-agent",
        )

    assert statements == []
