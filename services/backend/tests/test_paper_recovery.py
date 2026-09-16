from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from decimal import Decimal
from app.paper_trading import PaperTradingStore
from tests.test_paper_trading import pytestmark


def test_rebind_original_key_replays_after_version_has_advanced():
    store = PaperTradingStore()
    try:
        account = store.create_account({'name':'rebind original','cash':1500},trusted_owner='alice')
        pool = store.create_pool({'name':'pool','symbols':['000001.SZ']},trusted_owner='alice')
        payload = {'pool_id':pool['pool_id'],'expected_version':account['version'],'idempotency_key':'original'}
        first = store.rebind_account(account['account_id'],payload,trusted_owner='alice')
        second = store.rebind_account(account['account_id'],payload,trusted_owner='alice')
        assert second['version'] == first['version']
        assert second['bound_snapshot_id'] == first['bound_snapshot_id']
    finally: store.close()


def test_concurrent_orders_cannot_spend_same_cash_twice():
    stores = [PaperTradingStore(),PaperTradingStore()]
    try:
        account = stores[0].create_account({'name':'concurrent cash','cash':1500},trusted_owner='alice')
        pool = stores[0].create_pool({'name':'two symbols','symbols':['000001.SZ','600000.SH']},trusted_owner='alice')
        barrier = Barrier(2)
        def submit(index):
            barrier.wait(timeout=5)
            return stores[index].submit_order({'account_id':account['account_id'],'pool_id':pool['pool_id'],
                'symbol':['000001.SZ','600000.SH'][index],'side':'buy','quantity':100,'price':10,'trade_date':'20260105',
                'idempotency_key':f'order-{index}'},trusted_owner='alice')
        with ThreadPoolExecutor(2) as executor:
            orders = list(executor.map(submit,range(2)))
        assert sorted(order['status'] for order in orders) == ['blocked','filled']
        final = stores[0].get_account(account['account_id'],trusted_owner='alice')
        ledger = stores[0]._fetch_one('SELECT sum(cash_delta) AS cash FROM paper_ledger_entries WHERE account_id=:id',{'id':account['account_id']})
        assert Decimal(str(final['cash'])) == ledger['cash']
    finally:
        for store in stores: store.close()


def test_original_order_replay_uses_its_frozen_pool_after_lifecycle_change():
    import pytest
    from app.paper_trading import PaperTradingConflict
    store = PaperTradingStore()
    try:
        account = store.create_account({'name':'original order','cash':1500},trusted_owner='alice')
        pool = store.create_pool({'name':'original pool','symbols':['000001.SZ']},trusted_owner='alice')
        payload = {'account_id':account['account_id'],'pool_id':pool['pool_id'],'symbol':'000001.SZ','side':'buy',
            'quantity':100,'price':10,'trade_date':'20260105','idempotency_key':'original-order'}
        order = store.submit_order(payload,trusted_owner='alice')
        store.set_pool_lifecycle(pool['pool_id'],{'status':'inactive','reason':'pause','idempotency_key':'pause'},trusted_owner='alice')
        assert store.submit_order(payload,trusted_owner='alice') == order
        with pytest.raises(PaperTradingConflict):
            store.submit_order({**payload,'price':9},trusted_owner='alice')
        assert store._fetch_one('SELECT count(*) AS n FROM paper_fills')['n'] == 1
        assert store._fetch_one("SELECT count(*) AS n FROM paper_ledger_entries WHERE entry_type='fill'")['n'] == 1
    finally: store.close()


def test_concurrent_same_order_has_one_fill_and_one_cash_movement():
    stores = [PaperTradingStore(),PaperTradingStore()]
    try:
        account = stores[0].create_account({'name':'same order','cash':1500},trusted_owner='alice')
        pool = stores[0].create_pool({'name':'pool','symbols':['000001.SZ']},trusted_owner='alice')
        payload = {'account_id':account['account_id'],'pool_id':pool['pool_id'],'symbol':'000001.SZ','side':'buy',
            'quantity':100,'price':10,'trade_date':'20260105','idempotency_key':'original'}
        barrier = Barrier(2)
        def submit(store):
            barrier.wait(timeout=5)
            return store.submit_order(payload,trusted_owner='alice')
        with ThreadPoolExecutor(2) as executor:
            results = list(executor.map(submit,stores))
        assert results[0] == results[1]
        assert stores[0]._fetch_one('SELECT count(*) AS n FROM paper_fills')['n'] == 1
        assert Decimal(str(stores[0].get_account(account['account_id'],trusted_owner='alice')['cash'])) == Decimal('495')
    finally:
        for store in stores: store.close()
