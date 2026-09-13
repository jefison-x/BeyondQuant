import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.research import ResearchStore
from tests.test_research_continuation import setup_permission

pytestmark = pytest.mark.skipif(not os.environ.get('BYQ_DATABASE_URL'), reason='isolated PostgreSQL required')


def setup_handoff(monkeypatch, *, grant=True):
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
    store, task, context, payload = setup_permission()
    store.transition('research_task', task, 'running', 'handoff-progress', progress={
        'schema_version': 'research-progress.v1', 'stage': 'backtest', 'next_action': '核对原任务后继续',
        'blocked_reason': None, 'linked_objects': [{'kind': 'artifact', 'id': payload['confirmed_artifact_ids'][0]}],
        'completion_evidence': []})
    if grant:
        store.create_continuation_permission(task, {**payload, 'token_limit': 8000000}, trusted_context=context)
    conversation = store.get_task(task)['conversation_id']
    return store, task, context, payload, conversation


def test_initial_handoff_is_reserved_once_and_not_an_idle_loop(monkeypatch):
    store, task, context, _, conversation = setup_handoff(monkeypatch)
    other = ResearchStore()
    try:
        assert store.claim_conversation_continuation(conversation, trusted_context=context, admit=False)['status'] == 'eligible'
        assert not store._fetch_one('SELECT continuation_budget FROM research_tasks WHERE task_id=:task', {'task': task})['continuation_budget']
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(lambda s: s.claim_conversation_continuation(conversation, trusted_context=context), (store, other)))
        rid = receipts[0]['receipt']['reservation_id']
        assert rid == receipts[1]['receipt']['reservation_id']
        assert 'permission_handoff' in receipts[0]['receipt']['instruction']
        assert receipts[0]['receipt']['event_key'].startswith('handoff-v1:')
        assert store.claim_continuation_dispatch(task, rid, trusted_context=context) == {'dispatch': True, 'attempt': 1}
        assert other.claim_continuation_dispatch(task, rid, trusted_context=context) == {'dispatch': False}
        store.record_continuation_receipt(task, trusted_context=context, reservation_id=rid, status='settled',
            charged_tokens=1056768, settlement_sha256='a'*64, outcome='completed')
        store.close()
        store = ResearchStore()
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
        assert store.get_task(task)['status'] == 'running'
    finally:
        store.close()
        other.close()


def test_old_permission_replay_does_not_gain_handoff_triggers(monkeypatch):
    store, task, context, payload, conversation = setup_handoff(monkeypatch)
    try:
        store._execute("UPDATE research_tasks SET continuation_permission=continuation_permission-'handoff_version' WHERE task_id=:task", {'task': task})
        store.create_continuation_permission(task, {**payload, 'token_limit': 8000000}, trusted_context=context)
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
        assert 'handoff_version' not in store._fetch_one('SELECT continuation_permission FROM research_tasks WHERE task_id=:task', {'task': task})['continuation_permission']
    finally:
        store.close()


@pytest.mark.parametrize('blocker', ['missing', 'revoked', 'expired', 'cancelled', 'budget', 'disabled'])
def test_handoff_preserves_permission_guards(monkeypatch, blocker):
    store, task, context, _, conversation = setup_handoff(monkeypatch, grant=blocker != 'missing')
    try:
        if blocker == 'revoked':
            store.revoke_continuation_permission(task, grant_version=1, trusted_context=context)
        elif blocker == 'expired':
            store._execute("UPDATE research_tasks SET continuation_permission=jsonb_set(continuation_permission,'{expires_at}',to_jsonb((now()-interval '1 second')::text)) WHERE task_id=:task", {'task': task})
        elif blocker == 'cancelled':
            store.transition('research_task', task, 'cancelled', 'cancel-handoff')
        elif blocker == 'budget':
            store._execute("UPDATE research_tasks SET continuation_permission=jsonb_set(continuation_permission,'{token_limit}','100'::jsonb) WHERE task_id=:task", {'task': task})
        elif blocker == 'disabled':
            monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '0')
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] in {'waiting', 'blocked'}
    finally:
        store.close()


def test_foreground_activity_defers_dispatch_without_spending_attempts(monkeypatch):
    store, task, context, _, conversation = setup_handoff(monkeypatch)
    try:
        intent = store.claim_conversation_continuation(conversation, trusted_context=context)
        rid = intent['receipt']['reservation_id']
        store._execute('''INSERT INTO agent_runtime_turns
            (root_run_id,owner_principal,workspace_id,session_id,trace_id,status,created_at,updated_at)
            VALUES ('foreground',:owner,:workspace,'budget-session','budget-trace','active',now(),now())''',
            {'owner': context['owner_principal'], 'workspace': context['workspace_id']})
        for _ in range(10):
            assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
            assert store.claim_continuation_dispatch(task, rid, trusted_context=context) == {'dispatch': False}
        row = store._fetch_one('SELECT continuation_budget FROM research_tasks WHERE task_id=:task', {'task': task})
        assert row['continuation_budget'][0]['dispatch_attempts'] == 0
        assert row['continuation_budget'][0].get('reconcile_attempts', 0) == 0
        store._execute("UPDATE agent_runtime_turns SET status='completed' WHERE root_run_id='foreground'")
        assert store.claim_continuation_dispatch(task, rid, trusted_context=context) == {'dispatch': True, 'attempt': 1}
    finally:
        store.close()


