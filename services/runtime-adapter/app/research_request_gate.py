"""ADR-0086 request-scoped provider boundary gate.

The Runtime Adapter is trusted BYQ infrastructure. For ONE named bounded
research-judgment request this module opens a request-scoped gate at the provider
boundary: the DSH harness is pointed at a loopback proxy that forwards to the real
provider only after the gate admits the request. Because every root and child
provider request must traverse this boundary, the gate covers both roles and runs
BEFORE the request is issued.

The gate is deliberately request-scoped, not a cross-process persistent business
balance. Each judgment request builds a fresh gate with fresh counters; the
durable stage-call admission ledger is untouched and keeps its own identity /
idempotency / audit semantics. An interrupted request is never auto-resent here.

Dimensions (all hard, fail closed, first exceeded wins):
``provider_calls`` / ``attempts`` / ``input_bytes`` / ``declared_max_output_tokens``
/ ``tool_payload_bytes`` / ``deadline`` / ``concurrency`` / ``cancelled``.

ADR-0086 §3: the configured ceiling is NEVER reported as actual consumption. The
pre-request receipt records the *declared* ceiling; the completion receipt records
the provider-reported actual input/cache/output tokens and elapsed time, or a
structured ``unknown`` when the provider proves nothing. A response whose proven
actual output exceeds the declared ceiling is discarded and the request fails
closed; a response that arrives after the deadline is never forwarded.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from packages.contracts.research_request_budget import (
    JUDGMENT_STAGES,
    request_budget_decision,
    stage_request_limits,
)

PERSONA_TOOL = "byq_research_judgment_turn"
JOURNAL_SCHEMA = "research-request-gate-journal.v1"
UNKNOWN = "unknown"

# Closed completion reasons. ``actual_usage_unknown`` means the provider proved
# no actual output usage, so ADR-0086 §3 requires the result to fail closed
# rather than be submitted as an unproven (potentially over-limit) judgment.
COMPLETION_REASONS = frozenset({
    "within_request_budget", "deadline_exceeded", "output_tokens_exceeded",
    "actual_usage_unknown",
})


class RequestGateBlocked(RuntimeError):
    """A provider request was refused before it was issued."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _canonical_bytes(value: object) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _tool_payload_bytes(parsed: dict) -> int:
    total = _canonical_bytes(parsed.get("tools") or [])
    messages = parsed.get("messages")
    if isinstance(messages, list):
        total += sum(_canonical_bytes(m) for m in messages
                     if isinstance(m, dict) and m.get("role") == "tool")
    return total


# Closed minimal provider-request header allowlist. The DSH provider is
# configured with ``apiKeyEnv`` (DEEPSEEK_API_KEY / OPENCODE_API_KEY) and the
# OpenAI-compatible adapters authenticate with ``Authorization: Bearer``; there
# is no repository/SDK evidence for ``x-api-key``, so it is NOT forwarded. BYQ
# product/internal tokens (``x-byq-*``), cookies and hop-by-hop headers are never
# forwarded, and no header VALUE is ever written to a receipt, log or evidence.
_FORWARDED_REQUEST_HEADERS = ("authorization", "content-type", "accept")

_DECLARED_OUTPUT_FIELDS = ("max_tokens", "max_completion_tokens", "max_output_tokens")

# Closed pre-request reasons for an unusable declared output ceiling.
DECLARED_LIMIT_REASONS = frozenset({
    "declared_output_limit_missing", "declared_output_limit_invalid",
    "declared_output_limit_conflict",
})


def forwarded_request_headers(incoming) -> dict:
    """Return only the allowlisted provider headers (never BYQ/internal secrets)."""

    allowed = set(_FORWARDED_REQUEST_HEADERS)
    forwarded: dict = {}
    for name, value in incoming.items():
        key = str(name).lower()
        if key in allowed and value:
            forwarded[key] = value
    return forwarded


def resolve_declared_output_tokens(parsed: object) -> tuple[int | None, str | None]:
    """Resolve the request's declared output-token ceiling or a closed reason.

    ADR-0086 acceptance requires EVERY provider call to declare its output-token
    ceiling. A missing, zero, boolean, negative, or conflicting declaration fails
    closed BEFORE the request is issued; the ceiling is never silently filled.
    """

    if not isinstance(parsed, dict):
        return None, "declared_output_limit_missing"
    present: list[int] = []
    for field in _DECLARED_OUTPUT_FIELDS:
        if field not in parsed or parsed[field] is None:
            continue
        value = parsed[field]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None, "declared_output_limit_invalid"
        present.append(value)
    if not present:
        return None, "declared_output_limit_missing"
    if len(set(present)) != 1:
        return None, "declared_output_limit_conflict"
    return present[0], None


def declared_output_tokens(parsed: object) -> int | None:
    return resolve_declared_output_tokens(parsed)[0]


