"""ADR-0085 P3: bounded research-judgment stage input, admission and proposal seam.

This is the Backend side of ADR-0085 §6. It is BYQ Domain Workflow, not a second
generic agent harness: it persists no DSH private context, hidden reasoning, tool
state or session journal, and it never starts a model turn itself.

Named server-side seams and NOTHING ELSE:

* ``get_research_stage_input`` is READ-ONLY. It returns the bounded stage input
  for a genuine research-judgment stage. A deterministic stage is refused: it
  MUST use zero model calls.
* ``admit_research_stage_call`` is the durable model-call admission. The trusted
  caller supplies only its call identity; the 1-based call index and the two-call
  bound are derived from a persisted per-task/plan/stage counter under the
  task-row lock. A caller can never choose, reset or exceed the count, and an
  exact replay returns the same admission.
* ``record_research_judgment_result`` is the ATOMIC trusted result operation used
  by the runtime-adapter consumer. In ONE transaction it validates a closed
  proposal, commits it through the deterministic reducer/plan CAS, records the
  authoritative durable-progress receipt, completes the stage-call admission and
  (for a terminal stage) converges the ResearchTask. Any failure rolls back the
  plan, task, call ledger and receipts together. An exact replay returns the same
  receipt without another write.
* ``commit_research_proposal`` / ``record_research_stage_progress`` remain the
  narrower named seams for direct server callers and are implemented on top of
  the same transaction-internal helpers.

There is NO generic plan/event/proposal write route and no agent-facing write
tool. The internal invocation endpoints are trusted service-to-service only.
"""

from __future__ import annotations

import hashlib
import json

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
    stage_model_call_limit,
    stage_model_call_outcome,
    stage_requires_model,
    validate_judgment_result_request,
    validate_progress_evidence,
    validate_proposal,
    validate_stage_admission_request,
    validate_stage_input,
    validate_stage_progress_request,
)

__all__ = ["ModelTurnNotAllowed", "StageModelCallLimitExceeded", "ResearchJudgmentMixin",
           "SCHEMA_DDL"]


class ModelTurnNotAllowed(ValueError):
    """A deterministic plan stage MUST NOT start a model turn (zero model calls)."""


class StageModelCallLimitExceeded(RuntimeError):
    """The durable per-stage model-call bound is already reached."""


