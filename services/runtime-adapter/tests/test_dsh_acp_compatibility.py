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
session_id = "8b90c2b5-3a08-4eae-9fc7-04baf12910de"
model_value = '["deepseek-official","deepseek-v4.1-flash"]'

with open(os.environ["ACP_TEST_ENV_CAPTURE"], "w", encoding="utf-8") as output:
    json.dump({"legacy_mcp_token": os.environ.get("BYQ_MCP_TOKEN"),
        "backend_proof_token": os.environ.get("BYQ_MCP_BACKEND_PROOF_TOKEN"),
        "judgment_backend_proof_token": os.environ.get("BYQ_MCP_ACP_JUDGMENT_PROOF_TOKEN"),
        "credential_resolver_token": os.environ.get("BYQ_CREDENTIAL_RESOLVER_TOKEN"),
        "runtime_authority_token": os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN"),
        "product_token": os.environ.get("BYQ_PRODUCT_TOKEN"),
        "runtime_judgment_token": os.environ.get("BYQ_RUNTIME_JUDGMENT_TOKEN"),
        "read_only_token": os.environ.get("BYQ_MCP_READ_ONLY_TOKEN"),
        "postgres_password": os.environ.get("POSTGRES_PASSWORD"),
        "discovery_token": os.environ.get("BYQ_MCP_ACP_DISCOVERY_TOKEN"),
        "signing_key": os.environ.get("BYQ_MCP_ACP_SIGNING_KEY"),
        "judgment_mode": os.environ.get("BYQ_MCP_ACP_IDENTITY_MODE"),
        "judgment_task_id": os.environ.get("BYQ_MCP_ACP_JUDGMENT_TASK_ID"),
        "judgment_call_identity": os.environ.get("BYQ_MCP_ACP_JUDGMENT_CALL_IDENTITY"),
        "judgment_signing_key": os.environ.get("BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY"),
        "mcp_url": os.environ.get("BYQ_MCP_URL"),
        "product_mcp_url": os.environ.get("BYQ_MCP_PRODUCT_URL"),
        "deepseek_key": os.environ.get("DEEPSEEK_API_KEY"),
        "opencode_key": os.environ.get("OPENCODE_API_KEY"),
        "search_key": os.environ.get("DEEPSEEK_SEARCH_API_KEY"),
        "dsh_home": os.environ.get("DSH_HOME"),
        "dsh_session_root": os.environ.get("DSH_SESSION_ROOT")}, output)

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
        if method == "session/new":
            marker = os.path.join(os.environ["DSH_HOME"], ".byq-acp-root-binding.json")
            with open(marker, "x", encoding="utf-8") as output:
                json.dump({"schema_version":"byq-acp-root-binding.v1",
                    "native_root_session_id":session_id, "cwd":params["cwd"]}, output,
                separators=(",", ":"))
            os.chmod(marker, 0o600)
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


def _identity_environment(
    capture: Path, *, boot_id: str = "b" * 32, native_root_session_id: str | None = None,
) -> dict[str, str]:
    return {
        "ACP_TEST_CAPTURE": str(capture),
        "ACP_TEST_ENV_CAPTURE": str(capture.with_name(capture.name + ".env")),
        "BYQ_MCP_URL": "http://mcp.test/mcp/v1",
        "BYQ_MCP_ACP_DISCOVERY_TOKEN": "synthetic-discovery-only-token",
        "BYQ_MCP_ACP_SIGNING_KEY": "synthetic-signing-key-0123456789abcdef",
        "BYQ_MCP_TOKEN": "test-only-token",
        "BYQ_MCP_BACKEND_PROOF_TOKEN": "test-only-backend-proof-token",
        "BYQ_RUNTIME_BOOT_ID": boot_id,
        "BYQ_OWNER_PRINCIPAL": "owner-1",
        "BYQ_WORKSPACE_ID": "workspace-1",
        "BYQ_ACTOR_PRINCIPAL": "byq-product-agent-public-session-1",
        "BYQ_TRACE_ID": "trace-1",
        "BYQ_SESSION_ID": "public-session-1",
        "BYQ_DSH_RUN_ID": "run-1",
        "BYQ_ROOT_RUN_ID": "a" * 32,
        "DEEPSEEK_API_KEY": "test-only-model-key",
        **({"BYQ_NATIVE_ROOT_SESSION_ID": native_root_session_id}
           if native_root_session_id is not None else {}),
    }


def _harness(tmp_path: Path, capture: Path, *, boot_id: str = "b" * 32):
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


