"""ADR-0090: one closed background request, separate from durable business permission.

No balance, session recovery, dispatch loop, or persisted agent counter lives here.
The profile is BYQ-trusted data; clients cannot raise its limits.
"""
from __future__ import annotations
import hashlib
import json

PROFILE_ID = 'task-ready-read.v1'
PROFILE_VERSION = 1
PERMISSION_SCHEMA_VERSION = 'task-continuation-permission.v2'
RESERVATION_SCHEMA_VERSION = 'task-continuation-reservation.v2'
USAGE_SCHEMA_VERSION = 'continuation-request-usage.v1'
# ADR-0105: F6 continuation runs on OpenCode Go's OpenAI-compatible Chat route.
ALLOWED_PROVIDER = 'opencode-go-chat'
ALLOWED_MODEL = 'deepseek-v4.1-flash'
# Exact upstream target; the local proxy forwards the route request here and the
# DSH route baseURL is pinned to the proxy, so the path is never double-joined.
UPSTREAM_BASE_URL = 'https://opencode.ai/zen/go/v1'
UPSTREAM_REQUEST_TARGET = '/chat/completions'
ALLOWED_DOMAIN_TOOLS = frozenset({'byq_research_get', 'byq_backtest_task_get'})
ALLOWED_HARNESS_TOOLS = frozenset({'byq_agent_run_start', 'byq_agent_authorize', 'byq_agent_audit'})
_LIMITS = {
    'max_provider_calls': 16, 'max_attempts': 16, 'max_concurrent': 1,
    'max_input_bytes': 262144, 'max_total_input_bytes': 4194304,
    'max_output_tokens': 8192, 'max_total_output_tokens': 131072,
    'max_tool_payload_bytes': 131072, 'max_total_tool_payload_bytes': 1048576,
    'max_tool_calls': 16, 'deadline_ms': 180000,
}
_PROFILE = {'profile_id': PROFILE_ID, 'profile_version': PROFILE_VERSION,
            'provider': ALLOWED_PROVIDER, 'model': ALLOWED_MODEL, 'request_limits': _LIMITS,
            'upstream_base_url': UPSTREAM_BASE_URL, 'upstream_request_target': UPSTREAM_REQUEST_TARGET,
            'allowed_tools': sorted(ALLOWED_DOMAIN_TOOLS | ALLOWED_HARNESS_TOOLS)}
