from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from app.agent_research import AgentConflict, AgentForbidden, AgentNotFound, AgentResearchStore, AgentUnauthorized
from app.conversation_catalog import ConversationCatalogStore
from app.domain_call_admission import acp_binding_sha256
from app.research import ResearchStore
from packages.contracts.agent_run_lifecycle import registration_fingerprint
from tests.workspace_helpers import trusted_agent_context, trusted_product_agent_context


pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="requires isolated PostgreSQL")


def _context(label: str) -> dict[str, str]:
    return trusted_product_agent_context(
        f"acp-{label}", actor=f"byq-product-agent-session-acp-{label}",
        session_id=f"session-acp-{label}", trace_id=f"trace-acp-{label}",
        dsh_run_id=f"generation-acp-{label}",
    )


def _open_root(store: AgentResearchStore, ctx: dict[str, str], key: str,
               native_root_session_id: str, *, sequence: int = 1) -> tuple[str, dict[str, object]]:
    root = uuid4().hex
    fingerprint = registration_fingerprint(*[
        ctx[f"x-byq-{field}"] for field in (
            "owner-principal", "workspace-id", "actor-principal", "trace-id", "session-id", "dsh-run-id",
        )
    ], key)
    store.consume_runtime_lifecycle_event({
        "schema_version": "agent-run-lifecycle.v1", "root_run_id": root,
        "sequence": sequence, "outcome": "active", "registration_fingerprint": fingerprint,
    }, trusted_owner=ctx["x-byq-owner-principal"],
       trusted_workspace=ctx["x-byq-workspace-id"],
       trusted_session_id=ctx["x-byq-session-id"],
       trusted_trace_id=ctx["x-byq-trace-id"],
       trusted_boot_id=ctx["x-byq-runtime-boot-id"])
    identity = {
        "root_run_id": root, "runtime_boot_id": ctx["x-byq-runtime-boot-id"],
        "native_root_session_id": native_root_session_id,
        "native_agent_session_id": native_root_session_id,
        "native_parent_session_id": None, "origin": "root", "depth": 0,
    }
    payload = {"role_id": "quant_orchestrator", "trace_id": ctx["x-byq-trace-id"],
        "session_id": ctx["x-byq-session-id"], "dsh_run_id": ctx["x-byq-dsh-run-id"],
        "idempotency_key": key}
    run = store.start_run(payload, trusted_owner=ctx["x-byq-owner-principal"],
        trusted_actor=ctx["x-byq-actor-principal"], trusted_workspace=ctx["x-byq-workspace-id"],
        trusted_boot_id=ctx["x-byq-runtime-boot-id"], trusted_root_run_id=root,
        trusted_acp_registration=identity, require_runtime_binding=True)
    return root, {**identity, "agent_run_id": run["run_id"], "parent_run_id": None}


def _bind_payload(identity: dict[str, object]) -> dict[str, object]:
    return {"schema_version": "byq-acp-agent-bind.v1", **identity}


def _scope(ctx: dict[str, str], root: str, *, boot_id: str | None = None) -> dict[str, str]:
    return {"owner": ctx["x-byq-owner-principal"], "workspace": ctx["x-byq-workspace-id"],
        "actor": ctx["x-byq-actor-principal"], "trace": ctx["x-byq-trace-id"],
        "session": ctx["x-byq-session-id"], "generation": ctx["x-byq-dsh-run-id"],
        "boot_id": boot_id or ctx["x-byq-runtime-boot-id"], "root": root}


def _create_task(ctx: dict[str, str], catalog: ConversationCatalogStore,
                 research: ResearchStore, suffix: str) -> dict[str, object]:
    conversation = catalog.create(ctx["x-byq-owner-principal"],
        ctx["x-byq-session-id"], ctx["x-byq-trace-id"])
    return research.create_task({"owner_principal": ctx["x-byq-owner-principal"],
        "title": "ACP proof test", "objective": "Check trusted observation admission",
        "trace_id": ctx["x-byq-trace-id"], "idempotency_key": f"acp-task-{suffix}"},
        trusted_context={"owner_principal": ctx["x-byq-owner-principal"],
            "workspace_id": ctx["x-byq-workspace-id"], "actor_principal": ctx["x-byq-actor-principal"],
            "trace_id": ctx["x-byq-trace-id"], "session_id": ctx["x-byq-session-id"]})


def _child(store: AgentResearchStore, ctx: dict[str, str], root: str,
           parent_native_id: str, key: str, native_id: str | None = None) -> dict[str, object]:
    identity = {"root_run_id": root, "runtime_boot_id": ctx["x-byq-runtime-boot-id"],
        "native_root_session_id": parent_native_id, "native_agent_session_id": native_id or str(uuid4()),
        "native_parent_session_id": parent_native_id, "origin": "subagent", "depth": 1}
    payload = {"role_id": "strategy_researcher", "trace_id": ctx["x-byq-trace-id"],
        "session_id": ctx["x-byq-session-id"], "dsh_run_id": ctx["x-byq-dsh-run-id"],
        "idempotency_key": key}
    run = store.start_run(payload, trusted_owner=ctx["x-byq-owner-principal"],
        trusted_actor=ctx["x-byq-actor-principal"], trusted_workspace=ctx["x-byq-workspace-id"],
        trusted_boot_id=ctx["x-byq-runtime-boot-id"], trusted_root_run_id=root,
        trusted_acp_registration=identity, require_runtime_binding=True)
    return {**identity, "agent_run_id": run["run_id"], "parent_run_id": identity["native_parent_session_id"]}


def _bind(store: AgentResearchStore, ctx: dict[str, str], identity: dict[str, object]) -> dict:
    # Child parent_run_id is a Backend ID, resolved from the native parent binding.
    parent = store._fetch_one("""SELECT agent_run_id FROM agent_acp_native_agent_registrations
        WHERE root_run_id=:root AND native_agent_session_id=:native""",
        {"root": identity["root_run_id"], "native": identity["native_parent_session_id"]}) if identity["origin"] == "subagent" else None
    body = {**identity, "parent_run_id": parent["agent_run_id"] if parent else None}
    return store.bind_acp_agent(_bind_payload(body), trusted_scope=_scope(ctx, identity["root_run_id"]))


def _observe_tool(store: AgentResearchStore, ctx: dict[str, str], identity: dict[str, object],
                  tool_name: str, arguments: dict[str, object], request_id: str | None = None) -> dict:
    body = {"schema_version": "byq-acp-tool-ingress-observe.v1",
        "mcp_request_id": request_id or uuid4().hex,
        **{key: identity[key] for key in ("root_run_id", "runtime_boot_id", "native_root_session_id",
            "native_agent_session_id", "native_parent_session_id", "origin", "depth")},
        "tool_name": tool_name, "arguments": arguments}
    return store.observe_acp_tool_ingress(body, trusted_scope=_scope(ctx, identity["root_run_id"]))


def _settle_tool(store: AgentResearchStore, ctx: dict[str, str], identity: dict[str, object],
                 receipt: dict[str, object], outcome: str = "settled",
                 refusal_receipt: dict[str, object] | None = None) -> dict:
    body = {"schema_version": "byq-acp-tool-ingress-settle.v1",
        "mcp_request_id": receipt["mcp_request_id"], "root_run_id": receipt["root_run_id"],
        "runtime_boot_id": receipt["runtime_boot_id"],
        **{key: identity[key] for key in ("native_root_session_id", "native_agent_session_id",
            "native_parent_session_id", "origin", "depth")},
        "tool_name": receipt["tool_name"], "sequence": receipt["sequence"],
        "event_sha256": receipt["event_sha256"], "outcome": outcome}
    if outcome == "denied":
        body["refusal_receipt"] = refusal_receipt
    return store.settle_acp_tool_ingress(body, trusted_scope=_scope(ctx, identity["root_run_id"]))


def _authorize_tool(store: AgentResearchStore, ctx: dict[str, str], identity: dict[str, object],
                    observed: dict[str, object], arguments: dict[str, object]) -> dict:
    native_identity = {key: identity[key] for key in ("root_run_id", "runtime_boot_id",
        "native_root_session_id", "native_agent_session_id", "native_parent_session_id", "origin", "depth")}
    return store.authorize_acp_agent_tool({"schema_version": "byq-acp-agent-authorize.v1",
        "mcp_request_id": observed["mcp_request_id"], "arguments": arguments},
        trusted_scope=_scope(ctx, identity["root_run_id"]), trusted_identity=native_identity)


