"""ADR-0090: one closed background request, separate from durable business permission.

No balance, session recovery, dispatch loop, or persisted agent counter lives here.
The profile is BYQ-trusted data; clients cannot raise its limits.
"""
from __future__ import annotations
import hashlib
import json
import re

from packages.contracts.agent_execution_options import (
    SCHEMA_VERSION as AGENT_EXECUTION_OPTIONS_SCHEMA_VERSION,
    validate_agent_execution_options,
)
from packages.contracts.product_turn_request import product_turn_execution_limits

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


# ADR-0111 contract-only versions. The symbols above remain byte-for-byte
# historical readers for the old fixed profile and reservation shapes.
PROFILE_ID_V2 = 'task-ready-read.v2'
PROFILE_VERSION_V2 = 2
RESERVATION_SCHEMA_VERSION_V3 = 'task-continuation-reservation.v3'
USAGE_SCHEMA_VERSION_V2 = 'continuation-request-usage.v2'
SOURCE_FACTS_SCHEMA_VERSION_V1 = 'task-ready-source-facts.v1'
_EVENT_IDEMPOTENCY_SCHEMA_VERSION = 'task-ready-event-idempotency.v1'

_DOMAIN_TOOL_NAMES_V2 = tuple(sorted(ALLOWED_DOMAIN_TOOLS))
_HARNESS_TOOL_NAMES_V2 = tuple(sorted(ALLOWED_HARNESS_TOOLS))
_PROFILE_V2_FIELDS = frozenset({
    'profile_id', 'profile_version', 'options_schema_version', 'options_revision',
    'options', 'provider', 'model', 'upstream_base_url', 'upstream_request_target',
    'allowed_domain_tools', 'allowed_harness_tools', 'profile_sha256',
})


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def _json_copy(value: object) -> dict:
    return json.loads(json.dumps(value))


def execution_profile_v2(options: object, *, revision: int) -> dict:
    """Bind a trusted option snapshot to the closed F6 route and tool sets.

    This is structural profile identity only. It is not a continuation grant or
    proof that a matching business event is eligible for dispatch.
    """
    normalized = validate_agent_execution_options(options)
    if type(revision) is not int or revision < 0:
        raise ValueError('execution options revision is invalid')
    binding = {
        'profile_id': PROFILE_ID_V2,
        'profile_version': PROFILE_VERSION_V2,
        'options_schema_version': AGENT_EXECUTION_OPTIONS_SCHEMA_VERSION,
        'options_revision': revision,
        'options': normalized,
        'provider': ALLOWED_PROVIDER,
        'model': ALLOWED_MODEL,
        'upstream_base_url': UPSTREAM_BASE_URL,
        'upstream_request_target': UPSTREAM_REQUEST_TARGET,
        # Domain tools are read-only. Harness lifecycle calls remain required
        # for the existing F6 flow and do not add domain-action authority.
        'allowed_domain_tools': list(_DOMAIN_TOOL_NAMES_V2),
        'allowed_harness_tools': list(_HARNESS_TOOL_NAMES_V2),
    }
    return {**binding, 'profile_sha256': _canonical_sha256(binding)}


def validate_execution_profile_v2(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != _PROFILE_V2_FIELDS:
        raise ValueError('continuation execution profile v2 is invalid')
    revision = value.get('options_revision')
    options = validate_agent_execution_options(value.get('options'))
    expected = execution_profile_v2(options, revision=revision)
    if value != expected:
        raise ValueError('continuation execution profile v2 is unqualified')
    return expected


def request_limits_v2(options: object) -> dict:
    """Map the trusted option snapshot to nullable per-request execution limits."""
    return product_turn_execution_limits(options)


def validate_request_limits_v2(value: object, profile: object) -> dict:
    validated_profile = validate_execution_profile_v2(profile)
    expected = request_limits_v2(validated_profile['options'])
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError('continuation request limits v2 are invalid')
    if any(item is not None and (type(item) is not int or item < 1) for item in value.values()):
        raise ValueError('continuation request limits v2 require positive integers or null')
    if value != expected:
        raise ValueError('continuation request limits v2 do not match the profile')
    return dict(expected)


_V3_RESERVATION_FIELDS = frozenset({
    'schema_version', 'owner_principal', 'workspace_id', 'conversation_id',
    'task_id', 'event_key', 'signal_job_id', 'signal_job_status',
    'result_artifact_id', 'result_artifact_kind', 'result_artifact_status',
    'result_artifact_content_sha256', 'source_fact_sha256', 'idempotency_key',
    'execution_profile', 'request_limits',
})
_SHA256_RE = re.compile(r'[0-9a-f]{64}')
_READY_EVENT_RE = re.compile(r'ready-v1:[0-9a-f]{64}')
_TASK_ID_RE = re.compile(r'task_[0-9a-f]{32}')
_SIGNAL_JOB_ID_RE = re.compile(r'signaljob_[0-9a-f]{32}')
_ARTIFACT_ID_RE = re.compile(r'artifact_[0-9a-f]{32}')


def _require_nonempty_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f'invalid continuation {field}')
    return value


