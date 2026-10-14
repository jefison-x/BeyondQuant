"""ADR-0106: ordinary ACP Product provider request budget (independent closed profile).

Separate from the ADR-0105 background-continuation profile (`task-ready-read.v1`).
The provider proxy enforces only the model HTTP budget; the tool-call count is a
separate minimal proof and is not proven here.
"""
from __future__ import annotations

import hashlib
import json

from packages.contracts.agent_execution_options import (
    SCHEMA_VERSION as EXECUTION_OPTIONS_SCHEMA_VERSION,
    validate_agent_execution_options,
)

PRODUCT_TURN_PROFILE_ID = 'product-turn.v1'
PRODUCT_TURN_PROFILE_VERSION = 1

# The exact closed provider/model/route binding accepted in ADR-0106. The
# profile hash covers this binding AND the limits, so the ordinary budget cannot
# be applied to a different provider/model/route.
PRODUCT_TURN_PROVIDER = 'opencode-go-chat'
PRODUCT_TURN_MODEL = 'deepseek-v4.1-flash'
PRODUCT_TURN_UPSTREAM_BASE_URL = 'https://opencode.ai/zen/go/v1'
PRODUCT_TURN_UPSTREAM_REQUEST_TARGET = '/chat/completions'

# Normative values accepted in ADR-0106 (2026-10-07).
PRODUCT_TURN_LIMITS = {
    'max_provider_calls': 16, 'max_attempts': 16, 'max_concurrent': 1,
    'max_input_bytes': 262144, 'max_total_input_bytes': 4194304,
    'max_output_tokens': 8192, 'max_total_output_tokens': 131072,
    'max_tool_payload_bytes': 131072, 'max_total_tool_payload_bytes': 1048576,
    'max_tool_calls': 16, 'deadline_ms': 180000,
}

