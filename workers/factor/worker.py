"""Independent polling worker for durable BYQ factor computation Jobs."""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import uuid
from collections.abc import Callable

from app.factor_job import FactorJobLeaseLost, FactorJobStore
from app.factor_research import FactorValidationError, compute_factor
from app.factor_submission import submit_factor
from app.research import IdempotencyConflict, InvalidTransition, ResearchNotFound, ResearchStore


logger = logging.getLogger("byq.factor.worker")


class FactorWorker:
    def __init__(
        self,
        job_store: FactorJobStore,
        research_store: ResearchStore,
        *,
        compute: Callable[[object], dict[str, object]] = compute_factor,
        worker_id: str | None = None,
    ) -> None:
        self.job_store = job_store
        self.research_store = research_store
        self.compute = compute
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:12]}"

    def run_once(self) -> bool:
        claim = self.job_store.claim_next(self.worker_id)
        if claim is None:
            return False
        job_id = str(claim["job_id"])
        attempt = int(claim["attempt"])
        payload = dict(claim["request_json"])
        payload["idempotency_key"] = f"factor-result-{job_id}"
        context = {"owner_principal": str(claim["owner_principal"]),
                   "workspace_id": str(claim["workspace_id"])}
        try:
            # The claim row stays locked while the bounded deterministic factor
            # runs. Artifact validation and Job completion commit together;
            # an expired attempt rolls the Artifact back too.
            with self.job_store._transaction() as connection:
                self.job_store.require_execution_claim(connection, job_id, attempt)
                result = submit_factor(
                    self.research_store, payload, context, self.compute, _connection=connection,
                )
                artifact = result.get("artifact")
                artifact_id = artifact.get("artifact_id") if isinstance(artifact, dict) else None
                if not isinstance(artifact_id, str):
                    raise RuntimeError("factor computation returned no Artifact identity")
                validated = self.research_store.transition(
                    "artifact", artifact_id, "validated", f"factor-validation-{job_id}",
                    _connection=connection,
                )
                if (
                    validated.get("artifact_id") != artifact_id
                    or validated.get("task_id") != claim["task_id"]
                    or validated.get("owner_principal") != claim["owner_principal"]
                    or validated.get("workspace_id") != claim["workspace_id"]
                    or validated.get("kind") != "factor_result"
                    or validated.get("status") != "validated"
                ):
                    raise RuntimeError("factor result Artifact is not valid for this Job")
                if not self.job_store.complete(job_id, attempt, artifact_id, _connection=connection):
                    raise FactorJobLeaseLost("factor Job attempt expired before completion")
        except Exception as error:
            if isinstance(error, FactorValidationError):
                error_code, retryable = f"factor_{error.code}", False
            elif isinstance(error, IdempotencyConflict):
                error_code, retryable = "factor_artifact_conflict", False
            elif isinstance(error, ResearchNotFound):
                error_code, retryable = "factor_task_missing", False
            elif isinstance(error, InvalidTransition):
                error_code, retryable = "factor_artifact_transition_failed", False
            else:
                error_code, retryable = "factor_execution_failed", True
            self.job_store.fail(job_id, attempt, error_code, "factor computation failed", retryable=retryable)
            logger.warning("factor job %s attempt %d failed (%s)", job_id, attempt, error_code)
        return True

    def run_forever(
        self, *, poll_interval_seconds: float = 1.0, stop_event: threading.Event | None = None,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll interval must be positive")
        while stop_event is None or not stop_event.is_set():
            if self.run_once():
                continue
            if stop_event is None:
                time.sleep(poll_interval_seconds)
            elif stop_event.wait(poll_interval_seconds):
                break


def main() -> int:
    logging.basicConfig(level=os.getenv("BYQ_LOG_LEVEL", "INFO"))
    jobs = FactorJobStore.from_env()
    research = ResearchStore.from_env()
    worker = FactorWorker(jobs, research)
    stopping = threading.Event()

    def stop(_number: int, _frame: object) -> None:
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    poll_seconds = max(0.1, float(os.getenv("BYQ_FACTOR_POLL_SECONDS", "1")))
    try:
        worker.run_forever(poll_interval_seconds=poll_seconds, stop_event=stopping)
        return 0
    finally:
        research.close()
        jobs.close()


if __name__ == "__main__":
    raise SystemExit(main())
