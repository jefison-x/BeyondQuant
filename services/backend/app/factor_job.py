"""Durable, workspace-scoped factor computation Jobs (Clean Break Phase 11)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import PgStoreMixin, execute, fetch_one
from .factor_research import FactorValidationError, prepare_factor_input
from .research import IdempotencyConflict, ResearchNotFound, _identifier, _idempotency_key, _text, _trace_id


MAX_ATTEMPTS = 3
MAX_INPUT_BYTES = 4 * 1024 * 1024
CLAIM_LEASE_SECONDS = 5 * 60
_JOB_ID = re.compile(r"^factorjob_[0-9a-f]{32}$")
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PUBLIC_STATUS = {
    "queued": "QUEUED",
    "running": "RUNNING",
    "completed": "SUCCEEDED",
    "failed": "FAILED",
    "cancelled": "CANCELLED",
}


class FactorJobLeaseLost(RuntimeError):
    """The claimed attempt can no longer commit its result."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_text(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise FactorValidationError("factor input must be JSON-serializable") from error


class FactorJobStore(PgStoreMixin):
    """Factor-specific durable queue and its bounded public Job projection."""

    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS factor_jobs (
            job_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            owner_principal TEXT NOT NULL,
            experiment_id TEXT,
            trace_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            input_manifest_id TEXT NOT NULL,
            request_json JSONB NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('queued','running','completed','failed','cancelled')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
            max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 3),
            worker_id TEXT,
            claimed_at TIMESTAMPTZ,
            result_artifact_id TEXT,
            error_code TEXT,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            UNIQUE (task_id, idempotency_key)
        )
        """,
        "CREATE INDEX IF NOT EXISTS factor_jobs_poll ON factor_jobs(status, created_at, job_id)",
        "CREATE INDEX IF NOT EXISTS factor_jobs_stale_claim ON factor_jobs(status, claimed_at, job_id)",
    ]

    def create(self, payload: object, *, trusted_owner: str, trusted_workspace: str, _connection=None) -> dict[str, object]:
        """Validate and enqueue one factor request, atomically with its caller."""
        prepared = prepare_factor_input(payload)
        if not isinstance(payload, dict):  # prepare_factor_input raises first
            raise FactorValidationError("factor request must be an object")
        task_id = _identifier(payload.get("task_id"), field="task_id")
        key = _idempotency_key(payload.get("idempotency_key"))
        trace_id = _trace_id(payload.get("trace_id"))
        experiment_id = (
            _identifier(payload["experiment_id"], field="experiment_id")
            if payload.get("experiment_id") is not None else None
        )
        owner = _text(trusted_owner, field="trusted_owner", max_length=128)
        workspace = _text(trusted_workspace, field="trusted_workspace", max_length=128)

        request_json = dict(payload)
        request_json.update({"task_id": task_id, "trace_id": trace_id, "idempotency_key": key})
        if experiment_id is None:
            request_json.pop("experiment_id", None)
        else:
            request_json["experiment_id"] = experiment_id
        input_text = _json_text(request_json)
        if len(input_text.encode("utf-8")) > MAX_INPUT_BYTES:
            raise FactorValidationError(f"factor input exceeds {MAX_INPUT_BYTES} bytes")

        manifest_id = str(prepared["manifest_id"])
        # The factor manifest canonicalizes order-insensitive input collections.
        # Bind that normalized identity to task, trace and experiment so retries
        # of the same calculation reuse a Job while metadata changes conflict.
        hash_request = {
            "task_id": task_id,
            "trace_id": trace_id,
            "experiment_id": experiment_id,
            "input_manifest_id": manifest_id,
        }
        request_hash = hashlib.sha256(_json_text(hash_request).encode("utf-8")).hexdigest()
        now = _now()
        manager = nullcontext(_connection) if _connection is not None else self._transaction()
        with manager as connection:
            execute(connection, "SET LOCAL lock_timeout = '2s'")
            task = fetch_one(
                connection,
                """SELECT task_id, owner_principal, workspace_id FROM research_tasks
                   WHERE task_id=:task FOR SHARE""",
                {"task": task_id},
            )
            if task is None or task["owner_principal"] != owner or task["workspace_id"] != workspace:
                raise ResearchNotFound("research task not found")
            if experiment_id is not None:
                experiment = fetch_one(
                    connection,
                    """SELECT experiment_id FROM experiments
                       WHERE experiment_id=:experiment AND task_id=:task
                         AND owner_principal=:owner AND workspace_id=:workspace""",
                    {"experiment": experiment_id, "task": task_id, "owner": owner, "workspace": workspace},
                )
                if experiment is None:
                    raise ResearchNotFound("experiment does not belong to research task")

            # Use the existing Artifact lock so a key already consumed by an
            # Artifact submission cannot also admit a factor Job.
            execute(connection, "SELECT pg_advisory_xact_lock(hashtext(:scope))",
                    {"scope": f"research-artifact|{task_id}|{key}"})
            existing = fetch_one(
                connection,
                """SELECT * FROM factor_jobs
                   WHERE task_id=:task AND idempotency_key=:key FOR UPDATE""",
                {"task": task_id, "key": key},
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict("factor job idempotency key was reused")
                return self._public_row(existing)

            artifact = fetch_one(
                connection,
                "SELECT artifact_id FROM artifacts WHERE task_id=:task AND idempotency_key=:key",
                {"task": task_id, "key": key},
            )
            receipt = fetch_one(
                connection,
                """SELECT artifact_id FROM artifact_submission_receipts
                   WHERE task_id=:task AND idempotency_key=:key""",
                {"task": task_id, "key": key},
            )
            if artifact is not None or receipt is not None:
                raise IdempotencyConflict("factor idempotency key is already used by an artifact")

            job_id = f"factorjob_{uuid.uuid4().hex}"
            execute(
                connection,
                """INSERT INTO factor_jobs
                   (job_id, task_id, workspace_id, owner_principal, experiment_id,
                    trace_id, idempotency_key, request_hash, input_manifest_id,
                    request_json, status, attempts, max_attempts, created_at, updated_at)
                   VALUES (:job, :task, :workspace, :owner, :experiment,
                           :trace, :key, :request_hash, :manifest,
                           :request, 'queued', 0, :max_attempts, :now, :now)""",
                {"job": job_id, "task": task_id, "workspace": workspace, "owner": owner,
                 "experiment": experiment_id, "trace": trace_id, "key": key,
                 "request_hash": request_hash, "manifest": manifest_id, "request": request_json,
                 "max_attempts": MAX_ATTEMPTS, "now": now},
            )
            row = fetch_one(connection, "SELECT * FROM factor_jobs WHERE job_id=:job", {"job": job_id})
            if row is None:
                raise RuntimeError("factor job insert did not return its row")
            return self._public_row(row)

    def get(
        self, *, trusted_owner: str, trusted_workspace: str, job_id: str | None = None,
        task_id: str | None = None, idempotency_key: str | None = None,
    ) -> dict[str, object] | None:
        """Read one public Job under both workspace and owner scope."""
        owner = _text(trusted_owner, field="trusted_owner", max_length=128)
        workspace = _text(trusted_workspace, field="trusted_workspace", max_length=128)
        if job_id is not None:
            if task_id is not None or idempotency_key is not None:
                raise ValueError("query by job_id or task_id plus idempotency_key")
            identity = _text(job_id, field="job_id", max_length=64)
            if _JOB_ID.fullmatch(identity) is None:
                raise ValueError("job_id is invalid")
            row = self._fetch_one(
                """SELECT * FROM factor_jobs WHERE job_id=:job
                   AND owner_principal=:owner AND workspace_id=:workspace""",
                {"job": identity, "owner": owner, "workspace": workspace},
            )
        else:
            if task_id is None or idempotency_key is None:
                raise ValueError("task_id and idempotency_key are both required")
            task = _identifier(task_id, field="task_id")
            key = _idempotency_key(idempotency_key)
            row = self._fetch_one(
                """SELECT * FROM factor_jobs WHERE task_id=:task AND idempotency_key=:key
                   AND owner_principal=:owner AND workspace_id=:workspace""",
                {"task": task, "key": key, "owner": owner, "workspace": workspace},
            )
        return None if row is None else self._public_row(row)

    def claim_next(self, worker_id: str = "factor-worker") -> dict[str, object] | None:
        """Atomically claim queued or expired work and advance its attempt fence."""
        worker = _text(worker_id, field="worker_id", max_length=128)
        now = _now()
        stale_before = now - timedelta(seconds=CLAIM_LEASE_SECONDS)
        with self._transaction() as connection:
            exhausted = fetch_one(
                connection,
                """SELECT * FROM factor_jobs
                   WHERE status='running' AND attempts >= max_attempts AND claimed_at <= :stale
                   ORDER BY claimed_at, job_id LIMIT 1 FOR UPDATE SKIP LOCKED""",
                {"stale": stale_before},
            )
            if exhausted is not None:
                # A worker may have committed the validated Artifact and then
                # died before it acknowledged the Job. Reconcile that exact
                # result before declaring the final attempt failed.
                artifact = fetch_one(
                    connection,
                    """SELECT artifact.artifact_id FROM artifacts AS artifact
                       WHERE artifact.task_id=:task AND artifact.owner_principal=:owner
                         AND artifact.workspace_id=:workspace AND artifact.kind='factor_result'
                         AND artifact.status='validated' AND artifact.idempotency_key=:result_key
                         AND artifact.trace_id=:trace
                         AND artifact.experiment_id IS NOT DISTINCT FROM :experiment
                         AND artifact.content->>'input_manifest_id'=:manifest""",
                    {"task": exhausted["task_id"], "owner": exhausted["owner_principal"],
                     "workspace": exhausted["workspace_id"],
                     "result_key": f"factor-result-{exhausted['job_id']}",
                     "trace": exhausted["trace_id"], "experiment": exhausted["experiment_id"],
                     "manifest": exhausted["input_manifest_id"]},
                )
                if artifact is not None:
                    execute(connection, """UPDATE factor_jobs SET status='completed',
                        result_artifact_id=:artifact, error_code=NULL, error_message=NULL,
                        worker_id=NULL, claimed_at=NULL, finished_at=:now, updated_at=:now
                        WHERE job_id=:job AND status='running'""",
                        {"artifact": artifact["artifact_id"], "job": exhausted["job_id"], "now": now})
                else:
                    execute(connection, """UPDATE factor_jobs SET status='failed',
                        error_code='worker_attempts_exhausted',
                        error_message='factor worker attempts were exhausted', worker_id=NULL,
                        claimed_at=NULL, finished_at=:now, updated_at=:now
                        WHERE job_id=:job AND status='running'""",
                        {"job": exhausted["job_id"], "now": now})
            row = fetch_one(
                connection,
                """SELECT * FROM factor_jobs
                   WHERE (status='queued' AND attempts < max_attempts)
                      OR (status='running' AND attempts < max_attempts AND claimed_at <= :stale)
                   ORDER BY created_at, job_id LIMIT 1 FOR UPDATE SKIP LOCKED""",
                {"stale": stale_before},
            )
            if row is None:
                return None
            attempt = int(row["attempts"]) + 1
            execute(
                connection,
                """UPDATE factor_jobs SET status='running', attempts=:attempt, worker_id=:worker,
                       claimed_at=:now, started_at=COALESCE(started_at, :now), updated_at=:now,
                       error_code=NULL, error_message=NULL WHERE job_id=:job""",
                {"attempt": attempt, "worker": worker, "now": now, "job": row["job_id"]},
            )
            row.update({"status": "running", "attempts": attempt, "worker_id": worker,
                        "claimed_at": now.isoformat(), "started_at": row.get("started_at") or now.isoformat(),
                        "updated_at": now.isoformat(), "error_code": None, "error_message": None})
            return self._internal_row(row)

    def require_execution_claim(self, connection, job_id: str, attempt: int) -> None:
        """Lock the live Job for the entire factor and Artifact transaction."""
        live = fetch_one(connection, """SELECT job_id FROM factor_jobs
            WHERE job_id=:job AND status='running' AND attempts=:attempt
              AND claimed_at + make_interval(secs => CAST(:lease_seconds AS double precision)) > clock_timestamp()
            FOR UPDATE""", {"job": job_id, "attempt": attempt,
                "lease_seconds": CLAIM_LEASE_SECONDS})
        if live is None:
            raise FactorJobLeaseLost("factor Job attempt has expired")

    def complete(self, job_id: str, attempt: int, result_artifact_id: str, *, _connection=None) -> bool:
        """Complete only the currently fenced running attempt."""
        identity = _text(job_id, field="job_id", max_length=64)
        if _JOB_ID.fullmatch(identity) is None:
            raise ValueError("job_id is invalid")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= MAX_ATTEMPTS:
            raise ValueError("attempt is invalid")
        artifact_id = _identifier(result_artifact_id, field="result_artifact_id")
        now = _now()
        with (self._transaction() if _connection is None else nullcontext(_connection)) as connection:
            row = fetch_one(
                connection,
                """UPDATE factor_jobs AS job SET status='completed', result_artifact_id=:artifact,
                       error_code=NULL, error_message=NULL, worker_id=NULL, claimed_at=NULL,
                       finished_at=:now, updated_at=:now
                   WHERE job.job_id=:job AND job.status='running' AND job.attempts=:attempt
                     AND job.claimed_at + make_interval(secs => CAST(:lease_seconds AS double precision)) > clock_timestamp()
                     AND EXISTS (
                         SELECT 1 FROM artifacts AS artifact
                         WHERE artifact.artifact_id=:artifact AND artifact.task_id=job.task_id
                           AND artifact.owner_principal=job.owner_principal
                           AND artifact.workspace_id=job.workspace_id
                           AND artifact.kind='factor_result' AND artifact.status='validated'
                           AND artifact.idempotency_key='factor-result-' || job.job_id
                           AND artifact.trace_id=job.trace_id
                           AND artifact.experiment_id IS NOT DISTINCT FROM job.experiment_id
                           AND artifact.content->>'input_manifest_id'=job.input_manifest_id
                     )
                   RETURNING job.job_id""",
                {"artifact": artifact_id, "now": now, "job": identity, "attempt": attempt,
                 "lease_seconds": CLAIM_LEASE_SECONDS},
            )
            return row is not None

    def fail(
        self, job_id: str, attempt: int, error_code: str, error_message: str, *, retryable: bool = True,
    ) -> bool:
        """Fail or requeue only the currently fenced attempt."""
        identity = _text(job_id, field="job_id", max_length=64)
        if _JOB_ID.fullmatch(identity) is None:
            raise ValueError("job_id is invalid")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= MAX_ATTEMPTS:
            raise ValueError("attempt is invalid")
        if not isinstance(retryable, bool):
            raise ValueError("retryable must be boolean")
        code = _text(error_code, field="error_code", max_length=64)
        if _ERROR_CODE.fullmatch(code) is None:
            raise ValueError("error_code is invalid")
        message = _text(error_message, field="error_message", max_length=500)
        now = _now()
        with self._transaction() as connection:
            row = fetch_one(
                connection,
                """UPDATE factor_jobs SET
                       status=CASE WHEN :retryable AND attempts < max_attempts THEN 'queued' ELSE 'failed' END,
                       error_code=:code, error_message=:message, worker_id=NULL, claimed_at=NULL,
                       finished_at=CASE WHEN :retryable AND attempts < max_attempts THEN NULL ELSE :now END,
                       updated_at=:now
                   WHERE job_id=:job AND status='running' AND attempts=:attempt
                     AND claimed_at + make_interval(secs => CAST(:lease_seconds AS double precision)) > clock_timestamp()
                   RETURNING job_id""",
                {"retryable": retryable, "code": code, "message": message, "now": now,
                 "job": identity, "attempt": attempt, "lease_seconds": CLAIM_LEASE_SECONDS},
            )
            return row is not None

    @staticmethod
    def _public_row(row: dict[str, Any]) -> dict[str, object]:
        status = row.get("status")
        if status not in _PUBLIC_STATUS:
            raise RuntimeError("factor job has an unknown status")
        error = None if row.get("error_code") is None else {
            "code": row["error_code"], "message": row.get("error_message")
        }
        return {
            "job_id": row["job_id"], "workspace_id": row["workspace_id"], "task_id": row["task_id"],
            "type": "FACTOR", "status": _PUBLIC_STATUS[str(status)],
            "progress": 100 if status == "completed" else None,
            "input_ref": row["input_manifest_id"], "result_ref": row.get("result_artifact_id"),
            "error": error, "created_at": row.get("created_at"),
            "started_at": row.get("started_at"), "finished_at": row.get("finished_at"),
        }

    @staticmethod
    def _internal_row(row: dict[str, Any]) -> dict[str, object]:
        request = row.get("request_json")
        if not isinstance(request, dict):
            raise RuntimeError("factor job input is invalid")
        return {
            "job_id": row["job_id"], "task_id": row["task_id"],
            "workspace_id": row["workspace_id"], "owner_principal": row["owner_principal"],
            "request_json": request, "input_manifest_id": row["input_manifest_id"],
            "attempt": int(row["attempts"]),
        }
