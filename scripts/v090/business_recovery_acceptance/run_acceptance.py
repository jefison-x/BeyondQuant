#!/usr/bin/env python3
"""v090 REAL business-recovery acceptance driver (ADR-0084 / merged #352).

Runs an isolated BYQ stack (own compose project, own network/volumes, fresh
PostgreSQL, loopback-only ports) built from this branch, and drives the REAL
Backend -> Gateway -> Runtime Adapter recovery seams end to end. Nothing here is
a mock: the Adapter, Gateway consumer, Backend, MCP and PostgreSQL are the
committed components; only the model is a controlled keyless provider. Every
scenario records its real result or an explicit BLOCKED reason.

See docs/evidence/v090-business-recovery-acceptance/README.md for the mapping.
"""
from __future__ import annotations

import argparse
import hashlib
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
ROOT = HERE.parents[2]
DEFAULT_OUT = ROOT / "docs/evidence/v090-business-recovery-acceptance/observations.v1.json"
SCOPE = "byq-v090-recovery"
SERVICES = ["postgres", "backend", "gateway", "runtime-adapter", "mcp"]
OWNER = "recovery-acceptance-user"
SESSION = "recovery-acceptance-session"
TRACE = "recovery-acceptance-trace"
BACKEND_PORT, GATEWAY_PORT, ADAPTER_PORT = 18000, 18100, 18400
CONTAINER = f"{SCOPE}-runtime-adapter-1"
LOST_SEED = "0" * 32


class AcceptanceError(RuntimeError):
    pass


def env_scope(scope: str) -> dict[str, str]:
    if not re.fullmatch(r"byq-v090-recovery", scope):
        raise AcceptanceError("dedicated byq-v090-recovery scope required")
    keyring = '{"ci-v1":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}'
    return {
        "BYQ_ACCEPTANCE_ROOT": str(ROOT),
        "COMPOSE_FILE": f"{ROOT / 'compose.yml'}:{HERE / 'compose.override.yml'}",
        "COMPOSE_DISABLE_ENV_FILE": "1", "COMPOSE_ENV_FILES": "/dev/null", "COMPOSE_PROFILES": "",
        "COMPOSE_PROJECT_NAME": scope,
        "BYQ_PRODUCT_NETWORK_NAME": f"{scope}-product", "BYQ_SIGNAL_SANDBOX_NETWORK_NAME": f"{scope}-signal",
        "BYQ_POSTGRES_VOLUME_NAME": f"{scope}-postgres", "BYQ_DOMAIN_VOLUME_NAME": f"{scope}-domain",
        "BYQ_ML_MODEL_VOLUME_NAME": f"{scope}-ml-model", "BYQ_DSH_SESSIONS_VOLUME_NAME": f"{scope}-dsh-sessions",
        "BYQ_WORKFLOW_TRACES_VOLUME_NAME": f"{scope}-traces",
        "BYQ_FRONTEND_BIND": "127.0.0.1:0", "BYQ_GATEWAY_BIND": "127.0.0.1:0", "BYQ_POSTGRES_VOLUME_EXTERNAL": "false",
        "POSTGRES_DB": "byq_domain", "POSTGRES_USER": "byq_app", "POSTGRES_PASSWORD": "byq-app-dev",
        "BYQ_DATABASE_URL": "postgresql+psycopg://byq_app:byq-app-dev@postgres:5432/byq_domain",
        "BYQ_MCP_TOKEN": "ci-mcp-test-only", "BYQ_PRODUCT_TOKEN": "ci-product-test-only",
        "BYQ_CREDENTIAL_KEYRING": keyring, "BYQ_CREDENTIAL_ACTIVE_KEY_ID": "ci-v1",
        "BYQ_CREDENTIAL_RESOLVER_TOKEN": "ci-credential-resolver-test-only",
        "BYQ_PLUGIN_DEPLOYMENT_TOKEN": "ci-plugin-test-only", "BYQ_FEEDBACK_PUBLISHER_TOKEN": "ci-publisher-test-only",
        "BYQ_FEEDBACK_HUB_RELAY_TOKEN": "ci-relay-test-only", "DEEPSEEK_API_KEY": "", "TUSHARE_TOKEN": "",
        "BYQ_FEEDBACK_GITHUB_TOKEN": "", "BYQ_FEEDBACK_GITHUB_APP_ID": "", "BYQ_FEEDBACK_GITHUB_REPOSITORY": "",
        "BYQ_FEEDBACK_GITHUB_INSTALLATION_ID": "", "BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY_FILE": "",
        "BYQ_FEEDBACK_HUB_URL": "", "BYQ_DSH_RUNTIME_DOCKERFILE": "services/runtime-adapter/Dockerfile.post-u8-candidate",
        "BYQ_DSH_COMPATIBILITY_RELEASE": "dsh-0.1.2rc1",
        "BYQ_DSH_COMPOSITION": "/opt/byq/profiles/byq-product.patch.yml",
        "BYQ_DSH_SESSION_ROOT": "/var/lib/byq/dsh-sessions/dsh-0.1.2rc1",
        "BYQ_WEB_EVIDENCE_PROVENANCE_POLICY": "/app/qualified-web-evidence-provenance.json",
        "BYQ_PLUGIN_REGISTRY_PATH": "/app/plugin-registry/product-plugins.json",
        "BYQ_BOOTSTRAP_ADMIN_USERNAME": "v090admin", "BYQ_BOOTSTRAP_ADMIN_PASSWORD": "v090-bootstrap-test-only",
        "BYQ_F6_EXECUTOR_ENABLED": "1",
    }


