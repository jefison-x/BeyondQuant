"""BYQ task-scoped human permission ledger; no model dispatch capability."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
import os
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

from .db import execute, fetch_one
from .research_handoff_events import handoff_events, handoff_ready
from packages.contracts import business_recovery as recovery_contract

logger = logging.getLogger("byq.research.continuation")

# Data-ready continuations reuse the task-bound budget ledger, dispatch and
# MCP-admission seam. One produced signal snapshot wakes one bounded
# tool-calling turn: the first model call returns tool calls, and the next call
# resumes after the tools ran, so the reservation must cover several model
# calls. It never requires an inferred user token grant. The per-call input
# ceiling, per-call output bound and max call count are the single source of
# truth mirrored by the exported DATA_READY_* constants in
# plugins/dsh-byq/runtime/byq-continuation-budget.js; the guard charges each call
# `DATA_READY_INPUT_CEILING + options.maxTokens`, so the total budget is the max
# call count times the conservative per-call ceiling. The cross-component drift
# assertion lives in tests/architecture/test_architecture.py.
DATA_READY_EVENT_PREFIX = "ready-v1:"
DATA_READY_INPUT_CEILING = 1048576
DATA_READY_MAX_OUTPUT_TOKENS = 8192
DATA_READY_MAX_CALLS = 8
DATA_READY_TOKEN_LIMIT = DATA_READY_MAX_CALLS * (DATA_READY_INPUT_CEILING + DATA_READY_MAX_OUTPUT_TOKENS)
DATA_READY_MAX_TURNS = 8
DATA_READY_TURN_TIMEOUT_SECONDS = 900
# A deliberate task-wide needs_attention block (``block_continuation``) records
# this sentinel. A concrete ``ready-v1:``/other key scopes the block to that one
# event; a NULL key is a legacy pre-scoping row whose event is recovered from
# the settled ledger.
TASK_WIDE_BLOCK_EVENT_KEY = '*'


def _event_key(event: dict) -> str:
    """Deterministic at-most-once identity for a domain continuation event."""
    digest = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
    if event.get('data_ready'):
        return DATA_READY_EVENT_PREFIX + digest
    if event.get('kind') in {'permission_handoff', 'approval_handoff'}:
        return 'handoff-v1:' + digest
    return digest


def _positive(value: object, name: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"invalid {name}")
    return value


def _request(payload: object) -> dict:
    required = {"idempotency_key", "token_limit", "confirmed_artifact_ids"}
    optional = {"max_turns", "valid_seconds", "turn_timeout_seconds"}
    if not isinstance(payload, dict) or not required <= payload.keys() or payload.keys() - required - optional:
        raise ValueError("invalid continuation permission fields")
    key = payload["idempotency_key"]
    if not isinstance(key, str) or not key.strip() or len(key) > 128:
        raise ValueError("invalid continuation idempotency key")
    artifacts = payload["confirmed_artifact_ids"]
    if (not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 16
            or any(not isinstance(item, str) or len(item) > 64 for item in artifacts)
            or len(set(artifacts)) != len(artifacts)):
        raise ValueError("explicit artifact confirmation required")
    return {"idempotency_key": key, "confirmed_artifact_ids": sorted(artifacts),
            "token_limit": _positive(payload["token_limit"], "token limit", 2**53 - 1),
            "max_turns": _positive(payload.get("max_turns", 8), "turn limit", 8),
            "valid_seconds": _positive(payload.get("valid_seconds", 86400), "validity", 86400),
            "turn_timeout_seconds": _positive(payload.get("turn_timeout_seconds", payload.get("valid_seconds", 86400)), "turn timeout", 86400)}


class ResearchContinuationMixin:
    """Stored on the original task row, serialized with task transitions.

    One immutable grant per task; enforcement must qualify before dispatch.
    Grants cannot be renewed or replenished, including after unknown outcomes.
    """

    @staticmethod
    def _continuation_task(connection, task_id: str, context: dict, *, human: bool):
        owner, workspace = context.get("owner_principal"), context.get("workspace_id")
        if not owner or not workspace or (human and context.get("actor_principal") != owner):
            raise ValueError("continuation requires its authenticated human owner")
        identity = fetch_one(connection, """SELECT u.user_id FROM users u
            JOIN workspaces w ON w.owner_user_id = u.user_id
            JOIN workspace_memberships m ON m.workspace_id = w.workspace_id AND m.user_id = u.user_id
            WHERE u.username = :owner AND w.workspace_id = :workspace
              AND u.status = 'active' AND w.status = 'active' AND m.status = 'active' AND m.role = 'owner'
            FOR SHARE OF u, w, m""", {"owner": owner, "workspace": workspace})
        if identity is None:
            raise ValueError("continuation owner is unavailable")
        # Lock conversation before task, matching research task creation.
        conversation = fetch_one(connection, """SELECT c.* FROM product_conversations c
            JOIN research_tasks t ON t.conversation_id = c.conversation_id
            WHERE t.task_id = :task AND t.owner_principal = :owner AND t.workspace_id = :workspace
              AND c.owner_principal = :owner AND c.workspace_id = :workspace
            FOR SHARE OF c""", {"task": task_id, "owner": owner, "workspace": workspace})
        if conversation is None:
            raise ValueError("continuation requires the original bound conversation")
        task = fetch_one(connection, """SELECT * FROM research_tasks WHERE task_id = :task
            AND owner_principal = :owner AND workspace_id = :workspace FOR UPDATE""",
            {"task": task_id, "owner": owner, "workspace": workspace})
        if task is None or task["conversation_id"] != conversation["conversation_id"]:
            raise ValueError("continuation task binding changed")
        return task, conversation

    @staticmethod
    def _permission_blocked_reason(task, conversation):
        ledger = task.get("continuation_permission")
        if ledger is None:
            return 'permission_missing'
        if ledger['revoked_at'] is not None:
            return 'permission_revoked'
        if task['status'] in {'completed', 'cancelled', 'failed'}:
            return 'task_terminal'
        if conversation['status'] != 'active':
            return 'conversation_inactive'
        if datetime.fromisoformat(ledger['expires_at']) <= datetime.now(timezone.utc):
            return 'permission_expired'
        return None

    @staticmethod
    def _data_ready_blocked_reason(task, conversation):
        """Data-ready turns are bounded by task/conversation lifecycle only.

        They never authorize a domain action; every next action still needs its
        own approval, and the reservation carries no inferred user token grant.
        """
        if task['status'] in {'completed', 'cancelled', 'failed'}:
            return 'task_terminal'
        if conversation['status'] != 'active':
            return 'conversation_inactive'
        return None

    @staticmethod
    def _event_blocked_by_needs_attention(task, event_key: str) -> bool:
        """Whether a settled needs_attention block still governs this event.

        The block is event-scoped: a task with a recorded blocked event only
        withholds that exact event, so a new distinct data-ready event re-arms
        automatic continuation. An explicit task-wide block
        (``TASK_WIDE_BLOCK_EVENT_KEY``) governs every event. A NULL key is a
        legacy row written before the block was event-scoped, so the offending
        event is recovered from the most recent settled ``needs_attention``
        reservation; without such durable evidence the block stays task-wide.
        At-most-once is separately guaranteed by the settled ledger row, so an
        absent blocked event never permits a duplicate of the same event.
        """
        if task.get('continuation_blocked_reason') != 'continuation_needs_attention':
            return False
        blocked = task.get('continuation_blocked_event_key')
        if blocked == TASK_WIDE_BLOCK_EVENT_KEY:
            return True
        if blocked is None:
            settled = [row for row in (task.get('continuation_budget') or [])
                if row.get('status') == 'settled' and row.get('outcome') == 'needs_attention']
            if settled:
                blocked = settled[-1]['event_key']
        return blocked is None or blocked == event_key

    @staticmethod
    def _continuation_blocked_reason(task, conversation, receipt=None):
        """Single admission gate for both budgeted and data-ready receipts."""
        if receipt is not None and receipt.get('grant_kind') == 'data_ready':
            reason = ResearchContinuationMixin._data_ready_blocked_reason(task, conversation)
            if reason is not None:
                return reason
            if datetime.fromisoformat(receipt['expires_at']) <= datetime.now(timezone.utc):
                return 'permission_expired'
            return None
        return ResearchContinuationMixin._permission_blocked_reason(task, conversation)

    @staticmethod
    def _continuation_view(task, conversation):
        ledger = task.get("continuation_permission")
        if ledger is None:
            return {"schema_version": "task-continuation-permission.v1", "task_id": task["task_id"],
                    "permission": None, "can_start": False, "blocked_reason": "permission_missing"}
        public = {key: value for key, value in ledger.items() if key not in {"idempotency_key", "request_sha256", "handoff_version"}}
        rows = task.get('continuation_budget') or []
        reserved = sum(row['token_limit'] for row in rows if row['status'] != 'settled')
        charged = sum(row['charged_tokens'] for row in rows if row['status'] == 'settled')
        budget = {'token_limit': ledger['token_limit'], 'reserved_tokens': reserved,
            'charged_tokens': charged, 'available_tokens': ledger['token_limit'] - reserved - charged,
            'turns_reserved': len(rows), 'turns_remaining': ledger['max_turns'] - len(rows),
            'unconfirmed_reservations': sum(row['status'] != 'settled' for row in rows)}
        reason = ResearchContinuationMixin._permission_blocked_reason(task, conversation)
        if reason is None:
            if budget['unconfirmed_reservations']:
                reason = 'continuation_result_unconfirmed'
            elif os.environ.get('BYQ_F6_EXECUTOR_ENABLED') != '1':
                reason = 'budget_enforcement_unqualified'
            elif budget['turns_remaining'] == 0 or budget['available_tokens'] < 1048576 + 8192:
                reason = 'budget_exhausted'
            else:
                reason = task.get('continuation_blocked_reason') or 'waiting_for_event'
        return {"schema_version": "task-continuation-permission.v1", "task_id": task["task_id"],
                "permission": public, "budget": budget, "can_start": False, "blocked_reason": reason}

    def create_continuation_permission(self, task_id: str, payload: object, *, trusted_context: dict) -> dict:
        from .research import IdempotencyConflict

        request = _request(payload)
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self._transaction() as connection:
            task, conversation = self._continuation_task(connection, task_id, trusted_context, human=True)
            existing = task.get("continuation_permission")
            if existing is not None:
                # Replaying an old implicit default must not extend its grant.
                if 'turn_timeout_seconds' not in payload:
                    request['turn_timeout_seconds'] = existing['turn_timeout_seconds']
                    digest = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                if existing["idempotency_key"] != request["idempotency_key"] or existing["request_sha256"] != digest:
                    raise IdempotencyConflict("continuation permission cannot be replaced or replenished")
                return self._continuation_view(task, conversation)
            if task["status"] not in {"planned", "running"} or conversation["status"] != "active":
                raise ValueError("continuation task or conversation is inactive")
            confirmed_artifacts = []
            for artifact_id in request["confirmed_artifact_ids"]:
                artifact = fetch_one(connection, """SELECT artifact_id, content_sha256 FROM artifacts
                    WHERE artifact_id = :artifact AND task_id = :task AND owner_principal = :owner
                      AND workspace_id = :workspace AND status = 'validated' FOR SHARE""",
                    {"artifact": artifact_id, "task": task_id, "owner": task["owner_principal"],
                     "workspace": task["workspace_id"]})
                if artifact is None:
                    raise ValueError("confirmed artifact must be validated and belong to the exact task")
                confirmed_artifacts.append(artifact)
            now = datetime.now(timezone.utc)
            ledger = {**request, "request_sha256": digest, "grant_version": 1,
                      "confirmed_artifacts": confirmed_artifacts, "handoff_version": 1,
                      "owner_principal": task["owner_principal"], "workspace_id": task["workspace_id"],
                      "conversation_id": task["conversation_id"], "confirmed_by": trusted_context["actor_principal"],
                      "created_at": now.isoformat(), "expires_at": (now + timedelta(seconds=request["valid_seconds"])).isoformat(),
                      "revoked_at": None, "revoked_by": None}
            execute(connection, """UPDATE research_tasks SET continuation_permission = :ledger
                WHERE task_id = :task""", {"ledger": ledger, "task": task_id})
            task["continuation_permission"] = ledger
            return self._continuation_view(task, conversation)

    def get_continuation_permission(self, task_id: str, *, trusted_context: dict) -> dict:
        with self._transaction() as connection:
            task, conversation = self._continuation_task(connection, task_id, trusted_context, human=True)
            return self._continuation_view(task, conversation)

    def revoke_continuation_permission(self, task_id: str, *, grant_version: int, trusted_context: dict) -> dict:
        _positive(grant_version, "grant version", 2**53 - 1)
        with self._transaction() as connection:
            task, conversation = self._continuation_task(connection, task_id, trusted_context, human=True)
            ledger = task.get("continuation_permission")
            if ledger is None or ledger["grant_version"] != grant_version:
                raise ValueError("exact continuation grant version required")
            if ledger["revoked_at"] is None:
                ledger = {**ledger, "revoked_at": datetime.now(timezone.utc).isoformat(),
                          "revoked_by": trusted_context["actor_principal"]}
                execute(connection, "UPDATE research_tasks SET continuation_permission = :ledger WHERE task_id = :task",
                        {"ledger": ledger, "task": task_id})
                task["continuation_permission"] = ledger
            return self._continuation_view(task, conversation)

    def reserve_continuation_budget(self, task_id: str, *, trusted_context: dict,
            grant_version: int, event_key: str, input_sha256: str, token_limit: int,
            instruction: str | None = None, _connection=None) -> dict:
        """Reserve only; no dispatch or externally callable qualification switch.

        A future trusted consumer must validate the domain event and executor
        qualification before calling this accounting primitive. No public/MCP
        endpoint exposes it and a reservation is not action authorization.
        """
        from .research import IdempotencyConflict
        _positive(grant_version, 'grant version', 2**53 - 1)
        _positive(token_limit, 'reservation token limit', 2**53 - 1)
        if not isinstance(event_key, str) or not 8 <= len(event_key) <= 160:
            raise ValueError('invalid continuation event identity')
        if not isinstance(input_sha256, str) or re.fullmatch(r'[0-9a-f]{64}', input_sha256) is None:
            raise ValueError('invalid continuation input digest')
        if instruction is not None and (not isinstance(instruction, str) or len(instruction) > 8000
                or hashlib.sha256(instruction.encode()).hexdigest() != input_sha256):
            raise ValueError('continuation instruction digest mismatch')
        with self._transaction() if _connection is None else nullcontext(_connection) as connection:
            task, conversation = self._continuation_task(connection, task_id, trusted_context, human=False)
            permission = task.get('continuation_permission')
            if permission is None or permission['grant_version'] != grant_version:
                raise ValueError('exact continuation permission required')
            rows = task.get('continuation_budget') or []
            for row in rows:
                if row['event_key'] == event_key:
                    if (row['input_sha256'], row['token_limit'], row['grant_version']) != (
                            input_sha256, token_limit, grant_version):
                        raise IdempotencyConflict('continuation event input conflicts')
                    return row
            if self._permission_blocked_reason(task, conversation) is not None:
                raise ValueError('continuation permission is inactive')
            for confirmed in permission['confirmed_artifacts']:
                artifact = fetch_one(connection, '''SELECT artifact_id FROM artifacts
                    WHERE artifact_id=:artifact AND task_id=:task AND owner_principal=:owner
                      AND workspace_id=:workspace AND status='validated' AND content_sha256=:digest
                    FOR SHARE''', {'artifact': confirmed['artifact_id'], 'task': task_id,
                    'owner': task['owner_principal'], 'workspace': task['workspace_id'],
                    'digest': confirmed['content_sha256']})
                if artifact is None:
                    raise ValueError('confirmed continuation artifact is unavailable')
            if any(row['status'] != 'settled' for row in rows):
                raise ValueError('previous continuation result is unconfirmed')
            spent = sum(row['charged_tokens'] for row in rows)
            if len(rows) >= permission['max_turns'] or token_limit > permission['token_limit'] - spent:
                raise ValueError('continuation budget exhausted')
            now = datetime.now(timezone.utc)
            receipt = {'reservation_id': 'continuation_' + uuid.uuid4().hex,
                'grant_version': grant_version, 'event_key': event_key, 'input_sha256': input_sha256,
                'token_limit': token_limit, 'status': 'reserved', 'run_id': None,
                'charged_tokens': None, 'settlement_sha256': None, 'created_at': now.isoformat(),
                'instruction': instruction,
                'dispatch_attempts': 0, 'next_attempt_at': now.isoformat(),
                'expires_at': min(datetime.fromisoformat(permission['expires_at']),
                    now + timedelta(seconds=permission['turn_timeout_seconds'])).isoformat()}
            if task.get('continuation_blocked_reason') is not None:
                logger.info('continuation re-armed on reservation: task=%s reason=%s blocked_event=%s event=%s reservation=%s',
                    task_id, task.get('continuation_blocked_reason'), task.get('continuation_blocked_event_key'),
                    event_key, receipt['reservation_id'])
            execute(connection, 'UPDATE research_tasks SET continuation_budget = :budget, continuation_blocked_reason=NULL, continuation_blocked_event_key=NULL WHERE task_id = :task',
                {'budget': [*rows, receipt], 'task': task_id})
            return receipt

    def reserve_data_ready_budget(self, task_id: str, *, trusted_context: dict,
            event_key: str, input_sha256: str, instruction: str | None = None,
            _connection=None) -> dict:
        """Reserve one bounded data-ready turn without an inferred token grant.

        This is only reachable from the closed task-bound scan below, after a
        validated signal snapshot exists. It authorizes no domain action; the
        normal MCP admission and per-action approvals still apply.
        """
        from .research import IdempotencyConflict
        if not isinstance(event_key, str) or not event_key.startswith(DATA_READY_EVENT_PREFIX):
            raise ValueError('invalid data-ready event identity')
        if not isinstance(input_sha256, str) or re.fullmatch(r'[0-9a-f]{64}', input_sha256) is None:
            raise ValueError('invalid continuation input digest')
        if instruction is not None and (not isinstance(instruction, str) or len(instruction) > 8000
                or hashlib.sha256(instruction.encode()).hexdigest() != input_sha256):
            raise ValueError('continuation instruction digest mismatch')
        with self._transaction() if _connection is None else nullcontext(_connection) as connection:
            task, conversation = self._continuation_task(connection, task_id, trusted_context, human=False)
            rows = task.get('continuation_budget') or []
            for row in rows:
                if row['event_key'] == event_key:
                    if (row['input_sha256'], row['token_limit'], row.get('grant_kind')) != (
                            input_sha256, DATA_READY_TOKEN_LIMIT, 'data_ready'):
                        raise IdempotencyConflict('continuation event input conflicts')
                    return row
            if self._data_ready_blocked_reason(task, conversation) is not None:
                raise ValueError('data-ready continuation is inactive')
            if any(row['status'] != 'settled' for row in rows):
                raise ValueError('previous continuation result is unconfirmed')
            if len(rows) >= DATA_READY_MAX_TURNS:
                raise ValueError('continuation budget exhausted')
            now = datetime.now(timezone.utc)
            receipt = {'reservation_id': 'continuation_' + uuid.uuid4().hex,
                'grant_kind': 'data_ready', 'grant_version': None, 'event_key': event_key,
                'input_sha256': input_sha256, 'token_limit': DATA_READY_TOKEN_LIMIT,
                'status': 'reserved', 'run_id': None, 'charged_tokens': None,
                'settlement_sha256': None, 'created_at': now.isoformat(), 'instruction': instruction,
                'dispatch_attempts': 0, 'next_attempt_at': now.isoformat(),
                'expires_at': (now + timedelta(seconds=DATA_READY_TURN_TIMEOUT_SECONDS)).isoformat()}
            if task.get('continuation_blocked_reason') is not None:
                logger.info('continuation re-armed on reservation: task=%s reason=%s blocked_event=%s event=%s reservation=%s',
                    task_id, task.get('continuation_blocked_reason'), task.get('continuation_blocked_event_key'),
                    event_key, receipt['reservation_id'])
            execute(connection, 'UPDATE research_tasks SET continuation_budget = :budget, continuation_blocked_reason=NULL, continuation_blocked_event_key=NULL WHERE task_id = :task',
                {'budget': [*rows, receipt], 'task': task_id})
            logger.info("data-ready continuation enqueued: task=%s event=%s reservation=%s",
                task_id, event_key, receipt['reservation_id'])
            return receipt

    def claim_conversation_continuation(self, conversation_id: str, *, trusted_context: dict, admit: bool = True) -> dict:
        """Project durable terminal domain rows into one original-task intent.

        Only this closed domain scan supplies the executor consumer; it never
        uses workspace-wide newest objects or default page absence as proof.
        """
        if os.environ.get('BYQ_F6_EXECUTOR_ENABLED') != '1':
            return {'status': 'blocked', 'reason': 'budget_enforcement_unqualified'}
        owner, workspace = trusted_context.get('owner_principal'), trusted_context.get('workspace_id')
        with self._transaction() as connection:
            tasks = execute(connection, '''SELECT t.task_id FROM research_tasks t
                WHERE t.conversation_id=:conversation AND t.owner_principal=:owner AND t.workspace_id=:workspace
                  AND (t.continuation_permission IS NOT NULL OR EXISTS (
                        SELECT 1 FROM signal_producer_jobs j JOIN artifacts a ON a.artifact_id=j.result_artifact_id
                        WHERE j.task_id=t.task_id AND j.owner_principal=:owner AND j.workspace_id=:workspace
                          AND j.status='completed' AND a.task_id=j.task_id
                          AND a.owner_principal=j.owner_principal AND a.workspace_id=j.workspace_id
                          AND a.kind='signal_snapshot' AND a.status='validated'))
                ORDER BY EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(t.continuation_budget, '[]'::jsonb)) r WHERE r->>'status' != 'settled') DESC, t.continuation_checked_at NULLS FIRST,t.task_id LIMIT 64''',
                {'conversation': conversation_id, 'owner': owner, 'workspace': workspace})
            for selected in tasks:
                task, conversation = self._continuation_task(connection, selected['task_id'], trusted_context, human=False)
                execute(connection, 'UPDATE research_tasks SET continuation_checked_at=now() WHERE task_id=:task',
                    {'task': task['task_id']})
                permission = task.get('continuation_permission')
                ledger = task.get('continuation_budget') or []
                pending = next((r for r in ledger if r['status'] != 'settled' and r.get('instruction')), None)
                if pending is not None:
                    if (pending['status'] == 'reserved' and pending['event_key'].startswith('handoff-v1:')
                            and not handoff_ready(connection, task, conversation)):
                        # No model submission to reconcile while this handoff
                        # waits for a domain/foreground prerequisite.
                        continue
                    now = datetime.now(timezone.utc)
                    # Receipt watches are bounded independently from dispatch.
                    # Expired/unknown liabilities remain charged indefinitely;
                    # stopping automatic reconciliation never means zero spend.
                    permission_expired = (permission is not None
                        and now >= datetime.fromisoformat(permission['expires_at']))
                    if permission_expired or pending.get('reconcile_attempts', 0) >= 256:
                        continue
                    if now < datetime.fromisoformat(pending.get('next_reconcile_at', pending['created_at'])):
                        return {'status': 'waiting'}
                    pending['reconcile_attempts'] = pending.get('reconcile_attempts', 0) + 1
                    pending['next_reconcile_at'] = (now + timedelta(seconds=
                        min(300, 2 ** min(9, pending['reconcile_attempts'])))).isoformat()
                    execute(connection, 'UPDATE research_tasks SET continuation_budget=:budget WHERE task_id=:task',
                        {'budget': ledger, 'task': task['task_id']})
                    return self._continuation_intent(task, conversation, pending)
                budgeted = permission is not None
                if budgeted:
                    if self._permission_blocked_reason(task, conversation) is not None:
                        continue
                    if len(ledger) >= permission['max_turns']:
                        continue
                    remaining = permission['token_limit'] - sum(r['charged_tokens'] for r in ledger if r['status'] == 'settled')
                    if remaining < 1048576 + 8192:
                        continue
                    params = {'task': task['task_id'], 'owner': owner, 'workspace': workspace,
                        'since': permission['created_at'], 'artifacts': permission['confirmed_artifact_ids']}
                else:
                    if self._data_ready_blocked_reason(task, conversation) is not None:
                        continue
                    if len(ledger) >= DATA_READY_MAX_TURNS:
                        continue
                    params = {'task': task['task_id'], 'owner': owner, 'workspace': workspace,
                        'since': None, 'artifacts': []}
                events = []
                if budgeted:
                    for table, identity, artifact in (
                        ('ml_training_runs', 'training_run_id', 'ml_strategy_artifact_id'),
                        ('ml_prediction_runs', 'prediction_run_id', 'ml_strategy_artifact_id'),
                        ('backtest_jobs', 'job_id', 'strategy_version_artifact_id'),
                    ):
                        # Table/column choices are a closed constant set. Exact
                        # confirmed strategy lineage is required for every event.
                        rows = execute(connection, f'''SELECT {identity} AS identity, status, updated_at
                            FROM {table} WHERE task_id=:task AND owner_principal=:owner AND workspace_id=:workspace
                              AND {artifact} IN (SELECT jsonb_array_elements_text(CAST(:artifacts AS JSONB)))
                              AND status IN ('completed','failed','cancelled') AND updated_at >= CAST(:since AS TIMESTAMPTZ)
                            ORDER BY updated_at,{identity} LIMIT 64''', params)
                        events.extend({'kind': table, **row} for row in rows)
                # Data-ready signal jobs are the one terminal-ready outcome that
                # wakes the conversation: the job completed AND its produced
                # signal_snapshot artifact is validated. Failures never wake.
                ready_rows = execute(connection, '''SELECT j.job_id AS identity, 'completed' AS status,
                        j.updated_at, j.result_artifact_id
                    FROM signal_producer_jobs j JOIN artifacts a ON a.artifact_id=j.result_artifact_id
                    WHERE j.task_id=:task AND j.owner_principal=:owner AND j.workspace_id=:workspace
                      AND j.status='completed' AND a.task_id=j.task_id
                      AND a.owner_principal=j.owner_principal AND a.workspace_id=j.workspace_id
                      AND a.kind='signal_snapshot' AND a.status='validated'
                      AND (CAST(:since AS TIMESTAMPTZ) IS NULL OR j.updated_at >= CAST(:since AS TIMESTAMPTZ))
                    ORDER BY j.updated_at, j.job_id LIMIT 64''', params)
                events.extend({'kind': 'signal_producer_jobs', 'data_ready': True, **row} for row in ready_rows)
                unseen = [event for event in events if not any(
                    row['event_key'] == _event_key(event) for row in ledger)]
                if not unseen and budgeted:
                    events = handoff_events(connection, task, conversation)
                for event in sorted(events, key=lambda e: (e['updated_at'], e['kind'], e['identity'])):
                    event_key = _event_key(event)
                    if any(r['event_key'] == event_key for r in ledger):
                        if event.get('data_ready'):
                            logger.debug("data-ready continuation already reserved: task=%s event=%s",
                                task['task_id'], event_key)
                        continue
                    if self._event_blocked_by_needs_attention(task, event_key):
                        logger.info("continuation withheld by needs_attention block: task=%s reason=%s blocked_event=%s event=%s",
                            task['task_id'], task.get('continuation_blocked_reason'),
                            task.get('continuation_blocked_event_key'), event_key)
                        continue
                    if task.get('continuation_blocked_reason') == 'continuation_needs_attention':
                        logger.info("continuation re-arming for distinct event: task=%s reason=%s blocked_event=%s new_event=%s",
                            task['task_id'], task.get('continuation_blocked_reason'),
                            task.get('continuation_blocked_event_key'), event_key)
                    if not admit:
                        return {'status': 'eligible', 'task_id': task['task_id']}
                    if event.get('data_ready') and not budgeted:
                        instruction = ('BYQ trusted task continuation. Resume only the original research goal for task '
                            + task['task_id'] + '. The signal/data preparation this task waited on is now ready: '
                            'signal_producer_job ' + str(event['identity']) + ' completed with immutable validated '
                            'signal_snapshot ' + str(event['result_artifact_id']) + '. Re-read this exact task and its '
                            'progress through BeyondQuant MCP (byq_research_get / byq_backtest_task_get). Reconcile the '
                            'exact original object before any write. Apply current authorization to each prediction, '
                            'signal, backtest and comparison action separately. A prior strategy or action approval is '
                            'not blanket authorization. If approval is needed, persist/request it and explain the '
                            'blocker. The injected identity is authoritative. Workspace/conversation-wide context and '
                            'notification inbox calls (including byq_agent_context) are unavailable in this task-bound '
                            'turn; read only the exact task. Background web search is unavailable. Preserve the original '
                            'goal; update its durable progress and exact evidence. A completed model turn does not mean '
                            'the research goal is complete. Do not create a new task or choose a different workspace object.')
                        receipt = self.reserve_data_ready_budget(task['task_id'], trusted_context=trusted_context,
                            event_key=event_key,
                            input_sha256=hashlib.sha256(instruction.encode()).hexdigest(),
                            instruction=instruction, _connection=connection)
                        return self._continuation_intent(task, conversation, receipt)
                    instruction = ('BYQ trusted task continuation. Resume only the original research goal for task '
                        + task['task_id'] + '. Re-read this exact task and its progress through BeyondQuant MCP. '
                        'The confirmed strategy lineage is ' + json.dumps(permission['confirmed_artifact_ids']) + '. '
                        'A durable domain event is ' + json.dumps(event, sort_keys=True) + '. '
                        'Reconcile the exact original object before any write. Apply current authorization to each '
                        'prediction, signal, backtest and comparison action separately. A strategy approval is not '
                        'blanket authorization. If approval is needed, persist/request it and explain the blocker. '
                        'The injected identity is authoritative. Workspace/conversation-wide context and notification inbox '
                        'calls (including byq_agent_context) are unavailable in this task-bound turn; '
                        'read only the exact task through byq_research_get. '
                        'Background web search is unavailable. Preserve the original goal; update its durable progress '
                        'and exact evidence. A completed model turn does not mean the research goal is complete. '
                        'Do not create a new task or choose a different workspace object.')
                    receipt = self.reserve_continuation_budget(task['task_id'], trusted_context=trusted_context,
                        grant_version=permission['grant_version'], event_key=event_key,
                        input_sha256=hashlib.sha256(instruction.encode()).hexdigest(), token_limit=remaining,
                        instruction=instruction, _connection=connection)
                    return self._continuation_intent(task, conversation, receipt)
            return {'status': 'waiting'}

    @staticmethod
    def _recovery_cumulative_charge(row: dict) -> int | None:
        """Exact original + reconciled recovery charge; ``None`` means unknown.

        Unknown is never zero and never refunded. A reserved/rejected row that was
        never accepted has no charge; an accepted/outcome_unknown row without a
        reconciled settlement is unknown.
        """

        attempts = row.get('recovery_attempts') or []
        total = 0
        if row.get('status') == 'settled':
            total += row.get('charged_tokens') or 0
        elif row.get('status') in {'reserved', 'rejected'} and row.get('run_id') is None:
            pass
        else:
            return None
        for attempt in attempts:
            if attempt.get('status') == 'settled':
                charge = attempt.get('charged_tokens')
                if type(charge) is not int or charge < 0:
                    return None
                total += charge
            elif attempt.get('status') in {'reserved', 'rejected'} and attempt.get('run_id') is None:
                continue
            else:
                return None
        return total

    def begin_recovery(self, task_id: str, *, trusted_context: dict, reservation_id: str,
            interrupted_run_id: str, interrupted_generation: str, containment_attempt: int,
            interrupted_executor_epoch: int, snapshot_tail_sequence: int, snapshot_digest: str,
            model_call_floor: int = recovery_contract.MODEL_CALL_FLOOR, read_only: bool = True,
            replayed_calls: object = None, occurred_calls: object = None,
            evidence_conflict: bool = False) -> dict:
        """Authoritatively allocate/reuse one bounded recovery attempt in-row.

        Runs inside the SAME task-row ``SELECT ... FOR UPDATE`` transaction as the
        reservation ledger, so concurrent callers for one fenced loss allocate
        exactly one attempt and never double-deduct the reservation budget. The
        recovery row is an in-row addition (``recovery_attempts``), never an
        independent store, and the prompt identity is the Backend-minted attempt
        key, not the reservation id.
        """

        if not isinstance(reservation_id, str) or re.fullmatch(r'continuation_[0-9a-f]{32}', reservation_id) is None:
            raise ValueError('invalid recovery reservation identity')
        with self._transaction() as connection:
            task, conversation = self._continuation_task(connection, task_id, trusted_context, human=False)
            ledger = task.get('continuation_budget') or []
            row = next((r for r in ledger if r['reservation_id'] == reservation_id), None)
            if row is None:
                return {'status': 'blocked', 'reason': 'reservation_missing', 'carrier': None}
            permission = task.get('continuation_permission')
            blocked = self._permission_blocked_reason(task, conversation)
            now = datetime.now(timezone.utc)
            attempts = row.get('recovery_attempts') or []
            other_settled = sum(r['charged_tokens'] for r in ledger
                if r is not row and r['status'] == 'settled')
            other_unresolved = sum(r['token_limit'] for r in ledger
                if r is not row and r['status'] != 'settled')
            decision = recovery_contract.budget_decision(
                permission_token_limit=(permission or {}).get('token_limit', 0),
                other_settled=other_settled, other_unresolved=other_unresolved,
                r_token_limit=row['token_limit'],
                cum_exact=self._recovery_cumulative_charge(row),
                model_call_floor=model_call_floor,
                revoked=bool(permission and permission.get('revoked_at') is not None),
                expired=bool(permission and now >= datetime.fromisoformat(permission['expires_at'])),
                blocked_reason=blocked,
                ordinal=len(attempts), evidence_conflict=evidence_conflict)
            if decision['decision'] != 'eligible':
                return {'status': decision['decision'], 'reason': decision['reason'],
                        'carrier': None, 'r_available': decision['r_available']}
            envelope = recovery_contract.admission_envelope(
                read_only=read_only, replayed_calls=replayed_calls, occurred_calls=occurred_calls)
            if not envelope['eligible']:
                return {'status': 'blocked', 'reason': 'out_of_envelope',
                        'envelope': envelope, 'carrier': None}
            try:
                attempt, created = recovery_contract.allocate_recovery_attempt(
                    reservation_id=reservation_id, existing_attempts=attempts,
                    interrupted_run_id=interrupted_run_id,
                    interrupted_generation=interrupted_generation,
                    containment_attempt=containment_attempt,
                    interrupted_executor_epoch=interrupted_executor_epoch,
                    snapshot_tail_sequence=snapshot_tail_sequence, snapshot_digest=snapshot_digest)
            except recovery_contract.RecoveryRejected as exc:
                return {'status': 'blocked', 'reason': exc.code, 'carrier': None}
            if created:
                updated = {**row, 'recovery_attempts': [*attempts, attempt],
                           'status': 'reserved', 'next_attempt_at': now.isoformat()}
                ledger = [updated if r is row else r for r in ledger]
                execute(connection, 'UPDATE research_tasks SET continuation_budget=:budget WHERE task_id=:task',
                    {'budget': ledger, 'task': task_id})
                logger.info('recovery attempt allocated: task=%s reservation=%s attempt=%s ordinal=%s',
                    task_id, reservation_id, attempt['attempt_key'], attempt['ordinal'])
            return {'status': 'eligible', 'reason': 'recovery_attempt', 'reused': not created,
                    'carrier': recovery_contract.carrier_fields(attempt), 'attempt': attempt,
                    'envelope': envelope, 'r_available': decision['r_available']}

    def record_recovery_target(self, task_id: str, *, trusted_context: dict, reservation_id: str,
            attempt_key: str, run_id: str, target_executor_epoch: int, target_generation: str,
            status: str = 'accepted') -> dict:
        """Persist the Adapter's accepted target receipt, fenced against stale writes."""

        from .research import IdempotencyConflict
        if status not in {'accepted', 'settled', 'rejected', 'outcome_unknown'}:
            raise ValueError('invalid recovery attempt status')
        if not isinstance(run_id, str) or re.fullmatch(r'[0-9a-f]{32}', run_id) is None:
            raise ValueError('exact runtime identity required')
        if type(target_executor_epoch) is not int or target_executor_epoch < 1:
            raise ValueError('invalid target executor epoch')
        if not isinstance(target_generation, str) or not target_generation:
            raise ValueError('invalid target generation')
        with self._transaction() as connection:
            task, _ = self._continuation_task(connection, task_id, trusted_context, human=False)
            rows = task.get('continuation_budget') or []
            row = next((r for r in rows if r['reservation_id'] == reservation_id), None)
            if row is None:
                raise ValueError('original continuation reservation required')
            attempts = row.get('recovery_attempts') or []
            index = next((i for i, a in enumerate(attempts) if a['attempt_key'] == attempt_key), None)
            if index is None:
                raise ValueError('unknown recovery attempt')
            attempt = dict(attempts[index])
            if attempt.get('status') == 'settled':
                if (attempt.get('run_id'), attempt.get('target_executor_epoch'),
                        attempt.get('target_generation')) != (run_id, target_executor_epoch, target_generation):
                    raise IdempotencyConflict('settled recovery target cannot change')
                return attempt
            if attempt.get('run_id') is not None and attempt['run_id'] != run_id:
                raise IdempotencyConflict('recovery runtime identity conflicts')
            if (attempt.get('target_executor_epoch') is not None
                    and attempt['target_executor_epoch'] != target_executor_epoch):
                raise IdempotencyConflict('stale recovery target epoch')
            if (attempt.get('target_generation') is not None
                    and attempt['target_generation'] != target_generation):
                raise IdempotencyConflict('stale recovery target generation')
            attempt.update(status=status, run_id=run_id,
                target_executor_epoch=target_executor_epoch, target_generation=target_generation)
            attempts[index] = attempt
            updated = {**row, 'recovery_attempts': attempts}
            rows = [updated if r is row else r for r in rows]
            execute(connection, 'UPDATE research_tasks SET continuation_budget=:budget WHERE task_id=:task',
                {'budget': rows, 'task': task_id})
            return attempt

    def block_continuation(self, task_id: str, reason: str, *, trusted_context: dict) -> dict:
        if reason not in {'model_or_executor_unqualified', 'continuation_needs_attention'}:
            raise ValueError('invalid continuation blocker')
        with self._transaction() as connection:
            self._continuation_task(connection, task_id, trusted_context, human=False)
            event_key = TASK_WIDE_BLOCK_EVENT_KEY if reason == 'continuation_needs_attention' else None
            execute(connection, 'UPDATE research_tasks SET continuation_blocked_reason=:reason, continuation_blocked_event_key=:event WHERE task_id=:task',
                {'reason': reason, 'event': event_key, 'task': task_id})
            logger.info("continuation blocked: task=%s reason=%s event=%s", task_id, reason, event_key)
            return {'blocked_reason': reason}

    def claim_continuation_dispatch(self, task_id: str, reservation_id: str, *, trusted_context: dict) -> dict:
        with self._transaction() as connection:
            task, conversation = self._continuation_task(connection, task_id, trusted_context, human=False)
            rows = task.get('continuation_budget') or []
            row = next((r for r in rows if r['reservation_id'] == reservation_id), None)
            now = datetime.now(timezone.utc)
            if (os.environ.get('BYQ_F6_EXECUTOR_ENABLED') != '1' or row is None or row['status'] != 'reserved'
                    or self._continuation_blocked_reason(task, conversation, row) is not None
                    or datetime.fromisoformat(row['expires_at']) <= now
                    or datetime.fromisoformat(row['next_attempt_at']) > now or row['dispatch_attempts'] >= 8):
                return {'dispatch': False}
            if row['event_key'].startswith('handoff-v1:') and not handoff_ready(connection, task, conversation):
                # Waiting for a foreground turn, approval or job consumes no
                # dispatch attempts and does not create a second reservation.
                return {'dispatch': False}
            row['dispatch_attempts'] += 1
            row['next_attempt_at'] = (now + timedelta(seconds=min(60, 2 ** row['dispatch_attempts']))).isoformat()
            # The uncertainty is durable before crossing the process boundary.
            # A second consumer can only reconcile this original identity.
            row['status'] = 'outcome_unknown'
            execute(connection, 'UPDATE research_tasks SET continuation_budget=:budget WHERE task_id=:task',
                {'budget': rows, 'task': task_id})
            return {'dispatch': True, 'attempt': row['dispatch_attempts']}

    @staticmethod
    def _continuation_intent(task: dict, conversation: dict, receipt: dict) -> dict:
        pending_recovery = next((attempt for attempt in (receipt.get('recovery_attempts') or [])
            if attempt.get('status') == 'reserved'), None)
        reservation = {'schema_version': 'task-continuation-reservation.v1',
            'reservation_id': receipt['reservation_id'], 'task_id': task['task_id'],
            'owner': task['owner_principal'], 'workspace_id': task['workspace_id'],
            'token_limit': receipt['token_limit'], 'expires_at': receipt['expires_at']}
        if pending_recovery is not None:
            # The Backend mints the closed carrier; the Gateway only forwards it.
            reservation['recovery_attempt'] = recovery_contract.carrier_fields(pending_recovery)
        return {'status': 'intent', 'task_id': task['task_id'], 'conversation_id': task['conversation_id'],
            'session_id': conversation['runtime_session_id'], 'trace_id': conversation['trace_id'],
            'may_dispatch': ResearchContinuationMixin._continuation_blocked_reason(task, conversation, receipt) is None
                and datetime.fromisoformat(receipt['expires_at']) > datetime.now(timezone.utc),
            'receipt': receipt, 'reservation': reservation}

    def record_continuation_receipt(self, task_id: str, *, trusted_context: dict,
            reservation_id: str, status: str, run_id: str | None = None,
            charged_tokens: int | None = None, settlement_sha256: str | None = None,
            outcome: str | None = None) -> dict:
        """Trusted accounting evidence only; never infer zero usage from errors.

        Revocation and expiry do not discard an already reserved liability.
        Disabled identities remain rejected until a bounded trusted cleanup
        path with equivalent ownership checks is separately connected.
        """
        from .research import IdempotencyConflict
        if outcome not in {None, 'completed', 'needs_attention'} or (outcome is not None and status != 'settled'):
            raise ValueError('invalid continuation outcome')
        if status not in {'accepted', 'outcome_unknown', 'settled', 'rejected'}:
            raise ValueError('invalid continuation receipt status')
        if status == 'accepted' and (not isinstance(run_id, str) or re.fullmatch(r'[0-9a-f]{32}', run_id) is None):
            raise ValueError('exact runtime identity required')
        if status == 'settled':
            if type(charged_tokens) is not int or charged_tokens < 0:
                raise ValueError('exact nonnegative charge required')
            if not isinstance(settlement_sha256, str) or re.fullmatch(r'[0-9a-f]{64}', settlement_sha256) is None:
                raise ValueError('trusted unique settlement required')
        elif charged_tokens is not None or settlement_sha256 is not None:
            raise ValueError('unconfirmed receipt cannot return budget')
        if status != 'accepted' and run_id is not None:
            raise ValueError('run identity belongs to acceptance receipt')
        with self._transaction() as connection:
            task, _ = self._continuation_task(connection, task_id, trusted_context, human=False)
            rows = task.get('continuation_budget') or []
            row = next((row for row in rows if row['reservation_id'] == reservation_id), None)
            if row is None:
                raise ValueError('original continuation reservation required')
            if status == 'accepted':
                if row['run_id'] is not None and row['run_id'] != run_id:
                    raise IdempotencyConflict('continuation runtime identity conflicts')
                if row['status'] == 'settled':
                    if row['run_id'] != run_id:
                        raise IdempotencyConflict('settled continuation receipt conflicts')
                    return row
                row.update(status='accepted', run_id=run_id)
            elif status == 'rejected':
                if row['run_id'] is not None or row['status'] == 'settled':
                    raise IdempotencyConflict('accepted continuation cannot be rejected')
                row['status'] = 'reserved'
            elif status == 'outcome_unknown':
                if row['status'] != 'settled':
                    row['status'] = status
            else:
                if charged_tokens > row['token_limit']:
                    raise ValueError('settlement exceeds original reservation')
                if row['status'] == 'settled':
                    if (row['charged_tokens'], row['settlement_sha256'], row.get('outcome')) != (charged_tokens, settlement_sha256, outcome):
                        raise IdempotencyConflict('continuation settlement conflicts')
                    return row
                row.update(status='settled', charged_tokens=charged_tokens, settlement_sha256=settlement_sha256, outcome=outcome)
                if outcome == 'needs_attention':
                    execute(connection, "UPDATE research_tasks SET continuation_blocked_reason='continuation_needs_attention', continuation_blocked_event_key=:event WHERE task_id=:task",
                        {'event': row['event_key'], 'task': task_id})
                    logger.info("continuation settled needs_attention: task=%s event=%s reservation=%s",
                        task_id, row['event_key'], reservation_id)
            execute(connection, 'UPDATE research_tasks SET continuation_budget = :budget WHERE task_id = :task',
                {'budget': rows, 'task': task_id})
            return row
