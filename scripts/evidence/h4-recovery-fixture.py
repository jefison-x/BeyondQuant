"""Synthetic fixture for the isolated cross-process receipt probe."""
import json
import os
import sys

if os.environ.get('BYQ_H4_RECOVERY') != '1' or not os.environ.get('BYQ_DATABASE_URL', '').endswith('/byq_domain_test'):
    raise SystemExit('isolated test database and explicit fixture flag required')
from tests.workspace_helpers import trusted_agent_context
from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchStore
from tests.test_research import snapshot
sys.path.insert(0, 'tests')
from test_factor_research import factor_payload
headers = trusted_agent_context('h4-cross-process', session_id='h4-cross-session', trace_id='h4-cross-trace')
context = {k.removeprefix('x-byq-').replace('-', '_'): v for k, v in headers.items()}
catalog = ConversationCatalogStore()
catalog.create('h4-cross-process', 'h4-cross-session', 'h4-cross-trace')
store = ResearchStore()
parent = store.create_task({'owner_principal':'h4-cross-process', 'title':'H4 parent',
    'objective':'Synthetic recovery only', 'trace_id':'h4-cross-trace','idempotency_key':'h4-parent'}, trusted_context=context)
common = {'task_id':parent['task_id'], 'trace_id':'h4-cross-trace'}
print(json.dumps({'headers':headers, 'cases':[
    {'kind':'research_task','payload':{'owner_principal':'h4-cross-process','title':'Lost reply',
      'objective':'Synthetic lost receipt', 'trace_id':'h4-cross-trace','idempotency_key':'h4-lost-task'}},
    {'kind':'experiment','payload':{**common,'name':'Lost experiment','input_snapshot':snapshot(),'idempotency_key':'h4-lost-experiment'}},
    {'kind':'artifact','payload':{**common,'kind':'evidence','content':{'synthetic':True},'lineage':[],'idempotency_key':'h4-lost-artifact'}},
    {'kind':'factor','payload':{**factor_payload(),**common,'idempotency_key':'h4-lost-factor'}},
]}))
store.close()
catalog.close()
