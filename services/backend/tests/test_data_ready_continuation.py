"""Data-ready auto-continuation reuses the task-bound continuation contract.

A completed signal job whose produced signal_snapshot is validated wakes the
original conversation exactly once, without an inferred user token grant. The
normal budgeted F6 permission continues to work unchanged.
"""
import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.conversation_catalog import ConversationCatalogStore
from app.research import IdempotencyConflict, ResearchStore
from packages.contracts.agent_execution_options import default_agent_execution_options
from packages.contracts.continuation_request import (
    continuation_request_usage_v2,
    continuation_reservation_v3,
    unknown_actual_usage_v2,
    unknown_admission_usage_v2,
)
from tests.test_backtest_api import _strategy
from tests.workspace_helpers import trusted_agent_context
from tests.test_backtest_task_reconciliation import setup_creation
from tests.continuation_request_fixtures import confirmed_request_usage

pytestmark = pytest.mark.skipif(not os.environ.get('BYQ_DATABASE_URL'), reason='isolated PostgreSQL required')

SESSION = 'byq-session-product-user'
TRACE = 'byq-trace-task-receipt'


def setup_ready(monkeypatch, tmp_path, *, outcome='completed'):
    from tests import test_backtest_api
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
    headers = trusted_agent_context('product-user', trace_id=TRACE, session_id=SESSION)
    from app import main
    login = main.user_store.login('product-user', 'test-password-123')
    # Research-task creation is runtime-scoped and must bind to the original
    # ProductConversation. The authenticated human session is used only for the
    # separate signal-Job submission request below.
    monkeypatch.setattr(test_backtest_api, '_owner_headers', lambda principal: headers)
    context = {key.removeprefix('x-byq-').replace('-', '_'): value for key, value in headers.items()}
    catalog = ConversationCatalogStore()
    conversation = catalog.create('product-user', SESSION, TRACE)['conversation_id']
    catalog.close()
    store, backtests, jobs, client, payload = setup_creation(monkeypatch, tmp_path)
    task_binding = store._fetch_one('SELECT conversation_id FROM research_tasks WHERE task_id=:task',
        {'task': payload['task_id']})
    assert task_binding['conversation_id'] == conversation
    human_submission_headers = {**headers, 'x-byq-session-id': login['session_id']}
    created = client.post('/v1/research/backtest-tasks', headers=human_submission_headers, json=payload)
    assert created.status_code == 202, created.text
    public_job = created.json()
    job_id = created.json()['task']['references']['signal_producer_job_id']
    human_user = main.user_store._fetch_one('SELECT user_id FROM users WHERE username=:owner',
        {'owner': 'product-user'})
    persisted_job = jobs._fetch_one(
        'SELECT submission_origin FROM signal_producer_jobs WHERE job_id=:job', {'job': job_id})
    assert persisted_job['submission_origin'] == {
        'schema_version': 'signal-job-submission-origin.v1',
        'kind': 'authenticated_human',
        'user_id': str(human_user['user_id']),
        'owner_principal': 'product-user',
        'workspace_id': context['workspace_id'],
        'task_id': payload['task_id'],
        'conversation_id': conversation,
    }
    assert_session_not_exposed(login['session_id'], public_job, persisted_job['submission_origin'])
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
                conversation=conversation, context=context, job_id=job_id, artifact_id=artifact_id,
                public_job=public_job, human_session_id=login['session_id'])


def continuation_budget(store, task_id):
    return store._fetch_one('SELECT continuation_budget FROM research_tasks WHERE task_id=:task',
        {'task': task_id})['continuation_budget']


def continuation_block(store, task_id):
    return store._fetch_one("""SELECT continuation_blocked_reason, continuation_blocked_event_key
        FROM research_tasks WHERE task_id=:task""", {'task': task_id})


def assert_session_not_exposed(session_id, *public_values):
    encoded = json.dumps(public_values, sort_keys=True, default=str)
    if session_id and session_id in encoded:
        raise AssertionError('human auth session was exposed in a public projection or origin snapshot')


