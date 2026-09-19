"""Data-ready auto-continuation reuses the task-bound continuation contract.

A completed signal job whose produced signal_snapshot is validated wakes the
original conversation exactly once, without an inferred user token grant. The
normal budgeted F6 permission continues to work unchanged.
"""
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchStore
from tests.workspace_helpers import trusted_agent_context
from tests.test_backtest_task_reconciliation import setup_creation

pytestmark = pytest.mark.skipif(not os.environ.get('BYQ_DATABASE_URL'), reason='isolated PostgreSQL required')

SESSION = 'byq-session-product-user'
TRACE = 'byq-trace-task-receipt'


def setup_ready(monkeypatch, tmp_path, *, outcome='completed'):
    import test_backtest_api
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
    headers = trusted_agent_context('product-user', trace_id=TRACE, session_id=SESSION)
    monkeypatch.setattr(test_backtest_api, '_owner_headers', lambda principal: headers)
    context = {key.removeprefix('x-byq-').replace('-', '_'): value for key, value in headers.items()}
    catalog = ConversationCatalogStore()
    conversation = catalog.create('product-user', SESSION, TRACE)['conversation_id']
    catalog.close()
    store, backtests, jobs, client, payload = setup_creation(monkeypatch, tmp_path)
    created = client.post('/v1/research/backtest-tasks', json=payload)
    assert created.status_code == 202, created.text
    job_id = created.json()['task']['references']['signal_producer_job_id']
    artifact_id = None
    if outcome == 'completed':
        artifact = store.create_artifact({'task_id': payload['task_id'], 'kind': 'signal_snapshot',
            'content': {'synthetic': 'data-ready'}, 'lineage': [], 'trace_id': TRACE,
            'idempotency_key': 'ready-snapshot'})
        store.transition('artifact', artifact['artifact_id'], 'validated', 'ready-validate')
        jobs._execute("""UPDATE signal_producer_jobs SET status='completed', result_artifact_id=:artifact,
            updated_at=now() WHERE job_id=:job""", {'artifact': artifact['artifact_id'], 'job': job_id})
        artifact_id = artifact['artifact_id']
    elif outcome == 'draft':
        artifact = store.create_artifact({'task_id': payload['task_id'], 'kind': 'signal_snapshot',
            'content': {'synthetic': 'unvalidated'}, 'lineage': [], 'trace_id': TRACE,
            'idempotency_key': 'ready-draft-snapshot'})
        jobs._execute("""UPDATE signal_producer_jobs SET status='completed', result_artifact_id=:artifact,
            updated_at=now() WHERE job_id=:job""", {'artifact': artifact['artifact_id'], 'job': job_id})
        artifact_id = artifact['artifact_id']
    else:
        jobs._execute("""UPDATE signal_producer_jobs SET status='failed', error_code='synthetic_failure',
            updated_at=now() WHERE job_id=:job""", {'job': job_id})
    return dict(store=store, backtests=backtests, jobs=jobs, client=client, payload=payload,
                conversation=conversation, context=context, job_id=job_id, artifact_id=artifact_id)


def continuation_budget(store, task_id):
    return store._fetch_one('SELECT continuation_budget FROM research_tasks WHERE task_id=:task',
        {'task': task_id})['continuation_budget']


def continuation_block(store, task_id):
    return store._fetch_one("""SELECT continuation_blocked_reason, continuation_blocked_event_key
        FROM research_tasks WHERE task_id=:task""", {'task': task_id})


def add_ready_event(fixture, *, key, content):
    """Create a second completed signal job with its own validated snapshot."""
    store, jobs, task = fixture['store'], fixture['jobs'], fixture['payload']['task_id']
    template = jobs._fetch_one('SELECT * FROM signal_producer_jobs WHERE job_id=:job',
        {'job': fixture['job_id']})
    artifact = store.create_artifact({'task_id': task, 'kind': 'signal_snapshot',
        'content': content, 'lineage': [], 'trace_id': TRACE, 'idempotency_key': key})
    store.transition('artifact', artifact['artifact_id'], 'validated', key + '-validate')
    job_id = 'signaljob_' + hashlib.sha256(key.encode()).hexdigest()[:32]
    jobs._execute("""INSERT INTO signal_producer_jobs
        (job_id, owner_principal, task_id, experiment_id, strategy_version_artifact_id,
         stock_pool_snapshot_id, status, trace_id, idempotency_key, request_hash,
         created_at, updated_at, result_artifact_id)
        VALUES (:job,:owner,:task,:experiment,:strategy,:snapshot,'completed',:trace,:key,'retry',now(),now(),:artifact)""",
        {'job': job_id, 'owner': template['owner_principal'], 'task': task,
         'experiment': template['experiment_id'], 'strategy': template['strategy_version_artifact_id'],
         'snapshot': template['stock_pool_snapshot_id'], 'trace': TRACE, 'key': key,
         'artifact': artifact['artifact_id']})
    return job_id, artifact['artifact_id']


