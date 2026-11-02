from __future__ import annotations

from copy import deepcopy

from app.operations import _aggregate_continuation_usage
from packages.contracts.continuation_request import (
    ALLOWED_MODEL,
    ALLOWED_PROVIDER,
    OFFICIAL_MODEL,
    OFFICIAL_PROVIDER,
    continuation_request_usage_v2,
    continuation_reservation_identity_v3,
    continuation_reservation_v3,
    execution_profile_v2,
    request_limits_v2,
    unknown_admission_usage_v2,
)


def _actual(*, input_tokens, cache_read_tokens, output_tokens, provider_attempts,
            usage_source="provider_response", completeness="known"):
    return {
        "input_tokens": input_tokens,
        "cache_read_tokens": cache_read_tokens,
        "output_tokens": output_tokens,
        "provider_attempts": provider_attempts,
        "usage_source": usage_source,
        "completeness": completeness,
    }


def _entry(index: int, *, provider=ALLOWED_PROVIDER, actual=None, status="settled",
           usage_profile=None, usage_options=None, owner="usage-owner",
           workspace="workspace_usage_owner", task_id=None, conversation_id="conversation_usage_owner"):
    suffix = f"{index:032x}"
    common = {
        "owner_principal": owner,
        "workspace_id": workspace,
        "conversation_id": conversation_id,
        "task_id": task_id or "task_" + suffix,
        "signal_job_id": "signaljob_" + suffix,
        "result_artifact_id": "artifact_" + suffix,
        "result_artifact_content_sha256": f"{index:064x}",
    }
    identity = continuation_reservation_identity_v3(**common)
    model = OFFICIAL_MODEL if provider == OFFICIAL_PROVIDER else ALLOWED_MODEL
    reservation = continuation_reservation_v3(
        **common, event_key=identity["event_key"], options={}, options_revision=0,
        provider=provider, model=model,
    )
    profile = usage_profile or reservation["execution_profile"]
    limits = request_limits_v2(profile["options"] if usage_options is None else usage_options)
    observed = actual or _actual(
        input_tokens=None, cache_read_tokens=None, output_tokens=None, provider_attempts=None,
        usage_source="unknown", completeness="unknown",
    )
    admission = unknown_admission_usage_v2()
    if observed["provider_attempts"] is not None:
        admission["provider_calls"] = observed["provider_attempts"]
        admission["provider_attempts"] = observed["provider_attempts"]
    usage = continuation_request_usage_v2(
        execution_profile=profile, admission_usage=admission, actual_usage=observed,
        limit_violations=(),
    )
    # `continuation_request_usage_v2` derives these from the profile options.
    assert usage["request_limits"] == limits
    entry = {
        "schema_version": "task-continuation-ledger-entry.v1",
        "reservation_id": "continuation_" + reservation["idempotency_key"].removeprefix(
            "task-ready-event:")[:32],
        "event_key": reservation["event_key"],
        "signal_job_id": reservation["signal_job_id"],
        "status": status,
        "created_at": "2026-11-01T00:00:00+00:00",
        "reservation": reservation,
    }
    if status == "settled":
        entry.update({
            "dispatch_attempts": 1,
            "run_id": "a" * 32,
            "request_usage": usage,
            "settlement_sha256": "b" * 64,
            "outcome": "completed",
        })
    elif status == "accepted":
        entry.update({"dispatch_attempts": 1, "run_id": "a" * 32})
    return entry


def _task(*entries, owner="usage-owner", workspace="workspace_usage_owner", task_id=None):
    first_reservation = next((entry.get("reservation") for entry in entries
                              if isinstance(entry, dict) and isinstance(entry.get("reservation"), dict)), None)
    return {
        "task_id": task_id or (first_reservation.get("task_id") if first_reservation else "task_" + "0" * 32),
        "owner_principal": owner,
        "workspace_id": workspace,
        "continuation_budget": list(entries),
    }


def test_operations_usage_projects_official_f6_receipt_and_keeps_rows_unchanged():
    entry = _entry(
        1, provider=OFFICIAL_PROVIDER,
        actual=_actual(input_tokens=47_589, cache_read_tokens=319_232,
                       output_tokens=1_539, provider_attempts=8),
    )
    task = _task(entry)
    before = deepcopy(task)

    usage = _aggregate_continuation_usage([task])

    assert usage == {
        "schema_version": "operations-usage.v1",
        "scope": "persisted_continuation_requests",
        "source": "backend_validated_request_receipts",
        "completeness": "partial",
        "request_count": 1,
        "known_requests": 1,
        "unknown_requests": 0,
        "invalid_requests": 0,
        "known_totals": {
            "input_tokens": 47_589,
            "cache_read_tokens": 319_232,
            "output_tokens": 1_539,
            "provider_attempts": 8,
            "total_tokens": 368_360,
        },
        "uncovered_sources": ["ordinary_product_roots", "research_judgment"],
        "truncated": False,
    }
    assert task == before


