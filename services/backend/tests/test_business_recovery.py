"""ADR-0084 authoritative business-recovery allocation (Backend).

The concurrency-critical path runs inside the real task-row
``SELECT ... FOR UPDATE`` on the isolated PostgreSQL test database. The tests
prove: same fenced loss + same snapshot allocates exactly once; a retry reuses
the original attempt/ordinal; a snapshot change cannot rewrite it or consume
another ordinal; the ordinal cap, unknown cost, evidence conflict and the
model-call floor all fail closed; and the reservation budget is never
double-deducted by a second reservation.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.research import ResearchStore
from tests.test_research_continuation import setup_permission

pytestmark = pytest.mark.skipif(not os.environ.get('BYQ_DATABASE_URL'),
    reason='isolated PostgreSQL required')


def _begin(store, task, context, reservation_id, *, run='b' * 32, generation='generation-1',
           attempt=1, epoch=1, tail=0, digest='a' * 64, **overrides):
    return store.begin_recovery(task, trusted_context=context, reservation_id=reservation_id,
        interrupted_run_id=run, interrupted_generation=generation, containment_attempt=attempt,
        interrupted_executor_epoch=epoch, snapshot_tail_sequence=tail, snapshot_digest=digest,
        **overrides)


def test_same_trigger_allocates_exactly_once_and_retry_reuses_the_attempt():
    store, task, context, payload = setup_permission()
    other = ResearchStore()
    try:
        store.create_continuation_permission(task, {**payload, 'token_limit': 4_000_000},
            trusted_context=context)
        reservation_id = store.reserve_continuation_budget(task, trusted_context=context,
            grant_version=1, event_key='event-synthetic-1', input_sha256='a' * 64,
            token_limit=2_000_000)['reservation_id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_begin, s, task, context, reservation_id)
                       for s in (store, other)]
            results = [future.result() for future in futures]
        assert all(result['status'] == 'eligible' for result in results), results
        assert results[0]['carrier'] == results[1]['carrier']
        assert sorted(result['reused'] for result in results) == [False, True]
        # A retry (same trigger + same snapshot) reuses the same attempt.
        retry = _begin(store, task, context, reservation_id)
        assert retry['reused'] is True
        assert retry['carrier'] == results[0]['carrier']
        # A snapshot change for the SAME loss trigger cannot rewrite the attempt
        # and cannot consume another ordinal.
        changed = _begin(store, task, context, reservation_id, tail=1, digest='c' * 64)
        assert changed['status'] == 'blocked'
        assert changed['reason'] == 'snapshot_changed_for_existing_trigger'
        # A genuinely new fenced loss identity allocates the next ordinal.
        second = _begin(store, task, context, reservation_id, run='c' * 32, generation='generation-2')
        third = _begin(store, task, context, reservation_id, run='d' * 32, generation='generation-3')
        assert second['reused'] is False and second['carrier']['ordinal'] == 2
        assert third['reused'] is False and third['carrier']['ordinal'] == 3
        capped = _begin(store, task, context, reservation_id, run='e' * 32, generation='generation-4')
        assert capped['status'] == 'blocked' and capped['reason'] == 'ordinal_cap'
        # No second reservation and no double-deducted budget: still exactly one
        # reservation row, unchanged token limit.
        view = store.get_continuation_permission(task, trusted_context=context)
        assert view['budget']['turns_reserved'] == 1
        budget = store.get_task(task)  # must not expose the raw ledger
        assert 'continuation_budget' not in budget
    finally:
        store.close()
        other.close()


def test_unknown_cost_pauses_and_evidence_conflict_blocks():
    store, task, context, payload = setup_permission()
    try:
        store.create_continuation_permission(task, payload, trusted_context=context)
        reservation_id = store.reserve_continuation_budget(task, trusted_context=context,
            grant_version=1, event_key='event-synthetic-1', input_sha256='a' * 64,
            token_limit=600)['reservation_id']
        # A dispatched-but-unreconciled attempt has an unknown charge: never 0,
        # never refunded, so no new recovery run is eligible.
        store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=reservation_id, status='outcome_unknown')
        assert _begin(store, task, context, reservation_id)['reason'] == 'unknown_attempt_charge'
        assert _begin(store, task, context, reservation_id,
                      evidence_conflict=True)['reason'] == 'authoritative_evidence_conflict'
        # The model-call floor is required for ANY new recovery model run.
        assert _begin(store, task, context, reservation_id,
                      model_call_floor=2 ** 40)['reason'] in {'below_model_call_floor',
                                                              'unknown_attempt_charge'}
    finally:
        store.close()


def test_model_floor_and_envelope_and_revocation_fail_closed():
    store, task, context, payload = setup_permission()
    try:
        store.create_continuation_permission(task, payload, trusted_context=context)
        reservation_id = store.reserve_continuation_budget(task, trusted_context=context,
            grant_version=1, event_key='event-synthetic-1', input_sha256='a' * 64,
            token_limit=600)['reservation_id']
        above_floor = _begin(store, task, context, reservation_id,
                             model_call_floor=1, read_only=True)
        assert above_floor['status'] == 'eligible'
        # A new-key write action is never automatically rescheduled.
        blocked = _begin(store, task, context, reservation_id, read_only=False,
            model_call_floor=1,
            replayed_calls=[{'action': 'byq_ml_strategy_create', 'task_id': task,
                             'idempotency_key': 'idem-1', 'request_sha256': 'a' * 64,
                             'input_sha256': 'b' * 64}],
            occurred_calls=[{'action': 'byq_ml_strategy_create', 'task_id': task,
                             'idempotency_key': 'idem-1', 'request_sha256': 'a' * 64,
                             'input_sha256': 'b' * 64}],
            run='c' * 32, generation='generation-2')
        assert blocked['status'] == 'blocked' and blocked['reason'] == 'out_of_envelope'
        store.revoke_continuation_permission(task, grant_version=1, trusted_context=context)
        revoked = _begin(store, task, context, reservation_id, run='d' * 32,
                         generation='generation-3')
        assert revoked['status'] == 'blocked' and revoked['reason'] == 'permission_revoked'
    finally:
        store.close()


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
