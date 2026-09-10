#!/usr/bin/env python3
"""Explicit isolated fixtures for real Product API receipt projections."""
import json
import os
from urllib.request import Request, urlopen
from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchStore
from tests.workspace_helpers import trusted_agent_context

if os.environ.get('BYQ_F2_FIXTURE') != '1':
    raise SystemExit('explicit isolated receipt fixture invocation required')
for viewport in ('desktop','mobile'):
    owner='f2-browser-'+viewport
    headers=trusted_agent_context(owner,session_id='f2-session-'+viewport,trace_id='f2-trace-'+viewport)
    context={k.removeprefix('x-byq-').replace('-','_'):v for k,v in headers.items()}
    catalog=ConversationCatalogStore()
    conversation=catalog.create(owner,context['session_id'],context['trace_id'])
    catalog.close()
    def command(path, body):
        with urlopen(Request('http://127.0.0.1:8000'+path,data=json.dumps(body).encode(),
                headers={**headers,'content-type':'application/json'},method='POST'),timeout=15) as response:
            return json.load(response)
    payload={'owner_principal':owner,'title':'F2 原请求核对','objective':'Synthetic creation receipt only',
        'trace_id':context['trace_id'],'idempotency_key':'f2-original'}
    watch=command('/v1/research/submission-watches',{'entity_type':'research_task','request':payload})
    task=command('/v1/research/tasks',payload)
    store=ResearchStore()
    store._execute("UPDATE research_receipt_watches SET next_check_at=now()-interval '1 second' WHERE watch_id=:id",{'id':watch['watch_id']})
    assert store.consume_submission_watches(conversation['conversation_id'],trusted_context=context)==1
    assert store.get_submission_watch(watch['watch_id'],trusted_context=context)['entity_id']==task['task_id']
    unknown=command('/v1/research/submission-watches',{'entity_type':'research_task','request':{**payload,'idempotency_key':'f2-unsent'}})
    # Test-only elapsed deadline; no fabricated research entity or failure.
    store._execute("UPDATE research_receipt_watches SET deadline_at=now()-interval '1 second',next_check_at=now() WHERE watch_id=:id",{'id':unknown['watch_id']})
    store.consume_submission_watches(conversation['conversation_id'],trusted_context=context)
    store.close()
    print(json.dumps({'fixture':viewport,'conversation_id':conversation['conversation_id'],'confirmed':watch['watch_id'],'unknown':unknown['watch_id']}))
