#!/usr/bin/env python3
"""Interrupt and reclaim the exact authorized CPU Job; never submit a Job."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.dev.environment import local_env, compose_args, call as compose_call

spec = importlib.util.spec_from_file_location("golden_c", ROOT / "scripts/evidence/phase15-golden-c.py")
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)
VALUES = local_env()
assert VALUES["BYQ_DEV_SCOPE"] == evidence.SCOPE
port = compose_call(compose_args("port", "gateway", "8100"), VALUES, capture=True)
assert port.returncode == 0
evidence.BASE = "http://" + port.stdout.strip()


def compose(*parts: str) -> str:
    result = compose_call(compose_args(*parts), VALUES, capture=True)
    evidence.need(result.returncode == 0, "exact isolated Worker command failed; reconcile before retry")
    return result.stdout.strip()


def worker() -> dict[str, object]:
    identity = compose("ps", "--all", "-q", "ml-worker")
    evidence.need(re.fullmatch(r"[0-9a-f]{64}", identity), "isolated ML Worker is not unique")
    result = subprocess.run(["docker", "inspect", identity], capture_output=True, text=True)
    evidence.need(result.returncode == 0, "Worker inspection unavailable")
    value = json.loads(result.stdout)[0]
    evidence.need(value["Config"]["Labels"].get("com.docker.compose.project") == evidence.SCOPE
                  and value["Config"]["Labels"].get("com.docker.compose.service") == "ml-worker",
                  "Worker ownership differs from exact isolated project")
    return {"container_id": value["Id"], "image_id": value["Image"],
            "state": value["State"]["Status"], "exit_code": value["State"]["ExitCode"],
            "nano_cpus": value["HostConfig"]["NanoCpus"]}


def exact(call, data):
    run = call("GET", f"/api/product/ml/training-runs/{data['new_run_id']}")["training_run"]
    evidence.need(run["training_run_id"] == data["new_run_id"]
                  and run["idempotency_key"] == data["submission_key"]
                  and run["task_id"] == data["prior"]["task_id"]
                  and run["ml_strategy_artifact_id"] == data["prior"]["strategy_artifact_id"]
                  and run["stock_pool_snapshot_id"] == data["prior"]["pool_snapshot_id"],
                  "Worker observation changed the exact approved submission")
    return run


def interrupt(call, data):
    evidence.need(data["stage"] == "approved" and "worker_evidence" not in data,
                  "Worker interruption already attempted")
    for line in compose("ps", "--format", "json").splitlines():
        item = json.loads(line)
        evidence.need(item.get("Service") not in {"data-worker", "ml-worker"}
                      or item.get("State") != "running", "Data/ML Worker must initially be stopped")
    evidence.need(exact(call, data)["status"] in {"waiting_for_data", "queued"}, "Job already terminal or claimed")
    data["worker_evidence"] = {"stage": "start_attempted", "initial_cpu_limit": 0.1,
                               "reason": "bound CPU to observe the small real workload before completion"}
    evidence.save(data)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", dir="/tmp") as override:
        override.write("services:\n  ml-worker:\n    cpus: 0.1\n")
        override.flush()
        compose("-f", override.name, "up", "-d", "--no-deps", "ml-worker")
    before_worker = worker()
    evidence.need(before_worker["state"] == "running" and before_worker["nano_cpus"] == 100000000,
                  "bounded real CPU Worker did not start")
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        run = exact(call, data)
        evidence.need(run["status"] not in {"completed", "failed", "cancelled"},
                      "Job became terminal before interruption; do not create a replacement")
        if run["status"] == "running":
            evidence.need(run["attempt_count"] == 1 and isinstance(run.get("worker_id"), str)
                          and run.get("lease_expires_at"), "first active Worker claim is not proven")
            data["worker_evidence"].update(stage="stop_attempted", before_worker=before_worker,
                before_job={key: run.get(key) for key in (
                    "training_run_id", "status", "attempt_count", "worker_id", "lease_expires_at")})
            evidence.save(data)
            compose("stop", "-t", "0", "ml-worker")
            after_worker = worker()
            after_job = exact(call, data)
            data["worker_evidence"].update(after_worker=after_worker,
                after_job={key: after_job.get(key) for key in (
                    "training_run_id", "status", "attempt_count", "worker_id", "lease_expires_at")})
            evidence.save(data)
            evidence.need(after_worker["state"] == "exited" and after_worker["exit_code"] == 137
                          and after_job["status"] == "running"
                          and after_job["attempt_count"] == run["attempt_count"],
                          "nonterminal hard interruption was not confirmed")
            data["worker_evidence"]["stage"] = "interrupted"
            evidence.save(data)
            print(json.dumps(data["worker_evidence"]))
            return
        time.sleep(0.05)
    raise evidence.EvidenceError("no running claim observed in the bounded interval")


def restart(call, data):
    observation = data.get("worker_evidence", {})
    evidence.need(observation.get("stage") == "interrupted", "no confirmed exact interruption")
    evidence.need(worker()["state"] == "exited" and exact(call, data)["status"] == "running",
                  "interrupted Worker/Job state changed")
    observation["stage"] = "restart_attempted"
    evidence.save(data)
    # Restore the committed normal CPU allocation; no lease or Job row is edited.
    compose("up", "-d", "--no-deps", "ml-worker")
    restarted = worker()
    evidence.need(restarted["state"] == "running" and restarted["nano_cpus"] == 2000000000
                  and restarted["container_id"] != observation["before_worker"]["container_id"],
                  "normal independent Worker recreation was not confirmed")
    observation.update(stage="restarted", restarted_worker=restarted)
    evidence.save(data)
    print(json.dumps(observation))


def finish(call, data):
    observation = data.get("worker_evidence", {})
    evidence.need(observation.get("stage") == "restarted", "exact Worker restart not confirmed")
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        run = exact(call, data)
        evidence.need(run["status"] not in {"failed", "cancelled"}, "reclaimed CPU TrainingJob did not complete")
        if run["status"] == "completed":
            evidence.need(run["attempt_count"] == observation["before_job"]["attempt_count"] + 1,
                          "same Job did not acquire exactly one new Worker attempt")
            evidence.need(len(evidence.study(call, data["prior"])) == 2, "unexpected duplicate TrainingJob")
            artifacts = call("GET", "/api/product/research/artifacts")["artifacts"]
            evidence.need(len(artifacts) < 200, "Artifact list capped; duplicate result count is unproven")
            counts = {}
            for kind, field in (("ml_feature_snapshot", "feature_artifact_id"), ("ml_model", "model_artifact_id")):
                result_artifact = call("GET", f"/api/product/research/artifacts/{run[field]}")
                evidence.need(isinstance(result_artifact.get("content_sha256"), str)
                              and {"kind": "artifact", "id": data["prior"]["strategy_artifact_id"]} in result_artifact.get("lineage", [])
                              and {"kind": "stock_pool_snapshot", "id": data["prior"]["pool_snapshot_id"]} in result_artifact.get("lineage", []),
                              "result Artifact lacks frozen strategy/pool provenance")
                # Identical cached features may legitimately reuse the baseline
                # content-addressed Artifact, whose original lineage is retained.
                matches = [item for item in artifacts if item.get("kind") == kind
                           and item.get("task_id") == data["prior"]["task_id"]
                           and (item.get("content_sha256") == result_artifact.get("content_sha256")
                                if kind == "ml_feature_snapshot" else
                                {"kind": "ml_training_run", "id": run["training_run_id"]} in item.get("lineage", []))]
                evidence.need(len(matches) == 1 and matches[0]["artifact_id"] == run[field],
                              "duplicate or mismatched result Artifact for the exact Job")
                counts[kind] = len(matches)
            evidence.status(call)  # Exact Feature/Model Artifact and object metadata validation.
            data = evidence.load()
            observation = data["worker_evidence"]
            observation.update(stage="complete", result_artifact_counts=counts, final_job={key: run.get(key) for key in (
                "training_run_id", "status", "attempt_count", "worker_id", "feature_artifact_id", "model_artifact_id")})
            compose("stop", "ml-worker")
            evidence.need(worker()["state"] == "exited", "CPU Worker did not stop after completion")
            data["stage"] = "complete"
            evidence.save(data)
            print(json.dumps(observation))
            return
        time.sleep(2)
    raise evidence.EvidenceError("same Job did not complete within the natural lease/reclaim interval")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("interrupt", "restart", "finish"))
    stage = parser.parse_args().stage
    {"interrupt": interrupt, "restart": restart, "finish": finish}[stage](evidence.client(), evidence.load())
