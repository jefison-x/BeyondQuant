"""ADR-0085 P1: durable, task-scoped ``research-execution-plan.v1`` state.

This is BYQ Domain Workflow persistence, not a second generic agent harness. It
stores no DSH private context, hidden reasoning, tool state or session journal.

Invariants enforced here (the pure contract owns the closed vocabulary, legal
stage/action transitions and approval/reference/postcondition shapes):

* at most ONE current plan per ResearchTask (``task_id`` primary key);
* every write compare-and-swaps BOTH the persisted ``plan_version`` and the
  bound ``research_tasks.version`` under one task-row lock, so a stale model
  turn, old event or old generation can never advance a newer plan;
* a replayed exact command is served from a durable receipt instead of writing
  a second object (at-most-once business idempotency).

These methods are an INTERNAL Backend seam for the ADR-0085 deterministic
reducer. They are deliberately NOT exposed as agent-facing HTTP/MCP write routes:
a model or ordinary agent must never submit ``next_stage``/``status`` and act as
the workflow Router. P1 ships the contract, persistence/CAS and this seam; P2
wires the authoritative approval/data-ready/backtest/user-resume/recovery events
into the reducer, which derives the next state server-side.
"""

from __future__ import annotations

import hashlib
import json

from .db import execute, fetch_one
from packages.contracts.research_execution_plan import (
    advance,
    new_plan,
    validate_plan,
)

_KEY_MAX = 128


SCHEMA_DDL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS research_execution_plans (
        task_id TEXT PRIMARY KEY REFERENCES research_tasks(task_id),
        owner_principal TEXT NOT NULL,
        workspace_id TEXT,
        conversation_id TEXT NOT NULL,
        plan_version INTEGER NOT NULL,
        task_version INTEGER NOT NULL,
        stage TEXT NOT NULL,
        iteration INTEGER NOT NULL,
        status TEXT NOT NULL,
        next_action TEXT NOT NULL,
        plan JSONB NOT NULL,
        idempotency_key TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    """CREATE INDEX IF NOT EXISTS research_execution_plans_owner
        ON research_execution_plans(owner_principal, workspace_id)""",
    """
    CREATE TABLE IF NOT EXISTS research_execution_plan_receipts (
        task_id TEXT NOT NULL REFERENCES research_tasks(task_id),
        idempotency_key TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        plan_version INTEGER NOT NULL,
        result_json JSONB NOT NULL,
        PRIMARY KEY (task_id, idempotency_key)
    )
    """,
]


