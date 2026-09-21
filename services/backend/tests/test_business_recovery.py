"""ADR-0084 authoritative business-recovery allocation (Backend).

The concurrency-critical path runs inside the real task-row
``SELECT ... FOR UPDATE`` on the isolated PostgreSQL test database. The tests
prove: the request cannot inject security facts; same fenced loss + same snapshot
allocates exactly once; a retry reuses the original attempt/ordinal; a snapshot
change cannot rewrite it or consume another ordinal; the ordinal cap, unknown
cost, evidence conflict and the model-call floor fail closed; the accepted target
receipt is written back into the in-row attempt aggregate and stale targets are
fenced; and the reservation budget is never double-deducted.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.research import ResearchStore
from tests.test_research_continuation import setup_permission
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.environ.get('BYQ_DATABASE_URL'),
    reason='isolated PostgreSQL required')

LOST = 'b' * 32
BIG = 6_000_000


@pytest.fixture(autouse=True)
def _executor_enabled(monkeypatch):
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')


def _reserve_and_accept(store, task, context, payload, *, run=LOST, limit=BIG, charged=1_048_584):
    store.create_continuation_permission(task, {**payload, 'token_limit': 12_000_000},
        trusted_context=context)
    reservation_id = store.reserve_continuation_budget(task, trusted_context=context, grant_version=1,
        event_key='event-synthetic-1', input_sha256='a' * 64, token_limit=limit)['reservation_id']
    store.record_continuation_receipt(task, trusted_context=context, reservation_id=reservation_id,
        status='accepted', run_id=run,
        **({'charged_tokens': charged} if charged is not None else {}))
    return reservation_id


def _recovery(run=LOST, generation='generation-1', attempt=1, epoch=1, tail=0, digest='a' * 64):
    return {'interrupted_run_id': run, 'interrupted_generation': generation,
            'containment_attempt': attempt, 'interrupted_executor_epoch': epoch,
            'snapshot_tail_sequence': tail, 'snapshot_digest': digest}


def test_forged_policy_fields_are_rejected_by_the_route():
    headers = trusted_agent_context('alice', session_id='session-a', trace_id='trace-a')
    headers['x-byq-actor-principal'] = 'alice'
    client = TestClient(__import__('app.main', fromlist=['app']).app)
    for forged in ({'read_only': True}, {'occurred_calls': []}, {'replayed_calls': []},
                   {'model_call_floor': 1}, {'evidence_conflict': False}):
        body = {'reservation_id': 'continuation_' + 'a' * 32, 'recovery': {**_recovery(), **forged}}
        response = client.post('/internal/task-continuation/task_' + 'b' * 32 + '/dispatch',
            json=body, headers=headers)
        assert response.status_code == 422, forged


def test_forged_loss_run_cannot_obtain_a_carrier():
    store, task, context, payload = setup_permission()
    try:
        reservation_id = _reserve_and_accept(store, task, context, payload)
        outcome = store.claim_continuation_dispatch(task, reservation_id, trusted_context=context,
            recovery=_recovery(run='c' * 32))
        assert outcome['dispatch'] is False
        assert outcome['recovery']['status'] == 'blocked'
        assert outcome['recovery']['reason'] == 'lost_run_not_authoritative'
        # A non-existent reservation cannot recover either.
        missing = store.claim_continuation_dispatch(task, 'continuation_' + 'f' * 32,
            trusted_context=context, recovery=_recovery())
        assert missing['dispatch'] is False
    finally:
        store.close()


def test_same_trigger_allocates_exactly_once_and_retry_reuses_the_attempt():
    store, task, context, payload = setup_permission()
    other = ResearchStore()
    try:
        reservation_id = _reserve_and_accept(store, task, context, payload)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(s.claim_continuation_dispatch, task, reservation_id,
                trusted_context=context, recovery=_recovery()) for s in (store, other)]
            results = [future.result() for future in futures]
        assert all(result['dispatch'] is True for result in results), results
        carriers = [result['recovery_attempt'] for result in results]
        assert carriers[0] == carriers[1]
        assert carriers[0]['ordinal'] == 1
        # A retry (same trigger + same snapshot) reuses the same attempt.
        retry = store.claim_continuation_dispatch(task, reservation_id, trusted_context=context,
            recovery=_recovery())
        assert retry['dispatch'] is True and retry['recovery_attempt'] == carriers[0]
        # A snapshot change for the SAME loss trigger cannot rewrite the attempt
        # and cannot consume another ordinal.
        changed = store.claim_continuation_dispatch(task, reservation_id, trusted_context=context,
            recovery=_recovery(tail=1, digest='c' * 64))
        assert changed['dispatch'] is False
        assert changed['recovery']['reason'] == 'snapshot_changed_for_existing_trigger'
        # A later recovery run that loses again is a NEW fenced loss identity and
        # allocates the next ordinal; the lost run must be an accepted receipt.
        first_run = 'c' * 32
        store.record_continuation_receipt(task, trusted_context=context, reservation_id=reservation_id,
            status='accepted', run_id=first_run, attempt_key=carriers[0]['attempt_key'],
            target_executor_epoch=2, target_generation='generation-target', charged_tokens=1_048_584)
        second = store.claim_continuation_dispatch(task, reservation_id, trusted_context=context,
            recovery=_recovery(run=first_run, generation='generation-2'))
        assert second['dispatch'] is True and second['recovery_attempt']['ordinal'] == 2
        second_run = 'd' * 32
        store.record_continuation_receipt(task, trusted_context=context, reservation_id=reservation_id,
            status='accepted', run_id=second_run, attempt_key=second['recovery_attempt']['attempt_key'],
            target_executor_epoch=2, target_generation='generation-target', charged_tokens=1_048_584)
        third = store.claim_continuation_dispatch(task, reservation_id, trusted_context=context,
            recovery=_recovery(run=second_run, generation='generation-3'))
        assert third['dispatch'] is True and third['recovery_attempt']['ordinal'] == 3
        capped = store.claim_continuation_dispatch(task, reservation_id, trusted_context=context,
            recovery=_recovery(run=second_run, generation='generation-4'))
        assert capped['dispatch'] is False and capped['recovery']['reason'] == 'ordinal_cap'
        # No second reservation and no double-deducted budget.
        view = store.get_continuation_permission(task, trusted_context=context)
        assert view['budget']['turns_reserved'] == 1
    finally:
        store.close()
        other.close()


def test_accepted_receipt_write_back_and_stale_target_fence():
    from app.research import IdempotencyConflict
    store, task, context, payload = setup_permission()
    try:
        reservation_id = _reserve_and_accept(store, task, context, payload)
        outcome = store.claim_continuation_dispatch(task, reservation_id, trusted_context=context,
            recovery=_recovery())
        attempt_key = outcome['recovery_attempt']['attempt_key']
        written = store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=reservation_id, status='accepted', run_id='f' * 32,
            attempt_key=attempt_key, target_executor_epoch=2, target_generation='generation-target')
        assert (written['run_id'], written['target_executor_epoch'],
                written['target_generation']) == ('f' * 32, 2, 'generation-target')
        # Exact retry is idempotent; a stale target epoch/generation is fenced.
        assert store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=reservation_id, status='accepted', run_id='f' * 32,
            attempt_key=attempt_key, target_executor_epoch=2,
            target_generation='generation-target') == written
        with pytest.raises(IdempotencyConflict):
            store.record_continuation_receipt(task, trusted_context=context,
                reservation_id=reservation_id, status='accepted', run_id='f' * 32,
                attempt_key=attempt_key, target_executor_epoch=3,
                target_generation='generation-target')
        with pytest.raises(IdempotencyConflict):
            store.record_continuation_receipt(task, trusted_context=context,
                reservation_id=reservation_id, status='accepted', run_id='f' * 32,
                attempt_key=attempt_key, target_executor_epoch=2,
                target_generation='generation-other')
    finally:
        store.close()


def test_unknown_cost_pauses_and_evidence_conflict_blocks(monkeypatch):
    from app import research_continuation as rc
    store, task, context, payload = setup_permission()
    try:
        reservation_id = _reserve_and_accept(store, task, context, payload, charged=None)
        # A dispatched-but-unreconciled original attempt has an unknown charge:
        # never 0, never refunded, so no new recovery run is eligible.
        store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=reservation_id, status='outcome_unknown')
        paused = store.claim_continuation_dispatch(task, reservation_id, trusted_context=context,
            recovery=_recovery())
        assert paused['dispatch'] is False and paused['recovery']['reason'] == 'unknown_attempt_charge'
        # An authoritative evidence conflict blocks.
        monkeypatch.setattr(rc.ResearchContinuationMixin, '_recovery_policy_facts',
            staticmethod(lambda connection, **kwargs: {
                'gap': False, 'occurred': [], 'replayed': [], 'read_only': True,
                'unresolved': False, 'conflict': True}))
        conflict = store.claim_continuation_dispatch(task, reservation_id, trusted_context=context,
            recovery=_recovery())
        assert conflict['dispatch'] is False
        assert conflict['recovery']['reason'] == 'authoritative_evidence_conflict'
    finally:
        store.close()


def test_policy_facts_are_derived_from_persisted_evidence(monkeypatch):
    from app import research_continuation as rc
    observed = {}

    def fake_execute(connection, statement, params):
        observed[statement.split('FROM', 1)[1].split()[0]] = params
        if 'agent_domain_call_evidence' in statement:
            return [{'sequence': 1, 'task_id': 'task_x', 'action': 'byq_ml_strategy_create',
                     'idempotency_key': 'idem-1', 'request_sha256': 'a' * 64, 'input_sha256': 'b' * 64}]
        return [{'task_id': 'task_x', 'action': 'byq_ml_strategy_create', 'idempotency_key': 'idem-1',
                 'request_sha256': 'a' * 64, 'input_sha256': 'b' * 64, 'status': 'succeeded'}]

    monkeypatch.setattr(rc, 'execute', fake_execute)
    facts = rc.ResearchContinuationMixin._recovery_policy_facts(None, lost_run_id=LOST, task_id='task_x')
    assert observed['agent_domain_call_evidence'] == {'root': LOST}
    assert facts['read_only'] is False
    assert facts['conflict'] is False and facts['unresolved'] is False
    assert facts['occurred'] == facts['replayed']
    # A new-key action is present, so the closed envelope refuses to replay it.
    from packages.contracts import business_recovery as contract
    envelope = contract.admission_envelope(read_only=facts['read_only'],
        replayed_calls=facts['replayed'], occurred_calls=facts['occurred'])
    assert envelope['eligible'] is False
    assert 'new_key_action:byq_ml_strategy_create' in envelope['reasons']


def test_cumulative_exact_charge_is_not_double_deducted():
    from app.research_continuation import ResearchContinuationMixin
    row = {'status': 'settled', 'charged_tokens': 20, 'run_id': 'a' * 32,
           'recovery_attempts': [
               {'status': 'settled', 'charged_tokens': 5, 'run_id': 'b' * 32},
               {'status': 'reserved', 'charged_tokens': None, 'run_id': None}]}
    assert ResearchContinuationMixin._recovery_cumulative_charge(row) == 25
    unknown = {'status': 'outcome_unknown', 'charged_tokens': None, 'run_id': None,
               'recovery_attempts': []}
    assert ResearchContinuationMixin._recovery_cumulative_charge(unknown) is None
    fresh = {'status': 'reserved', 'charged_tokens': None, 'run_id': None,
             'recovery_attempts': []}
    assert ResearchContinuationMixin._recovery_cumulative_charge(fresh) == 0
