#!/usr/bin/env python3
"""Trusted in-container consumer for the ADR-0085 P4 journey driver.

This runs INSIDE the isolated Backend container and drives the production
plan-continuation seam and the P2 ledger adapters by their exact persisted
identities. It is the trusted consumer that ADR-0085 P2/P4 always assumed; it is
NOT a second generic agent harness or session store and it never starts a model
turn. Every command takes exact persisted identities, never caller routing.

Invoked by scripts/v091/continuation_p4/run_journey.py as:

    docker compose exec -T backend python - <command> <<< '<json>'
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from app.agent_research import AgentResearchStore
from app.research import ResearchStore


def _context(store: ResearchStore, task_id: str) -> dict:
    row = store._fetch_one("SELECT * FROM research_tasks WHERE task_id = :task",
                           {"task": task_id})
    if row is None:
        raise SystemExit(json.dumps({"error": "task_not_found", "task_id": task_id}))
    return {"owner_principal": row["owner_principal"], "workspace_id": row["workspace_id"],
            "conversation_id": row["conversation_id"]}


def _judgment_context(store: ResearchStore, task_id: str) -> dict:
    """Exact trusted identity and authoritative attempt binding for the entry."""

    context = _context(store, task_id)
    catalog = store._fetch_one(
        "SELECT runtime_session_id, trace_id FROM product_conversations WHERE conversation_id = :c",
        {"c": context["conversation_id"]})
    dispatch = _dispatch(store, task_id, context)
    attempt = f"{dispatch['plan_version']}:{dispatch['stage']}:{dispatch['iteration']}"
    return {"context": context, "trace_id": catalog["trace_id"],
            "runtime_session_id": catalog["runtime_session_id"],
            "dispatch": dispatch, "attempt": attempt}


def _plan(store: ResearchStore, task_id: str, context: dict) -> dict:
    return store.get_execution_plan(task_id, trusted_context=context)


def _dispatch(store: ResearchStore, task_id: str, context: dict) -> dict:
    return store.plan_continuation_dispatch(task_id, trusted_context=context)


def _state(store: ResearchStore, task_id: str) -> dict:
    context = _context(store, task_id)
    task = store._fetch_one("SELECT * FROM research_tasks WHERE task_id = :task",
                            {"task": task_id})
    plan_row = store._fetch_one("SELECT * FROM research_execution_plans WHERE task_id = :task",
                                {"task": task_id})
    approvals = store._execute(
        "SELECT approval_id, action, status, resource_type, resource_id, plan_version,"
        " plan_task_version, plan_params_digest, plan_idempotency_key FROM agent_approvals"
        " WHERE owner_principal = :owner ORDER BY created_at", {"owner": task["owner_principal"]})
    events = store._execute(
        "SELECT event_id, event_type, status, outcome, admitted FROM research_continuation_events"
        " WHERE task_id = :task ORDER BY created_at", {"task": task_id})
    stage_calls = store._execute(
        "SELECT call_identity, stage, call_index, status FROM research_judgment_stage_calls"
        " WHERE task_id = :task ORDER BY admitted_at", {"task": task_id})
    counts = {
        "research_tasks": store._fetch_one("SELECT COUNT(*) AS c FROM research_tasks")["c"],
        "research_execution_plans": store._fetch_one(
            "SELECT COUNT(*) AS c FROM research_execution_plans")["c"],
        "research_continuation_events": store._fetch_one(
            "SELECT COUNT(*) AS c FROM research_continuation_events")["c"],
        "research_judgment_stage_calls": store._fetch_one(
            "SELECT COUNT(*) AS c FROM research_judgment_stage_calls")["c"],
        "agent_approvals": store._fetch_one(
            "SELECT COUNT(*) AS c FROM agent_approvals WHERE owner_principal = :o",
            {"o": task["owner_principal"]})["c"],
        "artifacts": store._fetch_one(
            "SELECT COUNT(*) AS c FROM artifacts WHERE task_id = :task", {"task": task_id})["c"],
        "backtest_jobs": store._fetch_one(
            "SELECT COUNT(*) AS c FROM backtest_jobs WHERE task_id = :task", {"task": task_id})["c"],
        "paper_accounts": store._fetch_one(
            "SELECT COUNT(*) AS c FROM paper_accounts WHERE owner_principal = :o",
            {"o": task["owner_principal"]})["c"],
    }
    return {"task_status": task["status"], "task_version": task["version"],
            "plan": plan_row["plan"] if plan_row else None,
            "approvals": [dict(row) for row in (approvals or [])],
            "events": [dict(row) for row in (events or [])],
            "stage_calls": [dict(row) for row in (stage_calls or [])],
            "counts": counts, "context": context}


def _start_run(store: ResearchStore, task_id: str, key: str) -> dict:
    context = _context(store, task_id)
    catalog = store._fetch_one(
        "SELECT runtime_session_id, trace_id FROM product_conversations WHERE conversation_id = :c",
        {"c": context["conversation_id"]})
    agent = AgentResearchStore()
    try:
        run = agent.start_run({
            "owner_principal": context["owner_principal"],
            "actor_principal": context["owner_principal"], "role_id": "quant_orchestrator",
            "trace_id": catalog["trace_id"], "session_id": catalog["runtime_session_id"],
            "dsh_run_id": catalog["runtime_session_id"] + "-p4", "idempotency_key": key})
        return run
    finally:
        agent.close()


def _request_approval(store: ResearchStore, task_id: str) -> dict:
    context = _context(store, task_id)
    return store.request_plan_approval(task_id, trusted_context=context)


def _decide_approval(store: ResearchStore, task_id: str, approval_id: str,
                     decision: str) -> dict:
    context = _context(store, task_id)
    agent = AgentResearchStore()
    try:
        decided = agent.decide_approval(
            {"approval_id": approval_id, "decision": decision},
            trusted_owner=context["owner_principal"], trusted_actor="p4-human-reviewer")
        target = agent.plan_bound_approval_target(approval_id,
                                                  trusted_owner=context["owner_principal"])
        if target is not None and target.get("decision") in {"approved", "rejected"}:
            store.record_plan_approval_event(
                target["task_id"], approval_id,
                trusted_context={"owner_principal": target["owner_principal"],
                                 "workspace_id": target["workspace_id"]})
        return decided
    finally:
        agent.close()


def _seed_signal_job(store: ResearchStore, task_id: str, strategy_id: str,
                     pool_snapshot_id: str) -> dict:
    """Create one real signal producer job for the exact task (no worker run)."""
    import hashlib

    context = _context(store, task_id)
    job_id = "signaljob_" + hashlib.sha256(f"p4-{task_id}".encode()).hexdigest()[:32]
    existing = store._fetch_one("SELECT job_id FROM signal_producer_jobs WHERE job_id = :j",
                                {"j": job_id})
    if existing is not None:
        return {"job_id": job_id, "created": False}
    store._execute(
        """INSERT INTO signal_producer_jobs
        (job_id, owner_principal, task_id, strategy_version_artifact_id,
         stock_pool_snapshot_id, status, input_json, input_sha256, trace_id,
         idempotency_key, request_hash, created_at, updated_at)
        VALUES (:job, :owner, :task, :strategy, :pool, 'completed', '{}'::jsonb, 'p4', :trace,
                :key, 'p4', now(), now())""",
        {"job": job_id, "owner": context["owner_principal"], "task": task_id,
         "strategy": strategy_id, "pool": pool_snapshot_id, "trace": "p4-trace", "key": job_id})
    return {"job_id": job_id, "created": True}


def _seed_backtest_job(store: ResearchStore, task_id: str, key: str) -> dict:
    import hashlib

    context = _context(store, task_id)
    job_id = "backtest_" + hashlib.sha256(f"p4-bt-{task_id}-{key}".encode()).hexdigest()[:32]
    existing = store._fetch_one("SELECT job_id FROM backtest_jobs WHERE job_id = :j",
                                {"j": job_id})
    if existing is not None:
        return {"job_id": job_id, "created": False}
    store._execute(
        """INSERT INTO backtest_jobs
        (job_id, task_id, owner_principal, status, request_json, request_hash, input_manifest_id,
         input_manifest_json, strategy_version_artifact_id, approval_artifact_id,
         idempotency_key, attempts, max_attempts, created_at, updated_at)
        VALUES (:job, :task, :owner, 'completed', '{}'::jsonb, 'p4', 'p4', '{}'::jsonb,
                :strategy, :approval, :key, 1, 3, now(), now())""",
        {"job": job_id, "task": task_id, "owner": context["owner_principal"],
         "strategy": "artifact_" + "0" * 32, "approval": "artifact_" + "1" * 32, "key": key})
    return {"job_id": job_id, "created": True}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit("command required")
    command = argv[1]
    payload = json.loads(sys.stdin.read() or "{}")
    store = ResearchStore()
    try:
        if command == "state":
            result = _state(store, payload["task_id"])
        elif command == "judgment-context":
            result = _judgment_context(store, payload["task_id"])
        elif command == "start-run":
            result = _start_run(store, payload["task_id"], payload["key"])
        elif command == "request-approval":
            result = _request_approval(store, payload["task_id"])
        elif command == "decide-approval":
            result = _decide_approval(store, payload["task_id"], payload["approval_id"],
                                      payload.get("decision", "approved"))
        elif command == "seed-signal-job":
            result = _seed_signal_job(store, payload["task_id"], payload["strategy_id"],
                                      payload["pool_snapshot_id"])
        elif command == "seed-backtest-job":
            result = _seed_backtest_job(store, payload["task_id"], payload["key"])
        elif command == "record-data-ready":
            context = _context(store, payload["task_id"])
            result = store.record_data_ready_event(payload["task_id"], payload["signal_job_id"],
                                                   trusted_context=context)
        elif command == "record-backtest-completed":
            context = _context(store, payload["task_id"])
            result = store.record_backtest_completed_event(
                payload["task_id"], payload["backtest_job_id"], trusted_context=context)
        elif command == "apply-action":
            context = _context(store, payload["task_id"])
            result = store.apply_deterministic_action_result(
                payload["task_id"], payload["source"], trusted_context=context)
        elif command == "dispatch":
            result = _dispatch(store, payload["task_id"], _context(store, payload["task_id"]))
        else:
            raise SystemExit(f"unknown command {command}")
        print(json.dumps(result, default=str))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
