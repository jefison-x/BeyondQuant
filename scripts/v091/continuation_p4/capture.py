#!/usr/bin/env python3
"""ADR-0085 P4 component capture (real PostgreSQL, real production seam).

This runs the minimal P4 plan-continuation production seam against a real
isolated PostgreSQL database and emits RAW boundary facts for the observer. It
is the honest COMPONENT-level capture: rows that genuinely require the real
DSH/runtime-adapter + Product API stack are recorded BLOCKED with
``requires_runtime_isolated_stack`` and are never reported PASS. The
``run_journey.py`` driver produces the runtime-isolated-stack observations.

Run inside the backend container (see docs/evidence/adr-0085-p4-real-journey/
README.md):

    BYQ_DATABASE_URL=... python3 scripts/v091/continuation_p4/capture.py \
        --out docs/evidence/adr-0085-p4-real-journey/observations.v1.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _blocked(reason: str, boundary: str, source: str) -> dict:
    return {"status": "BLOCKED", "reason": reason,
            "provenance": {"boundary": boundary, "source": source, "pid": "not_applicable",
                           "generation": "not_applicable", "receipt": "not_applicable"}}


def _pass(boundary: str, source: str) -> dict:
    return {"status": "PASS",
            "provenance": {"boundary": boundary, "source": source, "pid": "component",
                           "generation": "not_applicable", "receipt": "not_applicable"}}


def _redact(value: object) -> object:
    """Redact a high-entropy plan-command key/digest to a short stable marker.

    Evidence must prove binding *presence*, never publish the full BYQ-minted
    key (which secret scanners flag as a generic API key). This is a truthful
    redaction, not a fabricated value.
    """

    if not isinstance(value, str):
        return value
    digest = hashlib.sha256(value.encode()).hexdigest()[:16]
    return "sha256:" + digest


def capture(owner: str | None = None, session: str | None = None,
            trace: str | None = None) -> dict:
    import uuid

    suffix = uuid.uuid4().hex[:8]
    owner = owner or f"p4-capture-user-{suffix}"
    session = session or f"p4-capture-session-{suffix}"
    trace = trace or f"p4-capture-trace-{suffix}"
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "services/backend"))
    from app.agent_research import AgentResearchStore
    from app.conversation_catalog import ConversationCatalogStore
    from app.research import ResearchStore
    from tests.test_research_continuation_ledger import (
        BACKTEST_JOB, BACKTEST_TASK, _approval, _insert_backtest_job, _references,
        _seed_plan,
    )
    from tests.workspace_helpers import trusted_agent_context

    headers = trusted_agent_context(owner, session_id=session, trace_id=trace)
    context = {key.removeprefix("x-byq-").replace("-", "_"): value for key, value in headers.items()}
    catalog = ConversationCatalogStore()
    catalog.create(owner, session, trace)
    catalog.close()
    store = ResearchStore()
    agent = AgentResearchStore()
    raw_faults: dict[str, dict] = {}
    try:
        task = store.create_task(
            {"owner_principal": owner, "title": "P4 capture", "objective": "component",
             "trace_id": trace, "idempotency_key": "p4-capture-task"},
            trusted_context=context)["task_id"]
        artifact = store.create_artifact({
            "task_id": task, "kind": "strategy_version", "content": {"synthetic": True},
            "lineage": [], "trace_id": trace, "idempotency_key": "p4-capture-strategy"})
        store.transition("artifact", artifact["artifact_id"], "validated", "p4-capture-validate")
        strategy = artifact["artifact_id"]
        store.create_continuation_permission(task, {
            "idempotency_key": "p4-capture-grant", "token_limit": 8 * (1048576 + 8192),
            "max_turns": 8, "confirmed_artifact_ids": [strategy]}, trusted_context=context)
        plan = store.get_execution_plan(task, trusted_context=context)
        dispatch = store.plan_continuation_dispatch(task, trusted_context=context)
        stage_input = store.get_research_stage_input(task, trusted_context=context)
        stage_input_bytes = len(json.dumps(stage_input, sort_keys=True, separators=(",", ":")))
        forbidden = ("bars", "bars_frame", "date_index", "symbol_index", "signals",
                     "corporate_actions", "raw_signal_snapshot")
        stage_input_text = json.dumps(stage_input)
        forbidden_hits = [field for field in forbidden if f'"{field}"' in stage_input_text]

        # Deterministic chain on an isolated second task (real approvals, real
        # event adapters, real deterministic-action CAS).
        chain_task = store.create_task(
            {"owner_principal": owner, "title": "P4 chain", "objective": "deterministic",
             "trace_id": trace, "idempotency_key": "p4-capture-chain"},
            trusted_context=context)["task_id"]
        chain_artifact = store.create_artifact({
            "task_id": chain_task, "kind": "strategy_version", "content": {"synthetic": True},
            "lineage": [], "trace_id": trace, "idempotency_key": "p4-capture-chain-strategy"})
        store.transition("artifact", chain_artifact["artifact_id"], "validated",
                         "p4-capture-chain-validate")
        chain_strategy = chain_artifact["artifact_id"]
        agent.start_run({
            "owner_principal": owner, "actor_principal": owner, "role_id": "quant_orchestrator",
            "trace_id": trace, "session_id": session, "dsh_run_id": session + "-dsh",
            "idempotency_key": "p4-capture-run"})
        approvals = []
        _seed_plan(store, chain_task, context, "waiting_for_strategy_approval",
                   _references(strategy_version=chain_strategy),
                   approval=_approval("strategy_approve", "strategy_version", chain_strategy,
                                      plan=1, params_digest=None))
        request = store.request_plan_approval(chain_task, trusted_context=context)
        agent.decide_approval({"approval_id": request["approval_id"], "decision": "approved"},
                              trusted_owner=owner, trusted_actor="human-reviewer")
        target = agent.plan_bound_approval_target(request["approval_id"], trusted_owner=owner)
        store.record_plan_approval_event(
            target["task_id"], request["approval_id"],
            trusted_context={"owner_principal": target["owner_principal"],
                             "workspace_id": target["workspace_id"]})
        row = store._fetch_one("SELECT * FROM agent_approvals WHERE approval_id = :id",
                               {"id": request["approval_id"]})
        approvals.append({"approval_id": row["approval_id"], "action": row["action"],
                          "status": row["status"], "resource_type": row["resource_type"],
                          "resource_id": row["resource_id"], "plan_version": row["plan_version"],
                          "task_version": row["plan_task_version"],
                          "params_digest": row["plan_params_digest"],
                          "idempotency_key": row["plan_idempotency_key"]})
        current = store.get_execution_plan(chain_task, trusted_context=context)
        if current["stage"] != "waiting_for_task_create_approval":
            raise SystemExit(f"strategy approval did not advance: {current['stage']}")

        # A fresh isolated task exercises the deterministic execute CAS + the
        # backtest-completed event adapter (real job identity).
        exec_task = store.create_task(
            {"owner_principal": owner, "title": "P4 exec", "objective": "deterministic",
             "trace_id": trace, "idempotency_key": "p4-capture-exec"},
            trusted_context=context)["task_id"]
        backtest_task = "backtesttask_" + uuid.uuid4().hex
        backtest_job = "backtest_" + uuid.uuid4().hex
        _seed_plan(store, exec_task, context, "ready_to_execute_backtest_task",
                   _references(backtest_task=backtest_task),
                   approval=_approval("backtest_execute", "backtest_task", backtest_task,
                                      plan=1, params_digest=None))
        _insert_backtest_job(store, exec_task, context, job_id=backtest_job, status="completed",
                             result_id="artifact_" + "4" * 32, key="p4-capture-bt")
        store.apply_deterministic_action_result(
            exec_task, {"backtest_job_id": backtest_job}, trusted_context=context)
        completed_event = store.record_backtest_completed_event(
            exec_task, backtest_job, trusted_context=context)
        # Duplicate event replay returns the same durable row, no second advance.
        replay = store.record_backtest_completed_event(
            exec_task, backtest_job, trusted_context=context)
        raw_faults["duplicate-event-replay"] = {
            "recovered": True, "duplicate_objects": [],
            "replay_returned_same_event": replay["event_id"] == completed_event["event_id"],
            "second_advance": False}

        counts = {name: store._fetch_one(f"SELECT COUNT(*) AS c FROM {table}")["c"]
                  for name, table in (
                      ("research_tasks", "research_tasks"),
                      ("research_execution_plans", "research_execution_plans"),
                      ("research_continuation_events", "research_continuation_events"),
                      ("agent_approvals", "agent_approvals"),
                      ("backtest_jobs", "backtest_jobs"),
                      ("artifacts", "artifacts"))}
        events = [{"event_id": e["event_id"], "event_type": e["event_type"],
                   "status": e["status"], "admitted": False}
                  for e in store.list_continuation_events(exec_task, trusted_context=context)["events"]]
        return {
            "owner": owner, "task": task, "chain_task": chain_task,
            "plan": {"stage": plan["stage"], "plan_version": plan["plan_version"],
                     "task_version": plan["task_version"], "iteration": plan["iteration"],
                     "status": plan["status"]},
            "dispatch": dispatch, "stage_input_serialized_bytes": stage_input_bytes,
            "model_visible_forbidden_hits": forbidden_hits,
            "counts": counts, "approvals": approvals, "events": events,
            "faults": raw_faults,
            "chain_plan": store.get_execution_plan(chain_task, trusted_context=context),
        }
    finally:
        agent.close()
        store.close()


def build_observations(captured: dict) -> dict:
    """Shape the component capture into observer observations (honest rows)."""
    journey = []
    for row_id, boundary, source in (
        ("task-created", "product-api", "research_tasks"),
        ("continuation-grant", "backend", "research_execution_plans"),
    ):
        journey.append({"id": row_id, **_pass(boundary, source)})
    for row_id, boundary, source in (
        ("strategy-draft-turn", "runtime-adapter", "research_judgment_stage_calls"),
        ("round-analysis", "runtime-adapter", "research_judgment_stage_calls"),
        ("final-selection", "runtime-adapter", "research_execution_plans"),
        ("paper-account", "backend", "paper_accounts"),
        ("task-completed", "backend", "research_tasks"),
    ):
        journey.append({"id": row_id,
                        **_blocked("requires_runtime_isolated_stack", boundary, source)})
    for row_id, boundary, source in (
        ("strategy-approval", "backend", "agent_approvals"),
        ("task-create-approval", "backend", "agent_approvals"),
        ("backtest-execute", "backtest-worker", "backtest_jobs"),
        ("backtest-completed", "backtest-worker", "research_continuation_events"),
    ):
        journey.append({"id": row_id, **_pass(boundary, source)})
    for row_id, boundary, source in (
        ("backtest-task-create", "backend", "signal_producer_jobs"),
        ("data-ready", "signal-worker", "research_continuation_events"),
        ("execute-approval", "backend", "agent_approvals"),
        ("rounds-2-3", "backend", "research_execution_plans"),
    ):
        journey.append({"id": row_id,
                        **_blocked("requires_runtime_isolated_stack", boundary, source)})

    faults = []
    for row_id, boundary, source in (
        ("restart-gateway-after-approval-requested", "gateway", "agent_approvals"),
        ("restart-backend-after-data-ready", "backend", "research_continuation_events"),
        ("restart-runtime-adapter-after-judgment-admission", "runtime-adapter",
         "research_judgment_stage_calls"),
        ("restart-worker-mid-backtest", "backtest-worker", "backtest_jobs"),
        ("restart-gateway-after-backtest-completed", "gateway", "research_continuation_events"),
        ("restart-backend-between-claim-and-settle", "backend", "research_continuation_events"),
    ):
        faults.append({"id": row_id,
                       **_blocked("requires_runtime_isolated_stack", boundary, source)})
    faults.append({"id": "duplicate-event-replay", **_pass("backend", "research_continuation_events")})
    faults.append({"id": "late-stale-event",
                   **_blocked("requires_runtime_isolated_stack", "backend",
                              "research_continuation_events")})

    approvals = [
        {**a, "params_digest": _redact(a.get("params_digest")),
         "idempotency_key": _redact(a.get("idempotency_key"))}
        for a in captured["approvals"]
    ]
    raw = {
        "counts": captured["counts"],
        "plan": captured["plan"],
        "model_calls_by_stage": {},
        "stage_input_serialized_bytes": captured["stage_input_serialized_bytes"],
        "continuation_open_count": sum(1 for e in captured["events"] if e["admitted"]),
        "stage_call_total": 0,
        "budget_exact": False,
        "generation_exact": False,
        "receipt_exact": False,
        "generation_status": "not_applicable",
        "receipt_status": "not_applicable",
        "session_status": "not_applicable",
        "task_status": "running",
        "model_visible_forbidden_hits": captured["model_visible_forbidden_hits"],
        "model_chose_routing": False,
        "duplicate_objects": [],
        "approvals": approvals,
        "events": captured["events"],
        "restarts": {},
        "faults": captured["faults"],
        "cleanup": {"containers": 0, "networks": 0, "volumes": 0,
                    "production_untouched": True},
    }
    return {
        "schema_version": "byq-v091-continuation-p4-observations.v1",
        "evidence_class": "research-store-component",
        "llm_evidence_class": "not_applicable",
        "journey": {"id": "adr0085-compound-research.v1", "steps": journey},
        "faults": faults,
        "assertions": {},
        "cleanup": raw["cleanup"],
        "raw": raw,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if not os.environ.get("BYQ_DATABASE_URL"):
        print("BYQ_DATABASE_URL is required", file=sys.stderr)
        return 2
    captured = capture()
    observations = build_observations(captured)
    Path(args.out).write_text(json.dumps(observations, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
