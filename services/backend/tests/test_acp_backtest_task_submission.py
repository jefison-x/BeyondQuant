from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest

from app import main
from app.agent_research import AgentResearchStore
from app.conversation_catalog import ConversationCatalogStore
from app.paper_trading import PaperTradingConflict
from app.user_policy import UserPolicyStore
from tests import test_backtest_api
from tests.test_acp_domain_call_proof import _bind, _observe_tool, _open_root, _settle_tool
from tests.test_backtest_task_reconciliation import setup_creation
from tests.workspace_helpers import trusted_product_agent_context


pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")

_TASK_CREATE = "byq_backtest_task_create"
_PROOF = "synthetic-acp-backend-proof"


def _setup_acp_task(monkeypatch, tmp_path, label: str):
    session_id = f"session-acp-{uuid4().hex}"
    trace_id = "byq-trace-task-receipt"
    generation = f"generation-{uuid4().hex}"
    owner = "product-user"
    context = trusted_product_agent_context(
        owner, actor=f"byq-product-agent-{session_id}", trace_id=trace_id,
        session_id=session_id, dsh_run_id=generation,
    )
    human_context = {**context, "x-byq-actor-principal": owner}
    monkeypatch.setattr(test_backtest_api, "_owner_headers", lambda _principal: dict(human_context))

    catalog = ConversationCatalogStore()
    try:
        conversation = catalog.create(owner, session_id, trace_id)
    finally:
        catalog.close()

    research, backtests, jobs, client, payload = setup_creation(monkeypatch, tmp_path)
    task = research.get_task(payload["task_id"])
    assert task["conversation_id"] == conversation["conversation_id"]

    agent_store = AgentResearchStore()
    monkeypatch.setattr(main, "agent_store", agent_store)
    authority = agent_store.current_runtime_authority()
    assert authority is not None
    context["x-byq-runtime-boot-id"] = authority["boot_id"]
    monkeypatch.setattr(main, "MCP_BACKEND_PROOF_TOKEN", _PROOF)
    native_root = str(uuid4())
    root_id, identity = _open_root(
        agent_store, context, f"acp-backtest-{label}-{uuid4().hex}", native_root,
    )
    _bind(agent_store, context, identity)
    arguments = {**payload, "order_quantity": 100}
    ingress = _observe_tool(agent_store, context, identity, _TASK_CREATE, arguments)
    headers = {
        **context,
        "Authorization": f"Bearer {_PROOF}",
        "x-byq-root-run-id": root_id,
        "x-byq-runtime-boot-id": context["x-byq-runtime-boot-id"],
        "x-byq-acp-observation-id": ingress["mcp_request_id"],
        "x-byq-acp-native-root-session-id": identity["native_root_session_id"],
        "x-byq-acp-native-agent-session-id": identity["native_agent_session_id"],
        "x-byq-acp-native-parent-session-id": "",
        "x-byq-acp-origin": identity["origin"],
        "x-byq-acp-depth": str(identity["depth"]),
    }
    return {
        "agent_store": agent_store, "arguments": arguments, "backtests": backtests,
        "client": client, "context": context, "conversation": conversation,
        "headers": headers, "human_context": human_context, "identity": identity,
        "ingress": ingress, "jobs": jobs, "payload": payload,
        "research": research, "root_id": root_id, "task": task,
    }


def _close_setup(fixture: dict[str, object]) -> None:
    for key in ("agent_store", "jobs", "backtests", "research"):
        store = fixture[key]
        store.close()


def _post_create(fixture: dict[str, object], *, payload=None, headers=None):
    return fixture["client"].post(
        "/v1/research/backtest-tasks",
        json=fixture["arguments"] if payload is None else payload,
        headers=fixture["headers"] if headers is None else headers,
    )


def _assert_no_job(fixture: dict[str, object]) -> None:
    row = fixture["jobs"].find_submission(
        fixture["task"]["task_id"], fixture["arguments"]["idempotency_key"],
        trusted_owner=fixture["context"]["x-byq-owner-principal"],
        trusted_workspace=fixture["context"]["x-byq-workspace-id"],
    )
    assert row is None


