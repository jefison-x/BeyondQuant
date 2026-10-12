"""Request-scoped provider boundary gates for current Clean Break paths.

The ADR-0090 task-ready profile reuses this measured HTTP boundary for one fresh
background request. It is enforced from the current shared continuation
contract, not by restoring an old cross-process budget. The existing named
research-judgment gate and its tests retain their established stage-specific
behavior; that archived ADR is not a general authority for continuation.

The continuation gate counts each request admitted to the upstream provider,
including retries and compaction, measures exact serialized request bytes,
per-call declared output and tool payloads, and records provider-reported
actual usage or explicit unknown/partial facts. Its 180 second deadline starts
at request admission and is also enforced by Runtime Adapter's owned-process
watchdog, including tool idle time.
"""

from __future__ import annotations

import http.client
import json
import os
import select
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
from packages.contracts.continuation_request import (
    ALLOWED_MODEL as CONTINUATION_MODEL,
    USAGE_SCHEMA_VERSION as CONTINUATION_USAGE_SCHEMA,
    request_limits as continuation_request_limits,
    validate_limits as validate_continuation_limits,
    validate_profile_binding,
    validate_request_usage,
)
from packages.contracts.product_turn_request import (
    validate_product_turn_limits,
    validate_product_turn_profile,
)

PERSONA_TOOL = "byq_research_judgment_turn"
JOURNAL_SCHEMA = "research-request-gate-journal.v1"
UNKNOWN = "unknown"

# Atomic provider-settlement classification for one request scope. Exactly one
# value is returned by :meth:`ResearchRequestGate.settlement_state`.
SETTLED_OK = "settled_ok"
KNOWN_BLOCKED = "known_blocked"
UNKNOWN_OR_UNPAIRED = "unknown_or_unpaired"

# The ADR-0106 PRE-DISPATCH request-budget limit guards. A sealed scope whose
# ONLY refusals are these reasons is a *known* budget exhaustion: every
# dispatched request has a matching known completion and the block was decided
# BEFORE dispatch (a rejected/aborted row with admitted False). `deadline_exceeded`
# is deliberately NOT here: it can also arrive post-dispatch as a
# completed-but-unforwarded response in `_complete_continuation_request`, which is
# a different (broader) case. Reasons outside this set (storage_failed, cancelled,
# budget_invalid, model_route_unqualified, provider_path_unqualified,
# declared_output_limit_*, client_disconnected, provider_outcome_unknown,
# provider_redirect_blocked, output_tokens_exceeded, concurrency_limit,
# queue_limit) are NOT budget exhaustion and must keep the session failed and
# fenced.
BUDGET_LIMIT_REASONS = frozenset({
    "provider_call_limit", "attempt_limit",
    "input_bytes_limit", "total_input_bytes_limit",
    "output_tokens_limit", "total_output_tokens_limit",
    "tool_payload_limit", "total_tool_payload_limit",
})

# Closed completion reasons for the retained named judgment request path. The
# ADR-0090 continuation path has a separate completion policy that preserves
# unknown usage without rewriting it as zero or rejecting a valid Job result.
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
    # Schemas, tool results, and earlier call arguments are all repeated provider
    # input; retries and compaction are measured again by the request gate.
    total = _canonical_bytes(parsed.get("tools") or [])
    messages = parsed.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            if message.get("role") == "tool":
                total += _canonical_bytes(message)
            calls = message.get("tool_calls")
            if isinstance(calls, list):
                total += _canonical_bytes(calls)
    return total


# Closed minimal provider-request header allowlist. The DSH provider is
# configured with ``apiKeyEnv`` (DEEPSEEK_API_KEY / OPENCODE_API_KEY) and the
# OpenAI-compatible adapters authenticate with ``Authorization: Bearer``; there
# is no repository/SDK evidence for ``x-api-key``, so it is NOT forwarded. BYQ
# product/internal tokens (``x-byq-*``), cookies and hop-by-hop headers are never
# forwarded, and no header VALUE is ever written to a receipt, log or evidence.
_FORWARDED_REQUEST_HEADERS = ("authorization", "content-type", "accept",
                              "x-opencode-session", "user-agent")

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

    Every provider call must declare its output-token ceiling. A missing, zero,
    boolean, negative, or conflicting declaration fails closed BEFORE the
    request is issued; the ceiling is never silently filled.
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
    every dimension. The continuation path preserves that unknown fact; the
    historical judgment completion policy separately decides whether to forward.
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
        "actual_input_tokens": input_tokens if type(input_tokens) is int and input_tokens >= 0 else UNKNOWN,
        "actual_cache_read_tokens": cache_read if type(cache_read) is int and cache_read >= 0 else UNKNOWN,
        "actual_output_tokens": output_tokens if type(output_tokens) is int and output_tokens >= 0 else UNKNOWN,
        "usage_source": "provider_response",
    }


def _unknown_usage() -> dict:
    return {"actual_input_tokens": UNKNOWN, "actual_cache_read_tokens": UNKNOWN,
            "actual_output_tokens": UNKNOWN, "usage_source": UNKNOWN}