def test_new_domain_approval_hands_off_once_and_later_rejection_does_not(monkeypatch, tmp_path):
    import test_backtest_api
    from app.conversation_catalog import ConversationCatalogStore
    from tests.workspace_helpers import trusted_agent_context
    from tests.test_backtest_task_reconciliation import setup_creation
    headers = trusted_agent_context('product-user', trace_id='byq-trace-task-receipt', session_id='byq-session-product-user')
    context = {k.removeprefix('x-byq-').replace('-', '_'): v for k, v in headers.items()}
    monkeypatch.setattr(test_backtest_api, '_owner_headers', lambda _: headers)
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
    catalog = ConversationCatalogStore()
    conversation = catalog.create('product-user', 'byq-session-product-user', 'byq-trace-task-receipt')['conversation_id']
    catalog.close()
    store, backtests, jobs, client, payload = setup_creation(monkeypatch, tmp_path)
    task, strategy = payload['task_id'], payload['strategy_version_artifact_id']
    try:
        store.transition('research_task', task, 'running', 'next-backtest', progress={
            'schema_version': 'research-progress.v1', 'stage': 'backtest', 'next_action': '核对策略后回测',
            'blocked_reason': None, 'linked_objects': [{'kind': 'artifact', 'id': strategy}], 'completion_evidence': []})
        store.create_continuation_permission(task, {'idempotency_key': 'new-handoff-grant', 'token_limit': 8000000,
            'confirmed_artifact_ids': [strategy]}, trusted_context=context)
        first = store.claim_conversation_continuation(conversation, trusted_context=context)['receipt']
        store.record_continuation_receipt(task, trusted_context=context, reservation_id=first['reservation_id'],
            status='settled', charged_tokens=1056768, settlement_sha256='a'*64, outcome='completed')
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
        body = {'task_id': task, 'strategy_version_artifact_id': strategy, 'reviewer_principal': 'product-user',
                'decision': 'approved', 'rationale': 'Synthetic domain approval',
                'trace_id': context['trace_id'], 'idempotency_key': 'new-domain-approval'}
        response = client.post('/v1/research/strategies/approvals', json=body)
        assert response.status_code == 201, response.text
        approved_id = response.json()['artifact']['artifact_id']
        second = store.claim_conversation_continuation(conversation, trusted_context=context)['receipt']
        assert 'approval_handoff' in second['instruction'] and approved_id in second['instruction']
        assert strategy in second['instruction'] and second['reservation_id'] != first['reservation_id']
        store.record_continuation_receipt(task, trusted_context=context, reservation_id=second['reservation_id'],
            status='settled', charged_tokens=1056768, settlement_sha256='b'*64, outcome='completed')
        assert client.post('/v1/research/strategies/approvals', json={**body, 'idempotency_key': 'another-approved'}).status_code == 201
        assert client.post('/v1/research/strategies/approvals', json={**body, 'decision': 'rejected', 'idempotency_key': 'new-rejected'}).status_code == 201
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
    finally:
        store.close()
        backtests.close()
        jobs.close()


def test_pending_approval_and_unknown_submission_wait_without_admission(monkeypatch):
    from app.agent_research import AgentResearchStore
    from tests.test_agent_research import start
    store, task, context, payload, conversation = setup_handoff(monkeypatch)
    agents = AgentResearchStore()
    try:
        run = start(agents, owner_principal=context['owner_principal'], actor_principal=context['owner_principal'],
                    session_id='budget-session', trace_id='budget-trace')
        approval = agents.create_approval({'run_id': run['run_id'], 'action': 'byq_backtest_task_execute',
            'reason': 'Synthetic approval', 'resource_type': 'artifact',
            'resource_id': payload['confirmed_artifact_ids'][0], 'idempotency_key': 'handoff-pending'})
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
        store._execute("UPDATE agent_approvals SET status='rejected',continuation_status='submitted' WHERE approval_id=:id", {'id': approval['approval_id']})
        store._execute('''INSERT INTO research_receipt_watches
            (watch_id,owner_principal,workspace_id,conversation_id,session_id,trace_id,entity_type,
             parent_task_id,idempotency_key,request_hash,state)
            VALUES ('researchwatch_h3',:owner,:workspace,:conversation,'budget-session','budget-trace',
                    'artifact',:task,'unknown-artifact','synthetic','awaiting_receipt')''',
            {'owner': context['owner_principal'], 'workspace': context['workspace_id'], 'conversation': conversation, 'task': task})
        assert store.claim_conversation_continuation(conversation, trusted_context=context)['status'] == 'waiting'
        assert not store._fetch_one('SELECT continuation_budget FROM research_tasks WHERE task_id=:task', {'task': task})['continuation_budget']
        store._execute("UPDATE research_receipt_watches SET state='confirmed' WHERE watch_id='researchwatch_h3'")
        assert store.claim_conversation_continuation(conversation, trusted_context=context, admit=False)['status'] == 'eligible'
    finally:
        agents.close()
        store.close()
