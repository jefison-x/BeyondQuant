"""Finite domain handoff triggers for explicitly confirmed v1 permissions.

No timer/idle-round trigger: initial permission handoff happens at most once;
subsequent handoffs require a new authoritative strategy approval artifact.
"""
from .db import execute, fetch_one
from .research_handoff import JOB_SOURCES


def handoff_ready(connection, task, conversation):
    permission = task.get('continuation_permission') or {}
    progress = task.get('progress') or {}
    confirmed = set(permission.get('confirmed_artifact_ids', []))
    linked = {ref['id'] for ref in progress.get('linked_objects', []) if ref['kind'] == 'artifact'}
    if (permission.get('handoff_version') != 1 or not progress.get('next_action')
            or progress.get('blocked_reason') or progress.get('stage') in {'blocked', 'completed'}
            or not confirmed.intersection(linked)):
        return False
    params = {'task': task['task_id'], 'owner': task['owner_principal'], 'workspace': task['workspace_id'],
              'session': conversation['runtime_session_id'], 'trace': conversation['trace_id']}
    if fetch_one(connection, '''SELECT root_run_id FROM agent_runtime_turns
        WHERE owner_principal=:owner AND workspace_id=:workspace AND session_id=:session
          AND trace_id=:trace AND status='active' LIMIT 1''', params):
        return False
    bindings = ' UNION ALL '.join(
        f'SELECT {key} FROM {table} WHERE task_id=:task AND owner_principal=:owner AND workspace_id=:workspace'
        for table, key in (('artifacts', 'artifact_id'), *JOB_SOURCES))
    if fetch_one(connection, f'''SELECT approval_id FROM agent_approvals
        WHERE owner_principal=:owner AND workspace_id=:workspace AND resource_id IN ({bindings})
          AND (status='pending' OR continuation_status IN ('queued','submitting','outcome_unknown')) LIMIT 1''', params):
        return False
    # A submitted approval continuation is not proof that the approved
    # strategy action has committed. Wait for its exact domain artifact.
    if fetch_one(connection, f'''SELECT a.approval_id FROM agent_approvals a
        WHERE a.owner_principal=:owner AND a.workspace_id=:workspace AND a.resource_id IN ({bindings})
          AND a.status='approved' AND a.action IN ('byq_strategy_approve','byq_ml_strategy_approve')
          AND NOT EXISTS (SELECT 1 FROM artifacts f WHERE f.task_id=:task
            AND f.owner_principal=:owner AND f.workspace_id=:workspace AND f.status='validated'
            AND ((a.action='byq_strategy_approve' AND f.kind='strategy_approval'
                  AND f.content->>'strategy_version_artifact_id'=a.resource_id)
              OR (a.action='byq_ml_strategy_approve' AND f.kind='ml_strategy_approval'
                  AND f.content->>'ml_strategy_artifact_id'=a.resource_id))
            AND f.content->>'decision'='approved' AND f.content->'execution_authorized'='true'::jsonb)
        LIMIT 1''', params):
        return False
    if fetch_one(connection, '''SELECT watch_id FROM research_receipt_watches
        WHERE owner_principal=:owner AND workspace_id=:workspace AND conversation_id=:conversation
          AND state <> 'confirmed' AND (parent_task_id=:task OR
            (entity_type='research_task' AND idempotency_key=:key)) LIMIT 1''',
        {**params, 'conversation': task['conversation_id'], 'key': task['idempotency_key']}):
        return False
    if fetch_one(connection, '''SELECT watch_id FROM ml_training_receipt_watches
        WHERE owner_principal=:owner AND workspace_id=:workspace AND state <> 'confirmed'
          AND identity_json->>'task_id'=:task LIMIT 1''', params):
        return False
    for table, key in JOB_SOURCES:
        if fetch_one(connection, f'''SELECT {key} FROM {table}
            WHERE task_id=:task AND owner_principal=:owner AND workspace_id=:workspace
              AND status NOT IN ('completed','failed','cancelled') LIMIT 1''', params):
            return False
    return True


def handoff_events(connection, task, conversation):
    if not handoff_ready(connection, task, conversation):
        return []
    permission = task['continuation_permission']
    ledger = task.get('continuation_budget') or []
    if not ledger:
        # This event exists only on a newly confirmed permission. Replaying an
        # old grant never adds the marker or grants another initial handoff.
        return [{'kind': 'permission_handoff', 'identity': task['task_id'], 'status': 'confirmed',
                 'grant_version': permission['grant_version'], 'updated_at': permission['created_at']}]
    # A previous task-bound turn already had the opportunity to read earlier
    # approvals. Only a newly committed approval can trigger another handoff.
    since = max(row['created_at'] for row in ledger)
    events = []
    for kind, field, strategy_kind in (
        ('strategy_approval', 'strategy_version_artifact_id', 'strategy_version'),
        ('ml_strategy_approval', 'ml_strategy_artifact_id', 'ml_strategy_version'),
    ):
        rows = execute(connection, f'''SELECT a.artifact_id AS identity,a.created_at AS updated_at,
                a.content->>'{field}' AS strategy_artifact_id
            FROM artifacts a JOIN artifacts s ON s.artifact_id=a.content->>'{field}'
            WHERE a.task_id=:task AND a.owner_principal=:owner AND a.workspace_id=:workspace
              AND a.kind=:kind AND a.status='validated'
              AND a.content->>'decision'='approved' AND a.content->'execution_authorized'='true'::jsonb
              AND a.created_at > CAST(:since AS TIMESTAMPTZ)
              AND NOT EXISTS (SELECT 1 FROM artifacts newer
                WHERE newer.task_id=:task AND newer.owner_principal=:owner AND newer.workspace_id=:workspace
                  AND newer.kind=:kind AND newer.status='validated'
                  AND newer.content->>'{field}'=a.content->>'{field}'
                  AND (newer.created_at,newer.artifact_id) > (a.created_at,a.artifact_id))
              AND s.task_id=:task AND s.owner_principal=:owner AND s.workspace_id=:workspace
              AND s.kind=:strategy_kind AND s.status='validated'
              AND s.artifact_id IN (SELECT jsonb_array_elements_text(CAST(:confirmed AS JSONB)))
            ORDER BY a.created_at,a.artifact_id LIMIT 64''',
            {'task': task['task_id'], 'owner': task['owner_principal'], 'workspace': task['workspace_id'],
             'kind': kind, 'strategy_kind': strategy_kind, 'since': since,
             'confirmed': permission['confirmed_artifact_ids']})
        events.extend({'kind': 'approval_handoff', 'status': 'approved', **row} for row in rows)
    return events
