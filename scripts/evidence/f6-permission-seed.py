#!/usr/bin/env python3
"""Isolated browser fixtures: real identities, bound tasks and strategy artifacts."""
import json
import os
from urllib.request import Request, urlopen

from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchStore
from tests.workspace_helpers import trusted_agent_context
from tests.test_backtest_api import _strategy

if os.environ.get('BYQ_F6_FIXTURE') != '1':
    raise SystemExit('explicit isolated F6 fixture invocation required')

for viewport in ('desktop', 'mobile'):
    owner = 'f6-browser-' + viewport
    session, trace = 'f6-session-' + viewport, 'f6-trace-' + viewport
    headers = trusted_agent_context(owner, session_id=session, trace_id=trace)
    context = {k.removeprefix('x-byq-').replace('-', '_'): v for k, v in headers.items()}
    catalog = ConversationCatalogStore()
    catalog.create(owner, session, trace)
    catalog.close()
    store = ResearchStore()
    task = store.create_task({'owner_principal': owner, 'title': 'F6 许可浏览器验收',
        'objective': 'Synthetic fixture: verify durable permission without any model or market download.',
        'trace_id': trace, 'idempotency_key': 'f6-browser-task'}, trusted_context=context)
    store.close()
    def command(path, body):
        request = Request('http://127.0.0.1:8000' + path, data=json.dumps(body).encode(),
            headers={**headers, 'content-type': 'application/json'}, method='POST')
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    draft = command('/v1/research/strategies/validate', {'task_id': task['task_id'], 'strategy': _strategy(),
        'trace_id': trace, 'idempotency_key': 'f6-browser-draft'})
    version = command('/v1/research/strategies/versions', {'task_id': task['task_id'],
        'draft_artifact_id': draft['artifact']['artifact_id'], 'trace_id': trace, 'idempotency_key': 'f6-browser-version'})
    print(json.dumps({'fixture': viewport, 'task_id': task['task_id'], 'artifact_id': version['artifact']['artifact_id']}))
