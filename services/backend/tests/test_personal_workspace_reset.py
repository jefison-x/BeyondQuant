"""ADR-0091 actual PostgreSQL contracts, using conftest's disposable DB only."""
from __future__ import annotations
import json
import os
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.credentials import CredentialStore,CredentialCipher
from app.paper_trading import PaperTradingStore
from app.product_feedback import ProductFeedbackStore
from app.user_auth import UserAuthStore
from app.user_policy import UserPolicyStore
from app.workspace_reset import WorkspaceResetStore,WorkspaceResetBlocked
from app.workspace_runtime_reset import WorkspaceRuntimeResetStore,WorkspaceRuntimeResetConflict
from app.workspace_reset_retention import expire_archives,collect_expired_objects
from app.workspace_reset_scope import RESET_SCOPE
from tests.test_workspace_reset import _research_graph
from tests.test_product_feedback import content, create, provision, workspace

pytestmark=pytest.mark.skipif(not os.environ.get('BYQ_DATABASE_URL'),reason='disposable PostgreSQL required')


def test_complete_personal_reset_defaults_archive_ciphertext_other_user_and_replay():
    suffix=uuid4().hex[:12]; owner='reset-full-'+suffix; other='reset-other-'+suffix
    ctx,conversation,task,_,_=_research_graph(owner,suffix=suffix+'a')
    ctx_b,_,task_b,_,_=_research_graph(other,suffix=suffix+'b')
    users=UserAuthStore(); paper=PaperTradingStore(); policies=UserPolicyStore(); feedback=ProductFeedbackStore()
    creds=CredentialStore(cipher=CredentialCipher.for_test({'test':bytes(range(32))},'test'))
    reset=WorkspaceRuntimeResetStore(); store=WorkspaceResetStore()
    try:
        identity=store._fetch_one('SELECT * FROM users WHERE username=:owner',{'owner':owner}); uid=identity['user_id']
        users.update_profile(uid,{'preferences':'中文研究','default_prompt':'personal prompt'})
        users.update_ui_preferences(uid,{'schema_version':'ui-preferences.v1','color_mode':'dark','accent_theme':'ocean','expected_version':0})
        policies.update(owner,{'automation_enabled':True,'paused':True},request_id=str(uuid4()))
        paper.create_account({'name':'personal simulation','cash':10000,'idempotency_key':'paper-key'},trusted_owner=owner,trusted_workspace=ctx['workspace_id'])
        paper.create_pool({'name':'personal pool','symbols':['000001.SZ'],'idempotency_key':'pool-key'},trusted_owner=owner,trusted_workspace=ctx['workspace_id'])
        feedback.create({**content(),'idempotency_key':'feedback-key'},trusted_workspace=ctx['workspace_id'],trusted_owner=owner,trusted_actor=owner)
        secret='sk-test-reset-private-value'
        creds.create_credential(owner,{'purpose':'model_api_key','provider':'deepseek','scope':'user','label':'personal','secret':secret,'idempotency_key':'cred-key'},actor=owner)
        system=creds.create_credential(owner,{'purpose':'model_api_key','provider':'deepseek','scope':'system','label':'shared','secret':'sk-test-shared-key','idempotency_key':'sys-key'},actor=owner,actor_role='admin')
        request_key=str(uuid4())
        begin=reset.begin_workspace_reset(owner_principal=owner,workspace_id=ctx['workspace_id'],idempotency_key=request_key)
        final=reset.finalize_workspace_reset(owner_principal=owner,workspace_id=ctx['workspace_id'],reset_id=begin['reset_id'],idempotency_key=request_key,released_sessions=[ctx['session_id']])
        assert final['status']=='reset';assert final['archive']['retention_days']==7
        archive=store._fetch_one('SELECT * FROM workspace_reset_archives WHERE reset_id=:id',{'id':begin['reset_id']})
        assert set(archive['payload_json']['tables'])=={t for t,_ in RESET_SCOPE}
        assert secret not in json.dumps(archive['payload_json'])
        encrypted=archive['payload_json']['tables']['credentials'][0]
        assert encrypted['envelope_ciphertext'] and encrypted['envelope_nonce']
        assert len(archive['payload_json']['tables']['paper_accounts'])==1
        assert len(archive['payload_json']['tables']['stock_pool_snapshot_members'])==1
        assert len(archive['payload_json']['tables']['product_feedback'])==1
        after=store._fetch_one('SELECT * FROM users WHERE username=:owner',{'owner':owner})
        for key in ('user_id','username','email','display_name','password_hash','role','status'):
            assert after[key]==identity[key]
        assert after['preferences'] is None and after['default_prompt'] is None
        assert users.get_ui_preferences(uid)['color_mode']=='system'
        assert policies.get(owner)['automation_enabled'] is False
        assert store._fetch_one('SELECT task_id FROM research_tasks WHERE task_id=:id',{'id':task_b})
        assert store._fetch_one('SELECT credential_id FROM credentials WHERE scope=\'system\' AND credential_id=:id',{'id':system['credential_id']})
        assert creds.list_credentials(owner)==[]
        assert reset.begin_workspace_reset(owner_principal=owner,workspace_id=ctx['workspace_id'],idempotency_key=request_key)['receipt']['archive']==final['archive']
        # Even after payload expiry, a retired external command identity must
        # fail instead of creating another account under the same request key.
        with pytest.raises(DBAPIError,match='retired'):
            paper.create_account({'name':'replayed simulation','cash':10000,'idempotency_key':'paper-key'},trusted_owner=owner,trusted_workspace=ctx['workspace_id'])
        assert store._fetch_one('SELECT count(*) AS n FROM paper_accounts WHERE workspace_id=:id',{'id':ctx['workspace_id']})['n']==0
        paper.create_account({'name':'new simulation','cash':10000,'idempotency_key':'paper-new-key'},trusted_owner=owner,trusted_workspace=ctx['workspace_id'])
        assert store._fetch_one('SELECT count(*) AS n FROM paper_accounts WHERE workspace_id=:id',{'id':ctx['workspace_id']})['n']==1
        reset.begin_workspace_reset(owner_principal=owner,workspace_id=ctx['workspace_id'],idempotency_key=request_key)
        assert store._fetch_one('SELECT count(*) AS n FROM paper_accounts WHERE workspace_id=:id',{'id':ctx['workspace_id']})['n']==1
    finally:
        for obj in (users,paper,policies,feedback,creds,reset,store):obj.close()


