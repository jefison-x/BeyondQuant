"""Prepare only synthetic inputs for the isolated six-family HTTP receipt probe."""
import json, os, sys
sys.path.insert(0,'/app')
assert os.environ.get('BYQ_H4_RECOVERY') == '1'
assert os.environ['BYQ_DATABASE_URL'].endswith('/byq_domain_test')
from tests.workspace_helpers import trusted_agent_context
from tests.test_product_feedback import content
from app.research import ResearchStore
from app.learning_loop import LearningLoopStore
headers = trusted_agent_context('h4-domain-recovery',trace_id='trace-domain-recovery')
context = {k.removeprefix('x-byq-').replace('-','_'):v for k,v in headers.items()}
research = ResearchStore()
task = research.create_task({'owner_principal':context['owner_principal'],'title':'Synthetic receipt parent',
    'objective':'Only validate recovery','trace_id':context['trace_id'],'idempotency_key':'parent'},trusted_context=context)
artifact = research.create_artifact({'task_id':task['task_id'],'kind':'research_evidence','content':{'synthetic':True},
    'lineage':[],'trace_id':context['trace_id'],'idempotency_key':'source'},trusted_owner=context['owner_principal'],trusted_workspace=context['workspace_id'])
research.transition('artifact',artifact['artifact_id'],'validated','validate')
learning = LearningLoopStore(research_store=research)
run = learning.start_run({'task_id':task['task_id'],'budget':{'max_iterations':1,'max_repairs':0},
    'trace_id':context['trace_id'],'idempotency_key':'iteration-parent'},trusted_owner=context['owner_principal'])
print(json.dumps({'headers':headers,'context':context,'task_id':task['task_id'],'run_id':run['learning_run_id'],'cases':[
    {'kind':'pool','payload':{'name':'Synthetic recovery pool','symbols':['000001.SZ'],'idempotency_key':'lost-pool'}},
    {'kind':'run','payload':{'task_id':task['task_id'],'budget':{'max_iterations':1,'max_repairs':0},'idempotency_key':'lost-run'}},
    {'kind':'iteration','payload':{'iteration_index':1,'attempt':1,'outcome':'produced','idempotency_key':'lost-iteration'}},
    {'kind':'signal','payload':{'task_id':task['task_id'],'source_artifact_id':artifact['artifact_id'],'metric':'sharpe','value':0.1,'idempotency_key':'lost-signal'}},
    {'kind':'lesson','payload':{'task_id':task['task_id'],'content':{'text':'Synthetic bounded observation'},'evidence':[{'kind':'artifact','id':artifact['artifact_id']}],'idempotency_key':'lost-lesson'}},
    {'kind':'feedback','payload':{**content(),'idempotency_key':'lost-feedback'}},
]}))
learning.close();research.close()
