"""Bounded seven-day personal archive expiry; no Agent dispatch or restore."""
from __future__ import annotations

import hashlib
import logging
import os
import stat
import time
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .db import execute
from .workspace_reset_gc import _validated_reference, _LIVE_REFERENCE_SQL

logger = logging.getLogger('byq.workspace.reset_retention')
BATCH_SIZE = 32
POLL_SECONDS = 3600
MAX_GC_SECONDS = 5
MAX_GC_BYTES = 64 * 1024 * 1024
MAX_OBJECT_BYTES = 32 * 1024 * 1024
_OBJECT_WRITERS = ('backtest_jobs','ml_training_runs','ml_prediction_runs','optimization_jobs')


def expire_archives(connection) -> dict[str,int]:
    """Expiry deletes user payload and queues only exact CAS references atomically."""
    rows = connection.execute(text('''SELECT reset_id,object_references_json FROM workspace_reset_archives
      WHERE expires_at<=now() ORDER BY expires_at,reset_id LIMIT :batch FOR UPDATE SKIP LOCKED'''),
      {'batch':BATCH_SIZE}).mappings().all()
    for row in rows:
        for ref in row['object_references_json']:
            namespace,object_id=_validated_reference(ref)
            execute(connection,'''INSERT INTO workspace_reset_expired_objects(namespace,object_id,reference_json)
              VALUES (:namespace,:object_id,CAST(:ref AS jsonb)) ON CONFLICT(namespace,object_id) DO NOTHING''',
              {'namespace':namespace,'object_id':object_id,'ref':ref})
        execute(connection,'DELETE FROM workspace_reset_archives WHERE reset_id=:id',{'id':row['reset_id']})
    # Earlier specialized archives remain single authority for their earlier
    # facts and expire from their original reset time, never renewed by reset.
    older = connection.execute(text('''SELECT source_artifact_id,approval_snapshot,strategy_version_snapshot
      FROM strategy_approval_fact_archive WHERE reset_at+interval '7 days'<=now()
      ORDER BY reset_at,source_artifact_id LIMIT :batch FOR UPDATE SKIP LOCKED'''),{'batch':BATCH_SIZE}).mappings().all()
    for row in older:
        for snapshot in (row['approval_snapshot'],row['strategy_version_snapshot']):
            for key in ('object_reference','result_reference'):
                ref=snapshot.get('content',{}).get(key)
                if ref is not None:
                    namespace,object_id=_validated_reference(ref)
                    execute(connection,'''INSERT INTO workspace_reset_expired_objects(namespace,object_id,reference_json)
                      VALUES (:namespace,:object_id,CAST(:ref AS jsonb)) ON CONFLICT(namespace,object_id) DO NOTHING''',
                      {'namespace':namespace,'object_id':object_id,'ref':ref})
        execute(connection,'DELETE FROM strategy_approval_fact_archive WHERE source_artifact_id=:id',{'id':row['source_artifact_id']})
    return {'expired_archives':len(rows),'expired_earlier_approval_facts':len(older)}