def test_account_writers_are_fenced_and_other_user_remains_writable():
    suffix=uuid4().hex[:12];owner='reset-fence-'+suffix;other='reset-write-'+suffix
    ctx,_,_,_,_=_research_graph(owner,suffix=suffix+'a');ctx_b,_,_,_,_=_research_graph(other,suffix=suffix+'b')
    store=WorkspaceResetStore();reset=WorkspaceRuntimeResetStore()
    try:
        key=str(uuid4());begin=reset.begin_workspace_reset(owner_principal=owner,workspace_id=ctx['workspace_id'],idempotency_key=key)
        for sql,params in (
            ('UPDATE users SET preferences=:value WHERE username=:owner',{'value':'late preference','owner':owner}),
            ('''INSERT INTO user_agent_policy(owner_principal,automation_enabled,paused,default_decision_mode,
                max_auto_executions_per_hour,max_auto_failures_per_hour,updated_at)
                VALUES (:owner,false,false,'manual',20,3,now())''',{'owner':owner}),
        ):
            with pytest.raises(DBAPIError,match='disabled'):
                store._execute(sql,params)
        store._execute('UPDATE users SET preferences=:value WHERE username=:owner',{'value':'other survives','owner':other})
        assert store._fetch_one('SELECT preferences FROM users WHERE username=:owner',{'owner':other})['preferences']=='other survives'
        reset.finalize_workspace_reset(owner_principal=owner,workspace_id=ctx['workspace_id'],reset_id=begin['reset_id'],idempotency_key=key,released_sessions=[ctx['session_id']])
    finally:store.close();reset.close()


@pytest.mark.parametrize('status',['reserved','accepted','outcome_unknown'])
def test_unresolved_continuation_blocks_before_fence(status):
    suffix=uuid4().hex[:12];owner='reset-unknown-'+suffix
    ctx,_,task,_,_=_research_graph(owner,suffix=suffix);store=WorkspaceResetStore();reset=WorkspaceRuntimeResetStore()
    try:
        store._execute('UPDATE research_tasks SET continuation_budget=CAST(:budget AS jsonb) WHERE task_id=:task',
                       {'budget':[{'reservation_id':'unknown-call','status':status}],'task':task})
        with pytest.raises(WorkspaceRuntimeResetConflict,match='reservation'):
            reset.begin_workspace_reset(owner_principal=owner,workspace_id=ctx['workspace_id'],idempotency_key=str(uuid4()))
        assert store._fetch_one('SELECT status FROM workspaces WHERE workspace_id=:id',{'id':ctx['workspace_id']})['status']=='active'
        assert store._fetch_one('SELECT count(*) AS n FROM workspace_reset_archives')['n']==0
    finally:store.close();reset.close()


