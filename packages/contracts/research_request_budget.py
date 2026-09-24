"""ADR-0086: request-scoped layered budget for one named research-judgment request.

This is a framework-neutral BYQ contract, not a second agent harness. ADR-0086
replaces the historical fixed "at most 2 model calls" reading with a *request*-
scoped budget: a single named, bounded research-judgment request declares its own
provider-call, input, output, tool-payload, wall-clock and concurrency limits, and
every root/child provider call is checked against those limits BEFORE the request
is issued. It explicitly does NOT model a cross-process persistent business
balance, and it never replaces the existing durable stage-call admission ledger
(``research_judgment_stage_calls``), whose identity/idempotency/audit semantics
are unchanged.

ADR-0086 §1 requires the limits to be configured per named stage/profile from the
observed DSH path and cost evidence, NOT a single global constant. This module
therefore holds a CLOSED, BYQ-trusted registry: each judgment stage maps to an
explicit named profile carrying the full multi-dimensional limits and an evidence
note. The observed root -> child -> root path is 3 provider calls for each of the
four current judgment stages, but that value is a per-profile fact, not a global
constant for all DSH work. A budget whose ``profile_id`` is unknown, whose limits
do not match the registered profile, or whose stage has no profile fails closed;
no model or arbitrary client can raise a limit.

All limits are hard ceilings. The module is pure so the decision is host-testable
and fail-able.
"""

from __future__ import annotations

import re

SCHEMA_VERSION = "research-request-budget.v1"
PROFILE_SCHEMA_VERSION = "research-request-profile.v1"

# The same four genuine research-judgment stages ADR-0085 §6 defines. A
# deterministic stage must never open a request budget.
JUDGMENT_STAGES = frozenset({
    "strategy_draft", "backtest_analysis", "iteration_comparison", "final_selection",
})

# Closed, BYQ-trusted named profiles. Values are the observed bounded path for
# THAT stage plus the dedicated composition's hard output ceiling; the evidence
# note is mandatory so the value can never be a silent global constant. A future
# stage whose real DSH path differs MUST add its own profile (and may not reuse a
# looser one).
REQUEST_PROFILES: dict[str, dict] = {
    "strategy-draft-bounded.v1": {
        "profile_id": "strategy-draft-bounded.v1",
        "stage": "strategy_draft",
        "max_provider_calls": 3, "max_attempts": 3, "max_input_bytes": 131072,
        "max_output_tokens": 8192, "max_tool_payload_bytes": 65536,
        "max_concurrent": 1, "deadline_ms": 180000,
        "evidence": "ADR-0086 §1: the observed strategy_draft path is root tool_call "
                    "-> child closed_result -> root final_text (3 provider calls). Each "
                    "call re-sends at most the 64 KiB bounded stage projection plus the "
                    "five read-only tool definitions; output is capped at 8192 by the "
                    "dedicated composition; one in-flight call.",
    },
    "backtest-analysis-bounded.v1": {
        "profile_id": "backtest-analysis-bounded.v1",
        "stage": "backtest_analysis",
        "max_provider_calls": 3, "max_attempts": 3, "max_input_bytes": 131072,
        "max_output_tokens": 8192, "max_tool_payload_bytes": 65536,
        "max_concurrent": 1, "deadline_ms": 180000,
        "evidence": "ADR-0086 §1: the observed backtest_analysis path is root tool_call "
                    "-> child closed_result -> root final_text (3 provider calls) over the "
                    "same bounded stage projection and read-only tool set; the bounded "
                    "backtest summary is an evidence descriptor, never raw rows.",
    },
    "iteration-comparison-bounded.v1": {
        "profile_id": "iteration-comparison-bounded.v1",
        "stage": "iteration_comparison",
        "max_provider_calls": 3, "max_attempts": 3, "max_input_bytes": 131072,
        "max_output_tokens": 8192, "max_tool_payload_bytes": 65536,
        "max_concurrent": 1, "deadline_ms": 180000,
        "evidence": "ADR-0086 §1: the observed iteration_comparison path is root tool_call "
                    "-> child closed_result -> root final_text (3 provider calls) over the "
                    "same bounded stage projection and read-only tool set.",
    },
    "final-selection-bounded.v1": {
        "profile_id": "final-selection-bounded.v1",
        "stage": "final_selection",
        "max_provider_calls": 3, "max_attempts": 3, "max_input_bytes": 131072,
        "max_output_tokens": 8192, "max_tool_payload_bytes": 65536,
        "max_concurrent": 1, "deadline_ms": 180000,
        "evidence": "ADR-0086 §1: the observed final_selection path is root tool_call "
                    "-> child closed_result -> root final_text (3 provider calls) over the "
                    "same bounded stage projection and read-only tool set.",
    },
}

