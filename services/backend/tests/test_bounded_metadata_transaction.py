from contextlib import contextmanager
import pytest
from sqlalchemy.exc import IntegrityError,SQLAlchemyError
from app import db

class StorageUnavailable(RuntimeError):pass
class Lock:
    def __init__(self,available=True):self.available=available;self.wait=None;self.released=0
    def acquire(self,*,timeout):self.wait=timeout;return self.available
    def release(self):self.released+=1
class Engine:
    def __init__(self,commit_error=False):self.events=[];self.commit_error=commit_error
    @contextmanager
    def begin(self):
        self.events.append('begin')
        try:
            yield self
            if self.commit_error:raise SQLAlchemyError('private database diagnostic')
        except BaseException:
            self.events.append('rollback');raise
        else:self.events.append('commit')

def scope(engine,lock,**options):
    return db.bounded_metadata_transaction(engine,lock,error_type=StorageUnavailable,
        error_message='storage unavailable',**options)

def test_success_uses_shared_bounds_and_releases_after_commit(monkeypatch):
    engine=Engine();lock=Lock();sql=[]
    monkeypatch.setattr(db,'execute',lambda connection,statement:sql.append(statement))
    with scope(engine,lock) as connection:assert connection is engine
    assert lock.wait==2 and lock.released==1
    assert sql==["SET LOCAL lock_timeout = '2s'","SET LOCAL statement_timeout = '5s'"]
    assert engine.events==['begin','commit']

def test_lock_failure_does_not_open_connection_or_release_unowned_lock():
    engine=Engine();lock=Lock(False)
    with pytest.raises(StorageUnavailable,match='^storage unavailable$'):
        with scope(engine,lock):raise AssertionError('must not enter')
    assert not engine.events and lock.released==0

@pytest.mark.parametrize('commit_error',[False,True])
def test_database_failure_rolls_back_and_maps_safe_error(monkeypatch,commit_error):
    engine=Engine(commit_error);lock=Lock()
    monkeypatch.setattr(db,'execute',lambda *args:None)
    with pytest.raises(StorageUnavailable,match='^storage unavailable$'):
        with scope(engine,lock):
            if not commit_error:raise SQLAlchemyError('private database diagnostic')
    assert engine.events==['begin','rollback'] and lock.released==1

@pytest.mark.parametrize('preserve',[False,True])
def test_integrity_passthrough_is_explicit_per_domain(monkeypatch,preserve):
    engine=Engine();lock=Lock();error=IntegrityError('statement',{},Exception('private'))
    monkeypatch.setattr(db,'execute',lambda *args:None)
    with pytest.raises(IntegrityError if preserve else StorageUnavailable):
        with scope(engine,lock,passthrough=(IntegrityError,) if preserve else ()):
            raise error
    assert engine.events==['begin','rollback'] and lock.released==1

def test_domain_conflict_is_preserved_and_transaction_rolls_back(monkeypatch):
    engine=Engine();lock=Lock();error=ValueError('domain conflict')
    monkeypatch.setattr(db,'execute',lambda *args:None)
    with pytest.raises(ValueError) as caught:
        with scope(engine,lock):raise error
    assert caught.value is error and lock.released==1 and engine.events==['begin','rollback']
