#!/usr/bin/env python3
"""Observe one Agent-started CPU TrainingJob in the isolated Phase 15 stack.

This script never starts a Worker or downloads market data. Run each stage once;
an uncertain Product write requires read-only reconciliation before any retry.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.request import HTTPCookieProcessor, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.dev.environment import local_env, compose_args, call as compose_call


ROOT = Path(__file__).resolve().parents[2]
SCOPE = "byq-dev-ea551690f4"
WORKSPACE = "workspace_9f180f427ac14bb7b5ccb35c4c59d1c8"
PRIOR = ROOT / ".phase15-ml-cpu.json"
MANIFEST = ROOT / ".phase15-golden-c.json"
RUN_ID = re.compile(r"mlrun_[0-9a-f]{32}")
APPROVAL_ID = re.compile(r"agent_approval_[0-9a-f]{32}")
BASE = os.environ.get("BYQ_REAL_BASE_URL", "")


class EvidenceError(RuntimeError):
    pass


def need(value: object, reason: str) -> None:
    if not value:
        raise EvidenceError(reason)


def save(data: dict[str, object]) -> None:
    temporary = MANIFEST.with_suffix(".json.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, MANIFEST)


def load() -> dict[str, object]:
    need(MANIFEST.is_file() and not MANIFEST.is_symlink(), "Golden C manifest is absent")
    data = json.loads(MANIFEST.read_text())
    need(data.get("scope") == SCOPE and data.get("workspace_id") == WORKSPACE,
         "Golden C manifest identity differs from isolated stack")
    return data


def client():
    values = local_env()
    need(values.get("BYQ_DEV_SCOPE") == SCOPE, "wrong isolated dev scope")
    need(BASE.startswith("http://127.0.0.1:") and BASE.count("/") == 2,
         "BYQ_REAL_BASE_URL must be the dynamic loopback Gateway origin")
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(method: str, path: str, payload: dict[str, object] | None = None,
             expected: int = 200) -> dict[str, object]:
        request = Request(
            BASE + path, None if payload is None else json.dumps(payload).encode(),
            {"content-type": "application/json"}, method=method,
        )
        with opener.open(request, timeout=45) as response:
            need(response.status == expected, f"unexpected HTTP status on {path}")
            body = json.load(response)
            need(isinstance(body, dict), f"non-object Product response on {path}")
            return body

    call("POST", "/api/auth/login", {
        "username": values.get("BYQ_BOOTSTRAP_ADMIN_USERNAME", "admin"),
        "password": values["BYQ_BOOTSTRAP_ADMIN_PASSWORD"],
    })
    me = call("GET", "/api/auth/me")
    need(me.get("workspace", {}).get("workspace_id") == WORKSPACE,
         "authenticated Product identity is outside the exact Workspace")
    return call


def study(call, prior: dict[str, object]) -> list[dict[str, object]]:
    result = call("GET", f"/api/product/ml/studies/{prior['strategy_artifact_id']}")
    need(result.get("approval_artifact_id") == prior["approval_artifact_id"],
         "exact approved ML strategy is no longer available")
    runs = result.get("training_runs", {}).get("runs")
    need(isinstance(runs, list), "Product study has no training-run page")
    return runs


def preflight(call) -> None:
    need(not MANIFEST.exists(), "Golden C manifest already exists")
    prior = json.loads(PRIOR.read_text())
    need(prior.get("scope") == SCOPE and prior.get("workspace_id") == WORKSPACE,
         "prior CPU evidence belongs to another isolated scope")
    runs = study(call, prior)
    need(len(runs) == 1 and runs[0].get("training_run_id") == prior["training_run_id"]
         and runs[0].get("status") == "completed", "unexpected current study run state")
    approvals = call("GET", "/api/product/approvals?status=pending&limit=100&offset=0")
    need(approvals.get("total") == 0, "unresolved Product approvals exist")
    save({"scope": SCOPE, "workspace_id": WORKSPACE, "prior": prior,
          "baseline_run_ids": [prior["training_run_id"]], "stage": "prepared"})
    print(json.dumps({"stage": "prepared", "prior_run_id": prior["training_run_id"]}))


def session(call, data: dict[str, object]) -> dict[str, object]:
    return call("GET", f"/v1/agent/sessions/{data['conversation_id']}")


def request(call) -> None:
    need(os.environ.get("BYQ_PHASE15_GOLDEN_C_MODEL_AUTHORIZED") == "1",
         "one bounded Product Agent turn requires explicit external-model authorization")
    data = load()
    need(data["stage"] == "prepared", "Agent request stage was already attempted")
    prior = data["prior"]
    need(isinstance(prior, dict), "prior CPU manifest is malformed")
    need(len(study(call, prior)) == 1, "study changed after preflight")
    data["stage"] = "session_creation_attempted"
    save(data)
    created = call("POST", "/v1/agent/sessions", expected=201)
    conversation_id = created.get("session_id")
    need(isinstance(conversation_id, str), "Product did not return Agent session ID")
    data["conversation_id"] = conversation_id
    data["stage"] = "turn_submission_attempted"
    prompt = (
        "在这个隔离 BYQ Workspace 中，仅发起一个 CPU LightGBM TrainingJob。"
        f"请严格使用现有 ResearchTask {prior['task_id']}、已验证 ML 策略 "
        f"{prior['strategy_artifact_id']}、已获人类批准的策略 Artifact "
        f"{prior['approval_artifact_id']}、冻结股票池 {prior['pool_snapshot_id']}。"
        "先通过 BYQ MCP 核对这些精确对象和已有运行，不创建新策略、股票池或研究任务。"
        "此前完成的 TrainingJob 仅作基线，不重试它。先用 byq_ml_training_create 的 "
        "prepare_only=true 冻结唯一新提交，记录其 receipt_watch.watch_id；"
        "再以 resource_type=ml_training_submission 和该 watch ID 请求精确 Product 人工审批。"
        "审批前不得提交训练；审批后用原 Task、策略、池和幂等键及 agent_approval_id 提交一次。"
        "训练窗口只允许 2024-01-02 至 2024-05-31，标的仅 000001.SZ，使用已缓存数据；"
        "不得请求扩大日期或标的、拉取新行情、使用 GPU、发起预测或回测。"
        "请报告精确审批 ID；获批并提交后报告新 TrainingJob ID。"
    )
    failed = data.get("failed_attempt")
    if isinstance(failed, dict):
        prompt += (
            f"此前会话已失效，仍未提交训练；现有冻结回执 {failed['watch_id']} "
            f"和原幂等键 {failed['submission_key']} 必须保留。先以该原键只读核对回执，"
            "不要替换提交身份；为当前会话请求该同一回执的精确审批。"
            "原会话的批准不能跨会话复用。"
        )
    data["prompt"] = prompt
    save(data)
    accepted = call("POST", f"/v1/agent/sessions/{conversation_id}/turns", {"content": prompt}, 202)
    need(accepted.get("accepted") is True, "Product Agent turn was not accepted")
    data["stage"] = "approval_pending"
    save(data)
    print(json.dumps({"stage": "approval_pending", "conversation_id": conversation_id}))


def pending(call) -> None:
    data = load()
    need(data["stage"] == "approval_pending", "not waiting for the exact training approval")
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        body = call("GET", "/api/product/approvals?status=pending&limit=100&offset=0")
        approvals = [row for row in body.get("approvals", [])
                     if row.get("conversation_id") == data["conversation_id"]
                     and row.get("action") == "byq_ml_training_create"]
        if approvals:
            need(len(approvals) == 1, "more than one training approval requested")
            approval = approvals[0]
            need(APPROVAL_ID.fullmatch(str(approval.get("approval_id", ""))),
                 "Product returned malformed approval identity")
            need(approval.get("resource_type") == "ml_training_submission"
                 and re.fullmatch(r"mlwatch_[0-9a-f]{32}", str(approval.get("resource_id", ""))),
                 "training approval is not bound to a frozen exact submission")
            preview = approval.get("resource_preview")
            prior = data["prior"]
            need(isinstance(preview, dict) and isinstance(prior, dict)
                 and preview.get("schema_version") == "ml-training-submission-preview.v1"
                 and preview.get("watch_id") == approval["resource_id"]
                 and preview.get("state") == "prepared"
                 and preview.get("task_id") == prior["task_id"]
                 and preview.get("ml_strategy_artifact_id") == prior["strategy_artifact_id"]
                 and preview.get("stock_pool_snapshot_id") == prior["pool_snapshot_id"]
                 and preview.get("experiment_id") is None
                 and isinstance(preview.get("idempotency_key"), str)
                 and preview["idempotency_key"] != prior.get("idempotency_key"),
                 "training approval preview differs from the exact intended submission")
            failed = data.get("failed_attempt")
            if isinstance(failed, dict):
                need(preview["watch_id"] == failed["watch_id"]
                     and preview["idempotency_key"] == failed["submission_key"],
                     "replacement conversation changed the original frozen submission")
            data["approval_id"] = approval["approval_id"]
            data["watch_id"] = approval["resource_id"]
            data["submission_key"] = preview["idempotency_key"]
            data["stage"] = "ready_for_decision"
            save(data)
            print(json.dumps({"stage": "ready_for_decision", "approval_id": data["approval_id"],
                              "watch_id": data["watch_id"]}))
            return
        conversation = session(call, data).get("conversation", {})
        need(conversation.get("status") not in {"failed", "interrupted"},
             "Agent conversation failed before requesting training approval")
        time.sleep(2)
    raise EvidenceError("no exact training approval after 900 seconds")


def approve(call, *, receipt_only: bool = False) -> None:
    need(receipt_only or os.environ.get("BYQ_PHASE15_GOLDEN_C_MODEL_AUTHORIZED") == "1",
         "approval continuation requires explicit external-model authorization")
    data = load()
    need(data["stage"] == ("decision_attempted" if receipt_only else "ready_for_decision"),
         "exact approval already decided or unknown")
    if receipt_only:
        approval = call("GET", f"/api/product/approvals/{data['approval_id']}")["approval"]
        need(approval.get("status") == "approved" and approval.get("continuation_status") == "submitted",
             "decision not committed; do not retry")
    values = local_env()
    port = compose_call(compose_args("port", "frontend", "80"), values, capture=True)
    need(port.returncode == 0, "isolated Frontend origin unavailable")
    environment = {**os.environ, "BYQ_REAL_BASE_URL": "http://" + port.stdout.strip(),
                   "BYQ_E2E_ADMIN_USERNAME": values.get("BYQ_BOOTSTRAP_ADMIN_USERNAME", "admin"),
                   "BYQ_E2E_ADMIN_PASSWORD": values["BYQ_BOOTSTRAP_ADMIN_PASSWORD"]}
    for key, value in {"WATCH_ID": data["watch_id"], "APPROVAL_ID": data["approval_id"],
                       "CONVERSATION_ID": data["conversation_id"],
                       "TASK_ID": data["prior"]["task_id"],
                       "STRATEGY_ID": data["prior"]["strategy_artifact_id"],
                       "POOL_SNAPSHOT_ID": data["prior"]["pool_snapshot_id"],
                       "SUBMISSION_KEY": data["submission_key"]}.items():
        environment["BYQ_PHASE15_" + key] = str(value)
    if not receipt_only:
        data["stage"] = "decision_attempted"
        save(data)
    browser = subprocess.run(
        ["node", "apps/frontend/tests/e2e/phase15-training-approval.mjs",
         "--receipt-only" if receipt_only else "--approve"],
        cwd=ROOT, env=environment, text=True, capture_output=True,
    )
    need(browser.returncode == 0, "browser approval/receipt unconfirmed; inspect Product state without retry")
    evidence = json.loads(browser.stdout.strip().splitlines()[-1])
    need(evidence.get("result") == "PASS" and evidence.get("approval_id") == data["approval_id"]
         and evidence.get("continuation_status") == "submitted"
         and RUN_ID.fullmatch(str(evidence.get("training_run_id", ""))),
         "browser did not confirm the exact decision and TrainingJob")
    data["stage"] = "approved"
    data["new_run_id"] = evidence["training_run_id"]
    data["browser_evidence"] = evidence
    if receipt_only:
        data["browser_approval_observer"] = "failed_after_committed_decision_agent_key_reconcile_404"
    save(data)
    print(json.dumps(evidence))


def status(call) -> None:
    data = load()
    prior = data["prior"]
    need(isinstance(prior, dict), "prior CPU manifest is malformed")
    runs = study(call, prior)
    new = [run for run in runs if run.get("training_run_id") not in data["baseline_run_ids"]]
    need(len(new) <= 1, "duplicate new TrainingJobs found in exact study")
    if not new:
        print(json.dumps({"stage": data["stage"], "new_run_count": 0}))
        return
    run_id = new[0].get("training_run_id")
    need(isinstance(run_id, str) and RUN_ID.fullmatch(run_id), "new TrainingJob has invalid ID")
    exact = call("GET", f"/api/product/ml/training-runs/{run_id}").get("training_run", {})
    need(exact.get("training_run_id") == run_id and exact.get("task_id") == prior["task_id"]
         and exact.get("ml_strategy_artifact_id") == prior["strategy_artifact_id"]
         and exact.get("stock_pool_snapshot_id") == prior["pool_snapshot_id"]
         and exact.get("idempotency_key") == data.get("submission_key"),
         "new TrainingJob is not bound to exact approved inputs")
    if exact.get("status") == "completed":
        need(exact.get("error_code") is None
             and exact.get("readiness", {}).get("state") == "ready",
             "completed TrainingJob has error or unready data")
        for field, kind in (("feature_artifact_id", "ml_feature_snapshot"),
                            ("model_artifact_id", "ml_model")):
            artifact_id = exact.get(field)
            need(isinstance(artifact_id, str), f"completed TrainingJob lacks {field}")
            artifact = call("GET", f"/api/product/research/artifacts/{artifact_id}")
            need(artifact.get("artifact_id") == artifact_id
                 and artifact.get("kind") == kind and artifact.get("status") == "validated"
                 and artifact.get("task_id") == prior["task_id"],
                 f"completed TrainingJob has invalid {field}")
            content = artifact.get("content")
            need(isinstance(content, dict) and isinstance(content.get("object_reference"), dict),
                 f"completed TrainingJob has no persisted object for {field}")
            if field == "model_artifact_id":
                need(content.get("training_run_id") == run_id and isinstance(content.get("metrics"), dict),
                     "Model Artifact lacks exact lineage or metrics")
    data["new_run_id"] = run_id
    save(data)
    print(json.dumps({"stage": data["stage"], "new_run_id": run_id,
                      "status": exact.get("status"), "attempt_count": exact.get("attempt_count"),
                      "worker_id": exact.get("worker_id"),
                      "feature_artifact_id": exact.get("feature_artifact_id"),
                      "model_artifact_id": exact.get("model_artifact_id")}))


def replace_session(call) -> None:
    """Preserve the failed observer attempt; never retry its unknown mutation."""
    data = load()
    need(data["stage"] == "decision_attempted", "not the failed decision observer stage")
    approval = call("GET", f"/api/product/approvals/{data['approval_id']}")["approval"]
    need(approval.get("status") == "approved"
         and approval.get("resource_preview", {}).get("state") == "prepared",
         "old exact submission is no longer prepared")
    need(len(study(call, data["prior"])) == 1, "a new TrainingJob exists; reconcile it instead")
    failed_file = ROOT / ".phase15-golden-c.failed.json"
    need(not failed_file.exists(), "failed-attempt evidence already archived")
    os.rename(MANIFEST, failed_file)
    save({"scope": SCOPE, "workspace_id": WORKSPACE, "prior": data["prior"],
          "baseline_run_ids": data["baseline_run_ids"], "stage": "prepared",
          "failed_attempt": {key: data[key] for key in (
              "conversation_id", "approval_id", "watch_id", "submission_key")}})
    print(json.dumps({"stage": "prepared", "preserved_failed_attempt": True,
                      "training_submit_attempted": False}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("preflight", "request", "pending", "approve", "status", "replace-session", "receipt-only"))
    stage = parser.parse_args().stage
    call = client()
    {"preflight": preflight, "request": request, "pending": pending,
     "approve": approve, "status": status, "replace-session": replace_session,
     "receipt-only": lambda call: approve(call, receipt_only=True)}[stage](call)


if __name__ == "__main__":
    main()
