import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from app.research import ResearchStore
from tests.test_web_research import evidence_fixture
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.getenv('BYQ_DATABASE_URL'), reason='isolated PostgreSQL required')


def test_concurrent_web_record_creates_one_task_and_artifact():
    trusted_agent_context('web-concurrent-owner')
    content = evidence_fixture()
    for source in content['sources']: source.pop('source_id')
    content['claims'][0]['source_indexes'] = [0]
    content['claims'][0].pop('source_ids')
    request = {'owner_principal':'web-concurrent-owner', 'trace_id':'trace-test',
        'task':{'title':'Concurrent web evidence','objective':'One durable original record'},
        'content':content,'lineage':[],'idempotency_key':'same-original-web-key'}
    stores = [ResearchStore() for _ in range(8)]
    barrier = Barrier(8)
    try:
        def create(store):
            barrier.wait(timeout=5)
            return store.create_web_evidence_record(request)
        with ThreadPoolExecutor(8) as executor:
            rows = list(executor.map(create, stores))
        assert len({row['task']['task_id'] for row in rows}) == 1
        assert len({row['artifact']['artifact_id'] for row in rows}) == 1
        assert stores[0]._fetch_one('SELECT count(*) AS n FROM research_tasks')['n'] == 1
        assert stores[0]._fetch_one('SELECT count(*) AS n FROM artifacts')['n'] == 1
    finally:
        for store in stores: store.close()


def test_web_record_artifact_failure_rolls_back_new_task(monkeypatch):
    from app import research
    from app.research import ResearchPersistenceError
    trusted_agent_context('web-rollback-owner')
    content = evidence_fixture()
    for source in content['sources']: source.pop('source_id')
    content['claims'][0]['source_indexes'] = [0]
    content['claims'][0].pop('source_ids')
    store = ResearchStore()
    original_execute = research.execute
    def fail_artifact(connection, sql, params=None):
        if 'INSERT INTO artifacts' in sql:
            raise ResearchPersistenceError('synthetic artifact persistence failure')
        return original_execute(connection, sql, params)
    try:
        monkeypatch.setattr(research, 'execute', fail_artifact)
        with pytest.raises(ResearchPersistenceError):
            store.create_web_evidence_record({'owner_principal':'web-rollback-owner','trace_id':'trace-test',
                'task':{'title':'Atomic evidence','objective':'No orphan task'},
                'content':content,'lineage':[],'idempotency_key':'rollback-original-web-key'})
        assert store._fetch_one('SELECT count(*) AS n FROM research_tasks')['n'] == 0
        assert store._fetch_one('SELECT count(*) AS n FROM artifacts')['n'] == 0
    finally:
        store.close()
