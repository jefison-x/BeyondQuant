"""Pure ADR-0111 continuation contract checks; no database or runtime imports."""

import pytest

from packages.contracts.agent_execution_options import default_agent_execution_options
from packages.contracts.product_turn_request import product_turn_execution_limits
from packages.contracts.continuation_request import (
    ALLOWED_DOMAIN_TOOLS,
    ALLOWED_HARNESS_TOOLS,
    PROFILE_ID,
    PROFILE_ID_V2,
    RESERVATION_SCHEMA_VERSION,
    RESERVATION_SCHEMA_VERSION_V3,
    USAGE_SCHEMA_VERSION,
    USAGE_SCHEMA_VERSION_V2,
    continuation_request_usage_v2,
    continuation_reservation_v3,
    exceeded_request_limits_v2,
    execution_profile_v2,
    profile_binding,
    request_limits,
    request_limits_v2,
    unknown_actual_usage_v2,
    unknown_admission_usage_v2,
    validate_execution_profile_v2,
    validate_request_limits_v2,
    validate_request_usage,
    validate_request_usage_v2,
    validate_reservation_v3,
)


def _reservation(**changes):
    value = {
        "owner_principal": "owner-a",
        "workspace_id": "workspace-a",
        "conversation_id": "conversation-a",
        "task_id": "task_" + "a" * 32,
        "event_key": "ready-v1:" + "b" * 64,
        "signal_job_id": "signaljob_" + "c" * 32,
        "result_artifact_id": "artifact_" + "d" * 32,
        "result_artifact_content_sha256": "e" * 64,
        "options": {},
        "options_revision": 0,
    }
    value.update(changes)
    return continuation_reservation_v3(**value)


def _known_admission(**changes):
    value = {
        "provider_calls": 1,
        "provider_attempts": 1,
        "input_bytes": 10,
        "declared_output_tokens": 8,
        "tool_payload_bytes": 4,
        "max_input_bytes": 10,
        "max_declared_output_tokens": 8,
        "max_tool_payload_bytes": 4,
        "tool_calls": 1,
        "max_concurrent": 1,
        "elapsed_ms": 100,
    }
    value.update(changes)
    return value


def _known_actual(**changes):
    value = {
        "input_tokens": 4,
        "cache_read_tokens": 0,
        "output_tokens": 3,
        "provider_attempts": 1,
        "usage_source": "provider_response",
        "completeness": "known",
    }
    value.update(changes)
    return value


def test_profile_v2_binds_full_options_revision_closed_route_and_tool_sets():
    profile = execution_profile_v2({}, revision=0)

    assert profile["profile_id"] == PROFILE_ID_V2 == "task-ready-read.v2"
    assert profile["options"] == default_agent_execution_options()
    assert profile["options_revision"] == 0
    assert profile["allowed_domain_tools"] == sorted(ALLOWED_DOMAIN_TOOLS)
    assert profile["allowed_harness_tools"] == sorted(ALLOWED_HARNESS_TOOLS)
    assert all(value is None for value in request_limits_v2(profile["options"]).values())
    assert "max_continuations" not in request_limits_v2(profile["options"])

    mapped_profile = execution_profile_v2({
        "max_output_tokens_per_call": 5,
        "max_output_tokens_total": 9,
        "max_concurrent_provider_calls": 2,
    }, revision=0)
    mapped_limits = request_limits_v2(mapped_profile["options"])
    assert mapped_limits == product_turn_execution_limits(mapped_profile["options"])
    assert (mapped_limits["max_output_tokens"], mapped_limits["max_total_output_tokens"],
            mapped_limits["max_concurrent"]) == (5, 9, 2)

    revised = execution_profile_v2({}, revision=1)
    changed = execution_profile_v2({"max_tool_calls": 3}, revision=0)
    assert revised["profile_sha256"] != profile["profile_sha256"]
    assert changed["profile_sha256"] != profile["profile_sha256"]
    assert validate_execution_profile_v2(profile) == profile

    for tampered in (
        {**profile, "provider": "other-provider"},
        {**profile, "upstream_base_url": "https://other.invalid"},
        {**profile, "upstream_request_target": "/other"},
        {**profile, "allowed_domain_tools": ["byq_research_get"]},
        {**profile, "allowed_harness_tools": ["byq_agent_audit"]},
        {**profile, "options_schema_version": "other-options.v1"},
        {**profile, "unexpected": True},
        {**profile, "profile_sha256": "0" * 64},
    ):
        with pytest.raises(ValueError):
            validate_execution_profile_v2(tampered)