def test_archive_failure_rolls_back_all_deletes_and_fence(monkeypatch):
    suffix=uuid4().hex[:12];owner='reset-limit-'+suffix;ctx,_,task,_,_=_research_graph(owner,suffix=suffix)
    from app import workspace_reset
    store=WorkspaceResetStore()
    try:
        monkeypatch.setattr(workspace_reset,'MAX_ARCHIVE_BYTES',1)
        with pytest.raises(WorkspaceResetBlocked,match='byte limit'):
            store.reset_workspace(owner_principal=owner,workspace_id=ctx['workspace_id'])
        assert store._fetch_one('SELECT task_id FROM research_tasks WHERE task_id=:id',{'id':task})
        assert store._fetch_one('SELECT status FROM workspaces WHERE workspace_id=:id',{'id':ctx['workspace_id']})['status']=='active'
        assert store._fetch_one('SELECT count(*) AS n FROM workspace_reset_archives')['n']==0
    finally:store.close()


def test_seven_day_expiry_keeps_current_archive_and_shared_blobs(tmp_path):
    from app.backtest import LocalObjectStore
    suffix=uuid4().hex[:12];owner='reset-ttl-'+suffix;ctx,_,_,_,artifact=_research_graph(owner,suffix=suffix)
    store=WorkspaceResetStore();objects=LocalObjectStore(tmp_path)
    try:
        ref=objects.put('backtest-results',b'original archived result',media_type='application/json')
        store._execute('UPDATE artifacts SET content=CAST(:content AS jsonb) WHERE artifact_id=:id',{'content':{'result_reference':ref},'id':artifact})
        result=store.reset_workspace(owner_principal=owner,workspace_id=ctx['workspace_id'])
        with store.engine.begin() as con:
            assert expire_archives(con)['expired_archives']==0
        assert objects.get(ref)==b'original archived result'
        with pytest.raises(DBAPIError,match='immutable'):
            store._execute('DELETE FROM workspace_reset_archives WHERE reset_id=:id',{'id':result['archive']['reset_id']})
        # Earlier archive is created with an already-expired UTC interval;
        # immutable historical timestamps are never edited to fake expiry.
        old_id=uuid4().hex;created=datetime.now(timezone.utc)-timedelta(days=8)
        store._execute('''INSERT INTO workspace_reset_archives(reset_id,workspace_id,owner_principal,created_at,expires_at,
          payload_json,payload_sha256,counts_json,object_references_json) VALUES(:id,:w,:owner,:created,:expires,
          '{}'::jsonb,:digest,'{}'::jsonb,CAST(:refs AS jsonb))''',
          {'id':old_id,'w':ctx['workspace_id'],'owner':owner,'created':created,'expires':created+timedelta(days=7),'digest':'a'*64,'refs':[ref]})
        with store.engine.begin() as con:
            assert expire_archives(con)['expired_archives']==1
            assert collect_expired_objects(con,backtest_root=tmp_path,ml_root=tmp_path)['deleted_objects']==0
        assert objects.get(ref)==b'original archived result'
        assert store._fetch_one('SELECT reset_id FROM workspace_reset_archives WHERE reset_id=:id',{'id':old_id}) is None
        assert store._fetch_one('SELECT reset_id FROM workspace_reset_archives WHERE reset_id=:id',{'id':result['archive']['reset_id']})
    finally:store.close()


@pytest.mark.parametrize('table',['workspace_reset_archives','strategy_approval_fact_archive'])
def test_archive_truncate_is_rejected(table):
    store=WorkspaceResetStore()
    try:
        with pytest.raises(DBAPIError,match='truncation is forbidden'):
            store._execute('TRUNCATE '+table)
    finally:store.close()


