"""Deterministic stable executor identity for the runtime-adapter test suite.

ADR-0079 removes host boot identity from the lifecycle-journal lease. Tests
therefore need a deployment-controlled ``runtime-executor.v1`` record instead of
the image path ``/opt/byq/releases/deployment.identity.json``. This fixture
points ``BYQ_DSH_RELEASE_IDENTITY`` at a session-scoped synthetic identity; every
test that claims a journal under its own ``tmp_path`` bootstraps its own
volume-owned epoch record from that identity.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

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