def _judgment_identity_environment(capture: Path) -> dict[str, str]:
    return {
        "ACP_TEST_CAPTURE": str(capture),
        "ACP_TEST_ENV_CAPTURE": str(capture.with_name(capture.name + ".env")),
        "BYQ_MCP_URL": "http://mcp.judgment.test/mcp/v1",
        "BYQ_MCP_PRODUCT_URL": "http://mcp.product.test/mcp/v1",
        "BYQ_MCP_ACP_IDENTITY_MODE": "research-judgment-root-v1",
        "BYQ_MCP_ACP_JUDGMENT_TASK_ID": "task_" + "a" * 32,
        "BYQ_MCP_ACP_JUDGMENT_CALL_IDENTITY": "byq-judgment-" + "b" * 32,
        "BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY": "synthetic-judgment-signing-key-0123456789",
        "BYQ_RUNTIME_BOOT_ID": "b" * 32,
        "BYQ_OWNER_PRINCIPAL": "owner-1",
        "BYQ_WORKSPACE_ID": "workspace-1",
        "BYQ_ACTOR_PRINCIPAL": "byq-product-agent-judgment-session-1",
        "BYQ_TRACE_ID": "trace-judgment-1",
        "BYQ_SESSION_ID": "judgment-session-1",
        "BYQ_DSH_RUN_ID": "generation-judgment-1",
        "BYQ_ROOT_RUN_ID": "c" * 32,
        "DEEPSEEK_API_KEY": "test-only-model-key",
    }


def test_official_acp_stdio_lifecycle_and_scoped_mcp_identity_resume(tmp_path: Path) -> None:
    capture = tmp_path / "wire.jsonl"
    compatibility, harness = _harness(tmp_path, capture)
    events: list[AcpNotification] = []
    try:
        compatibility.start(harness)
        native_id = compatibility.create_session(harness)
        assert native_id == "8b90c2b5-3a08-4eae-9fc7-04baf12910de"
        assert native_id in harness.native_session_ids
        assert compatibility.prompt(harness, native_id, "first root prompt", events.append) == "completed"
        compatibility.close_session(harness, native_id)
    finally:
        compatibility.close(harness)

    resumed_harness = compatibility.build_harness(
        provider="deepseek-official", model="deepseek-v4.1-flash",
        composition=harness.composition, session_root=harness.session_root,
        runtime_command=harness.runtime_command,
        environment=_identity_environment(capture, boot_id="c" * 32,
                                          native_root_session_id=native_id),
    )
    try:
        compatibility.start(resumed_harness)
        resumed = compatibility.resume_session(resumed_harness, native_id)
        assert resumed == native_id
        compatibility.cancel_session(resumed_harness, resumed)
    finally:
        compatibility.close(resumed_harness)

    requests = [json.loads(line) for line in capture.read_text(encoding="utf-8").splitlines()]
    created = next(item for item in requests if item.get("method") == "session/new")
    resumed_request = next(item for item in requests if item.get("method") == "session/resume")
    for request in (created, resumed_request):
        assert request["params"]["cwd"] == str(harness.session_root.resolve())
        assert request["params"]["mcpServers"] == []
    assert resumed_request["params"]["sessionId"] == native_id
    assert not any(item.get("method") == "$/cancel_request" for item in requests)
    cancel = next(item for item in requests if item.get("method") == "session/cancel")
    assert cancel["params"] == {"sessionId": native_id}
    set_route = next(item for item in requests if item.get("method") == "session/set_config_option")
    assert set_route["params"]["value"] == '["deepseek-official","deepseek-v4.1-flash"]'
    assert "test-only-token" not in repr(harness)
    assert "test-only-model-key" not in repr(harness)
    assert "synthetic-signing-key" not in repr(harness)
    child_environment = json.loads(capture.with_name(capture.name + ".env").read_text(encoding="utf-8"))
    assert child_environment["legacy_mcp_token"] is None
    assert child_environment["backend_proof_token"] is None
    assert child_environment["discovery_token"] == "synthetic-discovery-only-token"
    assert child_environment["signing_key"] == "synthetic-signing-key-0123456789abcdef"
    assert child_environment["judgment_mode"] is None
    assert child_environment["judgment_task_id"] is None
    assert child_environment["judgment_call_identity"] is None
    assert child_environment["judgment_signing_key"] is None
    assert child_environment["dsh_home"] == str(harness.session_root)
    assert child_environment["dsh_session_root"] == str(harness.session_root.parent)

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


