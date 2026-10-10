"""Small, offline test doubles for RuntimeAdapter lifecycle contracts.

These helpers exercise BYQ Adapter state and authority rules. They do not start
or emulate a DSH process and do not qualify an ACP transport or provider.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import SimpleNamespace
import uuid

from app.compat.types import RuntimeObservation, RuntimeToolResult
from packages.contracts.domain_call_admission import ACTIONS, parse_observed_arguments


def installed_sdk_version() -> str | None:
    """Return the SDK version only in the explicitly retained legacy test lane."""
    try:
        return version("deepseek-harness-sdk")
    except PackageNotFoundError:
        return None


@dataclass(frozen=True)
class NotificationDTO:
    """Structural event carrier for Adapter unit tests; no SDK class required."""

    method: str
    payload: dict


class FakeCompatibility:
    """Protocol test double around FakeHarness, not a runtime/harness implementation."""

    family = "test-runtime-observation.v1"
    product_slots = None

    def __init__(self, runtime_path: Path):
        self.runtime_path = runtime_path

    def runtime_command(self, _runtime_root: Path, _node: str) -> tuple[str, ...]:
        return (str(self.runtime_path),)

    def session_storage_root(self, base: Path, _workspace_id: str | None) -> Path:
        return base

    def build_harness(self, *, provider: str, model: str, composition: Path,
                      session_root: Path, runtime_command: tuple[str, ...],
                      environment: dict[str, str], max_tokens: int | None = None,
                      **_kwargs):
        from .test_process_cleanup import FakeHarness

        config = SimpleNamespace(provider=provider, model=model, composition=composition,
                                 session_root=session_root, runtime_command=runtime_command,
                                 env=dict(environment), max_tokens=max_tokens)
        return FakeHarness(config)

    @staticmethod
    def start(harness) -> None:
        harness.start()

    @staticmethod
    def create_session(harness, *, cwd: Path | str | None = None) -> str:
        _ = cwd
        native_id = "native-" + uuid.uuid4().hex
        harness.start_session(native_id)
        return native_id

    @staticmethod
    def resume_session(harness, native_session_id: str, *, cwd: Path | str | None = None) -> str:
        _ = cwd
        harness.start_session(native_session_id)
        return native_session_id

    @staticmethod
    def prepare_prompt(harness, session_id: str):
        harness.session_id = session_id
        return harness

    @staticmethod
    def run_prepared_prompt(session, content: str, on_notification) -> str:
        return session.run(content, on_notification=on_notification).finish_reason

    @staticmethod
    def cancel_session(harness, _native_session_id: str) -> None:
        harness.close()

    @staticmethod
    def close_session(harness, _native_session_id: str) -> None:
        harness.close()

    @staticmethod
    def close(harness) -> None:
        harness.close()

    @staticmethod
    def acknowledge_slot(_harness) -> None:
        return None

    @staticmethod
    def observe(notification: object, *, root_session_id: str) -> RuntimeObservation:
        if isinstance(notification, RuntimeObservation):
            return notification
        if not isinstance(notification, NotificationDTO) or not isinstance(notification.payload, dict):
            return RuntimeObservation(kind="ignored")
        payload = notification.payload
        session_id = payload.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            return RuntimeObservation(kind="ignored")
        root = session_id == root_session_id
        if notification.method == "session.status":
            status = payload.get("status")
            return RuntimeObservation(kind="session.status", session_id=session_id,
                                      root_session=root, status=status)
        event = payload.get("event")
        if notification.method != "session.event" or not isinstance(event, dict):
            return RuntimeObservation(kind="ignored", session_id=session_id, root_session=root)
        kind, data = event.get("type"), event.get("data")
        if not isinstance(data, dict):
            return RuntimeObservation(kind="ignored", session_id=session_id, root_session=root)
        common = {"session_id": session_id, "root_session": root,
                  "event_sequence": event.get("seq") if type(event.get("seq")) is int else None}
        if kind == "turn/start":
            return RuntimeObservation(kind="turn.start", runtime_activity=True, **common)
        if kind == "turn/end":
            reason = data.get("reason")
            reason_kind = reason.get("kind") if isinstance(reason, dict) else None
            terminal = {"completed": "completed", "aborted": "cancelled",
                        "cancelled": "cancelled", "error": "failed"}.get(reason_kind, "failed")
            return RuntimeObservation(kind="turn.end", runtime_activity=True,
                                      terminal_reason=terminal, **common)
        if kind in {"step/start", "step/end"}:
            return RuntimeObservation(kind="private.activity", runtime_activity=True, **common)
        if kind == "assistant/chunk":
            chunk = data.get("chunk")
            active = isinstance(chunk, dict) and bool(chunk.get("text"))
            return RuntimeObservation(kind="private.activity", runtime_activity=active, **common)
        if kind == "tool/call":
            call_id, name = data.get("callId"), data.get("name")
            valid = isinstance(call_id, str) and bool(call_id) and isinstance(name, str) and bool(name)
            arguments = data.get("arguments")
            domain_arguments = None
            if valid and name in {"mcp__byq__" + action for action in ACTIONS}:
                try:
                    domain_arguments = parse_observed_arguments(
                        arguments, action=name.removeprefix("mcp__byq__"))
                except ValueError:
                    domain_arguments = None
            registration_key = None
            if valid and name == "mcp__byq__byq_agent_run_start" and isinstance(arguments, str):
                try:
                    parsed = json.loads(arguments)
                except (ValueError, TypeError):
                    parsed = None
                key = parsed.get("idempotency_key") if isinstance(parsed, dict) else None
                if isinstance(key, str) and 1 <= len(key.strip()) <= 128:
                    registration_key = key.strip()
            return RuntimeObservation(kind="tool.call" if valid else "ignored",
                                      runtime_activity=valid, call_id=call_id if valid else None,
                                      tool_name=name if valid else None,
                                      registration_key=registration_key,
                                      domain_arguments=domain_arguments, **common)
        if kind == "assistant/message":
            message = data.get("message")
            blocks = message.get("content") if isinstance(message, dict) else data.get("content")
            text = "".join(block.get("text", "") for block in blocks or []
                           if isinstance(block, dict) and block.get("type") == "text"
                           and isinstance(block.get("text"), str)).strip()
            message_id = message.get("id") if isinstance(message, dict) else data.get("messageId")
            return RuntimeObservation(kind="assistant.message", runtime_activity=True,
                                      answer_text=text or None, message_id=message_id, **common)
        if kind == "tool/result":
            message = data.get("message")
            blocks = message.get("content") if isinstance(message, dict) else None
            results = []
            for block in blocks or []:
                if not isinstance(block, dict) or block.get("type") != "tool-result":
                    continue
                call_id = block.get("toolCallId")
                if not isinstance(call_id, str) or not call_id:
                    continue
                parsed = None
                for item in block.get("content", []):
                    if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                        try:
                            value = json.loads(item["text"])
                        except ValueError:
                            continue
                        if isinstance(value, dict):
                            parsed = value
                            break
                results.append(RuntimeToolResult(call_id, block.get("isError") is True, parsed))
            if not results:
                return RuntimeObservation(kind="ignored", **common)
            return RuntimeObservation(kind="tool.result", runtime_activity=True,
                                      call_id=results[0].call_id,
                                      tool_failed=results[0].failed, tool_result=results[0].result,
                                      completed_call_ids=tuple(item.call_id for item in results),
                                      tool_results=tuple(results), **common)
        return RuntimeObservation(kind="ignored", **common)
