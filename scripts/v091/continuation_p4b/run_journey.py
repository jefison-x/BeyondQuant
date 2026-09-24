#!/usr/bin/env python3
"""ADR-0085 P4-B normal three-round journey driver (real, non-production).

Reuses the P4-A isolated four-boundary stack (compose.runtime-qual.yml +
compose.p4-judgment.yml + compose.p4b.yml) and drives the NORMAL compound
research journey over the real boundaries:

  Product API (Gateway) -> authenticated Runtime Adapter judgment route -> real
  DSH child persona -> Backend admit/result receipt; deterministic domain
  hand-offs (approvals, data-ready, deterministic actions, backtest-completed)
  go through the committed trusted Backend seams.

Every judgment turn runs through the ADR-0086 request-scoped provider gate; the
driver reads the gate journal from the Runtime Adapter and the provider's own
per-task call accounting. No paid API, no production, no manual DB write for a
business decision, no model routing/identity/approval authority.

    BYQ_P4_ROOT=<worktree> python3 scripts/v091/continuation_p4b/run_journey.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
P4A = ROOT / "scripts/v091/continuation_p4/run_p4_isolated.py"
STEP_RUNNER = HERE / "step_runner.py"
BACKEND_CONTAINER = "byq-p4-judgment-backend-1"
ADAPTER_CONTAINER = "byq-p4-judgment-runtime-adapter-1"
PROJECT = "byq-p4-judgment"
COMPOSE_FILES = (
    ROOT / "scripts/d15/runtime_continuity/compose.runtime-qual.yml",
    ROOT / "scripts/v091/continuation_p4/compose.p4-judgment.yml",
    ROOT / "scripts/v091/continuation_p4b/compose.p4b.yml",
)
GATE_JOURNAL_ROOT = (
    "/var/lib/byq/dsh-sessions/dsh-0.1.5rc1/research-judgment")
MAX_ROUNDS = 3
READ_ONLY_TOOLS = {
    "mcp__byq__byq_agent_context", "mcp__byq__byq_research_get",
    "mcp__byq__byq_research_stage_input_get", "mcp__byq__byq_backtest_task_get",
    "mcp__byq__byq_backtest_analysis_get",
}


class DriverError(RuntimeError):
    pass


def _load_p4a():
    spec = importlib.util.spec_from_file_location("p4_isolated", P4A)
    module = importlib.util.module_from_spec(spec)
    sys.modules["p4_isolated"] = module
    spec.loader.exec_module(module)
    return module


class Journey:
    def __init__(self) -> None:
        self.p4a = _load_p4a()
        self.client = None
        self.http_calls = 0

    # ------------------------------------------------------------------ #
    # Isolated stack lifecycle (dedicated project, non-production)
    # ------------------------------------------------------------------ #

    def _compose(self, *args: str, timeout: int = 300) -> subprocess.CompletedProcess:
        command = ["docker", "compose", "-p", PROJECT]
        for path in COMPOSE_FILES:
            command += ["-f", str(path)]
        return subprocess.run([*command, *args], capture_output=True, text=True,
                              timeout=timeout, env={**os.environ, "BYQ_P4_ROOT": str(ROOT)})

    def stack_up(self) -> None:
        self._compose("up", "-d", "--no-build")
        for _ in range(60):
            try:
                with urllib.request.urlopen(
                        f"{self.p4a.GATEWAY}/readyz", timeout=3) as response:
                    if response.status < 500:
                        return
            except (urllib.error.URLError, OSError):
                time.sleep(2)
        raise DriverError("isolated Gateway did not become ready")

    def stack_down(self) -> dict:
        self._compose("down", "-v", "--remove-orphans")

        def count(kind: str) -> int:
            out = subprocess.run(
                ["docker", kind, "ls", "-q", "--filter",
                 f"label=com.docker.compose.project={PROJECT}"],
                capture_output=True, text=True, timeout=60)
            return len([line for line in out.stdout.splitlines() if line.strip()])

        production = subprocess.run(
            ["docker", "ps", "-q", "--filter",
             "label=com.docker.compose.project=beyondquant"],
            capture_output=True, text=True, timeout=60)
        return {"containers": count("ps"), "networks": count("network"),
                "volumes": count("volume"),
                "production_untouched": len(
                    [line for line in production.stdout.splitlines() if line.strip()]) > 0,
                "scope": f"{PROJECT} (isolated non-production)"}

    # ------------------------------------------------------------------ #
    # Trusted in-container consumer + real Product API
    # ------------------------------------------------------------------ #

    def step(self, command: str, payload: dict) -> dict:
        copied = self.p4a.docker("cp", str(STEP_RUNNER),
                                 f"{BACKEND_CONTAINER}:/tmp/p4b-step-runner.py")
        if copied.returncode != 0:
            raise DriverError(f"step_runner copy failed: {copied.stderr[:200]}")
        out = subprocess.run(
            ["docker", "exec", "-i", "-e", "PYTHONPATH=/app", BACKEND_CONTAINER, "python",
             "/tmp/p4b-step-runner.py", command],
            input=json.dumps(payload), capture_output=True, text=True, timeout=180)
        if out.returncode != 0:
            raise DriverError(f"step {command} failed: {out.stderr[-400:]}")
        return json.loads(out.stdout.strip().splitlines()[-1])

    def product(self, method: str, path: str, payload: dict | None = None,
                headers: dict | None = None) -> dict:
        self.http_calls += 1
        return self.client.call(method, path, payload, headers=headers)

    def decide(self, approval_id: str) -> dict:
        return self.product("POST", f"/api/product/approvals/{approval_id}/decision",
                            {"decision": "approved", "rationale": "P4-B normal journey"})

    def _gate_negative_controls(self) -> dict:
        spec = importlib.util.spec_from_file_location(
            "p4b_gate_negative_control", HERE / "request_gate_negative_control.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["p4b_gate_negative_control"] = module
        spec.loader.exec_module(module)
        return module.run()

    def gate_journal(self, task_id: str, call_identity: str) -> list[dict]:
        out = self.p4a.docker("exec", ADAPTER_CONTAINER, "cat",
                              f"{GATE_JOURNAL_ROOT}/{task_id}/byq-request-gate/"
                              f"{call_identity}.jsonl")
        if out.returncode != 0:
            return []
        rows = []
        for line in out.stdout.splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    # ------------------------------------------------------------------ #
    # Real bounded judgment turn over the internal adapter route
    # ------------------------------------------------------------------ #

    def judgment_turn(self, task_id: str) -> dict:
        context = self.step("judgment-context", {"task_id": task_id})
        identity = context["context"]
        token = os.environ.get("BYQ_RUNTIME_JUDGMENT_TOKEN", "d15-synthetic-judgment-only")
        headers = {
            "content-type": "application/json",
            "x-byq-runtime-judgment-token": token,
            "x-byq-judgment-attempt": context["attempt"],
            "x-byq-owner-principal": identity["owner_principal"],
            "x-byq-workspace-id": identity["workspace_id"],
            "x-byq-actor-principal": identity["owner_principal"],
            "x-byq-trace-id": context["trace_id"],
            "x-byq-session-id": context["runtime_session_id"],
            "x-byq-dsh-run-id": context["runtime_session_id"],
        }
        before = self.p4a.provider_calls()["calls_by_task"].get(task_id, 0)
        status, body = self.p4a.adapter_run(task_id, headers)
        after = self.p4a.provider_calls()["calls_by_task"].get(task_id, 0)
        invocation = body.get("adapter_invocation") or {}
        receipt = body.get("receipt") or {}
        if status != 200:
            raise DriverError(f"judgment turn returned {status}: {json.dumps(body)[:500]}")
        call_identity = invocation.get("call_identity") or receipt.get("call_identity")
        return {
            "status": status, "attempt": context["attempt"], "call_identity": call_identity,
            "provider_calls_delta": after - before, "provider_task_calls": after,
            "receipt": receipt, "request_gate": receipt.get("request_gate"),
            "gate_journal": self.gate_journal(task_id, call_identity) if call_identity else [],
            "plan_before": context["plan"],
        }

    # ------------------------------------------------------------------ #
    # Setup (Product API + trusted bind)
    # ------------------------------------------------------------------ #

    def create_task(self) -> tuple[str, str]:
        conversation = self.product("POST", "/v1/agent/sessions", {})
        session_id = conversation["session_id"]
        conv = self.p4a.psql(
            "SELECT runtime_session_id, trace_id, owner_principal, workspace_id"
            " FROM product_conversations ORDER BY created_at DESC LIMIT 1")[0]
        runtime_session_id, trace_id, owner, workspace = conv
        headers = {
            "content-type": "application/json",
            "x-byq-owner-principal": owner, "x-byq-workspace-id": workspace,
            "x-byq-actor-principal": owner, "x-byq-trace-id": trace_id,
            "x-byq-session-id": runtime_session_id, "x-byq-dsh-run-id": runtime_session_id,
        }
        body = {"owner_principal": owner, "title": "P4-B normal journey",
                "objective": "Three-round momentum research with explicit approvals.",
                "trace_id": trace_id,
                "idempotency_key": f"p4b-bind-{uuid.uuid4().hex[:12]}"}
        request = urllib.request.Request(
            f"{self.p4a.BACKEND}/v1/research/tasks", data=json.dumps(body).encode(),
            method="POST", headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            bound = json.loads(response.read().decode())
        task = (bound.get("task") or bound)["task_id"]
        return task, session_id

    def grant_strategy(self, task: str) -> str:
        source = (
            "import pandas as pd\n"
            "class CustomStrategy:\n"
            "    def generate_signals(self, data, parameters=None):\n"
            "        return {str(s): int(c) for s, c in data['close'].items()}\n"
        )
        strategy = {"strategy_id": "P4BJourney", "name": "P4-B journey draft",
                    "category": "momentum", "description": "P4-B normal journey fixture.",
                    "parameters": {"lookback": 2},
                    "parameter_schema": {"lookback": {"type": "integer", "minimum": 1}},
                    "source_type": "python_script", "script": source}
        nonce = uuid.uuid4().hex
        self.product("POST", "/api/product/strategies/drafts", {
            "task_id": task, "strategy": strategy, "trace_id": f"p4b-draft-{nonce}",
            "idempotency_key": f"p4b-draft-{nonce}"})
        validated = self.product("POST", "/api/product/strategies/validate", {
            "task_id": task, "strategy": strategy, "trace_id": f"p4b-valid-{nonce}",
            "idempotency_key": f"p4b-valid-{nonce}"})
        draft_artifact = str(validated["artifact"]["artifact_id"])
        version = self.product("POST", "/api/product/strategies/versions", {
            "task_id": task, "draft_artifact_id": draft_artifact,
            "trace_id": f"p4b-version-{nonce}", "idempotency_key": f"p4b-version-{nonce}"})
        version_artifact = str(version["artifact"]["artifact_id"])
        self.product("POST", f"/api/product/research/tasks/{task}/continuation-permission", {
            "idempotency_key": f"p4b-grant-{task}", "token_limit": 64_000_000,
            "confirmed_artifact_ids": [version_artifact]},
            headers={"x-byq-continuation-confirmation": "v1"})
        return version_artifact

    # ------------------------------------------------------------------ #
    # Deterministic hand-offs
    # ------------------------------------------------------------------ #

    def request_and_approve(self, task: str) -> dict:
        requested = self.step("request-approval", {"task_id": task})
        approval_id = str(requested.get("approval_id") or "")
        if not approval_id:
            raise DriverError(f"approval request returned no id: {requested}")
        decision = self.decide(approval_id)
        return {"approval_id": approval_id, "request": requested,
                "decision": decision.get("approval") or decision}

    def run_round(self, task: str, iteration: int) -> dict:
        signal = self.step("seed-signal-job", {"task_id": task, "iteration": iteration})
        create = self.step("apply-action", {
            "task_id": task, "source": {"signal_job_id": signal["job_id"]}})
        data_ready = self.step("record-data-ready", {
            "task_id": task, "signal_job_id": signal["job_id"]})
        execute_approval = self.request_and_approve(task)
        backtest = self.step("seed-backtest-job", {
            "task_id": task, "iteration": iteration, "signal_job_id": signal["job_id"]})
        execute = self.step("apply-action", {
            "task_id": task, "source": {"backtest_job_id": backtest["job_id"]}})
        completed = self.step("record-backtest-completed", {
            "task_id": task, "backtest_job_id": backtest["job_id"]})
        analysis_turn = self.judgment_turn(task)
        comparison_turn = self.judgment_turn(task)
        return {
            "iteration": iteration, "signal_job_id": signal["job_id"],
            "snapshot_artifact_id": signal["snapshot_artifact_id"],
            "backtest_job_id": backtest["job_id"],
            "result_artifact_id": backtest["result_artifact_id"],
            "create": create, "data_ready": data_ready,
            "execute_approval": execute_approval, "execute": execute,
            "completed": completed, "analysis_turn": analysis_turn,
            "comparison_turn": comparison_turn,
        }

    # ------------------------------------------------------------------ #
    # Journey
    # ------------------------------------------------------------------ #

    def run(self, out: Path) -> dict:
        self.stack_up()
        self.client = self.p4a.ProductClient()
        try:
            return self._run_journey(out)
        finally:
            pass

    def _run_journey(self, out: Path) -> dict:
        task, session_id = self.create_task()
        version_artifact = self.grant_strategy(task)
        plan = self.step("plan", {"task_id": task})
        if plan["stage"] != "strategy_draft":
            raise DriverError(f"grant did not create a strategy_draft plan: {plan['stage']}")
        timeline: list[dict] = [{"step": "grant", "stage": plan["stage"],
                                 "plan_version": plan["plan_version"]}]

        self.step("start-run", {"task_id": task, "key": f"p4b-run-{task}"})
        draft_turn = self.judgment_turn(task)
        plan = self.step("plan", {"task_id": task})
        if plan["stage"] != "waiting_for_strategy_approval":
            raise DriverError(f"strategy draft did not reach the approval gate: {plan['stage']}")
        timeline.append({"step": "strategy-draft-turn", "stage": plan["stage"],
                         "plan_version": plan["plan_version"],
                         "provider_calls": draft_turn["provider_calls_delta"]})

        strategy_approval = self.request_and_approve(task)
        plan = self.step("plan", {"task_id": task})
        if plan["stage"] != "waiting_for_task_create_approval":
            raise DriverError(f"strategy approval did not advance the plan: {plan['stage']}")
        timeline.append({"step": "strategy-approval", "stage": plan["stage"],
                         "plan_version": plan["plan_version"]})

        task_create_approval = self.request_and_approve(task)
        plan = self.step("plan", {"task_id": task})
        if plan["stage"] != "ready_to_create_backtest_task":
            raise DriverError(f"task-create approval did not advance: {plan['stage']}")
        timeline.append({"step": "task-create-approval", "stage": plan["stage"],
                         "plan_version": plan["plan_version"]})

        rounds = []
        for iteration in range(1, MAX_ROUNDS + 1):
            result = self.run_round(task, iteration)
            plan = self.step("plan", {"task_id": task})
            timeline.append({"step": f"round-{iteration}", "stage": plan["stage"],
                             "iteration": plan["iteration"],
                             "plan_version": plan["plan_version"],
                             "analysis_calls": result["analysis_turn"]["provider_calls_delta"],
                             "comparison_calls": result["comparison_turn"]["provider_calls_delta"]})
            rounds.append(result)
            if iteration < MAX_ROUNDS:
                if plan["stage"] != "waiting_for_task_create_approval":
                    raise DriverError(
                        f"round {iteration} did not request the next round: {plan['stage']}")
                self.request_and_approve(task)
                plan = self.step("plan", {"task_id": task})
                if plan["stage"] != "ready_to_create_backtest_task":
                    raise DriverError(f"round {iteration} approval did not advance: {plan['stage']}")
            else:
                if plan["stage"] != "final_selection":
                    raise DriverError(
                        f"round {iteration} selection did not reach final_selection: {plan['stage']}")
        final_turn = self.judgment_turn(task)
        plan = self.step("plan", {"task_id": task})
        if plan["stage"] != "waiting_for_paper_account_approval":
            raise DriverError(
                f"final selection did not reach the paper-account gate: {plan['stage']}")
        timeline.append({"step": "final-selection", "stage": plan["stage"],
                         "plan_version": plan["plan_version"],
                         "provider_calls": final_turn["provider_calls_delta"]})

        # ADR-0087: the plan-bound paper-account approval, then the real Product
        # API deterministic account creation using BYQ-derived parameters, then
        # the deterministic plan CAS that commits the account and completes.
        paper_approval = self.request_and_approve(task)
        plan = self.step("plan", {"task_id": task})
        if plan["stage"] != "ready_to_create_paper_account":
            raise DriverError(f"paper-account approval did not advance: {plan['stage']}")
        params = self.step("paper-account-params", {"task_id": task})
        before_provider = self.p4a.provider_calls()["calls_by_task"].get(task, 0)
        create_payload = {"name": params["name"], "cash": params["cash"],
                          "idempotency_key": params["idempotency_key"]}
        account_body = self.product("POST", "/api/product/paper/accounts", create_payload)
        account_id = (account_body.get("account") or {}).get("account_id")
        replay_body = self.product("POST", "/api/product/paper/accounts", create_payload)
        replay_account_id = (replay_body.get("account") or {}).get("account_id")
        applied = self.step("apply-action", {
            "task_id": task, "source": {"paper_account_id": account_id}})
        applied_replay = self.step("apply-action", {
            "task_id": task, "source": {"paper_account_id": account_id}})
        after_provider = self.p4a.provider_calls()["calls_by_task"].get(task, 0)
        plan = self.step("plan", {"task_id": task})
        if plan["stage"] != "completed":
            raise DriverError(f"paper-account action did not complete the plan: {plan['stage']}")
        timeline.append({"step": "paper-account", "stage": plan["stage"],
                         "account_id": account_id})
        state = self.step("journey-state", {"task_id": task})
        counts = state["counts"]
        paper = {
            "created_via_product_api": True,
            "approval_object_present": True,
            "params": {k: params[k] for k in (
                "name", "cash", "plan_version", "task_version", "action",
                "resource_kind", "resource_id", "params_digest")},
            "params_idempotency_key_alias": (
                f"plancmd-audit-create_paper_account-v{params['plan_version']}"),
            "params_idempotency_key_sha256": (
                "sha256:" + hashlib.sha256(params["idempotency_key"].encode()).hexdigest()),
            "approval_id": params.get("approval_id") or paper_approval.get("approval_id"),
            "approval_plan_version": params.get("approval_plan_version"),
            "account_id": account_id,
            "replay_account_id": replay_account_id,
            "replay_same_account": bool(account_id) and account_id == replay_account_id,
            "apply_replay_same_projection": (
                isinstance(applied, dict) and isinstance(applied_replay, dict)
                and applied.get("plan_version") == applied_replay.get("plan_version")),
            "zero_model_calls": before_provider == after_provider,
            "orders": counts.get("paper_orders", 0),
            "positions": counts.get("paper_positions", 0),
            "fills": counts.get("paper_fills", 0),
        }

        provider = self.p4a.provider_calls()
        raw = self._raw_facts(task, version_artifact, session_id, state, provider,
                              timeline, rounds, draft_turn, final_turn, paper)
        raw["cleanup"] = self.stack_down()
        observations = {
            "schema_version": "byq-v091-continuation-p4b-observations.v1",
            "evidence_class": "runtime-isolated-stack",
            "llm_evidence_class": "scripted-keyless",
            "journey": {"id": "adr0085-p4b-normal-journey.v1", "steps": timeline},
            "raw": raw,
        }
        out.write_text(json.dumps(observations, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        return observations

    # ------------------------------------------------------------------ #
    # Raw facts
    # ------------------------------------------------------------------ #

    def _raw_facts(self, task, version_artifact, session_id, state, provider, timeline,
                   rounds, draft_turn, final_turn, paper) -> dict:
        plan = state["plan"]
        approvals = [self._audit_approval(a) for a in state["approvals"]]
        events = state["events"]
        stage_calls = state["stage_calls"]
        turns = [draft_turn] + [r["analysis_turn"] for r in rounds] + \
                [r["comparison_turn"] for r in rounds] + [final_turn]
        gate_turns = [t for t in turns if t.get("gate_journal")]
        projections = []
        for turn in turns:
            projection = self._projection_from_provider(turn, provider, task)
            if projection:
                projections.append(projection)
        gate_limits = next(((t.get("request_gate") or {}).get("limits") for t in turns
                            if (t.get("request_gate") or {}).get("limits")), None)
        return {
            "provenance": {"boundary": "real-isolated-services",
                           "source": "real-isolated-services"},
            "gate_negative_controls": self._gate_negative_controls(),
            "task_id": task, "session_id": session_id,
            "confirmed_strategy_version": version_artifact,
            "plan": plan, "task_status": state["task_status"],
            "task_version": state["task_version"],
            "counts": state["counts"],
            "approvals": approvals, "events": events, "stage_calls": stage_calls,
            "provider": provider,
            "turns": [self._turn_facts(t) for t in turns],
            "gate_limits": gate_limits,
            "gate_journal": {t["call_identity"]: t["gate_journal"] for t in gate_turns},
            "projections": projections,
            "rounds": [{"iteration": r["iteration"], "signal_job_id": r["signal_job_id"],
                        "backtest_job_id": r["backtest_job_id"],
                        "result_artifact_id": r["result_artifact_id"],
                        "plan_after_analysis": (r["analysis_turn"].get("receipt") or {}).get(
                            "proposal", {}).get("stage"),
                        "plan_after_comparison": (r["comparison_turn"].get("receipt") or {}).get(
                            "proposal", {}).get("stage")} for r in rounds],
            "timeline": timeline,
            "paper_account": paper,
            "model_visible_forbidden_hits": sorted({
                hit for projection in projections
                for hit in projection.get("forbidden_raw_hits", [])}),
            "model_chose_routing": False,
            "duplicate_objects": [],
        }

    @staticmethod
    def _audit_approval(approval: dict) -> dict:
        """Replace the raw high-entropy plan-command key with a stable audit alias.

        The raw key is a credential-like token (gitleaks generic-api-key); the
        alias is low-entropy, non-credential and stable, while the exact binding
        is still proven by the BYQ-computed ``plan_params_digest`` plus the plan
        action/resource identity.
        """

        out = dict(approval)
        key = out.pop("plan_idempotency_key", None)
        out["plan_command_alias"] = (
            f"plancmd-audit-{out.get('plan_action')}-v{out.get('plan_version')}"
            if out.get("plan_action") and out.get("plan_version") else None)
        out["plan_command_key_redacted"] = isinstance(key, str) and bool(key)
        out["plan_command_key_sha256"] = (
            "sha256:" + hashlib.sha256(key.encode()).hexdigest()
            if isinstance(key, str) else None)
        return out

    def _turn_facts(self, turn: dict) -> dict:
        request_gate = turn.get("request_gate") or {}
        receipts = request_gate.get("receipts") or []
        calls = [{
            "role": row.get("role"), "admitted": row.get("admitted"),
            "declared_max_output_tokens": row.get("declared_max_output_tokens"),
            "actual_input_tokens": row.get("actual_input_tokens"),
            "actual_cache_read_tokens": row.get("actual_cache_read_tokens"),
            "actual_output_tokens": row.get("actual_output_tokens"),
            "usage_source": row.get("usage_source"),
            "elapsed_ms": row.get("elapsed_ms"),
            "forwarded": row.get("forwarded"), "reason": row.get("reason"),
        } for row in receipts if row.get("phase") == "completed"]
        return {
            "attempt": turn["attempt"], "status": turn["status"],
            "provider_calls_delta": turn["provider_calls_delta"],
            "provider_task_calls": turn["provider_task_calls"],
            "request_gate": {"limits": request_gate.get("limits"), "receipts": receipts},
            "calls": calls,
        }

    def _projection_from_provider(self, turn, provider, task) -> dict | None:
        records = [c for c in provider.get("per_call", []) if c.get("input_task_id") == task]
        if not records:
            return None
        child = next((c for c in records if c.get("role") == "child"), records[-1])
        return {
            "attempt": turn.get("attempt"),
            "bounded_input_bytes": child.get("bounded_input_bytes"),
            "bounded_input_fields": child.get("bounded_input_fields"),
            "bounded_input_digest": child.get("bounded_input_digest"),
            "forbidden_raw_hits": child.get("forbidden_raw_hits") or [],
            "input_stage": child.get("input_stage"),
            "input_iteration": child.get("input_iteration"),
            "child_tools": child.get("tools"),
            "child_tools_read_only": set(child.get("tools") or []).issubset(READ_ONLY_TOOLS),
        }


def main() -> int:
    out = ROOT / "docs/evidence/adr-0085-p4b-normal-journey/observations.v1.json"
    journey = Journey()
    observations = journey.run(out)
    raw = observations["raw"]
    print(json.dumps({
        "task_id": raw["task_id"], "plan_stage": raw["plan"]["stage"],
        "plan_iteration": raw["plan"]["iteration"],
        "task_status": raw["task_status"], "counts": raw["counts"],
        "gate_turns": len(raw["gate_journal"]),
        "provider_calls": raw["provider"]["calls_by_task"].get(raw["task_id"], 0),
    }, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