# Stage -> its default named profile. A stage with no registered profile fails
# closed; a caller cannot substitute another stage's profile.
STAGE_PROFILES: dict[str, str] = {
    profile["stage"]: profile_id for profile_id, profile in REQUEST_PROFILES.items()
}

_PROFILE_LIMIT_FIELDS = (
    "max_provider_calls", "max_attempts", "max_input_bytes", "max_output_tokens",
    "max_tool_payload_bytes", "max_concurrent",
)

# Closed decision reasons. Each names exactly one exceeded/invalid dimension.
REASONS = (
    "budget_invalid",
    "stage_not_a_judgment_stage",
    "unknown_profile",
    "deadline_exceeded",
    "cancelled",
    "concurrency_limit",
    "provider_call_limit",
    "attempt_limit",
    "input_bytes_limit",
    "output_tokens_limit",
    "tool_payload_limit",
)

_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

_BUDGET_FIELDS = frozenset({
    "schema_version", "request_id", "profile_id", "stage", "evidence",
    "max_provider_calls", "max_input_bytes", "max_output_tokens",
    "max_tool_payload_bytes", "max_attempts", "max_concurrent", "deadline_at_ms",
})

_USAGE_FIELDS = frozenset({
    "provider_calls", "input_bytes", "declared_max_output_tokens",
    "tool_payload_bytes", "attempts", "concurrent", "now_ms", "cancelled",
})


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def profile_for_stage(stage: object, *, profile: object = None) -> dict:
    """Resolve the closed named profile for a judgment stage or fail closed.

    ``profile`` (when supplied) must be the stage's registered profile; any other
    value is a caller override and is refused.
    """

    if not isinstance(stage, str) or stage not in JUDGMENT_STAGES:
        raise ValueError("a deterministic research stage must not open a request budget")
    registered = STAGE_PROFILES.get(stage)
    if registered is None:
        raise ValueError("research judgment stage has no registered request profile")
    if profile is not None and profile != registered:
        raise ValueError("caller may not override the stage request profile")
    return REQUEST_PROFILES[registered]


def stage_request_limits(stage: object, *, request_id: object, started_at_ms: object,
                         profile: object = None) -> dict:
    """Build the closed per-request budget for one named judgment request."""

    resolved = profile_for_stage(stage, profile=profile)
    if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
        raise ValueError("research request identity is invalid")
    if not _non_negative_int(started_at_ms):
        raise ValueError("research request start time is invalid")
    return validate_request_budget({
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "profile_id": resolved["profile_id"],
        "stage": resolved["stage"],
        "evidence": resolved["evidence"],
        "max_provider_calls": resolved["max_provider_calls"],
        "max_input_bytes": resolved["max_input_bytes"],
        "max_output_tokens": resolved["max_output_tokens"],
        "max_tool_payload_bytes": resolved["max_tool_payload_bytes"],
        "max_attempts": resolved["max_attempts"],
        "max_concurrent": resolved["max_concurrent"],
        "deadline_at_ms": started_at_ms + resolved["deadline_ms"],
    })


