"""Durable ML training jobs, point-in-time feature snapshots and model artifacts."""

from __future__ import annotations

import hashlib
import gzip
import io
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
from .ml_capabilities import (
    STRATEGY_SCHEMA as ML_V2_SCHEMA,
    expected_runtime_identity,
    learner_profile,
    model_size_limit_for_profile,
    runtime_lock_for_profile,
)
from .ml_regime import (
    BUNDLE_SCHEMA,
    build_regime_snapshot,
    validate_model_bundle,
    validate_regime_snapshot,
)
from .research import ResearchStore


TRAINING_SCHEMA = "ml-training-run.v1"
FEATURE_SCHEMA = "ml-feature-snapshot.v1"
FEATURE_STORAGE_FORMAT = "gzip-json-v1"
MODEL_SCHEMA = "ml-model-artifact.v1"
MAX_INPUT_BYTES = 256 * 1024 * 1024
MAX_ROWS = 2_000_000
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


def aggregate_ml_readiness(assessments: list[dict[str, object]]) -> dict[str, object]:
    if not assessments:
        raise ValueError("ML data preparation has no readiness partitions")
    ready_count = sum(item.get("state") == "ready" for item in assessments)
    ready_hashes = [item.get("ready_input_sha256") for item in assessments]
    missing_by_dataset: dict[str, int] = {}
    missing_sample: list[dict[str, str]] = []
    for assessment in assessments:
        counts = assessment.get("missing_by_dataset", {})
        if isinstance(counts, dict):
            for dataset, count in counts.items():
                missing_by_dataset[str(dataset)] = (
                    missing_by_dataset.get(str(dataset), 0) + int(count or 0)
                )
        items = assessment.get("missing", [])
        if isinstance(items, list):
            for item in items:
                if len(missing_sample) >= 20 or not isinstance(item, dict):
                    break
                missing_sample.append({
                    "symbol": str(item.get("symbol", "*")),
                    "trade_date": str(item.get("trade_date", "*")),
                    "dataset": str(item.get("dataset", "unknown")),
                })
    return {
        "schema_version": "ml-data-preparation.v1",
        "state": "ready" if ready_count == len(assessments) else "waiting_for_data",
        "partition_count": len(assessments), "ready_partitions": ready_count,
        "required_cell_count": sum(int(item.get("required_cell_count") or 0) for item in assessments),
        "missing_count": sum(int(item.get("missing_count") or 0) for item in assessments),
        "missing_by_dataset": missing_by_dataset,
        "missing_sample": missing_sample,
        "ready_input_sha256": (
            ready_hashes[0] if len(ready_hashes) == 1 else content_sha256(ready_hashes)
        ) if ready_count == len(assessments) else None,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("ML training input must be finite JSON") from error


def store_feature_snapshot(
    feature: dict[str, object], objects: LocalObjectStore,
) -> dict[str, object]:
    """Persist large row data as an immutable compressed object.

    The Research artifact remains small and queryable while retaining the
    source/coverage metadata needed by Product validation.
    """
    snapshot_hash = feature.get("content_sha256")
    body = dict(feature)
    body.pop("content_sha256", None)
    rows = feature.get("rows")
    if not isinstance(snapshot_hash, str) or snapshot_hash != content_sha256(body):
        raise ValueError("ML feature snapshot identity does not match content")
    if not isinstance(rows, list):
        raise ValueError("ML feature snapshot rows are unavailable")
    payload = gzip.compress(_canonical(feature), compresslevel=6, mtime=0)
    reference = objects.put(
        "ml-features", payload, media_type="application/vnd.byq.ml-feature+json+gzip",
    )
    descriptor = {key: value for key, value in feature.items() if key not in {"rows", "content_sha256"}}
    descriptor.update({
        "storage_format": FEATURE_STORAGE_FORMAT,
        "object_reference": reference,
        "row_count": len(rows),
        "snapshot_sha256": snapshot_hash,
    })
    descriptor["content_sha256"] = content_sha256(descriptor)
    return descriptor


def load_feature_snapshot(
    descriptor: dict[str, object], objects: LocalObjectStore,
) -> dict[str, object]:
    """Load a frozen feature snapshot, retaining legacy inline compatibility."""
    descriptor_hash = descriptor.get("content_sha256")
    descriptor_body = dict(descriptor)
    descriptor_body.pop("content_sha256", None)
    if not isinstance(descriptor_hash, str) or descriptor_hash != content_sha256(descriptor_body):
        raise ValueError("ML feature descriptor identity does not match content")
    if descriptor.get("storage_format") is None:
        if not isinstance(descriptor.get("rows"), list):
            raise ValueError("ML feature snapshot rows are unavailable")
        return descriptor
    if descriptor.get("storage_format") != FEATURE_STORAGE_FORMAT:
        raise ValueError("ML feature snapshot storage format is unsupported")
    reference = descriptor.get("object_reference")
    if not isinstance(reference, dict):
        raise ValueError("ML feature snapshot object reference is unavailable")
    compressed = objects.get(reference)
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as handle:
            payload = handle.read(MAX_INPUT_BYTES + 1)
        if len(payload) > MAX_INPUT_BYTES:
            raise ValueError("ML feature snapshot exceeds 256 MiB")
        feature = json.loads(payload)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("ML feature snapshot object is invalid") from error
    if not isinstance(feature, dict):
        raise ValueError("ML feature snapshot object is invalid")
    snapshot_hash = feature.get("content_sha256")
    body = dict(feature)
    body.pop("content_sha256", None)
    rows = feature.get("rows")
    if (
        not isinstance(snapshot_hash, str)
        or snapshot_hash != descriptor.get("snapshot_sha256")
        or snapshot_hash != content_sha256(body)
        or not isinstance(rows, list)
        or len(rows) != descriptor.get("row_count")
    ):
        raise ValueError("ML feature snapshot object failed integrity validation")
    return feature


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


def generate_walk_forward_folds(
    sessions: list[str], validation_plan: dict[str, object], *, horizon_sessions: int,
) -> list[dict[str, object]]:
    """Resolve a bounded, deterministic purged walk-forward manifest."""
    parameters = validation_plan.get("parameters")
    if validation_plan.get("id") != "walk-forward-purged-v1" or not isinstance(parameters, dict):
        raise ValueError("ML v2 validation plan is unsupported")
    train_count = int(parameters["train_sessions"])
    validation_count = int(parameters["validation_sessions"])
    step_count = int(parameters["step_sessions"])
    fold_count = int(parameters["folds"])
    purge_count = int(parameters["purge_sessions"])
    embargo_count = int(parameters["embargo_sessions"])
    mode = str(parameters["mode"])
    if purge_count < horizon_sessions:
        raise ValueError("walk-forward purge does not cover target horizon")
    if step_count < validation_count + embargo_count:
        raise ValueError("walk-forward step does not cover validation and embargo")
    required = train_count + purge_count + validation_count + step_count * (fold_count - 1)
    if len(sessions) < required:
        raise ValueError(
            f"walk-forward requires {required} development sessions but only {len(sessions)} are available"
        )
    selected = sessions[-required:]
    folds: list[dict[str, object]] = []
    for index in range(fold_count):
        validation_start_index = train_count + purge_count + index * step_count
        validation_end_index = validation_start_index + validation_count - 1
        train_end_index = validation_start_index - purge_count - 1
        train_start_index = 0 if mode == "expanding" else train_end_index - train_count + 1
        if train_start_index < 0 or validation_end_index >= len(selected):
            raise ValueError("walk-forward fold bounds are invalid")
        body: dict[str, object] = {
            "fold_id": f"fold-{index + 1:02d}",
            "train": {"start": selected[train_start_index], "end": selected[train_end_index]},
            "purge": {
                "start": selected[train_end_index + 1],
                "end": selected[validation_start_index - 1],
                "sessions": purge_count,
            },
            "validation": {
                "start": selected[validation_start_index], "end": selected[validation_end_index]
            },
            "embargo_sessions": embargo_count,
        }
        body["content_sha256"] = content_sha256(body)
        folds.append(body)
    return folds


def _build_feature_snapshot_v2(
    *, strategy: dict[str, object], universe: dict[str, object], ready_input: dict[str, object],
    readiness: dict[str, object],
) -> dict[str, object]:
    bars = ready_input.get("research_bars")
    development = strategy.get("development_window")
    prediction = strategy.get("prediction_window")
    target = strategy.get("target")
    validation_plan = strategy.get("validation_plan")
    if not all(isinstance(item, dict) for item in (development, prediction, target, validation_plan)):
        raise ValueError("ML v2 feature input is incomplete")
    if not isinstance(bars, list) or len(bars) > MAX_ROWS:
        raise ValueError("ML feature input is unavailable or exceeds 2000000 rows")
    horizon = int(target["parameters"]["horizon_sessions"])
    by_symbol: dict[str, dict[str, dict[str, object]]] = {}
    all_dates: set[str] = set()
    allowed_symbols = set(universe.get("symbols", []))
    for raw in bars:
        if not isinstance(raw, dict):
            raise ValueError("ML research bars must be objects")
        symbol, session = str(raw.get("symbol")), str(raw.get("trade_date"))
        if raw.get("is_universe_member") is False or symbol not in allowed_symbols:
            continue
        if session in by_symbol.setdefault(symbol, {}):
            raise ValueError("ML research bars contain duplicate symbol/session")
        by_symbol[symbol][session] = raw
        all_dates.add(session)
    dates = sorted(all_dates)
    development_sessions = [
        item for item in dates if str(development["start"]) <= item <= str(development["end"])
    ]
    folds = generate_walk_forward_folds(
        development_sessions, validation_plan, horizon_sessions=horizon
    )
    rows: list[dict[str, object]] = []
    excluded = {"warmup_or_missing": 0, "label_outside_development": 0, "non_finite": 0}
    for symbol in sorted(by_symbol):
        symbol_bars = by_symbol[symbol]
        for index, session in enumerate(dates):
            split_name = None
            if str(development["start"]) <= session <= str(development["end"]):
                split_name = "development"
            elif str(prediction["start"]) <= session <= str(prediction["end"]):
                split_name = "prediction"
            if split_name is None or index < 20:
                continue
            required_dates = [dates[index - offset] for offset in range(21)]
            if any(item not in symbol_bars for item in required_dates):
                excluded["warmup_or_missing"] += 1
                continue
            try:
                closes = [float(symbol_bars[item]["close"]) for item in required_dates]
                volumes = [float(symbol_bars[dates[index - offset]].get("volume") or 0) for offset in range(5)]
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
                "session": session, "symbol": symbol, "split": split_name,
                "feature_as_of": session, "features": features,
            }
            if split_name == "development":
                future_index = index + horizon
                if (
                    future_index >= len(dates)
                    or dates[future_index] > str(development["end"])
                    or dates[future_index] not in symbol_bars
                ):
                    excluded["label_outside_development"] += 1
                    continue
                target_value = float(symbol_bars[dates[future_index]]["close"]) / current - 1.0
                if not math.isfinite(target_value):
                    excluded["non_finite"] += 1
                    continue
                row.update({"target": target_value, "label_end_date": dates[future_index]})
            rows.append(row)
    rows.sort(key=lambda item: (str(item["session"]), str(item["symbol"])))
    counts = {
        name: sum(row["split"] == name for row in rows) for name in ("development", "prediction")
    }
    if counts["development"] < 20 or counts["prediction"] < 1:
        raise ValueError("ML v2 feature snapshot has insufficient development or prediction rows")
    candidate_count = len(rows) + sum(excluded.values())
    document: dict[str, object] = {
        "schema_version": "ml-feature-snapshot.v2",
        "feature_set": strategy["feature_set"], "feature_order": FEATURE_ORDER,
        "target": target, "validation_plan": validation_plan,
        "development_window": development, "prediction_window": prediction,
        "folds": folds, "universe": universe, "rows": rows, "counts": counts,
        "symbol_counts": {
            name: len({str(row["symbol"]) for row in rows if row["split"] == name})
            for name in ("development", "prediction")
        },
        "coverage": {
            "usable_rows": len(rows), "candidate_rows": candidate_count,
            "usable_ratio": len(rows) / candidate_count if candidate_count else 0.0,
        },
        "excluded": excluded,
        "source": {
            "ready_input_sha256": readiness.get("ready_input_sha256"),
            "research_view_sha256": ready_input.get("research_view_sha256"),
        },
    }
    regime = strategy.get("regime")
    if isinstance(regime, dict) and regime.get("enabled") is True:
        document["regime_snapshot"] = build_regime_snapshot(
            strategy=strategy,
            sessions=[str(row["session"]) for row in rows],
            benchmark_rows=ready_input.get("benchmark"),
            ready_input_sha256=readiness.get("ready_input_sha256"),
        )
        validate_regime_snapshot(document["regime_snapshot"])
    document["content_sha256"] = content_sha256(document)
    if len(_canonical(document)) > MAX_INPUT_BYTES:
        raise ValueError("ML feature snapshot exceeds 256 MiB")
    return document