def _source_facts_v1(value: dict) -> dict:
    """Return only canonical source/domain facts; this hash is not SQL proof."""
    return {
        'schema_version': SOURCE_FACTS_SCHEMA_VERSION_V1,
        'owner_principal': value['owner_principal'],
        'workspace_id': value['workspace_id'],
        'conversation_id': value['conversation_id'],
        'task_id': value['task_id'],
        'event_key': value['event_key'],
        'signal_job_id': value['signal_job_id'],
        'signal_job_status': value['signal_job_status'],
        'result_artifact_id': value['result_artifact_id'],
        'result_artifact_kind': value['result_artifact_kind'],
        'result_artifact_status': value['result_artifact_status'],
        'result_artifact_content_sha256': value['result_artifact_content_sha256'],
    }


def _event_idempotency_key_v1(value: dict) -> str:
    # One completed signal Job can be submitted once across option revisions,
    # root sessions, mutable event keys, or changes to its result metadata.
    identity = {
        'schema_version': _EVENT_IDEMPOTENCY_SCHEMA_VERSION,
        'owner_principal': value['owner_principal'],
        'workspace_id': value['workspace_id'],
        'conversation_id': value['conversation_id'],
        'task_id': value['task_id'],
        'signal_job_id': value['signal_job_id'],
    }
    return 'task-ready-event:' + _canonical_sha256(identity)


def continuation_reservation_v3(
    *, owner_principal: str, workspace_id: str, conversation_id: str, task_id: str,
    event_key: str, signal_job_id: str, result_artifact_id: str,
    result_artifact_content_sha256: str, options: object, options_revision: int,
) -> dict:
    """Create a pure carrier for one data-ready event; no grant or TTL is added."""
    value = {
        'schema_version': RESERVATION_SCHEMA_VERSION_V3,
        'owner_principal': owner_principal,
        'workspace_id': workspace_id,
        'conversation_id': conversation_id,
        'task_id': task_id,
        'event_key': event_key,
        'signal_job_id': signal_job_id,
        'signal_job_status': 'completed',
        'result_artifact_id': result_artifact_id,
        'result_artifact_kind': 'signal_snapshot',
        'result_artifact_status': 'validated',
        'result_artifact_content_sha256': result_artifact_content_sha256,
    }
    value['source_fact_sha256'] = _canonical_sha256(_source_facts_v1(value))
    value['idempotency_key'] = _event_idempotency_key_v1(value)
    profile = execution_profile_v2(options, revision=options_revision)
    value['execution_profile'] = profile
    value['request_limits'] = request_limits_v2(profile['options'])
    return validate_reservation_v3(value)


