from __future__ import annotations

import importlib.util
import io
import json
import os
import urllib.error
from pathlib import Path

import pytest
from starlette.requests import Request

from app import auth_api


def _load_phase48_script():
    configured_path = os.environ.get("BYQ_PHASE48_GOLDEN_SCRIPT_PATH")
    if configured_path:
        path = Path(configured_path)
    else:
        repo_root = Path(__file__).resolve().parents[3]
        path = repo_root / "scripts/evidence/phase48-product-golden.py"
    spec = importlib.util.spec_from_file_location("phase48_product_golden", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Phase 48 workspace receipt script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _request(method: str, path: str) -> Request:
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "server": ("gateway.test", 80),
        "client": ("test-client", 12345),
    })


def _actual_login_and_me(monkeypatch, username: str, workspace: dict[str, str]) -> tuple[dict, dict]:
    user = {"username": username, "display_name": "CI admin", "role": "admin"}
    monkeypatch.setattr(auth_api, "login_user", lambda _username, _password: {
        "user": user,
        "workspace": workspace,
        "session_id": "synthetic-session",
    })
    login_response = auth_api.login(
        _request("POST", "/api/auth/login"),
        {"username": username, "password": "synthetic-only"},
    )
    assert login_response.status_code == 200
    login_projection = json.loads(login_response.body)

    monkeypatch.setattr(auth_api, "resolve_user", lambda _request: {
        **user,
        "_workspace": workspace,
    })
    me_response = auth_api.me(_request("GET", "/api/auth/me"))
    assert me_response.status_code == 200
    me_projection = json.loads(me_response.body)
    return login_projection, me_projection


def test_receipt_uses_actual_gateway_auth_me_subject_and_workspace(monkeypatch) -> None:
    script = _load_phase48_script()
    username = "ci-admin"
    workspace = {
        "contract": "personal-workspace.v1",
        "workspace_id": "workspace_0123456789abcdef0123456789abcdef",
        "kind": "personal",
        "display_name": "CI admin workspace",
        "role": "owner",
    }
    login, me = _actual_login_and_me(monkeypatch, username, workspace)

    assert set(me) == {"subject", "display_name", "role", "workspace"}
    assert me["subject"] == username
    receipt = script.workspace_receipt_payload(
        username, login["user"], login["workspace"], me,
    )
    assert receipt["username"] == username
    assert receipt["workspace"]["workspace_id"] == workspace["workspace_id"]


def test_receipt_rejects_wrong_subject_and_workspace_from_actual_me_projection(monkeypatch) -> None:
    script = _load_phase48_script()
    username = "ci-admin"
    workspace = {
        "contract": "personal-workspace.v1",
        "workspace_id": "workspace_0123456789abcdef0123456789abcdef",
        "kind": "personal",
        "display_name": "CI admin workspace",
        "role": "owner",
    }
    login, _me = _actual_login_and_me(monkeypatch, username, workspace)

    wrong_owner, _wrong_me = _actual_login_and_me(monkeypatch, "other-user", workspace)
    with pytest.raises(AssertionError, match="authenticated session returned the wrong owner"):
        script.workspace_receipt_payload(
            username, login["user"], login["workspace"], _wrong_me,
        )

    changed_workspace = {**workspace, "workspace_id": "workspace_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
    _login, mismatched_me = _actual_login_and_me(monkeypatch, username, changed_workspace)
    with pytest.raises(AssertionError, match="authenticated session workspace differs from login"):
        script.workspace_receipt_payload(
            username, login["user"], login["workspace"], mismatched_me,
        )


class _FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_exc) -> bool:
        return False


def _client_with_fake_transport(script, monkeypatch, status: int, body: bytes):
    class _Opener:
        def open(self, request, timeout=None):
            if status >= 400:
                raise urllib.error.HTTPError(request.full_url, status, "error", {}, io.BytesIO(body))
            return _FakeResponse(status, body)

    monkeypatch.setattr(script.urllib.request, "build_opener", lambda *args, **kwargs: _Opener())
    client = script.ProductClient.__new__(script.ProductClient)
    client.opener = script.urllib.request.build_opener()
    return client