def validate_request_budget(value: object) -> dict:
    """Closed-schema validation. Unknown/missing keys or bad values fail closed.

    The limits MUST equal the registered named profile for ``profile_id``; a
    forged or caller-raised budget is refused even if its shape is valid.
    """

    if not isinstance(value, dict) or set(value) != _BUDGET_FIELDS:
        unknown = sorted(set(value) - _BUDGET_FIELDS) if isinstance(value, dict) else []
        missing = sorted(_BUDGET_FIELDS - set(value)) if isinstance(value, dict) else []
        raise ValueError(
            f"research request budget has invalid fields (unknown={unknown}, missing={missing})")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ValueError("research request budget schema is invalid")
    profile_id = value["profile_id"]
    if not isinstance(profile_id, str) or profile_id not in REQUEST_PROFILES:
        raise ValueError("research request budget profile is unknown")
    profile = REQUEST_PROFILES[profile_id]
    if value["stage"] != profile["stage"]:
        raise ValueError("research request budget stage does not match its profile")
    if not isinstance(value["evidence"], str) or not value["evidence"].strip():
        raise ValueError("research request budget evidence is required")
    if value["evidence"] != profile["evidence"]:
        # The audit evidence is part of the trusted profile binding; a caller may
        # not forge or restate it.
        raise ValueError("research request budget evidence does not match its profile")
    if not isinstance(value["request_id"], str) or _REQUEST_ID.fullmatch(value["request_id"]) is None:
        raise ValueError("research request budget identity is invalid")
    for field in _PROFILE_LIMIT_FIELDS:
        if not _positive_int(value[field]):
            raise ValueError(f"research request budget {field} is invalid")
        if field != "deadline_at_ms" and value[field] != profile[field]:
            raise ValueError(
                f"research request budget {field} does not match its registered profile")
    if not _positive_int(value["deadline_at_ms"]):
        raise ValueError("research request budget deadline is invalid")
    return value


def validate_request_usage(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != _USAGE_FIELDS:
        unknown = sorted(set(value) - _USAGE_FIELDS) if isinstance(value, dict) else []
        missing = sorted(_USAGE_FIELDS - set(value)) if isinstance(value, dict) else []
        raise ValueError(
            f"research request usage has invalid fields (unknown={unknown}, missing={missing})")
    for field in ("provider_calls", "input_bytes", "declared_max_output_tokens",
                  "tool_payload_bytes", "attempts", "concurrent"):
        if not _non_negative_int(value[field]):
            raise ValueError(f"research request usage {field} is invalid")
    if not _non_negative_int(value["now_ms"]):
        raise ValueError("research request usage clock is invalid")
    if not isinstance(value["cancelled"], bool):
        raise ValueError("research request usage cancellation flag is invalid")
    return value


def request_budget_decision(limits: object, usage: object) -> dict:
    """Decide whether ONE provider request may be issued.

    ``usage`` is the state INCLUDING the request being admitted. The first
    exceeded dimension wins; the result never admits on a partial match.
    """

    verified = validate_request_budget(limits)
    used = validate_request_usage(usage)
    if used["cancelled"]:
        return _blocked("cancelled")
    if used["now_ms"] >= verified["deadline_at_ms"]:
        return _blocked("deadline_exceeded")
    if used["concurrent"] > verified["max_concurrent"]:
        return _blocked("concurrency_limit")
    if used["attempts"] > verified["max_attempts"]:
        return _blocked("attempt_limit")
    if used["provider_calls"] > verified["max_provider_calls"]:
        return _blocked("provider_call_limit")
    if used["input_bytes"] > verified["max_input_bytes"]:
        return _blocked("input_bytes_limit")
    if used["declared_max_output_tokens"] > verified["max_output_tokens"]:
        return _blocked("output_tokens_limit")
    if used["tool_payload_bytes"] > verified["max_tool_payload_bytes"]:
        return _blocked("tool_payload_limit")
    return {
        "admit": True, "reason": "within_request_budget",
        "request_id": verified["request_id"], "profile_id": verified["profile_id"],
        "stage": verified["stage"],
        "remaining_provider_calls": verified["max_provider_calls"] - used["provider_calls"],
    }


def _blocked(reason: str) -> dict:
    if reason not in REASONS:
        raise ValueError("research request budget reason is unknown")
    return {"admit": False, "reason": reason}
