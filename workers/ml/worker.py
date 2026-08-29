"""Trusted, source-free LightGBM CPU training worker (ADR-0043)."""

from __future__ import annotations

import argparse
import math
import os
import signal
import time

import lightgbm as lgb
import numpy as np

from app.backtest import LocalObjectStore
from app.market_readiness import MarketReadinessStore
from app.ml_strategy import FEATURE_ORDER, RUNTIME_LOCK, effective_lightgbm_parameters
from app.ml_training import (
    MLTrainingCoordinator,
    MLTrainingRunStore,
    RUNTIME_IDENTITY,
    promote_waiting_training_runs,
)
from app.research import ResearchStore


class LightGBMTrainer:
    runtime_identity = RUNTIME_IDENTITY

    def __init__(self, image_identity: str | None = None) -> None:
        self.image_identity = image_identity or os.environ.get(
            "BYQ_ML_IMAGE_IDENTITY", "byq-ml-worker-v1-local-build"
        )

    @staticmethod
    def _rank(values: np.ndarray) -> np.ndarray:
        order = np.argsort(values, kind="mergesort")
        ranks = np.empty(len(values), dtype=float)
        ranks[order] = np.arange(1, len(values) + 1, dtype=float)
        return ranks

    def train(self, feature_snapshot: dict[str, object], strategy: dict[str, object]) -> dict[str, object]:
        rows = feature_snapshot.get("rows")
        if not isinstance(rows, list):
            raise ValueError("feature snapshot rows are unavailable")
        train_rows = [row for row in rows if isinstance(row, dict) and row.get("split") == "train"]
        validation_rows = [row for row in rows if isinstance(row, dict) and row.get("split") == "validation"]
        if len(train_rows) < 20 or len(validation_rows) < 5:
            raise ValueError("insufficient train or validation rows")

        def matrix(selected: list[dict[str, object]]) -> tuple[np.ndarray, np.ndarray]:
            x = np.asarray(
                [[float(row["features"][name]) for name in FEATURE_ORDER] for row in selected], dtype=np.float64
            )
            y = np.asarray([float(row["target"]) for row in selected], dtype=np.float64)
            if not np.isfinite(x).all() or not np.isfinite(y).all():
                raise ValueError("training matrix contains non-finite values")
            return x, y

        train_x, train_y = matrix(train_rows)
        validation_x, validation_y = matrix(validation_rows)
        effective = effective_lightgbm_parameters(strategy)
        num_round = int(effective.pop("num_boost_round"))
        early_stopping_rounds = int(effective.pop("early_stopping_rounds"))
        booster = lgb.train(
            effective,
            lgb.Dataset(train_x, label=train_y, feature_name=FEATURE_ORDER, free_raw_data=True),
            num_boost_round=num_round,
            valid_sets=[lgb.Dataset(validation_x, label=validation_y, reference=None, feature_name=FEATURE_ORDER)],
            valid_names=["validation"],
            callbacks=[lgb.early_stopping(early_stopping_rounds, first_metric_only=True, verbose=False)],
        )
        best_iteration = int(booster.best_iteration or num_round)
        predictions = np.asarray(booster.predict(validation_x, num_iteration=best_iteration), dtype=np.float64)
        rmse = float(np.sqrt(np.mean(np.square(predictions - validation_y))))
        rank_ic = 0.0
        if len(predictions) > 1:
            correlation = np.corrcoef(self._rank(predictions), self._rank(validation_y))[0, 1]
            rank_ic = 0.0 if not math.isfinite(float(correlation)) else float(correlation)
        model_text = booster.model_to_string(num_iteration=best_iteration)
        return {
            "model_text": model_text,
            "best_iteration": best_iteration,
            "effective_parameters": {**effective, "num_boost_round": num_round,
                                     "early_stopping_rounds": early_stopping_rounds},
            "metrics": {"validation_rmse": rmse, "validation_rank_ic": rank_ic,
                        "train_rows": len(train_rows), "validation_rows": len(validation_rows)},
            "runtime_identity": self.runtime_identity,
            "image_identity": self.image_identity,
        }


def probe() -> int:
    if lgb.__version__ != "4.7.0":
        raise RuntimeError(f"unexpected LightGBM version: {lgb.__version__}")
    if not RUNTIME_LOCK.startswith("python-3.13/lightgbm-4.7.0/"):
        raise RuntimeError("runtime lock mismatch")
    sample_x = np.asarray([[0.0], [1.0], [2.0], [3.0]], dtype=np.float64)
    booster = lgb.train(
        {"objective": "regression", "verbosity": -1, "num_threads": 1,
         "deterministic": True, "force_col_wise": True, "seed": 20260829},
        lgb.Dataset(sample_x, label=np.asarray([0.0, 1.0, 2.0, 3.0])), num_boost_round=2,
    )
    rendered = booster.model_to_string()
    restored = lgb.Booster(model_str=rendered)
    if not np.allclose(booster.predict(sample_x), restored.predict(sample_x)):
        raise RuntimeError("LightGBM native text round-trip failed")
    rows: list[dict[str, object]] = []
    for index in range(30):
        split = "train" if index < 24 else "validation"
        features = {
            name: float(index + feature_index) / 100.0
            for feature_index, name in enumerate(FEATURE_ORDER)
        }
        rows.append({"split": split, "features": features, "target": float(index) / 1000.0})
    trained = LightGBMTrainer().train(
        {"rows": rows},
        {"learner_parameters": {"num_boost_round": 4, "early_stopping_rounds": 2}},
    )
    trained_text = trained.get("model_text")
    if not isinstance(trained_text, str) or not trained_text.startswith("tree"):
        raise RuntimeError("five-feature LightGBM training probe failed")
    if trained.get("runtime_identity") != LightGBMTrainer.runtime_identity:
        raise RuntimeError("LightGBM runtime identity mismatch")
    if not trained.get("image_identity"):
        raise RuntimeError("LightGBM image identity is unavailable")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    if args.probe:
        return probe()
    runs = MLTrainingRunStore.from_env()
    research = ResearchStore.from_env()
    readiness = MarketReadinessStore.from_env()
    objects = LocalObjectStore(os.environ.get("BYQ_ML_OBJECT_ROOT", "/var/lib/byq/domain/ml-objects"))
    coordinator = MLTrainingCoordinator(
        runs, research, objects, LightGBMTrainer(),
        worker_id=os.environ.get("BYQ_ML_WORKER_ID", "ml-worker-1"),
    )
    poll = max(0.2, float(os.environ.get("BYQ_ML_POLL_SECONDS", "2")))
    running = True

    def stop(_number: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while running:
            promote_waiting_training_runs(runs, readiness)
            if coordinator.run_next() is None:
                time.sleep(poll)
    finally:
        readiness.close()
        research.close()
        runs.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