def test_acp_role_denial_receipt_is_durable_idempotent_and_terminally_settled():
    ctx = _context("authorize-denial")
    store = AgentResearchStore()
    try:
        authority = store.rotate_runtime_authority(uuid4().hex)
        ctx["x-byq-runtime-boot-id"] = authority["boot_id"]
        root_native = str(uuid4())
        root, root_identity = _open_root(store, ctx, f"acp-root-{uuid4().hex}", root_native)
        _bind(store, ctx, root_identity)
        arguments = {"run_id": root_identity["agent_run_id"],
            "action": "byq_ml_training_create", "resource_type": "training_run",
            "resource_id": "training-never-created"}
        observed = _observe_tool(store, ctx, root_identity, "byq_agent_authorize", arguments)

        with pytest.raises(ValueError, match="reserved ACP control evidence"):
            store.record_audit({"run_id": root_identity["agent_run_id"], "action": "forged",
                "outcome": "denied", "detail": {"nested": {"acp_control": {
                    "mcp_request_id": observed["mcp_request_id"]}}}},
                trusted_owner=ctx["x-byq-owner-principal"], trusted_actor=ctx["x-byq-actor-principal"])
        assert store._fetch_one("SELECT count(*) AS n FROM agent_audit WHERE run_id=:run AND action='forged'",
            {"run": root_identity["agent_run_id"]})["n"] == 0

        result = _authorize_tool(store, ctx, root_identity, observed, arguments)
        assert set(result) == {"status", "authorization", "refusal_receipt"}
        assert result["status"] == "denied"
        assert result["authorization"] == {"authorized": False, "decision": "denied",
            "run_id": root_identity["agent_run_id"], "role_id": "quant_orchestrator",
            "action": "byq_ml_training_create"}
        refusal = result["refusal_receipt"]
        assert set(refusal) == {"schema_version", "mcp_request_id", "root_run_id",
            "runtime_boot_id", "native_agent_session_id", "agent_run_id", "tool_name",
            "arguments_sha256", "event_sha256", "reason", "outcome", "audit_id", "receipt_sha256"}
        assert refusal["schema_version"] == "byq-acp-authorization-denial-receipt.v1"
        assert refusal["mcp_request_id"] == observed["mcp_request_id"]
        assert refusal["root_run_id"] == root
        assert refusal["native_agent_session_id"] == root_native
        assert refusal["agent_run_id"] == root_identity["agent_run_id"]
        assert refusal["tool_name"] == "byq_agent_authorize"
        assert refusal["reason"] == "role_tool_not_allowed" and refusal["outcome"] == "denied"
        assert refusal["receipt_sha256"] == acp_binding_sha256({
            key: value for key, value in refusal.items() if key != "receipt_sha256"})

        audit = store._fetch_one("SELECT * FROM agent_audit WHERE audit_id=:id",
            {"id": refusal["audit_id"]})
        assert audit["run_id"] == root_identity["agent_run_id"]
        assert audit["outcome"] == "denied"
        assert audit["detail_json"]["reason"] == "role_tool_not_allowed"
        assert audit["detail_json"]["acp_control"]["refusal_receipt"] == refusal
        assert _authorize_tool(store, ctx, root_identity, observed, arguments) == result
        assert store._fetch_one("SELECT count(*) AS n FROM agent_audit WHERE detail_json->'acp_control'->>'mcp_request_id'=:id",
            {"id": observed["mcp_request_id"]})["n"] == 1
        assert store._fetch_one("SELECT count(*) AS n FROM agent_approvals")["n"] == 0

        settled = _settle_tool(store, ctx, root_identity, observed, "denied", refusal)
        assert settled["outcome"] == "denied"
        assert settled["refusal_receipt_sha256"] == refusal["receipt_sha256"]
        assert _settle_tool(store, ctx, root_identity, observed, "denied", refusal) == settled
        with pytest.raises(AgentConflict, match="already fixed"):
            _settle_tool(store, ctx, root_identity, observed, "settled")
        ingress = store._fetch_one("SELECT status,settlement_json FROM agent_acp_tool_ingress_observations WHERE mcp_request_id=:id",
            {"id": observed["mcp_request_id"]})
        assert ingress["status"] == "settled"
        assert ingress["settlement_json"] == settled
        assert store._fetch_one("SELECT count(*) AS n FROM agent_domain_call_claims WHERE root_run_id=:root",
            {"root": root})["n"] == 0

        terminal = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": root,
            "sequence": 2, "outcome": "completed"}
        store.consume_runtime_lifecycle_event(terminal,
            trusted_owner=ctx["x-byq-owner-principal"], trusted_workspace=ctx["x-byq-workspace-id"],
            trusted_session_id=ctx["x-byq-session-id"], trusted_trace_id=ctx["x-byq-trace-id"],
            trusted_boot_id=authority["boot_id"])
        root_row = store._fetch_one("SELECT status,terminal_acp_ingress_sequence,terminal_acp_ingress_sha256 FROM agent_runtime_turns WHERE root_run_id=:root",
            {"root": root})
        assert root_row["status"] == "completed"
        assert root_row["terminal_acp_ingress_sequence"] == 1
        assert root_row["terminal_acp_ingress_sha256"] == acp_binding_sha256({
            "schema_version": "byq-acp-root-ingress-cursor.v1", "root_run_id": root,
            "sequence": 1, "events": [{"sequence": 1, "event_sha256": observed["event_sha256"],
                "kind": "tool_ingress", "status": "settled", "outcome": "denied",
                "settlement_sha256": settled["settlement_sha256"]}],
        })
        with pytest.raises(AgentConflict, match="not active under current Backend authority"):
            _authorize_tool(store, ctx, root_identity, observed, arguments)
        store.rotate_runtime_authority(uuid4().hex)
        with pytest.raises(AgentConflict, match="no longer current Backend authority"):
            _authorize_tool(store, ctx, root_identity, observed, arguments)
        assert store._fetch_one("SELECT status,settlement_json->>'outcome' AS outcome FROM agent_acp_tool_ingress_observations WHERE mcp_request_id=:id",
            {"id": observed["mcp_request_id"]}) == {"status": "settled", "outcome": "denied"}
    finally:
        store.close()


