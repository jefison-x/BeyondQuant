"""Browser authentication endpoints under /api/auth."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .user_session import SESSION_COOKIE, ProductAuthError, login as login_user, logout as logout_user, resolve_user


router = APIRouter(prefix="/api/auth")


class AuthApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


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
    response = JSONResponse(content={"user": result.get("user", {})})
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
        except ProductAuthError:
            pass
    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me")
def me(request: Request) -> JSONResponse:
    try:
        user = resolve_user(request)
    except ProductAuthError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})
    return JSONResponse(content={"subject": str(user.get("username") or user.get("user_id"))})
