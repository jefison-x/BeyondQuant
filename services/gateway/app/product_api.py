"""Phase 16 browser Product API/BFF.

This router is the only browser-facing product boundary. It never forwards
MCP tokens, provider credentials, DSH events, or raw Backend storage details.
"""

from __future__ import annotations

import os
import uuid

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .auth import AuthenticationUnavailable, Principal, authenticate_bearer
from .user_session import SESSION_COOKIE, ProductAuthError, login as login_user, logout as logout_user, resolve_principal, resolve_user


SERVICE = "byq-gateway"
PRODUCT_TOKEN = os.environ.get("BYQ_PRODUCT_TOKEN")
PRODUCT_PRINCIPAL = os.environ.get("BYQ_PRODUCT_PRINCIPAL", "product-user")
BACKEND_URL = os.environ.get("BYQ_BACKEND_URL", "http://backend:8000")
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


@router.get("/data-center/status")
def product_data_center_status(request: Request) -> dict[str, object]:
    _product_principal(request)
    return {
        "migration": "not_started",
        "datasets": [],
        "provider": "tushare",
        "quality": "not_audited",
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


@router.post("/paper/accounts", status_code=201)
def product_paper_account_create(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("POST", "/v1/paper/accounts", payload)


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
    return _backend_request("POST", "/v1/paper/pools", payload)


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
    return _backend_request("POST", "/v1/paper/orders", payload)


@router.get("/paper/accounts/{account_id}/orders")
def product_paper_orders(account_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/paper/accounts/{account_id}/orders")


@router.get("/paper/accounts/{account_id}/positions")
def product_paper_positions(account_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/paper/accounts/{account_id}/positions")


@router.get("/paper/accounts/{account_id}/fills")
def product_paper_fills(account_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/paper/accounts/{account_id}/fills")


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
