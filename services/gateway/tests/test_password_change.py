from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app import auth_api, main, user_session


def test_gateway_password_change_requires_exact_fields_and_cookie(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(auth_api, "change_user_password", lambda *args: calls.append(args))
    client = TestClient(main.app)

    missing_session = client.post("/api/auth/change-password", json={
        "current_password": "current-pass", "new_password": "new-pass-123",
    })
    assert missing_session.status_code == 401
    assert missing_session.json()["error"]["code"] == "product_authentication_required"

    client.cookies.set("byq_session", "session_" + "a" * 32)
    invalid_fields = client.post("/api/auth/change-password", json={
        "current_password": "current-pass", "new_password": "new-pass-123",
        "user_id": "user_" + "b" * 32,
    })
    assert invalid_fields.status_code == 422
    assert invalid_fields.json()["error"]["code"] == "product_request_invalid"
    assert calls == []


def test_gateway_password_change_checks_origin_and_fetch_site(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(auth_api, "change_user_password", lambda *args: calls.append(args))
    client = TestClient(main.app)
    client.cookies.set("byq_session", "session_" + "a" * 32)
    body = {"current_password": "current-pass", "new_password": "new-pass-123"}

    cross_site = client.post("/api/auth/change-password", json=body,
                             headers={"sec-fetch-site": "cross-site"})
    wrong_origin = client.post("/api/auth/change-password", json=body,
                               headers={"origin": "https://attacker.example"})
    assert cross_site.status_code == wrong_origin.status_code == 403
    assert cross_site.json()["error"]["code"] == "request_source_rejected"
    assert wrong_origin.json()["error"]["code"] == "request_source_rejected"
    assert calls == []


def test_gateway_password_change_clears_cookie_only_after_receipt(monkeypatch) -> None:
    client = TestClient(main.app)
    session_id = "session_" + "a" * 32
    client.cookies.set("byq_session", session_id)
    payload = {"current_password": "current-pass", "new_password": "new-pass-123"}
    calls = []

    monkeypatch.setattr(auth_api, "change_user_password",
                        lambda received_id, received_payload: calls.append((received_id, received_payload)))
    success = client.post("/api/auth/change-password", json=payload,
                          headers={"origin": "http://testserver"})
    assert success.status_code == 200
    assert success.json() == {"status": "ok"}
    assert "Max-Age=0" in success.headers["set-cookie"]
    assert calls == [(session_id, payload)]

    client.cookies.set("byq_session", session_id)

    def unknown(*_args):
        raise user_session.ProductAuthError(
            503, "password_change_outcome_unknown", "改密结果尚未确认，请检查登录状态后再继续。",
        )

    monkeypatch.setattr(auth_api, "change_user_password", unknown)
    uncertain = client.post("/api/auth/change-password", json=payload,
                            headers={"origin": "http://testserver"})
    assert uncertain.status_code == 503
    assert uncertain.json()["error"]["code"] == "password_change_outcome_unknown"
    assert "set-cookie" not in uncertain.headers
    assert client.cookies.get("byq_session") == session_id


@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_code"),
    [
        ("wrong_current", 403, "current_password_invalid"),
        ("invalid_policy", 422, "password_policy_invalid"),
        ("rate_limited", 429, "password_change_rate_limited"),
        ("server", 503, "password_change_outcome_unknown"),
        ("timeout", 503, "password_change_outcome_unknown"),
        ("bad_receipt", 503, "password_change_outcome_unknown"),
    ],
)
def test_user_session_password_change_maps_errors_without_echoing_secrets(
    monkeypatch, failure, expected_status, expected_code,
) -> None:
    current_password = "raw-current-secret"
    new_password = "raw-new-secret"
    payload = {"current_password": current_password, "new_password": new_password}
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if failure == "timeout":
            raise httpx.ReadTimeout("transport detail must not escape")
        if failure == "wrong_current":
            return httpx.Response(403, json={"detail": "current password is incorrect"},
                                  request=httpx.Request("POST", url))
        if failure == "invalid_policy":
            return httpx.Response(422, json={"detail": new_password},
                                  request=httpx.Request("POST", url))
        if failure == "server":
            return httpx.Response(500, json={"detail": new_password},
                                  request=httpx.Request("POST", url))
        if failure == "rate_limited":
            return httpx.Response(429, json={"detail": "password change rate limit reached"},
                                  request=httpx.Request("POST", url))
        return httpx.Response(200, json={"status": "maybe"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(user_session.httpx, "post", post)
    with pytest.raises(user_session.ProductAuthError) as caught:
        user_session.change_password("session_" + "a" * 32, payload)

    assert caught.value.status_code == expected_status
    assert caught.value.code == expected_code
    assert current_password not in caught.value.message
    assert new_password not in caught.value.message
    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url.endswith("/v1/auth/change-password")
    assert kwargs["headers"] == {"x-byq-session-id": "session_" + "a" * 32}
    assert kwargs["json"] == payload