@pytest.mark.parametrize('category',['transport_ambiguous','reconciliation_conflict','provider_unavailable'])
def test_legacy_failed_terminal_publication_is_not_known_external_outcome(category):
    _admin,alice,_bob=provision();feedback=ProductFeedbackStore();reset=WorkspaceRuntimeResetStore()
    try:
        item=create(feedback,alice,'legacy-reset-'+uuid4().hex)
        publication_id='feedback_publication_'+uuid4().hex
        event_id='feedback_outbox_'+uuid4().hex
        feedback._execute("UPDATE product_feedback SET publication_status='failed_terminal' WHERE feedback_id=:id",
                          {'id':item['feedback_id']})
        feedback._execute('''INSERT INTO product_feedback_publications
          (publication_id,feedback_id,schema_version,snapshot_json,snapshot_hash,created_by,created_at)
          VALUES(:publication,:feedback,'feedback-publication.v1',:snapshot,:hash,'legacy-test',NOW())''',
          {'publication':publication_id,'feedback':item['feedback_id'],
           'snapshot':{'schema_version':'feedback-publication.v1','public_content':{},'redactions':{}},'hash':'b'*64})
        feedback._execute('''INSERT INTO product_feedback_outbox
          (event_id,feedback_id,publication_id,schema_version,snapshot_hash,destination_key,state,attempt,
           next_attempt_at,lease_fence,create_started,last_error_category,created_at,updated_at)
          VALUES(:event,:feedback,:publication,'feedback-outbox.v1',:hash,'github_primary','failed_terminal',1,
                 NOW(),0,TRUE,:category,NOW(),NOW())''',
          {'event':event_id,'feedback':item['feedback_id'],'publication':publication_id,'hash':'b'*64,'category':category})
        legacy_workspace=workspace(alice)
        with pytest.raises(WorkspaceRuntimeResetConflict,match='feedback delivery'):
            reset.begin_workspace_reset(owner_principal=str(alice['username']),workspace_id=legacy_workspace,idempotency_key=str(uuid4()))
        assert feedback._fetch_one('SELECT state,create_started FROM product_feedback_outbox WHERE event_id=:id',{'id':event_id})=={'state':'failed_terminal','create_started':True}
        assert feedback._fetch_one('SELECT github_issue_number FROM product_feedback_publications WHERE publication_id=:id',{'id':publication_id})['github_issue_number'] is None
    finally:feedback.close();reset.close()


def test_concurrent_profile_write_drains_before_archive():
    import time
    suffix=uuid4().hex[:12];owner='reset-drain-'+suffix
    ctx,_,_,_,_=_research_graph(owner,suffix=suffix);store=WorkspaceResetStore();reset=WorkspaceRuntimeResetStore()
    started=threading.Event();key=str(uuid4())
    def begin():
        started.set()
        return reset.begin_workspace_reset(owner_principal=owner,workspace_id=ctx['workspace_id'],idempotency_key=key)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with store.engine.begin() as writer:
                writer.execute(text("UPDATE users SET preferences='committed before reset' WHERE username=:owner"),{'owner':owner})
                future=pool.submit(begin);assert started.wait(1)
                deadline=time.monotonic()+2;observed=False
                while time.monotonic()<deadline:
                    with store.engine.connect() as observer:
                        observed=bool(observer.execute(text("""SELECT 1 FROM pg_stat_activity
                          WHERE datname=current_database() AND wait_event_type='Lock'
                            AND query LIKE '%FOR UPDATE OF w%' LIMIT 1""")).first())
                    if observed:break
                    time.sleep(.01)
                assert observed,'must actually observe reset waiting behind profile writer'
                assert not future.done()
            begun=future.result(timeout=3)
        final=reset.finalize_workspace_reset(owner_principal=owner,workspace_id=ctx['workspace_id'],reset_id=begun['reset_id'],idempotency_key=key,released_sessions=[ctx['session_id']])
        payload=store._fetch_one('SELECT payload_json FROM workspace_reset_archives WHERE reset_id=:id',{'id':final['archive']['reset_id']})['payload_json']
        assert payload['profile_defaults']['preferences']=='committed before reset'
    finally:store.close();reset.close()


