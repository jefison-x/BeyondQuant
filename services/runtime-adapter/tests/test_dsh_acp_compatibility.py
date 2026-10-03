from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.compat.dsh_acp import (
    AcpNotification,
    AcpRpcError,
    AcpTransportError,
    DshAcpCompatibility,
)


_SERVER = r'''import json, os, sys

capture = os.environ["ACP_TEST_CAPTURE"]
session_id = "dsh-generated-native-session"
model_value = '["deepseek-official","deepseek-v4.1-flash"]'

def record(message):
    with open(capture, "a", encoding="utf-8") as output:
        output.write(json.dumps(message, separators=(",", ":")) + "\n")

def send(message):
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()

def config_options():
    return [{"id": "model", "options": [{"group": "deepseek-official",
        "options": [{"value": model_value, "name": "DeepSeek V4.1 Flash"}]}]}]

def update(params):
    send({"jsonrpc":"2.0", "method":"session/update", "params":params})

for line in sys.stdin:
    request = json.loads(line)
    record(request)
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params", {})
    if method == "initialize":
        send({"jsonrpc":"2.0", "id":request_id, "result":{"protocolVersion":1}})
    elif method in {"session/new", "session/resume"}:
        send({"jsonrpc":"2.0", "id":request_id, "result":{
            "sessionId":session_id, "configOptions":config_options()}})
    elif method == "session/set_config_option":
        send({"jsonrpc":"2.0", "id":request_id, "result":{"configOptions":config_options()}})
    elif method == "session/prompt":
        sid = params["sessionId"]
        update({"sessionId":sid, "update":{"sessionUpdate":"agent_thought_chunk",
            "messageId":"message-1", "content":{"type":"text", "text":"reasoning-never-public"}}})
        update({"sessionId":sid, "update":{"sessionUpdate":"agent_message_chunk",
            "messageId":"message-1", "content":{"type":"text", "text":"Alpha "}}})
        update({"sessionId":sid, "update":{"sessionUpdate":"agent_message_chunk",
            "messageId":"message-1", "content":{"type":"text", "text":"beta."}}})
        update({"sessionId":sid, "update":{"sessionUpdate":"tool_call", "toolCallId":"call-1",
            "title":"mcp__byq__byq_agent_run_start", "kind":"other", "status":"in_progress",
            "rawInput":{"role_id":"market_researcher", "idempotency_key":"registration-1"}}})
        update({"sessionId":sid, "update":{"sessionUpdate":"tool_call_update", "toolCallId":"call-1",
            "status":"completed", "content":[{"type":"content", "content":{"type":"text",
            "text":"{\"status\":\"ok\"}"}}]}})
        update({"sessionId":sid, "update":{"sessionUpdate":"usage_update", "used":11, "size":100}})
        send({"jsonrpc":"2.0", "id":request_id, "result":{"stopReason":"end_turn"}})
    elif method == "session/close":
        send({"jsonrpc":"2.0", "id":request_id, "result":{}})
    elif method == "session/cancel":
        pass
    else:
        send({"jsonrpc":"2.0", "id":request_id, "error":{"code":-32601, "message":"not found"}})
'''


def _identity_environment(capture: Path, *, boot_id: str = "boot-1") -> dict[str, str]:
    return {
        "ACP_TEST_CAPTURE": str(capture),
        "BYQ_MCP_URL": "http://mcp.test/mcp/v1",
        "BYQ_MCP_TOKEN": "test-only-token",
        "BYQ_RUNTIME_BOOT_ID": boot_id,
        "BYQ_OWNER_PRINCIPAL": "owner-1",
        "BYQ_WORKSPACE_ID": "workspace-1",
        "BYQ_ACTOR_PRINCIPAL": "byq-product-agent-public-session-1",
        "BYQ_TRACE_ID": "trace-1",
        "BYQ_SESSION_ID": "public-session-1",
        "BYQ_DSH_RUN_ID": "run-1",
        "BYQ_ROOT_RUN_ID": "a" * 32,
        "DEEPSEEK_API_KEY": "test-only-model-key",
    }


