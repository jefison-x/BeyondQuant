"""ADR-0085 P2: durable task/plan/event continuation ledger (Backend seam).

Unifies the five authoritative continuation event types
(``plan_approval``/``data_ready``/``backtest_completed``/``user_resume``/
``recovery``) into ONE task-scoped ledger bound to the current
``research-execution-plan.v1`` version.

This is BYQ Domain Workflow persistence, not a second generic agent harness. It
stores no DSH private context, hidden reasoning, tool state or session journal,
and it never starts a model turn.

Authoritative-record discipline (ADR-0085 §P2 review):

* there is NO generic event-write HTTP/MCP/Browser route and no public
  ``record_continuation_event(raw_payload)`` seam. The only public entry points
  are the five named adapters below. Each takes an EXACT durable record identity
  (approval id, signal job id, backtest job id, continuation trigger id) and
  loads the decision, action, resource, owner/workspace, plan/task versions,
  references, expected postcondition, parameter digest and business idempotency
  key from persisted BYQ facts. An external caller supplies none of them.
* ``plan_approval`` reads the real ``agent_approvals`` decision/status/action/
  resource and requires the exact owner + plan-bound resource; a pending or
  forged approval can never advance the plan.
* ``data_ready`` reads the exact ``signal_producer_jobs`` row and requires a
  completed job with a validated ``signal_snapshot``; it never selects a job by
  recency.
* ``backtest_completed`` reads the exact ``backtest_jobs`` row; it never selects
  a job by recency.
* ``user_resume``/``recovery`` bind a durable BYQ continuation trigger receipt
  (a real user message or a real lost runtime turn); an arbitrary source string
  is refused.

Invariants enforced here:

* at most ONE open continuation per task, guaranteed by a PostgreSQL partial
  unique index (``WHERE admitted``) as well as the task-row lock: an in-process
  lock or a fixed retry count is never a business guarantee;
* every write compare-and-swaps the current ``plan_version`` and the bound
  ``research_tasks.version`` under one task-row lock, so a late/old event can
  never advance a newer plan;
* a replayed event is served from its durable ledger row instead of writing a
  second object; the same BYQ-minted event identity with a different body is a
  conflict, not a replay;
* a ``retry_current_action`` outcome persists a durable, claimable/settleable
  PENDING intent in this same ledger (never a second store and never a fake
  ``settled`` receipt). Until a consumer exists it stays honestly pending.
"""

from __future__ import annotations

import hashlib
import json

from .db import execute, fetch_one
from .research_continuation import _data_ready_executable
from packages.contracts.research_execution_plan import advance
from packages.contracts.research_continuation_event import (
    EVENT_TYPES,
    EVENT_VERSION,
    RESULT_STATUSES,
    bind_command_digest,
    default_expected_postcondition,
    event_identity,
    event_request_hash,
    event_result_status,
    plan_command_digest,
    reduce_continuation_event,
    validate_event,
)

# Durable statuses of a ledger event row. ``admitted``/``pending``/``claimed``
# are OPEN (the partial unique index keeps at most one per task); the rest are
# terminal for this event.
_OPEN_STATUSES = frozenset({"admitted", "pending", "claimed"})
_TERMINAL_STATUSES = frozenset({"advanced", "settled", "needs_attention"})
_LEDGER_STATUSES = _OPEN_STATUSES | _TERMINAL_STATUSES

_TRIGGER_KINDS = frozenset({"user_resume", "recovery"})
_TRIGGER_SOURCE_KINDS = {"user_resume": "user_message", "recovery": "lost_run"}
_SETTLE_OUTCOMES = frozenset({"consumed", "completed", "failed", "needs_attention"})

# Plan pending-approval action -> the agent approval action that authorizes it.
_PLAN_APPROVAL_ACTION = {
    "strategy_approve": "byq_strategy_approve",
    "backtest_task_create": "byq_backtest_task_create",
    "backtest_execute": "byq_backtest_task_execute",
}
# Resource kinds whose exact task ownership can be proven from a table.
_ARTIFACT_RESOURCE_KINDS = frozenset({"strategy_version", "strategy_approval"})


class ContinuationInProgress(Exception):
    """Another continuation is already open for this task (at-most-once)."""


class ContinuationTriggerRequired(Exception):
    """A user-resume/recovery event has no durable authoritative trigger."""


