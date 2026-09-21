#!/usr/bin/env python3
"""Seed the real authoritative Backend before-state for the acceptance.

Runs INSIDE the Backend container against the isolated PostgreSQL and uses the
real stores only (no test double, no direct business-table shortcut). It creates
real users/workspaces, real bound conversations, real tasks, validated confirmed
artifacts, real continuation permissions and real continuation rows.

The happy task is bound to the acceptance Runtime Adapter session. The three
fail-closed negative reservations live in their own conversations so they never
interfere with the Gateway consumer; their negative decisions are still made by
the real Backend service over real HTTP.

Emits one JSON object on stdout with the exact identifiers the driver needs.
"""
from __future__ import annotations

import hashlib
import json

from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchStore
from tests.workspace_helpers import trusted_agent_context

OWNER = "recovery-acceptance-user"
SESSION = "recovery-acceptance-session"
TRACE = "recovery-acceptance-trace"
TOKEN_LIMIT = 2 * (1048576 + 8192)
CHARGED = 1048584
DIGEST = "9e952dd54f430824f4f5f61f47d892c39d1908472c1b81147714f52329648085"


def instruction(task_id: str) -> str:
    event = {"kind": "ml_training_runs", "identity": "training_" + "0" * 32,
             "status": "completed", "updated_at": "2026-09-21T00:00:00+00:00"}
    return ("BYQ trusted task continuation. Resume only the original research goal for task "
            + task_id + ". A durable domain event is " + json.dumps(event, sort_keys=True) + ".")


def _context(store, suffix):
    session_id = SESSION if suffix == "happy" else f"recovery-acceptance-{suffix}"
    trace_id = TRACE if suffix == "happy" else f"recovery-acceptance-{suffix}-trace"
    headers = trusted_agent_context(OWNER, session_id=session_id, trace_id=trace_id)
    context = {key.removeprefix("x-byq-").replace("-", "_"): value for key, value in headers.items()}
    catalog = ConversationCatalogStore()
    conversation = catalog.create(OWNER, session_id, trace_id)
    catalog.close()
    return context, conversation["conversation_id"]


def _make_task(store, context, suffix, conversation_id, *, token_limit, charged, run_id, event_suffix):
    task = store.create_task({"owner_principal": OWNER, "title": "Recovery acceptance " + suffix,
        "objective": "Accept the merged business-recovery vertical slice.",
        "trace_id": context["trace_id"], "idempotency_key": "recovery-acceptance-task-" + suffix},
        trusted_context=context)
    artifact = store.create_artifact({"task_id": task["task_id"], "kind": "research_note",
        "content": {"synthetic": True}, "lineage": [], "trace_id": context["trace_id"],
        "idempotency_key": "recovery-acceptance-artifact-" + suffix})
    store.transition("artifact", artifact["artifact_id"], "validated", "recovery-acceptance-validate-" + suffix)
    store.create_continuation_permission(task["task_id"], {
        "idempotency_key": "recovery-acceptance-permission-" + suffix, "token_limit": 12_000_000,
        "confirmed_artifact_ids": [artifact["artifact_id"]]}, trusted_context=context)
    text = instruction(task["task_id"])
    reservation = store.reserve_continuation_budget(task["task_id"], trusted_context=context,
        grant_version=1, event_key="recovery-acceptance-event-" + event_suffix,
        input_sha256=hashlib.sha256(text.encode()).hexdigest(),
        token_limit=token_limit, instruction=text)
    if run_id is not None:
        store.record_continuation_receipt(task["task_id"], trusted_context=context,
            reservation_id=reservation["reservation_id"], status="accepted", run_id=run_id,
            **({"charged_tokens": charged} if charged is not None else {}))
    return {"task_id": task["task_id"], "artifact_id": artifact["artifact_id"],
            "conversation_id": conversation_id, "reservation_id": reservation["reservation_id"],
            "instruction": text}


def main() -> int:
    store = ResearchStore()
    try:
        results = {}
        for suffix, token_limit, charged, run_id in (
                ("happy", TOKEN_LIMIT, None, None),
                ("unknown", TOKEN_LIMIT, None, "1" * 32),
                ("floor", 1, 0, "2" * 32),
                ("ordinal", TOKEN_LIMIT, 0, "3" * 32),
                ("snapshot", TOKEN_LIMIT, 0, "4" * 32)):
            context, conversation_id = _context(store, suffix)
            results[suffix] = _make_task(store, context, suffix, conversation_id,
                token_limit=token_limit, charged=charged, run_id=run_id,
                event_suffix={"happy": "0001", "unknown": "0002", "floor": "0003", "ordinal": "0004",
                              "snapshot": "0005"}[suffix])
            if suffix == "happy":
                owner_context = context
                main_conversation = conversation_id
        attempts = [{"attempt_key": "recovery_" + "a" * 32, "ordinal": index,
                     "trigger_key": "%064x" % index, "interrupted_run_id": run,
                     "interrupted_generation": "generation-seed-%d" % index,
                     "containment_attempt": 1, "interrupted_executor_epoch": 1,
                     "snapshot_tail_sequence": 0, "snapshot_digest": DIGEST,
                     "status": "settled", "run_id": run, "target_executor_epoch": 1,
                     "target_generation": "generation-target-%d" % index, "charged_tokens": 0}
                    for index, run in ((1, "a" * 32), (2, "b" * 32), (3, "c" * 32))]
        store._execute("UPDATE research_tasks SET continuation_budget = jsonb_set(continuation_budget, "
            "'{0,recovery_attempts}', CAST(:attempts AS jsonb)) WHERE task_id=:task",
            {"attempts": json.dumps(attempts), "task": results["ordinal"]["task_id"]})
        from packages.contracts import business_recovery as contract
        snap_run, snap_generation = "4" * 32, "generation-seed-snap"
        trigger = contract.trigger_key(results["snapshot"]["reservation_id"], snap_run, snap_generation, 1, 1)
        snapshot_attempt = [{"attempt_key": contract.attempt_key(trigger, 1), "ordinal": 1,
            "trigger_key": trigger, "interrupted_run_id": snap_run,
            "interrupted_generation": snap_generation, "containment_attempt": 1,
            "interrupted_executor_epoch": 1, "snapshot_tail_sequence": 0, "snapshot_digest": DIGEST,
            "status": "settled", "run_id": snap_run, "target_executor_epoch": 1,
            "target_generation": "generation-snapshot-target", "charged_tokens": 0}]
        store._execute("UPDATE research_tasks SET continuation_budget = jsonb_set(continuation_budget, "
            "'{0,recovery_attempts}', CAST(:attempts AS jsonb)) WHERE task_id=:task",
            {"attempts": json.dumps(snapshot_attempt), "task": results["snapshot"]["task_id"]})
        print(json.dumps({
            "schema_version": "byq-v090-business-recovery-seed.v1",
            "owner": OWNER, "workspace_id": owner_context["workspace_id"],
            "session_id": SESSION, "trace_id": TRACE, "conversation_id": main_conversation,
            "charged_tokens": CHARGED,
            "happy": results["happy"], "unknown_cost": results["unknown"],
            "below_floor": results["floor"], "ordinal_cap": results["ordinal"],
            "snapshot_change": results["snapshot"],
        }, sort_keys=True))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
