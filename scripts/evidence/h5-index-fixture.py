"""Explicit synthetic fixture for the isolated H5 Product browser flow only."""
import os
import sys
from sqlalchemy.engine import make_url

assert os.environ.get('BYQ_H5_EVIDENCE') == '1'
assert make_url(os.environ['BYQ_DATABASE_URL']).database == 'byq_domain_test'
sys.path.insert(0, "/app")
from app import main

mode = sys.argv[1]
if mode == 'bootstrap':
    main.user_store.create_user({'username':'h5-browser', 'password':'test-password-123',
        'display_name':'H5 synthetic browser', 'role':'admin'}, actor_role='admin')
elif mode == 'prepare':
    from calendar import monthrange
    from app.data_provider import IndexWeight, IndexWeightResult, Provenance
    from app.market_automation import sync_declared_inputs
    repair = main.market_automation_store.claim_data_repair()
    assert repair and repair['requirement_json']['kind'] == 'index_snapshot'
    assert repair['requirement_json']['requested_as_of'] == '20210815'
    class SyntheticProvider:
        def fetch_index_weights(self, symbol, start, end):
            date = start[:6] + str(monthrange(int(start[:4]), int(start[4:6]))[1])
            rows = tuple(IndexWeight(symbol, code, date, 50) for code in ('000001.SZ','600000.SH'))
            provenance = Provenance(provider='tushare',endpoint='index_weight',request_fingerprint='SYNTHETIC-H5-BROWSER',
                retrieved_at='2026-09-01T00:00:00+00:00',cache_hit=False,row_count=2)
            return IndexWeightResult(weights=rows, provenance=provenance)
    sync_declared_inputs(repair['requirement_json'], provider=SyntheticProvider(), readiness_store=main.market_readiness_store)
    assert main.market_readiness_store.assess(repair['requirement_json'])['state'] == 'ready'
    main.market_automation_store.complete_data_repair(repair['request_id'])
elif mode == 'materialize':
    run = main.stock_pool_producer_store.claim_next_run(worker_id='h5-synthetic-browser')
    assert run and run['requested_as_of'] == '20210815'
    result = main.stock_pool_producer_store.materialize_claimed(run, worker_id='h5-synthetic-browser')
    assert result['status'] == 'succeeded' and result['effective_trade_date'] == '20210731'
else:
    raise ValueError('unknown synthetic evidence step')
print(mode + ' PASS (synthetic data only)')
