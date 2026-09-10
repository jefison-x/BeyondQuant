import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchStore
from tests.workspace_helpers import trusted_agent_context
from tests.test_backtest_task_reconciliation import setup_creation

pytestmark = pytest.mark.skipif(not os.environ.get('BYQ_DATABASE_URL'), reason='isolated PostgreSQL required')


def test_terminal_notification_claim_and_dispatch_are_durable_and_once(monkeypatch, tmp_path):
    import test_backtest_api
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
    headers = trusted_agent_context('product-user', trace_id='byq-trace-task-receipt', session_id='byq-session-product-user')
    monkeypatch.setattr(test_backtest_api, '_owner_headers', lambda principal: headers)
    context = {key.removeprefix('x-byq-').replace('-', '_'): value for key, value in headers.items()}
    catalog = ConversationCatalogStore()
    conversation = catalog.create('product-user', 'byq-session-product-user', 'byq-trace-task-receipt')
    catalog.close()
    store, backtests, jobs, client, payload = setup_creation(monkeypatch, tmp_path)
    other = ResearchStore()
    task = payload['task_id']
    try:
        store.create_continuation_permission(task, {'idempotency_key': 'continuation-test',
            'token_limit': 3000000, 'confirmed_artifact_ids': [payload['strategy_version_artifact_id']]},
            trusted_context=context)
        assert store.claim_conversation_continuation(conversation['conversation_id'], trusted_context=context)['status'] == 'waiting'
        response = client.post('/v1/research/backtest-tasks', json=payload)
        assert response.status_code == 202, response.text
        # A synthetic terminal failure row is the notification fixture. This
        # test does not claim that a Worker executed a real strategy.
        jobs._execute("UPDATE signal_producer_jobs SET status='failed',updated_at=now() WHERE task_id=:task", {'task': task})
        assert store.claim_conversation_continuation(conversation['conversation_id'],
            trusted_context=context, admit=False)['status'] == 'eligible'
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(s.claim_conversation_continuation, conversation['conversation_id'],
                trusted_context=context) for s in (store, other)]
            first, second = [future.result() for future in futures]
        assert first['receipt']['reservation_id'] == second['receipt']['reservation_id']
        assert first['reservation']['task_id'] == task
        assert 'signal_producer_jobs' in first['receipt']['instruction']
        rid = first['receipt']['reservation_id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = list(pool.map(lambda s: s.claim_continuation_dispatch(task, rid, trusted_context=context), (store, other)))
        assert sum(r['dispatch'] for r in attempts) == 1
        store.close()
        store = ResearchStore()
        assert store.claim_continuation_dispatch(task, rid, trusted_context=context) == {'dispatch': False}
        assert store.claim_conversation_continuation(conversation['conversation_id'], trusted_context=context)['status'] == 'waiting'
        make_watch_due(store, task)
        recovered = store.claim_conversation_continuation(conversation['conversation_id'], trusted_context=context)
        assert recovered['receipt']['status'] == 'outcome_unknown'
        assert recovered['receipt']['dispatch_attempts'] == 1
        store.revoke_continuation_permission(task, grant_version=1, trusted_context=context)
        make_watch_due(store, task)
        assert store.claim_conversation_continuation(conversation['conversation_id'],
            trusted_context=context)['may_dispatch'] is False
        store.record_continuation_receipt(task, trusted_context=context, reservation_id=rid,
            status='settled', charged_tokens=1056768, settlement_sha256='d' * 64)
        assert store.claim_conversation_continuation(conversation['conversation_id'], trusted_context=context)['status'] == 'waiting'
    finally:
        store.close()
        other.close()
        backtests.close()
        jobs.close()


def make_watch_due(store, task):
    store._execute("""UPDATE research_tasks SET continuation_budget=jsonb_set(continuation_budget,
        '{0,next_reconcile_at}', to_jsonb((now()-interval '1 second')::text)) WHERE task_id=:task""", {'task': task})


def test_private_consumer_uses_catalog_identity_before_any_model_root(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    from tests.test_research_continuation import setup_permission
    store, task, context, payload = setup_permission()
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
    monkeypatch.setattr(main, 'research_store', store)
    try:
        grant = store.create_continuation_permission(task, payload, trusted_context=context)
        conversation = grant['permission']['conversation_id']
        headers = {'x-byq-owner-principal': context['owner_principal'],
            'x-byq-actor-principal': context['owner_principal'], 'x-byq-workspace-id': context['workspace_id']}
        client = TestClient(main.app)
        path = f'/internal/task-continuation/{conversation}/peek'
        reply = client.post(path, headers=headers)
        assert reply.status_code == 200 and reply.json() == {'status': 'waiting'}
        assert client.post(path, headers={**headers, 'x-byq-actor-principal': 'product-agent'}).status_code == 403
        assert client.post(path, headers={**headers, 'x-byq-workspace-id': 'another-workspace'}).status_code == 401
        # This consumer identity cannot be reused as an Agent tool admission.
        assert client.post('/internal/task-continuation/continuation_' + 'a'*32 + '/authorize-tool',
            headers=headers, json={'tool': 'byq_research_get', 'arguments': {}, 'root_run_id': 'b'*32}).status_code == 401
    finally:
        store.close()
