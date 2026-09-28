"""Exact read-only Backend projection for the current Adapter boot identity."""

import os

import pytest


def test_store_projection_is_exact_and_contains_no_secret(monkeypatch):
    from app.agent_research import AgentResearchStore

    store = object.__new__(AgentResearchStore)
    monkeypatch.setattr(store, "_fetch_one", lambda _sql, _params=None: {
        "boot_id": "a" * 32,
        "epoch": 7,
    })
    assert store.current_runtime_authority() == {
        "schema_version": "byq-runtime-authority-current.v1",
        "boot_id": "a" * 32,
        "authority_epoch": 7,
        "status": "current",
    }
    monkeypatch.setattr(store, "_fetch_one", lambda _sql, _params=None: None)
    assert store.current_runtime_authority() is None


@pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="Backend router bootstrap requires isolated PostgreSQL")
def test_gateway_authority_routes_require_service_bearer_and_exact_contract(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    boot_id = "a" * 32
    root_id = "b" * 32
    digest = "c" * 64
    receipt = {
        "schema_version": "byq-runtime-authority-receipt.v1",
        "boot_id": boot_id,
        "authority_epoch": 1,
        "revoked_root_count": 0,
        "revoked_agent_run_count": 0,
        "status": "current",
    }
    terminal_receipt = {
        "schema_version": "agent-run-lifecycle-receipt.v1",
        "sequence": 9,
        "root_run_id": root_id,
        "event_sha256": digest,
    }

    class Store:
        def rotate_runtime_authority(self, received_boot_id):
            assert received_boot_id == boot_id
            return receipt

        def close_runtime_root(self, received_root_id, **kwargs):
            assert received_root_id == root_id
            assert kwargs == {
                "boot_id": boot_id, "sequence": 9, "outcome": "failed", "event_sha256": digest,
            }
            return terminal_receipt

    monkeypatch.setattr(main, "agent_store", Store())
    monkeypatch.setattr(main, "RUNTIME_AUTHORITY_TOKEN", "synthetic-service-token")
    client = TestClient(main.app)
    boot_path = "/internal/runtime-authority/boot"
    boot_body = {"schema_version": "byq-runtime-authority-boot.v1", "boot_id": boot_id}
    assert client.post(boot_path, json=boot_body).status_code == 401
    headers = {"Authorization": "Bearer synthetic-service-token"}
    assert client.post(boot_path, json={**boot_body, "extra": True}, headers=headers).status_code == 422
    response = client.post(boot_path, json=boot_body, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"receipt": receipt}

    close_path = f"/internal/runtime-authority/roots/{root_id}/close"
    close_body = {
        "schema_version": "byq-runtime-root-close.v1", "boot_id": boot_id,
        "sequence": 9, "outcome": "failed", "event_sha256": digest,
    }
    assert client.post(close_path, json=close_body).status_code == 401
    assert client.post(close_path, json={**close_body, "event": {}}, headers=headers).status_code == 422
    response = client.post(close_path, json=close_body, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"receipt": terminal_receipt}


def test_runtime_authority_identity_fields_fail_closed_before_database_access():
    from app.agent_research import AgentResearchStore

    store = object.__new__(AgentResearchStore)
    for boot_id in ("A" * 32, "short", "a" * 31, "g" * 32):
        try:
            store.close_runtime_root("b" * 32, boot_id=boot_id, sequence=1,
                                     outcome="failed", event_sha256="c" * 64)
        except ValueError as error:
            assert "boot id" in str(error)
        else:
            raise AssertionError("invalid boot id was accepted")
    for digest in ("C" * 64, "short", "g" * 64):
        try:
            store.close_runtime_root("b" * 32, boot_id="a" * 32, sequence=1,
                                     outcome="failed", event_sha256=digest)
        except ValueError as error:
            assert "event_sha256" in str(error)
        else:
            raise AssertionError("invalid event digest was accepted")
