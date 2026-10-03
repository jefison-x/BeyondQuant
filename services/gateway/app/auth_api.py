"""Browser authentication endpoints under /api/auth."""

from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .user_session import (
    SESSION_COOKIE,
    ProductAuthError,
    change_password as change_user_password,
    login as login_user,
    logout as logout_user,
    resolve_user,
)


router = APIRouter(prefix="/api/auth")


class AuthApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _public_workspace(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ProductAuthError(502, "backend_invalid_response", "backend returned an invalid workspace")
    required = ("contract", "workspace_id", "kind", "display_name", "role")
    if any(not isinstance(value.get(field), str) for field in required):
        raise ProductAuthError(502, "backend_invalid_response", "backend returned an invalid workspace")
    return {field: str(value[field]) for field in required}


def _auth_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": uuid.uuid4().hex}},
    )


def _change_password_source_is_allowed(request: Request) -> bool:
    """Reject cross-site browser mutations at the cookie-authenticated boundary."""
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return True
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    host = request.headers.get("host", "")
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.netloc.casefold() == host.casefold()
        and not parsed.username
        and not parsed.password
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
    )


@router.post("/login")
def login(request: Request, payload: dict[str, object]) -> JSONResponse:
    username = payload.get("username")
    password = payload.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return JSONResponse(status_code=422, content={"error": {"code": "product_request_invalid", "message": "username and password are required"}})
    try:
        result = login_user(username, password)
    except ProductAuthError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})
    try:
        workspace = _public_workspace(result.get("workspace"))
    except ProductAuthError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})
    response = JSONResponse(content={"user": result.get("user", {}), "workspace": workspace})
    session_id = result.get("session_id")
    if isinstance(session_id, str):
        response.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="lax", path="/")
    return response


@router.post("/logout")
def logout(request: Request) -> JSONResponse:
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        try:
            logout_user(session_id)
        except ProductAuthError as exc:
            # Retain the exact session cookie for an idempotent retry; do not
            # claim server-side revocation when its receipt is unavailable.
            return JSONResponse(status_code=exc.status_code,
                content={"error": {"code": exc.code, "message": exc.message}})
    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.post("/change-password")
def change_password(request: Request, payload: dict[str, object]) -> JSONResponse:
    if not _change_password_source_is_allowed(request):
        return _auth_error(403, "request_source_rejected", "请求来源无效，请从当前产品页面重试。")
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return _auth_error(401, "product_authentication_required", "请先登录。")
    if (set(payload) != {"current_password", "new_password"}
            or not isinstance(payload.get("current_password"), str)
            or not isinstance(payload.get("new_password"), str)):
        return _auth_error(422, "product_request_invalid", "改密请求格式无效。")
    try:
        change_user_password(session_id, payload)
    except ProductAuthError as exc:
        return _auth_error(exc.status_code, exc.code, exc.message)
    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me")
def me(request: Request) -> JSONResponse:
    try:
        user = resolve_user(request)
    except ProductAuthError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})
    try:
        workspace = _public_workspace(user.get("_workspace"))
    except ProductAuthError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})
    return JSONResponse(content={
        "subject": str(user.get("username") or user.get("user_id")),
        "display_name": str(user.get("display_name") or ""),
        "role": str(user.get("role") or "user"),
        "workspace": workspace,
    })
