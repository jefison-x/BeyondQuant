"""Known budget-exhaustion classification for the ordinary ACP Product gate.

These are host tests (no carrier, no provider, no Job). They pin the atomic
distinction between a known, fully-settled budget-limit refusal (which may leave
the live conversation promptable for an explicit new instruction) and every
other outcome (storage/journal failure, cancellation, invalid route/auth,
client disconnect, provider anomaly, unknown/unpaired) which must keep the
session failed and fenced. The retained real f6 batch1 journal is committed as a
portable fixture under ``tests/fixtures/``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.research_request_gate import (
    BUDGET_LIMIT_REASONS,
    KNOWN_BLOCKED,
    SETTLED_OK,
    ResearchRequestGate,
)
from packages.contracts.product_turn_request import product_turn_limits, product_turn_profile

_BATCH1_JOURNAL = (
    Path(__file__).parent / "fixtures" / "dsh_batch1_known_budget_journal.jsonl"
)


def _gate(
    receipts: list[dict],
    *,
    provider_calls: int = 0,
    request_id: str = "product-turn-test",
    gate_closed: bool = True,
    journal_failed: bool = False,
    outcome_unknown: bool = False,
    inflight: int = 0,
    waiting: int = 0,
) -> ResearchRequestGate:
    gate = ResearchRequestGate(
        product_turn_limits(), execution_profile=product_turn_profile(),
        request_id=request_id,
    )
    gate._receipts = list(receipts)
    gate._provider_calls = provider_calls
    gate._attempts = provider_calls
    gate._gate_closed = gate_closed
    gate._journal_failed = journal_failed
    gate._outcome_unknown = outcome_unknown
    gate._inflight = inflight
    gate._waiting = waiting
    return gate


def _admitted(call: int = 1) -> dict:
    return {
        "schema_version": "continuation-request-gate.v1",
        "request_id": "product-turn-test",
        "phase": "admitted", "admitted": True, "call": call, "attempt": call,
    }


def _rejected(reason: str) -> dict:
    return {
        "schema_version": "continuation-request-gate.v1",
        "request_id": "product-turn-test",
        "phase": "rejected", "admitted": False, "reason": reason,
        "input_bytes": 10, "at_ms": 1,
    }


def _aborted(reason: str) -> dict:
    return {**_rejected(reason), "phase": "aborted"}


def _completed_forwarded(reason: str = "within_request_budget", call: int = 1) -> dict:
    return {
        "schema_version": "continuation-request-gate.v1",
        "request_id": "product-turn-test",
        "phase": "completed", "admitted": True, "call": call, "attempt": call,
        "forwarded": True, "reason": reason, "status": 200,
    }


def _completed_not_forwarded(reason: str) -> dict:
    return {**_completed_forwarded(reason), "forwarded": False}


def test_settled_scope_is_not_a_budget_block():
    gate = _gate([_admitted(1), _completed_forwarded(call=1)], provider_calls=1)
    assert gate.settlement_state() == SETTLED_OK
    assert gate.known_budget_block_reason() is None


@pytest.mark.parametrize("reason", sorted(BUDGET_LIMIT_REASONS))
def test_each_budget_limit_reason_is_known_budget_block(reason: str):
    gate = _gate([_rejected(reason)])
    assert gate.settlement_state() == KNOWN_BLOCKED
    assert gate.known_budget_block_reason() == reason


def test_completed_not_forwarded_deadline_is_not_a_known_budget_block():
    # A completed-but-unforwarded response (deadline_exceeded can arise
    # post-dispatch in _complete_continuation_request) is a broader case than
    # this slice's pre-dispatch refusal and must not reopen the conversation.
    gate = _gate([_admitted(1), _completed_not_forwarded("deadline_exceeded")], provider_calls=1)
    assert gate.settlement_state() == KNOWN_BLOCKED
    assert gate.known_budget_block_reason() is None


def test_mixed_budget_and_postdispatch_deadline_is_not_a_budget_block():
    gate = _gate(
        [_rejected("total_tool_payload_limit"), _admitted(1),
         _completed_not_forwarded("deadline_exceeded")],
        provider_calls=1,
    )
    assert gate.settlement_state() == KNOWN_BLOCKED
    assert gate.known_budget_block_reason() is None


def test_classifier_computes_settlement_under_one_lock():
    gate = _gate([_rejected("tool_payload_limit")])
    original = gate._settlement_state_locked
    observed: list[bool] = []

    def wrapper() -> str:
        observed.append(gate._lock.locked())
        return original()

    gate._settlement_state_locked = wrapper  # type: ignore[method-assign]
    assert gate.known_budget_block_reason() == "tool_payload_limit"
    assert observed == [True]
    # The public wrapper's semantics are unchanged.
    assert gate.settlement_state() == KNOWN_BLOCKED


def test_late_storage_failure_cannot_yield_a_stale_budget_verdict():
    # Simulate a storage failure becoming visible between the settlement snapshot
    # and the receipt read: the atomic classifier must not return a stale budget
    # reason (the old multi-lock design's gap).
    gate = _gate([_rejected("tool_payload_limit")])
    original = gate._settlement_state_locked

    def mutate_once() -> str:
        result = original()
        gate._journal_failed = True
        return result

    gate._settlement_state_locked = mutate_once  # type: ignore[method-assign]
    assert gate.known_budget_block_reason() is None


def test_storage_failure_after_budget_block_is_not_a_budget_block():
    gate = _gate([_rejected("tool_payload_limit")])
    assert gate.known_budget_block_reason() == "tool_payload_limit"
    with gate._lock:
        gate._journal_failed = True
    assert gate.known_budget_block_reason() is None


def test_multiple_distinct_budget_reasons_are_not_single_normalized_reason():
    gate = _gate([_rejected("total_tool_payload_limit"), _rejected("provider_call_limit")])
    assert gate.settlement_state() == KNOWN_BLOCKED
    assert gate.known_budget_block_reason() is None


def test_cancellation_reason_is_not_a_budget_block():
    gate = _gate([_rejected("cancelled")])
    assert gate.settlement_state() == KNOWN_BLOCKED
    assert gate.known_budget_block_reason() is None


def test_mixed_budget_and_cancellation_is_not_a_budget_block():
    gate = _gate([_rejected("total_tool_payload_limit"), _rejected("cancelled")])
    assert gate.known_budget_block_reason() is None


@pytest.mark.parametrize("reason", [
    "storage_failed", "budget_invalid", "model_route_unqualified",
    "provider_path_unqualified", "declared_output_limit_missing",
    "declared_output_limit_conflict", "client_disconnected",
])
def test_non_budget_refusals_are_not_known_budget_blocks(reason: str):
    gate = _gate([_aborted(reason) if reason == "client_disconnected" else _rejected(reason)])
    assert gate.known_budget_block_reason() is None


def test_output_tokens_exceeded_anomaly_is_not_a_budget_block():
    gate = _gate([_admitted(1), _completed_not_forwarded("output_tokens_exceeded")], provider_calls=1)
    assert gate.settlement_state() == KNOWN_BLOCKED
    assert gate.known_budget_block_reason() is None


def test_journal_failure_is_not_a_budget_block():
    gate = _gate([_rejected("total_tool_payload_limit")], journal_failed=True)
    assert gate.known_budget_block_reason() is None


def test_unknown_outcome_is_not_a_budget_block():
    gate = _gate([_rejected("total_tool_payload_limit")], outcome_unknown=True)
    assert gate.settlement_state() != KNOWN_BLOCKED
    assert gate.known_budget_block_reason() is None


def test_unsealed_inflight_or_waiting_scope_is_not_a_budget_block():
    assert _gate([_rejected("provider_call_limit")], gate_closed=False) \
        .known_budget_block_reason() is None
    assert _gate([_rejected("provider_call_limit")], inflight=1) \
        .known_budget_block_reason() is None
    assert _gate([_rejected("provider_call_limit")], waiting=1) \
        .known_budget_block_reason() is None


def test_retained_batch1_real_journal_classifies_known_budget_block():
    raw = _BATCH1_JOURNAL.read_text()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    provider_calls = sum(1 for row in rows if row.get("phase") == "completed")
    accepted = [row for row in rows if row.get("phase") == "admitted"]
    rejected = [row for row in rows if row.get("phase") == "rejected"]
    # Every admitted request in the real journal has exactly one completion row.
    assert len(accepted) == provider_calls
    # The real pre-dispatch refusal is a rejected row with admitted false.
    assert len(rejected) == 1
    assert rejected[0]["admitted"] is False
    assert rejected[0]["reason"] == "total_tool_payload_limit"
    gate = _gate(rows, provider_calls=provider_calls, request_id=rows[0]["request_id"])
    assert gate.settlement_state() == KNOWN_BLOCKED
    assert gate.has_unknown_outcome() is False
    assert gate.known_budget_block_reason() == "total_tool_payload_limit"