def validate_reservation_v3(value: object) -> dict:
    """Check exact carrier structure and digests, without asserting business truth."""
    if (not isinstance(value, dict) or set(value) != _V3_RESERVATION_FIELDS
            or value.get('schema_version') != RESERVATION_SCHEMA_VERSION_V3):
        raise ValueError('continuation reservation v3 is invalid')
    for field in ('owner_principal', 'workspace_id', 'conversation_id'):
        _require_nonempty_text(value.get(field), field)
    for field, pattern in (
        ('task_id', _TASK_ID_RE), ('signal_job_id', _SIGNAL_JOB_ID_RE),
        ('result_artifact_id', _ARTIFACT_ID_RE), ('event_key', _READY_EVENT_RE),
        ('result_artifact_content_sha256', _SHA256_RE),
        ('source_fact_sha256', _SHA256_RE),
    ):
        text_value = _require_nonempty_text(value.get(field), field)
        if pattern.fullmatch(text_value) is None:
            raise ValueError(f'invalid continuation {field}')
    if (value.get('signal_job_status') != 'completed'
            or value.get('result_artifact_kind') != 'signal_snapshot'
            or value.get('result_artifact_status') != 'validated'):
        raise ValueError('continuation source facts are not terminal and validated')
    if value['source_fact_sha256'] != _canonical_sha256(_source_facts_v1(value)):
        raise ValueError('continuation source fact digest changed')
    if value.get('idempotency_key') != _event_idempotency_key_v1(value):
        raise ValueError('continuation event idempotency key changed')
    profile = validate_execution_profile_v2(value.get('execution_profile'))
    validate_request_limits_v2(value.get('request_limits'), profile)
    return _json_copy(value)


_ADMISSION_FIELDS_V2 = frozenset({
    'provider_calls', 'provider_attempts', 'input_bytes', 'declared_output_tokens',
    'tool_payload_bytes', 'max_input_bytes', 'max_declared_output_tokens',
    'max_tool_payload_bytes', 'tool_calls', 'max_concurrent', 'elapsed_ms',
})
_ACTUAL_FIELDS_V2 = frozenset({
    'input_tokens', 'cache_read_tokens', 'output_tokens', 'provider_attempts',
    'usage_source', 'completeness',
})
_COUNT_FIELDS_V2 = ('input_tokens', 'cache_read_tokens', 'output_tokens', 'provider_attempts')
_PEAK_TOTAL_PAIRS_V2 = (
    ('max_input_bytes', 'input_bytes'),
    ('max_declared_output_tokens', 'declared_output_tokens'),
    ('max_tool_payload_bytes', 'tool_payload_bytes'),
)
_LIMIT_MEASURES_V2 = (
    ('provider_calls', 'max_provider_calls'),
    ('provider_attempts', 'max_attempts'),
    ('max_input_bytes', 'max_input_bytes'),
    ('input_bytes', 'max_total_input_bytes'),
    ('max_declared_output_tokens', 'max_output_tokens'),
    ('declared_output_tokens', 'max_total_output_tokens'),
    ('max_tool_payload_bytes', 'max_tool_payload_bytes'),
    ('tool_payload_bytes', 'max_total_tool_payload_bytes'),
    ('tool_calls', 'max_tool_calls'),
    ('max_concurrent', 'max_concurrent'),
)


def unknown_admission_usage_v2() -> dict:
    """Use null as the sole representation for an unavailable measurement."""
    return {field: None for field in sorted(_ADMISSION_FIELDS_V2)}


def unknown_actual_usage_v2() -> dict:
    return {
        'input_tokens': None, 'cache_read_tokens': None, 'output_tokens': None,
        'provider_attempts': None, 'usage_source': 'unknown', 'completeness': 'unknown',
    }


def _known_limit_overruns_v2(admission: dict, limits: dict) -> list[str]:
    overruns = []
    for measurement, limit_name in _LIMIT_MEASURES_V2:
        observed, limit = admission[measurement], limits[limit_name]
        if observed is not None and limit is not None and observed > limit:
            overruns.append(limit_name)
    elapsed, runtime_seconds = admission['elapsed_ms'], limits['max_runtime_seconds']
    if elapsed is not None and runtime_seconds is not None and elapsed > runtime_seconds * 1000:
        overruns.append('max_runtime_seconds')
    return sorted(set(overruns))


def _validate_admission_usage_v2(value: object) -> dict:
    if (not isinstance(value, dict) or set(value) != _ADMISSION_FIELDS_V2
            or any(item is not None and (type(item) is not int or item < 0) for item in value.values())):
        raise ValueError('invalid continuation admission measurements v2')
    if (value['provider_calls'] is not None and value['provider_attempts'] is not None
            and value['provider_calls'] != value['provider_attempts']):
        raise ValueError('provider calls are actual HTTP attempts, including retries and compaction')
    for peak, total in _PEAK_TOTAL_PAIRS_V2:
        if value[peak] is not None and value[total] is not None and value[peak] > value[total]:
            raise ValueError('continuation peak exceeds cumulative measurement')
    return value