def test_acp_lost_denial_settlement_ack_closes_root_child_with_exact_terminal_cursor(monkeypatch):
    """A Backend commit may close after a lost settlement ACK, with exact root/child evidence."""
    from fastapi.testclient import TestClient
    from app import main

    ctx = _context("lost-denial-settlement-ack")
    store = AgentResearchStore()
    monkeypatch.setattr(main, "agent_store", store)
    monkeypatch.setattr(main, "RUNTIME_AUTHORITY_TOKEN", "test-runtime-authority")
    try:
        authority = store.rotate_runtime_authority(uuid4().hex)
        ctx["x-byq-runtime-boot-id"] = authority["boot_id"]
        root_native = str(uuid4())
        root, root_identity = _open_root(store, ctx, f"lost-denial-root-{uuid4().hex}", root_native)
        _bind(store, ctx, root_identity)
        child = _child(store, ctx, root, root_native, f"lost-denial-child-{uuid4().hex}")
        _bind(store, ctx, child)

        ingress_by_agent = []
        for identity in (root_identity, child):
            arguments = {"run_id": identity["agent_run_id"], "action": "byq_ml_training_create",
                "resource_type": "training_run", "resource_id": f"denied-{identity['agent_run_id']}"}
            ingress = _observe_tool(store, ctx, identity, "byq_agent_authorize", arguments)
            authorization = _authorize_tool(store, ctx, identity, ingress, arguments)
            assert authorization["status"] == "denied"
            assert authorization["refusal_receipt"]["agent_run_id"] == identity["agent_run_id"]

            # Model a lost Backend HTTP response by discarding the Store return after its commit.
            # The real MCP lost-response behavior is covered by the earlier bridge evidence in
            # docs/evidence/dsh-acp-single-version/adr0109-20261008/tester-bridge.log and
            # tester-ledger.json; this test does not rerun MCP or claim its local unknown state.
            _settle_tool(store, ctx, identity, ingress, "denied", authorization["refusal_receipt"])
            ingress_by_agent.append((identity, ingress, authorization["refusal_receipt"]))

        persisted = store._execute("""SELECT sequence,event_sha256,agent_run_id,native_agent_session_id,
                status,settlement_json FROM agent_acp_tool_ingress_observations
            WHERE root_run_id=:root ORDER BY sequence""", {"root": root})
        assert len(persisted) == 2
        assert [row["agent_run_id"] for row in persisted] == [
            root_identity["agent_run_id"], child["agent_run_id"]]
        assert [row["native_agent_session_id"] for row in persisted] == [
            root_native, child["native_agent_session_id"]]
        assert all(row["status"] == "settled" for row in persisted)
        for row, (identity, ingress, refusal) in zip(persisted, ingress_by_agent):
            settlement_payload = {"mcp_request_id": ingress["mcp_request_id"], "root_run_id": root,
                "runtime_boot_id": authority["boot_id"],
                "native_agent_session_id": identity["native_agent_session_id"],
                "tool_name": "byq_agent_authorize", "sequence": ingress["sequence"],
                "event_sha256": ingress["event_sha256"], "outcome": "denied",
                "refusal_receipt_sha256": refusal["receipt_sha256"]}
            expected_settlement = {"schema_version": "byq-acp-tool-ingress-settle-receipt.v1",
                **settlement_payload, "settlement_sha256": acp_binding_sha256(settlement_payload)}
            assert row["settlement_json"] == expected_settlement
        assert store._fetch_one("SELECT count(*) AS n FROM agent_domain_call_claims WHERE root_run_id=:root",
            {"root": root})["n"] == 0

        cursor_events = [{"sequence": row["sequence"], "event_sha256": row["event_sha256"],
            "kind": "tool_ingress", "status": row["status"],
            "outcome": row["settlement_json"]["outcome"],
            "settlement_sha256": row["settlement_json"]["settlement_sha256"]} for row in persisted]
        expected_cursor_sha256 = acp_binding_sha256({
            "schema_version": "byq-acp-root-ingress-cursor.v1", "root_run_id": root,
            "sequence": len(persisted), "events": cursor_events})

        client = TestClient(main.app)
        close_body = {"schema_version": "byq-runtime-root-close.v1", "boot_id": authority["boot_id"],
            "sequence": 2, "outcome": "interrupted", "event_sha256": "a" * 64}
        close_headers = {"Authorization": "Bearer test-runtime-authority"}
        close_response = client.post(f"/internal/runtime-authority/roots/{root}/close",
            headers=close_headers, json=close_body)
        assert close_response.status_code == 200, close_response.text
        close_receipt = {"schema_version": "agent-run-lifecycle-receipt.v1", "sequence": 2,
            "root_run_id": root, "event_sha256": "a" * 64}
        assert close_response.json() == {"receipt": close_receipt}
        # Exact terminal retry must return the same ACK, and Backend readback must expose
        # the cursor containing both durable denied settlements.
        assert client.post(f"/internal/runtime-authority/roots/{root}/close",
            headers=close_headers, json=close_body).json() == {"receipt": close_receipt}
        root_row = store._fetch_one("""SELECT status,authority_status,terminal_sequence,
                terminal_event_sha256,terminal_acp_ingress_sequence,terminal_acp_ingress_sha256,
                terminal_unknown_claim_count FROM agent_runtime_turns WHERE root_run_id=:root""",
            {"root": root})
        assert root_row == {"status": "interrupted", "authority_status": "closed",
            "terminal_sequence": 2, "terminal_event_sha256": "a" * 64,
            "terminal_acp_ingress_sequence": 2,
            "terminal_acp_ingress_sha256": expected_cursor_sha256,
            "terminal_unknown_claim_count": 0}
        readback = client.get(f"/internal/runtime-authority/sessions/{ctx['x-byq-session-id']}/roots",
            headers={**close_headers, "x-byq-owner-principal": ctx["x-byq-owner-principal"],
                "x-byq-workspace-id": ctx["x-byq-workspace-id"],
                "x-byq-trace-id": ctx["x-byq-trace-id"]})
        assert readback.status_code == 200, readback.text
        projected = next(item for item in readback.json()["roots"] if item["root_run_id"] == root)
        assert projected["status"] == "interrupted"
        assert projected["terminal_acp_ingress_sequence"] == 2
        assert projected["terminal_acp_ingress_sha256"] == expected_cursor_sha256
        # This is Backend terminal evidence only; adapter process-cleanup proof remains a separate gate.
    finally:
        store.close()


def test_acp_lost_authorization_response_unknown_still_fences_close_and_new_root(monkeypatch):
    """An unknown authorization response stays immutable and blocks the Workspace slot."""
    from fastapi.testclient import TestClient
    from app import main

    ctx = _context("lost-denial-authorization-response")
    store = AgentResearchStore()
    main_token = "test-runtime-authority-unknown"
    try:
        authority = store.rotate_runtime_authority(uuid4().hex)
        ctx["x-byq-runtime-boot-id"] = authority["boot_id"]
        root_native = str(uuid4())
        root, identity = _open_root(store, ctx, f"lost-auth-root-{uuid4().hex}", root_native)
        _bind(store, ctx, identity)
        arguments = {"run_id": identity["agent_run_id"], "action": "byq_ml_training_create",
            "resource_type": "training_run", "resource_id": "lost-authorization-response"}
        ingress = _observe_tool(store, ctx, identity, "byq_agent_authorize", arguments)

        # Model the previously observed bridge case: Backend commits the denial audit,
        # but the authorization HTTP response is lost before MCP can settle it as denied.
        # See tester-bridge.log; this Store-only test does not rerun MCP.
        _authorize_tool(store, ctx, identity, ingress, arguments)
        unknown = _settle_tool(store, ctx, identity, ingress, "unknown")
        assert unknown["outcome"] == "unknown"
        stored_before = store._fetch_one("""SELECT status,settlement_json FROM agent_acp_tool_ingress_observations
            WHERE mcp_request_id=:id""", {"id": ingress["mcp_request_id"]})
        assert stored_before == {"status": "unknown", "settlement_json": unknown}
        with pytest.raises(AgentConflict, match="unknown ACP tool ingress cannot receive authorization proof"):
            _authorize_tool(store, ctx, identity, ingress, arguments)
        with pytest.raises(AgentConflict, match="unknown ACP tool ingress cannot be rewritten"):
            _settle_tool(store, ctx, identity, ingress, "denied", {})

        monkeypatch.setattr(main, "agent_store", store)
        monkeypatch.setattr(main, "RUNTIME_AUTHORITY_TOKEN", main_token)
        close_response = TestClient(main.app).post(
            f"/internal/runtime-authority/roots/{root}/close",
            headers={"Authorization": f"Bearer {main_token}"},
            json={"schema_version": "byq-runtime-root-close.v1", "boot_id": authority["boot_id"],
                "sequence": 2, "outcome": "interrupted", "event_sha256": "b" * 64})
        assert close_response.status_code == 409
        assert close_response.json() == {"detail": "pending or unknown ACP tool ingress prevents root close"}
        admission = store.workspace_agent_admission(
            owner_principal=ctx["x-byq-owner-principal"], workspace_id=ctx["x-byq-workspace-id"],
            root_run_id=uuid4().hex, session_id=ctx["x-byq-session-id"], boot_id=authority["boot_id"])
        assert admission["can_start"] is False
        stored_after = store._fetch_one("""SELECT status,settlement_json FROM agent_acp_tool_ingress_observations
            WHERE mcp_request_id=:id""", {"id": ingress["mcp_request_id"]})
        assert stored_after == stored_before
        assert store._fetch_one("SELECT status FROM agent_runtime_turns WHERE root_run_id=:root",
            {"root": root})["status"] == "active"
    finally:
        store.close()


