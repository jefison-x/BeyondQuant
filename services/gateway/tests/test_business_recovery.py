"""ADR-0084 recovery folded into the existing continuation consumer.

These tests drive the real Gateway ``_consume_admitted_task_continuation``
orchestrator across the existing task-continuation seam (peek/claim/dispatch/
receipt) and the existing Adapter containment + prompt routes. The Adapter's
fenced containment is the authoritative loss; the Backend re-derives the policy
and mints the closed carrier; the accepted target receipt is written back to the
Backend. Paused/blocked recovery is never resubmitted.
"""
import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main

LOST = 'c' * 32
CARRIER = {
    'attempt_key': 'recovery_' + 'a' * 32, 'ordinal': 1, 'trigger_key': 'b' * 64,
    'interrupted_run_id': LOST, 'interrupted_generation': 'generation-dead',
    'containment_attempt': 1, 'interrupted_executor_epoch': 1,
    'snapshot_tail_sequence': 0, 'snapshot_digest': 'd' * 64,
}


def _fixture(monkeypatch, *, contained=True, trace_id='trace-a', dispatch=None, prompt=None):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    reservation = dict(schema_version='task-continuation-reservation.v1',
        reservation_id='continuation_' + 'a' * 32, task_id='task_' + 'b' * 32, owner='alice',
        workspace_id='workspace-a', token_limit=3000000, expires_at='2030-01-01T00:00:00+00:00')
    receipt = dict(reservation_id=reservation['reservation_id'], instruction='Exact original task only.',
        status='accepted', run_id=LOST)
    intent = dict(status='intent', task_id=reservation['task_id'], conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a', may_dispatch=True,
        reservation=reservation, receipt=receipt)
    writes, prompts = [], []
    containment = {'schema_version': 'session-containment-summary.v1', 'session_id': 'session-a',
        'contained': True, 'attempts': 1,
        'latest': {'trace_id': trace_id, 'loss_cause': 'executor-loss', 'interrupted_run_id': LOST,
                   'interrupted_generation': 'generation-dead', 'executor_epoch': 1, 'attempt': 1},
        'recovery_anchor': {'snapshot_tail_sequence': 0, 'snapshot_digest': 'd' * 64, 'idle': True}}
    if not contained:
        containment = {'schema_version': 'session-containment-summary.v1', 'session_id': 'session-a',
                       'contained': False, 'latest': None, 'recovery_anchor': None}

    def backend(method, path, principal, workspace, payload=None):
        if path.endswith('/peek'):
            return intent
        writes.append((path.rsplit('/', 1)[-1], payload))
        if path.endswith('/dispatch'):
            if dispatch is not None:
                return dispatch(payload)
            return {'dispatch': True, 'recovery_attempt': CARRIER}
        if path.endswith('/receipt'):
            return payload
        raise AssertionError(path)

    def adapter(path, params=None):
        if '/containment' in path:
            return containment
        if '/continuation-receipt/' in path:
            return {'status': 'outcome_unknown', 'reservation_id': reservation['reservation_id']}
        if path.endswith('/prompts/reconcile'):
            return {'state': 'unknown'}
        raise AssertionError(path)

    monkeypatch.setattr(main, '_catalog_request', backend)
    monkeypatch.setattr(main, '_continuation_adapter_get', adapter)
    monkeypatch.setattr(main.product_sessions, 'get_owned',
        lambda *args: SimpleNamespace(session_id='session-a', trace_id='trace-a'))
    monkeypatch.setattr(main.product_sessions, 'idle_release_generation', lambda session: None)
    monkeypatch.setattr(main.product_sessions, 'hold_continuation', lambda *args: True)
    monkeypatch.setattr(main.product_sessions, 'finish_continuation', lambda *args: None)
    monkeypatch.setattr(main, '_runtime_recovery_payload', lambda session: {'conversation_context': []})
    monkeypatch.setattr(main, '_adapter_post', lambda path, payload, timeout: prompts.append(payload) or (
        prompt(payload) if prompt is not None else {
            'accepted': True, 'run_id': 'e' * 32,
            'recovery': {'attempt_key': CARRIER['attempt_key'], 'target_executor_epoch': 2,
                         'target_generation': 'generation-target'}}))
    return context, intent, writes, prompts


