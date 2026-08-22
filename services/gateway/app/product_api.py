"""Phase 16 browser Product API/BFF.

This router is the only browser-facing product boundary. It never forwards
MCP tokens, provider credentials, DSH events, or raw Backend storage details.
"""

from __future__ import annotations

import hashlib
import json
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
RUNTIME_ADAPTER_URL = os.environ.get("BYQ_RUNTIME_ADAPTER_URL", "http://runtime-adapter:8400")
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


def _data_actor_headers(request: Request, *, require_admin: bool = False) -> dict[str, str]:
    if SESSION_COOKIE in request.cookies:
        user = resolve_user(request)
        actor = str(user.get("username") or user.get("user_id") or "")
        role = str(user.get("role") or "user")
    else:
        principal = _product_principal(request)
        actor = principal.subject
        role = "user"
    if require_admin and role != "admin":
        raise ProductError(403, "product_forbidden", "admin role required")
    return {"x-byq-actor-principal": actor, "x-byq-actor-role": role}


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
    backtests.extend(
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict) and artifact.get("kind") == "backtest_archive"
    )
    pool_summaries = _owner_scoped_list("/v1/paper/pools", "pools", headers)
    pools: list[object] = []
    for summary in pool_summaries:
        pool_id = summary.get("pool_id") if isinstance(summary, dict) else None
        if not isinstance(pool_id, str):
            pools.append(summary)
            continue
        try:
            body = _backend_request("GET", f"/v1/paper/pools/{pool_id}", headers=headers)
            pools.append(body.get("pool") if isinstance(body.get("pool"), dict) else summary)
        except ProductError:
            pools.append(summary)
    accounts = _owner_scoped_list("/v1/paper/accounts", "accounts", headers)
    return strategies, backtests, pools, accounts


