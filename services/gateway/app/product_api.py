"""Phase 16 browser Product API/BFF.

This router is the only browser-facing product boundary. It never forwards
MCP tokens, provider credentials, DSH events, or raw Backend storage details.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .auth import AuthenticationUnavailable, Principal, authenticate_bearer
from .pooled_http import pooled_http as httpx
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
logger = logging.getLogger(__name__)


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
    if SESSION_COOKIE in request.cookies:
        user = resolve_user(request)
        principal = Principal(subject=str(user.get("username") or user.get("user_id")))
        workspace = user.get("_workspace")
        if not isinstance(workspace, dict) or not isinstance(workspace.get("workspace_id"), str):
            raise ProductError(401, "workspace_context_required", "personal workspace context required")
        workspace_id = workspace["workspace_id"]
    else:
        principal = _product_principal(request)
        # Product Token is bootstrap/internal compatibility only. Backend still
        # validates this deployment-provided value and fails closed.
        workspace_id = os.environ.get("BYQ_PRODUCT_WORKSPACE_ID", "workspace_bootstrap_unresolved")
    session_id = request.cookies.get(SESSION_COOKIE, "browser")
    return {
        "x-byq-workspace-id": workspace_id,
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
    headers = {"x-byq-actor-principal": actor, "x-byq-actor-role": role}
    if SESSION_COOKIE in request.cookies:
        headers.update(_trusted_agent_headers(request))
        headers["x-byq-actor-role"] = role
    return headers


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


def _public_workspace(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ProductError(502, "backend_invalid_response", "backend returned an invalid workspace")
    required = ("contract", "workspace_id", "kind", "display_name", "role")
    if any(not isinstance(value.get(field), str) for field in required):
        raise ProductError(502, "backend_invalid_response", "backend returned an invalid workspace")
    return {field: str(value[field]) for field in required}


def _session_workspace(request: Request) -> dict[str, str] | None:
    if SESSION_COOKIE not in request.cookies:
        return None
    return _public_workspace(resolve_user(request).get("_workspace"))


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
            detail = body.get("pool") if isinstance(body.get("pool"), dict) else summary
            if isinstance(detail, dict) and detail.get("pool_type") in {"index", "dynamic"}:
                producer_body = _backend_request("GET", f"/v1/paper/pools/{pool_id}/producer", headers=headers)
                producer = producer_body.get("producer")
                if isinstance(producer, dict):
                    detail = {**detail, "portable_producer": {
                        "producer_kind": producer.get("producer_kind"),
                        "definition": producer.get("definition"),
                    }}
            pools.append(detail)
        except ProductError:
            pools.append(summary)
    accounts = _owner_scoped_list("/v1/paper/accounts", "accounts", headers)
    return strategies, backtests, pools, accounts


def _clean_pool(pool: object) -> dict[str, object]:
    if not isinstance(pool, dict):
        raise ValueError("pool asset must be an object")
    result: dict[str, object] = {}
    for key in ("name", "pool_type", "description", "symbols", "weights", "provenance", "portable_producer"):
        if key in pool:
            result[key] = pool[key]
    return result


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _semantic_json_digest(value: object) -> str:
    """Hash JSON semantics without depending on a browser's number spelling.

    JSON.parse/stringify legitimately changes ``10.0`` to ``10``. Asset bundles
    cross that boundary, so their manifest must not depend on Python's lexical
    representation of an otherwise equal JSON number.
    """

    def project(item: object) -> object:
        if item is None:
            return ["null"]
        if isinstance(item, bool):
            return ["boolean", item]
        if isinstance(item, int):
            return ["number", str(item)]
        if isinstance(item, float):
            decimal = Decimal(str(item))
            if not decimal.is_finite():
                raise ValueError("asset bundle contains a non-finite number")
            normalized = decimal.normalize()
            rendered = "0" if normalized.is_zero() else format(normalized, "f")
            return ["number", rendered]
        if isinstance(item, str):
            return ["string", item]
        if isinstance(item, list):
            return ["array", [project(nested) for nested in item]]
        if isinstance(item, dict):
            return ["object", [
                [str(key), project(item[key])] for key in sorted(item, key=lambda key: str(key))
            ]]
        raise ValueError("asset bundle contains a non-JSON value")

    return _canonical_digest(project(value))


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
            logger.warning(
                "backend request rejected method=%s path=%s status=%s",
                "GET", path, status,
            )
            raise ProductError(503, "backend_unavailable", "backend is unavailable") from exc
        raise ProductError(status, "product_domain_rejected", message) from exc
    except httpx.HTTPError as exc:
        logger.warning(
            "backend request failed method=%s path=%s error_type=%s",
            "GET", path, type(exc).__name__,
        )
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
    params: dict[str, str] | None = None,
) -> dict[str, object]:
    try:
        response = httpx.request(
            method,
            f"{BACKEND_URL}{path}",
            json=payload,
            headers=headers,
            params=params,
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
            logger.warning(
                "backend request rejected method=%s path=%s status=%s",
                method, path, status,
            )
            raise ProductError(503, "backend_unavailable", "backend is unavailable") from exc
        raise ProductError(status, "product_domain_rejected", message) from exc
    except httpx.HTTPError as exc:
        logger.warning(
            "backend request failed method=%s path=%s error_type=%s",
            method, path, type(exc).__name__,
        )
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
    response = JSONResponse(content={
        "user": result.get("user", {}),
        "workspace": _public_workspace(result.get("workspace")),
    })
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
    user = resolve_user(request)
    return {
        "subject": str(user.get("username") or user.get("user_id")),
        "display_name": str(user.get("display_name") or ""),
        "role": str(user.get("role") or "user"),
        "workspace": _public_workspace(user.get("_workspace")),
    }


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


@router.post("/research/tasks", status_code=201)
def product_create_research_task(request: Request, payload: dict[str, object]) -> dict[str, object]:
    principal = _product_principal(request)
    if set(payload) != {"title", "objective"}:
        raise ProductError(422, "product_request_invalid", "research task request has invalid fields")
    nonce = uuid.uuid4().hex
    return _backend_request(
        "POST",
        "/v1/research/tasks",
        {
            "owner_principal": principal.subject,
            "title": payload.get("title"),
            "objective": payload.get("objective"),
            "trace_id": f"product-task-{nonce}",
            "idempotency_key": f"product-task-{nonce}",
        },
        headers=_trusted_agent_headers(request),
    )


@router.get("/research/experiments")
def product_research_experiments(request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", "/v1/research/experiments", headers=_trusted_agent_headers(request))


def _ml_nonce(prefix: str) -> tuple[str, str]:
    nonce = uuid.uuid4().hex
    return f"product-ml-{prefix}-{nonce}", f"product-ml-{prefix}-{nonce}"


def _ml_artifact_projection(artifact: object) -> dict[str, object] | None:
    if not isinstance(artifact, dict) or artifact.get("kind") not in {
        "ml_strategy_version", "ml_strategy_approval", "ml_model",
        "ml_prediction_snapshot", "signal_snapshot",
    }:
        return None
    content = artifact.get("content") if isinstance(artifact.get("content"), dict) else {}
    kind = str(artifact["kind"])
    allowed = {
        "ml_strategy_version": {"schema_version", "version_id", "name", "learner", "feature_set", "target", "split", "learner_parameters", "signal_policy", "runtime_lock"},
        "ml_strategy_approval": {"schema_version", "ml_strategy_version_id", "ml_strategy_artifact_id", "decision", "rationale", "execution_authorized", "execution_outcome"},
        "ml_model": {"schema_version", "training_run_id", "strategy_version_artifact_id", "feature_snapshot_artifact_id", "stock_pool_snapshot_id", "split", "feature_order", "best_iteration", "metrics", "counts", "runtime_lock", "runtime_identity", "content_sha256"},
        "ml_prediction_snapshot": {"schema_version", "model_artifact_id", "stock_pool_snapshot_id", "prediction_split", "runtime_lock", "runtime_identity", "rows", "counts", "content_sha256"},
        "signal_snapshot": {"schema_version", "strategy_version_id", "strategy_version_artifact_id", "universe", "signals", "execution", "source", "content_sha256"},
    }[kind]
    projected = {key: value for key, value in content.items() if key in allowed}
    if kind == "ml_prediction_snapshot" and isinstance(projected.get("rows"), list):
        projected["rows"] = projected["rows"][:200]
    if kind == "signal_snapshot":
        projected.pop("bars", None)
        if isinstance(projected.get("signals"), list):
            projected["signals"] = projected["signals"][:200]
    return {
        "artifact_id": artifact.get("artifact_id"), "task_id": artifact.get("task_id"),
        "kind": kind, "status": artifact.get("status"), "content_sha256": artifact.get("content_sha256"),
        "created_at": artifact.get("created_at"), "content": projected,
    }


@router.get("/ml/workspace")
def product_ml_workspace(request: Request) -> dict[str, object]:
    _product_principal(request)
    headers = _trusted_agent_headers(request)
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="ml-workspace") as executor:
        workspace_future = executor.submit(
            _backend_request, "GET", "/v1/research/ml/workspace", headers=headers,
        )
        backtests_future = executor.submit(
            _backend_request, "GET", "/v1/research/backtests?view=summary", headers=headers,
        )
        workspace = workspace_future.result()
        raw_backtests = backtests_future.result().get("backtests", [])
    tasks = workspace.get("tasks", [])
    pools = workspace.get("pools", [])
    artifacts = workspace.get("artifacts", [])
    training = workspace.get("training_runs", [])
    predictions = workspace.get("prediction_runs", [])
    backtests = [{key: item.get(key) for key in (
        "job_id", "task_id", "status", "strategy_version_artifact_id", "approval_artifact_id",
        "result_artifact_id", "summary", "error_code", "error_message", "created_at", "finished_at",
    )} for item in raw_backtests if isinstance(item, dict)]
    projected = [_ml_artifact_projection(item) for item in artifacts]
    return {
        "tasks": tasks, "pools": pools, "training_runs": training, "prediction_runs": predictions,
        "artifacts": [item for item in projected if item is not None], "backtests": backtests,
    }


def _ml_command(request: Request, path: str, payload: dict[str, object], fields: set[str], prefix: str) -> dict[str, object]:
    _product_principal(request)
    if set(payload) != fields:
        raise ProductError(422, "product_request_invalid", "ML research request has invalid fields")
    trace_id, idempotency_key = _ml_nonce(prefix)
    return _backend_request("POST", path, {**payload, "trace_id": trace_id, "idempotency_key": idempotency_key}, headers=_trusted_agent_headers(request))


@router.post("/ml/strategies/versions", status_code=201)
def product_ml_strategy(request: Request, payload: dict[str, object]) -> dict[str, object]:
    return _ml_command(request, "/v1/research/ml/strategies/versions", payload, {"task_id", "strategy"}, "strategy")


@router.post("/ml/strategies/approvals", status_code=201)
def product_ml_approval(request: Request, payload: dict[str, object]) -> dict[str, object]:
    return _ml_command(request, "/v1/research/ml/strategies/approvals", payload, {"task_id", "ml_strategy_artifact_id", "decision", "rationale"}, "approval")


@router.post("/ml/training-runs", status_code=202)
def product_ml_training(request: Request, payload: dict[str, object]) -> dict[str, object]:
    return _ml_command(request, "/v1/research/ml/training-runs", payload, {"task_id", "ml_strategy_artifact_id", "stock_pool_snapshot_id"}, "training")


@router.get("/ml/training-runs/{run_id}")
def product_ml_training_get(run_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/research/ml/training-runs/{run_id}", headers=_trusted_agent_headers(request))


@router.post("/ml/training-runs/{run_id}/cancel")
def product_ml_training_cancel(run_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("POST", f"/v1/research/ml/training-runs/{run_id}/cancel", headers=_trusted_agent_headers(request))


@router.post("/ml/prediction-runs", status_code=202)
def product_ml_prediction(request: Request, payload: dict[str, object]) -> dict[str, object]:
    return _ml_command(request, "/v1/research/ml/prediction-runs", payload, {"task_id", "model_artifact_id", "approval_artifact_id", "execution"}, "prediction")


@router.get("/ml/prediction-runs/{run_id}")
def product_ml_prediction_get(run_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/research/ml/prediction-runs/{run_id}", headers=_trusted_agent_headers(request))


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
        f"/v1/research/backtests/{job_id}?include_manifest=false",
        headers=_trusted_agent_headers(request),
    )


@router.get("/backtests/{job_id}/manifest")
def product_backtest_manifest(job_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET",
        f"/v1/research/backtests/{job_id}/manifest",
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
    return _backend_request("GET", "/v1/research/backtests?view=summary", headers=_trusted_agent_headers(request))


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


@router.get("/strategies/versions/{artifact_id}/approval")
def product_strategy_approval_get(artifact_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET",
        f"/v1/research/strategies/versions/{artifact_id}/approval",
        headers=_trusted_agent_headers(request),
    )


@router.get("/strategies")
def product_strategies(
    request: Request, lifecycle: str = "active", limit: int = 50, offset: int = 0
) -> dict[str, object]:
    _product_principal(request)
    if lifecycle not in {"active", "superseded", "all"}:
        raise ProductError(422, "product_strategy_view_invalid", "strategy lifecycle view is invalid")
    return _backend_request(
        "GET",
        f"/v1/research/strategies?lifecycle={lifecycle}&limit={limit}&offset={offset}",
        headers=_trusted_agent_headers(request),
    )


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


@router.post("/signal-producer/jobs", status_code=202)
def product_signal_producer_create(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST",
        "/v1/research/signal-producer/jobs",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.get("/signal-producer/jobs")
def product_signal_producer_list(request: Request, limit: int = 50, offset: int = 0) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET",
        f"/v1/research/signal-producer/jobs?limit={limit}&offset={offset}",
        headers=_trusted_agent_headers(request),
    )


@router.get("/signal-producer/jobs/{job_id}")
def product_signal_producer_get(job_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET",
        f"/v1/research/signal-producer/jobs/{job_id}",
        headers=_trusted_agent_headers(request),
    )


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


@router.post("/strategies/approvals", status_code=201)
def product_strategy_approval_create(request: Request, payload: dict[str, object]) -> dict[str, object]:
    principal = _product_principal(request)
    normalized = dict(payload)
    normalized["reviewer_principal"] = principal.subject
    return _backend_request(
        "POST",
        "/v1/research/strategies/approvals",
        normalized,
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


@router.get("/data-center/automation")
def product_market_sync_automation(request: Request) -> dict[str, object]:
    return _backend_request(
        "GET",
        "/v1/data-sync/automation",
        headers=_data_actor_headers(request, require_admin=True),
    )


@router.put("/data-center/automation/config")
def product_market_sync_automation_update(
    request: Request,
    payload: dict[str, object],
) -> dict[str, object]:
    return _backend_request(
        "PUT",
        "/v1/data-sync/automation/config",
        payload,
        headers=_data_actor_headers(request, require_admin=True),
    )


@router.post("/data-center/automation/run-now", status_code=202)
def product_market_sync_run_now(request: Request, payload: dict[str, object]) -> dict[str, object]:
    return _backend_request(
        "POST",
        "/v1/data-sync/automation/run-now",
        payload,
        headers=_data_actor_headers(request, require_admin=True),
    )


@router.get("/data-center/automation/run-now/{request_id}")
def product_market_sync_run_get(request_id: str, request: Request) -> dict[str, object]:
    return _backend_request(
        "GET",
        f"/v1/data-sync/automation/run-now/{request_id}",
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


@router.post("/data-center/readiness")
def product_data_readiness(request: Request, payload: dict[str, object]) -> dict[str, object]:
    return _backend_request(
        "POST",
        "/v1/data-center/readiness",
        payload,
        headers=_data_actor_headers(request),
    )


@router.post("/data-center/security-master/sync-jobs", status_code=201)
def product_security_master_sync_create(request: Request, payload: dict[str, object]) -> dict[str, object]:
    return _backend_request(
        "POST",
        "/v1/data-sync/security-master/jobs",
        payload,
        headers=_data_actor_headers(request, require_admin=True),
    )


@router.get("/data-center/security-master/sync-jobs/{job_id}")
def product_security_master_sync_get(job_id: str, request: Request) -> dict[str, object]:
    return _backend_request(
        "GET",
        f"/v1/data-sync/security-master/jobs/{job_id}",
        headers=_data_actor_headers(request, require_admin=True),
    )


@router.get("/data-center/securities")
def product_security_master_list(request: Request) -> dict[str, object]:
    params = {key: value for key, value in request.query_params.items()}
    return _backend_request(
        "GET",
        "/v1/data-center/securities",
        headers=_data_actor_headers(request),
        params=params,
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


@router.get("/settings/appearance")
def product_appearance_get(request: Request) -> dict[str, object]:
    user = resolve_user(request)
    user_id = user.get("user_id")
    if not isinstance(user_id, str):
        raise ProductError(502, "backend_invalid_response", "backend returned an invalid user")
    body = _backend_request(
        "GET",
        f"/v1/users/{user_id}/ui-preferences",
        headers={"x-byq-owner-user-id": user_id},
    )
    preferences = body.get("preferences")
    if not isinstance(preferences, dict):
        raise ProductError(502, "backend_invalid_response", "backend returned invalid UI preferences")
    return {"preferences": preferences}


@router.put("/settings/appearance")
def product_appearance_update(request: Request, payload: dict[str, object]) -> dict[str, object]:
    user = resolve_user(request)
    user_id = user.get("user_id")
    if not isinstance(user_id, str):
        raise ProductError(502, "backend_invalid_response", "backend returned an invalid user")
    body = _backend_request(
        "PUT",
        f"/v1/users/{user_id}/ui-preferences",
        payload,
        headers={"x-byq-owner-user-id": user_id},
    )
    preferences = body.get("preferences")
    if not isinstance(preferences, dict):
        raise ProductError(502, "backend_invalid_response", "backend returned invalid UI preferences")
    return {"preferences": preferences}


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
        "providers": catalog.get("providers", []),
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
    result: dict[str, object] = {
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
    workspace = _session_workspace(request)
    if workspace is not None:
        result["workspace"] = workspace
    return result


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
        "manifest_algorithm": "byq-semantic-json-v1",
        "exported_at": _now(),
        "owner_principal": principal.subject,
        "assets": assets,
    }
    workspace = _session_workspace(request)
    if workspace is not None:
        document["source_workspace"] = workspace
    return {**document, "manifest_sha256": _semantic_json_digest(document)}


@router.post("/settings/assets/import")
def product_assets_import(request: Request, payload: dict[str, object]) -> dict[str, object]:
    principal = _product_principal(request)
    if not isinstance(payload, dict) or payload.get("schema_version") != "byq-workspace-assets-v2":
        raise ProductError(422, "product_asset_bundle_invalid", "asset bundle is invalid")
    manifest_digest = payload.get("manifest_sha256")
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    algorithm = payload.get("manifest_algorithm")
    expected_digest = (
        _semantic_json_digest(unsigned)
        if algorithm == "byq-semantic-json-v1"
        else _canonical_digest(unsigned)
    )
    if not isinstance(manifest_digest, str) or manifest_digest != expected_digest:
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
            pool_type = clean_pool.get("pool_type", "custom")
            if pool_type in {"index", "dynamic"}:
                portable = clean_pool.get("portable_producer")
                if not isinstance(portable, dict) or portable.get("producer_kind") != pool_type:
                    raise ValueError("producer pool asset has no valid portable definition")
                _backend_request("POST", "/v1/paper/producer-imports", {
                    "name": clean_pool["name"], "description": clean_pool.get("description"),
                    "producer_kind": pool_type, "definition": portable.get("definition"),
                }, headers=headers)
            else:
                custom = {key: value for key, value in clean_pool.items() if key != "portable_producer"}
                _backend_request("POST", "/v1/paper/pools", custom, headers=headers)
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

    result: dict[str, object] = {
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
    workspace = _session_workspace(request)
    if workspace is not None:
        result["destination_workspace"] = workspace
    return result


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


@router.delete("/paper/accounts/{account_id}")
def product_paper_account_delete(
    account_id: str, request: Request, payload: dict[str, object],
) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "DELETE",
        f"/v1/paper/accounts/{account_id}",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.post("/paper/pools", status_code=201)
def product_stock_pool_create(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST",
        "/v1/paper/pools",
        payload,
        headers=_trusted_agent_headers(request),
    )


@router.get("/paper/index-pools/catalog")
def product_index_pool_catalog(request: Request, limit: int = 50, offset: int = 0) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET", f"/v1/paper/index-pools/catalog?limit={limit}&offset={offset}",
        headers=_trusted_agent_headers(request),
    )


@router.post("/paper/index-pools", status_code=202)
def product_index_pool_create(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST", "/v1/paper/index-pools", payload, headers=_trusted_agent_headers(request),
    )


@router.post("/paper/dynamic-pools/preview")
def product_dynamic_pool_preview(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST", "/v1/paper/dynamic-pools/preview", payload, headers=_trusted_agent_headers(request),
    )


@router.post("/paper/dynamic-pools", status_code=202)
def product_dynamic_pool_create(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST", "/v1/paper/dynamic-pools", payload, headers=_trusted_agent_headers(request),
    )


@router.get("/paper/pools/{pool_id}/producer")
def product_stock_pool_producer(pool_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET", f"/v1/paper/pools/{pool_id}/producer", headers=_trusted_agent_headers(request),
    )


@router.put("/paper/pools/{pool_id}/producer")
def product_stock_pool_producer_update(
    pool_id: str, request: Request, payload: dict[str, object],
) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "PUT", f"/v1/paper/pools/{pool_id}/producer", payload,
        headers=_trusted_agent_headers(request),
    )


@router.get("/paper/pools/{pool_id}/materializations")
def product_stock_pool_materializations(
    pool_id: str, request: Request, limit: int = 50, offset: int = 0,
) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET", f"/v1/paper/pools/{pool_id}/materializations?limit={limit}&offset={offset}",
        headers=_trusted_agent_headers(request),
    )


@router.post("/paper/pools/{pool_id}/materializations", status_code=202)
def product_stock_pool_materialization_create(
    pool_id: str, request: Request, payload: dict[str, object],
) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "POST", f"/v1/paper/pools/{pool_id}/materializations", payload,
        headers=_trusted_agent_headers(request),
    )


@router.get("/paper/pools/{pool_id}")
def product_stock_pool_get(pool_id: str, request: Request, include_members: bool = True) -> dict[str, object]:
    _product_principal(request)
    return _backend_request(
        "GET",
        f"/v1/paper/pools/{pool_id}?include_members={'true' if include_members else 'false'}",
        headers=_trusted_agent_headers(request),
    )


@router.get("/paper/pools/{pool_id}/members")
def product_stock_pool_members(
    pool_id: str, request: Request, query: str = "", limit: int = 20, offset: int = 0,
) -> dict[str, object]:
    _product_principal(request)
    params = urlencode({"query": query, "limit": limit, "offset": offset})
    return _backend_request(
        "GET", f"/v1/paper/pools/{pool_id}/members?{params}", headers=_trusted_agent_headers(request),
    )


@router.get("/paper/pools")
def product_stock_pools(request: Request, limit: int = 50, offset: int = 0) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/paper/pools?limit={limit}&offset={offset}", headers=_trusted_agent_headers(request))


@router.get("/paper/pools/{pool_id}/readiness")
def product_stock_pool_readiness(pool_id: str, request: Request) -> dict[str, object]:
    _product_principal(request)
    return _backend_request("GET", f"/v1/paper/pools/{pool_id}/readiness", headers=_trusted_agent_headers(request))


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


@router.get("/paper/pools/{pool_id}/snapshot-diff")
def product_stock_pool_snapshot_diff(
    pool_id: str, request: Request, from_snapshot_id: str, to_snapshot_id: str,
) -> dict[str, object]:
    _product_principal(request)
    query = urlencode({"from_snapshot_id": from_snapshot_id, "to_snapshot_id": to_snapshot_id})
    return _backend_request(
        "GET", f"/v1/paper/pools/{pool_id}/snapshot-diff?{query}", headers=_trusted_agent_headers(request),
    )


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


def _plugin_admin(request: Request) -> tuple[str, dict[str, str]]:
    user = resolve_user(request)
    if user.get("role") != "admin":
        raise ProductError(403, "product_forbidden", "admin role required")
    actor = str(user.get("username") or user.get("user_id") or "admin")
    return actor, {"x-byq-actor-role": "admin", "x-byq-actor-principal": actor}


def _decorate_plugin_center(body: dict[str, object], runtime: dict[str, object]) -> dict[str, object]:
    runtime_state = runtime.get("runtime") if isinstance(runtime.get("runtime"), dict) else {}
    assert isinstance(runtime_state, dict)
    active_ids = runtime_state.get("enabled_plugin_ids")
    active_ids = active_ids if isinstance(active_ids, list) else []
    active_hash = runtime_state.get("composition_hash")
    active_profile = runtime_state.get("plugin_profile")
    runtime_ready = runtime_state.get("status") == "ready"
    plugins = body.get("plugins")
    if isinstance(plugins, list):
        for plugin in plugins:
            if not isinstance(plugin, dict):
                continue
            plugin["active"] = runtime_ready and plugin.get("id") in active_ids
            if plugin.get("credential_required") is True:
                plugin["credential_configured"] = runtime_state.get("model_credentials") == "configured"
    policy = body.get("policy") if isinstance(body.get("policy"), dict) else {}
    desired_ids = policy.get("enabled_plugin_ids") if isinstance(policy, dict) else []
    requests = body.get("requests") if isinstance(body.get("requests"), list) else []
    policy_requests = [item for item in requests if isinstance(item, dict) and item.get("request_kind") != "qualify"]
    deployment_pending = any(
        isinstance(item, dict)
        and item.get("request_kind") != "qualify"
        and item.get("deployment_state") not in {"active", "rolled_back", "not_applicable"}
        for item in requests
    )
    latest_policy_request = policy_requests[0] if policy_requests else None
    deployed_identity_matches = (
        latest_policy_request is None
        or (
            latest_policy_request.get("deployment_state") == "active"
            and latest_policy_request.get("target_composition_hash") == active_hash
        )
    )
    body["runtime"] = {
        "status": runtime_state.get("status", "unavailable"),
        "sdk": runtime_state.get("sdk"),
        "runtime_bin": runtime_state.get("runtime_bin"),
        "active_profile": active_profile,
        "active_composition_hash": active_hash,
        "active_plugin_ids": active_ids,
        "desired_matches_active_plugins": (
            runtime_ready and not deployment_pending and deployed_identity_matches
            and sorted(active_ids) == sorted(desired_ids or [])
        ),
    }
    body["projection_status"] = "ready" if runtime_ready else "partial"
    return body


@router.get("/plugins")
def product_plugin_center(request: Request) -> dict[str, object]:
    _actor, headers = _plugin_admin(request)
    body = _backend_request("GET", "/v1/plugin-center", headers=headers)
    return _decorate_plugin_center(body, _runtime_operations())


@router.get("/plugins/{plugin_id}")
def product_plugin_detail(plugin_id: str, request: Request) -> dict[str, object]:
    _actor, headers = _plugin_admin(request)
    detail = _backend_request("GET", f"/v1/plugin-center/plugins/{plugin_id}", headers=headers)
    projection = {"plugins": [detail.get("plugin")], "policy": {}, **detail}
    return _decorate_plugin_center(projection, _runtime_operations())


@router.post("/plugins/changes", status_code=202)
def product_plugin_change(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _actor, headers = _plugin_admin(request)
    return _backend_request("POST", "/v1/plugin-center/changes", payload, headers=headers)


@router.post("/plugins/qualifications", status_code=202)
def product_plugin_qualification(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _actor, headers = _plugin_admin(request)
    return _backend_request("POST", "/v1/plugin-center/qualifications", payload, headers=headers)