def request_role(parsed: object, *, persona_tool: str = PERSONA_TOOL) -> str:
    """Root iff the bounded persona tool is offered; otherwise a child request."""

    if not isinstance(parsed, dict):
        return "child"
    tools = parsed.get("tools")
    if isinstance(tools, list):
        for item in tools:
            function = item.get("function") if isinstance(item, dict) else None
            if isinstance(function, dict) and function.get("name") == persona_tool:
                return "root"
    return "child"


def parse_response_usage(body: bytes) -> dict:
    """Provider-reported actual usage, or structured ``unknown`` when unprovable.

    Supports the two OpenAI-compatible response shapes the DSH runtime receives:
    a streamed SSE body whose final ``data:`` chunk carries ``usage``, and a
    non-streaming JSON body with a top-level ``usage``. Never infers usage from
    the declared ceiling: a missing ``usage`` block is reported as ``unknown`` for
    every dimension.
    """

    try:
        text = body.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return _unknown_usage()
    usage: dict | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("usage"), dict):
            usage = value["usage"]
    if usage is None:
        try:
            value = json.loads(text.strip())
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict) and isinstance(value.get("usage"), dict):
            usage = value["usage"]
    if usage is None:
        return _unknown_usage()
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    cache_read = usage.get("cache_read_input_tokens")
    if cache_read is None:
        details = usage.get("prompt_tokens_details")
        if isinstance(details, dict):
            cache_read = details.get("cached_tokens")
    return {
        "actual_input_tokens": input_tokens if isinstance(input_tokens, int) else UNKNOWN,
        "actual_cache_read_tokens": cache_read if isinstance(cache_read, int) else UNKNOWN,
        "actual_output_tokens": output_tokens if isinstance(output_tokens, int) else UNKNOWN,
        "usage_source": "provider_response",
    }


def _unknown_usage() -> dict:
    return {"actual_input_tokens": UNKNOWN, "actual_cache_read_tokens": UNKNOWN,
            "actual_output_tokens": UNKNOWN, "usage_source": UNKNOWN}