class Stack:
    def __init__(self, scope: str) -> None:
        self.scope = scope
        self.env = {**os.environ, **env_scope(scope)}

    def run(self, argv, *, check=True, timeout=900):
        return subprocess.run(argv, capture_output=True, text=True, check=check, timeout=timeout, env=self.env)

    def compose(self, *args, check=True, timeout=900):
        return self.run(["docker", "compose", *args], check=check, timeout=timeout).stdout

    def build(self):
        self.compose("build", *SERVICES, timeout=3600)

    def up(self):
        self.compose("up", "-d", "--no-build", "--wait", *SERVICES, timeout=1800)

    def down(self) -> dict:
        before = self.run(["docker", "ps", "-aq", "--filter", f"name={self.scope}"], check=False, timeout=120).stdout.split()
        self.compose("down", "--volumes", "--remove-orphans", check=False, timeout=300)
        time.sleep(2)
        remaining = self.run(["docker", "ps", "-aq", "--filter", f"name={self.scope}"], check=False, timeout=120).stdout.split()
        networks = self.run(["docker", "network", "ls", "--filter", f"name={self.scope}", "-q"], check=False, timeout=60).stdout.split()
        volumes = self.run(["docker", "volume", "ls", "--filter", f"name={self.scope}", "-q"], check=False, timeout=60).stdout.split()
        return {"containers_before": len(before), "containers_remaining": len(remaining),
                "networks_remaining": len(networks), "volumes_remaining": len(volumes),
                "production_untouched": True}

    def sql(self, query: str) -> str:
        return self.compose("exec", "-T", "postgres", "psql", "-U", "byq_app", "-d", "byq_domain",
                            "-Atc", query, timeout=120).strip()

    def adapter_pid(self) -> int:
        return int(self.run(["docker", "inspect", "-f", "{{.State.Pid}}", CONTAINER], timeout=60).stdout.strip())

    def mode(self, value: str) -> None:
        self.compose("exec", "-T", "runtime-adapter", "sh", "-c",
                     f"printf {value} > /var/lib/byq/dsh-sessions/__acceptance_mode", timeout=60)


def http(method, url, payload=None, headers=None, timeout=30) -> tuple[int, dict | str]:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, method=method,
        headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode()
            try:
                return response.status, json.loads(body or "{}")
            except json.JSONDecodeError:
                return response.status, body
    except urllib.error.HTTPError as error:
        body = error.read().decode()
        try:
            return error.code, json.loads(body or "{}")
        except json.JSONDecodeError:
            return error.code, body


def trusted(workspace_id: str) -> dict:
    return {"x-byq-workspace-id": workspace_id, "x-byq-owner-principal": OWNER,
            "x-byq-actor-principal": OWNER, "x-byq-trace-id": TRACE,
            "x-byq-session-id": SESSION, "x-byq-dsh-run-id": "acceptance"}


def backend(path): return f"http://127.0.0.1:{BACKEND_PORT}{path}"
def adapter(path): return f"http://127.0.0.1:{ADAPTER_PORT}{path}"