def test_profile_and_limits_reject_boolean_integers_unknown_options_and_drift():
    with pytest.raises(ValueError):
        execution_profile_v2({"max_tool_calls": True}, revision=0)
    for invalid in (-1, 1.5):
        with pytest.raises(ValueError):
            execution_profile_v2({"max_tool_calls": invalid}, revision=0)
    with pytest.raises(ValueError):
        execution_profile_v2({}, revision=True)
    with pytest.raises(ValueError):
        execution_profile_v2({}, revision=-1)
    with pytest.raises(ValueError):
        execution_profile_v2({"hidden_limit": 1}, revision=0)

    profile = execution_profile_v2({"max_provider_calls": 1}, revision=0)
    limits = request_limits_v2(profile["options"])
    boolean_limit = {**limits, "max_provider_calls": True}
    with pytest.raises(ValueError):
        validate_request_limits_v2(boolean_limit, profile)
    with pytest.raises(ValueError):
        validate_request_limits_v2({**limits, "max_provider_calls": 2}, profile)


def test_v3_idempotency_key_is_stable_for_same_job_across_options_and_result_metadata():
    original = _reservation()
    changed_profile = _reservation(options={"max_provider_calls": 4}, options_revision=7)
    changed_facts = _reservation(
        event_key="ready-v1:" + "f" * 64,
        result_artifact_id="artifact_" + "8" * 32,
        result_artifact_content_sha256="1" * 64,
    )

    assert original["execution_profile"]["profile_sha256"] != changed_profile["execution_profile"]["profile_sha256"]
    assert original["source_fact_sha256"] != changed_facts["source_fact_sha256"]
    assert original["idempotency_key"] == changed_profile["idempotency_key"]
    assert original["idempotency_key"] == changed_facts["idempotency_key"]
    assert original["idempotency_key"] != _reservation(
        signal_job_id="signaljob_" + "9" * 32
    )["idempotency_key"]
    assert original["idempotency_key"] != _reservation(
        task_id="task_" + "9" * 32
    )["idempotency_key"]


def test_v3_is_a_closed_self_hashed_carrier_without_grants_or_execution_ttl():
    reservation = _reservation()
    assert reservation["schema_version"] == RESERVATION_SCHEMA_VERSION_V3
    assert "execution_profile" in reservation and "request_limits" in reservation
    assert not ({"grant_version", "permission_id", "expires_at", "valid_seconds"} & set(reservation))
    assert validate_reservation_v3(reservation) == reservation

    tampered_values = (
        {**reservation, "owner_principal": "owner-other"},
        {**reservation, "workspace_id": "workspace-other"},
        {**reservation, "task_id": "task_" + "9" * 32},
        {**reservation, "signal_job_id": "signaljob_" + "9" * 32},
        {**reservation, "result_artifact_id": "artifact_" + "9" * 32},
        {**reservation, "result_artifact_content_sha256": "0" * 64},
        {**reservation, "signal_job_status": "running"},
        {**reservation, "execution_profile": {**reservation["execution_profile"], "model": "other"}},
        {**reservation, "execution_profile": {
            **reservation["execution_profile"],
            "options": {**reservation["execution_profile"]["options"], "max_tool_calls": 1},
        }},
        {**reservation, "request_limits": {**reservation["request_limits"], "max_provider_calls": 2}},
        {**reservation, "grant_version": 1},
        {key: item for key, item in reservation.items() if key != "event_key"},
    )
    for tampered in tampered_values:
        with pytest.raises(ValueError):
            validate_reservation_v3(tampered)


def test_v3_structure_does_not_claim_database_truth_or_dispatch_authority():
    # A self-consistent payload for a foreign owner is structurally valid. The
    # later Backend reservation fence must compare it with locked SQL facts.
    foreign_scope = _reservation(owner_principal="different-owner")
    assert validate_reservation_v3(foreign_scope) == foreign_scope


def test_usage_v2_keeps_unknown_counts_null_and_never_turns_them_into_zero():
    profile = execution_profile_v2({"max_provider_calls": 1}, revision=0)
    receipt = continuation_request_usage_v2(
        execution_profile=profile,
        admission_usage=unknown_admission_usage_v2(),
        actual_usage=unknown_actual_usage_v2(),
    )

    assert receipt["schema_version"] == USAGE_SCHEMA_VERSION_V2
    assert all(value is None for value in receipt["admission_usage"].values())
    assert all(receipt["actual_usage"][key] is None for key in (
        "input_tokens", "cache_read_tokens", "output_tokens", "provider_attempts"))
    assert receipt["actual_usage"]["completeness"] == "unknown"
    assert exceeded_request_limits_v2(receipt) == []  # no known overrun is not success evidence

    partial = continuation_request_usage_v2(
        execution_profile=profile,
        admission_usage=_known_admission(),
        actual_usage=_known_actual(cache_read_tokens=None, completeness="partial"),
    )
    assert partial["actual_usage"]["cache_read_tokens"] is None
    assert partial["actual_usage"]["input_tokens"] == 4