def _harness(tmp_path: Path, capture: Path, *, boot_id: str = "boot-1"):
    composition = tmp_path / "composition.yml"
    composition.write_text("[]\n", encoding="utf-8")
    session_root = tmp_path / "sessions" / "root-1"
    session_root.mkdir(parents=True)
    compatibility = DshAcpCompatibility()
    harness = compatibility.build_harness(
        provider="deepseek-official",
        model="deepseek-v4.1-flash",
        composition=composition,
        session_root=session_root,
        runtime_command=(sys.executable, "-u", "-c", _SERVER),
        environment=_identity_environment(capture, boot_id=boot_id),
    )
    return compatibility, harness


def test_official_acp_stdio_lifecycle_and_per_root_mcp_remount(tmp_path: Path) -> None:
    capture = tmp_path / "wire.jsonl"
    compatibility, harness = _harness(tmp_path, capture)
    events: list[AcpNotification] = []
    try:
        compatibility.start(harness)
        native_id = compatibility.create_session(harness)
        assert native_id == "dsh-generated-native-session"
        assert native_id in harness.native_session_ids
        assert compatibility.prompt(harness, native_id, "first root prompt", events.append) == "completed"
        compatibility.close_session(harness, native_id)

        harness.environment["BYQ_RUNTIME_BOOT_ID"] = "boot-2"
        resumed = compatibility.resume_session(harness, native_id)
        assert resumed == native_id
        compatibility.cancel_session(harness, resumed)
    finally:
        compatibility.close(harness)

    requests = [json.loads(line) for line in capture.read_text(encoding="utf-8").splitlines()]
    created = next(item for item in requests if item.get("method") == "session/new")
    resumed_request = next(item for item in requests if item.get("method") == "session/resume")
    for request in (created, resumed_request):
        assert request["params"]["cwd"] == str(harness.session_root.resolve())
        assert request["params"]["mcpServers"][0]["type"] == "http"
        headers = {entry["name"].lower(): entry["value"]
                   for entry in request["params"]["mcpServers"][0]["headers"]}
        assert headers["authorization"] == "Bearer test-only-token"
        assert headers["x-byq-session-id"] == "public-session-1"
        assert headers["x-byq-root-run-id"] == "a" * 32
    resumed_headers = {entry["name"].lower(): entry["value"]
                       for entry in resumed_request["params"]["mcpServers"][0]["headers"]}
    assert resumed_headers["x-byq-runtime-boot-id"] == "boot-2"
    assert not any(item.get("method") == "$/cancel_request" for item in requests)
    cancel = next(item for item in requests if item.get("method") == "session/cancel")
    assert cancel["params"] == {"sessionId": native_id}
    set_route = next(item for item in requests if item.get("method") == "session/set_config_option")
    assert set_route["params"]["value"] == '["deepseek-official","deepseek-v4.1-flash"]'
    assert "test-only-token" not in repr(harness)
    assert "test-only-model-key" not in repr(harness)

    observations = [compatibility.observe(event, root_session_id=native_id) for event in events]
    assert [item.kind for item in observations] == [
        "turn.start", "private.activity", "assistant.message", "tool.call",
        "tool.result", "private.activity", "turn.end",
    ]
    assert observations[2].answer_text == "Alpha beta."
    assert observations[2].message_id == "message-1"
    assert observations[2].event_sequence == 4
    assert observations[3].registration_key == "registration-1"
    assert observations[3].domain_arguments is None
    assert observations[4].completed_call_ids == ("call-1",)
    assert observations[4].tool_results[0].result == {"status": "ok"}
    assert observations[5].usage == {}
    assert observations[-1].terminal_reason == "completed"
    sequences = [item.event_sequence for item in observations]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
    assert "reasoning-never-public" not in repr(observations)

    domain_call = compatibility.observe(AcpNotification("session/update", {
        "sessionId": "native", "update": {
            "sessionUpdate": "tool_call", "toolCallId": "domain-call-1",
            "title": "mcp__byq__byq_strategy_validate",
            "rawInput": {
                "task_id": "task-1", "agent_run_id": "run-1",
                "idempotency_key": "key-1", "strategy": {"name": "candidate"},
            },
        },
    }, 9), root_session_id="native")
    assert domain_call.domain_arguments == {
        "task_id": "task-1", "agent_run_id": "run-1",
        "idempotency_key": "key-1", "strategy": {"name": "candidate"},
    }