class ResearchRequestGate:
    """Request-scoped counters and the pre/post-request admission decisions."""

    def __init__(self, limits: dict, *, journal: Path | None = None,
                 monotonic=time.monotonic, wall=time.time) -> None:
        self.limits = limits
        self._journal = journal
        self._monotonic = monotonic
        self._wall = wall
        self._lock = threading.Lock()
        self._provider_calls = 0
        self._attempts = 0
        self._inflight = 0
        self._cancelled = False
        self._receipts: list[dict] = []

    # ------------------------------------------------------------------ #
    # Request-scoped control
    # ------------------------------------------------------------------ #

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def receipts(self) -> list[dict]:
        with self._lock:
            return [{k: v for k, v in row.items() if not k.startswith("_")}
                    for row in self._receipts]

    def remaining_seconds(self) -> float:
        return (self.limits["deadline_at_ms"] - self._wall() * 1000) / 1000.0

    # ------------------------------------------------------------------ #
    # Provider boundary
    # ------------------------------------------------------------------ #

    def before_request(self, body: bytes, *, role: str | None = None) -> dict:
        """Admit or refuse ONE provider request before it is issued."""

        try:
            parsed = json.loads(body.decode() or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RequestGateBlocked("budget_invalid") from None
        if not isinstance(parsed, dict):
            raise RequestGateBlocked("budget_invalid")
        # ADR-0086 acceptance: every call must declare a usable output-token
        # ceiling BEFORE the request is issued. Missing/zero/bool/negative/
        # conflicting declarations fail closed here (never silently filled).
        declared_max, declared_reason = resolve_declared_output_tokens(parsed)
        if declared_reason is not None:
            raise RequestGateBlocked(declared_reason)
        detected = role or request_role(parsed)
        started = self._monotonic()
        with self._lock:
            self._provider_calls += 1
            self._attempts += 1
            usage = {
                "provider_calls": self._provider_calls,
                "input_bytes": len(body),
                "declared_max_output_tokens": declared_max,
                "tool_payload_bytes": _tool_payload_bytes(parsed),
                "attempts": self._attempts,
                "concurrent": self._inflight + 1,
                "now_ms": int(self._wall() * 1000),
                "cancelled": self._cancelled,
            }
            decision = request_budget_decision(self.limits, usage)
            receipt = {
                "schema_version": JOURNAL_SCHEMA, "phase": "admitted", "role": detected,
                "call": self._provider_calls, "attempt": self._attempts,
                "input_bytes": usage["input_bytes"],
                "declared_max_output_tokens": declared_max,
                "tool_payload_bytes": usage["tool_payload_bytes"],
                "admitted": decision["admit"], "reason": decision["reason"],
                "at_ms": usage["now_ms"], "_started": started,
            }
            self._receipts.append(receipt)
            if decision["admit"]:
                self._inflight += 1
            else:
                self._write_journal(receipt)
        if not decision["admit"]:
            raise RequestGateBlocked(decision["reason"])
        return receipt

    def complete(self, receipt: dict, *, status: int, body: bytes) -> dict:
        """Record actual usage and decide whether the response may be forwarded.

        The result is discarded when it arrives after the deadline, when the
        provider-proven actual output exceeds the declared hard ceiling, or when
        the provider proves no actual output usage at all. Missing usage is a
        structured ``unknown`` (never fabricated as 0 or the ceiling) and fails
        closed per ADR-0086 §3.
        """

        elapsed_ms = max(0, int((self._monotonic() - receipt.get("_started", self._monotonic()))
                                * 1000))
        actual = parse_response_usage(body)
        declared_max = int(receipt.get("declared_max_output_tokens") or 0)
        now_ms = int(self._wall() * 1000)
        late = now_ms >= self.limits["deadline_at_ms"]
        actual_output = actual["actual_output_tokens"]
        over_limit = isinstance(actual_output, int) and declared_max > 0 \
            and actual_output > declared_max
        if late:
            reason = "deadline_exceeded"
        elif over_limit:
            reason = "output_tokens_exceeded"
        elif not isinstance(actual_output, int):
            # ADR-0086 §3: an unprovable actual output may not be submitted.
            reason = "actual_usage_unknown"
        else:
            reason = None
        if reason is not None and reason not in COMPLETION_REASONS:
            raise ValueError("unknown request gate completion reason")
        with self._lock:
            self._inflight = max(0, self._inflight - 1)
            completed = {k: v for k, v in receipt.items() if not k.startswith("_")}
            completed.update({
                "phase": "completed", "status": status, "forwarded": reason is None,
                "reason": reason or "within_request_budget",
                "elapsed_ms": elapsed_ms, "completed_at_ms": now_ms,
                **actual,
            })
            self._receipts.append(completed)
            self._write_journal(completed)
        return {"forward": reason is None, "reason": reason, "elapsed_ms": elapsed_ms, **actual}

    # ------------------------------------------------------------------ #
    # Journal
    # ------------------------------------------------------------------ #

    def _write_journal(self, receipt: dict) -> None:
        if self._journal is None:
            return
        try:
            self._journal.parent.mkdir(parents=True, exist_ok=True)
            row = {k: v for k, v in receipt.items() if not k.startswith("_")}
            with self._journal.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            raise RequestGateBlocked("storage_failed") from None


class _GateProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: object) -> None:  # noqa: N802
        return

    def _failure(self, reason: str) -> None:
        payload = json.dumps({
            "error": {"type": "byq_request_gate_failed", "code": reason}}).encode()
        self.send_response(504 if reason == "deadline_exceeded" else 502)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or "0")
        body = self.rfile.read(length) if length else b""
        gate: ResearchRequestGate = self.server.gate  # type: ignore[attr-defined]
        upstream: str = self.server.upstream  # type: ignore[attr-defined]
        try:
            receipt = gate.before_request(body)
        except RequestGateBlocked as error:
            payload = json.dumps({
                "error": {"type": "byq_request_gate_blocked", "code": error.reason}}).encode()
            self.send_response(429)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        remaining = gate.remaining_seconds()
        if remaining <= 0:
            gate.complete(receipt, status=0, body=b"")
            self._failure("deadline_exceeded")
            return
        request = urllib.request.Request(
            upstream.rstrip("/") + self.path, data=body, method="POST",
            headers=forwarded_request_headers(self.headers))
        status = 502
        data = b""
        content_type = "application/json"
        timed_out = False
        try:
            # The upstream timeout is exactly the remaining deadline; it must
            # never exceed it (no artificial floor that could outlive the budget).
            with urllib.request.urlopen(request, timeout=remaining) as response:
                status = response.status
                content_type = response.headers.get("content-type", "application/json")
                data = response.read()
        except (socket.timeout, TimeoutError):
            timed_out = True
        except urllib.error.HTTPError as error:
            status = error.code
            content_type = error.headers.get("content-type", "application/json")
            data = error.read()
        except (urllib.error.URLError, OSError):
            timed_out = True
        completion = gate.complete(receipt, status=0 if timed_out else status, body=data)
        if timed_out:
            self._failure("deadline_exceeded")
            return
        if not completion["forward"]:
            # The response is discarded; its (over-limit or late) result is never
            # forwarded to the harness.
            self._failure(completion["reason"] or "deadline_exceeded")
            return
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class RequestGateProxy:
    """A loopback provider proxy enforcing one request-scoped gate."""

    def __init__(self, gate: ResearchRequestGate, upstream: str) -> None:
        self._gate = gate
        self._upstream = upstream
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _GateProxyHandler)
        self._server.gate = gate  # type: ignore[attr-defined]
        self._server.upstream = upstream  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "RequestGateProxy":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def build_request_gate(stage: str, *, request_id: str, journal: Path | None = None) -> ResearchRequestGate:
    """Build the closed request-scoped gate for one named judgment request."""

    if stage not in JUDGMENT_STAGES:
        raise ValueError("a deterministic research stage must not open a request gate")
    limits = stage_request_limits(
        stage, request_id=request_id, started_at_ms=int(time.time() * 1000))
    return ResearchRequestGate(limits, journal=journal)