def test_acp_authorization_refuses_sibling_changed_input_and_unknown_ingress():
    ctx = _context("authorize-isolation")
    store = AgentResearchStore()
    try:
        authority = store.rotate_runtime_authority(uuid4().hex)
        ctx["x-byq-runtime-boot-id"] = authority["boot_id"]
        root_native = str(uuid4())
        root, root_identity = _open_root(store, ctx, f"acp-root-{uuid4().hex}", root_native)
        _bind(store, ctx, root_identity)
        child_a = _child(store, ctx, root, root_native, f"acp-child-{uuid4().hex}")
        _bind(store, ctx, child_a)
        child_b = _child(store, ctx, root, root_native, f"acp-child-{uuid4().hex}")
        _bind(store, ctx, child_b)
        arguments = {"run_id": child_a["agent_run_id"], "action": "byq_strategy_approve",
            "resource_type": "strategy_version", "resource_id": "strategy-never-approved"}
        observed = _observe_tool(store, ctx, child_a, "byq_agent_authorize", arguments)

        with pytest.raises(AgentConflict, match="exact observed request identity or input"):
            _authorize_tool(store, ctx, child_b, observed, arguments)
        changed = {**arguments, "resource_id": "changed-input"}
        with pytest.raises(AgentConflict, match="exact observed request identity or input"):
            _authorize_tool(store, ctx, child_a, observed, changed)
        mismatched_run_arguments = {**arguments, "run_id": child_b["agent_run_id"]}
        mismatched_run = _observe_tool(store, ctx, child_a,
            "byq_agent_authorize", mismatched_run_arguments)
        with pytest.raises(AgentConflict, match="run_id does not match native AgentRun"):
            _authorize_tool(store, ctx, child_a, mismatched_run, mismatched_run_arguments)
        assert store._fetch_one("SELECT count(*) AS n FROM agent_audit WHERE detail_json->'acp_control'->>'mcp_request_id'=:id",
            {"id": observed["mcp_request_id"]})["n"] == 0
        assert store._fetch_one("SELECT count(*) AS n FROM agent_audit WHERE detail_json->'acp_control'->>'mcp_request_id'=:id",
            {"id": mismatched_run["mcp_request_id"]})["n"] == 0

        unknown_arguments = {"run_id": root_identity["agent_run_id"],
            "action": "byq_ml_training_create", "resource_type": "training_run",
            "resource_id": "unknown-result"}
        unknown = _observe_tool(store, ctx, root_identity, "byq_agent_authorize", unknown_arguments)
        _settle_tool(store, ctx, root_identity, unknown, "unknown")
        with pytest.raises(AgentConflict, match="unknown ACP tool ingress cannot receive authorization proof"):
            _authorize_tool(store, ctx, root_identity, unknown, unknown_arguments)
        with pytest.raises(AgentConflict, match="unknown ACP tool ingress cannot be rewritten"):
            _settle_tool(store, ctx, root_identity, unknown, "denied", {})
        assert store._fetch_one("SELECT status,settlement_json->>'outcome' AS outcome FROM agent_acp_tool_ingress_observations WHERE mcp_request_id=:id",
            {"id": unknown["mcp_request_id"]}) == {"status": "unknown", "outcome": "unknown"}
        assert store._fetch_one("SELECT count(*) AS n FROM agent_audit WHERE detail_json->'acp_control'->>'mcp_request_id'=:id",
            {"id": unknown["mcp_request_id"]})["n"] == 0
    finally:
        store.close()