class ResearchRequestGate:
    """Request-scoped provider gate for judgment and continuation profiles.

    Judgment limits keep their ADR-0086 contract. A continuation gate opens only
    from the closed ADR-0090 profile and measures serialized provider HTTP attempts,
    including DSH retry and compaction requests.
    """

    def __init__(self, limits: dict, *, journal: Path | None = None,
                 execution_profile: dict | None = None, request_id: str | None = None,
                 monotonic=time.monotonic, wall=time.time) -> None:
        self._monotonic = monotonic
        self._wall = wall
        # ADR-0106: the gate also serves the ordinary Product path under the
        # independent `product-turn.v1` profile. Both modes use the same
        # request-scoped cap decision; only the accepted profile/limits differ.
        self.product_turn = False
        self.execution_profile = None
        if execution_profile is not None:
            try:
                self.execution_profile = validate_profile_binding(execution_profile)
            except ValueError:
                self.execution_profile = validate_product_turn_profile(execution_profile)
                self.product_turn = True
        self.continuation_mode = self.execution_profile is not None
        self.limits = (validate_product_turn_limits(limits) if self.product_turn
                       else validate_continuation_limits(limits) if self.continuation_mode else limits)
        self.request_id = request_id
        self._journal = journal
        self._lock = threading.Lock()
        # One condition guards the single shared upstream slot. Parent and child
        # Agents in this owned process reach the same per-root proxy, so an
        # overlapping request serializes here instead of being refused. Close
        # and cancel wake a waiting request so it fails closed, never dispatching
        # late or replaying an unprovable upstream result.
        self._cond = threading.Condition(self._lock)
        self._gate_closed = False
        self._journal_failed = False
        # Set only when a DISPATCHED request's completion row could not be
        # persisted. Pre-dispatch write failures (admission/rejection) leave this
        # False: no provider call was issued, so the refusal is known.
        self._outcome_unknown = False
        self._waiting = 0
        self._provider_calls = 0
        self._attempts = 0
        self._inflight = 0
        self._cancelled = False
        self._receipts: list[dict] = []
        self._continuation_started = self._monotonic() if self.continuation_mode else None
        self._input_bytes_total = 0
        self._declared_output_tokens_total = 0
        self._tool_payload_bytes_total = 0
        self._max_input_bytes = 0
        self._max_declared_output_tokens = 0
        self._max_tool_payload_bytes = 0
        self._max_concurrent = 0
        self._actual_receipts: list[dict] = []
        self._limit_violations: set[str] = set()

    # ------------------------------------------------------------------ #
    # Request-scoped control
    # ------------------------------------------------------------------ #

    def cancel(self) -> None:
        with self._cond:
            self._cancelled = True
            self._cond.notify_all()

    def release_waiters(self) -> None:
        """Wake requests waiting for the upstream slot when the proxy closes.

        Fail-closed: a waiting request observes the closed gate and is refused
        before any dispatch. This never marks the request scope cancelled, so a
        normally completed judgment/continuation summary is not rewritten.
        """
        with self._cond:
            self._gate_closed = True
            self._cond.notify_all()

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    @property
    def waiting(self) -> int:
        """Requests currently serialized waiting to acquire the upstream slot.

        A deterministic synchronization point for tests and diagnostics: it is
        incremented before ``Condition.wait`` and decremented after the waiter
        wakes, so ``waiting > 0`` proves a request reached the gate and is
        queued rather than dispatched.
        """
        with self._lock:
            return self._waiting

    @property
    def journal_failed(self) -> bool:
        """Whether a durable journal write failed for this request scope.

        Once true the scope is fail-closed: no further request is dispatched,
        because the durable at-most-once evidence can no longer be trusted.
        """
        with self._lock:
            return self._journal_failed

    def receipts(self) -> list[dict]:
        with self._lock:
            return [{k: v for k, v in row.items() if not k.startswith("_")}
                    for row in self._receipts]

    @property
    def started_at(self) -> float | None:
        return self._continuation_started

    @property
    def deadline_monotonic(self) -> float | None:
        if not self.continuation_mode:
            return None
        return self._continuation_started + self.limits["deadline_ms"] / 1000.0

    def has_blocked_request(self) -> bool:
        with self._lock:
            return any(row.get("phase") == "rejected" or
                       (row.get("phase") == "completed" and not row.get("forwarded", True))
                       for row in self._receipts)

    def has_unknown_outcome(self) -> bool:
        """Whether a dispatched request has an unprovable outbound result.

        ADR-0105 §5: an unprovable outbound result keeps the execution receipt
        unresolved (`outcome_unknown`), distinct from a known redirect or
        output-limit block whose result is provable.

        A failed durable journal write for a DISPATCHED request also makes the
        result unprovable: the provider may have executed the request but its
        completion row could not be persisted, so the scope must not settle as a
        known outcome. A pre-dispatch write failure (no provider call issued) is
        a known refusal and does NOT set this.
        """
        with self._lock:
            return self._outcome_unknown or any(
                row.get("phase") == "completed"
                and row.get("reason") == "provider_outcome_unknown"
                for row in self._receipts)

    def settlement_state(self) -> str:
        with self._lock:
            return self._settlement_state_locked()

    def _settlement_state_locked(self) -> str:
        """Atomic classification of this scope's provider settlement.

        Evaluated in ONE lock acquisition so a late receipt cannot slip between
        separate checks. Returns exactly one of ``SETTLED_OK``,
        ``KNOWN_BLOCKED`` or ``UNKNOWN_OR_UNPAIRED``:

        * ``SETTLED_OK`` — the gate is sealed, nothing is in flight or waiting,
          the durable journal is intact, and every admitted
          ``(request_id, call, attempt)`` has exactly one matching completed
          receipt that was forwarded. A completed HTTP 200 response whose
          provider billing usage is missing is still settled: unknown usage is a
          recorded fact, not an unprovable outcome.
        * ``KNOWN_BLOCKED`` — a request was refused before dispatch (rejected or
          aborted), a completed response was provably not forwarded (redirect /
          output-limit), or a pre-dispatch journal write failed, with no
          unprovable or unpaired request. The outcome is known, not unknown.
        * ``UNKNOWN_OR_UNPAIRED`` — the seal is not proven, a request is still
          in flight or waiting, a dispatched completion could not be persisted,
          an outbound result is unprovable, or an admission has no unique
          matching completion. Callers must fail closed.

        Callers MUST hold ``self._lock`` (a non-reentrant lock); the public,
        self-locking wrapper is :meth:`settlement_state`.
        """
        if self._gate_closed is not True:
            return UNKNOWN_OR_UNPAIRED
        if (type(self._provider_calls) is not int or self._provider_calls < 0
                or type(self._attempts) is not int or self._attempts < 0
                or type(self._inflight) is not int or self._inflight < 0
                or type(self._waiting) is not int or self._waiting < 0
                or self._provider_calls != self._attempts
                or type(self._journal_failed) is not bool):
            return UNKNOWN_OR_UNPAIRED
        if self._inflight != 0 or self._waiting != 0:
            return UNKNOWN_OR_UNPAIRED
        if self._outcome_unknown is not False:
            return UNKNOWN_OR_UNPAIRED
        if not isinstance(self._receipts, list):
            return UNKNOWN_OR_UNPAIRED
        if self.continuation_mode and (
                not isinstance(self.request_id, str) or not self.request_id):
            return UNKNOWN_OR_UNPAIRED
        admitted: list[tuple[object, int, int]] = []
        completed: list[tuple[object, int, int]] = []
        blocked = self._journal_failed
        for row in self._receipts:
            if not isinstance(row, dict):
                return UNKNOWN_OR_UNPAIRED
            expected_schema = ("continuation-request-gate.v1" if self.continuation_mode
                               else JOURNAL_SCHEMA)
            if row.get("schema_version") != expected_schema:
                return UNKNOWN_OR_UNPAIRED
            phase = row.get("phase")
            if not isinstance(phase, str) or phase not in {
                    "admitted", "completed", "rejected", "aborted"}:
                return UNKNOWN_OR_UNPAIRED
            if self.continuation_mode and row.get("request_id") != self.request_id:
                return UNKNOWN_OR_UNPAIRED
            request_id = row.get("request_id")
            if request_id is not None and not isinstance(request_id, str):
                return UNKNOWN_OR_UNPAIRED
            if phase == "admitted":
                call, attempt = row.get("call"), row.get("attempt")
                if (row.get("admitted") is not True
                        or type(call) is not int or call <= 0
                        or type(attempt) is not int or attempt <= 0
                        or call != attempt):
                    return UNKNOWN_OR_UNPAIRED
                key = (request_id, call, attempt)
                admitted.append(key)
            elif phase == "completed":
                call, attempt = row.get("call"), row.get("attempt")
                if (row.get("admitted") is not True
                        or type(call) is not int or call <= 0
                        or type(attempt) is not int or attempt <= 0
                        or call != attempt):
                    return UNKNOWN_OR_UNPAIRED
                key = (request_id, call, attempt)
                if row.get("reason") == "provider_outcome_unknown":
                    return UNKNOWN_OR_UNPAIRED
                forwarded = row.get("forwarded")
                if forwarded is False:
                    blocked = True
                elif forwarded is not True:
                    return UNKNOWN_OR_UNPAIRED
                completed.append(key)
            elif phase in {"rejected", "aborted"}:
                # A request refused before dispatch is a known outcome.
                if row.get("admitted") is not False or not isinstance(row.get("reason"), str):
                    return UNKNOWN_OR_UNPAIRED
                blocked = True
        # Every admission must pair with exactly one completion carrying the
        # same (request_id, call, attempt); duplicate or substituted keys
        # must never be masked by matching totals.
        if (len(admitted) != len(set(admitted))
                or len(completed) != len(set(completed))
                or len(admitted) != self._provider_calls
                or len(admitted) != self._attempts
                or {key[1] for key in admitted} != set(range(1, self._provider_calls + 1))
                or set(admitted) != set(completed)):
            return UNKNOWN_OR_UNPAIRED
        return KNOWN_BLOCKED if blocked else SETTLED_OK

    def known_budget_block_reason(self) -> str | None:
        """Return a normalized PRE-DISPATCH budget-limit reason, or ``None``.

        The settlement classification AND the refusal receipts are read in ONE
        ``self._lock`` acquisition (via :meth:`_settlement_state_locked`) so a
        late ``_journal_failed`` / ``_outcome_unknown`` / in-flight / waiting
        mutation cannot yield a stale "known budget" verdict.

        Only a scope that is ``KNOWN_BLOCKED`` and whose ONLY refusals are
        pre-dispatch ADR-0106 budget limit guards (``phase`` rejected with
        ``admitted is False`` and a reason in :data:`BUDGET_LIMIT_REASONS`)
        qualifies. Post-dispatch completed-but-unforwarded responses
        (``deadline_exceeded``, ``provider_redirect_blocked``,
        ``output_tokens_exceeded``) are rejected, as are journal/storage failure,
        cancellation (``cancelled``), invalid model/route/auth declarations,
        client disconnects, and any unknown/unpaired/in-flight request.

        A budget rejection itself sets ``_cancelled`` true, so this classifier
        NEVER inspects ``_cancelled``; a user cancellation is distinguished by
        its own non-budget refusal reason and by the runtime's cancel precedence.
        This is a read-only classification; it never mutates the scope or
        replays a request.
        """

        with self._lock:
            if self._journal_failed:
                # A broken durable journal is a storage failure, not a budget
                # exhaustion, even though settlement may classify it blocked.
                return None
            if self._settlement_state_locked() != KNOWN_BLOCKED:
                return None
            if self._journal_failed:
                # Defense in depth: never accept a receipt set observed across a
                # storage-failure transition.
                return None
            reasons = [
                row.get("reason")
                for row in self._receipts
                if isinstance(row, dict) and (
                    (row.get("phase") in {"rejected", "aborted"}
                     and row.get("admitted") is False)
                    or (row.get("phase") == "completed"
                        and row.get("forwarded") is False))
            ]
            if not reasons or any(reason not in BUDGET_LIMIT_REASONS for reason in reasons):
                return None
            distinct = {reason for reason in reasons}
            return distinct.pop() if len(distinct) == 1 else None

    def remaining_seconds(self) -> float:
        if self.continuation_mode:
            elapsed = self._monotonic() - self._continuation_started
            return max(0.0, self.limits["deadline_ms"] / 1000.0 - elapsed)
        return (self.limits["deadline_at_ms"] - self._wall() * 1000) / 1000.0

    # ------------------------------------------------------------------ #
    # Provider boundary
    # ------------------------------------------------------------------ #

    def before_request(self, body: bytes, *, role: str | None = None,
                       abort_if=None) -> dict:
        """Admit or refuse ONE provider request before it is issued.

        ``abort_if`` is an optional zero-argument predicate supplied by the
        transport owner (the request proxy). It is evaluated while the request
        is serialized for the single upstream slot; if it reports the client is
        already gone, the request is refused before it becomes a late provider
        call.
        """

        if self.continuation_mode:
            return self._before_continuation_request(body, role=role, abort_if=abort_if)
        try:
            parsed = json.loads(body.decode() or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RequestGateBlocked("budget_invalid") from None
        if not isinstance(parsed, dict):
            raise RequestGateBlocked("budget_invalid")
        # The retained judgment contract requires a usable output-token ceiling
        # before each provider call; never fill a missing or invalid declaration.
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

    def complete(
        self, receipt: dict, *, status: int, body: bytes,
        outcome_unknown: bool = False,
    ) -> dict:
        """Record actual usage and decide whether the response may be forwarded.

        The named judgment result is discarded when it arrives after the
        deadline, exceeds its declared hard ceiling, or has unprovable output
        usage. The continuation profile uses its separate completion method: it
        preserves unknown usage and lets the durable business result be judged
        independently.
        """

        if self.continuation_mode:
            return self._complete_continuation_request(
                receipt, status=status, body=body, outcome_unknown=outcome_unknown)
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
            # Retained judgment contract: unknown actual output is not submitted.
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
    # ADR-0090 one-request continuation profile
    # ------------------------------------------------------------------ #

    def _reject_continuation_request(self, reason: str, *, input_bytes: int | None = None) -> None:
        with self._cond:
            self._cancelled = True
            receipt = {
                "schema_version": "continuation-request-gate.v1",
                "request_id": self.request_id,
                "phase": "rejected", "admitted": False, "reason": reason,
                "input_bytes": input_bytes, "at_ms": int(self._wall() * 1000),
            }
            self._receipts.append(receipt)
            try:
                self._write_journal(receipt)
            except RequestGateBlocked:
                self._journal_failed = True
                raise
            finally:
                # Wake a serialized waiter: this scope is now closed and it must
                # fail closed rather than wait out its remaining deadline.
                self._cond.notify_all()
        raise RequestGateBlocked(reason)

    def reject_oversized_body(self, size: int) -> None:
        """Reject a declared oversized HTTP body without buffering it."""

        self._reject_continuation_request("input_bytes_limit", input_bytes=size)

    def reject_provider_path(self) -> None:
        """Reject a DSH request path outside the official chat endpoint."""

        self._reject_continuation_request("provider_path_unqualified")

    def _continuation_decision(self, *, body_bytes: int, declared: int,
                               tool_bytes: int, elapsed_ms: int,
                               concurrent: int) -> str | None:
        if self._cancelled:
            return "cancelled"
        if elapsed_ms >= self.limits["deadline_ms"]:
            return "deadline_exceeded"
        if concurrent > self.limits["max_concurrent"]:
            return "concurrency_limit"
        if self._provider_calls + 1 > self.limits["max_provider_calls"]:
            return "provider_call_limit"
        if self._attempts + 1 > self.limits["max_attempts"]:
            return "attempt_limit"
        if body_bytes > self.limits["max_input_bytes"]:
            return "input_bytes_limit"
        if self._input_bytes_total + body_bytes > self.limits["max_total_input_bytes"]:
            return "total_input_bytes_limit"
        if declared > self.limits["max_output_tokens"]:
            return "output_tokens_limit"
        if self._declared_output_tokens_total + declared > self.limits["max_total_output_tokens"]:
            return "total_output_tokens_limit"
        if tool_bytes > self.limits["max_tool_payload_bytes"]:
            return "tool_payload_limit"
        if self._tool_payload_bytes_total + tool_bytes > self.limits["max_total_tool_payload_bytes"]:
            return "total_tool_payload_limit"
        return None

    def _before_continuation_request(self, body: bytes, *, role: str | None,
                                     abort_if=None) -> dict:
        try:
            parsed = json.loads(body.decode() or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._reject_continuation_request("budget_invalid", input_bytes=len(body))
        if not isinstance(parsed, dict):
            self._reject_continuation_request("budget_invalid", input_bytes=len(body))
        if parsed.get("model") != CONTINUATION_MODEL:
            self._reject_continuation_request("model_route_unqualified", input_bytes=len(body))
        declared, declared_reason = resolve_declared_output_tokens(parsed)
        if declared_reason is not None:
            self._reject_continuation_request(declared_reason, input_bytes=len(body))
        tool_bytes = _tool_payload_bytes(parsed)
        with self._cond:
            while True:
                now = self._monotonic()
                elapsed_ms = max(0, int((now - self._continuation_started) * 1000))
                if self._journal_failed:
                    # The durable at-most-once journal is broken; nothing more
                    # may be dispatched under this scope.
                    reason = "storage_failed"
                elif self._cancelled or self._gate_closed:
                    # Fail closed: a cancelled or closed request scope never
                    # dispatches, and never replays an unprovable result.
                    reason = "cancelled"
                elif elapsed_ms >= self.limits["deadline_ms"]:
                    reason = "deadline_exceeded"
                elif abort_if is not None and not abort_if():
                    # The caller's HTTP client is already gone. Refuse this
                    # request only: never dispatch a late provider call, and
                    # never poison the shared scope for the other request.
                    reason = "client_disconnected"
                elif self._inflight >= self.limits["max_concurrent"]:
                    # The single upstream slot is held by another admitted
                    # request (parent/child share one per-root proxy). Serialize
                    # instead of refusing: wait, bounded by the request deadline,
                    # so upstream concurrency never exceeds the profile limit.
                    # Bound the serialized queue too: each waiter holds an HTTP
                    # handler thread for up to the deadline, and a waiter beyond
                    # the profile's remaining attempt budget could never be
                    # admitted, so it fails closed immediately.
                    if self._waiting + 1 > self.limits["max_attempts"] - self._attempts:
                        reason = "queue_limit"
                    else:
                        remaining = (self.limits["deadline_ms"] - elapsed_ms) / 1000.0
                        if remaining <= 0:
                            reason = "deadline_exceeded"
                        else:
                            self._waiting += 1
                            try:
                                self._cond.wait(timeout=remaining)
                            finally:
                                self._waiting -= 1
                            continue
                else:
                    concurrent = self._inflight + 1
                    reason = self._continuation_decision(
                        body_bytes=len(body), declared=declared, tool_bytes=tool_bytes,
                        elapsed_ms=elapsed_ms, concurrent=concurrent)
                admitted = reason is None
                if reason == "client_disconnected":
                    phase = "aborted"
                elif admitted:
                    phase = "admitted"
                else:
                    phase = "rejected"
                receipt = {
                    "schema_version": "continuation-request-gate.v1",
                    "request_id": self.request_id,
                    "phase": phase,
                    "role": role or "root",
                    "call": self._provider_calls + (1 if admitted else 0),
                    "attempt": self._attempts + (1 if admitted else 0),
                    "input_bytes": len(body),
                    "declared_max_output_tokens": declared,
                    "tool_payload_bytes": tool_bytes,
                    "admitted": admitted,
                    "reason": reason or "within_request_budget",
                    "at_ms": int(self._wall() * 1000),
                    "_started": now,
                }
                # Persist the durable row BEFORE committing any in-memory
                # admission accounting. If this fails, the request was never
                # dispatched: provider calls/attempts stay accurate (no phantom
                # call) and the scope records a KNOWN pre-dispatch refusal
                # (storage_failed), never an unknown provider outcome.
                try:
                    self._write_journal(receipt)
                except RequestGateBlocked:
                    self._journal_failed = True
                    self._receipts.append({
                        "schema_version": "continuation-request-gate.v1",
                        "request_id": self.request_id,
                        "phase": "rejected", "role": role or "root",
                        "call": self._provider_calls, "attempt": self._attempts,
                        "input_bytes": len(body),
                        "declared_max_output_tokens": declared,
                        "tool_payload_bytes": tool_bytes,
                        "admitted": False, "reason": "storage_failed",
                        "at_ms": int(self._wall() * 1000),
                    })
                    self._cond.notify_all()
                    raise
                if admitted:
                    self._provider_calls += 1
                    self._attempts += 1
                    self._inflight += 1
                    self._input_bytes_total += len(body)
                    self._declared_output_tokens_total += declared
                    self._tool_payload_bytes_total += tool_bytes
                    self._max_input_bytes = max(self._max_input_bytes, len(body))
                    self._max_declared_output_tokens = max(self._max_declared_output_tokens, declared)
                    self._max_tool_payload_bytes = max(self._max_tool_payload_bytes, tool_bytes)
                    self._max_concurrent = max(self._max_concurrent, concurrent)
                elif reason not in ("concurrency_limit", "client_disconnected", "queue_limit"):
                    # Only terminal/poisoning refusals close the request scope.
                    # A transient concurrency refusal, a bounded-queue overflow
                    # or a per-request client disconnect (none dispatched
                    # upstream) must not poison later serialized requests.
                    self._cancelled = True
                self._receipts.append(receipt)
                break
        if reason is not None:
            raise RequestGateBlocked(reason)
        return receipt

    def _complete_continuation_request(
        self, receipt: dict, *, status: int, body: bytes, outcome_unknown: bool,
    ) -> dict:
        elapsed_ms = max(0, int((self._monotonic()
            - receipt.get("_started", self._monotonic())) * 1000))
        actual = parse_response_usage(body)
        declared = int(receipt.get("declared_max_output_tokens") or 0)
        total_elapsed_ms = max(0, int((self._monotonic() - self._continuation_started) * 1000))
        if total_elapsed_ms >= self.limits["deadline_ms"]:
            reason = "deadline_exceeded"
        elif outcome_unknown:
            # The provider connection ended without a complete response. Its
            # external result may exist even though this Adapter cannot prove
            # it, so this request closes before DSH can retry it automatically.
            reason = "provider_outcome_unknown"
        elif self.continuation_mode and 300 <= status < 400:
            # Never forward a redirect to the DSH HTTP client: it could follow
            # Location outside the counted official-provider proxy boundary.
            reason = "provider_redirect_blocked"
        elif (isinstance(actual["actual_output_tokens"], int)
                and actual["actual_output_tokens"] > declared):
            reason = "output_tokens_exceeded"
        else:
            # Missing provider usage remains unknown. It does not erase an
            # otherwise valid business result, and cannot authorize another request.
            reason = None
        with self._cond:
            self._inflight = max(0, self._inflight - 1)
            completed = {k: v for k, v in receipt.items() if not k.startswith("_")}
            completed.update({
                "phase": "completed", "status": status, "forwarded": reason is None,
                "reason": reason or "within_request_budget",
                "elapsed_ms": elapsed_ms, "completed_at_ms": int(self._wall() * 1000),
                **actual,
            })
            self._receipts.append(completed)
            self._actual_receipts.append(actual)
            if reason is not None:
                self._cancelled = True
                if reason == "output_tokens_exceeded":
                    # This is provider-observed actual output beyond the exact
                    # per-request declaration. Preserve it as a fact; never
                    # replace it with the profile ceiling or unknown usage.
                    self._limit_violations.add("provider_declared_output_exceeded")
            try:
                self._write_journal(completed)
            except RequestGateBlocked:
                # A DISPATCHED request ran but its completion row could not be
                # persisted: preserve an unprovable (unknown) outcome and never
                # let the scope settle as known or replay the request.
                self._journal_failed = True
                self._outcome_unknown = True
                raise
            finally:
                # A freed upstream slot must wake a serialized waiter even if
                # journaling fails, so the slot is never stranded.
                self._cond.notify_all()
        return {"forward": reason is None, "reason": reason, "elapsed_ms": elapsed_ms, **actual}

    def request_usage(self, *, tool_calls: int, elapsed_ms: int | None = None) -> dict:
        """Build a closed receipt, separating admission limits from actual use."""

        if not self.continuation_mode:
            raise ValueError("continuation request usage requires a closed profile")
        if type(tool_calls) is not int or tool_calls < 0:
            raise ValueError("continuation tool dispatch count is invalid")
        if elapsed_ms is None:
            elapsed_ms = max(0, int((self._monotonic() - self._continuation_started) * 1000))
        if type(elapsed_ms) is not int or elapsed_ms < 0:
            raise ValueError("continuation elapsed time is invalid")
        with self._lock:
            admission = {
                "provider_calls": self._provider_calls,
                "provider_attempts": self._attempts,
                "input_bytes": self._input_bytes_total,
                "declared_output_tokens": self._declared_output_tokens_total,
                "tool_payload_bytes": self._tool_payload_bytes_total,
                "max_input_bytes": self._max_input_bytes,
                "max_declared_output_tokens": self._max_declared_output_tokens,
                "max_tool_payload_bytes": self._max_tool_payload_bytes,
                "tool_calls": tool_calls,
                "max_concurrent": self._max_concurrent,
                "elapsed_ms": elapsed_ms,
            }
            if self._provider_calls == 0:
                actual_usage = {
                    "input_tokens": 0, "cache_read_tokens": 0, "output_tokens": 0,
                    "provider_attempts": 0, "usage_source": "no_provider_calls",
                    "completeness": "known",
                }
            elif self._outcome_unknown:
                # A dispatched request's completion row could not be persisted,
                # so the outbound provider outcome/usage cannot be proven.
                # Preserve unknown facts instead of reporting known counts that
                # could not be reconciled after a restart.
                actual_usage = {
                    "input_tokens": UNKNOWN, "cache_read_tokens": UNKNOWN,
                    "output_tokens": UNKNOWN, "provider_attempts": UNKNOWN,
                    "usage_source": "unknown", "completeness": "unknown",
                }
            else:
                completed = self._actual_receipts
                def total(field: str):
                    if len(completed) != self._provider_calls:
                        return UNKNOWN
                    values = [row[field] for row in completed]
                    if any(type(value) is not int or value < 0 for value in values):
                        return UNKNOWN
                    return sum(values)
                fields = {
                    "input_tokens": total("actual_input_tokens"),
                    "cache_read_tokens": total("actual_cache_read_tokens"),
                    "output_tokens": total("actual_output_tokens"),
                }
                has_provider_usage = any(row.get("usage_source") == "provider_response" for row in completed)
                usage_source = "provider_response" if has_provider_usage else "unknown"
                counts_known = all(type(value) is int for value in fields.values())
                if not has_provider_usage:
                    fields = {key: UNKNOWN for key in fields}
                    provider_attempts: int | str = UNKNOWN
                    completeness = "unknown"
                else:
                    provider_attempts = self._attempts
                    completeness = "known" if counts_known else "partial"
                actual_usage = {
                    **fields, "provider_attempts": provider_attempts,
                    "usage_source": usage_source, "completeness": completeness,
                }
            receipt = {
                "schema_version": CONTINUATION_USAGE_SCHEMA,
                "execution_profile": self.execution_profile,
                "request_limits": self.limits,
                "admission_usage": admission,
                "actual_usage": actual_usage,
                "limit_violations": sorted(self._limit_violations),
            }
        return validate_request_usage(receipt)

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


class _NoProviderRedirects(urllib.request.HTTPRedirectHandler):
    """Continuation requests must not follow an uncounted Location target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _response_socket(response):
    # A normal HTTPResponse exposes response.fp.raw._sock. urllib wraps
    # non-2xx responses in HTTPError, adding an extra .fp layer around that
    # HTTPResponse; walk the bounded public/file-wrapper chain so error bodies
    # receive the same absolute-deadline read as successful responses.
    pending = [response]
    visited: set[int] = set()
    for _ in range(8):
        following = []
        for item in pending:
            if item is None or id(item) in visited:
                continue
            visited.add(id(item))
            sock = getattr(item, "_sock", None)
            if isinstance(sock, socket.socket):
                return sock
            for attribute in ("fp", "raw"):
                nested = getattr(item, attribute, None)
                if nested is not None and id(nested) not in visited:
                    following.append(nested)
        pending = following
        if not pending:
            break
    return None


def _client_still_connected(connection) -> bool:
    """Best-effort check that a request's HTTP client is still open.

    A serialized request may wait for the single upstream slot while its client
    disconnects. If it is already gone, the request must be refused before it
    reaches the provider, so a queued request never becomes a late model call.
    A non-blocking peek is used: after the request body is fully read, any
    readable byte or EOF reflects the peer state and no body data is consumed.
    """

    try:
        readable, _, _ = select.select([connection], [], [], 0)
    except (OSError, ValueError):
        return False
    if not readable:
        return True
    try:
        return connection.recv(1, socket.MSG_PEEK) != b""
    except (BlockingIOError, InterruptedError):
        return True
    except OSError:
        return False


def _read_response(response, gate: ResearchRequestGate) -> bytes:
    """Read a continuation response in short chunks under one monotonic deadline."""

    if not gate.continuation_mode:
        return response.read()
    chunks: list[bytes] = []
    while True:
        remaining = gate.remaining_seconds()
        if remaining <= 0:
            raise TimeoutError("continuation provider response exceeded request deadline")
        # HTTPResponse closes its socket and clears fp as soon as a declared
        # Content-Length is consumed. Return here instead of setting a timeout
        # on that already-closed socket for a final EOF read.
        if getattr(response, "fp", object()) is None or getattr(response, "length", None) == 0:
            return b"".join(chunks)
        sock = _response_socket(response)
        if sock is None:
            raise OSError("provider response socket is unavailable")
        # A small Content-Length body may already be fully buffered while
        # HTTPResponse has closed its socket. In that case read1 can safely
        # consume the buffer, but settimeout() on the stale socket raises
        # EBADF. Keep the monotonic checks around read1 and only adjust a live
        # descriptor so trickle reads still share one absolute deadline.
        try:
            socket_is_live = sock.fileno() >= 0
        except OSError:
            socket_is_live = False
        if socket_is_live:
            sock.settimeout(remaining)
        chunk = response.read1(64 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        if gate.remaining_seconds() <= 0:
            raise TimeoutError("continuation provider response exceeded request deadline")
        if getattr(response, "fp", object()) is None or getattr(response, "length", None) == 0:
            return b"".join(chunks)


class _GateProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: object) -> None:  # noqa: N802
        return

    def _failure(self, reason: str) -> None:
        payload = json.dumps({
            "error": {"type": "byq_request_gate_failed", "code": reason}}).encode()
        status = (504 if reason == "deadline_exceeded" else
                  413 if reason == "input_bytes_limit" else
                  403 if reason in {"provider_path_unqualified", "model_route_unqualified"} else
                  429 if "limit" in reason or reason == "cancelled" else 502)
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802
        proxy: RequestGateProxy = self.server.proxy  # type: ignore[attr-defined]
        proxy._register_client(self.connection)
        try:
            self._handle_post(proxy)
        finally:
            proxy._unregister_client(self.connection)

    def _handle_post(self, proxy: "RequestGateProxy") -> None:
        gate: ResearchRequestGate = self.server.gate  # type: ignore[attr-defined]
        upstream: str = self.server.upstream  # type: ignore[attr-defined]
        if gate.continuation_mode and self.path not in {"/chat/completions", "/v1/chat/completions"}:
            try:
                gate.reject_provider_path()
            except RequestGateBlocked as error:
                self.close_connection = True
                self._failure(error.reason)
            return
        try:
            length = int(self.headers.get("content-length") or "0")
        except ValueError:
            self.close_connection = True
            self._failure("budget_invalid")
            return
        if length < 0:
            self.close_connection = True
            self._failure("budget_invalid")
            return
        if gate.continuation_mode and length > gate.limits["max_input_bytes"]:
            try:
                gate.reject_oversized_body(length)
            except RequestGateBlocked as error:
                self.close_connection = True
                self._failure(error.reason)
            return
        body = self.rfile.read(length) if length else b""
        try:
            receipt = gate.before_request(
                body, abort_if=lambda: _client_still_connected(self.connection))
        except RequestGateBlocked as error:
            payload = json.dumps({
                "error": {"type": "byq_request_gate_blocked", "code": error.reason}}).encode()
            try:
                self.send_response(429)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except OSError:
                # The client or the owning proxy may already be gone (for
                # example close() woke this serialized waiter). The refusal is
                # still fail-closed; only the transport write is unavailable.
                self.close_connection = True
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
        transport_outcome_unknown = False
        try:
            if gate.continuation_mode:
                opener = urllib.request.build_opener(_NoProviderRedirects())
                with opener.open(request, timeout=remaining) as response:
                    proxy._register_upstream(response)
                    try:
                        status = response.status
                        content_type = response.headers.get("content-type", "application/json")
                        data = _read_response(response, gate)
                        if proxy._closed:
                            raise OSError("continuation request proxy closed during provider response")
                    finally:
                        proxy._unregister_upstream(response)
            else:
                # Keep the existing judgment gate transport behavior intact.
                with urllib.request.urlopen(request, timeout=remaining) as response:
                    status = response.status
                    content_type = response.headers.get("content-type", "application/json")
                    data = response.read()
        except urllib.error.HTTPError as error:
            proxy._register_upstream(error)
            try:
                status = error.code
                content_type = error.headers.get("content-type", "application/json")
                if gate.continuation_mode and 300 <= status < 400:
                    # Do not wait for or expose a redirect response body. The
                    # SDK must never receive a Location it could follow.
                    data = b""
                else:
                    # HTTPError is itself an addinfourl wrapper, but its fp is
                    # the actual HTTPResponse. Use that response for read1 so
                    # non-2xx bodies keep the same socket deadline path.
                    response = error.fp if gate.continuation_mode else error
                    data = _read_response(response, gate)
            except (socket.timeout, TimeoutError):
                if gate.continuation_mode:
                    transport_outcome_unknown = True
                else:
                    timed_out = True
            except (urllib.error.URLError, OSError, http.client.HTTPException):
                if gate.continuation_mode:
                    transport_outcome_unknown = True
            finally:
                try:
                    error.close()
                except OSError:
                    pass
                proxy._unregister_upstream(error)
        except (socket.timeout, TimeoutError):
            if gate.continuation_mode:
                transport_outcome_unknown = True
            else:
                timed_out = True
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            # No complete provider response leaves the external outcome
            # unknown. Stop this request scope so the DSH retry policy cannot
            # replay it; legacy judgment transport retains its old behavior.
            transport_outcome_unknown = gate.continuation_mode
            data = b""
            if not gate.continuation_mode:
                status = 502
        try:
            completion = gate.complete(
                receipt,
                status=0 if timed_out or transport_outcome_unknown else status,
                body=data,
                outcome_unknown=transport_outcome_unknown,
            )
        except RequestGateBlocked as error:
            # The durable completion row could not be persisted. Never forward a
            # provider response whose at-most-once evidence is missing; fail
            # closed with a structured refusal.
            self.close_connection = True
            self._failure(error.reason)
            return
        if timed_out:
            self._failure("deadline_exceeded")
            return
        if not completion["forward"]:
            # Over-limit, late, redirect, and unknown transport outcomes are
            # discarded. No unknown provider call is eligible for SDK replay.
            self._failure(completion["reason"] or "deadline_exceeded")
            return
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class RequestGateProxy:
    """One request-scoped proxy whose active sockets the owner can close."""

    def __init__(self, gate: ResearchRequestGate, upstream: str, *,
                 bind_host: str = "127.0.0.1", advertise_host: str | None = None) -> None:
        if gate.continuation_mode:
            from packages.contracts.continuation_request import UPSTREAM_BASE_URL
            allowed_upstreams = {"https://api.deepseek.com", UPSTREAM_BASE_URL.rstrip("/")}
            if upstream.rstrip("/") not in allowed_upstreams:
                raise ValueError("continuation provider is not a qualified endpoint")
        # The ACP product slot runs the DSH child in a separate container, so the
        # loopback address is not reachable from that child. Callers may bind a
        # routable interface and advertise the address the child must use.
        self._advertise_host = advertise_host or (
            "127.0.0.1" if bind_host in {"127.0.0.1", "localhost"} else bind_host)
        self._gate = gate
        self._upstream = upstream.rstrip("/")
        self._server = ThreadingHTTPServer((bind_host, 0), _GateProxyHandler)
        self._server.daemon_threads = True
        self._server.gate = gate  # type: ignore[attr-defined]
        self._server.upstream = self._upstream  # type: ignore[attr-defined]
        self._server.proxy = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._started = False
        self._closed = False
        self._close_lock = threading.Lock()
        self._active_lock = threading.Lock()
        self._client_sockets: set[socket.socket] = set()
        self._upstream_responses: set[object] = set()

    @property
    def base_url(self) -> str:
        _host, port = self._server.server_address[:2]
        return f"http://{self._advertise_host}:{port}"

    def _register_client(self, connection: socket.socket) -> None:
        with self._active_lock:
            closed = self._closed
            if not closed:
                self._client_sockets.add(connection)
        if closed:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                connection.close()
            except OSError:
                pass

    def _unregister_client(self, connection: socket.socket) -> None:
        with self._active_lock:
            self._client_sockets.discard(connection)

    def _register_upstream(self, response: object) -> None:
        with self._active_lock:
            if self._closed:
                close = getattr(response, "close", None)
                if close is not None:
                    close()
                raise OSError("continuation request proxy is closed")
            self._upstream_responses.add(response)

    def _unregister_upstream(self, response: object) -> None:
        with self._active_lock:
            self._upstream_responses.discard(response)

    def __enter__(self) -> "RequestGateProxy":
        if self._closed:
            raise RuntimeError("request gate proxy is already closed")
        if not self._started:
            self._thread.start()
            self._started = True
        return self

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            # Wake any request serialized on the single upstream slot so it
            # fails closed immediately instead of waiting out the deadline.
            self._gate.release_waiters()
            if self._started:
                self._server.shutdown()
            with self._active_lock:
                responses = list(self._upstream_responses)
                clients = list(self._client_sockets)
                self._upstream_responses.clear()
                self._client_sockets.clear()
            for response in responses:
                # The handler owns HTTPResponse.close(). Closing its fp here
                # races read1() and can erase the unknown-result receipt with
                # an AttributeError. Interrupt only the socket; the handler
                # records the transport outcome and closes its own response.
                sock = _response_socket(response)
                if sock is not None:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
            for connection in clients:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    connection.close()
                except OSError:
                    pass
            self._server.server_close()
            if self._started:
                self._thread.join(timeout=2)

    def __exit__(self, *exc: object) -> None:
        self.close()


def build_continuation_request_gate(*, request_id: str, execution_profile: dict,
                                    limits: dict | None = None,
                                    journal: Path | None = None) -> ResearchRequestGate:
    """Build the one-request task-ready profile; callers cannot widen it."""

    return ResearchRequestGate(
        continuation_request_limits() if limits is None else limits,
        execution_profile=execution_profile, request_id=request_id, journal=journal,
    )


def build_request_gate(stage: str, *, request_id: str, journal: Path | None = None) -> ResearchRequestGate:
    """Build the closed request-scoped gate for one named judgment request."""

    if stage not in JUDGMENT_STAGES:
        raise ValueError("a deterministic research stage must not open a request gate")
    limits = stage_request_limits(
        stage, request_id=request_id, started_at_ms=int(time.time() * 1000))
    return ResearchRequestGate(limits, journal=journal)
