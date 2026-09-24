#!/usr/bin/env python3
"""ADR-0086 request-scoped provider gate negative controls (host, no carrier).

Builds a real request-scoped gate and drives real HTTP requests through the real
loopback proxy to prove every dimension refuses an over-budget, over-limit or
late request BEFORE/INSTEAD OF forwarding it to the provider. Returns a
machine-readable record; the P4-B observer requires every control to be blocked.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.research_request_gate import RequestGateBlocked, RequestGateProxy, ResearchRequestGate
from packages.contracts.research_request_budget import stage_request_limits, validate_request_budget

SCHEMA_VERSION = "byq-p4b-request-gate-negative-controls.v1"


def _body(*, root: bool = True, max_tokens: int | None = 100, tools_desc: str = "d",
          messages_extra: int = 0, extra_fields: dict | None = None) -> bytes:
    name = "byq_research_judgment_turn" if root else "mcp__byq__byq_research_get"
    body = {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "judge" * (1 + messages_extra)}],
        "tools": [{"type": "function", "function": {"name": name, "description": tools_desc}}],
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if extra_fields:
        body.update(extra_fields)
    return json.dumps(body).encode()


def _limits(*, stage: str = "strategy_draft", deadline_at_ms: int | None = None) -> dict:
    limits = stage_request_limits(
        stage, request_id="byq-judgment-negative", started_at_ms=int(time.time() * 1000))
    if deadline_at_ms is not None:
        limits = {**limits, "deadline_at_ms": deadline_at_ms}
    return validate_request_budget(limits)


def _gate(limits: dict | None = None) -> ResearchRequestGate:
    return ResearchRequestGate(limits or _limits())


def _sse_usage(prompt: int, completion: int) -> bytes:
    chunk = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": prompt, "completion_tokens": completion}}
    return (f"data: {json.dumps(chunk)}\n\n" + "data: [DONE]\n\n").encode()


class _Upstream(BaseHTTPRequestHandler):
    hits = 0
    mode = "ok"
    delay = 0.0

    def log_message(self, *args: object) -> None:  # noqa: N802
        return

    def do_POST(self) -> None:  # noqa: N802
        self.rfile.read(int(self.headers.get("content-length") or "0"))
        self.__class__.hits += 1
        if self.__class__.delay:
            time.sleep(self.__class__.delay)
        if self.__class__.mode == "over_limit":
            payload = _sse_usage(5, 999999)
        elif self.__class__.mode == "no_usage":
            payload = b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        else:
            payload = _sse_usage(5, 5)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _serve(mode: str = "ok", delay: float = 0.0):
    _Upstream.hits = 0
    _Upstream.mode = mode
    _Upstream.delay = delay
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _proxy_post(proxy: RequestGateProxy, body: bytes) -> int:
    request = urllib.request.Request(
        proxy.base_url + "/chat/completions", data=body, method="POST",
        headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def run() -> dict:
    controls: list[dict] = []

    # Provider-call bound: the fourth request is refused at the boundary.
    server, upstream = _serve()
    _Upstream.hits = 0
    with RequestGateProxy(_gate(), upstream) as proxy:
        admitted = [_proxy_post(proxy, _body(root=True)),
                    _proxy_post(proxy, _body(root=False)),
                    _proxy_post(proxy, _body(root=True))]
        fourth = _proxy_post(proxy, _body(root=True))
        controls.append({"name": "provider_call_limit", "blocked": fourth == 429,
                         "status": fourth, "admitted_statuses": admitted,
                         "upstream_hits": _Upstream.hits})
    server.shutdown()
    server.server_close()

    # Output-token hard limit: a provider-proven over-limit result is discarded.
    server, upstream = _serve(mode="over_limit")
    with RequestGateProxy(_gate(), upstream) as proxy:
        status = _proxy_post(proxy, _body(max_tokens=4))
    server.shutdown()
    server.server_close()
    controls.append({"name": "output_tokens_exceeded", "blocked": status == 502, "status": status})

    # Unprovable actual usage: ADR-0086 §3 requires fail closed, not forwarding.
    server, upstream = _serve(mode="no_usage")
    with RequestGateProxy(_gate(), upstream) as proxy:
        status = _proxy_post(proxy, _body())
    server.shutdown()
    server.server_close()
    controls.append({"name": "actual_usage_unknown", "blocked": status == 502, "status": status})

    # Deadline bounds the upstream: a slow upstream result is never forwarded.
    server, upstream = _serve(delay=1.0)
    short = _gate(_limits(deadline_at_ms=int(time.time() * 1000) + 150))
    with RequestGateProxy(short, upstream) as proxy:
        status = _proxy_post(proxy, _body())
    server.shutdown()
    server.server_close()
    controls.append({"name": "deadline_upstream_timeout", "blocked": status == 504, "status": status})

    # Pure pre-request controls.
    over_input = _gate()
    try:
        over_input.before_request(_body(messages_extra=200000))
        blocked, reason = False, None
    except RequestGateBlocked as error:
        blocked, reason = True, error.reason
    controls.append({"name": "input_bytes_limit", "blocked": blocked, "reason": reason})

    over_tool = _gate()
    try:
        over_tool.before_request(_body(tools_desc="d" * 70000))
        blocked, reason = False, None
    except RequestGateBlocked as error:
        blocked, reason = True, error.reason
    controls.append({"name": "tool_payload_limit", "blocked": blocked, "reason": reason})

    expired = ResearchRequestGate(_limits(deadline_at_ms=int(time.time() * 1000) - 1))
    try:
        expired.before_request(_body())
        blocked, reason = False, None
    except RequestGateBlocked as error:
        blocked, reason = True, error.reason
    controls.append({"name": "deadline_exceeded", "blocked": blocked, "reason": reason})

    cancelled = _gate()
    cancelled.cancel()
    try:
        cancelled.before_request(_body())
        blocked, reason = False, None
    except RequestGateBlocked as error:
        blocked, reason = True, error.reason
    controls.append({"name": "cancelled", "blocked": blocked, "reason": reason})

    concurrent = _gate()
    first = concurrent.before_request(_body())
    try:
        concurrent.before_request(_body(root=False))
        blocked, reason = False, None
    except RequestGateBlocked as error:
        blocked, reason = True, error.reason
    finally:
        concurrent.complete(first, status=200, body=_sse_usage(5, 5))
    controls.append({"name": "concurrency_limit", "blocked": blocked, "reason": reason})

    # ADR-0086 §1: the named profile is BYQ-trusted and closed; unknown stage /
    # profile, a caller override or a forged/raised budget must fail closed.
    def _refused(fn) -> bool:
        try:
            fn()
            return False
        except ValueError:
            return True

    limits = _limits()
    controls.append({"name": "profile_unknown_stage", "blocked": _refused(
        lambda: stage_request_limits("waiting_for_data", request_id="x", started_at_ms=1))})
    controls.append({"name": "profile_caller_override", "blocked": _refused(
        lambda: stage_request_limits("strategy_draft", request_id="x", started_at_ms=1,
                                     profile="final-selection-bounded.v1"))})
    controls.append({"name": "profile_unknown_id", "blocked": _refused(
        lambda: validate_request_budget({**limits, "profile_id": "unknown-profile.v1"}))})
    controls.append({"name": "profile_forged_raised_limit", "blocked": _refused(
        lambda: validate_request_budget({**limits, "max_provider_calls": 99}))})
    controls.append({"name": "profile_missing_field", "blocked": _refused(
        lambda: validate_request_budget({k: v for k, v in limits.items() if k != "evidence"}))})
    controls.append({"name": "profile_forged_evidence", "blocked": _refused(
        lambda: validate_request_budget({**limits, "evidence": "forged audit basis"}))})

    # ADR-0086 acceptance: an undeclared/zero/bool/negative/conflicting output
    # ceiling fails closed BEFORE the request; the upstream is never hit.
    for name, body in (
        ("declared_output_limit_missing", _body(max_tokens=None)),
        ("declared_output_limit_missing_child", _body(root=False, max_tokens=None)),
        ("declared_output_limit_invalid", _body(max_tokens=0)),
        ("declared_output_limit_invalid_bool", _body(max_tokens=True)),
        ("declared_output_limit_conflict", _body(extra_fields={"max_completion_tokens": 200})),
        ("declared_output_limit_exceeds_profile", _body(max_tokens=8193)),
    ):
        server, upstream = _serve()
        with RequestGateProxy(_gate(), upstream) as proxy:
            status = _proxy_post(proxy, body)
        server.shutdown()
        server.server_close()
        controls.append({"name": name, "blocked": status == 429 and _Upstream.hits == 0,
                         "status": status, "upstream_hits": _Upstream.hits})

    request_scoped = _gate()
    fresh = _gate()
    for _ in range(3):
        receipt = request_scoped.before_request(_body())
        request_scoped.complete(receipt, status=200, body=_sse_usage(5, 5))
    fresh_admitted = fresh.before_request(_body())
    controls.append({
        "name": "request_scoped_fresh_counters", "blocked": False,
        "reason": None, "fresh_request_admitted": fresh_admitted["admitted"]})

    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_class": "host-negative-control",
        "controls": controls,
        "all_blocked": all(c["blocked"] for c in controls
                           if c["name"] != "request_scoped_fresh_counters"),
        "request_scoped_fresh_counters": fresh_admitted["admitted"],
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
