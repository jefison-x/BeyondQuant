import json
import pytest
from app import main
from fastapi.testclient import TestClient
from tests.test_credentials import _store,_credential_payload,pytestmark
from tests.workspace_helpers import trusted_agent_context


def test_original_credential_receipts_are_private_metadata_only_after_rotation_and_revoke(monkeypatch):
    headers=trusted_agent_context('receipt-owner')
    store=_store();monkeypatch.setattr(main,'credential_store',store)
    try:
        credential=store.create_credential('receipt-owner',_credential_payload(),actor='receipt-owner')
        identity=credential['credential_id']
        store.update_credential(identity,'receipt-owner',{'secret':'synthetic-replacement-key-1234','expected_version':1,'request_id':'replace-original'},actor='receipt-owner')
        store.revoke_credential(identity,'receipt-owner',expected_version=2,request_id='revoke-original',actor='receipt-owner')
        store.revoke_credential(identity,'receipt-owner',expected_version=2,request_id='revoke-alias',actor='receipt-owner')
        client=TestClient(main.app)
        for operation,key,version in [('create','credential-create-1',1),('update','replace-original',2),('revoke','revoke-original',3),('revoke','revoke-alias',3)]:
            params={'operation':operation,'request_id':key}
            if operation!='create':params['credential_id']=identity
            response=client.get('/v1/users/model-credentials/receipts',params=params,headers=headers)
            assert response.status_code==200
            value=response.json();assert value['state']=='confirmed' and value['credential_id']==identity and value['committed_version']==version
            assert set(value)=={'state','operation','credential_id','committed_version'}
            serialized=json.dumps(value)
            for forbidden in ('envelope','secret','nonce','ciphertext','synthetic-replacement','sk-phase37'):assert forbidden not in serialized
        assert store.reconcile_model_write('create','credential-create-1',owner='foreign')=={'state':'not_found'}
        assert store.reconcile_model_write('update','replace-original',owner='receipt-owner',credential_id='cred_'+'f'*32)=={'state':'not_found'}
        assert store.reconcile_model_write('revoke','replace-original',owner='receipt-owner',credential_id=identity)=={'state':'not_found'}
        assert len(store.list_audit('receipt-owner'))==4
    finally:store.close()


@pytest.mark.parametrize('system',[False,True])
def test_concurrent_credential_creation_has_one_original_identity(system):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    stores=[_store() for _ in range(8)]
    payload=_credential_payload()
    if system:payload.update(purpose='tushare_token',provider='tushare',scope='system')
    barrier=Barrier(8)
    try:
        def create(store):
            barrier.wait(timeout=5)
            return store.create_credential('alice',payload,actor='alice',actor_role='admin')
        with ThreadPoolExecutor(8) as executor:results=list(executor.map(create,stores))
        assert len({row['credential_id'] for row in results})==1
        assert stores[0]._fetch_one('SELECT count(*) AS n FROM credentials')['n']==1
        assert stores[0]._fetch_one('SELECT count(*) AS n FROM credential_audit')['n']==1
    finally:
        for store in stores:store.close()


def test_legacy_ambiguous_system_original_key_is_not_arbitrarily_replayed():
    from app.credentials import CredentialConflict
    store=_store()
    try:
        payload={**_credential_payload(),'purpose':'tushare_token','provider':'tushare','scope':'system'}
        store.create_credential('alice',payload,actor='alice',actor_role='admin')
        second=store.create_credential('alice',{**payload,'idempotency_key':'other-key'},actor='alice',actor_role='admin')
        # Reproduce an old NULL-owner duplicate using valid separately encrypted test rows.
        store._execute('UPDATE credentials SET idempotency_key=:key WHERE credential_id=:identity',{'key':payload['idempotency_key'],'identity':second['credential_id']})
        with pytest.raises(CredentialConflict,match='ambiguous'):
            store.create_credential('alice',payload,actor='alice',actor_role='admin')
    finally:store.close()
