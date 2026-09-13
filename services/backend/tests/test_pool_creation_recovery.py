"""Exact Stock Pool creation receipts across connections and restarts."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from app.paper_trading import PaperTradingStore, PaperTradingConflict
from tests.test_paper_api import pytestmark
from tests.workspace_helpers import trusted_agent_context


def test_custom_pool_same_key_creates_only_one_pool():
    headers = trusted_agent_context('pool-recovery')
    stores = [PaperTradingStore() for _ in range(3)]
    payload = {'name':'Original pool', 'symbols':['000001.SZ'], 'idempotency_key':'original'}
    try:
        with ThreadPoolExecutor(3) as executor:
            results = list(executor.map(lambda index: stores[index].create_pool(payload, trusted_owner='pool-recovery', trusted_workspace=headers['x-byq-workspace-id']), range(3)))
        assert len({item['pool_id'] for item in results}) == 1
        assert stores[0]._fetch_one('SELECT count(*) AS n FROM stock_pools')['n'] == 1
    finally:
        for store in stores: store.close()


def test_creation_receipts_are_exact_owner_workspace_kind_and_survive_restart():
    from app.stock_pool_producer import StockPoolProducerStore
    headers = trusted_agent_context('pool-receipt')
    context = {'trusted_owner':'pool-receipt', 'trusted_workspace':headers['x-byq-workspace-id']}
    paper = PaperTradingStore()
    payload = {'name':'original', 'symbols':['000001.SZ'], 'idempotency_key':'original'}
    pool = paper.create_pool(payload, **context)
    with pytest.raises(PaperTradingConflict):
        paper.create_pool({**payload, 'name':'changed'}, **context)
    with pytest.raises(PaperTradingConflict):
        paper.create_pool(payload, **{**context, "trusted_workspace":"foreign"})
    paper.close()
    reopened = StockPoolProducerStore()
    try:
        receipt = reopened.reconcile_creation('custom','original',**context)
        assert receipt['state'] == 'confirmed' and receipt['pool']['pool_id'] == pool['pool_id']
        assert reopened.reconcile_creation('index','original',**context) == {'state':'not_found'}
        assert reopened.reconcile_creation('custom','original',**{**context,'trusted_workspace':'foreign'}) == {'state':'not_found'}
        assert reopened.reconcile_creation('custom','original',**{**context,'trusted_owner':'foreign'}) == {'state':'not_found'}
    finally: reopened.close()


def test_dynamic_concurrent_creation_has_one_receipt_and_no_fake_run():
    from app.stock_pool_producer import StockPoolProducerStore
    from tests.test_dynamic_stock_pool import _rule
    headers = trusted_agent_context('dynamic-receipt')
    context = {'trusted_owner':'dynamic-receipt', 'trusted_workspace':headers['x-byq-workspace-id']}
    stores = [StockPoolProducerStore() for _ in range(3)]
    payload = {'name':'inactive intent', 'rule':_rule(), 'activate':False, 'requested_as_of':'20260815', 'idempotency_key':'original'}
    try:
        with ThreadPoolExecutor(3) as executor:
            results = list(executor.map(lambda index: stores[index].create_dynamic_pool(payload, **context), range(3)))
        assert len({result['pool']['pool_id'] for result in results}) == 1
        receipt = stores[0].reconcile_creation('dynamic','original',**context)
        assert receipt['state'] == 'confirmed' and receipt['run'] is None
        assert receipt['pool']['current_snapshot_id'] is None
    finally:
        for store in stores: store.close()
