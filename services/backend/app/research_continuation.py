"""BYQ task-scoped human permission ledger; no model dispatch capability."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
import os
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

from .db import execute, fetch_one


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
    def _continuation_view(task, conversation):
        ledger = task.get("continuation_permission")
        if ledger is None:
            return {"schema_version": "task-continuation-permission.v1", "task_id": task["task_id"],
                    "permission": None, "can_start": False, "blocked_reason": "permission_missing"}
        public = {key: value for key, value in ledger.items() if key not in {"idempotency_key", "request_sha256"}}
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
                      "confirmed_artifacts": confirmed_artifacts,
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
            execute(connection, 'UPDATE research_tasks SET continuation_budget = :budget, continuation_blocked_reason=NULL WHERE task_id = :task',
                {'budget': [*rows, receipt], 'task': task_id})
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
            tasks = execute(connection, '''SELECT task_id FROM research_tasks
                WHERE conversation_id=:conversation AND owner_principal=:owner AND workspace_id=:workspace
                  AND continuation_permission IS NOT NULL
                ORDER BY EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(continuation_budget, '[]'::jsonb)) r WHERE r->>'status' != 'settled') DESC, continuation_checked_at NULLS FIRST,task_id LIMIT 64''',
                {'conversation': conversation_id, 'owner': owner, 'workspace': workspace})
            for selected in tasks:
                task, conversation = self._continuation_task(connection, selected['task_id'], trusted_context, human=False)
                execute(connection, 'UPDATE research_tasks SET continuation_checked_at=now() WHERE task_id=:task',
                    {'task': task['task_id']})
                permission = task['continuation_permission']
                ledger = task.get('continuation_budget') or []
                pending = next((r for r in ledger if r['status'] != 'settled' and r.get('instruction')), None)
                if pending is not None:
                    now = datetime.now(timezone.utc)
                    # Receipt watches are bounded independently from dispatch.
                    # Expired/unknown liabilities remain charged indefinitely;
                    # stopping automatic reconciliation never means zero spend.
                    if (now >= datetime.fromisoformat(permission['expires_at'])
                            or pending.get('reconcile_attempts', 0) >= 256):
                        continue
                    if now < datetime.fromisoformat(pending.get('next_reconcile_at', pending['created_at'])):
                        return {'status': 'waiting'}
                    pending['reconcile_attempts'] = pending.get('reconcile_attempts', 0) + 1
                    pending['next_reconcile_at'] = (now + timedelta(seconds=
                        min(300, 2 ** min(9, pending['reconcile_attempts'])))).isoformat()
                    execute(connection, 'UPDATE research_tasks SET continuation_budget=:budget WHERE task_id=:task',
                        {'budget': ledger, 'task': task['task_id']})
                    return self._continuation_intent(task, conversation, pending)
                if self._permission_blocked_reason(task, conversation) is not None:
                    continue
                if task.get('continuation_blocked_reason') == 'continuation_needs_attention':
                    continue
                if len(ledger) >= permission['max_turns']:
                    continue
                remaining = permission['token_limit'] - sum(r['charged_tokens'] for r in ledger if r['status'] == 'settled')
                if remaining < 1048576 + 8192:
                    continue
                params = {'task': task['task_id'], 'owner': owner, 'workspace': workspace,
                    'since': permission['created_at'], 'artifacts': permission['confirmed_artifact_ids']}
                events = []
                for table, identity, artifact in (
                    ('ml_training_runs', 'training_run_id', 'ml_strategy_artifact_id'),
                    ('ml_prediction_runs', 'prediction_run_id', 'ml_strategy_artifact_id'),
                    ('signal_producer_jobs', 'job_id', 'strategy_version_artifact_id'),
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
                for event in sorted(events, key=lambda e: (e['updated_at'], e['kind'], e['identity'])):
                    event_key = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
                    if any(r['event_key'] == event_key for r in ledger):
                        continue
                    if not admit:
                        return {'status': 'eligible', 'task_id': task['task_id']}
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

    def block_continuation(self, task_id: str, reason: str, *, trusted_context: dict) -> dict:
        if reason not in {'model_or_executor_unqualified', 'continuation_needs_attention'}:
            raise ValueError('invalid continuation blocker')
        with self._transaction() as connection:
            self._continuation_task(connection, task_id, trusted_context, human=False)
            execute(connection, 'UPDATE research_tasks SET continuation_blocked_reason=:reason WHERE task_id=:task',
                {'reason': reason, 'task': task_id})
            return {'blocked_reason': reason}

    def claim_continuation_dispatch(self, task_id: str, reservation_id: str, *, trusted_context: dict) -> dict:
        with self._transaction() as connection:
            task, conversation = self._continuation_task(connection, task_id, trusted_context, human=False)
            rows = task.get('continuation_budget') or []
            row = next((r for r in rows if r['reservation_id'] == reservation_id), None)
            now = datetime.now(timezone.utc)
            if (os.environ.get('BYQ_F6_EXECUTOR_ENABLED') != '1' or row is None or row['status'] != 'reserved'
                    or self._permission_blocked_reason(task, conversation) is not None
                    or datetime.fromisoformat(row['expires_at']) <= now
                    or datetime.fromisoformat(row['next_attempt_at']) > now or row['dispatch_attempts'] >= 8):
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
        return {'status': 'intent', 'task_id': task['task_id'], 'conversation_id': task['conversation_id'],
            'session_id': conversation['runtime_session_id'], 'trace_id': conversation['trace_id'],
            'may_dispatch': ResearchContinuationMixin._permission_blocked_reason(task, conversation) is None
                and datetime.fromisoformat(receipt['expires_at']) > datetime.now(timezone.utc),
            'receipt': receipt, 'reservation': {'schema_version': 'task-continuation-reservation.v1',
                'reservation_id': receipt['reservation_id'], 'task_id': task['task_id'],
                'owner': task['owner_principal'], 'workspace_id': task['workspace_id'],
                'token_limit': receipt['token_limit'], 'expires_at': receipt['expires_at']}}

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
                    execute(connection, "UPDATE research_tasks SET continuation_blocked_reason='continuation_needs_attention' WHERE task_id=:task",
                        {'task': task_id})
            execute(connection, 'UPDATE research_tasks SET continuation_budget = :budget WHERE task_id = :task',
                {'budget': rows, 'task': task_id})
            return row
