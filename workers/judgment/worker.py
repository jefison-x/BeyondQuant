"""ADR-0107 judgment-only consumer.

Reuses the per-domain worker shape (a bounded poll loop) but **not** the backtest
``requeue_stale`` auto-re-execution semantics: a judgment whose root may have
dispatched is never re-dispatched, and the consumer never advances the plan (the
existing Backend result transaction is the only plan advance). The consumer only
selects a ``judgment_turn`` stage, claims its exact attempt, dispatches the
Runtime Adapter judgment route with the task's trusted context, and reads the
result to confirm the stage advanced.

BYQ keeps only business attribution/authorization/idempotency/unknown-result
reconciliation/exact terminal ACK; generic Agent cancel/context/recovery and
container/process management are out of scope (DSH/container management).
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import signal
import time
import uuid

import httpx

from packages.contracts.research_judgment import (
    JUDGMENT_STAGE_CLAIM_SCHEMA_VERSION,
    attempt_binding,
)

_ACTOR_PREFIX = "byq-product-agent-"


def derive_call_identity(task_id: str, plan_version: int, stage: str, iteration: int) -> str:
    binding = attempt_binding(plan_version, stage, iteration)
    digest = hashlib.sha256(f"{task_id}:{binding}".encode("utf-8")).hexdigest()[:32]
    return "byq-judgment-" + digest


class JudgmentConsumer:
    """One bounded consumer over the Backend selection + claim and the Adapter route."""

    def __init__(self, *, backend_url: str, adapter_url: str, judgment_token: str,
                 claim_owner: str, lease_seconds: int = 300, transport=None,
                 authority_token: str = "", runtime_boot_id: str = "",
                 target_task: str = "") -> None:
        self._backend = backend_url.rstrip("/")
        self._adapter = adapter_url.rstrip("/")
        self._token = judgment_token
        self._authority_token = authority_token
        self._runtime_boot_id = runtime_boot_id
        self._owner = claim_owner
        self._lease_seconds = lease_seconds
        self._target_task = target_task
        self._http = transport or httpx.Client(timeout=30.0)

    def _consumer_headers(self, task: dict) -> dict:
        # The claim context is the existing trusted consumer (owner == actor) PLUS
        # the real runtime-authority service bearer (never just an x-byq-* header).
        return {"authorization": f"Bearer {self._authority_token}",
                "x-byq-owner-principal": task["owner_principal"],
                "x-byq-workspace-id": task["workspace_id"],
                "x-byq-actor-principal": task["owner_principal"]}

    def _adapter_headers(self, task: dict) -> dict:
        session = task["session_id"]
        return {
            "x-byq-runtime-judgment-token": self._token,
            "x-byq-judgment-attempt": attempt_binding(
                task["plan_version"], task["stage"], task["iteration"]),
            "x-byq-owner-principal": task["owner_principal"],
            "x-byq-workspace-id": task["workspace_id"],
            "x-byq-actor-principal": _ACTOR_PREFIX + session,
            "x-byq-trace-id": task["trace_id"],
            "x-byq-session-id": session,
            "x-byq-dsh-run-id": "byqjudg-" + hashlib.sha256(
                f"{task['task_id']}:{session}".encode("utf-8")).hexdigest()[:32],
        }

    def select(self) -> list[dict]:
        """READ-ONLY selection of tasks at a judgment stage (service-only).

        An optional single target task bounds the acceptance scope so the consumer
        never scans or touches unrelated tasks.
        """
        response = self._http.get(
            f"{self._backend}/internal/research-judgment/stages",
            headers={"authorization": f"Bearer {self._authority_token}"})
        response.raise_for_status()
        tasks = list(response.json().get("stages", []))
        if self._target_task:
            tasks = [task for task in tasks if task.get("task_id") == self._target_task]
        return tasks

    def claim(self, task: dict) -> dict:
        call_identity = derive_call_identity(
            task["task_id"], task["plan_version"], task["stage"], task["iteration"])
        response = self._http.post(
            f"{self._backend}/internal/research-judgment/{task['task_id']}/stage-claim",
            headers={**self._consumer_headers(task),
                     "x-byq-judgment-call-identity": call_identity},
            json={"schema_version": JUDGMENT_STAGE_CLAIM_SCHEMA_VERSION,
                  "claim_owner": self._owner, "lease_seconds": self._lease_seconds})
        response.raise_for_status()
        return response.json()

    def record_dispatch_intent(self, task: dict) -> dict:
        """Persist the dispatch-intent BEFORE the Adapter run request."""
        call_identity = derive_call_identity(
            task["task_id"], task["plan_version"], task["stage"], task["iteration"])
        response = self._http.post(
            f"{self._backend}/internal/research-judgment/{task['task_id']}/stage-dispatch-intent",
            headers={**self._consumer_headers(task),
                     "x-byq-judgment-call-identity": call_identity},
            json={"schema_version": JUDGMENT_STAGE_CLAIM_SCHEMA_VERSION,
                  "claim_owner": self._owner, "lease_seconds": self._lease_seconds})
        response.raise_for_status()
        return response.json()

    def _current_boot(self) -> str:
        """The exact current Backend runtime boot (fetched if not pinned)."""
        if self._runtime_boot_id:
            return self._runtime_boot_id
        response = self._http.get(f"{self._backend}/internal/runtime-authority/current")
        response.raise_for_status()
        boot = response.json().get("boot_id")
        if not isinstance(boot, str) or not boot:
            raise RuntimeError("runtime authority boot is unavailable")
        self._runtime_boot_id = boot
        return boot

    def _status_headers(self, task: dict) -> dict:
        return {"authorization": f"Bearer {self._authority_token}",
                "x-byq-owner-principal": task["owner_principal"],
                "x-byq-workspace-id": task["workspace_id"],
                "x-byq-runtime-boot-id": self._current_boot()}

    def business_gate(self, task: dict) -> dict:
        """The real read-only business gate (task status/approval/version/stage).

        The consumer must dispatch only when this bounded descriptor's kind is
        ``judgment_turn``; the SQL stage whitelist alone is not authorization.
        """
        response = self._http.get(
            f"{self._backend}/internal/research-judgment/{task['task_id']}/dispatch",
            headers=self._consumer_headers(task))
        response.raise_for_status()
        return response.json()

    def reconcile(self, task: dict) -> dict:
        """READ-ONLY readback of the exact ACP root status/terminal receipt.

        Reuses the trusted Backend read-only status interface; it never writes the
        plan and never re-dispatches. A 404 means the root does not exist yet (the
        run is in flight or the response was lost) and is reported as pending, not
        an error.
        """
        call_identity = derive_call_identity(
            task["task_id"], task["plan_version"], task["stage"], task["iteration"])
        response = self._http.post(
            f"{self._backend}/internal/research-judgment/{task['task_id']}/acp-root/status",
            headers=self._status_headers(task),
            json={"schema_version": "byq-research-judgment-acp-status.v1",
                  "call_identity": call_identity,
                  "attempt_binding": attempt_binding(
                      task["plan_version"], task["stage"], task["iteration"])})
        if getattr(response, "status_code", 200) == 404:
            return {"status": "no_root_yet"}
        response.raise_for_status()
        return response.json()

    def dispatch(self, task: dict) -> dict:
        response = self._http.post(
            f"{self._adapter}/internal/runtime/research-judgment/{task['task_id']}/acp-root/run",
            headers=self._adapter_headers(task), json={}, timeout=300.0)
        response.raise_for_status()
        return response.json()

    def run_once(self) -> dict:
        """One bounded pass: select, claim, dispatch-intent, dispatch, reconcile.

        The consumer never writes the plan; the Backend result transaction is the
        only plan advance. A reconcile-only claim reads the trusted status receipt
        and never re-runs.
        """
        outcomes = []
        for task in self.select():
            # The real business gate (task status/approval/version/stage) must be
            # read before any claim; only a judgment_turn may be dispatched.
            gate = self.business_gate(task)
            if gate.get("kind") != "judgment_turn":
                outcomes.append({"task_id": task["task_id"], "kind": gate.get("kind"),
                                 "dispatched": False})
                continue
            claimed = self.claim(task)
            if claimed.get("reconcile_only") is True:
                outcomes.append({"task_id": task["task_id"], "reconcile_only": True,
                                 "reason": claimed.get("reason"),
                                 "status_receipt": self.reconcile(task)})
                continue
            if claimed.get("claimed") is not True:
                outcomes.append({"task_id": task["task_id"], "claimed": False,
                                 "reason": claimed.get("reason")})
                continue
            intent = self.record_dispatch_intent(task)
            if intent.get("intent") is not True:
                outcomes.append({"task_id": task["task_id"], "claimed": True,
                                 "intent": False, "reason": intent.get("reason")})
                continue
            # A claim + dispatch-intent authorize nothing by themselves; the Adapter
            # route performs begin/register/prompt/settle and the Backend result
            # transaction is the only plan advance. The consumer does not write the plan.
            result = self.dispatch(task)
            # Verify the exact Backend terminal/root/current stage (read-only).
            outcomes.append({"task_id": task["task_id"], "claimed": True, "intent": True,
                             "run": {"status": result.get("status"),
                                     "settlement_kind": result.get("settlement_kind")},
                             "status_receipt": self.reconcile(task)})
        return {"outcomes": outcomes}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the ADR-0107 judgment consumer")
    parser.add_argument("--once", action="store_true")
    arguments = parser.parse_args()
    logging.basicConfig(level=os.getenv("BYQ_LOG_LEVEL", "INFO"))
    logger = logging.getLogger("byq.judgment.worker")
    authority_token = os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
    runtime_boot_id = os.environ.get("BYQ_RUNTIME_BOOT_ID", "")
    judgment_token = os.environ.get("BYQ_RUNTIME_JUDGMENT_TOKEN", "")
    if not authority_token or not judgment_token:
        # Fail fast: the trusted service credential and the judgment bearer are
        # required; the exact runtime boot is fetched (never defaulted).
        logger.error("judgment consumer requires BYQ_RUNTIME_AUTHORITY_TOKEN and "
                     "BYQ_RUNTIME_JUDGMENT_TOKEN")
        return 2
    consumer = JudgmentConsumer(
        backend_url=os.environ.get("BYQ_BACKEND_URL", "http://backend:8000"),
        adapter_url=os.environ.get("BYQ_RUNTIME_ADAPTER_URL", "http://runtime-adapter:8400"),
        judgment_token=judgment_token,
        authority_token=authority_token,
        runtime_boot_id=runtime_boot_id,
        # A per-instance unique owner id: two replicas must never share one id and
        # be treated as the "same owner". Never rely on a default shared name.
        claim_owner=os.environ.get("BYQ_JUDGMENT_CONSUMER_ID")
        or ("byq-judgment-consumer-" + uuid.uuid4().hex),
        target_task=os.environ.get("BYQ_JUDGMENT_TARGET_TASK", ""),
        lease_seconds=int(os.environ.get("BYQ_JUDGMENT_CLAIM_LEASE_SECONDS", "300")))
    running = True

    def stop(_number: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    poll = max(0.2, float(os.getenv("BYQ_JUDGMENT_POLL_SECONDS", "2")))
    while running:
        outcome = consumer.run_once()
        if outcome["outcomes"]:
            logger.info("judgment consumer: %s", outcome["outcomes"])
        if arguments.once:
            break
        time.sleep(poll)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
