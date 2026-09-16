"""Read-only durable counts after six-family service/process recovery."""
import json,os
from sqlalchemy import create_engine,text
assert os.environ.get('BYQ_H4_RECOVERY') == '1'
assert os.environ['BYQ_DATABASE_URL'].endswith('/byq_domain_test')
queries = {
 'task':"SELECT count(*) FROM research_tasks WHERE owner_principal=:owner",
 'artifact':"SELECT count(*) FROM artifacts a JOIN research_tasks t USING(task_id) WHERE t.owner_principal=:owner",
 'run':"SELECT count(*) FROM learning_runs WHERE owner_principal=:owner",
 'iteration':"SELECT count(*) FROM learning_iterations i JOIN learning_runs r USING(learning_run_id) WHERE r.owner_principal=:owner",
 'signal':"SELECT count(*) FROM evaluation_signals s JOIN research_tasks t USING(task_id) WHERE t.owner_principal=:owner",
 'lesson':"SELECT count(*) FROM lessons WHERE owner_principal=:owner",
 'pool':"SELECT count(*) FROM stock_pools WHERE owner_principal=:owner",
 'feedback':"SELECT count(*) FROM product_feedback WHERE owner_principal=:owner",
 'hub_events':"SELECT count(*) FROM product_feedback_hub_outbox h JOIN product_feedback f USING(feedback_id) WHERE f.owner_principal=:owner",
}
engine = create_engine(os.environ['BYQ_DATABASE_URL'])
with engine.begin() as connection:
 connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
 counts = {name:connection.execute(text(query),{'owner':'h4-domain-recovery'}).scalar_one() for name,query in queries.items()}
assert counts == {'task':1,'artifact':1,'run':2,'iteration':1,'signal':1,'lesson':1,'pool':1,'feedback':1,'hub_events':0}, counts
print(json.dumps({'status':'PASS','durable_counts':counts,'recovery_writes':0}))
engine.dispose()
