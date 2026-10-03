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
from .research_handoff_events import handoff_ready
from .backtest_task import project_backtest_task, task_id_from_signal_job
from packages.contracts.research_executable_action import derive_executable_action
from packages.contracts.continuation_request import (
    PERMISSION_SCHEMA_VERSION,
    RESERVATION_SCHEMA_VERSION,
    exceeded_request_limits,
    profile_binding,
    request_limits,
    validate_limits,
    validate_profile_binding,
    validate_request_usage,
)

logger = logging.getLogger("byq.research.continuation")

# Grantless data-ready events only advance deterministic task progress and
# create a zero-token notification. An explicit human grant uses the ordinary
# task-bound reservation path. Legacy `data_ready` model reservations remain
# settleable, but never regain dispatch eligibility.
DATA_READY_EVENT_PREFIX = "ready-v1:"
DATA_READY_MAX_TURNS = 8
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


def _request_v2(payload: object) -> dict:
    """Validate the closed one-request profile grant payload."""
    from packages.contracts.continuation_request import PROFILE_ID

    required = {"idempotency_key", "confirmed_artifact_ids"}
    optional = {"execution_profile_id", "max_turns", "valid_seconds", "turn_timeout_seconds"}
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
    profile_id = payload.get("execution_profile_id", PROFILE_ID)
    if profile_id != PROFILE_ID:
        raise ValueError("unqualified continuation execution profile")
    max_turns = payload.get("max_turns", 1)
    if type(max_turns) is not int or max_turns != 1:
        raise ValueError("continuation permission supports exactly one request")
    valid_seconds = _positive(payload.get("valid_seconds", 86400), "validity", 86400)
    turn_timeout_seconds = _positive(payload.get("turn_timeout_seconds", valid_seconds), "turn timeout", 86400)
    return {
        "idempotency_key": key,
        "confirmed_artifact_ids": sorted(artifacts),
        "max_turns": 1,
        "valid_seconds": valid_seconds,
        "turn_timeout_seconds": turn_timeout_seconds,
        "execution_profile": validate_profile_binding(profile_binding()),
        "request_limits": validate_limits(request_limits()),
    }


def _is_v2_permission(value: object) -> bool:
    return isinstance(value, dict) and value.get("schema_version") == PERMISSION_SCHEMA_VERSION


def _is_v2_reservation(value: object) -> bool:
    return isinstance(value, dict) and value.get("schema_version") == RESERVATION_SCHEMA_VERSION


def _approved_execution_artifact(connection, *, owner: str, workspace: str, task_id: str,
                                 strategy_version_artifact_id: object) -> str | None:
    """Backend-authoritative execution approval for a strategy version."""

    if not isinstance(strategy_version_artifact_id, str):
        return None
    row = fetch_one(connection, """SELECT artifact_id FROM artifacts
        WHERE task_id=:task AND owner_principal=:owner AND workspace_id=:workspace
          AND kind='strategy_approval' AND status='validated'
          AND content->>'strategy_version_artifact_id'=:strategy
          AND content->>'decision'='approved'
          AND content->>'execution_authorized'='true'
        ORDER BY created_at, artifact_id LIMIT 1""",
        {'task': task_id, 'owner': owner, 'workspace': workspace, 'strategy': strategy_version_artifact_id})
    return row['artifact_id'] if row is not None else None


def _backtest_job_for_snapshot(connection, *, owner: str, signal_snapshot_artifact_id: object) -> dict | None:
    if not isinstance(signal_snapshot_artifact_id, str):
        return None
    row = fetch_one(connection, """SELECT job_id, name, status, attempts, max_attempts,
            summary_json, error_code, error_message, result_artifact_id FROM backtest_jobs
        WHERE owner_principal=:owner AND request_json->>'signal_snapshot_artifact_id'=:snapshot
        ORDER BY created_at DESC, job_id DESC LIMIT 1""",
        {'owner': owner, 'snapshot': signal_snapshot_artifact_id})
    if row is None:
        return None
    return {'job_id': row['job_id'], 'name': row['name'], 'status': row['status'],
            'attempts': row['attempts'], 'max_attempts': row['max_attempts'],
            'summary': row['summary_json'], 'error_code': row['error_code'],
            'error_message': row['error_message'], 'result_artifact_id': row['result_artifact_id']}