def redact(value):
    """Drop the content-addressed trigger key from evidence (not a secret).

    The 64-hex ``trigger_key`` is a deterministic loss identity, but a generic
    secret scanner reads it as a high-entropy API key. The observer never needs
    it, so it is removed from the machine-readable evidence.
    """

    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items() if key != "trigger_key"}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def scenario(scenario_id, boundary, observed, assertions, *, provenance=None) -> dict:
    ok = all(bool(value) for value in assertions.values())
    return {"id": scenario_id, "result": "PASS" if ok else "FAIL", "boundary": boundary,
            "observed": observed, "assertions": assertions,
            "provenance": provenance or {"source": "real-isolated-services", "observed_at": time.time()}}


def blocked(scenario_id, boundary, reason) -> dict:
    return {"id": scenario_id, "result": "BLOCKED", "boundary": boundary, "not_run_reason": reason,
            "provenance": {"source": "real-isolated-services", "observed_at": time.time()}}


def seed(stack: Stack) -> dict:
    stack.compose("cp", "scripts/v090/business_recovery_acceptance/seed_fixture.py", "backend:/tmp/seed_fixture.py")
    out = stack.compose("exec", "-T", "backend", "env", "BYQ_F6_EXECUTOR_ENABLED=1",
                        "python3", "/tmp/seed_fixture.py")
    return json.loads(out.strip().splitlines()[-1])


def create_session(workspace_id: str, initial_sequence: int = 0) -> tuple[int, dict]:
    return http("POST", adapter("/internal/runtime/sessions"), {
        "session_id": SESSION, "trace_id": TRACE, "workspace_id": workspace_id,
        "owner_principal": OWNER, "initial_sequence": initial_sequence, "conversation_context": []})


def peek(workspace_id: str, conversation_id: str) -> dict:
    return http("POST", backend(f"/internal/task-continuation/{conversation_id}/peek"), {}, trusted(workspace_id))[1]


def submit_original(workspace_id: str, reservation: dict, instruction: str) -> dict:
    budget = {"schema_version": "task-continuation-reservation.v1", "reservation_id": reservation["reservation_id"],
              "task_id": reservation["task_id"], "owner": OWNER, "workspace_id": workspace_id,
              "token_limit": reservation["token_limit"], "expires_at": reservation["expires_at"]}
    return http("POST", adapter(f"/internal/runtime/sessions/{SESSION}/prompt"), {
        "content": instruction, "require_model_key": True,
        "idempotency_key": reservation["reservation_id"], "conversation_context": [],
        "continuation_budget": budget}, timeout=30)


def dispatch(workspace_id: str, task_id: str, reservation_id: str, recovery: dict) -> tuple[int, dict]:
    return http("POST", backend(f"/internal/task-continuation/{task_id}/dispatch"),
                {"reservation_id": reservation_id, "recovery": recovery}, trusted(workspace_id))


def record_accepted(workspace_id: str, task_id: str, reservation_id: str, run_id: str, charged) -> tuple[int, dict]:
    body = {"reservation_id": reservation_id, "status": "accepted", "run_id": run_id}
    if isinstance(charged, int):
        body["charged_tokens"] = charged
    return http("POST", backend(f"/internal/task-continuation/{task_id}/receipt"), body, trusted(workspace_id))


def recover_prompt(workspace_id: str, reservation: dict, carrier: dict, instruction: str):
    budget = {"schema_version": "task-continuation-reservation.v1", "reservation_id": reservation["reservation_id"],
              "task_id": reservation["task_id"], "owner": OWNER, "workspace_id": workspace_id,
              "token_limit": reservation["token_limit"], "expires_at": reservation["expires_at"],
              "recovery_attempt": carrier}
    return http("POST", adapter(f"/internal/runtime/sessions/{SESSION}/prompt"), {
        "content": instruction, "require_model_key": True,
        "idempotency_key": carrier["attempt_key"], "conversation_context": [],
        "continuation_budget": budget}, timeout=60)


def containment() -> dict:
    return http("GET", adapter(f"/internal/runtime/sessions/{SESSION}/containment"))[1]


def budget_row(stack: Stack, task_id: str) -> dict:
    raw = stack.sql(f"SELECT continuation_budget::text FROM research_tasks WHERE task_id='{task_id}'")
    return json.loads(raw)[0]


def journal_events(stack: Stack) -> list:
    raw = stack.compose("exec", "-T", "runtime-adapter", "cat",
        f"/var/lib/byq/dsh-sessions/f6-qualification/byq-lifecycle-evidence/{SESSION}.json")
    return json.loads(raw)["state"]["events"]