def build_feature_snapshot(
    *, strategy: dict[str, object], universe: dict[str, object], ready_input: dict[str, object],
    readiness: dict[str, object],
) -> dict[str, object]:
    """Build the closed five-feature panel without crossing split boundaries."""
    if strategy.get("schema_version") == ML_V2_SCHEMA:
        return _build_feature_snapshot_v2(
            strategy=strategy, universe=universe, ready_input=ready_input, readiness=readiness
        )
    bars = ready_input.get("research_bars")
    split = strategy.get("split")
    target = strategy.get("target")
    if not isinstance(bars, list) or not isinstance(split, dict) or not isinstance(target, dict):
        raise ValueError("ML feature input is incomplete")
    if len(bars) > MAX_ROWS:
        raise ValueError("ML feature input exceeds 2000000 rows")
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
        raise ValueError("ML feature snapshot exceeds 256 MiB")
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
        """CREATE INDEX IF NOT EXISTS ml_training_runs_study_catalog
            ON ml_training_runs(workspace_id, owner_principal, ml_strategy_artifact_id, created_at DESC)""",
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
            # Serialize the study lifecycle with a concurrent Product delete and
            # re-check its current authoritative status inside this transaction.
            execute(
                connection,
                "SELECT pg_advisory_xact_lock(hashtext(:study_lock))",
                {"study_lock": f"ml-study|{workspace}|{owner}|{strategy}"},
            )
            study = fetch_one(
                connection,
                """SELECT status FROM artifacts WHERE artifact_id=:strategy
                   AND owner_principal=:owner AND workspace_id=:workspace
                   AND kind='ml_strategy_version'""",
                {"strategy": strategy, "owner": owner, "workspace": workspace},
            )
            if study is None or study["status"] != "validated":
                raise MLTrainingConflict("ML strategy is not available for training")
            # Serialize equivalent active submissions independently of the caller's
            # transport idempotency key.  Browser retries and Agent retries may use
            # different keys after an outcome-unknown timeout, but they must still
            # converge on one authoritative active run.
            semantic_lock = "|".join((workspace, owner, task, strategy, pool))
            execute(
                connection,
                "SELECT pg_advisory_xact_lock(hashtext(:semantic_lock))",
                {"semantic_lock": semantic_lock},
            )
            equivalent = fetch_one(connection, """SELECT * FROM ml_training_runs
                WHERE workspace_id=:workspace AND owner_principal=:owner
                AND task_id=:task AND ml_strategy_artifact_id=:strategy
                AND stock_pool_snapshot_id=:pool
                AND status IN ('waiting_for_data','queued','running')
                ORDER BY created_at,training_run_id LIMIT 1""", {
                    "workspace": workspace, "owner": owner, "task": task,
                    "strategy": strategy, "pool": pool,
                })
            if equivalent is not None:
                return self._public(equivalent)
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

    def get_by_idempotency(
        self, idempotency_key: object, *, trusted_workspace: str, trusted_owner: str,
    ) -> dict[str, object]:
        key = _text(idempotency_key, "idempotency_key")
        row = self._fetch_one(
            """SELECT * FROM ml_training_runs WHERE workspace_id=:workspace
               AND owner_principal=:owner AND idempotency_key=:key""",
            {"workspace": trusted_workspace, "owner": trusted_owner, "key": key},
        )
        if row is None:
            raise MLTrainingNotFound("ML training run not found")
        return self._public(row)

    def list_runs(
        self, *, trusted_workspace: str, trusted_owner: str,
        strategy_artifact_id: str | None = None, limit: int = 100, offset: int = 0,
    ) -> dict[str, object]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be non-negative")
        params: dict[str, object] = {
            "workspace": trusted_workspace, "owner": trusted_owner,
            "limit": limit, "offset": offset,
        }
        strategy_clause = ""
        if strategy_artifact_id is not None:
            params["strategy"] = _identifier(strategy_artifact_id, "ml_strategy_artifact_id")
            strategy_clause = "AND ml_strategy_artifact_id=:strategy"
        rows = self._execute("""SELECT training_run_id,workspace_id,owner_principal,task_id,experiment_id,
            ml_strategy_artifact_id,stock_pool_snapshot_id,status,readiness_json,input_sha256,trace_id,
            attempt_count,max_attempts,worker_id,lease_expires_at,feature_artifact_id,model_artifact_id,
            error_code,error_detail,created_at,started_at,finished_at,updated_at FROM ml_training_runs
            WHERE workspace_id=:workspace AND owner_principal=:owner """ + strategy_clause + """
            ORDER BY created_at DESC,training_run_id DESC LIMIT :limit OFFSET :offset""", params)
        total_row = self._fetch_one(
            "SELECT COUNT(*) AS total FROM ml_training_runs WHERE workspace_id=:workspace "
            "AND owner_principal=:owner " + strategy_clause,
            params,
        )
        total = int(total_row["total"] if total_row else 0)
        return {"runs": [self._public(row) for row in rows], "total": total,
                "limit": limit, "offset": offset, "has_more": offset + limit < total}

    def list_recent(self, limit: int = 50) -> list[dict[str, object]]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        rows = self._execute("""SELECT training_run_id,workspace_id,owner_principal,task_id,experiment_id,
            ml_strategy_artifact_id,stock_pool_snapshot_id,status,readiness_json,input_sha256,trace_id,
            attempt_count,max_attempts,worker_id,lease_expires_at,feature_artifact_id,model_artifact_id,
            error_code,error_detail,created_at,started_at,finished_at,updated_at FROM ml_training_runs
            ORDER BY created_at DESC,training_run_id DESC LIMIT :limit""", {"limit": limit})
        return [self._public(row) for row in rows]

    def list_agent_notifications(
        self, *, trusted_workspace: str, trusted_owner: str, limit: int = 10,
    ) -> list[dict[str, object]]:
        """Return a bounded, row-free progress inbox for the next Agent turn."""
        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        rows = self._execute("""SELECT training_run_id,task_id,ml_strategy_artifact_id,
            stock_pool_snapshot_id,status,attempt_count,max_attempts,error_code,error_detail,
            model_artifact_id,created_at,started_at,finished_at,updated_at
            FROM ml_training_runs WHERE workspace_id=:workspace AND owner_principal=:owner
            ORDER BY updated_at DESC,training_run_id DESC LIMIT :limit""", {
                "workspace": trusted_workspace, "owner": trusted_owner, "limit": limit,
            })
        labels = {
            "waiting_for_data": "训练数据准备中",
            "queued": "训练已排队",
            "running": "模型训练中",
            "completed": "模型训练已完成",
            "failed": "模型训练失败",
            "cancelled": "模型训练已取消",
        }
        return [{
            "kind": "ml_training_progress",
            "notification_id": f"ml-training:{row['training_run_id']}:{row['updated_at']}",
            "training_run_id": row["training_run_id"],
            "task_id": row["task_id"],
            "ml_strategy_artifact_id": row["ml_strategy_artifact_id"],
            "stock_pool_snapshot_id": row["stock_pool_snapshot_id"],
            "status": row["status"],
            "notification": labels.get(str(row["status"]), "模型训练状态已更新"),
            "attempt_count": row["attempt_count"],
            "max_attempts": row["max_attempts"],
            "model_artifact_id": row.get("model_artifact_id"),
            "error_code": row.get("error_code"),
            "safe_error": row.get("error_detail"),
            "created_at": row["created_at"],
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "updated_at": row["updated_at"],
        } for row in rows]

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

    def fail_waiting(self, run_id: str, code: str, detail: str) -> None:
        self._execute("""UPDATE ml_training_runs SET status='failed',error_code=:code,
            error_detail=:detail,finished_at=now(),updated_at=now()
            WHERE training_run_id=:id AND status='waiting_for_data'""",
            {"code": _text(code, "error_code", 64),
             "detail": _text(detail, "error_detail", 500), "id": run_id})

    def promote_ready(self, run_id: str, feature_snapshot: dict[str, object]) -> dict[str, object]:
        expected = feature_snapshot.get("content_sha256")
        body = dict(feature_snapshot)
        body.pop("content_sha256", None)
        if expected != content_sha256(body):
            raise ValueError("ML feature snapshot identity does not match content")
        if len(_canonical(feature_snapshot)) > MAX_INPUT_BYTES:
            raise ValueError("ML training input exceeds 256 MiB")
        input_sha256 = feature_snapshot.get("snapshot_sha256", expected)
        if not isinstance(input_sha256, str):
            raise ValueError("ML training input identity is unavailable")
        self._execute("""UPDATE ml_training_runs SET status='queued',input_json=:input,
            input_sha256=:sha,updated_at=:now WHERE training_run_id=:id AND status='waiting_for_data'""",
            {"input": feature_snapshot, "sha": input_sha256, "now": _now(), "id": run_id})
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

    def retry_failed(self, run_id: object) -> dict[str, object]:
        identity = _identifier(run_id, "training_run_id")
        row = self._fetch_one("""UPDATE ml_training_runs SET status='queued',worker_id=NULL,
            lease_expires_at=NULL,error_code=NULL,error_detail=NULL,finished_at=NULL,updated_at=now()
            WHERE training_run_id=:id AND status='failed' AND input_json IS NOT NULL
            AND attempt_count<max_attempts RETURNING *""", {"id": identity})
        if row is None:
            raise MLTrainingConflict("ML training run is not retryable")
        return self._public(row)

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


