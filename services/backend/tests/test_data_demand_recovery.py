"""Durable request identity and real repair transaction recovery."""
import pytest
from fastapi.testclient import TestClient
from app import main
from app.data_demand import DataDemandStore, DataDemandPersistenceError
from app.market_automation import MarketAutomationStore
from tests.test_data_demand import _context, _payload, FakeDemandReadiness, pytestmark


def test_demand_persistence_failure_rolls_back_repair(monkeypatch):
    context = _context()
    demands, automation = DataDemandStore(), MarketAutomationStore()
    requirement = {'requirement_sha256':'a'*64, 'start_date':'20260101', 'end_date':'20260131', 'partition':0}
    monkeypatch.setattr(main, 'data_demand_store', demands)
    monkeypatch.setattr(main, 'market_automation_store', automation)
    monkeypatch.setattr(main, 'market_readiness_store', FakeDemandReadiness())
    monkeypatch.setattr(main, '_data_demand_requirements', lambda *args: ({'symbol_count':1}, [requirement]))
    def fail(*args, **kwargs):
        raise DataDemandPersistenceError('synthetic fault before demand commit')
    monkeypatch.setattr(demands, 'create', fail)
    response = TestClient(main.app).post('/v1/agent/data-demands', json=_payload(),
        headers={'x-byq-'+key.replace('_','-'):value for key,value in context.items()})
    assert response.status_code == 503, response.text
    assert automation._fetch_one('SELECT count(*) AS n FROM market_data_repair_requests')['n'] == 0
    demands.close()
    automation.close()


def test_concurrent_demand_freezes_original_plan_and_reconciles():
    from concurrent.futures import ThreadPoolExecutor
    from app.data_demand import DataDemandConflict
    context = _context()
    demands, automation = DataDemandStore(), MarketAutomationStore()
    planned = []
    def planner(payload, context):
        planned.append(True)
        return {'symbol_count':1}, [{'requirement_sha256':'b'*64, 'start_date':'20260101', 'end_date':'20260131'}]
    def submit(_):
        return demands.submit(_payload(), context=context, planner=planner, automation_store=automation)
    with ThreadPoolExecutor(3) as executor:
        results = list(executor.map(submit, range(3)))
    assert sum(created for _, created in results) == 1
    assert len({item['demand_id'] for item, _ in results}) == 1
    assert len(planned) == 1
    assert automation._fetch_one('SELECT count(*) AS n FROM market_data_repair_requests')['n'] == 1
    demands.close()
    reopened = DataDemandStore()
    def forbidden(*args):
        raise AssertionError('retry must not recalculate mutable readiness or source plan')
    try:
        existing, created = reopened.submit(_payload(), context=context, planner=forbidden, automation_store=automation)
        assert not created and existing['demand_id'] == results[0][0]['demand_id']
        receipt = reopened.reconcile_submission('demand-1', trusted_owner='alice', trusted_workspace=context['workspace_id'])
        assert receipt == {'state':'confirmed', 'demand':existing}
        assert reopened.reconcile_submission('demand-1', trusted_owner='foreign', trusted_workspace=context['workspace_id']) == {'state':'not_found'}
        with pytest.raises(DataDemandConflict):
            reopened.submit({**_payload(), 'end_date':'2024-01-01'}, context=context, planner=forbidden, automation_store=automation)
    finally:
        reopened.close()
        automation.close()