def test_acp_authorize_private_endpoint_requires_trusted_native_identity(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    monkeypatch.setattr(main, "MCP_BACKEND_PROOF_TOKEN", "test-acp-backend-proof")
    store = main.agent_store
    ctx = _context("authorize-private-api")
    authority = store.rotate_runtime_authority(uuid4().hex)
    ctx["x-byq-runtime-boot-id"] = authority["boot_id"]
    root_native = str(uuid4())
    root, identity = _open_root(store, ctx, f"acp-root-{uuid4().hex}", root_native)
    _bind(store, ctx, identity)
    arguments = {"run_id": identity["agent_run_id"], "action": "byq_ml_training_create",
        "resource_type": "training_run", "resource_id": "endpoint-denial"}
    observed = _observe_tool(store, ctx, identity, "byq_agent_authorize", arguments)
    payload = {"schema_version": "byq-acp-agent-authorize.v1",
        "mcp_request_id": observed["mcp_request_id"], "arguments": arguments}
    headers = {**ctx, "Authorization": "Bearer test-acp-backend-proof",
        "x-byq-root-run-id": root,
        "x-byq-acp-native-root-session-id": root_native,
        "x-byq-acp-native-agent-session-id": root_native,
        "x-byq-acp-native-parent-session-id": "",
        "x-byq-acp-origin": "root", "x-byq-acp-depth": "0"}
    client = TestClient(main.app)
    missing = dict(headers)
    missing.pop("x-byq-acp-depth")
    assert client.post("/internal/acp/agent-authorize", headers=missing, json=payload).status_code == 401
    response = client.post("/internal/acp/agent-authorize", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "denied"
    assert response.json()["refusal_receipt"]["root_run_id"] == root
    assert response.json()["refusal_receipt"]["native_agent_session_id"] == root_native

    policy_arguments = {"run_id": identity["agent_run_id"], "action": "byq_factor_compute",
        "resource_type": "factor", "resource_id": "policy-denied-factor"}
    policy_ingress = _observe_tool(store, ctx, identity, "byq_agent_authorize", policy_arguments)
    policy_payload = {"schema_version": "byq-acp-agent-authorize.v1",
        "mcp_request_id": policy_ingress["mcp_request_id"], "arguments": policy_arguments}
    monkeypatch.setattr(main.user_policy_store, "evaluate_authorization", lambda _owner, authorization: {
        **authorization, "authorized": False, "decision": "policy_denied", "policy_rule_id": "test-rule"})
    policy_response = client.post("/internal/acp/agent-authorize", headers=headers, json=policy_payload)
    assert policy_response.status_code == 403
    assert policy_response.json() == {"detail": "authorization denied by user policy"}
    ingress_row = store._fetch_one("SELECT status,settlement_json FROM agent_acp_tool_ingress_observations WHERE mcp_request_id=:id",
        {"id": policy_ingress["mcp_request_id"]})
    assert ingress_row == {"status": "pending", "settlement_json": None}
    policy_audit = store._fetch_one("SELECT outcome,detail_json FROM agent_audit WHERE run_id=:run AND action='policy.enforce' ORDER BY created_at DESC LIMIT 1",
        {"run": identity["agent_run_id"]})
    assert policy_audit == {"outcome": "denied", "detail_json": {
        "domain_action": "byq_factor_compute", "policy_rule_id": "test-rule"}}
    # The public Product endpoint retains its existing 403 contract and has no ACP receipt.
    public = client.post("/v1/agents/authorize", headers=ctx, json=arguments)
    assert public.status_code == 403


def _abort_tool(store: AgentResearchStore, ctx: dict[str, str], identity: dict[str, object],
                tool_name: str, arguments: dict[str, object], request_id: str | None = None,
                *, scope: dict[str, str] | None = None) -> dict:
    body = {"schema_version": "byq-acp-tool-ingress-abort.v1",
        "mcp_request_id": request_id or uuid4().hex,
        **{key: identity[key] for key in ("root_run_id", "runtime_boot_id", "native_root_session_id",
            "native_agent_session_id", "native_parent_session_id", "origin", "depth")},
        "tool_name": tool_name, "arguments": arguments}
    return store.abort_acp_tool_ingress_before_dispatch(body,
        trusted_scope=scope or _scope(ctx, identity["root_run_id"]))


def test_acp_native_binding_requires_exact_observation_before_unknown_safe_claim():
    ctx = _context("proof")
    catalog, research, store = ConversationCatalogStore(), ResearchStore(), AgentResearchStore()
    try:
        boot = store.rotate_runtime_authority(uuid4().hex)
        ctx["x-byq-runtime-boot-id"] = boot["boot_id"]
        root_native = str(uuid4())
        root, root_identity = _open_root(store, ctx, f"acp-root-{uuid4().hex}", root_native)
        prebind_bootstrap = _observe_tool(store, ctx, root_identity,
            "byq_agent_context", {"bootstrap_secret": "DO_NOT_PERSIST_GENERIC_ARGS"})
        assert prebind_bootstrap["agent_run_id"] is None
        root_receipt = _bind(store, ctx, root_identity)
        assert set(root_receipt) == {"schema_version", "root_run_id", "runtime_boot_id",
            "native_agent_session_id", "native_parent_session_id", "agent_run_id", "parent_run_id",
            "origin", "depth", "status", "binding_sha256"}
        assert root_receipt["native_agent_session_id"] == root_native
        assert re.fullmatch(r"[0-9a-f]{64}", root_receipt["binding_sha256"])
        assert _bind(store, ctx, root_identity) == root_receipt

        bootstrap = _observe_tool(store, ctx, root_identity, "byq_agent_context", {"query": "bootstrap"})
        assert bootstrap["agent_run_id"] == root_identity["agent_run_id"]
        assert bootstrap["native_root_session_id"] == root_native
        assert bootstrap["sequence"] == 2

        child = _child(store, ctx, root, root_native, f"acp-child-{uuid4().hex}")
        wrong_parent = _bind_payload({**child, "native_parent_session_id": str(uuid4()),
            "parent_run_id": root_identity["agent_run_id"]})
        with pytest.raises(AgentConflict):
            store.bind_acp_agent(wrong_parent, trusted_scope=_scope(ctx, root))
        child_receipt = _bind(store, ctx, child)
        assert child_receipt["parent_run_id"] == root_identity["agent_run_id"]
        child_ingress = _observe_tool(store, ctx, child, "byq_strategy_validate",
            {"agent_run_id": child["agent_run_id"], "task_id": "task_placeholder", "strategy": {}})
        assert child_ingress["agent_run_id"] == child["agent_run_id"]
        assert child_ingress["sequence"] == 3
        assert _observe_tool(store, ctx, child, "byq_strategy_validate",
            {"agent_run_id": child["agent_run_id"], "task_id": "task_placeholder", "strategy": {}},
            child_ingress["mcp_request_id"]) == child_ingress
        with pytest.raises(AgentConflict, match="request id was reused"):
            _observe_tool(store, ctx, child, "byq_strategy_validate",
                {"agent_run_id": child["agent_run_id"], "task_id": "task_placeholder", "strategy": {"changed": True}},
                child_ingress["mcp_request_id"])
        with pytest.raises(AgentForbidden, match="role is not authorized"):
            _observe_tool(store, ctx, child, "byq_ml_training_create", {"payload": "not persisted"})
        for identity, observed in ((root_identity, prebind_bootstrap), (root_identity, bootstrap),
                                   (child, child_ingress)):
            settled = _settle_tool(store, ctx, identity, observed)
            assert settled["outcome"] == "settled"
            assert _settle_tool(store, ctx, identity, observed) == settled
            with pytest.raises(AgentConflict, match="outcome is already fixed"):
                _settle_tool(store, ctx, identity, observed, "unknown")
        status = store.get_acp_agent_binding(root_run_id=root,
            native_agent_session_id=child["native_agent_session_id"], trusted_scope=_scope(ctx, root))
        assert status == {"schema_version": "byq-acp-agent-binding-status.v1", "root_run_id": root,
            "runtime_boot_id": ctx["x-byq-runtime-boot-id"],
            "native_agent_session_id": child["native_agent_session_id"],
            "status": "bound", "receipt": child_receipt}

        task = _create_task(ctx, catalog, research, "proof")
        args = {"task_id": task["task_id"], "agent_run_id": child["agent_run_id"],
            "idempotency_key": "acp-domain-call-proof", "strategy": {"code": "DO_NOT_PERSIST_RAW_ARGS"}}
        observation = {"schema_version": "byq-acp-domain-call-observe.v1",
            "mcp_request_id": uuid4().hex, "root_run_id": root,
            "runtime_boot_id": ctx["x-byq-runtime-boot-id"],
            "native_agent_session_id": child["native_agent_session_id"],
            "action": "byq_strategy_validate", "arguments": args}
        with pytest.raises(AgentConflict, match="requires its exact Backend observation"):
            store.claim_domain_call("byq_strategy_validate", args,
                trusted_owner=ctx["x-byq-owner-principal"], trusted_workspace=ctx["x-byq-workspace-id"],
                trusted_session_id=ctx["x-byq-session-id"], trusted_trace_id=ctx["x-byq-trace-id"],
                trusted_generation=ctx["x-byq-dsh-run-id"], trusted_root=root,
                trusted_boot_id=ctx["x-byq-runtime-boot-id"])

        receipt = store.observe_acp_domain_call(observation, trusted_scope=_scope(ctx, root))
        assert set(receipt) == {"schema_version", "mcp_request_id", "root_run_id", "sequence", "event_sha256"}
        assert receipt["schema_version"] == "byq-acp-domain-call-observation-receipt.v1"
        assert receipt["sequence"] == 4 and re.fullmatch(r"[0-9a-f]{64}", receipt["event_sha256"])
        assert store.observe_acp_domain_call(observation, trusted_scope=_scope(ctx, root)) == receipt
        with pytest.raises(AgentConflict, match="request id was reused"):
            store.observe_acp_domain_call({**observation, "arguments": {**args,
                "strategy": {"code": "CHANGED_INPUT"}}}, trusted_scope=_scope(ctx, root))

        claim_kwargs = {"trusted_owner": ctx["x-byq-owner-principal"],
            "trusted_workspace": ctx["x-byq-workspace-id"], "trusted_session_id": ctx["x-byq-session-id"],
            "trusted_trace_id": ctx["x-byq-trace-id"], "trusted_generation": ctx["x-byq-dsh-run-id"],
            "trusted_root": root, "trusted_boot_id": ctx["x-byq-runtime-boot-id"]}
        claim = store.claim_domain_call("byq_strategy_validate", args, **claim_kwargs,
                                        trusted_acp_observation_id=receipt["mcp_request_id"])
        assert claim["state"] == "claimed"
        with store._transaction() as connection:
            from app.db import execute
            execute(connection, "UPDATE agent_domain_call_claims SET status='executing' WHERE claim_id=:id",
                    {"id": claim["claim_id"]})
        assert store.claim_domain_call("byq_strategy_validate", args, **claim_kwargs,
            trusted_acp_observation_id=receipt["mcp_request_id"]) == {"state": "unknown"}
        evidence = store._fetch_one("""SELECT evidence_json::text AS evidence_json
            FROM agent_domain_call_evidence WHERE root_run_id=:root""", {"root": root})
        assert "DO_NOT_PERSIST_RAW_ARGS" not in evidence["evidence_json"]
        stored_ingress = store._fetch_one("""SELECT arguments_sha256,receipt_json::text AS receipt_json
            FROM agent_acp_tool_ingress_observations WHERE root_run_id=:root
              AND mcp_request_id=:request_id""", {"root": root,
            "request_id": prebind_bootstrap["mcp_request_id"]})
        assert re.fullmatch(r"[0-9a-f]{64}", stored_ingress["arguments_sha256"])
        assert "DO_NOT_PERSIST_GENERIC_ARGS" not in stored_ingress["receipt_json"]

        foreign = trusted_agent_context("acp-foreign")
        with pytest.raises(AgentNotFound):
            store.get_acp_domain_call_observation(mcp_request_id=receipt["mcp_request_id"],
                trusted_scope={**_scope(ctx, root), "owner": foreign["x-byq-owner-principal"],
                    "workspace": foreign["x-byq-workspace-id"]})
        with pytest.raises(AgentConflict, match="unresolved ACP domain call claim"):
            store.close_runtime_root(root, boot_id=ctx["x-byq-runtime-boot-id"], sequence=2,
                outcome="interrupted", event_sha256="a" * 64)
    finally:
        store.close()
        catalog.close()
        research.close()


def test_acp_pending_registration_marker_is_atomic_under_competing_child_start_and_blocks_transfer():
    ctx = _context("race")
    first, second = AgentResearchStore(), AgentResearchStore()
    try:
        boot = first.rotate_runtime_authority(uuid4().hex)
        ctx["x-byq-runtime-boot-id"] = boot["boot_id"]
        root_native = str(uuid4())
        root, root_identity = _open_root(first, ctx, f"acp-root-{uuid4().hex}", root_native)
        _bind(first, ctx, root_identity)
        child_ids = [str(uuid4()), str(uuid4())]
        barrier = Barrier(2)

        def register(store: AgentResearchStore, native_id: str):
            barrier.wait()
            return _child(store, ctx, root, root_native, "same-child-idempotency", native_id)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(register, first, child_ids[0]), pool.submit(register, second, child_ids[1])]
            outcomes = []
            for future in futures:
                try:
                    outcomes.append(future.result())
                except AgentConflict:
                    outcomes.append(None)
        winners = [value for value in outcomes if value is not None]
        assert len(winners) == 1
        pending = first._fetch_one("""SELECT status,agent_run_id FROM agent_acp_native_agent_registrations
            WHERE root_run_id=:root AND origin='subagent'""", {"root": root})
        assert pending["status"] == "pending" and pending["agent_run_id"] == winners[0]["agent_run_id"]
        with pytest.raises(AgentConflict, match="pending ACP native registration"):
            first.close_runtime_root(root, boot_id=ctx["x-byq-runtime-boot-id"], sequence=2,
                outcome="interrupted", event_sha256="c" * 64)
        with pytest.raises(AgentConflict, match="requires its exact Backend observation"):
            first.claim_domain_call("byq_strategy_validate", {"task_id": "researchtask_" + "1" * 32,
                "agent_run_id": winners[0]["agent_run_id"], "idempotency_key": "pending-call",
                "strategy": {"code": "x"}}, trusted_owner=ctx["x-byq-owner-principal"],
                trusted_workspace=ctx["x-byq-workspace-id"], trusted_session_id=ctx["x-byq-session-id"],
                trusted_trace_id=ctx["x-byq-trace-id"], trusted_generation=ctx["x-byq-dsh-run-id"],
                trusted_root=root, trusted_boot_id=ctx["x-byq-runtime-boot-id"])
        new_authority = first.rotate_runtime_authority(uuid4().hex)
        with pytest.raises(AgentConflict, match="pending or mismatched ACP native registration"):
            first.transfer_runtime_root_authority(root,
                previous_boot_id=boot["boot_id"], previous_authority_epoch=boot["authority_epoch"],
                boot_id=new_authority["boot_id"], authority_epoch=new_authority["authority_epoch"],
                owner_principal=ctx["x-byq-owner-principal"], workspace_id=ctx["x-byq-workspace-id"],
                session_id=ctx["x-byq-session-id"], trace_id=ctx["x-byq-trace-id"])
    finally:
        second.close()
        first.close()


def test_acp_same_root_transfer_rebinds_native_identity_but_preserves_unknown_claim():
    ctx = _context("transfer")
    catalog, research, store = ConversationCatalogStore(), ResearchStore(), AgentResearchStore()
    try:
        old_authority = store.rotate_runtime_authority(uuid4().hex)
        ctx["x-byq-runtime-boot-id"] = old_authority["boot_id"]
        root_native = str(uuid4())
        root, root_identity = _open_root(store, ctx, f"acp-root-{uuid4().hex}", root_native)
        _bind(store, ctx, root_identity)
        child = _child(store, ctx, root, root_native, f"acp-child-{uuid4().hex}")
        old_binding_receipt = _bind(store, ctx, child)
        task = _create_task(ctx, catalog, research, "transfer")
        args = {"task_id": task["task_id"], "agent_run_id": child["agent_run_id"],
            "idempotency_key": "transfer-call", "strategy": {"code": "UNKNOWN_BUSINESS_RESULT"}}
        old_observation = {"schema_version": "byq-acp-domain-call-observe.v1",
            "mcp_request_id": uuid4().hex, "root_run_id": root,
            "runtime_boot_id": old_authority["boot_id"],
            "native_agent_session_id": child["native_agent_session_id"],
            "action": "byq_strategy_validate", "arguments": args}
        old_receipt = store.observe_acp_domain_call(old_observation, trusted_scope=_scope(ctx, root))
        claim_kwargs = {"trusted_owner": ctx["x-byq-owner-principal"],
            "trusted_workspace": ctx["x-byq-workspace-id"], "trusted_session_id": ctx["x-byq-session-id"],
            "trusted_trace_id": ctx["x-byq-trace-id"], "trusted_generation": ctx["x-byq-dsh-run-id"],
            "trusted_root": root, "trusted_boot_id": old_authority["boot_id"]}
        claim = store.claim_domain_call("byq_strategy_validate", args, **claim_kwargs,
            trusted_acp_observation_id=old_receipt["mcp_request_id"])
        assert claim["state"] == "claimed"
        with store._transaction() as connection:
            from app.db import execute
            execute(connection, "UPDATE agent_domain_call_claims SET status='executing' WHERE claim_id=:id",
                    {"id": claim["claim_id"]})

        new_authority = store.rotate_runtime_authority(uuid4().hex)
        transfer = store.transfer_runtime_root_authority(root,
            previous_boot_id=old_authority["boot_id"],
            previous_authority_epoch=old_authority["authority_epoch"],
            boot_id=new_authority["boot_id"], authority_epoch=new_authority["authority_epoch"],
            owner_principal=ctx["x-byq-owner-principal"], workspace_id=ctx["x-byq-workspace-id"],
            session_id=ctx["x-byq-session-id"], trace_id=ctx["x-byq-trace-id"])
        assert transfer["status"] == "transferred"
        ctx["x-byq-runtime-boot-id"] = new_authority["boot_id"]
        new_scope = _scope(ctx, root)
        new_binding = store.get_acp_agent_binding(root_run_id=root,
            native_agent_session_id=child["native_agent_session_id"], trusted_scope=new_scope)
        assert new_binding["status"] == "bound"
        assert new_binding["receipt"]["runtime_boot_id"] == new_authority["boot_id"]
        assert new_binding["receipt"]["binding_sha256"] != old_binding_receipt["binding_sha256"]
        assert new_binding["receipt"] == _bind(store, ctx,
            {**child, "runtime_boot_id": new_authority["boot_id"],
             "parent_run_id": root_identity["agent_run_id"]})

        with pytest.raises(AgentConflict, match="no longer current Backend authority"):
            store.observe_acp_domain_call(old_observation,
                trusted_scope=_scope(ctx, root, boot_id=old_authority["boot_id"]))
        new_identity = {**root_identity, "runtime_boot_id": new_authority["boot_id"]}
        new_ingress = _observe_tool(store, ctx, new_identity, "byq_agent_context", {"recovery": True})
        assert new_ingress["agent_run_id"] == root_identity["agent_run_id"]
        assert new_ingress["runtime_boot_id"] == new_authority["boot_id"]

        new_observation = {**old_observation, "mcp_request_id": uuid4().hex,
            "runtime_boot_id": new_authority["boot_id"]}
        new_receipt = store.observe_acp_domain_call(new_observation, trusted_scope=new_scope)
        new_claim_kwargs = {**claim_kwargs, "trusted_boot_id": new_authority["boot_id"]}
        assert store.claim_domain_call("byq_strategy_validate", args, **new_claim_kwargs,
            trusted_acp_observation_id=new_receipt["mcp_request_id"]) == {"state": "unknown"}
        unknown_count = store._fetch_one("""SELECT count(*) AS count FROM agent_domain_call_claims
            WHERE root_run_id=:root AND task_id=:task AND action='byq_strategy_validate'
              AND idempotency_key='transfer-call' AND status='executing'""",
            {"root": root, "task": task["task_id"]})
        assert unknown_count["count"] == 1
    except AgentConflict as error:
        # The transfer path itself returns a persisted receipt; this catch is
        # intentionally not used for expected safety outcomes in this test.
        raise AssertionError(f"unexpected ACP transfer conflict: {error}") from error
    finally:
        store.close()
        catalog.close()
        research.close()


def test_acp_transfer_rejects_pending_or_unknown_tool_dispatch():
    ctx = _context("transfer-ingress-fence")
    unknown_ctx = _context("transfer-ingress-fence-unknown")
    store = AgentResearchStore()
    try:
        previous = store.rotate_runtime_authority(uuid4().hex)
        ctx["x-byq-runtime-boot-id"] = previous["boot_id"]
        root_native = str(uuid4())
        root, identity = _open_root(store, ctx, f"acp-root-{uuid4().hex}", root_native)
        _bind(store, ctx, identity)
        observed = _observe_tool(store, ctx, identity, "byq_feedback_create_draft", {"title": "held write"})
        unknown_ctx["x-byq-runtime-boot-id"] = previous["boot_id"]
        unknown_native = str(uuid4())
        unknown_root, unknown_identity = _open_root(store, unknown_ctx, f"acp-root-{uuid4().hex}", unknown_native)
        _bind(store, unknown_ctx, unknown_identity)
        unknown = _observe_tool(store, unknown_ctx, unknown_identity, "byq_feedback_create_draft",
            {"title": "unknown write"})
        assert _settle_tool(store, unknown_ctx, unknown_identity, unknown, "unknown")["outcome"] == "unknown"
        with pytest.raises(AgentConflict, match="already settled or unknown"):
            _abort_tool(store, unknown_ctx, unknown_identity, "byq_feedback_create_draft",
                {"title": "unknown write"}, unknown["mcp_request_id"])
        current = store.rotate_runtime_authority(uuid4().hex)
        with pytest.raises(AgentConflict, match="pending or unknown ACP tool ingress"):
            store.transfer_runtime_root_authority(root,
                previous_boot_id=previous["boot_id"], previous_authority_epoch=previous["authority_epoch"],
                boot_id=current["boot_id"], authority_epoch=current["authority_epoch"],
                owner_principal=ctx["x-byq-owner-principal"], workspace_id=ctx["x-byq-workspace-id"],
                session_id=ctx["x-byq-session-id"], trace_id=ctx["x-byq-trace-id"])
        with pytest.raises(AgentConflict, match="pending or unknown ACP tool ingress"):
            store.transfer_runtime_root_authority(unknown_root,
                previous_boot_id=previous["boot_id"], previous_authority_epoch=previous["authority_epoch"],
                boot_id=current["boot_id"], authority_epoch=current["authority_epoch"],
                owner_principal=unknown_ctx["x-byq-owner-principal"], workspace_id=unknown_ctx["x-byq-workspace-id"],
                session_id=unknown_ctx["x-byq-session-id"], trace_id=unknown_ctx["x-byq-trace-id"])
        with pytest.raises(AgentConflict, match="no longer current Backend authority"):
            _observe_tool(store, ctx, identity, "byq_feedback_create_draft", {"title": "late new dispatch"})
        status = store._fetch_one("""SELECT status,authority_status,authority_boot_id
            FROM agent_runtime_turns WHERE root_run_id=:root""", {"root": root})
        assert status == {"status": "active", "authority_status": "authority_revoked_unconfirmed",
            "authority_boot_id": previous["boot_id"]}
        assert store._fetch_one("""SELECT status FROM agent_acp_tool_ingress_observations
            WHERE mcp_request_id=:id""", {"id": observed["mcp_request_id"]})["status"] == "pending"
    finally:
        store.close()


def test_acp_close_fences_pending_and_unknown_ingress_then_freezes_settled_cursor():
    ctx = _context("close-fence")
    store = AgentResearchStore()
    try:
        authority = store.rotate_runtime_authority(uuid4().hex)
        ctx["x-byq-runtime-boot-id"] = authority["boot_id"]
        root_native = str(uuid4())
        root, identity = _open_root(store, ctx, f"acp-root-{uuid4().hex}", root_native)
        _bind(store, ctx, identity)
        ingress = _observe_tool(store, ctx, identity, "byq_feedback_create_draft", {"title": "held write"})

        with pytest.raises(AgentConflict, match="pending or unknown ACP tool ingress"):
            store.close_runtime_root(root, boot_id=authority["boot_id"], sequence=2,
                outcome="interrupted", event_sha256="b" * 64)
        event = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": root,
            "sequence": 2, "outcome": "interrupted"}
        with pytest.raises(AgentConflict, match="pending or unknown ACP tool ingress"):
            store.consume_runtime_lifecycle_event(event,
                trusted_owner=ctx["x-byq-owner-principal"],
                trusted_workspace=ctx["x-byq-workspace-id"],
                trusted_session_id=ctx["x-byq-session-id"],
                trusted_trace_id=ctx["x-byq-trace-id"],
                trusted_boot_id=authority["boot_id"])
        assert store._fetch_one("SELECT status FROM agent_runtime_turns WHERE root_run_id=:root",
            {"root": root})["status"] == "active"

        unknown = _settle_tool(store, ctx, identity, ingress, "unknown")
        assert unknown["outcome"] == "unknown"
        with pytest.raises(AgentConflict, match="pending or unknown ACP tool ingress"):
            store.close_runtime_root(root, boot_id=authority["boot_id"], sequence=2,
                outcome="interrupted", event_sha256="b" * 64)
        with pytest.raises(AgentConflict, match="pending or unknown ACP tool ingress"):
            store.consume_runtime_lifecycle_event(event,
                trusted_owner=ctx["x-byq-owner-principal"],
                trusted_workspace=ctx["x-byq-workspace-id"],
                trusted_session_id=ctx["x-byq-session-id"],
                trusted_trace_id=ctx["x-byq-trace-id"],
                trusted_boot_id=authority["boot_id"])

    finally:
        store.close()


