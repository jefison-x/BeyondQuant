"""Durable central-Hub delivery evidence; no actual external Hub or GitHub calls."""
import pytest
from app.product_feedback import ProductFeedbackStore, FeedbackConflict, MAX_HUB_DELIVERY_ATTEMPTS
from tests.test_product_feedback import provision,create,submit,pytestmark


def seed():
    _,alice,_=provision()
    store=ProductFeedbackStore()
    submit(store,create(store,alice),alice)
    store.hub_relay_heartbeat({'configured':True,'hub_origin':'https://feedback.example.org','worker_version':'feedback-hub-relay.v1'})
    return store


def claim(store,worker='relay-original'):
    return store.claim_hub_deliveries({'worker_id':worker,'limit':1,'lease_seconds':15})['events']


def test_crashed_relay_claims_cannot_bypass_durable_attempt_cap():
    store=seed()
    original=None
    try:
        for index in range(MAX_HUB_DELIVERY_ATTEMPTS):
            event=claim(store)[0]
            identity=(event['event_id'],event['installation_id'],event['snapshot_hash'],event['snapshot'])
            original=identity if original is None else original
            assert identity==original and event['attempt']==index+1
            store._execute("UPDATE product_feedback_hub_outbox SET lease_expires_at=now()-interval '1 second'")
            if index==3:
                store.close();store=ProductFeedbackStore()
        assert claim(store)==[]
        row=store._fetch_one('SELECT * FROM product_feedback_hub_outbox')
        assert row['state']=='failed_terminal' and row['attempt']==MAX_HUB_DELIVERY_ATTEMPTS
        assert row['last_error_category']=='retry_exhausted'
        assert row['snapshot_hash']==original[2] and row['snapshot_json']==original[3]
    finally:store.close()


def test_stale_relay_fence_and_late_status_cannot_replace_confirmed_publication():
    store=seed()
    try:
        first=claim(store)[0]
        store._execute("UPDATE product_feedback_hub_outbox SET lease_expires_at=now()-interval '1 second'")
        second=claim(store,'relay-replacement')[0]
        receipt='central_feedback_'+'d'*32
        payload={'worker_id':'relay-original','lease_fence':first['lease_fence'],'receipt_id':receipt,'status_token':'e'*64}
        with pytest.raises(FeedbackConflict):store.complete_hub_delivery(first['event_id'],payload)
        store.complete_hub_delivery(second['event_id'],{**payload,'worker_id':'relay-replacement','lease_fence':second['lease_fence']})
        published={'schema_version':'central-feedback-status.v1','receipt_id':receipt,'status':'published',
            'github_issue':{'repository':'jefison-x/BeyondQuant','issue_number':123,'html_url':'https://github.com/jefison-x/BeyondQuant/issues/123'}}
        store.update_hub_status(second['event_id'],published)
        with pytest.raises(FeedbackConflict):
            store.update_hub_status(second['event_id'],{**published,'status':'received','github_issue':None})
        with pytest.raises(FeedbackConflict):
            store.update_hub_status(second['event_id'],{**published,'github_issue':{**published['github_issue'],
                'issue_number':124,'html_url':'https://github.com/jefison-x/BeyondQuant/issues/124'}})
        row=store._fetch_one('SELECT * FROM product_feedback_hub_outbox')
        assert row['state']=='published' and row['github_issue_number']==123
    finally:store.close()