def test_exact_acp_observation_creates_secret_free_origin_and_replays_once(monkeypatch, tmp_path):
    fixture = _setup_acp_task(monkeypatch, tmp_path, "exact")
    try:
        first = _post_create(fixture)
        assert first.status_code == 202, first.text
        assert "submission_origin" not in first.text
        assert first.json()["task"]["references"]["research_task_id"] == fixture["task"]["task_id"]

        stored = fixture["jobs"]._fetch_one(
            "SELECT * FROM signal_producer_jobs WHERE owner_principal=:owner AND idempotency_key=:key",
            {"owner": fixture["context"]["x-byq-owner-principal"],
             "key": fixture["arguments"]["idempotency_key"]},
        )
        assert stored is not None
        origin = stored["submission_origin"]
        assert origin["schema_version"] == "signal-job-submission-origin.v2"
        assert origin["kind"] == "authorized_agent"
        assert origin["mcp_request_id"] == fixture["ingress"]["mcp_request_id"]
        assert origin["root_run_id"] == fixture["root_id"]
        assert origin["task_id"] == fixture["task"]["task_id"]
        assert origin["conversation_id"] == fixture["conversation"]["conversation_id"]
        assert origin["authorization_decision"] == "allowed"
        assert len(origin["policy_snapshot_sha256"]) == 64
        assert not ({"cookie", "auth_session_id", "authorization", "password"} & set(origin))
        assert _PROOF not in str(origin)

        _settle_tool(fixture["agent_store"], fixture["context"], fixture["identity"],
                     fixture["ingress"], "settled")
        replay = _post_create(fixture)
        assert replay.status_code == 202, replay.text
        replayed = fixture["jobs"]._fetch_one(
            "SELECT * FROM signal_producer_jobs WHERE owner_principal=:owner AND idempotency_key=:key",
            {"owner": fixture["context"]["x-byq-owner-principal"],
             "key": fixture["arguments"]["idempotency_key"]},
        )
        assert replayed["job_id"] == stored["job_id"]
        assert replayed["submission_origin"] == origin
        assert fixture["jobs"]._fetch_one(
            "SELECT count(*) AS n FROM signal_producer_jobs WHERE task_id=:task",
            {"task": fixture["task"]["task_id"]},
        )["n"] == 1
    finally:
        _close_setup(fixture)


@pytest.mark.parametrize("case", [
    "missing_observation", "wrong_proof", "wrong_scope", "changed_arguments", "unknown_ingress",
])
def test_acp_backtest_create_rejects_unproven_or_unknown_ingress(monkeypatch, tmp_path, case):
    fixture = _setup_acp_task(monkeypatch, tmp_path, case)
    try:
        payload = dict(fixture["arguments"])
        headers = dict(fixture["headers"])
        if case == "missing_observation":
            headers.pop("x-byq-acp-observation-id")
        elif case == "wrong_proof":
            headers["Authorization"] = "Bearer invalid-proof"
        elif case == "wrong_scope":
            headers["x-byq-session-id"] = "session-acp-other-scope"
        elif case == "changed_arguments":
            payload["order_quantity"] += 100
        else:
            _settle_tool(fixture["agent_store"], fixture["context"], fixture["identity"],
                         fixture["ingress"], "unknown")

        response = _post_create(fixture, payload=payload, headers=headers)
        assert response.status_code in {401, 409}, response.text
        _assert_no_job(fixture)
        stored_ingress = fixture["agent_store"]._fetch_one(
            "SELECT status,settlement_json FROM agent_acp_tool_ingress_observations WHERE mcp_request_id=:id",
            {"id": fixture["ingress"]["mcp_request_id"]},
        )
        if case == "unknown_ingress":
            assert stored_ingress["status"] == "unknown"
            assert stored_ingress["settlement_json"]["outcome"] == "unknown"
        else:
            assert stored_ingress["status"] == "pending"
    finally:
        _close_setup(fixture)


