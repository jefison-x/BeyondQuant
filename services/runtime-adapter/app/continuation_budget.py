"""ADR-0090 request carrier validation and DSH-side bounded tool guard.

Business authorization is durable in Backend. This module only validates that
closed carrier and the static execution profile for one fresh Runtime Adapter
request. The old token journal reader remains solely for read-only liability
reconciliation; it is never an admission path.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from packages.contracts.continuation_request import (
    ALLOWED_DOMAIN_TOOLS,
    ALLOWED_HARNESS_TOOLS,
    PROFILE_ID,
    RESERVATION_SCHEMA_VERSION,
    request_limits,
    validate_limits,
    validate_profile_binding,
    validate_reservation_v3,
)

# Historical v1 receipt parser compatibility only. Current request bounds are
# owned by the ADR-0090 shared profile and provider gate.
CONTINUATION_INPUT_CEILING = 1048576
CONTINUATION_OUTPUT_CEILING = 393216
CONTINUATION_MAX_OUTPUT_TOKENS = 8192

_RESERVATION_FIELDS = frozenset({
    'schema_version', 'reservation_id', 'task_id', 'owner', 'workspace_id',
    'execution_profile', 'request_limits', 'expires_at',
})
_TOOL_PREFIX = 'mcp__byq__'
_ALLOWED_TOOL_NAMES = frozenset(
    _TOOL_PREFIX + name for name in (ALLOWED_DOMAIN_TOOLS | ALLOWED_HARNESS_TOOLS)
)
_GUARD_SCHEMA = 'continuation-tool-guard.v1'
_TASK_READY_GUARD_SCHEMA = 'task-ready-tool-guard.v2'
_TASK_READY_ROW_BYTES = 128 * 1024
_TASK_READY_ROOT_RUN_ID_RE = re.compile(r'[0-9a-f]{32}')
_TASK_READY_IDEMPOTENCY_KEY_RE = re.compile(r'task-ready-event:[0-9a-f]{64}')
_TASK_READY_BLOCKED_REASONS = frozenset({
    'BYQ_CONTINUATION_TOOL_UNQUALIFIED',
    'BYQ_CONTINUATION_TOOL_LIMIT',
    'BYQ_CONTINUATION_TOOL_STORAGE_FAILED',
    'BYQ_CONTINUATION_CANCELLED',
})


def validate_reservation(value: object, *, owner: str, workspace: str) -> dict:
    """Validate the exact, Backend-issued v2 carrier; old token grants fail closed."""

    if not isinstance(value, dict) or set(value) != _RESERVATION_FIELDS:
        raise ValueError('invalid continuation reservation')
    if value['schema_version'] != RESERVATION_SCHEMA_VERSION:
        raise ValueError('invalid continuation reservation')
    if value['owner'] != owner or value['workspace_id'] != workspace:
        raise ValueError('continuation reservation ownership mismatch')
    if not isinstance(value['owner'], str) or not value['owner'].strip():
        raise ValueError('continuation owner is required')
    if not isinstance(value['workspace_id'], str) or not value['workspace_id'].strip():
        raise ValueError('continuation workspace is required')
    if not isinstance(value['reservation_id'], str) or re.fullmatch(r'continuation_[0-9a-f]{32}', value['reservation_id']) is None:
        raise ValueError('invalid continuation reservation identity')
    if not isinstance(value['task_id'], str) or re.fullmatch(r'task_[0-9a-f]{32}', value['task_id']) is None:
        raise ValueError('invalid continuation task identity')
    validate_profile_binding(value['execution_profile'])
    validate_limits(value['request_limits'])
    if not isinstance(value['expires_at'], str):
        raise ValueError('invalid continuation expiry')
    try:
        expiry = datetime.fromisoformat(value['expires_at'])
    except ValueError as exc:
        raise ValueError('invalid continuation expiry') from exc
    if expiry.tzinfo is None or not 0 < (expiry - datetime.now(timezone.utc)).total_seconds() <= 86400:
        raise ValueError('continuation reservation expired or exceeds hard deadline')
    return json.loads(json.dumps(value))


def create_guard_patch(
    source: Path, root: Path, reservation: dict, *, deadline_epoch_ms: int,
    proxy_base_url: str,
) -> tuple[Path, Path]:
    """Create private DSH config carrying the exact profile and tool journal."""

    if type(deadline_epoch_ms) is not int or deadline_epoch_ms <= int(time.time() * 1000):
        raise ValueError('continuation request deadline must be a future epoch millisecond')
    matched = re.fullmatch(r"http://([0-9.]+):([1-9][0-9]{0,4})", proxy_base_url or "")
    if matched is None or not _valid_local_proxy_host(matched[1]) or int(matched[2]) > 65535:
        raise ValueError('exact local continuation proxy address is required')
    root.mkdir(parents=True, exist_ok=True)
    journal = root / 'continuation-tool-guard.jsonl'
    patch = root / 'continuation.yml'
    config = {
        'deadlineEpochMs': deadline_epoch_ms,
        'journalPath': str(journal),
        'reservationId': reservation['reservation_id'],
        'executionProfile': reservation['execution_profile'],
        'requestLimits': reservation['request_limits'],
    }
    # All network-capable tools are removed at composition level too; the
    # public DSH pre-execute hook below remains the authoritative dispatch fence.
    # ADR-0105: the selected OpenCode Go chat route's baseURL is pinned to the
    # private continuation proxy so the request cannot bypass the budget gate.
    overlay = '\n- id: web-search-deepseek\n  disabled: true\n- id: tool-web\n  disabled: true\n'
    overlay += '- id: llm-deepseek\n  disabled: true\n'
    overlay += ('- id: llm-pi-ai\n  config:\n    providers:\n      opencode-go-chat:\n'
                '        api: openai-completions\n'
                '        apiKeyEnv: OPENCODE_API_KEY\n'
                '        baseURL: ' + json.dumps(proxy_base_url) + '\n'
                '        retryPolicy:\n          mode: normal\n          maxRetries: 0\n'
                '        models:\n          - id: deepseek-v4.1-flash\n'
                '            maxTokens: ' + str(CONTINUATION_MAX_OUTPUT_TOKENS) + '\n')
    overlay += "- insert:\n    - id: byq-continuation-budget\n      name: 'file:///opt/byq/runtime/byq-continuation-budget.js'\n      config:\n"
    overlay += ''.join(
        f'        {key}: {json.dumps(value, separators=(",", ":"))}\n'
        for key, value in config.items()
    )
    # This private invocation patch is Agent Plane state, never application
    # source or a user-provided plugin path.
    with patch.open('x', encoding='utf-8') as stream:
        base = source.read_text(encoding='utf-8')
        base, count = re.subn(
            r'(?m)^(\s*)X-BYQ-Root-Run-ID:.*$',
            lambda match: match.group(0) + '\n' + match.group(1)
                + 'X-BYQ-Continuation-Reservation: ' + json.dumps(reservation['reservation_id']),
            base,
        )
        if count != 1:
            raise ValueError('continuation requires the qualified MCP identity carrier')
        stream.write(base + overlay)
    return patch, journal


def _guard_overlay_bytes(reservation: dict, deadline_epoch_ms: int,
                         mcp_reservation_id: str, proxy_base_url: str,
                         provider_session_id: str) -> bytes:
    # Canonical JSON is a valid DSH `--patch` document. journalPath is injected by
    # the trusted runner (it owns the private session directory); the Adapter only
    # declares the tightening route pin, budget and limits. The runner validates
    # this exact shape and the local proxy address. ADR-0105: the selected
    # OpenCode Go chat route's baseURL is pinned to the private continuation proxy
    # so the outbound request can never reach the provider directly.
    matched = re.fullmatch(r"http://([0-9.]+):([1-9][0-9]{0,4})", proxy_base_url or "")
    if matched is None or not _valid_local_proxy_host(matched[1]) or int(matched[2]) > 65535:
        raise ValueError('exact local continuation proxy address is required')
    # The OpenCode Go API requires the route's x-opencode-session header. The
    # profile sets it from BYQ_PROVIDER_SESSION_ID; this overlay replaces the
    # provider config, so it must carry the same resolved value or the request is
    # rejected 400 MissingSessionID before dispatch.
    if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", provider_session_id or "") is None:
        raise ValueError('exact provider session identity is required')
    config = {
        'deadlineEpochMs': deadline_epoch_ms,
        'reservationId': mcp_reservation_id,
        'executionProfile': reservation['execution_profile'],
        'requestLimits': reservation['request_limits'],
    }
    overlay = [
        {'id': 'web-search-deepseek', 'disabled': True},
        {'id': 'tool-web', 'disabled': True},
        # ADR-0105: keep llm-deepseek ACTIVE because DSH session/new requires a
        # registered adapter for the profile's default provider, but cap its
        # output; the selected OpenCode route below is the only route the pinned
        # session model uses, and no DeepSeek credential is present.
        {'id': 'llm-deepseek', 'config': {'maxTokens': CONTINUATION_MAX_OUTPUT_TOKENS}},
        {'id': 'llm-pi-ai', 'config': {'providers': {'opencode-go-chat': {
            'api': 'openai-completions',
            'apiKeyEnv': 'OPENCODE_API_KEY',
            'baseURL': proxy_base_url,
            'retryPolicy': {'mode': 'normal', 'maxRetries': 0},
            'headers': {'x-opencode-session': provider_session_id},
            'models': [{'id': 'deepseek-v4.1-flash',
                        'maxTokens': CONTINUATION_MAX_OUTPUT_TOKENS}],
        }}}},
        {'insert': [{'id': 'byq-continuation-budget',
                     'name': 'file:///opt/byq/runtime/byq-continuation-budget.js',
                     'config': config}]},
    ]
    return json.dumps(overlay, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True).encode('utf-8')


def _valid_local_proxy_host(value: str) -> bool:
    import ipaddress
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (isinstance(address, ipaddress.IPv4Address)
            and any(address in network for network in (
                ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("10.0.0.0/8"),
                ipaddress.ip_network("172.16.0.0/12"), ipaddress.ip_network("192.168.0.0/16"))))


def create_acp_guard_overlay(
    reservation: dict, *, deadline_epoch_ms: int, root_run_id: str,
    mcp_reservation_id: str, proxy_base_url: str, provider_session_id: str,
) -> bytes:
    """Return ONLY the restricted continuation guard overlay for one ACP root.

    This is a tightening-only patch (disable web tools, cap the DeepSeek output
    and install the continuation budget guard). The Product runner validates the
    exact shape before applying it as an additional patch, so neither the model
    nor a browser can supply arbitrary composition.
    """
    if (re.fullmatch(r'[0-9a-f]{32}', root_run_id) is None
            or reservation.get('reservation_id') != mcp_reservation_id
            or re.fullmatch(r'continuation_[0-9a-f]{32}', mcp_reservation_id) is None):
        raise ValueError('ACP continuation MCP identity carrier is unproven')
    if type(deadline_epoch_ms) is not int or deadline_epoch_ms <= int(time.time() * 1000):
        raise ValueError('continuation request deadline must be a future epoch millisecond')
    validate_profile_binding(reservation['execution_profile'])
    validate_limits(reservation['request_limits'])
    return _guard_overlay_bytes(reservation, deadline_epoch_ms, mcp_reservation_id,
                                proxy_base_url, provider_session_id)


# Archived ADR-0106 ordinary profile encoder. Active ordinary Product roots use
# `create_acp_product_execution_overlay` below; this v1 encoder remains only to
# interpret old profile receipts and is not a current runtime path.
from packages.contracts.product_turn_request import (
    PRODUCT_TURN_LIMITS,
    PRODUCT_TURN_MODEL,
    PRODUCT_TURN_PROFILE_ID,
    PRODUCT_TURN_PROFILE_SHA256,
    PRODUCT_TURN_PROFILE_VERSION,
    PRODUCT_TURN_PROVIDER,
    PRODUCT_TURN_UPSTREAM_BASE_URL,
    product_turn_execution_output_cap,
    product_turn_execution_limits,
    validate_product_turn_execution_profile,
)


def create_acp_product_budget_overlay(*, proxy_base_url: str, provider_session_id: str,
                                      provider: str, model: str) -> bytes:
    """Encode the archived ADR-0106 v1 route-only Product overlay.

    Current ordinary roots must use the v2 execution-options overlay below.
    This fixed-limit encoder exists only for historical profile compatibility.
    """
    if provider != PRODUCT_TURN_PROVIDER or model != PRODUCT_TURN_MODEL:
        raise ValueError('ordinary product-turn provider/model is not qualified')
    matched = re.fullmatch(r"http://([0-9.]+):([1-9][0-9]{0,4})", proxy_base_url or "")
    if matched is None or not _valid_local_proxy_host(matched[1]) or int(matched[2]) > 65535:
        raise ValueError('exact local product-turn proxy address is required')
    if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                    provider_session_id or "") is None:
        raise ValueError('exact provider session identity is required')
    providers = {
        PRODUCT_TURN_PROVIDER: {
            'api': 'openai-completions', 'apiKeyEnv': 'OPENCODE_API_KEY',
            'baseURL': proxy_base_url,
            'retryPolicy': {'mode': 'normal', 'maxRetries': 0},
            'headers': {'x-opencode-session': provider_session_id},
            'models': [{'id': PRODUCT_TURN_MODEL,
                        'maxTokens': PRODUCT_TURN_LIMITS['max_output_tokens']}],
        },
    }
    overlay = [
        {'id': 'llm-pi-ai', 'config': {'providers': providers}},
        # ADR-0106 count-only tool guard: an explicit product-turn.v1 identity
        # (never inferred from a missing continuation reservation). The Adapter
        # injects the journal path; the guard counts every tool call and blocks
        # the seventeenth. No tool allowlist and no web-tool change.
        {'insert': [{
            'id': 'byq-continuation-budget',
            'name': 'file:///opt/byq/runtime/byq-continuation-budget.js',
            'config': {
                'guardMode': 'count-only',
                'deadlineEpochMs': int(time.time() * 1000) + PRODUCT_TURN_LIMITS['deadline_ms'],
                'executionProfile': {
                    'profile_id': PRODUCT_TURN_PROFILE_ID,
                    'profile_version': PRODUCT_TURN_PROFILE_VERSION,
                    'profile_sha256': PRODUCT_TURN_PROFILE_SHA256,
                },
                'requestLimits': dict(PRODUCT_TURN_LIMITS),
            },
        }]},
    ]
    return json.dumps(overlay, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')


def create_acp_product_execution_overlay(*, proxy_base_url: str, provider_session_id: str,
                                         provider: str, model: str,
                                         execution_profile: dict) -> bytes:
    """Pin one ordinary root to its trusted ADR-0111 option revision.

    Numeric `None` values remain absent from the DSH model config. An explicit
    per-call output ceiling is passed as maxTokens; a total-only output ceiling
    is also declared per call, and the provider gate sums those declarations.
    No deadline or request count is synthesized when the user left it unset.
    """
    if provider != PRODUCT_TURN_PROVIDER or model != PRODUCT_TURN_MODEL:
        raise ValueError('ordinary product execution provider/model is not qualified')
    matched = re.fullmatch(r"http://([0-9.]+):([1-9][0-9]{0,4})", proxy_base_url or "")
    if matched is None or not _valid_local_proxy_host(matched[1]) or int(matched[2]) > 65535:
        raise ValueError('exact local product execution proxy address is required')
    if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                    provider_session_id or "") is None:
        raise ValueError('exact provider session identity is required')
    profile = validate_product_turn_execution_profile(execution_profile)
    options = profile['options']
    output_cap = product_turn_execution_output_cap(options)
    model_config: dict[str, object] = {'id': PRODUCT_TURN_MODEL}
    if output_cap is not None:
        model_config['maxTokens'] = output_cap
    providers = {
        PRODUCT_TURN_PROVIDER: {
            'api': 'openai-completions', 'apiKeyEnv': 'OPENCODE_API_KEY',
            'baseURL': proxy_base_url,
            'retryPolicy': {'mode': 'normal', 'maxRetries': 0},
            'headers': {'x-opencode-session': provider_session_id},
            'models': [model_config],
        },
    }
    overlay = [
        {'id': 'llm-pi-ai', 'config': {'providers': providers}},
        {'insert': [{
            'id': 'byq-continuation-budget',
            'name': 'file:///opt/byq/runtime/byq-continuation-budget.js',
            'config': {
                'guardMode': 'ordinary-options',
                'executionProfile': profile,
                'requestLimits': product_turn_execution_limits(options),
            },
        }]},
    ]
    return json.dumps(overlay, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True).encode('utf-8')


def create_acp_guard_patch(
    source: Path, root: Path, reservation: dict, *, deadline_epoch_ms: int,
    root_run_id: str, mcp_reservation_id: str, proxy_base_url: str,
) -> tuple[Path, Path]:
    """Compose the existing DSH guard for one ACP process and exact MCP carrier.

    ACP mounts HTTP MCP headers at session/new rather than through a Cordis
    process row. The transport validates and sends the same reservation ID on
    that call; this constructor refuses a missing or mismatched root/carrier.
    """

    if (re.fullmatch(r'[0-9a-f]{32}', root_run_id) is None
            or reservation.get('reservation_id') != mcp_reservation_id
            or re.fullmatch(r'continuation_[0-9a-f]{32}', mcp_reservation_id) is None):
        raise ValueError('ACP continuation MCP identity carrier is unproven')
    if type(deadline_epoch_ms) is not int or deadline_epoch_ms <= int(time.time() * 1000):
        raise ValueError('continuation request deadline must be a future epoch millisecond')
    matched = re.fullmatch(r"http://([0-9.]+):([1-9][0-9]{0,4})", proxy_base_url or "")
    if matched is None or not _valid_local_proxy_host(matched[1]) or int(matched[2]) > 65535:
        raise ValueError('exact local continuation proxy address is required')
    root.mkdir(parents=True, exist_ok=True)
    journal = root / f'continuation-tool-guard-{root_run_id}.jsonl'
    patch = root / f'continuation-{root_run_id}.yml'
    config = {
        'deadlineEpochMs': deadline_epoch_ms,
        'journalPath': str(journal),
        'reservationId': mcp_reservation_id,
        'executionProfile': reservation['execution_profile'],
        'requestLimits': reservation['request_limits'],
    }
    overlay = '\n- id: web-search-deepseek\n  disabled: true\n- id: tool-web\n  disabled: true\n'
    overlay += '- id: llm-deepseek\n  disabled: true\n'
    overlay += ('- id: llm-pi-ai\n  config:\n    providers:\n      opencode-go-chat:\n'
                '        api: openai-completions\n'
                '        apiKeyEnv: OPENCODE_API_KEY\n'
                '        baseURL: ' + json.dumps(proxy_base_url) + '\n'
                '        retryPolicy:\n          mode: normal\n          maxRetries: 0\n'
                '        models:\n          - id: deepseek-v4.1-flash\n'
                '            maxTokens: ' + str(CONTINUATION_MAX_OUTPUT_TOKENS) + '\n')
    overlay += "- insert:\n    - id: byq-continuation-budget\n      name: 'file:///opt/byq/runtime/byq-continuation-budget.js'\n      config:\n"
    overlay += ''.join(f'        {key}: {json.dumps(value, separators=(",", ":"))}\n'
                       for key, value in config.items())
    with patch.open('x', encoding='utf-8') as stream:
        stream.write(source.read_text(encoding='utf-8') + overlay)
    return patch, journal


def read_request_guard(journal: Path, reservation: dict, *, terminal: bool = False) -> dict:
    """Read DSH's fsynced pre-dispatch allow/deny journal for this request."""

    if journal.stat().st_size > 128 * 1024:
        raise ValueError('continuation tool journal is oversized')
    rows = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
    expected = {
        'schema_version': _GUARD_SCHEMA,
        'reservation_id': reservation['reservation_id'],
        'execution_profile': reservation['execution_profile'],
        'request_limits': reservation['request_limits'],
        'ready': True,
    }
    if not rows or rows[0] != expected:
        raise ValueError('continuation DSH tool guard is not ready')
    max_rows = request_limits()['max_tool_calls'] + 2
    if len(rows) > max_rows:
        raise ValueError('continuation tool journal is oversized')
    calls = 0
    blocked_reason = None
    for row in rows[1:]:
        if not isinstance(row, dict) or blocked_reason is not None:
            raise ValueError('invalid continuation tool journal ordering')
        if set(row) == {'phase', 'reservation_id', 'call', 'tool_name'}:
            calls += 1
            if (row['phase'] != 'tool' or row['reservation_id'] != reservation['reservation_id']
                    or type(row['call']) is not int or row['call'] != calls
                    or row['tool_name'] not in _ALLOWED_TOOL_NAMES
                    or calls > request_limits()['max_tool_calls']):
                raise ValueError('invalid admitted continuation tool dispatch')
        elif set(row) == {'phase', 'reservation_id', 'blocked_reason', 'tool_name'}:
            if (row['phase'] != 'blocked' or row['reservation_id'] != reservation['reservation_id']
                    or row['blocked_reason'] not in {
                        'BYQ_CONTINUATION_TOOL_UNQUALIFIED',
                        'BYQ_CONTINUATION_TOOL_LIMIT',
                        'BYQ_CONTINUATION_TOOL_STORAGE_FAILED',
                        'BYQ_CONTINUATION_CANCELLED',
                        'BYQ_CONTINUATION_DEADLINE_EXCEEDED',
                    }
                    or not isinstance(row['tool_name'], str) or len(row['tool_name']) > 192):
                raise ValueError('invalid blocked continuation tool dispatch')
            blocked_reason = row['blocked_reason']
        else:
            raise ValueError('invalid continuation tool journal row')
    return {
        'reservation_id': reservation['reservation_id'],
        'tool_calls': calls,
        'blocked_reason': blocked_reason,
        'status': 'settled' if terminal else 'accepted',
    }