def test_keyless_turn_requires_observed_public_503_rejection() -> None:
    script = _load_phase48_script()
    script.require_observed_public_turn_rejection_503({"detail": "product model is unavailable"})
    script.require_observed_public_turn_rejection_503({"detail": "product model is unavailable", "accepted": False})
    for body in (
        {"detail": "internal error"},
        {"detail": "product model is unavailable", "accepted": True},
        {"detail": "product model is unavailable", "accepted": 1},
        {"detail": "product model is unavailable", "accepted": "true"},
        {"detail": "product model is unavailable", "accepted": 0},
        {"detail": "product model is unavailable", "accepted": []},
        {"detail": "product model is unavailable", "accepted": {}},
        {"accepted": False},
        {},
        None,
        ["not", "an", "object"],
        "not-an-object",
    ):
        with pytest.raises(AssertionError):
            script.require_observed_public_turn_rejection_503(body)


def test_default_accepted_turn_requires_true_and_rejects_false() -> None:
    script = _load_phase48_script()
    script.require_accepted_turn({"accepted": True})
    for body in ({"accepted": False}, {}, None, {"accepted": 1}):
        with pytest.raises(AssertionError):
            script.require_accepted_turn(body)


def test_keyless_turn_rejects_unexpected_status_and_malformed_body(monkeypatch) -> None:
    script = _load_phase48_script()
    unexpected = _client_with_fake_transport(script, monkeypatch, 200, b'{"accepted": true}')
    with pytest.raises(AssertionError):
        unexpected.request("POST", "/v1/agent/sessions/s/turns", {"content": "x"}, expected_status=503)
    malformed = _client_with_fake_transport(script, monkeypatch, 200, b"{")
    with pytest.raises(ValueError):
        malformed.request("POST", "/v1/agent/sessions/s/turns", {"content": "x"}, expected_status=503)


def test_keyless_turn_accepts_exact_503_detail(monkeypatch) -> None:
    script = _load_phase48_script()
    client = _client_with_fake_transport(
        script, monkeypatch, 503, b'{"detail": "product model is unavailable"}')
    body = client.request("POST", "/v1/agent/sessions/s/turns", {"content": "x"}, expected_status=503)
    script.require_observed_public_turn_rejection_503(body)


def test_main_rejects_unknown_argument_before_login(monkeypatch) -> None:
    script = _load_phase48_script()
    constructed: list[int] = []
    monkeypatch.setattr(script, "ProductClient", lambda *args, **kwargs: constructed.append(1))
    monkeypatch.setattr(script.sys, "argv", ["phase48-product-golden.py", "--bogus"])
    with pytest.raises(SystemExit):
        script.main()
    assert constructed == []


def test_main_routes_workspace_receipt_and_keyless_modes(monkeypatch) -> None:
    script = _load_phase48_script()
    calls: list[str] = []

    def _receipt() -> None:
        calls.append("receipt")

    monkeypatch.setattr(script, "workspace_receipt", _receipt)
    monkeypatch.setattr(script.sys, "argv", ["phase48-product-golden.py", "--workspace-receipt"])
    script.main()
    assert calls == ["receipt"]

    def _stop(*_args, **_kwargs):
        raise RuntimeError("proceeded past argument parsing")

    monkeypatch.setattr(script, "ProductClient", _stop)
    monkeypatch.setattr(script.sys, "argv", ["phase48-product-golden.py", "--keyless-acp"])
    with pytest.raises(RuntimeError, match="proceeded past argument parsing"):
        script.main()


def test_require_single_persisted_user_turn_accepts_exact_user_with_optional_assistant() -> None:
    script = _load_phase48_script()
    content = "记录 Phase 48"
    script.require_single_persisted_user_turn(
        {"messages": [{"role": "user", "content": content}, {"role": "assistant", "content": "ok"}]},
        content,
    )
    script.require_single_persisted_user_turn(
        {"messages": [{"role": "user", "content": content}]}, content)


def test_require_single_persisted_user_turn_rejects_malformed_readbacks() -> None:
    script = _load_phase48_script()
    content = "记录 Phase 48"
    for replay in (
        {"messages": [{"role": "assistant", "content": content}]},            # no user
        {"messages": [{"role": "system", "content": content}]},               # wrong role
        {"messages": [{"role": "user", "content": content},
                      {"role": "user", "content": content}]},                  # duplicate users
        {"messages": [{"role": "user", "content": "other"}]},                 # wrong content
        {"messages": "not-a-list"},                                            # malformed list
        {"messages": {"role": "user", "content": content}},                   # object not list
        {},                                                                    # missing messages
        [],                                                                    # not an object
        None,                                                                  # not an object
    ):
        with pytest.raises(AssertionError):
            script.require_single_persisted_user_turn(replay, content)