def test_acp_close_projection_freezes_zero_cursor_for_new_root_and_lifecycle_terminal_path():
    ctx = _context("terminal-projection")
    store = AgentResearchStore()
    try:
        authority = store.rotate_runtime_authority(uuid4().hex)
        ctx["x-byq-runtime-boot-id"] = authority["boot_id"]
        root_native = str(uuid4())
        root, identity = _open_root(store, ctx, f"acp-root-{uuid4().hex}", root_native)
        _bind(store, ctx, identity)
        event = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": root,
            "sequence": 2, "outcome": "interrupted"}
        store.consume_runtime_lifecycle_event(event,
            trusted_owner=ctx["x-byq-owner-principal"],
            trusted_workspace=ctx["x-byq-workspace-id"],
            trusted_session_id=ctx["x-byq-session-id"],
            trusted_trace_id=ctx["x-byq-trace-id"],
            trusted_boot_id=authority["boot_id"])
        projection = store.runtime_roots_for_scope(owner_principal=ctx["x-byq-owner-principal"],
            workspace_id=ctx["x-byq-workspace-id"], session_id=ctx["x-byq-session-id"],
            trace_id=ctx["x-byq-trace-id"])
        row = next(row for row in projection["roots"] if row["root_run_id"] == root)
        assert row["terminal_acp_ingress_sequence"] == 0
        assert re.fullmatch(r"[0-9a-f]{64}", row["terminal_acp_ingress_sha256"])
        assert row["terminal_unknown_claim_count"] == 0
        assert re.fullmatch(r"[0-9a-f]{64}", row["terminal_unknown_claims_sha256"])
        assert row["terminal_sequence"] == 2
        with pytest.raises(AgentConflict, match="not active under current Backend authority"):
            _observe_tool(store, ctx, identity, "byq_feedback_create_draft", {"title": "after terminal"})
    finally:
        store.close()


