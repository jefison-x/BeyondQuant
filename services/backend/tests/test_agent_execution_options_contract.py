from __future__ import annotations

import pytest

from packages.contracts.agent_execution_options import (
    NUMERIC_OPTION_FIELDS,
    SCHEMA_VERSION,
    default_agent_execution_options,
    validate_agent_execution_options,
    validate_execution_options_update,
)


def test_execution_options_defaults_and_sparse_normalization_have_no_implicit_limits():
    assert NUMERIC_OPTION_FIELDS == {
        "max_provider_calls", "max_provider_attempts", "max_tool_calls",
        "max_concurrent_provider_calls", "max_input_bytes_per_call", "max_input_bytes_total",
        "max_output_tokens_per_call", "max_output_tokens_total",
        "max_tool_payload_bytes_per_call", "max_tool_payload_bytes_total", "max_continuations",
        "max_runtime_seconds", "max_no_progress_seconds", "max_child_runtime_seconds",
        "max_child_no_progress_seconds",
    }
    defaults = default_agent_execution_options()
    assert defaults["auto_continue"] is True
    assert set(defaults) == {"auto_continue", *NUMERIC_OPTION_FIELDS}
    assert all(defaults[field] is None for field in NUMERIC_OPTION_FIELDS)
    assert validate_agent_execution_options({}) == defaults
    sparse = validate_agent_execution_options({"max_provider_calls": 3, "max_output_tokens_total": 99})
    assert sparse["auto_continue"] is True
    assert sparse["max_provider_calls"] == 3
    assert sparse["max_output_tokens_total"] == 99
    assert all(sparse[field] is None for field in NUMERIC_OPTION_FIELDS - {
        "max_provider_calls", "max_output_tokens_total"})


def test_execution_options_accept_positive_integer_or_null_for_every_supported_dimension():
    positive = validate_agent_execution_options({field: 1 for field in NUMERIC_OPTION_FIELDS})
    assert all(positive[field] == 1 for field in NUMERIC_OPTION_FIELDS)
    unbounded = validate_agent_execution_options({field: None for field in NUMERIC_OPTION_FIELDS})
    assert all(unbounded[field] is None for field in NUMERIC_OPTION_FIELDS)


def test_execution_options_reject_unknown_fields_and_nonpositive_or_noninteger_limits():
    for invalid in (0, -1, True, 1.5, "1"):
        with pytest.raises(ValueError):
            validate_agent_execution_options({"max_provider_calls": invalid})
    with pytest.raises(ValueError, match="unsupported"):
        validate_agent_execution_options({"hidden_limit": 1})
    with pytest.raises(ValueError, match="boolean"):
        validate_agent_execution_options({"auto_continue": 1})


def test_execution_options_update_requires_schema_and_nonnegative_cas_revision():
    revision, options = validate_execution_options_update({
        "schema_version": SCHEMA_VERSION,
        "expected_revision": 0,
        "options": {"auto_continue": False, "max_tool_calls": 4},
    })
    assert revision == 0
    assert options["auto_continue"] is False
    assert options["max_tool_calls"] == 4
    assert options["max_provider_calls"] is None
    for payload in (
        {"schema_version": SCHEMA_VERSION, "expected_revision": True, "options": {}},
        {"schema_version": SCHEMA_VERSION, "expected_revision": -1, "options": {}},
        {"schema_version": "wrong", "expected_revision": 0, "options": {}},
        {"schema_version": SCHEMA_VERSION, "expected_revision": 0,
         "options": {"unsupported": 1}},
    ):
        with pytest.raises(ValueError):
            validate_execution_options_update(payload)
