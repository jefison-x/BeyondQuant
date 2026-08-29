#!/usr/bin/env python3
"""Verify Phase 74 persistence, safe projection, and two-user isolation."""
from __future__ import annotations
import argparse, http.cookiejar, json, os, urllib.error, urllib.request

ORIGIN = os.environ.get("BYQ_GOLDEN_ORIGIN", "http://127.0.0.1:18080").rstrip("/")

class Client:
    def __init__(self, username: str, password: str) -> None:
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.call("POST", "/api/product/auth/login", {"username": username, "password": password}, 200)
    def call(self, method: str, path: str, payload=None, expected=200):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(ORIGIN + path, data=data, headers={"content-type": "application/json"} if data else {}, method=method)
        try:
            with self.opener.open(request, timeout=30) as response: status, body = response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error: status, body = error.code, json.loads(error.read() or b"{}")
        if status != expected: raise AssertionError(f"{method} {path}: expected {expected}, got {status}: {body}")
        return body

def identities(workspace: dict) -> dict[str, str]:
    training = next((run for run in workspace["training_runs"] if run.get("status") == "completed" and run.get("model_artifact_id")), None)
    prediction = next((run for run in workspace["prediction_runs"] if run.get("status") == "completed" and run.get("signal_artifact_id")), None)
    if not training or not prediction: raise AssertionError("completed Phase 74 training/prediction is unavailable")
    artifact_ids = {item["artifact_id"] for item in workspace["artifacts"]}
    required = {training["model_artifact_id"], prediction["prediction_artifact_id"], prediction["signal_artifact_id"]}
    if not required.issubset(artifact_ids): raise AssertionError("completed ML artifact projection is incomplete")
    serialized = json.dumps(workspace, sort_keys=True)
    if "object_reference" in serialized or "ml_feature_snapshot" in serialized: raise AssertionError("private model/feature material leaked")
    return {"training_run_id": training["training_run_id"], "model_artifact_id": training["model_artifact_id"], "prediction_run_id": prediction["prediction_run_id"], "prediction_artifact_id": prediction["prediction_artifact_id"], "signal_artifact_id": prediction["signal_artifact_id"]}

def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("manifest"); parser.add_argument("--verify", action="store_true"); args = parser.parse_args()
    owner = Client(os.environ.get("BYQ_GOLDEN_OWNER_USERNAME", "ci-admin"), os.environ.get("BYQ_GOLDEN_OWNER_PASSWORD", "ci-bootstrap-test-only"))
    current = identities(owner.call("GET", "/api/product/ml/workspace"))
    if args.verify:
        with open(args.manifest, encoding="utf-8") as handle: expected = json.load(handle)
        if current != expected: raise AssertionError("ML identities changed across worker restart")
    else:
        with open(args.manifest, "w", encoding="utf-8") as handle: json.dump(current, handle, sort_keys=True)
    other = Client("phase74-user", "phase74-user-test-only")
    isolated = other.call("GET", "/api/product/ml/workspace")
    if isolated["training_runs"] or isolated["prediction_runs"] or isolated["artifacts"]: raise AssertionError("secondary user can see owner ML resources")
    other.call("GET", f"/api/product/ml/training-runs/{current['training_run_id']}", expected=404)
    print(json.dumps({"status": "passed", "restart_verified": args.verify, "owner_identities": current, "secondary_user_hidden": True}, ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
