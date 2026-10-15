import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main
from packages.contracts.agent_execution_options import default_agent_execution_options
from packages.contracts.continuation_request import (
    continuation_request_usage_v2, profile_binding, request_limits,
    execution_profile_v2, request_limits_v2,
    unknown_actual_usage, unknown_actual_usage_v2, unknown_admission_usage_v2,
    USAGE_SCHEMA_VERSION,
)
from packages.contracts.continuation_request import continuation_reservation_v3
from app.task_continuation import CONTEXT_SCHEMA, TaskContinuationDelivery


def write_context(root, context):
    path = root / f"{context['session_id']}.continuation.json"
    path.write_text(json.dumps({'schema_version': CONTEXT_SCHEMA, 'context': context}))
    return path


def fixture(monkeypatch):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    reservation = dict(schema_version='task-continuation-reservation.v2', reservation_id='continuation_' + 'a'*32,
        task_id='task_' + 'b'*32, owner='alice', workspace_id='workspace-a', execution_profile=profile_binding(), request_limits=request_limits(),
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
        if '/containment' in path:
            return {'schema_version': 'session-containment-summary.v1', 'session_id': 'session-a',
                    'contained': False, 'latest': None}
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
    monkeypatch.setattr(main.product_sessions, 'get_owned',
        lambda *args: SimpleNamespace(session_id='session-a', boot_id='a' * 32))
    monkeypatch.setattr(main.product_sessions, 'idle_release_generation', lambda session: None)
    monkeypatch.setattr(main.product_sessions, 'hold_continuation', lambda *args: True)
    monkeypatch.setattr(main.product_sessions, 'finish_continuation', lambda *args: None)
    monkeypatch.setattr(main, '_runtime_conversation_payload', lambda session: {'conversation_context': []})
    monkeypatch.setattr(main, '_adapter_post', lambda path, payload, timeout: prompts.append(payload) or
        {'accepted': True, 'run_id': 'c'*32})
    return context, intent, writes, reads, prompts, original, settlement


def v3_fixture(monkeypatch, *, eligible=False, adapter_receipt=None, reconcile_state='outcome_unknown',
        signal_job_id='signaljob_' + 'c' * 32, result_artifact_id='artifact_' + 'd' * 32):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    task_id = 'task_' + 'b' * 32
    carrier_args = dict(owner_principal=context['owner'], workspace_id=context['workspace_id'],
        conversation_id=context['conversation_id'], task_id=task_id, signal_job_id=signal_job_id,
        result_artifact_id=result_artifact_id, result_artifact_content_sha256='e' * 64,
        options=default_agent_execution_options(), options_revision=7)
    placeholder = continuation_reservation_v3(**carrier_args, event_key='ready-v1:' + '0' * 64)
    digest = placeholder['idempotency_key'].split(':', 1)[1]
    carrier = continuation_reservation_v3(**carrier_args, event_key='ready-v1:' + digest)
    reservation_id = 'continuation_' + digest[:32]
    ledger_entry = {
        'schema_version': 'task-continuation-ledger-entry.v1',
        'reservation_id': reservation_id,
        'event_key': carrier['event_key'],
        'signal_job_id': signal_job_id,
        'status': 'reserved',
        'created_at': '2026-10-15T00:00:00+00:00',
        'dispatch_attempts': 0,
        'reservation': carrier,
    }
    receipt_projection = {**ledger_entry, 'idempotency_key': carrier['idempotency_key']}
    intent = {
        'status': 'intent', 'task_id': task_id,
        'conversation_id': context['conversation_id'], 'session_id': context['session_id'],
        'trace_id': context['trace_id'], 'may_dispatch': True,
        'receipt': receipt_projection, 'reservation': carrier,
        'instruction': 'Read the exact completed task snapshot and report it.',
    }
    candidate = {
        'status': 'eligible', 'reservation_schema_version': main.RESERVATION_SCHEMA_VERSION_V3,
        'task_id': task_id, 'signal_job_id': signal_job_id,
        'conversation_id': context['conversation_id'], 'session_id': context['session_id'],
        'trace_id': context['trace_id'],
    }
    state = {'peek_eligible': eligible, 'adapter_receipt': adapter_receipt or {
        'reservation_id': reservation_id, 'status': 'outcome_unknown'},
        'reconcile_state': reconcile_state,
        # `intent` is the Backend response snapshot. Keep the durable row
        # separate so receipt writes must follow the real ledger transitions.
        'backend_receipt': None if eligible else dict(ledger_entry)}
    backend_calls, writes, adapter_reads, prompts = [], [], [], []

    session = main.ProductSession(context['conversation_id'], context['session_id'], context['trace_id'],
        main.Principal(subject=context['owner']), context['workspace_id'], boot_id='a' * 32)
    registry = main.ProductSessionRegistry()
    registry.add(session)
    monkeypatch.setattr(main, 'product_sessions', registry)
    monkeypatch.setattr(main, '_require_session_runtime_authority', lambda _: 'a' * 32)
    monkeypatch.setattr(main, '_schedule_idle_release', lambda *_: None)
    monkeypatch.setattr(main, '_runtime_conversation_payload', lambda _: {'conversation_context': []})

    def backend(method, path, principal, workspace, payload=None, runtime_boot_id=None):
        backend_calls.append((path, payload, runtime_boot_id))
        if path.endswith('/peek'):
            return candidate if state['peek_eligible'] else intent
        if path.endswith('/claim'):
            assert payload == {
                'reservation_schema_version': main.RESERVATION_SCHEMA_VERSION_V3,
                'signal_job_id': signal_job_id,
            }
            state['peek_eligible'] = False
            state['backend_receipt'] = dict(ledger_entry)
            return intent
        kind = path.rsplit('/', 1)[-1]
        writes.append((kind, payload))
        if kind == 'dispatch':
            durable = state['backend_receipt']
            assert durable is not None
            assert durable['status'] == 'reserved' and durable['dispatch_attempts'] == 0
            durable.update(status='outcome_unknown', dispatch_attempts=1)
            return {'dispatch': True, 'attempt': 1}
        if kind == 'receipt':
            durable = state['backend_receipt']
            assert durable is not None
            status = payload['status']
            if status == 'accepted':
                assert durable['status'] in {'outcome_unknown', 'accepted', 'settled'}
                assert durable.get('run_id') in {None, payload['run_id']}
            elif status == 'outcome_unknown':
                assert durable['status'] in {'reserved', 'outcome_unknown'}
                if durable['status'] == 'reserved':
                    durable['dispatch_attempts'] = 1
            elif status == 'settled':
                assert durable['status'] in {'accepted', 'outcome_unknown'}
                assert durable.get('run_id') is not None
            else:
                raise AssertionError(f'unexpected v3 receipt status: {status}')
            if status == 'accepted' and durable['status'] != 'settled':
                durable.update(status='accepted', run_id=payload['run_id'])
            elif status == 'outcome_unknown':
                durable['status'] = 'outcome_unknown'
            elif status == 'settled':
                durable.update(status='settled', request_usage=payload['request_usage'],
                    settlement_sha256=payload['settlement_sha256'], outcome=payload['outcome'])
            projection = {
                'reservation_id': reservation_id,
                'idempotency_key': carrier['idempotency_key'],
                'status': durable['status'],
            }
            for field in ('run_id', 'request_usage', 'settlement_sha256', 'outcome'):
                if field in durable:
                    projection[field] = durable[field]
            return projection
        raise AssertionError(path)

    def adapter_get(path, params=None):
        adapter_reads.append((path, params))
        if path.endswith('/continuation-qualification'):
            return {'task_ready_qualified': True}
        if '/continuation-receipt/' in path:
            return state['adapter_receipt']
        if path.endswith('/prompts/reconcile'):
            expected = json.dumps({'content': intent['instruction'], 'reservation': carrier},
                sort_keys=True, separators=(',', ':'))
            assert params == {'idempotency_key': reservation_id,
                'content_sha256': hashlib.sha256(expected.encode()).hexdigest()}
            if state.get('reconcile_projection') is not None:
                return state['reconcile_projection']
            if state['reconcile_state'] == 'accepted':
                return {'schema_version': 'prompt-receipt.v1',
                    'state': 'accepted', 'run_id': 'f' * 32}
            return {'schema_version': 'prompt-receipt.v1', 'state': state['reconcile_state']}
        raise AssertionError(path)

    def adapter_post(path, *, payload=None, timeout=20.0):
        prompts.append((path, payload, timeout))
        return {'accepted': True, 'run_id': 'f' * 32}

    monkeypatch.setattr(main, '_catalog_request', backend)
    monkeypatch.setattr(main, '_continuation_adapter_get', adapter_get)
    monkeypatch.setattr(main, '_adapter_post', adapter_post)
    return context, candidate, intent, carrier, reservation_id, state, backend_calls, writes, adapter_reads, prompts, session


def v3_request_usage(carrier):
    return continuation_request_usage_v2(
        execution_profile=carrier['execution_profile'],
        admission_usage=unknown_admission_usage_v2(),
        actual_usage=unknown_actual_usage_v2(),
    )


def v3_settled_adapter_receipt(carrier, reservation_id, *, run_id='f' * 32, outcome='completed'):
    receipt = {
        'reservation_id': reservation_id,
        'idempotency_key': carrier['idempotency_key'],
        'status': 'settled',
        'run_id': run_id,
        'outcome': outcome,
        'request_usage': v3_request_usage(carrier),
    }
    receipt['settlement_sha256'] = hashlib.sha256(json.dumps(
        receipt, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return receipt


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


@pytest.mark.parametrize('status', ['reserved', 'outcome_unknown', 'accepted'])
def test_implicit_data_ready_receipt_cannot_submit_another_prompt(monkeypatch, status):
    context, intent, writes, reads, prompts, _, _ = fixture(monkeypatch)
    intent['receipt'].update(grant_kind='data_ready', status=status)
    if status == 'accepted':
        intent['receipt']['run_id'] = 'c' * 32
    # Backend supplies the dispatch decision; historical receipt facts remain
    # available for exact reconciliation without becoming a new permission.
    intent['may_dispatch'] = False
    main._consume_admitted_task_continuation(context)
    assert writes == prompts == []
    assert len(reads) == 2


def test_implicit_data_ready_receipt_keeps_exact_settlement(monkeypatch):
    context, intent, writes, _, prompts, _, settlement = fixture(monkeypatch)
    intent['receipt'].update(grant_kind='data_ready', status='outcome_unknown')
    intent['may_dispatch'] = False
    intent['reservation']['schema_version'] = 'task-continuation-reservation.v1'
    settlement.update(status='settled', run_id='c' * 32, charged_tokens=1056768,
        settlement_sha256='d' * 64, outcome='completed')
    main._consume_admitted_task_continuation(context)
    assert prompts == []
    assert writes == [
        ('receipt', {'reservation_id': intent['reservation']['reservation_id'],
            'status': 'accepted', 'run_id': 'c' * 32}),
        ('receipt', {'reservation_id': intent['reservation']['reservation_id'],
            'status': 'settled', 'charged_tokens': 1056768,
            'settlement_sha256': 'd' * 64, 'outcome': 'completed'}),
    ]


def test_unknown_never_resubmits_or_refunds(monkeypatch):
    context, intent, writes, _, prompts, _, _ = fixture(monkeypatch)
    intent['receipt']['status'] = 'outcome_unknown'
    main._consume_admitted_task_continuation(context)
    assert writes == prompts == []


def test_accepted_settlement_projects_charge_and_failure_atomically(monkeypatch):
    context, intent, writes, _, prompts, _, settlement = fixture(monkeypatch)
    intent['reservation']['schema_version'] = 'task-continuation-reservation.v1'
    settlement.update(status='settled', run_id='c'*32, charged_tokens=1056768,
        settlement_sha256='d'*64, outcome='needs_attention')
    main._consume_admitted_task_continuation(context)
    assert prompts == []
    assert writes[-1] == ('receipt', dict(reservation_id=intent['reservation']['reservation_id'],
        status='settled', charged_tokens=1056768, settlement_sha256='d'*64, outcome='needs_attention'))


@pytest.mark.parametrize('status', [409, 422, 503, 504])
def test_unclassified_error_preserves_unknown_dispatch_without_retry(monkeypatch, status):
    context, _, writes, _, prompts, _, _ = fixture(monkeypatch)
    def rejected(*args, **kwargs):
        raise HTTPException(status, 'synthetic')
    monkeypatch.setattr(main, '_adapter_post', rejected)
    main._consume_admitted_task_continuation(context)
    assert [kind for kind, _ in writes] == ['dispatch']


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


@pytest.mark.parametrize(('field', 'value'), [
    ('owner', 'mallory'),
    ('workspace_id', 'workspace-other'),
    ('task_id', 'task_' + 'c' * 32),
    ('reservation_id', 'continuation_' + 'd' * 32),
])
def test_misbound_reservation_fails_before_observer_or_runtime_io(monkeypatch, field, value):
    context, intent, writes, reads, prompts, _, _ = fixture(monkeypatch)
    intent['reservation'][field] = value
    owned_reads = []
    authority_checks = []
    monkeypatch.setattr(main.product_sessions, 'get_owned',
        lambda *args: owned_reads.append(args) or SimpleNamespace(session_id='session-a', boot_id='a' * 32))
    monkeypatch.setattr(main, '_require_session_runtime_authority',
        lambda session: authority_checks.append(session))

    with pytest.raises(ValueError, match='identity'):
        main._consume_admitted_task_continuation(context)

    assert owned_reads == []
    assert authority_checks == []
    assert writes == reads == prompts == []


def test_waiting_backend_intent_does_not_touch_runtime_or_prompt(monkeypatch):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    calls = []

    def backend(method, path, principal, workspace, payload=None):
        calls.append((method, path, principal.subject, workspace, payload))
        return {'status': 'waiting'}

    def unexpected(*args, **kwargs):
        raise AssertionError('waiting continuation must not access Runtime')

    monkeypatch.setattr(main, '_catalog_request', backend)
    monkeypatch.setattr(main, '_continuation_adapter_get', unexpected)
    monkeypatch.setattr(main, '_adapter_post', unexpected)
    monkeypatch.setattr(main.product_sessions, 'get_owned', unexpected)

    main._consume_admitted_task_continuation(context)

    assert calls == [(
        'POST', '/internal/task-continuation/conversation-a/peek', 'alice', 'workspace-a', None,
    )]


def test_unqualified_executor_blocks_before_claim_or_prompt(monkeypatch):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    task_id = 'task_' + 'b' * 32
    backend_calls = []
    adapter_reads = []
    prompts = []

    def backend(method, path, principal, workspace, payload=None):
        backend_calls.append((path, payload))
        if path.endswith('/peek'):
            return {'status': 'eligible', 'task_id': task_id}
        if path.endswith('/block'):
            return {'blocked_reason': payload['reason']}
        raise AssertionError(f'unexpected Backend call: {path}')

    monkeypatch.setattr(main, '_catalog_request', backend)
    monkeypatch.setattr(main.product_sessions, 'get_owned',
        lambda *args: SimpleNamespace(session_id='session-a', boot_id='a' * 32))
    monkeypatch.setattr(main, '_continuation_adapter_get',
        lambda path, params=None: adapter_reads.append((path, params)) or {
            'qualified': False, 'reason': 'model_or_executor_unqualified'})
    monkeypatch.setattr(main, '_adapter_post', lambda *args, **kwargs: prompts.append((args, kwargs)))

    main._consume_admitted_task_continuation(context)

    assert [path.rsplit('/', 1)[-1] for path, _ in backend_calls] == ['peek', 'block']
    assert backend_calls[-1][1] == {'reason': 'model_or_executor_unqualified'}
    assert adapter_reads == [(
        '/internal/runtime/sessions/session-a/continuation-qualification', None,
    )]
    assert prompts == []


def test_eligible_missing_runtime_uses_live_attach_only_and_never_prompts(monkeypatch):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    task_id = 'task_' + 'b' * 32
    backend_calls = []
    catalog_reads = []
    adapter_posts = []

    def backend(method, path, principal, workspace, payload=None):
        backend_calls.append((path, payload))
        assert path.endswith('/peek')
        return {'status': 'eligible', 'task_id': task_id}

    def catalog(method, path, principal, workspace, payload=None):
        catalog_reads.append((method, path, principal.subject, workspace))
        return {'conversation': {
            'conversation_id': context['conversation_id'],
            'runtime_session_id': context['session_id'],
            'trace_id': context['trace_id'],
            'status': 'active',
        }}

    def lost_attach(path, *, payload=None, timeout=20.0):
        adapter_posts.append((path, payload))
        error = HTTPException(status_code=409, detail='runtime session is not available')
        error.adapter_conflict_detail = 'BYQ runtime session was interrupted; start a new Agent session'
        raise error

    def missing_product_session(*args):
        raise HTTPException(status_code=404, detail='product session missing from Gateway registry')

    monkeypatch.setattr(main, 'product_sessions', main.ProductSessionRegistry())
    monkeypatch.setattr(main.product_sessions, 'get_owned', missing_product_session)
    monkeypatch.setattr(main, '_catalog_request', lambda method, path, principal, workspace, payload=None:
        backend(method, path, principal, workspace, payload) if '/task-continuation/' in path else
        catalog(method, path, principal, workspace, payload))
    monkeypatch.setattr(main, 'trace_store', SimpleNamespace(read=lambda *_: []))
    monkeypatch.setattr(main, '_adapter_post', lost_attach)
    monkeypatch.setattr(main, '_adapter_get',
        lambda *args, **kwargs: (_ for _ in ()).throw(HTTPException(status_code=404, detail='no binding')))
    monkeypatch.setattr(main, '_runtime_root_rows', lambda _session: [{'root_run_id': 'a' * 32}])

    with pytest.raises(main.ProductError) as error:
        main._consume_admitted_task_continuation(context)

    assert error.value.code == 'agent_session_interrupted'
    assert backend_calls == [('/internal/task-continuation/conversation-a/peek', None)]
    assert catalog_reads == [(
        'GET', '/v1/product/conversations/conversation-a', 'alice', 'workspace-a',
    )]
    assert adapter_posts == [('/internal/runtime/sessions', {
        'session_id': 'session-a', 'trace_id': 'trace-a', 'workspace_id': 'workspace-a',
        'owner_principal': 'alice', 'initial_sequence': 0, 'attach_live_only': True,
    })]


def test_registered_conversation_scan_is_bounded_fair_and_flagged(tmp_path, monkeypatch):
    called = []
    for i in range(10):
        context = dict(owner='alice', workspace_id='workspace-a', conversation_id=f'conversation-{i}',
            session_id=f'session-{i}', trace_id=f'trace-{i}')
        write_context(tmp_path, context)
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


def test_default_consumer_runs_without_f6_while_legacy_consumer_stays_gated(tmp_path, monkeypatch):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    write_context(tmp_path, context)
    legacy_calls, default_calls = [], []
    delivery = TaskContinuationDelivery(
        tmp_path, legacy_calls.append, consume_default=default_calls.append,
    )
    monkeypatch.delenv('BYQ_F6_EXECUTOR_ENABLED', raising=False)

    delivery.tick()

    assert legacy_calls == []
    assert default_calls == [context]
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
    delivery.tick()
    assert legacy_calls == [context]
    assert default_calls == [context]


@pytest.mark.parametrize('status', ['eligible', 'intent', 'waiting'])
def test_default_v3_consumer_rejects_every_legacy_shape_before_legacy_io(monkeypatch, status):
    context, intent, writes, reads, prompts, _, _ = fixture(monkeypatch)
    intent['status'] = status
    intent['may_dispatch'] = False

    main._consume_admitted_task_continuation(context, allow_legacy=False)

    assert writes == reads == prompts == []

    # Explicit F6 reconciliation remains available for historical liabilities.
    if status == 'intent':
        main._consume_admitted_task_continuation(context, allow_legacy=True)
        assert writes == prompts == []
        assert [path for path, _ in reads] == [
            f"/internal/runtime/sessions/{context['session_id']}/continuation-receipt/"
            f"{intent['reservation']['reservation_id']}",
            f"/internal/runtime/sessions/{context['session_id']}/prompts/reconcile",
        ]


def test_v3_cancel_marker_is_exact_durable_idempotent_and_survives_restart(tmp_path):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    delivery = TaskContinuationDelivery(tmp_path, lambda _: None)
    session = main.ProductSession(context['conversation_id'], context['session_id'], context['trace_id'],
        main.Principal(subject=context['owner']), context['workspace_id'])
    delivery.register(session)
    reservation_id = 'continuation_' + 'a' * 32

    assert delivery.request_cancel(context, reservation_id, 'soft')
    path = tmp_path / 'session-a.continuation-cancel.json'
    saved = json.loads(path.read_text())
    assert saved == {
        'schema_version': 'task-continuation-cancel.v2',
        'context': context,
        'reservation_id': reservation_id,
        'mode': 'soft',
    }
    assert delivery.request_cancel(context, reservation_id, 'soft')
    with pytest.raises(ValueError, match='another exact'):
        delivery.request_cancel(context, 'continuation_' + 'b' * 32, 'soft')
    with pytest.raises(ValueError, match='mode cannot change'):
        delivery.request_cancel(context, reservation_id, 'hard')
    assert json.loads(path.read_text()) == saved

    restarted = TaskContinuationDelivery(tmp_path, lambda _: None)
    assert restarted.pending_cancel(context) == (reservation_id, 'soft')
    assert not restarted.clear_cancel(context, reservation_id, 'hard')
    assert restarted.pending_cancel(context) == (reservation_id, 'soft')
    assert restarted.clear_cancel(context, reservation_id, 'soft')
    assert restarted.pending_cancel(context) is None


def test_v3_consumer_claims_and_dispatches_exact_missing_record_once(monkeypatch):
    (context, candidate, intent, carrier, reservation_id, state, backend_calls,
     writes, _reads, prompts, _session) = v3_fixture(monkeypatch, eligible=True)

    main._consume_admitted_task_continuation(context)

    assert candidate['status'] == 'eligible'
    assert [path.rsplit('/', 1)[-1] for path, _, _ in backend_calls] == [
        'peek', 'claim', 'dispatch', 'receipt',
    ]
    assert backend_calls[1][1] == {
        'reservation_schema_version': main.RESERVATION_SCHEMA_VERSION_V3,
        'signal_job_id': carrier['signal_job_id'],
    }
    assert [boot_id for _, _, boot_id in backend_calls] == [None, 'a' * 32, 'a' * 32, 'a' * 32]
    assert writes[0] == ('dispatch', {'reservation_id': reservation_id})
    assert writes[-1][1] == {
        'reservation_id': reservation_id, 'idempotency_key': carrier['idempotency_key'],
        'status': 'accepted', 'run_id': 'f' * 32,
    }
    assert 'idempotency_key' not in state['backend_receipt']
    assert state['backend_receipt']['reservation']['idempotency_key'] == carrier['idempotency_key']
    assert intent['receipt']['idempotency_key'] == carrier['idempotency_key']
    assert prompts[0][0] == f'/internal/runtime/sessions/{context["session_id"]}/prompt'
    assert prompts[0][1]['idempotency_key'] == reservation_id
    assert prompts[0][1]['continuation_budget'] == carrier
    assert prompts[0][1]['idempotency_key'] != prompts[0][1]['continuation_budget']['idempotency_key']
    assert len(prompts) == 1


@pytest.mark.parametrize(('adapter_status', 'peek_status', 'expected_status'), [
    ('accepted', 'reserved', ['accepted']),
    ('outcome_unknown', 'reserved', ['outcome_unknown']),
    ('settled', 'reserved', ['accepted', 'settled']),
])
def test_v3_consumer_reconciles_exact_adapter_states_without_prompt_replay(
        monkeypatch, adapter_status, peek_status, expected_status):
    context, _, intent, carrier, reservation_id, state, _calls, writes, _reads, prompts, session = v3_fixture(
        monkeypatch, adapter_receipt={
            'reservation_id': 'placeholder', 'status': adapter_status,
        })
    # This is a stale peek: the returned intent still says `reserved`, while
    # another consumer has already committed the one-shot dispatch fence.
    # Runtime acceptance/settlement is therefore reconciled from durable
    # Backend `outcome_unknown`; it must never dispatch a second prompt.
    intent['receipt']['status'] = peek_status
    state['backend_receipt'].update(status='outcome_unknown', dispatch_attempts=1)
    if adapter_status == 'settled':
        state['adapter_receipt'] = v3_settled_adapter_receipt(carrier, reservation_id)
    else:
        state['adapter_receipt'] = {
            'reservation_id': reservation_id, 'status': adapter_status,
            'idempotency_key': carrier['idempotency_key'],
        }
        if adapter_status == 'accepted':
            state['adapter_receipt']['run_id'] = 'f' * 32

    main._consume_admitted_task_continuation(context)

    assert prompts == []
    assert not any(kind == 'dispatch' for kind, _ in writes)
    assert intent['receipt']['status'] == peek_status
    assert [payload['status'] for kind, payload in writes if kind == 'receipt'] == expected_status
    if adapter_status == 'accepted':
        assert writes[-1][1] == {
            'reservation_id': reservation_id, 'idempotency_key': carrier['idempotency_key'],
            'status': 'accepted', 'run_id': 'f' * 32,
        }
    if adapter_status == 'outcome_unknown':
        assert writes[-1][1] == {
            'reservation_id': reservation_id, 'idempotency_key': carrier['idempotency_key'],
            'status': 'outcome_unknown',
        }
    if adapter_status == 'settled':
        assert session.continuation_reservation is None
        assert writes[-1][1]['status'] == 'settled'
        assert writes[-1][1]['settlement_sha256'] == state['adapter_receipt']['settlement_sha256']
    assert state['backend_receipt']['status'] == {
        'accepted': 'accepted', 'outcome_unknown': 'outcome_unknown', 'settled': 'settled',
    }[adapter_status]


def test_v3_consumer_keeps_hold_until_exact_backend_settlement_receipt(monkeypatch):
    context, _, intent, carrier, reservation_id, state, _calls, writes, _reads, prompts, session = v3_fixture(
        monkeypatch, adapter_receipt={'reservation_id': 'placeholder', 'status': 'settled'})
    state['backend_receipt'].update(status='outcome_unknown', dispatch_attempts=1)
    state['adapter_receipt'] = v3_settled_adapter_receipt(carrier, reservation_id)
    original_catalog_request = main._catalog_request

    def wrong_settlement_ack(method, path, principal, workspace, payload=None, runtime_boot_id=None):
        reply = original_catalog_request(method, path, principal, workspace,
            payload=payload, runtime_boot_id=runtime_boot_id)
        if (path.endswith('/receipt') and isinstance(payload, dict)
                and payload.get('status') == 'settled'):
            return {**reply, 'settlement_sha256': '0' * 64}
        return reply

    monkeypatch.setattr(main, '_catalog_request', wrong_settlement_ack)
    with pytest.raises(ValueError, match='Backend v3 settlement receipt was not confirmed'):
        main._consume_admitted_task_continuation(context)

    assert state['backend_receipt']['status'] == 'settled'
    assert session.continuation_reservation == reservation_id
    assert prompts == []
    assert [payload['status'] for kind, payload in writes if kind == 'receipt'] == ['accepted', 'settled']


def _set_backend_v3_settled(intent, state, carrier, reservation_id):
    runtime_receipt = v3_settled_adapter_receipt(carrier, reservation_id)
    fields = {key: runtime_receipt[key] for key in (
        'run_id', 'request_usage', 'outcome', 'settlement_sha256')}
    state['backend_receipt'].update(status='settled', dispatch_attempts=1, **fields)
    intent['receipt'].update(status='settled', dispatch_attempts=1, **fields)
    intent.update(status='waiting', may_dispatch=False)


def test_v3_settled_missing_runtime_releases_old_lease_for_next_reservation(monkeypatch):
    (context, _, old_intent, old_carrier, old_reservation_id, old_state, old_calls,
     old_writes, old_reads, old_prompts, session) = v3_fixture(monkeypatch)
    _set_backend_v3_settled(old_intent, old_state, old_carrier, old_reservation_id)
    old_state['adapter_receipt'] = {
        'reservation_id': old_reservation_id, 'status': 'outcome_unknown',
    }
    old_state['reconcile_state'] = 'outcome_unknown'
    old_registry = main.product_sessions

    # The Backend's immutable settled receipt is the only positive evidence in
    # this case; the Runtime's exact receipt has since disappeared. Never replay
    # this old prompt, but do not let its completed lease occupy the session.
    main._consume_admitted_task_continuation(context)

    assert session.continuation_reservation is None
    assert old_writes == []
    assert old_prompts == []
    assert [path.rsplit('/', 1)[-1] for path, _, _ in old_calls] == ['peek']
    assert len(old_reads) == 2
    assert old_reads[0][0].endswith(f'/continuation-receipt/{old_reservation_id}')
    assert old_reads[1][0].endswith('/prompts/reconcile')

    (new_context, _, _new_intent, new_carrier, new_reservation_id, _new_state, new_calls,
     new_writes, new_reads, new_prompts, _new_session) = v3_fixture(
        monkeypatch, signal_job_id='signaljob_' + 'f' * 32,
        result_artifact_id='artifact_' + 'a' * 32)
    monkeypatch.setattr(main, 'product_sessions', old_registry)

    main._consume_admitted_task_continuation(new_context)

    assert new_reservation_id != old_reservation_id
    assert session.continuation_reservation == new_reservation_id
    assert [path.rsplit('/', 1)[-1] for path, _, _ in new_calls] == [
        'peek', 'dispatch', 'receipt',
    ]
    assert new_writes[0] == ('dispatch', {'reservation_id': new_reservation_id})
    assert new_writes[-1][1] == {
        'reservation_id': new_reservation_id,
        'idempotency_key': new_carrier['idempotency_key'],
        'status': 'accepted', 'run_id': 'f' * 32,
    }
    assert new_prompts[0][1]['idempotency_key'] == new_reservation_id
    assert new_reads[0][0].endswith(f'/continuation-receipt/{new_reservation_id}')


@pytest.mark.parametrize(('old_status', 'pending_cancel'), [
    ('reserved', False), ('accepted', False), ('outcome_unknown', False), ('settled', True),
])
def test_v3_missing_runtime_keeps_unresolved_or_cancelled_old_lease(
        monkeypatch, old_status, pending_cancel):
    (context, _, old_intent, old_carrier, old_reservation_id, old_state, _old_calls,
     _old_writes, _old_reads, old_prompts, session) = v3_fixture(monkeypatch)
    if pending_cancel:
        _set_backend_v3_settled(old_intent, old_state, old_carrier, old_reservation_id)
        session.continuation_cancel_requested = old_reservation_id
    else:
        attempts = 0 if old_status == 'reserved' else 1
        old_state['backend_receipt'].update(status=old_status, dispatch_attempts=attempts)
        old_intent['receipt'].update(status=old_status, dispatch_attempts=attempts)
        old_intent['may_dispatch'] = old_status == 'reserved'
        if old_status == 'accepted':
            old_state['backend_receipt']['run_id'] = old_intent['receipt']['run_id'] = 'f' * 32
    old_state['adapter_receipt'] = {
        'reservation_id': old_reservation_id, 'status': 'outcome_unknown',
    }
    old_state['reconcile_state'] = 'outcome_unknown'

    main._consume_admitted_task_continuation(context)

    assert session.continuation_reservation == old_reservation_id
    if old_status == 'reserved':
        assert len(old_prompts) == 1
        assert old_prompts[0][1]['idempotency_key'] == old_reservation_id
    else:
        assert old_prompts == []


def test_v3_backend_cancel_requested_keeps_settled_missing_runtime_lease(monkeypatch):
    (context, _, intent, carrier, reservation_id, state, _calls, writes,
     _reads, prompts, session) = v3_fixture(monkeypatch)
    _set_backend_v3_settled(intent, state, carrier, reservation_id)
    state['backend_receipt']['cancel_requested_at'] = intent['receipt']['cancel_requested_at'] = (
        '2026-10-16T00:00:00+00:00')
    state['adapter_receipt'] = {
        'reservation_id': reservation_id, 'status': 'outcome_unknown',
    }

    main._consume_admitted_task_continuation(context)

    assert session.continuation_reservation == reservation_id
    assert writes == []
    assert prompts == []


def test_v3_settled_missing_runtime_requires_exact_missing_record_projection(monkeypatch):
    (context, _, intent, carrier, reservation_id, state, _calls, writes,
     _reads, prompts, session) = v3_fixture(monkeypatch)
    _set_backend_v3_settled(intent, state, carrier, reservation_id)
    state['adapter_receipt'] = {
        'reservation_id': reservation_id, 'status': 'outcome_unknown', 'diagnostic': 'extra',
    }

    main._consume_admitted_task_continuation(context)

    assert session.continuation_reservation == reservation_id
    assert writes == []
    assert prompts == []


@pytest.mark.parametrize('tamper', [
    'run_id', 'idempotency_key', 'request_usage', 'profile', 'limits',
    'outcome', 'dispatch_attempts', 'settlement_sha256',
])
def test_v3_bad_backend_settlement_does_not_release_missing_runtime_lease(monkeypatch, tamper):
    (context, _, intent, carrier, reservation_id, state, _calls, writes,
     _reads, prompts, session) = v3_fixture(monkeypatch)
    _set_backend_v3_settled(intent, state, carrier, reservation_id)
    if tamper == 'run_id':
        state['backend_receipt']['run_id'] = intent['receipt']['run_id'] = 'not-a-run'
    elif tamper == 'idempotency_key':
        state['backend_receipt']['idempotency_key'] = intent['receipt']['idempotency_key'] = 'task-ready-event:' + '0' * 64
    elif tamper == 'request_usage':
        state['backend_receipt']['request_usage'] = intent['receipt']['request_usage'] = {}
    elif tamper in {'profile', 'limits'}:
        options = dict(carrier['execution_profile']['options'])
        options['max_tool_calls'] = 7
        profile = execution_profile_v2(options, revision=carrier['execution_profile']['options_revision'])
        usage = state['backend_receipt']['request_usage']
        if tamper == 'profile':
            usage['execution_profile'] = profile
            usage['request_limits'] = request_limits_v2(options)
        else:
            usage['request_limits'] = dict(usage['request_limits'])
            usage['request_limits']['max_tool_calls'] = 7
        intent['receipt']['request_usage'] = usage
    elif tamper == 'outcome':
        state['backend_receipt']['outcome'] = intent['receipt']['outcome'] = 'running'
    elif tamper == 'dispatch_attempts':
        state['backend_receipt']['dispatch_attempts'] = intent['receipt']['dispatch_attempts'] = 2
    else:
        state['backend_receipt']['settlement_sha256'] = intent['receipt']['settlement_sha256'] = '0' * 64
    state['adapter_receipt'] = {
        'reservation_id': reservation_id, 'status': 'outcome_unknown',
    }
    state['reconcile_state'] = 'outcome_unknown'

    with pytest.raises(ValueError):
        main._consume_admitted_task_continuation(context)

    assert session.continuation_reservation == reservation_id
    assert writes == []
    assert prompts == []


@pytest.mark.parametrize('reconcile_projection', [
    {'schema_version': 'prompt-receipt.v1', 'state': 'outcome_unknown', 'run_id': 'f' * 32},
    {'schema_version': 'prompt-receipt.v2', 'state': 'outcome_unknown'},
    {'schema_version': 'prompt-receipt.v1', 'state': 'outcome_unknown', 'extra': True},
])
def test_v3_settled_missing_runtime_requires_exact_reconcile_unknown(
        monkeypatch, reconcile_projection):
    (context, _, intent, carrier, reservation_id, state, _calls, writes,
     _reads, prompts, session) = v3_fixture(monkeypatch)
    _set_backend_v3_settled(intent, state, carrier, reservation_id)
    state['adapter_receipt'] = {
        'reservation_id': reservation_id, 'status': 'outcome_unknown',
    }
    state['reconcile_projection'] = reconcile_projection

    main._consume_admitted_task_continuation(context)

    assert session.continuation_reservation == reservation_id
    assert writes == []
    assert prompts == []


@pytest.mark.parametrize('tamper', ['event_key', 'reservation_id'])
def test_v3_consumer_rejects_mismatched_event_digest_before_dispatch(monkeypatch, tamper):
    context, _, intent, carrier, reservation_id, _state, calls, writes, reads, prompts, _session = v3_fixture(
        monkeypatch)
    if tamper == 'event_key':
        carrier_args = dict(owner_principal=carrier['owner_principal'],
            workspace_id=carrier['workspace_id'], conversation_id=carrier['conversation_id'],
            task_id=carrier['task_id'], signal_job_id=carrier['signal_job_id'],
            result_artifact_id=carrier['result_artifact_id'],
            result_artifact_content_sha256=carrier['result_artifact_content_sha256'],
            options=carrier['execution_profile']['options'],
            options_revision=carrier['execution_profile']['options_revision'])
        tampered_carrier = continuation_reservation_v3(
            **carrier_args, event_key='ready-v1:' + '1' * 64)
        intent['reservation'] = tampered_carrier
        intent['receipt']['reservation'] = tampered_carrier
        intent['receipt']['event_key'] = tampered_carrier['event_key']
    else:
        intent['receipt']['reservation_id'] = 'continuation_' + '1' * 32

    with pytest.raises(ValueError, match='identit|digest'):
        main._consume_admitted_task_continuation(context)

    assert [path.rsplit('/', 1)[-1] for path, _, _ in calls] == ['peek']
    assert writes == reads == prompts == []


@pytest.mark.parametrize('foreign', [False, True])
def test_invalid_or_foreign_cancel_marker_fails_closed_before_consumption(tmp_path, monkeypatch, foreign):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    delivery = TaskContinuationDelivery(tmp_path, lambda _: pytest.fail('legacy consumer called'),
        consume_default=lambda _: pytest.fail('default consumer called'), cancel_pending=lambda *_: True)
    session = main.ProductSession(context['conversation_id'], context['session_id'], context['trace_id'],
        main.Principal(subject=context['owner']), context['workspace_id'])
    delivery.register(session)
    marker = {'schema_version': 'task-continuation-cancel.v1', 'context': dict(context),
        'reservation_id': 'continuation_' + 'a' * 32}
    if foreign:
        marker['context']['owner'] = 'mallory'
    else:
        marker['extra'] = 'not-allowed'
    marker_path = tmp_path / 'session-a.continuation-cancel.json'
    marker_path.write_text(json.dumps(marker))

    monkeypatch.delenv('BYQ_F6_EXECUTOR_ENABLED', raising=False)
    delivery.tick()
    assert marker_path.exists()


def test_pending_cancel_fence_precedes_reconcile_and_consumption(tmp_path, monkeypatch):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    reservation_id = 'continuation_' + 'a' * 32
    session = main.ProductSession(context['conversation_id'], context['session_id'], context['trace_id'],
        main.Principal(subject=context['owner']), context['workspace_id'])
    calls, fence_ok = [], [False]
    delivery = TaskContinuationDelivery(tmp_path, lambda _: pytest.fail('legacy consumer called'),
        consume_default=lambda value: calls.append(('consume', value)),
        reconcile=lambda value: calls.append(('reconcile', value)),
        cancel_pending=lambda value, identity, mode: calls.append(('fence', value, identity, mode)) or fence_ok[0])
    delivery.register(session)
    delivery.request_cancel(context, reservation_id, 'hard')
    monkeypatch.delenv('BYQ_F6_EXECUTOR_ENABLED', raising=False)

    delivery.tick()

    assert calls == [('fence', context, reservation_id, 'hard')]
    assert delivery.pending_cancel(context) == (reservation_id, 'hard')

    fence_ok[0] = True
    delivery.tick()

    assert calls[1:] == [('fence', context, reservation_id, 'hard'), ('reconcile', context), ('consume', context)]
    assert delivery.pending_cancel(context) is None


def test_collector_registers_business_context_for_gateway_restart(monkeypatch, tmp_path):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    registry = TaskContinuationDelivery(tmp_path, lambda _: None)
    monkeypatch.setattr(main, 'task_continuation_delivery', registry)
    monkeypatch.setattr(main, 'domain_call_delivery', SimpleNamespace(register=lambda _: None))
    monkeypatch.setattr(main, '_register_answer_delivery', lambda _: None)
    captured = []

    class CapturedThread:
        def __init__(self, *, target, args, **kwargs):
            captured.append((target, args))
        def start(self):
            return None

    monkeypatch.setattr(main.threading, 'Thread', CapturedThread)
    session = main.ProductSession(context['conversation_id'], context['session_id'], context['trace_id'],
        main.Principal(subject=context['owner']), context['workspace_id'])
    main._start_trace_collector(session)

    path = tmp_path / 'session-a.continuation.json'
    assert path.exists() and not (tmp_path / 'session-a.lifecycle.json').exists()
    restarted_calls = []
    restarted = TaskContinuationDelivery(tmp_path, restarted_calls.append)
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
    restarted.tick()
    assert restarted_calls == [context]
    assert captured and captured[0][1] == (session,)


def test_registered_context_cannot_change_identity(tmp_path):
    delivery = TaskContinuationDelivery(tmp_path, lambda _: None)
    session = main.ProductSession('conversation-a', 'session-a', 'trace-a',
        main.Principal(subject='alice'), 'workspace-a')
    delivery.register(session)
    session.trace_id = 'trace-b'
    with pytest.raises(ValueError, match='cannot change'):
        delivery.register(session)


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


@pytest.mark.parametrize('missing', [False, True])
def test_restarted_gateway_attaches_to_original_runtime_without_prompting(monkeypatch, missing):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    registry = main.ProductSessionRegistry()
    monkeypatch.setattr(main, 'product_sessions', registry)
    started, reopened, adapter_posts, catalog_reads = [], [], [], []
    monkeypatch.setattr(main, 'trace_store', SimpleNamespace(read=lambda *_: [], reopen=reopened.append))
    monkeypatch.setattr(main, '_continuation_adapter_get', lambda path, params=None: {'qualified': not missing,
        'reason': 'session_missing' if missing else None})
    monkeypatch.setattr(main, '_start_trace_collector', started.append)
    def catalog(method, path, principal, workspace, payload=None):
        catalog_reads.append((method, path, principal.subject, workspace, payload))
        return {'conversation': {
            'conversation_id': context['conversation_id'], 'runtime_session_id': context['session_id'],
            'trace_id': context['trace_id'], 'status': 'active',
        }, 'messages': []}
    def adapter_post(path, *, payload=None, timeout=20.0):
        adapter_posts.append((path, payload))
        if path == '/internal/runtime/sessions':
            assert payload['attach_live_only'] is True
            return {'session_id': context['session_id'], 'trace_id': context['trace_id'],
                    'status': 'ready', 'boot_id': 'a' * 32}
        raise AssertionError(f'unexpected Adapter POST: {path}')
    monkeypatch.setattr(main, '_catalog_request', catalog)
    monkeypatch.setattr(main, '_adapter_post', adapter_post)

    session = main._attach_continuation_observer(context)
    if missing:
        assert session is None and started == reopened == []
        assert catalog_reads == [] and adapter_posts == []
    else:
        assert session.session_id == context['session_id'] and session.workspace_id == context['workspace_id']
        assert started == [session] and reopened == [context['session_id']]
        assert catalog_reads == [(
            'GET', '/v1/product/conversations/conversation-a', 'alice', 'workspace-a', None)]
        assert adapter_posts == [('/internal/runtime/sessions', {
            'session_id': context['session_id'], 'trace_id': context['trace_id'],
            'workspace_id': context['workspace_id'], 'owner_principal': 'alice',
            'initial_sequence': 0, 'attach_live_only': True,
        })]
        assert not any(path.endswith('/prompt') for path, _ in adapter_posts)
        assert main._attach_continuation_observer(context) is session
        assert started == [session]


def test_background_turn_fences_old_idle_timer_and_browser_disconnect_without_renewal(monkeypatch):
    from datetime import datetime, timedelta, timezone
    clock = [100.0]
    monkeypatch.setattr(main.time, 'monotonic', lambda: clock[0])
    registry = main.ProductSessionRegistry()
    session = main.ProductSession(conversation_id='conversation-a', session_id='session-a',
        trace_id='trace-a', principal=main.Principal(subject='alice'))
    registry.add(session)
    old = registry.idle_release_generation(session)
    expiry = (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat()
    assert registry.hold_continuation(session, 'reservation-a', expiry)
    deadline = session.continuation_deadline
    assert not registry.claim_idle_release(session, old)
    registry.begin_stream(session)
    disconnected = registry.end_stream(session)
    assert session.public_streams == 0 and disconnected is not None
    assert not registry.claim_idle_release(session, disconnected)
    assert registry.idle_release_delay(session) > 300
    clock[0] += 30
    assert registry.hold_continuation(session, 'reservation-a', expiry)
    assert session.continuation_deadline == deadline
    registry.finish_continuation(session, 'different-reservation')
    assert session.continuation_deadline == deadline
    # Unknown outcomes still have a bounded physical idle lease, without
    # refunding Backend budget or inventing a terminal execution receipt.
    clock[0] = deadline + 1
    assert registry.idle_release_delay(session) == main.RUNTIME_SESSION_IDLE_SECONDS - 1
    clock[0] = deadline + main.RUNTIME_SESSION_IDLE_SECONDS + 1
    assert registry.hold_continuation(session, 'reservation-a', expiry)
    assert registry.idle_release_delay(session) == 0
    generation = registry.idle_release_generation(session)
    assert registry.claim_idle_release(session, generation)


def test_settlement_releases_only_matching_background_idle_lease():
    from datetime import datetime, timedelta, timezone
    registry = main.ProductSessionRegistry()
    session = main.ProductSession(conversation_id='conversation-a', session_id='session-a',
        trace_id='trace-a', principal=main.Principal(subject='alice'))
    registry.add(session)
    registry.hold_continuation(session, 'reservation-a', (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat())
    registry.finish_continuation(session, 'reservation-a')
    assert registry.idle_release_delay(session) == main.RUNTIME_SESSION_IDLE_SECONDS
    assert registry.claim_idle_release(session, registry.idle_release_generation(session))


def test_passive_receipt_checks_survive_restart_without_f6_model_permission(tmp_path, monkeypatch):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    write_context(tmp_path, context)
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '0')
    reads, prompts = [], []
    for _ in range(2):
        delivery = TaskContinuationDelivery(tmp_path, prompts.append, reconcile=reads.append)
        delivery.tick()
    assert reads == [context, context] and prompts == []


def test_passive_failure_does_not_block_separately_admitted_f6(tmp_path, monkeypatch):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    write_context(tmp_path, context)
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
    prompts = []
    def unavailable(_):
        raise RuntimeError('synthetic read unavailable')
    TaskContinuationDelivery(tmp_path, prompts.append, reconcile=unavailable).tick()
    assert prompts == [context]


def test_receipt_failure_backoff_survives_restart_and_recovers(tmp_path, monkeypatch):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    write_context(tmp_path, context)
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
    clock = [1000.0]
    reads, prompts = [], []
    def missing(value):
        reads.append(value)
        raise HTTPException(status_code=404, detail='not found')
    def delivery(reconcile):
        return TaskContinuationDelivery(tmp_path, prompts.append, reconcile=reconcile, now=lambda: clock[0])
    delivery(missing).tick()
    delivery(missing).tick()
    assert len(reads) == 1 and len(prompts) == 2
    assert (tmp_path / 'session-a.continuation.json').exists()
    clock[0] += 60
    delivery(reads.append).tick()
    delivery(reads.append).tick()
    assert len(reads) == 3  # success clears backoff


def test_receipt_backoff_does_not_cross_context_identity(tmp_path, monkeypatch):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    path = write_context(tmp_path, context)
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '0')
    def missing(_):
        raise RuntimeError('unavailable')
    TaskContinuationDelivery(tmp_path, lambda _: None, reconcile=missing, now=lambda: 1000).tick()
    context['trace_id'] = 'trace-b'
    path.write_text(json.dumps({'schema_version': CONTEXT_SCHEMA, 'context': context}))
    reads = []
    TaskContinuationDelivery(tmp_path, lambda _: None, reconcile=reads.append, now=lambda: 1001).tick()
    assert reads == [context]


@pytest.mark.parametrize('state', ['[]', '{bad json', '{"context": null}'])
def test_corrupt_receipt_backoff_does_not_block_checks_or_f6(tmp_path, monkeypatch, state):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    write_context(tmp_path, context)
    (tmp_path / 'session-a.continuation.receipt-backoff.json').write_text(state)
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
    reads, prompts = [], []
    TaskContinuationDelivery(tmp_path, prompts.append, reconcile=reads.append).tick()
    assert reads == [context] and prompts == [context]


def test_long_continuation_hold_survives_old_limit_without_renewal(monkeypatch):
    from datetime import datetime, timedelta, timezone
    clock = [1000.0]
    monkeypatch.setattr(main.time, 'monotonic', lambda: clock[0])
    registry = main.ProductSessionRegistry()
    session = main.ProductSession(conversation_id='long-conversation', session_id='long-session',
        trace_id='long-trace', principal=main.Principal(subject='alice'))
    registry.add(session)
    expiry = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    assert registry.hold_continuation(session, 'long-reservation', expiry)
    deadline = session.continuation_deadline
    assert 8190 < deadline <= 8205
    clock[0] += 1800
    assert registry.hold_continuation(session, 'long-reservation', expiry)
    assert session.continuation_deadline == deadline
    registry.finish_continuation(session, 'long-reservation')
    assert registry.idle_release_delay(session) == main.RUNTIME_SESSION_IDLE_SECONDS


def test_v3_continuation_hold_has_no_expiry_and_only_exact_reservation_releases(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(main.time, 'monotonic', lambda: clock[0])
    registry = main.ProductSessionRegistry()
    session = main.ProductSession(conversation_id='v3-conversation', session_id='v3-session',
        trace_id='v3-trace', principal=main.Principal(subject='alice'))
    registry.add(session)
    monkeypatch.setattr(main, 'product_sessions', registry)
    reservation_id = 'continuation_' + 'a' * 32
    assert registry.hold_v3_continuation(session, reservation_id)
    generation = registry.idle_release_generation(session)
    assert generation is not None
    assert session.continuation_reservation == reservation_id
    assert session.continuation_deadline is None
    assert registry.idle_release_delay(session) is None
    assert not registry.claim_idle_release(session, generation)
    monkeypatch.setattr(main.threading, 'Timer', lambda *args, **kwargs: pytest.fail(
        'an unbounded v3 reservation must not schedule idle release'))
    main._schedule_idle_release(session, generation)

    # Passage of arbitrary Gateway time never creates a v3 expiry or release.
    clock[0] += 10**9
    assert registry.hold_v3_continuation(session, reservation_id)
    assert registry.idle_release_delay(session) is None
    registry.finish_continuation(session, 'continuation_' + 'b' * 32)
    assert session.continuation_reservation == reservation_id
    assert not registry.hold_v3_continuation(session, 'continuation_' + 'b' * 32)

    registry.finish_continuation(session, reservation_id)
    assert session.continuation_reservation is None
    assert registry.idle_release_delay(session) == main.RUNTIME_SESSION_IDLE_SECONDS
    release_generation = registry.idle_release_generation(session)
    assert registry.claim_idle_release(session, release_generation)


def _v3_cancel_route_fixture(monkeypatch, tmp_path, *, mode='soft'):
    context = dict(owner='alice', workspace_id='workspace-a', conversation_id='conversation-a',
        session_id='session-a', trace_id='trace-a')
    task_id = 'task_' + 'b' * 32
    carrier_args = dict(owner_principal=context['owner'], workspace_id=context['workspace_id'],
        conversation_id=context['conversation_id'], task_id=task_id,
        signal_job_id='signaljob_' + 'c' * 32, result_artifact_id='artifact_' + 'd' * 32,
        result_artifact_content_sha256='e' * 64, options=default_agent_execution_options(),
        options_revision=7)
    placeholder = continuation_reservation_v3(**carrier_args, event_key='ready-v1:' + '0' * 64)
    digest = placeholder['idempotency_key'].split(':', 1)[1]
    carrier = continuation_reservation_v3(**carrier_args, event_key='ready-v1:' + digest)
    reservation_id = 'continuation_' + digest[:32]
    ledger_entry = {
        'schema_version': 'task-continuation-ledger-entry.v1',
        'reservation_id': reservation_id,
        'event_key': carrier['event_key'],
        'signal_job_id': carrier['signal_job_id'],
        'status': 'reserved',
        'created_at': '2026-10-15T00:00:00+00:00',
        'dispatch_attempts': 0,
        'reservation': carrier,
    }
    run_id = 'f' * 32
    ledger_entry.update(status='accepted', dispatch_attempts=1, run_id=run_id)
    receipt_projection = {**ledger_entry, 'idempotency_key': carrier['idempotency_key']}
    intent = {
        'status': 'intent', 'task_id': task_id,
        'conversation_id': context['conversation_id'], 'session_id': context['session_id'],
        'trace_id': context['trace_id'], 'may_dispatch': False,
        'receipt': receipt_projection, 'reservation': carrier,
        'instruction': 'Read the exact completed task snapshot and report it.',
    }
    adapter_receipt = {
        'reservation_id': reservation_id, 'status': 'accepted',
        'idempotency_key': carrier['idempotency_key'], 'run_id': run_id,
    }
    state = {
        'backend_cancel_fails': False,
        'runtime_failures_remaining': 0,
        'runtime_failure_status': 503,
        'ack_root_run_id': run_id,
        'cancel_mode': mode,
        'intent': intent,
        'backend_receipt': ledger_entry,
        'carrier': carrier,
        'adapter_receipt': adapter_receipt,
        'prompt_reconcile': {'state': 'accepted', 'run_id': run_id},
        'trace_events': [],
        'root_rows': [],
    }
    calls = []

    registry = main.ProductSessionRegistry()
    session = main.ProductSession(context['conversation_id'], context['session_id'], context['trace_id'],
        main.Principal(subject=context['owner']), context['workspace_id'], boot_id='a' * 32)
    registry.add(session)
    assert registry.hold_v3_continuation(session, reservation_id)
    monkeypatch.setattr(main, 'product_sessions', registry)
    monkeypatch.setattr(main, '_product_session', lambda *_: session)
    monkeypatch.setattr(main, '_require_session_runtime_authority', lambda _: 'a' * 32)

    def backend(method, path, principal, workspace, payload=None):
        calls.append(('backend', method, path, payload))
        assert principal.subject == context['owner'] and workspace == context['workspace_id']
        if path.endswith('/peek'):
            return intent
        if path.endswith('/cancel'):
            if state['backend_cancel_fails']:
                raise HTTPException(status_code=503, detail='synthetic Backend unavailable')
            assert payload == {'reservation_id': reservation_id}
            ledger = state['backend_receipt']
            projection = state['intent']['receipt']
            if ledger['status'] == 'reserved':
                ledger.update(status='cancelled', dispatch_attempts=0)
                projection.update(status='cancelled', dispatch_attempts=0)
            elif ledger['status'] in {'outcome_unknown', 'accepted'}:
                cancel_requested_at = ledger.setdefault(
                    'cancel_requested_at', '2026-10-15T00:00:00+00:00')
                projection['cancel_requested_at'] = cancel_requested_at
            return {'reservation_id': reservation_id, 'cancel_requested': True,
                'status': ledger['status']}
        raise AssertionError(path)

    def adapter_get(path, params=None):
        calls.append(('adapter_get', path, params))
        if path.endswith(f'/continuation-receipt/{reservation_id}'):
            return state['adapter_receipt']
        if path.endswith('/prompts/reconcile'):
            return state['prompt_reconcile']
        raise AssertionError(path)

    def runtime(path, payload=None, timeout=20.0):
        calls.append(('runtime', path, payload, timeout))
        assert path == (f"/internal/runtime/sessions/{session.session_id}/cancel"
            f"?mode={state['cancel_mode']}&expected_root_run_id={run_id}")
        assert payload is None and timeout == 5.0
        if state['runtime_failures_remaining']:
            state['runtime_failures_remaining'] -= 1
            raise HTTPException(status_code=state['runtime_failure_status'],
                detail='synthetic Runtime cancel unavailable')
        return {
            'session_id': session.session_id,
            'trace_id': session.trace_id,
            'boot_id': session.boot_id,
            'status': 'cancelling',
            'active_prompt': True,
            'cancelled_root_run_id': state['ack_root_run_id'],
        }

    trace_event = {
        'session_id': session.session_id, 'trace_id': session.trace_id,
        'source': 'runtime-adapter', 'sequence': 1, 'kind': 'session.started',
        'payload': {'run_id': run_id},
    }
    state['trace_events'] = [trace_event]
    state['root_rows'] = [{
        'root_run_id': run_id, 'status': 'active', 'authority_status': 'active',
        'terminal_sequence': None, 'terminal_event_sha256': None,
    }]
    monkeypatch.setattr(main, '_catalog_request', backend)
    monkeypatch.setattr(main, '_continuation_adapter_get', adapter_get)
    monkeypatch.setattr(main, '_adapter_post', runtime)
    monkeypatch.setattr(main, 'trace_store', SimpleNamespace(read=lambda _: state['trace_events']))
    monkeypatch.setattr(main, '_runtime_root_rows', lambda _: state['root_rows'])

    delivery = TaskContinuationDelivery(tmp_path, lambda _: None)
    delivery.register(session)
    monkeypatch.setattr(main, 'task_continuation_delivery', delivery)
    return context, registry, session, reservation_id, delivery, state, calls


def test_v3_cancel_rejects_mode_less_marker_before_external_calls(monkeypatch, tmp_path):
    context, _registry, _session, reservation_id, delivery, _state, calls = _v3_cancel_route_fixture(
        monkeypatch, tmp_path)
    marker_path = tmp_path / 'session-a.continuation-cancel.json'
    marker_path.write_text(json.dumps({
        'schema_version': 'task-continuation-cancel.v1',
        'context': context,
        'reservation_id': reservation_id,
    }))

    with pytest.raises(HTTPException) as exc_info:
        main.cancel_product_session(
            'conversation-a', main.ProductCancelRequest(mode='soft'), object())

    assert exc_info.value.status_code == 409
    assert marker_path.exists()
    assert calls == []


def test_v3_cancel_rejects_conflicting_pending_mode_without_changing_marker(monkeypatch, tmp_path):
    context, _registry, _session, reservation_id, delivery, _state, calls = _v3_cancel_route_fixture(
        monkeypatch, tmp_path)
    delivery.request_cancel(context, reservation_id, 'soft')

    with pytest.raises(HTTPException) as exc_info:
        main.cancel_product_session(
            'conversation-a', main.ProductCancelRequest(mode='hard'), object())

    assert exc_info.value.status_code == 409
    assert delivery.pending_cancel(context) == (reservation_id, 'soft')
    assert calls == []


def test_v3_cancel_persists_intent_and_runtime_cancel_runs_after_backend_failure(monkeypatch, tmp_path):
    context, registry, session, reservation_id, delivery, state, calls = _v3_cancel_route_fixture(
        monkeypatch, tmp_path)
    state['backend_cancel_fails'] = True
    response = main.cancel_product_session('conversation-a', main.ProductCancelRequest(mode='soft'), object())

    assert [call[0] for call in calls] == ['backend', 'adapter_get', 'backend', 'runtime']
    assert calls[0][2].endswith('/peek') and calls[2][2].endswith('/cancel')
    assert calls[-1][1].endswith(f'?mode=soft&expected_root_run_id={"f" * 32}')
    assert delivery.pending_cancel(context) == (reservation_id, 'soft')
    assert registry.v3_cancel_blocks_dispatch(session, reservation_id)
    assert response['continuation_cancel'] == {
        'reservation_id': reservation_id,
        'backend_fence_confirmed': False,
        'backend_status': None,
        'marker_persisted_before_fence': True,
        'marker_pending': True,
        'runtime_cancel_attempted': True,
        'runtime_cancel_acknowledged': True,
        'runtime_target_closed': False,
        'durable_cancel_confirmed': False,
        'state': 'outcome_unknown',
        'activation_hold': True,
        'activation_hold_durable': True,
    }


def _set_v3_cancel_settled_receipts(state, reservation_id):
    run_id = 'f' * 32
    carrier = state['carrier']
    usage = continuation_request_usage_v2(
        execution_profile=carrier['execution_profile'],
        admission_usage=unknown_admission_usage_v2(),
        actual_usage=unknown_actual_usage_v2(),
    )
    facts = {
        'reservation_id': reservation_id,
        'idempotency_key': carrier['idempotency_key'],
        'status': 'settled',
        'run_id': run_id,
        'outcome': 'needs_attention',
        'request_usage': usage,
    }
    settlement_sha256 = hashlib.sha256(json.dumps(
        facts, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    state['adapter_receipt'] = {**facts, 'settlement_sha256': settlement_sha256}
    settled_fields = {
        'status': 'settled', 'run_id': run_id, 'request_usage': usage,
        'outcome': 'needs_attention', 'settlement_sha256': settlement_sha256,
    }
    state['backend_receipt'].update(settled_fields)
    state['intent']['receipt'].update(settled_fields)


@pytest.mark.parametrize('mismatch', [
    'accepted_run_id',
    'reserved_vs_accepted',
    'settled_without_runtime_settlement',
    'settled_typed_usage',
    'settled_outcome',
    'settled_hash',
    'cancelled_vs_accepted',
    'cancelled_vs_reconciled_acceptance',
    'rejected_vs_settled',
])
def test_v3_cancel_receipt_conflicts_do_not_send_cancel_or_clear_hold(
        monkeypatch, tmp_path, mismatch):
    context, registry, session, reservation_id, delivery, state, calls = _v3_cancel_route_fixture(
        monkeypatch, tmp_path)
    backend_projection = state['intent']['receipt']

    def update_backend_receipt(**fields):
        state['backend_receipt'].update(fields)
        backend_projection.update(fields)

    def remove_backend_receipt_fields(*fields):
        for field in fields:
            state['backend_receipt'].pop(field, None)
            backend_projection.pop(field, None)

    if mismatch == 'accepted_run_id':
        update_backend_receipt(status='accepted', run_id='0' * 32)
    elif mismatch == 'reserved_vs_accepted':
        remove_backend_receipt_fields('run_id')
        update_backend_receipt(status='reserved', dispatch_attempts=0)
    elif mismatch == 'settled_without_runtime_settlement':
        _set_v3_cancel_settled_receipts(state, reservation_id)
        state['adapter_receipt'] = {
            'reservation_id': reservation_id, 'status': 'accepted',
            'idempotency_key': state['carrier']['idempotency_key'], 'run_id': 'f' * 32,
        }
    elif mismatch in {'settled_typed_usage', 'settled_outcome', 'settled_hash'}:
        _set_v3_cancel_settled_receipts(state, reservation_id)
        if mismatch == 'settled_typed_usage':
            update_backend_receipt(request_usage={
                **backend_projection['request_usage'],
                'limit_violations': ['max_runtime_seconds'],
            })
        elif mismatch == 'settled_outcome':
            update_backend_receipt(outcome='completed')
        else:
            update_backend_receipt(settlement_sha256='0' * 64)
    elif mismatch == 'cancelled_vs_accepted':
        remove_backend_receipt_fields('run_id')
        update_backend_receipt(status='cancelled', dispatch_attempts=0)
    elif mismatch == 'cancelled_vs_reconciled_acceptance':
        remove_backend_receipt_fields('run_id')
        update_backend_receipt(status='cancelled', dispatch_attempts=0)
        state['adapter_receipt'] = {
            'reservation_id': reservation_id, 'status': 'outcome_unknown',
            'idempotency_key': state['carrier']['idempotency_key'],
        }
    else:
        _set_v3_cancel_settled_receipts(state, reservation_id)
        remove_backend_receipt_fields('run_id', 'request_usage', 'outcome', 'settlement_sha256')
        update_backend_receipt(status='rejected')

    response = main.cancel_product_session(
        'conversation-a', main.ProductCancelRequest(mode='soft'), object())

    assert response['continuation_cancel']['runtime_cancel_attempted'] is False
    assert response['continuation_cancel']['runtime_cancel_acknowledged'] is False
    assert response['continuation_cancel']['durable_cancel_confirmed'] is False
    assert delivery.pending_cancel(context) == (reservation_id, 'soft')
    assert session.continuation_reservation == reservation_id
    assert registry.v3_cancel_blocks_dispatch(session, reservation_id)
    assert not any(call[0] == 'runtime' for call in calls)
    assert not any(call[0] == 'backend' and call[2].endswith('/cancel') for call in calls)


def test_v3_cancel_poller_receipt_conflict_retains_marker_without_retrying_cancel(
        monkeypatch, tmp_path):
    context, registry, session, reservation_id, delivery, state, calls = _v3_cancel_route_fixture(
        monkeypatch, tmp_path)
    state['backend_receipt'].update(status='accepted', run_id='0' * 32)
    state['intent']['receipt'].update(status='accepted', run_id='0' * 32)
    delivery.request_cancel(context, reservation_id, 'soft')

    assert main._retry_v3_continuation_cancel(context, reservation_id, 'soft') is False

    assert delivery.pending_cancel(context) == (reservation_id, 'soft')
    assert session.continuation_reservation == reservation_id
    assert registry.v3_cancel_blocks_dispatch(session, reservation_id)
    assert not any(call[0] == 'runtime' for call in calls)
    assert not any(call[0] == 'backend' and call[2].endswith('/cancel') for call in calls)


def test_v3_cancel_marker_write_failure_still_attempts_backend_and_runtime(monkeypatch, tmp_path):
    context, registry, session, reservation_id, delivery, state, calls = _v3_cancel_route_fixture(
        monkeypatch, tmp_path)
    state['backend_cancel_fails'] = True

    def fail_marker(*_args):
        raise OSError('synthetic marker write failure')

    monkeypatch.setattr(delivery, 'request_cancel', fail_marker)
    response = main.cancel_product_session('conversation-a', main.ProductCancelRequest(mode='soft'), object())

    assert [call[0] for call in calls] == ['backend', 'adapter_get', 'backend', 'runtime']
    assert delivery.pending_cancel(context) is None
    assert registry.v3_cancel_blocks_dispatch(session, reservation_id)
    assert response['continuation_cancel']['marker_persisted_before_fence'] is False
    assert response['continuation_cancel']['durable_cancel_confirmed'] is False
    assert response['continuation_cancel']['runtime_cancel_acknowledged'] is True


def test_v3_cancel_exact_backend_confirmation_clears_marker_without_releasing_hold(monkeypatch, tmp_path):
    context, registry, session, reservation_id, delivery, state, calls = _v3_cancel_route_fixture(
        monkeypatch, tmp_path)
    response = main.cancel_product_session('conversation-a', main.ProductCancelRequest(mode='soft'), object())

    assert [call[0] for call in calls] == ['backend', 'adapter_get', 'backend', 'runtime']
    assert 'idempotency_key' not in state['backend_receipt']
    assert state['intent']['receipt']['idempotency_key'] == state['carrier']['idempotency_key']
    assert delivery.pending_cancel(context) is None
    assert response['continuation_cancel']['durable_cancel_confirmed'] is True
    assert response['continuation_cancel']['backend_status'] == 'accepted'
    assert session.continuation_reservation == reservation_id
    assert session.continuation_deadline is None
    assert registry.v3_cancel_blocks_dispatch(session, reservation_id)


def test_v3_cancel_unknown_runtime_ack_keeps_exact_marker_and_hold(monkeypatch, tmp_path):
    context, registry, session, reservation_id, delivery, state, _calls = _v3_cancel_route_fixture(
        monkeypatch, tmp_path)
    state['ack_root_run_id'] = '0' * 32

    response = main.cancel_product_session('conversation-a', main.ProductCancelRequest(mode='soft'), object())

    assert response['continuation_cancel']['backend_fence_confirmed'] is True
    assert response['continuation_cancel']['runtime_cancel_attempted'] is True
    assert response['continuation_cancel']['runtime_cancel_acknowledged'] is False
    assert response['continuation_cancel']['durable_cancel_confirmed'] is False
    assert response['status'] == 'outcome_unknown'
    assert delivery.pending_cancel(context) == (reservation_id, 'soft')
    assert registry.v3_cancel_blocks_dispatch(session, reservation_id)


def test_v3_cancel_hard_mode_is_preserved_when_runtime_returns_409(monkeypatch, tmp_path):
    context, registry, session, reservation_id, delivery, state, calls = _v3_cancel_route_fixture(
        monkeypatch, tmp_path, mode='hard')
    state['runtime_failures_remaining'] = 1
    state['runtime_failure_status'] = 409

    response = main.cancel_product_session('conversation-a', main.ProductCancelRequest(mode='hard'), object())

    assert response['continuation_cancel']['runtime_cancel_attempted'] is True
    assert response['continuation_cancel']['runtime_cancel_acknowledged'] is False
    assert response['continuation_cancel']['durable_cancel_confirmed'] is False
    assert delivery.pending_cancel(context) == (reservation_id, 'hard')
    assert registry.v3_cancel_blocks_dispatch(session, reservation_id)
    assert session.released is False
    assert [call[1] for call in calls if call[0] == 'runtime'] == [
        f'/internal/runtime/sessions/{session.session_id}/cancel'
        f'?mode=hard&expected_root_run_id={"f" * 32}',
    ]


@pytest.mark.parametrize(('terminal_mode', 'expected_closed'), [('soft', True), ('hard', False)])
def test_v3_cancel_accepts_only_matching_terminal_root_closure(
        monkeypatch, tmp_path, terminal_mode, expected_closed):
    context, registry, session, reservation_id, delivery, state, calls = _v3_cancel_route_fixture(
        monkeypatch, tmp_path)
    run_id = 'f' * 32
    terminal_event = {
        'session_id': session.session_id, 'trace_id': session.trace_id,
        'source': 'runtime-adapter', 'sequence': 2, 'kind': 'session.cancelled',
        'payload': {'run_id': run_id, 'mode': terminal_mode},
    }
    lifecycle = main.project_lifecycle_event(terminal_event, session.session_id, session.trace_id)
    terminal_receipt = main.lifecycle_receipt(lifecycle)
    carrier = state['carrier']
    usage = continuation_request_usage_v2(
        execution_profile=carrier['execution_profile'],
        admission_usage=unknown_admission_usage_v2(),
        actual_usage=unknown_actual_usage_v2(),
    )
    settled_facts = {
        'reservation_id': reservation_id,
        'idempotency_key': carrier['idempotency_key'],
        'status': 'settled',
        'run_id': run_id,
        'outcome': 'needs_attention',
        'request_usage': usage,
    }
    state['adapter_receipt'] = {
        **settled_facts,
        'settlement_sha256': hashlib.sha256(json.dumps(
            settled_facts, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
    }
    state['trace_events'].append(terminal_event)
    state['root_rows'] = [{
        'root_run_id': run_id, 'status': 'cancelled', 'authority_status': 'closed',
        'terminal_sequence': terminal_receipt['sequence'],
        'terminal_event_sha256': terminal_receipt['event_sha256'],
    }]

    response = main.cancel_product_session('conversation-a', main.ProductCancelRequest(mode='soft'), object())

    assert response['continuation_cancel']['runtime_target_closed'] is expected_closed
    assert response['continuation_cancel']['runtime_cancel_attempted'] is False
    assert response['continuation_cancel']['durable_cancel_confirmed'] is expected_closed
    assert [call[0] for call in calls if call[0] == 'runtime'] == []
    assert delivery.pending_cancel(context) == (
        None if expected_closed else (reservation_id, 'soft'))
    assert session.continuation_reservation == reservation_id
    assert registry.v3_cancel_blocks_dispatch(session, reservation_id)


def test_v3_cancel_hard_mode_uses_exact_runtime_route(monkeypatch, tmp_path):
    context, registry, session, reservation_id, delivery, _state, calls = _v3_cancel_route_fixture(
        monkeypatch, tmp_path, mode='hard')

    response = main.cancel_product_session(
        'conversation-a', main.ProductCancelRequest(mode='hard'), object())

    assert response['continuation_cancel']['runtime_cancel_acknowledged'] is True
    assert [call[1] for call in calls if call[0] == 'runtime'] == [
        f'/internal/runtime/sessions/{session.session_id}/cancel'
        f'?mode=hard&expected_root_run_id={"f" * 32}',
    ]
    assert delivery.pending_cancel(context) is None
    assert registry.v3_cancel_blocks_dispatch(session, reservation_id)


@pytest.mark.parametrize('adapter_status', ['accepted', 'outcome_unknown'])
def test_v3_cancel_cancelled_event_without_settlement_keeps_marker_and_hold(
        monkeypatch, tmp_path, adapter_status):
    context, registry, session, reservation_id, delivery, state, calls = _v3_cancel_route_fixture(
        monkeypatch, tmp_path)
    run_id = 'f' * 32
    state['runtime_failures_remaining'] = 1
    if adapter_status == 'outcome_unknown':
        state['adapter_receipt'] = {
            'reservation_id': reservation_id, 'status': 'outcome_unknown',
            'idempotency_key': state['carrier']['idempotency_key'],
        }
    first = main.cancel_product_session('conversation-a', main.ProductCancelRequest(mode='soft'), object())
    assert first['continuation_cancel']['runtime_cancel_acknowledged'] is False
    assert delivery.pending_cancel(context) == (reservation_id, 'soft')

    terminal_event = {
        'session_id': session.session_id, 'trace_id': session.trace_id,
        'source': 'runtime-adapter', 'sequence': 2, 'kind': 'session.cancelled',
        'payload': {'run_id': run_id, 'mode': 'soft'},
    }
    lifecycle = main.project_lifecycle_event(terminal_event, session.session_id, session.trace_id)
    terminal_receipt = main.lifecycle_receipt(lifecycle)
    state['trace_events'].append(terminal_event)
    state['root_rows'] = [{
        'root_run_id': run_id, 'status': 'cancelled', 'authority_status': 'closed',
        'terminal_sequence': terminal_receipt['sequence'],
        'terminal_event_sha256': terminal_receipt['event_sha256'],
    }]
    restarted = TaskContinuationDelivery(
        tmp_path, lambda _: pytest.fail('cancelled task must not dispatch'),
        cancel_pending=main._retry_v3_continuation_cancel,
    )
    monkeypatch.delenv('BYQ_F6_EXECUTOR_ENABLED', raising=False)
    restarted.tick()

    assert delivery.pending_cancel(context) == (reservation_id, 'soft')
    assert registry.v3_cancel_blocks_dispatch(session, reservation_id)
    assert [call[0] for call in calls].count('runtime') == 1


@pytest.mark.parametrize('mode', ['soft', 'hard'])
def test_v3_cancel_poller_restart_retries_both_fences_with_original_mode(
        monkeypatch, tmp_path, mode):
    context, registry, session, reservation_id, delivery, state, calls = _v3_cancel_route_fixture(
        monkeypatch, tmp_path, mode=mode)
    state['runtime_failures_remaining'] = 1

    first = main.cancel_product_session(
        'conversation-a', main.ProductCancelRequest(mode=mode), object())

    assert first['continuation_cancel']['backend_fence_confirmed'] is True
    assert first['continuation_cancel']['runtime_cancel_acknowledged'] is False
    assert delivery.pending_cancel(context) == (reservation_id, mode)
    assert registry.v3_cancel_blocks_dispatch(session, reservation_id)

    restarted = TaskContinuationDelivery(
        tmp_path, lambda _: pytest.fail('cancelled task must not dispatch'),
        cancel_pending=main._retry_v3_continuation_cancel,
    )
    monkeypatch.delenv('BYQ_F6_EXECUTOR_ENABLED', raising=False)
    restarted.tick()

    assert delivery.pending_cancel(context) is None
    assert registry.v3_cancel_blocks_dispatch(session, reservation_id)
    assert [call[0] for call in calls].count('backend') == 4
    assert [call[0] for call in calls].count('runtime') == 2
    assert [call[1] for call in calls if call[0] == 'runtime'] == [
        f'/internal/runtime/sessions/{session.session_id}/cancel'
        f'?mode={mode}&expected_root_run_id={"f" * 32}',
        f'/internal/runtime/sessions/{session.session_id}/cancel'
        f'?mode={mode}&expected_root_run_id={"f" * 32}',
    ]


def test_legacy_reserved_receipt_never_dispatches_even_if_backend_claims_permission(monkeypatch):
    context, intent, writes, reads, prompts, _, _ = fixture(monkeypatch)
    intent['reservation']['schema_version'] = 'task-continuation-reservation.v1'
    main._consume_admitted_task_continuation(context)
    assert writes == prompts == []
    assert len(reads) == 2


def request_usage():
    return dict(schema_version=USAGE_SCHEMA_VERSION, execution_profile=profile_binding(), request_limits=request_limits(), limit_violations=[],
        admission_usage=dict(provider_calls=1,provider_attempts=1,input_bytes=100,declared_output_tokens=8192,
            tool_payload_bytes=0,max_input_bytes=100,max_declared_output_tokens=8192,max_tool_payload_bytes=0,
            tool_calls=0,max_concurrent=1,elapsed_ms=100), actual_usage=unknown_actual_usage())


def test_new_settlement_forwards_actual_unknown_separately_from_limits(monkeypatch):
    context, intent, writes, _, prompts, _, settlement = fixture(monkeypatch)
    usage = request_usage()
    settlement.update(status='settled', run_id='c'*32, request_usage=usage, settlement_sha256='d'*64, outcome='needs_attention')
    main._consume_admitted_task_continuation(context)
    assert prompts == []
    assert writes[-1] == ('receipt', dict(reservation_id=intent['reservation']['reservation_id'], status='settled',
        request_usage=usage, settlement_sha256='d'*64, outcome='needs_attention'))
    assert 'charged_tokens' not in writes[-1][1]


def test_invalid_new_settlement_cannot_mark_business_receipt_accepted(monkeypatch):
    context, _, writes, _, prompts, _, settlement = fixture(monkeypatch)
    usage = request_usage(); usage['actual_usage']['input_tokens'] = 0
    settlement.update(status='settled', run_id='c'*32, request_usage=usage, settlement_sha256='d'*64, outcome='completed')
    with pytest.raises(ValueError, match='factual source'):
        main._consume_admitted_task_continuation(context)
    assert writes == prompts == []


def test_live_registry_cannot_redirect_reserved_request_to_another_session(monkeypatch):
    context, _, writes, _, prompts, _, _ = fixture(monkeypatch)
    monkeypatch.setattr(main.product_sessions, 'get_owned', lambda *args: SimpleNamespace(session_id='different-session', boot_id='a'*32))
    with pytest.raises(ValueError, match='original session identity'):
        main._consume_admitted_task_continuation(context)
    assert writes == prompts == []


@pytest.mark.parametrize('detail,definite', [
    ('previous turn domain cleanup is not yet acknowledged', True),
    ('previous runtime process cleanup is not complete', True),
    ('session session-a cannot accept a prompt in state running', True),
    ('prompt idempotency key was reused with different content', False),
    ('session another-session cannot accept a prompt in state running', False),
])
def test_known_preaccept_conflict_is_terminal_and_unknown_identity_conflict_stays_unresolved(monkeypatch, detail, definite):
    context, intent, writes, _, prompts, _, _ = fixture(monkeypatch)
    def rejected(path, payload, timeout):
        prompts.append(payload)
        error = HTTPException(409, detail)
        error.adapter_conflict_detail = detail
        raise error
    monkeypatch.setattr(main, '_adapter_post', rejected)
    main._consume_admitted_task_continuation(context)
    assert [kind for kind, _ in writes] == (['dispatch','receipt'] if definite else ['dispatch'])
    assert intent['receipt']['status'] == ('rejected' if definite else 'outcome_unknown')
    main._consume_admitted_task_continuation(context)
    assert len(prompts) == 1
    if definite:assert writes[-1][1]['status'] == 'rejected'