def promote_waiting_training_runs(
    store: MLTrainingRunStore, readiness_store: object,
    objects: LocalObjectStore | None = None, *, max_promotions: int = 1,
) -> int:
    """Prepare at most one large ready run per worker turn.

    Readiness checks stay cheap and bounded, while feature materialisation is
    deliberately serialized so several waiting runs cannot coexist in memory.
    When an object store is available only a bounded descriptor is retained in
    PostgreSQL; the large row payload remains in the immutable ML object store.
    """
    if max_promotions < 1:
        raise ValueError("max_promotions must be positive")
    promoted = 0
    for row in store.list_waiting():
        requirement, preparation = row.get("requirement_json"), row.get("preparation_json")
        if not isinstance(requirement, dict) or not isinstance(preparation, dict):
            continue
        run_id = str(row["training_run_id"])
        try:
            raw_requirements = preparation.get("requirements", [requirement])
            if not isinstance(raw_requirements, list) or not raw_requirements or any(
                not isinstance(item, dict) for item in raw_requirements
            ):
                raise ValueError("ML data preparation partition plan is invalid")
            requirements = [dict(item) for item in raw_requirements]
            assessments = [readiness_store.assess(item) for item in requirements]
            readiness = aggregate_ml_readiness(assessments)
            store.update_readiness(run_id, readiness)
            if readiness["state"] != "ready":
                continue
            ready_input = (
                readiness_store.build_partitioned_ready_input(requirements)
                if len(requirements) > 1 else readiness_store.build_ready_input(requirement)
            )
            strategy, universe = preparation.get("strategy"), preparation.get("universe")
            if not isinstance(strategy, dict) or not isinstance(universe, dict):
                raise ValueError("ML preparation snapshot is invalid")
            feature_snapshot = build_feature_snapshot(
                strategy=strategy, universe=universe, ready_input=ready_input, readiness=readiness
            )
            del ready_input
            persisted_input = (
                store_feature_snapshot(feature_snapshot, objects)
                if objects is not None else feature_snapshot
            )
            store.promote_ready(run_id, persisted_input)
            promoted += 1
            if promoted >= max_promotions:
                break
        except Exception as error:
            store.fail_waiting(
                run_id, "ml_data_preparation_failed",
                str(error)[:500] or "ML data preparation failed",
            )
    return promoted


