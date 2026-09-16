"""Synthetic historical source qualification; never a real research completion."""
import pytest
from fastapi.testclient import TestClient
from app import main
from app.data_demand import DataDemandStore
from app.market_automation import MarketAutomationStore, sync_declared_inputs
from app.market_readiness import MarketReadinessStore
from app.index_snapshot_demand import index_snapshot_requirement
from tests.test_data_demand import _context
from tests.test_index_repair_cache import Provider, weights, provenance, pytestmark


def test_historical_preparation_progress_cache_reuse_and_exact_date(monkeypatch):
    context = _context()
    readiness, demands, automation = MarketReadinessStore(), DataDemandStore(), MarketAutomationStore()
    monkeypatch.setattr(main, 'market_readiness_store', readiness)
    monkeypatch.setattr(main, 'data_demand_store', demands)
    monkeypatch.setattr(main, 'market_automation_store', automation)
    client = TestClient(main.app)
    headers = {'x-byq-'+key.replace('_','-'):value for key,value in context.items()}
    payload = {'purpose':'research', 'scope_kind':'index_snapshot', 'index_symbol':'000300.SH',
               'requested_as_of':'2026-08-15', 'idempotency_key':'historical'}
    created = client.post('/v1/agent/data-demands', json=payload, headers=headers)
    assert created.status_code == 202, created.text
    assert created.json()['demand']['status'] == 'queued'
    demand_id = created.json()['demand']['demand_id']
    assert created.json()['demand']['scope']['historical_series'] is False
    claimed = automation.claim_data_repair()
    assert claimed is not None
    provider = Provider()
    sync_declared_inputs(claimed['requirement_json'], provider=provider, readiness_store=readiness)
    ready = readiness.assess(claimed['requirement_json'])
    assert ready['state'] == 'ready'
    assert ready['snapshot']['snapshot_date'] == '20260731'  # August 31 is future at the cutoff.
    assert len(provider.calls) == 3
    automation.complete_data_repair(claimed['request_id'])
    result = client.get('/v1/agent/data-demands/'+demand_id, headers=headers)
    assert result.json()['demand']['status'] == 'ready'
    assert '不表示历史调仓序列' in result.json()['demand']['notification']
    assert result.json()['demand']['progress']['unit'] == 'index_snapshots'
    repeated = client.post('/v1/agent/data-demands', json=payload, headers=headers)
    assert repeated.json()['created'] is False
    assert automation.claim_data_repair() is None
    sync_declared_inputs(claimed['requirement_json'], provider=provider, readiness_store=readiness)
    assert len(provider.calls) == 3
    readiness.close(); demands.close(); automation.close()


def test_future_only_or_tampered_evidence_never_satisfies_snapshot():
    store = MarketReadinessStore()
    _, requirement = index_snapshot_requirement('000300.SH', '20260815')
    store.import_index_weights('000300.SH','202608',weights('202608'),provenance().as_dict())
    assert store.assess(requirement)['state'] == 'missing'
    with pytest.raises(ValueError):
        store.assess({**requirement, 'end_date':'20260831'})
    store._execute("UPDATE market_index_weights SET weight=weight+1")
    with pytest.raises(ValueError):
        store.assess(requirement)
    store.close()