def _load_task_ready_guard_row(line: bytes) -> dict:
    def object_without_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate key in task-ready tool journal')
            result[key] = value
        return result

    def reject_non_finite(value):
        raise ValueError('non-finite value in task-ready tool journal')

    try:
        value = json.loads(
            line.decode('utf-8'), object_pairs_hook=object_without_duplicates,
            parse_constant=reject_non_finite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('invalid task-ready tool journal JSON') from exc
    if not isinstance(value, dict):
        raise ValueError('invalid task-ready tool journal row')
    return value


def _same_json_value(left: object, right: object) -> bool:
    """Compare JSON types as well as values (so True never equals 1)."""
    return json.dumps(left, sort_keys=True, separators=(',', ':'), ensure_ascii=True) == json.dumps(
        right, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def read_task_ready_v2_guard(
    journal: Path, reservation_v3: dict, root_run_id: str, *, terminal: bool = False,
) -> dict:
    """Stream the v2 DSH guard journal as payload-bound execution evidence.

    This checks the v3 carrier's structure/self-digests and its binding to the
    separately supplied trusted root run ID. It does not prove SQL facts,
    eligibility, authorization, completion, or business settlement. The 128 KiB
    bound applies to each JSONL row only; cumulative file size and row count are
    intentionally unbounded when the profile leaves tool calls unbounded.
    """
    reservation = validate_reservation_v3(reservation_v3)
    if (not isinstance(root_run_id, str)
            or _TASK_READY_ROOT_RUN_ID_RE.fullmatch(root_run_id) is None
            or type(terminal) is not bool):
        raise ValueError('invalid task-ready guard identity or classification')
    idempotency_key = reservation['idempotency_key']
    if _TASK_READY_IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key) is None:
        raise ValueError('invalid task-ready event idempotency identity')
    profile = reservation['execution_profile']
    profile_sha256 = profile['profile_sha256']
    options_revision = profile['options_revision']
    expected_header = {
        'schema_version': _TASK_READY_GUARD_SCHEMA,
        'root_run_id': root_run_id,
        'idempotency_key': idempotency_key,
        'source_fact_sha256': reservation['source_fact_sha256'],
        'execution_profile': profile,
        'request_limits': reservation['request_limits'],
        'ready': True,
    }
    tool_fields = {
        'phase', 'root_run_id', 'idempotency_key', 'source_fact_sha256',
        'profile_sha256', 'options_revision', 'call', 'tool_name',
    }
    blocked_fields = {
        'phase', 'root_run_id', 'idempotency_key', 'source_fact_sha256',
        'profile_sha256', 'options_revision', 'blocked_reason', 'tool_name',
    }
    identity = {
        'root_run_id': root_run_id,
        'idempotency_key': idempotency_key,
        'source_fact_sha256': reservation['source_fact_sha256'],
        'profile_sha256': profile_sha256,
        'options_revision': options_revision,
    }
    calls = 0
    blocked_reason = None
    header_seen = False
    with journal.open('rb') as stream:
        while True:
            line = stream.readline(_TASK_READY_ROW_BYTES + 1)
            if not line:
                break
            if len(line) > _TASK_READY_ROW_BYTES or not line.endswith(b'\n'):
                raise ValueError('task-ready tool journal row is oversized or incomplete')
            row = _load_task_ready_guard_row(line[:-1])
            if not header_seen:
                if (set(row) != set(expected_header)
                        or type(row.get('ready')) is not bool
                        or not _same_json_value(row, expected_header)):
                    raise ValueError('task-ready DSH tool guard is not ready or bound')
                header_seen = True
                continue
            if blocked_reason is not None:
                raise ValueError('task-ready tool journal has rows after a terminal block')
            if set(row) == tool_fields:
                calls += 1
                if (row.get('phase') != 'tool'
                        or any(not _same_json_value(row.get(key), value)
                               for key, value in identity.items())
                        or type(row.get('call')) is not int or row['call'] != calls
                        or not isinstance(row.get('tool_name'), str)
                        or row['tool_name'] not in _ALLOWED_TOOL_NAMES
                        or (reservation['request_limits']['max_tool_calls'] is not None
                            and calls > reservation['request_limits']['max_tool_calls'])):
                    raise ValueError('invalid admitted task-ready tool dispatch')
            elif set(row) == blocked_fields:
                if (row.get('phase') != 'blocked'
                        or any(not _same_json_value(row.get(key), value)
                               for key, value in identity.items())
                        or not isinstance(row.get('blocked_reason'), str)
                        or row['blocked_reason'] not in _TASK_READY_BLOCKED_REASONS
                        or not isinstance(row.get('tool_name'), str)
                        or len(row['tool_name']) > 192):
                    raise ValueError('invalid blocked task-ready tool dispatch')
                blocked_reason = row['blocked_reason']
            else:
                raise ValueError('invalid task-ready tool journal row')
    if not header_seen:
        raise ValueError('task-ready DSH tool guard is not ready')
    return {
        'root_run_id': root_run_id,
        'idempotency_key': idempotency_key,
        'source_fact_sha256': reservation['source_fact_sha256'],
        'profile_sha256': profile_sha256,
        'options_revision': options_revision,
        'tool_calls': calls,
        'blocked_reason': blocked_reason,
        'observed_status': 'terminal_observed' if terminal else 'nonterminal_observed',
    }


def read_guard(journal: Path, reservation: dict, *, terminal: bool = False) -> dict:
    """Read a historical v1 token journal for liability reconciliation only.

    Active Runtime Adapter admission never calls this function; v1 carriers are
    rejected by ``validate_reservation``. Retaining the parser lets an operator
    inspect already-written facts without reopening or charging that allowance.
    """

    if reservation.get('schema_version') != 'task-continuation-reservation.v1':
        raise ValueError('historical guard reader only accepts the v1 receipt shape')
    if journal.stat().st_size > 128 * 1024:
        raise ValueError('continuation budget journal is oversized')
    rows = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
    expected = {'schema_version': 'continuation-budget-guard.v1',
        'reservation_id': reservation['reservation_id'], 'token_limit': reservation['token_limit'], 'ready': True}
    if not rows or rows[0] != expected or len(rows) > 258:
        raise ValueError('historical continuation budget guard is not ready')
    blocked = None
    if set(rows[-1]) == {'blocked_reason', 'blocked_purpose'}:
        if rows[-1]['blocked_purpose'] not in {'model', 'compaction'}:
            raise ValueError('invalid historical continuation budget purpose')
        blocked = rows.pop()['blocked_reason']
        if blocked not in {'BYQ_CONTINUATION_BUDGET_CLOSED', 'BYQ_CONTINUATION_ROUTE_UNQUALIFIED',
                'BYQ_CONTINUATION_BUDGET_EXHAUSTED', 'BYQ_CONTINUATION_BUDGET_STORAGE_FAILED'}:
            raise ValueError('invalid historical continuation budget blocker')
    charged = 0
    for index, row in enumerate(rows[1:], 1):
        if (set(row) != {'reservation_id', 'call', 'reserved_tokens', 'charged_ceiling'}
                or row['reservation_id'] != reservation['reservation_id'] or type(row['call']) is not int
                or row['call'] != index or type(row['reserved_tokens']) is not int
                or not CONTINUATION_INPUT_CEILING + 1 <= row['reserved_tokens']
                    <= CONTINUATION_INPUT_CEILING + CONTINUATION_OUTPUT_CEILING):
            raise ValueError('invalid historical continuation budget charge')
        charged += row['reserved_tokens']
        if type(row['charged_ceiling']) is not int or row['charged_ceiling'] != charged or charged > reservation['token_limit']:
            raise ValueError('historical continuation budget conservation failed')
    receipt = {'reservation_id': reservation['reservation_id'], 'charged_tokens': charged,
        'call_count': len(rows) - 1, 'status': 'settled' if terminal else 'accepted', 'blocked_reason': blocked}
    receipt['settlement_sha256'] = hashlib.sha256(json.dumps(
        receipt, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return receipt