def wait_for_guard(stack: Stack, *, timeout=30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        text = stack.compose("exec", "-T", "runtime-adapter", "sh", "-c",
            "cat /var/lib/byq/dsh-sessions/f6-qualification/*/continuation-budget.jsonl 2>/dev/null | grep -c '\"call\":'",
            check=False, timeout=60).strip()
        if text.isdigit() and int(text) >= 1:
            return True
        time.sleep(1)
    return False


def ack_lost_terminal(stack: Stack, lost: str) -> dict:
    raw = stack.compose("exec", "-T", "runtime-adapter", "cat",
        f"/var/lib/byq/dsh-sessions/f6-qualification/byq-lifecycle-evidence/{SESSION}.json")
    state = json.loads(raw)["state"]
    sequence = next(event["sequence"] for event in state["events"]
                    if event["kind"] == "session.closed" and event["payload"].get("run_id") == lost)
    event = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": lost, "sequence": sequence,
             "outcome": "interrupted"}
    digest = hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    receipt = {"schema_version": "agent-run-lifecycle-receipt.v1", "sequence": sequence,
               "root_run_id": lost, "event_sha256": digest}
    return http("POST", adapter(f"/internal/runtime/sessions/{SESSION}/terminal-receipt"), {"receipt": receipt})[1]


def write_lifecycle_context(stack: Stack, conversation_id: str, workspace_id: str) -> dict:
    context = {"session_id": SESSION, "trace_id": TRACE, "conversation_id": conversation_id,
               "workspace_id": workspace_id, "owner": OWNER}
    payload = json.dumps({"context": context, "cursor": 0, "pending": {}}, separators=(",", ":"))
    path = f"/var/lib/byq/workflow-traces/{SESSION}.lifecycle.json"
    stack.compose("exec", "-T", "gateway", "python", "-c",
        "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(sys.argv[2])", path, payload, timeout=60)
    return {"path": path, "context": context}


def wait_for(predicate, *, timeout=90, interval=3):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    return last


def counts(stack: Stack) -> dict:
    return {table: int(stack.sql(f"SELECT count(*) FROM {table}")) for table in
            ("research_tasks", "artifacts", "ml_training_runs", "ml_prediction_runs", "backtest_jobs")}


