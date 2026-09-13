from __future__ import annotations
import pytest
from app.product_feedback import ProductFeedbackStore,FeedbackForbidden
from test_product_feedback import provision,create,submit,pytestmark


def test_moderation_receipt_survives_later_transition_restart_and_actor_isolation():
    _,alice,_=provision();store=ProductFeedbackStore()
    item=submit(store,create(store,alice),alice)
    original_id=item['feedback_id']
    try:
        triaged=store.moderate(original_id,'triage',{'expected_version':item['version'],
            'rationale':'已核实问题','idempotency_key':'triage-original'},trusted_actor='feedback-admin',actor_role='admin')['feedback']
        store.moderate(original_id,'accept',{'expected_version':triaged['version'],
            'rationale':'批准发布','idempotency_key':'accept-original'},trusted_actor='feedback-admin',actor_role='admin')
        store.close();store=ProductFeedbackStore()
        context={'trusted_actor':'feedback-admin','actor_role':'admin'}
        recovered=store.reconcile_moderation(original_id,'triage','triage-original',**context)
        assert recovered=={'state':'confirmed','feedback':triaged}
        assert store.reconcile_moderation(original_id,'accept','accept-original',**context)['feedback']['status']=='accepted'
        assert store.reconcile_moderation(original_id,'triage','triage-original',trusted_actor='another-admin',actor_role='admin')=={'state':'not_found'}
        with pytest.raises(FeedbackForbidden):store.reconcile_moderation(original_id,'triage','triage-original',trusted_actor='feedback-admin',actor_role='user')
        assert store._fetch_one('SELECT count(*) AS n FROM product_feedback_outbox')['n']==1
    finally:store.close()
