"""Closed, trusted continuation reservation carrier and local guard receipts."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def validate_reservation(value: object, *, owner: str, workspace: str) -> dict:
    fields = {'schema_version', 'reservation_id', 'task_id', 'owner', 'workspace_id', 'token_limit', 'expires_at'}
    if not isinstance(value, dict) or set(value) != fields or value['schema_version'] != 'task-continuation-reservation.v1':
        raise ValueError('invalid continuation reservation')
    if value['owner'] != owner or value['workspace_id'] != workspace:
        raise ValueError('continuation reservation ownership mismatch')
    if not isinstance(value['reservation_id'], str) or re.fullmatch(r'continuation_[0-9a-f]{32}', value['reservation_id']) is None:
        raise ValueError('invalid continuation reservation identity')
    if not isinstance(value['task_id'], str) or re.fullmatch(r'task_[0-9a-f]{32}', value['task_id']) is None:
        raise ValueError('invalid continuation task identity')
    if type(value['token_limit']) is not int or not 1 <= value['token_limit'] <= 2**53 - 1:
        raise ValueError('invalid continuation allowance')
    if not isinstance(value['expires_at'], str):
        raise ValueError('invalid continuation expiry')
    expiry = datetime.fromisoformat(value['expires_at'])
    if expiry.tzinfo is None or not 0 < (expiry - datetime.now(timezone.utc)).total_seconds() <= 900:
        raise ValueError('continuation reservation expired or exceeds hard deadline')
    return dict(value)


def create_guard_patch(source: Path, root: Path, reservation: dict) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    journal = root / 'continuation-budget.jsonl'
    patch = root / 'continuation.yml'
    config = {'journalPath': str(journal), 'reservationId': reservation['reservation_id'],
        'tokenLimit': reservation['token_limit'],
        'expiresAt': int(datetime.fromisoformat(reservation['expires_at']).timestamp() * 1000)}
    # No route is silently switched. The caller already checked the resolved
    # provider/model. Search's direct HTTP path is absent in this composition.
    overlay = '\n- id: web-search-deepseek\n  disabled: true\n- id: tool-web\n  disabled: true\n'
    overlay += '- id: llm-deepseek\n  config:\n    maxTokens: 8192\n'
    overlay += "- insert:\n    - id: byq-continuation-budget\n      name: 'file:///opt/byq/runtime/byq-continuation-budget.js'\n      config:\n"
    overlay += ''.join(f'        {key}: {json.dumps(value)}\n' for key, value in config.items())
    # This private invocation patch is Agent Plane state, never application
    # source or a user-provided plugin path.
    with patch.open('x') as stream:
        base = source.read_text()
        # The original Product MCP entry retains its transport, immutable
        # identity and credentials. Only this owned process gains the scope.
        base, count = re.subn(r'(?m)^(\s*)X-BYQ-Root-Run-ID:.*$',
            lambda match: match.group(0) + '\n' + match.group(1)
                + 'X-BYQ-Continuation-Reservation: ' + json.dumps(reservation['reservation_id']), base)
        if count != 1:
            raise ValueError('continuation requires the qualified MCP identity carrier')
        stream.write(base + overlay)
    return patch, journal


def read_guard(journal: Path, reservation: dict, *, terminal: bool = False) -> dict:
    if journal.stat().st_size > 128 * 1024:
        raise ValueError('continuation budget journal is oversized')
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    expected = {'schema_version': 'continuation-budget-guard.v1',
        'reservation_id': reservation['reservation_id'], 'token_limit': reservation['token_limit'], 'ready': True}
    if not rows or rows[0] != expected or len(rows) > 258:
        raise ValueError('continuation budget guard is not ready')
    blocked = None
    if set(rows[-1]) == {'blocked_reason', 'blocked_purpose'}:
        if rows[-1]['blocked_purpose'] not in {'model', 'compaction'}:
            raise ValueError('invalid continuation budget purpose')
        blocked = rows.pop()['blocked_reason']
        if blocked not in {'BYQ_CONTINUATION_BUDGET_CLOSED', 'BYQ_CONTINUATION_ROUTE_UNQUALIFIED',
                'BYQ_CONTINUATION_BUDGET_EXHAUSTED', 'BYQ_CONTINUATION_BUDGET_STORAGE_FAILED'}:
            raise ValueError('invalid continuation budget blocker')
    charged = 0
    for index, row in enumerate(rows[1:], 1):
        if (set(row) != {'reservation_id', 'call', 'reserved_tokens', 'charged_ceiling'}
                or row['reservation_id'] != reservation['reservation_id'] or type(row['call']) is not int
                or row['call'] != index or type(row['reserved_tokens']) is not int
                or not 1048577 <= row['reserved_tokens'] <= 1048576 + 393216):
            raise ValueError('invalid continuation budget charge')
        charged += row['reserved_tokens']
        if type(row['charged_ceiling']) is not int or row['charged_ceiling'] != charged or charged > reservation['token_limit']:
            raise ValueError('continuation budget conservation failed')
    receipt = {'reservation_id': reservation['reservation_id'], 'charged_tokens': charged,
        'call_count': len(rows) - 1, 'status': 'settled' if terminal else 'accepted', 'blocked_reason': blocked}
    receipt['settlement_sha256'] = hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return receipt


def persist_settlement(root: Path, context: dict, receipt: dict) -> None:
    """A closed-process receipt, never an execution queue or a spend reset."""
    import os
    import tempfile
    directory = root / 'byq-continuation-receipts' / context['session_id']
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (receipt['reservation_id'] + '.json')
    value = {'schema_version': 'continuation-settlement.v1', 'context': context, 'receipt': receipt}
    data = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    envelope = json.dumps({'value': value, 'sha256': hashlib.sha256(data).hexdigest()}, sort_keys=True, separators=(',', ':')).encode()
    if path.exists():
        if path.read_bytes() != envelope:
            raise ValueError('original continuation settlement cannot change')
        return
    if sum(1 for _ in directory.glob('*.json')) >= 256:
        raise ValueError('continuation settlement retention bound reached')
    fd, name = tempfile.mkstemp(prefix='.settlement-', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(envelope)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        for target in (directory, directory.parent, root):
            descriptor = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def recovered_settlement(root: Path, session_id: str, reservation_id: str, state: dict) -> dict:
    import os
    if re.fullmatch(r'continuation_[0-9a-f]{32}', reservation_id) is None:
        raise ValueError('invalid settlement identity')
    path = root / 'byq-continuation-receipts' / session_id / (reservation_id + '.json')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        data = stream.read(4097)
    if len(data) > 4096:
        raise ValueError('settlement receipt exceeds bound')
    envelope = json.loads(data)
    if set(envelope) != {'value', 'sha256'}:
        raise ValueError('invalid settlement envelope')
    value = envelope['value']
    if hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest() != envelope['sha256']:
        raise ValueError('settlement integrity mismatch')
    if (set(value) != {'schema_version', 'context', 'receipt'} or value['schema_version'] != 'continuation-settlement.v1'
            or value['context'] != state['context'] or value['context']['session_id'] != session_id):
        raise ValueError('settlement context mismatch')
    receipt = value['receipt']
    from packages.contracts.agent_run_lifecycle import project_lifecycle_event
    original = state['prompts'].get(reservation_id)
    if (receipt.get('reservation_id') != reservation_id or receipt.get('status') != 'settled'
            or original is None or original['root_run_id'] != receipt.get('run_id')
            or not any(e['payload'].get('run_id') == receipt['run_id']
                and (projection := project_lifecycle_event(e, session_id, state['context']['trace_id']))
                and projection['outcome'] != 'active' for e in state['events'])):
        raise ValueError('settlement original terminal identity is missing')
    return receipt