SCHEMA_DDL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS research_judgment_stage_calls (
        task_id TEXT NOT NULL REFERENCES research_tasks(task_id),
        call_identity TEXT NOT NULL,
        plan_version INTEGER NOT NULL,
        stage TEXT NOT NULL,
        call_index INTEGER NOT NULL,
        status TEXT NOT NULL,
        admitted_at TIMESTAMPTZ NOT NULL,
        completed_at TIMESTAMPTZ,
        progress_identity TEXT,
        outcome TEXT,
        result_json JSONB,
        PRIMARY KEY (task_id, call_identity),
        UNIQUE (task_id, plan_version, stage, call_index)
    )
    """,
    """CREATE INDEX IF NOT EXISTS research_judgment_stage_calls_scope
        ON research_judgment_stage_calls(task_id, plan_version, stage)""",
]

_STAGE_INSTRUCTION = {
    "strategy_draft": "Propose the bounded strategy draft judgment for this research task.",
    "backtest_analysis": "Analyse the bounded backtest summary for the current round.",
    "iteration_comparison": "Compare the completed rounds and propose a bounded next step.",
    "final_selection": "Select the best round or escalate when evidence is insufficient.",
}

_COMPLETION_EVIDENCE_REFERENCE_KINDS = (
    "strategy_version", "strategy_approval", "signal_snapshot", "backtest_result",
)

RESULT_RECEIPT_SCHEMA_VERSION = "research-judgment-result-receipt.v1"


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class ResearchJudgmentMixin:
    """Read-only stage input, durable admission, atomic commit/progress and fence."""

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
            self._require_model_stage(plan["stage"])
            return self._build_stage_input(task, plan)

    # ------------------------------------------------------------------ #
    # Durable model-call admission
    # ------------------------------------------------------------------ #

    def admit_research_stage_call(self, task_id: str, payload: object, *,
                                  trusted_context: dict) -> dict:
        """Reserve one bounded model call for the current plan stage."""

        from .research import InvalidTransition, ResearchNotFound

        request = validate_stage_admission_request(payload)
        call_identity = str(request["call_identity"])
        attempt = request.get("attempt_binding")
        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=True)
            # A COMPLETED call is an idempotent replay FIRST, before any attempt or
            # current-plan check: its result may already have advanced the plan (and
            # even moved it to a non-judgment stage), so a late retry with the old
            # identity must return the stored receipt instead of failing the
            # attempt/plan binding. It never creates a row or runs a model turn.
            existing = self._load_stage_call(connection, task["task_id"], call_identity, lock=True)
            if existing is not None and existing["status"] == "completed":
                return {
                    "call_identity": existing["call_identity"], "status": "completed",
                    "receipt": existing["result_json"], "created": False,
                    "call_index": int(existing["call_index"]), "stage": existing["stage"],
                    "plan_version": int(existing["plan_version"]),
                }
            plan_row = self._load_current_plan(connection, task["task_id"], lock=True)
            if plan_row is None:
                raise ResearchNotFound("research execution plan not found")
            plan = validate_plan(plan_row["plan"])
            self._require_model_stage(plan["stage"])
            if attempt is not None:
                from packages.contracts.research_judgment import attempt_binding
                if attempt != attempt_binding(plan["plan_version"], plan["stage"], plan["iteration"]):
                    # A stale/forged/future attempt must not consume the stage budget.
                    raise InvalidTransition(
                        "research stage attempt binding does not match the current plan")
            if existing is not None:
                if (existing["plan_version"] != plan["plan_version"]
                        or existing["stage"] != plan["stage"]):
                    raise InvalidTransition(
                        "research stage call identity was reused for another plan revision")
                admission = self._stage_admission(existing, task, plan)
                admission["status"] = existing["status"]
                admission["created"] = False
                return admission
            counted = fetch_one(connection, """SELECT COUNT(*) AS count FROM research_judgment_stage_calls
                WHERE task_id = :task AND plan_version = :plan AND stage = :stage""",
                {"task": task["task_id"], "plan": plan["plan_version"], "stage": plan["stage"]})
            used = int(counted["count"]) if counted else 0
            limit = stage_model_call_limit(plan["stage"])
            if used >= limit:
                raise StageModelCallLimitExceeded(
                    "research stage model call limit reached for this plan revision")
            call_index = used + 1
            execute(connection, """INSERT INTO research_judgment_stage_calls
                (task_id, call_identity, plan_version, stage, call_index, status, admitted_at,
                 completed_at, progress_identity, outcome, result_json)
                VALUES (:task, :identity, :plan, :stage, :index, 'admitted', :now,
                        NULL, NULL, NULL, NULL)""",
                {"task": task["task_id"], "identity": call_identity, "plan": plan["plan_version"],
                 "stage": plan["stage"], "index": call_index, "now": _now()})
            row = self._load_stage_call(connection, task["task_id"], call_identity, lock=True)
            assert row is not None
            admission = self._stage_admission(row, task, plan)
            admission["status"] = "admitted"
            admission["created"] = True
            return admission

    # ------------------------------------------------------------------ #
    # Atomic trusted result operation
    # ------------------------------------------------------------------ #

    def record_research_judgment_result(self, task_id: str, payload: object, *,
                                        trusted_context: dict) -> dict:
        """Validate + commit + progress + complete in ONE transaction.

        A valid proposal whose durable evidence is malformed/foreign leaves the
        plan, task, stage-call ledger and receipts unchanged. An exact replay
        returns the stored receipt without another write.
        """

        from .research import InvalidTransition, ResearchNotFound

        request = validate_judgment_result_request(payload)
        call_identity = str(request["call_identity"])
        evidence = request["durable_evidence"]
        proposal = request.get("proposal")
        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=True)
            plan_row = self._load_current_plan(connection, task["task_id"], lock=True)
            if plan_row is None:
                raise ResearchNotFound("research execution plan not found")
            plan = validate_plan(plan_row["plan"])
            row = self._load_stage_call(connection, task["task_id"], call_identity, lock=True)
            if row is None:
                raise InvalidTransition("research stage call was not admitted")
            if int(row["plan_version"]) > plan["plan_version"]:
                raise InvalidTransition("research stage call belongs to a newer plan revision")
            if row["status"] == "completed":
                stored = row["result_json"] if isinstance(row["result_json"], dict) else {}
                return {**stored, "replayed": True}
            if row["status"] != "admitted":
                raise InvalidTransition("research stage call is not completable")
            self._require_model_stage(row["stage"])

            committed = None
            if proposal is not None:
                committed = self._commit_proposal_in_transaction(connection, task, plan, proposal)
                plan = committed["plan"]
            progress = self._complete_stage_call(connection, task, plan, row, evidence)
            receipt = {
                "schema_version": RESULT_RECEIPT_SCHEMA_VERSION,
                "call_identity": call_identity,
                "proposal": committed["projection"] if committed is not None else None,
                "proposal_identity": committed["proposal_identity"] if committed is not None else None,
                "progress": progress,
            }
            execute(connection, """UPDATE research_judgment_stage_calls SET
                status = 'completed', completed_at = :now, progress_identity = :progress,
                outcome = :outcome, result_json = :result
                WHERE task_id = :task AND call_identity = :identity AND status = 'admitted'""",
                {"now": _now(), "progress": progress.get("progress_identity"),
                 "outcome": progress.get("outcome"), "result": receipt,
                 "task": task["task_id"], "identity": call_identity})
            return {**receipt, "replayed": False}

    # ------------------------------------------------------------------ #
    # Narrow named seams (shared transaction-internal helpers)
    # ------------------------------------------------------------------ #

    def commit_research_proposal(self, task_id: str, payload: object, *,
                                 trusted_context: dict) -> dict:
        """Validate and commit one bounded research-judgment proposal."""

        from .research import ResearchNotFound

        proposal = validate_proposal(payload)
        if proposal["task_id"] != task_id:
            from .research import InvalidTransition
            raise InvalidTransition("research proposal task does not match its route")
        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=True)
            plan_row = self._load_current_plan(connection, task["task_id"], lock=True)
            if plan_row is None:
                raise ResearchNotFound("research execution plan not found")
            plan = validate_plan(plan_row["plan"])
            committed = self._commit_proposal_in_transaction(connection, task, plan, proposal)
            return committed["projection"]

    def record_research_stage_progress(self, task_id: str, payload: object, *,
                                       trusted_context: dict) -> dict:
        """Complete one admitted call with authoritative durable evidence."""

        from .research import InvalidTransition, ResearchNotFound

        request = validate_stage_progress_request(payload)
        call_identity = str(request["call_identity"])
        evidence = request["durable_evidence"]
        with self._transaction() as connection:
            task = self._plan_task(connection, task_id, trusted_context, lock=True)
            plan_row = self._load_current_plan(connection, task["task_id"], lock=True)
            if plan_row is None:
                raise ResearchNotFound("research execution plan not found")
            plan = validate_plan(plan_row["plan"])
            row = self._load_stage_call(connection, task["task_id"], call_identity, lock=True)
            if row is None:
                raise InvalidTransition("research stage call was not admitted")
            if int(row["plan_version"]) > plan["plan_version"]:
                raise InvalidTransition("research stage call belongs to a newer plan revision")
            if row["status"] == "completed":
                stored = row["result_json"] if isinstance(row["result_json"], dict) else {}
                return {**stored, "replayed": True}
            if row["status"] != "admitted":
                raise InvalidTransition("research stage call is not completable")
            self._require_model_stage(row["stage"])
            progress = self._complete_stage_call(connection, task, plan, row, evidence)
            execute(connection, """UPDATE research_judgment_stage_calls SET
                status = 'completed', completed_at = :now, progress_identity = :progress,
                outcome = :outcome, result_json = :result
                WHERE task_id = :task AND call_identity = :identity AND status = 'admitted'""",
                {"now": _now(), "progress": progress.get("progress_identity"),
                 "outcome": progress.get("outcome"), "result": progress,
                 "task": task["task_id"], "identity": call_identity})
            return progress

    # ------------------------------------------------------------------ #
    # Transaction-internal proposal commit
    # ------------------------------------------------------------------ #

    def _commit_proposal_in_transaction(self, connection, task, plan, payload) -> dict:
        from .research import IdempotencyConflict, InvalidTransition
        from .research_execution_plan import project_execution_plan

        proposal = validate_proposal(payload)
        if proposal["task_id"] != task["task_id"]:
            raise InvalidTransition("research proposal task does not match the plan")
        identity = proposal_identity(proposal)
        request_hash = proposal_request_hash(proposal)
        receipt = fetch_one(connection, """SELECT * FROM research_execution_plan_receipts
            WHERE task_id = :task AND idempotency_key = :key""",
            {"task": task["task_id"], "key": identity})
        if receipt is not None:
            if receipt["request_hash"] != request_hash:
                raise IdempotencyConflict("research proposal identity was reused")
            return {"plan": validate_plan(receipt["result_json"]),
                    "projection": {**project_execution_plan(receipt["result_json"]),
                                   "proposal_identity": identity, "replayed": True},
                    "proposal_identity": identity, "reason": "replayed", "replayed": True}

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
            advanced = plan
        execute(connection, """INSERT INTO research_execution_plan_receipts
            (task_id, idempotency_key, request_hash, plan_version, result_json)
            VALUES (:task_id, :idempotency_key, :request_hash, :plan_version, :result_json)""",
            {"task_id": task["task_id"], "idempotency_key": identity,
             "request_hash": request_hash, "plan_version": advanced["plan_version"],
             "result_json": advanced})
        return {"plan": advanced, "projection": {**project_execution_plan(advanced),
                "proposal_identity": identity, "replayed": False, "reason": decision["reason"]},
                "proposal_identity": identity, "reason": decision["reason"], "replayed": False}

    # ------------------------------------------------------------------ #
    # Transaction-internal progress completion + fence
    # ------------------------------------------------------------------ #

    def _complete_stage_call(self, connection, task, plan, admission, evidence) -> dict:
        """Derive progress, fence if needed, and return the progress result (no write)."""

        evidence = validate_progress_evidence(evidence)
        # Validate the named evidence record authoritatively EVEN when an accepted
        # proposal already advanced the plan: a malformed/foreign record must fail
        # closed and roll the proposal commit back with it.
        evidence_identity = self._derive_progress_identity(connection, task, plan, admission, evidence)
        plan_advanced = plan["plan_version"] > int(admission["plan_version"])
        if plan_advanced:
            progress_identity = _hash({
                "kind": "plan_advance", "task_id": task["task_id"],
                "plan_version": plan["plan_version"],
                "last_progress_identity": plan.get("last_progress_identity")})
        else:
            progress_identity = evidence_identity
        if plan_advanced and plan["stage"] != admission["stage"]:
            outcome = {"status": "stop", "outcome": "advance", "reason": "stage_advanced",
                       "model_calls_used": int(admission["call_index"]),
                       "model_calls_remaining": 0, "continue": False}
        else:
            outcome = stage_model_call_outcome(
                stage=admission["stage"], calls_used=int(admission["call_index"]),
                durable_progress_identity=progress_identity)
        result = {**outcome, "call_identity": admission["call_identity"],
                  "call_index": int(admission["call_index"]),
                  "progress_identity": progress_identity,
                  "plan_moved_to_needs_attention": False, "replayed": False}
        if (outcome["status"] == "stop" and outcome["outcome"] == "needs_attention"
                and not plan_advanced):
            self._apply_stage_needs_attention(
                connection, task, plan, str(outcome["reason"]),
                f"stage-fence-{admission['call_identity']}")
            result["plan_moved_to_needs_attention"] = True
        return result

    def _derive_progress_identity(self, connection, task, plan, admission, evidence) -> str | None:
        """Derive the progress identity from a persisted BYQ record (never a digest)."""

        kind = evidence["kind"]
        if kind == "none":
            return None
        if kind == "plan_advance":
            if plan["plan_version"] <= int(admission["plan_version"]):
                return None
            return _hash({"kind": "plan_advance", "task_id": task["task_id"],
                          "plan_version": plan["plan_version"],
                          "last_progress_identity": plan.get("last_progress_identity")})
        if kind in {"artifact", "experiment"}:
            table, id_column = ("artifacts", "artifact_id") if kind == "artifact" else (
                "experiments", "experiment_id")
            row = fetch_one(connection, f"""SELECT * FROM {table}
                WHERE {id_column} = :id AND task_id = :task AND owner_principal = :owner
                  AND workspace_id = :workspace""",
                {"id": evidence["id"], "task": task["task_id"], "owner": task["owner_principal"],
                 "workspace": task["workspace_id"]})
            if row is None:
                raise ValueError("research progress evidence does not belong to this task")
            if row["created_at"] < admission["admitted_at"]:
                raise ValueError("research progress evidence predates the admitted call")
            return _hash({"kind": kind, "id": row[id_column],
                          "content_sha256": row.get("content_sha256") or row.get("request_hash"),
                          "created_at": row["created_at"]})
        if kind == "backtest_job":
            job = fetch_one(connection, """SELECT * FROM backtest_jobs
                WHERE job_id = :id AND task_id = :task AND owner_principal = :owner""",
                {"id": evidence["id"], "task": task["task_id"], "owner": task["owner_principal"]})
            if job is None:
                raise ValueError("research progress evidence does not belong to this task")
            if job["status"] not in {"completed", "failed", "cancelled"}:
                raise ValueError("research progress backtest job is not terminal")
            if not isinstance(job.get("result_artifact_id"), str):
                raise ValueError("research progress backtest job has no durable result")
            return _hash({"kind": "backtest_job", "id": job["job_id"], "status": job["status"],
                          "result_artifact_id": job["result_artifact_id"]})
        raise ValueError("research progress evidence kind is unknown")

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
        if target_stage == "completed":
            new_task_version = self._complete_research_task(connection, task, plan, identity)
            advanced = validate_plan({**advanced, "task_version": new_task_version})
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

    def _complete_research_task(self, connection, task, plan, identity) -> int:
        """Atomically complete the ResearchTask using validated durable evidence."""

        references = plan.get("references") or {}
        evidence_ids: list[str] = []
        for kind in _COMPLETION_EVIDENCE_REFERENCE_KINDS:
            reference = references.get(kind)
            if isinstance(reference, dict) and isinstance(reference.get(kind), str):
                evidence_ids.append(reference[kind])
        checkpoint = {
            "schema_version": "research-progress.v1",
            "stage": "completed",
            "next_action": None,
            "blocked_reason": None,
            "linked_objects": [],
            "completion_evidence": evidence_ids,
        }
        self.transition("research_task", task["task_id"], "completed",
                        f"{identity}-complete", progress=checkpoint,
                        require_completion_evidence=True, _connection=connection)
        updated = fetch_one(connection, "SELECT version FROM research_tasks WHERE task_id = :task",
                            {"task": task["task_id"]})
        return int(updated["version"])

    def _apply_stage_needs_attention(self, connection, task, plan, reason, identity):
        """Atomically move plan + ResearchTask to ``needs_attention``."""

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
        """Mint the target stage's exact bound approval from the plan's own reference."""

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
    # Persistence / bounded projection helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _load_stage_call(connection, task_id: str, call_identity: str, *, lock: bool = False):
        clause = "FOR UPDATE" if lock else ""
        return fetch_one(connection, f"""SELECT * FROM research_judgment_stage_calls
            WHERE task_id = :task AND call_identity = :identity {clause}""",
            {"task": task_id, "identity": call_identity})

    def _stage_admission(self, row, task, plan) -> dict:
        return {
            "call_identity": row["call_identity"],
            "call_index": int(row["call_index"]),
            "model_call_limit": stage_model_call_limit(plan["stage"]),
            "stage": plan["stage"],
            "plan_version": plan["plan_version"],
            "task_version": plan["task_version"],
            "stage_input": self._build_stage_input(task, plan),
        }

    def _build_stage_input(self, task, plan) -> dict:
        return validate_stage_input({
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
            "evidence": self._stage_evidence(plan),
            "allowed_tools": sorted(self._stage_tools(plan["stage"])),
            "model_call_limit": stage_model_call_limit(plan["stage"]),
            "escalation_allowed": True,
        })

    @staticmethod
    def _stage_tools(stage: str):
        from packages.contracts.research_judgment import STAGE_ALLOWED_TOOLS

        return STAGE_ALLOWED_TOOLS[stage]

    @staticmethod
    def _stage_evidence(plan: dict) -> list:
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
            if len(evidence) >= 32:
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
