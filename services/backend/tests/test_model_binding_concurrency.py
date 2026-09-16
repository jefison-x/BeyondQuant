from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from tests.test_credentials import _store, pytestmark
from app.credentials import CredentialConflict
import pytest


@pytest.mark.parametrize("initialized",[False,True])
def test_same_expected_model_binding_version_cannot_commit_twice(initialized):
    stores=[_store(),_store()]
    try:
        initial=stores[0].bind('alice','byq-product',None) if initialized else {'version':0}
        boundary=Barrier(2)
        # Force the old pre-write version reads to observe the same committed version.
        for store in stores:
            original=store._fetch_one
            def read(sql,params=None,_original=original):
                value=_original(sql,params)
                if 'SELECT * FROM agent_model_bindings' in sql:boundary.wait(timeout=5)
                return value
            store._fetch_one=read
        def change(store):
            try:
                return store.bind('alice','byq-product',None,expected_version=initial['version'])
            except CredentialConflict:
                return 'conflict'
        with ThreadPoolExecutor(2) as executor:results=list(executor.map(change,stores))
        assert sum(result=='conflict' for result in results)==1
        successful=next(result for result in results if result!='conflict')
        assert successful['version']==initial['version']+1
        assert stores[0].list_bindings('alice')[0]['version']==successful['version']
    finally:
        for store in stores:store.close()