def test_completed_roots_rebind_one_native_session_without_admitting_late_old_calls():
    """The native ID may persist; business and child identities remain root-scoped."""
    first = _context("native-reuse")
    store = AgentResearchStore()
    try:
        authority = store.rotate_runtime_authority(uuid4().hex)
        first["x-byq-runtime-boot-id"] = authority["boot_id"]
        native = str(uuid4())
        old_root, old_agent = _open_root(store, first, f"reuse-old-{uuid4().hex}", native)
        _bind(store, first, old_agent)
        old_child = _child(store, first, old_root, native, f"reuse-child-old-{uuid4().hex}")
        _bind(store, first, old_child)
        old_call = _observe_tool(store, first, old_child, "byq_strategy_validate",
            {"agent_run_id": old_child["agent_run_id"], "task_id": "old-task", "strategy": {}})
        _settle_tool(store, first, old_child, old_call)
        closed = store.consume_runtime_lifecycle_event({
            "schema_version": "agent-run-lifecycle.v1", "root_run_id": old_root,
            "sequence": 2, "outcome": "completed",
        }, trusted_owner=first["x-byq-owner-principal"],
           trusted_workspace=first["x-byq-workspace-id"],
           trusted_session_id=first["x-byq-session-id"],
           trusted_trace_id=first["x-byq-trace-id"],
           trusted_boot_id=authority["boot_id"])
        assert closed["root_run_id"] == old_root

        second = {**first, "x-byq-dsh-run-id": f"generation-acp-native-reuse-{uuid4().hex}"}
        new_root, new_agent = _open_root(store, second, f"reuse-new-{uuid4().hex}", native,
            sequence=3)
        _bind(store, second, new_agent)
        assert new_root != old_root
        assert new_agent["agent_run_id"] != old_agent["agent_run_id"]
        assert new_agent["native_agent_session_id"] == old_agent["native_agent_session_id"] == native
        new_child = _child(store, second, new_root, native, f"reuse-child-new-{uuid4().hex}")
        child_receipt = _bind(store, second, new_child)
        assert child_receipt["parent_run_id"] == new_agent["agent_run_id"]
        new_call = _observe_tool(store, second, new_child, "byq_strategy_validate",
            {"agent_run_id": new_child["agent_run_id"], "task_id": "new-task", "strategy": {}})
        assert new_call["root_run_id"] == new_root
        assert new_call["agent_run_id"] == new_child["agent_run_id"]
        _settle_tool(store, second, new_child, new_call)

        with pytest.raises(AgentConflict, match="not active under current Backend authority"):
            _observe_tool(store, first, old_child, "byq_strategy_validate",
                {"agent_run_id": old_child["agent_run_id"], "task_id": "late-old-task", "strategy": {}})
    finally:
        store.close()


