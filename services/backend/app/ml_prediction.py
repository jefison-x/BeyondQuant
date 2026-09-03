"""Durable out-of-sample inference and frozen ML signal production."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy.exc import SQLAlchemyError

from .backtest import LocalObjectStore, membership_fingerprint, normalize_signal_snapshot, signal_snapshot_content_sha256
from .db import PgStoreMixin, execute, fetch_one
from .ml_strategy import FEATURE_ORDER, RUNTIME_LOCK, content_sha256, validate_ml_strategy_version
from .ml_capabilities import (
    STRATEGY_SCHEMA as ML_V2_SCHEMA,
    expected_runtime_identity,
    runtime_lock_for_profile,
)
from .ml_regime import (
    BUNDLE_SCHEMA,
    expert_key_for,
    validate_model_bundle,
    validate_regime_snapshot,
)
from .ml_training import (
    FEATURE_SCHEMA,
    MODEL_SCHEMA,
    RUNTIME_IDENTITY,
    aggregate_ml_readiness,
    load_feature_snapshot,
)
from .research import ResearchStore


PREDICTION_SCHEMA = "ml-prediction-snapshot.v1"
PREDICTION_SCHEMA_V2 = "ml-prediction-snapshot.v2"
PREDICTION_RUN_SCHEMA = "ml-prediction-run.v1"
MAX_ATTEMPTS = 3


class MLPredictionError(RuntimeError):
    pass


class MLPredictionNotFound(MLPredictionError):
    pass


class MLPredictionConflict(MLPredictionError):
    pass


class MLPredictionPersistenceError(MLPredictionError):
    pass


class MLPredictor(Protocol):
    def predict(self, model_text: str, rows: list[dict[str, object]], *, best_iteration: int) -> list[float]: ...


class MLPredictionMarketData(Protocol):
    def assess(self, requirement: dict[str, object]) -> dict[str, object]: ...
    def build_ready_input(self, requirement: dict[str, object]) -> dict[str, object]: ...
    def build_partitioned_ready_input(
        self, requirements: list[dict[str, object]],
    ) -> dict[str, object]: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    except (TypeError, ValueError) as error:
        raise ValueError("ML prediction input must be finite JSON") from error


def _text(value: object, field: str, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{field} must be a non-empty string of at most {maximum} characters")
    return value.strip()


def _identifier(value: object, field: str) -> str:
    value = _text(value, field)
    if not value.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"{field} has invalid format")
    return value


def _verify_embedded_hash(document: dict[str, object], field: str) -> str:
    expected = document.get("content_sha256")
    body = dict(document)
    body.pop("content_sha256", None)
    if not isinstance(expected, str) or expected != content_sha256(body):
        raise ValueError(f"{field} identity does not match content")
    return expected


def build_prediction_snapshot(
    *, scores: list[float], prediction_rows: list[dict[str, object]], model: dict[str, object],
    feature_artifact_id: str, model_artifact_id: str, stock_pool_snapshot_id: str,
) -> dict[str, object]:
    if len(scores) != len(prediction_rows) or not scores:
        raise ValueError("prediction output row count does not match frozen prediction input")
    grouped: dict[str, list[tuple[str, float]]] = {}
    for row, raw_score in zip(prediction_rows, scores, strict=True):
        if set(row) != {"session", "symbol", "split", "feature_as_of", "features"}:
            raise ValueError("prediction split rows must not contain labels or undeclared fields")
        if row.get("split") != "prediction" or row.get("feature_as_of") != row.get("session"):
            raise ValueError("prediction row violates the point-in-time split contract")
        features = row.get("features")
        if not isinstance(features, dict) or set(features) != set(FEATURE_ORDER):
            raise ValueError("prediction row feature set is invalid")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in features.values()):
            raise ValueError("prediction row contains non-finite features")
        score = float(raw_score)
        if not math.isfinite(score):
            raise ValueError("prediction output contains a non-finite score")
        grouped.setdefault(str(row["session"]), []).append((str(row["symbol"]), score))
    rows: list[dict[str, object]] = []
    for session in sorted(grouped):
        ranked = sorted(grouped[session], key=lambda item: (-item[1], item[0]))
        rows.extend(
            {"session": session, "symbol": symbol, "score": score, "rank": rank}
            for rank, (symbol, score) in enumerate(ranked, 1)
        )
    document: dict[str, object] = {
        "schema_version": PREDICTION_SCHEMA,
        "model_artifact_id": model_artifact_id,
        "model_content_sha256": model["content_sha256"],
        "feature_snapshot_artifact_id": feature_artifact_id,
        "feature_snapshot_sha256": model["feature_snapshot_sha256"],
        "stock_pool_snapshot_id": stock_pool_snapshot_id,
        "prediction_split": model["split"]["prediction"],
        "runtime_lock": RUNTIME_LOCK,
        "runtime_identity": RUNTIME_IDENTITY,
        "rows": rows,
        "counts": {
            "rows": len(rows), "sessions": len(grouped),
            "symbols": len({str(row["symbol"]) for row in rows}),
        },
    }
    document["content_sha256"] = content_sha256(document)
    return document


def build_routed_prediction_snapshot(
    *, scored_rows: list[dict[str, object]], feature_artifact_id: str,
    feature_snapshot_sha256: str, model_bundle_artifact_id: str,
    model_bundle_sha256: str, regime_snapshot_artifact_id: str,
    regime_snapshot_sha256: str, stock_pool_snapshot_id: str,
    prediction_window: dict[str, object], capability_lock: object,
) -> dict[str, object]:
    if not scored_rows:
        raise ValueError("routed prediction has no rows")
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    required = {
        "session", "symbol", "score", "regime", "regime_snapshot_id",
        "expert_key", "model_artifact_id",
    }
    for raw in scored_rows:
        if set(raw) != required:
            raise ValueError("routed prediction row contract is invalid")
        score = raw.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)):
            raise ValueError("routed prediction score is invalid")
        grouped.setdefault((str(raw["session"]), str(raw["expert_key"])), []).append(dict(raw))
    rows: list[dict[str, object]] = []
    for group in sorted(grouped):
        ranked = sorted(grouped[group], key=lambda item: (-float(item["score"]), str(item["symbol"])))
        for rank, row in enumerate(ranked, 1):
            rows.append({**row, "score": float(row["score"]), "rank": rank})
    document: dict[str, object] = {
        "schema_version": PREDICTION_SCHEMA_V2,
        "mode": "regime_routed",
        "model_bundle_artifact_id": model_bundle_artifact_id,
        "model_bundle_sha256": model_bundle_sha256,
        "regime_snapshot_artifact_id": regime_snapshot_artifact_id,
        "regime_snapshot_sha256": regime_snapshot_sha256,
        "feature_snapshot_artifact_id": feature_artifact_id,
        "feature_snapshot_sha256": feature_snapshot_sha256,
        "stock_pool_snapshot_id": stock_pool_snapshot_id,
        "prediction_window": prediction_window,
        "capability_lock": capability_lock,
        "rows": rows,
        "counts": {
            "rows": len(rows), "sessions": len({str(row["session"]) for row in rows}),
            "symbols": len({str(row["symbol"]) for row in rows}),
            "experts": len({str(row["expert_key"]) for row in rows}),
        },
    }
    document["content_sha256"] = content_sha256(document)
    return document


def build_single_prediction_snapshot_v2(
    *, scores: list[float], prediction_rows: list[dict[str, object]], model: dict[str, object],
    feature_artifact_id: str, model_artifact_id: str, stock_pool_snapshot_id: str,
) -> dict[str, object]:
    if len(scores) != len(prediction_rows) or not scores:
        raise ValueError("prediction output row count does not match frozen prediction input")
    grouped: dict[str, list[tuple[str, float]]] = {}
    for row, raw_score in zip(prediction_rows, scores, strict=True):
        if set(row) != {"session", "symbol", "split", "feature_as_of", "features"}:
            raise ValueError("prediction split rows must not contain labels or undeclared fields")
        if row.get("split") != "prediction" or row.get("feature_as_of") != row.get("session"):
            raise ValueError("prediction row violates the point-in-time split contract")
        score = float(raw_score)
        if not math.isfinite(score):
            raise ValueError("prediction output contains a non-finite score")
        grouped.setdefault(str(row["session"]), []).append((str(row["symbol"]), score))
    rows: list[dict[str, object]] = []
    for session in sorted(grouped):
        rows.extend(
            {"session": session, "symbol": symbol, "score": score, "rank": rank}
            for rank, (symbol, score) in enumerate(
                sorted(grouped[session], key=lambda item: (-item[1], item[0])), 1
            )
        )
    document: dict[str, object] = {
        "schema_version": PREDICTION_SCHEMA_V2, "mode": "single",
        "model_artifact_id": model_artifact_id, "model_content_sha256": model["content_sha256"],
        "feature_snapshot_artifact_id": feature_artifact_id,
        "feature_snapshot_sha256": model["feature_snapshot_sha256"],
        "stock_pool_snapshot_id": stock_pool_snapshot_id,
        "prediction_window": model["prediction_window"],
        "runtime_lock": model["runtime_lock"], "runtime_identity": model["runtime_identity"],
        "rows": rows,
        "counts": {"rows": len(rows), "sessions": len(grouped),
                   "symbols": len({str(row["symbol"]) for row in rows})},
    }
    document["content_sha256"] = content_sha256(document)
    return document


def _rebalance_sessions(sessions: list[str], cadence: str) -> list[str]:
    if cadence == "daily":
        return sessions
    chosen: dict[str, str] = {}
    for session in sessions:
        parsed = datetime.strptime(session, "%Y-%m-%d")
        key = f"{parsed.isocalendar().year:04d}-W{parsed.isocalendar().week:02d}" if cadence == "weekly" else session[:7]
        chosen[key] = session
    return [chosen[key] for key in sorted(chosen)]


def build_ml_signal_snapshot(
    *, prediction: dict[str, object], strategy: dict[str, object], strategy_artifact_id: str,
    approval_artifact_id: str, feature_artifact_id: str, model_artifact_id: str,
    prediction_artifact_id: str, stock_pool_snapshot_id: str, ready_input: dict[str, object],
    execution: dict[str, object], readiness: dict[str, object],
) -> dict[str, object]:
    raw_policy = strategy.get("portfolio_policy") if strategy.get("schema_version") == ML_V2_SCHEMA else strategy.get("signal_policy")
    if not isinstance(raw_policy, dict):
        raise ValueError("ML signal policy is unsupported")
    if raw_policy.get("id") == "top-n-equal-weight-v1" and isinstance(raw_policy.get("parameters"), dict):
        policy = raw_policy["parameters"]
    elif raw_policy.get("kind") == "top_n_equal_weight":
        policy = raw_policy
    else:
        raise ValueError("ML signal policy is unsupported")
    capital, lot_size = execution.get("initial_capital"), execution.get("lot_size")
    if isinstance(capital, bool) or not isinstance(capital, (int, float)) or not math.isfinite(float(capital)) or float(capital) <= 0:
        raise ValueError("execution.initial_capital must be a positive finite number")
    if isinstance(lot_size, bool) or not isinstance(lot_size, int) or lot_size <= 0:
        raise ValueError("execution.lot_size must be a positive integer")
    rows = prediction.get("rows")
    raw_bars = ready_input.get("bars")
    if not isinstance(rows, list) or not isinstance(raw_bars, list):
        raise ValueError("frozen ML prediction or market bars are unavailable")
    split = prediction.get("prediction_window", prediction.get("prediction_split"))
    if not isinstance(split, dict):
        raise ValueError("ML prediction window is unavailable")
    start, end = str(split["start"]), str(split["end"])
    bars = [dict(row) for row in raw_bars if isinstance(row, dict) and start <= str(row.get("trade_date")) <= end]
    raw_factors = ready_input.get("adjustment_factors", [])
    if not isinstance(raw_factors, list):
        raise ValueError("frozen adjustment factors are invalid")
    factor_by_key = {
        (str(row.get("trade_date")), str(row.get("symbol"))): row.get("adjustment_factor")
        for row in raw_factors if isinstance(row, dict)
    }
    for bar in bars:
        factor = factor_by_key.get((str(bar.get("trade_date")), str(bar.get("symbol"))))
        if factor is not None:
            bar["adjustment_factor"] = factor
    bar_by_key = {(str(row["trade_date"]), str(row["symbol"])): row for row in bars}
    sessions = sorted({str(row["trade_date"]) for row in bars})
    # A signal on the final frozen session has no next-session execution bar.
    eligible = set(_rebalance_sessions(sessions[:-1], str(policy["rebalance"])))
    by_session: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_session.setdefault(str(row["session"]), []).append(row)
    holdings: dict[str, int] = {}
    signals: list[dict[str, object]] = []
    unfunded_lots_skipped = 0
    top_n = int(policy["top_n"])
    for session in sorted(eligible):
        selected = {
            str(row["symbol"]) for row in by_session.get(session, []) if int(row["rank"]) <= top_n
        }
        for symbol in sorted(set(holdings) - selected):
            signals.append({"symbol": symbol, "trade_date": session, "side": "sell", "quantity": holdings.pop(symbol)})
        allocation = float(capital) / len(selected) if selected else 0.0
        for symbol in sorted(selected - set(holdings)):
            bar = bar_by_key.get((session, symbol))
            if bar is None:
                raise ValueError("selected prediction has no frozen execution-price bar")
            quantity = int(allocation / float(bar["close"])) // lot_size * lot_size
            if quantity <= 0:
                unfunded_lots_skipped += 1
                continue
            holdings[symbol] = quantity
            signals.append({"symbol": symbol, "trade_date": session, "side": "buy", "quantity": quantity})
    universe_symbols = sorted({str(row["symbol"]) for row in bars})
    execution_symbols = {str(row["symbol"]) for row in signals}
    if not execution_symbols and universe_symbols:
        # A no-trade snapshot still carries one deterministic price path so it
        # remains a valid, replayable backtest input without freezing the full
        # research universe.
        execution_symbols = {universe_symbols[0]}
    bars = [row for row in bars if str(row["symbol"]) in execution_symbols]
    universe = {
        "universe_id": "ml-frozen-pool", "version_id": stock_pool_snapshot_id,
        "membership_fingerprint": membership_fingerprint(universe_symbols), "symbols": universe_symbols,
    }
    actions = ready_input.get("corporate_actions", [])
    actions = [
        dict(row) for row in actions
        if isinstance(row, dict)
        and str(row.get("symbol")) in execution_symbols
        and start <= str(row.get("ex_date")) <= end
    ]
    return normalize_signal_snapshot(
        {
            "universe": universe, "bars": bars, "signals": signals, "execution": execution,
            "corporate_actions": actions, "benchmark": ready_input.get("benchmark", []),
            "source": {
                "producer": "byq-ml-top-n-v1",
                "selection_constraints": {
                    "unfunded_lots_skipped": unfunded_lots_skipped,
                },
                "data_readiness": {
                    "requirement_sha256": readiness.get("requirement_sha256"),
                    "ready_input_sha256": readiness.get("ready_input_sha256"),
                    "research_view_sha256": ready_input.get("research_view_sha256"),
                },
                "ml_lineage": {
                    "ml_strategy_artifact_id": strategy_artifact_id,
                    "ml_strategy_approval_artifact_id": approval_artifact_id,
                    "model_artifact_id": model_artifact_id,
                    "feature_snapshot_artifact_id": feature_artifact_id,
                    "prediction_snapshot_artifact_id": prediction_artifact_id,
                    "stock_pool_snapshot_id": stock_pool_snapshot_id,
                    "policy_sha256": content_sha256(raw_policy),
                    **({
                        "model_bundle_artifact_id": model_artifact_id,
                        "regime_snapshot_artifact_id": str(prediction["regime_snapshot_artifact_id"]),
                        "routing_policy_sha256": content_sha256(strategy["routing_policy"]),
                    } if prediction.get("mode") == "regime_routed" else {}),
                },
            },
        },
        strategy_version_artifact_id=strategy_artifact_id,
        strategy_version_id=str(strategy["version_id"]),
    )


class MLPredictionRunStore(PgStoreMixin):
    SCHEMA_DDL = [
        """
        CREATE TABLE IF NOT EXISTS ml_prediction_runs (
            prediction_run_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, owner_principal TEXT NOT NULL,
            task_id TEXT NOT NULL, experiment_id TEXT, ml_strategy_artifact_id TEXT NOT NULL,
            approval_artifact_id TEXT NOT NULL, model_artifact_id TEXT NOT NULL,
            feature_artifact_id TEXT NOT NULL, stock_pool_snapshot_id TEXT NOT NULL,
            status TEXT NOT NULL, input_json JSONB NOT NULL, trace_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3, worker_id TEXT, lease_expires_at TIMESTAMPTZ,
            prediction_artifact_id TEXT, signal_artifact_id TEXT, error_code TEXT, error_detail TEXT,
            created_at TIMESTAMPTZ NOT NULL, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL, UNIQUE(workspace_id, idempotency_key)
        )
        """,
        "CREATE INDEX IF NOT EXISTS ml_prediction_runs_queue ON ml_prediction_runs(status,created_at)",
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as error:
            raise MLPredictionPersistenceError("ML prediction storage is unavailable") from error

    @classmethod
    def from_env(cls) -> "MLPredictionRunStore":
        return cls()

    def create(self, *, workspace_id: object, owner_principal: object, task_id: object,
               experiment_id: object | None, ml_strategy_artifact_id: object,
               approval_artifact_id: object, model_artifact_id: object, feature_artifact_id: object,
               stock_pool_snapshot_id: object, input_document: dict[str, object], trace_id: object,
               idempotency_key: object) -> dict[str, object]:
        values = {
            "workspace": _identifier(workspace_id, "workspace_id"), "owner": _text(owner_principal, "owner_principal"),
            "task": _identifier(task_id, "task_id"), "experiment": None if experiment_id is None else _identifier(experiment_id, "experiment_id"),
            "strategy": _identifier(ml_strategy_artifact_id, "ml_strategy_artifact_id"),
            "approval": _identifier(approval_artifact_id, "approval_artifact_id"), "model": _identifier(model_artifact_id, "model_artifact_id"),
            "feature": _identifier(feature_artifact_id, "feature_artifact_id"), "pool": _identifier(stock_pool_snapshot_id, "stock_pool_snapshot_id"),
            "input": input_document, "trace": _text(trace_id, "trace_id"), "key": _text(idempotency_key, "idempotency_key"),
        }
        request_hash = hashlib.sha256(_canonical({key: value for key, value in values.items() if key != "key"})).hexdigest()
        with self._transaction() as connection:
            existing = fetch_one(connection, "SELECT * FROM ml_prediction_runs WHERE workspace_id=:workspace AND idempotency_key=:key", values)
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise MLPredictionConflict("ML prediction idempotency key was reused")
                return self._public(existing)
            values.update({"id": f"mlpred_{uuid.uuid4().hex}", "hash": request_hash, "now": _now()})
            execute(connection, """INSERT INTO ml_prediction_runs
                (prediction_run_id,workspace_id,owner_principal,task_id,experiment_id,ml_strategy_artifact_id,
                 approval_artifact_id,model_artifact_id,feature_artifact_id,stock_pool_snapshot_id,status,input_json,
                 trace_id,idempotency_key,request_hash,created_at,updated_at)
                VALUES (:id,:workspace,:owner,:task,:experiment,:strategy,:approval,:model,:feature,:pool,'queued',
                        :input,:trace,:key,:hash,:now,:now)""", values)
        return self.get(values["id"], trusted_workspace=values["workspace"], trusted_owner=values["owner"])

    def get(self, run_id: object, *, trusted_workspace: str | None = None, trusted_owner: str | None = None) -> dict[str, object]:
        identity = _identifier(run_id, "prediction_run_id")
        row = self._fetch_one("SELECT * FROM ml_prediction_runs WHERE prediction_run_id=:id", {"id": identity})
        if row is None or (trusted_workspace and row["workspace_id"] != trusted_workspace) or (trusted_owner and row["owner_principal"] != trusted_owner):
            raise MLPredictionNotFound("ML prediction run not found")
        return self._public(row)

    def list_runs(self, *, trusted_workspace: str, trusted_owner: str) -> dict[str, object]:
        rows = self._execute("""SELECT prediction_run_id,workspace_id,owner_principal,task_id,experiment_id,
            ml_strategy_artifact_id,approval_artifact_id,model_artifact_id,feature_artifact_id,
            stock_pool_snapshot_id,status,trace_id,attempt_count,max_attempts,worker_id,lease_expires_at,
            prediction_artifact_id,signal_artifact_id,error_code,error_detail,created_at,started_at,
            finished_at,updated_at FROM ml_prediction_runs WHERE workspace_id=:workspace AND owner_principal=:owner
            ORDER BY created_at DESC,prediction_run_id DESC LIMIT 100""", {"workspace": trusted_workspace, "owner": trusted_owner})
        return {"runs": [self._public(row) for row in rows]}

    def claim_next(self, worker_id: str) -> dict[str, object] | None:
        with self._transaction() as connection:
            execute(connection, """UPDATE ml_prediction_runs SET status='queued',worker_id=NULL,lease_expires_at=NULL,updated_at=now()
                WHERE status='running' AND lease_expires_at<now() AND attempt_count<max_attempts""")
            execute(connection, """UPDATE ml_prediction_runs SET status='failed',error_code='attempts_exhausted',
                error_detail='ML prediction attempts exhausted',finished_at=now(),updated_at=now()
                WHERE status='running' AND lease_expires_at<now() AND attempt_count>=max_attempts""")
            row = fetch_one(connection, """SELECT prediction_run_id FROM ml_prediction_runs WHERE status='queued'
                ORDER BY created_at,prediction_run_id FOR UPDATE SKIP LOCKED LIMIT 1""")
            if row is None:
                return None
            claimed = fetch_one(connection, """UPDATE ml_prediction_runs SET status='running',attempt_count=attempt_count+1,
                worker_id=:worker,started_at=COALESCE(started_at,now()),lease_expires_at=now()+interval '5 minutes',updated_at=now()
                WHERE prediction_run_id=:id RETURNING *""", {"worker": _text(worker_id, "worker_id"), "id": row["prediction_run_id"]})
        return self._internal(claimed) if claimed else None

    def complete(self, run_id: str, *, prediction_artifact_id: str, signal_artifact_id: str,
                 worker_id: str, attempt_count: int) -> dict[str, object]:
        self._execute("""UPDATE ml_prediction_runs SET status='completed',prediction_artifact_id=:prediction,
            signal_artifact_id=:signal,lease_expires_at=NULL,finished_at=now(),updated_at=now()
            WHERE prediction_run_id=:id AND status='running' AND worker_id=:worker AND attempt_count=:attempt""",
            {"prediction": prediction_artifact_id, "signal": signal_artifact_id, "id": run_id, "worker": worker_id, "attempt": attempt_count})
        return self.get(run_id)

    def fail(self, run_id: str, code: str, detail: str, *, worker_id: str, attempt_count: int) -> dict[str, object]:
        self._execute("""UPDATE ml_prediction_runs SET status='failed',error_code=:code,error_detail=:detail,
            lease_expires_at=NULL,finished_at=now(),updated_at=now() WHERE prediction_run_id=:id AND status='running'
            AND worker_id=:worker AND attempt_count=:attempt""", {"code": _text(code, "error_code", 64),
            "detail": _text(detail, "error_detail", 500), "id": run_id, "worker": worker_id, "attempt": attempt_count})
        return self.get(run_id)

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, object]:
        value = dict(row)
        value.pop("input_json", None)
        value.pop("request_hash", None)
        return value

    @staticmethod
    def _internal(row: dict[str, Any]) -> dict[str, object]:
        value = dict(row)
        value["input"] = value.pop("input_json")
        value.pop("request_hash", None)
        return value


class MLPredictionCoordinator:
    def __init__(self, runs: MLPredictionRunStore, research: ResearchStore, objects: LocalObjectStore,
                 predictor: MLPredictor, *, worker_id: str,
                 market_data: MLPredictionMarketData | None = None) -> None:
        self.runs, self.research, self.objects, self.predictor, self.worker_id = runs, research, objects, predictor, worker_id
        self.market_data = market_data

    def _ready_input(
        self, input_document: dict[str, object], feature: dict[str, object],
    ) -> dict[str, object]:
        ready_input = input_document.get("ready_input")
        if isinstance(ready_input, dict):
            return ready_input
        requirements = input_document.get("requirements")
        readiness = input_document.get("readiness")
        if (
            self.market_data is None
            or not isinstance(requirements, list)
            or not requirements
            or any(not isinstance(item, dict) for item in requirements)
            or not isinstance(readiness, dict)
        ):
            raise ValueError("ML prediction market input is unavailable")
        frozen_requirements = [dict(item) for item in requirements]
        current = aggregate_ml_readiness([
            self.market_data.assess(item) for item in frozen_requirements
        ])
        if (
            current.get("state") != "ready"
            or current.get("ready_input_sha256") != readiness.get("ready_input_sha256")
        ):
            raise ValueError("frozen ML data identity changed before prediction")
        ready_input = (
            self.market_data.build_partitioned_ready_input(frozen_requirements)
            if len(frozen_requirements) > 1
            else self.market_data.build_ready_input(frozen_requirements[0])
        )
        source = feature.get("source")
        if (
            not isinstance(source, dict)
            or ready_input.get("research_view_sha256") != source.get("research_view_sha256")
        ):
            raise ValueError("frozen feature source no longer matches market input")
        return ready_input

    def _predict_qualified(
        self, model: dict[str, object], rows: list[dict[str, object]],
    ) -> list[float]:
        method = getattr(self.predictor, "predict_qualified", None)
        if not callable(method):
            raise ValueError("qualified v2 predictor is unavailable")
        payload = self.objects.get(model["object_reference"])
        return method(
            str(model.get("model_format")), payload, rows,
            best_iteration=model.get("best_iteration"),
        )

    def _predict_v2(
        self, *, input_document: dict[str, object], strategy: dict[str, object],
        feature: dict[str, object], model: dict[str, object], job: dict[str, object],
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        feature_hash = _verify_embedded_hash(feature, "feature snapshot")
        hydrated = load_feature_snapshot(feature, self.objects)
        if hydrated.get("schema_version") != "ml-feature-snapshot.v2":
            raise ValueError("ML v2 feature snapshot schema is unsupported")
        prediction_rows = [
            row for row in hydrated.get("rows", [])
            if isinstance(row, dict) and row.get("split") == "prediction"
        ]
        if model.get("schema_version") == "ml-model-artifact.v2":
            _verify_embedded_hash(model, "model artifact")
            if (
                model.get("feature_snapshot_sha256") != feature_hash
                or model.get("feature_snapshot_artifact_id") != job["feature_artifact_id"]
                or model.get("strategy_version_artifact_id") != job["ml_strategy_artifact_id"]
                or model.get("stock_pool_snapshot_id") != job["stock_pool_snapshot_id"]
                or model.get("feature_order") != FEATURE_ORDER
            ):
                raise ValueError("ML v2 model lineage or feature contract is invalid")
            profile = str(model.get("learner_profile"))
            expert_strategy = dict(strategy)
            expert_strategy["learner"] = {"profile": profile, "parameters": model.get("effective_parameters", {})}
            if (
                model.get("runtime_lock") != runtime_lock_for_profile(profile)
                or model.get("runtime_identity") != expected_runtime_identity(expert_strategy)
            ):
                raise ValueError("ML v2 model runtime is unsupported")
            scores = self._predict_qualified(model, prediction_rows)
            prediction = build_single_prediction_snapshot_v2(
                scores=scores, prediction_rows=prediction_rows, model=model,
                feature_artifact_id=str(job["feature_artifact_id"]),
                model_artifact_id=str(job["model_artifact_id"]),
                stock_pool_snapshot_id=str(job["stock_pool_snapshot_id"]),
            )
            return prediction, []
        if model.get("schema_version") != BUNDLE_SCHEMA:
            raise ValueError("ML v2 model or bundle schema is unsupported")
        bundle = validate_model_bundle(model)
        if (
            bundle.get("feature_snapshot_sha256") != feature_hash
            or bundle.get("feature_snapshot_artifact_id") != job["feature_artifact_id"]
            or bundle.get("strategy_version_artifact_id") != job["ml_strategy_artifact_id"]
            or bundle.get("stock_pool_snapshot_id") != job["stock_pool_snapshot_id"]
        ):
            raise ValueError("model bundle lineage does not match the prediction request")
        regime = validate_regime_snapshot(input_document.get("regime_snapshot"))
        if (
            regime.get("content_sha256") != bundle.get("regime_snapshot_sha256")
            or bundle.get("regime_snapshot_artifact_id") is None
        ):
            raise ValueError("model bundle regime snapshot does not match")
        state_by_session = {
            str(row["session"]): str(row["state"])
            for row in regime["rows"]
        }
        raw_models = input_document.get("expert_models")
        if not isinstance(raw_models, dict):
            raise ValueError("model bundle expert artifacts are unavailable")
        model_by_key: dict[str, tuple[str, dict[str, object]]] = {}
        for expert in bundle["experts"]:
            key = str(expert["key"])
            wrapped = raw_models.get(key)
            if not isinstance(wrapped, dict) or set(wrapped) != {"artifact_id", "content"}:
                raise ValueError("model bundle expert projection is invalid")
            content = wrapped.get("content")
            if not isinstance(content, dict) or content.get("schema_version") != "ml-model-artifact.v2":
                raise ValueError("model bundle expert model schema is invalid")
            _verify_embedded_hash(content, "expert model")
            if (
                wrapped.get("artifact_id") != expert.get("model_artifact_id")
                or content.get("content_sha256") != expert.get("model_content_sha256")
                or content.get("expert_key") != key
                or content.get("feature_snapshot_artifact_id") != job["feature_artifact_id"]
                or content.get("regime_snapshot_artifact_id") != bundle.get("regime_snapshot_artifact_id")
            ):
                raise ValueError("model bundle expert identity or lineage is invalid")
            profile = str(content.get("learner_profile"))
            expert_strategy = dict(strategy)
            expert_strategy["learner"] = {"profile": profile, "parameters": content.get("effective_parameters", {})}
            if (
                content.get("runtime_lock") != runtime_lock_for_profile(profile)
                or content.get("runtime_identity") != expected_runtime_identity(expert_strategy)
            ):
                raise ValueError("model bundle expert runtime is unsupported")
            model_by_key[key] = (str(wrapped["artifact_id"]), content)
        if set(model_by_key) != {str(item["key"]) for item in bundle["experts"]}:
            raise ValueError("model bundle expert set does not match")
        routed: dict[str, list[tuple[int, dict[str, object]]]] = {}
        for index, row in enumerate(prediction_rows):
            session = str(row["session"])
            state = state_by_session.get(session)
            if state is None:
                raise ValueError("prediction session has no frozen regime evidence")
            key = expert_key_for(state, bundle)
            routed.setdefault(key, []).append((index, row))
        scored: list[dict[str, object] | None] = [None] * len(prediction_rows)
        expert_lineage: list[dict[str, object]] = []
        for key in sorted(routed):
            artifact_id, expert_model = model_by_key[key]
            selected = [item[1] for item in routed[key]]
            scores = self._predict_qualified(expert_model, selected)
            if len(scores) != len(selected):
                raise ValueError("expert prediction row count does not match")
            expert_lineage.append({"kind": "artifact", "id": artifact_id})
            for (index, row), score in zip(routed[key], scores, strict=True):
                session = str(row["session"])
                scored[index] = {
                    "session": session, "symbol": str(row["symbol"]), "score": float(score),
                    "regime": state_by_session[session],
                    "regime_snapshot_id": bundle["regime_snapshot_artifact_id"],
                    "expert_key": key, "model_artifact_id": artifact_id,
                }
        if any(item is None for item in scored):
            raise ValueError("routed prediction did not score every row")
        prediction = build_routed_prediction_snapshot(
            scored_rows=[item for item in scored if isinstance(item, dict)],
            feature_artifact_id=str(job["feature_artifact_id"]),
            feature_snapshot_sha256=feature_hash,
            model_bundle_artifact_id=str(job["model_artifact_id"]),
            model_bundle_sha256=str(bundle["content_sha256"]),
            regime_snapshot_artifact_id=str(bundle["regime_snapshot_artifact_id"]),
            regime_snapshot_sha256=str(bundle["regime_snapshot_sha256"]),
            stock_pool_snapshot_id=str(job["stock_pool_snapshot_id"]),
            prediction_window=bundle["prediction_window"],
            capability_lock=bundle.get("capability_lock"),
        )
        return prediction, expert_lineage

    def run_next(self) -> dict[str, object] | None:
        job = self.runs.claim_next(self.worker_id)
        if job is None:
            return None
        run_id = str(job["prediction_run_id"])
        try:
            input_document = job.get("input")
            if not isinstance(input_document, dict):
                raise ValueError("ML prediction input is unavailable")
            strategy, feature, model = input_document.get("strategy"), input_document.get("feature"), input_document.get("model")
            if not all(isinstance(item, dict) for item in (strategy, feature, model)):
                raise ValueError("ML prediction artifacts are unavailable")
            strategy = validate_ml_strategy_version(strategy)
            ready_input = self._ready_input(input_document, feature)
            expert_lineage: list[dict[str, object]] = []
            if strategy.get("schema_version") == ML_V2_SCHEMA:
                prediction, expert_lineage = self._predict_v2(
                    input_document=input_document, strategy=strategy, feature=feature,
                    model=model, job=job,
                )
            else:
                if feature.get("schema_version") != FEATURE_SCHEMA or model.get("schema_version") != MODEL_SCHEMA:
                    raise ValueError("ML prediction artifact schema is unsupported")
                feature_hash = _verify_embedded_hash(feature, "feature snapshot")
                _verify_embedded_hash(model, "model artifact")
                if model.get("feature_snapshot_sha256") != feature_hash or model.get("feature_snapshot_artifact_id") != job["feature_artifact_id"]:
                    raise ValueError("model does not match the frozen feature snapshot")
                if model.get("strategy_version_artifact_id") != job["ml_strategy_artifact_id"] or model.get("stock_pool_snapshot_id") != job["stock_pool_snapshot_id"]:
                    raise ValueError("model lineage does not match the prediction request")
                if model.get("runtime_lock") != RUNTIME_LOCK or model.get("runtime_identity") != RUNTIME_IDENTITY or model.get("feature_order") != FEATURE_ORDER:
                    raise ValueError("model runtime or feature contract is unsupported")
                model_text = self.objects.get(model["object_reference"]).decode("utf-8")
                hydrated_feature = load_feature_snapshot(feature, self.objects)
                prediction_rows = [row for row in hydrated_feature.get("rows", []) if isinstance(row, dict) and row.get("split") == "prediction"]
                scores = self.predictor.predict(model_text, prediction_rows, best_iteration=int(model["best_iteration"]))
                prediction = build_prediction_snapshot(scores=scores, prediction_rows=prediction_rows, model=model,
                    feature_artifact_id=str(job["feature_artifact_id"]), model_artifact_id=str(job["model_artifact_id"]),
                    stock_pool_snapshot_id=str(job["stock_pool_snapshot_id"]))
            prediction_artifact_hash = content_sha256(prediction)
            prediction_artifact = self.research.find_artifact_by_content(str(job["task_id"]), "ml_prediction_snapshot", prediction_artifact_hash)
            if prediction_artifact is None:
                prediction_artifact = self.research.create_artifact({"task_id": job["task_id"], "experiment_id": job.get("experiment_id"),
                    "kind": "ml_prediction_snapshot", "content": prediction,
                    "lineage": [{"kind": "artifact", "id": job["ml_strategy_artifact_id"]}, {"kind": "artifact", "id": job["model_artifact_id"]},
                                *expert_lineage,
                                {"kind": "artifact", "id": job["feature_artifact_id"]}, {"kind": "stock_pool_snapshot", "id": job["stock_pool_snapshot_id"]}],
                    "trace_id": job["trace_id"], "idempotency_key": f"ml-prediction-{prediction_artifact_hash}"})
            if prediction_artifact["status"] == "draft":
                prediction_artifact = self.research.transition("artifact", prediction_artifact["artifact_id"], "validated", f"ml-prediction-validate-{prediction_artifact_hash[:24]}")
            signal = build_ml_signal_snapshot(prediction=prediction, strategy=strategy,
                strategy_artifact_id=str(job["ml_strategy_artifact_id"]), approval_artifact_id=str(job["approval_artifact_id"]),
                feature_artifact_id=str(job["feature_artifact_id"]), model_artifact_id=str(job["model_artifact_id"]),
                prediction_artifact_id=str(prediction_artifact["artifact_id"]), stock_pool_snapshot_id=str(job["stock_pool_snapshot_id"]),
                ready_input=ready_input, execution=input_document["execution"], readiness=input_document["readiness"])
            signal_hash = signal_snapshot_content_sha256(signal)
            signal_artifact = self.research.find_artifact_by_content(str(job["task_id"]), "signal_snapshot", signal_hash)
            if signal_artifact is None:
                signal_artifact = self.research.create_artifact({"task_id": job["task_id"], "experiment_id": job.get("experiment_id"),
                    "kind": "signal_snapshot", "content": signal,
                    "lineage": [{"kind": "artifact", "id": job["ml_strategy_artifact_id"]}, {"kind": "artifact", "id": job["approval_artifact_id"]},
                                {"kind": "artifact", "id": job["model_artifact_id"]}, {"kind": "artifact", "id": job["feature_artifact_id"]},
                                {"kind": "artifact", "id": prediction_artifact["artifact_id"]}, *expert_lineage,
                                {"kind": "stock_pool_snapshot", "id": job["stock_pool_snapshot_id"]}],
                    "trace_id": job["trace_id"], "idempotency_key": f"ml-signal-{signal_hash}"})
            if signal_artifact["status"] == "draft":
                signal_artifact = self.research.transition("artifact", signal_artifact["artifact_id"], "validated", f"ml-signal-validate-{signal_hash[:24]}")
            return self.runs.complete(run_id, prediction_artifact_id=str(prediction_artifact["artifact_id"]),
                signal_artifact_id=str(signal_artifact["artifact_id"]), worker_id=str(job["worker_id"]), attempt_count=int(job["attempt_count"]))
        except Exception as error:
            return self.runs.fail(run_id, "ml_prediction_failed", str(error)[:500] or "ML prediction failed",
                worker_id=str(job["worker_id"]), attempt_count=int(job["attempt_count"]))