def test_usage_v2_records_known_overruns_and_preserves_provider_observations():
    profile = execution_profile_v2({
        "max_provider_calls": 2,
        "max_provider_attempts": 2,
        "max_input_bytes_per_call": 4,
        "max_input_bytes_total": 10,
        "max_tool_calls": 1,
        "max_runtime_seconds": 1,
    }, revision=0)
    admission = _known_admission(
        provider_calls=3, provider_attempts=3, input_bytes=11,
        max_input_bytes=5, tool_calls=2, elapsed_ms=1001,
    )
    receipt = continuation_request_usage_v2(
        execution_profile=profile,
        admission_usage=admission,
        actual_usage=_known_actual(provider_attempts=3),
        limit_violations=["provider_declared_output_exceeded"],
    )

    assert set(exceeded_request_limits_v2(receipt)) == {
        "max_provider_calls", "max_attempts", "max_input_bytes",
        "max_total_input_bytes", "max_tool_calls", "max_runtime_seconds",
        "provider_declared_output_exceeded",
    }
    omitted = {**receipt, "limit_violations": [
        item for item in receipt["limit_violations"] if item != "max_provider_calls"]}
    with pytest.raises(ValueError):
        validate_request_usage_v2(omitted)


def test_usage_v2_rejects_bool_counts_peaks_above_totals_and_legacy_shape():
    profile = execution_profile_v2({}, revision=0)
    with pytest.raises(ValueError):
        continuation_request_usage_v2(
            execution_profile=profile,
            admission_usage=_known_admission(provider_calls=True),
            actual_usage=_known_actual(),
        )
    with pytest.raises(ValueError):
        continuation_request_usage_v2(
            execution_profile=profile,
            admission_usage={key: item for key, item in _known_admission().items() if key != "tool_calls"},
            actual_usage=_known_actual(),
        )
    with pytest.raises(ValueError):
        continuation_request_usage_v2(
            execution_profile=profile,
            admission_usage=_known_admission(provider_calls=2, provider_attempts=1),
            actual_usage=_known_actual(),
        )
    with pytest.raises(ValueError):
        continuation_request_usage_v2(
            execution_profile=profile,
            admission_usage=_known_admission(max_input_bytes=11),
            actual_usage=_known_actual(),
        )
    with pytest.raises(ValueError):
        continuation_request_usage_v2(
            execution_profile=profile,
            admission_usage=_known_admission(),
            actual_usage=_known_actual(output_tokens=True),
        )
    with pytest.raises(ValueError):
        continuation_request_usage_v2(
            execution_profile=profile,
            admission_usage=unknown_admission_usage_v2(),
            actual_usage=unknown_actual_usage_v2() | {"completeness": "known"},
        )
    zero_counts = {
        "input_tokens": 0, "cache_read_tokens": 0, "output_tokens": 0,
        "provider_attempts": 0, "usage_source": "no_provider_calls", "completeness": "known",
    }
    proven_zero_admission = _known_admission(**{key: 0 for key in _known_admission()})
    proven_zero = continuation_request_usage_v2(
        execution_profile=profile,
        admission_usage=proven_zero_admission,
        actual_usage=zero_counts,
    )
    assert validate_request_usage_v2(proven_zero)["actual_usage"] == zero_counts
    with pytest.raises(ValueError):
        continuation_request_usage_v2(
            execution_profile=profile,
            admission_usage=unknown_admission_usage_v2(),
            actual_usage=zero_counts,
        )
    with pytest.raises(ValueError):
        continuation_request_usage_v2(
            execution_profile=profile,
            admission_usage=_known_admission(),
            actual_usage=zero_counts,
        )
    with pytest.raises(ValueError):
        validate_request_usage_v2({"schema_version": USAGE_SCHEMA_VERSION})

    assert PROFILE_ID == "task-ready-read.v1"
    assert RESERVATION_SCHEMA_VERSION == "task-continuation-reservation.v2"
    assert USAGE_SCHEMA_VERSION == "continuation-request-usage.v1"
    legacy_admission = _known_admission()
    legacy_actual = _known_actual()
    legacy = {
        "schema_version": USAGE_SCHEMA_VERSION,
        "execution_profile": profile_binding(),
        "request_limits": request_limits(),
        "admission_usage": legacy_admission,
        "actual_usage": legacy_actual,
        "limit_violations": [],
    }
    assert validate_request_usage(legacy) == legacy
    with pytest.raises(ValueError):
        validate_request_usage_v2(legacy)
