from fastapi.testclient import TestClient
from app import main
from tests.test_credentials import _store,_credential_payload,pytestmark
from tests.workspace_helpers import trusted_agent_context


def test_binding_and_delete_receipts_keep_original_version_after_later_changes(monkeypatch):
    store=_store();monkeypatch.setattr(main,'credential_store',store)
    try:
        credential=store.create_credential('model-owner',_credential_payload(),actor='model-owner')
        profile=store.create_profile('model-owner',{'credential_id':credential['credential_id'],'key_name':'original-model',
            'display_name':'Original','provider':'deepseek','model':'deepseek-v4-flash','temperature':0.2,'reasoning_enabled':False})
        binding=store.bind('model-owner','byq-product',profile['profile_id'],expected_version=0)
        store.bind('model-owner','byq-product',None,expected_version=binding['version'])
        deleted=store.delete_profile(profile['profile_id'],'model-owner',expected_version=1)
        client=TestClient(main.app);headers=trusted_agent_context('model-owner')
        queries=[({'operation':'binding','resource_id':'byq-product','expected_version':0,'profile_id':profile['profile_id']},1),
                 ({'operation':'delete_profile','resource_id':profile['profile_id'],'expected_version':1},2)]
        for query,version in queries:
            r=client.get('/v1/users/model-commands/receipts',params=query,headers=headers)
            assert r.status_code==200
            body=r.json();assert body['state']=='confirmed' and body['committed_version']==version
            assert body['operation']==query['operation'] and body['resource_id']==query['resource_id']
            assert client.get('/v1/users/model-commands/receipts',params=query,headers=trusted_agent_context('foreign-owner')).json()=={'state':'not_found'}
        wrong={**queries[0][0],'profile_id':'profile_'+'f'*32}
        assert client.get('/v1/users/model-commands/receipts',params=wrong,headers=headers).json()=={'state':'not_found'}
        rows=store._execute('SELECT * FROM model_command_receipts')
        assert len(rows)==3 and {r['actor_principal'] for r in rows}=={'model-owner'}
        assert deleted['version']==2
    finally:store.close()


import pytest
from app.credentials import CredentialPersistenceError


@pytest.mark.parametrize('operation',['binding','delete_profile'])
def test_receipt_failure_rolls_back_model_command_and_binding_side_effects(monkeypatch,operation):
    store=_store()
    try:
        credential=store.create_credential('model-owner',_credential_payload(),actor='model-owner')
        profile=store.create_profile('model-owner',{'credential_id':credential['credential_id'],'key_name':'atomic-model',
            'display_name':'Atomic','provider':'deepseek','model':'deepseek-v4-flash','temperature':0.2,'reasoning_enabled':False})
        store.bind('model-owner','byq-product',profile['profile_id'],expected_version=0)
        def fail(*args,**kwargs):raise CredentialPersistenceError('synthetic receipt unavailable')
        monkeypatch.setattr(store,'_record_model_command',fail)
        with pytest.raises(CredentialPersistenceError):
            if operation=='binding':store.bind('model-owner','byq-product',None,expected_version=1)
            else:store.delete_profile(profile['profile_id'],'model-owner',expected_version=1)
        binding=store.list_bindings('model-owner')[0]
        assert binding['version']==1 and binding['profile_id']==profile['profile_id']
        assert store.get_profile(profile['profile_id'],owner='model-owner')['version']==1
        assert store._fetch_one('SELECT count(*) AS n FROM model_command_receipts')['n']==1
    finally:store.close()
