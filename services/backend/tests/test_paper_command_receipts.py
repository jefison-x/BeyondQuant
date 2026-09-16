from app.paper_trading import PaperTradingStore
from tests.test_paper_trading import pytestmark
from tests.workspace_helpers import trusted_agent_context


def test_account_creation_original_key_does_not_depend_on_mutable_name_lookup():
    headers = trusted_agent_context('account-receipts')
    store = PaperTradingStore()
    payload = {'name':'original','cash':1500,'idempotency_key':'account-original'}
    try:
        first = store.create_account(payload,trusted_owner='account-receipts',trusted_workspace=headers['x-byq-workspace-id'])
        second = store.create_account(payload,trusted_owner='account-receipts',trusted_workspace=headers['x-byq-workspace-id'])
        assert second['account_id'] == first['account_id']
        assert store._fetch_one("SELECT count(*) AS n FROM paper_ledger_entries WHERE entry_type='initial_funding'")['n'] == 1
    finally: store.close()


def test_paper_receipts_are_scoped_and_settlement_alias_has_no_second_snapshot():
    headers = trusted_agent_context('paper-command-owner')
    scope = {'trusted_owner':'paper-command-owner','trusted_workspace':headers['x-byq-workspace-id']}
    store = PaperTradingStore()
    try:
        account = store.create_account({'name':'receipts','cash':1500,'idempotency_key':'create-original'},**scope)
        identity=account['account_id']
        receipt = store.reconcile_command('create','create-original',**scope)
        assert receipt['state']=='confirmed' and receipt['account_id']==identity
        assert store.reconcile_command('create','create-original',**{**scope,'trusted_workspace':'foreign'})=={'state':'not_found'}
        payload={'trade_date':'20260106','expected_version':account['version'],'marks':{},'idempotency_key':'settle-original'}
        first=store.settle_account(identity,payload,trusted_owner=scope['trusted_owner'])
        second=store.settle_account(identity,{**payload,'idempotency_key':'settle-alias'},trusted_owner=scope['trusted_owner'])
        assert second['snapshot_id']==first['snapshot_id']
        alias=store.reconcile_command('settlement','settle-alias',account_id=identity,**scope)
        assert alias['details']['snapshot_id']==first['snapshot_id']
        assert alias['details']['receipt_alias'] is True
        assert store._fetch_one('SELECT count(*) AS n FROM paper_account_snapshots')['n']==1
        assert store._fetch_one("SELECT count(*) AS n FROM paper_ledger_entries WHERE entry_type='settlement'")['n']==1
    finally: store.close()


def test_all_account_command_receipts_survive_later_changes_and_deletion():
    headers = trusted_agent_context('paper-history-owner')
    scope = {'trusted_owner':'paper-history-owner','trusted_workspace':headers['x-byq-workspace-id']}
    owner = {'trusted_owner':scope['trusted_owner']}
    store = PaperTradingStore()
    try:
        account = store.create_account({'name':'history','cash':1500,'idempotency_key':'history-create'},**scope)
        identity = account['account_id']
        pool = store.create_pool({'name':'history pool','symbols':['000001.SZ']},**owner)
        bound = store.rebind_account(identity,{'pool_id':pool['pool_id'],'expected_version':account['version'],'idempotency_key':'history-rebind'},**owner)
        controls = store.update_controls(identity,{'expected_version':1,'kill_switch_engaged':False,'idempotency_key':'history-controls'},**owner)
        order = store.submit_order({'account_id':identity,'pool_id':pool['pool_id'],'symbol':'000001.SZ','side':'buy',
            'quantity':100,'price':10,'trade_date':'20260105','idempotency_key':'history-order'},**owner)
        assert order['status']=='filled'
        current = store.get_account(identity,**owner)
        store.delete_account(identity,{'expected_version':current['version'],'idempotency_key':'history-delete'},**owner)
        for operation in ('create','rebind','controls','order','delete'):
            receipt = store.reconcile_command(operation,'history-'+operation,account_id=identity,**scope)
            assert receipt['state']=='confirmed' and receipt['account_id']==identity
            assert store.reconcile_command(operation,'history-'+operation,account_id=identity,**{**scope,'trusted_owner':'foreign'})=={'state':'not_found'}
            if operation != 'create':
                assert store.reconcile_command(operation,'history-'+operation,account_id='paper_account_'+'0'*32,**scope)=={'state':'not_found'}
            if operation == 'order': assert receipt['order']==order
            if operation == 'controls': assert receipt['details']['version']==controls['version']
        assert store.reconcile_command('controls','history-delete',account_id=identity,**scope)=={'state':'not_found'}
    finally: store.close()