def test_hub_callback_lock_timeout_is_safe_and_cannot_commit_late(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor,TimeoutError
    from fastapi.testclient import TestClient
    from app import main
    from app.db import execute
    store=seed();event=claim(store)[0]
    monkeypatch.setattr(main,'feedback_store',store)
    monkeypatch.setattr(main,'FEEDBACK_HUB_RELAY_TOKEN','synthetic-hub-service-only')
    client=TestClient(main.app,raise_server_exceptions=False)
    response=None
    try:
        with ThreadPoolExecutor(1) as executor:
            with store.engine.begin() as blocked:
                execute(blocked,'SELECT event_id FROM product_feedback_hub_outbox WHERE event_id=:id FOR UPDATE',{'id':event['event_id']})
                future=executor.submit(client.post,f"/internal/feedback-hub/{event['event_id']}/complete",
                    headers={'x-byq-feedback-hub-relay-token':'synthetic-hub-service-only'},json={
                        'worker_id':'relay-original','lease_fence':event['lease_fence'],
                        'receipt_id':'central_feedback_'+'d'*32,'status_token':'e'*64})
                try:response=future.result(timeout=3)
                except TimeoutError:pass
            future.result(timeout=5)
        assert response is not None,'Hub callback remained waiting past the bounded metadata window'
        assert response.status_code==503 and response.json()=={'detail':'feedback storage is unavailable'}
        row=store._fetch_one('SELECT state,receipt_id FROM product_feedback_hub_outbox')
        assert row=={'state':'delivering','receipt_id':None}
    finally:store.close()


def test_publisher_retry_status_is_allowed_but_received_cannot_regress():
    store=seed();event=claim(store)[0];receipt='central_feedback_'+'d'*32
    try:
        store.complete_hub_delivery(event['event_id'],{'worker_id':'relay-original','lease_fence':event['lease_fence'],
            'receipt_id':receipt,'status_token':'e'*64})
        status={'schema_version':'central-feedback-status.v1','receipt_id':receipt,'github_issue':None}
        for state in ('accepted','publishing','accepted'):
            assert store.update_hub_status(event['event_id'],{**status,'status':state})['status']==state
        with pytest.raises(FeedbackConflict):store.update_hub_status(event['event_id'],{**status,'status':'received'})
    finally:store.close()


def test_failed_status_queries_do_not_starve_later_receipts_after_restart():
    _,alice,_=provision();store=ProductFeedbackStore()
    try:
        for index in range(2):
            submit(store,create(store,alice,f'fair-create-{index}'),alice,f'fair-submit-{index}')
        store.hub_relay_heartbeat({'configured':True,'hub_origin':'https://feedback.example.org','worker_version':'feedback-hub-relay.v1'})
        events=store.claim_hub_deliveries({'worker_id':'relay-original','limit':2,'lease_seconds':15})['events']
        for index,event in enumerate(events):
            store.complete_hub_delivery(event['event_id'],{'worker_id':'relay-original','lease_fence':event['lease_fence'],
                'receipt_id':'central_feedback_'+str(index)*32,'status_token':'e'*64})
        first=store.claim_hub_status_checks({'limit':1})['items'][0]
        # No status callback: the first remote read failed. Its wait must survive restart.
        store.close();store=ProductFeedbackStore()
        second=store.claim_hub_status_checks({'limit':1})['items'][0]
        assert first['event_id']!=second['event_id']
        assert store.claim_hub_status_checks({'limit':1})['items']==[]
        store._execute("UPDATE product_feedback_hub_outbox SET next_status_check_at=now()-interval '1 second' WHERE event_id=:id",{'id':first['event_id']})
        assert store.claim_hub_status_checks({'limit':1})['items'][0]==first
    finally:store.close()


def test_status_check_claim_requires_relay_identity_and_valid_payload(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    store=seed();event=claim(store)[0]
    store.complete_hub_delivery(event['event_id'],{'worker_id':'relay-original','lease_fence':event['lease_fence'],
        'receipt_id':'central_feedback_'+'d'*32,'status_token':'e'*64})
    monkeypatch.setattr(main,'feedback_store',store)
    monkeypatch.setattr(main,'FEEDBACK_HUB_RELAY_TOKEN','synthetic-hub-service-only')
    client=TestClient(main.app,raise_server_exceptions=False)
    path='/internal/feedback-hub/status-checks/claim'
    headers={'x-byq-feedback-hub-relay-token':'synthetic-hub-service-only'}
    try:
        assert client.post(path,json={'limit':1}).status_code==401
        for payload in ({'limit':True},{'limit':0},{'limit':1,'extra':'no'}):
            assert client.post(path,headers=headers,json=payload).status_code==422
        result=client.post(path,headers=headers,json={'limit':1})
        assert result.status_code==200
        assert result.json()=={'schema_version':'feedback-hub-status-checks.v1','items':[{
            'event_id':event['event_id'],'receipt_id':'central_feedback_'+'d'*32,'status_token':'e'*64}]}
        assert client.post(path,headers=headers,json={'limit':1}).json()['items']==[]
    finally:store.close()
