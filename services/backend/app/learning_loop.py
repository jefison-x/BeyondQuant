"""BYQ-owned Phase 14 Quant Learning Loop contracts.

This module owns bounded learning runs, deterministic evaluation signals,
experiment comparison, and evidence promotion. DSH may propose generic
iteration or orchestration, but every business invariant is enforced here.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .research import ResearchNotFound, ResearchStore


MAX_JSON_BYTES = 32 * 1024
MAX_LINEAGE = 64
_ID_PATTERN = re.compile(
    r"^(?:learning_run|learning_iteration|evaluation_signal|lesson)_[0-9a-f]{32}$"
)
_TRACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_PRINCIPAL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")
_SECRET_KEY_FRAGMENTS = (
    "token",
    "password",
    "secret",
    "apikey",
    "accesskey",
    "privatekey",
    "credential",
    "authorization",
)

RUN_TRANSITIONS = {
    "active": {"active", "awaiting_review", "cancelled"},
    "awaiting_review": {"completed", "failed", "cancelled"},
    "completed": {"completed"},
    "failed": {"failed"},
    "cancelled": {"cancelled"},
}
LESSON_TRANSITIONS = {
    "proposed": {"proposed", "approved", "rejected"},
    "approved": {"approved", "superseded"},
    "rejected": {"rejected"},
    "superseded": {"superseded"},
}


class LearningError(RuntimeError):
    """Safe base class for Phase 14 learning-loop failures."""


class LearningNotFound(LearningError):
    pass


class LearningUnauthorized(LearningError):
    pass


class LearningForbidden(LearningError):
    pass


class LearningConflict(LearningError):
    pass


class LearningPersistenceError(LearningError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object, *, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _principal(value: object, *, field: str) -> str:
    normalized = _text(value, field=field, max_length=128)
    if _PRINCIPAL_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field} is not a valid BYQ principal")
    return normalized


def _trace(value: object, *, field: str = "trace_id") -> str:
    normalized = _text(value, field=field, max_length=64)
    if _TRACE_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field} is not a valid BYQ identifier")
    return normalized


def _idempotency(value: object) -> str:
    return _text(value, field="idempotency_key", max_length=128)


def _learning_id(value: object, *, field: str, prefix: str) -> str:
    normalized = _text(value, field=field, max_length=64)
    if normalized.startswith(f"{prefix}_") and re.fullmatch(
        rf"{prefix}_[0-9a-f]{{32}}", normalized
    ):
        return normalized
    raise ValueError(f"{field} is not a valid BYQ learning identifier")


def _reject_unknown(payload: dict[str, object], allowed: set[str]) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(unknown)}")


def _reject_secret_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            if any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS):
                raise ValueError("learning payload must not contain credential fields")
            _reject_secret_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_secret_keys(nested)


def _json_object(value: object, *, field: str) -> tuple[dict[str, object], str]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return _canonical_json(value, field=field)


def _canonical_json(value: object, *, field: str) -> tuple[object, str]:
    _reject_secret_keys(value)
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be JSON-serializable") from exc
    if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError(f"{field} exceeds {MAX_JSON_BYTES} bytes")
    return value, encoded


def _lineage(value: object) -> tuple[list[dict[str, str]], str]:
    if not isinstance(value, list) or len(value) > MAX_LINEAGE:
        raise ValueError(f"lineage must be a list of at most {MAX_LINEAGE} entries")
    result: list[dict[str, str]] = []
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"kind", "id"}:
            raise ValueError("lineage entries must contain exactly kind and id")
        result.append(
            {
                "kind": _text(entry["kind"], field="lineage.kind", max_length=64),
                "id": _text(entry["id"], field="lineage.id", max_length=128),
            }
        )
    _, encoded = _canonical_json(result, field="lineage")
    return result, encoded


def _hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _loads(value: str, *, field: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise LearningPersistenceError(f"stored {field} is invalid") from exc


class LearningLoopStore:
    """Durable BYQ store for bounded learning runs and promoted lessons."""

    def __init__(self, path: str | Path, research_store: ResearchStore) -> None:
        self.path = str(path)
        self.research_store = research_store
        self._lock = threading.RLock()
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = sqlite3.connect(self.path, timeout=10.0, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 10000")
            self._create_schema()
        except sqlite3.Error as exc:
            raise LearningPersistenceError("learning storage is unavailable") from exc

    @classmethod
    def from_env(cls, research_store: ResearchStore) -> "LearningLoopStore":
        return cls(os.getenv("BYQ_DOMAIN_DB_PATH", "/tmp/byq-domain.sqlite3"), research_store)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS learning_runs (
                    learning_run_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    owner_principal TEXT NOT NULL,
                    actor_principal TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    budget_json TEXT NOT NULL,
                    stopping_rules_json TEXT NOT NULL,
                    lineage_json TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS learning_runs_idempotency
                    ON learning_runs(owner_principal, idempotency_key);

                CREATE TABLE IF NOT EXISTS learning_iterations (
                    iteration_id TEXT PRIMARY KEY,
                    learning_run_id TEXT NOT NULL REFERENCES learning_runs(learning_run_id),
                    sequence INTEGER NOT NULL,
                    iteration_index INTEGER NOT NULL,
                    attempt INTEGER NOT NULL,
                    outcome TEXT NOT NULL,
                    feedback_json TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    result_refs_json TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS learning_iterations_idempotency
                    ON learning_iterations(learning_run_id, idempotency_key);
                CREATE UNIQUE INDEX IF NOT EXISTS learning_iterations_order
                    ON learning_iterations(learning_run_id, sequence);

                CREATE TABLE IF NOT EXISTS evaluation_signals (
                    signal_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    experiment_id TEXT,
                    source_artifact_id TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT,
                    lineage_json TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS evaluation_signals_idempotency
                    ON evaluation_signals(task_id, idempotency_key);

                CREATE TABLE IF NOT EXISTS lessons (
                    lesson_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    owner_principal TEXT NOT NULL,
                    actor_principal TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    validation_json TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS lessons_idempotency
                    ON lessons(task_id, idempotency_key);

                CREATE TABLE IF NOT EXISTS learning_history (
                    history_id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    reviewer_principal TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS learning_history_entity
                    ON learning_history(entity_type, entity_id, created_at, history_id);
                """
            )

    def start_run(
        self,
        payload: object,
        *,
        trusted_owner: str | None = None,
        trusted_actor: str | None = None,
    ) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("learning run request must be an object")
        _reject_unknown(payload, {"task_id", "budget", "stopping_rules", "lineage", "trace_id", "idempotency_key"})
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        actor = _principal(trusted_actor, field="actor_principal") if trusted_actor else owner
        if owner is None or actor is None:
            raise LearningUnauthorized("learning run requires trusted owner and actor")
        task_id = _text(payload.get("task_id"), field="task_id", max_length=64)
        task = self._owned_task(task_id, owner)
        budget, budget_json = self._budget(payload.get("budget"))
        stopping_rules, stopping_json = self._stopping_rules(payload.get("stopping_rules", {}))
        lineage, lineage_json = _lineage(payload.get("lineage", []))
        trace_id = _trace(payload.get("trace_id"), field="trace_id")
        key = _idempotency(payload.get("idempotency_key"))
        request = {
            "task_id": task_id,
            "owner_principal": owner,
            "actor_principal": actor,
            "budget": budget,
            "stopping_rules": stopping_rules,
            "lineage": lineage,
            "trace_id": trace_id,
            "idempotency_key": key,
        }
        request_hash = _hash(request)
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT * FROM learning_runs WHERE owner_principal = ? AND idempotency_key = ?",
                (owner, key),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise LearningConflict("learning run idempotency key was reused")
                return self._run_row(existing)
            now = _now()
            run_id = _new_id("learning_run")
            self._connection.execute(
                """INSERT INTO learning_runs
                (learning_run_id, task_id, owner_principal, actor_principal, trace_id,
                 status, budget_json, stopping_rules_json, lineage_json,
                 idempotency_key, request_hash, created_at, updated_at, version)
                VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, 1)""",
                (run_id, task_id, owner, actor, trace_id, budget_json, stopping_json, lineage_json, key, request_hash, now, now),
            )
            row = self._connection.execute("SELECT * FROM learning_runs WHERE learning_run_id = ?", (run_id,)).fetchone()
            assert row is not None
            return self._run_row(row)

    def get_run(self, run_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        run_id = _learning_id(run_id, field="learning_run_id", prefix="learning_run")
        with self._lock:
            row = self._connection.execute("SELECT * FROM learning_runs WHERE learning_run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise LearningNotFound("learning run not found")
        if trusted_owner and row["owner_principal"] != trusted_owner:
            raise LearningUnauthorized("learning run is not owned by this principal")
        return self._run_row(row)

    def record_iteration(
        self,
        payload: object,
        *,
        trusted_owner: str | None = None,
        trusted_actor: str | None = None,
    ) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("learning iteration request must be an object")
        _reject_unknown(
            payload,
            {"run_id", "iteration_index", "attempt", "outcome", "feedback", "source_refs", "result_refs", "trace_id", "idempotency_key"},
        )
        run_id = _learning_id(payload.get("run_id"), field="run_id", prefix="learning_run")
        with self._lock:
            run = self._connection.execute("SELECT * FROM learning_runs WHERE learning_run_id = ?", (run_id,)).fetchone()
        if run is None:
            raise LearningNotFound("learning run not found")
        self._check_run_access(run, trusted_owner=trusted_owner, trusted_actor=trusted_actor)
        if run["status"] != "active":
            raise LearningForbidden("learning run is not active")
        iteration_index = self._positive_int(payload.get("iteration_index"), "iteration_index")
        attempt = self._positive_int(payload.get("attempt"), "attempt")
        outcome = _text(payload.get("outcome"), field="outcome", max_length=32)
        if outcome not in {"produced", "no_change", "failed"}:
            raise ValueError("outcome must be produced, no_change, or failed")
        feedback, feedback_json = _json_object(payload.get("feedback", {}), field="feedback")
        source_refs, source_json = _lineage(payload.get("source_refs", []))
        result_refs, result_json = _lineage(payload.get("result_refs", []))
        trace_id = _trace(payload.get("trace_id"), field="trace_id")
        key = _idempotency(payload.get("idempotency_key"))
        request = {
            "run_id": run_id,
            "iteration_index": iteration_index,
            "attempt": attempt,
            "outcome": outcome,
            "feedback": feedback,
            "source_refs": source_refs,
            "result_refs": result_refs,
            "trace_id": trace_id,
            "idempotency_key": key,
        }
        request_hash = _hash(request)
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT * FROM learning_iterations WHERE learning_run_id = ? AND idempotency_key = ?",
                (run_id, key),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise LearningConflict("learning iteration idempotency key was reused")
                return {"iteration": self._iteration_row(existing), "run": self._run_row(run)}
            rows = self._connection.execute(
                "SELECT * FROM learning_iterations WHERE learning_run_id = ? ORDER BY sequence ASC",
                (run_id,),
            ).fetchall()
            budget = self._stored_budget(run["budget_json"])
            self._validate_iteration_sequence(rows, iteration_index, attempt, budget)
            now = _now()
            iteration_id = _new_id("learning_iteration")
            sequence = len(rows) + 1
            self._connection.execute(
                """INSERT INTO learning_iterations
                (iteration_id, learning_run_id, sequence, iteration_index, attempt,
                 outcome, feedback_json, source_refs_json, result_refs_json,
                 trace_id, idempotency_key, request_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (iteration_id, run_id, sequence, iteration_index, attempt, outcome, feedback_json, source_json, result_json, trace_id, key, request_hash, now),
            )
            inserted = self._connection.execute("SELECT * FROM learning_iterations WHERE iteration_id = ?", (iteration_id,)).fetchone()
            assert inserted is not None
            new_status = self._next_run_status(run, outcome, iteration_index, attempt, budget, feedback)
            if new_status != run["status"]:
                self._connection.execute(
                    "UPDATE learning_runs SET status = ?, updated_at = ?, version = version + 1 WHERE learning_run_id = ?",
                    (new_status, now, run_id),
                )
                run = self._connection.execute("SELECT * FROM learning_runs WHERE learning_run_id = ?", (run_id,)).fetchone()
                assert run is not None
            return {"iteration": self._iteration_row(inserted), "run": self._run_row(run)}

    def review_run(
        self,
        payload: object,
        *,
        trusted_owner: str | None = None,
        trusted_actor: str | None = None,
    ) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("learning run review must be an object")
        _reject_unknown(payload, {"run_id", "decision", "rationale"})
        run_id = _learning_id(payload.get("run_id"), field="run_id", prefix="learning_run")
        reviewer = _principal(trusted_actor, field="reviewer_principal") if trusted_actor else None
        if reviewer is None:
            raise LearningUnauthorized("learning run review requires a trusted reviewer")
        decision = _text(payload.get("decision"), field="decision", max_length=16)
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        rationale = _text(payload.get("rationale") or "", field="rationale", max_length=2000) if payload.get("rationale") else ""
        with self._lock, self._connection:
            run = self._connection.execute("SELECT * FROM learning_runs WHERE learning_run_id = ?", (run_id,)).fetchone()
            if run is None:
                raise LearningNotFound("learning run not found")
            if trusted_owner and run["owner_principal"] != trusted_owner:
                raise LearningUnauthorized("learning run is not owned by this principal")
            if reviewer == run["actor_principal"]:
                raise LearningForbidden("the initiating actor cannot review their own learning run")
            if run["status"] != "awaiting_review":
                raise LearningForbidden("learning run is not awaiting human review")
            target = "completed" if decision == "approved" else "failed"
            now = _now()
            self._connection.execute(
                "UPDATE learning_runs SET status = ?, updated_at = ?, version = version + 1 WHERE learning_run_id = ?",
                (target, now, run_id),
            )
            self._record_history("learning_run", run_id, "awaiting_review", target, reviewer, decision, rationale)
            updated = self._connection.execute("SELECT * FROM learning_runs WHERE learning_run_id = ?", (run_id,)).fetchone()
            assert updated is not None
            return self._run_row(updated)

    def list_iterations(self, run_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        run_id = _learning_id(run_id, field="run_id", prefix="learning_run")
        with self._lock:
            run = self._connection.execute("SELECT * FROM learning_runs WHERE learning_run_id = ?", (run_id,)).fetchone()
            if run is None:
                raise LearningNotFound("learning run not found")
            if trusted_owner and run["owner_principal"] != trusted_owner:
                raise LearningUnauthorized("learning run is not owned by this principal")
            rows = self._connection.execute(
                "SELECT * FROM learning_iterations WHERE learning_run_id = ? ORDER BY sequence ASC",
                (run_id,),
            ).fetchall()
        return {"run": self._run_row(run), "iterations": [self._iteration_row(row) for row in rows]}

    def create_signal(
        self,
        payload: object,
        *,
        trusted_owner: str | None = None,
    ) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("evaluation signal request must be an object")
        _reject_unknown(payload, {"task_id", "experiment_id", "source_artifact_id", "metric", "value", "unit", "lineage", "trace_id", "idempotency_key"})
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        if owner is None:
            raise LearningUnauthorized("evaluation signal requires a trusted owner")
        task_id = _text(payload.get("task_id"), field="task_id", max_length=64)
        task = self._owned_task(task_id, owner)
        experiment_id = payload.get("experiment_id")
        if experiment_id is not None:
            experiment_id = _text(experiment_id, field="experiment_id", max_length=64)
            experiment = self.research_store.get_experiment(experiment_id)
            if experiment["task_id"] != task_id:
                raise ValueError("experiment does not belong to research task")
        artifact_id = _text(payload.get("source_artifact_id"), field="source_artifact_id", max_length=64)
        artifact = self.research_store.get_artifact(artifact_id)
        if artifact["task_id"] != task_id:
            raise ValueError("source artifact does not belong to research task")
        if artifact["status"] != "validated":
            raise ValueError("source artifact must be validated before it can produce an evaluation signal")
        metric = _text(payload.get("metric"), field="metric", max_length=128)
        value = self._finite_value(payload.get("value"), "value")
        unit = _text(payload["unit"], field="unit", max_length=32) if payload.get("unit") else None
        lineage, lineage_json = _lineage(payload.get("lineage", []))
        trace_id = _trace(payload.get("trace_id"), field="trace_id")
        key = _idempotency(payload.get("idempotency_key"))
        request = {
            "task_id": task_id,
            "experiment_id": experiment_id,
            "source_artifact_id": artifact_id,
            "metric": metric,
            "value": value,
            "unit": unit,
            "lineage": lineage,
            "trace_id": trace_id,
            "idempotency_key": key,
        }
        request_hash = _hash(request)
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT * FROM evaluation_signals WHERE task_id = ? AND idempotency_key = ?",
                (task_id, key),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise LearningConflict("evaluation signal idempotency key was reused")
                return self._signal_row(existing)
            now = _now()
            signal_id = _new_id("evaluation_signal")
            self._connection.execute(
                """INSERT INTO evaluation_signals
                (signal_id, task_id, experiment_id, source_artifact_id, metric,
                 value, unit, lineage_json, trace_id, idempotency_key,
                 request_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (signal_id, task_id, experiment_id, artifact_id, metric, value, unit, lineage_json, trace_id, key, request_hash, now),
            )
            row = self._connection.execute("SELECT * FROM evaluation_signals WHERE signal_id = ?", (signal_id,)).fetchone()
            assert row is not None
            return self._signal_row(row)

    def get_signal(self, signal_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        signal_id = _learning_id(signal_id, field="signal_id", prefix="evaluation_signal")
        with self._lock:
            row = self._connection.execute("SELECT * FROM evaluation_signals WHERE signal_id = ?", (signal_id,)).fetchone()
        if row is None:
            raise LearningNotFound("evaluation signal not found")
        if trusted_owner:
            task = self.research_store.get_task(row["task_id"])
            if task["owner_principal"] != trusted_owner:
                raise LearningUnauthorized("evaluation signal is not owned by this principal")
        return self._signal_row(row)

    def compare_experiments(self, payload: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("experiment comparison request must be an object")
        _reject_unknown(payload, {"task_id", "experiment_a_id", "experiment_b_id", "metric"})
        task_id = _text(payload.get("task_id"), field="task_id", max_length=64)
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        if owner is None:
            raise LearningUnauthorized("experiment comparison requires a trusted owner")
        self._owned_task(task_id, owner)
        experiment_a = _text(payload.get("experiment_a_id"), field="experiment_a_id", max_length=64)
        experiment_b = _text(payload.get("experiment_b_id"), field="experiment_b_id", max_length=64)
        for experiment_id in (experiment_a, experiment_b):
            experiment = self.research_store.get_experiment(experiment_id)
            if experiment["task_id"] != task_id:
                raise ValueError("experiment does not belong to research task")
        metric = _text(payload.get("metric"), field="metric", max_length=128)
        with self._lock:
            a = self._latest_signal(task_id, experiment_a, metric)
            b = self._latest_signal(task_id, experiment_b, metric)
        if a is None or b is None:
            raise ValueError("both experiments must have an evaluation signal for the requested metric")
        a_value = float(a["value"])
        b_value = float(b["value"])
        difference = b_value - a_value
        if a_value > b_value:
            winner = "a"
        elif b_value > a_value:
            winner = "b"
        else:
            winner = "tie"
        return {
            "task_id": task_id,
            "metric": metric,
            "experiment_a": {"experiment_id": experiment_a, "signal_id": a["signal_id"], "value": a_value},
            "experiment_b": {"experiment_id": experiment_b, "signal_id": b["signal_id"], "value": b_value},
            "difference": difference,
            "winner": winner,
        }

    def propose_lesson(
        self,
        payload: object,
        *,
        trusted_owner: str | None = None,
        trusted_actor: str | None = None,
    ) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("lesson proposal must be an object")
        _reject_unknown(payload, {"task_id", "content", "evidence", "validation", "trace_id", "idempotency_key"})
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        actor = _principal(trusted_actor, field="actor_principal") if trusted_actor else owner
        if owner is None or actor is None:
            raise LearningUnauthorized("lesson proposal requires trusted owner and actor")
        task_id = _text(payload.get("task_id"), field="task_id", max_length=64)
        self._owned_task(task_id, owner)
        content, content_json = _json_object(payload.get("content"), field="content")
        validation, validation_json = _json_object(payload.get("validation", {}), field="validation")
        evidence, evidence_json = self._evidence_refs(payload.get("evidence"), task_id=task_id, owner=owner)
        trace_id = _trace(payload.get("trace_id"), field="trace_id")
        key = _idempotency(payload.get("idempotency_key"))
        request = {
            "task_id": task_id,
            "owner_principal": owner,
            "actor_principal": actor,
            "content": content,
            "validation": validation,
            "evidence": evidence,
            "trace_id": trace_id,
            "idempotency_key": key,
        }
        request_hash = _hash(request)
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT * FROM lessons WHERE task_id = ? AND idempotency_key = ?",
                (task_id, key),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise LearningConflict("lesson idempotency key was reused")
                return self._lesson_with_history(existing)
            now = _now()
            lesson_id = _new_id("lesson")
            self._connection.execute(
                """INSERT INTO lessons
                (lesson_id, task_id, owner_principal, actor_principal, trace_id,
                 status, content_json, evidence_json, validation_json,
                 idempotency_key, request_hash, created_at, updated_at, version)
                VALUES (?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?, 1)""",
                (lesson_id, task_id, owner, actor, trace_id, content_json, evidence_json, validation_json, key, request_hash, now, now),
            )
            row = self._connection.execute("SELECT * FROM lessons WHERE lesson_id = ?", (lesson_id,)).fetchone()
            assert row is not None
            return self._lesson_with_history(row)

    def get_lesson(self, lesson_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        lesson_id = _learning_id(lesson_id, field="lesson_id", prefix="lesson")
        with self._lock:
            row = self._connection.execute("SELECT * FROM lessons WHERE lesson_id = ?", (lesson_id,)).fetchone()
        if row is None:
            raise LearningNotFound("lesson not found")
        if trusted_owner and row["owner_principal"] != trusted_owner:
            raise LearningUnauthorized("lesson is not owned by this principal")
        return self._lesson_with_history(row)

    def review_lesson(
        self,
        payload: object,
        *,
        trusted_owner: str | None = None,
        trusted_actor: str | None = None,
    ) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("lesson review must be an object")
        _reject_unknown(payload, {"lesson_id", "decision", "rationale"})
        lesson_id = _learning_id(payload.get("lesson_id"), field="lesson_id", prefix="lesson")
        reviewer = _principal(trusted_actor, field="reviewer_principal") if trusted_actor else None
        if reviewer is None:
            raise LearningUnauthorized("lesson review requires a trusted reviewer")
        decision = _text(payload.get("decision"), field="decision", max_length=16)
        if decision not in {"approved", "rejected", "superseded"}:
            raise ValueError("decision must be approved, rejected, or superseded")
        rationale = _text(payload.get("rationale") or "", field="rationale", max_length=2000) if payload.get("rationale") else ""
        with self._lock, self._connection:
            row = self._connection.execute("SELECT * FROM lessons WHERE lesson_id = ?", (lesson_id,)).fetchone()
            if row is None:
                raise LearningNotFound("lesson not found")
            if trusted_owner and row["owner_principal"] != trusted_owner:
                raise LearningUnauthorized("lesson is not owned by this principal")
            if reviewer == row["actor_principal"]:
                raise LearningForbidden("the initiating actor cannot promote their own lesson")
            current = row["status"]
            target = decision
            if target not in LESSON_TRANSITIONS[current]:
                raise LearningForbidden(f"cannot transition lesson from {current} to {target}")
            now = _now()
            self._connection.execute(
                "UPDATE lessons SET status = ?, updated_at = ?, version = version + 1 WHERE lesson_id = ?",
                (target, now, lesson_id),
            )
            self._record_history("lesson", lesson_id, current, target, reviewer, decision, rationale)
            updated = self._connection.execute("SELECT * FROM lessons WHERE lesson_id = ?", (lesson_id,)).fetchone()
            assert updated is not None
            return self._lesson_with_history(updated)

    def _owned_task(self, task_id: str, owner: str) -> dict[str, object]:
        try:
            task = self.research_store.get_task(task_id)
        except ResearchNotFound as exc:
            raise LearningNotFound("research task not found") from exc
        if task["owner_principal"] != owner:
            raise LearningUnauthorized("research task is not owned by this principal")
        return task

    def _evidence_refs(self, value: object, *, task_id: str, owner: str) -> tuple[list[dict[str, str]], str]:
        evidence, evidence_json = _lineage(value)
        if not evidence:
            raise ValueError("lesson evidence must contain at least one validated source")
        for ref in evidence:
            if ref["kind"] == "artifact":
                try:
                    artifact = self.research_store.get_artifact(ref["id"])
                except ResearchNotFound as exc:
                    raise ValueError("lesson evidence references a missing artifact") from exc
                if artifact["task_id"] != task_id:
                    raise ValueError("lesson evidence artifact does not belong to research task")
                if artifact["status"] != "validated":
                    raise ValueError("lesson evidence artifact must be validated")
            elif ref["kind"] == "evaluation_signal":
                signal = self.get_signal(ref["id"], trusted_owner=owner)
                if signal["task_id"] != task_id:
                    raise ValueError("lesson evidence signal does not belong to research task")
            else:
                raise ValueError("lesson evidence kind must be artifact or evaluation_signal")
        return evidence, evidence_json

    @staticmethod
    def _budget(value: object) -> tuple[dict[str, int], str]:
        budget, budget_json = _json_object(value, field="budget")
        _reject_unknown(budget, {"max_iterations", "max_repairs"})
        max_iterations = budget.get("max_iterations")
        max_repairs = budget.get("max_repairs", 0)
        if not isinstance(max_iterations, int) or isinstance(max_iterations, bool) or not 1 <= max_iterations <= 100:
            raise ValueError("budget.max_iterations must be an integer between 1 and 100")
        if not isinstance(max_repairs, int) or isinstance(max_repairs, bool) or not 0 <= max_repairs <= 10:
            raise ValueError("budget.max_repairs must be an integer between 0 and 10")
        return {"max_iterations": max_iterations, "max_repairs": max_repairs}, budget_json

    @staticmethod
    def _stopping_rules(value: object) -> tuple[dict[str, object], str]:
        rules, rules_json = _json_object(value, field="stopping_rules")
        if not rules:
            return {}, rules_json
        _reject_unknown(rules, {"target_metric", "target_value", "operator"})
        metric = _text(rules.get("target_metric"), field="target_metric", max_length=128)
        target = rules.get("target_value")
        if not isinstance(target, (int, float)) or isinstance(target, bool) or not math.isfinite(float(target)):
            raise ValueError("target_value must be a finite number")
        operator = _text(rules.get("operator"), field="operator", max_length=8)
        if operator not in {"gte", "lte"}:
            raise ValueError("operator must be gte or lte")
        return {"target_metric": metric, "target_value": float(target), "operator": operator}, rules_json

    @staticmethod
    def _stored_budget(budget_json: str) -> dict[str, int]:
        budget = _loads(budget_json, field="budget")
        if not isinstance(budget, dict):
            raise LearningPersistenceError("stored learning budget is invalid")
        return budget

    @staticmethod
    def _stored_stopping_rules(rules_json: str) -> dict[str, object]:
        rules = _loads(rules_json, field="stopping_rules")
        if not isinstance(rules, dict):
            raise LearningPersistenceError("stored learning stopping rules are invalid")
        return rules

    @staticmethod
    def _positive_int(value: object, field: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{field} must be a positive integer")
        return value

    @staticmethod
    def _finite_value(value: object, field: str) -> float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{field} must be a finite number")
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"{field} must be a finite number")
        return result

    @staticmethod
    def _validate_iteration_sequence(
        rows: list[sqlite3.Row],
        iteration_index: int,
        attempt: int,
        budget: dict[str, int],
    ) -> None:
        if iteration_index > budget["max_iterations"]:
            raise LearningForbidden("iteration index exceeds the learning run budget")
        if attempt > budget["max_repairs"] + 1:
            raise LearningForbidden("attempt exceeds the learning run repair budget")
        if not rows:
            if iteration_index != 1 or attempt != 1:
                raise LearningConflict("first learning iteration must be index 1, attempt 1")
            return
        previous = rows[-1]
        if attempt == 1:
            if iteration_index != previous["iteration_index"] + 1:
                raise LearningConflict("iteration index must advance by exactly one")
            return
        if iteration_index != previous["iteration_index"]:
            raise LearningConflict("a retried attempt must target the current iteration index")
        if previous["attempt"] != attempt - 1 or previous["outcome"] != "failed":
            raise LearningConflict("a retried attempt must follow a failed attempt")

    @staticmethod
    def _next_run_status(
        run: sqlite3.Row,
        outcome: str,
        iteration_index: int,
        attempt: int,
        budget: dict[str, int],
        feedback: dict[str, object],
    ) -> str:
        if outcome == "failed":
            if attempt <= budget["max_repairs"]:
                return "active"
            return "awaiting_review"
        if iteration_index >= budget["max_iterations"]:
            return "awaiting_review"
        rules = LearningLoopStore._stored_stopping_rules(run["stopping_rules_json"])
        if outcome == "produced" and rules:
            observed = feedback.get(str(rules["target_metric"]))
            if isinstance(observed, (int, float)) and not isinstance(observed, bool) and math.isfinite(float(observed)):
                value = float(observed)
                target = float(rules["target_value"])
                if rules["operator"] == "gte" and value >= target:
                    return "awaiting_review"
                if rules["operator"] == "lte" and value <= target:
                    return "awaiting_review"
        return "active"

    def _check_run_access(self, run: sqlite3.Row, *, trusted_owner: str | None, trusted_actor: str | None) -> None:
        if trusted_owner and run["owner_principal"] != trusted_owner:
            raise LearningUnauthorized("learning run is not owned by this principal")
        if trusted_actor and run["actor_principal"] != trusted_actor:
            raise LearningUnauthorized("learning run actor does not match the active run")

    def _latest_signal(self, task_id: str, experiment_id: str, metric: str) -> sqlite3.Row | None:
        return self._connection.execute(
            """SELECT * FROM evaluation_signals
            WHERE task_id = ? AND experiment_id = ? AND metric = ?
            ORDER BY created_at DESC, signal_id DESC LIMIT 1""",
            (task_id, experiment_id, metric),
        ).fetchone()

    def _record_history(
        self,
        entity_type: str,
        entity_id: str,
        from_status: str,
        to_status: str,
        reviewer: str,
        decision: str,
        rationale: str,
    ) -> None:
        history_id = _new_id("learning_history")
        self._connection.execute(
            """INSERT INTO learning_history
            (history_id, entity_type, entity_id, from_status, to_status,
             reviewer_principal, decision, rationale, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (history_id, entity_type, entity_id, from_status, to_status, reviewer, decision, rationale, _now()),
        )

    @staticmethod
    def _run_row(row: sqlite3.Row) -> dict[str, object]:
        result = dict(row)
        result.pop("idempotency_key", None)
        result.pop("request_hash", None)
        result["budget"] = _loads(result.pop("budget_json"), field="budget")
        result["stopping_rules"] = _loads(result.pop("stopping_rules_json"), field="stopping_rules")
        result["lineage"] = _loads(result.pop("lineage_json"), field="lineage")
        return result

    @staticmethod
    def _iteration_row(row: sqlite3.Row) -> dict[str, object]:
        result = dict(row)
        result.pop("idempotency_key", None)
        result.pop("request_hash", None)
        result["feedback"] = _loads(result.pop("feedback_json"), field="feedback")
        result["source_refs"] = _loads(result.pop("source_refs_json"), field="source_refs")
        result["result_refs"] = _loads(result.pop("result_refs_json"), field="result_refs")
        return result

    @staticmethod
    def _signal_row(row: sqlite3.Row) -> dict[str, object]:
        result = dict(row)
        result.pop("idempotency_key", None)
        result.pop("request_hash", None)
        result["lineage"] = _loads(result.pop("lineage_json"), field="lineage")
        return result

    @staticmethod
    def _lesson_row(row: sqlite3.Row) -> dict[str, object]:
        result = dict(row)
        result.pop("idempotency_key", None)
        result.pop("request_hash", None)
        result["content"] = _loads(result.pop("content_json"), field="content")
        result["evidence"] = _loads(result.pop("evidence_json"), field="evidence")
        result["validation"] = _loads(result.pop("validation_json"), field="validation")
        return result

    def _lesson_with_history(self, row: sqlite3.Row) -> dict[str, object]:
        lesson = self._lesson_row(row)
        with self._lock:
            rows = self._connection.execute(
                """SELECT * FROM learning_history
                WHERE entity_type = 'lesson' AND entity_id = ?
                ORDER BY created_at ASC, history_id ASC""",
                (lesson["lesson_id"],),
            ).fetchall()
        lesson["history"] = [dict(item) for item in rows]
        return lesson