SCHEMA_DDL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS research_continuation_events (
        task_id TEXT NOT NULL REFERENCES research_tasks(task_id),
        event_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        event_version INTEGER NOT NULL,
        source_identity TEXT NOT NULL,
        owner_principal TEXT NOT NULL,
        workspace_id TEXT,
        plan_version INTEGER NOT NULL,
        task_version INTEGER NOT NULL,
        status TEXT NOT NULL,
        outcome TEXT NOT NULL,
        admitted BOOLEAN NOT NULL DEFAULT FALSE,
        request_hash TEXT NOT NULL,
        decision TEXT,
        params_digest TEXT,
        retry_action TEXT,
        retry_identity TEXT,
        claimed_at TIMESTAMPTZ,
        claimed_by TEXT,
        settled_at TIMESTAMPTZ,
        result_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (task_id, event_id)
    )
    """,
    # The business at-most-once invariant: at most one OPEN continuation per
    # task, enforced by the database, not by process memory. A retry intent
    # keeps ``admitted`` TRUE after the transaction commits, so it survives a
    # crash/restart and can be claimed/settled exactly once.
    """CREATE UNIQUE INDEX IF NOT EXISTS research_continuation_one_open
        ON research_continuation_events(task_id) WHERE admitted""",
    """CREATE INDEX IF NOT EXISTS research_continuation_events_owner
        ON research_continuation_events(owner_principal, workspace_id, task_id)""",
    """
    CREATE TABLE IF NOT EXISTS research_continuation_triggers (
        trigger_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES research_tasks(task_id),
        owner_principal TEXT NOT NULL,
        workspace_id TEXT,
        kind TEXT NOT NULL,
        source_kind TEXT NOT NULL,
        source_identity TEXT NOT NULL,
        observed_plan_version INTEGER NOT NULL,
        observed_task_version INTEGER NOT NULL,
        request_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        UNIQUE (task_id, request_hash)
    )
    """,
    """CREATE INDEX IF NOT EXISTS research_continuation_triggers_owner
        ON research_continuation_triggers(owner_principal, workspace_id, task_id)""",
]


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _digest(value: object) -> str:
    """BYQ-derived parameter digest for a deterministic command."""

    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def project_continuation_event(row: object) -> dict[str, object]:
    """Bounded Product projection of one persisted ledger row."""

    if not isinstance(row, dict):
        raise ValueError("continuation event row is invalid")
    if row.get("status") not in _LEDGER_STATUSES:
        raise ValueError("continuation event row status is invalid")
    result = row.get("result_json")
    result = result if isinstance(result, dict) else {}
    decision = result.get("decision") if isinstance(result.get("decision"), dict) else {}
    return {
        "event_id": row["event_id"],
        "event_type": row["event_type"],
        "event_version": row["event_version"],
        "status": row["status"],
        "outcome": row["outcome"],
        "plan_version": row["plan_version"],
        "task_version": row["task_version"],
        "next_stage": decision.get("next_stage"),
        "reason": decision.get("reason"),
        "retry_action": row.get("retry_action"),
    }


def project_continuation_intent(row: object) -> dict[str, object]:
    """Bounded projection of a claimable/settleable pending intent."""

    if not isinstance(row, dict):
        raise ValueError("continuation intent row is invalid")
    if row.get("status") not in _OPEN_STATUSES | {"settled"}:
        raise ValueError("continuation intent row status is invalid")
    return {
        "event_id": row["event_id"],
        "event_type": row["event_type"],
        "status": row["status"],
        "outcome": row["outcome"],
        "plan_version": row["plan_version"],
        "task_version": row["task_version"],
        "retry_action": row.get("retry_action"),
        "retry_identity": row.get("retry_identity"),
        "claimed_by": row.get("claimed_by"),
    }


def project_continuation_trigger(row: object) -> dict[str, object]:
    """Bounded projection of a durable continuation trigger receipt."""

    if not isinstance(row, dict):
        raise ValueError("continuation trigger row is invalid")
    if row.get("kind") not in _TRIGGER_KINDS:
        raise ValueError("continuation trigger kind is invalid")
    return {
        "trigger_id": row["trigger_id"],
        "task_id": row["task_id"],
        "kind": row["kind"],
        "source_kind": row["source_kind"],
        "observed_plan_version": row["observed_plan_version"],
        "observed_task_version": row["observed_task_version"],
    }


def _bounded_result(decision: dict) -> dict:
    return {
        "outcome": decision["outcome"], "reason": decision["reason"],
        "next_stage": decision.get("next_stage"), "status": decision.get("status"),
        "expected_postcondition": decision.get("expected_postcondition"),
        "retry_action": decision.get("retry_action"),
    }


class ResearchContinuationLedgerMixin:
    """Durable task/plan/event ledger with a deterministic server-side reducer.

    The five public adapters are the ONLY way an event enters the ledger. They
    accept exact durable record identities, never a raw event body.
    """

    # ------------------------------------------------------------------ #
    # Named authoritative adapters
    # ------------------------------------------------------------------ #

    def record_plan_approval_event(self, task_id: str, approval_id: object, *,
                                   trusted_context: dict) -> dict:
        """Record the real human decision stored on an ``agent_approvals`` row."""

        approval_id = self._require_agent_approval_id(approval_id)
        return self._record_event(
            task_id, event_type="plan_approval", source_identity=approval_id,
            resolver=lambda connection, task, plan: self._resolve_plan_approval(
                connection, task, plan, approval_id),
            trusted_context=trusted_context)

    def record_data_ready_event(self, task_id: str, signal_job_id: object, *,
                                trusted_context: dict) -> dict:
        """Record a completed+validated signal job by its EXACT job identity."""

        signal_job_id = self._require_identity(signal_job_id, "signal job")
        return self._record_event(
            task_id, event_type="data_ready", source_identity=signal_job_id,
            resolver=lambda connection, task, plan: self._resolve_data_ready(
                connection, task, plan, signal_job_id),
            trusted_context=trusted_context)

    def record_backtest_completed_event(self, task_id: str, backtest_job_id: object, *,
                                        trusted_context: dict) -> dict:
        """Record a terminal backtest job by its EXACT job identity."""

        backtest_job_id = self._require_identity(backtest_job_id, "backtest job")
        return self._record_event(
            task_id, event_type="backtest_completed", source_identity=backtest_job_id,
            resolver=lambda connection, task, plan: self._resolve_backtest_completed(
                connection, task, plan, backtest_job_id),
            trusted_context=trusted_context)

    def record_user_resume_event(self, task_id: str, trigger_id: object, *,
                                 trusted_context: dict) -> dict:
        """Consume a durable user-resume trigger receipt (a real user message)."""

        return self._record_trigger_event(task_id, trigger_id, kind="user_resume",
                                          trusted_context=trusted_context)

    def record_recovery_event(self, task_id: str, trigger_id: object, *,
                              trusted_context: dict) -> dict:
        """Consume a durable recovery trigger receipt (a real lost runtime turn)."""

        return self._record_trigger_event(task_id, trigger_id, kind="recovery",
                                          trusted_context=trusted_context)

    # ------------------------------------------------------------------ #
    # Durable trigger receipts
    # ------------------------------------------------------------------ #

    def register_continuation_trigger(self, task_id: str, payload: object, *,
                                      trusted_context: dict) -> dict:
        """Register a durable user-resume/recovery trigger from a real record.

        ``user_resume`` requires an exact owner-authored user message in the
        task's bound conversation. ``recovery`` requires an exact runtime turn
        owned by the same owner/workspace/session. The trigger stores the
        observed plan/task versions, so a late trigger is provably stale.
        """

        from .research import ResearchNotFound

        if not isinstance(payload, dict) or set(payload) != {"kind", "source_identity"}:
            raise ValueError("continuation trigger request has invalid fields")
        kind = payload["kind"]
        if kind not in _TRIGGER_KINDS:
            raise ValueError("continuation trigger kind is invalid")
        source_identity = self._require_identity(payload["source_identity"], "trigger source")
        request_hash = _hash({"kind": kind, "source_identity": source_identity})
        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=True)
            plan_row = self._load_current_plan(connection, task["task_id"], lock=True)
            if plan_row is None:
                raise ResearchNotFound("research execution plan not found")
            plan = plan_row["plan"]
            existing = fetch_one(connection, """SELECT * FROM research_continuation_triggers
                WHERE task_id = :task AND request_hash = :hash""",
                {"task": task["task_id"], "hash": request_hash})
            if existing is not None:
                return project_continuation_trigger(existing)
            source_kind = self._validate_trigger_source(
                connection, task, kind=kind, source_identity=source_identity)
            trigger_id = "continuation_trigger_" + hashlib.sha256(
                f"{kind}\x00{source_identity}".encode()).hexdigest()[:32]
            execute(connection, """INSERT INTO research_continuation_triggers
                (trigger_id, task_id, owner_principal, workspace_id, kind, source_kind,
                 source_identity, observed_plan_version, observed_task_version, request_hash,
                 created_at)
                VALUES (:trigger_id, :task, :owner, :workspace, :kind, :source_kind,
                        :source, :plan_version, :task_version, :hash, :now)""",
                {"trigger_id": trigger_id, "task": task["task_id"],
                 "owner": task["owner_principal"], "workspace": task["workspace_id"],
                 "kind": kind, "source_kind": source_kind, "source": source_identity,
                 "plan_version": plan["plan_version"], "task_version": plan["task_version"],
                 "hash": request_hash, "now": _now()})
            return project_continuation_trigger({
                "trigger_id": trigger_id, "task_id": task["task_id"], "kind": kind,
                "source_kind": source_kind, "observed_plan_version": plan["plan_version"],
                "observed_task_version": plan["task_version"]})

    def list_continuation_triggers(self, task_id: str, *, trusted_context: dict) -> dict:
        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=False)
            rows = execute(connection, """SELECT * FROM research_continuation_triggers
                WHERE task_id = :task ORDER BY created_at, trigger_id""",
                {"task": task["task_id"]})
            return {"task_id": task["task_id"],
                    "triggers": [project_continuation_trigger(row) for row in (rows or [])]}

    # ------------------------------------------------------------------ #
    # Pending intent claim/settle (crash-safe, idempotent, at-most-once)
    # ------------------------------------------------------------------ #

    def claim_continuation_intent(self, task_id: str, event_id: object, *,
                                  trusted_context: dict) -> dict:
        """Idempotently claim the task's open pending intent for consumption."""

        from .research import ResearchNotFound

        event_id = self._require_identity(event_id, "event")
        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=True)
            row = self._load_event(connection, task["task_id"], event_id, lock=True)
            if row is None:
                raise ResearchNotFound("continuation intent not found")
            if row["status"] == "claimed":
                return project_continuation_intent(row)
            if row["status"] != "pending" or not row["admitted"]:
                raise ValueError("continuation intent is not claimable")
            execute(connection, """UPDATE research_continuation_events
                SET status = 'claimed', claimed_at = :now, claimed_by = :owner, updated_at = :now
                WHERE task_id = :task AND event_id = :event""",
                {"now": _now(), "owner": task["owner_principal"],
                 "task": task["task_id"], "event": event_id})
            return project_continuation_intent(
                self._load_event(connection, task["task_id"], event_id, lock=False))

    def settle_continuation_intent(self, task_id: str, event_id: object, outcome: object, *,
                                   trusted_context: dict) -> dict:
        """Idempotently settle a claimed/pending intent, releasing at-most-once."""

        from .research import IdempotencyConflict, ResearchNotFound

        event_id = self._require_identity(event_id, "event")
        if outcome not in _SETTLE_OUTCOMES:
            raise ValueError("continuation intent outcome is invalid")
        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=True)
            row = self._load_event(connection, task["task_id"], event_id, lock=True)
            if row is None:
                raise ResearchNotFound("continuation intent not found")
            if row["status"] == "settled":
                if row["outcome"] != outcome:
                    raise IdempotencyConflict("continuation intent settlement conflicts")
                return project_continuation_intent(row)
            if row["status"] not in {"pending", "claimed"}:
                raise ValueError("continuation intent is not settleable")
            execute(connection, """UPDATE research_continuation_events
                SET admitted = FALSE, status = 'settled', outcome = :outcome,
                    settled_at = :now, updated_at = :now
                WHERE task_id = :task AND event_id = :event""",
                {"outcome": outcome, "now": _now(),
                 "task": task["task_id"], "event": event_id})
            return project_continuation_intent(
                self._load_event(connection, task["task_id"], event_id, lock=False))

    # ------------------------------------------------------------------ #
    # Bounded read
    # ------------------------------------------------------------------ #

    def list_continuation_events(self, task_id: str, *, trusted_context: dict, limit: int = 50) -> dict:
        """Bounded, owner-scoped read of the task's continuation ledger."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("continuation event limit must be between 1 and 100")
        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=False)
            rows = execute(connection, """SELECT * FROM research_continuation_events
                WHERE task_id = :task ORDER BY created_at, event_id LIMIT :limit""",
                {"task": task["task_id"], "limit": limit})
            if rows is None:
                rows = []
            return {"task_id": task["task_id"],
                    "events": [project_continuation_event(row) for row in rows]}

    # ------------------------------------------------------------------ #
    # Private ledger primitive
    # ------------------------------------------------------------------ #

    def _record_event(self, task_id: str, *, event_type: str, source_identity: str,
                      resolver, trusted_context: dict) -> dict:
        """Admit and reduce one authoritative event built from persisted facts.

        ``resolver`` runs INSIDE the transaction and returns the server-derived
        facts, references, expected postcondition, parameter digest, observed
        versions and decision. Nothing here comes from an external caller.
        """

        from .research import ResearchNotFound

        if event_type not in EVENT_TYPES:
            raise ValueError("continuation event type is unknown")
        event_id = event_identity(
            event_type=event_type, source_identity=source_identity, event_version=EVENT_VERSION)
        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=True)
            plan_row = self._load_current_plan(connection, task["task_id"], lock=True)
            if plan_row is None:
                raise ResearchNotFound("research execution plan not found")
            plan = plan_row["plan"]
            # Replay is checked on the BYQ-minted event identity BEFORE any
            # derivation, so an exact replay of an already-recorded source is
            # served from its durable row even after the plan advanced. The
            # source records (terminal approval/job, immutable message/turn) are
            # authoritative and never mutate underneath a recorded identity.
            existing = self._load_event(connection, task["task_id"], event_id, lock=True)
            if existing is not None:
                return project_continuation_event(existing)
            resolved = resolver(connection, task, plan)
            request_hash = _hash({
                "event_type": event_type, "source_identity": source_identity,
                "plan_version": resolved["plan_version"], "task_version": resolved["task_version"],
                "decision": resolved.get("decision"), "params_digest": resolved.get("params_digest"),
            })

            stale = (resolved["plan_version"] != plan["plan_version"]
                     or resolved["task_version"] != plan["task_version"])
            if stale:
                self._insert_event(
                    connection, task, event_id, event_type, source_identity, request_hash,
                    plan_version=resolved["plan_version"], task_version=resolved["task_version"],
                    decision=resolved.get("decision"), params_digest=resolved.get("params_digest"),
                    admitted=False, status="needs_attention", outcome="needs_attention",
                    retry_action=None, retry_identity=None,
                    decision_body={"outcome": "needs_attention", "reason": "stale_event",
                                   "next_stage": None})
                return project_continuation_event(
                    self._load_event(connection, task["task_id"], event_id))

            event = {
                "schema_version": "research-continuation-event.v1",
                "event_id": event_id, "event_type": event_type,
                "event_version": EVENT_VERSION, "source_identity": source_identity,
                "task_id": task["task_id"], "owner_principal": task["owner_principal"],
                "workspace_id": task["workspace_id"],
                "plan_version": resolved["plan_version"], "task_version": resolved["task_version"],
                "references": resolved["references"],
                "expected_postcondition": resolved["expected_postcondition"], "request_hash": "",
            }
            if resolved.get("decision") is not None:
                event["decision"] = resolved["decision"]
            if resolved.get("params_digest") is not None:
                event["params_digest"] = resolved["params_digest"]
            event["request_hash"] = event_request_hash(event)
            validate_event(event)

            admitted = fetch_one(connection, """SELECT event_id FROM research_continuation_events
                WHERE task_id = :task AND admitted FOR UPDATE""",
                {"task": task["task_id"]})
            if admitted is not None:
                raise ContinuationInProgress("a continuation is already open for this task")

            self._insert_event(
                connection, task, event_id, event_type, source_identity, request_hash,
                plan_version=resolved["plan_version"], task_version=resolved["task_version"],
                decision=resolved.get("decision"), params_digest=resolved.get("params_digest"),
                admitted=True, status="admitted", outcome="admitted",
                retry_action=None, retry_identity=None,
                decision_body={"outcome": "admitted", "reason": "admitted", "next_stage": None})
            decision = reduce_continuation_event(plan, event, facts=resolved["facts"])
            if decision["outcome"] == "advance":
                self._apply_plan_advance(connection, task, plan_row, event, decision)
            status = event_result_status(decision["outcome"])
            if status not in RESULT_STATUSES:
                raise ValueError("continuation result status is unknown")
            retry_action = decision.get("retry_action") if status == "pending" else None
            retry_identity = decision.get("retry_identity") if status == "pending" else None
            # A retry intent stays OPEN (``admitted`` TRUE) so it survives a
            # crash/restart and is claimable exactly once. Every other outcome is
            # terminal for this event and releases the at-most-once slot.
            execute(connection, """UPDATE research_continuation_events
                SET admitted = :admitted, status = :status, outcome = :outcome,
                    retry_action = :retry_action, retry_identity = :retry_identity,
                    result_json = :result, updated_at = :now
                WHERE task_id = :task AND event_id = :event""",
                {"admitted": status == "pending", "status": status, "outcome": decision["outcome"],
                 "retry_action": retry_action, "retry_identity": retry_identity,
                 "result": {"decision": _bounded_result(decision), "event_type": event_type},
                 "now": _now(), "task": task["task_id"], "event": event_id})
            return project_continuation_event(
                self._load_event(connection, task["task_id"], event_id))

    def _record_trigger_event(self, task_id: str, trigger_id: object, *, kind: str,
                              trusted_context: dict) -> dict:
        from .research import ResearchNotFound

        trigger_id = self._require_identity(trigger_id, "trigger")

        def resolver(connection, task, plan):
            trigger = fetch_one(connection, """SELECT * FROM research_continuation_triggers
                WHERE trigger_id = :id AND task_id = :task AND owner_principal = :owner""",
                {"id": trigger_id, "task": task["task_id"], "owner": task["owner_principal"]})
            if trigger is None or trigger["kind"] != kind:
                raise ResearchNotFound("continuation trigger not found")
            return {
                "facts": {}, "references": dict(plan["references"]),
                "expected_postcondition": default_expected_postcondition(plan=plan, event_type=kind),
                "params_digest": None, "decision": None,
                "plan_version": trigger["observed_plan_version"],
                "task_version": trigger["observed_task_version"],
            }

        return self._record_event(
            task_id, event_type=kind, source_identity=trigger_id, resolver=resolver,
            trusted_context=trusted_context)

    # ------------------------------------------------------------------ #
    # Authoritative resolvers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _resolve_plan_approval(connection, task, plan, approval_id: str) -> dict:
        row = fetch_one(connection, """SELECT a.*, r.session_id AS source_session_id,
                r.owner_principal AS run_owner
            FROM agent_approvals a JOIN agent_runs r ON r.run_id = a.run_id
            WHERE a.approval_id = :id""", {"id": approval_id})
        if row is None:
            raise ValueError("plan approval record not found")
        if row["owner_principal"] != task["owner_principal"] or row["run_owner"] != task["owner_principal"]:
            raise ValueError("plan approval owner does not match the task")
        if row["status"] not in {"approved", "rejected"}:
            raise ValueError("plan approval has no authoritative human decision")
        pending = plan.get("approval")
        if not isinstance(pending, dict):
            raise ValueError("plan has no pending approval requirement")
        if _PLAN_APPROVAL_ACTION.get(pending["action"]) != row["action"]:
            raise ValueError("plan approval action does not match the plan gate")
        if row.get("resource_type") != pending["resource_kind"]:
            raise ValueError("plan approval resource kind does not match the plan gate")
        reference = (plan["references"] or {}).get(pending["resource_kind"])
        if (not isinstance(reference, dict)
                or reference.get(pending["resource_kind"]) != row.get("resource_id")):
            raise ValueError("plan approval resource is not bound to the plan reference")
        _require_resource_owner(connection, task, pending["resource_kind"], row["resource_id"])
        derived = plan_command_digest(
            plan, action=pending["action"], resource_kind=pending["resource_kind"],
            resource_id=pending["resource_id"])
        if pending.get("params_digest") not in {None, derived}:
            raise ValueError("plan approval parameter digest does not match the plan command")
        return {
            "facts": {}, "references": dict(plan["references"]),
            "expected_postcondition": default_expected_postcondition(plan=plan, event_type="plan_approval"),
            "params_digest": derived, "decision": row["status"],
            "plan_version": plan["plan_version"], "task_version": plan["task_version"],
        }

    @staticmethod
    def _resolve_data_ready(connection, task, plan, signal_job_id: str) -> dict:
        job = fetch_one(connection, """SELECT j.* FROM signal_producer_jobs j
            WHERE j.job_id = :job AND j.task_id = :task AND j.owner_principal = :owner""",
            {"job": signal_job_id, "task": task["task_id"], "owner": task["owner_principal"]})
        if job is None:
            raise ValueError("data-ready event source job does not belong to this task")
        if job["status"] != "completed":
            raise ValueError("data-ready event source job is not completed")
        snapshot_id = job.get("result_artifact_id")
        artifact = fetch_one(connection, """SELECT * FROM artifacts
            WHERE artifact_id = :artifact AND task_id = :task AND owner_principal = :owner
              AND workspace_id = :workspace AND kind = 'signal_snapshot' AND status = 'validated'""",
            {"artifact": snapshot_id, "task": task["task_id"], "owner": task["owner_principal"],
             "workspace": task["workspace_id"]})
        if artifact is None:
            raise ValueError("data-ready event has no validated signal snapshot")
        executable = _data_ready_executable(connection, task, job)
        backtest_task_id = executable.get("backtest_task_id")
        if not isinstance(backtest_task_id, str) or not isinstance(snapshot_id, str):
            raise ValueError("data-ready event could not derive its backtest identity")
        references = {
            "research_task": {"research_task": task["task_id"]},
            "conversation": {"conversation": task["conversation_id"]},
            "signal_producer_job": {"signal_producer_job": job["job_id"]},
            "signal_snapshot": {"signal_snapshot": snapshot_id},
            "backtest_task": {"backtest_task": backtest_task_id},
        }
        for kind, value in (
            ("strategy_version", (executable.get("references") or {}).get("strategy_version_artifact_id")),
            ("strategy_approval", (executable.get("references") or {}).get("approval_artifact_id")),
            ("stock_pool_snapshot", (executable.get("references") or {}).get("stock_pool_snapshot_id")),
            ("backtest_job", (executable.get("references") or {}).get("backtest_job_id")),
            ("backtest_result", (executable.get("references") or {}).get("result_artifact_id")),
        ):
            if isinstance(value, str):
                references[kind] = {kind: value}
        facts = {
            "backtest_task_id": backtest_task_id, "phase": executable.get("phase"),
            "next_action": executable.get("next_action"), "signal_snapshot_id": snapshot_id,
        }
        params_digest = _digest({
            "task_id": task["task_id"], "plan_version": plan["plan_version"],
            "task_version": plan["task_version"], "next_action": executable.get("next_action"),
            "backtest_task_id": backtest_task_id, "signal_snapshot_id": snapshot_id,
            "references": references,
        })
        return {
            "facts": facts, "references": references,
            "expected_postcondition": default_expected_postcondition(
                plan=plan, event_type="data_ready", next_action=executable.get("next_action")),
            "params_digest": params_digest, "decision": None,
            "plan_version": plan["plan_version"], "task_version": plan["task_version"],
        }

    @staticmethod
    def _resolve_backtest_completed(connection, task, plan, backtest_job_id: str) -> dict:
        job = fetch_one(connection, """SELECT * FROM backtest_jobs
            WHERE job_id = :job AND task_id = :task AND owner_principal = :owner""",
            {"job": backtest_job_id, "task": task["task_id"], "owner": task["owner_principal"]})
        if job is None:
            raise ValueError("backtest-completed source job does not belong to this task")
        if job["status"] not in {"completed", "failed", "cancelled"}:
            raise ValueError("backtest-completed source job is not terminal")
        references = {
            "research_task": {"research_task": task["task_id"]},
            "conversation": {"conversation": task["conversation_id"]},
            "backtest_job": {"backtest_job": job["job_id"]},
        }
        result_id = job.get("result_artifact_id")
        if isinstance(result_id, str):
            references["backtest_result"] = {"backtest_result": result_id}
        facts = {
            "backtest_job_id": job["job_id"], "backtest_result_id": result_id,
            "terminal_status": job["status"],
            "next_action": "review_result" if job["status"] == "completed" else "review_failure",
        }
        params_digest = _digest({
            "task_id": task["task_id"], "plan_version": plan["plan_version"],
            "task_version": plan["task_version"], "backtest_job_id": job["job_id"],
            "result_artifact_id": result_id,
        })
        return {
            "facts": facts, "references": references,
            "expected_postcondition": default_expected_postcondition(
                plan=plan, event_type="backtest_completed"),
            "params_digest": params_digest, "decision": None,
            "plan_version": plan["plan_version"], "task_version": plan["task_version"],
        }

    # ------------------------------------------------------------------ #
    # Persistence helpers
    # ------------------------------------------------------------------ #

    def _validate_trigger_source(self, connection, task, *, kind: str, source_identity: str) -> str:
        source_kind = _TRIGGER_SOURCE_KINDS[kind]
        if kind == "user_resume":
            row = fetch_one(connection, """SELECT m.* FROM product_conversation_messages m
                WHERE m.message_id = :id AND m.conversation_id = :conversation
                  AND m.owner_principal = :owner AND m.role = 'user'""",
                {"id": source_identity, "conversation": task["conversation_id"],
                 "owner": task["owner_principal"]})
            if row is None:
                raise ContinuationTriggerRequired(
                    "user-resume trigger requires an exact owner-authored user message")
            return source_kind
        row = fetch_one(connection, """SELECT t.* FROM agent_runtime_turns t
            JOIN product_conversations c ON c.runtime_session_id = t.session_id
            WHERE t.root_run_id = :id AND t.owner_principal = :owner
              AND t.workspace_id = :workspace AND c.conversation_id = :conversation
              AND c.owner_principal = :owner""",
            {"id": source_identity, "owner": task["owner_principal"],
             "workspace": task["workspace_id"], "conversation": task["conversation_id"]})
        if row is None:
            raise ContinuationTriggerRequired(
                "recovery trigger requires an exact lost runtime turn")
        return source_kind

    def _insert_event(self, connection, task, event_id, event_type, source_identity,
                      request_hash, *, plan_version, task_version, decision, params_digest,
                      admitted, status, outcome, retry_action, retry_identity,
                      decision_body) -> None:
        execute(connection, """INSERT INTO research_continuation_events
            (task_id, event_id, event_type, event_version, source_identity, owner_principal,
             workspace_id, plan_version, task_version, status, outcome, admitted, request_hash,
             decision, params_digest, retry_action, retry_identity, result_json,
             created_at, updated_at)
            VALUES (:task_id, :event_id, :event_type, :event_version, :source_identity, :owner,
                    :workspace, :plan_version, :task_version, :status, :outcome, :admitted,
                    :request_hash, :decision, :params_digest, :retry_action, :retry_identity,
                    :result, :now, :now)""",
            {"task_id": task["task_id"], "event_id": event_id,
             "event_type": event_type, "event_version": EVENT_VERSION,
             "source_identity": source_identity, "owner": task["owner_principal"],
             "workspace": task["workspace_id"], "plan_version": plan_version,
             "task_version": task_version, "status": status, "outcome": outcome,
             "admitted": admitted, "request_hash": request_hash,
             "decision": decision, "params_digest": params_digest,
             "retry_action": retry_action, "retry_identity": retry_identity,
             "result": {"decision": _bounded_result(decision_body), "event_type": event_type},
             "now": _now()})

    @staticmethod
    def _load_event(connection, task_id: str, event_id: str, *, lock: bool = False):
        clause = "FOR UPDATE" if lock else ""
        return fetch_one(connection, f"""SELECT * FROM research_continuation_events
            WHERE task_id = :task AND event_id = :event {clause}""",
            {"task": task_id, "event": event_id})

    def _apply_plan_advance(self, connection, task, plan_row, event, decision) -> None:
        """CAS the plan to the reducer-derived target with the BYQ-minted key."""

        from .research import InvalidTransition

        plan = plan_row["plan"]
        idempotency_key = f"cont-{event['event_id']}"
        try:
            advanced = advance(
                plan, expected_plan_version=plan["plan_version"],
                expected_task_version=plan["task_version"],
                next_stage=decision["next_stage"], iteration=plan["iteration"],
                status=decision["status"],
                expected_postcondition=decision["expected_postcondition"],
                idempotency_key=idempotency_key, references=decision["references"],
                prerequisites=None, approval=decision["approval"],
                last_progress_identity=event["request_hash"])
            # The reducer never carries a caller-supplied digest: stamp the exact
            # BYQ-derived command digest onto the target approval requirement.
            advanced = bind_command_digest(advanced)
        except ValueError as error:
            raise InvalidTransition(str(error)) from error
        cas_row = fetch_one(connection, """UPDATE research_execution_plans SET
            plan_version = :plan_version, task_version = :task_version, stage = :stage,
            iteration = :iteration, status = :status, next_action = :next_action,
            plan = :plan, idempotency_key = :idempotency_key, request_hash = :request_hash,
            legacy_reason = NULL, updated_at = :now
            WHERE task_id = :task_id AND plan_version = :expected_plan_version
              AND task_version = :expected_task_version
            RETURNING task_id""",
            {"plan_version": advanced["plan_version"], "task_version": advanced["task_version"],
             "stage": advanced["stage"], "iteration": advanced["iteration"],
             "status": advanced["status"], "next_action": advanced["next_action"],
             "plan": advanced, "idempotency_key": idempotency_key,
             "request_hash": event["request_hash"], "now": _now(),
             "task_id": task["task_id"], "expected_plan_version": plan["plan_version"],
             "expected_task_version": plan["task_version"]})
        if cas_row is None:
            raise InvalidTransition("research execution plan compare-and-swap failed")

    # ------------------------------------------------------------------ #
    # Validation helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _require_identity(value: object, field: str) -> str:
        import re
        if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) is None:
            raise ValueError(f"continuation {field} identity is invalid")
        return value

    @classmethod
    def _require_agent_approval_id(cls, value: object) -> str:
        import re
        if not isinstance(value, str) or re.fullmatch(r"agent_approval_[0-9a-f]{32}", value) is None:
            raise ValueError("continuation approval identity is invalid")
        return value


def _require_resource_owner(connection, task, resource_kind: str, resource_id: object) -> None:
    """Prove an approval resource belongs to this exact task when provable."""

    if resource_kind in _ARTIFACT_RESOURCE_KINDS:
        row = fetch_one(connection, """SELECT artifact_id FROM artifacts
            WHERE artifact_id = :id AND task_id = :task AND owner_principal = :owner
              AND workspace_id = :workspace""",
            {"id": resource_id, "task": task["task_id"], "owner": task["owner_principal"],
             "workspace": task["workspace_id"]})
        if row is None:
            raise ValueError("plan approval resource does not belong to this task")
