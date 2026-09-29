#!/usr/bin/env python3
"""Bounded real-provider CPU TrainingJob evidence in one disposable dev stack."""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / ".phase15-ml-cpu.json"
SCOPE = os.environ.get("BYQ_DEV_SCOPE", "")
ORIGIN = os.environ.get("BYQ_REAL_BASE_URL", "").rstrip("/")
URL = urlsplit(ORIGIN)
expected_scope = "byq-dev-" + hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:10]
if not re.fullmatch(r"byq-dev-[0-9a-f]{10}", SCOPE) or SCOPE != expected_scope:
    raise SystemExit("an isolated BYQ dev scope is required")
if URL.scheme != "http" or URL.hostname != "127.0.0.1" or not URL.port:
    raise SystemExit("a dynamic loopback Gateway URL is required")
client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))


def call(method: str, path: str, payload: dict[str, object] | None = None,
         *, expected: int = 200, headers: dict[str, str] | None = None) -> dict[str, object]:
    request = Request(
        ORIGIN + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"content-type": "application/json", **(headers or {})}, method=method,
    )
    try:
        with client.open(request, timeout=45) as response:
            result = json.load(response)
            if response.status != expected or not isinstance(result, dict):
                raise AssertionError(f"unexpected Product response: {path}")
            return result
    except HTTPError as error:
        raise AssertionError(f"Product request failed: {path} HTTP {error.code}") from error


def authenticate() -> str:
    username = os.environ["BYQ_E2E_ADMIN_USERNAME"]
    password = os.environ["BYQ_E2E_ADMIN_PASSWORD"]
    call("POST", "/api/auth/login", {"username": username, "password": password})
    return str(call("GET", "/api/auth/me")["workspace"]["workspace_id"])