def test_acp_settled_dispatch_is_included_in_terminal_cursor_digest():
    ctx = _context("settled-cursor")
    store = AgentResearchStore()
    try:
        authority = store.rotate_runtime_authority(uuid4().hex)
        ctx["x-byq-runtime-boot-id"] = authority["boot_id"]
        root_native = str(uuid4())
        root, identity = _open_root(store, ctx, f"acp-root-{uuid4().hex}", root_native)
        _bind(store, ctx, identity)
        ingress = _observe_tool(store, ctx, identity, "byq_feedback_create_draft", {"title": "settled"})
        settle_receipt = _settle_tool(store, ctx, identity, ingress)
        assert settle_receipt["outcome"] == "settled"
        with pytest.raises(AgentConflict, match="already settled or unknown"):
            _abort_tool(store, ctx, identity, "byq_feedback_create_draft", {"title": "settled"},
                ingress["mcp_request_id"])

        close_receipt = store.close_runtime_root(root, boot_id=authority["boot_id"], sequence=2,
            outcome="completed", event_sha256="d" * 64)
        assert close_receipt["root_run_id"] == root
        row = store._fetch_one("""SELECT terminal_acp_ingress_sequence,terminal_acp_ingress_sha256,
                terminal_unknown_claim_count,terminal_unknown_claims_sha256,status
            FROM agent_runtime_turns WHERE root_run_id=:root""", {"root": root})
        assert row["status"] == "completed"
        assert row["terminal_acp_ingress_sequence"] == 1
        expected_cursor = acp_binding_sha256({
            "schema_version": "byq-acp-root-ingress-cursor.v1", "root_run_id": root,
            "sequence": 1, "events": [{"sequence": 1, "event_sha256": ingress["event_sha256"],
                "kind": "tool_ingress", "status": "settled", "outcome": "settled",
                "settlement_sha256": settle_receipt["settlement_sha256"]}],
        })
        assert row["terminal_acp_ingress_sha256"] == expected_cursor
        assert row["terminal_unknown_claim_count"] == 0
        assert row["terminal_unknown_claims_sha256"] == acp_binding_sha256({
            "schema_version": "byq-acp-unknown-claims.v1", "root_run_id": root, "claims": []})
    finally:
        store.close()


def test_acp_abort_existing_pending_observation_is_exact_idempotent_and_scope_bound():
    ctx = _context("abort-pending")
    store = AgentResearchStore()
    try:
        authority = store.rotate_runtime_authority(uuid4().hex)
        ctx["x-byq-runtime-boot-id"] = authority["boot_id"]
        native_root = str(uuid4())
        root, identity = _open_root(store, ctx, f"acp-root-{uuid4().hex}", native_root)
        _bind(store, ctx, identity)
        request_id = uuid4().hex
        tool_name = "byq_feedback_create_draft"
        arguments = {"title": "NO_RAW_ABORT_ARGUMENT"}
        observed = _observe_tool(store, ctx, identity, tool_name, arguments, request_id)

        foreign_scope = {**_scope(ctx, root), "owner": "foreign-owner"}
        with pytest.raises(AgentUnauthorized):
            _abort_tool(store, ctx, identity, tool_name, arguments, request_id, scope=foreign_scope)

        aborted = _abort_tool(store, ctx, identity, tool_name, arguments, request_id)
        assert set(aborted) == {"schema_version", "mcp_request_id", "root_run_id", "runtime_boot_id",
            "native_root_session_id", "native_agent_session_id", "native_parent_session_id",
            "origin", "depth", "tool_name", "arguments_sha256", "sequence", "event_sha256",
            "outcome", "abort_sha256"}
        assert aborted["schema_version"] == "byq-acp-tool-ingress-abort-receipt.v1"
        assert aborted["outcome"] == "aborted_before_dispatch"
        assert aborted["sequence"] == observed["sequence"]
        assert aborted["event_sha256"] == observed["event_sha256"]
        assert _abort_tool(store, ctx, identity, tool_name, arguments, request_id) == aborted
        with pytest.raises(AgentConflict, match="outcome is already fixed"):
            _settle_tool(store, ctx, identity, observed, "settled")
        with pytest.raises(AgentConflict, match="aborted before dispatch"):
            _observe_tool(store, ctx, identity, tool_name, arguments, request_id)
        persisted = store._fetch_one("""SELECT status,arguments_sha256,settlement_json::text AS settlement,
                receipt_json::text AS receipt
            FROM agent_acp_tool_ingress_observations WHERE mcp_request_id=:id""", {"id": request_id})
        assert persisted["status"] == "settled"
        assert "NO_RAW_ABORT_ARGUMENT" not in persisted["settlement"] + persisted["receipt"]
        assert re.fullmatch(r"[0-9a-f]{64}", persisted["arguments_sha256"])
    finally:
        store.close()


def test_acp_abort_before_observe_leaves_tombstone_and_fences_late_observe():
    ctx = _context("abort-before-observe")
    first, second = AgentResearchStore(), AgentResearchStore()
    try:
        authority = first.rotate_runtime_authority(uuid4().hex)
        ctx["x-byq-runtime-boot-id"] = authority["boot_id"]
        native_root = str(uuid4())
        root, identity = _open_root(first, ctx, f"acp-root-{uuid4().hex}", native_root)
        _bind(first, ctx, identity)
        request_id = uuid4().hex
        tool_name = "byq_feedback_create_draft"
        arguments = {"title": "ABORT_TOMBSTONE_SECRET"}
        observed_body = {"schema_version": "byq-acp-tool-ingress-observe.v1",
            "mcp_request_id": request_id,
            **{key: identity[key] for key in ("root_run_id", "runtime_boot_id", "native_root_session_id",
                "native_agent_session_id", "native_parent_session_id", "origin", "depth")},
            "tool_name": tool_name, "arguments": arguments}
        barrier = Barrier(2)

        def observe():
            barrier.wait()
            try:
                return first.observe_acp_tool_ingress(observed_body,
                    trusted_scope=_scope(ctx, root))
            except AgentConflict as error:
                return error

        def abort():
            barrier.wait()
            return _abort_tool(second, ctx, identity, tool_name, arguments, request_id)

        with ThreadPoolExecutor(max_workers=2) as pool:
            observed_future = pool.submit(observe)
            aborted_future = pool.submit(abort)
            observed_result = observed_future.result()
            aborted = aborted_future.result()
        assert aborted["outcome"] == "aborted_before_dispatch"
        assert isinstance(observed_result, AgentConflict) or observed_result["event_sha256"] == aborted["event_sha256"]
        assert _abort_tool(first, ctx, identity, tool_name, arguments, request_id) == aborted
        with pytest.raises(AgentConflict, match="aborted before dispatch"):
            _observe_tool(first, ctx, identity, tool_name, arguments, request_id)

        closed = first.close_runtime_root(root, boot_id=authority["boot_id"], sequence=2,
            outcome="interrupted", event_sha256="e" * 64)
        assert closed["root_run_id"] == root
        projection = first.runtime_roots_for_scope(owner_principal=ctx["x-byq-owner-principal"],
            workspace_id=ctx["x-byq-workspace-id"], session_id=ctx["x-byq-session-id"],
            trace_id=ctx["x-byq-trace-id"])
        row = next(item for item in projection["roots"] if item["root_run_id"] == root)
        assert row["terminal_acp_ingress_sequence"] == 1
        assert _abort_tool(first, ctx, identity, tool_name, arguments, request_id) == aborted
        persisted = first._fetch_one("""SELECT status,settlement_json::text AS settlement,
                receipt_json::text AS receipt FROM agent_acp_tool_ingress_observations
            WHERE mcp_request_id=:id""", {"id": request_id})
        assert persisted["status"] == "settled"
        assert "ABORT_TOMBSTONE_SECRET" not in persisted["settlement"] + persisted["receipt"]
    finally:
        second.close()
        first.close()


def test_acp_abort_commit_first_rejects_late_observe_and_exact_retry_survives_close():
    ctx = _context("abort-first")
    store = AgentResearchStore()
    try:
        authority = store.rotate_runtime_authority(uuid4().hex)
        ctx["x-byq-runtime-boot-id"] = authority["boot_id"]
        native_root = str(uuid4())
        root, identity = _open_root(store, ctx, f"acp-root-{uuid4().hex}", native_root)
        _bind(store, ctx, identity)
        request_id = uuid4().hex
        tool_name = "byq_feedback_create_draft"
        arguments = {"title": "LATE_OBSERVE_SECRET"}
        aborted = _abort_tool(store, ctx, identity, tool_name, arguments, request_id)
        assert _abort_tool(store, ctx, identity, tool_name, arguments, request_id) == aborted
        with pytest.raises(AgentConflict, match="aborted before dispatch"):
            _observe_tool(store, ctx, identity, tool_name, arguments, request_id)
        store.close_runtime_root(root, boot_id=authority["boot_id"], sequence=2,
            outcome="interrupted", event_sha256="f" * 64)
        assert _abort_tool(store, ctx, identity, tool_name, arguments, request_id) == aborted
    finally:
        store.close()