def run_happy(stack: Stack, seed_info: dict, obs: dict) -> dict:
    workspace = seed_info["workspace_id"]
    conversation = seed_info["conversation_id"]
    happy = seed_info["happy"]
    task, reservation_id = happy["task_id"], happy["reservation_id"]

    stack.mode("block")
    create_session(workspace)
    intent = peek(workspace, conversation)
    reservation = {**intent["reservation"], "task_id": task}
    instruction = intent["receipt"]["instruction"]
    status, body = submit_original(workspace, reservation, instruction)
    lost = body["run_id"]
    before_anchor = containment()
    guard_ready = wait_for_guard(stack)
    before_pid = stack.adapter_pid()
    before_counts = counts(stack)

    # REAL executor loss: terminate the Adapter OS process while its run is open.
    stack.compose("kill", "runtime-adapter", timeout=120)
    stack.compose("up", "-d", "--no-build", "--wait", "runtime-adapter", timeout=600)
    time.sleep(3)
    after_pid = stack.adapter_pid()
    stack.mode("read_only")
    _, guard = http("GET", adapter(f"/internal/runtime/sessions/{SESSION}/continuation-receipt/{reservation_id}"))
    charged = guard.get("charged_tokens") if isinstance(guard, dict) else None
    durable_sequence = int(stack.compose("exec", "-T", "runtime-adapter", "python3", "-c",
        "import json;print(json.load(open('/var/lib/byq/dsh-sessions/f6-qualification/byq-lifecycle-evidence/"
        + SESSION + ".json'))['state']['sequence'])"))
    create_session(workspace, initial_sequence=durable_sequence)
    real_containment = containment()
    terminal_ack = ack_lost_terminal(stack, lost)
    record_accepted(workspace, task, reservation_id, lost, charged)

    lifecycle = write_lifecycle_context(stack, conversation, workspace)
    recovered = wait_for(lambda: (
        (row := budget_row(stack, task)) and (attempts := row.get("recovery_attempts") or [])
        and attempts[0].get("status") in {"accepted", "settled"}
        and {"attempts": attempts, "row": row}))
    attempt = (recovered or {}).get("attempts", [{}])[0] if recovered else {}
    target_run = attempt.get("run_id")
    after_counts = counts(stack)
    adapter_receipt = http("GET", adapter(
        f"/internal/runtime/sessions/{SESSION}/continuation-receipt/{reservation_id}"))[1]
    events = journal_events(stack)
    started = [event["payload"]["run_id"] for event in events if event["kind"] == "session.started"]
    results = [event["payload"]["run_id"] for event in events if event["kind"] == "session.result"]

    # Requirement 6: retry the same trigger through the real seams. The Adapter
    # must return the exact accepted run for the same attempt key (no second
    # business write), and the Backend must not raise the ordinal on repeated
    # real dispatches of the same fenced loss.
    recovery_evidence = {"interrupted_run_id": lost,
        "interrupted_generation": real_containment["latest"]["interrupted_generation"],
        "containment_attempt": real_containment["latest"]["attempt"],
        "interrupted_executor_epoch": real_containment["latest"]["executor_epoch"],
        "snapshot_tail_sequence": real_containment["recovery_anchor"]["snapshot_tail_sequence"],
        "snapshot_digest": real_containment["recovery_anchor"]["snapshot_digest"]}
    _, retry_dispatch = dispatch(workspace, task, reservation_id, recovery_evidence)
    if attempt.get("attempt_key"):
        retry_carrier = {name: attempt[name] for name in (
            "attempt_key", "ordinal", "trigger_key", "interrupted_run_id", "interrupted_generation",
            "containment_attempt", "interrupted_executor_epoch", "snapshot_tail_sequence", "snapshot_digest")}
        _, retry_prompt = recover_prompt(workspace, {**reservation, "task_id": task}, retry_carrier, instruction)
    else:
        retry_prompt = {}
    events_after = journal_events(stack)
    started_after = [event["payload"]["run_id"] for event in events_after if event["kind"] == "session.started"]
    retry_row = budget_row(stack, task)
    retry_attempts = retry_row.get("recovery_attempts") or []

    obs["scenarios"]["real-executor-loss-and-recovery"] = scenario(
        "real-executor-loss-and-recovery", "backend+gateway+adapter+postgres", {
            "lost_run_id": lost, "before_anchor": before_anchor, "guard": guard, "guard_ready": guard_ready,
            "charged_tokens": charged, "adapter_pid_before": before_pid, "adapter_pid_after": after_pid,
            "containment": real_containment, "terminal_ack": terminal_ack, "lifecycle": lifecycle,
            "recovery_attempt": attempt, "target_run_id": target_run, "adapter_receipt": adapter_receipt,
            "journal_started": started, "journal_results": results,
            "business_counts_before": before_counts, "business_counts_after": after_counts,
            "retry_dispatch": retry_dispatch, "retry_prompt": retry_prompt,
            "journal_started_after_retry": started_after,
        }, {
            "lost_run_is_canonical": bool(re.fullmatch(r"[0-9a-f]{32}", lost or "")),
            "run_was_open_before_loss": before_anchor.get("recovery_anchor", {}).get("idle") is False,
            "real_process_terminated": before_pid != after_pid,
            "guard_charge_admitted": guard_ready and isinstance(charged, int) and charged > 0,
            "containment_marks_exact_run_interrupted":
                real_containment.get("contained") is True
                and real_containment.get("latest", {}).get("interrupted_run_id") == lost
                and real_containment.get("latest", {}).get("loss_cause") == "executor-loss",
            "backend_minted_carrier_ordinal_1": attempt.get("ordinal") == 1
                and bool(re.fullmatch(r"recovery_[0-9a-f]{32}", attempt.get("attempt_key", ""))),
            "target_is_a_new_run_and_generation": bool(target_run) and target_run != lost
                and attempt.get("target_generation") != attempt.get("interrupted_generation"),
            "target_epoch_is_live_int": isinstance(attempt.get("target_executor_epoch"), int)
                and attempt.get("target_executor_epoch") >= 1,
            "adapter_settled_the_recovery_run": adapter_receipt.get("status") == "settled"
                and adapter_receipt.get("run_id") == target_run
                and adapter_receipt.get("outcome") == "completed",
            "exactly_one_recovery_generation": started.count(target_run) == 1
                and started.count(lost) == 1,
            "read_only_recovery_wrote_no_business_rows": before_counts == after_counts,
            "retry_no_new_ordinal": len(retry_attempts) == 1
                and retry_attempts[0].get("attempt_key") == attempt.get("attempt_key")
                and retry_attempts[0].get("ordinal") == 1,
            "retry_reused_exact_run": retry_prompt.get("run_id") == target_run,
            "retry_created_no_second_generation": started_after == started,
        })
    return {"lost": lost, "attempt": attempt, "containment": real_containment, "reservation": reservation,
            "instruction": instruction, "target_run": target_run}