def test_expired_unreferenced_blob_is_collected_once(tmp_path):
    from app.backtest import LocalObjectStore
    store=WorkspaceResetStore();objects=LocalObjectStore(tmp_path)
    try:
        ref=objects.put('ml-models',b'expired model bytes',media_type='application/octet-stream')
        created=datetime.now(timezone.utc)-timedelta(days=8)
        store._execute("""INSERT INTO workspace_reset_archives(reset_id,workspace_id,owner_principal,created_at,expires_at,
          payload_json,payload_sha256,counts_json,object_references_json) VALUES(:id,'archived-only','archived-owner',:created,:expires,
          '{}'::jsonb,:digest,'{}'::jsonb,CAST(:refs AS jsonb))""",{'id':uuid4().hex,'created':created,'expires':created+timedelta(days=7),'digest':'b'*64,'refs':[ref]})
        with store.engine.begin() as con:
            assert expire_archives(con)['expired_archives']==1
            assert collect_expired_objects(con,backtest_root=tmp_path,ml_root=tmp_path)['deleted_objects']==1
        assert not objects.exists(ref)
        with store.engine.begin() as con:
            assert expire_archives(con)['expired_archives']==0
            assert collect_expired_objects(con,backtest_root=tmp_path,ml_root=tmp_path)['deleted_objects']==0
    finally:store.close()


@pytest.mark.parametrize('category',['authentication_failed','validation_rejected'])
def test_last_hub_error_does_not_clear_previous_unknown_attempt(category):
    from tests.test_product_feedback import provision,create
    _,user,_=provision();feedback=ProductFeedbackStore();reset=WorkspaceRuntimeResetStore()
    try:
        item=create(feedback,user);workspace=feedback._fetch_one('SELECT workspace_id FROM product_feedback WHERE feedback_id=:id',{'id':item['feedback_id']})['workspace_id']
        feedback._execute("""INSERT INTO product_feedback_hub_outbox
          (event_id,feedback_id,schema_version,snapshot_json,snapshot_hash,state,attempt,next_attempt_at,created_at,updated_at,last_error_category)
          VALUES(:event,:feedback,'feedback-hub-delivery.v1','{}'::jsonb,'hash','failed_terminal',2,now(),now(),now(),:category)""",
          {'event':'hub-two-attempts','feedback':item['feedback_id'],'category':category})
        with pytest.raises(WorkspaceRuntimeResetConflict,match='feedback delivery'):
            reset.begin_workspace_reset(owner_principal=str(user['username']),workspace_id=workspace,idempotency_key=str(uuid4()))
        assert feedback._fetch_one('SELECT attempt,last_error_category FROM product_feedback_hub_outbox')=={'attempt':2,'last_error_category':category}
    finally:feedback.close();reset.close()


def test_cas_deadline_defers_without_unlink(tmp_path,monkeypatch):
    from app import workspace_reset_retention as retention
    from app.backtest import LocalObjectStore
    store=WorkspaceResetStore();objects=LocalObjectStore(tmp_path)
    try:
        ref=objects.put('ml-models',b'bounded deletion candidate',media_type='application/octet-stream')
        store._execute("""INSERT INTO workspace_reset_expired_objects(namespace,object_id,reference_json)
          VALUES(:namespace,:id,CAST(:ref AS jsonb))""",{'namespace':ref['namespace'],'id':ref['object_id'],'ref':ref})
        monkeypatch.setattr(retention,'MAX_GC_SECONDS',0)
        with store.engine.begin() as con:
            assert retention.collect_expired_objects(con,backtest_root=tmp_path,ml_root=tmp_path)['deleted_objects']==0
        assert objects.get(ref)==b'bounded deletion candidate'
        assert store._fetch_one('SELECT count(*) AS n FROM workspace_reset_expired_objects')['n']==1
    finally:store.close()


@pytest.mark.parametrize('root_kind',['directory_without_namespace','regular_file'])
def test_missing_object_mount_or_namespace_keeps_expiry_queue(tmp_path,root_kind):
    store=WorkspaceResetStore();root=tmp_path/'mount'
    try:
        if root_kind=='regular_file':root.write_bytes(b'not a mounted directory')
        else:root.mkdir()
        ref={'namespace':'ml-models','object_id':'c'*64,'sha256':'c'*64,'size':10,'media_type':'application/octet-stream'}
        store._execute("""INSERT INTO workspace_reset_expired_objects(namespace,object_id,reference_json)
          VALUES(:namespace,:id,CAST(:ref AS jsonb))""",{'namespace':ref['namespace'],'id':ref['object_id'],'ref':ref})
        with store.engine.begin() as con:
            assert collect_expired_objects(con,backtest_root=root,ml_root=root)['deleted_objects']==0
        assert store._fetch_one('SELECT count(*) AS n FROM workspace_reset_expired_objects')['n']==1
    finally:store.close()