PROFILE_SHA256 = hashlib.sha256(json.dumps(_PROFILE, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def profile_binding() -> dict:
    return {'profile_id': PROFILE_ID, 'profile_version': PROFILE_VERSION, 'profile_sha256': PROFILE_SHA256}


def request_limits() -> dict:
    return dict(_LIMITS)


def validate_profile_binding(value: object) -> dict:
    if not isinstance(value, dict) or value != profile_binding() or type(value.get('profile_version')) is not int:
        raise ValueError('unqualified continuation execution profile')
    return dict(value)


def validate_limits(value: object) -> dict:
    if (not isinstance(value, dict) or value != _LIMITS
            or any(type(value.get(key)) is not int for key in _LIMITS)):
        raise ValueError('continuation request limits cannot be overridden')
    return dict(value)


_ADMISSION_FIELDS = frozenset({'provider_calls', 'provider_attempts', 'input_bytes', 'declared_output_tokens',
    'tool_payload_bytes', 'max_input_bytes', 'max_declared_output_tokens', 'max_tool_payload_bytes', 'tool_calls', 'max_concurrent', 'elapsed_ms'})
_ACTUAL_FIELDS = frozenset({'input_tokens', 'cache_read_tokens', 'output_tokens',
    'provider_attempts', 'usage_source', 'completeness'})


def unknown_actual_usage() -> dict:
    return {'input_tokens': 'unknown', 'cache_read_tokens': 'unknown', 'output_tokens': 'unknown',
            'provider_attempts': 'unknown', 'usage_source': 'unknown', 'completeness': 'unknown'}


def validate_request_usage(value: object) -> dict:
    """Validate a trusted factual receipt, including truthful overrun/unknown data.

    Recording an exceeded bound never grants another call. Terminal policy checks
    the bound separately so unsafe/unknown observations are not erased.
    """
    fields = {'schema_version', 'execution_profile', 'request_limits', 'admission_usage', 'actual_usage', 'limit_violations'}
    if not isinstance(value, dict) or set(value) != fields or value['schema_version'] != USAGE_SCHEMA_VERSION:
        raise ValueError('invalid continuation request usage')
    validate_profile_binding(value['execution_profile']); validate_limits(value['request_limits'])
    violations = value['limit_violations']
    allowed_violations = set(_LIMITS) | {'provider_declared_output_exceeded'}
    if (not isinstance(violations, list) or any(not isinstance(item, str) or item not in allowed_violations for item in violations)
            or len(set(violations)) != len(violations)):
        raise ValueError('invalid observed continuation limit violations')
    admission, actual = value['admission_usage'], value['actual_usage']
    if (not isinstance(admission, dict) or set(admission) != _ADMISSION_FIELDS
            or any(type(n) is not int or n < 0 for n in admission.values())):
        raise ValueError('invalid continuation admission measurements')
    if admission['provider_calls'] != admission['provider_attempts']:
        raise ValueError('provider calls are actual HTTP attempts, including retries and compaction')
    for peak, total in [('max_input_bytes', 'input_bytes'), ('max_declared_output_tokens', 'declared_output_tokens'), ('max_tool_payload_bytes', 'tool_payload_bytes')]:
        if admission[peak] > admission[total]:
            raise ValueError('continuation peak exceeds cumulative measurement')
    if not isinstance(actual, dict) or set(actual) != _ACTUAL_FIELDS:
        raise ValueError('invalid continuation actual usage')
    for key in ('input_tokens', 'cache_read_tokens', 'output_tokens', 'provider_attempts'):
        if actual[key] != 'unknown' and (type(actual[key]) is not int or actual[key] < 0):
            raise ValueError('invalid continuation actual usage count')
    if actual['usage_source'] not in {'provider_response', 'unknown', 'no_provider_calls'}:
        raise ValueError('invalid continuation usage source')
    if actual['completeness'] not in {'known', 'partial', 'unknown'}:
        raise ValueError('invalid continuation usage completeness')
    counts = [actual[k] for k in ('input_tokens', 'cache_read_tokens', 'output_tokens', 'provider_attempts')]
    if actual['completeness'] == 'known' and 'unknown' in counts:
        raise ValueError('unknown continuation usage cannot be complete')
    if actual['usage_source'] == 'unknown' and any(n != 'unknown' for n in counts):
        raise ValueError('continuation usage lacks a factual source')
    if actual['usage_source'] == 'no_provider_calls' and (any(n != 0 for n in counts) or actual['completeness'] != 'known' or admission['provider_attempts'] != 0):
        raise ValueError('no-provider usage requires proven zero attempts and counts')
    if actual['provider_attempts'] != 'unknown' and actual['provider_attempts'] != admission['provider_attempts']:
        raise ValueError('continuation attempt measurement conflicts')
    return json.loads(json.dumps(value))


def exceeded_request_limits(value: object) -> list[str]:
    receipt = validate_request_usage(value)
    usage = receipt['admission_usage']
    limits = {'provider_calls': 'max_provider_calls', 'max_input_bytes': 'max_input_bytes',
              'max_declared_output_tokens': 'max_output_tokens', 'max_tool_payload_bytes': 'max_tool_payload_bytes',
              'provider_attempts': 'max_attempts', 'input_bytes': 'max_total_input_bytes',
              'declared_output_tokens': 'max_total_output_tokens', 'tool_payload_bytes': 'max_total_tool_payload_bytes',
              'tool_calls': 'max_tool_calls', 'max_concurrent': 'max_concurrent', 'elapsed_ms': 'deadline_ms'}
    return sorted(set(receipt['limit_violations']) | {bound for key, bound in limits.items() if usage[key] > _LIMITS[bound]})