def _data_ready_executable(connection, task: dict, job: dict) -> dict:
    """Backend-derived exact next action for a completed signal job.

    Reuses the authoritative ``project_backtest_task`` projection (ADR-0044) so
    the model never rebuilds create parameters or guesses the task identity.
    """

    approval_id = _approved_execution_artifact(connection, owner=task['owner_principal'],
        workspace=task['workspace_id'], task_id=task['task_id'],
        strategy_version_artifact_id=job.get('strategy_version_artifact_id'))
    readiness = job.get('readiness_json')
    signal_projection = {
        'job_id': job.get('job_id'), 'status': 'completed',
        'attempt_count': job.get('attempt_count'),
        'result_artifact_id': job.get('result_artifact_id'),
        'error_code': job.get('error_code'), 'error_detail': job.get('error_detail'),
    }
    projection = project_backtest_task(
        research_task_id=task['task_id'],
        strategy_version_artifact_id=str(job.get('strategy_version_artifact_id')),
        approval_artifact_id=approval_id,
        stock_pool_snapshot_id=str(job.get('stock_pool_snapshot_id')),
        readiness=readiness if isinstance(readiness, dict) else None,
        signal_job=signal_projection,
        backtest_job=_backtest_job_for_snapshot(connection, owner=task['owner_principal'],
            signal_snapshot_artifact_id=job.get('result_artifact_id')),
    )
    return derive_executable_action(projection)


def _deterministic_progress(task: dict, executable: dict) -> dict:
    """Structured ResearchTask progress advanced without a model turn."""

    existing = task.get('progress') if isinstance(task.get('progress'), dict) else {}
    linked = existing.get('linked_objects') if isinstance(existing.get('linked_objects'), list) else []
    stage = {'execute': 'backtest', 'wait': 'data_preparation',
             'review_result': 'comparison', 'review_failure': 'blocked',
             'create': 'strategy', 'resolve_blockers': 'blocked'}.get(
        executable.get('next_action'), 'backtest')
    blocked_reason = None
    if stage == 'blocked':
        blocked_reason = 'backtest_action_requires_review'
    return {
        'schema_version': 'research-progress.v1',
        'stage': stage,
        'next_action': executable.get('next_action'),
        'blocked_reason': blocked_reason,
        'linked_objects': linked,
        'completion_evidence': existing.get('completion_evidence')
            if isinstance(existing.get('completion_evidence'), list) else [],
    }


def _needs_attention_progress(task: dict, event_key: str) -> dict:
    """Structured ResearchTask progress for a budget/guard needs_attention stop."""

    existing = task.get('progress') if isinstance(task.get('progress'), dict) else {}
    linked = existing.get('linked_objects') if isinstance(existing.get('linked_objects'), list) else []
    evidence = existing.get('completion_evidence') if isinstance(existing.get('completion_evidence'), list) else []
    reason = 'continuation_needs_attention:' + str(event_key)[:96]
    return {
        'schema_version': 'research-progress.v1',
        'stage': 'blocked',
        'next_action': 'needs_attention',
        'blocked_reason': reason[:160],
        'linked_objects': linked,
        'completion_evidence': evidence,
    }


