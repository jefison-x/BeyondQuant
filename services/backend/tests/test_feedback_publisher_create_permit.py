from __future__ import annotations

import pytest
from app.product_feedback import ProductFeedbackStore,FeedbackConflict
from test_product_feedback import provision,create,submit,pytestmark


def seed():
    _,alice,_=provision();store=ProductFeedbackStore()
    item=submit(store,create(store,alice),alice)
    for action in ('triage','accept'):
        item=store.moderate(item['feedback_id'],action,{'expected_version':item['version'],
            'rationale':'approved synthetic snapshot','idempotency_key':'permit-'+action},
            trusted_actor='feedback-admin',actor_role='admin')['feedback']
    store.publisher_heartbeat({'configured':True,'credential_kind':'github_app',
        'repository':'jefison-x/BeyondQuant','worker_version':'test-v1'})
    event=store.claim_publications({'worker_id':'worker-original','limit':1,'lease_seconds':15})['events'][0]
    return store,event


def test_create_permission_cannot_repeat_after_lost_reply_restart_and_reclaim():
    store,event=seed();payload={'worker_id':'worker-original','lease_fence':event['lease_fence']}
    try:
        assert store.begin_publication_create(event['event_id'],payload)['allowed'] is True
        assert store.begin_publication_create(event['event_id'],payload)['allowed'] is False
        store.close();store=ProductFeedbackStore()
        store._execute("UPDATE product_feedback_outbox SET lease_expires_at=now()-interval '1 second'")
        replacement=store.claim_publications({'worker_id':'worker-replacement','limit':1,'lease_seconds':15})['events'][0]
        with pytest.raises(FeedbackConflict):store.begin_publication_create(event['event_id'],payload)
        assert store.begin_publication_create(event['event_id'],{'worker_id':'worker-replacement',
            'lease_fence':replacement['lease_fence']})['allowed'] is False
        # Read-only reconciliation can still complete the original issue.
        assert store.complete_publication(event['event_id'],{'worker_id':'worker-replacement',
            'lease_fence':replacement['lease_fence'],'repository':'jefison-x/BeyondQuant','issue_number':321,
            'html_url':'https://github.com/jefison-x/BeyondQuant/issues/321','provider_identity':'9001'})['status']=='published'
    finally:store.close()


def test_expired_lease_cannot_start_an_external_create():
    store,event=seed()
    try:
        store._execute("UPDATE product_feedback_outbox SET lease_expires_at=now()-interval '1 second'")
        with pytest.raises(FeedbackConflict):store.begin_publication_create(event['event_id'],{
            'worker_id':'worker-original','lease_fence':event['lease_fence']})
        assert store._fetch_one('SELECT create_started FROM product_feedback_outbox')['create_started'] is False
    finally:store.close()


def test_old_events_migrate_to_reconciliation_only():
    store,event=seed()
    try:
        store._execute('ALTER TABLE product_feedback_outbox DROP COLUMN create_started')
        store.close();store=ProductFeedbackStore()
        assert store.begin_publication_create(event['event_id'],{'worker_id':'worker-original',
            'lease_fence':event['lease_fence']})['allowed'] is False
    finally:store.close()


def test_crash_reclaim_still_obeys_publication_attempt_limit():
    from app.product_feedback import MAX_PUBLICATION_ATTEMPTS
    store,event=seed()
    try:
        store._execute("UPDATE product_feedback_outbox SET attempt=:attempt,lease_expires_at=now()-interval '1 second'",
            {'attempt':MAX_PUBLICATION_ATTEMPTS})
        assert store.claim_publications({'worker_id':'worker-replacement','limit':1,'lease_seconds':15})['events']==[]
        row=store._fetch_one('SELECT attempt,state FROM product_feedback_outbox')
        assert row=={'attempt':MAX_PUBLICATION_ATTEMPTS,'state':'failed_terminal'}
    finally:store.close()