def grant_retry_permission(store, fixture, *, key, max_turns=8):
    store.create_continuation_permission(fixture['payload']['task_id'], {
        'idempotency_key': key, 'token_limit': max_turns * (1048576 + 8192),
        'max_turns': max_turns,
        'confirmed_artifact_ids': [fixture['payload']['strategy_version_artifact_id']]},
        trusted_context=fixture['context'])
    # The grant must predate the readiness transition for the bounded scan.
    fixture['jobs']._execute("UPDATE signal_producer_jobs SET updated_at=now() WHERE job_id=:job",
        {'job': fixture['job_id']})


def settle_needs_attention(store, fixture, intent):
    return store.record_continuation_receipt(fixture['payload']['task_id'],
        trusted_context=fixture['context'], reservation_id=intent['receipt']['reservation_id'],
        status='settled', charged_tokens=1048576, settlement_sha256='a' * 64,
        outcome='needs_attention')


def test_ready_signal_job_enqueues_exactly_one_data_ready_continuation(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        assert store.claim_conversation_continuation(conversation, trusted_context=context, admit=False) == {
            'status': 'eligible', 'task_id': task}
        intent = store.claim_conversation_continuation(conversation, trusted_context=context)
        assert intent['status'] == 'intent'
        receipt = intent['receipt']
        assert receipt['grant_kind'] == 'data_ready'
        assert receipt['event_key'].startswith('ready-v1:')
        assert fixture['job_id'] in receipt['instruction']
        assert fixture['artifact_id'] in receipt['instruction']
        assert intent['may_dispatch'] is True
        assert intent['reservation']['task_id'] == task
        assert len(continuation_budget(store, task)) == 1
    finally:
        fixture['store'].close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_data_ready_budget_covers_a_bounded_multi_call_turn(monkeypatch, tmp_path):
    from app.research_continuation import (DATA_READY_INPUT_CEILING, DATA_READY_MAX_CALLS,
        DATA_READY_MAX_OUTPUT_TOKENS, DATA_READY_TOKEN_LIMIT)
    per_call = DATA_READY_INPUT_CEILING + DATA_READY_MAX_OUTPUT_TOKENS
    assert DATA_READY_MAX_CALLS >= 2
    assert DATA_READY_TOKEN_LIMIT == DATA_READY_MAX_CALLS * per_call
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        intent = store.claim_conversation_continuation(conversation, trusted_context=context)
        assert intent['status'] == 'intent'
        receipt = intent['receipt']
        assert receipt['grant_kind'] == 'data_ready'
        assert receipt['token_limit'] == DATA_READY_TOKEN_LIMIT
        # Two model calls -- the minimum a tool-calling turn needs -- each charge
        # the conservative per-call ceiling and must fit inside the reservation.
        assert intent['reservation']['token_limit'] >= 2 * per_call
    finally:
        fixture['store'].close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_duplicate_polls_and_restart_never_enqueue_a_second_turn(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    other = ResearchStore()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(
                lambda instance: instance.claim_conversation_continuation(conversation, trusted_context=context),
                (store, other)))
        reservation_id = receipts[0]['receipt']['reservation_id']
        assert reservation_id == receipts[1]['receipt']['reservation_id']
        assert len(continuation_budget(store, task)) == 1
        store.record_continuation_receipt(task, trusted_context=context, reservation_id=reservation_id,
            status='settled', charged_tokens=1048576, settlement_sha256='a' * 64, outcome='completed')
        store.close()
        restarted = ResearchStore()
        try:
            assert restarted.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
            assert len(continuation_budget(restarted, task)) == 1
        finally:
            restarted.close()
    finally:
        other.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_failed_signal_job_never_wakes_the_conversation(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path, outcome='failed')
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        assert store.claim_conversation_continuation(conversation, trusted_context=context, admit=False)['status'] == 'waiting'
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
        assert continuation_budget(store, task) in (None, [])
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_unvalidated_snapshot_is_not_ready(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path, outcome='draft')
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        assert store.claim_conversation_continuation(conversation, trusted_context=context, admit=False)['status'] == 'waiting'
        assert continuation_budget(store, task) in (None, [])
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_foreign_owner_and_unrelated_conversation_never_wake(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        foreign = {**context, 'owner_principal': 'foreign-user', 'actor_principal': 'foreign-user'}
        assert store.claim_conversation_continuation(conversation, trusted_context=foreign)['status'] == 'waiting'
        assert store.claim_conversation_continuation('conversation_' + '0' * 32,
            trusted_context=context)['status'] == 'waiting'
        assert continuation_budget(store, task) in (None, [])
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_data_ready_scope_admits_only_the_original_task(monkeypatch, tmp_path):
    from app.continuation_scope import authorize
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        reservation_id = store.claim_conversation_continuation(
            conversation, trusted_context=context)['receipt']['reservation_id']
        store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=reservation_id, status='outcome_unknown')
        call = {'tool': 'byq_research_get', 'arguments': {'entity_type': 'research_task', 'entity_id': task},
            'root_run_id': 'a' * 32}
        assert authorize(store, reservation_id, call, context)['admitted'] is True
        other = store.create_task({'owner_principal': context['owner_principal'], 'title': 'Other task',
            'objective': 'Unrelated', 'trace_id': context['trace_id'], 'idempotency_key': 'data-ready-other'},
            trusted_context=context)
        assert authorize(store, reservation_id, {**call, 'arguments': {
            'entity_type': 'research_task', 'entity_id': other['task_id']}}, context)['admitted'] is False
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_budgeted_permission_still_reserves_the_ready_event(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        store.create_continuation_permission(task, {'idempotency_key': 'ready-grant',
            'token_limit': 8000000, 'confirmed_artifact_ids': [fixture['payload']['strategy_version_artifact_id']]},
            trusted_context=context)
        # The grant predates the readiness transition in this regression path.
        fixture['jobs']._execute("UPDATE signal_producer_jobs SET updated_at=now() WHERE job_id=:job",
            {'job': fixture['job_id']})
        intent = store.claim_conversation_continuation(conversation, trusted_context=context)
        assert intent['status'] == 'intent'
        assert intent['receipt']['event_key'].startswith('ready-v1:')
        assert intent['receipt'].get('grant_kind') != 'data_ready'
        assert intent['receipt']['token_limit'] == 8000000
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_needs_attention_rearms_on_a_distinct_ready_event(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        grant_retry_permission(store, fixture, key='rearm-grant')
        first = store.claim_conversation_continuation(conversation, trusted_context=context)
        first_key = first['receipt']['event_key']
        assert first_key.startswith('ready-v1:')
        assert settle_needs_attention(store, fixture, first)['outcome'] == 'needs_attention'
        blocked = continuation_block(store, task)
        assert blocked['continuation_blocked_reason'] == 'continuation_needs_attention'
        assert blocked['continuation_blocked_event_key'] == first_key
        # The settled event itself never re-fires while the world is unchanged.
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
        assert len(continuation_budget(store, task)) == 1
        # A new distinct completed job with a new validated snapshot re-arms the task.
        second_job, second_artifact = add_ready_event(fixture, key='ready-snapshot-2',
            content={'synthetic': 'data-ready-2'})
        intent = store.claim_conversation_continuation(conversation, trusted_context=context)
        assert intent['status'] == 'intent'
        second_key = intent['receipt']['event_key']
        assert second_key.startswith('ready-v1:') and second_key != first_key
        assert second_job in intent['receipt']['instruction']
        assert second_artifact in intent['receipt']['instruction']
        assert intent['may_dispatch'] is True
        assert len(continuation_budget(store, task)) == 2
        assert continuation_block(store, task) == {
            'continuation_blocked_reason': None, 'continuation_blocked_event_key': None}
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_needs_attention_rearm_respects_the_turn_cap(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        grant_retry_permission(store, fixture, key='cap-grant', max_turns=1)
        first = store.claim_conversation_continuation(conversation, trusted_context=context)
        settle_needs_attention(store, fixture, first)
        add_ready_event(fixture, key='ready-snapshot-cap', content={'synthetic': 'data-ready-cap'})
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
        assert len(continuation_budget(store, task)) == 1
        assert continuation_block(store, task)['continuation_blocked_reason'] == 'continuation_needs_attention'
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_terminal_task_still_blocks_a_distinct_ready_event(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        grant_retry_permission(store, fixture, key='terminal-grant')
        first = store.claim_conversation_continuation(conversation, trusted_context=context)
        settle_needs_attention(store, fixture, first)
        add_ready_event(fixture, key='ready-snapshot-terminal', content={'synthetic': 'data-ready-terminal'})
        store.transition('research_task', task, 'cancelled', 'retry-cancel')
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
        assert len(continuation_budget(store, task)) == 1
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_rearmed_event_is_admitted_once_across_concurrent_polls_and_restart(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    other = ResearchStore()
    try:
        grant_retry_permission(store, fixture, key='concurrent-grant')
        first = store.claim_conversation_continuation(conversation, trusted_context=context)
        settle_needs_attention(store, fixture, first)
        add_ready_event(fixture, key='ready-snapshot-concurrent',
            content={'synthetic': 'data-ready-concurrent'})
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(
                lambda instance: instance.claim_conversation_continuation(
                    conversation, trusted_context=context),
                (store, other)))
        reservation_id = receipts[0]['receipt']['reservation_id']
        assert reservation_id == receipts[1]['receipt']['reservation_id']
        assert receipts[0]['receipt']['event_key'] != first['receipt']['event_key']
        assert len(continuation_budget(store, task)) == 2
        store.close()
        restarted = ResearchStore()
        try:
            for _ in range(2):
                restarted.claim_conversation_continuation(conversation, trusted_context=context)
            ledger = continuation_budget(restarted, task)
            assert [row['event_key'] for row in ledger] == [
                first['receipt']['event_key'], receipts[0]['receipt']['event_key']]
        finally:
            restarted.close()
    finally:
        other.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_legacy_null_block_recovers_its_event_from_the_settled_ledger(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        grant_retry_permission(store, fixture, key='legacy-grant')
        first = store.claim_conversation_continuation(conversation, trusted_context=context)
        first_key = first['receipt']['event_key']
        settle_needs_attention(store, fixture, first)
        # Simulate a production row written before the block was event-scoped.
        store._execute("UPDATE research_tasks SET continuation_blocked_event_key=NULL WHERE task_id=:task",
            {'task': task})
        blocked = continuation_block(store, task)
        assert blocked['continuation_blocked_reason'] == 'continuation_needs_attention'
        assert blocked['continuation_blocked_event_key'] is None
        # The settled event is still suppressed by its ledger row.
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
        add_ready_event(fixture, key='ready-snapshot-legacy', content={'synthetic': 'data-ready-legacy'})
        intent = store.claim_conversation_continuation(conversation, trusted_context=context)
        assert intent['status'] == 'intent'
        assert intent['receipt']['event_key'] != first_key
        assert len(continuation_budget(store, task)) == 2
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_explicit_task_wide_block_still_blocks_a_distinct_ready_event(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        grant_retry_permission(store, fixture, key='wide-grant')
        first = store.claim_conversation_continuation(conversation, trusted_context=context)
        settle_needs_attention(store, fixture, first)
        store.block_continuation(task, 'continuation_needs_attention', trusted_context=context)
        assert continuation_block(store, task)['continuation_blocked_event_key'] == '*'
        add_ready_event(fixture, key='ready-snapshot-wide', content={'synthetic': 'data-ready-wide'})
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
        assert len(continuation_budget(store, task)) == 1
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_data_ready_rearm_without_a_budget_permission(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        first = store.claim_conversation_continuation(conversation, trusted_context=context)
        assert first['receipt']['grant_kind'] == 'data_ready'
        first_key = first['receipt']['event_key']
        settle_needs_attention(store, fixture, first)
        add_ready_event(fixture, key='ready-snapshot-grantless', content={'synthetic': 'data-ready-grantless'})
        intent = store.claim_conversation_continuation(conversation, trusted_context=context)
        assert intent['status'] == 'intent'
        assert intent['receipt']['grant_kind'] == 'data_ready'
        assert intent['receipt']['event_key'] != first_key
        assert len(continuation_budget(store, task)) == 2
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()