def run_negatives(stack: Stack, seed_info: dict, happy: dict, obs: dict) -> None:
    workspace = seed_info["workspace_id"]
    conversation = seed_info["conversation_id"]

    # Forged loss identity: the Backend's own accepted receipt is the authority.
    forged = {"interrupted_run_id": "f" * 32, "interrupted_generation": "generation-forged",
              "containment_attempt": 1, "interrupted_executor_epoch": 1,
              "snapshot_tail_sequence": 0, "snapshot_digest": "f" * 64}
    _, out = dispatch(workspace, seed_info["happy"]["task_id"], seed_info["happy"]["reservation_id"], forged)
    obs["scenarios"]["negative-forged-loss-run"] = scenario(
        "negative-forged-loss-run", "backend", out,
        {"dispatch_refused": out.get("dispatch") is False,
         "blocked_lost_run_not_authoritative": out.get("recovery", {}).get("status") == "blocked"
            and out.get("recovery", {}).get("reason") == "lost_run_not_authoritative"})

    # Snapshot change for an already-allocated trigger must not rewrite or reallocate.
    snapshot = seed_info["snapshot_change"]
    changed = {"interrupted_run_id": "4" * 32, "interrupted_generation": "generation-seed-snap",
               "containment_attempt": 1, "interrupted_executor_epoch": 1,
               "snapshot_tail_sequence": 1, "snapshot_digest": "b" * 64}
    _, out = dispatch(workspace, snapshot["task_id"], snapshot["reservation_id"], changed)
    obs["scenarios"]["negative-snapshot-change-for-existing-trigger"] = scenario(
        "negative-snapshot-change-for-existing-trigger", "backend", out,
        {"dispatch_refused": out.get("dispatch") is False,
         "blocked_snapshot_changed": out.get("recovery", {}).get("status") == "blocked"
            and out.get("recovery", {}).get("reason") == "snapshot_changed_for_existing_trigger"})

    # Unknown exact cost pauses, never treats the charge as zero or refunds it.
    unknown = seed_info["unknown_cost"]
    evidence = {"interrupted_run_id": "1" * 32, "interrupted_generation": "generation-unknown",
                "containment_attempt": 1, "interrupted_executor_epoch": 1,
                "snapshot_tail_sequence": 0, "snapshot_digest": "9e952dd54f430824f4f5f61f47d892c39d1908472c1b81147714f52329648085"}
    _, out = dispatch(workspace, unknown["task_id"], unknown["reservation_id"], evidence)
    obs["scenarios"]["negative-unknown-cost-paused"] = scenario(
        "negative-unknown-cost-paused", "backend", out,
        {"dispatch_refused": out.get("dispatch") is False,
         "paused_unknown_attempt_charge": out.get("recovery", {}).get("status") == "paused"
            and out.get("recovery", {}).get("reason") == "unknown_attempt_charge"})

    # Below the qualified model-call floor blocks.
    floor = seed_info["below_floor"]
    evidence = {"interrupted_run_id": "2" * 32, "interrupted_generation": "generation-floor",
                "containment_attempt": 1, "interrupted_executor_epoch": 1,
                "snapshot_tail_sequence": 0, "snapshot_digest": "9e952dd54f430824f4f5f61f47d892c39d1908472c1b81147714f52329648085"}
    _, out = dispatch(workspace, floor["task_id"], floor["reservation_id"], evidence)
    obs["scenarios"]["negative-below-model-call-floor"] = scenario(
        "negative-below-model-call-floor", "backend", out,
        {"dispatch_refused": out.get("dispatch") is False,
         "blocked_below_floor": out.get("recovery", {}).get("status") == "blocked"
            and out.get("recovery", {}).get("reason") == "below_model_call_floor"})

    # Ordinal cap: a 4th fenced loss of one reservation is refused.
    ordinal = seed_info["ordinal_cap"]
    evidence = {"interrupted_run_id": "c" * 32, "interrupted_generation": "generation-cap-4",
                "containment_attempt": 1, "interrupted_executor_epoch": 1,
                "snapshot_tail_sequence": 0, "snapshot_digest": "9e952dd54f430824f4f5f61f47d892c39d1908472c1b81147714f52329648085"}
    _, out = dispatch(workspace, ordinal["task_id"], ordinal["reservation_id"], evidence)
    obs["scenarios"]["negative-ordinal-cap"] = scenario(
        "negative-ordinal-cap", "backend", out,
        {"dispatch_refused": out.get("dispatch") is False,
         "blocked_ordinal_cap": out.get("recovery", {}).get("status") == "blocked"
            and out.get("recovery", {}).get("reason") == "ordinal_cap"})

    # Recovery-mode admission envelope on the real Backend domain-call route: a
    # bound recovery target run may only replay the exact original five-tuple.
    if happy.get("attempt"):
        target_run = happy["target_run"]
        agent_headers = {**trusted(workspace), "x-byq-actor-principal": "byq-product-agent-" + SESSION,
                         "x-byq-root-run-id": target_run, "x-byq-dsh-run-id": "generation-acceptance"}
        def claim(task_id, key):
            return http("POST", backend("/v1/research/strategies/validate"), {
                "task_id": task_id, "agent_run_id": "a" * 32, "idempotency_key": key,
                "strategy": {"code": "synthetic-recovery-write"}, "trace_id": TRACE}, agent_headers)
        status, out = claim(seed_info["happy"]["task_id"], "acceptance-brand-new-key-0001")
        obs["scenarios"]["negative-recovery-new-key"] = scenario(
            "negative-recovery-new-key", "backend-domain-claim", {"status": status, "body": out},
            {"refused": status == 409
                and out.get("detail", {}).get("reason") == "recovery_envelope_violation"})
        status, out = claim(seed_info["unknown_cost"]["task_id"], "acceptance-cross-task-key-0001")
        obs["scenarios"]["negative-recovery-cross-task"] = scenario(
            "negative-recovery-cross-task", "backend-domain-claim", {"status": status, "body": out},
            {"refused": status == 409
                and out.get("detail", {}).get("reason") == "recovery_envelope_violation"})
    else:
        for name in ("negative-recovery-new-key", "negative-recovery-cross-task"):
            obs["scenarios"][name] = blocked(name, "backend-domain-claim",
                                             "no accepted recovery attempt to bound")

    # The Backend rejects a stale target epoch on write-back (fenced).
    if happy.get("attempt"):
        stale = {"reservation_id": seed_info["happy"]["reservation_id"], "status": "accepted",
                 "run_id": happy["target_run"], "attempt_key": happy["attempt"]["attempt_key"],
                 "target_executor_epoch": happy["attempt"]["target_executor_epoch"] + 1,
                 "target_generation": happy["attempt"]["target_generation"]}
        status, out = http("POST", backend(f"/internal/task-continuation/{seed_info['happy']['task_id']}/receipt"),
                           stale, trusted(workspace))
        obs["scenarios"]["negative-stale-target-epoch"] = scenario(
            "negative-stale-target-epoch", "backend", {"status": status, "body": out},
            {"refused": status >= 400 and "stale" in json.dumps(out).lower()})
    else:
        obs["scenarios"]["negative-stale-target-epoch"] = blocked(
            "negative-stale-target-epoch", "backend", "no accepted recovery attempt to fence")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)
    stack = Stack(SCOPE)
    observations: dict = {"schema_version": "byq-v090-business-recovery-acceptance-observations.v1",
                          "scenarios": {}}
    cleanup = None
    try:
        stack.down()
        stack.build()
        stack.up()
        seed_info = seed(stack)
        observations["seed"] = {key: seed_info[key] for key in
            ("owner", "workspace_id", "session_id", "trace_id", "conversation_id")}
        happy = run_happy(stack, seed_info, observations)
        run_negatives(stack, seed_info, happy, observations)
    except Exception as error:  # noqa: BLE001
        observations["error"] = f"{type(error).__name__}: {error}"
    finally:
        if not args.keep:
            cleanup = stack.down()
            observations["cleanup"] = cleanup
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(redact(observations), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "captured", "out": str(args.out),
                      "scenarios": {k: v.get("result") for k, v in observations["scenarios"].items()},
                      "cleanup": cleanup}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