def test_acp_observation_fails_closed_for_malformed_tool_inputs_and_unknown_stops() -> None:
    compatibility = DshAcpCompatibility()
    malformed = AcpNotification("session/update", {"sessionId": "native", "update": {
        "sessionUpdate": "tool_call", "toolCallId": "c1", "title": "mcp__byq__byq_agent_run_start",
        "rawInput": {"idempotency_key": 7, "receipt_only": False},
    }}, 3)
    observed = compatibility.observe(malformed, root_session_id="native")
    assert observed.kind == "tool.call"
    assert observed.registration_key is None
    assert observed.domain_arguments is None

    unexpected = AcpNotification("byq/turn/end", {
        "sessionId": "native", "stopReason": "future-stop-reason",
    }, 4)
    terminal = compatibility.observe(unexpected, root_session_id="native")
    assert terminal.terminal_reason == "failed"
    assert terminal.event_sequence == 4

    untrusted = AcpNotification("session/update", {"sessionId": "other", "update": {
        "sessionUpdate": "agent_message_chunk", "messageId": "m1",
        "content": {"type": "text", "text": "private"},
    }}, 5)
    assert compatibility.observe(untrusted, root_session_id="native").root_session is False


def test_json_rpc_error_does_not_echo_remote_error_text(tmp_path: Path) -> None:
    server = r'''import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if request.get("method") == "initialize":
        sys.stdout.write(json.dumps({"jsonrpc":"2.0", "id":request["id"],
            "result":{"protocolVersion":1}}) + "\n")
    else:
        sys.stdout.write(json.dumps({"jsonrpc":"2.0", "id":request["id"],
            "error":{"code":-32001, "message":"private-secret-provider-body"}}) + "\n")
    sys.stdout.flush()
'''
    composition = tmp_path / "composition.yml"
    composition.write_text("[]\n", encoding="utf-8")
    compatibility = DshAcpCompatibility()
    harness = compatibility.build_harness(
        provider="deepseek-official", model="model", composition=composition,
        session_root=tmp_path / "home", runtime_command=(sys.executable, "-u", "-c", server),
        environment={},
    )
    compatibility.start(harness)
    try:
        with pytest.raises(AcpRpcError) as error:
            harness.process.request("session/new", {})
        assert error.value.code == -32001
        assert "private-secret" not in str(error.value)
    finally:
        compatibility.close(harness)


def test_continuation_reservation_header_is_optional_and_strict() -> None:
    base = _identity_environment(Path("/dev/null"))
    servers = DshAcpCompatibility._mcp_servers(base)
    assert all(entry["name"].lower() != "x-byq-continuation-reservation"
               for entry in servers[0]["headers"])

    reservation = "continuation_" + "b" * 32
    guarded = DshAcpCompatibility._mcp_servers({
        **base, "BYQ_CONTINUATION_RESERVATION_ID": reservation,
    })
    headers = {entry["name"].lower(): entry["value"] for entry in guarded[0]["headers"]}
    assert headers["x-byq-continuation-reservation"] == reservation

    with pytest.raises(AcpTransportError):
        DshAcpCompatibility._mcp_servers({
            **base, "BYQ_CONTINUATION_RESERVATION_ID": "not-a-reservation",
        })
    with pytest.raises(AcpTransportError):
        DshAcpCompatibility._mcp_servers({
            **base,
            "BYQ_ROOT_RUN_ID": "invalid-root",
            "BYQ_CONTINUATION_RESERVATION_ID": reservation,
        })
