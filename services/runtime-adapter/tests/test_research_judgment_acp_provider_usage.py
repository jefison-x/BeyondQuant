"""SSE terminal and provider-reported usage facts, with no external provider."""

from __future__ import annotations

import json

import pytest

from app.research_judgment_acp_provider_usage import parse_acp_provider_stream


def _sse(*events: tuple[str | None, dict | str]) -> bytes:
    frames = []
    for name, value in events:
        lines = [f"event: {name}"] if name else []
        lines.append("data: " + (value if isinstance(value, str) else json.dumps(value)))
        frames.append("\n".join(lines))
    return ("\n\n".join(frames) + "\n\n").encode()


def test_chat_complete_uses_final_stream_usage_and_done():
    body = _sse((None, {"choices": [{"finish_reason": "tool_calls"}], "usage": {
        "prompt_tokens": 12, "completion_tokens": 4,
        "prompt_tokens_details": {"cached_tokens": 3, "cache_write_tokens": 2}}}),
        (None, "[DONE]"))
    receipt = parse_acp_provider_stream(
        protocol="chat", content_type="text/event-stream; charset=utf-8", body=body)
    assert receipt.terminal == "completed"
    assert receipt.actual_input_tokens == 7
    assert receipt.actual_output_tokens == 4
    assert receipt.actual_cache_read_tokens == 3
    assert receipt.actual_cache_write_tokens == 2
    assert receipt.usage_state == "known"
    assert (receipt.actual_input_tokens + receipt.actual_cache_read_tokens
            + receipt.actual_cache_write_tokens) == 12
    assert receipt.output_proven is True


def test_chat_early_usage_does_not_replace_missing_final_receipt():
    body = _sse((None, {"choices": [{"finish_reason": None}],
                        "usage": {"prompt_tokens": 3, "completion_tokens": 1}}),
                (None, {"choices": [{"finish_reason": "stop"}]}),
                (None, "[DONE]"))
    receipt = parse_acp_provider_stream(
        protocol="chat", content_type="text/event-stream", body=body)
    assert receipt.terminal == "completed"
    assert receipt.actual_output_tokens == "unknown"
    assert receipt.output_proven is False


def test_chat_usage_only_chunk_after_finish_is_final_receipt():
    body = _sse((None, {"choices": [{"finish_reason": "tool_calls"}]}),
                (None, {"choices": [], "usage": {"prompt_tokens": 7,
                                                  "completion_tokens": 2}}),
                (None, "[DONE]"))
    receipt = parse_acp_provider_stream(
        protocol="chat", content_type="text/event-stream", body=body)
    assert receipt.terminal == "completed"
    assert receipt.actual_output_tokens == 2
    assert receipt.output_proven is True