def collect_expired_objects(connection, *, backtest_root: str | Path, ml_root: str | Path) -> dict[str,int]:
    """Delete queued expired blobs only with no active producer and full refs.

    SHARE locks drain commits and block new claims/Artifact/Job/archive writes
    through the bounded collection. Any nonterminal producer defers all unlinks.
    No namespace/global sweep, other-user deletion, or fixed Worker stop.
    """
    tables=(*_OBJECT_WRITERS,'artifacts','workspace_reset_archives','strategy_approval_fact_archive')
    connection.execute(text('LOCK TABLE '+','.join(tables)+' IN SHARE MODE'))
    for table in _OBJECT_WRITERS:
        if connection.execute(text(f"SELECT 1 FROM {table} WHERE status NOT IN ('completed','failed','cancelled') LIMIT 1")).first():
            return {'deleted_objects':0,'deferred_for_producer':1}
    sql = _LIVE_REFERENCE_SQL + '''
      UNION ALL SELECT value AS reference FROM workspace_reset_archives,
        jsonb_array_elements(object_references_json)
      UNION ALL SELECT strategy_version_snapshot->'content'->'object_reference' AS reference
        FROM strategy_approval_fact_archive
        WHERE strategy_version_snapshot->'content' ? 'object_reference'
      UNION ALL SELECT strategy_version_snapshot->'content'->'result_reference' AS reference
        FROM strategy_approval_fact_archive
        WHERE strategy_version_snapshot->'content' ? 'result_reference'
    '''
    live={_validated_reference(r) for r in connection.execute(text(sql)).scalars()}
    queue=connection.execute(text('''SELECT namespace,object_id,reference_json FROM workspace_reset_expired_objects
       ORDER BY namespace,object_id LIMIT :batch FOR UPDATE SKIP LOCKED'''),{'batch':BATCH_SIZE}).mappings().all()
    roots={'backtest-results':Path(backtest_root),'ml-features':Path(ml_root),'ml-models':Path(ml_root)}
    deleted=0; scanned_bytes=0; deadline=time.monotonic()+MAX_GC_SECONDS
    for row in queue:
        if time.monotonic()>=deadline: break
        namespace,object_id=_validated_reference(row['reference_json']); key=(namespace,object_id)
        if key not in live:
            root=roots[namespace]; directory=root/namespace; path=directory/object_id
            try:
                # A missing root in this deployment is deferred, never treated
                # as proof that a blob in another mount was deleted.
                try:
                    root_mode=root.lstat().st_mode;directory_mode=directory.lstat().st_mode
                except FileNotFoundError:
                    continue
                if not stat.S_ISDIR(root_mode) or not stat.S_ISDIR(directory_mode): continue
                try: mode=path.lstat().st_mode
                except FileNotFoundError: mode=None
                if mode is not None:
                    if not stat.S_ISREG(mode): continue
                    size=path.stat().st_size
                    if size!=row['reference_json']['size'] or size>MAX_OBJECT_BYTES: continue
                    if scanned_bytes+size>MAX_GC_BYTES: break
                    digest=hashlib.sha256(); complete=True
                    with path.open('rb') as handle:
                        while True:
                            if time.monotonic()>=deadline:
                                complete=False;break
                            chunk=handle.read(1024*1024)
                            if not chunk:break
                            scanned_bytes+=len(chunk);digest.update(chunk)
                    if not complete or digest.hexdigest()!=object_id: continue
                    # Immutable CAS producers are quiescent under the table
                    # locks; recheck type/size immediately before unlink.
                    if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size!=size:continue
                    path.unlink();deleted+=1
            except OSError:
                continue
        execute(connection,'''DELETE FROM workspace_reset_expired_objects WHERE namespace=:namespace AND object_id=:id''',
                {'namespace':namespace,'id':object_id})
    return {'deleted_objects':deleted,'deferred_for_producer':0}


def retention_cycle(engine, *, backtest_root: str | Path, ml_root: str | Path) -> dict[str,int]:
    with engine.begin() as connection:
        execute(connection,"SET LOCAL lock_timeout='2s'");execute(connection,"SET LOCAL statement_timeout='30s'")
        result=expire_archives(connection)
    # Filesystem cleanup is retryable and separate from archival payload expiry.
    with engine.begin() as connection:
        execute(connection,"SET LOCAL lock_timeout='2s'");execute(connection,"SET LOCAL statement_timeout='30s'")
        result.update(collect_expired_objects(connection,backtest_root=backtest_root,ml_root=ml_root))
    return result


@asynccontextmanager
async def retention_lifespan(app):
    async def maintain():
        while True:
            try:
                def cycle():
                    from . import main
                    return retention_cycle(main.workspace_runtime_reset_store.engine,
                      backtest_root=os.getenv('BYQ_BACKTEST_OBJECT_ROOT','/var/lib/byq/domain/backtest-objects'),
                      ml_root=os.getenv('BYQ_ML_OBJECT_ROOT','/var/lib/byq/ml-objects'))
                await anyio.to_thread.run_sync(cycle)
            except (SQLAlchemyError, ValueError, RuntimeError):
                # Safe category only; no SQL, snapshots or credential output.
                logger.warning('personal reset retention cycle deferred')
            await anyio.sleep(POLL_SECONDS)
    async with anyio.create_task_group() as group:
        group.start_soon(maintain)
        try: yield
        finally: group.cancel_scope.cancel()
