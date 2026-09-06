from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    from deepseek_harness import Notification
    from app.compat.dsh_012 import Dsh012Compatibility
except ImportError:
    pytest.skip("0.1.2 candidate SDK/runtime is not installed", allow_module_level=True)


def notification(event_type: str, data: dict, *, session_id: str = "root") -> Notification:
    return Notification(
        method="session.event",
        payload={"sessionId": session_id, "event": {"type": event_type, "data": data}},
    )


def test_candidate_uses_only_public_sdk_configuration(tmp_path: Path) -> None:
    executable = tmp_path / "dsh"
    executable.write_text("candidate", encoding="utf-8")
    patch = tmp_path / "candidate.patch.yml"
    patch.write_text("profile: sdk\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def config_factory(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(**kwargs)

    compatibility = Dsh012Compatibility(
        harness_factory=lambda *, config: config,
        runtime_path_factory=lambda: executable,
        config_factory=config_factory,
    )
    command = compatibility.runtime_command(tmp_path, "node")
    config = compatibility.build_harness(
        provider="deepseek-official", model="deepseek-v4-flash", composition=patch,
        session_root=tmp_path / "home", runtime_command=command,
        environment={"DEEPSEEK_API_KEY": "redacted"},
    )

    assert config.dsh_bin == str(executable.resolve())
    assert config.profile == "sdk"
    assert config.patches == (str(patch.resolve()),)
    assert config.dsh_home == str((tmp_path / "home").resolve())
    assert config.cwd == config.dsh_home == config.runtime_cwd
    assert config.env["DSH_TELEMETRY_DISABLED"] == "1"
    assert config.env["DSH_PERMISSION_MODE"] == "read-only"
    assert "launch_args_override" not in captured
    assert "cordis" not in captured


def test_candidate_normalizes_lifecycle_lineage_and_finish_reasons() -> None:
    compatibility = Dsh012Compatibility()
    started = compatibility.observe(
        Notification(method="subagent.started", payload={
            "parentSessionId": "root", "childSessionId": "child",
        }), root_session_id="root",
    )
    receipt = compatibility.observe(
        notification("agent/inbox/spliced", {}), root_session_id="root",
    )
    ended = compatibility.observe(
        notification("turn/end", {"reason": {"kind": "max-tokens"}}),
        root_session_id="root",
    )

    assert started.kind == "subagent.started"
    assert started.parent_session_id == "root"
    assert started.child_session_id == "child"
    assert started.runtime_activity is True
    assert receipt.kind == "prompt.receipt"
    assert ended.terminal_reason == "max_tokens"


def test_candidate_drops_private_reasoning_arguments_and_unknown_reasons() -> None:
    compatibility = Dsh012Compatibility()
    assistant = compatibility.observe(notification("assistant/message", {
        "message": {"id": "message-1", "content": [
            {"type": "reasoning", "text": "private-chain"},
            {"type": "text", "text": "公开回答"},
        ]},
    }), root_session_id="root")
    tool = compatibility.observe(notification("tool/call", {
        "callId": "call-1", "name": "byq_market_daily",
        "arguments": {"secret": "must-not-cross"},
    }), root_session_id="root")
    unknown = compatibility.observe(
        notification("turn/end", {"reason": {"kind": "future-value"}}),
        root_session_id="root",
    )

    assert assistant.answer_text == "公开回答"
    assert "private-chain" not in repr(assistant)
    assert tool.call_id == "call-1"
    assert "must-not-cross" not in repr(tool)
    assert unknown.terminal_reason == "failed"