def legacy_model_reservation(suffix, *, status='reserved'):
    """Persist a pre-cleanup data-ready model receipt in the disposable DB."""
    now = datetime.now(timezone.utc)
    created = (now - timedelta(minutes=1)).isoformat()
    return {
        'reservation_id': 'continuation_' + suffix * 32,
        'grant_kind': 'data_ready', 'grant_version': None,
        'event_key': 'ready-v1:' + suffix * 64,
        'input_sha256': 'a' * 64, 'token_limit': 8000000,
        'status': status, 'run_id': None, 'charged_tokens': None,
        'settlement_sha256': None, 'created_at': created,
        'instruction': 'legacy data-ready model instruction',
        'dispatch_attempts': 0, 'next_attempt_at': created,
        'reconcile_attempts': 0, 'next_reconcile_at': created,
        'expires_at': (now + timedelta(hours=1)).isoformat(),
    }


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
         created_at, updated_at, result_artifact_id, submission_origin)
        VALUES (:job,:owner,:task,:experiment,:strategy,:snapshot,'completed',:trace,:key,'retry',now(),now(),:artifact,:origin)""",
        {'job': job_id, 'owner': template['owner_principal'], 'task': task,
         'experiment': template['experiment_id'], 'strategy': template['strategy_version_artifact_id'],
         'snapshot': template['stock_pool_snapshot_id'], 'trace': TRACE, 'key': key,
         'artifact': artifact['artifact_id'], 'origin': template.get('submission_origin')})
    return job_id, artifact['artifact_id']


def grant_retry_permission(store, fixture, *, key, max_turns=1):
    store.create_continuation_permission(fixture['payload']['task_id'], {
        'idempotency_key': key,
        'max_turns': max_turns,
        'confirmed_artifact_ids': [fixture['payload']['strategy_version_artifact_id']]},
        trusted_context=fixture['context'])
    # The grant must predate the readiness transition for the bounded scan.
    fixture['jobs']._execute("UPDATE signal_producer_jobs SET updated_at=now() WHERE job_id=:job",
        {'job': fixture['job_id']})


def settle_needs_attention(store, fixture, intent):
    return store.record_continuation_receipt(fixture['payload']['task_id'],
        trusted_context=fixture['context'], reservation_id=intent['receipt']['reservation_id'],
        status='settled', request_usage=confirmed_request_usage(),
        settlement_sha256='a' * 64,
        outcome='needs_attention')


def default_backend_peek(fixture, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    monkeypatch.setattr(main, 'research_store', fixture['store'])
    owner = fixture['context']['owner_principal']
    headers = {
        'x-byq-owner-principal': owner,
        'x-byq-actor-principal': owner,
        'x-byq-workspace-id': fixture['context']['workspace_id'],
    }
    path = f"/internal/task-continuation/{fixture['conversation']}/peek"
    return TestClient(main.app).post(path, headers=headers)


def _v3_runtime_root(fixture, *, close=True, session_id=None, trace_id=None, outcome='completed'):
    """Create a Backend-owned Runtime root for exact settlement evidence tests."""
    from app import main

    store = main.agent_store
    authority = store.current_runtime_authority()
    if authority is None:
        authority = store.rotate_runtime_authority(uuid4().hex)
    conversation = fixture['store']._fetch_one('''SELECT runtime_session_id, trace_id
        FROM product_conversations WHERE conversation_id=:conversation''',
        {'conversation': fixture['conversation']})
    root_id = uuid4().hex
    root_session = session_id or conversation['runtime_session_id']
    root_trace = trace_id or conversation['trace_id']
    identity = {
        'schema_version': 'agent-run-lifecycle.v1',
        'root_run_id': root_id,
        'sequence': 1,
        'outcome': 'active',
    }
    scope = {
        'trusted_owner': fixture['context']['owner_principal'],
        'trusted_workspace': fixture['context']['workspace_id'],
        'trusted_session_id': root_session,
        'trusted_trace_id': root_trace,
        'trusted_boot_id': authority['boot_id'],
    }
    store.consume_runtime_lifecycle_event(identity, **scope)
    if close:
        store.close_runtime_root(root_id, boot_id=authority['boot_id'], sequence=2,
            outcome=outcome, event_sha256='d' * 64)
    return root_id, store, authority['boot_id']


def _v3_usage(carrier):
    return continuation_request_usage_v2(
        execution_profile=carrier['execution_profile'],
        admission_usage=unknown_admission_usage_v2(),
        actual_usage=unknown_actual_usage_v2())


def _v3_settlement_sha256(reservation_id, carrier, run_id, outcome, usage):
    runtime_receipt = {
        'reservation_id': reservation_id,
        'idempotency_key': carrier['idempotency_key'],
        'status': 'settled',
        'run_id': run_id,
        'outcome': outcome,
        'request_usage': usage,
    }
    return hashlib.sha256(json.dumps(
        runtime_receipt, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def reserve_v3(fixture, *, signal_job_id=None, conversation_id=None, context=None):
    return fixture['store'].reserve_default_continuation_v3(
        conversation_id or fixture['conversation'],
        signal_job_id=signal_job_id or fixture['job_id'],
        trusted_context=context or fixture['context'])


def trusted_v3_tool_context(fixture):
    runtime_identity = fixture['store']._fetch_one(
        'SELECT runtime_session_id, trace_id FROM product_conversations WHERE conversation_id=:conversation',
        {'conversation': fixture['conversation']})
    context = {**fixture['context'], 'session_id': runtime_identity['runtime_session_id'],
        'trace_id': runtime_identity['trace_id']}
    assert context['session_id'] == fixture['context']['session_id']
    if context['session_id'] == fixture['human_session_id']:
        raise AssertionError('Runtime and authenticated-human session identities must be distinct')
    return context


def stable_v3_event_key(fixture, signal_job_id):
    job = fixture['jobs']._fetch_one(
        'SELECT result_artifact_id FROM signal_producer_jobs WHERE job_id=:job',
        {'job': signal_job_id})
    artifact = fixture['store']._fetch_one(
        'SELECT content_sha256 FROM artifacts WHERE artifact_id=:artifact',
        {'artifact': job['result_artifact_id']})
    probe = continuation_reservation_v3(
        owner_principal=fixture['context']['owner_principal'],
        workspace_id=fixture['context']['workspace_id'],
        conversation_id=fixture['conversation'],
        task_id=fixture['payload']['task_id'],
        signal_job_id=signal_job_id,
        result_artifact_id=job['result_artifact_id'],
        result_artifact_content_sha256=artifact['content_sha256'],
        options=default_agent_execution_options(), options_revision=0,
        event_key='ready-v1:' + '0' * 64)
    return 'ready-v1:' + probe['idempotency_key'].removeprefix('task-ready-event:')


def test_ready_signal_job_enqueues_exactly_one_data_ready_continuation(monkeypatch, tmp_path):
    """ADR-0085 P0: a grantless data-ready event notifies deterministically.

    Without an explicit task/plan grant the reducer must NOT start a generic
    model turn. It advances the durable progress and records an at-most-once
    notification carrying the exact Backend-derived next action.
    """
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        assert store.claim_conversation_continuation(conversation, trusted_context=context, admit=False) == {
            'status': 'eligible', 'task_id': task}
        intent = store.claim_conversation_continuation(conversation, trusted_context=context)
        assert intent['status'] == 'notified'
        receipt = intent['receipt']
        assert receipt['grant_kind'] == 'data_ready_notification'
        assert receipt['event_key'].startswith('ready-v1:')
        assert receipt['token_limit'] == 0
        # No model grant, no dispatchable reservation and no instruction.
        assert receipt['instruction'] is None
        assert 'reservation' not in intent
        assert receipt['executable']['backtest_task_id'].startswith('backtesttask_')
        assert receipt['executable']['next_action'] in {'create', 'execute', 'wait', 'review_result'}
        assert intent['executable']['references']['signal_producer_job_id'] == fixture['job_id']
        assert intent['executable']['references']['signal_snapshot_artifact_id'] == fixture['artifact_id']
        assert receipt['outcome'] == 'notified'
        assert len(continuation_budget(store, task)) == 1
    finally:
        fixture['store'].close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_grantless_data_ready_notification_records_zero_model_liability(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        intent = store.claim_conversation_continuation(conversation, trusted_context=context)
        assert intent['status'] == 'notified'
        receipt = intent['receipt']
        assert receipt['grant_kind'] == 'data_ready_notification'
        assert receipt['event_key'].startswith('ready-v1:')
        assert receipt['instruction'] is None
        assert receipt['run_id'] is None
        # Notifications are settled immediately and never enter model dispatch.
        assert receipt['token_limit'] == 0
        assert receipt['charged_tokens'] == 0
        assert receipt['status'] == 'settled'
        assert 'reservation' not in intent
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
        # Exactly one concurrent caller creates the notification; the other sees
        # 'waiting' because the settled event is already recorded. No second
        # deterministic notification and no model turn is produced.
        notified = [item for item in receipts if item['status'] == 'notified']
        assert len(notified) == 1
        assert all(item['status'] in {'notified', 'waiting'} for item in receipts)
        assert notified[0]['receipt']['grant_kind'] == 'data_ready_notification'
        assert len(continuation_budget(store, task)) == 1
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
        # ADR-0085 P0: grantless data-ready is notify-only, so the task-bound
        # scope check is exercised through an explicit budgeted continuation.
        store.create_continuation_permission(task, {
            'max_turns': 1, 'valid_seconds': 86400,
            'idempotency_key': 'data-ready-scope-grant',
            'confirmed_artifact_ids': [fixture['payload']['strategy_version_artifact_id']]},
            trusted_context=context)
        # The grant must predate the readiness transition for the bounded scan.
        fixture['jobs']._execute("UPDATE signal_producer_jobs SET updated_at=now() WHERE job_id=:job",
            {'job': fixture['job_id']})
        reservation_id = store.claim_conversation_continuation(
            conversation, trusted_context=context)['receipt']['reservation_id']
        assert store.claim_continuation_dispatch(task, reservation_id,
            trusted_context=context) == {'dispatch': True, 'attempt': 1}
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
            'confirmed_artifact_ids': [fixture['payload']['strategy_version_artifact_id']]},
            trusted_context=context)
        # The grant predates the readiness transition in this regression path.
        fixture['jobs']._execute("UPDATE signal_producer_jobs SET updated_at=now() WHERE job_id=:job",
            {'job': fixture['job_id']})
        intent = store.claim_conversation_continuation(conversation, trusted_context=context)
        assert intent['status'] == 'intent'
        assert intent['receipt']['event_key'].startswith('ready-v1:')
        assert intent['receipt'].get('grant_kind') != 'data_ready'
        assert intent['receipt']['schema_version'] == 'task-continuation-reservation.v2'
        assert 'token_limit' not in intent['receipt']
        assert intent['receipt']['dispatch_attempts'] == 0
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


@pytest.mark.parametrize('later_grant', [False, True])
def test_legacy_data_ready_model_receipt_never_dispatches_or_authorizes(
        monkeypatch, tmp_path, later_grant):
    from app.continuation_scope import authorize

    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    reserved = legacy_model_reservation('c', status='reserved')
    unknown = legacy_model_reservation('d', status='outcome_unknown')
    try:
        store._execute('UPDATE research_tasks SET continuation_budget=:budget WHERE task_id=:task',
            {'task': task, 'budget': [reserved, unknown]})
        if later_grant:
            # The historical reservation predates this explicit human grant.
            with pytest.raises(ValueError, match='legacy continuation liability'):
                grant_retry_permission(store, fixture, key='grant-after-legacy-reservation')

        intent = store.claim_conversation_continuation(conversation, trusted_context=context)
        dispatch = store.claim_continuation_dispatch(task, reserved['reservation_id'],
            trusted_context=context)
        call = {'tool': 'byq_research_get',
            'arguments': {'entity_type': 'research_task', 'entity_id': task},
            'root_run_id': 'e' * 32}
        try:
            authorization = authorize(store, unknown['reservation_id'], call, context)
            authorization_denied = authorization.get('admitted') is not True
        except ValueError as exc:
            assert str(exc) == 'continuation action is no longer admitted'
            authorization_denied = True

        persisted = {row['reservation_id']: row for row in continuation_budget(store, task)}
        assert intent['status'] == 'intent'
        assert intent['may_dispatch'] is False
        assert dispatch == {'dispatch': False}
        assert authorization_denied is True
        assert persisted[reserved['reservation_id']]['status'] == 'reserved'
        assert persisted[reserved['reservation_id']]['dispatch_attempts'] == 0
        assert persisted[unknown['reservation_id']]['status'] == 'outcome_unknown'
        assert persisted[unknown['reservation_id']]['run_id'] is None
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_needs_attention_request_cannot_rearm_on_a_distinct_ready_event(monkeypatch, tmp_path):
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
        # A fresh ready event cannot renew or replenish the one-request grant.
        second_job, second_artifact = add_ready_event(fixture, key='ready-snapshot-2',
            content={'synthetic': 'data-ready-2'})
        assert second_job != fixture['job_id'] and second_artifact != fixture['artifact_id']
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
        assert len(continuation_budget(store, task)) == 1
        assert continuation_block(store, task)['continuation_blocked_event_key'] == first_key
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


def test_active_request_stays_at_most_once_across_concurrent_polls_and_restart(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    other = ResearchStore()
    try:
        grant_retry_permission(store, fixture, key='concurrent-grant')
        first = store.claim_conversation_continuation(conversation, trusted_context=context)
        add_ready_event(fixture, key='ready-snapshot-concurrent',
            content={'synthetic': 'data-ready-concurrent'})
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(
                lambda instance: instance.claim_conversation_continuation(
                    conversation, trusted_context=context),
                (store, other)))
        intents = [reply for reply in receipts if reply['status'] == 'intent']
        waits = [reply for reply in receipts if reply['status'] == 'waiting']
        assert len(intents) == 1
        assert len(waits) == 1
        reservation_id = intents[0]['receipt']['reservation_id']
        assert reservation_id == first['receipt']['reservation_id']
        assert intents[0]['receipt']['event_key'] == first['receipt']['event_key']
        assert len(continuation_budget(store, task)) == 1
        assert store.claim_continuation_dispatch(task, reservation_id,
            trusted_context=context) == {'dispatch': True, 'attempt': 1}
        assert other.claim_continuation_dispatch(task, reservation_id,
            trusted_context=context) == {'dispatch': False}
        store.close()
        restarted = ResearchStore()
        try:
            replies = [restarted.claim_conversation_continuation(
                conversation, trusted_context=context) for _ in range(2)]
            for reply in replies:
                if reply['status'] == 'intent':
                    assert reply['receipt']['reservation_id'] == reservation_id
                    assert reply['may_dispatch'] is False
                else:
                    assert reply['status'] == 'waiting'
            ledger = continuation_budget(restarted, task)
            assert len(ledger) == 1
            assert ledger[0]['event_key'] == first['receipt']['event_key']
            assert ledger[0]['reservation_id'] == reservation_id
            assert ledger[0]['status'] == 'outcome_unknown'
            assert ledger[0]['dispatch_attempts'] == 1
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
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
        assert len(continuation_budget(store, task)) == 1
        assert continuation_block(store, task)['continuation_blocked_reason'] == 'continuation_needs_attention'
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
        assert first['receipt']['grant_kind'] == 'data_ready_notification'
        first_key = first['receipt']['event_key']
        # A distinct data-ready event re-arms a second deterministic notification
        # without any model grant and without a needs_attention block.
        add_ready_event(fixture, key='ready-snapshot-grantless', content={'synthetic': 'data-ready-grantless'})
        intent = store.claim_conversation_continuation(conversation, trusted_context=context)
        assert intent['status'] == 'notified'
        assert intent['receipt']['grant_kind'] == 'data_ready_notification'
        assert intent['receipt']['event_key'] != first_key
        assert len(continuation_budget(store, task)) == 2
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_v3_reservation_uses_exact_validated_signal_job_without_legacy_grant(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task = fixture['store'], fixture['payload']['task_id']
    try:
        entry = reserve_v3(fixture)
        reservation = entry['reservation']
        assert entry['schema_version'] == 'task-continuation-ledger-entry.v1'
        assert entry['status'] == 'reserved'
        assert entry['event_key'] == reservation['event_key']
        assert entry['signal_job_id'] == fixture['job_id']
        assert reservation['schema_version'] == 'task-continuation-reservation.v3'
        assert reservation['owner_principal'] == fixture['context']['owner_principal']
        assert reservation['workspace_id'] == fixture['context']['workspace_id']
        assert reservation['conversation_id'] == fixture['conversation']
        assert reservation['task_id'] == task
        assert reservation['signal_job_id'] == fixture['job_id']
        assert reservation['signal_job_status'] == 'completed'
        assert reservation['result_artifact_id'] == fixture['artifact_id']
        assert reservation['result_artifact_kind'] == 'signal_snapshot'
        assert reservation['result_artifact_status'] == 'validated'
        job = fixture['jobs']._fetch_one('''SELECT job_id, task_id, owner_principal,
            workspace_id, status, result_artifact_id, submission_origin FROM signal_producer_jobs WHERE job_id=:job''',
            {'job': fixture['job_id']})
        assert job['submission_origin'] == {
            'schema_version': 'signal-job-submission-origin.v1',
            'kind': 'authenticated_human',
            'user_id': str(fixture['jobs']._fetch_one(
                'SELECT user_id FROM users WHERE username=:owner',
                {'owner': fixture['context']['owner_principal']})['user_id']),
            'owner_principal': fixture['context']['owner_principal'],
            'workspace_id': fixture['context']['workspace_id'],
            'task_id': job['task_id'],
            'conversation_id': fixture['conversation'],
        }
        assert_session_not_exposed(fixture['human_session_id'],
            fixture['public_job'], job['submission_origin'])
        artifact = store._fetch_one('''SELECT artifact_id, task_id, owner_principal,
            workspace_id, kind, status, content_sha256 FROM artifacts WHERE artifact_id=:artifact''',
            {'artifact': fixture['artifact_id']})
        identity = {
            'schema_version': 'task-ready-event-idempotency.v1',
            'owner_principal': job['owner_principal'],
            'workspace_id': job['workspace_id'],
            'conversation_id': fixture['conversation'],
            'task_id': job['task_id'],
            'signal_job_id': job['job_id'],
        }
        event_digest = hashlib.sha256(json.dumps(
            identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        expected_event_key = 'ready-v1:' + event_digest
        assert reservation['event_key'] == expected_event_key
        source_facts = {
            'schema_version': 'task-ready-source-facts.v1',
            'owner_principal': job['owner_principal'],
            'workspace_id': job['workspace_id'],
            'conversation_id': fixture['conversation'],
            'task_id': job['task_id'],
            'event_key': expected_event_key,
            'signal_job_id': job['job_id'],
            'signal_job_status': job['status'],
            'result_artifact_id': artifact['artifact_id'],
            'result_artifact_kind': artifact['kind'],
            'result_artifact_status': artifact['status'],
            'result_artifact_content_sha256': artifact['content_sha256'],
        }
        expected_source_sha = hashlib.sha256(json.dumps(
            source_facts, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        assert reservation['source_fact_sha256'] == expected_source_sha
        assert reservation['execution_profile']['options_revision'] == 0
        assert reservation['execution_profile']['options']['auto_continue'] is True
        expected_limit_fields = {
            'max_provider_calls', 'max_attempts', 'max_concurrent', 'max_input_bytes',
            'max_total_input_bytes', 'max_output_tokens', 'max_total_output_tokens',
            'max_tool_payload_bytes', 'max_total_tool_payload_bytes', 'max_tool_calls',
            'max_runtime_seconds',
        }
        assert set(reservation['request_limits']) == expected_limit_fields
        assert all(reservation['request_limits'][key] is None for key in expected_limit_fields)
        assert 'grant_version' not in reservation and 'expires_at' not in reservation
        assert entry['reservation_id'].startswith('continuation_')
        assert continuation_budget(store, task) == [entry]
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_v3_tool_authorization_admits_exact_reads_and_blocks_wrong_target(monkeypatch, tmp_path):
    from app.continuation_scope import authorize
    from app.backtest_task import task_id_from_signal_job

    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, context = fixture['store'], fixture['payload']['task_id'], fixture['context']
    try:
        entry = reserve_v3(fixture)
        assert store.claim_continuation_dispatch(task, entry['reservation_id'],
            trusted_context=context) == {'dispatch': True, 'attempt': 1}
        tool_context = trusted_v3_tool_context(fixture)
        root_id = 'a' * 32

        research_read = {'tool': 'byq_research_get',
            'arguments': {'entity_type': 'research_task', 'entity_id': task},
            'root_run_id': root_id}
        expected = {'schema_version': 'continuation-action-admission.v1', 'admitted': True,
            'reservation_id': entry['reservation_id'], 'task_id': task}
        assert authorize(store, entry['reservation_id'], research_read, tool_context) == expected

        backtest_read = {'tool': 'byq_backtest_task_get',
            'arguments': {'backtest_task_id': task_id_from_signal_job(fixture['job_id'])},
            'root_run_id': root_id}
        assert authorize(store, entry['reservation_id'], backtest_read, tool_context) == expected

        other = store.create_task({'owner_principal': context['owner_principal'],
            'title': 'Other task', 'objective': 'Unrelated', 'trace_id': context['trace_id'],
            'idempotency_key': 'v3-tool-wrong-target'}, trusted_context=context)
        before = continuation_budget(store, task)
        denied = authorize(store, entry['reservation_id'], {**research_read,
            'arguments': {'entity_type': 'research_task', 'entity_id': other['task_id']}}, tool_context)
        assert denied == {'schema_version': 'continuation-action-admission.v1', 'admitted': False,
            'reservation_id': entry['reservation_id'], 'task_id': task}
        block = continuation_block(store, task)
        assert block['continuation_blocked_reason'] == 'continuation_needs_attention'
        assert block['continuation_blocked_event_key'] == entry['event_key']
        after = continuation_budget(store, task)
        assert json.dumps(after, sort_keys=True, separators=(',', ':')).encode() == json.dumps(
            before, sort_keys=True, separators=(',', ':')).encode()
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_v3_tool_authorization_refuses_cancel_requested_accepted_reservation(monkeypatch, tmp_path):
    from app.continuation_scope import authorize

    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, context = fixture['store'], fixture['payload']['task_id'], fixture['context']
    try:
        entry = reserve_v3(fixture)
        assert store.claim_continuation_dispatch(task, entry['reservation_id'],
            trusted_context=context) == {'dispatch': True, 'attempt': 1}
        tool_context = trusted_v3_tool_context(fixture)
        call = {'tool': 'byq_research_get',
            'arguments': {'entity_type': 'research_task', 'entity_id': task},
            'root_run_id': 'b' * 32}
        assert authorize(store, entry['reservation_id'], call, tool_context)['admitted'] is True

        cancelled = store.cancel_default_continuation_v3(fixture['conversation'],
            entry['reservation_id'], trusted_context=context)
        assert cancelled == {'reservation_id': entry['reservation_id'],
            'cancel_requested': True, 'status': 'accepted'}
        before = continuation_budget(store, task)
        assert before[0]['status'] == 'accepted'
        assert before[0]['cancel_requested_at'] is not None
        before_bytes = json.dumps(before, sort_keys=True, separators=(',', ':')).encode()
        with pytest.raises(ValueError, match='continuation action is no longer admitted'):
            authorize(store, entry['reservation_id'], call, tool_context)
        after = continuation_budget(store, task)
        assert json.dumps(after, sort_keys=True, separators=(',', ':')).encode() == before_bytes
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_signal_job_origin_requires_a_verified_human_session(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app import main

    fixture = setup_ready(monkeypatch, tmp_path)
    store, client = fixture['store'], fixture['client']
    base_headers = dict(client.headers)
    try:
        no_session_headers = {key: value for key, value in base_headers.items()
            if key != 'x-byq-session-id'}
        before = fixture['jobs']._fetch_one(
            'SELECT count(*) AS count FROM signal_producer_jobs WHERE task_id=:task',
            {'task': fixture['payload']['task_id']})['count']
        denied = TestClient(main.app).post('/v1/research/backtest-tasks',
            headers=no_session_headers,
            json={**fixture['payload'], 'idempotency_key': 'origin-missing-context-session'})
        assert denied.status_code == 401
        assert fixture['jobs']._fetch_one(
            'SELECT count(*) AS count FROM signal_producer_jobs WHERE task_id=:task',
            {'task': fixture['payload']['task_id']})['count'] == before

        other_context = trusted_agent_context('origin-other-human')
        other_login = main.user_store.login('origin-other-human', 'test-password-123')
        expired_login = main.user_store.login('product-user', 'test-password-123')
        main.user_store._execute('''UPDATE auth_sessions SET expires_at=now()-interval '1 second'
            WHERE session_id=:session''', {'session': expired_login['session_id']})
        unknown_session_id = 'session_' + uuid4().hex
        assert main.user_store._fetch_one(
            'SELECT session_id FROM auth_sessions WHERE session_id=:session',
            {'session': unknown_session_id}) is None

        cases = [
            ('runtime_session', fixture['context']['session_id'], {}),
            ('unknown_session', unknown_session_id, {}),
            ('expired_session', expired_login['session_id'], {}),
            ('wrong_owner_session', other_login['session_id'], {}),
            ('product_token_bootstrap', unknown_session_id, {
                'authorization': 'Bearer synthetic-bootstrap-token',
                'x-byq-product-token': 'synthetic-bootstrap-token',
                'x-byq-product-human-actor': 'true',
            }),
        ]
        assert other_context['x-byq-owner-principal'] != base_headers['x-byq-owner-principal']
        for case, session_id, extra_headers in cases:
            headers = {**base_headers, **extra_headers, 'x-byq-session-id': session_id}
            response = client.post('/v1/research/backtest-tasks', headers=headers, json={
                **fixture['payload'], 'idempotency_key': 'origin-' + case})
            assert response.status_code == 202, response.text
            public_projection = response.json()
            assert 'submission_origin' not in json.dumps(public_projection, sort_keys=True)
            assert_session_not_exposed(session_id, public_projection)
            job_id = public_projection['task']['references']['signal_producer_job_id']
            persisted = fixture['jobs']._fetch_one(
                'SELECT submission_origin FROM signal_producer_jobs WHERE job_id=:job',
                {'job': job_id})
            assert persisted['submission_origin'] is None
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_v3_reservation_rejects_wrong_scope_and_unvalidated_artifact(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path, outcome='draft')
    store, task, conversation = (
        fixture['store'], fixture['payload']['task_id'], fixture['conversation'])
    try:
        foreign = {**fixture['context'], 'owner_principal': 'foreign-user'}
        with pytest.raises(ValueError):
            reserve_v3(fixture, context=foreign)
        foreign_workspace = {**fixture['context'], 'workspace_id': 'workspace_' + '0' * 32}
        with pytest.raises(ValueError):
            reserve_v3(fixture, context=foreign_workspace)
        with pytest.raises(ValueError, match='original bound conversation'):
            reserve_v3(fixture, conversation_id='conversation_' + '0' * 32)
        with pytest.raises(ValueError, match='not validated'):
            reserve_v3(fixture)
        fixture['jobs']._execute('UPDATE signal_producer_jobs SET result_artifact_id=:artifact WHERE job_id=:job',
            {'artifact': fixture['payload']['strategy_version_artifact_id'], 'job': fixture['job_id']})
        with pytest.raises(ValueError, match='not validated'):
            reserve_v3(fixture)
        assert continuation_budget(store, task) in (None, [])

        def create_task_chain(client, key, trace_id):
            created_task = client.post('/v1/research/tasks', json={
                'owner_principal': 'product-user', 'title': f'v3 scope {key}',
                'objective': 'Create a scoped signal fixture', 'trace_id': trace_id,
                'idempotency_key': f'v3-scope-task-{key}',
            })
            assert created_task.status_code == 201, created_task.text
            task_row = created_task.json()
            draft_response = client.post('/v1/research/strategies/validate', json={
                'task_id': task_row['task_id'], 'strategy': _strategy(), 'trace_id': trace_id,
                'idempotency_key': f'v3-scope-draft-{key}',
            })
            assert draft_response.status_code == 201, draft_response.text
            version_response = client.post('/v1/research/strategies/versions', json={
                'task_id': task_row['task_id'],
                'draft_artifact_id': draft_response.json()['artifact']['artifact_id'],
                'trace_id': trace_id, 'idempotency_key': f'v3-scope-version-{key}',
            })
            assert version_response.status_code == 201, version_response.text
            approval_response = client.post('/v1/research/strategies/approvals', json={
                'task_id': task_row['task_id'],
                'strategy_version_artifact_id': version_response.json()['artifact']['artifact_id'],
                'reviewer_principal': 'product-user', 'decision': 'approved',
                'trace_id': trace_id, 'idempotency_key': f'v3-scope-approval-{key}',
            })
            assert approval_response.status_code == 201, approval_response.text
            return task_row, version_response.json()['artifact']

        def create_completed_job(client, chain_task, version, key, trace_id):
            # The task was created under this conversation's Runtime identity;
            # submit the Job as the authenticated human without rebinding it.
            human_headers = {**dict(client.headers),
                'x-byq-session-id': fixture['human_session_id']}
            created = client.post('/v1/research/backtest-tasks', headers=human_headers, json={
                **fixture['payload'], 'task_id': chain_task['task_id'],
                'strategy_version_artifact_id': version['artifact_id'],
                'idempotency_key': f'v3-scope-job-{key}',
            })
            assert created.status_code == 202, created.text
            job_id = created.json()['task']['references']['signal_producer_job_id']
            task_binding = store._fetch_one(
                'SELECT conversation_id FROM research_tasks WHERE task_id=:task',
                {'task': chain_task['task_id']})
            origin = fixture['jobs']._fetch_one(
                'SELECT submission_origin FROM signal_producer_jobs WHERE job_id=:job',
                {'job': job_id})['submission_origin']
            assert origin['kind'] == 'authenticated_human'
            assert origin['task_id'] == chain_task['task_id']
            assert origin['conversation_id'] == task_binding['conversation_id']
            assert_session_not_exposed(fixture['human_session_id'], origin)
            snapshot = store.create_artifact({
                'task_id': chain_task['task_id'], 'kind': 'signal_snapshot',
                'content': {'synthetic': f'v3-scope-{key}'}, 'lineage': [],
                'trace_id': trace_id, 'idempotency_key': f'v3-scope-snapshot-{key}',
            })
            store.transition('artifact', snapshot['artifact_id'], 'validated',
                f'v3-scope-validate-{key}')
            fixture['jobs']._execute("""UPDATE signal_producer_jobs
                SET status='completed', result_artifact_id=:artifact, updated_at=now()
                WHERE job_id=:job""", {'artifact': snapshot['artifact_id'], 'job': job_id})
            return job_id, snapshot['artifact_id']

        def assert_valid_job_lineage(job_id, *, expected_task, expected_conversation, expected_artifact):
            lineage = fixture['jobs']._fetch_one("""SELECT j.task_id, j.owner_principal,
                    j.workspace_id, j.status, j.result_artifact_id, t.conversation_id,
                    a.task_id AS artifact_task_id, a.owner_principal AS artifact_owner,
                    a.workspace_id AS artifact_workspace, a.kind AS artifact_kind,
                    a.status AS artifact_status
                FROM signal_producer_jobs j
                JOIN research_tasks t ON t.task_id=j.task_id
                JOIN artifacts a ON a.artifact_id=j.result_artifact_id
                WHERE j.job_id=:job""", {'job': job_id})
            assert lineage == {
                'task_id': expected_task,
                'owner_principal': fixture['context']['owner_principal'],
                'workspace_id': fixture['context']['workspace_id'],
                'status': 'completed',
                'result_artifact_id': expected_artifact,
                'conversation_id': expected_conversation,
                'artifact_task_id': expected_task,
                'artifact_owner': fixture['context']['owner_principal'],
                'artifact_workspace': fixture['context']['workspace_id'],
                'artifact_kind': 'signal_snapshot',
                'artifact_status': 'validated',
            }

        client = fixture['client']
        original_headers = dict(client.headers)
        cross_session = 'byq-session-v3-cross-conversation'
        cross_trace = 'byq-trace-v3-cross-conversation'
        catalog = ConversationCatalogStore()
        cross_conversation = catalog.create('product-user', cross_session, cross_trace)['conversation_id']
        catalog.close()
        client.headers.update({
            'x-byq-session-id': cross_session, 'x-byq-trace-id': cross_trace,
            'x-byq-dsh-run-id': 'byq-run-v3-cross-conversation',
        })
        try:
            cross_task, cross_version = create_task_chain(client, 'cross-conversation', cross_trace)
            cross_job, cross_artifact = create_completed_job(
                client, cross_task, cross_version, 'cross-conversation', cross_trace)
            assert_valid_job_lineage(cross_job, expected_task=cross_task['task_id'],
                expected_conversation=cross_conversation, expected_artifact=cross_artifact)
        finally:
            client.headers.update(original_headers)

        cross_before = continuation_budget(store, cross_task['task_id'])
        original_before = continuation_budget(store, task)
        with pytest.raises(ValueError, match='original bound conversation'):
            reserve_v3(fixture, signal_job_id=cross_job)
        assert continuation_budget(store, task) == original_before
        assert continuation_budget(store, cross_task['task_id']) == cross_before

        # The method derives the owning Task from the signal Job, so another
        # valid Task bound to the same conversation is independently eligible.
        same_task, same_version = create_task_chain(client, 'same-conversation', TRACE)
        same_job, same_artifact = create_completed_job(
            client, same_task, same_version, 'same-conversation', TRACE)
        assert_valid_job_lineage(same_job, expected_task=same_task['task_id'],
            expected_conversation=conversation, expected_artifact=same_artifact)
        same_before = continuation_budget(store, same_task['task_id'])
        same_entry = reserve_v3(fixture, signal_job_id=same_job)
        assert same_entry['reservation']['task_id'] == same_task['task_id']
        assert continuation_budget(store, task) == original_before
        assert continuation_budget(store, same_task['task_id']) == [*(same_before or []), same_entry]
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_v3_concurrent_claims_persist_one_reservation(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task = fixture['store'], fixture['payload']['task_id']
    other = ResearchStore()
    barrier = threading.Barrier(2, timeout=5)
    arrivals = []
    original_task_helper = type(store)._continuation_task

    def synchronized_task_helper(connection, task_id, context, *, human):
        try:
            arrivals.append(barrier.wait(timeout=5))
        except threading.BrokenBarrierError as exc:
            raise AssertionError('both reservation transactions must reach the task-lock boundary') from exc
        return original_task_helper(connection, task_id, context, human=human)

    monkeypatch.setattr(type(store), '_continuation_task', staticmethod(synchronized_task_helper))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            entries = list(pool.map(
                lambda instance: instance.reserve_default_continuation_v3(
                    fixture['conversation'], signal_job_id=fixture['job_id'],
                    trusted_context=fixture['context']),
                (store, other)))
        assert sorted(arrivals) == [0, 1]
        assert entries[0] == entries[1]
        assert entries[0]['reservation_id'] == entries[1]['reservation_id']
        assert continuation_budget(store, task) == [entries[0]]
    finally:
        other.close()
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_v3_replay_after_restart_and_options_revision_is_idempotent(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task = fixture['store'], fixture['payload']['task_id']
    restarted = None
    catalog = None
    try:
        first = reserve_v3(fixture)
        fixture['jobs']._execute("UPDATE signal_producer_jobs SET updated_at=updated_at + interval '1 second' WHERE job_id=:job",
            {'job': fixture['job_id']})
        catalog = ConversationCatalogStore()
        catalog.update_execution_options(fixture['context']['owner_principal'],
            fixture['context']['workspace_id'], fixture['conversation'], {
                'schema_version': 'agent-execution-options.v1', 'expected_revision': 0,
                'options': {'max_tool_calls': 7},
            })
        catalog.close()
        catalog = None
        store.close()
        restarted = ResearchStore()
        replay = restarted.reserve_default_continuation_v3(fixture['conversation'],
            signal_job_id=fixture['job_id'], trusted_context=fixture['context'])
        assert replay == first
        assert replay['reservation']['execution_profile']['options_revision'] == 0

        changed_hash = hashlib.sha256(b'changed validated fixture content').hexdigest()
        fixture['jobs']._execute('UPDATE artifacts SET content_sha256=:digest WHERE artifact_id=:artifact',
            {'digest': changed_hash, 'artifact': fixture['artifact_id']})
        with pytest.raises(IdempotencyConflict, match='source facts conflict'):
            restarted.reserve_default_continuation_v3(fixture['conversation'],
                signal_job_id=fixture['job_id'], trusted_context=fixture['context'])
        assert continuation_budget(restarted, task) == [first]
    finally:
        if catalog is not None:
            catalog.close()
        if restarted is not None:
            restarted.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_v3_auto_continue_disabled_blocks_new_reservation_only(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task = fixture['store'], fixture['payload']['task_id']
    catalog = ConversationCatalogStore()
    try:
        first = reserve_v3(fixture)
        catalog.update_execution_options(fixture['context']['owner_principal'],
            fixture['context']['workspace_id'], fixture['conversation'], {
                'schema_version': 'agent-execution-options.v1', 'expected_revision': 0,
                'options': {'auto_continue': False},
            })
        assert reserve_v3(fixture) == first
        next_job, _ = add_ready_event(fixture, key='v3-disabled-next',
            content={'synthetic': 'v3-disabled-next'})
        with pytest.raises(ValueError, match='automatic continuation is disabled'):
            reserve_v3(fixture, signal_job_id=next_job)
        assert continuation_budget(store, task) == [first]
    finally:
        catalog.close()
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


@pytest.mark.parametrize('blocked_case', ['auto_continue_disabled', 'unknown_origin', 'needs_attention'])
def test_default_peek_does_not_fall_back_to_f6_legacy_claim(monkeypatch, tmp_path, blocked_case):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task = fixture['store'], fixture['payload']['task_id']
    catalog = None
    try:
        monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
        grant_retry_permission(store, fixture, key='v3-default-fallback-' + blocked_case)
        if blocked_case == 'auto_continue_disabled':
            catalog = ConversationCatalogStore()
            catalog.update_execution_options(fixture['context']['owner_principal'],
                fixture['context']['workspace_id'], fixture['conversation'], {
                    'schema_version': 'agent-execution-options.v1', 'expected_revision': 0,
                    'options': {'auto_continue': False},
                })
        elif blocked_case == 'unknown_origin':
            fixture['jobs']._execute(
                'UPDATE signal_producer_jobs SET submission_origin=NULL WHERE job_id=:job',
                {'job': fixture['job_id']})
        else:
            store._execute("""UPDATE research_tasks SET
                continuation_blocked_reason='continuation_needs_attention',
                continuation_blocked_event_key='*' WHERE task_id=:task""", {'task': task})

        before = continuation_budget(store, task)
        legacy_claims = []
        original_claim = store.claim_conversation_continuation
        monkeypatch.setattr(store, 'claim_conversation_continuation',
            lambda *args, **kwargs: legacy_claims.append((args, kwargs))
                or original_claim(*args, **kwargs))
        response = default_backend_peek(fixture, monkeypatch)

        assert response.status_code == 200, response.text
        assert response.json() == {'status': 'waiting'}
        assert legacy_claims == []
        assert continuation_budget(store, task) == before
    finally:
        if catalog is not None:
            catalog.close()
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_v3_explicit_revoke_blocks_but_natural_expiry_does_not(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task = fixture['store'], fixture['payload']['task_id']
    try:
        grant_retry_permission(store, fixture, key='v3-expired-legacy-grant')
        permission = store._fetch_one(
            'SELECT continuation_permission FROM research_tasks WHERE task_id=:task',
            {'task': task})['continuation_permission']
        permission['expires_at'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        store._execute('UPDATE research_tasks SET continuation_permission=:permission WHERE task_id=:task',
            {'permission': permission, 'task': task})
        allowed = reserve_v3(fixture)
        assert allowed['reservation']['signal_job_id'] == fixture['job_id']

        permission = store._fetch_one(
            'SELECT continuation_permission FROM research_tasks WHERE task_id=:task',
            {'task': task})['continuation_permission']
        permission['revoked_at'] = datetime.now(timezone.utc).isoformat()
        permission['revoked_by'] = fixture['context']['owner_principal']
        store._execute('UPDATE research_tasks SET continuation_permission=:permission WHERE task_id=:task',
            {'permission': permission, 'task': task})
        next_job, _ = add_ready_event(fixture, key='v3-revoked-next',
            content={'synthetic': 'v3-revoked-next'})
        with pytest.raises(ValueError, match='explicitly revoked'):
            reserve_v3(fixture, signal_job_id=next_job)
        assert continuation_budget(store, task) == [allowed]
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_v3_old_pending_and_unknown_receipts_block_without_mutation(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        grant_retry_permission(store, fixture, key='v3-old-v2-pending')
        intent = store.claim_conversation_continuation(conversation, trusted_context=context)
        reservation = intent['receipt']
        assert reservation['schema_version'] == 'task-continuation-reservation.v2'
        before_reserved = continuation_budget(store, task)
        legacy_claims = []
        original_claim = store.claim_conversation_continuation
        monkeypatch.setattr(store, 'claim_conversation_continuation',
            lambda *args, **kwargs: legacy_claims.append((args, kwargs))
                or original_claim(*args, **kwargs))
        response = default_backend_peek(fixture, monkeypatch)
        assert response.status_code == 200, response.text
        assert response.json() == {'status': 'waiting'}
        assert legacy_claims == []
        assert continuation_budget(store, task) == before_reserved
        monkeypatch.setattr(store, 'claim_conversation_continuation', original_claim)
        with pytest.raises(ValueError, match='unresolved legacy'):
            reserve_v3(fixture)
        assert continuation_budget(store, task) == before_reserved

        assert store.claim_continuation_dispatch(task, reservation['reservation_id'],
            trusted_context=context) == {'dispatch': True, 'attempt': 1}
        before_unknown = continuation_budget(store, task)
        assert before_unknown[0]['status'] == 'outcome_unknown'
        with pytest.raises(ValueError, match='unresolved legacy'):
            reserve_v3(fixture)
        assert continuation_budget(store, task) == before_unknown

        # Historical terminal v2 rows have no stable Job reference either.
        # Exercise a rejected row from the persisted unknown shape, then restore
        # the original unknown receipt before recording the settled path below.
        rejected_v2 = dict(before_unknown[0], status='rejected')
        with_rejected = [rejected_v2]
        store._execute('UPDATE research_tasks SET continuation_budget=:budget WHERE task_id=:task',
            {'budget': with_rejected, 'task': task})
        with pytest.raises(ValueError, match='legacy continuation receipt identity'):
            reserve_v3(fixture)
        assert continuation_budget(store, task) == with_rejected
        store._execute('UPDATE research_tasks SET continuation_budget=:budget WHERE task_id=:task',
            {'budget': before_unknown, 'task': task})

        accepted_v2 = store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=reservation['reservation_id'], status='accepted', run_id='b' * 32)
        before_accepted = continuation_budget(store, task)
        assert before_accepted[0]['status'] == 'accepted'
        assert before_accepted[0]['run_id'] == 'b' * 32
        accepted_bytes = json.dumps(
            before_accepted, sort_keys=True, separators=(',', ':')).encode()
        with pytest.raises(ValueError, match='unresolved legacy'):
            reserve_v3(fixture)
        after_accepted = continuation_budget(store, task)
        assert accepted_v2['status'] == 'accepted'
        assert after_accepted == before_accepted
        assert json.dumps(after_accepted, sort_keys=True, separators=(',', ':')).encode() == accepted_bytes
        closed_v2 = store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=reservation['reservation_id'], status='settled',
            request_usage=confirmed_request_usage(), settlement_sha256='c' * 64,
            outcome='completed')
        assert closed_v2['status'] == 'settled'
        with_closed_v2 = [closed_v2]
        store._execute('UPDATE research_tasks SET continuation_budget=:budget WHERE task_id=:task',
            {'budget': with_closed_v2, 'task': task})
        with pytest.raises(ValueError, match='legacy continuation receipt identity'):
            reserve_v3(fixture)
        assert continuation_budget(store, task) == with_closed_v2

        # A closed v2 receipt still cannot disambiguate a historical model
        # receipt that has no verifiable Job reference. Its old event prefix and
        # grant label are deliberately non-specific, with no instruction text.
        ambiguous_model = legacy_model_reservation('e', status='settled')
        ambiguous_model['grant_kind'] = 'legacy_model_receipt'
        ambiguous_model['event_key'] = 'handoff-v1:' + 'f' * 64
        ambiguous_model['instruction'] = None
        with_ambiguous = [ambiguous_model, closed_v2]
        store._execute('UPDATE research_tasks SET continuation_budget=:budget WHERE task_id=:task',
            {'budget': with_ambiguous, 'task': task})
        with pytest.raises(ValueError, match='legacy continuation receipt identity'):
            reserve_v3(fixture)
        assert continuation_budget(store, task) == with_ambiguous
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_v3_existing_notification_for_same_job_is_not_upgraded(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        notification = store.claim_conversation_continuation(conversation, trusted_context=context)
        assert notification['receipt']['grant_kind'] == 'data_ready_notification'
        before = continuation_budget(store, task)
        with pytest.raises(ValueError, match='already consumed'):
            reserve_v3(fixture)
        assert continuation_budget(store, task) == before

        next_job, _ = add_ready_event(fixture, key='v3-notification-distinct-job',
            content={'synthetic': 'v3-notification-distinct-job'})
        next_event_key = stable_v3_event_key(fixture, next_job)
        same_event_block = store._fetch_one(
            'SELECT continuation_blocked_reason FROM research_tasks WHERE task_id=:task',
            {'task': task})
        assert same_event_block['continuation_blocked_reason'] is None
        store._execute("""UPDATE research_tasks SET continuation_blocked_reason='continuation_needs_attention',
            continuation_blocked_event_key=:event WHERE task_id=:task""",
            {'event': next_event_key, 'task': task})
        with pytest.raises(ValueError, match='blocked by continuation needs_attention'):
            reserve_v3(fixture, signal_job_id=next_job)
        assert continuation_budget(store, task) == before

        store._execute("""UPDATE research_tasks SET continuation_blocked_reason='continuation_needs_attention',
            continuation_blocked_event_key='*' WHERE task_id=:task""", {'task': task})
        with pytest.raises(ValueError, match='blocked by continuation needs_attention'):
            reserve_v3(fixture, signal_job_id=next_job)
        assert continuation_budget(store, task) == before

        # A blocker scoped to a different Job must not suppress this new event.
        store._execute("""UPDATE research_tasks SET continuation_blocked_reason='continuation_needs_attention',
            continuation_blocked_event_key=:event WHERE task_id=:task""",
            {'event': stable_v3_event_key(fixture, fixture['job_id']), 'task': task})
        different_event = reserve_v3(fixture, signal_job_id=next_job)
        assert different_event['signal_job_id'] == next_job
        before = continuation_budget(store, task)

        without_job_ref = [dict(row) for row in before]
        refs = without_job_ref[0]['executable']['references']
        refs.pop('signal_producer_job_id')
        store._execute('UPDATE research_tasks SET continuation_budget=:budget WHERE task_id=:task',
            {'budget': without_job_ref, 'task': task})
        with pytest.raises(ValueError, match='already consumed'):
            reserve_v3(fixture)
        assert continuation_budget(store, task) == without_job_ref

        ambiguous = [dict(row) for row in without_job_ref]
        ambiguous[0]['executable']['references'].pop('signal_snapshot_artifact_id')
        store._execute('UPDATE research_tasks SET continuation_budget=:budget WHERE task_id=:task',
            {'budget': ambiguous, 'task': task})
        with pytest.raises(ValueError, match='lineage is ambiguous'):
            reserve_v3(fixture)
        assert continuation_budget(store, task) == ambiguous
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_v3_envelope_fails_closed_through_legacy_dispatch_and_settlement(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, conversation, context = (fixture['store'], fixture['payload']['task_id'],
        fixture['conversation'], fixture['context'])
    try:
        grant_retry_permission(store, fixture, key='v3-legacy-paths')
        entry = reserve_v3(fixture)
        cancel = store.cancel_default_continuation_v3(conversation, entry['reservation_id'],
            trusted_context=context)
        assert cancel['status'] == 'cancelled'
        before = continuation_budget(store, task)
        legacy_claims = []
        original_claim = store.claim_conversation_continuation
        monkeypatch.setattr(store, 'claim_conversation_continuation',
            lambda *args, **kwargs: legacy_claims.append((args, kwargs))
                or original_claim(*args, **kwargs))
        response = default_backend_peek(fixture, monkeypatch)
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'waiting'
        assert response.json()['may_dispatch'] is False
        assert legacy_claims == []
        assert continuation_budget(store, task) == before
        monkeypatch.setattr(store, 'claim_conversation_continuation', original_claim)
        checked_before = store._fetch_one(
            'SELECT continuation_checked_at FROM research_tasks WHERE task_id=:task',
            {'task': task})['continuation_checked_at']
        assert store.claim_conversation_continuation(conversation, trusted_context=context) == {
            'status': 'waiting'}
        checked_after = store._fetch_one(
            'SELECT continuation_checked_at FROM research_tasks WHERE task_id=:task',
            {'task': task})['continuation_checked_at']
        assert checked_after == checked_before
        view = store.get_continuation_permission(task, trusted_context=context)
        assert view['request_state']['requests_reserved'] == 0
        assert view['request_state']['request_identity'] is None
        assert store.claim_continuation_dispatch(task, entry['reservation_id'],
            trusted_context=context) == {'dispatch': False}
        with pytest.raises(ValueError, match='v3 continuation receipt'):
            store.record_continuation_receipt(task, trusted_context=context,
                reservation_id=entry['reservation_id'], status='outcome_unknown')
        assert continuation_budget(store, task) == before
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_v3_unknown_dispatch_cannot_be_rejected_without_no_start_evidence(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, context = fixture['store'], fixture['payload']['task_id'], fixture['context']
    try:
        entry = reserve_v3(fixture)
        carrier = entry['reservation']
        assert store.claim_continuation_dispatch(task, entry['reservation_id'],
            trusted_context=context) == {'dispatch': True, 'attempt': 1}
        before = continuation_budget(store, task)
        before_bytes = json.dumps(before, sort_keys=True, separators=(',', ':')).encode()
        with pytest.raises(IdempotencyConflict, match='no-start evidence'):
            store.record_continuation_receipt(task, trusted_context=context,
                reservation_id=entry['reservation_id'],
                idempotency_key=carrier['idempotency_key'], status='rejected')
        after = continuation_budget(store, task)
        assert after == before
        assert json.dumps(after, sort_keys=True, separators=(',', ':')).encode() == before_bytes

        root_id, _, _ = _v3_runtime_root(fixture)
        accepted = store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=entry['reservation_id'], idempotency_key=carrier['idempotency_key'],
            status='accepted', run_id=root_id)
        assert accepted['status'] == 'accepted'
        usage = _v3_usage(carrier)
        digest = _v3_settlement_sha256(
            entry['reservation_id'], carrier, root_id, 'completed', usage)
        settled = store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=entry['reservation_id'], idempotency_key=carrier['idempotency_key'],
            status='settled', request_usage=usage, settlement_sha256=digest,
            outcome='completed')
        assert settled['status'] == 'settled'
        assert settled['run_id'] == root_id
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


@pytest.mark.parametrize('mutation', ['origin_before_accept', 'artifact_hash_before_settlement'])
def test_v3_receipts_recheck_exact_source_facts_without_ledger_mutation(
        monkeypatch, tmp_path, mutation):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, jobs = fixture['store'], fixture['jobs']
    task, context = fixture['payload']['task_id'], fixture['context']
    try:
        entry = reserve_v3(fixture)
        carrier = entry['reservation']
        assert store.claim_continuation_dispatch(task, entry['reservation_id'],
            trusted_context=context) == {'dispatch': True, 'attempt': 1}
        root_id = None
        if mutation == 'origin_before_accept':
            jobs._execute('UPDATE signal_producer_jobs SET submission_origin=NULL WHERE job_id=:job',
                {'job': fixture['job_id']})
            before = continuation_budget(store, task)
            with pytest.raises(ValueError, match='origin is unknown'):
                store.record_continuation_receipt(task, trusted_context=context,
                    reservation_id=entry['reservation_id'],
                    idempotency_key=carrier['idempotency_key'],
                    status='accepted', run_id='a' * 32)
        else:
            root_id, _, _ = _v3_runtime_root(fixture)
            store.record_continuation_receipt(task, trusted_context=context,
                reservation_id=entry['reservation_id'],
                idempotency_key=carrier['idempotency_key'],
                status='accepted', run_id=root_id)
            before = continuation_budget(store, task)
            changed_hash = hashlib.sha256(b'mutated validated snapshot fixture').hexdigest()
            store._execute('UPDATE artifacts SET content_sha256=:digest WHERE artifact_id=:artifact',
                {'digest': changed_hash, 'artifact': fixture['artifact_id']})
            usage = _v3_usage(carrier)
            digest = _v3_settlement_sha256(
                entry['reservation_id'], carrier, root_id, 'completed', usage)
            with pytest.raises(ValueError, match='source facts changed'):
                store.record_continuation_receipt(task, trusted_context=context,
                    reservation_id=entry['reservation_id'],
                    idempotency_key=carrier['idempotency_key'], status='settled',
                    request_usage=usage, settlement_sha256=digest, outcome='completed')
        after = continuation_budget(store, task)
        assert after == before
        assert json.dumps(after, sort_keys=True, separators=(',', ':')).encode() == json.dumps(
            before, sort_keys=True, separators=(',', ':')).encode()
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_v3_settlement_keeps_cancelled_snapshot_liability_after_option_change(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, context = fixture['store'], fixture['payload']['task_id'], fixture['context']
    catalog = None
    try:
        entry = reserve_v3(fixture)
        carrier = entry['reservation']
        assert store.claim_continuation_dispatch(task, entry['reservation_id'],
            trusted_context=context) == {'dispatch': True, 'attempt': 1}
        root_id, _, _ = _v3_runtime_root(fixture)
        store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=entry['reservation_id'], idempotency_key=carrier['idempotency_key'],
            status='accepted', run_id=root_id)

        catalog = ConversationCatalogStore()
        changed = catalog.update_execution_options(context['owner_principal'],
            context['workspace_id'], fixture['conversation'], {
                'schema_version': 'agent-execution-options.v1', 'expected_revision': 0,
                'options': {'auto_continue': False},
            })
        assert changed['revision'] == 1
        cancelled = store.cancel_default_continuation_v3(fixture['conversation'],
            entry['reservation_id'], trusted_context=context)
        assert cancelled == {
            'reservation_id': entry['reservation_id'],
            'cancel_requested': True,
            'status': 'accepted',
        }

        usage = _v3_usage(carrier)
        digest = _v3_settlement_sha256(
            entry['reservation_id'], carrier, root_id, 'completed', usage)
        settled = store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=entry['reservation_id'], idempotency_key=carrier['idempotency_key'],
            status='settled', request_usage=usage, settlement_sha256=digest,
            outcome='completed')
        assert settled['status'] == 'settled'
        assert settled['request_usage'] == usage
        persisted = continuation_budget(store, task)[0]
        assert persisted['status'] == 'settled'
        assert persisted['cancel_requested_at'] is not None
    finally:
        if catalog is not None:
            catalog.close()
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


@pytest.mark.parametrize('evidence_case', [
    'missing_root', 'active_root', 'wrong_owner', 'wrong_workspace',
    'wrong_session', 'wrong_trace', 'unknown_claim_count',
])
def test_v3_settlement_refuses_unclosed_or_mismatched_runtime_evidence(
        monkeypatch, tmp_path, evidence_case):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, context = fixture['store'], fixture['payload']['task_id'], fixture['context']
    root_id = None
    runtime_store = None
    runtime_boot_id = None
    try:
        entry = reserve_v3(fixture)
        carrier = entry['reservation']
        assert store.claim_continuation_dispatch(task, entry['reservation_id'],
            trusted_context=context) == {'dispatch': True, 'attempt': 1}

        if evidence_case == 'missing_root':
            root_id = uuid4().hex
        elif evidence_case == 'active_root':
            root_id, runtime_store, runtime_boot_id = _v3_runtime_root(fixture, close=False)
        elif evidence_case == 'wrong_session':
            root_id, runtime_store, runtime_boot_id = _v3_runtime_root(
                fixture, session_id='wrong-runtime-session')
        elif evidence_case == 'wrong_trace':
            root_id, runtime_store, runtime_boot_id = _v3_runtime_root(
                fixture, trace_id='wrong-runtime-trace')
        else:
            root_id, runtime_store, runtime_boot_id = _v3_runtime_root(fixture)
            if evidence_case == 'wrong_owner':
                runtime_store._execute('''UPDATE agent_runtime_turns
                    SET owner_principal='other-owner' WHERE root_run_id=:root''', {'root': root_id})
            elif evidence_case == 'wrong_workspace':
                runtime_store._execute('''UPDATE agent_runtime_turns
                    SET workspace_id='other-workspace' WHERE root_run_id=:root''', {'root': root_id})
            else:
                runtime_store._execute('''UPDATE agent_runtime_turns
                    SET terminal_unknown_claim_count=1 WHERE root_run_id=:root''', {'root': root_id})

        store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=entry['reservation_id'], idempotency_key=carrier['idempotency_key'],
            status='accepted', run_id=root_id)
        before = continuation_budget(store, task)
        usage = _v3_usage(carrier)
        digest = _v3_settlement_sha256(
            entry['reservation_id'], carrier, root_id, 'completed', usage)
        with pytest.raises(ValueError, match='closed Runtime root evidence'):
            store.record_continuation_receipt(task, trusted_context=context,
                reservation_id=entry['reservation_id'], idempotency_key=carrier['idempotency_key'],
                status='settled', request_usage=usage, settlement_sha256=digest,
                outcome='completed')
        assert continuation_budget(store, task) == before
    finally:
        if root_id is not None and runtime_store is not None:
            root = runtime_store._fetch_one(
                'SELECT status FROM agent_runtime_turns WHERE root_run_id=:root', {'root': root_id})
            if root and root['status'] == 'active':
                runtime_store.close_runtime_root(root_id, boot_id=runtime_boot_id,
                    sequence=2, outcome='interrupted', event_sha256='e' * 64)
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()


def test_v3_settlement_recomputes_runtime_digest_and_requires_exact_closed_root(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, context = fixture['store'], fixture['payload']['task_id'], fixture['context']
    try:
        entry = reserve_v3(fixture)
        carrier = entry['reservation']
        assert store.claim_continuation_dispatch(task, entry['reservation_id'],
            trusted_context=context) == {'dispatch': True, 'attempt': 1}
        root_id, _, _ = _v3_runtime_root(fixture)
        store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=entry['reservation_id'], idempotency_key=carrier['idempotency_key'],
            status='accepted', run_id=root_id)

        usage = _v3_usage(carrier)
        digest = _v3_settlement_sha256(
            entry['reservation_id'], carrier, root_id, 'completed', usage)
        before = continuation_budget(store, task)
        with pytest.raises(ValueError, match='digest does not match'):
            store.record_continuation_receipt(task, trusted_context=context,
                reservation_id=entry['reservation_id'], idempotency_key=carrier['idempotency_key'],
                status='settled', request_usage=usage, settlement_sha256='0' * 64,
                outcome='completed')
        assert continuation_budget(store, task) == before

        settled = store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=entry['reservation_id'], idempotency_key=carrier['idempotency_key'],
            status='settled', request_usage=usage, settlement_sha256=digest,
            outcome='completed')
        assert settled['status'] == 'settled'
        assert settled['run_id'] == root_id
        assert settled['request_usage'] == usage
        assert settled['settlement_sha256'] == digest
        assert continuation_budget(store, task)[0]['status'] == 'settled'
        assert store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=entry['reservation_id'], idempotency_key=carrier['idempotency_key'],
            status='settled', request_usage=usage, settlement_sha256=digest,
            outcome='completed') == settled
    finally:
        store.close()
        fixture['backtests'].close()
        fixture['jobs'].close()
