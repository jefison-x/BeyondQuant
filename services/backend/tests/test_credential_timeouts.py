from concurrent.futures import ThreadPoolExecutor, TimeoutError
from time import monotonic
import pytest
from fastapi.testclient import TestClient
from app import main
from app.db import execute
from tests.test_credentials import _store, _credential_payload, pytestmark
from tests.workspace_helpers import trusted_agent_context


@pytest.mark.parametrize('operation',['update','revoke','delete_profile'])
def test_locked_credential_write_returns_bounded_safe_error_without_late_commit(monkeypatch,operation):
    store=_store();monkeypatch.setattr(main,'credential_store',store)
    credential=store.create_credential('timeout-owner',_credential_payload(),actor='timeout-owner')
    profile=store.create_profile('timeout-owner',{'credential_id':credential['credential_id'],'key_name':'locked-profile',
        'display_name':'Locked','provider':'deepseek','model':'deepseek-v4-flash','temperature':0.2,'reasoning_enabled':False})
    client=TestClient(main.app,raise_server_exceptions=False)
    headers=trusted_agent_context('timeout-owner')
    if operation=='delete_profile':
        path='/v1/users/model-profiles/'+profile['profile_id']+'/delete';method='POST';payload={'expected_version':1}
        sql='SELECT profile_id FROM model_profiles WHERE profile_id=:identity FOR UPDATE';identity=profile['profile_id']
    else:
        path='/v1/users/model-credentials/'+credential['credential_id'];method='PUT';payload={'expected_version':1,'request_id':'locked-operation','label':'must-not-commit'}
        if operation=='revoke':path+='/revoke';method='POST';payload.pop('label')
        sql='SELECT credential_id FROM credentials WHERE credential_id=:identity FOR UPDATE';identity=credential['credential_id']
    response=None
    try:
        with ThreadPoolExecutor(1) as executor:
            with store.engine.begin() as blocking:
                execute(blocking,sql,{'identity':identity})
                start=monotonic();future=executor.submit(client.request,method,path,json=payload,headers=headers)
                try:response=future.result(timeout=3)
                except TimeoutError:pass
            future.result(timeout=5)
        assert response is not None,'write remained blocked beyond its response budget'
        assert response.status_code==503 and monotonic()-start<3
        assert response.json()=={'detail':'credential storage is unavailable'}
        assert store.get_credential(credential['credential_id'],owner='timeout-owner')['version']==1
        assert store.get_profile(profile['profile_id'],owner='timeout-owner')['version']==1
    finally:store.close()


def test_busy_local_credential_store_returns_before_database_wait(monkeypatch):
    store=_store();monkeypatch.setattr(main,'credential_store',store)
    client=TestClient(main.app,raise_server_exceptions=False)
    response=None
    try:
        with ThreadPoolExecutor(1) as executor:
            with store._lock:
                start=monotonic()
                future=executor.submit(client.get,'/v1/users/model-credentials',headers=trusted_agent_context('timeout-owner'))
                try:response=future.result(timeout=3)
                except TimeoutError:pass
            future.result(timeout=5)
        assert response is not None and response.status_code==503 and monotonic()-start<3
        assert response.json()=={'detail':'credential storage is unavailable'}
    finally:store.close()


def test_private_resolver_storage_failure_is_safe_and_not_a_model_selection_result(monkeypatch):
    from app.credentials import CredentialPersistenceError
    monkeypatch.setattr(main,'CREDENTIAL_RESOLVER_TOKEN','test-resolver-only')
    def unavailable(*args):raise CredentialPersistenceError('private database diagnostics must not escape')
    monkeypatch.setattr(main.credential_store,'resolve_model',unavailable)
    response=TestClient(main.app,raise_server_exceptions=False).post('/internal/credentials/model-resolution',
        headers={'x-byq-credential-resolver-token':'test-resolver-only'},
        json={'owner_principal':'timeout-owner','agent_id':'byq-product','session_id':'synthetic-session','trace_id':'synthetic-trace'})
    assert response.status_code==503
    assert response.json()=={'detail':'credential storage is unavailable'}
