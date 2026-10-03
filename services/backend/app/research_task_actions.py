"""ResearchTask-owned business actions for exact approval handoffs.

This table records current BYQ business action state. It is not an event log,
Agent turn queue, or Worker claim lease. Approval decisions insert a pending
action in the same transaction; the Product decision request may reconcile only
that exact action after commit.
"""

from __future__ import annotations

import hashlib
import json
import re

from .db import fetch_one
from packages.contracts.research_plan_approval import (
    PLAN_APPROVAL_ACTION,
    apply_approval_decision,
    approval_plan_binding,
    bind_command_digest,
    plan_command_digest,
    plan_command_idempotency_key,
)
from packages.contracts.research_execution_plan import advance, validate_plan


_ACTION_ID = re.compile(r"^research_action_[0-9a-f]{32}$")
_JUDGMENT_STAGES = frozenset({
    "strategy_draft", "backtest_analysis", "iteration_comparison", "final_selection",
})


SCHEMA_DDL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS research_task_actions (
        task_id TEXT NOT NULL REFERENCES research_tasks(task_id),
        action_id TEXT NOT NULL,
        source_approval_id TEXT NOT NULL,
        owner_principal TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        plan_version INTEGER NOT NULL,
        task_version INTEGER NOT NULL,
        action TEXT NOT NULL,
        resource_kind TEXT NOT NULL,
        resource_id TEXT NOT NULL,
        params_digest TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        source_digest TEXT NOT NULL,
        request_digest TEXT NOT NULL,
        decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
        status TEXT NOT NULL CHECK (status IN ('pending', 'applied', 'waiting_for_agent', 'needs_attention')),
        result_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (task_id, action_id),
        UNIQUE (source_approval_id),
        UNIQUE (task_id, idempotency_key)
    )
    """,
    """CREATE UNIQUE INDEX IF NOT EXISTS research_task_actions_one_open
        ON research_task_actions(task_id)
        WHERE status IN ('pending', 'waiting_for_agent', 'needs_attention')""",
    """CREATE INDEX IF NOT EXISTS research_task_actions_owner
        ON research_task_actions(owner_principal, workspace_id, task_id, created_at)""",
]


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False,
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def action_id_for_approval(approval_id: str) -> str:
    return "research_action_" + hashlib.sha256(approval_id.encode("utf-8")).hexdigest()[:32]


def approval_source_digest(approval: dict) -> str:
    """Digest the exact immutable approval source and frozen plan command."""

    fields = (
        "approval_id", "run_id", "run_owner", "run_workspace", "owner_principal",
        "workspace_id", "actor_principal", "decision_by",
        "action", "reason", "resource_type", "resource_id", "idempotency_key", "request_hash",
        "plan_task_id", "plan_workspace_id", "plan_version", "plan_task_version", "plan_action",
        "plan_resource_kind", "plan_resource_id", "plan_params_digest", "plan_idempotency_key",
    )
    return _canonical_digest({field: approval.get(field) for field in fields})


def approval_decision_digest(approval_id: str, decision: str, rationale: str) -> str:
    return _canonical_digest({
        "approval_id": approval_id,
        "decision": decision,
        "rationale": rationale,
    })


def project_research_task_action(row: object) -> dict[str, object]:
    if not isinstance(row, dict) or row.get("status") not in {
        "pending", "applied", "waiting_for_agent", "needs_attention",
    }:
        raise ValueError("research task action row is invalid")
    return {
        "task_id": row["task_id"],
        "action_id": row["action_id"],
        "status": row["status"],
    }


def insert_pending_approval_action(
    connection, approval: dict, *, binding: dict, decision: str, rationale: str,
    now: str,
) -> dict:
    """Insert the exact approval-bound action inside the decision transaction."""

    action_id = action_id_for_approval(approval["approval_id"])
    source_digest = approval_source_digest(approval)
    request_digest = approval_decision_digest(approval["approval_id"], decision, rationale)
    return fetch_one(connection, """INSERT INTO research_task_actions
        (task_id, action_id, source_approval_id, owner_principal, workspace_id,
         plan_version, task_version, action, resource_kind, resource_id, params_digest,
         idempotency_key, source_digest, request_digest, decision, status, result_json,
         created_at, updated_at)
        VALUES (:task, :action_id, :approval_id, :owner, :workspace,
                :plan_version, :task_version, :action, :resource_kind, :resource_id, :params_digest,
                :idempotency_key, :source_digest, :request_digest, :decision, 'pending',
                :result, :now, :now)
        RETURNING *""", {
        "task": binding["task_id"], "action_id": action_id,
        "approval_id": approval["approval_id"], "owner": approval["owner_principal"],
        "workspace": binding["workspace"], "plan_version": binding["plan_version"],
        "task_version": binding["task_version"], "action": binding["action"],
        "resource_kind": binding["resource_kind"], "resource_id": binding["resource_id"],
        "params_digest": binding["params_digest"], "idempotency_key": binding["idempotency_key"],
        "source_digest": source_digest, "request_digest": request_digest,
        "decision": decision, "result": {"decision": decision, "reason": "approval_recorded"},
        "now": now,
    })


class ResearchTaskActionMixin:
    """Read and reconcile exact ResearchTask business actions."""

    def reconcile_research_task_action(
        self, task_id: str, action_id: object, *, trusted_context: dict,
    ) -> dict[str, object]:
        from .research import ResearchNotFound
        if not isinstance(action_id, str) or _ACTION_ID.fullmatch(action_id) is None:
            raise ValueError("research task action identity is invalid")
        owner = trusted_context.get("owner_principal")
        workspace = trusted_context.get("workspace_id")
        if not isinstance(owner, str) or not owner or not isinstance(workspace, str) or not workspace:
            raise ValueError("research task action requires its authenticated owner and workspace")

        # This unlocked read only locates the immutable source approval. The row
        # is revalidated after the required task → plan → approval → action locks.
        pre_action = self._fetch_one("""SELECT source_approval_id FROM research_task_actions
            WHERE task_id = :task AND action_id = :action""",
            {"task": task_id, "action": action_id})
        if pre_action is None:
            raise ResearchNotFound("research task action not found")

        with self._transaction() as connection:
            task = fetch_one(connection, """SELECT * FROM research_tasks
                WHERE task_id = :task AND owner_principal = :owner AND workspace_id = :workspace
                FOR UPDATE""", {"task": task_id, "owner": owner, "workspace": workspace})
            if task is None:
                raise ResearchNotFound("research task action not found")
            plan_row = fetch_one(connection, """SELECT * FROM research_execution_plans
                WHERE task_id = :task FOR UPDATE""", {"task": task_id})
            approval = fetch_one(connection, """SELECT a.*, r.owner_principal AS run_owner
                    , r.workspace_id AS run_workspace
                FROM agent_approvals a JOIN agent_runs r ON r.run_id = a.run_id
                WHERE a.approval_id = :approval FOR UPDATE OF a""",
                {"approval": pre_action["source_approval_id"]})
            action = fetch_one(connection, """SELECT * FROM research_task_actions
                WHERE task_id = :task AND action_id = :action FOR UPDATE""",
                {"task": task_id, "action": action_id})
            if action is None or approval is None:
                raise ResearchNotFound("research task action source not found")
            if (action["source_approval_id"] != pre_action["source_approval_id"]
                    or action["owner_principal"] != owner or action["workspace_id"] != workspace
                    or approval["owner_principal"] != owner or approval["workspace_id"] != workspace
                    or approval["run_owner"] != owner or approval["run_workspace"] != workspace
                    or task["owner_principal"] != owner or task["workspace_id"] != workspace):
                raise ResearchNotFound("research task action not found")
            if action["status"] != "pending":
                return project_research_task_action(action)

            binding = approval_plan_binding(approval)
            source_matches = (
                approval["owner_principal"] == owner and approval["run_owner"] == owner
                and approval["status"] in {"approved", "rejected"}
                and binding is not None
                and action["source_digest"] == approval_source_digest(approval)
                and action["request_digest"] == approval_decision_digest(
                    approval["approval_id"], approval["status"], approval.get("decision_reason") or "")
                and action["decision"] == approval["status"]
                and binding["task_id"] == task_id and binding["workspace"] == workspace
                and binding["plan_version"] == action["plan_version"]
                and binding["task_version"] == action["task_version"]
                and binding["action"] == action["action"]
                and binding["resource_kind"] == action["resource_kind"]
                and binding["resource_id"] == action["resource_id"]
                and binding["params_digest"] == action["params_digest"]
                and binding["idempotency_key"] == action["idempotency_key"]
            )
            if not source_matches or plan_row is None:
                return self._mark_action_needs_attention(
                    connection, action, reason="approval_source_or_plan_missing")

            plan = validate_plan(plan_row["plan"])
            if (plan["task_id"] != task_id or plan["owner_principal"] != owner
                    or plan["workspace_id"] != workspace
                    or int(plan["task_version"]) != int(task["version"])
                    or int(plan_row["plan_version"]) != int(plan["plan_version"])
                    or int(plan_row["task_version"]) != int(plan["task_version"])
                    or plan_row["stage"] != plan["stage"]
                    or (binding["plan_version"], binding["task_version"])
                        != (plan["plan_version"], plan["task_version"])):
                return self._mark_action_needs_attention(
                    connection, action, reason="stale_plan_or_task_binding")
            gate = plan.get("approval")
            if (not isinstance(gate, dict)
                    or (gate.get("action"), gate.get("resource_kind"), gate.get("resource_id"))
                       != (binding["action"], binding["resource_kind"], binding["resource_id"])
                    or approval.get("action") != PLAN_APPROVAL_ACTION.get(binding["action"])
                    or approval.get("resource_type") != binding["resource_kind"]
                    or approval.get("resource_id") != binding["resource_id"]):
                return self._mark_action_needs_attention(
                    connection, action, reason="approval_gate_mismatch")
            reference = (plan.get("references") or {}).get(binding["resource_kind"])
            if not isinstance(reference, dict) or reference.get(binding["resource_kind"]) != binding["resource_id"]:
                return self._mark_action_needs_attention(
                    connection, action, reason="approval_resource_reference_mismatch")
            try:
                digest = plan_command_digest(
                    plan, action=binding["action"], resource_kind=binding["resource_kind"],
                    resource_id=binding["resource_id"])
                idempotency_key = plan_command_idempotency_key(
                    plan, action=binding["action"], resource_kind=binding["resource_kind"],
                    resource_id=binding["resource_id"])
            except ValueError:
                return self._mark_action_needs_attention(
                    connection, action, reason="approval_command_invalid")
            if digest != binding["params_digest"] or idempotency_key != binding["idempotency_key"]:
                return self._mark_action_needs_attention(
                    connection, action, reason="approval_command_digest_mismatch")

            reduced = apply_approval_decision(
                plan, decision=approval["status"], action=binding["action"],
                resource_kind=binding["resource_kind"], resource_id=binding["resource_id"],
                params_digest=binding["params_digest"],
            )
            if reduced["outcome"] == "needs_attention":
                return self._mark_action_needs_attention(
                    connection, action, reason=str(reduced["reason"]))

            if reduced["outcome"] == "advance":
                try:
                    advanced = advance(
                        plan, expected_plan_version=plan["plan_version"],
                        expected_task_version=plan["task_version"],
                        next_stage=reduced["next_stage"], iteration=plan["iteration"],
                        status=reduced["status"],
                        expected_postcondition=reduced["expected_postcondition"],
                        idempotency_key=f"research-action-{action_id}",
                        references=reduced["references"], prerequisites=None,
                        approval=reduced["approval"],
                        last_progress_identity=action["request_digest"],
                    )
                    advanced = bind_command_digest(advanced)
                except ValueError:
                    return self._mark_action_needs_attention(
                        connection, action, reason="plan_action_transition_invalid")
                cas = fetch_one(connection, """UPDATE research_execution_plans SET
                    plan_version = :plan_version, task_version = :task_version, stage = :stage,
                    iteration = :iteration, status = :status, next_action = :next_action,
                    plan = :plan, idempotency_key = :idempotency_key, request_hash = :request_hash,
                    updated_at = :now
                    WHERE task_id = :task AND plan_version = :expected_plan_version
                      AND task_version = :expected_task_version
                    RETURNING task_id""", {
                    "plan_version": advanced["plan_version"], "task_version": advanced["task_version"],
                    "stage": advanced["stage"], "iteration": advanced["iteration"],
                    "status": advanced["status"], "next_action": advanced["next_action"],
                    "plan": advanced, "idempotency_key": f"research-action-{action_id}",
                    "request_hash": action["request_digest"], "now": self._action_now(),
                    "task": task_id, "expected_plan_version": plan["plan_version"],
                    "expected_task_version": plan["task_version"],
                })
                if cas is None:
                    return self._mark_action_needs_attention(
                        connection, action, reason="plan_compare_and_swap_failed")
                new_stage = advanced["stage"]
            elif reduced["outcome"] == "applied":
                new_stage = plan["stage"]
            else:
                return self._mark_action_needs_attention(
                    connection, action, reason="approval_action_outcome_unknown")

            next_status = "waiting_for_agent" if new_stage in _JUDGMENT_STAGES else "applied"
            result = {
                "decision": approval["status"], "outcome": reduced["outcome"],
                "reason": reduced["reason"], "plan_stage": new_stage,
            }
            updated = fetch_one(connection, """UPDATE research_task_actions SET
                status = :status, result_json = :result, updated_at = :now
                WHERE task_id = :task AND action_id = :action AND status = 'pending'
                RETURNING *""", {
                "status": next_status, "result": result, "now": self._action_now(),
                "task": task_id, "action": action_id,
            })
            if updated is None:
                raise ValueError("research task action changed during reconciliation")
            return project_research_task_action(updated)

    @staticmethod
    def _action_now() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _mark_action_needs_attention(connection, action: dict, *, reason: str) -> dict[str, object]:
        updated = fetch_one(connection, """UPDATE research_task_actions SET
            status = 'needs_attention', result_json = :result, updated_at = :now
            WHERE task_id = :task AND action_id = :action AND status = 'pending'
            RETURNING *""", {
            "result": {"outcome": "needs_attention", "reason": reason},
            "now": ResearchTaskActionMixin._action_now(),
            "task": action["task_id"], "action": action["action_id"],
        })
        if updated is None:
            updated = action
        return project_research_task_action(updated)
