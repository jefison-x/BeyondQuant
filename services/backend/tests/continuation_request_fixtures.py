"""Focused fixtures for Backend continuation profile tests."""

from packages.contracts.continuation_request import (
    USAGE_SCHEMA_VERSION,
    profile_binding,
    request_limits,
)


def confirmed_request_usage(*, provider_attempts=1):
    if provider_attempts:
        admission = {
            "provider_calls": provider_attempts,
            "provider_attempts": provider_attempts,
            "input_bytes": 32,
            "declared_output_tokens": 128,
            "tool_payload_bytes": 64,
            "max_input_bytes": 32,
            "max_declared_output_tokens": 128,
            "max_tool_payload_bytes": 64,
            "tool_calls": 2,
            "max_concurrent": 1,
            "elapsed_ms": 100,
        }
        actual = {
            "input_tokens": 24,
            "cache_read_tokens": 0,
            "output_tokens": 16,
            "provider_attempts": provider_attempts,
            "usage_source": "provider_response",
            "completeness": "known",
        }
    else:
        admission = {
            "provider_calls": 0,
            "provider_attempts": 0,
            "input_bytes": 0,
            "declared_output_tokens": 0,
            "tool_payload_bytes": 0,
            "max_input_bytes": 0,
            "max_declared_output_tokens": 0,
            "max_tool_payload_bytes": 0,
            "tool_calls": 0,
            "max_concurrent": 0,
            "elapsed_ms": 0,
        }
        actual = {
            "input_tokens": 0,
            "cache_read_tokens": 0,
            "output_tokens": 0,
            "provider_attempts": 0,
            "usage_source": "no_provider_calls",
            "completeness": "known",
        }
    return {
        "schema_version": USAGE_SCHEMA_VERSION,
        "execution_profile": profile_binding(),
        "request_limits": request_limits(),
        "admission_usage": admission,
        "actual_usage": actual,
        "limit_violations": [],
    }


def legacy_reservation(*, suffix="f", status="outcome_unknown"):
    suffix_char = suffix[0]
    return {
        "reservation_id": "continuation_" + suffix_char * 32,
        "grant_kind": "data_ready",
        "grant_version": None,
        "event_key": "ready-v1:" + suffix_char * 64,
        "input_sha256": "a" * 64,
        "token_limit": 1000,
        "status": status,
        "run_id": None,
        "charged_tokens": None,
        "settlement_sha256": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "instruction": "historical continuation instruction",
        "dispatch_attempts": 1 if status == "outcome_unknown" else 0,
        "next_attempt_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2027-01-01T00:00:00+00:00",
    }
