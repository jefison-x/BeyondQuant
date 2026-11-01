"""Pure ADR-0111 continuation contract checks; no database or runtime imports."""

import pytest

from packages.contracts.agent_execution_options import default_agent_execution_options
from packages.contracts.product_turn_request import product_turn_execution_limits
from packages.contracts.continuation_request import (
    ALLOWED_DOMAIN_TOOLS,
    ALLOWED_HARNESS_TOOLS,
    PERMISSION_SCHEMA_VERSION,
    ALLOWED_MODEL,
    ALLOWED_PROVIDER,
    OFFICIAL_MODEL,
    OFFICIAL_PROFILE_ID,
    OFFICIAL_PROFILE_VERSION,
    OFFICIAL_PROVIDER,
    OFFICIAL_UPSTREAM_BASE_URL,
    OFFICIAL_UPSTREAM_REQUEST_TARGET,
    PROFILE_ID,
    PROFILE_ID_V2,
    RESERVATION_SCHEMA_VERSION,
    RESERVATION_SCHEMA_VERSION_V3,
    USAGE_SCHEMA_VERSION,
    USAGE_SCHEMA_VERSION_V2,
    continuation_request_usage_v2,
    continuation_reservation_identity_v3,
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
from app.research_continuation import ResearchContinuationMixin


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


def _settled_v3_ledger_entry(*, job_suffix="c"):
    common = {
        "owner_principal": "owner-a",
        "workspace_id": "workspace-a",
        "conversation_id": "conversation-a",
        "task_id": "task_" + "a" * 32,
        "signal_job_id": "signaljob_" + job_suffix * 32,
        "result_artifact_id": "artifact_" + job_suffix * 32,
        "result_artifact_content_sha256": "e" * 64,
    }
    identity = continuation_reservation_identity_v3(**common)
    reservation = continuation_reservation_v3(
        **common, event_key=identity["event_key"], options={}, options_revision=0,
    )
    usage = continuation_request_usage_v2(
        execution_profile=reservation["execution_profile"],
        admission_usage=unknown_admission_usage_v2(),
        actual_usage=unknown_actual_usage_v2(),
    )
    entry = {
        "schema_version": "task-continuation-ledger-entry.v1",
        "reservation_id": "continuation_" + reservation["idempotency_key"].removeprefix(
            "task-ready-event:")[:32],
        "event_key": reservation["event_key"],
        "signal_job_id": reservation["signal_job_id"],
        "status": "settled",
        "created_at": "2026-11-01T00:00:00+00:00",
        "reservation": reservation,
        "dispatch_attempts": 1,
        "run_id": "f" * 32,
        "request_usage": usage,
        "settlement_sha256": "d" * 64,
        "outcome": "completed",
    }
    return entry, usage


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

    # Calls that omit route arguments retain the historical v2 carrier and
    # profile hash byte-for-byte.
    import hashlib
    import json
    from packages.contracts.agent_execution_options import SCHEMA_VERSION

    legacy_binding = {
        "profile_id": PROFILE_ID_V2,
        "profile_version": 2,
        "options_schema_version": SCHEMA_VERSION,
        "options_revision": 0,
        "options": default_agent_execution_options(),
        "provider": ALLOWED_PROVIDER,
        "model": ALLOWED_MODEL,
        "upstream_base_url": "https://opencode.ai/zen/go/v1",
        "upstream_request_target": "/chat/completions",
        "allowed_domain_tools": sorted(ALLOWED_DOMAIN_TOOLS),
        "allowed_harness_tools": sorted(ALLOWED_HARNESS_TOOLS),
    }
    assert profile == {
        **legacy_binding,
        "profile_sha256": hashlib.sha256(json.dumps(
            legacy_binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    }

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


def test_official_deepseek_route_is_a_closed_versioned_profile():
    options = default_agent_execution_options()
    profile = execution_profile_v2(
        options, revision=3, provider=OFFICIAL_PROVIDER, model=OFFICIAL_MODEL,
    )
    assert profile["profile_id"] == OFFICIAL_PROFILE_ID == "task-ready-read.official-deepseek.v1"
    assert profile["profile_version"] == OFFICIAL_PROFILE_VERSION == 1
    assert profile["provider"] == OFFICIAL_PROVIDER == "deepseek-official"
    assert profile["model"] == OFFICIAL_MODEL == "deepseek-flash"
    assert profile["upstream_base_url"] == OFFICIAL_UPSTREAM_BASE_URL == "https://api.deepseek.com/anthropic"
    assert profile["upstream_request_target"] == OFFICIAL_UPSTREAM_REQUEST_TARGET == "/v1/messages"
    assert profile["options"] == options and profile["options_revision"] == 3
    assert all(value is None for value in request_limits_v2(options).values())
    assert validate_execution_profile_v2(profile) == profile

    for wrong_route in (
        {"provider": OFFICIAL_PROVIDER, "model": ALLOWED_MODEL},
        {"provider": ALLOWED_PROVIDER, "model": OFFICIAL_MODEL},
        {"provider": "deepseek", "model": OFFICIAL_MODEL},
        {"provider": OFFICIAL_PROVIDER, "model": "deepseek-chat"},
        {"provider": [OFFICIAL_PROVIDER], "model": OFFICIAL_MODEL},
    ):
        with pytest.raises(ValueError):
            execution_profile_v2(options, revision=3, **wrong_route)
    for tampered in (
        {**profile, "profile_version": 2},
        {**profile, "upstream_base_url": "https://api.deepseek.com"},
        {**profile, "upstream_request_target": "/messages"},
        {**profile, "provider": ALLOWED_PROVIDER},
        {**profile, "model": ALLOWED_MODEL},
        {**profile, "profile_sha256": "0" * 64},
    ):
        with pytest.raises(ValueError):
            validate_execution_profile_v2(tampered)


def test_v3_route_variants_preserve_stable_event_identity_and_carrier_shape():
    common = {
        "owner_principal": "owner-a",
        "workspace_id": "workspace-a",
        "conversation_id": "conversation-a",
        "task_id": "task_" + "a" * 32,
        "signal_job_id": "signaljob_" + "c" * 32,
        "result_artifact_id": "artifact_" + "d" * 32,
        "result_artifact_content_sha256": "e" * 64,
    }
    identity = continuation_reservation_identity_v3(**common)
    legacy = continuation_reservation_v3(
        **common, event_key=identity["event_key"], options={}, options_revision=0,
    )
    official = continuation_reservation_v3(
        **common, event_key=identity["event_key"], options={}, options_revision=0,
        provider=OFFICIAL_PROVIDER, model=OFFICIAL_MODEL,
    )
    assert set(legacy) == set(official)
    assert legacy["schema_version"] == official["schema_version"] == RESERVATION_SCHEMA_VERSION_V3
    assert legacy["idempotency_key"] == official["idempotency_key"] == identity["idempotency_key"]
    assert legacy["source_fact_sha256"] == official["source_fact_sha256"] == identity["source_fact_sha256"]
    assert legacy["request_limits"] == official["request_limits"]
    assert legacy["execution_profile"]["profile_sha256"] != official["execution_profile"]["profile_sha256"]
    assert official["execution_profile"]["profile_id"] == OFFICIAL_PROFILE_ID


def test_continuation_view_projects_only_the_latest_validated_v3_request():
    earlier, _ = _settled_v3_ledger_entry(job_suffix="c")
    latest, usage = _settled_v3_ledger_entry(job_suffix="d")
    task = {
        "task_id": latest["reservation"]["task_id"],
        "continuation_permission": None,
        "continuation_budget": [earlier, latest],
    }

    view = ResearchContinuationMixin._continuation_view(task, {})
    automatic = view["automatic_request"]
    assert set(automatic) == {
        "schema_version", "reservation_id", "task_id", "signal_job_id",
        "result_artifact_id", "status", "dispatch_attempts", "run_id",
        "outcome", "execution_profile", "request_usage", "settlement_sha256",
    }
    assert automatic == {
        "schema_version": "task-ready-request-view.v1",
        "reservation_id": latest["reservation_id"],
        "task_id": latest["reservation"]["task_id"],
        "signal_job_id": latest["signal_job_id"],
        "result_artifact_id": latest["reservation"]["result_artifact_id"],
        "status": "settled",
        "dispatch_attempts": 1,
        "run_id": "f" * 32,
        "outcome": "completed",
        "execution_profile": latest["reservation"]["execution_profile"],
        "request_usage": usage,
        "settlement_sha256": "d" * 64,
    }
    assert view["permission"] is None
    assert view["blocked_reason"] == "permission_missing"
    assert "budget" not in view
    assert not ({"prompt", "instruction", "idempotency_key", "owner_principal"}
                & set(automatic))


def test_continuation_view_preserves_old_payload_without_v3_and_fails_closed_on_invalid_latest():
    empty_task = {
        "task_id": "task_" + "a" * 32,
        "continuation_permission": None,
        "continuation_budget": [],
    }
    unchanged = ResearchContinuationMixin._continuation_view(empty_task, {})
    assert set(unchanged) == {
        "schema_version", "task_id", "permission", "available_profile",
        "request_state", "can_start", "blocked_reason",
    }
    assert "automatic_request" not in unchanged

    valid, _ = _settled_v3_ledger_entry(job_suffix="c")
    invalid_latest = {**valid, "schema_version": "tampered-ledger-version"}
    task = {**empty_task, "continuation_budget": [valid, invalid_latest]}
    with pytest.raises(ValueError, match="continuation ledger entry v3 is invalid"):
        ResearchContinuationMixin._continuation_view(task, {})


def test_legacy_permission_view_adds_v3_read_projection_without_legacy_usage_accounting():
    entry, _ = _settled_v3_ledger_entry()
    permission = {
        "schema_version": PERMISSION_SCHEMA_VERSION,
        "idempotency_key": "legacy-request-confirmation",
        "request_sha256": "a" * 64,
        "grant_version": 1,
        "max_turns": 1,
        "revoked_at": None,
        "expires_at": "2999-01-01T00:00:00+00:00",
        "execution_profile": profile_binding(),
        "request_limits": request_limits(),
    }
    task = {
        "task_id": entry["reservation"]["task_id"],
        "status": "running",
        "continuation_permission": permission,
        "continuation_budget": [entry],
    }
    view = ResearchContinuationMixin._continuation_view(task, {"status": "active"})
    assert view["request_state"]["requests_reserved"] == 0
    assert view["request_state"]["request_identity"] is None
    assert view["automatic_request"]["reservation_id"] == entry["reservation_id"]


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
