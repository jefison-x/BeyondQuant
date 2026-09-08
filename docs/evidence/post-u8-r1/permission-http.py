"""Synthetic HTTP qualification; run only inside the disposable BYQ CI network."""
import httpx

with httpx.Client(base_url="http://gateway:8100", timeout=10) as browser:
    response = browser.post("/api/auth/login", json={"username": "ci-r2-admin", "password": "ci-r2-browser-only"})
    response.raise_for_status()
    workspace = response.json()["workspace"]["workspace_id"]
    headers = {"x-byq-owner-principal": "ci-r2-admin", "x-byq-workspace-id": workspace,
               "x-byq-actor-principal": "ci-r2-admin", "x-byq-session-id": "permission-http-session",
               "x-byq-trace-id": "permission-http-trace", "x-byq-dsh-run-id": "synthetic-no-runtime"}
    with httpx.Client(base_url="http://backend:8000", headers=headers, timeout=10) as backend:
        def post(path, body):
            reply = backend.post(path, json=body)
            reply.raise_for_status()
            return reply.json()
        post("/v1/product/conversations", {"runtime_session_id": "permission-http-session", "trace_id": "permission-http-trace"})
        task = post("/v1/research/tasks", {"owner_principal": "ci-r2-admin", "title": "Synthetic permission HTTP",
            "objective": "No model or business execution", "trace_id": "permission-http-trace", "idempotency_key": "permission-http-task"})
        artifact = post("/v1/research/artifacts", {"task_id": task["task_id"], "kind": "research_note", "content": {"synthetic": True},
            "lineage": [], "trace_id": "permission-http-trace", "idempotency_key": "permission-http-artifact"})
        post(f"/v1/research/artifacts/{artifact['artifact_id']}/transitions", {"target_status": "validated", "idempotency_key": "permission-http-validate"})
    path = f"/api/product/research/tasks/{task['task_id']}/continuation-permission"
    payload = {"idempotency_key": "permission-http-confirm", "token_limit": 1000,
               "confirmed_artifact_ids": [artifact["artifact_id"]]}
    confirmation = {"x-byq-continuation-confirmation": "v1"}
    assert browser.post(path, json=payload).status_code == 403
    created = browser.post(path, json=payload, headers=confirmation)
    assert created.status_code == 201, created.status_code
    original = created.json()
    assert original["can_start"] is False
    assert original["blocked_reason"] == "budget_enforcement_unqualified"
    assert browser.post(path, json=payload, headers=confirmation).json() == original
    assert browser.get(path).json() == original
    revoked = browser.post(path + "/revoke", json={"grant_version": 1}, headers=confirmation)
    assert revoked.status_code == 200
    assert revoked.json()["blocked_reason"] == "permission_revoked"
    assert browser.post(path, json=payload, headers=confirmation).json() == revoked.json()
    assert browser.post(path, json={**payload, "token_limit": 2000}, headers=confirmation).status_code == 409
    browser.post("/api/auth/logout").raise_for_status()
    assert browser.get(path).status_code == 401
print("PASS: real personal login, explicit confirmation, durable replay, revocation, no reset, logout; no execution")