def test_judgment_identity_mode_is_explicit_and_process_scope_has_only_its_credential(
    tmp_path: Path,
) -> None:
    capture = tmp_path / "judgment-root.jsonl"
    composition = tmp_path / "judgment-composition.yml"
    composition.write_text("[]\n", encoding="utf-8")
    session_root = tmp_path / "sessions" / "judgment-root"
    session_root.mkdir(parents=True)
    compatibility = DshAcpCompatibility()
    harness = compatibility.build_harness(
        provider="deepseek-official", model="deepseek-v4.1-flash",
        composition=composition, session_root=session_root,
        runtime_command=(sys.executable, "-u", "-c", _SERVER),
        environment=_judgment_identity_environment(capture),
    )
    try:
        compatibility.start(harness)
        native_id = compatibility.create_session(harness)
    finally:
        compatibility.close(harness)

    child_environment = json.loads(capture.with_name(capture.name + ".env").read_text(
        encoding="utf-8"))
    assert child_environment["judgment_mode"] == "research-judgment-root-v1"
    assert child_environment["judgment_task_id"] == "task_" + "a" * 32
    assert child_environment["judgment_call_identity"] == "byq-judgment-" + "b" * 32
    assert child_environment["judgment_signing_key"] == \
        "synthetic-judgment-signing-key-0123456789"
    assert child_environment["mcp_url"] == "http://mcp.judgment.test/mcp/v1"
    assert child_environment["product_mcp_url"] == "http://mcp.product.test/mcp/v1"
    for name in (
        "legacy_mcp_token", "backend_proof_token", "judgment_backend_proof_token",
        "credential_resolver_token",
        "runtime_authority_token", "runtime_judgment_token", "product_token",
        "read_only_token", "discovery_token", "signing_key",
    ):
        assert child_environment[name] is None
    requests = [json.loads(line) for line in capture.read_text(encoding="utf-8").splitlines()]
    assert any(item.get("method") == "session/new" for item in requests)
    assert not any(item.get("method") == "session/prompt" for item in requests)
    assert native_id in harness.native_session_ids


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "BYQ_MCP_ACP_DISCOVERY_TOKEN", "BYQ_MCP_ACP_SIGNING_KEY", "BYQ_MCP_TOKEN",
        "BYQ_MCP_READ_ONLY_TOKEN", "BYQ_MCP_BACKEND_PROOF_TOKEN",
        "BYQ_MCP_ACP_JUDGMENT_PROOF_TOKEN",
        "BYQ_RUNTIME_AUTHORITY_TOKEN", "BYQ_RUNTIME_JUDGMENT_TOKEN",
        "BYQ_CREDENTIAL_RESOLVER_TOKEN", "BYQ_PRODUCT_TOKEN",
        "BYQ_NATIVE_ROOT_SESSION_ID", "BYQ_CONTINUATION_RESERVATION_ID",
    ],
)
def test_judgment_identity_rejects_product_or_stale_credentials_even_when_empty(
    tmp_path: Path, forbidden_key: str,
) -> None:
    composition = tmp_path / "composition.yml"
    composition.write_text("[]\n", encoding="utf-8")
    session_root = tmp_path / "sessions" / "root-1"
    session_root.mkdir(parents=True)
    environment = _judgment_identity_environment(tmp_path / "wire.jsonl")
    environment[forbidden_key] = ""
    with pytest.raises(AcpTransportError, match="contains Product credentials"):
        DshAcpCompatibility().build_harness(
            provider="deepseek-official", model="deepseek-v4.1-flash",
            composition=composition, session_root=session_root,
            runtime_command=(sys.executable, "-u", "-c", _SERVER), environment=environment,
        )


def test_product_identity_cannot_select_the_judgment_root_mode(tmp_path: Path) -> None:
    capture = tmp_path / "product-root.jsonl"
    composition = tmp_path / "composition.yml"
    composition.write_text("[]\n", encoding="utf-8")
    session_root = tmp_path / "sessions" / "root-1"
    session_root.mkdir(parents=True)
    environment = _identity_environment(capture)
    environment["BYQ_MCP_ACP_IDENTITY_MODE"] = "research-judgment-root-v1"
    with pytest.raises(AcpTransportError, match="Product credentials"):
        DshAcpCompatibility().build_harness(
            provider="deepseek-official", model="deepseek-v4.1-flash",
            composition=composition, session_root=session_root,
            runtime_command=(sys.executable, "-u", "-c", _SERVER), environment=environment,
        )