@pytest.mark.parametrize("terminal", ["task", "conversation"])
def test_terminal_task_or_conversation_cannot_admit_new_acp_job(monkeypatch, tmp_path, terminal):
    fixture = _setup_acp_task(monkeypatch, tmp_path, f"terminal-{terminal}")
    try:
        if terminal == "task":
            response = fixture["client"].post(
                f"/v1/research/tasks/{fixture['task']['task_id']}/transitions",
                json={"target_status": "cancelled", "idempotency_key": f"terminal-{uuid4().hex}"},
                headers=fixture["human_context"],
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "cancelled"
        else:
            response = fixture["client"].patch(
                f"/v1/product/conversations/{fixture['conversation']['conversation_id']}",
                json={"status": "archived"}, headers=fixture["human_context"],
            )
            assert response.status_code == 200, response.text
            assert response.json()["conversation"]["status"] == "archived"

        rejected = _post_create(fixture)
        assert rejected.status_code == 409, rejected.text
        _assert_no_job(fixture)
        assert fixture["agent_store"]._fetch_one(
            "SELECT status FROM agent_acp_tool_ingress_observations WHERE mcp_request_id=:id",
            {"id": fixture["ingress"]["mcp_request_id"]},
        )["status"] == "pending"
    finally:
        _close_setup(fixture)


def test_current_owner_policy_denial_creates_no_acp_job(monkeypatch, tmp_path):
    fixture = _setup_acp_task(monkeypatch, tmp_path, "policy-deny")
    try:
        main.user_policy_store.update(
            fixture["context"]["x-byq-owner-principal"],
            {"automation_enabled": True, "paused": False, "default_decision_mode": "auto_deny"},
            request_id=f"deny-{uuid4().hex}",
        )
        response = _post_create(fixture)
        assert response.status_code == 403
        _assert_no_job(fixture)
        assert fixture["agent_store"]._fetch_one(
            "SELECT status FROM agent_acp_tool_ingress_observations WHERE mcp_request_id=:id",
            {"id": fixture["ingress"]["mcp_request_id"]},
        )["status"] == "pending"
    finally:
        _close_setup(fixture)


def test_acp_job_reference_failure_rolls_back_job_and_origin(monkeypatch, tmp_path):
    fixture = _setup_acp_task(monkeypatch, tmp_path, "reference-rollback")
    try:
        def fail_reference(*_args, **_kwargs):
            raise PaperTradingConflict("synthetic pool reference rejection")

        monkeypatch.setattr(main.paper_store, "record_pool_reference_in_transaction", fail_reference)
        response = _post_create(fixture)
        assert response.status_code == 409
        _assert_no_job(fixture)
        assert fixture["jobs"]._fetch_one(
            "SELECT count(*) AS n FROM stock_pool_domain_references WHERE domain='signal_producer' AND owner_principal=:owner",
            {"owner": fixture["context"]["x-byq-owner-principal"]},
        )["n"] == 0
        assert fixture["agent_store"]._fetch_one(
            "SELECT status FROM agent_acp_tool_ingress_observations WHERE mcp_request_id=:id",
            {"id": fixture["ingress"]["mcp_request_id"]},
        )["status"] == "pending"
    finally:
        _close_setup(fixture)


def test_first_owner_policy_write_waits_for_admission_snapshot_lock():
    policy = UserPolicyStore()
    writer_policy = UserPolicyStore()
    owner = f"policy-lock-{uuid4().hex}"
    authorization = {"authorized": True, "decision": "allowed", "role_id": "quant_orchestrator",
                     "action": _TASK_CREATE, "run_id": f"agent_run_{uuid4().hex}"}
    read_locked = Event()
    release_read = Event()
    write_started = Event()
    write_done = Event()

    assert policy._fetch_one(
        "SELECT owner_principal FROM user_agent_policy WHERE owner_principal=:owner",
        {"owner": owner},
    ) is None

    def admission_snapshot():
        with policy._transaction() as connection:
            effective, _ = policy.evaluate_authorization_in_transaction(connection, owner, authorization)
            assert effective["authorized"] is True
            read_locked.set()
            assert release_read.wait(5)

    def first_write():
        assert read_locked.wait(5)
        write_started.set()
        writer_policy.update(owner, {"automation_enabled": True, "paused": False,
                                     "default_decision_mode": "auto_deny"},
                             request_id=f"policy-write-{uuid4().hex}")
        write_done.set()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            admission = pool.submit(admission_snapshot)
            assert read_locked.wait(5)
            mutation = pool.submit(first_write)
            assert write_started.wait(5)
            assert not write_done.wait(0.15)
            release_read.set()
            admission.result(timeout=5)
            mutation.result(timeout=5)
        assert write_done.is_set()
        assert policy.get(owner)["default_decision_mode"] == "auto_deny"
    finally:
        release_read.set()
        policy.close()
        writer_policy.close()
