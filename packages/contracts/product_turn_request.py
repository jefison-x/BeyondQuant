"""ADR-0106: ordinary ACP Product provider request budget (independent closed profile).

Separate from the ADR-0105 background-continuation profile (`task-ready-read.v1`).
The provider proxy enforces only the model HTTP budget; the tool-call count is a
separate minimal proof and is not proven here.
"""
from __future__ import annotations

import hashlib
import json

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
