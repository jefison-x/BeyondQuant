"""User-owned, per-conversation execution options (Accepted ADR-0111).

These are optional BYQ execution parameters, not approval or continuation grants.
``None`` means that BYQ imposes no bound for that dimension. Counts, totals,
and root runtime apply to one Root execution; ``*_per_call`` values are per
provider call; concurrency is the peak provider-call count in that execution.
``max_continuations`` is the number of future automatic continuation events
for the same conversation/task and options revision, measured from trusted
continuation receipts. It is an optional parameter, not a token balance or
permission. Child runtime and no-progress values apply independently to each
child execution. Output-token totals are the sum of per-call declared output
token ceilings, not measured actual usage or cost.
Input-token limits are not supported because the provider proxy does not expose
a trusted input-token measurement; input-byte limits are available.
"""
from __future__ import annotations

SCHEMA_VERSION = "agent-execution-options.v1"

NUMERIC_OPTION_FIELDS = frozenset({
    "max_provider_calls",
    "max_provider_attempts",
    "max_tool_calls",
    "max_concurrent_provider_calls",
    "max_input_bytes_per_call",
    "max_input_bytes_total",
    "max_output_tokens_per_call",
    "max_output_tokens_total",
    "max_tool_payload_bytes_per_call",
    "max_tool_payload_bytes_total",
    "max_continuations",
    "max_runtime_seconds",
    "max_no_progress_seconds",
    "max_child_runtime_seconds",
    "max_child_no_progress_seconds",
})
OPTION_FIELDS = frozenset({"auto_continue", *NUMERIC_OPTION_FIELDS})


def default_agent_execution_options() -> dict[str, object]:
    """Return the unbounded defaults; no numeric ceiling is implicit."""
    return {"auto_continue": True, **{field: None for field in sorted(NUMERIC_OPTION_FIELDS)}}


def validate_agent_execution_options(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) - OPTION_FIELDS:
        raise ValueError("execution options contain unsupported fields")
    if "auto_continue" in value and type(value["auto_continue"]) is not bool:
        raise ValueError("auto_continue must be boolean")
    normalized: dict[str, object] = {
        "auto_continue": value.get("auto_continue", True),
        **{field: None for field in sorted(NUMERIC_OPTION_FIELDS)},
    }
    for field in sorted(NUMERIC_OPTION_FIELDS):
        item = value.get(field)
        if item is not None and (type(item) is not int or item < 1):
            raise ValueError(f"{field} must be a positive integer or null")
        normalized[field] = item
    return normalized


def validate_execution_options_update(value: object) -> tuple[int, dict[str, object]]:
    if (not isinstance(value, dict)
            or set(value) != {"schema_version", "expected_revision", "options"}
            or value.get("schema_version") != SCHEMA_VERSION):
        raise ValueError("invalid execution options update")
    revision = value["expected_revision"]
    if type(revision) is not int or revision < 0:
        raise ValueError("expected_revision must be a non-negative integer")
    return revision, validate_agent_execution_options(value["options"])


def execution_options_projection(value: object) -> dict[str, object]:
    """Return an independent normalized options object for a public projection."""
    return validate_agent_execution_options(value)
