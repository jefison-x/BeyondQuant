import os

import pytest
from app.continuation_scope import authorize
from tests.test_research_continuation import setup_permission
from tests.test_continuation_budget_ledger import reserve

pytestmark = pytest.mark.skipif(not os.environ.get('BYQ_DATABASE_URL'), reason='isolated PostgreSQL required')


def setup():
    store, task, context, payload = setup_permission()
    store.create_continuation_permission(task, payload, trusted_context=context)
    receipt = reserve(store, task, context)
    store.record_continuation_receipt(task, trusted_context=context,
        reservation_id=receipt['reservation_id'], status='outcome_unknown')
    return store, task, context, payload, receipt


def test_scope_binds_original_task_and_root_before_lost_prompt_ack():
    store, task, context, _, receipt = setup()
    call = dict(tool='byq_research_get', arguments={'entity_type': 'research_task', 'entity_id': ' ' + task + '\t'}, root_run_id='a'*32)
    try:
        reply = authorize(store, receipt['reservation_id'], call, context)
        assert reply['admitted'] is True and reply['task_id'] == task
        assert reserve(store, task, context)['run_id'] == 'a'*32
        with pytest.raises(ValueError, match='no longer admitted'):
            authorize(store, receipt['reservation_id'], {**call, 'root_run_id': 'b'*32}, context)
    finally:
        store.close()


@pytest.mark.parametrize('tool', ['byq_agent_approval_decide', 'byq_research_task_create',
    'byq_ml_training_create', 'byq_pool_create', 'byq_feedback_submit', 'byq_agent_context'])
def test_background_scope_cannot_approve_or_change_goals(tool):
    store, _, context, _, receipt = setup()
    try:
        assert authorize(store, receipt['reservation_id'], dict(tool=tool, arguments={}, root_run_id='a'*32), context)['admitted'] is False
    finally:
        store.close()


@pytest.mark.parametrize('padding', ['{}', ' {} ', '\t{}\n'])
def test_scope_rejects_same_owner_other_task_and_cross_conversation(padding):
    store, task, context, _, receipt = setup()
    try:
        other = store.create_task({'owner_principal': context['owner_principal'], 'title': 'Other task',
            'objective': 'Unrelated', 'trace_id': context['trace_id'], 'idempotency_key': 'other-task'}, trusted_context=context)
        identity = padding.format(other['task_id'])
        assert store.get_task(identity)['task_id'] == other['task_id']
        call = dict(tool='byq_research_transition', arguments={'entity_type': 'research_task',
            'entity_id': identity, 'target_status': 'running'}, root_run_id='a'*32)
        assert authorize(store, receipt['reservation_id'], call, context)['admitted'] is False
        with pytest.raises(ValueError, match='no longer admitted'):
            authorize(store, receipt['reservation_id'], {**call, 'arguments': {'entity_id': task}},
                {**context, 'session_id': 'other-conversation'})
        assert reserve(store, task, context)['run_id'] is None
    finally:
        store.close()


def test_revocation_refuses_new_domain_admission_without_refunding():
    store, task, context, payload, receipt = setup()
    try:
        store.revoke_continuation_permission(task, grant_version=1, trusted_context=context)
        with pytest.raises(ValueError, match='no longer admitted'):
            authorize(store, receipt['reservation_id'], dict(tool='byq_research_get',
                arguments={'entity_type': 'artifact', 'entity_id': payload['confirmed_artifact_ids'][0]}, root_run_id='a'*32), context)
        assert store.get_continuation_permission(task, trusted_context=context)['budget']['reserved_tokens'] == 600
    finally:
        store.close()
