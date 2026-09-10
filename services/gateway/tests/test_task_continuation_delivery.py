import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main
from app.task_continuation import TaskContinuationDelivery


def fixture(monkeypatch):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    reservation = dict(schema_version='task-continuation-reservation.v1', reservation_id='continuation_' + 'a'*32,
        task_id='task_' + 'b'*32, owner='alice', workspace_id='workspace-a', token_limit=3000000,
        expires_at='2026-09-10T12:00:00+00:00')
    receipt = dict(reservation_id=reservation['reservation_id'], instruction='Exact original task only.', status='reserved')
    intent = dict(status='intent', task_id=reservation['task_id'], conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a', may_dispatch=True, reservation=reservation, receipt=receipt)
    writes, reads, prompts = [], [], []
    original = {'state': 'unknown'}
    settlement = {'status': 'outcome_unknown', 'reservation_id': reservation['reservation_id']}
    def backend(method, path, principal, workspace, payload=None):
        assert principal.subject == 'alice' and workspace == 'workspace-a'
        if path.endswith('/peek'):
            return intent
        writes.append((path.rsplit('/', 1)[-1], payload))
        if path.endswith('/dispatch'):
            receipt['status'] = 'outcome_unknown'
            return {'dispatch': True}
        if path.endswith('/receipt'):
            receipt['status'] = payload['status']
            return payload
        raise AssertionError(path)
    def adapter(path, params=None):
        reads.append((path, params))
        if '/continuation-receipt/' in path:
            return settlement
        if path.endswith('/prompts/reconcile'):
            expected = json.dumps({'content': receipt['instruction'], 'reservation': reservation}, sort_keys=True, separators=(',', ':'))
            assert params == {'idempotency_key': reservation['reservation_id'],
                'content_sha256': hashlib.sha256(expected.encode()).hexdigest()}
            return original
        raise AssertionError(path)
    monkeypatch.setattr(main, '_catalog_request', backend)
    monkeypatch.setattr(main, '_continuation_adapter_get', adapter)
    monkeypatch.setattr(main.product_sessions, 'get_owned', lambda *args: SimpleNamespace(session_id='session-a'))
    monkeypatch.setattr(main.product_sessions, 'idle_release_generation', lambda session: None)
    monkeypatch.setattr(main, '_runtime_recovery_payload', lambda session: {'conversation_context': []})
    monkeypatch.setattr(main, '_adapter_post', lambda path, payload, timeout: prompts.append(payload) or
        {'accepted': True, 'run_id': 'c'*32})
    return context, intent, writes, reads, prompts, original, settlement


def test_dispatch_then_lost_ack_only_reconciles_exact_original(monkeypatch):
    context, intent, writes, reads, prompts, original, _ = fixture(monkeypatch)
    def lost(path, payload, timeout):
        prompts.append(payload)
        original.update(state='accepted', run_id='c'*32)
        raise HTTPException(504, 'synthetic lost reply')
    monkeypatch.setattr(main, '_adapter_post', lost)
    main._consume_admitted_task_continuation(context)
    assert intent['receipt']['status'] == 'outcome_unknown'
    # A restarted consumer uses only durable Backend state and original receipt.
    main._consume_admitted_task_continuation(context)
    assert len(prompts) == 1
    assert [kind for kind, _ in writes] == ['dispatch', 'receipt']
    assert writes[-1][1]['run_id'] == 'c'*32


def test_unknown_never_resubmits_or_refunds(monkeypatch):
    context, intent, writes, _, prompts, _, _ = fixture(monkeypatch)
    intent['receipt']['status'] = 'outcome_unknown'
    main._consume_admitted_task_continuation(context)
    assert writes == prompts == []


def test_accepted_settlement_projects_charge_and_failure_atomically(monkeypatch):
    context, intent, writes, _, prompts, _, settlement = fixture(monkeypatch)
    settlement.update(status='settled', run_id='c'*32, charged_tokens=1056768,
        settlement_sha256='d'*64, outcome='needs_attention')
    main._consume_admitted_task_continuation(context)
    assert prompts == []
    assert writes[-1] == ('receipt', dict(reservation_id=intent['reservation']['reservation_id'],
        status='settled', charged_tokens=1056768, settlement_sha256='d'*64, outcome='needs_attention'))


@pytest.mark.parametrize('status', [409, 422, 503, 504])
def test_only_definite_admission_conflict_releases_dispatch_attempt(monkeypatch, status):
    context, _, writes, _, prompts, _, _ = fixture(monkeypatch)
    def rejected(*args, **kwargs):
        raise HTTPException(status, 'synthetic')
    monkeypatch.setattr(main, '_adapter_post', rejected)
    main._consume_admitted_task_continuation(context)
    assert [kind for kind, _ in writes] == (['dispatch', 'receipt'] if status == 409 else ['dispatch'])
    if status == 409:
        assert writes[-1][1]['status'] == 'rejected'


def test_revoked_intent_can_reconcile_but_not_dispatch(monkeypatch):
    context, intent, writes, reads, prompts, _, _ = fixture(monkeypatch)
    intent['may_dispatch'] = False
    main._consume_admitted_task_continuation(context)
    assert len(reads) == 2
    assert writes == prompts == []


def test_identity_mismatch_stops_before_runtime_access(monkeypatch):
    context, intent, writes, reads, prompts, _, _ = fixture(monkeypatch)
    intent['conversation_id'] = 'conversation-other'
    with pytest.raises(ValueError, match='identity'):
        main._consume_admitted_task_continuation(context)
    assert writes == reads == prompts == []


def test_registered_conversation_scan_is_bounded_fair_and_flagged(tmp_path, monkeypatch):
    called = []
    for i in range(10):
        context = dict(owner='alice', workspace_id='workspace-a', conversation_id=f'conversation-{i}',
            session_id=f'session-{i}', trace_id=f'trace-{i}')
        (tmp_path / f'{i:02}.lifecycle.json').write_text(json.dumps({'context': context}))
    delivery = TaskContinuationDelivery(tmp_path, called.append)
    monkeypatch.delenv('BYQ_F6_EXECUTOR_ENABLED', raising=False)
    delivery.tick()
    assert called == []
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
    delivery.tick()
    assert len(called) == 8
    delivery.tick()
    assert len(called) == 10
    assert len({c['conversation_id'] for c in called}) == 10


def test_background_completion_does_not_release_a_live_browser_stream():
    registry = main.ProductSessionRegistry()
    session = main.ProductSession(conversation_id='conversation-a', session_id='session-a',
        trace_id='trace-a', principal=main.Principal(subject='alice'))
    registry.add(session)
    registry.begin_stream(session)
    assert registry.idle_release_generation(session) is None
    assert session.public_streams == 1
    registry.end_stream(session)
    generation = registry.idle_release_generation(session)
    assert generation is not None and registry.claim_idle_release(session, generation)
