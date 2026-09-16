"""Synthetic volume fixture; only for the explicitly isolated H5 database."""
import os
from sqlalchemy.engine import make_url
assert os.environ.get('BYQ_H5_EVIDENCE') == '1'
assert make_url(os.environ['BYQ_DATABASE_URL']).database == 'byq_domain_test'
from app import main
from app.db import execute
store = main.research_store
task = store.create_task({'owner_principal':'h5-browser', 'title':'H4 synthetic pagination',
    'objective':'Synthetic pagination only, not strategy research completion',
    'trace_id':'h107-pagination', 'idempotency_key':'h107-pagination'})
with store._transaction() as connection:
    execute(connection, """INSERT INTO artifacts
        (artifact_id,task_id,experiment_id,owner_principal,kind,status,content,content_sha256,
         lineage,trace_id,idempotency_key,request_hash,created_at,updated_at,version)
        SELECT 'artifact_'||md5('h107-'||n), :task, NULL, 'h5-browser','strategy_version','validated',
          jsonb_build_object('synthetic',true,'strategy_id','H107Pagination','version_id','synthetic-'||n,
            'snapshot',jsonb_build_object('strategy_id','H107Pagination','name','H4 synthetic pagination',
            'script','class CustomStrategy: pass')),
          repeat('a',64),'[]'::jsonb,'h107-pagination','h107-version-'||n,repeat('b',64),
          '2026-09-13T00:00:00Z'::timestamptz + n*interval '1 second',now(),1
        FROM generate_series(1,1005)n ON CONFLICT(artifact_id) DO NOTHING""", {'task':task['task_id']})
print('synthetic 1005-version fixture ready; no backtest/model execution')
