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
) -> tuple[Path, Path]:
    """Create private DSH config carrying the exact profile and tool journal."""

    if type(deadline_epoch_ms) is not int or deadline_epoch_ms <= int(time.time() * 1000):
        raise ValueError('continuation request deadline must be a future epoch millisecond')
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
    overlay = '\n- id: web-search-deepseek\n  disabled: true\n- id: tool-web\n  disabled: true\n'
    overlay += '- id: llm-deepseek\n  config:\n    maxTokens: ' + str(CONTINUATION_MAX_OUTPUT_TOKENS) + '\n'
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
