"""Read-only handoff projection from durable domain facts (ADR-0062).

Never schedules work or changes task lifecycle. A database snapshot prevents
mixing a pre-cancellation task with post-cancellation delivery facts.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone

from .db import execute, fetch_one

LIMIT = 64
_V3_LEDGER_SCHEMA = 'task-continuation-ledger-entry.v1'
_READY_EVENT = re.compile(r'ready-v1:[0-9a-f]{64}')
_NOTIFICATION_ID = re.compile(r'notification_[0-9a-f]{32}')
_LEGACY_NOTIFICATION_FIELDS = frozenset({
    'reservation_id', 'grant_kind', 'grant_version', 'event_key', 'input_sha256',
    'token_limit', 'status', 'run_id', 'charged_tokens', 'settlement_sha256',
    'created_at', 'instruction', 'outcome', 'executable',
})
_EXECUTABLE_ACTION_FIELDS = frozenset({
    'schema_version', 'backtest_task_id', 'phase', 'next_action', 'references',
    'approval_required', 'approval', 'expected_postcondition',
})
_EXECUTABLE_REFERENCE_FIELDS = frozenset({
    'research_task_id', 'strategy_version_artifact_id', 'approval_artifact_id',
    'stock_pool_snapshot_id', 'signal_producer_job_id', 'signal_snapshot_artifact_id',
    'backtest_job_id', 'result_artifact_id',
})
JOB_SOURCES = (
    ('ml_training_runs', 'training_run_id'),
    ('ml_prediction_runs', 'prediction_run_id'),
    ('signal_producer_jobs', 'job_id'),
    ('backtest_jobs', 'job_id'),
)


def _legacy_notification_is_resolved(connection, task, row):
    """Whether a historical deterministic notification has visible lineage."""
    if (not isinstance(row, dict) or set(row) != _LEGACY_NOTIFICATION_FIELDS
            or row.get('grant_kind') != 'data_ready_notification'
            or row.get('status') != 'settled' or row.get('outcome') != 'notified'
            or row.get('instruction') is not None or row.get('run_id') is not None
            or row.get('grant_version') is not None or type(row.get('token_limit')) is not int
            or row.get('token_limit') != 0 or type(row.get('charged_tokens')) is not int
            or row.get('charged_tokens') != 0
            or not isinstance(row.get('reservation_id'), str)
            or _NOTIFICATION_ID.fullmatch(row['reservation_id']) is None
            or not isinstance(row.get('event_key'), str)
            or _READY_EVENT.fullmatch(row['event_key']) is None
            or not isinstance(row.get('input_sha256'), str)
            or not isinstance(row.get('settlement_sha256'), str)):
        return False
    try:
        created_at = datetime.fromisoformat(row['created_at'])
    except (TypeError, ValueError):
        return False
    if created_at.tzinfo is None:
        return False
    executable = row.get('executable')
    if (not isinstance(executable, dict) or set(executable) != _EXECUTABLE_ACTION_FIELDS
            or executable.get('schema_version') != 'research-executable-action.v1'
            or not isinstance(executable.get('references'), dict)
            or set(executable['references']) != _EXECUTABLE_REFERENCE_FIELDS
            or type(executable.get('approval_required')) is not bool):
        return False
    encoded = json.dumps(executable, sort_keys=True, separators=(',', ':')).encode()
    if (hashlib.sha256(encoded).hexdigest() != row['input_sha256']
            or hashlib.sha256(('notified:' + row['event_key']).encode()).hexdigest()
            != row['settlement_sha256']):
        return False
    references = executable['references']
    if references.get('research_task_id') != task['task_id']:
        return False
    job_id = references.get('signal_producer_job_id')
    artifact_id = references.get('signal_snapshot_artifact_id')
    params = {'task': task['task_id'], 'owner': task['owner_principal'],
              'workspace': task['workspace_id']}
    if isinstance(job_id, str) and re.fullmatch(r'signaljob_[0-9a-f]{32}', job_id):
        job = fetch_one(connection, '''SELECT job_id, status, result_artifact_id
            FROM signal_producer_jobs WHERE job_id=:job AND task_id=:task
              AND owner_principal=:owner AND workspace_id=:workspace''',
            {**params, 'job': job_id})
        if (job is None or job['status'] != 'completed' or not isinstance(job['result_artifact_id'], str)
                or (artifact_id is not None and artifact_id != job['result_artifact_id'])):
            return False
        artifact_id = job['result_artifact_id']
    elif job_id is not None:
        return False
    elif not isinstance(artifact_id, str) or re.fullmatch(r'artifact_[0-9a-f]{32}', artifact_id) is None:
        return False
    artifact = fetch_one(connection, '''SELECT artifact_id FROM artifacts
        WHERE artifact_id=:artifact AND task_id=:task AND owner_principal=:owner
          AND workspace_id=:workspace AND kind='signal_snapshot' AND status='validated' ''',
        {**params, 'artifact': artifact_id})
    if artifact is None:
        return False
    if job_id is None:
        lineage = execute(connection, '''SELECT j.job_id FROM signal_producer_jobs j
            WHERE j.result_artifact_id=:artifact AND j.task_id=:task
              AND j.owner_principal=:owner AND j.workspace_id=:workspace
              AND j.status='completed' ORDER BY j.job_id LIMIT 2''',
            {**params, 'artifact': artifact_id})
        return len(lineage) == 1
    return True


class ResearchHandoffMixin:
    def get_task_handoff(self, task_id, *, trusted_context):
        from .research import ResearchNotFound, _identifier
        from .agent_research import APPROVAL_RESOURCE_TYPES
        from .research_continuation import (
            ResearchContinuationMixin,
            _validate_v3_ledger_entry,
        )
        from packages.contracts.agent_execution_options import (
            default_agent_execution_options,
            validate_agent_execution_options,
        )

        task_id = _identifier(task_id, field='task_id')
        params = {'task': task_id, 'owner': trusted_context.get('owner_principal'),
                  'workspace': trusted_context.get('workspace_id')}
        options = default_agent_execution_options()
        options_invalid = False
        active_roots = []
        v3_entries = []
        legacy_rows = []
        ledger_invalid = False
        ledger_overflow = False
        unresolved_legacy = False
        permission = None
        explicit_revoke = False
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
            if conversation is not None:
                options_row = fetch_one(connection, '''SELECT revision, options_json
                    FROM product_conversation_execution_options
                    WHERE conversation_id=:conversation AND owner_principal=:owner
                      AND workspace_id=:workspace''',
                    {**params, 'conversation': conversation['conversation_id']})
                if options_row is not None:
                    try:
                        revision = options_row['revision']
                        if type(revision) is not int or revision < 1:
                            raise ValueError('stored execution options revision is invalid')
                        options = validate_agent_execution_options(options_row['options_json'])
                    except (KeyError, TypeError, ValueError):
                        options_invalid = True

            permission = task.get('continuation_permission')
            if permission is not None:
                if not isinstance(permission, dict) or 'revoked_at' not in permission:
                    ledger_invalid = True
                else:
                    explicit_revoke = permission['revoked_at'] is not None

            ledger = task.get('continuation_budget')
            if ledger is None:
                ledger = []
            if not isinstance(ledger, list):
                ledger_invalid = True
                ledger = []
            if len(ledger) > LIMIT:
                ledger_overflow = True
            for stored in ledger[:LIMIT + 1]:
                if not isinstance(stored, dict):
                    ledger_invalid = True
                    continue
                if stored.get('schema_version') == _V3_LEDGER_SCHEMA:
                    try:
                        entry = _validate_v3_ledger_entry(stored)
                    except (KeyError, TypeError, ValueError):
                        ledger_invalid = True
                        continue
                    carrier = entry['reservation']
                    if (carrier.get('owner_principal') != task['owner_principal']
                            or carrier.get('workspace_id') != task['workspace_id']
                            or carrier.get('conversation_id') != task.get('conversation_id')
                            or carrier.get('task_id') != task['task_id']):
                        ledger_invalid = True
                        continue
                    v3_entries.append(entry)
                else:
                    legacy_rows.append(stored)
            unresolved_legacy = any(
                not _legacy_notification_is_resolved(connection, task, row)
                for row in legacy_rows
            )

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
            active_roots = []
            if conversation is not None:
                active_roots = execute(connection, '''SELECT root_run_id FROM agent_runtime_turns
                    WHERE owner_principal=:owner AND workspace_id=:workspace AND session_id=:session
                      AND trace_id=:trace AND status='active' ORDER BY root_run_id LIMIT 2''',
                    {**params, 'session': conversation['runtime_session_id'], 'trace': task['trace_id']})
            progress = task.get('progress')
            if not isinstance(progress, dict):
                progress = {}
            completion = []
            completion_evidence = progress.get('completion_evidence', [])
            if not isinstance(completion_evidence, list):
                completion_evidence = []
            for identity in completion_evidence:
                evidence = fetch_one(connection, """SELECT artifact_id FROM artifacts WHERE artifact_id=:artifact
                    AND task_id=:task AND owner_principal=:owner AND workspace_id=:workspace AND status='validated'""",
                    {**params, 'artifact': identity})
                if evidence:
                    completion.append(identity)
        now = datetime.now(timezone.utc)

        v3_refs = [
            {'kind': 'continuation', 'id': entry['reservation_id'], 'status': entry['status'],
             **({'outcome': entry['outcome']} if entry.get('outcome') is not None else {})}
            for entry in v3_entries
        ]
        refs = v3_refs + [
            {'kind': 'approval', 'id': row['identity'], 'status': row['status']}
            for row in approvals[:LIMIT]
        ]
        refs += [{'kind': row['kind'], 'id': row['identity'], 'status': row['status']} for row in jobs]
        refs_truncated = len(refs) > LIMIT
        v3_reference_overflow = len(v3_refs) > LIMIT
        refs = refs[:LIMIT]
        truncated |= refs_truncated or ledger_overflow or v3_reference_overflow
        continuation_task = {**task, 'continuation_budget': ledger}

        v3_unknown = any(entry['status'] == 'outcome_unknown' for entry in v3_entries)
        accepted_entries = [entry for entry in v3_entries if entry['status'] == 'accepted']
        reserved_entries = [entry for entry in v3_entries if entry['status'] == 'reserved']
        accepted_active = (
            len(active_roots) == 1
            and len(accepted_entries) == 1
            and conversation is not None and conversation['status'] == 'active'
            and active_roots[0].get('root_run_id') is not None
            and accepted_entries[0].get('run_id') == active_roots[0]['root_run_id']
        )
        accepted_unconfirmed = bool(accepted_entries) and not accepted_active
        mixed_active_reserved = accepted_active and bool(reserved_entries)
        reserved_cancel_pending = any(entry.get('cancel_requested_at') is not None
                                      for entry in reserved_entries)
        unresolved_v3 = v3_unknown or accepted_unconfirmed or reserved_cancel_pending
        revoked_pending = explicit_revoke and bool(v3_unknown or accepted_entries or reserved_entries)
        has_settled_needs_attention = any(
            isinstance(entry, dict) and entry.get('status') == 'settled'
            and entry.get('outcome') == 'needs_attention'
            for entry in ledger
        )
        taskwide_needs_attention = (
            task.get('continuation_blocked_reason') == 'continuation_needs_attention'
            and (task.get('continuation_blocked_event_key') == '*'
                 or (task.get('continuation_blocked_event_key') is None
                     and not has_settled_needs_attention))
        )
        blocked_reserved = not (ledger_invalid or unresolved_legacy or ledger_overflow) and any(
            ResearchContinuationMixin._event_blocked_by_needs_attention(continuation_task, entry['event_key'])
            for entry in reserved_entries
        )

        reason = None
        if options_invalid:
            state, reason = 'needs_reconciliation', 'execution_options_invalid'
        elif ledger_invalid:
            state, reason = 'needs_reconciliation', 'continuation_ledger_invalid'
        elif unresolved_v3 or revoked_pending or mixed_active_reserved:
            state, reason = 'needs_reconciliation', 'continuation_result_unconfirmed'
        elif unresolved_legacy:
            state, reason = 'needs_reconciliation', 'continuation_result_unconfirmed'
        elif ledger_overflow or v3_reference_overflow:
            state, reason = 'needs_reconciliation', 'evidence_limit_reached'
        elif accepted_active and task['status'] in {'completed', 'failed', 'cancelled'}:
            state, reason = 'needs_reconciliation', 'continuation_result_unconfirmed'
        elif task['status'] == 'completed' and (not completion
                or len(completion) != len(completion_evidence)
                or progress.get('stage') != 'completed' or progress.get('next_action')
                or progress.get('blocked_reason')):
            state, reason = 'needs_reconciliation', 'completion_evidence_missing'
        elif task['status'] in {'completed', 'failed', 'cancelled'} and reserved_entries:
            state, reason = 'needs_reconciliation', 'continuation_result_unconfirmed'
        elif task['status'] in {'completed', 'failed', 'cancelled'}:
            state = task['status']
        elif truncated:
            state, reason = 'needs_reconciliation', 'evidence_limit_reached'
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
        elif accepted_active:
            if conversation is not None and conversation['status'] == 'active':
                # The persisted Runtime row is only a DB snapshot; it does
                # not prove that the process is still executing now.
                state, reason = 'conversation_active', 'task_execution_unconfirmed'
            else:
                state, reason = 'needs_reconciliation', 'continuation_result_unconfirmed'
        elif active_roots:
            # A conversation can contain several tasks. Do not attribute this
            # run to this task without a task-scoped delivery receipt.
            state, reason = 'conversation_active', 'task_execution_unconfirmed'
        elif reserved_entries:
            if conversation is None:
                state, reason = 'needs_reconciliation', 'continuation_result_unconfirmed'
            elif conversation['status'] != 'active' or task['status'] in {'completed', 'failed', 'cancelled'}:
                state, reason = 'needs_reconciliation', 'continuation_result_unconfirmed'
            elif explicit_revoke:
                state, reason = 'needs_reconciliation', 'continuation_result_unconfirmed'
            elif taskwide_needs_attention:
                state, reason = 'blocked', 'continuation_needs_attention'
            elif blocked_reserved:
                state, reason = 'needs_reconciliation', 'continuation_needs_attention'
            elif os.environ.get('BYQ_F6_EXECUTOR_ENABLED') == '1':
                state = 'continuation_queued'
            else:
                state, reason = 'blocked', 'no_registered_executor'
        elif conversation is None:
            state, reason = 'blocked', 'conversation_binding_missing'
        elif conversation['status'] != 'active':
            state, reason = 'blocked', 'conversation_inactive'
        elif explicit_revoke:
            state, reason = 'blocked', 'automatic_continuation_stopped'
        elif taskwide_needs_attention:
            state, reason = 'blocked', 'continuation_needs_attention'
        elif not options['auto_continue']:
            state, reason = 'blocked', 'automatic_continuation_disabled'
        elif os.environ.get('BYQ_F6_EXECUTOR_ENABLED') != '1':
            state, reason = 'blocked', 'no_registered_executor'
        else:
            state = 'waiting_event'
        return {'schema_version': 'research-task-handoff.v1', 'task_id': task_id,
                'task_version': task['version'], 'task_status': task['status'],
                'objective': task['objective'], 'progress': progress, 'state': state,
                'reason': reason, 'references': refs, 'has_more': truncated,
                'observed_at': now.isoformat()}
