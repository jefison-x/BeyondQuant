"""Focused PostgreSQL tests for Workspace-scoped runtime reset fencing."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.agent_research import AgentResearchStore
from app.conversation_catalog import ConversationCatalogStore
from app.workspace_runtime_reset import WorkspaceRuntimeResetConflict, WorkspaceRuntimeResetStore
from app.workspace_tenancy import WorkspaceTenancyStore
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required",
)


def _open_root(agents: AgentResearchStore, context: dict[str, str], boot_id: str) -> str:
    root_id = uuid4().hex
    agents.apply_runtime_lifecycle_event(
        {"schema_version": "agent-run-lifecycle.v1", "root_run_id": root_id,
         "sequence": 1, "outcome": "active"},
        trusted_owner=context["x-byq-owner-principal"],
        trusted_workspace=context["x-byq-workspace-id"],
        trusted_session_id=context["x-byq-session-id"],
        trusted_trace_id=context["x-byq-trace-id"],
        trusted_boot_id=boot_id,
    )
    return root_id


def _open_run(agents: AgentResearchStore, context: dict[str, str], boot_id: str) -> str:
    run = agents.start_run(
        {"role_id": "quant_orchestrator", "trace_id": context["x-byq-trace-id"],
         "session_id": context["x-byq-session-id"], "dsh_run_id": context["x-byq-dsh-run-id"],
         "idempotency_key": "reset-" + uuid4().hex},
        trusted_owner=context["x-byq-owner-principal"],
        trusted_actor=context["x-byq-actor-principal"],
        trusted_workspace=context["x-byq-workspace-id"],
        trusted_boot_id=boot_id,
    )
    return str(run["run_id"])


def test_reset_fences_only_one_workspace_and_requires_exact_release_proof() -> None:
    suffix = uuid4().hex[:12]
    contexts = [
        trusted_agent_context(f"runtime-reset-a-{suffix}", session_id=f"session-a-{suffix}",
                              trace_id=f"trace-a-{suffix}", dsh_run_id=f"dsh-a-{suffix}"),
        trusted_agent_context(f"runtime-reset-b-{suffix}", session_id=f"session-b-{suffix}",
                              trace_id=f"trace-b-{suffix}", dsh_run_id=f"dsh-b-{suffix}"),
    ]
    tenancy = WorkspaceTenancyStore()
    conversations = ConversationCatalogStore()
    agents = AgentResearchStore()
    resets = WorkspaceRuntimeResetStore()
    try:
        authority = agents.current_runtime_authority()
        if authority is None:
            authority = agents.rotate_runtime_authority(uuid4().hex)
        boot_id = str(authority["boot_id"])
        conversation_ids: list[str] = []
        roots: list[str] = []
        runs: list[str] = []
        for context in contexts:
            owner = context["x-byq-owner-principal"]
            conversation = conversations.create(
                owner, context["x-byq-session-id"], context["x-byq-trace-id"])
            conversations.append_user_message(owner, conversation["conversation_id"], "retain this transcript")
            conversation_ids.append(str(conversation["conversation_id"]))
            roots.append(_open_root(agents, context, boot_id))
            runs.append(_open_run(agents, context, boot_id))

        first = resets.begin(owner_principal=contexts[0]["x-byq-owner-principal"],
                             workspace_id=contexts[0]["x-byq-workspace-id"])
        assert first["schema_version"] == "workspace-runtime-reset-begin.v1"
        assert first["sessions"] == [{
            "conversation_id": conversation_ids[0],
            "session_id": contexts[0]["x-byq-session-id"],
            "trace_id": contexts[0]["x-byq-trace-id"],
        }]
        assert len(first["reset_id"]) == 32
        assert resets.begin(owner_principal=contexts[0]["x-byq-owner-principal"],
                            workspace_id=contexts[0]["x-byq-workspace-id"]) == first

        with pytest.raises(ValueError, match="trusted workspace context"):
            tenancy.resolve_context(contexts[0]["x-byq-owner-principal"],
                                    contexts[0]["x-byq-workspace-id"])
        assert tenancy.resolve_context(contexts[1]["x-byq-owner-principal"],
                                       contexts[1]["x-byq-workspace-id"])["workspace_id"] == contexts[1]["x-byq-workspace-id"]
        assert agents._fetch_one("SELECT authority_status FROM agent_runtime_turns WHERE root_run_id=:id",
                                 {"id": roots[0]})["authority_status"] == "authority_revoked_unconfirmed"
        assert agents._fetch_one("SELECT authority_status FROM agent_runtime_turns WHERE root_run_id=:id",
                                 {"id": roots[1]})["authority_status"] == "active"
        assert agents._fetch_one("SELECT authority_status FROM agent_runs WHERE run_id=:id",
                                 {"id": runs[0]})["authority_status"] == "authority_revoked_unconfirmed"
        assert agents._fetch_one("SELECT authority_status FROM agent_runs WHERE run_id=:id",
                                 {"id": runs[1]})["authority_status"] == "active"

        with pytest.raises(WorkspaceRuntimeResetConflict, match="release proof"):
            resets.finalize(owner_principal=contexts[0]["x-byq-owner-principal"],
                            workspace_id=contexts[0]["x-byq-workspace-id"],
                            reset_id=first["reset_id"], released_sessions=[])
        pending = tenancy._fetch_one("SELECT status,reset_id FROM workspaces WHERE workspace_id=:id",
                                     {"id": contexts[0]["x-byq-workspace-id"]})
        assert pending == {"status": "disabled", "reset_id": first["reset_id"]}

        released = [contexts[0]["x-byq-session-id"]]
        finalized = resets.finalize(owner_principal=contexts[0]["x-byq-owner-principal"],
                                    workspace_id=contexts[0]["x-byq-workspace-id"],
                                    reset_id=first["reset_id"], released_sessions=released)
        assert finalized == {
            "schema_version": "workspace-runtime-reset-finalize.v1",
            "workspace_id": contexts[0]["x-byq-workspace-id"],
            "reset_id": first["reset_id"],
            "status": "finalized",
            "archived_conversation_ids": [conversation_ids[0]],
        }
        assert resets.finalize(owner_principal=contexts[0]["x-byq-owner-principal"],
                               workspace_id=contexts[0]["x-byq-workspace-id"],
                               reset_id=first["reset_id"], released_sessions=released) == finalized
        assert tenancy.resolve_context(contexts[0]["x-byq-owner-principal"],
                                       contexts[0]["x-byq-workspace-id"])["workspace_id"] == contexts[0]["x-byq-workspace-id"]
        assert agents._fetch_one("SELECT status,authority_status,terminal_sequence FROM agent_runtime_turns WHERE root_run_id=:id",
                                 {"id": roots[0]}) == {
                                     "status": "interrupted", "authority_status": "closed", "terminal_sequence": None}
        assert agents._fetch_one("SELECT status,authority_status FROM agent_runs WHERE run_id=:id",
                                 {"id": runs[0]}) == {"status": "interrupted", "authority_status": "closed"}
        assert conversations.get(contexts[0]["x-byq-owner-principal"], conversation_ids[0])["status"] == "archived"
        assert [message["content"] for message in conversations.messages(
            contexts[0]["x-byq-owner-principal"], conversation_ids[0])] == ["retain this transcript"]
        assert conversations.get(contexts[1]["x-byq-owner-principal"], conversation_ids[1])["status"] == "active"
    finally:
        resets.close()
        agents.close()
        conversations.close()
        tenancy.close()


def test_private_reset_routes_keep_cookie_identity_and_deny_agent_admission(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app import main
    from app.user_auth import UserAuthStore

    owner = "runtime-reset-api-" + uuid4().hex[:12]
    password = "test-password-123"
    users = UserAuthStore()
    user = users.create_user(
        {"username": owner, "password": password, "display_name": owner}, actor_role="admin")
    tenancy = WorkspaceTenancyStore()
    conversations = ConversationCatalogStore()
    agents = AgentResearchStore()
    resets = WorkspaceRuntimeResetStore()
    try:
        workspace = tenancy.public_workspace(str(user["user_id"]))
        session_id = "session-" + uuid4().hex
        trace_id = "trace-" + uuid4().hex
        conversation = conversations.create(owner, session_id, trace_id)
        login = users.login(owner, password)
        authority = agents.current_runtime_authority()
        if authority is None:
            authority = agents.rotate_runtime_authority(uuid4().hex)

        monkeypatch.setattr(main, "user_store", users)
        monkeypatch.setattr(main, "workspace_tenancy_store", tenancy)
        monkeypatch.setattr(main, "workspace_runtime_reset_store", resets)
        monkeypatch.setattr(main, "RUNTIME_AUTHORITY_TOKEN", "workspace-reset-test-token")
        client = TestClient(main.app)
        owner_headers = {
            "x-byq-owner-principal": owner,
            "x-byq-workspace-id": workspace["workspace_id"],
        }
        begin_body = {"schema_version": "workspace-runtime-reset-begin.v1"}
        begin_path = "/internal/workspace-runtime-reset/begin"
        assert client.post(begin_path, json=begin_body, headers=owner_headers).status_code == 401
        service_headers = {**owner_headers, "Authorization": "Bearer workspace-reset-test-token"}
        assert client.post(begin_path, json={**begin_body, "unexpected": True},
                           headers=service_headers).status_code == 422
        response = client.post(begin_path, json=begin_body, headers=service_headers)
        assert response.status_code == 200, response.text
        begin = response.json()
        assert begin == {
            "schema_version": "workspace-runtime-reset-begin.v1",
            "workspace_id": workspace["workspace_id"],
            "reset_id": begin["reset_id"],
            "sessions": [{"conversation_id": conversation["conversation_id"],
                          "session_id": session_id, "trace_id": trace_id}],
        }

        session = client.get("/v1/auth/session", headers={"x-byq-session-id": login["session_id"]})
        assert session.status_code == 200, session.text
        assert session.json()["user"]["username"] == owner
        assert session.json()["workspace"] == workspace

        agent_headers = {
            **owner_headers,
            "x-byq-actor-principal": f"byq-product-agent-{session_id}",
            "x-byq-runtime-boot-id": str(authority["boot_id"]),
            "x-byq-trace-id": trace_id,
            "x-byq-session-id": session_id,
            "x-byq-dsh-run-id": "dsh-" + uuid4().hex,
        }
        agent_mutation = client.post("/v1/agents/runs", headers=agent_headers, json={
            "role_id": "quant_orchestrator", "trace_id": trace_id,
            "session_id": session_id, "dsh_run_id": agent_headers["x-byq-dsh-run-id"],
            "idempotency_key": "reset-api-" + uuid4().hex,
        })
        assert agent_mutation.status_code == 401

        finalize_body = {
            "schema_version": "workspace-runtime-reset-finalize.v1",
            "reset_id": begin["reset_id"],
            "released_sessions": [session_id],
        }
        finalize_headers = {**service_headers}
        assert client.post("/internal/workspace-runtime-reset/finalize",
                          json={**finalize_body, "extra": True},
                          headers=finalize_headers).status_code == 422
        finalized = client.post("/internal/workspace-runtime-reset/finalize",
                                json=finalize_body, headers=finalize_headers)
        assert finalized.status_code == 200, finalized.text
        assert finalized.json() == {
            "schema_version": "workspace-runtime-reset-finalize.v1",
            "workspace_id": workspace["workspace_id"],
            "reset_id": begin["reset_id"],
            "status": "finalized",
            "archived_conversation_ids": [conversation["conversation_id"]],
        }
    finally:
        resets.close()
        agents.close()
        conversations.close()
        tenancy.close()
        users.close()


def test_private_workspace_reset_routes_require_service_authority_and_exact_contract(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app import main

    workspace_id = "workspace-route-reset"
    reset_id = "b" * 32
    request_key = str(uuid4())

    class ResetStub:
        def __init__(self) -> None:
            self.calls = []

        def begin_workspace_reset(self, **kwargs):
            self.calls.append(("begin", kwargs))
            return {"schema_version": "workspace-reset-begin.v1", "workspace_id": workspace_id,
                    "reset_id": reset_id, "status": "pending", "sessions": []}

        def finalize_workspace_reset(self, **kwargs):
            self.calls.append(("finalize", kwargs))
            return {"schema_version": "workspace-reset-finalize.v1", "workspace_id": workspace_id,
                    "reset_id": reset_id, "status": "reset", "deleted": {}, "already_empty": True}

    resets = ResetStub()
    monkeypatch.setattr(main, "workspace_runtime_reset_store", resets)
    monkeypatch.setattr(main, "RUNTIME_AUTHORITY_TOKEN", "workspace-reset-service-token")
    client = TestClient(main.app)
    identity_headers = {
        "x-byq-owner-principal": "alice",
        "x-byq-workspace-id": workspace_id,
    }
    service_headers = {**identity_headers, "Authorization": "Bearer workspace-reset-service-token"}
    begin_path = "/internal/workspace-reset/begin"
    begin_body = {"schema_version": "workspace-reset-begin.v1", "request_key": request_key}
    assert client.post(begin_path, json=begin_body, headers=identity_headers).status_code == 401
    assert client.post(begin_path, json={**begin_body, "extra": True},
                       headers=service_headers).status_code == 422
    begun = client.post(begin_path, json=begin_body, headers=service_headers)
    assert begun.status_code == 200, begun.text
    assert begun.json()["status"] == "pending"

    finalize_path = "/internal/workspace-reset/finalize"
    finalize_body = {"schema_version": "workspace-reset-finalize.v1", "reset_id": reset_id,
                     "request_key": request_key, "released_sessions": []}
    assert client.post(finalize_path, json=finalize_body, headers=identity_headers).status_code == 401
    assert client.post(finalize_path, json={**finalize_body, "extra": True},
                       headers=service_headers).status_code == 422
    finalized = client.post(finalize_path, json=finalize_body, headers=service_headers)
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["status"] == "reset"
    assert resets.calls == [
        ("begin", {"owner_principal": "alice", "workspace_id": workspace_id,
                    "idempotency_key": request_key}),
        ("finalize", {"owner_principal": "alice", "workspace_id": workspace_id,
                       "reset_id": reset_id, "idempotency_key": request_key,
                       "released_sessions": []}),
    ]
