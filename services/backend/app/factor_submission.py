"""Exact factor-result reuse under the existing Artifact submission lock."""
from .db import execute, fetch_one
from .factor_research import prepare_factor_input
from .research import IdempotencyConflict, ResearchNotFound, _identifier, _idempotency_key


def submit_factor(store, payload, context, compute):
    task_id = _identifier(payload.get('task_id'), field='task_id')
    key = _idempotency_key(payload.get('idempotency_key'))
    with store._transaction() as connection:
        execute(connection, "SET LOCAL lock_timeout = '2s'")
        execute(connection, 'SELECT pg_advisory_xact_lock(hashtext(:scope))',
                {'scope': f'research-artifact|{task_id}|{key}'})
        task = fetch_one(connection, 'SELECT * FROM research_tasks WHERE task_id=:id', {'id': task_id})
        if (task is None or task['owner_principal'] != context['owner_principal']
                or task['workspace_id'] != context['workspace_id']):
            raise ResearchNotFound('research task not found')
        prepared = prepare_factor_input(payload)
        original = fetch_one(connection,
            'SELECT * FROM artifacts WHERE task_id=:task AND idempotency_key=:key',
            {'task': task_id, 'key': key})
        if original is None and fetch_one(connection,
                'SELECT artifact_id FROM artifact_submission_receipts WHERE task_id=:task AND idempotency_key=:key',
                {'task':task_id, 'key':key}) is not None:
            raise IdempotencyConflict('factor key belongs to another artifact submission')
        if original is not None:
            content = original['content']
            if (original['kind'] != 'factor_result'
                    or not isinstance(content, dict)
                    or content.get('input_manifest_id') != prepared['manifest_id']):
                raise IdempotencyConflict('factor idempotency key was reused')
            computed = {
                'factor': content, 'artifact_content': content,
                'artifact_lineage': [{'kind': 'factor_input', 'id': prepared['manifest_id']}],
                'coverage': prepared['coverage_counts'],
                'input_manifest': {
                    'id': prepared['manifest_id'], 'schema_version': 'factor-input-v1',
                    'as_of_date': prepared['normalized']['as_of_date'],
                    'source_count': len(prepared['normalized']['sources']),
                    'row_count': len(prepared['normalized']['bars']),
                },
            }
        else:
            computed = compute(payload)
        # Preserve Artifact's exact request-hash, experiment and lineage checks,
        # including conflicts in fields not covered by the factor input manifest.
        artifact = store.create_artifact({
            'task_id': task_id, 'experiment_id': payload.get('experiment_id'),
            'kind': 'factor_result', 'content': computed['artifact_content'],
            'lineage': computed['artifact_lineage'], 'trace_id': payload.get('trace_id'),
            'idempotency_key': key,
        }, trusted_owner=context['owner_principal'], trusted_workspace=context['workspace_id'],
            _connection=connection)
        return {name: computed[name] for name in ('factor', 'input_manifest', 'coverage')} | {'artifact': artifact}
