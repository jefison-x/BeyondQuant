"""ADR-0090 request identity, at-most-once dispatch, and legacy liability tests."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.research import IdempotencyConflict, ResearchStore
from app.research_continuation import _event_key
from packages.contracts.continuation_request import RESERVATION_SCHEMA_VERSION
from tests.continuation_request_fixtures import confirmed_request_usage, legacy_reservation
from tests.test_data_ready_continuation import add_ready_event, setup_ready

pytestmark = pytest.mark.skipif(not os.environ.get('BYQ_DATABASE_URL'), reason='isolated PostgreSQL required')


def setup_granted(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store = fixture['store']
    store.create_continuation_permission(fixture['payload']['task_id'], {
        'idempotency_key': 'request-ledger-confirmation',
        'confirmed_artifact_ids': [fixture['payload']['strategy_version_artifact_id']],
    }, trusted_context=fixture['context'])
    fixture['jobs']._execute("UPDATE signal_producer_jobs SET updated_at=now() WHERE job_id=:job",
        {'job': fixture['job_id']})
    return fixture


def close_fixture(fixture, other=None):
    fixture['store'].close()
    if other is not None:
        other.close()
    fixture['backtests'].close()
    fixture['jobs'].close()


def test_concurrent_same_event_returns_one_v2_request_and_unknown_never_replays(monkeypatch, tmp_path):
    fixture = setup_granted(monkeypatch, tmp_path)
    store, task, context = fixture['store'], fixture['payload']['task_id'], fixture['context']
    other = ResearchStore()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(s.claim_conversation_continuation, fixture['conversation'],
                trusted_context=context) for s in (store, other)]
            first, second = [future.result() for future in futures]
        receipt = first['receipt']
        assert second['receipt']['reservation_id'] == receipt['reservation_id']
        assert receipt['schema_version'] == RESERVATION_SCHEMA_VERSION
        assert receipt['dispatch_attempts'] == 0
        assert 'instruction' in receipt  # internal dispatch data; public request_identity omits it

        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = list(pool.map(lambda s: s.claim_continuation_dispatch(
                task, receipt['reservation_id'], trusted_context=context), (store, other)))
        assert sum(row['dispatch'] for row in attempts) == 1
        store.close()
        store = ResearchStore()
        assert store.claim_continuation_dispatch(task, receipt['reservation_id'],
            trusted_context=context) == {'dispatch': False}

        view = store.get_continuation_permission(task, trusted_context=context)
        identity = view['request_state']['request_identity']
        assert identity == {
            'reservation_id': receipt['reservation_id'],
            'status': 'outcome_unknown',
            'run_id': None,
            'event_key': receipt['event_key'],
            'input_sha256': receipt['input_sha256'],
            'grant_version': 1,
            'outcome': None,
            'settlement_sha256': None,
            'dispatch_attempts': 1,
        }
        assert 'instruction' not in identity

        store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=receipt['reservation_id'], status='outcome_unknown')
        assert store.claim_continuation_dispatch(task, receipt['reservation_id'],
            trusted_context=context) == {'dispatch': False}
    finally:
        close_fixture(fixture, other)
        if store is not fixture['store']:
            store.close()


def test_same_event_input_conflict_and_second_event_cannot_use_one_request_grant(monkeypatch, tmp_path):
    fixture = setup_granted(monkeypatch, tmp_path)
    store, task, context = fixture['store'], fixture['payload']['task_id'], fixture['context']
    try:
        original = store.claim_conversation_continuation(fixture['conversation'], trusted_context=context)
        event_row = fixture['jobs']._fetch_one(
            'SELECT job_id,status,updated_at,result_artifact_id FROM signal_producer_jobs WHERE job_id=:job',
            {'job': fixture['job_id']})
        event = {'kind': 'signal_producer_jobs', 'data_ready': True,
            'identity': event_row['job_id'], 'status': event_row['status'],
            'updated_at': event_row['updated_at'],
            'result_artifact_id': event_row['result_artifact_id']}
        assert _event_key(event) == original['receipt']['event_key']
        with pytest.raises(IdempotencyConflict, match='input conflicts'):
            store.reserve_continuation_request(task, trusted_context=context, event=event,
                instruction='different read-only request text')

        store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=original['receipt']['reservation_id'], status='settled',
            request_usage=confirmed_request_usage(), settlement_sha256='b' * 64,
            outcome='completed')
        add_ready_event(fixture, key='request-second-ready-event', content={'synthetic': 'second'})
        assert store.claim_conversation_continuation(
            fixture['conversation'], trusted_context=context)['status'] == 'waiting'
        assert store.get_continuation_permission(task, trusted_context=context)['request_state']['request_identity'][
            'reservation_id'] == original['receipt']['reservation_id']
    finally:
        close_fixture(fixture)


def test_exact_run_receipt_and_settlement_are_idempotent_and_keep_usage_facts(monkeypatch, tmp_path):
    fixture = setup_granted(monkeypatch, tmp_path)
    store, task, context = fixture['store'], fixture['payload']['task_id'], fixture['context']
    try:
        intent = store.claim_conversation_continuation(fixture['conversation'], trusted_context=context)
        rid = intent['receipt']['reservation_id']
        assert store.claim_continuation_dispatch(task, rid, trusted_context=context) == {
            'dispatch': True, 'attempt': 1}
        run_id = 'a' * 32
        accepted = store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=rid, status='accepted', run_id=run_id)
        assert accepted['run_id'] == run_id
        with pytest.raises(IdempotencyConflict, match='identity conflicts'):
            store.record_continuation_receipt(task, trusted_context=context,
                reservation_id=rid, status='accepted', run_id='b' * 32)
        with pytest.raises(IdempotencyConflict, match='submitted continuation cannot be rejected'):
            store.record_continuation_receipt(task, trusted_context=context,
                reservation_id=rid, status='rejected')

        usage = confirmed_request_usage(provider_attempts=1)
        settled = store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=rid, status='settled', request_usage=usage,
            settlement_sha256='c' * 64, outcome='completed')
        assert settled['request_usage'] == usage
        assert settled['settlement_sha256'] == 'c' * 64
        assert store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=rid, status='settled', request_usage=usage,
            settlement_sha256='c' * 64, outcome='completed') == settled
        with pytest.raises(IdempotencyConflict, match='settlement conflicts'):
            store.record_continuation_receipt(task, trusted_context=context,
                reservation_id=rid, status='settled', request_usage=usage,
                settlement_sha256='d' * 64, outcome='completed')
        with pytest.raises(ValueError, match='cumulative token'):
            store.record_continuation_receipt(task, trusted_context=context,
                reservation_id=rid, status='settled', charged_tokens=1,
                request_usage=usage, settlement_sha256='c' * 64, outcome='completed')

        identity = store.get_continuation_permission(task, trusted_context=context)['request_state']['request_identity']
        assert identity == {
            'reservation_id': rid, 'status': 'settled', 'run_id': run_id,
            'event_key': intent['receipt']['event_key'], 'input_sha256': intent['receipt']['input_sha256'],
            'grant_version': 1, 'outcome': 'completed', 'settlement_sha256': 'c' * 64,
            'dispatch_attempts': 1,
        }
    finally:
        close_fixture(fixture)


def test_definite_rejection_after_dispatch_consumes_single_request_without_reopening(monkeypatch, tmp_path):
    fixture = setup_granted(monkeypatch, tmp_path)
    store, task, context = fixture['store'], fixture['payload']['task_id'], fixture['context']
    try:
        intent = store.claim_conversation_continuation(fixture['conversation'], trusted_context=context)
        rid = intent['receipt']['reservation_id']
        assert intent['receipt']['status'] == 'reserved'
        assert store.claim_continuation_dispatch(task, rid, trusted_context=context) == {
            'dispatch': True, 'attempt': 1}

        rejected = store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=rid, status='rejected')
        assert rejected['status'] == 'rejected'
        assert rejected['run_id'] is None
        assert rejected['dispatch_attempts'] == 1
        assert rejected.get('request_usage') is None
        assert store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=rid, status='rejected') == rejected

        view = store.get_continuation_permission(task, trusted_context=context)
        assert view['request_state']['requests_reserved'] == 1
        assert view['request_state']['requests_remaining'] == 0
        assert view['request_state']['request_identity']['status'] == 'rejected'
        assert view['request_state']['request_identity']['dispatch_attempts'] == 1
        assert store.claim_continuation_dispatch(task, rid, trusted_context=context) == {'dispatch': False}
        assert store.claim_conversation_continuation(
            fixture['conversation'], trusted_context=context)['status'] == 'waiting'
        assert store.get_continuation_permission(task, trusted_context=context)[
            'request_state']['request_identity']['reservation_id'] == rid
    finally:
        close_fixture(fixture)


def test_revocation_blocks_new_dispatch_but_does_not_discard_reserved_settlement(monkeypatch, tmp_path):
    fixture = setup_granted(monkeypatch, tmp_path)
    store, task, context = fixture['store'], fixture['payload']['task_id'], fixture['context']
    try:
        intent = store.claim_conversation_continuation(fixture['conversation'], trusted_context=context)
        rid = intent['receipt']['reservation_id']
        store.revoke_continuation_permission(task, grant_version=1, trusted_context=context)
        assert store.claim_continuation_dispatch(task, rid, trusted_context=context) == {'dispatch': False}
        # A verified zero-provider outcome can settle a request that never crossed dispatch.
        settled = store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=rid, status='settled', request_usage=confirmed_request_usage(provider_attempts=0),
            settlement_sha256='e' * 64, outcome='completed')
        assert settled['status'] == 'settled'
        assert settled['request_usage']['actual_usage']['usage_source'] == 'no_provider_calls'
        assert store.get_continuation_permission(task, trusted_context=context)['blocked_reason'] == 'permission_revoked'
    finally:
        close_fixture(fixture)


def test_legacy_unknown_liability_is_read_only_but_exactly_settleable(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, context = fixture['store'], fixture['payload']['task_id'], fixture['context']
    old = legacy_reservation(suffix='f')
    legacy_permission = {
        'schema_version': 'task-continuation-permission.v1',
        'idempotency_key': 'historical-confirmation', 'request_sha256': 'a' * 64,
        'grant_version': 1, 'token_limit': 1000, 'max_turns': 2,
        'confirmed_artifact_ids': [fixture['payload']['strategy_version_artifact_id']],
        'confirmed_artifacts': [], 'owner_principal': context['owner_principal'],
        'workspace_id': context['workspace_id'], 'conversation_id': fixture['conversation'],
        'confirmed_by': context['actor_principal'], 'created_at': '2026-01-01T00:00:00+00:00',
        'expires_at': '2027-01-01T00:00:00+00:00', 'revoked_at': None, 'revoked_by': None,
    }
    try:
        store._execute('UPDATE research_tasks SET continuation_permission=:permission,continuation_budget=:rows WHERE task_id=:task',
            {'permission': legacy_permission, 'rows': [old], 'task': task})
        view = store.get_continuation_permission(task, trusted_context=context)
        assert view['blocked_reason'] == 'legacy_continuation_read_only'
        assert store.claim_continuation_dispatch(task, old['reservation_id'], trusted_context=context) == {'dispatch': False}
        with pytest.raises(ValueError, match='legacy continuation permission is read-only'):
            store.create_continuation_permission(task, {
                'idempotency_key': 'fresh-v2',
                'confirmed_artifact_ids': [fixture['payload']['strategy_version_artifact_id']],
            }, trusted_context=context)

        settled = store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=old['reservation_id'], status='settled', charged_tokens=700,
            settlement_sha256='f' * 64)
        assert settled['token_limit'] == 1000
        assert settled['charged_tokens'] == 700
        assert store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=old['reservation_id'], status='settled', charged_tokens=700,
            settlement_sha256='f' * 64) == settled
        with pytest.raises(IdempotencyConflict):
            store.record_continuation_receipt(task, trusted_context=context,
                reservation_id=old['reservation_id'], status='settled', charged_tokens=699,
                settlement_sha256='0' * 64)
    finally:
        close_fixture(fixture)
