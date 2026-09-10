import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.research import IdempotencyConflict, ResearchStore
from tests.test_research_continuation import setup_permission

pytestmark = pytest.mark.skipif(not os.environ.get('BYQ_DATABASE_URL'), reason='isolated PostgreSQL required')


def reserve(store, task, context, event='event-synthetic-1', limit=600):
    return store.reserve_continuation_budget(task, trusted_context=context, grant_version=1,
        event_key=event, input_sha256='a' * 64, token_limit=limit)


def test_concurrent_reservations_share_receipt_and_unknown_survives_reconnect():
    store, task, context, payload = setup_permission()
    other = ResearchStore()
    try:
        store.create_continuation_permission(task, payload, trusted_context=context)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(reserve, s, task, context) for s in (store, other)]
            receipt = futures[0].result()
            assert futures[1].result() == receipt
        store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=receipt['reservation_id'], status='outcome_unknown')
        store.close()
        store = ResearchStore()
        assert reserve(store, task, context)['status'] == 'outcome_unknown'
        with pytest.raises(ValueError, match='unconfirmed'):
            reserve(store, task, context, event='event-synthetic-2')
        with pytest.raises(IdempotencyConflict):
            reserve(store, task, context, limit=601)
        assert 'continuation_budget' not in store.get_task(task)
        view = store.get_continuation_permission(task, trusted_context=context)
        assert view['can_start'] is False
        assert view['blocked_reason'] == 'continuation_result_unconfirmed'
        assert view['budget']['reserved_tokens'] == 600
        assert view['budget']['available_tokens'] == 400
        assert view['budget']['unconfirmed_reservations'] == 1
    finally:
        store.close()
        other.close()


def test_revocation_and_admission_serialize_across_connections():
    store, task, context, payload = setup_permission()
    other = ResearchStore()
    try:
        store.create_continuation_permission(task, payload, trusted_context=context)
        with ThreadPoolExecutor(max_workers=2) as pool:
            admission = pool.submit(reserve, store, task, context)
            revoke = pool.submit(other.revoke_continuation_permission, task,
                grant_version=1, trusted_context=context)
            revoke.result()
            try:
                admitted = admission.result()
            except ValueError as exc:
                assert 'inactive' in str(exc)
                admitted = None
        view = store.get_continuation_permission(task, trusted_context=context)
        assert view['blocked_reason'] == 'permission_revoked'
        assert view['budget']['reserved_tokens'] == (600 if admitted else 0)
        with pytest.raises(ValueError, match='inactive'):
            reserve(other, task, context, event='event-after-revoke')
    finally:
        store.close()
        other.close()


def test_exact_settlement_unique_and_remaining_allowance_cannot_exceed_grant():
    store, task, context, payload = setup_permission()
    try:
        store.create_continuation_permission(task, payload, trusted_context=context)
        receipt = reserve(store, task, context)
        args = dict(trusted_context=context, reservation_id=receipt['reservation_id'])
        store.record_continuation_receipt(task, **args, status='accepted', run_id='1' * 32)
        with pytest.raises(IdempotencyConflict):
            store.record_continuation_receipt(task, **args, status='accepted', run_id='2' * 32)
        with pytest.raises(ValueError):
            store.record_continuation_receipt(task, **args, status='settled', charged_tokens=601, settlement_sha256='b' * 64)
        settled = store.record_continuation_receipt(task, **args, status='settled',
            charged_tokens=400, settlement_sha256='b' * 64)
        assert store.record_continuation_receipt(task, **args, status='settled',
            charged_tokens=400, settlement_sha256='b' * 64) == settled
        assert store.record_continuation_receipt(task, **args, status='outcome_unknown') == settled
        with pytest.raises(IdempotencyConflict):
            store.record_continuation_receipt(task, **args, status='settled',
                charged_tokens=399, settlement_sha256='c' * 64)
        with pytest.raises(ValueError, match='exhausted'):
            reserve(store, task, context, event='event-synthetic-2', limit=601)
        assert reserve(store, task, context, event='event-synthetic-2', limit=600)['token_limit'] == 600
    finally:
        store.close()


def test_revocation_blocks_new_admission_but_keeps_existing_liability_and_settlement():
    store, task, context, payload = setup_permission()
    try:
        store.create_continuation_permission(task, payload, trusted_context=context)
        receipt = reserve(store, task, context)
        store.revoke_continuation_permission(task, grant_version=1, trusted_context=context)
        assert reserve(store, task, context) == receipt
        settled = store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=receipt['reservation_id'], status='settled', charged_tokens=0,
            settlement_sha256='c' * 64)
        assert settled['status'] == 'settled'
        with pytest.raises(ValueError, match='inactive'):
            reserve(store, task, context, event='event-synthetic-2')
    finally:
        store.close()


def test_distinct_concurrent_events_admit_only_one_and_turn_limit_does_not_refund():
    store, task, context, payload = setup_permission()
    other = ResearchStore()
    try:
        store.create_continuation_permission(task, {**payload, 'max_turns': 1}, trusted_context=context)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(reserve, s, task, context, f'event-synthetic-{i}')
                for i, s in enumerate((store, other))]
            receipts = []
            for future in futures:
                try:
                    receipts.append(future.result())
                except ValueError as exc:
                    assert 'unconfirmed' in str(exc)
        assert len(receipts) == 1
        store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=receipts[0]['reservation_id'], status='settled',
            charged_tokens=0, settlement_sha256='c' * 64)
        with pytest.raises(ValueError, match='exhausted'):
            reserve(store, task, context, event='event-synthetic-next')
    finally:
        store.close()
        other.close()
