from __future__ import annotations

import os
import pytest

from fastapi.testclient import TestClient

from app import main
from app.research import ResearchStore
from test_factor_research import factor_payload
from tests.workspace_helpers import trusted_agent_context




pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)

def test_factor_endpoint_persists_factor_result_artifact(monkeypatch) -> None:
    context = trusted_agent_context(
        "product-user", trace_id="byq-trace-factor-api", session_id="byq-session-factor-api",
        dsh_run_id="byq-run-factor-api",
    )
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)
    client.headers.update(context)
    task = client.post(
        "/v1/research/tasks",
        json={
            "owner_principal": "product-user",
            "title": "Factor task",
            "objective": "Compute a deterministic factor.",
            "trace_id": "byq-trace-factor-api",
            "idempotency_key": "factor-api-task-1",
        },
    ).json()

    request = {**factor_payload(), "task_id": task["task_id"], "idempotency_key": "factor-api-compute-1"}
    response = client.post("/v1/research/factors/compute", json=request)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["factor"]["reproducibility"] == "reproducible"
    assert store._fetch_one("SELECT count(*) AS n FROM agent_domain_call_claims")["n"] == 0
    assert body["artifact"]["kind"] == "factor_result"
    assert body["artifact"]["lineage"][-1]["kind"] == "factor_input"

    def no_recompute(*args, **kwargs):
        raise AssertionError("same-key retry must not recompute the factor")
    monkeypatch.setattr(main, "compute_factor", no_recompute)
    retry = client.post("/v1/research/factors/compute", json=request)
    assert retry.status_code == 201
    assert retry.json()["artifact"]["artifact_id"] == body["artifact"]["artifact_id"]
    store.close()


def _factor_submission_fixture():
    headers = trusted_agent_context('factor-recovery')
    context = {k.removeprefix('x-byq-').replace('-', '_'): v for k, v in headers.items()}
    store = ResearchStore()
    task = store.create_task({'owner_principal':'factor-recovery','title':'Recovery',
        'objective':'Synthetic factor recovery','trace_id':context['trace_id'],
        'idempotency_key':'parent'}, trusted_context=context)
    return store, context, {**factor_payload(), 'task_id':task['task_id']}


def test_factor_reopen_normalized_retry_and_conflicts():
    from app.factor_submission import submit_factor
    from app.factor_research import compute_factor
    from app.research import IdempotencyConflict
    store, context, payload = _factor_submission_fixture()
    first = submit_factor(store, payload, context, compute_factor)
    store.close()
    store = ResearchStore()
    def forbidden(_):
        raise AssertionError('must reuse original calculation')
    reordered = {**payload, 'bars':list(reversed(payload['bars']))}
    assert submit_factor(store, reordered, context, forbidden) == first
    for changed in ({'trace_id':'changed-trace'}, {'factor':{'name':'momentum','version':'1','lookback':2}}):
        with pytest.raises(IdempotencyConflict):
            submit_factor(store, {**payload, **changed}, context, forbidden)
    receipt = store.reconcile_submission('artifact', payload['idempotency_key'],
        trusted_owner=context['owner_principal'], trusted_workspace=context['workspace_id'], task_id=payload['task_id'])
    assert receipt['entity']['artifact_id'] == first['artifact']['artifact_id']
    store.close()


def test_concurrent_factor_submissions_compute_once():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock
    from app.factor_submission import submit_factor
    from app.factor_research import compute_factor
    store, context, payload = _factor_submission_fixture()
    lock, calls = Lock(), []
    def counted(value):
        with lock:
            calls.append(1)
        return compute_factor(value)
    def submit(_):
        other = ResearchStore()
        try:
            return submit_factor(other, payload, context, counted)
        finally:
            other.close()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(submit, range(3)))
    assert len(calls) == 1
    assert results[0] == results[1] == results[2]
    store.close()


def test_factor_failure_after_insert_rolls_back(monkeypatch):
    from app.factor_submission import submit_factor
    from app.factor_research import compute_factor
    store, context, payload = _factor_submission_fixture()
    create = store.create_artifact
    def fail(*args, **kwargs):
        create(*args, **kwargs)
        raise RuntimeError('synthetic crash before commit')
    with monkeypatch.context() as patch:
        patch.setattr(store, 'create_artifact', fail)
        with pytest.raises(RuntimeError):
            submit_factor(store, payload, context, compute_factor)
    receipt = store.reconcile_submission('artifact', payload['idempotency_key'],
        trusted_owner=context['owner_principal'], trusted_workspace=context['workspace_id'], task_id=payload['task_id'])
    assert receipt['status'] == 'outcome_unknown'
    assert submit_factor(store, payload, context, compute_factor)['artifact']['kind'] == 'factor_result'
    store.close()
