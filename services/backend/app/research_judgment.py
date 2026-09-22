"""ADR-0085 P3: bounded research-judgment stage input and proposal seam.

This is the Backend side of ADR-0085 §6. It is BYQ Domain Workflow, not a second
generic agent harness: it persists no DSH private context, hidden reasoning, tool
state or session journal, and it never starts a model turn itself.

Two named server-side seams exist and NOTHING ELSE:

* ``get_research_stage_input`` is READ-ONLY. It returns the bounded stage input
  for a genuine research-judgment stage (bounded plan projection + bounded
  evidence descriptors + the minimal read-only tool set). A deterministic stage
  is refused: it MUST use zero model calls.
* ``commit_research_proposal`` is the named server-side proposal seam. It
  validates a CLOSED, bounded proposal, derives the exact next plan state through
  the framework-neutral reducer, and commits it through the same plan
  compare-and-swap the P1/P2 reducers use. An external caller can never name a
  target stage/action, an object identity, an approval, an idempotency key, a job
  route or recovery/continuation state.
* ``record_research_stage_progress`` enforces the durable-progress fence. After
  the FIRST model call, a missing durable-progress identity atomically moves the
  plan and ResearchTask to ``needs_attention`` with reason ``no_durable_progress``
  instead of retrying, spawning subagents or consuming the eight-call budget.

There is NO generic plan/event/proposal write route. The proposal is submitted
by trusted server code through the named seam; the agent-facing surface stays
read-only (see ``services/mcp`` and ``services/backend/app/main.py``).
"""

from __future__ import annotations

from .db import execute, fetch_one
from packages.contracts.research_execution_plan import (
    STAGE_APPROVAL_REQUIREMENT,
    STAGE_POSTCONDITION,
    advance,
    validate_plan,
)
from packages.contracts.research_continuation_event import bound_approval, bind_command_digest
from packages.contracts.research_judgment import (
    STAGE_INPUT_SCHEMA_VERSION,
    STAGE_PROPOSAL_KINDS,
    TEXT_MAX,
    assert_commit_is_legal,
    derive_proposal_commit,
    proposal_identity,
    proposal_request_hash,
    stage_model_call_outcome,
    stage_requires_model,
    validate_proposal,
    validate_stage_input,
)

__all__ = ["ModelTurnNotAllowed", "ResearchJudgmentMixin"]

# A deterministic plan stage MUST NOT start a model turn. ValueError maps to a
# safe 422 through the read-only route, never to a model escalation path.
class ModelTurnNotAllowed(ValueError):
    pass


# Closed stage instruction text. It names the bounded judgment; it never names a
# routing target.
_STAGE_INSTRUCTION = {
    "strategy_draft": "Propose the bounded strategy draft judgment for this research task.",
    "backtest_analysis": "Analyse the bounded backtest summary for the current round.",
    "iteration_comparison": "Compare the completed rounds and propose a bounded next step.",
    "final_selection": "Select the best round or escalate when evidence is insufficient.",
}

_MAX_EVIDENCE = 32


