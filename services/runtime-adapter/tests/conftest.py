"""Deterministic stable executor identity for the runtime-adapter test suite.

ADR-0079 removes host boot identity from the lifecycle-journal lease. Tests
therefore need a deployment-controlled ``runtime-executor.v1`` record instead of
the image path ``/opt/byq/releases/deployment.identity.json``. This fixture
points ``BYQ_DSH_RELEASE_IDENTITY`` at a session-scoped synthetic identity; every
test that claims a journal under its own ``tmp_path`` bootstraps its own
volume-owned epoch record from that identity.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import secrets

import pytest


@pytest.fixture(scope="session", autouse=True)
def _stable_executor_identity(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("byq-executor-identity")
    path = directory / "deployment.identity.json"
    path.write_text(json.dumps({
        "schema_version": "dsh-deployment-identity.v1",
        "default_release": "dsh-0.1.5rc1",
        "python": {"sdk": "0.1.5rc1", "runtime_bin": "0.1.5rc1"},
        "runtime_executor": {
            "schema_version": "runtime-executor.v1",
            "deployment_id": "byq-test-runtime",
            "runtime_release": "dsh-0.1.5rc1",
            "volume_identity": "byq-test-sessions",
            "executor_epoch": 1,
        },
    }), encoding="utf-8")
    previous = os.environ.get("BYQ_DSH_RELEASE_IDENTITY")
    os.environ["BYQ_DSH_RELEASE_IDENTITY"] = str(path)
    try:
        yield path
    finally:
        if previous is None:
            os.environ.pop("BYQ_DSH_RELEASE_IDENTITY", None)
        else:
            os.environ["BYQ_DSH_RELEASE_IDENTITY"] = previous


@pytest.fixture
def allow_current_runtime_authority(monkeypatch: pytest.MonkeyPatch):
    """Isolate legacy Adapter API tests from the external Backend authority row."""

    def allow(adapter) -> None:
        monkeypatch.setattr(adapter, "require_current_backend_authority", lambda: None)

    return allow

_PRODUCT_SLOT_TRANSPORT_ENV = "BYQ_DSH_ACP_PROCESS_TRANSPORT"
_PRODUCT_SLOT_BINDINGS_ENV = "BYQ_ACP_PRODUCT_SLOT_BINDINGS"
_PRODUCT_SLOT_SECRET_PREFIX = "BYQ_ACP_PRODUCT_SLOT_TEST_"
_product_slot_env_restore: dict[str, str | None] | None = None


def pytest_configure(config: pytest.Config) -> None:
    """Supply offline synthetic Product bindings before test-module collection."""

    del config
    global _product_slot_env_restore
    if (_product_slot_env_restore is not None
            or os.environ.get(_PRODUCT_SLOT_TRANSPORT_ENV) != "product-slot-v1"
            or _PRODUCT_SLOT_BINDINGS_ENV in os.environ):
        return

    token = secrets.token_hex(8).upper()
    secret_name = f"{_PRODUCT_SLOT_SECRET_PREFIX}{token}_SECRET"
    while secret_name in os.environ:
        token = secrets.token_hex(8).upper()
        secret_name = f"{_PRODUCT_SLOT_SECRET_PREFIX}{token}_SECRET"
    secret_value = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    binding_value = json.dumps({
        "byq-pytest-workspace": {
            "socket_path": f"/tmp/byq-product-slot-pytest-{token.lower()}.sock",
            "control_secret_env": secret_name,
        },
    }, sort_keys=True, separators=(",", ":"))

    _product_slot_env_restore = {
        _PRODUCT_SLOT_BINDINGS_ENV: os.environ.get(_PRODUCT_SLOT_BINDINGS_ENV),
        secret_name: os.environ.get(secret_name),
    }
    os.environ[_PRODUCT_SLOT_BINDINGS_ENV] = binding_value
    os.environ[secret_name] = secret_value


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restore exactly the environment values supplied by this test hook."""

    del config
    global _product_slot_env_restore
    if _product_slot_env_restore is None:
        return
    for name, previous in _product_slot_env_restore.items():
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous
    _product_slot_env_restore = None
