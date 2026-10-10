from __future__ import annotations

import importlib.util
import json
import os
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
