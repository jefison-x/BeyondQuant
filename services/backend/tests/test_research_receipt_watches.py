"""Finite exact-request receipt recovery; never replay research writes."""
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchStore, IdempotencyConflict
from tests.workspace_helpers import trusted_agent_context
from tests.test_research import snapshot

pytestmark = pytest.mark.skipif(not os.environ.get('BYQ_DATABASE_URL'), reason='isolated PostgreSQL required')


def fixture(kind='research_task'):
    headers = trusted_agent_context('watch-owner', session_id='watch-session', trace_id='watch-trace')
    context = {k.removeprefix('x-byq-').replace('-', '_'): v for k, v in headers.items()}
    catalog = ConversationCatalogStore()
    conversation = catalog.create('watch-owner', 'watch-session', 'watch-trace')
    catalog.close()
    store = ResearchStore()
    request = {'owner_principal':'watch-owner', 'title':'Synthetic receipt', 'objective':'Recover exact original result',
               'trace_id':'watch-trace', 'idempotency_key':'original-key'}
    if kind != 'research_task':
        task = store.create_task({**request, 'idempotency_key':'parent'}, trusted_context=context)
        request = {'task_id':task['task_id'], 'trace_id':'watch-trace', 'idempotency_key':'original-key'}
        request.update({'name':'Synthetic experiment', 'input_snapshot':snapshot()} if kind == 'experiment'
                       else {'kind':'evidence','content':{'synthetic':True},'lineage':[]})
    return store, context, conversation['conversation_id'], {'entity_type':kind,'request':request}


def due(store):
    store._execute("UPDATE research_receipt_watches SET next_check_at=now()-interval '1 second'")


@pytest.mark.parametrize('kind', ['research_task','experiment','artifact'])
def test_late_commit_after_reopen_exact_identity_and_no_write_replay(monkeypatch, kind):
    store, context, conversation, payload = fixture(kind)
    watch = store.register_submission_watch(payload, trusted_context=context)
    assert watch['status'] == 'awaiting_receipt' and watch['attempts'] == 1
    due(store)
    assert store.consume_submission_watches(conversation, trusted_context=context) == 1
    before = store.get_submission_watch(watch['watch_id'], trusted_context=context)
    assert before['status'] == 'awaiting_receipt' and before['attempts'] == 2
    store.close()
    store = ResearchStore()
    replay = store.register_submission_watch(payload, trusted_context=context)
    assert replay.pop('registration_created') is False
    assert replay == before
    if kind == 'research_task':
        entity = store.create_task(payload['request'], trusted_context=context)
    elif kind == 'experiment':
        entity = store.create_experiment(payload['request'])
    else:
        entity = store.create_artifact(payload['request'], trusted_owner=context['owner_principal'], trusted_workspace=context['workspace_id'])
    for name in ('create_task','create_experiment','create_artifact','list_tasks','list_experiments','list_artifacts'):
        monkeypatch.setattr(store, name, lambda *a, **k: pytest.fail('receipt recovery replayed a write or used a list'))
    due(store)
    assert store.consume_submission_watches(conversation, trusted_context=context) == 1
    result = store.get_submission_watch(watch['watch_id'], trusted_context=context)
    assert result['status'] == 'confirmed'
    assert result['entity_id'] == entity[{'research_task':'task_id','experiment':'experiment_id','artifact':'artifact_id'}[kind]]
    assert result['attempts'] == 3 and 'request_hash' not in result
    assert store.consume_submission_watches(conversation, trusted_context=context) == 0
    store.close()


def test_reused_key_cannot_replace_request_or_reset_budget():
    store, context, conversation, payload = fixture()
    original = store.register_submission_watch(payload, trusted_context=context)
    due(store)
    store.consume_submission_watches(conversation, trusted_context=context)
    with pytest.raises(IdempotencyConflict):
        store.register_submission_watch({**payload,'request':{**payload['request'],'objective':'different input'}}, trusted_context=context)
    assert store.get_submission_watch(original['watch_id'], trusted_context=context)['attempts'] == 2
    store.close()


def test_missing_receipt_exhausts_without_inventing_failure_or_absence():
    store, context, conversation, payload = fixture()
    original = store.register_submission_watch(payload, trusted_context=context)
    for _ in range(8):
        due(store)
        store.consume_submission_watches(conversation, trusted_context=context)
    result = store.get_submission_watch(original['watch_id'], trusted_context=context)
    assert result['status'] == 'needs_attention' and result['attempts'] == 8
    assert result['entity_id'] is None and result['outcome'] == 'outcome_unknown'
    due(store)
    assert store.consume_submission_watches(conversation, trusted_context=context) == 0
    replay = store.register_submission_watch(payload, trusted_context=context)
    assert replay.pop('registration_created') is False
    assert replay == result
    store.close()


def test_concurrent_consumers_charge_once_and_restart_keeps_backoff():
    store, context, conversation, payload = fixture()
    other = ResearchStore()
    watch = store.register_submission_watch(payload, trusted_context=context)
    due(store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda s:s.consume_submission_watches(conversation, trusted_context=context), (store,other)))
    assert sum(results) == 1
    assert other.get_submission_watch(watch['watch_id'], trusted_context=context)['attempts'] == 2
    assert other.consume_submission_watches(conversation, trusted_context=context) == 0
    store.close(); other.close()