def save(value: dict[str, object]) -> None:
    fd = os.open(MANIFEST, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")


def submit(workspace_id: str) -> None:
    if os.environ.get("BYQ_PHASE15_ML_PROVIDER_AUTHORIZED") != "1":
        raise SystemExit("this exact real-provider TrainingJob requires operator authorization")
    if MANIFEST.exists():
        raise SystemExit("existing exact ML manifest; inspect status before another submission")
    run_key = "phase15-ml-real-" + secrets.token_hex(6)
    task = call("POST", "/api/product/research/tasks", {
        "title": "Phase 15 real-provider CPU TrainingJob",
        "objective": "Train one bounded LightGBM model on 2024 TuShare market data.",
    }, expected=201)
    if task.get("workspace_id") != workspace_id:
        raise AssertionError("ResearchTask escaped the authenticated Workspace")
    task_id = str(task["task_id"])
    pool = call("POST", "/api/product/paper/pools", {
        "name": "Phase 15 real-provider ML pool", "pool_type": "custom",
        "idempotency_key": run_key + "-pool", "symbols": ["000001.SZ"],
    }, expected=201)["pool"]
    snapshot_id = str(pool["snapshot"]["snapshot_id"])
    strategy = {
        "schema_version": "ml-strategy-version.v2", "name": "Phase 15 CPU LightGBM",
        "feature_set": {"id": "price-volume-basic-v1", "parameters": {}},
        "target": {"id": "forward-return-v1", "parameters": {"horizon_sessions": 1}},
        "validation_plan": {"id": "walk-forward-purged-v1", "parameters": {
            "mode": "expanding", "train_sessions": 60, "validation_sessions": 10,
            "step_sessions": 10, "folds": 2, "purge_sessions": 1, "embargo_sessions": 0,
        }},
        "learner": {"profile": "byq-lightgbm-cpu-v1", "parameters": {}},
        "portfolio_policy": {"id": "top-n-equal-weight-v1", "parameters": {
            "top_n": 1, "rebalance": "weekly",
        }},
        "development_window": {"start": "2024-01-02", "end": "2024-05-17"},
        "prediction_window": {"start": "2024-05-20", "end": "2024-05-31"},
    }
    version = call("POST", "/api/product/ml/strategies/versions", {
        "task_id": task_id, "strategy": strategy,
    }, expected=201, headers={"x-idempotency-key": run_key + "-version"})["artifact"]
    version_id = str(version["artifact_id"])
    approval = call("POST", "/api/product/ml/strategies/approvals", {
        "task_id": task_id, "ml_strategy_artifact_id": version_id,
        "decision": "approved", "rationale": "Authorized isolated real-provider CPU validation",
    }, expected=201, headers={"x-idempotency-key": run_key + "-approval"})["artifact"]
    run = call("POST", "/api/product/ml/training-runs", {
        "task_id": task_id, "ml_strategy_artifact_id": version_id,
        "stock_pool_snapshot_id": snapshot_id,
    }, expected=202, headers={"x-idempotency-key": run_key + "-training"})["training_run"]
    if run.get("status") != "waiting_for_data":
        raise AssertionError("TrainingJob did not enter waiting_for_data")
    manifest = {
        "scope": SCOPE, "workspace_id": workspace_id, "task_id": task_id,
        "pool_snapshot_id": snapshot_id, "strategy_artifact_id": version_id,
        "approval_artifact_id": str(approval["artifact_id"]),
        "training_run_id": str(run["training_run_id"]),
        "authorized_window": ["2024-01-02", "2024-05-31"],
    }
    save(manifest)
    print(json.dumps({"result": "SUBMITTED", "training_run_id": manifest["training_run_id"],
                      "status": run["status"], "workspace_id": workspace_id}))


def status(workspace_id: str) -> None:
    manifest = json.loads(MANIFEST.read_text())
    if manifest["scope"] != SCOPE or manifest["workspace_id"] != workspace_id:
        raise AssertionError("ML manifest does not belong to the active isolated Workspace")
    run_id = str(manifest["training_run_id"])
    run = call("GET", f"/api/product/ml/training-runs/{run_id}")["training_run"]
    if run.get("training_run_id") != run_id:
        raise AssertionError("Product returned a different TrainingJob")
    if run["status"] in {"failed", "cancelled"}:
        raise AssertionError(f"TrainingJob ended {run['status']}: {run.get('error_code')}")
    result = {"result": "STATUS", "training_run_id": run_id, "status": run["status"],
              "readiness": run.get("readiness"), "error_code": run.get("error_code"),
              "feature_artifact_id": run.get("feature_artifact_id"),
              "model_artifact_id": run.get("model_artifact_id")}
    if run["status"] == "completed":
        if run.get("error_code") is not None or (run.get("readiness") or {}).get("state") != "ready":
            raise AssertionError("completed TrainingJob has error or unready data")
        for field, kind in (("feature_artifact_id", "ml_feature_snapshot"),
                            ("model_artifact_id", "ml_model")):
            artifact_id = run.get(field)
            if not isinstance(artifact_id, str):
                raise AssertionError(f"completed TrainingJob lacks {field}")
            artifact = call("GET", f"/api/product/research/artifacts/{artifact_id}")
            if (artifact.get("artifact_id") != artifact_id or artifact.get("kind") != kind
                    or artifact.get("status") != "validated"
                    or artifact.get("task_id") != manifest["task_id"]):
                raise AssertionError(f"Product Artifact mismatch: {field}")
            content = artifact.get("content")
            if not isinstance(content, dict) or not isinstance(content.get("object_reference"), dict):
                raise AssertionError(f"Product Artifact lacks a persisted object: {field}")
            if field == "feature_artifact_id" and not int(content.get("row_count") or 0) > 0:
                raise AssertionError("Feature Artifact has no persisted rows")
            if field == "model_artifact_id" and (
                content.get("training_run_id") != run_id
                or content.get("runtime_identity") != "lightgbm-4.7.0-python-3.13-linux-cpu-single-thread"
                or not isinstance(content.get("metrics"), dict)
                or not content["metrics"]
            ):
                raise AssertionError("Model Artifact does not match the CPU TrainingJob")
        result["result"] = "PASS"
    print(json.dumps(result, sort_keys=True))


parser = argparse.ArgumentParser()
parser.add_argument("action", choices=("submit", "status"))
action = parser.parse_args().action
owner_workspace = authenticate()
if action == "submit":
    submit(owner_workspace)
else:
    status(owner_workspace)
