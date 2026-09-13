#!/usr/bin/env python3
"""Explicitly synthetic H3 fixture for an isolated PostgreSQL Product stack."""
import os
import re

if os.environ.get('BYQ_H3_FIXTURE') != '1' or not os.environ.get('BYQ_DATABASE_URL', '').endswith('/byq_domain_test'):
    raise SystemExit('explicit isolated H3 fixture required')
owner = os.environ.get('BYQ_H3_BROWSER_USER', 'h3-browser-user')
if not re.fullmatch(r'h3-browser-[a-z0-9-]{1,24}', owner):
    raise SystemExit('synthetic owner prefix required')
from tests.workspace_helpers import trusted_agent_context
from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchStore

store, catalog = ResearchStore(), ConversationCatalogStore()
try:
    for width in (1440, 390):
        session, trace = f'{owner}-{width}', f'h3-trace-{owner}-{width}'
        headers = trusted_agent_context(owner, session_id=session, trace_id=trace)
        context = {k.removeprefix('x-byq-').replace('-', '_'): v for k, v in headers.items()}
        catalog.create(owner, session, trace)
        task = store.create_task({'owner_principal': owner, 'title': f'H3 synthetic {width}',
            'objective': 'Synthetic handoff only; no model execution', 'trace_id': trace,
            'idempotency_key': f'h3-task-{width}'}, trusted_context=context)
        artifact = store.create_artifact({'task_id': task['task_id'], 'kind': 'research_note',
            'content': {'synthetic': True}, 'lineage': [], 'trace_id': trace, 'idempotency_key': f'h3-note-{width}'})
        store.transition('artifact', artifact['artifact_id'], 'validated', f'h3-validate-{width}')
        store.transition('research_task', task['task_id'], 'running', f'h3-progress-{width}', progress={
            'schema_version': 'research-progress.v1', 'stage': 'research', 'next_action': '核对原任务',
            'blocked_reason': None, 'linked_objects': [{'kind': 'artifact', 'id': artifact['artifact_id']}],
            'completion_evidence': []})
    print('H3 synthetic fixture ready')
finally:
    store.close()
    catalog.close()