def continuation_request_usage_v2(
    *, execution_profile: object, admission_usage: object, actual_usage: object,
    limit_violations: object = (),
) -> dict:
    """Build a factual v2 usage receipt; overrun and unknown facts are retained."""
    profile = validate_execution_profile_v2(execution_profile)
    limits = request_limits_v2(profile['options'])
    if (not isinstance(limit_violations, (list, tuple))
            or any(type(item) is not str for item in limit_violations)):
        raise ValueError('invalid continuation limit violations')
    admission = _validate_admission_usage_v2(admission_usage)
    observed = _known_limit_overruns_v2(admission, limits)
    receipt = {
        'schema_version': USAGE_SCHEMA_VERSION_V2,
        'execution_profile': profile,
        'request_limits': limits,
        'admission_usage': admission,
        'actual_usage': actual_usage,
        'limit_violations': sorted(set(limit_violations) | set(observed)),
    }
    return validate_request_usage_v2(receipt)


def validate_request_usage_v2(value: object) -> dict:
    fields = {
        'schema_version', 'execution_profile', 'request_limits', 'admission_usage',
        'actual_usage', 'limit_violations',
    }
    if (not isinstance(value, dict) or set(value) != fields
            or value.get('schema_version') != USAGE_SCHEMA_VERSION_V2):
        raise ValueError('invalid continuation request usage v2')
    profile = validate_execution_profile_v2(value['execution_profile'])
    limits = validate_request_limits_v2(value['request_limits'], profile)
    admission, actual = value['admission_usage'], value['actual_usage']
    admission = _validate_admission_usage_v2(admission)
    if not isinstance(actual, dict) or set(actual) != _ACTUAL_FIELDS_V2:
        raise ValueError('invalid continuation actual usage v2')
    for key in _COUNT_FIELDS_V2:
        item = actual[key]
        if item is not None and (type(item) is not int or item < 0):
            raise ValueError('invalid continuation actual usage count')
    if (not isinstance(actual['usage_source'], str)
            or actual['usage_source'] not in {'provider_response', 'unknown', 'no_provider_calls'}):
        raise ValueError('invalid continuation usage source')
    if (not isinstance(actual['completeness'], str)
            or actual['completeness'] not in {'known', 'partial', 'unknown'}):
        raise ValueError('invalid continuation usage completeness')
    counts = [actual[key] for key in _COUNT_FIELDS_V2]
    known_count = sum(item is not None for item in counts)
    if ((actual['completeness'] == 'known' and known_count != len(counts))
            or (actual['completeness'] == 'partial' and not 0 < known_count < len(counts))
            or (actual['completeness'] == 'unknown' and known_count != 0)):
        raise ValueError('continuation usage completeness does not match its counts')
    if actual['usage_source'] == 'unknown' and actual['completeness'] != 'unknown':
        raise ValueError('unknown continuation usage source cannot establish counts')
    if actual['usage_source'] == 'no_provider_calls':
        if (any(item != 0 for item in counts) or actual['completeness'] != 'known'
                or admission['provider_attempts'] != 0):
            raise ValueError('no-provider usage requires proven zero attempts and counts')
    if (actual['provider_attempts'] is not None and admission['provider_attempts'] is not None
            and actual['provider_attempts'] != admission['provider_attempts']):
        raise ValueError('continuation attempt measurement conflicts')
    violations = value['limit_violations']
    allowed_violations = set(limits) | {'provider_declared_output_exceeded'}
    if (not isinstance(violations, list)
            or any(not isinstance(item, str) or item not in allowed_violations for item in violations)
            or violations != sorted(set(violations))):
        raise ValueError('invalid observed continuation limit violations v2')
    required_overruns = _known_limit_overruns_v2(admission, limits)
    if not set(required_overruns) <= set(violations):
        raise ValueError('known continuation overrun was omitted from the receipt')
    return _json_copy(value)


def exceeded_request_limits_v2(value: object) -> list[str]:
    """Report known overruns; an empty list does not establish safe success."""
    receipt = validate_request_usage_v2(value)
    calculated = _known_limit_overruns_v2(receipt['admission_usage'], receipt['request_limits'])
    return sorted(set(receipt['limit_violations']) | set(calculated))
