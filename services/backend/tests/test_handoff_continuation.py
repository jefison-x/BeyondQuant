"""Handoff and approval facts do not grant ADR-0090 background model turns."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchStore
from tests.test_research_continuation import setup_permission
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.environ.get('BYQ_DATABASE_URL'), reason='isolated PostgreSQL required')


def setup_handoff(monkeypatch, *, grant=True):
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
    store, task, context, payload = setup_permission()
    store.transition('research_task', task, 'running', 'handoff-progress', progress={
        'schema_version': 'research-progress.v1', 'stage': 'backtest', 'next_action': '核对原任务后继续',
        'blocked_reason': None, 'linked_objects': [{'kind': 'artifact', 'id': payload['confirmed_artifact_ids'][0]}],
        'completion_evidence': []})
    if grant:
        store.create_continuation_permission(task, payload, trusted_context=context)
    conversation = store.get_task(task)['conversation_id']
    return store, task, context, payload, conversation


def test_handoff_event_does_not_create_or_dispatch_a_profile_request(monkeypatch):
    store, task, context, _, conversation = setup_handoff(monkeypatch)
    other = ResearchStore()
    try:
        assert store.claim_conversation_continuation(
            conversation, trusted_context=context, admit=False)['status'] == 'waiting'
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda s: s.claim_conversation_continuation(
                conversation, trusted_context=context), (store, other)))
        assert replies == [{'status': 'waiting'}, {'status': 'waiting'}]
        assert store._fetch_one('SELECT continuation_budget FROM research_tasks WHERE task_id=:task',
            {'task': task})['continuation_budget'] in (None, [])
        assert store.get_continuation_permission(task, trusted_context=context)['request_state']['request_identity'] is None
        assert store.get_task(task)['status'] == 'running'
    finally:
        store.close()
        other.close()


def test_strategy_approval_artifact_is_preserved_without_triggering_background_model(monkeypatch, tmp_path):
    from tests import test_backtest_api
    from tests.test_backtest_task_reconciliation import setup_creation

    headers = trusted_agent_context('product-user', trace_id='byq-trace-task-receipt',
        session_id='byq-session-product-user')
    context = {key.removeprefix('x-byq-').replace('-', '_'): value for key, value in headers.items()}
    monkeypatch.setattr(test_backtest_api, '_owner_headers', lambda _: headers)
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
    catalog = ConversationCatalogStore()
    conversation = catalog.create('product-user', 'byq-session-product-user',
        'byq-trace-task-receipt')['conversation_id']
    catalog.close()
    store, backtests, jobs, client, payload = setup_creation(monkeypatch, tmp_path)
    task, strategy = payload['task_id'], payload['strategy_version_artifact_id']
    try:
        store.transition('research_task', task, 'running', 'approval-progress', progress={
            'schema_version': 'research-progress.v1', 'stage': 'backtest',
            'next_action': '核对策略后回测', 'blocked_reason': None,
            'linked_objects': [{'kind': 'artifact', 'id': strategy}], 'completion_evidence': []})
        store.create_continuation_permission(task, {
            'idempotency_key': 'approval-event-confirmation',
            'confirmed_artifact_ids': [strategy]}, trusted_context=context)
        body = {'task_id': task, 'strategy_version_artifact_id': strategy,
            'reviewer_principal': 'product-user', 'decision': 'approved',
            'rationale': 'Synthetic domain approval', 'trace_id': context['trace_id'],
            'idempotency_key': 'new-domain-approval'}
        response = client.post('/v1/research/strategies/approvals', json=body)
        assert response.status_code == 201, response.text
        approval_id = response.json()['artifact']['artifact_id']
        approval = store.get_artifact(approval_id)
        assert approval['kind'] == 'strategy_approval'
        assert store.claim_conversation_continuation(
            conversation, trusted_context=context, admit=False)['status'] == 'waiting'
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
        assert store._fetch_one('SELECT continuation_budget FROM research_tasks WHERE task_id=:task',
            {'task': task})['continuation_budget'] in (None, [])
        assert store.get_task(task)['progress']['next_action'] == '核对策略后回测'
    finally:
        store.close()
        backtests.close()
        jobs.close()


def test_pending_approval_or_unknown_submission_does_not_create_a_request(monkeypatch):
    from app.agent_research import AgentResearchStore
    from app.strategy_artifact import prepare_strategy, strategy_version_content
    from tests.test_agent_research import start
    from tests.test_strategy_artifact import strategy_payload

    store, task, context, _, conversation = setup_handoff(monkeypatch, grant=False)
    agents = AgentResearchStore()
    try:
        strategy = store.create_artifact({
            'task_id': task, 'kind': 'strategy_version',
            'content': strategy_version_content(prepare_strategy(strategy_payload())),
            'lineage': [], 'trace_id': context['trace_id'], 'idempotency_key': 'handoff-strategy-version',
        })
        strategy = store.transition('artifact', strategy['artifact_id'], 'validated', 'handoff-strategy-validate')
        run = start(agents, owner_principal=context['owner_principal'], actor_principal=context['owner_principal'],
            session_id='budget-session', trace_id='budget-trace')
        approval = agents.create_approval({'run_id': run['run_id'], 'action': 'byq_strategy_approve',
            'reason': 'Synthetic strategy approval', 'resource_type': 'strategy_version',
            'resource_id': strategy['artifact_id'], 'idempotency_key': 'handoff-pending'})
        assert approval['action'] == 'byq_strategy_approve'
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
        store._execute("UPDATE agent_approvals SET status='rejected',continuation_status='submitted' WHERE approval_id=:id",
            {'id': approval['approval_id']})
        store._execute('''INSERT INTO research_receipt_watches
            (watch_id,owner_principal,workspace_id,conversation_id,session_id,trace_id,entity_type,
             parent_task_id,idempotency_key,request_hash,state)
            VALUES ('researchwatch_h3',:owner,:workspace,:conversation,'budget-session','budget-trace',
                    'artifact',:task,'unknown-artifact','synthetic','awaiting_receipt')''',
            {'owner': context['owner_principal'], 'workspace': context['workspace_id'],
             'conversation': conversation, 'task': task})
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
        store._execute("UPDATE research_receipt_watches SET state='confirmed' WHERE watch_id='researchwatch_h3'")
        assert store.claim_conversation_continuation(
            conversation, trusted_context=context, admit=False)['status'] == 'waiting'
        assert store._fetch_one('SELECT continuation_budget FROM research_tasks WHERE task_id=:task',
            {'task': task})['continuation_budget'] in (None, [])
    finally:
        agents.close()
        store.close()