class MLTrainingCoordinator:
    def __init__(
        self, runs: MLTrainingRunStore, research: ResearchStore, objects: LocalObjectStore,
        trainer: MLTrainer, *, worker_id: str,
    ) -> None:
        self.runs, self.research, self.objects, self.trainer = runs, research, objects, trainer
        self.worker_id = worker_id

    @staticmethod
    def _encoded_result(
        result: dict[str, object], strategy: dict[str, object],
    ) -> tuple[bytes, str, str, str]:
        model_text = result.pop("model_text", None)
        model_bytes = result.pop("model_bytes", None)
        if isinstance(model_text, str) and model_text:
            encoded_model = model_text.encode("utf-8")
        elif isinstance(model_bytes, bytes) and model_bytes:
            encoded_model = model_bytes
        else:
            raise ValueError("ML trainer returned no qualified model")
        if len(encoded_model) > model_size_limit_for_profile(learner_profile(strategy)):
            raise ValueError("ML trainer model exceeds the qualified size limit")
        if result.get("runtime_identity") != expected_runtime_identity(strategy):
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
        model_format = str(result.get("model_format") or "lightgbm-text-v1")
        if model_format not in {"lightgbm-text-v1", "ridge-linear-json-v1"}:
            raise ValueError("ML trainer model format is not qualified")
        return encoded_model, model_format, image_identity, str(
            result.get("media_type") or "text/x-lightgbm-model"
        )

    def _create_validated_artifact(
        self, *, job: dict[str, object], kind: str, content: dict[str, object],
        lineage: list[dict[str, object]], key_prefix: str,
    ) -> dict[str, object]:
        artifact_hash = content_sha256(content)
        artifact = self.research.find_artifact_by_content(str(job["task_id"]), kind, artifact_hash)
        if artifact is None:
            artifact = self.research.create_artifact({
                "task_id": job["task_id"], "experiment_id": job.get("experiment_id"),
                "kind": kind, "content": content, "lineage": lineage,
                "trace_id": job["trace_id"],
                "idempotency_key": f"{key_prefix}-{artifact_hash}",
            })
        if artifact["status"] == "draft":
            artifact = self.research.transition(
                "artifact", artifact["artifact_id"], "validated",
                f"{key_prefix}-validate-{artifact_hash[:24]}",
            )
        return artifact

    def _complete_regime_bundle(
        self, *, job: dict[str, object], feature: dict[str, object], strategy: dict[str, object],
        expert_results: list[object],
    ) -> dict[str, object]:
        run_id = str(job["training_run_id"])
        regime = validate_regime_snapshot(feature.get("regime_snapshot"))
        regime_artifact = self._create_validated_artifact(
            job=job, kind="ml_regime_snapshot", content=regime,
            lineage=[
                {"kind": "artifact", "id": job["ml_strategy_artifact_id"]},
                {"kind": "stock_pool_snapshot", "id": job["stock_pool_snapshot_id"]},
                {"kind": "ml_training_run", "id": run_id},
            ], key_prefix="ml-regime",
        )
        stored_feature = store_feature_snapshot(feature, self.objects)
        feature_hash = str(stored_feature["content_sha256"])
        feature_artifact = self._create_validated_artifact(
            job=job, kind="ml_feature_snapshot", content=stored_feature,
            lineage=[
                {"kind": "artifact", "id": job["ml_strategy_artifact_id"]},
                {"kind": "artifact", "id": regime_artifact["artifact_id"]},
                {"kind": "stock_pool_snapshot", "id": job["stock_pool_snapshot_id"]},
                {"kind": "ml_training_run", "id": run_id},
            ], key_prefix="ml-feature",
        )
        configured = {
            str(item["key"]): item for item in strategy.get("experts", []) if isinstance(item, dict)
        }
        if not 2 <= len(expert_results) <= 4 or len(expert_results) != len(configured):
            raise ValueError("ML trainer returned an invalid expert result count")
        bundle_experts: list[dict[str, object]] = []
        expert_lineage: list[dict[str, object]] = []
        seen: set[str] = set()
        for raw_result in expert_results:
            if not isinstance(raw_result, dict):
                raise ValueError("ML trainer expert result is invalid")
            result = dict(raw_result)
            key = str(result.pop("expert_key", ""))
            training_regimes = result.pop("training_regimes", None)
            expert = configured.get(key)
            if expert is None or key in seen or training_regimes != expert.get("training_regimes"):
                raise ValueError("ML trainer expert result does not match the frozen strategy")
            seen.add(key)
            expert_strategy = dict(strategy)
            expert_strategy["learner"] = expert["learner"]
            profile = str(expert["learner"]["profile"])
            if result.get("learner_profile") != profile:
                raise ValueError("ML trainer expert profile does not match the frozen strategy")
            encoded_model, model_format, image_identity, media_type = self._encoded_result(
                result, expert_strategy
            )
            reference = self.objects.put("ml-models", encoded_model, media_type=media_type)
            model_content: dict[str, object] = {
                "schema_version": "ml-model-artifact.v2",
                "model_format": model_format, "object_reference": reference,
                "runtime_lock": runtime_lock_for_profile(profile),
                "runtime_identity": result.get("runtime_identity"), "image_identity": image_identity,
                "feature_order": result.get("feature_order", FEATURE_ORDER),
                "target": feature.get("target"), "feature_snapshot_artifact_id": feature_artifact["artifact_id"],
                "feature_snapshot_sha256": feature_hash,
                "strategy_version_artifact_id": job["ml_strategy_artifact_id"],
                "stock_pool_snapshot_id": job["stock_pool_snapshot_id"], "training_run_id": run_id,
                "learner_profile": profile, "expert_key": key,
                "training_regimes": training_regimes,
                "regime_snapshot_artifact_id": regime_artifact["artifact_id"],
                "regime_snapshot_sha256": regime["content_sha256"],
                "effective_parameters": result.get("effective_parameters"),
                "best_iteration": result.get("best_iteration"), "metrics": result.get("metrics"),
                "validation_plan": feature.get("validation_plan"), "folds": result.get("folds"),
                "selection_rule": result.get("selection_rule"), "capability_lock": strategy.get("capability_lock"),
                "development_window": feature.get("development_window"),
                "prediction_window": feature.get("prediction_window"),
                "counts": {"rows": feature.get("counts"), "symbols": feature.get("symbol_counts")},
                "coverage": feature.get("coverage"),
            }
            model_content["content_sha256"] = content_sha256(model_content)
            model_artifact = self._create_validated_artifact(
                job=job, kind="ml_model", content=model_content,
                lineage=[
                    {"kind": "artifact", "id": job["ml_strategy_artifact_id"]},
                    {"kind": "artifact", "id": feature_artifact["artifact_id"]},
                    {"kind": "artifact", "id": regime_artifact["artifact_id"]},
                    {"kind": "stock_pool_snapshot", "id": job["stock_pool_snapshot_id"]},
                    {"kind": "ml_training_run", "id": run_id},
                ], key_prefix=f"ml-model-{key}",
            )
            expert_lineage.append({"kind": "artifact", "id": model_artifact["artifact_id"]})
            bundle_experts.append({
                "key": key, "training_regimes": training_regimes,
                "model_artifact_id": model_artifact["artifact_id"],
                "model_content_sha256": model_content["content_sha256"],
                "learner_profile": profile,
                "folds_sha256": content_sha256(result.get("folds")),
            })
        bundle_experts.sort(key=lambda item: str(item["key"]))
        bundle_content: dict[str, object] = {
            "schema_version": BUNDLE_SCHEMA,
            "strategy_version_artifact_id": job["ml_strategy_artifact_id"],
            "feature_snapshot_artifact_id": feature_artifact["artifact_id"],
            "feature_snapshot_sha256": feature_hash,
            "regime_snapshot_artifact_id": regime_artifact["artifact_id"],
            "regime_snapshot_sha256": regime["content_sha256"],
            "stock_pool_snapshot_id": job["stock_pool_snapshot_id"],
            "training_run_id": run_id,
            "routing_policy": strategy["routing_policy"],
            "experts": bundle_experts,
            "capability_lock": strategy.get("capability_lock"),
            "prediction_window": feature.get("prediction_window"),
        }
        bundle_content["content_sha256"] = content_sha256(bundle_content)
        validate_model_bundle(bundle_content)
        bundle_artifact = self._create_validated_artifact(
            job=job, kind="ml_model_bundle", content=bundle_content,
            lineage=[
                {"kind": "artifact", "id": job["ml_strategy_artifact_id"]},
                {"kind": "artifact", "id": feature_artifact["artifact_id"]},
                {"kind": "artifact", "id": regime_artifact["artifact_id"]},
                *expert_lineage,
                {"kind": "stock_pool_snapshot", "id": job["stock_pool_snapshot_id"]},
                {"kind": "ml_training_run", "id": run_id},
            ], key_prefix="ml-bundle",
        )
        return self.runs.complete(
            run_id, feature_artifact_id=str(feature_artifact["artifact_id"]),
            model_artifact_id=str(bundle_artifact["artifact_id"]),
            worker_id=str(job["worker_id"]), attempt_count=int(job["attempt_count"]),
        )

    def run_next(self) -> dict[str, object] | None:
        job = self.runs.claim_next(self.worker_id)
        if job is None:
            return None
        run_id = str(job["training_run_id"])
        try:
            feature_input = job.get("input")
            preparation = job.get("preparation")
            if not isinstance(feature_input, dict) or not isinstance(preparation, dict):
                raise ValueError("ML training input is unavailable")
            feature = load_feature_snapshot(feature_input, self.objects)
            strategy = preparation.get("strategy")
            if not isinstance(strategy, dict):
                raise ValueError("ML strategy snapshot is unavailable")
            result = self.trainer.train(feature, strategy)
            expert_results = result.get("expert_results") if isinstance(result, dict) else None
            if expert_results is not None:
                if not isinstance(expert_results, list):
                    raise ValueError("ML trainer expert results are invalid")
                return self._complete_regime_bundle(
                    job=job, feature=feature, strategy=strategy, expert_results=expert_results,
                )
            model_text = result.pop("model_text", None)
            model_bytes = result.pop("model_bytes", None)
            is_v2 = strategy.get("schema_version") == ML_V2_SCHEMA
            if isinstance(model_text, str) and model_text:
                encoded_model = model_text.encode("utf-8")
            elif is_v2 and isinstance(model_bytes, bytes) and model_bytes:
                encoded_model = model_bytes
            else:
                raise ValueError("ML trainer returned no qualified model")
            if len(encoded_model) > 32 * 1024 * 1024:
                raise ValueError("ML trainer model exceeds the qualified size limit")
            if result.get("runtime_identity") != expected_runtime_identity(strategy):
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
            model_format = str(result.get("model_format") or "lightgbm-text-v1")
            if model_format not in {"lightgbm-text-v1", "ridge-linear-json-v1"}:
                raise ValueError("ML trainer model format is not qualified")
            reference = self.objects.put(
                "ml-models", encoded_model,
                media_type=str(result.get("media_type") or "text/x-lightgbm-model"),
            )
            stored_feature = store_feature_snapshot(feature, self.objects)
            feature_hash = str(stored_feature["content_sha256"])
            feature_artifact_hash = content_sha256(stored_feature)
            feature_artifact = self.research.find_artifact_by_content(
                str(job["task_id"]), "ml_feature_snapshot", feature_artifact_hash
            )
            if feature_artifact is None:
                feature_artifact = self.research.create_artifact({
                    "task_id": job["task_id"], "experiment_id": job.get("experiment_id"),
                    "kind": "ml_feature_snapshot", "content": stored_feature,
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
                "schema_version": "ml-model-artifact.v2" if is_v2 else MODEL_SCHEMA,
                "model_format": model_format,
                "object_reference": reference,
                "runtime_lock": strategy.get("runtime_lock") if is_v2 else RUNTIME_LOCK,
                "runtime_identity": result.get("runtime_identity"),
                "image_identity": image_identity,
                "feature_order": result.get("feature_order", FEATURE_ORDER),
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
            if is_v2:
                model_content.update({
                    "learner_profile": result.get("learner_profile"),
                    "validation_plan": feature.get("validation_plan"),
                    "folds": result.get("folds"),
                    "selection_rule": result.get("selection_rule"),
                    "capability_lock": strategy.get("capability_lock"),
                    "development_window": feature.get("development_window"),
                    "prediction_window": feature.get("prediction_window"),
                })
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
