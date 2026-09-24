"""ADR-0085 P4: minimal trusted plan-continuation production seam.

P0-P3 delivered the closed plan vocabulary, the durable event ledger with five
named adapters, and the bounded research-judgment turn. They intentionally did
NOT add a production consumer: the plan store, the ledger adapters and the
adapter judgment invocation had no runtime caller, and no code created a plan for
a granted compound task or executed a ``ready_to_*`` deterministic action.

This module adds ONLY the missing trusted consumer seam, as BYQ Domain Workflow
(not a second generic agent harness and not a second session store):

* :meth:`ResearchPlanContinuationMixin.ensure_execution_plan` creates the single
  current plan for a task that already has a durable continuation grant. It is
  idempotent and fails closed for an ungranted or terminal task.
* :meth:`ResearchPlanContinuationMixin.plan_continuation_dispatch` is READ-ONLY.
  It returns the exact bounded next step (judgment turn / approval wait /
  deterministic action / waiting / terminal) derived from the persisted plan.
  The model never chooses any of these.
* :meth:`ResearchPlanContinuationMixin.request_plan_approval` mints the EXACT
  plan-command-bound ``agent_approvals`` row for the current human gate, server
  side. The caller supplies no action/resource/version/digest/key.
* :meth:`ResearchPlanContinuationMixin.apply_deterministic_action_result` records
  the authoritative result of one READY deterministic action (an exact
  ``signal_producer_jobs`` or ``backtest_jobs`` identity) and advances the plan
  through the plan CAS with a BYQ-minted idempotency key.

There is no generic plan/event write route, no model-facing write tool, and no
caller-supplied routing/identity/idempotency.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from .db import execute, fetch_one
from packages.contracts.research_execution_plan import (
    APPROVAL_WAIT_STAGES,
    READY_STAGES,
    STAGE_APPROVAL_REQUIREMENT,
    STAGE_POSTCONDITION,
    advance,
    validate_plan,
)
from packages.contracts.research_continuation_event import (
    PLAN_APPROVAL_ACTION,
    bind_command_digest,
    plan_command_digest,
    plan_command_idempotency_key,
)

__all__ = ["ResearchPlanContinuationMixin", "PlanContinuationError"]

_JUDGMENT_STAGES = frozenset({
    "strategy_draft", "backtest_analysis", "iteration_comparison", "final_selection",
})
_WAITING_STAGES = frozenset({"waiting_for_data", "waiting_for_backtest_job"})
_TERMINAL_STAGES = frozenset({"completed", "needs_attention"})

# The deterministic READY stage -> exact authoritative source the result must
# name, and the next stage it advances to.
_DETERMINISTIC_RESULT = {
    "ready_to_create_backtest_task": {
        "action": "create_backtest_task", "source": "signal_job_id",
        "next_stage": "waiting_for_data",
    },
    "ready_to_execute_backtest_task": {
        "action": "execute_backtest_task", "source": "backtest_job_id",
        "next_stage": "waiting_for_backtest_job",
    },
}


class PlanContinuationError(RuntimeError):
    """The plan-continuation seam failed closed."""


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class ResearchPlanContinuationMixin:
    """Trusted, deterministic plan-continuation consumer seam."""

    # ------------------------------------------------------------------ #
    # Plan creation for a granted compound task
    # ------------------------------------------------------------------ #

    def ensure_execution_plan(self, task_id: str, *, trusted_context: dict) -> dict:
        """Create the one current plan for a granted compound task (idempotent).

        A plan is only created when the task already carries a durable
        continuation grant; an ungranted task is refused (fail closed). A task
        that already has a plan returns the existing bounded projection.
        """

        from .research import InvalidTransition, ResearchNotFound
        from .research_execution_plan import project_execution_plan

        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=True)
            existing = self._load_current_plan(connection, task["task_id"], lock=True)
            if existing is not None:
                # Idempotent replay (including a later revoked grant): the single
                # current plan is returned unchanged.
                return project_execution_plan(existing["plan"])
            if task["status"] in {"completed", "failed", "cancelled"}:
                raise InvalidTransition("a terminal research task cannot start an execution plan")
            grant = task.get("continuation_permission")
            if not isinstance(grant, dict) or grant.get("revoked_at") is not None:
                raise InvalidTransition(
                    "an execution plan requires an active continuation grant")
        # Creation (including the deterministic grant reference binding and the
        # revoke/expiry/artifact re-validation) happens in ONE trusted transaction
        # under the task-row lock, so nothing can go invalid in between.
        return self.create_execution_plan(
            task_id, {"idempotency_key": f"plan-grant-{task_id}"},
            trusted_context=trusted_context,
            require_active_grant=True, bind_grant_references=True)

    # ------------------------------------------------------------------ #
    # Read-only bounded dispatch
    # ------------------------------------------------------------------ #

    def plan_continuation_dispatch(self, task_id: str, *, trusted_context: dict) -> dict:
        """Bounded, read-only descriptor of the exact next plan step."""

        from .research import ResearchNotFound

        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=False)
            plan_row = self._load_current_plan(connection, task["task_id"], lock=False)
            if plan_row is None:
                raise ResearchNotFound("research execution plan not found")
            plan = validate_plan(plan_row["plan"])
        return self._dispatch_descriptor(task, plan)

    @staticmethod
    def _dispatch_descriptor(task: dict, plan: dict) -> dict:
        stage = plan["stage"]
        base = {
            "task_id": plan["task_id"], "plan_version": plan["plan_version"],
            "task_version": plan["task_version"], "stage": stage,
            "iteration": plan["iteration"], "next_action": plan["next_action"],
        }
        if stage in _JUDGMENT_STAGES:
            from packages.contracts.research_judgment import (
                STAGE_ALLOWED_TOOLS,
                stage_model_call_limit,
            )
            return {**base, "kind": "judgment_turn",
                    "model_call_limit": stage_model_call_limit(stage),
                    "allowed_tools": sorted(STAGE_ALLOWED_TOOLS[stage]),
                    "bounded_projection_only": True}
        if stage in APPROVAL_WAIT_STAGES:
            return {**base, "kind": "approval_wait", "gate": dict(plan.get("approval") or {})}
        if stage in READY_STAGES:
            return {**base, "kind": "deterministic_action",
                    "action": _DETERMINISTIC_RESULT[stage]["action"],
                    "allowed_capabilities": list(plan["allowed_capabilities"])}
        if stage in _WAITING_STAGES:
            return {**base, "kind": "waiting"}
        if stage == "needs_attention":
            return {**base, "kind": "needs_attention"}
        if stage == "completed":
            return {**base, "kind": "terminal", "status": plan["status"]}
        raise PlanContinuationError("plan stage has no continuation dispatch")

    # ------------------------------------------------------------------ #
    # Server-side bound approval request
    # ------------------------------------------------------------------ #

    def request_plan_approval(self, task_id: str, *, trusted_context: dict) -> dict:
        """Mint the exact plan-command-bound approval for the current human gate.

        The action, resource, plan/task version, parameter digest and BYQ
        idempotency key are all derived from the persisted plan; the caller
        supplies none of them. An exact replay returns the same approval row.
        """

        from .research import InvalidTransition, ResearchNotFound

        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=True)
            plan_row = self._load_current_plan(connection, task["task_id"], lock=True)
            if plan_row is None:
                raise ResearchNotFound("research execution plan not found")
            plan = validate_plan(plan_row["plan"])
            gate = plan.get("approval")
            if plan["stage"] not in APPROVAL_WAIT_STAGES or not isinstance(gate, dict):
                raise InvalidTransition("the plan is not at a human approval gate")
            agent_action = PLAN_APPROVAL_ACTION.get(str(gate["action"]))
            if agent_action is None:
                raise InvalidTransition("the plan gate has no agent approval action")
            digest = plan_command_digest(
                plan, action=gate["action"], resource_kind=gate["resource_kind"],
                resource_id=gate["resource_id"])
            key = plan_command_idempotency_key(
                plan, action=gate["action"], resource_kind=gate["resource_kind"],
                resource_id=gate["resource_id"])
            if gate.get("params_digest") not in {None, digest}:
                raise InvalidTransition("the plan gate parameter digest does not match")
            run = self._plan_gate_run(connection, task)
            if run is None:
                raise InvalidTransition("plan approval requires a bound agent run")
            existing = fetch_one(connection, """SELECT * FROM agent_approvals
                WHERE run_id = :run AND idempotency_key = :key""",
                {"run": run["run_id"], "key": key})
            if existing is not None:
                return self._approval_binding_view(existing, plan, key)
            approval_id = "agent_approval_" + uuid.uuid4().hex
            request_hash = _hash({
                "task_id": task["task_id"], "plan_version": plan["plan_version"],
                "task_version": plan["task_version"], "action": gate["action"],
                "resource_kind": gate["resource_kind"], "resource_id": gate["resource_id"],
                "params_digest": digest, "idempotency_key": key,
            })
            execute(connection, """INSERT INTO agent_approvals
                (approval_id, run_id, owner_principal, actor_principal, action, reason,
                 resource_type, resource_id, status, decision_by, decision_reason,
                 execution_outcome, continuation_status, idempotency_key, request_hash,
                 created_at, updated_at, plan_task_id, plan_workspace_id, plan_version,
                 plan_task_version, plan_action, plan_resource_kind, plan_resource_id,
                 plan_params_digest, plan_idempotency_key)
                VALUES (:approval_id, :run_id, :owner, :actor, :action, :reason,
                        :resource_type, :resource_id, 'pending', NULL, NULL,
                        'not_started', 'blocked', :key, :request_hash,
                        :now, :now, :task, :workspace, :plan_version,
                        :task_version, :plan_action, :resource_kind, :resource_id,
                        :digest, :key)""",
                {"approval_id": approval_id, "run_id": run["run_id"],
                 "owner": task["owner_principal"], "actor": run["actor_principal"],
                 "action": agent_action,
                 "reason": f"ADR-0085 plan gate {gate['action']} for {gate['resource_id']}",
                 "resource_type": gate["resource_kind"], "resource_id": gate["resource_id"],
                 "key": key, "request_hash": request_hash, "now": _now(),
                 "task": task["task_id"], "workspace": task["workspace_id"],
                 "plan_version": plan["plan_version"], "task_version": plan["task_version"],
                 "plan_action": gate["action"], "resource_kind": gate["resource_kind"],
                 "digest": digest})
            row = fetch_one(connection, "SELECT * FROM agent_approvals WHERE approval_id = :id",
                            {"id": approval_id})
            assert row is not None
            return self._approval_binding_view(row, plan, key)

    @staticmethod
    def _approval_binding_view(row: dict, plan: dict, key: str) -> dict:
        return {
            "approval_id": row["approval_id"], "action": row["action"],
            "resource_type": row.get("resource_type"), "resource_id": row.get("resource_id"),
            "status": row["status"], "plan_version": plan["plan_version"],
            "task_version": plan["task_version"], "plan_command_key": key,
        }

    @staticmethod
    def _plan_gate_run(connection, task: dict):
        """The task's exact bound owner run, or the owner's latest run."""

        row = fetch_one(connection, """SELECT r.run_id, r.actor_principal
            FROM agent_runs r
            JOIN product_conversations c ON c.runtime_session_id = r.session_id
            WHERE c.conversation_id = :conversation AND r.owner_principal = :owner
            ORDER BY r.created_at DESC, r.run_id LIMIT 1""",
            {"conversation": task["conversation_id"], "owner": task["owner_principal"]})
        if row is not None:
            return row
        return fetch_one(connection, """SELECT run_id, actor_principal FROM agent_runs
            WHERE owner_principal = :owner ORDER BY created_at DESC, run_id LIMIT 1""",
            {"owner": task["owner_principal"]})

    # ------------------------------------------------------------------ #
    # Deterministic action result -> plan CAS
    # ------------------------------------------------------------------ #

    def apply_deterministic_action_result(self, task_id: str, payload: object, *,
                                          trusted_context: dict) -> dict:
        """Record the authoritative result of the current READY action.

        ``payload`` names ONLY the exact persisted domain identity of the action's
        result (``signal_job_id`` for task creation, ``backtest_job_id`` for
        execution). The action, next stage, references, progress identity and
        idempotency key are all derived server side. An exact replay of an
        already-applied result returns the current bounded projection.
        """

        from .research import InvalidTransition, ResearchNotFound
        from .research_execution_plan import project_execution_plan
        from .backtest_task import task_id_from_signal_job

        if not isinstance(payload, dict) or len(payload) != 1:
            raise InvalidTransition("deterministic action result must name exactly one source")
        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=True)
            plan_row = self._load_current_plan(connection, task["task_id"], lock=True)
            if plan_row is None:
                raise ResearchNotFound("research execution plan not found")
            plan = validate_plan(plan_row["plan"])
            spec = _DETERMINISTIC_RESULT.get(plan["stage"])
            if spec is None:
                # Idempotent replay: if the plan already recorded this exact
                # source, return it; otherwise the plan is not at a READY action.
                source_kind, source_id = next(iter(payload.items()))
                if source_kind in {"signal_job_id", "backtest_job_id"} and self._plan_has_source(
                        plan, source_kind, source_id):
                    return project_execution_plan(plan)
                raise InvalidTransition("the plan is not at a deterministic action stage")
            source_kind, source_id = next(iter(payload.items()))
            if source_kind != spec["source"]:
                raise InvalidTransition("deterministic action result names the wrong source kind")
            if not isinstance(source_id, str):
                raise InvalidTransition("deterministic action result source is invalid")
            if spec["source"] == "signal_job_id":
                row = fetch_one(connection, """SELECT * FROM signal_producer_jobs
                    WHERE job_id = :id AND task_id = :task AND owner_principal = :owner""",
                    {"id": source_id, "task": task["task_id"], "owner": task["owner_principal"]})
                if row is None:
                    raise InvalidTransition("deterministic result signal job does not belong to this task")
                references = {**plan["references"],
                              "signal_producer_job": {"signal_producer_job": source_id},
                              "backtest_task": {"backtest_task": task_id_from_signal_job(source_id)}}
                progress_identity = _hash({
                    "kind": "signal_producer_job", "id": row["job_id"], "status": row["status"]})
            else:
                row = fetch_one(connection, """SELECT * FROM backtest_jobs
                    WHERE job_id = :id AND task_id = :task AND owner_principal = :owner""",
                    {"id": source_id, "task": task["task_id"], "owner": task["owner_principal"]})
                if row is None:
                    raise InvalidTransition("deterministic result backtest job does not belong to this task")
                references = {**plan["references"],
                              "backtest_job": {"backtest_job": source_id}}
                progress_identity = _hash({
                    "kind": "backtest_job", "id": row["job_id"], "status": row["status"]})
            next_stage = spec["next_stage"]
            idempotency_key = f"planaction-{spec['action']}-{source_id}"
            try:
                advanced = advance(
                    plan, expected_plan_version=plan["plan_version"],
                    expected_task_version=plan["task_version"], next_stage=next_stage,
                    iteration=plan["iteration"], status="waiting",
                    expected_postcondition=STAGE_POSTCONDITION[next_stage],
                    idempotency_key=idempotency_key, references=references,
                    prerequisites=None, approval=None,
                    last_progress_identity=progress_identity)
            except ValueError as error:
                raise InvalidTransition(str(error)) from error
            cas_row = fetch_one(connection, """UPDATE research_execution_plans SET
                plan_version = :plan_version, task_version = :task_version, stage = :stage,
                iteration = :iteration, status = :status, next_action = :next_action,
                plan = :plan, idempotency_key = :idempotency_key, request_hash = :request_hash,
                legacy_reason = NULL, updated_at = :now
                WHERE task_id = :task_id AND plan_version = :expected_plan_version
                RETURNING task_id""",
                {"plan_version": advanced["plan_version"], "task_version": advanced["task_version"],
                 "stage": advanced["stage"], "iteration": advanced["iteration"],
                 "status": advanced["status"], "next_action": advanced["next_action"],
                 "plan": advanced, "idempotency_key": idempotency_key,
                 "request_hash": progress_identity, "now": _now(),
                 "task_id": task["task_id"], "expected_plan_version": plan["plan_version"]})
            if cas_row is None:
                raise InvalidTransition("research execution plan compare-and-swap failed")
            return project_execution_plan(advanced)

    @staticmethod
    def _plan_has_source(plan: dict, source_kind: str, source_id: object) -> bool:
        references = plan.get("references") or {}
        if source_kind == "signal_job_id":
            ref = references.get("signal_producer_job")
            return isinstance(ref, dict) and ref.get("signal_producer_job") == source_id
        ref = references.get("backtest_job")
        return isinstance(ref, dict) and ref.get("backtest_job") == source_id