def test_chat_decreasing_final_usage_is_unknown():
    body = _sse((None, {"choices": [{"finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 8, "completion_tokens": 5}}),
                (None, {"choices": [], "usage": {"prompt_tokens": 8,
                                                  "completion_tokens": 3}}),
                (None, "[DONE]"))
    receipt = parse_acp_provider_stream(
        protocol="chat", content_type="text/event-stream", body=body)
    assert receipt.terminal == "unknown"
    assert receipt.output_proven is False


def test_responses_requires_completed_response_usage_not_intermediate_usage():
    body = _sse(
        ("response.created", {"type": "response.created", "usage": {
            "input_tokens": 999, "output_tokens": 999}}),
        ("response.completed", {"type": "response.completed", "response": {
            "status": "completed", "usage": {"input_tokens": 21, "output_tokens": 6,
                                            "input_tokens_details": {"cached_tokens": 2,
                                                                     "cache_write_tokens": 3}}}}))
    receipt = parse_acp_provider_stream(
        protocol="responses", content_type="text/event-stream", body=body)
    assert receipt.terminal == "completed"
    assert (receipt.actual_input_tokens, receipt.actual_output_tokens,
            receipt.actual_cache_read_tokens, receipt.actual_cache_write_tokens) == (16, 6, 2, 3)
    assert (receipt.actual_input_tokens + receipt.actual_cache_read_tokens
            + receipt.actual_cache_write_tokens) == 21
    assert receipt.output_proven is True


@pytest.mark.parametrize("protocol,body", [
    ("chat", _sse((None, {"choices": [{"finish_reason": "stop"}], "usage": {
        "prompt_tokens": 4, "completion_tokens": 1,
        "prompt_tokens_details": {"cached_tokens": 5}}}), (None, "[DONE]"))),
    ("responses", _sse(("response.completed", {"type": "response.completed", "response": {
        "status": "completed", "usage": {"input_tokens": 4, "output_tokens": 1,
                                          "input_tokens_details": {"cache_write_tokens": 5}}}}))),
])
def test_cache_count_exceeding_total_never_proves_usage(protocol, body):
    receipt = parse_acp_provider_stream(
        protocol=protocol, content_type="text/event-stream", body=body)
    assert receipt.terminal == "unknown"
    assert receipt.output_proven is False


def test_messages_combines_start_and_final_delta_without_summing():
    body = _sse(
        ("message_start", {"type": "message_start", "message": {"usage": {
            "input_tokens": 8, "output_tokens": 0,
            "cache_read_input_tokens": 3, "cache_creation_input_tokens": 1}}}),
        ("message_delta", {"type": "message_delta", "usage": {"output_tokens": 2}}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use"},
                           "usage": {"output_tokens": 5}}),
        ("message_stop", {"type": "message_stop"}))
    receipt = parse_acp_provider_stream(
        protocol="messages", content_type="text/event-stream", body=body)
    assert receipt.terminal == "completed"
    assert (receipt.actual_input_tokens, receipt.actual_output_tokens,
            receipt.actual_cache_read_tokens, receipt.actual_cache_write_tokens) == (8, 5, 3, 1)
    assert receipt.usage_state == "known"
    assert receipt.output_proven is True


def test_messages_decreasing_cumulative_usage_is_unknown():
    body = _sse(
        ("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 8}}}),
        ("message_delta", {"type": "message_delta", "usage": {"output_tokens": 5}}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                           "usage": {"output_tokens": 3}}),
        ("message_stop", {"type": "message_stop"}))
    receipt = parse_acp_provider_stream(
        protocol="messages", content_type="text/event-stream", body=body)
    assert receipt.terminal == "unknown"
    assert receipt.output_proven is False


@pytest.mark.parametrize("protocol,body", [
    ("chat", _sse((None, {"usage": {"prompt_tokens": 4, "completion_tokens": 2}}))),
    ("responses", _sse(("response.created", {"type": "response.created", "usage": {
        "input_tokens": 4, "output_tokens": 2}}))),
    ("messages", _sse(("message_start", {"type": "message_start", "message": {
        "usage": {"input_tokens": 4, "output_tokens": 0}}}),
                       ("message_delta", {"type": "message_delta", "usage": {"output_tokens": 2}}))),
])
def test_truncated_stream_never_proves_terminal(protocol, body):
    receipt = parse_acp_provider_stream(
        protocol=protocol, content_type="text/event-stream", body=body)
    assert receipt.terminal == "unknown"
    assert receipt.output_proven is False


def test_messages_start_without_final_delta_does_not_prove_output_zero():
    body = _sse(("message_start", {"type": "message_start", "message": {
        "usage": {"input_tokens": 5, "output_tokens": 0}}}),
                ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}),
                ("message_stop", {"type": "message_stop"}))
    receipt = parse_acp_provider_stream(
        protocol="messages", content_type="text/event-stream", body=body)
    assert receipt.terminal == "completed"
    assert receipt.actual_output_tokens == "unknown"
    assert receipt.output_proven is False


def test_messages_early_output_without_final_delta_usage_remains_unknown():
    body = _sse(
        ("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 5}}}),
        ("message_delta", {"type": "message_delta", "usage": {"output_tokens": 5}}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}),
        ("message_stop", {"type": "message_stop"}))
    receipt = parse_acp_provider_stream(
        protocol="messages", content_type="text/event-stream", body=body)
    assert receipt.terminal == "completed"
    assert receipt.actual_output_tokens == "unknown"
    assert receipt.output_proven is False


@pytest.mark.parametrize("protocol,body", [
    ("responses", _sse(("response.incomplete", {"type": "response.incomplete"}))),
    ("responses", _sse(("response.failed", {"type": "response.failed"}))),
    ("messages", _sse(("error", {"type": "error"}))),
])
def test_provider_error_or_incomplete_terminal_is_not_success(protocol, body):
    receipt = parse_acp_provider_stream(
        protocol=protocol, content_type="text/event-stream", body=body)
    assert receipt.terminal == "incomplete"
    assert receipt.output_proven is False


def test_incomplete_responses_preserves_observed_usage_without_success():
    body = _sse(("response.incomplete", {"type": "response.incomplete", "response": {
        "status": "incomplete", "usage": {"input_tokens": 9, "output_tokens": 16}}}))
    receipt = parse_acp_provider_stream(
        protocol="responses", content_type="text/event-stream", body=body)
    assert receipt.terminal == "incomplete"
    assert (receipt.actual_input_tokens, receipt.actual_output_tokens) == (9, 16)
    assert receipt.output_proven is False


@pytest.mark.parametrize("protocol,body,terminal", [
    ("chat", _sse((None, {"choices": [{"finish_reason": "length"}],
                          "usage": {"prompt_tokens": 10, "completion_tokens": 32}}),
                       (None, "[DONE]")), "incomplete"),
    ("chat", _sse((None, {"choices": [], "usage": {"completion_tokens": 3}}),
                       (None, "[DONE]")), "unknown"),
    ("messages", _sse(
        ("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 4}}}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "max_tokens"},
                           "usage": {"output_tokens": 32}}),
        ("message_stop", {"type": "message_stop"})), "incomplete"),
    ("messages", _sse(
        ("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 4}}}),
        ("message_delta", {"type": "message_delta", "usage": {"output_tokens": 3}}),
        ("message_stop", {"type": "message_stop"})), "unknown"),
])
def test_missing_or_limit_stop_reason_does_not_prove_completion(protocol, body, terminal):
    receipt = parse_acp_provider_stream(
        protocol=protocol, content_type="text/event-stream", body=body)
    assert receipt.terminal == terminal
    assert receipt.output_proven is False


@pytest.mark.parametrize("protocol,content_type,body", [
    ("chat", "application/json", _sse((None, "[DONE]"))),
    ("other", "text/event-stream", _sse((None, "[DONE]"))),
    ("chat", "text/event-stream", b"data: {bad json}\n\n"),
    ("chat", "text/event-stream", b'data: {"usage":{"prompt_tokens":1,"prompt_tokens":2}}\n\n'),
    ("chat", "text/event-stream", b'data: [DONE]\n'),
    ("chat", "text/event-stream", _sse(
        (None, {"choices": [{"finish_reason": "stop"}, {"finish_reason": None}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1}}),
        (None, "[DONE]"))),
    ("responses", "text/event-stream", _sse(("response.completed", {
        "type": "response.completed", "response": {"status": "incomplete",
                                                  "usage": {"output_tokens": 2}}}))),
    ("messages", "text/event-stream", _sse(("message_stop", {"type": "message_stop"}))),
    ("chat", "text/event-stream", b'event: error\n\ndata: {"choices":[{"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'),
    ("responses", "text/event-stream", _sse(
        ("response.failed", {"type": None}),
        ("response.completed", {"type": "response.completed", "response": {"status": "completed",
            "usage": {"input_tokens": 1, "output_tokens": 1}}}))),
    ("responses", "text/event-stream", _sse(
        (None, {"type": None}),
        ("response.completed", {"type": "response.completed", "response": {"status": "completed",
            "usage": {"input_tokens": 1, "output_tokens": 1}}}))),
    ("messages", "text/event-stream", _sse(
        ("message_start", {"type": "message_start", "message": {
            "usage": {"input_tokens": -1}}}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                           "usage": {"output_tokens": 1}}),
        ("message_stop", {"type": "message_stop"}))),
])
def test_malformed_or_mismatched_stream_is_unknown(protocol, content_type, body):
    receipt = parse_acp_provider_stream(protocol=protocol, content_type=content_type, body=body)
    assert receipt.terminal == "unknown"
    assert receipt.output_proven is False


def test_completed_chat_without_usage_remains_unknown_actual_not_zero():
    receipt = parse_acp_provider_stream(
        protocol="chat", content_type="text/event-stream",
        body=_sse((None, {"choices": [{"finish_reason": "stop"}]}), (None, "[DONE]")))
    assert receipt.terminal == "completed"
    assert receipt.actual_output_tokens == "unknown"
    assert receipt.usage_state == "unknown"
    assert receipt.output_proven is False
