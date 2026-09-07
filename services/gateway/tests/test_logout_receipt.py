import httpx
import pytest
from fastapi.testclient import TestClient
from app import main, user_session


@pytest.mark.parametrize("path", ["/api/auth/logout", "/api/product/auth/logout"])
@pytest.mark.parametrize("failure", ["transport", "server", "json", "wrong_ack"])
def test_logout_keeps_original_cookie_until_exact_revocation_receipt(monkeypatch, path, failure):
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs["json"])
        if len(calls) == 1:
            if failure == "transport":
                raise httpx.ReadTimeout("synthetic lost logout acknowledgement")
            return httpx.Response(500 if failure == "server" else 200,
                text="invalid" if failure == "json" else "{}", request=httpx.Request("POST", url))
        return httpx.Response(200, json={"status": "ok"}, request=httpx.Request("POST", url))
    monkeypatch.setattr(user_session.httpx, "post", post)
    client = TestClient(main.app)
    first = client.post(path, headers={"cookie": "byq_session=synthetic-session"})
    assert first.status_code == 503
    assert first.json()["error"]["code"] == "logout_outcome_unknown"
    assert "set-cookie" not in first.headers
    second = client.post(path, headers={"cookie": "byq_session=synthetic-session"})
    assert second.status_code == 200
    assert "Max-Age=0" in second.headers["set-cookie"]
    assert calls == [{"session_id": "synthetic-session"}] * 2