@pytest.mark.parametrize('state,checks,has_receipt,mismatch,allowed', [
    ('prepared',0,False,None,True),
    ('prepared',1,False,None,False),
    ('prepared',0,False,'watch_run',False),
    ('rejected',0,False,None,True),
    ('rejected',2,False,None,True),
    ('awaiting_receipt',0,False,None,False),
    ('needs_attention',8,False,None,False),
    ('conflict',0,False,None,False),
    ('unknown_future_state',0,False,None,False),
    ('confirmed',0,False,None,False),
    ('prepared',0,True,None,False),
    ('rejected',0,True,None,False),
    ('confirmed',0,True,None,True),
    ('confirmed',0,True,'identity',False),
    ('confirmed',0,True,'watch_run',False),
    ('confirmed',0,True,'active_job',False),
    ('confirmed',0,True,'alias_only',True),
])
def test_ml_watch_reset_requires_closed_frozen_receipt(state,checks,has_receipt,mismatch,allowed):
    """Synthetic DB rows exercise reset guards; no model/Worker execution."""
    suffix=uuid4().hex[:12];owner='reset-watch-'+suffix
    ctx,_,task,experiment,artifact=_research_graph(owner,suffix=suffix)
    store=WorkspaceResetStore();paper=PaperTradingStore()
    try:
        pool=paper.create_pool({'name':'Receipt guard','symbols':['000001.SZ']},
            trusted_owner=owner,trusted_workspace=ctx['workspace_id'])
        run='mlrun_'+uuid4().hex;key='reset-watch-'+suffix
        identity={'workspace_id':ctx['workspace_id'],'owner_principal':owner,'task_id':task,
                  'experiment_id':experiment,'ml_strategy_artifact_id':artifact,
                  'stock_pool_snapshot_id':pool['current_snapshot_id']}
        if has_receipt:
            store._execute("""INSERT INTO ml_training_runs(training_run_id,workspace_id,owner_principal,
                task_id,experiment_id,ml_strategy_artifact_id,stock_pool_snapshot_id,status,
                preparation_json,requirement_json,readiness_json,trace_id,idempotency_key,request_hash,
                created_at,updated_at) VALUES(:run,:workspace_id,:owner_principal,:task_id,:experiment_id,
                :ml_strategy_artifact_id,:stock_pool_snapshot_id,:status,'{}','{}','{}','guard-trace',:key,
                :hash,now(),now())""",{**identity,'run':run,'key':key+'original' if mismatch=='alias_only' else key,
                'hash':'a'*64,'status':'running' if mismatch=='active_job' else 'cancelled'})
            if mismatch=='alias_only':
                store._execute("""INSERT INTO ml_training_submission_keys
                    (workspace_id,owner_principal,idempotency_key,request_hash,training_run_id)
                    VALUES(:workspace_id,:owner_principal,:key,:hash,:run)""",
                    {**identity,'key':key,'hash':'a'*64,'run':run})
        if mismatch=='identity':identity={**identity,'experiment_id':None}
        store._execute("""INSERT INTO ml_training_receipt_watches(watch_id,workspace_id,owner_principal,
            idempotency_key,request_hash,identity_json,state,training_run_id,check_count)
            VALUES(:id,:workspace_id,:owner_principal,:key,:hash,CAST(:identity AS jsonb),:state,:run,:checks)""",
            {**identity,'id':'mlwatch_'+uuid4().hex,'key':key,'hash':'b'*64,'identity':identity,'state':state,
             'run':'mlrun_wrong' if mismatch=='watch_run' else run if has_receipt and state=='confirmed' else None,
             'checks':checks})
        with store.engine.connect() as con:
            if allowed:store._preflight(con,owner=owner,workspace=ctx['workspace_id'])
            else:
                with pytest.raises(WorkspaceResetBlocked,match='ml_training'):
                    store._preflight(con,owner=owner,workspace=ctx['workspace_id'])
        assert store._fetch_one('SELECT status FROM workspaces WHERE workspace_id=:id',{'id':ctx['workspace_id']})['status']=='active'
        assert store._fetch_one('SELECT count(*) AS n FROM workspace_reset_archives')['n']==0
    finally:store.close();paper.close()
