"""Durable completed-candidate parameter-search Jobs.

An OptimizationJob ranks already completed BacktestJob results using explicit,
caller-supplied parameter records. It never invokes a strategy or reruns a
backtest, and it is independent of Agent session/runtime state.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Any

from .backtest import ObjectIntegrityError, build_backtest_analysis, load_result
from .db import PgStoreMixin, execute, fetch_one
from .research import ResearchNotFound, _identifier, _idempotency_key, _text, _trace_id


MAX_ATTEMPTS = 3
CLAIM_LEASE_SECONDS = 5 * 60
MAX_CANDIDATES = 20
MAX_REQUEST_BYTES = 64 * 1024
MAX_PARAMETER_BYTES = 4096
_JOB_ID = re.compile(r"^optimizationjob_[0-9a-f]{32}$")
_BACKTEST_ID = re.compile(r"^backtest_[0-9a-f]{32}$")
_OBJECTIVE_DIRECTIONS = {
    "total_return": "maximize",
    "sharpe_ratio": "maximize",
    "max_drawdown": "minimize",
}
_PUBLIC_STATUS = {
    "queued": "QUEUED",
    "running": "RUNNING",
    "completed": "SUCCEEDED",
    "failed": "FAILED",
    "cancelled": "CANCELLED",
}


class OptimizationValidationError(ValueError):
    """Closed request/result validation failure safe to expose through Product API."""

    def __init__(self, message: str, *, field: str = "request", code: str = "invalid_input") -> None:
        super().__init__(message)
        self.field = field
        self.code = code

    def public_problem(self) -> dict[str, object]:
        return {
            "schema_version": "optimization-validation-problem.v1",
            "field": self.field,
            "code": self.code,
            "repair_limit": 1,
            "next_action": "correct_once",
        }


class OptimizationConflict(RuntimeError):
    """The optimization Job idempotency or current state conflicts."""


class OptimizationLeaseLost(RuntimeError):
    """The claimed OptimizationJob attempt can no longer commit a result."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise OptimizationValidationError("optimization request must be valid JSON") from error