def test_lookup_failure_is_charged_and_crash_before_ack_does_not_reset(monkeypatch):
    store, context, conversation, payload = fixture()
    watch = store.register_submission_watch(payload, trusted_context=context)
    def failed(row):
        assert store.get_submission_watch(row['watch_id'],trusted_context=context)['attempts'] == 2
        raise RuntimeError('private storage failure must not be projected')
    monkeypatch.setattr(store,'_find_watched_submission',failed)
    due(store)
    store.consume_submission_watches(conversation,trusted_context=context)
    state = store.get_submission_watch(watch['watch_id'],trusted_context=context)
    assert state['attempts']==2 and state['reason']=='query_unavailable'
    assert 'private storage' not in str(state)
    store.close()
    store = ResearchStore()
    assert store.consume_submission_watches(conversation,trusted_context=context)==0
    assert store.get_submission_watch(watch['watch_id'],trusted_context=context)==state
    store.close()


@pytest.mark.parametrize('change', ['expiry','conversation','disabled_owner'])
def test_expired_inactive_or_disabled_identity_never_reads_domain(monkeypatch,change):
    from app.research import ResearchNotFound
    store, context, conversation, payload = fixture()
    watch = store.register_submission_watch(payload,trusted_context=context)
    if change=='expiry':
        store._execute("UPDATE research_receipt_watches SET deadline_at=now()-interval '1 second'")
    elif change=='conversation':
        store._execute("UPDATE product_conversations SET status='archived'")
    else:
        store._execute("UPDATE users SET status='disabled' WHERE username='watch-owner'")
    monkeypatch.setattr(store,'_find_watched_submission',lambda *_:pytest.fail('inactive identity read a domain result'))
    due(store)
    if change=='disabled_owner':
        with pytest.raises(ResearchNotFound):
            store.consume_submission_watches(conversation,trusted_context=context)
    else:
        assert store.consume_submission_watches(conversation,trusted_context=context)==0
        state=store.get_submission_watch(watch['watch_id'],trusted_context=context)
        assert state['status']=='needs_attention' and state['attempts']==1
    store.close()


@pytest.mark.parametrize('kind',['research_task','experiment','artifact'])
def test_existing_original_is_confirmed_without_new_write_and_wrong_hash_conflicts(kind):
    store, context, conversation, payload=fixture(kind)
    if kind=='research_task':
        store.create_task(payload['request'],trusted_context=context)
    elif kind=='experiment':
        store.create_experiment(payload['request'])
    else:
        store.create_artifact(payload['request'])
    watched=store.register_submission_watch(payload,trusted_context=context)
    assert watched['status']=='confirmed' and watched['attempts']==1
    store.close()


def test_foreign_owner_conversation_or_payload_cannot_rebind_watch():
    from app.research import ResearchNotFound
    store, context, conversation, payload=fixture()
    watch=store.register_submission_watch(payload,trusted_context=context)
    headers=trusted_agent_context('watch-other',session_id='other-session',trace_id='other-trace')
    foreign={k.removeprefix('x-byq-').replace('-','_'):v for k,v in headers.items()}
    for ctx in (foreign,{**context,'workspace_id':foreign['workspace_id']},{**context,'session_id':'other-session'}):
        with pytest.raises(ResearchNotFound):
            store.get_submission_watch(watch['watch_id'],trusted_context=ctx)
        with pytest.raises(ResearchNotFound):
            store.consume_submission_watches(conversation,trusted_context=ctx)
    assert store.list_submission_watches(conversation,trusted_context=context)['receipts'][0]['watch_id']==watch['watch_id']
    with pytest.raises(ValueError):
        store.register_submission_watch({**payload,'request':{**payload['request'],'owner_principal':'watch-other'}},trusted_context=context)
    store.close()


def test_existing_different_request_is_conflict_without_exposing_entity():
    store, context, _, payload = fixture()
    store.create_task({**payload['request'],'objective':'different'},trusted_context=context)
    watched=store.register_submission_watch(payload,trusted_context=context)
    assert watched['status']=='conflict' and watched['entity_id'] is None
    store.close()


def test_competing_registrations_grant_only_one_initial_post():
    store, context, _, payload=fixture()
    other=ResearchStore()
    with ThreadPoolExecutor(max_workers=2) as pool:
        watches=list(pool.map(lambda s:s.register_submission_watch(payload,trusted_context=context),(store,other)))
    assert sum(w['registration_created'] for w in watches)==1
    assert watches[0]['watch_id']==watches[1]['watch_id']
    store.close();other.close()


def test_http_watch_requires_trusted_identity_and_original_conversation(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    store, context, conversation, payload=fixture()
    monkeypatch.setattr(main,'research_store',store)
    client=TestClient(main.app)
    path='/v1/research/submission-watches'
    assert client.post(path,json=payload).status_code==401
    headers={'x-byq-'+k.replace('_','-'):v for k,v in context.items()}
    response=client.post(path,json=payload,headers=headers)
    assert response.status_code==201,response.text
    watch=response.json()
    assert client.get(path+'/'+watch['watch_id'],headers=headers).json()['status']=='awaiting_receipt'
    foreign=trusted_agent_context('http-other',session_id='other',trace_id='other')
    denied=client.get(path+'/'+watch['watch_id'],headers=foreign)
    assert denied.status_code==404 and watch['watch_id'] not in denied.text
    store.close()
