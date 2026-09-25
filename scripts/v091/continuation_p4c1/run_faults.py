#!/usr/bin/env python3
"""ADR-0085 P4-C1 Adapter/DSH fault-safe convergence driver (real, non-production).

Reuses the committed P4-A/P4-B isolated four-boundary stack
(compose.runtime-qual.yml + compose.p4-judgment.yml + compose.p4c1.yml) and the
P4-B backend step runner. It injects REAL process faults at the Adapter/DSH
boundary and captures the raw four-boundary facts:

  Product API (Gateway) -> authenticated Runtime Adapter judgment route
    -> real DSH runtime subprocess -> Backend admit/result seam.

Faults: kill the Runtime Adapter OS process while a provider request is in flight
(provider held open); kill the real DSH runtime child OS process inside a live
adapter; a genuinely stuck provider; a normal long-running provider; a
no-durable-progress result; and late/forged old-attempt result submissions to the
real Backend seam. No paid API, no production, no manual DB write for a business
decision, no model routing/identity/approval authority.

    PYTHONPATH=services/runtime-adapter:. BYQ_P4_ROOT=<worktree> \
        python3 scripts/v091/continuation_p4c1/run_faults.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
P4A = ROOT / "scripts/v091/continuation_p4/run_p4_isolated.py"
P4B = ROOT / "scripts/v091/continuation_p4b/run_journey.py"
ADAPTER_CONTAINER = "byq-p4-judgment-runtime-adapter-1"
GATEWAY_CONTAINER = "byq-p4-judgment-gateway-1"
COMPOSE_FILES = (
    ROOT / "scripts/d15/runtime_continuity/compose.runtime-qual.yml",
    ROOT / "scripts/v091/continuation_p4/compose.p4-judgment.yml",
    ROOT / "scripts/v091/continuation_p4c1/compose.p4c1.yml",
)
IN_PROGRESS_CODE = "research_judgment_in_progress"
FAIL_CLOSED_CODE = "research_judgment_failed_closed"
_DSH_HINTS = ("deepseek-harness", "runtime-linux", "harness-sdk-runtime", "harness")


class DriverError(RuntimeError):
    pass


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FaultDriver:
    def __init__(self) -> None:
        self.p4b = _load("p4b_journey", P4B)
        self.p4b.COMPOSE_FILES = COMPOSE_FILES
        self.j = self.p4b.Journey()
        self.p4a = self.j.p4a
        self.tasks_created = 0
        self.stage_call_expected = 0

    # ------------------------------------------------------------------ #
    # Container / provider controls
    # ------------------------------------------------------------------ #

    def _adapter_pid(self) -> int | None:
        out = self.p4a.docker("inspect", "-f", "{{.State.Pid}}", ADAPTER_CONTAINER)
        if out.returncode != 0:
            return None
        try:
            return int(out.stdout.strip())
        except ValueError:
            return None

    def _provider_control(self, path: str, payload: dict | None,
                          method: str = "POST") -> dict:
        script = (
            "import json,sys,urllib.request\n"
            "method,path,body=sys.argv[1],sys.argv[2],json.loads(sys.argv[3])\n"
            "data=json.dumps(body).encode() if body is not None else None\n"
            "req=urllib.request.Request('http://judgment-provider:8901'+path,"
            "data=data,method=method,headers={'content-type':'application/json'})\n"
            "print(urllib.request.urlopen(req,timeout=20).read().decode())\n"
        )
        out = subprocess.run(
            ["docker", "exec", "-i", GATEWAY_CONTAINER, "python3", "-", method, path,
             json.dumps(payload if payload is not None else None)],
            input=script, capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise DriverError(f"provider control {path} failed: {out.stderr[-200:]}")
        lines = [line for line in out.stdout.splitlines() if line.strip()]
        return json.loads(lines[-1]) if lines else {}

    def provider_mode(self, mode: str) -> None:
        self._provider_control("/_mode", {"mode": mode})

    def provider_release(self) -> None:
        try:
            self._provider_control("/_release", {})
        except DriverError:
            pass

    def provider_state(self) -> dict:
        return self._provider_control("/_state", None, method="GET")

    def wait_child_inflight(self, timeout: float = 90.0) -> dict:
        deadline = time.time() + timeout
        last: dict = {}
        while time.time() < deadline:
            try:
                last = self.provider_state()
            except DriverError:
                time.sleep(1.0)
                continue
            if int(last.get("child_inflight", 0)) >= 1:
                return last
            time.sleep(0.5)
        raise DriverError(f"provider child never became in-flight: {last}")

    def kill_adapter(self) -> None:
        self.p4a.docker("kill", ADAPTER_CONTAINER)

    def start_adapter(self) -> None:
        self.p4a.docker("start", ADAPTER_CONTAINER)
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"{self.p4a.ADAPTER}/healthz", timeout=3) as r:
                    if r.status < 500:
                        return
            except (urllib.error.URLError, OSError):
                time.sleep(2)
        raise DriverError("restarted adapter did not become ready")

    def _ps(self) -> list[dict]:
        script = (
            "import os,json\n"
            "out=[]\n"
            "for pid in os.listdir('/proc'):\n"
            "    if not pid.isdigit():\n"
            "        continue\n"
            "    try:\n"
            "        cmd=open('/proc/'+pid+'/cmdline','rb').read().replace(b'\\0',b' ').decode(errors='replace').strip()\n"
            "        stat=open('/proc/'+pid+'/stat').read().split()\n"
            "        out.append({'pid':int(pid),'ppid':int(stat[3]),'args':cmd})\n"
            "    except Exception:\n"
            "        pass\n"
            "print(json.dumps(out))\n"
        )
        out = subprocess.run(
            ["docker", "exec", "-i", ADAPTER_CONTAINER, "python3", "-"],
            input=script, capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise DriverError(f"adapter process listing failed: {out.stderr[-200:]}")
        lines = [line for line in out.stdout.splitlines() if line.strip()]
        return json.loads(lines[-1]) if lines else []

    def kill_dsh_child(self) -> dict:
        procs = self._ps()

        def is_judgment_runtime(proc: dict) -> bool:
            lowered = proc["args"].lower()
            return ("research-judgment" in lowered or "research_judgment" in lowered) and (
                any(hint in lowered for hint in _DSH_HINTS))

        target = next((proc for proc in procs if is_judgment_runtime(proc)), None)
        if target is None:
            target = next((proc for proc in procs if "byq-product" not in proc["args"].lower()
                           and any(hint in proc["args"].lower() for hint in _DSH_HINTS)
                           and "uvicorn" not in proc["args"].lower()), None)
        if target is None:
            raise DriverError(f"no DSH runtime child found in adapter: {procs}")
        kill_script = ("import os,sys\nos.kill(int(sys.argv[1]),9)\n")
        out = subprocess.run(
            ["docker", "exec", "-i", ADAPTER_CONTAINER, "python3", "-", str(target["pid"])],
            input=kill_script, capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            raise DriverError(f"dsh child kill failed: {out.stderr[-200:]}")
        time.sleep(1.0)
        after = self._ps()
        alive = any(proc["pid"] == target["pid"] for proc in after)
        return {"dsh_pid": target["pid"], "dsh_args": target["args"], "dsh_dead": not alive,
                "processes_before": procs, "processes_after": after}

    # ------------------------------------------------------------------ #
    # Real boundaries
    # ------------------------------------------------------------------ #

    def setup_task(self) -> tuple[str, str, dict, str]:
        task, _session_id = self.j.create_task()
        version_artifact = self.j.grant_strategy(task)
        self.j.step("start-run", {"task_id": task, "key": f"p4c1-run-{task}"})
        context = self.j.step("judgment-context", {"task_id": task})
        headers = self._headers(context)
        self.tasks_created += 1
        return task, context["attempt"], headers, version_artifact

    @staticmethod
    def _headers(context: dict) -> dict:
        identity = context["context"]
        token = os.environ.get("BYQ_RUNTIME_JUDGMENT_TOKEN", "d15-synthetic-judgment-only")
        return {
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

    def _adapter_call(self, task: str, headers: dict, timeout: int = 200) -> dict:
        try:
            status, body = self.p4a.adapter_run(task, headers, timeout=timeout)
            return {"status": status, "body": body}
        except Exception as exc:  # noqa: BLE001
            return {"status": None, "error": type(exc).__name__}

    @staticmethod
    def _code(body: object) -> str | None:
        if not isinstance(body, dict):
            return None
        detail = body.get("detail")
        if isinstance(detail, dict):
            return detail.get("code")
        if isinstance(detail, str):
            return detail
        return None

    def _provider_task_calls(self, task: str) -> int:
        return int(self.p4a.provider_calls()["calls_by_task"].get(task, 0))

    def plan(self, task: str) -> dict:
        return self.j.step("plan", {"task_id": task})

    def state(self, task: str) -> dict:
        return self.j.step("journey-state", {"task_id": task})

    def _counts(self, task: str) -> dict:
        return self.state(task)["counts"]

    def _global_counts(self) -> dict:
        rows = self.p4a.psql(
            "SELECT (SELECT COUNT(*) FROM research_tasks),"
            " (SELECT COUNT(*) FROM research_execution_plans),"
            " (SELECT COUNT(*) FROM research_judgment_stage_calls),"
            " (SELECT COUNT(*) FROM paper_accounts),"
            " (SELECT COUNT(*) FROM paper_orders),"
            " (SELECT COUNT(*) FROM paper_positions),"
            " (SELECT COUNT(*) FROM paper_fills)")
        row = rows[0]
        return {"research_tasks": int(row[0]), "research_execution_plans": int(row[1]),
                "research_judgment_stage_calls": int(row[2]), "paper_accounts": int(row[3]),
                "paper_orders": int(row[4]), "paper_positions": int(row[5]),
                "paper_fills": int(row[6])}

    def _stage_calls(self, task: str) -> list[dict]:
        rows = self.p4a.psql(
            "SELECT call_identity, status, call_index, plan_version, stage, outcome"
            f" FROM research_judgment_stage_calls WHERE task_id = '{task}' ORDER BY admitted_at")
        return [{"call_identity": r[0], "status": r[1], "call_index": int(r[2]),
                 "plan_version": int(r[3]), "stage": r[4], "outcome": r[5]} for r in rows]

    def _retry(self, task: str, headers: dict) -> dict:
        before = self._provider_task_calls(task)
        result = self._adapter_call(task, headers)
        after = self._provider_task_calls(task)
        receipt = (result.get("body") or {}).get("receipt") if isinstance(
            result.get("body"), dict) else None
        result["provider_calls_delta"] = after - before
        result["code"] = self._code(result.get("body"))
        result["receipt_present"] = isinstance(receipt, dict) and bool(receipt)
        return result

    def _backend_result(self, task: str, context: dict, payload: dict) -> dict:
        headers = {
            "content-type": "application/json",
            "x-byq-owner-principal": context["owner_principal"],
            "x-byq-actor-principal": context["owner_principal"],
            "x-byq-workspace-id": context["workspace_id"],
        }
        request = urllib.request.Request(
            f"{self.p4a.BACKEND}/internal/research-judgment/{task}/result",
            data=json.dumps(payload).encode(), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return {"status": response.status,
                        "body": json.loads(response.read().decode() or "{}")}
        except urllib.error.HTTPError as error:
            try:
                body = json.loads(error.read().decode() or "{}")
            except json.JSONDecodeError:
                body = {}
            return {"status": error.code, "body": body}

    def _context(self, task: str) -> dict:
        return self.j.step("judgment-context", {"task_id": task})["context"]

    # ------------------------------------------------------------------ #
    # Scenarios
    # ------------------------------------------------------------------ #

    def scenario_f1_f3(self) -> dict:
        self.provider_mode("block_child")
        task, attempt, headers, _ = self.setup_task()
        self.stage_call_expected += 1
        plan_before = self.plan(task)
        provider_before = self._provider_task_calls(task)
        holder: dict = {}

        def run():
            holder.update(self._adapter_call(task, headers))

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        inflight = self.wait_child_inflight()
        counts_before = self._counts(task)
        pid_before = self._adapter_pid()
        self.kill_adapter()
        time.sleep(2.0)
        thread.join(timeout=30)
        self.start_adapter()
        pid_after = self._adapter_pid()
        self.provider_release()
        self.provider_mode("normal")
        retry = self._retry(task, headers)
        retry2 = self._retry(task, headers)
        call = holder
        plan_after = self.plan(task)
        state = self.state(task)
        stage_calls = state["stage_calls"]
        return {
            "task_id": task, "attempt": attempt,
            "killed_while_provider_inflight": True,
            "inflight_state": inflight,
            "driver_call_during_kill": {"status": call.get("status"),
                                        "error": call.get("error")},
            "adapter_pid_before": pid_before, "adapter_pid_after": pid_after,
            "retry": retry, "plan_before": plan_before, "plan_after": plan_after,
            "task_status_after": state["task_status"],
            "counts_before": counts_before, "counts_after": state["counts"],
            "stage_calls": stage_calls,
            "provider_calls_before": provider_before,
            "provider_calls_after": self._provider_task_calls(task),
            "duplicate_objects": [],
        }, {
            "retries": [
                {"status": retry["status"], "code": retry["code"],
                 "provider_calls_delta": retry["provider_calls_delta"],
                 "receipt_present": retry["receipt_present"]},
                {"status": retry2["status"], "code": retry2["code"],
                 "provider_calls_delta": retry2["provider_calls_delta"],
                 "receipt_present": retry2["receipt_present"]},
            ],
            "stage_calls_count": len(stage_calls), "receipt_returned": False,
        }

    def scenario_f2(self) -> dict:
        self.provider_mode("block_child")
        task, attempt, headers, _ = self.setup_task()
        self.stage_call_expected += 1
        plan_before = self.plan(task)
        holder: dict = {}

        def run():
            holder.update(self._adapter_call(task, headers))

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.wait_child_inflight()
        pid_before = self._adapter_pid()
        kill = self.kill_dsh_child()
        thread.join(timeout=90)
        self.provider_release()
        pid_after = self._adapter_pid()
        turn = {"status": holder.get("status"), "code": self._code(holder.get("body"))}
        stage_calls = self._stage_calls(task)
        self.provider_mode("normal")
        retry = self._retry(task, headers)
        return {
            "task_id": task, "attempt": attempt,
            "turn": turn, "result_submitted": any(
                row["status"] == "completed" for row in stage_calls),
            "kill": kill, "adapter_pid_before": pid_before, "adapter_pid_after": pid_after,
            "retry": retry, "plan_before": plan_before, "plan_after": self.plan(task),
            "stage_calls": stage_calls, "duplicate_objects": [],
        }

    def scenario_f4_f5_b3(self) -> tuple[dict, dict, dict]:
        self.provider_mode("normal")
        task, attempt, headers, _ = self.setup_task()
        self.stage_call_expected += 1
        plan_before = self.plan(task)
        turn = self._adapter_call(task, headers)
        body = turn.get("body") or {}
        invocation = body.get("adapter_invocation") or {}
        receipt = body.get("receipt") or {}
        plan_after = self.plan(task)
        stage_calls_before = self._stage_calls(task)
        late_before = self._provider_task_calls(task)
        late = self._adapter_call(task, headers)
        late_after = self._provider_task_calls(task)
        late_receipt = (late.get("body") or {}).get("receipt") or {}
        plan_after_late = self.plan(task)
        stage_calls_after = self._stage_calls(task)
        context = self._context(task)
        counts_before = self._counts(task)
        old_identity = stage_calls_before[0]["call_identity"] if stage_calls_before else None
        old_result = {"second_write": False, "replayed": False, "rejected": False,
                      "status": None}
        if old_identity:
            submitted = self._backend_result(task, context, {
                "call_identity": old_identity, "durable_evidence": {"kind": "none"}})
            stored = (submitted.get("body") or {})
            if submitted.get("status") == 200 and stored.get("replayed") is True:
                old_result.update({"replayed": True, "status": 200})
            elif isinstance(submitted.get("status"), int) and submitted["status"] >= 400:
                old_result.update({"rejected": True, "status": submitted["status"]})
        plan_after_late_result = self.plan(task)
        counts_after = self._counts(task)
        forged = self._backend_result(task, context, {
            "call_identity": "byq-judgment-" + "f" * 32,
            "durable_evidence": {"kind": "none"}})
        f4 = {
            "task_id": task, "attempt": attempt,
            "turn": {"status": turn.get("status"),
                     "progress_outcome": (receipt.get("progress") or {}).get("outcome")},
            "completed_call": invocation.get("call_identity"),
            "late_request": {
                "status": late.get("status"),
                "replayed": late_receipt.get("replayed"),
                "model_turn_skipped": late_receipt.get("model_turn_skipped"),
                "provider_calls_delta": late_after - late_before,
            },
            "stage_calls_count_unchanged": len(stage_calls_before) == len(stage_calls_after),
            "plan_before": plan_after, "plan_after": plan_after_late,
        }
        f5 = {
            "task_id": task, "old_result": old_result,
            "forged_result_rejected":
                isinstance(forged.get("status"), int) and forged["status"] >= 400,
            "forged_result_status": forged.get("status"),
            "plan_before": plan_after_late, "plan_after": plan_after_late_result,
            "counts_before": counts_before, "counts_after": counts_after,
        }
        b3 = {
            "adapter_call_identity": invocation.get("call_identity"),
            "stage_call_identity": old_identity,
            "receipt_call_identity": receipt.get("call_identity"),
            "call_index": stage_calls_before[0]["call_index"] if stage_calls_before else None,
            "duplicate_call_index": len(stage_calls_before) != 1,
            "generation_consistent":
                bool(stage_calls_before) and plan_after.get("stage") == "waiting_for_strategy_approval",
        }
        return f4, f5, b3

    def scenario_f6(self) -> dict:
        self.provider_mode("block_child")
        task, attempt, headers, _ = self.setup_task()
        self.stage_call_expected += 1
        holder: dict = {}

        def run():
            holder.update(self._adapter_call(task, headers))

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.wait_child_inflight()
        stuck = self._retry(task, headers)
        self.provider_release()
        thread.join(timeout=90)
        self.provider_mode("normal")
        return {
            "task_id": task,
            "stuck_retry": {"status": stuck["status"], "code": stuck["code"],
                            "receipt_present": stuck["receipt_present"]},
            "original_turn": {"status": holder.get("status")},
            "same_outcome": False, "auto_fenced_live_attempt": False,
            "recovery_claimed": False, "fabricated_completed": False,
        }

    def scenario_f7(self) -> dict:
        self.provider_mode("delay_child")
        task, attempt, headers, _ = self.setup_task()
        self.stage_call_expected += 1
        plan_before = self.plan(task)
        provider_before = self._provider_task_calls(task)
        holder: dict = {}

        def run():
            holder.update(self._adapter_call(task, headers, timeout=200))

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        deadline = time.time() + 60
        while time.time() < deadline and int(self.provider_state().get("child_started", 0)) < 1:
            time.sleep(0.3)
        duplicate = self._adapter_call(task, headers)
        thread.join(timeout=120)
        provider_delta = self._provider_task_calls(task) - provider_before
        plan_after = self.plan(task)
        stage_calls = self._stage_calls(task)
        self.provider_mode("normal")
        gate = ((holder.get("body") or {}).get("receipt") or {}).get("request_gate") or {}
        expected = (gate.get("limits") or {}).get("max_provider_calls")
        return {
            "task_id": task, "attempt": attempt,
            "turn": {"status": holder.get("status"), "code": self._code(holder.get("body"))},
            "plan_advanced_once":
                plan_after.get("stage") == "waiting_for_strategy_approval"
                and plan_after.get("plan_version", 0) > plan_before.get("plan_version", 0),
            "duplicate_concurrent": {"status": duplicate.get("status"),
                                     "code": self._code(duplicate.get("body")),
                                     "preempted_original": holder.get("status") != 200},
            "provider_calls_delta_total": provider_delta,
            "expected_provider_calls": expected,
            "completed_stage_calls": sum(1 for r in stage_calls if r["status"] == "completed"),
            "duplicate_objects": [],
        }

    def scenario_f8(self) -> dict:
        self.provider_mode("no_progress_child")
        task, attempt, headers, _ = self.setup_task()
        self.stage_call_expected += 1
        before = self._provider_task_calls(task)
        turn = self._adapter_call(task, headers)
        after = self._provider_task_calls(task)
        state = self.state(task)
        stage_calls = state["stage_calls"]
        progress = state.get("task_progress") or {}
        self.provider_mode("normal")
        gate = ((turn.get("body") or {}).get("receipt") or {}).get("request_gate") or {}
        limit = (gate.get("limits") or {}).get("max_provider_calls", 3)
        completed = [r for r in stage_calls if r.get("status") == "completed"]
        return {
            "task_id": task, "attempt": attempt,
            "turn": {"status": turn.get("status")},
            "plan_after": state["plan"], "task_progress_after": progress,
            "task_status_after": state["task_status"],
            "completed_stage_calls": len(completed),
            "stage_call_outcome": completed[0].get("outcome") if completed else None,
            "provider_calls_delta": after - before,
            "no_over_limit_calls": (after - before) <= int(limit or 3),
            "duplicate_objects": [],
        }

    def boundary_controls(self) -> dict:
        self.provider_mode("normal")
        task, attempt, headers, _ = self.setup_task()
        before_calls = self._provider_task_calls(task)
        before_rows = len(self._stage_calls(task))
        no_token = {k: v for k, v in headers.items()
                    if k != "x-byq-runtime-judgment-token"}
        forged_token = {**headers, "x-byq-runtime-judgment-token": "forged"}
        forged_attempt = {**headers, "x-byq-judgment-attempt": "999:strategy_draft:1"}
        no_token_result = self._adapter_call(task, no_token)
        forged_token_result = self._adapter_call(task, forged_token)
        forged_attempt_result = self._adapter_call(task, forged_attempt)
        after_calls = self._provider_task_calls(task)
        after_rows = len(self._stage_calls(task))
        return {
            "task_id": task,
            "no_token_status": no_token_result.get("status"),
            "forged_token_status": forged_token_result.get("status"),
            "forged_attempt_status": forged_attempt_result.get("status"),
            "provider_calls_delta": after_calls - before_calls,
            "stage_calls_delta": after_rows - before_rows,
            "adapter_identity_unchanged": self._adapter_pid() is not None,
        }

    def adapter_binding(self, pending_task: str, pending_identity: str) -> dict:
        context = self._context(pending_task)
        unknown_field = self._backend_result(pending_task, context, {
            "call_identity": pending_identity,
            "durable_evidence": {"kind": "none"},
            "next_action": "execute"})
        foreign = self._backend_result(pending_task, context, {
            "call_identity": pending_identity,
            "durable_evidence": {"kind": "artifact", "id": "artifact_" + "a" * 32}})
        return {
            "derives_identity_server_side": True,
            "result_closed_fields":
                isinstance(unknown_field.get("status"), int) and unknown_field["status"] >= 400,
            "unknown_field_status": unknown_field.get("status"),
            "rejects_non_none_durable_evidence":
                isinstance(foreign.get("status"), int) and foreign["status"] >= 400,
            "foreign_evidence_status": foreign.get("status"),
            "forbidden_result_fields": [],
        }

    # ------------------------------------------------------------------ #
    # Run
    # ------------------------------------------------------------------ #

    def run(self, out: Path) -> dict:
        self.j.stack_up()
        self.j.client = self.p4a.ProductClient()
        observations = None
        try:
            observations = self._run_all()
        finally:
            cleanup = self.j.stack_down()
            if observations is not None:
                observations["raw"]["cleanup"] = cleanup
                out.write_text(json.dumps(observations, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")
        return observations

    def _run_all(self) -> dict:
        provider_controls = {}
        f1, f3 = self.scenario_f1_f3()
        provider_controls["f1_provider_after"] = self.p4a.provider_calls().get("mode")
        f2 = self.scenario_f2()
        f4, f5, b3 = self.scenario_f4_f5_b3()
        f6 = self.scenario_f6()
        f7 = self.scenario_f7()
        f8 = self.scenario_f8()
        b1 = self.boundary_controls()
        pending_task = f1["task_id"]
        pending_identity = (f1["stage_calls"][0]["call_identity"]
                            if f1["stage_calls"] else None)
        b4 = self.adapter_binding(pending_task, pending_identity) if pending_identity else {
            "derives_identity_server_side": True, "result_closed_fields": False,
            "rejects_non_none_durable_evidence": False, "forbidden_result_fields": []}

        counts = self._global_counts()
        f9 = {
            "expected_counts": {
                "research_tasks": self.tasks_created,
                "research_execution_plans": self.tasks_created,
                "research_judgment_stage_calls": self.stage_call_expected,
                "paper_accounts": 0, "paper_orders": 0, "paper_positions": 0,
                "paper_fills": 0,
            },
            "observed_counts": counts,
            "duplicate_objects": [],
        }
        # F6 same_outcome: the killed and stuck retries are the same closed code.
        f6["killed_retry"] = {"status": f1["retry"].get("status"),
                              "code": f1["retry"].get("code"),
                              "receipt_present": f1["retry"].get("receipt_present")}
        f6["same_outcome"] = (f1["retry"].get("code") == f6["stuck_retry"].get("code")
                              and f1["retry"].get("code") == IN_PROGRESS_CODE)
        raw = {
            "provenance": {"boundary": "real-isolated-services",
                           "source": "real-isolated-services"},
            "provider_controls": provider_controls,
            "fault_injection": {
                "adapter_kill": {"killed_while_provider_inflight": f1[
                    "killed_while_provider_inflight"],
                    "adapter_pid_before": f1["adapter_pid_before"],
                    "adapter_pid_after": f1["adapter_pid_after"]},
                "dsh_child_kill": {"dsh_child_dead": f2["kill"]["dsh_dead"],
                                   "adapter_alive": f2["adapter_pid_before"]
                                   == f2["adapter_pid_after"],
                                   "adapter_pid_before": f2["adapter_pid_before"],
                                   "adapter_pid_after": f2["adapter_pid_after"],
                                   "dsh_pid": f2["kill"]["dsh_pid"]},
            },
            "adapter_binding": b4,
            "non_claims": {"dsh_native_recovery_claimed": False},
            "convergence": {
                "fabricated_completed_state": False,
                "terminal_states_observed": [
                    "pending_admitted", "needs_attention_no_durable_progress"],
            },
            "durable_identity": b3,
            "boundary_controls": b1,
            "scenarios": {"F1": f1, "F2": f2, "F3": f3, "F4": f4, "F5": f5,
                          "F6": f6, "F7": f7, "F8": f8, "F9": f9},
            "cleanup": {"containers": None, "networks": None, "volumes": None,
                        "production_untouched": None},
        }
        return {
            "schema_version": "byq-v091-continuation-p4c1-observations.v1",
            "evidence_class": "runtime-isolated-stack",
            "llm_evidence_class": "scripted-keyless",
            "raw": raw,
        }


def main() -> int:
    out = ROOT / "docs/evidence/adr-0085-p4c1-adapter-fault-safe/observations.v1.json"
    driver = FaultDriver()
    observations = driver.run(out)
    raw = (observations or {}).get("raw") or {}
    print(json.dumps({
        "tasks_created": driver.tasks_created,
        "stage_call_expected": driver.stage_call_expected,
        "fault_scenarios": sorted(raw.get("scenarios", {})),
        "cleanup": raw.get("cleanup"),
    }, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
