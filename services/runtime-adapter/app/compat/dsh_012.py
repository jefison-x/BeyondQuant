"""Official DSH 0.1.2rc1 SDK and notification compatibility boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig, Notification
from deepseek_harness_runtime import bundled_runtime_path

from .types import RuntimeObservation


_SESSION_STATUSES = frozenset({
    "starting", "ready", "idle", "running", "cancelling", "interrupted", "failed", "closed",
})
_FINISH_REASONS = {
    "completed": "completed",
    "max-tokens": "max_tokens",
    "aborted": "cancelled",
    "error": "failed",
    "failed": "failed",
    "refusal": "failed",
}
_USAGE_FIELDS = {
    "inputTokens": "input_tokens", "outputTokens": "output_tokens",
    "cacheReadTokens": "cache_read_tokens", "cacheWriteTokens": "cache_write_tokens",
    "reasoningTokens": "reasoning_tokens",
}


class Dsh012Compatibility:
    """Use only the 0.1.2rc1 public SDK and bundled executable surfaces."""

    family = "dsh-0.1.2"

    def __init__(
        self,
        harness_factory: Callable[..., Any] = DeepSeekHarness,
        runtime_path_factory: Callable[[], Path] = bundled_runtime_path,
        config_factory: Callable[..., Any] = DeepSeekHarnessConfig,
    ) -> None:
        self._harness_factory = harness_factory
        self._runtime_path_factory = runtime_path_factory
        self._config_factory = config_factory

    def runtime_command(self, _runtime_root: Path, _node: str) -> tuple[str, ...]:
        return (str(self._runtime_path_factory().resolve()),)

    def build_harness(
        self, *, provider: str, model: str, composition: Path, session_root: Path,
        runtime_command: tuple[str, ...], environment: dict[str, str],
    ) -> Any:
        patch = composition.expanduser().resolve()
        home = session_root.expanduser().resolve()
        if not patch.is_file():
            raise FileNotFoundError(f"candidate DSH patch is unavailable: {patch}")
        if len(runtime_command) != 1 or not Path(runtime_command[0]).is_file():
            raise FileNotFoundError("candidate DSH bundled executable is unavailable")
        # The 0.1.2 public launcher uses runtime_cwd immediately when spawning.
        # The adapter has already validated that this generation path is
        # contained below DSH_SESSION_ROOT.
        home.mkdir(parents=True, exist_ok=True)
        child_environment = {
            **environment,
            "DSH_RUNTIME_MODE": "exe",
            "DSH_TELEMETRY_DISABLED": "1",
            "DSH_PERMISSION_MODE": "read-only",
            "DSH_MAX_TOKENS_AS_SUCCESS": "false",
        }
        config = self._config_factory(
            provider=provider,
            model=model,
            dsh_bin=runtime_command[0],
            profile="sdk",
            patches=(str(patch),),
            dsh_home=str(home),
            cwd=str(home),
            runtime_cwd=str(home),
            env=child_environment,
            initialize_timeout_seconds=60.0,
            request_timeout_seconds=None,
            shutdown_timeout_seconds=2.0,
        )
        return self._harness_factory(config=config)

    @staticmethod
    def start(harness: Any) -> None:
        harness.start()

    @staticmethod
    def prompt(harness: Any, session_id: str, content: str, on_notification: Callable[[object], None]) -> str:
        result = harness.start_session(session_id).run(content, on_notification=on_notification)
        reason = getattr(result, "finish_reason", None)
        return _FINISH_REASONS.get(reason, "failed")

    @staticmethod
    def close(harness: Any) -> None:
        harness.close()

    @staticmethod
    def observe(notification: object, *, root_session_id: str) -> RuntimeObservation:
        if not isinstance(notification, Notification) or not isinstance(notification.payload, dict):
            return RuntimeObservation(kind="ignored")
        payload = notification.payload
        if notification.method in {"subagent.started", "subagent.finished"}:
            parent = payload.get("parentSessionId")
            child = payload.get("childSessionId")
            valid = all(isinstance(value, str) and value for value in (parent, child))
            return RuntimeObservation(
                kind=("subagent.started" if notification.method == "subagent.started" else "subagent.finished")
                if valid else "ignored",
                session_id=parent if isinstance(parent, str) else None,
                root_session=parent == root_session_id,
                runtime_activity=valid,
                parent_session_id=parent if isinstance(parent, str) else None,
                child_session_id=child if isinstance(child, str) else None,
            )
        session_id = payload.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            return RuntimeObservation(kind="ignored")
        is_root = session_id == root_session_id
        if notification.method == "session.status":
            status = payload.get("status")
            return RuntimeObservation(
                kind="session.status" if status in _SESSION_STATUSES else "ignored",
                session_id=session_id, root_session=is_root,
                status=status if status in _SESSION_STATUSES else None,
            )
        if notification.method != "session.event":
            return RuntimeObservation(kind="ignored", session_id=session_id, root_session=is_root)
        event = payload.get("event")
        if not isinstance(event, dict):
            return RuntimeObservation(kind="ignored", session_id=session_id, root_session=is_root)
        event_type = event.get("type")
        data = event.get("data")
        if not isinstance(event_type, str) or not isinstance(data, dict):
            return RuntimeObservation(kind="ignored", session_id=session_id, root_session=is_root)
        if event_type == "agent/inbox/spliced":
            return RuntimeObservation(kind="prompt.receipt", session_id=session_id, root_session=is_root)
        if event_type == "assistant/chunk":
            chunk = data.get("chunk")
            active = (
                isinstance(chunk, dict) and chunk.get("type") in {"text-delta", "reasoning-delta"}
                and isinstance(chunk.get("text"), str) and bool(chunk["text"])
            )
            return RuntimeObservation(kind="private.activity", session_id=session_id, root_session=is_root, runtime_activity=active)
        if event_type in {"step/start", "step/end"}:
            return RuntimeObservation(kind="private.activity", session_id=session_id, root_session=is_root, runtime_activity=True)
        if event_type == "turn/start":
            return RuntimeObservation(kind="turn.start", session_id=session_id, root_session=is_root, runtime_activity=True)
        if event_type == "turn/end":
            reason = data.get("reason")
            value = reason.get("kind") if isinstance(reason, dict) else None
            return RuntimeObservation(
                kind="turn.end", session_id=session_id, root_session=is_root,
                runtime_activity=True, terminal_reason=_FINISH_REASONS.get(value, "failed"),
            )
        if event_type == "assistant/message":
            return _assistant_observation(data, session_id=session_id, is_root=is_root)
        if event_type == "tool/call":
            call_id, name = data.get("callId"), data.get("name")
            valid = isinstance(call_id, str) and bool(call_id) and isinstance(name, str) and bool(name)
            return RuntimeObservation(
                kind="tool.call" if valid else "ignored", session_id=session_id, root_session=is_root,
                runtime_activity=valid, call_id=call_id if isinstance(call_id, str) else None,
                tool_name=name if isinstance(name, str) else None,
            )
        if event_type == "tool/result":
            return _tool_result_observation(data, session_id=session_id, is_root=is_root)
        return RuntimeObservation(kind="ignored", session_id=session_id, root_session=is_root)


def _assistant_observation(data: dict[str, Any], *, session_id: str, is_root: bool) -> RuntimeObservation:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if not isinstance(content, list):
        return RuntimeObservation(kind="ignored", session_id=session_id, root_session=is_root)
    has_tool_call = any(isinstance(block, dict) and block.get("type") == "tool-call" for block in content)
    text = "" if has_tool_call else "".join(
        block.get("text", "") for block in content
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
    ).strip()
    message_id = message.get("id") if isinstance(message, dict) else data.get("messageId")
    return RuntimeObservation(
        kind="assistant.message", session_id=session_id, root_session=is_root, runtime_activity=True,
        message_id=message_id if isinstance(message_id, str) and message_id else None,
        answer_text=text or None, usage=_normalized_usage(data.get("usage")),
    )


def _tool_result_observation(data: dict[str, Any], *, session_id: str, is_root: bool) -> RuntimeObservation:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return RuntimeObservation(kind="ignored", session_id=session_id, root_session=is_root)
    completed: list[str] = []
    selected: dict[str, Any] | None = None
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool-result":
            continue
        call_id = block.get("toolCallId")
        if isinstance(call_id, str) and call_id:
            completed.append(call_id)
            if selected is None:
                selected = block
    if selected is None:
        return RuntimeObservation(kind="ignored", session_id=session_id, root_session=is_root)
    call_id = selected.get("toolCallId")
    return RuntimeObservation(
        kind="tool.result", session_id=session_id, root_session=is_root, runtime_activity=True,
        call_id=call_id if isinstance(call_id, str) else None,
        tool_failed=selected.get("isError") is True, tool_result=_parse_tool_result(selected),
        completed_call_ids=tuple(completed),
    )


def _parse_tool_result(block: dict[str, Any]) -> dict[str, Any] | None:
    content = block.get("content")
    if not isinstance(content, list):
        return None
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str):
            continue
        try:
            value = json.loads(item["text"])
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _normalized_usage(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, int] = {}
    for source, target in _USAGE_FIELDS.items():
        amount = value.get(source, 0)
        if isinstance(amount, bool) or not isinstance(amount, int) or not 0 <= amount <= 1_000_000_000:
            return {}
        normalized[target] = amount
    return normalized
