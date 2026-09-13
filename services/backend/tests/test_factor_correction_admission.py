"""Real PostgreSQL/HTTP factor admission; no model or provider requests."""
from fastapi.testclient import TestClient

from app import main
from app.agent_research import AgentResearchStore
from packages.contracts.domain_call_admission import request_evidence
from tests.test_domain_call_evidence import observed, pytestmark
from test_factor_research import factor_payload


def test_factor_requires_proof_and_persists_one_correction(observed, monkeypatch):
    store, evidence, scope, ctx = observed
    monkeypatch.setattr(main, 'agent_store', store)
    client = TestClient(main.app)
    headers = {**ctx, 'x-byq-root-run-id': evidence['root_run_id']}
    payload = factor_payload(task_id=evidence['task_id'], agent_run_id=evidence['agent_run_id'],
                             trace_id='trace-test', idempotency_key='factor-invalid',
                             factor={'name':'daily_return', 'version':'1', 'lookback':2})
    calls = []
    compute = main.compute_factor
    def counted(data):
        calls.append(data)
        return compute(data)
    monkeypatch.setattr(main, 'compute_factor', counted)
    def post(data, sequence, prove=True):
        if prove:
            store.consume_domain_call_evidence({**evidence,
                **request_evidence('byq_factor_compute', data, trace_id='trace-test'),
                'sequence':sequence}, **scope)
        return client.post('/v1/research/factors/compute', json=data, headers=headers)
    assert post(payload, 2, False).status_code == 425
    assert calls == []
    failure = post(payload, 2)
    assert failure.status_code == 422, failure.text
    assert failure.json()['detail']['validation']['field'] == 'factor.lookback'
    assert store._fetch_one('SELECT count(*) AS n FROM artifacts')['n'] == 0
    unchanged = post({**payload, 'idempotency_key':'new-key'}, 3)
    assert unchanged.status_code == 409
    assert unchanged.json()['detail']['reason'] == 'unchanged_failed_input'
    repaired = {**payload, 'idempotency_key':'repair',
                'factor':{'name':'daily_return', 'version':'1', 'lookback':1}}
    result = post(repaired, 4)
    assert result.status_code == 201, result.text
    assert len(calls) == 1
    assert result.json()['artifact']['trace_id'] == 'trace-test'
    reopened = AgentResearchStore()
    monkeypatch.setattr(main, 'agent_store', reopened)
    try:
        replay = post(repaired, 5)
        assert replay.status_code == 201 and replay.json() == result.json()
        assert len(calls) == 1
        exhausted = post({**repaired, 'idempotency_key':'third',
                          'factor':{'name':'momentum','version':'1','lookback':2}}, 6)
        assert exhausted.status_code == 409
        assert exhausted.json()['detail']['reason'] == 'correction_budget_exhausted'
        assert store._fetch_one('SELECT count(*) AS n FROM artifacts')['n'] == 1
    finally:
        reopened.close()


def test_factor_error_projection_never_echoes_unknown_input():
    from app.factor_research import FactorValidationError, prepare_factor_input
    from app.domain_call_admission import DomainValidationRejected
    import pytest
    with pytest.raises(FactorValidationError) as caught:
        prepare_factor_input(factor_payload(**{'private-secret-field':'sensitive'}))
    public = DomainValidationRejected('private', validation_error=caught.value).validation
    assert public['code'] == 'unknown_fields'
    assert 'private' not in str(public) and 'sensitive' not in str(public)
