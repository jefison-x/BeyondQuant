"""Strict provider SSE completion and usage facts for a future ACP judgment gate.

This parser never authorizes a retry or treats a partial stream as a completed
provider attempt. It does not receive ACP context-window ``usage_update``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

UNKNOWN = "unknown"
MAX_SSE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class AcpProviderStreamReceipt:
    terminal: str  # completed, incomplete, unknown
    actual_input_tokens: int | str = UNKNOWN
    actual_output_tokens: int | str = UNKNOWN
    actual_cache_read_tokens: int | str = UNKNOWN
    actual_cache_write_tokens: int | str = UNKNOWN

    @property
    def usage_state(self) -> str:
        values = (self.actual_input_tokens, self.actual_output_tokens,
                  self.actual_cache_read_tokens, self.actual_cache_write_tokens)
        known = sum(type(value) is int for value in values)
        return "known" if known == len(values) else "partial" if known else "unknown"

    @property
    def output_proven(self) -> bool:
        return self.terminal == "completed" and type(self.actual_output_tokens) is int


def _number(value: object) -> int | str:
    return value if type(value) is int and value >= 0 else UNKNOWN


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value: dict = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate provider response field")
        value[key] = item
    return value


def _events(body: bytes) -> list[tuple[str | None, dict | str]]:
    if not body or len(body) > MAX_SSE_BYTES:
        raise ValueError("provider stream size is invalid")
    text = body.decode("utf-8").replace("\r\n", "\n")
    if not text.endswith("\n\n"):
        raise ValueError("provider stream ended in an unterminated frame")
    events: list[tuple[str | None, dict | str]] = []
    for frame in text.split("\n\n"):
        if not frame.strip():
            continue
        event_name: str | None = None
        data: list[str] = []
        for line in frame.split("\n"):
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                if event_name is not None:
                    raise ValueError("duplicate provider event name")
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif line:
                raise ValueError("invalid provider stream field")
        if not data:
            if event_name is not None:
                raise ValueError("provider event has no data")
            continue
        payload = "\n".join(data)
        if payload == "[DONE]":
            events.append((event_name, payload))
            continue
        value = json.loads(payload, object_pairs_hook=_unique_object)
        if not isinstance(value, dict):
            raise ValueError("provider stream event is not an object")
        if event_name and (not isinstance(value.get("type"), str)
                           or value["type"] != event_name):
            raise ValueError("provider stream event name differs from body")
        events.append((event_name, value))
    if not events:
        raise ValueError("provider stream has no events")
    return events


def _receipt(terminal: str, usage: dict) -> AcpProviderStreamReceipt:
    return AcpProviderStreamReceipt(
        terminal=terminal,
        actual_input_tokens=_number(usage.get("input")),
        actual_output_tokens=_number(usage.get("output")),
        actual_cache_read_tokens=_number(usage.get("cache_read")),
        actual_cache_write_tokens=_number(usage.get("cache_write")),
    )


def _included_cache_usage(total: object, cache_read: object, cache_write: object) -> tuple[int, int, int] | None:
    """Split total input into the disjoint fields used by the pinned pi-ai SDK."""
    if any(_number(value) == UNKNOWN for value in (total, cache_read, cache_write)):
        return None
    if cache_read + cache_write > total:
        return None
    return total - cache_read - cache_write, cache_read, cache_write


def _response_usage(usage: dict, response: object) -> bool:
    current = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(current, dict):
        return True
    details = current.get("input_tokens_details")
    if details is not None and not isinstance(details, dict):
        return False
    details = details or {}
    normalized = _included_cache_usage(current.get("input_tokens"),
                                       details.get("cached_tokens", 0),
                                       details.get("cache_write_tokens", 0))
    if normalized is None:
        return False
    usage.update({"input": normalized[0], "output": current.get("output_tokens"),
                  "cache_read": normalized[1], "cache_write": normalized[2]})
    return True


def parse_acp_provider_stream(
    *, protocol: str, content_type: str, body: bytes,
) -> AcpProviderStreamReceipt:
    """Parse one complete HTTP body without converting missing usage to zero.

    A caller must separately prove HTTP 2xx, transport completion, selected
    route, deadline and declared-output admission before considering forwarding.
    """
    if (protocol not in {"chat", "responses", "messages"}
            or content_type.split(";", 1)[0].strip().lower() != "text/event-stream"):
        return AcpProviderStreamReceipt(UNKNOWN)
    try:
        events = _events(body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return AcpProviderStreamReceipt(UNKNOWN)

    usage: dict = {}
    terminal = UNKNOWN
    saw_start = False
    saw_terminal_event = False
    stop_reason: str | None = None
    messages_final_output_missing = False
    for event_name, value in events:
        if saw_terminal_event:
            # Responses and Messages have one terminal event. Chat may put
            # [DONE] after its final usage chunk, but nothing follows [DONE].
            return AcpProviderStreamReceipt(UNKNOWN)
        if value == "[DONE]":
            if protocol != "chat":
                return AcpProviderStreamReceipt(UNKNOWN)
            saw_terminal_event = True
            terminal = ("completed" if stop_reason in {"stop", "end", "tool_calls", "function_call"}
                        else "incomplete" if stop_reason in {"length", "content_filter", "network_error"}
                        else UNKNOWN)
            continue
        if not isinstance(value, dict):
            return AcpProviderStreamReceipt(UNKNOWN)
        kind = value.get("type", event_name)
        if protocol in {"responses", "messages"} and not isinstance(kind, str):
            return AcpProviderStreamReceipt(UNKNOWN)
        if (protocol == "chat" and kind in {"response.completed", "response.incomplete",
                                             "response.failed", "message_stop"}) \
                or (protocol == "responses" and kind in {"message_start", "message_delta", "message_stop"}) \
                or (protocol == "messages" and kind in {"response.completed", "response.incomplete",
                                                        "response.failed"}):
            return AcpProviderStreamReceipt(UNKNOWN)
        if kind in {"error", "response.failed", "response.incomplete"}:
            if protocol == "responses":
                if not _response_usage(usage, value.get("response")):
                    return AcpProviderStreamReceipt(UNKNOWN)
            saw_terminal_event = True
            terminal = "incomplete"
            continue
        if protocol == "chat":
            choices = value.get("choices")
            if isinstance(choices, list) and len(choices) > 1:
                return AcpProviderStreamReceipt(UNKNOWN)
            choice = choices[0] if isinstance(choices, list) and choices \
                and isinstance(choices[0], dict) else None
            reason = choice.get("finish_reason") if choice is not None else None
            if reason is not None:
                if not isinstance(reason, str) or (stop_reason is not None and stop_reason != reason):
                    return AcpProviderStreamReceipt(UNKNOWN)
                stop_reason = reason
            current = value.get("usage")
            if not isinstance(current, dict):
                current = choice.get("usage") if choice is not None else None
            # A usage field in an earlier content chunk may be provisional.
            # Accept only a finish chunk or a subsequent usage-only chunk.
            final_usage_chunk = reason is not None or (stop_reason is not None and choices == [])
            if isinstance(current, dict) and final_usage_chunk:
                details = current.get("prompt_tokens_details")
                if details is not None and not isinstance(details, dict):
                    return AcpProviderStreamReceipt(UNKNOWN)
                details = details or {}
                normalized = _included_cache_usage(
                    current.get("prompt_tokens"),
                    details.get("cached_tokens", current.get("prompt_cache_hit_tokens",
                                                               current.get("cached_tokens", 0))),
                    details.get("cache_write_tokens", 0))
                if normalized is None:
                    return AcpProviderStreamReceipt(UNKNOWN)
                observed_fields = {"input": normalized[0],
                                   "output": _number(current.get("completion_tokens")),
                                   "cache_read": normalized[1], "cache_write": normalized[2]}
                for field, observed in observed_fields.items():
                    prior = usage.get(field)
                    if observed == UNKNOWN or (type(prior) is int and observed < prior):
                        return AcpProviderStreamReceipt(UNKNOWN)
                    usage[field] = observed
        elif protocol == "responses":
            if kind == "response.completed":
                saw_terminal_event = True
                response = value.get("response")
                if not isinstance(response, dict) or response.get("status") != "completed":
                    return AcpProviderStreamReceipt(UNKNOWN)
                if not _response_usage(usage, response):
                    return AcpProviderStreamReceipt(UNKNOWN)
                terminal = "completed"
        elif kind == "message_start":
            if saw_start:
                return AcpProviderStreamReceipt(UNKNOWN)
            saw_start = True
            message = value.get("message")
            current = message.get("usage") if isinstance(message, dict) else None
            if isinstance(current, dict):
                for key in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                            "cache_creation_input_tokens"):
                    if key in current and _number(current[key]) == UNKNOWN:
                        return AcpProviderStreamReceipt(UNKNOWN)
                usage.update({"input": current.get("input_tokens"),
                              "cache_read": current.get("cache_read_input_tokens"),
                              "cache_write": current.get("cache_creation_input_tokens")})
        elif kind == "message_delta":
            if not saw_start:
                return AcpProviderStreamReceipt(UNKNOWN)
            current = value.get("usage")
            delta = value.get("delta")
            reason = delta.get("stop_reason") if isinstance(delta, dict) else None
            if reason is not None:
                if not isinstance(reason, str) or (stop_reason is not None and stop_reason != reason):
                    return AcpProviderStreamReceipt(UNKNOWN)
                stop_reason = reason
                if not isinstance(current, dict) or "output_tokens" not in current:
                    messages_final_output_missing = True
            if isinstance(current, dict):
                for field, key in (("input", "input_tokens"), ("output", "output_tokens"),
                                   ("cache_read", "cache_read_input_tokens"),
                                   ("cache_write", "cache_creation_input_tokens")):
                    if key in current and current[key] is not None:
                        prior = usage.get(field)
                        observed = _number(current[key])
                        if observed == UNKNOWN or (type(prior) is int and observed < prior):
                            return AcpProviderStreamReceipt(UNKNOWN)
                        usage[field] = current[key]
        elif kind == "message_stop":
            saw_terminal_event = True
            if not saw_start:
                return AcpProviderStreamReceipt(UNKNOWN)
            terminal = ("completed" if stop_reason in {"end_turn", "tool_use", "pause_turn", "stop_sequence"}
                        else "incomplete" if stop_reason in {"max_tokens", "refusal", "sensitive"}
                        else UNKNOWN)
    if protocol == "messages" and messages_final_output_missing:
        usage.pop("output", None)
    return _receipt(terminal, usage)
