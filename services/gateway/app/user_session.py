"""Gateway-owned durable user session helpers."""

from __future__ import annotations

import os

import httpx
from fastapi import Request

from .auth import Principal


BACKEND_URL = os.environ.get("BYQ_BACKEND_URL", "http://backend:8000")
SESSION_COOKIE = "byq_session"


class ProductAuthError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def login(username: str, password: str) -> dict[str, object]:
    try:
        response = httpx.post(
            f"{BACKEND_URL}/v1/auth/login",
            json={"username": username, "password": password},
            timeout=5.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = "invalid username or password"
        if exc.response.status_code == 403:
            detail = str(exc.response.json().get("detail", detail))
        raise ProductAuthError(exc.response.status_code, "login_failed", detail) from exc
    except httpx.HTTPError as exc:
        raise ProductAuthError(503, "backend_unavailable", "backend is unavailable") from exc
    body = response.json()
    if not isinstance(body, dict):
        raise ProductAuthError(502, "backend_invalid_response", "backend returned an invalid response")
    return body


def logout(session_id: str) -> None:
    try:
        response = httpx.post(f"{BACKEND_URL}/v1/auth/logout", json={"session_id": session_id}, timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProductAuthError(503, "backend_unavailable", "backend is unavailable") from exc


def resolve_principal(request: Request) -> Principal:
    user = resolve_user(request)
    return Principal(subject=str(user.get("username") or user.get("user_id")))


def resolve_user(request: Request) -> dict[str, object]:
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        raise ProductAuthError(401, "product_authentication_required", "product authentication required")
    try:
        response = httpx.get(
            f"{BACKEND_URL}/v1/auth/session",
            headers={"x-byq-session-id": session_id},
            timeout=5.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ProductAuthError(exc.response.status_code, "session_invalid", "session is not valid") from exc
    except httpx.HTTPError as exc:
        raise ProductAuthError(503, "backend_unavailable", "backend is unavailable") from exc
    body = response.json()
    if (
        not isinstance(body, dict)
        or not isinstance(body.get("user"), dict)
        or not isinstance(body.get("workspace"), dict)
        or not isinstance(body["workspace"].get("workspace_id"), str)
    ):
        raise ProductAuthError(502, "backend_invalid_response", "backend returned an invalid response")
    user = dict(body["user"])
    user["_workspace"] = body["workspace"]
    return user
