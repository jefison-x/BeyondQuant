"""Database contention must not leave research commands waiting past caller failure."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from time import monotonic
import os
import pytest
from fastapi.testclient import TestClient
from app import main
from app.db import execute
from app.research import ResearchStore
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.getenv('BYQ_DATABASE_URL'), reason='isolated PostgreSQL required')


def test_research_transition_locked_row_has_safe_bounded_failure(monkeypatch):
    headers = trusted_agent_context('research-lock-owner')
    store = ResearchStore()
    monkeypatch.setattr(main, 'research_store', store)
    client = TestClient(main.app, raise_server_exceptions=False)
    created = client.post('/v1/research/tasks', headers=headers, json={
        'owner_principal': 'research-lock-owner', 'title': 'Locked task',
        'objective': 'No late transition', 'trace_id': 'trace-test', 'idempotency_key': 'locked-task',
    })
    assert created.status_code == 201, created.text
    task = created.json()
    response = None
    try:
        with ThreadPoolExecutor(1) as executor:
            with store.engine.begin() as blocking:
                execute(blocking, 'SELECT task_id FROM research_tasks WHERE task_id=:id FOR UPDATE', {'id':task['task_id']})
                started = monotonic()
                future = executor.submit(client.post, f"/v1/research/tasks/{task['task_id']}/transitions",
                    headers=headers, json={'target_status':'running','idempotency_key':'original-transition'})
                try: response = future.result(timeout=3)
                except TimeoutError: pass
            future.result(timeout=5)
        assert response is not None, 'research write stayed queued beyond the bounded response window'
        assert response.status_code == 503 and monotonic()-started < 3
        assert response.json() == {'detail':'research storage is unavailable'}
        assert store.get_task(task['task_id'])['status'] == 'planned'
        assert store._fetch_one('SELECT count(*) AS n FROM research_transitions')['n'] == 0
    finally:
        store.close()


def test_research_process_lock_does_not_queue_reads_indefinitely(monkeypatch):
    headers = trusted_agent_context('research-process-owner')
    store = ResearchStore()
    monkeypatch.setattr(main, 'research_store', store)
    client = TestClient(main.app, raise_server_exceptions=False)
    try:
        with ThreadPoolExecutor(1) as executor:
            with store._lock:
                started = monotonic()
                future = executor.submit(client.get, '/v1/research/tasks', headers=headers)
                response = future.result(timeout=3)
        assert monotonic()-started < 3
        assert response.status_code == 503
        assert response.json() == {'detail':'research storage is unavailable'}
    finally:
        store.close()


def test_research_statement_deadline_rolls_back_metadata():
    from app.research import ResearchPersistenceError
    store = ResearchStore()
    try:
        started = monotonic()
        with pytest.raises(ResearchPersistenceError, match='research storage is unavailable'):
            with store._transaction() as connection:
                execute(connection, 'SELECT pg_sleep(6)')
        assert 4 < monotonic()-started < 6
        assert store.list_tasks() == {'tasks':[]}
    finally:
        store.close()
