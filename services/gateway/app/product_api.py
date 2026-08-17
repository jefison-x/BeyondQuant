"""Phase 16 browser Product API/BFF.

This router is the only browser-facing product boundary. It never forwards
MCP tokens, provider credentials, DSH events, or raw Backend storage details.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .auth import AuthenticationUnavailable, Principal, authenticate_bearer
from .user_session import SESSION_COOKIE, ProductAuthError, login as login_user, logout as logout_user, resolve_principal, resolve_user


SERVICE = "byq-gateway"
PRODUCT_TOKEN = os.environ.get("BYQ_PRODUCT_TOKEN")
PRODUCT_PRINCIPAL = os.environ.get("BYQ_PRODUCT_PRINCIPAL", "product-user")
BACKEND_URL = os.environ.get("BYQ_BACKEND_URL", "http://backend:8000")
_SECRET_KEY_FRAGMENTS = (
    "token",
    "password",
    "secret",
    "apikey",
    "accesskey",
    "privatekey",
    "credential",
    "authorization",
)
router = APIRouter(prefix="/api/product")


class ProductError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.request_id = uuid.uuid4().hex


def _authenticate(authorization: str | None) -> Principal:
    try:
        return authenticate_bearer(
            authorization,
            configured_token=PRODUCT_TOKEN,
            subject=PRODUCT_PRINCIPAL,
        )
    except AuthenticationUnavailable as exc:
        raise ProductError(503, "product_authentication_unavailable", "product authentication is unavailable") from exc
    except PermissionError as exc:
        raise ProductError(401, "product_authentication_required", "product authentication required") from exc


def _product_principal(request: Request) -> Principal:
    if SESSION_COOKIE in request.cookies:
        try:
            return resolve_principal(request)
        except ProductAuthError as exc:
            raise ProductError(exc.status_code, exc.code, exc.message) from exc
    return _authenticate(request.headers.get("authorization"))


def _trusted_agent_headers(request: Request) -> dict[str, str]:
    """Build backend-owned agent context headers for browser Product API calls."""
    principal = _product_principal(request)
    session_id = request.cookies.get(SESSION_COOKIE, "browser")
    return {
        "x-byq-owner-principal": principal.subject,
        "x-byq-actor-principal": principal.subject,
        "x-byq-trace-id": f"product-{uuid.uuid4().hex}",
        "x-byq-session-id": session_id,
        "x-byq-dsh-run-id": "browser",
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_profile(user: dict[str, object]) -> dict[str, object]:
    return {
        "subject": str(user.get("username") or user.get("user_id")),
        "display_name": str(user.get("display_name") or ""),
        "preferences": user.get("preferences") or "",
        "default_prompt": user.get("default_prompt") or "",
        "role": str(user.get("role", "user")),
        "status": str(user.get("status", "active")),
    }


def _reject_secret_fields(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            if any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS):
                raise ProductError(422, "product_asset_bundle_invalid", "asset bundle must not contain credential fields")
            _reject_secret_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_secret_fields(nested)


def _owner_scoped_list(path: str, key: str, headers: dict[str, str]) -> list[object]:
    try:
        body = _backend_request("GET", path, headers=headers)
    except ProductError:
        return []
    items = body.get(key, [])
    return items if isinstance(items, list) else []


def _asset_lists(request: Request) -> tuple[list[object], list[object], list[object], list[object]]:
    headers = _trusted_agent_headers(request)
    artifacts = _owner_scoped_list("/v1/research/artifacts", "artifacts", headers)
    strategies = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict) and artifact.get("kind") in {"strategy_version", "strategy_draft"}
    ]
    backtests = _owner_scoped_list("/v1/research/backtests", "backtests", headers)
    pools = _owner_scoped_list("/v1/paper/pools", "pools", headers)
    accounts = _owner_scoped_list("/v1/paper/accounts", "accounts", headers)
    return strategies, backtests, pools, accounts


def _clean_pool(pool: object) -> dict[str, object]:
    if not isinstance(pool, dict):
        raise ValueError("pool asset must be an object")
    result: dict[str, object] = {}
    for key in ("name", "symbols", "provenance"):
        if key in pool:
            result[key] = pool[key]
    return result


def _clean_account(account: object) -> dict[str, object]:
    if not isinstance(account, dict):
        raise ValueError("paper account asset must be an object")
    result: dict[str, object] = {}
    for key in ("name", "cash"):
        if key in account:
            result[key] = account[key]
    return result


def _backend_get(path: str) -> dict[str, object]:
    try:
        response = httpx.get(f"{BACKEND_URL}{path}", timeout=3.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProductError(503, "backend_unavailable", "backend is unavailable") from exc
    body = response.json()
    if not isinstance(body, dict):
        raise ProductError(502, "backend_invalid_response", "backend returned an invalid response")
    return body


def _backend_request(
    method: str,
    path: str,
    payload: object | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    try:
        response = httpx.request(
            method,
            f"{BACKEND_URL}{path}",
            json=payload,
            headers=headers,
            timeout=8.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProductError(503, "backend_unavailable", "backend is unavailable") from exc
    body = response.json()
    if not isinstance(body, dict):
        raise ProductError(502, "backend_invalid_response", "backend returned an invalid response")
    return body


@router.get("/health")
def product_health(request: Request) -> dict[str, object]:
    _product_principal(request)
    return {"status": "ok", "service": SERVICE}


@router.post("/auth/login")
def product_login(request: Request, payload: dict[str, object]) -> dict[str, object]:
    username = payload.get("username")
    password = payload.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise ProductError(422, "product_request_invalid", "username and password are required")
    try:
        result = login_user(username, password)
    except ProductAuthError as exc:
        raise ProductError(exc.status_code, exc.code, exc.message) from exc
    response = JSONResponse(
        content={"user": result.get("user", {})},
    )
    session_id = result.get("session_id")
    if isinstance(session_id, str):
        response.set_cookie(
            SESSION_COOKIE,
            session_id,
            httponly=True,
            samesite="lax",
            path="/",
        )
    return response


@router.post("/auth/logout")
def product_logout(request: Request) -> dict[str, object]:
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        try:
            logout_user(session_id)
        except ProductAuthError:
            pass
    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/auth/me")
def product_me(request: Request) -> dict[str, object]:
    principal = _product_principal(request)
    return {"subject": principal.subject}


@router.get("/dashboard")
def product_dashboard(request: Request) -> dict[str, object]:
    _product_principal(request)
    backend = _backend_get("/readyz")
    headers = _trusted_agent_headers(request)
    counts: dict[str, object] = {}
    for path, key in (
        ("/v1/research/tasks", "tasks"),
        ("/v1/research/experiments", "experiments"),
        ("/v1/research/artifacts", "artifacts"),
        ("/v1/research/backtests", "backtests"),
    ):
        try:
            body = _backend_request("GET", path, headers=headers)
            counts[key] = len(body.get(key, body.get("artifacts", [])))
        except ProductError:
            counts[key] = "unavailable"
    return {
        "status": "ok",
        "resources": {
            "backend": str(backend.get("status", "unknown")),
            "data": "not_loaded",
            "migration": "not_started",
            "counts": counts,
        },
    }


@router.get("/data/status")
def product_data_status(request: Request) -> dict[str, object]:
    _product_principal(request)
    backend = _backend_get("/readyz")
    return {
        "status": "ok",
        "provider": "tushare",
        "migration": "not_started",
        "backend": str(backend.get("status", "unknown")),
    }


@router.get("/research/{entity_type}/{entity_id}")
def product_research_entity(entity_type: str, entity_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    if entity_type not in {"tasks", "experiments", "artifacts"}:
        raise ProductError(404, "product_entity_not_found", "research entity type is not supported")
    return _backend_request("GET", f"/v1/research/{entity_type}/{entity_id}")


@router.get("/research/artifacts")
def product_artifacts(request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", "/v1/research/artifacts", headers=_trusted_agent_headers(request))


@router.get("/research/tasks")
def product_research_tasks(request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", "/v1/research/tasks", headers=_trusted_agent_headers(request))


@router.get("/research/experiments")
def product_research_experiments(request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", "/v1/research/experiments", headers=_trusted_agent_headers(request))


@router.get("/backtests/{job_id}")
def product_backtest_get(job_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/research/backtests/{job_id}")


@router.get("/backtests/{job_id}/result")
def product_backtest_result(job_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET",
        f"/v1/research/backtests/{job_id}/result",
        headers=_trusted_agent_headers(request),
    )


@router.get("/backtests")
def product_backtests(request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", "/v1/research/backtests", headers=_trusted_agent_headers(request))


@router.post("/backtests/{job_id}/run")
def product_backtest_run(job_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("POST", f"/v1/research/backtests/{job_id}/run")


@router.post("/backtests/{job_id}/cancel")
def product_backtest_cancel(job_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("POST", f"/v1/research/backtests/{job_id}/cancel")


@router.get("/strategies/versions/{artifact_id}/export")
def product_strategy_export(artifact_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/research/strategies/versions/{artifact_id}/export")


@router.get("/strategies")
def product_strategies(request: Request) -> dict[str, object]:
    _product_principal(request)
    body = _backend_request("GET", "/v1/research/artifacts", headers=_trusted_agent_headers(request))
    artifacts = body.get("artifacts", [])
    if isinstance(artifacts, list):
        return {"strategies": [a for a in artifacts if isinstance(a, dict) and a.get("kind") in {"strategy_version", "strategy_draft"}]}
    return {"strategies": []}


@router.post("/strategies/validate", status_code=201)
def product_strategy_validate(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("POST", "/v1/research/strategies/validate", payload)


@router.post("/strategies/versions", status_code=201)
def product_strategy_version_create(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST",
        "/v1/research/strategies/versions",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.get("/factors")
def product_factors(request: Request) -> dict[str, object]:
    _product_principal(request)
    body = _backend_request("GET", "/v1/research/artifacts", headers=_trusted_agent_headers(request))
    artifacts = body.get("artifacts", [])
    if isinstance(artifacts, list):
        return {"factors": [a for a in artifacts if isinstance(a, dict) and a.get("kind") == "factor_result"]}
    return {"factors": []}


@router.get("/approvals/{approval_id}")
def product_approval_get(approval_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET",
        f"/v1/agents/approvals/{approval_id}",
        headers=_trusted_agent_headers(request),
    )


@router.get("/approvals")
def product_approvals(request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", "/v1/agents/approvals", headers=_trusted_agent_headers(request))


@router.post("/approvals/{approval_id}/decision")
def product_approval_decision(approval_id: str, request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST",
        f"/v1/agents/approvals/{approval_id}/decision",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.get("/data-center/status")
def product_data_center_status(request: Request) -> dict[str, object]:
    _product_principal(request)
    return {
        "migration": "not_started",
        "datasets": [],
        "provider": "tushare",
        "quality": "not_audited",
        "provider_status": {
            "configured": bool(os.environ.get("TUSHARE_TOKEN")),
            "sync": "not_started",
        },
    }


@router.get("/admin/users")
def product_admin_users(request: Request) -> dict[str, object]:
    user = resolve_user(request)
    if user.get("role") != "admin":
        raise ProductError(403, "product_forbidden", "admin role required")
    return _backend_request("GET", "/v1/users", headers={"x-byq-actor-role": "admin"})


@router.post("/admin/users/{user_id}/disable")
def product_admin_disable_user(user_id: str, request: Request) -> dict[str, object]:
    user = resolve_user(request)
    if user.get("role") != "admin":
        raise ProductError(403, "product_forbidden", "admin role required")
    return _backend_request("POST", f"/v1/users/{user_id}/disable", headers={"x-byq-actor-role": "admin"})


@router.get("/settings/status")
def product_settings_status(request: Request) -> dict[str, object]:
    _product_principal(request)
    return {
        "profile": {"configured": True},
        "model_provider": {"configured": False},
        "data_provider": {"provider": "tushare", "migration": "not_started"},
        "storage": {"status": "ready"},
        "approval_inbox": {"pending": 0},
    }


@router.get("/profile")
def product_profile_get(request: Request) -> dict[str, object]:
    return {"profile": _public_profile(resolve_user(request))}


@router.put("/profile")
def product_profile_update(request: Request, payload: dict[str, object]) -> dict[str, object]:
    user = resolve_user(request)
    user_id = user.get("user_id")
    if not isinstance(user_id, str):
        raise ProductError(502, "backend_invalid_response", "backend returned an invalid user")
    body = _backend_request(
        "PUT",
        f"/v1/users/{user_id}/profile",
        payload,
        headers={"x-byq-owner-user-id": user_id},
    )
    updated = body.get("user")
    if not isinstance(updated, dict):
        raise ProductError(502, "backend_invalid_response", "backend returned an invalid user")
    return {"profile": _public_profile(updated)}


@router.get("/settings/models")
def product_model_settings(request: Request) -> dict[str, object]:
    _product_principal(request)
    return {
        "provider": "deepseek",
        "configured": bool(os.environ.get("DEEPSEEK_API_KEY")),
        "models": [],
        "credentials": {"masked": True, "write_only": True},
    }


@router.get("/settings/agent-policy")
def product_agent_policy(request: Request) -> dict[str, object]:
    _product_principal(request)
    approvals = _owner_scoped_list("/v1/agents/approvals", "approvals", _trusted_agent_headers(request))
    pending = sum(1 for approval in approvals if isinstance(approval, dict) and approval.get("status") == "pending")
    personal = _backend_request(
        "GET",
        "/v1/users/agent-policy",
        headers=_trusted_agent_headers(request),
    ).get("policy", {})
    return {
        "platform_policy": {
            "automation_enabled": False,
            "paused": False,
            "default_decision_mode": "manual",
            "max_auto_executions_per_hour": 20,
            "max_auto_failures_per_hour": 3,
        },
        "personal_policy": personal,
        "approval_inbox": {"pending": pending},
    }


@router.put("/settings/agent-policy")
def product_agent_policy_update(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    body = _backend_request(
        "PUT",
        "/v1/users/agent-policy",
        payload,
        headers=_trusted_agent_headers(request),
    )
    return {"personal_policy": body.get("policy", {})}


@router.get("/settings/assets")
def product_assets(request: Request) -> dict[str, object]:
    _product_principal(request)
    strategies, backtests, pools, accounts = _asset_lists(request)
    return {
        "strategies": strategies,
        "backtests": backtests,
        "pools": pools,
        "paper_accounts": accounts,
        "summary": {
            "strategies": len(strategies),
            "backtests": len(backtests),
            "pools": len(pools),
            "paper_accounts": len(accounts),
        },
    }


@router.get("/settings/assets/export")
def product_assets_export(request: Request) -> dict[str, object]:
    principal = _product_principal(request)
    strategies, backtests, pools, accounts = _asset_lists(request)
    return {
        "schema_version": "byq-workspace-assets-v1",
        "exported_at": _now(),
        "owner_principal": principal.subject,
        "assets": {
            "strategies": strategies,
            "backtests": backtests,
            "pools": pools,
            "paper_accounts": accounts,
        },
    }


@router.post("/settings/assets/import")
def product_assets_import(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    if not isinstance(payload, dict) or payload.get("schema_version") != "byq-workspace-assets-v1":
        raise ProductError(422, "product_asset_bundle_invalid", "asset bundle is invalid")
    assets = payload.get("assets")
    if not isinstance(assets, dict):
        raise ProductError(422, "product_asset_bundle_invalid", "asset bundle is invalid")
    _reject_secret_fields(assets)

    headers = _trusted_agent_headers(request)
    imported_pools = 0
    imported_accounts = 0
    errors: list[dict[str, str]] = []

    pools = assets.get("pools", [])
    if not isinstance(pools, list):
        pools = []
    for pool in pools:
        try:
            _backend_request("POST", "/v1/paper/pools", _clean_pool(pool), headers=headers)
            imported_pools += 1
        except (ProductError, ValueError) as exc:
            errors.append({"kind": "pool", "message": str(exc)})

    accounts = assets.get("paper_accounts", [])
    if not isinstance(accounts, list):
        accounts = []
    for account in accounts:
        try:
            _backend_request("POST", "/v1/paper/accounts", _clean_account(account), headers=headers)
            imported_accounts += 1
        except (ProductError, ValueError) as exc:
            errors.append({"kind": "paper_account", "message": str(exc)})

    strategies = assets.get("strategies", [])
    backtests = assets.get("backtests", [])
    return {
        "imported": {"pools": imported_pools, "paper_accounts": imported_accounts},
        "skipped": {
            "strategies": len(strategies) if isinstance(strategies, list) else 0,
            "backtests": len(backtests) if isinstance(backtests, list) else 0,
            "reason": "research artifacts require validation or recomputation",
        },
        "errors": errors,
    }


@router.post("/paper/accounts", status_code=201)
def product_paper_account_create(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST",
        "/v1/paper/accounts",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.get("/paper/accounts/{account_id}")
def product_paper_account_get(account_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/paper/accounts/{account_id}")


@router.get("/paper/accounts")
def product_paper_accounts(request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", "/v1/paper/accounts", headers=_trusted_agent_headers(request))


@router.post("/paper/pools", status_code=201)
def product_stock_pool_create(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST",
        "/v1/paper/pools",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.get("/paper/pools/{pool_id}")
def product_stock_pool_get(pool_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/paper/pools/{pool_id}")


@router.get("/paper/pools")
def product_stock_pools(request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", "/v1/paper/pools", headers=_trusted_agent_headers(request))


@router.post("/paper/orders", status_code=201)
def product_paper_order_create(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST",
        "/v1/paper/orders",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.get("/paper/accounts/{account_id}/orders")
def product_paper_orders(account_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET",
        f"/v1/paper/accounts/{account_id}/orders",
        headers=_trusted_agent_headers(request),
    )


@router.get("/paper/accounts/{account_id}/positions")
def product_paper_positions(account_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET",
        f"/v1/paper/accounts/{account_id}/positions",
        headers=_trusted_agent_headers(request),
    )


@router.get("/paper/accounts/{account_id}/fills")
def product_paper_fills(account_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET",
        f"/v1/paper/accounts/{account_id}/fills",
        headers=_trusted_agent_headers(request),
    )


@router.get("/paper/accounts/{account_id}/ledger")
def product_paper_ledger(account_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET",
        f"/v1/paper/accounts/{account_id}/ledger",
        headers=_trusted_agent_headers(request),
    )


@router.get("/operations/status")
def product_operations_status(request: Request) -> dict[str, object]:
    _product_principal(request)
    backend = _backend_get("/readyz")
    return {
        "backend": str(backend.get("status", "unknown")),
        "runtime": "runtime-adapter",
        "storage": "ready",
        "migration": "not_started",
        "observability": {
            "workflow_trace": "configured",
            "audit": "configured",
        },
    }