def test_operations_usage_normalizes_go_cached_prompt_and_deduplicates_exact_rows():
    entry = _entry(
        2, actual=_actual(input_tokens=100, cache_read_tokens=70,
                          output_tokens=5, provider_attempts=2),
    )

    usage = _aggregate_continuation_usage([_task(entry, deepcopy(entry))])

    assert usage["request_count"] == usage["known_requests"] == 1
    assert usage["known_totals"] == {
        "input_tokens": 30,
        "cache_read_tokens": 70,
        "output_tokens": 5,
        "provider_attempts": 2,
        "total_tokens": 105,
    }


def test_operations_usage_separates_unknown_invalid_and_conflicting_bindings():
    conflicting = _entry(
        3, provider=OFFICIAL_PROVIDER,
        actual=_actual(input_tokens=5, cache_read_tokens=0, output_tokens=1, provider_attempts=1),
    )
    conflict_copy = deepcopy(conflicting)
    conflict_copy["outcome"] = "needs_attention"

    fake_digest = _entry(
        4, provider=OFFICIAL_PROVIDER,
        actual=_actual(input_tokens=5, cache_read_tokens=0, output_tokens=1, provider_attempts=1),
    )
    fake_digest["reservation"]["source_fact_sha256"] = "f" * 64

    owner_mismatch = _entry(
        5, provider=OFFICIAL_PROVIDER,
        actual=_actual(input_tokens=5, cache_read_tokens=0, output_tokens=1, provider_attempts=1),
    )
    task_mismatch = _entry(
        12, provider=OFFICIAL_PROVIDER,
        actual=_actual(input_tokens=5, cache_read_tokens=0, output_tokens=1, provider_attempts=1),
    )
    workspace_mismatch = _entry(
        13, provider=OFFICIAL_PROVIDER,
        actual=_actual(input_tokens=5, cache_read_tokens=0, output_tokens=1, provider_attempts=1),
    )
    profile_mismatch = _entry(
        6, provider=OFFICIAL_PROVIDER,
        actual=_actual(input_tokens=5, cache_read_tokens=0, output_tokens=1, provider_attempts=1),
        usage_profile=execution_profile_v2(
            {"max_provider_calls": 2}, revision=1,
            provider=OFFICIAL_PROVIDER, model=OFFICIAL_MODEL,
        ),
        usage_options={"max_provider_calls": 2},
    )
    cache_exceeds_prompt = _entry(
        7, actual=_actual(input_tokens=10, cache_read_tokens=11, output_tokens=1, provider_attempts=1),
    )
    accepted = _entry(8, status="accepted")
    partial = _entry(9, provider=OFFICIAL_PROVIDER, actual=_actual(
        input_tokens=5, cache_read_tokens=None, output_tokens=None, provider_attempts=None,
        completeness="partial",
    ))
    unknown = _entry(10)
    old_version = {
        "schema_version": "task-continuation-reservation.v2",
        "reservation_id": "continuation_legacy_v2",
        "status": "settled",
    }
    tasks = [
        _task(conflicting, conflict_copy),
        _task(fake_digest),
        _task(accepted),
        _task(partial),
        _task(unknown),
        _task(old_version),
        _task(owner_mismatch, owner="different-owner"),
        _task(task_mismatch, task_id="task_" + "f" * 32),
        _task(workspace_mismatch, workspace="different-workspace"),
        _task(profile_mismatch),
        _task(cache_exceeds_prompt),
    ]

    usage = _aggregate_continuation_usage(tasks)

    assert usage["request_count"] == 11
    assert usage["known_requests"] == 0
    assert usage["unknown_requests"] == 4
    assert usage["invalid_requests"] == 7
    assert usage["known_totals"] == {
        "input_tokens": 0, "cache_read_tokens": 0, "output_tokens": 0,
        "provider_attempts": 0, "total_tokens": 0,
    }


def test_operations_usage_counts_proven_no_provider_call_as_known_zero():
    usage = _entry(11, actual=_actual(
        input_tokens=0, cache_read_tokens=0, output_tokens=0, provider_attempts=0,
        usage_source="no_provider_calls",
    ))

    projected = _aggregate_continuation_usage([_task(usage)])

    assert projected["request_count"] == projected["known_requests"] == 1
    assert projected["unknown_requests"] == projected["invalid_requests"] == 0
    assert projected["known_totals"] == {
        "input_tokens": 0, "cache_read_tokens": 0, "output_tokens": 0,
        "provider_attempts": 0, "total_tokens": 0,
    }
