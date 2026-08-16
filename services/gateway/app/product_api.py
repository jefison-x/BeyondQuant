"""Phase 16 browser Product API/BFF.

This router is the only browser-facing product boundary. It never forwards
MCP tokens, provider credentials, DSH events, or raw Backend storage details.
"""

from __future__ import annotations

import os
import uuid

import httpx
from fastapi import APIRouter, Request

from .auth import AuthenticationUnavailable, Principal, authenticate_bearer


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
    return _authenticate(request.headers.get("authorization"))


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


def _backend_request(method: str, path: str, payload: object | None = None) -> dict[str, object]:
    try:
        response = httpx.request(
            method,
            f"{BACKEND_URL}{path}",
            json=payload,
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


@router.get("/dashboard")
def product_dashboard(request: Request) -> dict[str, object]:
    _product_principal(request)
    backend = _backend_get("/readyz")
    return {
        "status": "ok",
        "resources": {
            "backend": str(backend.get("status", "unknown")),
            "data": "not_loaded",
            "migration": "not_started",
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


@router.get("/backtests/{job_id}")
def product_backtest_get(job_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/research/backtests/{job_id}")


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


@router.post("/paper/pools", status_code=201)
def product_stock_pool_create(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("POST", "/v1/paper/pools", payload)


@router.get("/paper/pools/{pool_id}")
def product_stock_pool_get(pool_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/paper/pools/{pool_id}")


@router.post("/paper/orders", status_code=201)
def product_paper_order_create(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("POST", "/v1/paper/orders", payload)


@router.get("/paper/accounts/{account_id}/orders")
def product_paper_orders(account_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/paper/accounts/{account_id}/orders")