def test_lost_accepted_run_recovers_and_writes_back_the_target(monkeypatch):
    context, intent, writes, prompts = _fixture(monkeypatch)
    main._consume_admitted_task_continuation(context)
    assert [kind for kind, _ in writes] == ['dispatch', 'receipt']
    dispatch_payload = writes[0][1]
    assert dispatch_payload['reservation_id'] == intent['reservation']['reservation_id']
    assert dispatch_payload['recovery'] == {
        'interrupted_run_id': LOST, 'interrupted_generation': 'generation-dead',
        'containment_attempt': 1, 'interrupted_executor_epoch': 1,
        'snapshot_tail_sequence': 0, 'snapshot_digest': 'd' * 64}
    # The Adapter is dispatched with the Backend-minted attempt key and the
    # closed carrier; it is never the reservation id (which dedups the lost run).
    assert len(prompts) == 1
    assert prompts[0]['idempotency_key'] == CARRIER['attempt_key']
    assert prompts[0]['continuation_budget']['recovery_attempt'] == CARRIER
    # The accepted target epoch/generation are written back to the Backend.
    assert writes[1] == ('receipt', {
        'reservation_id': intent['reservation']['reservation_id'], 'status': 'accepted',
        'run_id': 'e' * 32, 'attempt_key': CARRIER['attempt_key'],
        'target_executor_epoch': 2, 'target_generation': 'generation-target'})


def test_no_containment_loss_means_no_recovery(monkeypatch):
    context, intent, writes, prompts = _fixture(monkeypatch, contained=False)
    main._consume_admitted_task_continuation(context)
    assert writes == [] and prompts == []


def test_trace_mismatch_never_recovers(monkeypatch):
    context, intent, writes, prompts = _fixture(monkeypatch, trace_id='trace-other')
    main._consume_admitted_task_continuation(context)
    assert writes == [] and prompts == []


@pytest.mark.parametrize('status,reason', [('paused', 'unknown_attempt_charge'),
                                           ('blocked', 'out_of_envelope'),
                                           ('blocked', 'lost_run_not_authoritative')])
def test_paused_or_blocked_recovery_never_resubmits(monkeypatch, status, reason):
    context, intent, writes, prompts = _fixture(monkeypatch,
        dispatch=lambda payload: {'dispatch': False, 'recovery': {'status': status, 'reason': reason}})
    main._consume_admitted_task_continuation(context)
    assert [kind for kind, _ in writes] == ['dispatch']
    assert prompts == []


def test_adapter_rejects_recovery_with_a_closed_conflict(monkeypatch):
    context, intent, writes, prompts = _fixture(monkeypatch)
    def rejected(path, payload, timeout):
        prompts.append(payload)
        raise HTTPException(409, 'recovery admission rejected')
    monkeypatch.setattr(main, '_adapter_post', rejected)
    main._consume_admitted_task_continuation(context)
    assert [kind for kind, _ in writes] == ['dispatch', 'receipt']
    assert writes[-1][1]['status'] == 'rejected'
    assert writes[-1][1]['attempt_key'] == CARRIER['attempt_key']


def test_normal_reserved_dispatch_is_unchanged(monkeypatch):
    context, intent, writes, prompts = _fixture(monkeypatch,
        dispatch=lambda payload: {'dispatch': True})
    intent['receipt'] = {**intent['receipt'], 'status': 'reserved', 'run_id': None}
    main._consume_admitted_task_continuation(context)
    assert [kind for kind, _ in writes] == ['dispatch', 'receipt']
    assert prompts[0]['idempotency_key'] == intent['reservation']['reservation_id']
    assert 'recovery_attempt' not in prompts[0]['continuation_budget']
