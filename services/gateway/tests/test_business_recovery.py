"""Interrupted task continuations stay unresolved and are never replayed."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from app import main

LOST = 'c' * 32
CARRIER = {
    'attempt_key': 'recovery_' + 'a' * 32, 'ordinal': 1, 'trigger_key': 'b' * 64,
    'interrupted_run_id': LOST, 'interrupted_generation': 'generation-dead',
    'containment_attempt': 1, 'interrupted_executor_epoch': 1,
    'snapshot_tail_sequence': 0, 'snapshot_digest': 'd' * 64,
}


def _fixture(monkeypatch, *, receipt_status='accepted', settled_status='outcome_unknown',
             settled_charge=None, reconcile_state='unknown', stale_carrier=False):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    reservation = dict(schema_version='task-continuation-reservation.v1',
        reservation_id='continuation_' + 'a' * 32, task_id='task_' + 'b' * 32, owner='alice',
        workspace_id='workspace-a', token_limit=3000000, expires_at='2030-01-01T00:00:00+00:00')
    if stale_carrier:
        reservation['recovery_attempt'] = stale_carrier if isinstance(stale_carrier, dict) else CARRIER
    receipt = dict(reservation_id=reservation['reservation_id'], instruction='Exact original task only.',
        status=receipt_status, run_id=None if receipt_status == 'reserved' else LOST)
    intent = dict(status='intent', task_id=reservation['task_id'], conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a', may_dispatch=True,
        reservation=reservation, receipt=receipt)
    writes, prompts, adapter_reads = [], [], []
    settled = {'status': settled_status, 'reservation_id': reservation['reservation_id']}
    if settled_charge is not None:
        settled['charged_tokens'] = settled_charge

    def backend(method, path, principal, workspace, payload=None):
        if path.endswith('/peek'):
            return intent
        writes.append((path.rsplit('/', 1)[-1], payload))
        if path.endswith('/dispatch'):
            return {'dispatch': True}
        if path.endswith('/receipt'):
            return payload
        raise AssertionError(path)

    def adapter(path, params=None):
        adapter_reads.append((path, params))
        if '/containment' in path:
            return {'schema_version': 'session-containment-summary.v1', 'session_id': 'session-a',
                'contained': True, 'attempts': 1,
                'latest': {'trace_id': 'trace-a', 'loss_cause': 'executor-loss', 'interrupted_run_id': LOST,
                           'interrupted_generation': 'generation-dead', 'executor_epoch': 1, 'attempt': 1}}
        if '/continuation-receipt/' in path:
            return settled
        if path.endswith('/prompts/reconcile'):
            if reconcile_state == 'accepted':
                return {'state': 'accepted', 'run_id': LOST}
            return {'state': reconcile_state}
        raise AssertionError(path)

    monkeypatch.setattr(main, '_catalog_request', backend)
    monkeypatch.setattr(main, '_continuation_adapter_get', adapter)
    monkeypatch.setattr(main.product_sessions, 'get_owned',
        lambda *args: SimpleNamespace(session_id='session-a', trace_id='trace-a', boot_id='a' * 32))
    monkeypatch.setattr(main.product_sessions, 'idle_release_generation', lambda session: None)
    monkeypatch.setattr(main.product_sessions, 'hold_continuation', lambda *args: True)
    monkeypatch.setattr(main.product_sessions, 'finish_continuation', lambda *args: None)
    monkeypatch.setattr(main, '_runtime_recovery_payload', lambda session: {'conversation_context': []})
    monkeypatch.setattr(main, '_adapter_post', lambda path, payload, timeout: prompts.append(payload) or {
        'accepted': True, 'run_id': 'e' * 32})
    return context, intent, writes, prompts, adapter_reads


def _expected_original_reconcile(intent):
    reservation = intent['reservation']
    instruction = intent['receipt']['instruction']
    content = json.dumps({'content': instruction, 'reservation': reservation}, sort_keys=True, separators=(',', ':'))
    return {
        'idempotency_key': reservation['reservation_id'],
        'content_sha256': hashlib.sha256(content.encode()).hexdigest(),
    }


@pytest.mark.parametrize('status', ['accepted', 'outcome_unknown'])
def test_unknown_original_prompt_reconcile_stays_unresolved_without_replay(monkeypatch, status):
    context, intent, writes, prompts, adapter_reads = _fixture(monkeypatch, receipt_status=status)

    main._consume_admitted_task_continuation(context)

    assert writes == []
    assert prompts == []
    reconcile_reads = [(path, params) for path, params in adapter_reads if path.endswith('/prompts/reconcile')]
    assert reconcile_reads == [(
        '/internal/runtime/sessions/session-a/prompts/reconcile', _expected_original_reconcile(intent))]
    assert not any('/containment' in path for path, _ in adapter_reads)


def test_known_continuation_charge_is_recorded_without_replaying_unknown_turn(monkeypatch):
    context, intent, writes, prompts, adapter_reads = _fixture(monkeypatch,
        receipt_status='outcome_unknown', settled_status='accepted', settled_charge=913)

    main._consume_admitted_task_continuation(context)

    assert writes == [('receipt', {
        'reservation_id': intent['reservation']['reservation_id'], 'status': 'accepted',
        'run_id': LOST, 'charged_tokens': 913,
    })]
    assert prompts == []
    assert any(path.endswith('/prompts/reconcile') for path, _ in adapter_reads)
    assert not any(path.endswith('/dispatch') for path, _ in writes)


def test_exact_original_reconcile_acceptance_is_recorded_without_another_prompt(monkeypatch):
    context, intent, writes, prompts, _ = _fixture(monkeypatch,
        receipt_status='reserved', reconcile_state='accepted')

    main._consume_admitted_task_continuation(context)

    assert writes == [('receipt', {
        'reservation_id': intent['reservation']['reservation_id'], 'status': 'accepted', 'run_id': LOST,
    })]
    assert prompts == []


@pytest.mark.parametrize('carrier', [CARRIER, {'invented': 'authority'}])
def test_stale_recovery_carrier_fails_closed_without_dispatch_or_prompt(monkeypatch, carrier):
    context, intent, writes, prompts, adapter_reads = _fixture(monkeypatch,
        receipt_status='reserved', stale_carrier=carrier)

    main._consume_admitted_task_continuation(context)

    assert writes == []
    assert prompts == []
    assert any(path.endswith('/prompts/reconcile') for path, _ in adapter_reads)


def test_normal_reserved_dispatch_uses_original_reservation_id(monkeypatch):
    context, intent, writes, prompts, _ = _fixture(monkeypatch, receipt_status='reserved')

    main._consume_admitted_task_continuation(context)

    assert [kind for kind, _ in writes] == ['dispatch', 'receipt']
    assert writes[0][1] == {'reservation_id': intent['reservation']['reservation_id']}
    assert prompts[0]['idempotency_key'] == intent['reservation']['reservation_id']
    assert 'recovery_attempt' not in prompts[0]['continuation_budget']
    assert writes[1] == ('receipt', {
        'reservation_id': intent['reservation']['reservation_id'], 'status': 'accepted', 'run_id': 'e' * 32,
    })
