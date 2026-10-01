"""No-database checks for ADR-0090 Backend admission and public views."""

import pytest

from app.continuation_scope import _v2_tool_arguments_allowed
from app.research_continuation import (
    ResearchContinuationMixin,
    _request_v2,
)
from packages.contracts.continuation_request import (
    PERMISSION_SCHEMA_VERSION,
    RESERVATION_SCHEMA_VERSION,
    profile_binding,
    request_limits,
)


def test_v2_grant_payload_is_one_closed_profile_request():
    payload = {
        "idempotency_key": "user-confirmation-nonce",
        "confirmed_artifact_ids": ["artifact_" + "a" * 32],
    }

    request = _request_v2(payload)

    assert request["idempotency_key"] == payload["idempotency_key"]
    assert request["confirmed_artifact_ids"] == payload["confirmed_artifact_ids"]
    assert request["max_turns"] == 1
    assert request["execution_profile"] == profile_binding()
    assert request["request_limits"] == request_limits()
    assert "token_limit" not in request


@pytest.mark.parametrize("change", [
    {"token_limit": 1},
    {"max_turns": 2},
    {"execution_profile_id": "other-profile"},
    {"request_limits": {"max_provider_calls": 100}},
    {"background_web_search": True},
])
def test_v2_grant_rejects_legacy_budget_and_unlisted_fields(change):
    with pytest.raises(ValueError):
        _request_v2({
            "idempotency_key": "user-confirmation-nonce",
            "confirmed_artifact_ids": ["artifact_" + "a" * 32],
            **change,
        })


def test_missing_permission_exposes_only_the_trusted_profile_and_empty_request_state():
    view = ResearchContinuationMixin._continuation_view(
        {
            "task_id": "task_" + "a" * 32,
            "continuation_permission": None,
            "continuation_budget": [],
        },
        {"status": "active"},
    )

    assert view["schema_version"] == PERMISSION_SCHEMA_VERSION
    assert view["permission"] is None
    assert view["available_profile"] == {
        "execution_profile": profile_binding(),
        "request_limits": request_limits(),
    }
    assert view["request_state"] == {
        "requests_reserved": 0,
        "requests_remaining": 1,
        "unconfirmed_requests": 0,
        "request_usage": None,
        "request_identity": None,
    }
    assert view["can_start"] is False


def test_v2_public_view_has_confirmation_id_but_no_bearer_or_cumulative_budget():
    nonce = "user-confirmation-nonce"
    permission = {
        "schema_version": PERMISSION_SCHEMA_VERSION,
        "idempotency_key": nonce,
        "request_sha256": "b" * 64,
        "grant_version": 1,
        "max_turns": 1,
        "confirmed_artifact_ids": ["artifact_" + "a" * 32],
        "confirmed_artifacts": [],
        "execution_profile": profile_binding(),
        "request_limits": request_limits(),
        "owner_principal": "owner",
        "workspace_id": "workspace",
        "conversation_id": "conversation",
        "confirmed_by": "owner",
        "created_at": "2026-10-01T00:00:00+00:00",
        "expires_at": "2027-10-01T00:00:00+00:00",
        "revoked_at": None,
        "revoked_by": None,
    }
    view = ResearchContinuationMixin._continuation_view(
        {
            "task_id": "task_" + "a" * 32,
            "status": "running",
            "continuation_permission": permission,
            "continuation_budget": [{
                "schema_version": RESERVATION_SCHEMA_VERSION,
                "reservation_id": "continuation_" + "c" * 32,
                "grant_version": 1,
                "event_key": "ready-v1:" + "d" * 64,
                "input_sha256": "e" * 64,
                "instruction": "must not be projected",
                "status": "outcome_unknown",
                "run_id": "dsh-run-123",
                "request_usage": None,
                "settlement_sha256": None,
                "outcome": None,
                "dispatch_attempts": 1,
                "execution_profile": profile_binding(),
                "request_limits": request_limits(),
            }],
            "continuation_blocked_reason": None,
            "continuation_blocked_event_key": None,
        },
        {"status": "active"},
    )

    assert view["permission"]["confirmation_id"] == nonce
    assert view["available_profile"] == {
        "execution_profile": profile_binding(),
        "request_limits": request_limits(),
    }
    assert "idempotency_key" not in view["permission"]
    assert "request_sha256" not in view["permission"]
    assert "token_limit" not in view
    assert view["request_state"]["requests_remaining"] == 0
    assert view["request_state"]["unconfirmed_requests"] == 1
    assert view["request_state"]["request_identity"] == {
        "reservation_id": "continuation_" + "c" * 32,
        "status": "outcome_unknown",
        "run_id": "dsh-run-123",
        "event_key": "ready-v1:" + "d" * 64,
        "input_sha256": "e" * 64,
        "grant_version": 1,
        "outcome": None,
        "settlement_sha256": None,
        "dispatch_attempts": 1,
    }
    assert "instruction" not in view["request_state"]["request_identity"]
    assert view["can_start"] is False