def _clean_pool(pool: object) -> dict[str, object]:
    if not isinstance(pool, dict):
        raise ValueError("pool asset must be an object")
    result: dict[str, object] = {}
    for key in ("name", "pool_type", "description", "symbols", "weights", "provenance"):
        if key in pool:
            result[key] = pool[key]
    return result


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _portable_strategy(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or value.get("kind") != "strategy_version":
        return None
    content = value.get("content")
    if not isinstance(content, dict) or not isinstance(content.get("export"), dict):
        return None
    portable = {
        "kind": "strategy_version",
        "export": content["export"],
        "source_content_sha256": value.get("content_sha256"),
    }
    return {**portable, "digest_sha256": _canonical_digest(portable)}


def _portable_backtest(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    if value.get("kind") == "backtest_archive":
        content = value.get("content")
        if isinstance(content, dict):
            archive = content.get("archive")
            if isinstance(archive, dict):
                return archive
        return None
    portable = {
        "kind": "backtest_archive",
        "status": value.get("status"),
        "input_manifest": value.get("input_manifest"),
        "summary": value.get("summary"),
        "source": {
            "job_id": value.get("job_id"),
            "strategy_version_artifact_id": value.get("strategy_version_artifact_id"),
            "created_at": value.get("created_at"),
            "finished_at": value.get("finished_at"),
        },
    }
    return {**portable, "digest_sha256": _canonical_digest(portable)}


def _validated_portable(value: object, kind: str) -> dict[str, object]:
    if not isinstance(value, dict) or value.get("kind") != kind:
        raise ValueError(f"{kind} asset is invalid")
    digest = value.get("digest_sha256")
    unsigned = {key: nested for key, nested in value.items() if key != "digest_sha256"}
    if not isinstance(digest, str) or digest != _canonical_digest(unsigned):
        raise ValueError(f"{kind} asset digest does not match")
    return value


def _backend_get(path: str) -> dict[str, object]:
    try:
        response = httpx.get(f"{BACKEND_URL}{path}", timeout=3.0)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        try:
            error_body = exc.response.json()
        except ValueError:
            error_body = {}
        detail = error_body.get("detail") if isinstance(error_body, dict) else None
        message = detail if isinstance(detail, str) else "backend rejected the request"
        if status not in {400, 401, 403, 404, 409, 422}:
            raise ProductError(503, "backend_unavailable", "backend is unavailable") from exc
        raise ProductError(status, "product_domain_rejected", message) from exc
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
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        try:
            error_body = exc.response.json()
        except ValueError:
            error_body = {}
        detail = error_body.get("detail") if isinstance(error_body, dict) else None
        message = detail if isinstance(detail, str) else "backend rejected the request"
        if status not in {400, 401, 403, 404, 409, 422}:
            raise ProductError(503, "backend_unavailable", "backend is unavailable") from exc
        raise ProductError(status, "product_domain_rejected", message) from exc
    except httpx.HTTPError as exc:
        raise ProductError(503, "backend_unavailable", "backend is unavailable") from exc
    body = response.json()
    if not isinstance(body, dict):
        raise ProductError(502, "backend_invalid_response", "backend returned an invalid response")
    return body


def _runtime_operations() -> dict[str, object]:
    try:
        response = httpx.get(f"{RUNTIME_ADAPTER_URL}/internal/runtime/operations", timeout=3.0)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return {
            "schema_version": "runtime-operations.v1",
            "runtime": {"status": "unavailable"},
            "sessions": {"active": 0, "active_prompts": 0, "status_counts": {}},
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "reasoning_tokens": 0,
                "model_calls": 0,
                "total_tokens": 0,
                "scope": "adapter_process_lifetime",
                "source": "unavailable",
            },
            "raw_dsh_events": False,
        }
    if not isinstance(body, dict):
        raise ProductError(502, "runtime_invalid_response", "runtime adapter returned an invalid response")
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
    return _backend_request(
        "GET",
        f"/v1/research/{entity_type}/{entity_id}",
        headers=_trusted_agent_headers(request),
    )


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


@router.get("/backtests/options")
def product_backtest_options(request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET", "/v1/research/backtests/options", headers=_trusted_agent_headers(request)
    )


@router.post("/backtests", status_code=202)
def product_backtest_submit(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST", "/v1/research/backtests", payload, headers=_trusted_agent_headers(request)
    )


@router.get("/backtests/{job_id}")
def product_backtest_get(job_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET",
        f"/v1/research/backtests/{job_id}",
        headers=_trusted_agent_headers(request),
    )


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
    return _backend_request(
        "POST",
        f"/v1/research/backtests/{job_id}/run",
        headers=_trusted_agent_headers(request),
    )


@router.post("/backtests/{job_id}/cancel")
def product_backtest_cancel(job_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST",
        f"/v1/research/backtests/{job_id}/cancel",
        headers=_trusted_agent_headers(request),
    )

@router.delete("/backtests/{job_id}")
def product_backtest_delete(job_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "DELETE",
        f"/v1/research/backtests/{job_id}",
        headers=_trusted_agent_headers(request),
    )


@router.get("/strategies/versions/{artifact_id}/export")
def product_strategy_export(artifact_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET",
        f"/v1/research/strategies/versions/{artifact_id}/export",
        headers=_trusted_agent_headers(request),
    )


@router.get("/strategies")
def product_strategies(request: Request) -> dict[str, object]:
    _product_principal(request)
    body = _backend_request("GET", "/v1/research/artifacts", headers=_trusted_agent_headers(request))
    artifacts = body.get("artifacts", [])
    if isinstance(artifacts, list):
        return {"strategies": [a for a in artifacts if isinstance(a, dict) and a.get("kind") in {"strategy_version", "strategy_draft"}]}
    return {"strategies": []}


@router.get("/signal-snapshots")
def product_signal_snapshots(request: Request) -> dict[str, object]:
    _product_principal(request)
    body = _backend_request("GET", "/v1/research/artifacts", headers=_trusted_agent_headers(request))
    artifacts = body.get("artifacts", [])
    if isinstance(artifacts, list):
        return {
            "snapshots": [
                a for a in artifacts if isinstance(a, dict) and a.get("kind") == "signal_snapshot"
            ]
        }
    return {"snapshots": []}


@router.post("/strategies/drafts", status_code=201)
def product_strategy_draft_save(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST",
        "/v1/research/strategies/drafts",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.delete("/strategies/drafts/{artifact_id}")
def product_strategy_draft_delete(artifact_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "DELETE",
        f"/v1/research/strategies/drafts/{artifact_id}",
        headers=_trusted_agent_headers(request),
    )


@router.get("/strategies/{strategy_id}/versions")
def product_strategy_versions(strategy_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET",
        f"/v1/research/strategies/{strategy_id}/versions",
        headers=_trusted_agent_headers(request),
    )


@router.get("/strategies/{strategy_id}/backtest-count")
def product_strategy_backtest_count(strategy_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET",
        f"/v1/research/strategies/{strategy_id}/backtest-count",
        headers=_trusted_agent_headers(request),
    )


@router.post("/strategies/validate", status_code=201)
def product_strategy_validate(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST",
        "/v1/research/strategies/validate",
        payload,
        headers=_trusted_agent_headers(request),
    )


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
    return _backend_request(
        "GET",
        "/v1/data-center/status",
        headers=_data_actor_headers(request),
    )


@router.post("/data-center/source/credentials", status_code=201)
def product_tushare_credential_create(request: Request, payload: dict[str, object]) -> dict[str, object]:
    return _backend_request(
        "POST",
        "/v1/data-sources/tushare/credentials",
        payload,
        headers=_data_actor_headers(request, require_admin=True),
    )


@router.put("/data-center/source/credentials/{credential_id}")
def product_tushare_credential_update(
    credential_id: str,
    request: Request,
    payload: dict[str, object],
) -> dict[str, object]:
    return _backend_request(
        "PUT",
        f"/v1/data-sources/tushare/credentials/{credential_id}",
        payload,
        headers=_data_actor_headers(request, require_admin=True),
    )


@router.post("/data-center/source/credentials/{credential_id}/revoke")
def product_tushare_credential_revoke(
    credential_id: str,
    request: Request,
    payload: dict[str, object],
) -> dict[str, object]:
    return _backend_request(
        "POST",
        f"/v1/data-sources/tushare/credentials/{credential_id}/revoke",
        payload,
        headers=_data_actor_headers(request, require_admin=True),
    )


@router.post("/data-center/source/test")
def product_tushare_connection_test(request: Request, payload: dict[str, object]) -> dict[str, object]:
    return _backend_request(
        "POST",
        "/v1/data-sources/tushare/test",
        payload,
        headers=_data_actor_headers(request, require_admin=True),
    )


@router.post("/data-center/sync-jobs", status_code=201)
def product_data_sync_create(request: Request, payload: dict[str, object]) -> dict[str, object]:
    return _backend_request(
        "POST",
        "/v1/data-sync/jobs",
        payload,
        headers=_data_actor_headers(request, require_admin=True),
    )


@router.get("/data-center/sync-jobs/{job_id}")
def product_data_sync_get(job_id: str, request: Request) -> dict[str, object]:
    return _backend_request(
        "GET",
        f"/v1/data-sync/jobs/{job_id}",
        headers=_data_actor_headers(request, require_admin=True),
    )


@router.get("/data-center/coverage")
def product_data_coverage(request: Request) -> dict[str, object]:
    return _backend_request(
        "GET",
        "/v1/data-center/coverage",
        headers=_data_actor_headers(request),
    )


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
    headers = _trusted_agent_headers(request)
    catalog = _backend_request("GET", "/v1/users/model-catalog", headers=headers)
    credential_body = _backend_request("GET", "/v1/users/model-credentials", headers=headers)
    profile_body = _backend_request("GET", "/v1/users/model-profiles", headers=headers)
    binding_body = _backend_request("GET", "/v1/users/model-bindings", headers=headers)
    audit_body = _backend_request("GET", "/v1/users/model-credential-audit?limit=50", headers=headers)
    credentials = credential_body.get("credentials", [])
    return {
        "provider": "deepseek",
        "configured": any(
            isinstance(item, dict) and item.get("status") == "active"
            for item in credentials if isinstance(credentials, list)
        ),
        "models": catalog.get("models", []),
        "agents": catalog.get("agents", []),
        "credential_items": credentials,
        "profiles": profile_body.get("profiles", []),
        "bindings": binding_body.get("bindings", []),
        "audit": audit_body.get("events", []),
        "encryption": credential_body.get("encryption", {}),
        "credentials": {"masked": True, "write_only": True},
    }


@router.post("/settings/models/credentials", status_code=201)
def product_model_credential_create(
    request: Request,
    payload: dict[str, object],
) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST",
        "/v1/users/model-credentials",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.put("/settings/models/credentials/{credential_id}")
def product_model_credential_update(
    credential_id: str,
    request: Request,
    payload: dict[str, object],
) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "PUT",
        f"/v1/users/model-credentials/{credential_id}",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.post("/settings/models/credentials/{credential_id}/revoke")
def product_model_credential_revoke(
    credential_id: str,
    request: Request,
    payload: dict[str, object],
) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST",
        f"/v1/users/model-credentials/{credential_id}/revoke",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.post("/settings/models/profiles", status_code=201)
def product_model_profile_create(
    request: Request,
    payload: dict[str, object],
) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST",
        "/v1/users/model-profiles",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.post("/settings/models/profiles/{profile_id}/delete")
def product_model_profile_delete(
    profile_id: str,
    request: Request,
    payload: dict[str, object],
) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST",
        f"/v1/users/model-profiles/{profile_id}/delete",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.put("/settings/models/bindings/{agent_id}")
def product_model_binding_update(
    agent_id: str,
    request: Request,
    payload: dict[str, object],
) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "PUT",
        f"/v1/users/model-bindings/{agent_id}",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.get("/settings/agent-policy")
def product_agent_policy(request: Request) -> dict[str, object]:
    _product_principal(request)
    approvals = _owner_scoped_list("/v1/agents/approvals", "approvals", _trusted_agent_headers(request))
    pending = sum(1 for approval in approvals if isinstance(approval, dict) and approval.get("status") == "pending")
    policy_body = _backend_request(
        "GET",
        "/v1/users/agent-policy",
        headers=_trusted_agent_headers(request),
    )
    personal = policy_body.get("policy", {})
    return {
        "platform_policy": {
            "automation_enabled": False,
            "paused": False,
            "default_decision_mode": "manual",
            "max_auto_executions_per_hour": 20,
            "max_auto_failures_per_hour": 3,
        },
        "personal_policy": personal,
        "rules": policy_body.get("rules", []),
        "presets": policy_body.get("presets", []),
        "audit": policy_body.get("audit", []),
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


@router.post("/settings/agent-policy/rules", status_code=201)
def product_agent_policy_rule_create(
    request: Request,
    payload: dict[str, object],
) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST",
        "/v1/users/agent-policy/rules",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.put("/settings/agent-policy/rules/{rule_id}")
def product_agent_policy_rule_update(
    rule_id: str,
    request: Request,
    payload: dict[str, object],
) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "PUT",
        f"/v1/users/agent-policy/rules/{rule_id}",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.post("/settings/agent-policy/rules/{rule_id}/delete")
def product_agent_policy_rule_delete(
    rule_id: str,
    request: Request,
    payload: dict[str, object],
) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST",
        f"/v1/users/agent-policy/rules/{rule_id}/delete",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.post("/settings/agent-policy/presets/{preset_id}/apply")
def product_agent_policy_preset_apply(preset_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST",
        f"/v1/users/agent-policy/presets/{preset_id}/apply",
        {},
        headers=_trusted_agent_headers(request),
    )


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
    headers = _trusted_agent_headers(request)
    strategies, backtests, pools, accounts = _asset_lists(request)
    portable_strategies = [item for value in strategies if (item := _portable_strategy(value))]
    portable_backtests = [item for value in backtests if (item := _portable_backtest(value))]
    portable_accounts: list[object] = []
    for account in accounts:
        account_id = account.get("account_id") if isinstance(account, dict) else None
        if not isinstance(account_id, str):
            continue
        body = _backend_request("GET", f"/v1/paper/accounts/{account_id}/export", headers=headers)
        bundle = body.get("bundle")
        if isinstance(bundle, dict):
            portable_accounts.append(bundle)
    assets = {
        "strategies": portable_strategies,
        "backtests": portable_backtests,
        "pools": [_clean_pool(value) for value in pools],
        "paper_accounts": portable_accounts,
    }
    document = {
        "schema_version": "byq-workspace-assets-v2",
        "exported_at": _now(),
        "owner_principal": principal.subject,
        "assets": assets,
    }
    return {**document, "manifest_sha256": _canonical_digest(document)}


@router.post("/settings/assets/import")
def product_assets_import(request: Request, payload: dict[str, object]) -> dict[str, object]:
    principal = _product_principal(request)
    if not isinstance(payload, dict) or payload.get("schema_version") != "byq-workspace-assets-v2":
        raise ProductError(422, "product_asset_bundle_invalid", "asset bundle is invalid")
    manifest_digest = payload.get("manifest_sha256")
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    if not isinstance(manifest_digest, str) or manifest_digest != _canonical_digest(unsigned):
        raise ProductError(422, "product_asset_bundle_invalid", "asset bundle manifest digest does not match")
    assets = payload.get("assets")
    if not isinstance(assets, dict):
        raise ProductError(422, "product_asset_bundle_invalid", "asset bundle is invalid")
    _reject_secret_fields(assets)

    headers = _trusted_agent_headers(request)
    imported_pools = 0
    imported_accounts = 0
    imported_strategies = 0
    imported_backtests = 0
    errors: list[dict[str, str]] = []
    import_nonce = uuid.uuid4().hex[:16]

    strategies = assets.get("strategies", [])
    backtests = assets.get("backtests", [])
    if not isinstance(strategies, list):
        strategies = []
    if not isinstance(backtests, list):
        backtests = []

    if strategies or backtests:
        task = _backend_request(
            "POST",
            "/v1/research/tasks",
            {
                "owner_principal": principal.subject,
                "title": "Imported workspace assets",
                "objective": "Validated re-import from a portable BYQ workspace bundle",
                "trace_id": f"product-import-{import_nonce}",
                "idempotency_key": f"workspace-import-{import_nonce}",
            },
            headers=headers,
        )
        task_id = task.get("task_id")
        if not isinstance(task_id, str):
            raise ProductError(502, "backend_invalid_response", "backend returned an invalid import task")

        for index, value in enumerate(strategies):
            try:
                portable = _validated_portable(value, "strategy_version")
                exported = portable.get("export")
                if not isinstance(exported, dict) or not isinstance(exported.get("snapshot"), dict):
                    raise ValueError("strategy_version export is invalid")
                draft = _backend_request(
                    "POST",
                    "/v1/research/strategies/validate",
                    {
                        "task_id": task_id,
                        "experiment_id": None,
                        "strategy": exported["snapshot"],
                        "trace_id": f"product-import-{import_nonce}",
                        "idempotency_key": f"import-strategy-draft-{import_nonce}-{index}",
                    },
                    headers=headers,
                )
                artifact = draft.get("artifact")
                draft_id = artifact.get("artifact_id") if isinstance(artifact, dict) else None
                if not isinstance(draft_id, str):
                    raise ValueError("strategy validation returned no draft artifact")
                rebuilt = _backend_request(
                    "POST",
                    "/v1/research/strategies/versions",
                    {
                        "task_id": task_id,
                        "experiment_id": None,
                        "draft_artifact_id": draft_id,
                        "trace_id": f"product-import-{import_nonce}",
                        "idempotency_key": f"import-strategy-version-{import_nonce}-{index}",
                    },
                    headers=headers,
                )
                rebuilt_version = rebuilt.get("strategy_version")
                if (
                    not isinstance(rebuilt_version, dict)
                    or rebuilt_version.get("version_id") != exported.get("version_id")
                ):
                    raise ValueError("rebuilt strategy identity does not match the portable export")
                imported_strategies += 1
            except (ProductError, ValueError) as exc:
                errors.append({"kind": "strategy_version", "message": str(exc)})

        for index, value in enumerate(backtests):
            try:
                portable = _validated_portable(value, "backtest_archive")
                _backend_request(
                    "POST",
                    "/v1/research/artifacts",
                    {
                        "task_id": task_id,
                        "experiment_id": None,
                        "kind": "backtest_archive",
                        "content": {
                            "schema_version": "byq-backtest-archive-v1",
                            "archive": portable,
                            "imported_at": _now(),
                        },
                        "lineage": [],
                        "trace_id": f"product-import-{import_nonce}",
                        "idempotency_key": f"import-backtest-{import_nonce}-{index}",
                    },
                    headers=headers,
                )
                imported_backtests += 1
            except (ProductError, ValueError) as exc:
                errors.append({"kind": "backtest_archive", "message": str(exc)})

    pools = assets.get("pools", [])
    if not isinstance(pools, list):
        pools = []
    for index, pool in enumerate(pools):
        try:
            clean_pool = _clean_pool(pool)
            source_name = clean_pool.get("name")
            if not isinstance(source_name, str) or not source_name.strip():
                raise ValueError("pool asset has no name")
            suffix = f" · 导入-{import_nonce[:6]}-{index + 1}"
            clean_pool["name"] = f"{source_name[:128 - len(suffix)]}{suffix}"
            _backend_request("POST", "/v1/paper/pools", clean_pool, headers=headers)
            imported_pools += 1
        except (ProductError, ValueError) as exc:
            errors.append({"kind": "pool", "message": str(exc)})

    accounts = assets.get("paper_accounts", [])
    if not isinstance(accounts, list):
        accounts = []
    for account in accounts:
        try:
            if not isinstance(account, dict):
                raise ValueError("paper account bundle must be an object")
            _backend_request("POST", "/v1/paper/accounts/import", {"bundle": account}, headers=headers)
            imported_accounts += 1
        except (ProductError, ValueError) as exc:
            errors.append({"kind": "paper_account", "message": str(exc)})

    return {
        "imported": {
            "strategies": imported_strategies,
            "backtests": imported_backtests,
            "pools": imported_pools,
            "paper_accounts": imported_accounts,
        },
        "source_owner_reused": False,
        "identity_policy": "new-owner-scoped-identities",
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
    return _backend_request(
        "GET",
        f"/v1/paper/accounts/{account_id}",
        headers=_trusted_agent_headers(request),
    )


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
    return _backend_request(
        "GET",
        f"/v1/paper/pools/{pool_id}",
        headers=_trusted_agent_headers(request),
    )


@router.get("/paper/pools")
def product_stock_pools(request: Request, limit: int = 50, offset: int = 0) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/paper/pools?limit={limit}&offset={offset}", headers=_trusted_agent_headers(request))


@router.patch("/paper/pools/{pool_id}/metadata")
def product_stock_pool_metadata(pool_id: str, request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("PATCH", f"/v1/paper/pools/{pool_id}/metadata", payload, headers=_trusted_agent_headers(request))


@router.put("/paper/pools/{pool_id}/snapshot")
def product_stock_pool_snapshot_replace(pool_id: str, request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("PUT", f"/v1/paper/pools/{pool_id}/snapshot", payload, headers=_trusted_agent_headers(request))


@router.get("/paper/pools/{pool_id}/snapshots")
def product_stock_pool_snapshots(pool_id: str, request: Request, limit: int = 50, offset: int = 0) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/paper/pools/{pool_id}/snapshots?limit={limit}&offset={offset}", headers=_trusted_agent_headers(request))


@router.get("/paper/pools/{pool_id}/snapshots/{snapshot_id}")
def product_stock_pool_snapshot_get(pool_id: str, snapshot_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/paper/pools/{pool_id}/snapshots/{snapshot_id}", headers=_trusted_agent_headers(request))


@router.get("/paper/pools/{pool_id}/as-of/{trade_date}")
def product_stock_pool_as_of(pool_id: str, trade_date: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/paper/pools/{pool_id}/as-of/{trade_date}", headers=_trusted_agent_headers(request))


@router.patch("/paper/pools/{pool_id}/lifecycle")
def product_stock_pool_lifecycle(pool_id: str, request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("PATCH", f"/v1/paper/pools/{pool_id}/lifecycle", payload, headers=_trusted_agent_headers(request))


@router.delete("/paper/pools/{pool_id}")
def product_stock_pool_delete(pool_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    headers = _trusted_agent_headers(request)
    headers["x-idempotency-key"] = request.headers.get("x-idempotency-key") or f"delete-{pool_id}"
    return _backend_request("DELETE", f"/v1/paper/pools/{pool_id}", headers=headers)


@router.get("/paper/pools/{pool_id}/references")
def product_stock_pool_references(pool_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/paper/pools/{pool_id}/references", headers=_trusted_agent_headers(request))


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


@router.get("/paper/accounts/{account_id}/orders/{order_id}")
def product_paper_order_get(account_id: str, order_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET", f"/v1/paper/accounts/{account_id}/orders/{order_id}",
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


@router.get("/paper/accounts/{account_id}/snapshots")
def product_paper_snapshots(account_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/paper/accounts/{account_id}/snapshots", headers=_trusted_agent_headers(request))


@router.post("/paper/accounts/{account_id}/settlements", status_code=201)
def product_paper_settlement(account_id: str, request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("POST", f"/v1/paper/accounts/{account_id}/settlements", payload, headers=_trusted_agent_headers(request))


@router.get("/paper/accounts/{account_id}/controls")
def product_paper_controls(account_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/paper/accounts/{account_id}/controls", headers=_trusted_agent_headers(request))


@router.put("/paper/accounts/{account_id}/controls")
def product_paper_controls_update(account_id: str, request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("PUT", f"/v1/paper/accounts/{account_id}/controls", payload, headers=_trusted_agent_headers(request))


@router.put("/paper/accounts/{account_id}/binding")
def product_paper_binding_update(account_id: str, request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("PUT", f"/v1/paper/accounts/{account_id}/binding", payload, headers=_trusted_agent_headers(request))


@router.get("/paper/accounts/{account_id}/export")
def product_paper_export(account_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/paper/accounts/{account_id}/export", headers=_trusted_agent_headers(request))


@router.post("/paper/accounts/import", status_code=201)
def product_paper_import(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("POST", "/v1/paper/accounts/import", payload, headers=_trusted_agent_headers(request))


@router.get("/operations/status")
def product_operations_status(request: Request) -> dict[str, object]:
    user = resolve_user(request)
    if user.get("role") != "admin":
        raise ProductError(403, "product_forbidden", "admin role required")
    actor = str(user.get("username") or user.get("user_id") or "admin")
    backend = _backend_request(
        "GET",
        "/v1/operations/overview",
        headers={"x-byq-actor-role": "admin", "x-byq-actor-principal": actor},
    )
    runtime = _runtime_operations()
    return {
        "schema_version": "operations.v1",
        "services": {
            "gateway": "ready",
            "backend": str((backend.get("database") or {}).get("status", "unknown"))
                if isinstance(backend.get("database"), dict) else "unknown",
            "runtime_adapter": str((runtime.get("runtime") or {}).get("status", "unknown"))
                if isinstance(runtime.get("runtime"), dict) else "unknown",
        },
        **backend,
        "runtime": runtime,
        "observability": {
            "workflow_trace": "normalized",
            "audit": "append_only",
            "raw_dsh_events": False,
        },
    }


@router.put("/operations/budget")
def product_operations_budget_update(
    request: Request,
    payload: dict[str, object],
) -> dict[str, object]:
    user = resolve_user(request)
    if user.get("role") != "admin":
        raise ProductError(403, "product_forbidden", "admin role required")
    actor = str(user.get("username") or user.get("user_id") or "admin")
    return _backend_request(
        "PUT",
        "/v1/operations/budget",
        payload,
        headers={"x-byq-actor-role": "admin", "x-byq-actor-principal": actor},
    )
