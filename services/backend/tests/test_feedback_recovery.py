from concurrent.futures import ThreadPoolExecutor
from app.product_feedback import ProductFeedbackStore
from tests.test_product_feedback import provision, workspace, content, pytestmark


def test_independent_concurrent_feedback_creation_returns_same_receipt():
    _, user, _ = provision()
    context = {'trusted_workspace':workspace(user),'trusted_owner':user['username'],'trusted_actor':user['username']}
    stores = [ProductFeedbackStore() for _ in range(3)]
    try:
        with ThreadPoolExecutor(3) as executor:
            results = list(executor.map(lambda store:store.create({**content(),'idempotency_key':'original'},**context),stores))
        assert len({item['feedback']['feedback_id'] for item in results}) == 1
        assert stores[0]._fetch_one('SELECT count(*) AS n FROM product_feedback')['n'] == 1
    finally:
        for store in stores: store.close()


def test_feedback_receipt_is_original_actor_scoped_and_read_only():
    _, user, other = provision()
    scope = workspace(user)
    store = ProductFeedbackStore()
    context = {'trusted_workspace':scope,'trusted_actor':user['username']}
    original = store.create({**content(),'idempotency_key':'original'},trusted_owner=user['username'],**context)['feedback']
    store.close()
    store = ProductFeedbackStore()
    try:
        receipt = store.reconcile_command('create','original',**context)
        assert receipt['state'] == 'confirmed' and receipt['feedback']['feedback_id'] == original['feedback_id']
        assert receipt['feedback']['status'] == 'draft'
        assert store.reconcile_command('create','original',**{**context,'trusted_actor':other['username']}) == {'state':'not_found'}
        assert store.reconcile_command('create','original',**{**context,'trusted_workspace':workspace(other)}) == {'state':'not_found'}
        changed = store.update(original['feedback_id'],{'content':content('新的反馈标题'), 'expected_version':1,'idempotency_key':'update-original'},**context)['feedback']
        update = store.reconcile_command('update','update-original',feedback_id=original['feedback_id'],**context)
        assert update['feedback']['version'] == changed['version'] == 2
        assert store.reconcile_command('create','original',**context)['feedback']['version'] == 1
        assert store._fetch_one('SELECT count(*) AS n FROM product_feedback')['n'] == 1
        assert store._fetch_one('SELECT count(*) AS n FROM product_feedback_hub_outbox')['n'] == 0
    finally: store.close()