def _bounded_json(value: object, *, field: str, depth: int = 0) -> object:
    if depth > 4:
        raise OptimizationValidationError(f"{field} exceeds the supported nesting depth", field=field, code="out_of_range")
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str) and len(value) > 256:
            raise OptimizationValidationError(f"{field} text is too long", field=field, code="out_of_range")
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if abs(value) > 10**12:
            raise OptimizationValidationError(f"{field} number is out of range", field=field, code="out_of_range")
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or abs(value) > 10**12:
            raise OptimizationValidationError(f"{field} number must be finite and in range", field=field, code="out_of_range")
        return value
    if isinstance(value, list):
        if len(value) > 64:
            raise OptimizationValidationError(f"{field} has too many values", field=field, code="out_of_range")
        return [_bounded_json(item, field=field, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 32 or any(not isinstance(key, str) or not key or len(key) > 64 for key in value):
            raise OptimizationValidationError(f"{field} has invalid fields", field=field, code="out_of_range")
        return {key: _bounded_json(item, field=field, depth=depth + 1) for key, item in sorted(value.items())}
    raise OptimizationValidationError(f"{field} must contain JSON values only", field=field, code="invalid_input")


def normalize_optimization_request(payload: object) -> dict[str, object]:
    """Normalize the closed request for a completed-candidate parameter search."""
    allowed = {"task_id", "experiment_id", "trace_id", "idempotency_key", "objective", "candidates"}
    if not isinstance(payload, dict):
        raise OptimizationValidationError("optimization request must be an object", field="request", code="object_required")
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise OptimizationValidationError("optimization request has unknown fields", field="request", code="unknown_fields")
    task_id = _identifier(payload.get("task_id"), field="task_id")
    experiment_id = _identifier(payload["experiment_id"], field="experiment_id") if payload.get("experiment_id") is not None else None
    trace_id = _trace_id(payload.get("trace_id"))
    idempotency_key = _idempotency_key(payload.get("idempotency_key"))
    objective = _text(payload.get("objective"), field="objective", max_length=32)
    if objective not in _OBJECTIVE_DIRECTIONS:
        raise OptimizationValidationError("objective is unsupported", field="objective", code="unsupported_value")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not 2 <= len(candidates) <= MAX_CANDIDATES:
        raise OptimizationValidationError("candidates must contain 2 to 20 completed backtest references", field="candidates", code="out_of_range")
    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    seen_parameters: set[str] = set()
    parameter_keys: set[str] | None = None
    for index, candidate in enumerate(candidates):
        field = f"candidates[{index}]"
        if not isinstance(candidate, dict) or set(candidate) != {"backtest_job_id", "parameters"}:
            raise OptimizationValidationError(f"{field} must contain backtest_job_id and parameters", field="candidates", code="object_required")
        job_id = _text(candidate.get("backtest_job_id"), field=f"{field}.backtest_job_id", max_length=64)
        if _BACKTEST_ID.fullmatch(job_id) is None:
            raise OptimizationValidationError(f"{field}.backtest_job_id is invalid", field="candidates", code="invalid_input")
        if job_id in seen:
            raise OptimizationValidationError("candidate backtest IDs must be unique", field="candidates", code="invalid_input")
        seen.add(job_id)
        params = candidate.get("parameters")
        if not isinstance(params, dict) or not params:
            raise OptimizationValidationError(f"{field}.parameters must be a non-empty JSON object", field="candidates", code="object_required")
        frozen_params = _bounded_json(params, field=f"{field}.parameters")
        assert isinstance(frozen_params, dict)
        if parameter_keys is None:
            parameter_keys = set(frozen_params)
        elif set(frozen_params) != parameter_keys:
            raise OptimizationValidationError("all candidates must use the same parameter fields", field="candidates", code="invalid_input")
        if len(_canonical(frozen_params).encode("utf-8")) > MAX_PARAMETER_BYTES:
            raise OptimizationValidationError(f"{field}.parameters exceeds the size limit", field="candidates", code="out_of_range")
        parameter_identity = _canonical(frozen_params)
        if parameter_identity in seen_parameters:
            raise OptimizationValidationError("candidate parameter sets must be unique", field="candidates", code="invalid_input")
        seen_parameters.add(parameter_identity)
        normalized.append({"backtest_job_id": job_id, "parameters": frozen_params})
    normalized.sort(key=lambda item: str(item["backtest_job_id"]))
    request = {
        "task_id": task_id,
        "experiment_id": experiment_id,
        "trace_id": trace_id,
        "idempotency_key": idempotency_key,
        "objective": objective,
        "candidates": normalized,
    }
    if len(_canonical(request).encode("utf-8")) > MAX_REQUEST_BYTES:
        raise OptimizationValidationError("optimization request exceeds the size limit", field="request", code="out_of_range")
    return request


def rank_completed_candidates(
    candidates: list[dict[str, object]], *, objective: str,
) -> dict[str, object]:
    """Rank already computed finite metrics; ties resolve by stable BacktestJob ID."""
    if objective not in _OBJECTIVE_DIRECTIONS:
        raise OptimizationValidationError("objective is unsupported", field="objective", code="unsupported_value")
    scored: list[dict[str, object]] = []
    seen: set[str] = set()
    for candidate in candidates:
        backtest_id = candidate.get("backtest_job_id")
        metric = candidate.get("metric_value")
        if not isinstance(backtest_id, str) or _BACKTEST_ID.fullmatch(backtest_id) is None or backtest_id in seen:
            raise OptimizationValidationError("candidate identity is invalid", field="candidates", code="invalid_input")
        seen.add(backtest_id)
        if isinstance(metric, bool) or not isinstance(metric, (int, float)) or not math.isfinite(float(metric)):
            raise OptimizationValidationError("candidate metric is missing or invalid", field="metric", code="invalid_metric")
        value = float(metric)
        if objective == "total_return" and value < -1:
            raise OptimizationValidationError("candidate total_return is outside valid range", field="metric", code="invalid_metric")
        if objective == "max_drawdown" and not 0 <= value <= 1:
            raise OptimizationValidationError("candidate max_drawdown is outside valid range", field="metric", code="invalid_metric")
        params = candidate.get("parameters")
        if not isinstance(params, dict):
            raise OptimizationValidationError("candidate parameters are missing", field="candidates", code="invalid_input")
        scored.append({"backtest_job_id": backtest_id, "parameters": params, "metric_value": value})
    if not 2 <= len(scored) <= MAX_CANDIDATES:
        raise OptimizationValidationError("candidate count must be between 2 and 20", field="candidates", code="out_of_range")
    descending = _OBJECTIVE_DIRECTIONS[objective] == "maximize"
    ranked = sorted(scored, key=lambda item: ((-float(item["metric_value"])) if descending else float(item["metric_value"]), str(item["backtest_job_id"])))
    for rank, candidate in enumerate(ranked, 1):
        candidate["rank"] = rank
    return {
        "schema_version": "optimization-comparison.v1",
        "evaluation": "completed_backtest_parameter_search",
        "reran_backtests": False,
        "objective": {"name": objective, "direction": _OBJECTIVE_DIRECTIONS[objective]},
        "candidate_count": len(ranked),
        "winner_backtest_job_id": ranked[0]["backtest_job_id"],
        "ranking": ranked,
    }


class OptimizationJobStore(PgStoreMixin):
    """Workspace-scoped durable queue for bounded completed-candidate comparisons."""

    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS optimization_jobs (
            job_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES research_tasks(task_id),
            workspace_id TEXT NOT NULL,
            owner_principal TEXT NOT NULL,
            experiment_id TEXT,
            trace_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
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
        "CREATE INDEX IF NOT EXISTS optimization_jobs_poll ON optimization_jobs(status, created_at, job_id)",
        "CREATE INDEX IF NOT EXISTS optimization_jobs_stale_claim ON optimization_jobs(status, claimed_at, job_id)",
    ]

    def create(
        self, payload: object, *, trusted_owner: str, trusted_workspace: str,
        _connection=None,
    ) -> dict[str, object]:
        request = normalize_optimization_request(payload)
        owner = _text(trusted_owner, field="trusted_owner", max_length=128)
        workspace = _text(trusted_workspace, field="trusted_workspace", max_length=128)
        request_hash = hashlib.sha256(_canonical(request).encode("utf-8")).hexdigest()
        now = _now()
        manager = nullcontext(_connection) if _connection is not None else self._transaction()
        with manager as connection:
            execute(connection, "SET LOCAL lock_timeout = '2s'")
            task = fetch_one(connection, """SELECT task_id,owner_principal,workspace_id FROM research_tasks
                WHERE task_id=:task FOR SHARE""", {"task": request["task_id"]})
            if task is None or task["owner_principal"] != owner or task["workspace_id"] != workspace:
                raise ResearchNotFound("research task not found")
            if request["experiment_id"] is not None:
                experiment = fetch_one(connection, """SELECT experiment_id FROM experiments
                    WHERE experiment_id=:experiment AND task_id=:task AND owner_principal=:owner
                      AND workspace_id=:workspace""",
                    {"experiment": request["experiment_id"], "task": request["task_id"],
                     "owner": owner, "workspace": workspace})
                if experiment is None:
                    raise ResearchNotFound("experiment does not belong to research task")
            execute(connection, "SELECT pg_advisory_xact_lock(hashtext(:scope))",
                    {"scope": f"optimization-job|{workspace}|{request['task_id']}|{request['idempotency_key']}"})
            existing = fetch_one(connection, """SELECT * FROM optimization_jobs
                WHERE task_id=:task AND idempotency_key=:key FOR UPDATE""",
                {"task": request["task_id"], "key": request["idempotency_key"]})
            if existing is not None:
                if (existing["owner_principal"] != owner or existing["workspace_id"] != workspace):
                    raise ResearchNotFound("optimization job not found")
                if existing["request_hash"] != request_hash:
                    raise OptimizationConflict("optimization idempotency key was reused")
                return self._public_row(existing)

            self._lock_candidate_rows(connection, request)
            facts = self._candidate_facts(connection, request, owner=owner, workspace=workspace)
            if len(facts) != len(request["candidates"]):
                raise ResearchNotFound("completed backtest candidate not found")
            self._validate_candidate_facts(facts, request["candidates"])
            job_id = f"optimizationjob_{uuid.uuid4().hex}"
            execute(connection, """INSERT INTO optimization_jobs
                (job_id,task_id,workspace_id,owner_principal,experiment_id,trace_id,
                 idempotency_key,request_hash,request_json,status,attempts,max_attempts,created_at,updated_at)
                VALUES (:job,:task,:workspace,:owner,:experiment,:trace,:key,:hash,:request,
                        'queued',0,:max_attempts,:now,:now)""",
                {"job": job_id, "task": request["task_id"], "workspace": workspace,
                 "owner": owner, "experiment": request["experiment_id"], "trace": request["trace_id"],
                 "key": request["idempotency_key"], "hash": request_hash, "request": request,
                 "max_attempts": MAX_ATTEMPTS, "now": now})
            row = fetch_one(connection, "SELECT * FROM optimization_jobs WHERE job_id=:job", {"job": job_id})
            if row is None:
                raise RuntimeError("optimization job insert did not return its row")
            return self._public_row(row)

    def get(
        self, *, trusted_owner: str, trusted_workspace: str,
        job_id: str | None = None, task_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, object] | None:
        owner = _text(trusted_owner, field="trusted_owner", max_length=128)
        workspace = _text(trusted_workspace, field="trusted_workspace", max_length=128)
        if job_id is not None:
            if task_id is not None or idempotency_key is not None:
                raise ValueError("query by job_id or task_id plus idempotency_key")
            identity = _text(job_id, field="job_id", max_length=64)
            if _JOB_ID.fullmatch(identity) is None:
                raise ValueError("job_id is invalid")
            row = self._fetch_one("""SELECT * FROM optimization_jobs WHERE job_id=:job
                AND owner_principal=:owner AND workspace_id=:workspace""",
                {"job": identity, "owner": owner, "workspace": workspace})
        else:
            if task_id is None or idempotency_key is None:
                raise ValueError("task_id and idempotency_key are both required")
            task = _identifier(task_id, field="task_id")
            key = _idempotency_key(idempotency_key)
            row = self._fetch_one("""SELECT * FROM optimization_jobs WHERE task_id=:task
                AND idempotency_key=:key AND owner_principal=:owner AND workspace_id=:workspace""",
                {"task": task, "key": key, "owner": owner, "workspace": workspace})
        return None if row is None else self._public_row(row)

    def cancel(self, job_id: str, *, trusted_owner: str, trusted_workspace: str) -> dict[str, object] | None:
        identity = _text(job_id, field="job_id", max_length=64)
        if _JOB_ID.fullmatch(identity) is None:
            raise ValueError("job_id is invalid")
        owner = _text(trusted_owner, field="trusted_owner", max_length=128)
        workspace = _text(trusted_workspace, field="trusted_workspace", max_length=128)
        now = _now()
        with self._transaction() as connection:
            row = fetch_one(connection, """UPDATE optimization_jobs SET status='cancelled',
                error_code='cancelled',error_message='cancelled by owner',worker_id=NULL,
                claimed_at=NULL,finished_at=:now,updated_at=:now
                WHERE job_id=:job AND owner_principal=:owner AND workspace_id=:workspace
                  AND status IN ('queued','running') RETURNING *""",
                {"job": identity, "owner": owner, "workspace": workspace, "now": now})
            if row is None:
                row = fetch_one(connection, """SELECT * FROM optimization_jobs WHERE job_id=:job
                    AND owner_principal=:owner AND workspace_id=:workspace""",
                    {"job": identity, "owner": owner, "workspace": workspace})
            return None if row is None else self._public_row(row)

    def claim_next(self, worker_id: str = "optimization-worker") -> dict[str, object] | None:
        worker = _text(worker_id, field="worker_id", max_length=128)
        now = _now()
        stale_before = now - timedelta(seconds=CLAIM_LEASE_SECONDS)
        with self._transaction() as connection:
            exhausted = fetch_one(connection, """SELECT * FROM optimization_jobs
                WHERE status='running' AND attempts>=max_attempts AND claimed_at<=:stale
                ORDER BY claimed_at,job_id LIMIT 1 FOR UPDATE SKIP LOCKED""", {"stale": stale_before})
            if exhausted is not None:
                execute(connection, """UPDATE optimization_jobs SET status='failed',
                    error_code='worker_attempts_exhausted',
                    error_message='optimization worker attempts were exhausted',worker_id=NULL,
                    claimed_at=NULL,finished_at=:now,updated_at=:now
                    WHERE job_id=:job AND status='running'""",
                    {"job": exhausted["job_id"], "now": now})
            row = fetch_one(connection, """SELECT * FROM optimization_jobs
                WHERE (status='queued' AND attempts<max_attempts)
                   OR (status='running' AND attempts<max_attempts AND claimed_at<=:stale)
                ORDER BY created_at,job_id LIMIT 1 FOR UPDATE SKIP LOCKED""", {"stale": stale_before})
            if row is None:
                return None
            attempt = int(row["attempts"]) + 1
            execute(connection, """UPDATE optimization_jobs SET status='running',attempts=:attempt,
                worker_id=:worker,claimed_at=:now,started_at=COALESCE(started_at,:now),
                updated_at=:now,error_code=NULL,error_message=NULL WHERE job_id=:job""",
                {"attempt": attempt, "worker": worker, "now": now, "job": row["job_id"]})
            row.update({"status": "running", "attempts": attempt, "worker_id": worker,
                        "claimed_at": now.isoformat(), "started_at": row.get("started_at") or now.isoformat(),
                        "updated_at": now.isoformat(), "error_code": None, "error_message": None})
            return self._internal_row(row)

    @staticmethod
    def _lock_candidate_rows(connection, request: dict[str, object]) -> None:
        candidates = request.get("candidates")
        if not isinstance(candidates, list):
            raise RuntimeError("optimization job candidates are invalid")
        identities = sorted(str(item["backtest_job_id"]) for item in candidates)
        locked = execute(connection, """SELECT job_id FROM backtest_jobs
            WHERE job_id IN (SELECT jsonb_array_elements_text(CAST(:ids AS jsonb)))
            ORDER BY job_id FOR SHARE""", {"ids": identities})
        if len(locked) != len(identities):
            raise ResearchNotFound("completed backtest candidate not found")

    def _candidate_facts(
        self, connection, request: dict[str, object], *, owner: str, workspace: str,
    ) -> list[dict[str, object]]:
        candidates = request.get("candidates")
        assert isinstance(candidates, list)
        identities = [str(item["backtest_job_id"]) for item in candidates]
        return execute(connection, """WITH selected AS (
                SELECT * FROM backtest_jobs
                 WHERE job_id IN (SELECT jsonb_array_elements_text(CAST(:ids AS jsonb)))
            ), baseline AS (
                SELECT selected.*, strategy.content AS strategy_content, strategy.kind AS strategy_kind
                  FROM selected JOIN artifacts strategy
                    ON strategy.artifact_id=selected.strategy_version_artifact_id
                 ORDER BY selected.job_id LIMIT 1
            )
            SELECT candidate.job_id,candidate.task_id,candidate.workspace_id,candidate.owner_principal,
                   candidate.status,candidate.input_manifest_id,candidate.result_reference_json,
                   candidate.result_artifact_id,candidate.summary_json,candidate.strategy_version_artifact_id,
                   candidate.input_manifest_json->'universe' AS universe,
                   candidate.input_manifest_json->'execution' AS execution,
                   candidate.input_manifest_json->'environment' AS environment,
                   strategy.content->'snapshot'->'parameters' AS strategy_parameters,
                   (strategy.kind='strategy_version' AND strategy.status='validated'
                     AND strategy.task_id=candidate.task_id AND strategy.owner_principal=candidate.owner_principal
                     AND strategy.workspace_id=candidate.workspace_id) AS valid_strategy_artifact,
                   (strategy.kind=baseline.strategy_kind
                     AND strategy.content->>'strategy_id'=baseline.strategy_content->>'strategy_id'
                     AND strategy.content->>'source_fingerprint'=baseline.strategy_content->>'source_fingerprint'
                     AND ((strategy.content->'snapshot') - 'parameters')=((baseline.strategy_content->'snapshot') - 'parameters')) AS same_strategy_template,
                   (candidate.input_manifest_json->'universe' IS NOT DISTINCT FROM baseline.input_manifest_json->'universe') AS same_universe,
                   (candidate.input_manifest_json->'bars' IS NOT DISTINCT FROM baseline.input_manifest_json->'bars') AS same_bars,
                   (candidate.input_manifest_json->'corporate_actions' IS NOT DISTINCT FROM baseline.input_manifest_json->'corporate_actions') AS same_corporate_actions,
                   (candidate.input_manifest_json->'benchmark' IS NOT DISTINCT FROM baseline.input_manifest_json->'benchmark') AS same_benchmark,
                   (candidate.input_manifest_json->'execution' IS NOT DISTINCT FROM baseline.input_manifest_json->'execution') AS same_execution,
                   (candidate.input_manifest_json->'environment' IS NOT DISTINCT FROM baseline.input_manifest_json->'environment') AS same_environment,
                   EXISTS (SELECT 1 FROM artifacts result
                       WHERE result.artifact_id=candidate.result_artifact_id
                         AND result.task_id=candidate.task_id AND result.owner_principal=candidate.owner_principal
                         AND result.workspace_id=candidate.workspace_id AND result.kind='backtest_result'
                         AND result.status='validated' AND result.content->>'job_id'=candidate.job_id
                         AND result.content->>'input_manifest_id'=candidate.input_manifest_id
                         AND result.content->'result_reference'=candidate.result_reference_json) AS valid_result_artifact
              FROM selected candidate CROSS JOIN baseline
              LEFT JOIN artifacts strategy ON strategy.artifact_id=candidate.strategy_version_artifact_id
             WHERE candidate.task_id=:task AND candidate.owner_principal=:owner
               AND candidate.workspace_id=:workspace
             ORDER BY candidate.job_id""",
            {"ids": identities, "task": request["task_id"], "owner": owner, "workspace": workspace})

    @staticmethod
    def _validate_candidate_facts(
        facts: list[dict[str, object]], candidates: list[object],
    ) -> None:
        if any(row.get("status") != "completed" for row in facts):
            raise OptimizationConflict("every candidate backtest must be completed")
        if any(row.get("valid_strategy_artifact") is not True for row in facts):
            raise OptimizationConflict("every candidate must reference a validated strategy version")
        if any(row.get("same_strategy_template") is not True for row in facts):
            raise OptimizationConflict("candidate backtests must use the same strategy definition")
        parameters_by_id = {
            str(item["backtest_job_id"]): item["parameters"]
            for item in candidates if isinstance(item, dict)
        }
        if any(
            _canonical(row.get("strategy_parameters")) != _canonical(parameters_by_id.get(str(row.get("job_id"))))
            for row in facts
        ):
            raise OptimizationConflict("candidate parameters do not match their validated strategy versions")
        if any(row.get("valid_result_artifact") is not True for row in facts):
            raise OptimizationConflict("every candidate must have a validated backtest result")
        comparable_fields = (
            "same_universe", "same_bars", "same_corporate_actions", "same_benchmark",
            "same_execution", "same_environment",
        )
        if any(row.get(field) is not True for row in facts for field in comparable_fields):
            raise OptimizationConflict("candidate backtests do not share the same frozen inputs")
        if any(not isinstance(row.get("result_reference_json"), dict) for row in facts):
            raise OptimizationConflict("every candidate must have an immutable result")
        if any(not isinstance(row.get("universe"), dict) or not isinstance(row.get("execution"), dict) for row in facts):
            raise OptimizationConflict("candidate frozen inputs are unavailable")

    def candidate_facts(self, claim: dict[str, object]) -> list[dict[str, object]]:
        request = claim.get("request_json")
        if not isinstance(request, dict):
            raise RuntimeError("optimization job input is invalid")
        with self._transaction() as connection:
            facts = self._candidate_facts(connection, request,
                owner=str(claim["owner_principal"]), workspace=str(claim["workspace_id"]))
        if len(facts) != len(request.get("candidates", [])):
            raise ResearchNotFound("completed backtest candidate not found")
        self._validate_candidate_facts(facts, request["candidates"])
        return facts

    def validate_locked_candidates(self, connection, claim: dict[str, object]) -> None:
        """Hold source rows through the result commit so delete cannot break lineage."""
        request = claim.get("request_json")
        if not isinstance(request, dict):
            raise RuntimeError("optimization job input is invalid")
        self._lock_candidate_rows(connection, request)
        facts = self._candidate_facts(connection, request,
            owner=str(claim["owner_principal"]), workspace=str(claim["workspace_id"]))
        if len(facts) != len(request["candidates"]):
            raise ResearchNotFound("completed backtest candidate not found")
        self._validate_candidate_facts(facts, request["candidates"])

    def require_execution_claim(self, connection, job_id: str, attempt: int) -> None:
        live = fetch_one(connection, """SELECT job_id FROM optimization_jobs
            WHERE job_id=:job AND status='running' AND attempts=:attempt
              AND claimed_at + make_interval(secs => CAST(:lease_seconds AS double precision)) > clock_timestamp()
            FOR UPDATE""", {"job": job_id, "attempt": attempt, "lease_seconds": CLAIM_LEASE_SECONDS})
        if live is None:
            raise OptimizationLeaseLost("optimization Job attempt has expired")

    def complete(self, job_id: str, attempt: int, result_artifact_id: str, *, _connection=None) -> bool:
        identity = _text(job_id, field="job_id", max_length=64)
        if _JOB_ID.fullmatch(identity) is None:
            raise ValueError("job_id is invalid")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= MAX_ATTEMPTS:
            raise ValueError("attempt is invalid")
        artifact_id = _identifier(result_artifact_id, field="result_artifact_id")
        now = _now()
        with (self._transaction() if _connection is None else nullcontext(_connection)) as connection:
            row = fetch_one(connection, """UPDATE optimization_jobs AS job SET status='completed',
                    result_artifact_id=:artifact,error_code=NULL,error_message=NULL,worker_id=NULL,
                    claimed_at=NULL,finished_at=:now,updated_at=:now
                WHERE job.job_id=:job AND job.status='running' AND job.attempts=:attempt
                  AND job.claimed_at + make_interval(secs => CAST(:lease_seconds AS double precision)) > clock_timestamp()
                  AND EXISTS (SELECT 1 FROM artifacts result
                      WHERE result.artifact_id=:artifact AND result.task_id=job.task_id
                        AND result.owner_principal=job.owner_principal AND result.workspace_id=job.workspace_id
                        AND result.kind='optimization_comparison' AND result.status='validated'
                        AND result.idempotency_key='optimization-result-' || job.job_id
                        AND result.trace_id=job.trace_id
                        AND result.content->>'optimization_job_id'=job.job_id)
                RETURNING job.job_id""", {"artifact": artifact_id, "now": now, "job": identity,
                    "attempt": attempt, "lease_seconds": CLAIM_LEASE_SECONDS})
            return row is not None

    def fail(self, job_id: str, attempt: int, error_code: str, error_message: str, *, retryable: bool) -> bool:
        if _JOB_ID.fullmatch(str(job_id)) is None:
            raise ValueError("job_id is invalid")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= MAX_ATTEMPTS:
            raise ValueError("attempt is invalid")
        if not isinstance(retryable, bool):
            raise ValueError("retryable must be boolean")
        code = _text(error_code, field="error_code", max_length=64)
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) is None:
            raise ValueError("error_code is invalid")
        message = _text(error_message, field="error_message", max_length=500)
        now = _now()
        with self._transaction() as connection:
            row = fetch_one(connection, """UPDATE optimization_jobs SET
                    status=CASE WHEN :retryable AND attempts<max_attempts THEN 'queued' ELSE 'failed' END,
                    error_code=:code,error_message=:message,worker_id=NULL,claimed_at=NULL,
                    finished_at=CASE WHEN :retryable AND attempts<max_attempts THEN NULL ELSE :now END,
                    updated_at=:now
                WHERE job_id=:job AND status='running' AND attempts=:attempt
                  AND claimed_at + make_interval(secs => CAST(:lease_seconds AS double precision)) > clock_timestamp()
                RETURNING job_id""", {"retryable": retryable, "code": code, "message": message,
                    "now": now, "job": job_id, "attempt": attempt, "lease_seconds": CLAIM_LEASE_SECONDS})
            return row is not None

    @staticmethod
    def _public_row(row: dict[str, Any]) -> dict[str, object]:
        status = row.get("status")
        if status not in _PUBLIC_STATUS:
            raise RuntimeError("optimization job has an unknown status")
        request = row.get("request_json")
        if not isinstance(request, dict):
            raise RuntimeError("optimization job input is invalid")
        candidates = request.get("candidates")
        if not isinstance(candidates, list):
            raise RuntimeError("optimization job candidates are invalid")
        error = None if row.get("error_code") is None else {
            "code": row["error_code"], "message": row.get("error_message"),
        }
        return {
            "job_id": row["job_id"], "workspace_id": row["workspace_id"], "task_id": row["task_id"],
            "type": "OPTIMIZATION", "status": _PUBLIC_STATUS[str(status)],
            "objective": request["objective"], "candidate_count": len(candidates),
            "input_ref": f"optimization-request-sha256:{row['request_hash']}",
            "progress": 100 if status == "completed" else None,
            "result_artifact_id": row.get("result_artifact_id"), "result_ref": row.get("result_artifact_id"),
            "error": error, "error_code": row.get("error_code"), "error_message": row.get("error_message"),
            "created_at": row.get("created_at"), "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
        }

    @staticmethod
    def _internal_row(row: dict[str, Any]) -> dict[str, object]:
        request = row.get("request_json")
        if not isinstance(request, dict):
            raise RuntimeError("optimization job input is invalid")
        return {
            "job_id": row["job_id"], "task_id": row["task_id"], "workspace_id": row["workspace_id"],
            "owner_principal": row["owner_principal"], "request_json": request,
            "attempt": int(row["attempts"]),
        }


class OptimizationWorker:
    """Rank frozen metrics from completed BacktestJobs and commit one Artifact."""

    def __init__(self, jobs: OptimizationJobStore, research, objects, *, worker_id: str = "optimization-worker") -> None:
        self.jobs, self.research, self.objects = jobs, research, objects
        self.worker_id = _text(worker_id, field="worker_id", max_length=128)

    def run_once(self) -> bool:
        claim = self.jobs.claim_next(self.worker_id)
        if claim is None:
            return False
        job_id, attempt = str(claim["job_id"]), int(claim["attempt"])
        request = claim["request_json"]
        objective = str(request["objective"])
        try:
            facts = self.jobs.candidate_facts(claim)
            params_by_id = {
                str(candidate["backtest_job_id"]): candidate["parameters"]
                for candidate in request["candidates"]
            }
            scored: list[dict[str, object]] = []
            for fact in facts:
                backtest_id = str(fact["job_id"])
                reference = fact.get("result_reference_json")
                if not isinstance(reference, dict):
                    raise OptimizationValidationError("candidate result is unavailable", field="metric", code="invalid_metric")
                result = load_result(self.objects, reference)
                if result.get("job_id") != backtest_id or result.get("input_manifest_id") != fact.get("input_manifest_id"):
                    raise OptimizationValidationError("candidate result does not match its completed backtest", field="metric", code="invalid_metric")
                execution = fact.get("execution")
                execution = execution if isinstance(execution, dict) else None
                analysis = build_backtest_analysis(result, section="summary", execution=execution)
                summary = analysis.get("summary")
                if not isinstance(summary, dict):
                    raise OptimizationValidationError("candidate metric summary is unavailable", field="metric", code="invalid_metric")
                metric = summary.get(objective)
                if objective in {"total_return", "max_drawdown"}:
                    stored = fact.get("summary_json")
                    stored_metric = stored.get(objective) if isinstance(stored, dict) else None
                    if isinstance(metric, bool) or not isinstance(metric, (int, float)) or stored_metric != metric:
                        raise OptimizationValidationError("candidate metric is inconsistent with its completed record", field="metric", code="invalid_metric")
                scored.append({"backtest_job_id": backtest_id, "parameters": params_by_id[backtest_id], "metric_value": metric})
            comparison = rank_completed_candidates(scored, objective=objective)
            artifact_content = {
                **comparison,
                "optimization_job_id": job_id,
                "task_id": claim["task_id"],
                "candidates": [
                    {**item, "input_manifest_id": next(str(fact["input_manifest_id"]) for fact in facts if fact["job_id"] == item["backtest_job_id"]),
                     "strategy_version_artifact_id": next(str(fact["strategy_version_artifact_id"]) for fact in facts if fact["job_id"] == item["backtest_job_id"])}
                    for item in comparison["ranking"]
                ],
            }
            # Artifact creation, validation, and Job completion share one transaction.
            # A cancelled, expired, or superseded attempt cannot leave an Artifact behind.
            with self.jobs._transaction() as connection:
                self.jobs.require_execution_claim(connection, job_id, attempt)
                self.jobs.validate_locked_candidates(connection, claim)
                artifact = self.research.create_artifact({
                    "task_id": claim["task_id"], "experiment_id": request.get("experiment_id"),
                    "kind": "optimization_comparison", "content": artifact_content,
                    "lineage": [{"kind": "backtest_job", "id": str(candidate["backtest_job_id"])}
                                 for candidate in request["candidates"]],
                    "trace_id": request["trace_id"], "idempotency_key": f"optimization-result-{job_id}",
                }, trusted_owner=claim["owner_principal"], trusted_workspace=claim["workspace_id"], _connection=connection)
                if artifact.get("status") == "draft":
                    artifact = self.research.transition("artifact", artifact["artifact_id"], "validated",
                        f"optimization-result-validate-{job_id}", _connection=connection)
                if (artifact.get("task_id") != claim["task_id"]
                        or artifact.get("owner_principal") != claim["owner_principal"]
                        or artifact.get("workspace_id") != claim["workspace_id"]
                        or artifact.get("kind") != "optimization_comparison"
                        or artifact.get("status") != "validated"):
                    raise RuntimeError("optimization Artifact is invalid for this Job")
                if not self.jobs.complete(job_id, attempt, str(artifact["artifact_id"]), _connection=connection):
                    raise OptimizationLeaseLost("optimization Job attempt expired before completion")
        except ResearchNotFound:
            self.jobs.fail(job_id, attempt, "candidate_missing", "a completed backtest candidate is unavailable", retryable=False)
        except OptimizationValidationError as error:
            self.jobs.fail(job_id, attempt, error.code if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error.code) else "invalid_candidate", "completed backtest candidates could not be compared", retryable=False)
        except (ObjectIntegrityError, FileNotFoundError):
            self.jobs.fail(job_id, attempt, "candidate_result_unavailable", "a completed backtest result is unavailable", retryable=False)
        except OptimizationLeaseLost:
            # The transaction rolls back the Artifact; cancellation/reclaim owns the terminal state.
            pass
        except Exception:
            self.jobs.fail(job_id, attempt, "optimization_execution_failed", "completed-candidate comparison failed", retryable=True)
        return True
