from app.paper_trading import PaperTradingStore
from tests.test_paper_trading import pytestmark
from tests.workspace_helpers import trusted_agent_context


def test_import_original_receipt_survives_replay_and_scope_isolation():
    headers = trusted_agent_context('import-owner')
    scope = {'trusted_owner':'import-owner','trusted_workspace':headers['x-byq-workspace-id']}
    store = PaperTradingStore()
    try:
        source = store.create_account({'name':'source','cash':1500},trusted_owner='import-owner')
        bundle = store.export_bundle(source['account_id'],trusted_owner='import-owner')
        first = store.import_bundle(bundle,idempotency_key='original-import',**scope)
        second = store.import_bundle(bundle,idempotency_key='original-import',**scope)
        assert first['account']['account_id']==second['account']['account_id']
        receipt = store.reconcile_command('import','original-import',**scope)
        assert receipt['account_id']==first['account']['account_id']
        assert store.reconcile_command('import','original-import',**{**scope,'trusted_workspace':'foreign'})=={'state':'not_found'}
        assert store._fetch_one("SELECT count(*) AS n FROM paper_transfer_audit WHERE direction='import'")['n']==1
        assert store._fetch_one("SELECT count(*) AS n FROM paper_accounts")['n']==2
    finally: store.close()


def test_concurrent_same_bundle_has_one_import_and_rejects_changed_identity():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import pytest
    from app.paper_trading import PaperTradingConflict
    headers = trusted_agent_context('concurrent-import-owner')
    scope = {'trusted_owner':'concurrent-import-owner','trusted_workspace':headers['x-byq-workspace-id']}
    stores = [PaperTradingStore(),PaperTradingStore()]
    try:
        source = stores[0].create_account({'name':'concurrent source','cash':1500},trusted_owner=scope['trusted_owner'])
        bundle = stores[0].export_bundle(source['account_id'],trusted_owner=scope['trusted_owner'])
        barrier = Barrier(2)
        def submit(store):
            barrier.wait(timeout=5)
            return store.import_bundle(bundle,idempotency_key='same-import',**scope)
        with ThreadPoolExecutor(2) as executor:
            results = list(executor.map(submit,stores))
        assert results[0]['account']['account_id']==results[1]['account']['account_id']
        assert stores[0]._fetch_one("SELECT count(*) AS n FROM paper_transfer_audit WHERE direction='import'")['n']==1
        with pytest.raises(PaperTradingConflict):
            stores[0].import_bundle(bundle,idempotency_key='same-import',**{**scope,'trusted_workspace':'foreign'})
    finally:
        for store in stores: store.close()


def test_bundle_digest_is_stable_original_key_for_service_imports():
    store = PaperTradingStore()
    try:
        source = store.create_account({'name':'service source','cash':1500},trusted_owner='alice')
        bundle = store.export_bundle(source['account_id'],trusted_owner='alice')
        first = store.import_bundle(bundle,trusted_owner='alice')
        assert store.import_bundle(bundle,trusted_owner='alice')['account']['account_id']==first['account']['account_id']
    finally: store.close()
