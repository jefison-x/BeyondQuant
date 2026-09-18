"""Data-ready auto-continuation reuses the task-bound continuation contract.

A completed signal job whose produced signal_snapshot is validated wakes the
original conversation exactly once, without an inferred user token grant. The
normal budgeted F6 permission continues to work unchanged.
"""
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
