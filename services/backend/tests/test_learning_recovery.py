"""Lost receipts must remain readable after a learning state transition."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from app.learning_loop import LearningLoopStore, LearningUnauthorized, LearningForbidden
from app.research import ResearchStore
from tests.test_learning_loop import make_task, make_artifact, pytestmark


def test_final_iteration_same_key_survives_restart_without_new_event():
    research = ResearchStore()
    task = make_task(research)
    store = LearningLoopStore(research_store=research)
    run = store.start_run({'task_id':task['task_id'], 'budget':{'max_iterations':1,'max_repairs':0},
        'trace_id':'trace-run', 'idempotency_key':'original-run'}, trusted_owner='alice')
    payload = {'run_id':run['learning_run_id'], 'iteration_index':1,'attempt':1,'outcome':'produced',
        'trace_id':'trace-iteration','idempotency_key':'original-iteration'}
    first = store.record_iteration(payload, trusted_owner='alice')
    assert first['run']['status'] == 'awaiting_review'
    store.close()
    reopened = LearningLoopStore(research_store=research)
    try:
        second = reopened.record_iteration(payload, trusted_owner='alice')
        assert second['iteration']['iteration_id'] == first['iteration']['iteration_id']
        assert reopened._fetch_one('SELECT count(*) AS n FROM learning_iterations')['n'] == 1
    finally: reopened.close(); research.close()


def test_learning_receipts_cover_existing_keys_and_reject_foreign_owner():
    research = ResearchStore()
    task = make_task(research)
    artifact = make_artifact(research, task['task_id'])
    store = LearningLoopStore(research_store=research)
    context = {'trusted_owner':'alice'}
    try:
        signal = store.create_signal({'task_id':task['task_id'],'source_artifact_id':artifact['artifact_id'],
            'metric':'sharpe','value':0.2,'trace_id':'trace-signal','idempotency_key':'signal-key'}, **context)
        lesson = store.propose_lesson({'task_id':task['task_id'],'content':{'text':'bounded observation'},
            'evidence':[{'kind':'artifact','id':artifact['artifact_id']}], 'trace_id':'trace-lesson','idempotency_key':'lesson-key'},**context)
        for kind, key, original, field in [('signal','signal-key',signal,'signal_id'),('lesson','lesson-key',lesson,'lesson_id')]:
            receipt = store.reconcile_submission(kind,key,task_id=task['task_id'],**context)
            assert receipt['state'] == 'confirmed' and receipt[kind][field] == original[field]
            assert store.reconcile_submission(kind,'absent',task_id=task['task_id'],**context) == {'state':'not_found'}
            with pytest.raises((LearningUnauthorized,LearningForbidden)):
                store.reconcile_submission(kind,key,task_id=task['task_id'],trusted_owner='bob')
    finally: store.close(); research.close()


def test_concurrent_last_iteration_returns_one_durable_event():
    research = ResearchStore()
    task = make_task(research)
    stores = [LearningLoopStore(research_store=ResearchStore()) for _ in range(3)]
    try:
        payload = {'task_id':task['task_id'],'budget':{'max_iterations':1,'max_repairs':0},'trace_id':'trace-run','idempotency_key':'run-key'}
        with ThreadPoolExecutor(3) as executor:
            runs = list(executor.map(lambda store:store.start_run(payload,trusted_owner='alice'),stores))
        assert len({run['learning_run_id'] for run in runs}) == 1
        run_id = runs[0]['learning_run_id']
        iteration = {'run_id':run_id,'iteration_index':1,'attempt':1,'outcome':'produced','trace_id':'trace-last','idempotency_key':'last-key'}
        with ThreadPoolExecutor(3) as executor:
            results = list(executor.map(lambda store:store.record_iteration(iteration,trusted_owner='alice'),stores))
        assert len({item['iteration']['iteration_id'] for item in results}) == 1
        receipt = stores[0].reconcile_submission('iteration','last-key',run_id=run_id,trusted_owner='alice')
        assert receipt['iteration']['iteration_id'] == results[0]['iteration']['iteration_id']
        assert receipt['run']['status'] == 'awaiting_review'
        assert stores[0]._fetch_one('SELECT count(*) AS n FROM learning_iterations')['n'] == 1
    finally:
        for store in stores: store.research_store.close(); store.close()
        research.close()
