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


def test_runtime_roots_projection_filters_in_storage_and_fails_closed_over_limit(monkeypatch):
    from app.agent_research import AgentPersistenceError, AgentResearchStore

    store = object.__new__(AgentResearchStore)
    captured = {}

    def fetch(sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return [{"root_run_id": "a" * 32, "status": "active", "authority_status": "active",
                 "terminal_sequence": None, "terminal_event_sha256": None}]

    monkeypatch.setattr(store, "_execute", fetch)
    result = store.runtime_roots_for_scope(owner_principal="owner", workspace_id="workspace_1",
                                           session_id="session_1", trace_id="trace_1")
    assert captured["params"] == {"owner": "owner", "workspace": "workspace_1", "session": "session_1",
                                   "trace": "trace_1", "limit": 501}
    assert "WHERE owner_principal=:owner AND workspace_id=:workspace" in captured["sql"]
    assert "AND session_id=:session AND trace_id=:trace" in captured["sql"]
    assert "ORDER BY created_at, root_run_id" in captured["sql"]
    assert result["schema_version"] == "byq-business-root-status.v1"
    assert result["roots"] == [{"root_run_id": "a" * 32, "status": "active", "authority_status": "active",
                                "terminal_sequence": None, "terminal_event_sha256": None}]

    monkeypatch.setattr(store, "_execute", lambda _sql, _params: [{}] * 501)
    with pytest.raises(AgentPersistenceError, match="bounded result"):
        store.runtime_roots_for_scope(owner_principal="owner", workspace_id="workspace_1",
                                      session_id="session_1", trace_id="trace_1")


@pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="requires isolated PostgreSQL")
def test_runtime_roots_endpoint_is_bearer_protected_and_exactly_scoped(monkeypatch):
    from uuid import uuid4

    from fastapi.testclient import TestClient
    from app import main
    from app.agent_research import AgentResearchStore
    from tests.workspace_helpers import trusted_agent_context

    monkeypatch.setattr(main, "RUNTIME_AUTHORITY_TOKEN", "synthetic-service-token")
    store = AgentResearchStore()
    client = TestClient(main.app)
    try:
        authority = store.current_runtime_authority()
        if authority is None:
            authority = store.rotate_runtime_authority(uuid4().hex)
        boot_id = authority["boot_id"]

        matching = trusted_agent_context(
            f"runtime-roots-{uuid4().hex[:12]}", session_id="roots-session",
            trace_id="roots-trace", dsh_run_id="roots-generation",
        )
        another_owner = trusted_agent_context(
            f"runtime-roots-{uuid4().hex[:12]}", session_id="roots-session",
            trace_id="roots-trace", dsh_run_id="roots-generation",
        )
        other_session = {**matching, "x-byq-session-id": "other-roots-session"}
        other_trace = {**matching, "x-byq-trace-id": "other-roots-trace"}

        def open_root(context, root_id):
            return store.apply_runtime_lifecycle_event(
                {"schema_version": "agent-run-lifecycle.v1", "root_run_id": root_id,
                 "sequence": 1, "outcome": "active"},
                trusted_owner=context["x-byq-owner-principal"],
                trusted_workspace=context["x-byq-workspace-id"],
                trusted_session_id=context["x-byq-session-id"],
                trusted_trace_id=context["x-byq-trace-id"], trusted_boot_id=boot_id,
            )

        active_root, terminal_root = sorted((uuid4().hex, uuid4().hex))
        open_root(matching, terminal_root)
        store.close_runtime_root(terminal_root, boot_id=boot_id, sequence=9,
                                 outcome="completed", event_sha256="c" * 64)
        open_root(matching, active_root)
        another_owner_root = uuid4().hex
        other_session_root = uuid4().hex
        other_trace_root = uuid4().hex
        open_root(another_owner, another_owner_root)
        open_root(other_session, other_session_root)
        open_root(other_trace, other_trace_root)

        # Equal timestamps exercise the documented root_run_id tie break.
        store._execute("UPDATE agent_runtime_turns SET created_at=TIMESTAMPTZ '2026-01-01 00:00:00+00' "
                       "WHERE root_run_id IN (:first,:second)",
                       {"first": terminal_root, "second": active_root})

        path = "/internal/runtime-authority/sessions/roots-session/roots"
        assert client.get(path).status_code == 401
        headers = {
            "Authorization": "Bearer synthetic-service-token",
            "x-byq-owner-principal": matching["x-byq-owner-principal"],
            "x-byq-workspace-id": matching["x-byq-workspace-id"],
            "x-byq-trace-id": matching["x-byq-trace-id"],
        }
        response = client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json() == {
            "schema_version": "byq-business-root-status.v1",
            "roots": [
                {"root_run_id": active_root, "status": "active", "authority_status": "active",
                 "terminal_sequence": None, "terminal_event_sha256": None},
                {"root_run_id": terminal_root, "status": "completed", "authority_status": "closed",
                 "terminal_sequence": 9, "terminal_event_sha256": "c" * 64},
            ],
        }
        wrong_trace = {**headers, "x-byq-trace-id": "other-roots-trace"}
        wrong_workspace = {**headers, "x-byq-workspace-id": another_owner["x-byq-workspace-id"]}
        wrong_owner = {
            **headers,
            "x-byq-owner-principal": another_owner["x-byq-owner-principal"],
            "x-byq-workspace-id": another_owner["x-byq-workspace-id"],
        }
        assert [root["root_run_id"] for root in client.get(path, headers=wrong_trace).json()["roots"]] == [other_trace_root]
        assert client.get(path, headers=wrong_workspace).json()["roots"] == []
        assert [root["root_run_id"] for root in client.get(path, headers=wrong_owner).json()["roots"]] == [another_owner_root]
        assert [root["root_run_id"] for root in client.get(
            "/internal/runtime-authority/sessions/other-roots-session/roots",
            headers=headers).json()["roots"]] == [other_session_root]
    finally:
        store.close()
