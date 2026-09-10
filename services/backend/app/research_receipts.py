"""Finite research creation receipt bookkeeping (ADR-0062), never a write queue."""
from datetime import datetime, timedelta, timezone
import uuid

from .db import execute, fetch_one

DELAYS = (2, 5, 15, 60, 300, 900, 3600, 3600)
MAX_ATTEMPTS = 8
MAX_WATCHES = 64
SCHEMA_DDL = ["""CREATE TABLE IF NOT EXISTS research_receipt_watches (
    watch_id TEXT PRIMARY KEY, owner_principal TEXT NOT NULL, workspace_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL, session_id TEXT NOT NULL, trace_id TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('research_task','experiment','artifact')),
    parent_task_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('awaiting_receipt','confirmed','conflict','needs_attention')),
    entity_id TEXT, check_count INTEGER NOT NULL DEFAULT 0 CHECK (check_count BETWEEN 0 AND 8),
    reason TEXT NOT NULL DEFAULT 'awaiting_receipt',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deadline_at TIMESTAMPTZ NOT NULL DEFAULT (now()+interval '24 hours'),
    next_check_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_principal,workspace_id,entity_type,parent_task_id,idempotency_key)
)""", """CREATE INDEX IF NOT EXISTS research_receipt_watches_due
    ON research_receipt_watches(conversation_id,next_check_at,watch_id) WHERE state='awaiting_receipt'"""]


