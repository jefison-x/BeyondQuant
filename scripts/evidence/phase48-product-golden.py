#!/usr/bin/env python3
"""Run the Phase 48 no-mock, two-user Product coherence journey."""

from __future__ import annotations

import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


ORIGIN = os.environ.get("BYQ_GOLDEN_ORIGIN", "http://127.0.0.1:8710").rstrip("/")


class ProductClient:
    def __init__(self, username: str, password: str) -> None:
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        body = self.product("POST", "/auth/login", {"username": username, "password": password})
        self.user = body.get("user", {})
        if self.user.get("username") != username:
            raise AssertionError("login returned the wrong user")

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        expected_status: int | None = None,
    ) -> dict[str, object]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {} if data is None else {"content-type": "application/json"}
        request = urllib.request.Request(ORIGIN + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                status = response.status
                body = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as error:
            status = error.code
            body = json.loads(error.read().decode("utf-8") or "{}")
        if expected_status is not None and status != expected_status:
            raise AssertionError(f"{method} {path}: expected {expected_status}, got {status}: {body}")
        if expected_status is None and not 200 <= status < 300:
            raise AssertionError(f"{method} {path}: unexpected {status}: {body}")
        return body

    def product(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        expected_status: int | None = None,
    ) -> dict[str, object]:
        return self.request(method, f"/api/product{path}", payload, expected_status)


def identity(prefix: str) -> str:
    return f"p48-{prefix}-{uuid.uuid4().hex}"


def require(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    owner = ProductClient(
        os.environ.get("BYQ_GOLDEN_OWNER_USERNAME", "p48-admin"),
        os.environ.get("BYQ_GOLDEN_OWNER_PASSWORD", "P48AdminPass123"),
    )
    other = ProductClient(
        os.environ.get("BYQ_GOLDEN_OTHER_USERNAME", "p48-user"),
        os.environ.get("BYQ_GOLDEN_OTHER_PASSWORD", "P48UserPass123"),
    )
    suffix = uuid.uuid4().hex[:10]

    profile = owner.product(
        "PUT",
        "/profile",
        {
            "display_name": f"Phase 48 Owner {suffix}",
            "preferences": "低波动，先给结论再给证据",
            "default_prompt": "使用可复现数据并明确审批边界",
        },
    )["profile"]
    require(profile.get("display_name") == f"Phase 48 Owner {suffix}", "profile did not persist")
    owner_appearance = owner.product("GET", "/settings/appearance")["preferences"]
    appearance = owner.product(
        "PUT",
        "/settings/appearance",
        {
            "schema_version": "ui-preferences.v1",
            "color_mode": "dark",
            "accent_theme": "indigo",
            "expected_version": owner_appearance["version"],
        },
    )["preferences"]
    require(appearance.get("accent_theme") == "indigo", "appearance did not persist")
    other_appearance = other.product("GET", "/settings/appearance")["preferences"]
    require(other_appearance.get("version") == 0, "secondary user inherited owner appearance")

    secret = f"sk-phase48-nonproduction-{suffix}"
    credential_response = owner.product(
        "POST",
        "/settings/models/credentials",
        {
            "provider": "deepseek",
            "label": f"Phase 48 credential {suffix}",
            "secret": secret,
            "idempotency_key": identity("credential"),
        },
    )
    serialized_credential = json.dumps(credential_response, sort_keys=True)
    require(secret not in serialized_credential and "ciphertext" not in serialized_credential, "secret material leaked")
    credential_id = str(credential_response["credential"]["credential_id"])
    model_profile = owner.product(
        "POST",
        "/settings/models/profiles",
        {
            "credential_id": credential_id,
            "key_name": f"phase48-{suffix}",
            "display_name": f"Phase 48 profile {suffix}",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "temperature": 0.2,
            "reasoning_enabled": False,
        },
    )["profile"]
    model_settings = owner.product("GET", "/settings/models")
    binding = next(item for item in model_settings["bindings"] if item["agent_id"] == "byq-product")
    owner.product(
        "PUT",
        "/settings/models/bindings/byq-product",
        {"profile_id": model_profile["profile_id"], "expected_version": binding["version"]},
    )
    require(other.product("GET", "/settings/models").get("profiles") == [], "secondary user observed owner model profile")

    conversation = owner.request("POST", "/v1/agent/sessions")
    session_id = str(conversation["session_id"])
    turn = owner.request(
        "POST",
        f"/v1/agent/sessions/{urllib.parse.quote(session_id)}/turns",
        {"content": "记录 Phase 48 连续投研旅程，并保持所有操作可审计。"},
    )
    require(turn.get("accepted") is True, "conversation turn was not accepted")
    title = f"Phase 48 golden conversation {suffix}"
    owner.request("PATCH", f"/v1/agent/sessions/{session_id}", {"title": title, "pinned": True})
    replay = owner.request("GET", f"/v1/agent/sessions/{session_id}")
    require(replay["conversation"].get("title") == title, "conversation title was not restored")
    require(any(message.get("content", "").startswith("记录 Phase 48") for message in replay["messages"]), "user turn was not durable")
    other.request("GET", f"/v1/agent/sessions/{session_id}", expected_status=404)
    owner.request("PATCH", f"/v1/agent/sessions/{session_id}", {"status": "archived"})
    archived = owner.request("GET", "/v1/agent/sessions?status=archived")
    require(any(item["session_id"] == session_id for item in archived["sessions"]), "archived conversation missing")
    owner.request("PATCH", f"/v1/agent/sessions/{session_id}", {"status": "active"})

    task = owner.product(
        "POST",
        "/research/tasks",
        {"title": f"Phase 48 golden strategy {suffix}", "objective": "Prove the isolated signal-to-backtest path."},
    )
    task_id = str(task["task_id"])
    pool = owner.product(
        "POST",
        "/paper/pools",
        {"name": f"Phase 48 golden pool {suffix}", "pool_type": "custom", "symbols": ["000001.SZ"]},
    )["pool"]
    pool_id = str(pool["pool_id"])
    snapshot_id = str(pool["snapshot"]["snapshot_id"])

    source = (
        "class CustomStrategy:\n"
        "    def generate_signals(self, data, parameters=None):\n"
        "        result = {}\n"
        "        for symbol in data.index.get_level_values('symbol').unique():\n"
        "            closes = data.xs(symbol, level='symbol')['close']\n"
        "            result[str(symbol)] = (closes > closes.shift(1)).fillna(False).astype(int)\n"
        "        return result\n"
    )
    strategy = {
        "strategy_id": f"Phase48Golden{suffix}",
        "name": f"Phase 48 Golden Momentum {suffix}",
        "category": "momentum",
        "description": "Deterministic isolated signal producer evidence.",
        "parameters": {"lookback": 1},
        "parameter_schema": {"lookback": {"type": "integer", "minimum": 1}},
        "source_type": "python_script",
        "script": source,
    }
    common = {"task_id": task_id, "strategy": strategy}
    owner.product("POST", "/strategies/drafts", {**common, "trace_id": identity("draft"), "idempotency_key": identity("draft")})
    validated = owner.product("POST", "/strategies/validate", {**common, "trace_id": identity("validate"), "idempotency_key": identity("validate")})
    version = owner.product(
        "POST",
        "/strategies/versions",
        {
            "task_id": task_id,
            "draft_artifact_id": validated["artifact"]["artifact_id"],
            "trace_id": identity("version"),
            "idempotency_key": identity("version"),
        },
    )
    version_id = str(version["artifact"]["artifact_id"])
    approval = owner.product(
        "POST",
        "/strategies/approvals",
        {
            "task_id": task_id,
            "strategy_version_artifact_id": version_id,
            "decision": "approved",
            "rationale": "Phase 48 owner approval.",
            "trace_id": identity("approval"),
            "idempotency_key": identity("approval"),
        },
    )
    approval_id = str(approval["artifact"]["artifact_id"])
    produced = owner.product(
        "POST",
        "/signal-producer/jobs",
        {
            "task_id": task_id,
            "strategy_version_artifact_id": version_id,
            "stock_pool_snapshot_id": snapshot_id,
            "start_date": "2026-01-05",
            "end_date": "2026-01-07",
            "parameters": {"lookback": 1},
            "execution": {
                "initial_capital": 100000,
                "commission_rate": 0.0003,
                "stamp_tax_rate": 0.001,
                "slippage_rate": 0,
                "lot_size": 100,
                "max_positions": 10,
                "a_share_rules": True,
                "max_runtime_seconds": 10,
                "max_attempts": 2,
            },
            "order_quantity": 100,
            "trace_id": identity("signal"),
            "idempotency_key": identity("signal"),
        },
    )
    signal_job = produced["job"]
    signal_job_id = str(signal_job["job_id"])
    for _ in range(30):
        if signal_job.get("status") in {"completed", "failed"}:
            break
        time.sleep(1)
        signal_job = owner.product("GET", f"/signal-producer/jobs/{signal_job_id}")["job"]
    require(signal_job.get("status") == "completed", f"signal job did not complete: {signal_job}")
    signal_artifact_id = str(signal_job["result_artifact_id"])
    backtest = owner.product(
        "POST",
        "/backtests",
        {
            "task_id": task_id,
            "strategy_version_artifact_id": version_id,
            "approval_artifact_id": approval_id,
            "signal_snapshot_artifact_id": signal_artifact_id,
            "trace_id": identity("backtest"),
            "idempotency_key": identity("backtest"),
        },
    )
    backtest_job_id = str(backtest["job"]["job_id"])
    completed = owner.product("POST", f"/backtests/{backtest_job_id}/run")["job"]
    require(completed.get("status") == "completed", f"backtest did not complete: {completed}")
    result = owner.product("GET", f"/backtests/{backtest_job_id}/result")["result"]

    assets = owner.product("GET", "/settings/assets")
    require(assets["summary"]["strategies"] >= 1 and assets["summary"]["backtests"] >= 1 and assets["summary"]["pools"] >= 1, "asset summary omitted golden resources")
    bundle = owner.product("GET", "/settings/assets/export")
    require(bundle.get("schema_version") == "byq-workspace-assets-v2", "asset bundle schema mismatch")
    require("secret" not in json.dumps(bundle).lower(), "asset bundle contains secret-like fields")
    imported = owner.product("POST", "/settings/assets/import", bundle)

    operations = owner.product("GET", "/operations/status")
    require(operations.get("schema_version") == "operations.v1", "admin operations projection mismatch")
    require(operations.get("observability", {}).get("raw_dsh_events") is False, "raw DSH events crossed Product boundary")
    users = owner.product("GET", "/admin/users")
    require(len(users.get("users", [])) >= 2, "admin user list omitted the secondary user")
    other.product("GET", "/operations/status", expected_status=403)
    other.product("GET", "/admin/users", expected_status=403)
    other.product("GET", f"/research/tasks/{task_id}", expected_status=404)
    other.product("GET", f"/paper/pools/{pool_id}", expected_status=404)
    other.product("GET", f"/signal-producer/jobs/{signal_job_id}", expected_status=404)
    require(other.product("GET", "/strategies").get("total") == 0, "secondary user observed owner strategies")
    require(other.product("GET", "/backtests").get("backtests") == [], "secondary user observed owner backtests")
    require(other.product("GET", "/settings/assets")["summary"] == {"strategies": 0, "backtests": 0, "pools": 0, "paper_accounts": 0}, "secondary user observed owner assets")

    print(
        json.dumps(
            {
                "schema_version": "phase-48-product-coherence-v1",
                "status": "passed",
                "product_origin": ORIGIN,
                "conversation": {"session_id": session_id, "title": title, "turn_accepted": True, "restored": True},
                "owner_flow": {
                    "task_id": task_id,
                    "pool_id": pool_id,
                    "strategy_version_artifact_id": version_id,
                    "approval_artifact_id": approval_id,
                    "signal_job_id": signal_job_id,
                    "signal_snapshot_artifact_id": signal_artifact_id,
                    "backtest_job_id": backtest_job_id,
                    "backtest_status": completed["status"],
                    "trade_count": result.get("trade_count"),
                },
                "personalization": {"profile": True, "appearance": appearance["accent_theme"], "model_binding": True},
                "assets": {"schema_version": bundle["schema_version"], "imported": imported.get("imported")},
                "administration": {"operations": "operations.v1", "users": len(users.get("users", [])), "raw_dsh_events": False},
                "secondary_user": {"owner_resources_hidden": True, "admin_status": 403, "appearance_version": 0},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