def test_close_retains_transport_handle_until_process_exit_is_confirmed(tmp_path: Path) -> None:
    capture = tmp_path / "close-proof.jsonl"
    compatibility, harness = _harness(tmp_path, capture)

    class PendingExitTransport:
        exit_code = None
        process = None

        def __init__(self) -> None:
            self.process = type("Process", (), {"poll": lambda _self: self.exit_code})()

        def close(self) -> None:
            return None

    transport = PendingExitTransport()
    harness.process = transport
    with pytest.raises(AcpTransportError, match="exit could not be confirmed"):
        compatibility.close(harness)
    assert harness.process is transport

    transport.exit_code = 0
    compatibility.close(harness)
    assert harness.process is None


@pytest.mark.parametrize(
    ("provider", "selected_key", "expected_deepseek", "expected_opencode"),
    [
        ("deepseek-official", "DEEPSEEK_API_KEY", "selected-deepseek", None),
        ("opencode-zen", "OPENCODE_API_KEY", None, "selected-opencode"),
    ],
)
def test_acp_child_receives_only_selected_provider_credential(
    tmp_path: Path, monkeypatch, provider: str, selected_key: str,
    expected_deepseek: str | None, expected_opencode: str | None,
) -> None:
    # The Adapter service may have both provider credentials for unrelated
    # sessions. The ACP child must receive only the key for this route.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ambient-deepseek-must-not-leak")
    monkeypatch.setenv("OPENCODE_API_KEY", "ambient-opencode-must-not-leak")
    monkeypatch.setenv("DEEPSEEK_SEARCH_API_KEY", "ambient-search-must-not-leak")
    monkeypatch.setenv("BYQ_CREDENTIAL_RESOLVER_TOKEN", "ambient-resolver-must-not-leak")
    monkeypatch.setenv("BYQ_RUNTIME_AUTHORITY_TOKEN", "ambient-authority-must-not-leak")
    monkeypatch.setenv("BYQ_PRODUCT_TOKEN", "ambient-product-must-not-leak")
    monkeypatch.setenv("POSTGRES_PASSWORD", "ambient-database-must-not-leak")
    capture = tmp_path / f"{provider}.jsonl"
    environment = _identity_environment(capture)
    environment["BYQ_CREDENTIAL_RESOLVER_TOKEN"] = "explicit-resolver-must-not-leak"
    environment.pop("DEEPSEEK_API_KEY", None)
    environment[selected_key] = (
        "selected-deepseek" if selected_key == "DEEPSEEK_API_KEY" else "selected-opencode"
    )
    composition = tmp_path / f"{provider}.yml"
    composition.write_text("[]\n", encoding="utf-8")
    compatibility = DshAcpCompatibility()
    harness = compatibility.build_harness(
        provider=provider, model="qualified-test-model", composition=composition,
        session_root=tmp_path / provider, runtime_command=(sys.executable, "-u", "-c", _SERVER),
        environment=environment,
    )
    try:
        compatibility.start(harness)
    finally:
        compatibility.close(harness)

    child_environment = json.loads(capture.with_name(capture.name + ".env").read_text())
    assert child_environment["deepseek_key"] == expected_deepseek
    assert child_environment["opencode_key"] == expected_opencode
    assert child_environment["search_key"] is None
    assert child_environment["credential_resolver_token"] is None
    assert child_environment["runtime_authority_token"] is None
    assert child_environment["product_token"] is None
    assert child_environment["postgres_password"] is None

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


def test_acp_runtime_rejects_reused_discovery_or_signing_credential() -> None:
    base = _identity_environment(Path("/dev/null"))
    for replacement in (
        {"BYQ_MCP_ACP_DISCOVERY_TOKEN": base["BYQ_MCP_TOKEN"]},
        {"BYQ_MCP_ACP_DISCOVERY_TOKEN": base["BYQ_MCP_ACP_SIGNING_KEY"]},
        {"BYQ_MCP_TOKEN": base["BYQ_MCP_ACP_SIGNING_KEY"]},
    ):
        with pytest.raises(AcpTransportError, match="credentials must be distinct"):
            DshAcpCompatibility._validate_runtime_identity({**base, **replacement})


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
        environment=_identity_environment(tmp_path / "wire.jsonl"),
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
    assert DshAcpCompatibility._mcp_servers(base) == []

    reservation = "continuation_" + "b" * 32
    guarded = DshAcpCompatibility._mcp_servers({
        **base, "BYQ_CONTINUATION_RESERVATION_ID": reservation,
    })
    assert guarded == []

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