class ResearchJudgmentMixin:
    """Read-only stage input, named proposal commit and the no-progress fence."""

    @staticmethod
    def _require_model_stage(stage: object) -> str:
        if not stage_requires_model(stage):
            raise ModelTurnNotAllowed("a deterministic research stage must not start a model turn")
        return str(stage)

    # ------------------------------------------------------------------ #
    # Read-only bounded stage input
    # ------------------------------------------------------------------ #

    def get_research_stage_input(self, task_id: str, *, trusted_context: dict) -> dict:
        from .research import ResearchNotFound

        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=False)
            plan_row = self._load_current_plan(connection, task["task_id"], lock=False)
            if plan_row is None:
                raise ResearchNotFound("research execution plan not found")
            plan = validate_plan(plan_row["plan"])
            # A deterministic stage is refused here: it uses zero model calls.
            self._require_model_stage(plan["stage"])
            evidence = self._stage_evidence(task, plan)
            payload = {
                "schema_version": STAGE_INPUT_SCHEMA_VERSION,
                "task_id": plan["task_id"],
                "plan_version": plan["plan_version"],
                "task_version": plan["task_version"],
                "stage": plan["stage"],
                "iteration": plan["iteration"],
                "status": plan["status"],
                "objective": str(task.get("objective") or "")[:TEXT_MAX],
                "stage_instruction": _STAGE_INSTRUCTION[plan["stage"]],
                "proposal_kinds": sorted(STAGE_PROPOSAL_KINDS[plan["stage"]]),
                "evidence": evidence,
                "allowed_tools": sorted(self._stage_tools(plan["stage"])),
                "model_call_limit": self._stage_call_limit(plan["stage"]),
                "escalation_allowed": True,
            }
            return validate_stage_input(payload)

    # ------------------------------------------------------------------ #
    # Named server-side proposal seam
    # ------------------------------------------------------------------ #

    def commit_research_proposal(self, task_id: str, payload: object, *,
                                 trusted_context: dict) -> dict:
        """Validate and commit one bounded research-judgment proposal.

        The proposal body is CLOSED and carries no routing/identity authority.
        The exact next plan state is derived server-side and committed through a
        plan-version compare-and-swap under the task-row lock.
        """

        from .research import IdempotencyConflict, InvalidTransition, ResearchNotFound
        from .research_execution_plan import project_execution_plan

        proposal = validate_proposal(payload)
        if proposal["task_id"] != task_id:
            raise InvalidTransition("research proposal task does not match its route")
        identity = proposal_identity(proposal)
        request_hash = proposal_request_hash(proposal)

        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=True)
            plan_row = self._load_current_plan(connection, task["task_id"], lock=True)
            if plan_row is None:
                raise ResearchNotFound("research execution plan not found")
            plan = validate_plan(plan_row["plan"])

            # An exact replay is served from its durable receipt BEFORE any
            # version check, so a duplicate submission never writes twice and a
            # mutated body under the same identity is a conflict.
            receipt = fetch_one(connection, """SELECT * FROM research_execution_plan_receipts
                WHERE task_id = :task AND idempotency_key = :key""",
                {"task": task["task_id"], "key": identity})
            if receipt is not None:
                if receipt["request_hash"] != request_hash:
                    raise IdempotencyConflict("research proposal identity was reused")
                return {**project_execution_plan(receipt["result_json"]),
                        "proposal_identity": identity, "replayed": True}

            self._require_model_stage(plan["stage"])
            if proposal["stage"] != plan["stage"]:
                raise InvalidTransition("research proposal stage does not match the current plan")
            if proposal["iteration"] != plan["iteration"]:
                raise InvalidTransition("research proposal iteration does not match the current plan")
            if proposal["plan_version"] != plan["plan_version"]:
                raise InvalidTransition("research execution plan version is stale")
            if proposal["task_version"] != plan["task_version"]:
                raise InvalidTransition("research execution task version is stale")

            decision = derive_proposal_commit(plan, proposal)
            assert_commit_is_legal(plan, decision)

            if decision["outcome"] == "advance":
                advanced = self._apply_proposal_advance(connection, task, plan, proposal, decision, identity)
            elif decision["outcome"] == "needs_attention":
                advanced = self._apply_stage_needs_attention(
                    connection, task, plan, str(decision["reason"]), identity)
            else:
                # A bounded "stay" records the proposal without moving the plan.
                advanced = plan
            execute(connection, """INSERT INTO research_execution_plan_receipts
                (task_id, idempotency_key, request_hash, plan_version, result_json)
                VALUES (:task_id, :idempotency_key, :request_hash, :plan_version, :result_json)""",
                {"task_id": task["task_id"], "idempotency_key": identity,
                 "request_hash": request_hash, "plan_version": advanced["plan_version"],
                 "result_json": advanced})
            return {**project_execution_plan(advanced), "proposal_identity": identity,
                    "replayed": False, "reason": decision["reason"]}

    # ------------------------------------------------------------------ #
    # Durable-progress fence
    # ------------------------------------------------------------------ #

    def record_research_stage_progress(self, task_id: str, payload: object, *,
                                       trusted_context: dict) -> dict:
        """Record one model call's durable-progress evidence for the fence.

        The payload carries a BYQ-observed durable-progress identity (or None)
        and the 1-based model call count. It never carries routing/identity
        authority. A first call without durable progress stops the stage as
        ``needs_attention/no_durable_progress`` atomically.
        """

        from .research import InvalidTransition

        if not isinstance(payload, dict) or set(payload) != {"call_index", "durable_progress_identity"}:
            raise ValueError("research stage progress request has invalid fields")
        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=True)
            plan_row = self._load_current_plan(connection, task["task_id"], lock=True)
            if plan_row is None:
                raise InvalidTransition("research execution plan not found")
            plan = validate_plan(plan_row["plan"])
            self._require_model_stage(plan["stage"])
            outcome = stage_model_call_outcome(
                stage=plan["stage"], calls_used=payload["call_index"],
                durable_progress_identity=payload["durable_progress_identity"])
            if outcome["status"] == "stop" and outcome["outcome"] == "needs_attention":
                self._apply_stage_needs_attention(
                    connection, task, plan, str(outcome["reason"]),
                    f"stage-fence-{plan['task_id']}-{plan['plan_version']}")
                outcome = {**outcome, "plan_moved_to_needs_attention": True}
            else:
                outcome = {**outcome, "plan_moved_to_needs_attention": False}
            return outcome

    # ------------------------------------------------------------------ #
    # Commit helpers
    # ------------------------------------------------------------------ #

    def _apply_proposal_advance(self, connection, task, plan, proposal, decision, identity):
        from .research import InvalidTransition

        target_stage = str(decision["next_stage"])
        iteration = decision.get("iteration")
        iteration = iteration if isinstance(iteration, int) else plan["iteration"]
        approval = self._target_approval(plan, target_stage)
        try:
            advanced = advance(
                plan, expected_plan_version=plan["plan_version"],
                expected_task_version=plan["task_version"], next_stage=target_stage,
                iteration=iteration, status=str(decision["status"]),
                expected_postcondition=str(decision["expected_postcondition"]),
                idempotency_key=identity, references=None, prerequisites=None,
                approval=approval, last_progress_identity=plan["last_progress_identity"])
            if isinstance(advanced.get("approval"), dict):
                advanced = bind_command_digest(advanced)
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
             "plan": advanced, "idempotency_key": identity,
             "request_hash": proposal_request_hash(proposal), "now": _now(),
             "task_id": task["task_id"], "expected_plan_version": plan["plan_version"]})
        if cas_row is None:
            raise InvalidTransition("research execution plan compare-and-swap failed")
        return advanced

    def _apply_stage_needs_attention(self, connection, task, plan, reason, identity):
        """Atomically move plan + ResearchTask to ``needs_attention``.

        The historical eight-call continuation budget is NOT touched: this is a
        durable stop, not a reservation.
        """

        from .research import InvalidTransition

        reason = str(reason)[:160]
        try:
            advanced = advance(
                plan, expected_plan_version=plan["plan_version"],
                expected_task_version=plan["task_version"], next_stage="needs_attention",
                iteration=plan["iteration"], status="blocked",
                expected_postcondition=STAGE_POSTCONDITION["needs_attention"],
                idempotency_key=identity, references=None, prerequisites=None,
                approval=None, last_progress_identity=plan["last_progress_identity"])
        except ValueError as error:
            raise InvalidTransition(str(error)) from error
        new_task_version = task["version"] + 1
        advanced = validate_plan({**advanced, "task_version": new_task_version})
        progress = self._blocked_progress(task, reason)
        updated = fetch_one(connection, """UPDATE research_tasks SET
            progress = :progress, version = :version, updated_at = :now
            WHERE task_id = :task AND version = :expected RETURNING task_id""",
            {"progress": progress, "version": new_task_version, "now": _now(),
             "task": task["task_id"], "expected": task["version"]})
        if updated is None:
            raise InvalidTransition("research task compare-and-swap failed")
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
             "plan": advanced, "idempotency_key": identity,
             "request_hash": identity, "now": _now(),
             "task_id": task["task_id"], "expected_plan_version": plan["plan_version"]})
        if cas_row is None:
            raise InvalidTransition("research execution plan compare-and-swap failed")
        return advanced

    @staticmethod
    def _blocked_progress(task: dict, reason: str) -> dict:
        existing = task.get("progress") if isinstance(task.get("progress"), dict) else {}
        linked = existing.get("linked_objects") if isinstance(existing.get("linked_objects"), list) else []
        evidence = existing.get("completion_evidence") if isinstance(existing.get("completion_evidence"), list) else []
        return {
            "schema_version": "research-progress.v1",
            "stage": "blocked",
            "next_action": "needs_attention",
            "blocked_reason": reason,
            "linked_objects": linked,
            "completion_evidence": evidence,
        }

    @staticmethod
    def _target_approval(plan: dict, target_stage: str):
        """Mint the target stage's exact bound approval from the plan's own reference.

        The proposal never supplies the approval, action, resource or version.
        A missing reference is a closed, honest blocker rather than a guessed
        identity.
        """

        from .research import InvalidTransition

        requirement = STAGE_APPROVAL_REQUIREMENT.get(target_stage)
        if requirement is None:
            return None
        kind = requirement["resource_kind"]
        reference = (plan.get("references") or {}).get(kind)
        resource_id = reference.get(kind) if isinstance(reference, dict) else None
        if not isinstance(resource_id, str) or not resource_id:
            raise InvalidTransition(
                f"research judgment target requires an existing {kind} reference")
        return bound_approval(
            action=requirement["action"], resource_kind=kind, resource_id=resource_id,
            plan_version=plan["plan_version"] + 1, task_version=plan["task_version"],
            params_digest=None)

    # ------------------------------------------------------------------ #
    # Bounded stage evidence / tools
    # ------------------------------------------------------------------ #

    @staticmethod
    def _stage_tools(stage: str):
        from packages.contracts.research_judgment import STAGE_ALLOWED_TOOLS

        return STAGE_ALLOWED_TOOLS[stage]

    @staticmethod
    def _stage_call_limit(stage: str) -> int:
        from packages.contracts.research_judgment import stage_model_call_limit

        return stage_model_call_limit(stage)

    @staticmethod
    def _stage_evidence(task: dict, plan: dict) -> list:
        """Bounded evidence descriptors: references only, never raw payloads."""

        summaries = {
            "strategy_version": "validated strategy version reference",
            "strategy_approval": "strategy approval reference",
            "stock_pool_snapshot": "frozen stock-pool snapshot reference",
            "signal_producer_job": "signal production job reference",
            "signal_snapshot": "validated signal snapshot reference",
            "backtest_task": "backtest task reference",
            "backtest_job": "backtest job reference",
            "backtest_result": "backtest result reference",
        }
        evidence: list[dict] = []
        for kind, reference in sorted((plan.get("references") or {}).items()):
            identity = reference.get(kind) if isinstance(reference, dict) else None
            if not isinstance(identity, str) or kind not in summaries:
                continue
            evidence.append({"kind": kind, "id": identity, "summary": summaries[kind]})
            if len(evidence) >= _MAX_EVIDENCE:
                return evidence
        if isinstance(plan.get("last_progress_identity"), str):
            evidence.append({
                "kind": "plan_progress",
                "id": plan["last_progress_identity"],
                "summary": "last durable research progress identity",
            })
        return evidence


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