def test_legacy_permission_view_is_explicitly_read_only_and_keeps_liability_facts():
    permission = {
        "schema_version": "task-continuation-permission.v1",
        "idempotency_key": "historical-key",
        "request_sha256": "b" * 64,
        "grant_version": 1,
        "token_limit": 900,
        "max_turns": 2,
        "revoked_at": None,
        "expires_at": "2027-10-01T00:00:00+00:00",
    }
    legacy_reservation = {
        "reservation_id": "continuation_" + "a" * 32,
        "status": "outcome_unknown",
        "token_limit": 200,
        "charged_tokens": None,
        "event_key": "legacy-event",
        "run_id": None,
    }

    view = ResearchContinuationMixin._continuation_view(
        {
            "task_id": "task_" + "a" * 32,
            "status": "running",
            "continuation_permission": permission,
            "continuation_budget": [legacy_reservation],
        },
        {"status": "active"},
    )

    assert view["schema_version"] == "task-continuation-permission.v1"
    assert view["blocked_reason"] == "legacy_continuation_read_only"
    assert view["budget"]["reserved_tokens"] == 200
    assert view["budget"]["unconfirmed_reservations"] == 1
    assert "confirmation_id" not in view["permission"]
    assert view["can_start"] is False


def test_v2_tool_scope_is_limited_to_exact_task_and_linked_backtest_reads():
    task = {"task_id": "task_" + "a" * 32}
    receipt = {
        "schema_version": RESERVATION_SCHEMA_VERSION,
        "backtest_task_id": "backtesttask_" + "b" * 32,
    }
    context = {
        "owner_principal": "owner",
        "actor_principal": "owner",
        "session_id": "session",
        "trace_id": "trace",
        "dsh_run_id": "dsh-run",
    }

    assert _v2_tool_arguments_allowed("byq_research_get", {
        "entity_type": "research_task", "entity_id": task["task_id"],
    }, task, receipt, context)
    assert _v2_tool_arguments_allowed("byq_backtest_task_get", {
        "backtest_task_id": receipt["backtest_task_id"],
    }, task, receipt, context)
    assert _v2_tool_arguments_allowed("byq_agent_authorize", {
        "action": "byq_research_get", "resource_type": "research_task",
        "resource_id": task["task_id"],
    }, task, receipt, context)
    assert _v2_tool_arguments_allowed("byq_agent_audit", {
        "action": "byq_backtest_task_get", "resource_type": "backtest_task",
        "resource_id": receipt["backtest_task_id"],
    }, task, receipt, context)

    assert not _v2_tool_arguments_allowed("byq_research_get", {
        "entity_type": "research_task", "entity_id": "task_" + "c" * 32,
    }, task, receipt, context)
    assert not _v2_tool_arguments_allowed("byq_backtest_task_get", {
        "backtest_task_id": "backtesttask_" + "c" * 32,
    }, task, receipt, context)
    assert not _v2_tool_arguments_allowed("byq_agent_authorize", {
        "action": "byq_backtest_task_execute", "resource_type": "backtest_task",
        "resource_id": receipt["backtest_task_id"],
    }, task, receipt, context)
    assert not _v2_tool_arguments_allowed("byq_agent_run_start", {
        "parent_run_id": "agent_run_" + "c" * 32,
    }, task, receipt, context)
