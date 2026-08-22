"""Durable BYQ signal-production jobs and trusted coordinator (ADR-0023)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy.exc import SQLAlchemyError

from .backtest import normalize_signal_snapshot, signal_snapshot_content_sha256
from .db import PgStoreMixin, execute, fetch_one
from .research import ResearchStore


SIGNAL_JOB_SCHEMA_VERSION = "signal-producer-job-v1"
EXECUTION_PROFILE = "byq-signal-python-v1"
RUNTIME_LOCK = "python-3.13/pandas-2.3.3/numpy-2.3.3"
MAX_JOB_BYTES = 32 * 1024 * 1024
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,127}$")
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_SECRET_FRAGMENTS = (
    "token", "password", "secret", "apikey", "accesskey", "privatekey",
    "credential", "authorization",
)


class SignalProducerError(RuntimeError):
    pass


class SignalProducerNotFound(SignalProducerError):
    pass


class SignalProducerConflict(SignalProducerError):
    pass


class SignalProducerPersistenceError(SignalProducerError):
    pass


class SignalExecutionFailure(SignalProducerError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code


class SandboxExecutor(Protocol):
    def execute(self, payload: dict[str, object], *, timeout_seconds: float) -> dict[str, object]: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("signal producer input must be finite JSON") from error


def _reject_secrets(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            compact = "".join(character for character in str(key).lower() if character.isalnum())
            if any(fragment in compact for fragment in _SECRET_FRAGMENTS):
                raise ValueError("signal producer input must not contain credential fields")
            _reject_secrets(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_secrets(nested)


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value.strip()) is None:
        raise ValueError(f"{field} has invalid format")
    return value.strip()


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{field} must be a non-empty string of at most {maximum} characters")
    return value.strip()


def prepare_signal_job_input(
    *,
    strategy_version_artifact_id: str,
    strategy_version_id: str,
    source_fingerprint: str,
    script: str,
    stock_pool_snapshot_id: str,
    stock_pool_id: str,
    membership_fingerprint: str,
    symbols: list[str],
    bars: list[dict[str, object]],
    parameters: dict[str, object],
    execution: dict[str, object],
    order_quantity: int,
) -> dict[str, object]:
    """Build the secret-free immutable document handed to the coordinator."""
    document: dict[str, object] = {
        "schema_version": SIGNAL_JOB_SCHEMA_VERSION,
        "profile": EXECUTION_PROFILE,
        "runtime_lock": RUNTIME_LOCK,
        "strategy": {
            "strategy_version_artifact_id": strategy_version_artifact_id,
            "strategy_version_id": strategy_version_id,
            "source_fingerprint": source_fingerprint,
            "script": script,
        },
        "universe": {
            "universe_id": stock_pool_id,
            "version_id": stock_pool_snapshot_id,
            "membership_fingerprint": membership_fingerprint,
            "symbols": sorted(symbols),
        },
        "bars": bars,
        "parameters": parameters,
        "execution": execution,
        "order_quantity": order_quantity,
    }
    _reject_secrets(document)
    encoded = _canonical(document)
    if len(encoded) > MAX_JOB_BYTES:
        raise ValueError("signal producer input exceeds 32 MiB")
    document["input_sha256"] = hashlib.sha256(encoded).hexdigest()
    return document


class SignalJobStore(PgStoreMixin):
    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS signal_producer_jobs (
            job_id TEXT PRIMARY KEY,
            owner_principal TEXT NOT NULL,
            task_id TEXT NOT NULL REFERENCES research_tasks(task_id),
            experiment_id TEXT REFERENCES experiments(experiment_id),
            strategy_version_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
            stock_pool_snapshot_id TEXT NOT NULL REFERENCES stock_pool_snapshots(snapshot_id),
            status TEXT NOT NULL,
            input_json JSONB NOT NULL,
            input_sha256 TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            result_artifact_id TEXT REFERENCES artifacts(artifact_id),
            error_code TEXT,
            error_detail TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS signal_producer_jobs_idempotency
            ON signal_producer_jobs(owner_principal, idempotency_key)
        """,
        """
        CREATE INDEX IF NOT EXISTS signal_producer_jobs_queue
            ON signal_producer_jobs(status, created_at)
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as error:
            raise SignalProducerPersistenceError("signal producer storage is unavailable") from error

    @classmethod
    def from_env(cls) -> "SignalJobStore":
        return cls()

    def create(
        self,
        *,
        owner_principal: object,
        task_id: object,
        experiment_id: object | None,
        strategy_version_artifact_id: object,
        stock_pool_snapshot_id: object,
        input_document: dict[str, object],
        trace_id: object,
        idempotency_key: object,
    ) -> dict[str, object]:
        owner = _text(owner_principal, "owner_principal", 128)
        task = _identifier(task_id, "task_id")
        experiment = None if experiment_id is None else _identifier(experiment_id, "experiment_id")
        strategy = _identifier(strategy_version_artifact_id, "strategy_version_artifact_id")
        snapshot = _identifier(stock_pool_snapshot_id, "stock_pool_snapshot_id")
        trace = _text(trace_id, "trace_id", 128)
        idempotency = _text(idempotency_key, "idempotency_key", 128)
        if input_document.get("schema_version") != SIGNAL_JOB_SCHEMA_VERSION:
            raise ValueError("unsupported signal producer input schema")
        _reject_secrets(input_document)
        encoded = _canonical(input_document)
        if len(encoded) > MAX_JOB_BYTES:
            raise ValueError("signal producer input exceeds 32 MiB")
        input_sha256 = str(input_document.get("input_sha256", ""))
        without_identity = dict(input_document)
        without_identity.pop("input_sha256", None)
        if input_sha256 != hashlib.sha256(_canonical(without_identity)).hexdigest():
            raise ValueError("signal producer input identity does not match content")
        request = {
            "owner_principal": owner,
            "task_id": task,
            "experiment_id": experiment,
            "strategy_version_artifact_id": strategy,
            "stock_pool_snapshot_id": snapshot,
            "input_sha256": input_sha256,
            "trace_id": trace,
        }
        request_hash = hashlib.sha256(_canonical(request)).hexdigest()
        with self._transaction() as connection:
            existing = fetch_one(
                connection,
                """SELECT * FROM signal_producer_jobs
                   WHERE owner_principal = :owner AND idempotency_key = :idempotency_key""",
                {"owner": owner, "idempotency_key": idempotency},
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise SignalProducerConflict("signal job idempotency key was reused")
                return self._public_row(existing)
            now = _now()
            job_id = f"signaljob_{uuid.uuid4().hex}"
            execute(
                connection,
                """INSERT INTO signal_producer_jobs
                   (job_id, owner_principal, task_id, experiment_id,
                    strategy_version_artifact_id, stock_pool_snapshot_id, status,
                    input_json, input_sha256, trace_id, idempotency_key, request_hash,
                    created_at, updated_at)
                   VALUES (:job_id, :owner, :task_id, :experiment_id, :strategy,
                           :snapshot, 'queued', :input_json, :input_sha256, :trace_id,
                           :idempotency_key, :request_hash, :created_at, :updated_at)""",
                {
                    "job_id": job_id, "owner": owner, "task_id": task,
                    "experiment_id": experiment, "strategy": strategy, "snapshot": snapshot,
                    "input_json": input_document, "input_sha256": input_sha256,
                    "trace_id": trace, "idempotency_key": idempotency,
                    "request_hash": request_hash, "created_at": now, "updated_at": now,
                },
            )
        return self.get(job_id, trusted_owner=owner)

    def get(self, job_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        identity = _identifier(job_id, "job_id")
        row = self._fetch_one(
            "SELECT * FROM signal_producer_jobs WHERE job_id = :job_id", {"job_id": identity}
        )
        if row is None or (trusted_owner is not None and row["owner_principal"] != trusted_owner):
            raise SignalProducerNotFound("signal producer job not found")
        return self._public_row(row)

    def list_jobs(self, *, trusted_owner: str, limit: int = 50, offset: int = 0) -> dict[str, object]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("offset must be non-negative")
        rows = self._execute(
            """SELECT * FROM signal_producer_jobs WHERE owner_principal = :owner
               ORDER BY created_at DESC, job_id DESC LIMIT :limit OFFSET :offset""",
            {"owner": trusted_owner, "limit": limit, "offset": offset},
        )
        total = self._fetch_one(
            "SELECT COUNT(*) AS total FROM signal_producer_jobs WHERE owner_principal = :owner",
            {"owner": trusted_owner},
        )
        return {
            "jobs": [self._public_row(row) for row in rows],
            "total": int(total["total"] if total else 0),
            "limit": limit,
            "offset": offset,
        }

    def claim_next(self) -> dict[str, object] | None:
        with self._transaction() as connection:
            row = fetch_one(
                connection,
                """SELECT * FROM signal_producer_jobs WHERE status = 'queued'
                   ORDER BY created_at, job_id FOR UPDATE SKIP LOCKED LIMIT 1""",
            )
            if row is None:
                return None
            now = _now()
            execute(
                connection,
                """UPDATE signal_producer_jobs SET status = 'running', attempt_count = attempt_count + 1,
                          started_at = COALESCE(started_at, :now), updated_at = :now
                   WHERE job_id = :job_id""",
                {"job_id": row["job_id"], "now": now},
            )
            row["status"] = "running"
            row["attempt_count"] = int(row["attempt_count"]) + 1
            row["started_at"] = row.get("started_at") or now
            row["updated_at"] = now
            return self._internal_row(row)

    def complete(self, job_id: str, result_artifact_id: str) -> dict[str, object]:
        with self._transaction() as connection:
            row = fetch_one(
                connection,
                "SELECT * FROM signal_producer_jobs WHERE job_id = :job_id FOR UPDATE",
                {"job_id": job_id},
            )
            if row is None:
                raise SignalProducerNotFound("signal producer job not found")
            if row["status"] == "completed":
                if row["result_artifact_id"] != result_artifact_id:
                    raise SignalProducerConflict("signal job result identity changed")
                return self._public_row(row)
            if row["status"] != "running":
                raise SignalProducerConflict("signal job is not running")
            now = _now()
            execute(
                connection,
                """UPDATE signal_producer_jobs SET status = 'completed', result_artifact_id = :artifact_id,
                          error_code = NULL, error_detail = NULL, finished_at = :now, updated_at = :now
                   WHERE job_id = :job_id""",
                {"job_id": job_id, "artifact_id": result_artifact_id, "now": now},
            )
        return self.get(job_id)

    def fail(self, job_id: str, error_code: str, error_detail: str) -> dict[str, object]:
        if _ERROR_CODE.fullmatch(error_code) is None:
            raise ValueError("error_code has invalid format")
        detail = str(error_detail).strip()[:500] or "signal execution failed"
        with self._transaction() as connection:
            row = fetch_one(
                connection,
                "SELECT status FROM signal_producer_jobs WHERE job_id = :job_id FOR UPDATE",
                {"job_id": job_id},
            )
            if row is None:
                raise SignalProducerNotFound("signal producer job not found")
            if row["status"] not in {"running", "queued"}:
                raise SignalProducerConflict("signal job is already terminal")
            now = _now()
            execute(
                connection,
                """UPDATE signal_producer_jobs SET status = 'failed', error_code = :error_code,
                          error_detail = :error_detail, finished_at = :now, updated_at = :now
                   WHERE job_id = :job_id""",
                {"job_id": job_id, "error_code": error_code, "error_detail": detail, "now": now},
            )
        return self.get(job_id)

    @staticmethod
    def _public_row(row: dict[str, Any]) -> dict[str, object]:
        value = dict(row)
        input_document = value.pop("input_json", {})
        universe = input_document.get("universe", {}) if isinstance(input_document, dict) else {}
        bars = input_document.get("bars", []) if isinstance(input_document, dict) else []
        value.pop("request_hash", None)
        value["input"] = {
            "schema_version": input_document.get("schema_version") if isinstance(input_document, dict) else None,
            "profile": input_document.get("profile") if isinstance(input_document, dict) else None,
            "runtime_lock": input_document.get("runtime_lock") if isinstance(input_document, dict) else None,
            "symbol_count": len(universe.get("symbols", [])) if isinstance(universe, dict) else 0,
            "bar_count": len(bars) if isinstance(bars, list) else 0,
        }
        return value

    @staticmethod
    def _internal_row(row: dict[str, Any]) -> dict[str, object]:
        value = dict(row)
        value.pop("request_hash", None)
        value["input"] = value.pop("input_json")
        return value


class SignalProducerCoordinator:
    """Trusted tier: normalize sandbox output and persist the immutable Artifact."""

    def __init__(self, jobs: SignalJobStore, research: ResearchStore, executor: SandboxExecutor) -> None:
        self.jobs = jobs
        self.research = research
        self.executor = executor

    def run_next(self) -> dict[str, object] | None:
        job = self.jobs.claim_next()
        if job is None:
            return None
        job_id = str(job["job_id"])
        try:
            document = self._produce(job)
            fingerprint = signal_snapshot_content_sha256(document)
            artifact = self.research.find_artifact_by_content(job["task_id"], "signal_snapshot", fingerprint)
            if artifact is None:
                artifact = self.research.create_artifact(
                    {
                        "task_id": job["task_id"],
                        "experiment_id": job.get("experiment_id"),
                        "kind": "signal_snapshot",
                        "content": document,
                        "lineage": [
                            {"kind": "artifact", "id": job["strategy_version_artifact_id"]},
                            {"kind": "stock_pool_snapshot", "id": job["stock_pool_snapshot_id"]},
                            {"kind": "signal_producer_job", "id": job_id},
                        ],
                        "trace_id": job["trace_id"],
                        "idempotency_key": f"signal-producer-{fingerprint}",
                    }
                )
            if artifact["status"] == "draft":
                artifact = self.research.transition(
                    "artifact", artifact["artifact_id"], "validated", f"signal-producer-validate-{fingerprint[:24]}"
                )
            return self.jobs.complete(job_id, str(artifact["artifact_id"]))
        except Exception as error:
            code = getattr(error, "error_code", "signal_execution_failed")
            if not isinstance(code, str) or _ERROR_CODE.fullmatch(code) is None:
                code = "signal_execution_failed"
            detail = str(error) if hasattr(error, "error_code") else "signal production failed"
            return self.jobs.fail(job_id, code, detail)

    def _produce(self, job: dict[str, object]) -> dict[str, object]:
        input_document = job.get("input")
        if not isinstance(input_document, dict):
            raise ValueError("signal job input is unavailable")
        if input_document.get("profile") != EXECUTION_PROFILE:
            raise SignalExecutionFailure(
                "execution_profile_unsupported", "execution profile is unsupported"
            )
        execution = input_document.get("execution")
        timeout = float(execution.get("max_runtime_seconds", 10.0)) if isinstance(execution, dict) else 10.0
        sandbox_payload = {
            "schema_version": "byq-signal-sandbox-request-v1",
            "profile": input_document["profile"],
            "runtime_lock": input_document["runtime_lock"],
            "strategy": input_document["strategy"],
            "bars": input_document["bars"],
            "parameters": input_document["parameters"],
        }
        response = self.executor.execute(sandbox_payload, timeout_seconds=timeout)
        if response.get("schema_version") != "byq-signal-sandbox-response-v1":
            raise ValueError("sandbox returned an unsupported response")
        raw_signals = response.get("signals")
        if not isinstance(raw_signals, list):
            raise ValueError("sandbox signals must be a list")
        quantity = input_document.get("order_quantity")
        signals: list[dict[str, object]] = []
        for row in raw_signals:
            if not isinstance(row, dict):
                raise ValueError("sandbox signal row must be an object")
            direction = row.get("signal")
            if direction == 0:
                continue
            signals.append(
                {
                    "symbol": row.get("symbol"),
                    "trade_date": row.get("trade_date"),
                    "side": "buy" if direction == 1 else "sell" if direction == -1 else direction,
                    "quantity": quantity,
                }
            )
        strategy = input_document["strategy"]
        return normalize_signal_snapshot(
            {
                "universe": input_document["universe"],
                "bars": input_document["bars"],
                "signals": signals,
                "execution": input_document["execution"],
                "corporate_actions": [],
                "source": {"producer": EXECUTION_PROFILE},
            },
            strategy_version_artifact_id=strategy["strategy_version_artifact_id"],
            strategy_version_id=strategy["strategy_version_id"],
        )


class CallableSandboxExecutor:
    """Small test seam; production uses the HTTP-only sandbox client."""

    def __init__(self, call: Callable[[dict[str, object], float], dict[str, object]]) -> None:
        self.call = call

    def execute(self, payload: dict[str, object], *, timeout_seconds: float) -> dict[str, object]:
        return self.call(payload, timeout_seconds)