def project_execution_plan(plan: object) -> dict[str, object]:
    """Bounded, closed Product projection of a persisted plan.

    Product surfaces only need the workflow state a user can act on: the exact
    stage/status/iteration, the bounded enum next action, the approval summary
    and the expected postcondition. Internal execution identity
    (owner/workspace/conversation binding, raw idempotency key), references,
    prerequisites, progress identity and tool capabilities are deliberately
    omitted so the browser is never shown or granted execution authority.
    """

    # Fail closed: a persisted row or durable receipt that is corrupt, partial
    # or has been tampered with must never be projected as if it were valid.
    # Every projection (including a receipt replay) runs the closed contract
    # first, then builds the bounded projection from the VERIFIED object.
    verified = validate_plan(plan)
    return {
        "schema_version": verified["schema_version"],
        "task_id": verified["task_id"],
        "plan_version": verified["plan_version"],
        "task_version": verified["task_version"],
        "stage": verified["stage"],
        "iteration": verified["iteration"],
        "status": verified["status"],
        "next_action": verified["next_action"],
        "expected_postcondition": verified["expected_postcondition"],
        "approval": verified["approval"],
    }


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _key(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _KEY_MAX:
        raise ValueError("research execution plan idempotency key is invalid")
    return value


def _create_request(payload: object) -> dict[str, object]:
    allowed = {"idempotency_key", "references", "iteration", "last_progress_identity"}
    if not isinstance(payload, dict) or "idempotency_key" not in payload or set(payload) - allowed:
        raise ValueError("invalid research execution plan create request")
    _key(payload["idempotency_key"])
    return {field: payload[field] for field in allowed if field in payload}


def _advance_request(payload: object) -> dict[str, object]:
    required = {"expected_plan_version", "expected_task_version", "next_stage",
                "iteration", "status", "expected_postcondition", "idempotency_key"}
    allowed = required | {"references", "prerequisites", "approval", "last_progress_identity"}
    if not isinstance(payload, dict) or not required <= set(payload) or set(payload) - allowed:
        raise ValueError("invalid research execution plan advance request")
    for field in ("expected_plan_version", "expected_task_version", "iteration"):
        value = payload[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"research execution plan {field} is invalid")
    for field in ("next_stage", "status", "expected_postcondition"):
        if not isinstance(payload[field], str) or not payload[field]:
            raise ValueError(f"research execution plan {field} is invalid")
    _key(payload["idempotency_key"])
    request = {field: payload[field] for field in required}
    for field in ("references", "prerequisites", "approval"):
        if field in payload:
            request[field] = payload[field]
    request["last_progress_identity"] = payload.get("last_progress_identity")
    return request


def _request_hash(task_id: str, request: dict[str, object]) -> str:
    """Deterministic request identity for at-most-once replay.

    It depends ONLY on the immutable task id and the caller's request body, never
    on the mutable current ``research_tasks.version``. An advance request already
    carries its own ``expected_task_version`` binding, so the same request replays
    to the same receipt even after later task transitions move the task version.
    """

    return _hash({"task_id": task_id, "request": request})


class ResearchExecutionPlanMixin:
    """Durable one-current-plan-per-task ledger with task/plan version CAS."""

    @staticmethod
    def _plan_task(connection, task_id, context, *, lock: bool):
        from .research import ResearchNotFound

        owner = context.get("owner_principal")
        workspace = context.get("workspace_id")
        if not owner or not workspace:
            raise ValueError("research execution plan requires its authenticated owner")
        clause = "FOR UPDATE" if lock else "FOR SHARE"
        task = fetch_one(connection, f"""SELECT * FROM research_tasks
            WHERE task_id = :task AND owner_principal = :owner AND workspace_id = :workspace
            {clause}""", {"task": task_id, "owner": owner, "workspace": workspace})
        if task is None:
            raise ResearchNotFound("research task not found")
        return task

    @staticmethod
    def _require_conversation(task: dict) -> str:
        conversation_id = task.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise ValueError("research execution plan requires the bound conversation")
        return conversation_id

    def _load_current_plan(self, connection, task_id: str, *, lock: bool):
        clause = "FOR UPDATE" if lock else ""
        return fetch_one(connection,
            f"SELECT * FROM research_execution_plans WHERE task_id = :task {clause}",
            {"task": task_id})

    def create_execution_plan(self, task_id: str, payload: object, *, trusted_context: dict,
                              require_active_grant: bool = False,
                              bind_grant_references: bool = False) -> dict:
        from .research import IdempotencyConflict, InvalidTransition

        request = _create_request(payload)
        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=True)
            if require_active_grant:
                raise InvalidTransition(
                    "a continuation permission cannot authorize execution plan creation")
            if bind_grant_references:
                raise InvalidTransition(
                    "execution plan references must be provided by the foreground caller")
            conversation_id = self._require_conversation(task)
            if task["status"] in {"completed", "failed", "cancelled"}:
                raise InvalidTransition("a terminal research task cannot start an execution plan")
            references = request.get("references")
            request_hash = _request_hash(task["task_id"], request)
            existing = self._load_current_plan(connection, task["task_id"], lock=True)
            if existing is not None:
                if (existing["idempotency_key"] == request["idempotency_key"]
                        and existing["request_hash"] == request_hash):
                    return project_execution_plan(existing["plan"])
                raise IdempotencyConflict("a current research execution plan already exists for this task")
            plan = new_plan(
                task_id=task["task_id"], owner_principal=task["owner_principal"],
                workspace_id=task["workspace_id"], conversation_id=conversation_id,
                task_version=task["version"], idempotency_key=request["idempotency_key"],
                references=references, iteration=request.get("iteration", 1),
                last_progress_identity=request.get("last_progress_identity"))
            execute(connection, """INSERT INTO research_execution_plans
                (task_id, owner_principal, workspace_id, conversation_id, plan_version,
                 task_version, stage, iteration, status, next_action, plan, idempotency_key,
                 request_hash, created_at, updated_at)
                VALUES (:task_id, :owner, :workspace, :conversation, :plan_version,
                        :task_version, :stage, :iteration, :status, :next_action, :plan,
                        :idempotency_key, :request_hash, :now, :now)""",
                {"task_id": task["task_id"], "owner": task["owner_principal"],
                 "workspace": task["workspace_id"], "conversation": conversation_id,
                 "plan_version": plan["plan_version"], "task_version": plan["task_version"],
                 "stage": plan["stage"], "iteration": plan["iteration"], "status": plan["status"],
                 "next_action": plan["next_action"], "plan": plan,
                 "idempotency_key": request["idempotency_key"], "request_hash": request_hash,
                 "now": _now()})
            return project_execution_plan(plan)

    def get_execution_plan(self, task_id: str, *, trusted_context: dict) -> dict:
        from .research import ResearchNotFound

        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=False)
            row = self._load_current_plan(connection, task["task_id"], lock=False)
            if row is None:
                raise ResearchNotFound("research execution plan not found")
            return project_execution_plan(row["plan"])

    def advance_execution_plan(self, task_id: str, payload: object, *, trusted_context: dict) -> dict:
        from .research import IdempotencyConflict, InvalidTransition, ResearchNotFound

        request = _advance_request(payload)
        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=True)
            request_hash = _request_hash(task["task_id"], request)
            existing = self._load_current_plan(connection, task["task_id"], lock=True)
            if existing is None:
                raise ResearchNotFound("research execution plan not found")
            receipt = fetch_one(connection, """SELECT * FROM research_execution_plan_receipts
                WHERE task_id = :task AND idempotency_key = :key""",
                {"task": task["task_id"], "key": request["idempotency_key"]})
            if receipt is not None:
                if receipt["request_hash"] != request_hash:
                    raise IdempotencyConflict("research execution plan idempotency key was reused")
                return project_execution_plan(receipt["result_json"])
            if existing["plan_version"] != request["expected_plan_version"]:
                raise InvalidTransition("research execution plan version is stale")
            if task["version"] != request["expected_task_version"]:
                raise InvalidTransition("research execution task version is stale")
            try:
                advanced = advance(
                    existing["plan"],
                    expected_plan_version=request["expected_plan_version"],
                    expected_task_version=request["expected_task_version"],
                    next_stage=request["next_stage"], iteration=request["iteration"],
                    status=request["status"],
                    expected_postcondition=request["expected_postcondition"],
                    idempotency_key=request["idempotency_key"],
                    references=request.get("references"),
                    prerequisites=request.get("prerequisites"),
                    approval=request.get("approval"),
                    last_progress_identity=request.get("last_progress_identity"))
            except ValueError as error:
                raise InvalidTransition(str(error)) from error
            # The CAS is enforced by the conditional UPDATE itself, and the
            # affected-row count is checked exactly (RETURNING), so a future
            # locking change can never silently turn a lost CAS into success.
            cas_row = fetch_one(connection, """UPDATE research_execution_plans SET
                plan_version = :plan_version, task_version = :task_version, stage = :stage,
                iteration = :iteration, status = :status, next_action = :next_action,
                plan = :plan, idempotency_key = :idempotency_key, request_hash = :request_hash,
                updated_at = :now
                WHERE task_id = :task_id AND plan_version = :expected_plan_version
                RETURNING task_id""",
                {"plan_version": advanced["plan_version"], "task_version": advanced["task_version"],
                 "stage": advanced["stage"], "iteration": advanced["iteration"],
                 "status": advanced["status"], "next_action": advanced["next_action"],
                 "plan": advanced, "idempotency_key": request["idempotency_key"],
                 "request_hash": request_hash, "now": _now(), "task_id": task["task_id"],
                 "expected_plan_version": request["expected_plan_version"]})
            if cas_row is None:
                raise InvalidTransition("research execution plan compare-and-swap failed")
            execute(connection, """INSERT INTO research_execution_plan_receipts
                (task_id, idempotency_key, request_hash, plan_version, result_json)
                VALUES (:task_id, :idempotency_key, :request_hash, :plan_version, :result_json)""",
                {"task_id": task["task_id"], "idempotency_key": request["idempotency_key"],
                 "request_hash": request_hash, "plan_version": advanced["plan_version"],
                 "result_json": advanced})
            return project_execution_plan(advanced)

def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
