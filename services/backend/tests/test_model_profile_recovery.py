from tests.test_credentials import _store, _credential_payload, pytestmark
from app import main
from fastapi.testclient import TestClient
from tests.workspace_helpers import trusted_agent_context


def test_profile_original_key_receipt_survives_delete_without_leaking_other_owners(monkeypatch):
    store=_store();monkeypatch.setattr(main,'credential_store',store)
    try:
        credential=store.create_credential('profile-owner',_credential_payload(),actor='profile-owner')
        payload={'credential_id':credential['credential_id'],'key_name':'original-profile','display_name':'Original',
                 'provider':'deepseek','model':'deepseek-v4-flash','temperature':0.2,'reasoning_enabled':False}
        profile=store.create_profile('profile-owner',payload)
        store.delete_profile(profile['profile_id'],'profile-owner',expected_version=1)
        client=TestClient(main.app)
        receipt=client.get('/v1/users/model-profiles/receipts',params={'key_name':payload['key_name']},headers=trusted_agent_context('profile-owner'))
        assert receipt.status_code==200
        assert receipt.json()=={'state':'confirmed','profile_id':profile['profile_id'],'committed_version':1,'input':payload}
        assert client.get('/v1/users/model-profiles/receipts',params={'key_name':payload['key_name']},headers=trusted_agent_context('foreign-owner')).json()=={'state':'not_found'}
        assert client.get('/v1/users/model-profiles/receipts',params={'key_name':'absent'},headers=trusted_agent_context('profile-owner')).json()=={'state':'not_found'}
    finally:store.close()
