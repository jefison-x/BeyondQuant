import os

import pytest

from app.research import ResearchNotFound, ResearchStore
from tests.test_research_continuation import setup_permission

pytestmark = pytest.mark.skipif(not os.environ.get('BYQ_DATABASE_URL'), reason='isolated PostgreSQL required')


def test_orphaned_running_task_is_not_reported_as_executing_and_survives_restart():
    store, task, context, _ = setup_permission()
    store.transition('research_task', task, 'running', 'handoff-start')
    first = store.get_task_handoff(task, trusted_context=context)
    assert first['state'] == 'needs_permission'
    assert first['reason'] == 'permission_missing'
    assert first['task_status'] == 'running'
    assert first['objective'] == 'No execution'
    assert first['references'] == []
    store.close()
    reopened = ResearchStore()
    try:
        second = reopened.get_task_handoff(task, trusted_context=context)
        assert {k: v for k, v in first.items() if k != 'observed_at'} == {
            k: v for k, v in second.items() if k != 'observed_at'}
        assert reopened.get_task(task)['status'] == 'running'
    finally:
        reopened.close()


@pytest.mark.parametrize('field', ['owner_principal', 'workspace_id'])
def test_handoff_rejects_foreign_identity(field):
    store, task, context, _ = setup_permission()
    try:
        with pytest.raises(ResearchNotFound):
            store.get_task_handoff(task, trusted_context={**context, field: 'foreign'})
    finally:
        store.close()


def test_cancelled_task_wins_over_late_active_conversation():
    store, task, context, _ = setup_permission()
    try:
        store._execute('''INSERT INTO agent_runtime_turns
            (root_run_id,owner_principal,workspace_id,session_id,trace_id,status,created_at,updated_at)
            VALUES ('late-root',:owner,:workspace,'budget-session','budget-trace','active',now(),now())''',
            {'owner': context['owner_principal'], 'workspace': context['workspace_id']})
        assert store.get_task_handoff(task, trusted_context=context)['state'] == 'conversation_active'
        store.transition('research_task', task, 'cancelled', 'handoff-cancel')
        for _ in range(2):
            assert store.get_task_handoff(task, trusted_context=context)['state'] == 'cancelled'
    finally:
        store.close()


def test_permission_alone_does_not_mean_continuation_is_queued(monkeypatch):
    store, task, context, payload = setup_permission()
    try:
        monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
        store.create_continuation_permission(task, {**payload, 'token_limit': 4000000}, trusted_context=context)
        view = store.get_task_handoff(task, trusted_context=context)
        assert view['state'] == 'blocked'
        assert view['reason'] == 'no_registered_executor'
    finally:
        store.close()


@pytest.mark.parametrize('delivery_status,expected', [('reserved', 'continuation_queued'),
    ('outcome_unknown', 'needs_reconciliation'), ('accepted', 'needs_reconciliation')])
