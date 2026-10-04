"""Pure contract checks for ADR-0098 pre-result settlement payloads."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.research_judgment import (
    validate_acp_judgment_cancel_intent_request,
    validate_acp_judgment_settlement_request,
)


def _request(kind: str = "never_dispatched", outcome: str = "failed",
             process_fence: str = "stopped") -> dict:
    cancellation_receipt = None
    if outcome == "cancelled":
        cancellation_receipt = {
            "schema_version": "byq-research-judgment-acp-cancel-intent-receipt.v1",
            "intent_id": "byqcancel-" + "f" * 32,
            "task_id": "task_" + "a" * 32,
            "owner_principal": "alice",
            "workspace_id": "workspace-a",
            "call_identity": "byq-judgment-" + "b" * 32,
            "root_run_id": "c" * 32,
            "intent_sha256": "sha256:" + "d" * 64,
        }
    if kind == "never_dispatched":
        journal_status, journal_digest = "available", "sha256:" + "1" * 64
        prompt_dispatch, provider_attempt = "not_dispatched", "not_started"
    elif kind == "cancelled_after_dispatch":
        journal_status, journal_digest = "missing", None
        prompt_dispatch, provider_attempt = "may_have_dispatched", "may_have_started"
    else:
        journal_status, journal_digest = "unavailable", None
        prompt_dispatch, provider_attempt = "may_have_dispatched", "may_have_started"
    return {
        "schema_version": "byq-research-judgment-acp-settlement-request.v1",
        "call_identity": "byq-judgment-" + "b" * 32,
        "attempt_binding": "1:strategy_draft:1",
        "root_run_id": "c" * 32,
        "runtime_boot_id": "e" * 32,
        "authority_epoch": 1,
        "dsh_run_id": "byqjudg-" + "9" * 32,
        "settlement_kind": kind,
        "terminal_outcome": outcome,
        "evidence": {
            "schema_version": "byq-research-judgment-acp-settlement-evidence.v1",
            "journal_status": journal_status,
            "journal_sha256": journal_digest,
            "prompt_dispatch": prompt_dispatch,
            "prompt_sha256": None,
            "provider_attempt": provider_attempt,
            "provider_attempt_sha256": None,
            "process_fence": process_fence,
            "process_fence_sha256": "sha256:" + "2" * 64 if process_fence == "stopped" else None,
            "known_usage": {"status": "unknown"},
            "cancellation_intent_receipt": cancellation_receipt,
        },
    }


@pytest.mark.parametrize(("kind", "outcome", "fence"), [
    ("never_dispatched", "failed", "stopped"),
    ("cancelled_after_dispatch", "cancelled", "stopped"),
    ("outcome_unknown", "interrupted", "unproven"),
])
def test_exact_settlement_variants_validate(kind: str, outcome: str, fence: str) -> None:
    assert validate_acp_judgment_settlement_request(_request(kind, outcome, fence))[
        "settlement_kind"] == kind


def test_settlement_request_is_closed_and_never_dispatched_requires_no_dispatch_proof() -> None:
    request = _request()
    opened = deepcopy(request)
    opened["untrusted"] = True
    with pytest.raises(ValueError, match="exact ACP judgment"):
        validate_acp_judgment_settlement_request(opened)

    dispatched = _request()
    dispatched["evidence"]["prompt_dispatch"] = "may_have_dispatched"
    with pytest.raises(ValueError, match="never_dispatched"):
        validate_acp_judgment_settlement_request(dispatched)


def test_unknown_can_be_recorded_without_claiming_process_fence() -> None:
    request = _request("outcome_unknown", "interrupted", "unproven")
    validated = validate_acp_judgment_settlement_request(request)
    assert validated["evidence"]["process_fence"] == "unproven"


def test_cancel_intent_receipt_is_closed_and_owner_scoped() -> None:
    request = {
        "schema_version": "byq-research-judgment-acp-cancel-intent-request.v1",
        "idempotency_key": "browser-request-123",
    }
    assert validate_acp_judgment_cancel_intent_request(request) == request
    with pytest.raises(ValueError, match="exact ACP judgment cancel-intent"):
        validate_acp_judgment_cancel_intent_request({**request, "root_run_id": "untrusted"})