class ResearchReceiptMixin:
    @staticmethod
    def _receipt_conversation(connection, context, conversation_id=None):
        from .research import ResearchNotFound
        params = {'owner':context.get('owner_principal'), 'workspace':context.get('workspace_id')}
        where = 'c.conversation_id=:conversation' if conversation_id else 'c.runtime_session_id=:session'
        params.update(conversation=conversation_id, session=context.get('session_id'))
        row = fetch_one(connection, f"""SELECT c.* FROM product_conversations c
            JOIN users u ON u.username=c.owner_principal
            JOIN workspaces w ON w.workspace_id=c.workspace_id AND w.owner_user_id=u.user_id
            JOIN workspace_memberships m ON m.workspace_id=w.workspace_id AND m.user_id=u.user_id
            WHERE c.owner_principal=:owner AND c.workspace_id=:workspace AND {where}
              AND u.status='active' AND w.status='active' AND m.status='active' AND m.role='owner'
            FOR SHARE OF c,u,w,m""", params)
        if row is None or any(context.get(field) is not None and context[field] != row[column]
                              for field,column in (('session_id','runtime_session_id'),('trace_id','trace_id'))):
            raise ResearchNotFound('research receipt conversation not found')
        return row

    def _receipt_data(self, kind, payload):
        from .research import _hash_request, _lineage
        normalizers = {'research_task':self._task_payload, 'experiment':self._experiment_payload,
                       'artifact':self._artifact_payload}
        if not isinstance(kind, str) or kind not in normalizers:
            raise ValueError('unsupported research receipt type')
        data = normalizers[kind](payload)
        if kind == 'artifact':
            lineage = [{'kind':'research_task','id':data['task_id']}]
            if data['experiment_id'] is not None:
                lineage.append({'kind':'experiment','id':data['experiment_id']})
            data['lineage'], _ = _lineage(lineage + data['lineage'])
        return data, _hash_request(data)

    @staticmethod
    def _receipt_view(row):
        state, reason = row['state'], row['reason']
        if state == 'awaiting_receipt' and datetime.fromisoformat(row['deadline_at']) <= datetime.now(timezone.utc):
            state, reason = 'needs_attention', 'deadline_exhausted'
        return {'schema_version':'research-receipt-watch.v1','watch_id':row['watch_id'],
            'entity_type':row['entity_type'],'task_id':row['parent_task_id'] or None,
            'idempotency_key':row['idempotency_key'],'status':state,'reason':reason,
            'entity_id':row['entity_id'],'attempts':row['check_count'],'max_attempts':MAX_ATTEMPTS,
            'deadline_at':row['deadline_at'],'next_check_at':row['next_check_at'] if state=='awaiting_receipt' else None,
            'outcome':'confirmed' if state=='confirmed' else 'outcome_unknown'}

    def register_submission_watch(self, payload, *, trusted_context):
        from .research import IdempotencyConflict, ResearchNotFound
        if not isinstance(payload,dict) or set(payload) != {'entity_type','request'}:
            raise ValueError('exact research watch request required')
        kind = payload['entity_type']
        data, digest = self._receipt_data(kind,payload['request'])
        params = {'owner':trusted_context.get('owner_principal'),'workspace':trusted_context.get('workspace_id'),
            'kind':kind,'task':data.get('task_id',''),'key':data['idempotency_key'],'hash':digest}
        if data['trace_id'] != trusted_context.get('trace_id') or (kind=='research_task' and data['owner_principal']!=params['owner']):
            raise ValueError('research watch request identity mismatch')
        with self._transaction() as connection:
            conversation = self._receipt_conversation(connection,trusted_context)
            if conversation['status']!='active':
                raise ValueError('research watch conversation is inactive')
            params['conversation'] = conversation['conversation_id']
            execute(connection, 'SELECT pg_advisory_xact_lock(hashtext(:scope))',
                    {'scope':'research-watches|'+params['owner']+'|'+params['workspace']})
            if kind != 'research_task' and fetch_one(connection,"""SELECT task_id FROM research_tasks
                WHERE task_id=:task AND owner_principal=:owner AND workspace_id=:workspace""",params) is None:
                raise ResearchNotFound('research receipt parent not found')
            old = fetch_one(connection,"""SELECT * FROM research_receipt_watches WHERE owner_principal=:owner
                AND workspace_id=:workspace AND entity_type=:kind AND parent_task_id=:task AND idempotency_key=:key""",params)
            if old is not None:
                if old['request_hash'] != digest or old['conversation_id'] != conversation['conversation_id']:
                    raise IdempotencyConflict('research receipt identity cannot change')
                return {**self._receipt_view(old),'registration_created':False}
            count = fetch_one(connection,'SELECT count(*) AS n FROM research_receipt_watches WHERE conversation_id=:conversation',params)
            if count['n']>=MAX_WATCHES:
                raise IdempotencyConflict('research receipt conversation capacity exhausted')
            row = fetch_one(connection,"""INSERT INTO research_receipt_watches
                (watch_id,owner_principal,workspace_id,conversation_id,session_id,trace_id,entity_type,
                 parent_task_id,idempotency_key,request_hash,state)
                VALUES (:id,:owner,:workspace,:conversation,:session,:trace,:kind,:task,:key,:hash,'awaiting_receipt')
                RETURNING *""",{**params,'id':'researchwatch_'+uuid.uuid4().hex,
                    'session':conversation['runtime_session_id'],'trace':conversation['trace_id']})
            # Check even legacy creations before granting this caller the one
            # initial POST. This lookup is charged just like later lookups.
            execute(connection,"SET LOCAL statement_timeout='1000ms'")
            receipt = self._watched_submission_query(connection,row)
            state, reason, entity = self._matched_receipt(row,receipt)
            row = fetch_one(connection,"""UPDATE research_receipt_watches SET state=:state,reason=:reason,
                entity_id=:entity,check_count=1,next_check_at=now()+interval '2 seconds' WHERE watch_id=:id RETURNING *""",
                {'id':row['watch_id'],'state':state,'reason':reason,'entity':entity})
            return {**self._receipt_view(row),'registration_created':True}

    def get_submission_watch(self, watch_id, *, trusted_context):
        from .research import ResearchNotFound
        with self._transaction() as connection:
            row = fetch_one(connection,"""SELECT * FROM research_receipt_watches WHERE watch_id=:id
                AND owner_principal=:owner AND workspace_id=:workspace""",{'id':watch_id,
                'owner':trusted_context.get('owner_principal'),'workspace':trusted_context.get('workspace_id')})
            if row is None:
                raise ResearchNotFound('research receipt not found')
            self._receipt_conversation(connection,trusted_context,row['conversation_id'])
            return self._receipt_view(row)

    def list_submission_watches(self, conversation_id, *, trusted_context):
        with self._transaction() as connection:
            self._receipt_conversation(connection,trusted_context,conversation_id)
            rows = execute(connection,"""SELECT * FROM research_receipt_watches WHERE conversation_id=:conversation
                AND owner_principal=:owner AND workspace_id=:workspace ORDER BY created_at,watch_id LIMIT 64""",
                {'conversation':conversation_id,'owner':trusted_context['owner_principal'],'workspace':trusted_context['workspace_id']})
            return {'schema_version':'research-receipt-list.v1','conversation_id':conversation_id,
                    'receipts':[self._receipt_view(row) for row in rows]}

    @staticmethod
    def _watched_submission_query(connection,row):
        tables = {'research_task':('research_tasks','task_id'),'experiment':('experiments','experiment_id'),
                  'artifact':('artifacts','artifact_id')}
        table, column = tables[row['entity_type']]
        parent = '' if row['entity_type']=='research_task' else ' AND task_id=:task'
        conversation = ',conversation_id' if row['entity_type']=='research_task' else ''
        return fetch_one(connection,f"""SELECT {column} AS entity_id,request_hash{conversation} FROM {table}
            WHERE owner_principal=:owner AND workspace_id=:workspace AND idempotency_key=:key{parent}""",
            {'owner':row['owner_principal'],'workspace':row['workspace_id'],
             'key':row['idempotency_key'],'task':row['parent_task_id']})

    def _find_watched_submission(self, row):
        with self._transaction() as connection:
            execute(connection,"SET LOCAL statement_timeout='1000ms'")
            self._receipt_conversation(connection,{'owner_principal':row['owner_principal'],
                'workspace_id':row['workspace_id'],'session_id':row['session_id'],'trace_id':row['trace_id']},row['conversation_id'])
            return self._watched_submission_query(connection,row)

    @staticmethod
    def _matched_receipt(row,receipt):
        if receipt is None:
            return 'awaiting_receipt','awaiting_receipt',None
        matches = receipt['request_hash']==row['request_hash'] and (
            row['entity_type']!='research_task' or receipt['conversation_id']==row['conversation_id'])
        return ('confirmed','receipt_confirmed',receipt['entity_id']) if matches else ('conflict','identity_conflict',None)

    def consume_submission_watches(self, conversation_id, *, trusted_context):
        # Charge and commit before the lookup: crashes/query failures cannot
        # roll back the finite budget. Attempt-number fencing rejects late ACKs.
        claimed = []
        with self._transaction() as connection:
            conversation = self._receipt_conversation(connection,trusted_context,conversation_id)
            now = datetime.fromisoformat(fetch_one(connection,'SELECT now() AS at')['at'])
            rows = execute(connection,"""SELECT * FROM research_receipt_watches WHERE conversation_id=:conversation
                AND owner_principal=:owner AND workspace_id=:workspace AND state='awaiting_receipt'
                AND next_check_at<=now() ORDER BY next_check_at,watch_id LIMIT 4 FOR UPDATE SKIP LOCKED""",
                {'conversation':conversation_id,'owner':trusted_context['owner_principal'],'workspace':trusted_context['workspace_id']})
            for row in rows:
                reason = ('conversation_inactive' if conversation['status']!='active' else
                    'deadline_exhausted' if now>=datetime.fromisoformat(row['deadline_at']) else
                    'attempts_exhausted' if row['check_count']>=MAX_ATTEMPTS else None)
                if reason:
                    execute(connection,"UPDATE research_receipt_watches SET state='needs_attention',reason=:reason,updated_at=now() WHERE watch_id=:id",
                            {'id':row['watch_id'],'reason':reason})
                    continue
                row['check_count'] += 1
                execute(connection,"""UPDATE research_receipt_watches SET check_count=:attempts,next_check_at=:next,
                    updated_at=now() WHERE watch_id=:id""", {'id':row['watch_id'],'attempts':row['check_count'],
                        'next':(now+timedelta(seconds=DELAYS[row['check_count']-1])).isoformat()})
                claimed.append(row)
        for row in claimed:
            state, reason, entity_id = 'awaiting_receipt','awaiting_receipt',None
            try:
                receipt = self._find_watched_submission(row)
                state, reason, entity_id = self._matched_receipt(row,receipt)
            except Exception:
                # No raw DB/transport diagnostic enters the Product projection.
                reason = 'query_unavailable'
            if state=='awaiting_receipt' and row['check_count']>=MAX_ATTEMPTS:
                state, reason = 'needs_attention','attempts_exhausted'
            self._execute("""UPDATE research_receipt_watches SET state=:state,reason=:reason,entity_id=:entity,updated_at=now()
                WHERE watch_id=:id AND check_count=:attempts AND state='awaiting_receipt'""",
                {'id':row['watch_id'],'attempts':row['check_count'],'state':state,'reason':reason,'entity':entity_id})
        return len(claimed)