def test_durable_receipt_controls_queue_state_and_revocation(delivery_status, expected, monkeypatch):
    from datetime import datetime, timedelta, timezone
    store, task, context, payload = setup_permission()
    try:
        monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
        store.create_continuation_permission(task, {**payload, 'token_limit': 4000000}, trusted_context=context)
        store._execute('UPDATE research_tasks SET continuation_budget=:budget WHERE task_id=:task', {
            'task': task, 'budget': [{'status': delivery_status, 'instruction': 'synthetic',
                'token_limit': 100, 'charged_tokens': None, 'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}]})
        assert store.get_task_handoff(task, trusted_context=context)['state'] == expected
        store.revoke_continuation_permission(task, grant_version=1, trusted_context=context)
        assert store.get_task_handoff(task, trusted_context=context)['state'] != 'continuation_queued'
    finally:
        store.close()


def test_inactive_owner_cannot_read_handoff():
    store, task, context, _ = setup_permission()
    try:
        store._execute("UPDATE users SET status='disabled' WHERE username='budget-user'")
        with pytest.raises(ResearchNotFound):
            store.get_task_handoff(task, trusted_context=context)
    finally:
        store.close()


def test_exact_job_scope_and_terminal_job_does_not_complete_task():
    store, task, context, payload = setup_permission()
    try:
        params = {'task': task, 'owner': context['owner_principal'], 'workspace': context['workspace_id'],
                  'artifact': payload['confirmed_artifact_ids'][0]}
        store._execute('''INSERT INTO ml_training_runs
            (training_run_id,workspace_id,owner_principal,task_id,ml_strategy_artifact_id,
             stock_pool_snapshot_id,status,preparation_json,requirement_json,readiness_json,
             trace_id,idempotency_key,request_hash,created_at,updated_at)
            VALUES ('synthetic-job',:workspace,:owner,:task,:artifact,'synthetic-pool','running',
                    '{}','{}','{}','budget-trace','handoff-job','synthetic',now(),now())''', params)
        view = store.get_task_handoff(task, trusted_context=context)
        assert view['state'] == 'waiting_job'
        assert view['references'][0]['id'] == 'synthetic-job'
        other = store.create_task({'owner_principal': context['owner_principal'], 'title': 'Other task',
            'objective': 'Independent', 'trace_id': 'budget-trace', 'idempotency_key': 'other-handoff-task'},
            trusted_context=context)
        assert store.get_task_handoff(other['task_id'], trusted_context=context)['references'] == []
        store._execute("UPDATE ml_training_runs SET workspace_id=:workspace,status='completed' WHERE training_run_id='synthetic-job'", params)
        assert store.get_task_handoff(task, trusted_context=context)['state'] == 'needs_permission'
        assert store.get_task(task)['status'] == 'planned'
    finally:
        store.close()


def test_completed_lifecycle_without_evidence_needs_reconciliation():
    store, task, context, _ = setup_permission()
    try:
        store.transition('research_task', task, 'running', 'handoff-start')
        store.transition('research_task', task, 'completed', 'handoff-legacy-complete')
        view = store.get_task_handoff(task, trusted_context=context)
        assert view['state'] == 'needs_reconciliation'
        assert view['reason'] == 'completion_evidence_missing'
    finally:
        store.close()


def test_approval_wait_and_delivery_are_distinct_from_action_execution():
    from app.agent_research import AgentResearchStore
    from tests.test_agent_research import start
    store, task, context, payload = setup_permission()
    agents = AgentResearchStore()
    try:
        run = start(agents, owner_principal=context['owner_principal'], actor_principal=context['owner_principal'],
                    session_id='budget-session', trace_id='budget-trace')
        approval = agents.create_approval({'run_id': run['run_id'], 'action': 'byq_backtest_task_execute',
            'reason': 'Synthetic scope check', 'resource_type': 'artifact',
            'resource_id': payload['confirmed_artifact_ids'][0], 'idempotency_key': 'handoff-approval'})
        assert store.get_task_handoff(task, trusted_context=context)['state'] == 'waiting_approval'
        store._execute("UPDATE agent_approvals SET status='approved',continuation_status='queued' WHERE approval_id=:id", {'id': approval['approval_id']})
        assert store.get_task_handoff(task, trusted_context=context)['state'] == 'approval_continuation_queued'
        store._execute("UPDATE agent_approvals SET continuation_status='outcome_unknown' WHERE approval_id=:id", {'id': approval['approval_id']})
        assert store.get_task_handoff(task, trusted_context=context)['state'] == 'needs_reconciliation'
        store._execute("UPDATE agent_approvals SET continuation_status='submitted' WHERE approval_id=:id", {'id': approval['approval_id']})
        assert store.get_task_handoff(task, trusted_context=context)['state'] == 'needs_permission'
    finally:
        agents.close()
        store.close()


def test_completed_checkpoint_is_preserved_and_read_does_not_mutate_task():
    store, task, context, _ = setup_permission()
    try:
        report = store.create_artifact({'task_id': task, 'kind': 'research_report', 'content': {'synthetic': True},
            'lineage': [], 'trace_id': 'budget-trace', 'idempotency_key': 'handoff-report'})
        store.transition('artifact', report['artifact_id'], 'validated', 'handoff-report-validation')
        store.transition('research_task', task, 'running', 'handoff-start')
        progress = {'schema_version': 'research-progress.v1', 'stage': 'completed', 'next_action': None,
                    'blocked_reason': None, 'linked_objects': [], 'completion_evidence': [report['artifact_id']]}
        store.transition('research_task', task, 'completed', 'handoff-finish', progress=progress, require_completion_evidence=True)
        before = store._fetch_one('SELECT * FROM research_tasks WHERE task_id=:task', {'task': task})
        view = store.get_task_handoff(task, trusted_context=context)
        assert view['state'] == 'completed'
        assert view['progress'] == progress
        assert set(view) == {'schema_version', 'task_id', 'task_version', 'task_status', 'objective', 'progress',
                             'state', 'reason', 'references', 'has_more', 'observed_at'}
        assert store._fetch_one('SELECT * FROM research_tasks WHERE task_id=:task', {'task': task}) == before
    finally:
        store.close()
