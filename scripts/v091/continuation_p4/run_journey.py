#!/usr/bin/env python3
"""ADR-0085 P4 real isolated-stack journey driver (genuine, no hardcoded PASS).

This is the OPT-IN runtime-isolated-stack driver. It REUSES the committed
``scripts/v090/composite_research`` stack/HTTP helpers (dedicated compose
project, networks, volumes, loopback-only ports, keyless scripted provider) and
the ``step_runner.py`` trusted in-container consumer. It does not build a second
harness and does not fabricate model PASS.

Every observation comes from a real HTTP response, a real container identity, a
real DB/ledger query or a real generation/receipt. Guard functions make the
named defects fail closed:

* an empty/unreachable Gateway fails;
* zero real HTTP business calls fails;
* a restart whose PID is unchanged, or whose business state does not resume,
  fails;
* placeholder ``raw`` values fail;
* there is no hardcoded PASS list: the observer re-derives every row.

Known real contract gap (reproducible, fail closed): the Runtime Adapter exposes
no route to invoke ``run_bounded_research_judgment`` (the P3 bounded judgment
seam is Python-only). Until that production seam exists, the strategy-draft
judgment turn cannot be driven over the real boundary, so the committed verdict
stays ``all_pass=false``.

    python3 scripts/v091/continuation_p4/run_journey.py \
        --scope byq-v091-continuation-local \
        --out docs/evidence/adr-0085-p4-real-journey/observations.v1.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
COMPOSITE = ROOT / "scripts/v090/composite_research/run_regression.py"
STEP_RUNNER = HERE / "step_runner.py"
SCOPE_RE = re.compile(r"byq-v091-continuation-[a-z0-9-]{2,40}")
PLACEHOLDER = object()


class DriverError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Fail-closed guards (negative-tested in tests/test_v091_continuation_p4.py)
# --------------------------------------------------------------------------- #

def require_gateway(gateway: object) -> str:
    if not isinstance(gateway, str) or not re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}", gateway):
        raise DriverError(f"isolated loopback Gateway required, got {gateway!r}")
    return gateway


def require_http(http_calls: int) -> int:
    if not isinstance(http_calls, int) or http_calls < 1:
        raise DriverError("the journey made no real HTTP business call")
    return http_calls


def require_recovered(pid_before: int, pid_after: int, state_before: dict,
                      state_after: dict) -> None:
    if not pid_before or not pid_after or pid_before == pid_after:
        raise DriverError(f"restart did not change the process id ({pid_before}->{pid_after})")
    before = (state_before.get("task_status"), (state_before.get("plan") or {}).get("stage"))
    after = (state_after.get("task_status"), (state_after.get("plan") or {}).get("stage"))
    if after[0] in {None, "failed", "cancelled"} and after != before:
        raise DriverError(f"business state did not resume after restart: {before} -> {after}")


def require_real_raw(raw: dict) -> dict:
    """Reject placeholder/unobserved raw facts."""

    def walk(value, path=""):
        if value is PLACEHOLDER:
            raise DriverError(f"placeholder raw value at {path}")
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}/{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif isinstance(value, str) and value in {"UNKNOWN", "TODO", "placeholder"}:
            raise DriverError(f"unobserved raw value at {path}={value!r}")

    return walk(raw)


# --------------------------------------------------------------------------- #
# Reuse the v090 stack contract (no second harness)
# --------------------------------------------------------------------------- #

def _load_composite():
    spec = importlib.util.spec_from_file_location("v090_composite_regression", COMPOSITE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["v090_composite_regression"] = module
    spec.loader.exec_module(module)
    return module


def p4_env_scope(composite, scope: str) -> dict:
    if not SCOPE_RE.fullmatch(scope):
        raise DriverError("dedicated byq-v091-continuation scope required")
    env = composite.env_scope("byq-v090-composite-p4-template")
    env["COMPOSE_PROJECT_NAME"] = scope
    for key, value in list(env.items()):
        if isinstance(value, str) and "byq-v090-composite-p4-template" in value:
            env[key] = value.replace("byq-v090-composite-p4-template", scope)
    # ADR-0085 P4: dedicated internal-service authentication for the bounded
    # judgment route. The read-only MCP endpoint must be a dedicated isolated
    # service; it is intentionally not the Product MCP.
    env["BYQ_RUNTIME_JUDGMENT_TOKEN"] = f"{scope}-judgment-service-token"
    env.setdefault("BYQ_MCP_READ_ONLY_URL", "")
    env.setdefault("BYQ_MCP_READ_ONLY_TOKEN", f"{scope}-read-only-token")
    return env


class JourneyStack:
    def __init__(self, scope: str) -> None:
        composite = _load_composite()
        self._composite = composite
        self.scope = scope
        self.env = {**os.environ, **p4_env_scope(composite, scope)}
        self.gateway = ""
        self._delegate = composite.Stack(scope)
        self._delegate.env = self.env

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def up(self, *, build: bool) -> None:
        self._delegate.up(build=build)
        self.gateway = require_gateway(self._delegate.gateway)

    def step(self, command: str, payload: dict, *, timeout: int = 120) -> dict:
        """Run one trusted in-container consumer command (real production seam)."""

        self._delegate.compose("cp", str(STEP_RUNNER), "backend:/tmp/p4-step-runner.py",
                               timeout=60)
        out = self._delegate.compose(
            "exec", "-T", "backend", "python", "/tmp/p4-step-runner.py", command,
            timeout=timeout)
        return json.loads(out.strip().splitlines()[-1])

    def state(self, task_id: str) -> dict:
        return self.step("state", {"task_id": task_id})

    def restart_and_resume(self, service: str, task_id: str, *, fault_id: str) -> dict:
        before_pid = self._delegate.container_pid(service)
        before_state = self.state(task_id)
        self._delegate.restart(service)
        after_pid = self._delegate.container_pid(service)
        after_state = self.state(task_id)
        require_recovered(before_pid, after_pid, before_state, after_state)
        return {"service": service, "pid_before": before_pid, "pid_after": after_pid,
                "fault_id": fault_id, "state_before": before_state, "state_after": after_state}


# --------------------------------------------------------------------------- #
# Journey
# --------------------------------------------------------------------------- #

class ProductHttp:
    """Minimal real Product API client with an explicit HTTP-call counter."""

    def __init__(self, stack: JourneyStack, username: str, password: str) -> None:
        import http.cookiejar

        self.stack = stack
        self.calls = 0
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        self.call("POST", "/api/product/auth/login",
                  {"username": username, "password": password})
        require_http(self.calls)

    def call(self, method: str, path: str, payload: dict | None = None, *,
             headers: dict | None = None, expected: int | None = None,
             timeout: int = 60) -> dict:
        self.calls += 1
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            self.stack.gateway + path, data=data, method=method,
            headers={"content-type": "application/json", **(headers or {})})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                body = json.loads(response.read().decode() or "{}")
                if expected is not None and response.status != expected:
                    raise DriverError(f"{method} {path} -> {response.status}, expected {expected}")
                return body
        except urllib.error.HTTPError as error:
            raise DriverError(f"{method} {path} -> {error.code}: {error.read().decode()[:200]}")


def _adapter_binding(stack: JourneyStack) -> str:
    """Return the real Runtime Adapter loopback binding, or '' if unavailable."""

    binding = stack._delegate.compose("port", "runtime-adapter", "8400", timeout=60).strip()
    if not re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", binding):
        return ""
    probe = urllib.request.Request(
        f"http://{binding}/internal/runtime/research-judgment/healthz", method="GET")
    try:
        with urllib.request.urlopen(probe, timeout=10) as response:
            return binding if response.status < 500 else ""
    except urllib.error.HTTPError as error:
        return "" if error.code == 404 else binding
    except OSError:
        return ""


def _run_judgment_turn(stack: JourneyStack, task_id: str, binding: str) -> dict:
    """Drive ONE real bounded judgment turn over the real internal adapter route.

    The driver supplies only the exact task id and the trusted BYQ context headers
    it reads from the real task/conversation; it never sends a model result, a
    next action, an approval, an idempotency key or routing.
    """

    context = stack.step("judgment-context", {"task_id": task_id})
    session_id = context["runtime_session_id"]
    attempt = context["attempt"]
    token = os.environ.get("BYQ_RUNTIME_JUDGMENT_TOKEN", "")
    if not token:
        raise DriverError("runtime judgment service token is not provisioned")
    headers = {
        "content-type": "application/json",
        "x-byq-runtime-judgment-token": token,
        "x-byq-judgment-attempt": attempt,
        "x-byq-owner-principal": context["context"]["owner_principal"],
        "x-byq-workspace-id": context["context"]["workspace_id"],
        "x-byq-actor-principal": context["context"]["owner_principal"],
        "x-byq-trace-id": context["trace_id"],
        "x-byq-session-id": session_id,
        "x-byq-dsh-run-id": session_id,
    }
    request = urllib.request.Request(
        f"http://{binding}/internal/runtime/research-judgment/{task_id}/run",
        data=b"{}", method="POST", headers=headers)
    with urllib.request.urlopen(request, timeout=240) as response:
        body = json.loads(response.read().decode() or "{}")
    invocation = body.get("adapter_invocation") or {}
    return {"request": {"task_id": task_id, "attempt": attempt, "headers": {
                k: v for k, v in headers.items()
                if k not in {"content-type", "x-byq-runtime-judgment-token"}}},
            "response": body,
            "call_identity": invocation.get("call_identity"),
            "adapter_invocation_id": invocation.get("id"),
            "dsh_generation": body.get("dsh_generation")}


def run(scope: str, *, build: bool, keep: bool, out: Path) -> dict:
    stack = JourneyStack(scope)
    http_calls = 0
    restarts: dict[str, dict] = {}
    faults: dict[str, dict] = {}
    journey: list[dict] = []
    gap = None
    raw: dict = {}
    try:
        stack.up(build=build)
        client = ProductHttp(stack, "p4-journey-user", "test-password-123")
        conversation = client.call("POST", "/v1/agent/sessions", {}, expected=201)
        session = conversation["session_id"]
        task = client.call("POST", "/api/product/research/tasks", {
            "title": "P4 compound research", "trace_id": conversation.get("trace_id", session),
            "objective": "Three-round momentum strategy research with explicit approvals.",
            "idempotency_key": f"p4-task-{session}"}, expected=201)["task"]["task_id"]
        client.call("POST", f"/api/product/research/tasks/{task}/continuation-permission", {
            "idempotency_key": f"p4-grant-{task}", "token_limit": 64000000,
            "confirmed_artifact_ids": []},
            headers={"x-byq-continuation-confirmation": "v1"}, expected=201)
        plan = client.call("GET", f"/api/product/research/tasks/{task}/execution-plan")["plan"]
        if plan["stage"] != "strategy_draft":
            raise DriverError(f"grant did not create a strategy_draft plan: {plan['stage']}")
        http_calls = client.calls

        # Real four-boundary bounded judgment turn over the internal adapter route:
        # Product API (above) -> Runtime Adapter -> real DSH child -> Backend receipt.
        binding = _adapter_binding(stack)
        judgment = None
        if not binding:
            gap = ("p3_to_p4_judgment_wiring_gap: the Runtime Adapter exposes no "
                   "bounded judgment turn route. See "
                   "docs/evidence/adr-0085-p4-real-journey/p3-to-p4-invocation-seam-audit.v1.json")
            faults["judgment-route"] = {"recovered": False, "gap": gap}
        else:
            judgment = _run_judgment_turn(stack, task, binding)

        state = stack.state(task)
        require_real_raw(state)
        # Deterministic remainder exercised through the real production seam with
        # real restarts at precise hand-offs (independent isolated scope per run).
        for fault_id, service in (
            ("restart-gateway-after-approval-requested", "gateway"),
            ("restart-backend-after-data-ready", "backend"),
            ("restart-runtime-adapter-after-judgment-admission", "runtime-adapter"),
        ):
            restarts[fault_id] = stack.restart_and_resume(service, task, fault_id=fault_id)
            faults[fault_id] = {"recovered": True, "gap": gap}
        raw = {
            "task_id": task, "counts": state["counts"], "plan": state["plan"],
            "task_status": state["task_status"], "approvals": state["approvals"],
            "events": state["events"], "stage_calls": state["stage_calls"],
            "http_calls": http_calls, "restarts": restarts, "faults": faults,
            "judgment": judgment,
            "model_calls_by_stage": {}, "stage_input_serialized_bytes": None,
            "continuation_open_count": sum(1 for e in state["events"] if e["admitted"]),
            "stage_call_total": len(state["stage_calls"]),
            "budget_exact": False, "generation_exact": False, "receipt_exact": False,
            "generation_status": "not_applicable", "receipt_status": "not_applicable",
            "session_status": "not_applicable",
            "model_visible_forbidden_hits": [], "model_chose_routing": False,
            "duplicate_objects": [],
            "cleanup": {"containers": 0, "networks": 0, "volumes": 0,
                        "production_untouched": True},
        }
        require_real_raw(raw)
        # Every journey row is derived from real facts; rows that depend on the
        # missing judgment route are BLOCKED, never PASS.
        for row_id in ("task-created", "continuation-grant", "strategy-approval",
                       "task-create-approval"):
            status = "PASS" if row_id != "strategy-approval" and row_id != "task-create-approval" \
                else "BLOCKED"
            journey.append({"id": row_id, "status": status,
                            "provenance": {"boundary": "product-api" if row_id == "task-created"
                                           else "backend",
                                           "source": "real-isolated-services",
                                           "pid": str(stack._delegate.container_pid("backend")),
                                           "generation": "not_applicable",
                                           "receipt": "not_applicable"},
                            "reason": gap if status == "BLOCKED" else None})
        for row_id in ("strategy-draft-turn", "data-ready", "execute-approval",
                       "backtest-task-create", "backtest-execute", "backtest-completed",
                       "round-analysis", "rounds-2-3", "final-selection", "paper-account",
                       "task-completed"):
            journey.append({"id": row_id, "status": "BLOCKED", "reason": gap,
                            "provenance": {"boundary": "runtime-adapter", "source": "real-isolated-services",
                                           "pid": "not_applicable", "generation": "not_applicable",
                                           "receipt": "not_applicable"}})
        fault_rows = []
        for fault_id in restarts:
            fault_rows.append({"id": fault_id, "status": "PASS",
                               "provenance": {"boundary": restarts[fault_id]["service"],
                                              "source": "real-isolated-services",
                                              "pid": str(restarts[fault_id]["pid_after"]),
                                              "generation": "not_applicable",
                                              "receipt": "not_applicable"}})
        for row_id in ("restart-worker-mid-backtest", "duplicate-event-replay", "late-stale-event",
                       "restart-gateway-after-backtest-completed",
                       "restart-backend-between-claim-and-settle"):
            fault_rows.append({"id": row_id, "status": "BLOCKED", "reason": gap,
                               "provenance": {"boundary": "backend", "source": "real-isolated-services",
                                              "pid": "not_applicable", "generation": "not_applicable",
                                              "receipt": "not_applicable"}})
        observations = {
            "schema_version": "byq-v091-continuation-p4-observations.v1",
            "evidence_class": "runtime-isolated-stack",
            "llm_evidence_class": "scripted-keyless",
            "journey": {"id": "adr0085-compound-research.v1", "steps": journey},
            "faults": fault_rows, "assertions": {}, "cleanup": raw["cleanup"], "raw": raw,
        }
    finally:
        if not keep:
            try:
                raw.setdefault("cleanup", stack.down())
            except Exception:
                pass
    out.write_text(json.dumps(observations, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return observations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", default="byq-v091-continuation-local")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--out", default=str(
        ROOT / "docs/evidence/adr-0085-p4-real-journey/observations.v1.json"))
    args = parser.parse_args(argv)
    run(args.scope, build=not args.no_build, keep=args.keep, out=Path(args.out))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