_PRODUCT_TURN_PROFILE = {
    'profile_id': PRODUCT_TURN_PROFILE_ID,
    'profile_version': PRODUCT_TURN_PROFILE_VERSION,
    'provider': PRODUCT_TURN_PROVIDER,
    'model': PRODUCT_TURN_MODEL,
    'upstream_base_url': PRODUCT_TURN_UPSTREAM_BASE_URL,
    'upstream_request_target': PRODUCT_TURN_UPSTREAM_REQUEST_TARGET,
    'request_limits': PRODUCT_TURN_LIMITS,
}
PRODUCT_TURN_PROFILE_SHA256 = hashlib.sha256(
    json.dumps(_PRODUCT_TURN_PROFILE, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def product_turn_limits() -> dict:
    return dict(PRODUCT_TURN_LIMITS)


def product_turn_profile() -> dict:
    """The exact ordinary Product execution binding (recorded in the gate journal)."""
    return {'profile_id': PRODUCT_TURN_PROFILE_ID,
            'profile_version': PRODUCT_TURN_PROFILE_VERSION,
            'profile_sha256': PRODUCT_TURN_PROFILE_SHA256,
            'provider': PRODUCT_TURN_PROVIDER,
            'model': PRODUCT_TURN_MODEL,
            'upstream_base_url': PRODUCT_TURN_UPSTREAM_BASE_URL,
            'upstream_request_target': PRODUCT_TURN_UPSTREAM_REQUEST_TARGET}


def validate_product_turn_profile(value: object) -> dict:
    if not isinstance(value, dict) or value != product_turn_profile() \
            or type(value.get('profile_version')) is not int:
        raise ValueError('unqualified ordinary product-turn execution profile')
    return dict(value)


def validate_product_turn_limits(value: object) -> dict:
    if (not isinstance(value, dict) or value != PRODUCT_TURN_LIMITS
            or any(type(value.get(key)) is not int for key in PRODUCT_TURN_LIMITS)):
        raise ValueError('ordinary product-turn request limits cannot be overridden')
    return dict(value)


# ADR-0111 ordinary executions bind the trusted per-conversation option
# snapshot and its revision into a new profile identity. The v1 symbols above
# remain only for interpreting archived ADR-0106 receipts; new ordinary roots
# must use the v2 helpers below.
PRODUCT_EXECUTION_PROFILE_ID = 'product-turn.v2'
PRODUCT_EXECUTION_PROFILE_VERSION = 2
# The ordinary ACP profile is bound to this exact checked-in Product profile.
# F6/Judgment keep their existing fixed profile. Pinned DSH web search applies
# 4096 output tokens and five native-search uses per provider request; removing
# those values would restore the same plugin defaults, so user-configurable
# unbounded native-search limits are NOT_SUPPORTED by this plugin version.
PRODUCT_EXECUTION_COMPOSITION_SHA256 = (
    '10396c708651b24e3012df51e13cbb0e1eaf8178cda9547c91d682c189eacd45'
)

_OPTION_TO_LIMIT = {
    'max_provider_calls': 'max_provider_calls',
    'max_provider_attempts': 'max_attempts',
    'max_concurrent_provider_calls': 'max_concurrent',
    'max_input_bytes_per_call': 'max_input_bytes',
    'max_input_bytes_total': 'max_total_input_bytes',
    'max_output_tokens_per_call': 'max_output_tokens',
    'max_output_tokens_total': 'max_total_output_tokens',
    'max_tool_payload_bytes_per_call': 'max_tool_payload_bytes',
    'max_tool_payload_bytes_total': 'max_total_tool_payload_bytes',
    'max_tool_calls': 'max_tool_calls',
    'max_runtime_seconds': 'max_runtime_seconds',
}


def product_turn_execution_limits(options: object) -> dict:
    """Map trusted user options to ordinary provider-gate limits.

    `None` remains unbounded. auto_continue and max_continuations are bound in
    the profile but are consumed only by the later automatic-continuation
    receipt slice; they do not cap this ordinary root execution.
    """
    normalized = validate_agent_execution_options(options)
    limits = {name: None for name in (
        'max_provider_calls', 'max_attempts', 'max_concurrent',
        'max_input_bytes', 'max_total_input_bytes', 'max_output_tokens',
        'max_total_output_tokens', 'max_tool_payload_bytes',
        'max_total_tool_payload_bytes', 'max_tool_calls', 'max_runtime_seconds',
    )}
    for option_name, limit_name in _OPTION_TO_LIMIT.items():
        limits[limit_name] = normalized[option_name]
    return limits


def product_turn_execution_output_cap(options: object) -> int | None:
    """Return the tightest declared output ceiling for the provider route."""
    normalized = validate_agent_execution_options(options)
    caps = [normalized[name] for name in (
        'max_output_tokens_per_call', 'max_output_tokens_total',
    ) if normalized[name] is not None]
    return min(caps) if caps else None


def product_turn_execution_profile(options: object, *, revision: int) -> dict:
    """Return the exact ordinary v2 route + revision + option binding."""
    normalized = validate_agent_execution_options(options)
    if type(revision) is not int or revision < 0:
        raise ValueError('execution options revision is invalid')
    binding = {
        'profile_id': PRODUCT_EXECUTION_PROFILE_ID,
        'profile_version': PRODUCT_EXECUTION_PROFILE_VERSION,
        'composition_source_sha256': PRODUCT_EXECUTION_COMPOSITION_SHA256,
        'options_schema_version': EXECUTION_OPTIONS_SCHEMA_VERSION,
        'options_revision': revision,
        'options': normalized,
        'provider': PRODUCT_TURN_PROVIDER,
        'model': PRODUCT_TURN_MODEL,
        'upstream_base_url': PRODUCT_TURN_UPSTREAM_BASE_URL,
        'upstream_request_target': PRODUCT_TURN_UPSTREAM_REQUEST_TARGET,
    }
    profile_sha256 = hashlib.sha256(json.dumps(
        binding, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {**binding, 'profile_sha256': profile_sha256}


def validate_product_turn_execution_profile(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError('ordinary product execution profile is invalid')
    revision = value.get('options_revision')
    options = validate_agent_execution_options(value.get('options'))
    expected = product_turn_execution_profile(options, revision=revision)
    if value != expected:
        raise ValueError('ordinary product execution profile is unqualified')
    return expected


def validate_product_turn_execution_limits(value: object, profile: dict) -> dict:
    expected = product_turn_execution_limits(profile['options'])
    if not isinstance(value, dict) or value != expected:
        raise ValueError('ordinary product execution limits do not match the profile')
    return dict(expected)
