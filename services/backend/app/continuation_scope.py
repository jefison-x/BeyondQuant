"""Task-bound MCP admission for an already reserved background model turn."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from .db import execute, fetch_one

TOOLS = frozenset({
    'byq_agent_roles', 'byq_agent_run_start', 'byq_agent_authorize',
    'byq_agent_audit', 'byq_agent_audit_get', 'byq_agent_approval_request', 'byq_agent_approval_get',
    'byq_research_get', 'byq_research_transition', 'byq_experiment_create', 'byq_artifact_create',
    'byq_ml_training_get', 'byq_ml_prediction_create', 'byq_ml_prediction_get',
    'byq_backtest_task_prepare', 'byq_backtest_task_create', 'byq_backtest_task_get',
    'byq_backtest_task_execute', 'byq_backtest_get', 'byq_backtest_analysis_get',
    'byq_signal_snapshot_get', 'byq_experiment_compare', 'byq_workflow_card_propose',
    'byq_evaluation_signal_create', 'byq_evaluation_signal_get',
})


def authorize(store, reservation_id, payload, context):
    if (not isinstance(payload, dict) or set(payload) != {'tool', 'arguments', 'root_run_id'}
            or not isinstance(payload['tool'], str) or not isinstance(payload['arguments'], dict)
            or not isinstance(payload['root_run_id'], str)
            or re.fullmatch(r'[0-9a-f]{32}', payload['root_run_id']) is None
            or not isinstance(reservation_id, str)
            or re.fullmatch(r'continuation_[0-9a-f]{32}', reservation_id) is None
            or len(json.dumps(payload).encode()) > 512 * 1024):
        raise ValueError('continuation action is outside its scope')
    with store._transaction() as connection:
        match = fetch_one(connection, '''SELECT task_id FROM research_tasks
            WHERE owner_principal=:owner AND workspace_id=:workspace
              AND continuation_budget @> CAST(:receipt AS JSONB)''',
            {'owner': context['owner_principal'], 'workspace': context['workspace_id'],
             'receipt': [{'reservation_id': reservation_id}]})
        if match is None:
            raise ValueError('continuation reservation is unavailable')
        task, conversation = store._continuation_task(connection, match['task_id'], context, human=False)
        receipt = next(r for r in task['continuation_budget'] if r['reservation_id'] == reservation_id)
        if (store._permission_blocked_reason(task, conversation) is not None
                or context['session_id'] != conversation['runtime_session_id']
                or context['trace_id'] != conversation['trace_id']
                or receipt['status'] not in {'outcome_unknown', 'accepted'}
                or datetime.fromisoformat(receipt['expires_at']) <= datetime.now(timezone.utc)
                or receipt['run_id'] not in {None, payload['root_run_id']}):
            raise ValueError('continuation action is no longer admitted')
        scope = Scope(connection, task, context)
        args = payload['arguments']
        # Unscoped original-key lookups cannot choose a different task. Exact
        # object identities and task-scoped receipts remain available.
        try:
            if payload['tool'] not in TOOLS:
                raise ValueError('continuation action is outside its scope')
            if payload['tool'] == 'byq_ml_training_get' and not args.get('training_run_id'):
                raise ValueError('continuation requires the exact training identity')
            if payload['tool'] == 'byq_research_get' and not args.get('entity_id') and args.get('task_id') != task['task_id']:
                raise ValueError('continuation requires the original task identity')
            scope.walk(args)
        except ValueError:
            execute(connection, "UPDATE research_tasks SET continuation_blocked_reason='continuation_needs_attention' WHERE task_id=:task",
                {'task': task['task_id']})
            return {'schema_version': 'continuation-action-admission.v1', 'admitted': False,
                'reservation_id': reservation_id, 'task_id': task['task_id']}
        # This trusted MCP request proves the root accepted the original
        # reservation even when the Gateway lost its prompt acknowledgement.
        receipt.update(status='accepted', run_id=payload['root_run_id'])
        execute(connection, 'UPDATE research_tasks SET continuation_budget=:budget WHERE task_id=:task',
            {'budget': task['continuation_budget'], 'task': task['task_id']})
        return {'schema_version': 'continuation-action-admission.v1', 'admitted': True,
            'reservation_id': reservation_id, 'task_id': task['task_id']}


class Scope:
    def __init__(self, connection, task, context):
        self.connection, self.task, self.context = connection, task, context
        self.checked = set()
        self.nodes = 0

    def walk(self, value, depth=0):
        self.nodes += 1
        if depth > 20 or self.nodes > 4096:
            raise ValueError('continuation references exceed their bound')
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {'idempotency_key', 'schema_version', 'trace_id', 'role_id'}:
                    continue
                self.walk(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                self.walk(item, depth + 1)
        elif isinstance(value, str):
            self.identity(value)

    def identity(self, identity):
        # Match typed Domain identifier normalization before recognizing a
        # reference; padding must not turn a foreign object into plain text.
        identity = identity.strip()
        if identity in self.checked:
            return
        if len(self.checked) >= 128:
            raise ValueError('continuation identity bound exceeded')
        if re.fullmatch(r'evaluation_signal_[0-9a-f]{32}', identity):
            row = fetch_one(self.connection, '''SELECT s.task_id FROM evaluation_signals s
                JOIN research_tasks t ON t.task_id=s.task_id WHERE s.signal_id=:identity
                  AND t.owner_principal=:owner AND t.workspace_id=:workspace''',
                {'identity': identity, 'owner': self.context['owner_principal'], 'workspace': self.context['workspace_id']})
            if row is None or row['task_id'] != self.task['task_id']:
                raise ValueError('continuation evaluation belongs to another task')
            self.checked.add(identity)
            return
        if identity.startswith('backtesttask_ml_'):
            return self.identity(identity.replace('backtesttask_ml_', 'mlpred_', 1))
        if identity.startswith('backtesttask_'):
            return self.identity(identity.replace('backtesttask_', 'signaljob_', 1))
        tables = (
            ('task_', 'research_tasks', 'task_id'), ('artifact_', 'artifacts', 'artifact_id'),
            ('experiment_', 'experiments', 'experiment_id'), ('mlrun_', 'ml_training_runs', 'training_run_id'),
            ('mlpred_', 'ml_prediction_runs', 'prediction_run_id'), ('signaljob_', 'signal_producer_jobs', 'job_id'),
            ('backtest_', 'backtest_jobs', 'job_id'), ('agent_run_', 'agent_runs', 'run_id'),
            ('agent_approval_', 'agent_approvals', 'approval_id'),
        )
        found = next((entry for entry in tables if re.fullmatch(re.escape(entry[0]) + r'[0-9a-f]{32}', identity)), None)
        if found is None:
            return  # Non-identity content remains validated by the typed domain tool.
        _, table, column = found
        row = fetch_one(self.connection, f'''SELECT * FROM {table} WHERE {column}=:identity
            AND owner_principal=:owner AND workspace_id=:workspace''',
            {'identity': identity, 'owner': self.context['owner_principal'], 'workspace': self.context['workspace_id']})
        if row is None:
            raise ValueError('continuation referenced object is unavailable')
        self.checked.add(identity)
        if table == 'agent_approvals':
            self.identity(row['run_id'])
            if row.get('resource_id'):
                self.identity(row['resource_id'])
            return
        if table == 'agent_runs':
            if any(row[key] != self.context[key] for key in ('session_id', 'trace_id', 'dsh_run_id')):
                raise ValueError('continuation agent belongs to another execution')
            return
        if row.get('task_id') != self.task['task_id']:
            raise ValueError('continuation cannot access another task')
        if table == 'artifacts':
            if row['kind'] in {'strategy_version', 'ml_strategy_version'}:
                confirmed = self.task['continuation_permission']['confirmed_artifacts']
                if not any(r['artifact_id'] == identity and r['content_sha256'] == row['content_sha256'] for r in confirmed):
                    raise ValueError('continuation strategy lineage was not confirmed')
            self.walk(row.get('lineage') or [])
        for key in ('ml_strategy_artifact_id', 'strategy_version_artifact_id'):
            if row.get(key):
                self.identity(row[key])