def _notification_receipt(event_key: str, executable: dict, now) -> dict:
    """Durable at-most-once notification marker; it never reserves a model turn."""

    encoded = json.dumps(executable, sort_keys=True, separators=(',', ':')).encode()
    return {
        'reservation_id': 'notification_' + uuid.uuid4().hex,
        'grant_kind': 'data_ready_notification', 'grant_version': None,
        'event_key': event_key, 'input_sha256': hashlib.sha256(encoded).hexdigest(),
        'token_limit': 0, 'status': 'settled', 'run_id': None, 'charged_tokens': 0,
        'settlement_sha256': hashlib.sha256(('notified:' + event_key).encode()).hexdigest(),
        'created_at': now.isoformat(), 'instruction': None, 'outcome': 'notified',
        'executable': executable,
    }


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
        if _is_v2_permission(ledger):
            try:
                validate_profile_binding(ledger.get('execution_profile'))
                validate_limits(ledger.get('request_limits'))
            except ValueError:
                return 'continuation_permission_invalid'
            if ledger.get('schema_version') != PERMISSION_SCHEMA_VERSION or ledger.get('max_turns') != 1:
                return 'continuation_permission_invalid'
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
        """Single admission gate for current grants and persisted receipts."""
        if receipt is not None and receipt.get('grant_kind') == 'data_ready':
            # This legacy subtype represented an inferred model grant. It is
            # retained only so its exact liability can be reconciled; a later
            # human grant must not make the old reservation dispatchable.
            return 'unsupported_model_grant'
        if receipt is not None and not _is_v2_reservation(receipt):
            return 'legacy_continuation_read_only'
        if receipt is not None:
            try:
                validate_profile_binding(receipt.get('execution_profile'))
                validate_limits(receipt.get('request_limits'))
            except ValueError:
                return 'continuation_request_invalid'
            permission = task.get('continuation_permission') or {}
            if (not _is_v2_permission(permission)
                    or receipt.get('execution_profile') != permission.get('execution_profile')
                    or receipt.get('request_limits') != permission.get('request_limits')):
                return 'continuation_request_profile_mismatch'
        return ResearchContinuationMixin._permission_blocked_reason(task, conversation)

    @staticmethod
    def _continuation_view(task, conversation):
        ledger = task.get("continuation_permission")
        if ledger is None:
            return {
                'schema_version': PERMISSION_SCHEMA_VERSION,
                'task_id': task['task_id'],
                'permission': None,
                'available_profile': {'execution_profile': profile_binding(), 'request_limits': request_limits()},
                'request_state': {'requests_reserved': 0, 'requests_remaining': 1,
                    'unconfirmed_requests': 0, 'request_usage': None,
                    'request_identity': None},
                'can_start': False,
                'blocked_reason': 'permission_missing',
            }
        public = {key: value for key, value in ledger.items() if key not in {"idempotency_key", "request_sha256", "handoff_version"}}
        rows = task.get('continuation_budget') or []
        if _is_v2_permission(ledger):
            # This user-supplied confirmation nonce lets the browser reconcile
            # an ambiguous grant POST without exposing it as a bearer secret.
            public['confirmation_id'] = ledger.get('idempotency_key')
            requests = [row for row in rows if _is_v2_reservation(row)]
            latest = requests[-1] if requests else None
            request_identity = ({key: latest.get(key) for key in (
                'reservation_id', 'status', 'run_id', 'event_key', 'input_sha256',
                'grant_version', 'outcome', 'settlement_sha256', 'dispatch_attempts')}
                if latest is not None else None)
            request_state = {
                'requests_reserved': len(requests),
                'requests_remaining': max(0, ledger['max_turns'] - len(requests)),
                'unconfirmed_requests': sum(row.get('status') not in {'settled', 'rejected'} for row in requests),
                'request_usage': latest.get('request_usage') if latest is not None else None,
                'request_identity': request_identity,
            }
            reason = ResearchContinuationMixin._permission_blocked_reason(task, conversation)
            if reason is None:
                if request_state['unconfirmed_requests']:
                    reason = 'continuation_result_unconfirmed'
                elif latest is not None and latest.get('status') == 'settled':
                    usage = latest.get('request_usage')
                    try:
                        if not isinstance(usage, dict):
                            reason = 'continuation_usage_unconfirmed'
                        elif exceeded_request_limits(usage):
                            reason = 'continuation_request_limit_exceeded'
                    except ValueError:
                        reason = 'continuation_usage_unconfirmed'
                if reason is None and os.environ.get('BYQ_F6_EXECUTOR_ENABLED') != '1':
                    reason = 'request_profile_unqualified'
                elif reason is None and not request_state['requests_remaining']:
                    reason = 'continuation_request_exhausted'
                elif reason is None:
                    reason = task.get('continuation_blocked_reason') or 'waiting_for_event'
            return {
                'schema_version': PERMISSION_SCHEMA_VERSION,
                'task_id': task['task_id'],
                'permission': public,
                'available_profile': {'execution_profile': profile_binding(), 'request_limits': request_limits()},
                'request_state': request_state,
                'can_start': False,
                'blocked_reason': reason,
                'blocked_event_key': task.get('continuation_blocked_event_key'),
                'blocked_reason_detail': task.get('continuation_blocked_reason'),
            }
        reserved = sum(row['token_limit'] for row in rows if row['status'] != 'settled')
        charged = sum(row['charged_tokens'] for row in rows if row['status'] == 'settled')
        budget = {'token_limit': ledger['token_limit'], 'reserved_tokens': reserved,
            'charged_tokens': charged, 'available_tokens': ledger['token_limit'] - reserved - charged,
            'turns_reserved': len(rows), 'turns_remaining': ledger['max_turns'] - len(rows),
            'unconfirmed_reservations': sum(row['status'] != 'settled' for row in rows),
            # ADR-0085 P0/§8: the conservative per-call reservation ceiling is
            # NOT model usage. Provider-provable actual input/cache/output usage
            # is only available from the Runtime Adapter's normalized DSH usage
            # projection, so it is explicitly unknown here rather than faked
            # from the reservation (never report 8,454,144 as actual usage).
            'reserved_token_ceiling': reserved + charged,
            'actual_usage': {
                'input_tokens': None, 'cache_read_tokens': None, 'output_tokens': None,
                'model_call_count': None, 'tool_payload_bytes': None,
                'provenance': 'runtime_adapter_normalized_dsh_usage',
            }}
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
        if not _is_v2_permission(ledger):
            reason = 'legacy_continuation_read_only'
        return {"schema_version": "task-continuation-permission.v1", "task_id": task["task_id"],
                "permission": public, "budget": budget, "can_start": False, "blocked_reason": reason,
                "blocked_event_key": task.get("continuation_blocked_event_key"),
                "blocked_reason_detail": task.get("continuation_blocked_reason")}

    def create_continuation_permission(self, task_id: str, payload: object, *, trusted_context: dict) -> dict:
        from .research import IdempotencyConflict

        request = _request_v2(payload)
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self._transaction() as connection:
            task, conversation = self._continuation_task(connection, task_id, trusted_context, human=True)
            existing = task.get("continuation_permission")
            if existing is not None:
                if not _is_v2_permission(existing):
                    raise ValueError("legacy continuation permission is read-only")
                if existing["idempotency_key"] != request["idempotency_key"] or existing["request_sha256"] != digest:
                    raise IdempotencyConflict("continuation permission cannot be replaced or replenished")
                view = self._continuation_view(task, conversation)
            else:
                if task["status"] not in {"planned", "running"} or conversation["status"] != "active":
                    raise ValueError("continuation task or conversation is inactive")
                if any(row.get('status') != 'settled' for row in (task.get('continuation_budget') or [])):
                    raise ValueError("an unresolved legacy continuation liability prevents a new grant")
                confirmed_artifacts = []
                for artifact_id in request["confirmed_artifact_ids"]:
                    artifact = fetch_one(connection, """SELECT artifact_id, content_sha256, kind FROM artifacts
                        WHERE artifact_id = :artifact AND task_id = :task AND owner_principal = :owner
                          AND workspace_id = :workspace AND status = 'validated' FOR SHARE""",
                        {"artifact": artifact_id, "task": task_id, "owner": task["owner_principal"],
                         "workspace": task["workspace_id"]})
                    if artifact is None:
                        raise ValueError("confirmed artifact must be validated and belong to the exact task")
                    if artifact['kind'] not in {'strategy_version', 'ml_strategy_version'}:
                        raise ValueError("continuation grant must bind a validated strategy version")
                    confirmed_artifacts.append(artifact)
                now = datetime.now(timezone.utc)
                ledger = {**request, "schema_version": PERMISSION_SCHEMA_VERSION,
                          "request_sha256": digest, "grant_version": 1,
                          "confirmed_artifacts": confirmed_artifacts,
                          "owner_principal": task["owner_principal"], "workspace_id": task["workspace_id"],
                          "conversation_id": task["conversation_id"], "confirmed_by": trusted_context["actor_principal"],
                          "created_at": now.isoformat(), "expires_at": (now + timedelta(seconds=request["valid_seconds"])).isoformat(),
                          "revoked_at": None, "revoked_by": None}
                execute(connection, """UPDATE research_tasks SET continuation_permission = :ledger
                    WHERE task_id = :task""", {"ledger": ledger, "task": task_id})
                task["continuation_permission"] = ledger
                view = self._continuation_view(task, conversation)
        return view

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
        """Legacy cumulative-token reservations remain read-only liabilities."""
        raise ValueError('legacy continuation budget reservations are read-only')

    def reserve_continuation_request(self, task_id: str, *, trusted_context: dict,
            event: dict, instruction: str, _connection=None) -> dict:
        """Atomically reserve one exact ready-signal read under the v2 profile."""
        from .research import IdempotencyConflict

        if (not isinstance(event, dict) or event.get('kind') != 'signal_producer_jobs'
                or event.get('data_ready') is not True or event.get('status') != 'completed'
                or not isinstance(event.get('identity'), str)
                or re.fullmatch(r'signaljob_[0-9a-f]{32}', event['identity']) is None
                or not isinstance(instruction, str) or not instruction
                or len(instruction.encode()) > 65536):
            raise ValueError('only an exact ready signal result can reserve this request profile')
        event_key = _event_key(event)
        if re.fullmatch(r'ready-v1:[0-9a-f]{64}', event_key) is None:
            raise ValueError('invalid ready signal event identity')
        input_sha256 = hashlib.sha256(instruction.encode()).hexdigest()
        with self._transaction() if _connection is None else nullcontext(_connection) as connection:
            task, conversation = self._continuation_task(connection, task_id, trusted_context, human=False)
            permission = task.get('continuation_permission')
            if permission is None or not _is_v2_permission(permission) or permission['grant_version'] != 1:
                raise ValueError('exact v2 continuation permission required')
            rows = task.get('continuation_budget') or []
            profiled_rows = [row for row in rows if _is_v2_reservation(row)]
            for row in profiled_rows:
                if row.get('event_key') == event_key:
                    if (row.get('input_sha256'), row.get('grant_version'), row.get('execution_profile'), row.get('request_limits')) != (
                            input_sha256, permission['grant_version'], permission['execution_profile'], permission['request_limits']):
                        raise IdempotencyConflict('continuation request input conflicts')
                    return row
            if self._permission_blocked_reason(task, conversation) is not None:
                raise ValueError('continuation permission is inactive')
            if profiled_rows:
                raise ValueError('continuation request limit exhausted')
            if any(row.get('status') != 'settled' for row in rows):
                raise ValueError('legacy continuation liability is unconfirmed')
            for confirmed in permission['confirmed_artifacts']:
                artifact = fetch_one(connection, '''SELECT artifact_id FROM artifacts
                    WHERE artifact_id=:artifact AND task_id=:task AND owner_principal=:owner
                      AND workspace_id=:workspace AND status='validated' AND content_sha256=:digest
                    FOR SHARE''', {'artifact': confirmed['artifact_id'], 'task': task_id,
                    'owner': task['owner_principal'], 'workspace': task['workspace_id'],
                    'digest': confirmed['content_sha256']})
                if artifact is None:
                    raise ValueError('confirmed continuation artifact is unavailable')
            job = fetch_one(connection, '''SELECT job_id, status, result_artifact_id, strategy_version_artifact_id
                FROM signal_producer_jobs WHERE job_id=:job AND task_id=:task
                  AND owner_principal=:owner AND workspace_id=:workspace FOR SHARE''',
                {'job': event['identity'], 'task': task_id, 'owner': task['owner_principal'],
                 'workspace': task['workspace_id']})
            if (job is None or job['status'] != 'completed'
                    or job['result_artifact_id'] != event.get('result_artifact_id')
                    or job['strategy_version_artifact_id'] not in permission['confirmed_artifact_ids']):
                raise ValueError('ready signal is not bound to the confirmed strategy version')
            snapshot = fetch_one(connection, '''SELECT artifact_id FROM artifacts
                WHERE artifact_id=:artifact AND task_id=:task AND owner_principal=:owner
                  AND workspace_id=:workspace AND kind='signal_snapshot' AND status='validated'
                FOR SHARE''', {'artifact': job['result_artifact_id'], 'task': task_id,
                'owner': task['owner_principal'], 'workspace': task['workspace_id']})
            if snapshot is None:
                raise ValueError('ready signal snapshot is not validated')
            now = datetime.now(timezone.utc)
            receipt = {
                'schema_version': RESERVATION_SCHEMA_VERSION,
                'reservation_id': 'continuation_' + uuid.uuid4().hex,
                'grant_version': permission['grant_version'],
                'event_key': event_key,
                'input_sha256': input_sha256,
                'instruction': instruction,
                'backtest_task_id': task_id_from_signal_job(event['identity']),
                'execution_profile': permission['execution_profile'],
                'request_limits': permission['request_limits'],
                'status': 'reserved',
                'run_id': None,
                'request_usage': None,
                'settlement_sha256': None,
                'outcome': None,
                'created_at': now.isoformat(),
                'dispatch_attempts': 0,
                'next_attempt_at': now.isoformat(),
                'expires_at': min(datetime.fromisoformat(permission['expires_at']),
                    now + timedelta(seconds=permission['turn_timeout_seconds'])).isoformat(),
            }
            execute(connection, 'UPDATE research_tasks SET continuation_budget=:budget, '
                'continuation_blocked_reason=NULL, continuation_blocked_event_key=NULL WHERE task_id=:task',
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
                pending = next((r for r in ledger if r['status'] not in {'settled', 'rejected'}
                    and r.get('instruction')), None)
                if pending is not None:
                    if (pending['status'] == 'reserved' and pending['event_key'].startswith('handoff-v1:')
                            and not handoff_ready(connection, task, conversation)):
                        # No model submission to reconcile while this handoff
                        # waits for a domain/foreground prerequisite.
                        continue
                    now = datetime.now(timezone.utc)
                    # Receipt watches are bounded independently from dispatch.
                    # Historical v1 charges remain factual and are not refunded;
                    # v2 unknown usage stays unresolved rather than becoming a charge or zero.
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
                profiled = _is_v2_permission(permission)
                budgeted = False
                if profiled:
                    if self._permission_blocked_reason(task, conversation) is not None:
                        continue
                    if any(_is_v2_reservation(row) for row in ledger):
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
                params['profiled'] = profiled
                events = []
                # ADR-0090 profile is only eligible for the original task's
                # validated ready-signal result. Historical permission events
                # remain readable/settleable but cannot create a new request.
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
                      AND (NOT CAST(:profiled AS BOOLEAN) OR j.strategy_version_artifact_id IN
                        (SELECT jsonb_array_elements_text(CAST(:artifacts AS JSONB))))
                      AND (CAST(:since AS TIMESTAMPTZ) IS NULL OR j.updated_at >= CAST(:since AS TIMESTAMPTZ))
                    ORDER BY j.updated_at, j.job_id LIMIT 64''', params)
                events.extend({'kind': 'signal_producer_jobs', 'data_ready': True, **row} for row in ready_rows)
                unseen = [event for event in events if not any(
                    row['event_key'] == _event_key(event) for row in ledger)]
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
                    if profiled:
                        instruction = (
                            'BYQ trusted read-only task-ready follow-up for exact task ' + task['task_id'] + '. '
                            'Use only byq_research_get to read this exact ResearchTask and byq_backtest_task_get '
                            'to read the exact BacktestTask linked to the completed ready signal below. '
                            'Exact BacktestTask ID: ' + task_id_from_signal_job(event['identity']) + '. '
                            'Do not create or update domain objects, request approvals, execute jobs, browse the web, '
                            'delegate, or access another task. Summarize only facts returned by these exact read tools. '
                            'Ready signal: ' + json.dumps(event, sort_keys=True, separators=(',', ':'))
                        )
                        receipt = self.reserve_continuation_request(task['task_id'],
                            trusted_context=trusted_context, event=event, instruction=instruction,
                            _connection=connection)
                        return self._continuation_intent(task, conversation, receipt)
                    if event.get('data_ready'):
                        # ADR-0085 P0: with NO explicit task/plan grant only a
                        # DETERMINISTIC reducer advances and notifies the user.
                        # It never starts a generic full model turn and never
                        # promises automatic research completion. The exact
                        # Backend-derived next action is persisted atomically
                        # with the durable at-most-once notification marker.
                        job = fetch_one(connection, 'SELECT * FROM signal_producer_jobs WHERE job_id=:job',
                            {'job': event['identity']})
                        if job is None:
                            continue
                        executable = _data_ready_executable(connection, task, job)
                        now = datetime.now(timezone.utc)
                        receipt = _notification_receipt(event_key, executable, now)
                        progress = _deterministic_progress(task, executable)
                        execute(connection, 'UPDATE research_tasks SET continuation_budget=:budget, '
                            'progress=:progress, continuation_blocked_reason=NULL, '
                            'continuation_blocked_event_key=NULL WHERE task_id=:task',
                            {'budget': [*ledger, receipt], 'progress': progress, 'task': task['task_id']})
                        logger.info('data-ready deterministic notification: task=%s event=%s action=%s '
                            'backtest_task=%s approval_required=%s', task['task_id'], event_key,
                            executable['next_action'], executable['backtest_task_id'],
                            executable['approval_required'])
                        return {'status': 'notified', 'task_id': task['task_id'],
                            'conversation_id': task['conversation_id'], 'event_key': event_key,
                            'executable': executable, 'receipt': receipt}
            return {'status': 'waiting'}

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
            if os.environ.get('BYQ_F6_EXECUTOR_ENABLED') != '1' or row is None or not _is_v2_reservation(row):
                return {'dispatch': False}
            if (self._continuation_blocked_reason(task, conversation, row) is not None
                    or row['status'] != 'reserved'
                    or row.get('run_id') is not None
                    or datetime.fromisoformat(row['expires_at']) <= now
                    or datetime.fromisoformat(row['next_attempt_at']) > now or row['dispatch_attempts'] != 0):
                return {'dispatch': False}
            row['dispatch_attempts'] += 1
            row['next_attempt_at'] = row['expires_at']
            # The uncertainty is durable before crossing the process boundary.
            # A second consumer can only reconcile this original identity.
            row['status'] = 'outcome_unknown'
            execute(connection, 'UPDATE research_tasks SET continuation_budget=:budget WHERE task_id=:task',
                {'budget': rows, 'task': task_id})
            return {'dispatch': True, 'attempt': row['dispatch_attempts']}

    @staticmethod
    def _continuation_intent(task: dict, conversation: dict, receipt: dict,
            executable: dict | None = None) -> dict:
        if _is_v2_reservation(receipt):
            reservation = {
                'schema_version': RESERVATION_SCHEMA_VERSION,
                'reservation_id': receipt['reservation_id'],
                'task_id': task['task_id'],
                'owner': task['owner_principal'],
                'workspace_id': task['workspace_id'],
                'expires_at': receipt['expires_at'],
                'execution_profile': receipt['execution_profile'],
                'request_limits': receipt['request_limits'],
            }
        else:
            reservation = {'schema_version': 'task-continuation-reservation.v1',
                'reservation_id': receipt['reservation_id'], 'task_id': task['task_id'],
                'owner': task['owner_principal'], 'workspace_id': task['workspace_id'],
                'token_limit': receipt['token_limit'], 'expires_at': receipt['expires_at']}
        if executable is not None:
            # ADR-0085 P0: the event/intent carries the exact Backend-derived
            # next action so no consumer re-derives the task identity.
            reservation['executable'] = executable
        return {'status': 'intent', 'task_id': task['task_id'], 'conversation_id': task['conversation_id'],
            'session_id': conversation['runtime_session_id'], 'trace_id': conversation['trace_id'],
            'may_dispatch': ResearchContinuationMixin._continuation_blocked_reason(task, conversation, receipt) is None
                and receipt.get('status') == 'reserved' and receipt.get('run_id') is None
                and (not _is_v2_reservation(receipt) or receipt.get('dispatch_attempts') == 0)
                and datetime.fromisoformat(receipt['expires_at']) > datetime.now(timezone.utc),
            'receipt': receipt, 'reservation': reservation,
            **({'executable': executable} if executable is not None else {})}

    def record_continuation_receipt(self, task_id: str, *, trusted_context: dict,
            reservation_id: str, status: str, run_id: str | None = None,
            charged_tokens: int | None = None, settlement_sha256: str | None = None,
            outcome: str | None = None, request_usage: dict | None = None) -> dict:
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
        if status != 'accepted' and run_id is not None:
            raise ValueError('run identity belongs to acceptance receipt')
        if status != 'settled' and (settlement_sha256 is not None or outcome is not None or request_usage is not None):
            raise ValueError('settlement fields require a terminal receipt')
        if status not in {'accepted', 'settled'} and charged_tokens is not None:
            raise ValueError('unconfirmed receipt cannot return budget')
        with self._transaction() as connection:
            task, _ = self._continuation_task(connection, task_id, trusted_context, human=False)
            rows = task.get('continuation_budget') or []
            row = next((row for row in rows if row['reservation_id'] == reservation_id), None)
            if row is None:
                raise ValueError('original continuation reservation required')
            if _is_v2_reservation(row):
                if charged_tokens is not None:
                    raise ValueError('v2 continuation receipts do not contain cumulative token charges')
                if status == 'settled':
                    if request_usage is None or outcome not in {'completed', 'needs_attention'}:
                        raise ValueError('v2 terminal receipt requires request usage and outcome')
                    usage = validate_request_usage(request_usage)
                    if (usage['execution_profile'] != row['execution_profile']
                            or usage['request_limits'] != row['request_limits']):
                        raise ValueError('request usage does not match the reserved profile')
                    if not isinstance(settlement_sha256, str) or re.fullmatch(r'[0-9a-f]{64}', settlement_sha256) is None:
                        raise ValueError('trusted unique settlement required')
                    if row['status'] == 'settled':
                        if (row.get('request_usage'), row.get('settlement_sha256'), row.get('outcome')) != (
                                usage, settlement_sha256, outcome):
                            raise IdempotencyConflict('continuation settlement conflicts')
                        return row
                    if row['status'] == 'rejected':
                        raise IdempotencyConflict('rejected continuation cannot be settled')
                    violations = exceeded_request_limits(usage)
                    row.update(status='settled', request_usage=usage,
                        settlement_sha256=settlement_sha256, outcome=outcome,
                        exceeded_limits=violations)
                    if outcome == 'needs_attention' or violations:
                        progress = _needs_attention_progress(task, row['event_key'])
                        execute(connection, "UPDATE research_tasks SET continuation_blocked_reason='continuation_needs_attention', continuation_blocked_event_key=:event, progress=:progress WHERE task_id=:task",
                            {'event': row['event_key'], 'task': task_id, 'progress': progress})
                elif status == 'accepted':
                    if row['status'] == 'rejected':
                        raise IdempotencyConflict('rejected continuation cannot be accepted')
                    if row['run_id'] is not None and row['run_id'] != run_id:
                        raise IdempotencyConflict('continuation runtime identity conflicts')
                    if row['status'] == 'settled':
                        if row['run_id'] != run_id:
                            raise IdempotencyConflict('settled continuation receipt conflicts')
                        return row
                    row.update(status='accepted', run_id=run_id)
                elif status == 'rejected':
                    attempts = row.get('dispatch_attempts', 0)
                    if row['run_id'] is not None or row['status'] in {'accepted', 'settled'}:
                        raise IdempotencyConflict('submitted continuation cannot be rejected')
                    if row['status'] == 'rejected':
                        if attempts not in {0, 1}:
                            raise IdempotencyConflict('rejected continuation dispatch count conflicts')
                        return row
                    if not ((row['status'] == 'reserved' and attempts == 0)
                            or (row['status'] == 'outcome_unknown' and attempts == 1)):
                        raise IdempotencyConflict('submitted continuation cannot be rejected')
                    row['status'] = 'rejected'
                elif row['status'] != 'settled':
                    row['status'] = 'outcome_unknown'
                execute(connection, 'UPDATE research_tasks SET continuation_budget = :budget WHERE task_id = :task',
                    {'budget': rows, 'task': task_id})
                return row

            if request_usage is not None:
                raise ValueError('legacy continuation receipts cannot contain request usage')
            if status == 'settled':
                if type(charged_tokens) is not int or charged_tokens < 0:
                    raise ValueError('exact nonnegative charge required')
                if not isinstance(settlement_sha256, str) or re.fullmatch(r'[0-9a-f]{64}', settlement_sha256) is None:
                    raise ValueError('trusted unique settlement required')
            elif status == 'accepted':
                # Historical charge facts may be bound to the exact attempt;
                # they never reopen or refund a legacy reservation.
                if charged_tokens is not None and (type(charged_tokens) is not int or charged_tokens < 0):
                    raise ValueError('exact nonnegative charge required')
                if settlement_sha256 is not None:
                    raise ValueError('settlement belongs to a settled receipt')
            elif charged_tokens is not None or settlement_sha256 is not None:
                raise ValueError('unconfirmed receipt cannot return budget')
            if status == 'accepted':
                if row['run_id'] is not None and row['run_id'] != run_id:
                    raise IdempotencyConflict('continuation runtime identity conflicts')
                if row['status'] == 'settled':
                    if row['run_id'] != run_id:
                        raise IdempotencyConflict('settled continuation receipt conflicts')
                    return row
                if charged_tokens is not None:
                    if row.get('charged_tokens') is not None and row['charged_tokens'] != charged_tokens:
                        raise IdempotencyConflict('continuation charge conflicts')
                    row['charged_tokens'] = charged_tokens
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
                    # ADR-0085 P0: the ResearchTask structured progress/blocker
                    # and its Product projection are updated atomically with the
                    # budget settlement in the SAME transaction. A conversation
                    # may stay active, but the task now carries the exact
                    # blocking reason and event identity.
                    progress = _needs_attention_progress(task, row['event_key'])
                    execute(connection, "UPDATE research_tasks SET continuation_blocked_reason='continuation_needs_attention', continuation_blocked_event_key=:event, progress=:progress WHERE task_id=:task",
                        {'event': row['event_key'], 'task': task_id, 'progress': progress})
                    logger.info("continuation settled needs_attention: task=%s event=%s reservation=%s",
                        task_id, row['event_key'], reservation_id)
            execute(connection, 'UPDATE research_tasks SET continuation_budget = :budget WHERE task_id = :task',
                {'budget': rows, 'task': task_id})
            return row
