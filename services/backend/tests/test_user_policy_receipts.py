from fastapi.testclient import TestClient
from app import main
from app.user_policy import UserPolicyStore
from tests.test_user_policy import pytestmark
from tests.workspace_helpers import trusted_agent_context

RULE={'name':'Original rule','description':'synthetic policy recovery','action':'byq_backtest_run','agent_id':'*','decision_mode':'auto_deny','risk_level':'high','priority':10,'enabled':True}


def test_policy_replays_do_not_recreate_deleted_rules_or_overwrite_later_settings(monkeypatch):
    store=UserPolicyStore();monkeypatch.setattr(main,'user_policy_store',store)
    client=TestClient(main.app);headers=trusted_agent_context('policy-owner')
    root='/v1/users/agent-policy'
    try:
        created=client.post(root+'/rules',json={**RULE,'request_id':'original-create'},headers=headers)
        assert created.status_code==201
        identity=created.json()['rule']['rule_id']
        updated=client.put(root+'/rules/'+identity,json={**RULE,'name':'Changed','expected_version':1,'request_id':'original-update'},headers=headers)
        assert updated.status_code==200
        deleted=client.post(root+'/rules/'+identity+'/delete',json={'expected_version':2,'request_id':'original-delete'},headers=headers)
        assert deleted.status_code==200
        assert client.post(root+'/rules',json={**RULE,'request_id':'original-create'},headers=headers).json()==created.json()
        assert client.put(root+'/rules/'+identity,json={**RULE,'name':'Changed','expected_version':1,'request_id':'original-update'},headers=headers).json()==updated.json()
        assert client.post(root+'/rules/'+identity+'/delete',json={'expected_version':2,'request_id':'original-delete'},headers=headers).json()==deleted.json()
        assert store.list_rules('policy-owner')==[]
        preset=client.post(root+'/presets/deny_backtests/apply',json={'request_id':'original-preset'},headers=headers)
        assert preset.status_code==200
        extra=client.post(root+'/rules',json={**RULE,'request_id':'later-rule'},headers=headers);assert extra.status_code==201
        assert client.post(root+'/presets/deny_backtests/apply',json={'request_id':'original-preset'},headers=headers).json()==preset.json()
        assert len(store.list_rules('policy-owner'))==3
        for key,paused in [('original-settings',True),('later-settings',False)]:
            assert client.put(root,json={'paused':paused,'request_id':key},headers=headers).status_code==200
        assert client.put(root,json={'paused':True,'request_id':'original-settings'},headers=headers).status_code==200
        assert store.get('policy-owner')['paused'] is False
        for operation,key,resource in [('rule_create','original-create',None),('rule_update','original-update',identity),('rule_delete','original-delete',identity),('preset','original-preset','deny_backtests'),('settings','original-settings',None)]:
            query={'operation':operation,'request_id':key}
            if resource:query['resource_id']=resource
            r=client.get(root+'/receipts',params=query,headers=headers);assert r.status_code==200 and r.json()['state']=='confirmed'
            assert client.get(root+'/receipts',params=query,headers=trusted_agent_context('foreign-owner')).json()=={'state':'not_found'}
        assert client.post(root+'/rules',json={**RULE,'name':'Different','request_id':'original-create'},headers=headers).status_code==409
        assert store._fetch_one('SELECT count(*) AS n FROM user_policy_command_receipts')['n']==7
    finally:store.close()


import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from app.user_policy import UserPolicyPersistenceError


def test_concurrent_original_rule_key_creates_one_rule_and_one_audit():
    stores=[UserPolicyStore() for _ in range(8)];barrier=Barrier(8)
    try:
        def create(store):
            barrier.wait(timeout=5)
            return store.create_rule('policy-owner',RULE,actor='policy-owner',request_id='concurrent-rule')
        with ThreadPoolExecutor(8) as executor:results=list(executor.map(create,stores))
        assert len({v['rule_id'] for v in results})==1
        assert len(stores[0].list_rules('policy-owner'))==1
        assert len(stores[0].list_audit('policy-owner'))==1
        assert stores[0]._fetch_one('SELECT count(*) AS n FROM user_policy_command_receipts')['n']==1
    finally:
        for store in stores:store.close()


@pytest.mark.parametrize('operation',['settings','rule_create','rule_update','rule_delete','preset'])
def test_policy_receipt_failure_rolls_back_every_policy_command(monkeypatch,operation):
    store=UserPolicyStore()
    try:
        store.update('policy-owner',{'paused':False},request_id='initial-settings')
        rule=store.create_rule('policy-owner',RULE,actor='policy-owner',request_id='initial-rule')
        before=(store.get('policy-owner'),store.list_rules('policy-owner'),store.list_audit('policy-owner'))
        def fail(*args,**kwargs):raise UserPolicyPersistenceError('synthetic receipt unavailable')
        monkeypatch.setattr(store,'_record_command',fail)
        kwargs={'actor':'policy-owner','request_id':'failed-command'}
        with pytest.raises(UserPolicyPersistenceError):
            if operation=='settings':store.update('policy-owner',{'paused':True},**kwargs)
            elif operation=='rule_create':store.create_rule('policy-owner',RULE,**kwargs)
            elif operation=='rule_update':store.update_rule(rule['rule_id'],'policy-owner',{**RULE,'name':'Changed','expected_version':1},**kwargs)
            elif operation=='rule_delete':store.delete_rule(rule['rule_id'],'policy-owner',expected_version=1,**kwargs)
            else:store.apply_preset('policy-owner','deny_backtests',**kwargs)
        assert (store.get('policy-owner'),store.list_rules('policy-owner'),store.list_audit('policy-owner'))==before
        assert store._fetch_one('SELECT count(*) AS n FROM user_policy_command_receipts')['n']==2
    finally:store.close()


def test_policy_wait_is_bounded_and_missing_identity_cannot_write(monkeypatch):
    from concurrent.futures import TimeoutError
    from time import monotonic
    from app.db import execute
    store=UserPolicyStore();monkeypatch.setattr(main,'user_policy_store',store)
    client=TestClient(main.app,raise_server_exceptions=False);headers=trusted_agent_context('policy-owner')
    try:
        assert client.post('/v1/users/agent-policy/rules',json=RULE,headers=headers).status_code==422
        response=None
        with ThreadPoolExecutor(1) as executor:
            with store.engine.begin() as blocking:
                execute(blocking,"SELECT pg_advisory_xact_lock(hashtextextended(:owner,0))",{'owner':'user-policy:policy-owner'})
                start=monotonic();future=executor.submit(client.post,'/v1/users/agent-policy/rules',json={**RULE,'request_id':'locked-original'},headers=headers)
                try:response=future.result(timeout=3)
                except TimeoutError:pass
            future.result(timeout=5)
        assert response is not None and response.status_code==503 and monotonic()-start<3
        assert response.json()=={'detail':'user policy storage is unavailable'}
        assert store.list_rules('policy-owner')==[]
        assert store._fetch_one('SELECT count(*) AS n FROM user_policy_command_receipts')['n']==0
    finally:store.close()
