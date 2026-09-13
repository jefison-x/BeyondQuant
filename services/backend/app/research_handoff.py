"""Read-only handoff projection from durable domain facts (ADR-0062).

Never schedules work or changes task lifecycle. A database snapshot prevents
mixing a pre-cancellation task with post-cancellation delivery facts.
"""
import os
from datetime import datetime, timezone

from .db import execute, fetch_one

LIMIT = 64
JOB_SOURCES = (
    ('ml_training_runs', 'training_run_id'),
    ('ml_prediction_runs', 'prediction_run_id'),
    ('signal_producer_jobs', 'job_id'),
    ('backtest_jobs', 'job_id'),
)


class ResearchHandoffMixin:
    def get_task_handoff(self, task_id, *, trusted_context):
        from .research import ResearchNotFound, _identifier
        from .agent_research import APPROVAL_RESOURCE_TYPES
        task_id = _identifier(task_id, field='task_id')
        params = {'task': task_id, 'owner': trusted_context.get('owner_principal'),
                  'workspace': trusted_context.get('workspace_id')}
        with self._transaction() as connection:
            execute(connection, 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            task = fetch_one(connection, '''SELECT t.* FROM research_tasks t
                JOIN workspaces w ON w.workspace_id=t.workspace_id
                JOIN users u ON u.user_id=w.owner_user_id
                JOIN workspace_memberships m ON m.workspace_id=w.workspace_id AND m.user_id=u.user_id
                WHERE t.task_id=:task AND t.owner_principal=:owner AND t.workspace_id=:workspace
                  AND u.username=:owner AND u.status='active' AND w.status='active'
                  AND m.status='active' AND m.role='owner' ''', params)
            if task is None:
                raise ResearchNotFound('research task not found')
            conversation = fetch_one(connection, '''SELECT * FROM product_conversations
                WHERE conversation_id=:conversation AND owner_principal=:owner AND workspace_id=:workspace''',
                {**params, 'conversation': task.get('conversation_id')})
            bindings = ' UNION ALL '.join(
                f'SELECT {key} FROM {table} WHERE task_id=:task AND owner_principal=:owner AND workspace_id=:workspace'
                for table, key in (('artifacts', 'artifact_id'), *JOB_SOURCES))
            approvals = execute(connection, f'''SELECT a.approval_id AS identity,a.status,a.continuation_status,a.action,a.resource_type,f.kind AS artifact_kind
                FROM agent_approvals a LEFT JOIN artifacts f ON f.artifact_id=a.resource_id
                JOIN agent_runs r ON r.run_id=a.run_id
                WHERE a.resource_id IN ({bindings})
                  AND a.owner_principal=:owner AND a.workspace_id=:workspace
                  AND r.owner_principal=:owner AND r.workspace_id=:workspace AND r.trace_id=:trace
                  AND (a.status='pending' OR a.continuation_status IN ('queued','submitting','outcome_unknown'))
                ORDER BY a.created_at,a.approval_id LIMIT 65''', {**params, 'trace': task['trace_id']})
            jobs = []
            truncated = len(approvals) > LIMIT
            for table, key in JOB_SOURCES:
                rows = execute(connection, f'''SELECT {key} AS identity,status FROM {table}
                    WHERE task_id=:task AND owner_principal=:owner AND workspace_id=:workspace
                      AND status NOT IN ('completed','failed','cancelled')
                    ORDER BY created_at,{key} LIMIT 65''', params)
                truncated |= len(rows) > LIMIT
                jobs.extend({'kind': table, **row} for row in rows[:LIMIT])
            active = None
            if conversation is not None:
                active = fetch_one(connection, '''SELECT root_run_id FROM agent_runtime_turns
                    WHERE owner_principal=:owner AND workspace_id=:workspace AND session_id=:session
                      AND trace_id=:trace AND status='active' LIMIT 1''',
                    {**params, 'session': conversation['runtime_session_id'], 'trace': task['trace_id']})
            completion = []
            for identity in (task.get('progress') or {}).get('completion_evidence', []):
                evidence = fetch_one(connection, """SELECT artifact_id FROM artifacts WHERE artifact_id=:artifact
                    AND task_id=:task AND owner_principal=:owner AND workspace_id=:workspace AND status='validated'""",
                    {**params, 'artifact': identity})
                if evidence:
                    completion.append(identity)
        progress = task.get('progress') or {}
        permission = self._continuation_view(task, conversation or {'status': 'inactive'})
        now = datetime.now(timezone.utc)
        deliveries = [r for r in (task.get('continuation_budget') or []) if r['status'] != 'settled']
        refs = [{'kind': 'approval', 'id': r['identity'], 'status': r['status']} for r in approvals[:LIMIT]]
        refs += [{'kind': r['kind'], 'id': r['identity'], 'status': r['status']} for r in jobs]
        reason = None
        if task['status'] == 'completed' and (not completion
                or len(completion) != len(progress.get('completion_evidence', []))
                or progress.get('stage') != 'completed' or progress.get('next_action')
                or progress.get('blocked_reason')):
            state, reason = 'needs_reconciliation', 'completion_evidence_missing'
        elif task['status'] in {'completed', 'failed', 'cancelled'}:
            state = task['status']
        elif truncated:
            state, reason = 'needs_reconciliation', 'evidence_limit_reached'
        elif any(r['status'] == 'outcome_unknown' for r in deliveries):
            state, reason = 'needs_reconciliation', 'continuation_result_unconfirmed'
        elif any(r['action'] in {'byq_strategy_approve', 'byq_ml_strategy_approve'}
                 and (r['resource_type'] != APPROVAL_RESOURCE_TYPES[r['action']]
                      or r['artifact_kind'] != APPROVAL_RESOURCE_TYPES[r['action']]) for r in approvals):
            state, reason = 'needs_reconciliation', 'approval_binding_invalid'
        elif any(r['continuation_status'] in {'submitting', 'outcome_unknown'} for r in approvals):
            state, reason = 'needs_reconciliation', 'approval_continuation_unconfirmed'
        elif any(r['status'] == 'pending' for r in approvals):
            state = 'waiting_approval'
        elif any(r['continuation_status'] == 'queued' for r in approvals):
            state = 'approval_continuation_queued'
        elif jobs:
            state = 'waiting_job'
        elif active is not None:
            # A conversation can contain several tasks. Do not attribute this
            # run to this task without a task-scoped delivery receipt.
            state, reason = 'conversation_active', 'task_execution_unconfirmed'
        elif deliveries:
            ready = [r for r in deliveries if r['status'] == 'reserved' and r.get('instruction')
                     and r.get('dispatch_attempts', 0) < 8
                     and datetime.fromisoformat(r['expires_at']) > now]
            blocked = self._permission_blocked_reason(task, conversation or {'status': 'inactive'})
            if ready and blocked is None and os.environ.get('BYQ_F6_EXECUTOR_ENABLED') == '1':
                state = 'continuation_queued'
            else:
                state, reason = 'needs_reconciliation', blocked or 'continuation_result_unconfirmed'
        elif conversation is None:
            state, reason = 'blocked', 'conversation_binding_missing'
        elif permission['blocked_reason'] in {'permission_missing', 'permission_revoked', 'permission_expired'}:
            state, reason = 'needs_permission', permission['blocked_reason']
        else:
            state, reason = 'blocked', permission['blocked_reason']
            if reason == 'waiting_for_event':
                reason = 'no_registered_executor'
        return {'schema_version': 'research-task-handoff.v1', 'task_id': task_id,
                'task_version': task['version'], 'task_status': task['status'],
                'objective': task['objective'], 'progress': progress, 'state': state,
                'reason': reason, 'references': refs, 'has_more': truncated,
                'observed_at': now.isoformat()}
