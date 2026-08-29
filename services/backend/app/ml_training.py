"""Durable ML training jobs, point-in-time feature snapshots and model artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy.exc import SQLAlchemyError

from .backtest import LocalObjectStore
from .db import PgStoreMixin, execute, fetch_one
from .ml_strategy import FEATURE_ORDER, FEATURE_SET, RUNTIME_LOCK, content_sha256
from .research import ResearchStore


TRAINING_SCHEMA = "ml-training-run.v1"
FEATURE_SCHEMA = "ml-feature-snapshot.v1"
MODEL_SCHEMA = "ml-model-artifact.v1"
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_ROWS = 50_000
MAX_ATTEMPTS = 3
RUNTIME_IDENTITY = "lightgbm-4.7.0-python-3.13-linux-cpu-single-thread"


class MLTrainingError(RuntimeError):
    pass


class MLTrainingNotFound(MLTrainingError):
    pass


class MLTrainingConflict(MLTrainingError):
    pass


class MLTrainingPersistenceError(MLTrainingError):
    pass


class MLTrainer(Protocol):
    def train(self, feature_snapshot: dict[str, object], strategy: dict[str, object]) -> dict[str, object]: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("ML training input must be finite JSON") from error


def _text(value: object, field: str, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{field} must be a non-empty string of at most {maximum} characters")
    return value.strip()


def _identifier(value: object, field: str) -> str:
    normalized = _text(value, field)
    if not normalized.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"{field} has invalid format")
    return normalized


def _split_for(date: str, split: dict[str, object]) -> str | None:
    for name in ("train", "validation", "prediction"):
        window = split.get(name)
        if isinstance(window, dict) and str(window.get("start")) <= date <= str(window.get("end")):
            return name
    return None


def build_feature_snapshot(
    *, strategy: dict[str, object], universe: dict[str, object], ready_input: dict[str, object],
    readiness: dict[str, object],
) -> dict[str, object]:
    """Build the closed five-feature panel without crossing split boundaries."""
    bars = ready_input.get("research_bars")
    split = strategy.get("split")
    target = strategy.get("target")
    if not isinstance(bars, list) or not isinstance(split, dict) or not isinstance(target, dict):
        raise ValueError("ML feature input is incomplete")
    if len(bars) > MAX_ROWS:
        raise ValueError("ML feature input exceeds 50000 rows")
    horizon = int(target["horizon_sessions"])
    by_symbol: dict[str, dict[str, dict[str, object]]] = {}
    all_dates: set[str] = set()
    allowed_symbols = set(universe.get("symbols", []))
    for raw in bars:
        if not isinstance(raw, dict):
            raise ValueError("ML research bars must be objects")
        symbol, date = str(raw.get("symbol")), str(raw.get("trade_date"))
        if raw.get("is_universe_member") is False:
            continue
        if symbol not in allowed_symbols:
            continue
        if date in by_symbol.setdefault(symbol, {}):
            raise ValueError("ML research bars contain duplicate symbol/session")
        by_symbol[symbol][date] = raw
        all_dates.add(date)
    dates = sorted(all_dates)
    rows: list[dict[str, object]] = []
    excluded = {"warmup_or_missing": 0, "label_outside_split": 0, "non_finite": 0}
    for symbol in sorted(by_symbol):
        symbol_bars = by_symbol[symbol]
        for index, date in enumerate(dates):
            split_name = _split_for(date, split)
            if split_name is None or index < 20:
                continue
            required_dates = [dates[index - offset] for offset in range(0, 21)]
            if any(item not in symbol_bars for item in required_dates):
                excluded["warmup_or_missing"] += 1
                continue
            try:
                closes = [float(symbol_bars[item]["close"]) for item in required_dates]
                volumes = [float(symbol_bars[dates[index - offset]].get("volume") or 0) for offset in range(0, 5)]
                current = closes[0]
                daily_returns = [closes[offset] / closes[offset + 1] - 1.0 for offset in range(20)]
                mean_volume = sum(volumes) / len(volumes)
                features = {
                    "return_1": current / closes[1] - 1.0,
                    "return_5": current / closes[5] - 1.0,
                    "return_20": current / closes[20] - 1.0,
                    "volatility_20": statistics.pstdev(daily_returns),
                    "volume_ratio_5": volumes[0] / mean_volume if mean_volume > 0 else 0.0,
                }
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                excluded["non_finite"] += 1
                continue
            if not all(math.isfinite(value) for value in features.values()):
                excluded["non_finite"] += 1
                continue
            row: dict[str, object] = {
                "session": date, "symbol": symbol, "split": split_name,
                "feature_as_of": date, "features": features,
            }
            if split_name != "prediction":
                future_index = index + horizon
                split_end = str(split[split_name]["end"])
                if future_index >= len(dates) or dates[future_index] > split_end or dates[future_index] not in symbol_bars:
                    excluded["label_outside_split"] += 1
                    continue
                future_close = float(symbol_bars[dates[future_index]]["close"])
                label = future_close / current - 1.0
                if not math.isfinite(label):
                    excluded["non_finite"] += 1
                    continue
                row.update({"target": label, "label_end_date": dates[future_index]})
            rows.append(row)
    rows.sort(key=lambda item: (str(item["session"]), str(item["symbol"])))
    counts = {name: sum(row["split"] == name for row in rows) for name in ("train", "validation", "prediction")}
    symbol_counts = {
        name: len({str(row["symbol"]) for row in rows if row["split"] == name})
        for name in ("train", "validation", "prediction")
    }
    candidate_count = len(rows) + sum(excluded.values())
    coverage = {
        "usable_rows": len(rows),
        "candidate_rows": candidate_count,
        "usable_ratio": (len(rows) / candidate_count if candidate_count else 0.0),
    }
    if counts["train"] < 20 or counts["validation"] < 5:
        raise ValueError("ML feature snapshot has insufficient train or validation rows")
    document: dict[str, object] = {
        "schema_version": FEATURE_SCHEMA,
        "feature_set": FEATURE_SET,
        "feature_order": FEATURE_ORDER,
        "target": target,
        "split": split,
        "universe": universe,
        "rows": rows,
        "counts": counts,
        "symbol_counts": symbol_counts,
        "coverage": coverage,
        "excluded": excluded,
        "source": {
            "ready_input_sha256": readiness.get("ready_input_sha256"),
            "research_view_sha256": ready_input.get("research_view_sha256"),
        },
    }
    document["content_sha256"] = content_sha256(document)
    encoded = _canonical(document)
    if len(encoded) > MAX_INPUT_BYTES:
        raise ValueError("ML feature snapshot exceeds 32 MiB")
    return document


class MLTrainingRunStore(PgStoreMixin):
    SCHEMA_DDL = [
        """
        CREATE TABLE IF NOT EXISTS ml_training_runs (
            training_run_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            owner_principal TEXT NOT NULL,
            task_id TEXT NOT NULL,
            experiment_id TEXT,
            ml_strategy_artifact_id TEXT NOT NULL,
            stock_pool_snapshot_id TEXT NOT NULL,
            status TEXT NOT NULL,
            preparation_json JSONB NOT NULL,
            requirement_json JSONB NOT NULL,
            readiness_json JSONB NOT NULL,
            input_json JSONB,
            input_sha256 TEXT,
            trace_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            worker_id TEXT,
            lease_expires_at TIMESTAMPTZ,
            feature_artifact_id TEXT,
            model_artifact_id TEXT,
            error_code TEXT,
            error_detail TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL,
            UNIQUE(workspace_id, idempotency_key)
        )
        """,
        """CREATE INDEX IF NOT EXISTS ml_training_runs_queue ON ml_training_runs(status, created_at)""",
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as error:
            raise MLTrainingPersistenceError("ML training storage is unavailable") from error

    @classmethod
    def from_env(cls) -> "MLTrainingRunStore":
        return cls()

    def create_waiting(
        self, *, workspace_id: object, owner_principal: object, task_id: object,
        experiment_id: object | None, ml_strategy_artifact_id: object,
        stock_pool_snapshot_id: object, preparation: dict[str, object],
        requirement: dict[str, object], readiness: dict[str, object], trace_id: object,
        idempotency_key: object,
    ) -> dict[str, object]:
        workspace = _identifier(workspace_id, "workspace_id")
        owner = _text(owner_principal, "owner_principal")
        task = _identifier(task_id, "task_id")
        experiment = None if experiment_id is None else _identifier(experiment_id, "experiment_id")
        strategy = _identifier(ml_strategy_artifact_id, "ml_strategy_artifact_id")
        pool = _identifier(stock_pool_snapshot_id, "stock_pool_snapshot_id")
        trace = _text(trace_id, "trace_id")
        key = _text(idempotency_key, "idempotency_key")
        request = {
            "workspace_id": workspace, "owner_principal": owner, "task_id": task,
            "experiment_id": experiment, "ml_strategy_artifact_id": strategy,
            "stock_pool_snapshot_id": pool, "preparation": preparation,
            "requirement_sha256": requirement.get("requirement_sha256"), "trace_id": trace,
        }
        request_hash = hashlib.sha256(_canonical(request)).hexdigest()
        with self._transaction() as connection:
            existing = fetch_one(connection, """SELECT * FROM ml_training_runs
                WHERE workspace_id=:workspace AND idempotency_key=:key""", {"workspace": workspace, "key": key})
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise MLTrainingConflict("ML training idempotency key was reused")
                return self._public(existing)
            run_id, now = f"mlrun_{uuid.uuid4().hex}", _now()
            execute(connection, """INSERT INTO ml_training_runs
                (training_run_id,workspace_id,owner_principal,task_id,experiment_id,
                 ml_strategy_artifact_id,stock_pool_snapshot_id,status,preparation_json,
                 requirement_json,readiness_json,trace_id,idempotency_key,request_hash,
                 created_at,updated_at)
                VALUES (:run_id,:workspace,:owner,:task,:experiment,:strategy,:pool,
                        'waiting_for_data',:preparation,:requirement,:readiness,:trace,:key,
                        :request_hash,:now,:now)""", {
                "run_id": run_id, "workspace": workspace, "owner": owner, "task": task,
                "experiment": experiment, "strategy": strategy, "pool": pool,
                "preparation": preparation, "requirement": requirement, "readiness": readiness,
                "trace": trace, "key": key, "request_hash": request_hash, "now": now,
            })
        return self.get(run_id, trusted_workspace=workspace, trusted_owner=owner)

    def get(self, run_id: object, *, trusted_workspace: str | None = None, trusted_owner: str | None = None) -> dict[str, object]:
        identity = _identifier(run_id, "training_run_id")
        row = self._fetch_one("SELECT * FROM ml_training_runs WHERE training_run_id=:id", {"id": identity})
        if row is None or (trusted_workspace and row["workspace_id"] != trusted_workspace) or (
            trusted_owner and row["owner_principal"] != trusted_owner
        ):
            raise MLTrainingNotFound("ML training run not found")
        return self._public(row)

    def list_runs(self, *, trusted_workspace: str, trusted_owner: str) -> dict[str, object]:
        rows = self._execute("""SELECT * FROM ml_training_runs
            WHERE workspace_id=:workspace AND owner_principal=:owner
            ORDER BY created_at DESC,training_run_id DESC LIMIT 100""",
            {"workspace": trusted_workspace, "owner": trusted_owner})
        return {"runs": [self._public(row) for row in rows]}

    def prediction_material(
        self, run_id: object, *, trusted_workspace: str, trusted_owner: str
    ) -> dict[str, object]:
        """Return frozen training material only to the trusted inference boundary."""
        identity = _identifier(run_id, "training_run_id")
        row = self._fetch_one(
            """SELECT * FROM ml_training_runs WHERE training_run_id=:id
               AND workspace_id=:workspace AND owner_principal=:owner AND status='completed'""",
            {"id": identity, "workspace": trusted_workspace, "owner": trusted_owner},
        )
        if row is None:
            raise MLTrainingNotFound("completed ML training run not found")
        return self._internal(row)

    def list_waiting(self, limit: int = 20) -> list[dict[str, object]]:
        return self._execute("""SELECT * FROM ml_training_runs WHERE status='waiting_for_data'
            ORDER BY created_at,training_run_id LIMIT :limit""", {"limit": limit})

    def update_readiness(self, run_id: str, readiness: dict[str, object]) -> None:
        self._execute("""UPDATE ml_training_runs SET readiness_json=:readiness,updated_at=:now
            WHERE training_run_id=:id AND status='waiting_for_data'""",
            {"readiness": readiness, "now": _now(), "id": run_id})

    def promote_ready(self, run_id: str, feature_snapshot: dict[str, object]) -> dict[str, object]:
        expected = feature_snapshot.get("content_sha256")
        body = dict(feature_snapshot)
        body.pop("content_sha256", None)
        if expected != content_sha256(body):
            raise ValueError("ML feature snapshot identity does not match content")
        if len(_canonical(feature_snapshot)) > MAX_INPUT_BYTES:
            raise ValueError("ML training input exceeds 32 MiB")
        self._execute("""UPDATE ml_training_runs SET status='queued',input_json=:input,
            input_sha256=:sha,updated_at=:now WHERE training_run_id=:id AND status='waiting_for_data'""",
            {"input": feature_snapshot, "sha": expected, "now": _now(), "id": run_id})
        return self.get(run_id)

    def claim_next(self, worker_id: str) -> dict[str, object] | None:
        worker = _text(worker_id, "worker_id")
        with self._transaction() as connection:
            execute(connection, """UPDATE ml_training_runs SET status='queued',worker_id=NULL,
                lease_expires_at=NULL,updated_at=now() WHERE status='running'
                AND lease_expires_at<now() AND attempt_count<max_attempts""")
            execute(connection, """UPDATE ml_training_runs SET status='failed',error_code='attempts_exhausted',
                error_detail='ML training attempts exhausted',finished_at=now(),updated_at=now()
                WHERE status='running' AND lease_expires_at<now() AND attempt_count>=max_attempts""")
            row = fetch_one(connection, """SELECT training_run_id FROM ml_training_runs
                WHERE status='queued' ORDER BY created_at,training_run_id
                FOR UPDATE SKIP LOCKED LIMIT 1""")
            if row is None:
                return None
            claimed = fetch_one(connection, """UPDATE ml_training_runs SET status='running',
                attempt_count=attempt_count+1,worker_id=:worker,started_at=COALESCE(started_at,now()),
                lease_expires_at=now()+interval '5 minutes',updated_at=now()
                WHERE training_run_id=:id RETURNING *""",
                {"worker": worker, "id": row["training_run_id"]})
        return self._internal(claimed) if claimed else None

    def complete(
        self, run_id: str, *, feature_artifact_id: str, model_artifact_id: str,
        worker_id: str, attempt_count: int,
    ) -> dict[str, object]:
        self._execute("""UPDATE ml_training_runs SET status='completed',feature_artifact_id=:feature,
            model_artifact_id=:model,lease_expires_at=NULL,finished_at=now(),updated_at=now()
            WHERE training_run_id=:id AND status='running' AND worker_id=:worker
            AND attempt_count=:attempt""",
            {"feature": feature_artifact_id, "model": model_artifact_id, "id": run_id,
             "worker": worker_id, "attempt": attempt_count})
        return self.get(run_id)

    def fail(
        self, run_id: str, code: str, detail: str, *, worker_id: str, attempt_count: int,
    ) -> dict[str, object]:
        self._execute("""UPDATE ml_training_runs SET status='failed',error_code=:code,
            error_detail=:detail,lease_expires_at=NULL,finished_at=now(),updated_at=now()
            WHERE training_run_id=:id AND status='running' AND worker_id=:worker
            AND attempt_count=:attempt""",
            {"code": _text(code, "error_code", 64), "detail": _text(detail, "error_detail", 500),
             "id": run_id, "worker": worker_id, "attempt": attempt_count})
        return self.get(run_id)

    def cancel(self, run_id: object, *, trusted_workspace: str, trusted_owner: str) -> dict[str, object]:
        current = self.get(
            run_id, trusted_workspace=trusted_workspace, trusted_owner=trusted_owner
        )
        if current["status"] not in {"waiting_for_data", "queued"}:
            raise MLTrainingConflict("only waiting or queued ML training runs can be cancelled")
        updated = self._fetch_one("""UPDATE ml_training_runs SET status='cancelled',
            error_code='cancelled',error_detail='cancelled by owner',finished_at=now(),updated_at=now()
            WHERE training_run_id=:id AND workspace_id=:workspace AND owner_principal=:owner
            AND status IN ('waiting_for_data','queued') RETURNING *""",
            {"id": current["training_run_id"], "workspace": trusted_workspace,
             "owner": trusted_owner})
        if updated is None:
            raise MLTrainingConflict("ML training run can no longer be cancelled")
        return self._public(updated)

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, object]:
        value = dict(row)
        for field in ("preparation_json", "requirement_json", "input_json", "request_hash"):
            value.pop(field, None)
        value["readiness"] = value.pop("readiness_json", {})
        return value

    @staticmethod
    def _internal(row: dict[str, Any]) -> dict[str, object]:
        value = dict(row)
        value["preparation"] = value.pop("preparation_json")
        value["requirement"] = value.pop("requirement_json")
        value["readiness"] = value.pop("readiness_json")
        value["input"] = value.pop("input_json")
        value.pop("request_hash", None)
        return value


def promote_waiting_training_runs(store: MLTrainingRunStore, readiness_store: object) -> int:
    promoted = 0
    for row in store.list_waiting():
        requirement, preparation = row.get("requirement_json"), row.get("preparation_json")
        if not isinstance(requirement, dict) or not isinstance(preparation, dict):
            continue
        readiness = readiness_store.assess(requirement)
        store.update_readiness(str(row["training_run_id"]), readiness)
        if readiness.get("state") != "ready":
            continue
        ready_input = readiness_store.build_ready_input(requirement)
        strategy, universe = preparation.get("strategy"), preparation.get("universe")
        if not isinstance(strategy, dict) or not isinstance(universe, dict):
            continue
        feature_snapshot = build_feature_snapshot(
            strategy=strategy, universe=universe, ready_input=ready_input, readiness=readiness
        )
        store.promote_ready(str(row["training_run_id"]), feature_snapshot)
        promoted += 1
    return promoted


class MLTrainingCoordinator:
    def __init__(
        self, runs: MLTrainingRunStore, research: ResearchStore, objects: LocalObjectStore,
        trainer: MLTrainer, *, worker_id: str,
    ) -> None:
        self.runs, self.research, self.objects, self.trainer = runs, research, objects, trainer
        self.worker_id = worker_id

    def run_next(self) -> dict[str, object] | None:
        job = self.runs.claim_next(self.worker_id)
        if job is None:
            return None
        run_id = str(job["training_run_id"])
        try:
            feature = job.get("input")
            preparation = job.get("preparation")
            if not isinstance(feature, dict) or not isinstance(preparation, dict):
                raise ValueError("ML training input is unavailable")
            strategy = preparation.get("strategy")
            if not isinstance(strategy, dict):
                raise ValueError("ML strategy snapshot is unavailable")
            result = self.trainer.train(feature, strategy)
            model_text = result.pop("model_text", None)
            if not isinstance(model_text, str) or not model_text:
                raise ValueError("ML trainer returned no native model")
            if result.get("runtime_identity") != RUNTIME_IDENTITY:
                raise ValueError("ML trainer runtime identity does not match the trusted profile")
            image_identity = result.get("image_identity")
            if not isinstance(image_identity, str) or not image_identity.strip() or len(image_identity) > 256:
                raise ValueError("ML trainer image identity is unavailable")
            metrics = result.get("metrics")
            if not isinstance(metrics, dict) or any(
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))
                for value in metrics.values()
            ):
                raise ValueError("ML trainer metrics must be finite numbers")
            reference = self.objects.put(
                "ml-models", model_text.encode("utf-8"), media_type="text/x-lightgbm-model"
            )
            feature_hash = str(feature["content_sha256"])
            feature_artifact_hash = content_sha256(feature)
            feature_artifact = self.research.find_artifact_by_content(
                str(job["task_id"]), "ml_feature_snapshot", feature_artifact_hash
            )
            if feature_artifact is None:
                feature_artifact = self.research.create_artifact({
                    "task_id": job["task_id"], "experiment_id": job.get("experiment_id"),
                    "kind": "ml_feature_snapshot", "content": feature,
                    "lineage": [
                        {"kind": "artifact", "id": job["ml_strategy_artifact_id"]},
                        {"kind": "stock_pool_snapshot", "id": job["stock_pool_snapshot_id"]},
                        {"kind": "ml_training_run", "id": run_id},
                    ],
                    "trace_id": job["trace_id"],
                    "idempotency_key": f"ml-feature-{feature_artifact_hash}",
                })
            if feature_artifact["status"] == "draft":
                feature_artifact = self.research.transition(
                    "artifact", feature_artifact["artifact_id"], "validated", f"ml-feature-validate-{feature_hash[:24]}"
                )
            model_content: dict[str, object] = {
                "schema_version": MODEL_SCHEMA,
                "model_format": "lightgbm-text-v1",
                "object_reference": reference,
                "runtime_lock": RUNTIME_LOCK,
                "runtime_identity": result.get("runtime_identity"),
                "image_identity": image_identity,
                "feature_order": FEATURE_ORDER,
                "target": feature.get("target"),
                "split": feature.get("split"),
                "feature_snapshot_artifact_id": feature_artifact["artifact_id"],
                "feature_snapshot_sha256": feature_hash,
                "strategy_version_artifact_id": job["ml_strategy_artifact_id"],
                "stock_pool_snapshot_id": job["stock_pool_snapshot_id"],
                "training_run_id": run_id,
                "effective_parameters": result.get("effective_parameters"),
                "best_iteration": result.get("best_iteration"),
                "metrics": result.get("metrics"),
                "counts": {
                    "rows": feature.get("counts"),
                    "symbols": feature.get("symbol_counts"),
                },
                "coverage": feature.get("coverage"),
            }
            model_hash = content_sha256(model_content)
            model_content["content_sha256"] = model_hash
            model_artifact_hash = content_sha256(model_content)
            model_artifact = self.research.find_artifact_by_content(
                str(job["task_id"]), "ml_model", model_artifact_hash
            )
            if model_artifact is None:
                model_artifact = self.research.create_artifact({
                    "task_id": job["task_id"], "experiment_id": job.get("experiment_id"),
                    "kind": "ml_model", "content": model_content,
                    "lineage": [
                        {"kind": "artifact", "id": job["ml_strategy_artifact_id"]},
                        {"kind": "artifact", "id": feature_artifact["artifact_id"]},
                        {"kind": "stock_pool_snapshot", "id": job["stock_pool_snapshot_id"]},
                        {"kind": "ml_training_run", "id": run_id},
                    ],
                    "trace_id": job["trace_id"],
                    "idempotency_key": f"ml-model-{model_artifact_hash}",
                })
            if model_artifact["status"] == "draft":
                model_artifact = self.research.transition(
                    "artifact", model_artifact["artifact_id"], "validated", f"ml-model-validate-{model_hash[:24]}"
                )
            return self.runs.complete(
                run_id, feature_artifact_id=str(feature_artifact["artifact_id"]),
                model_artifact_id=str(model_artifact["artifact_id"]),
                worker_id=str(job["worker_id"]), attempt_count=int(job["attempt_count"]),
            )
        except Exception as error:
            return self.runs.fail(
                run_id, "ml_training_failed", str(error)[:500] or "ML training failed",
                worker_id=str(job["worker_id"]), attempt_count=int(job["attempt_count"]),
            )
