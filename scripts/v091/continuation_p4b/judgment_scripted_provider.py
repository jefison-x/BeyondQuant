#!/usr/bin/env python3
"""ADR-0085 P4-B keyless journey-aware scripted provider (isolated non-production).

A non-LLM OpenAI-compatible streaming provider used ONLY by the isolated P4-B
normal-journey stack. It drives the REAL DSH child/tool path for EVERY bounded
research-judgment stage of the normal three-round journey:

  strategy_draft        -> research-proposal.v1 kind=strategy_draft
  backtest_analysis     -> kind=backtest_analysis
  iteration_comparison  -> kind=propose_revision (iteration 1/2)
                           kind=select_iteration (iteration 3)
  final_selection       -> kind=select_iteration

The provider copies the authoritative task_id/plan_version/task_version/stage/
iteration from the bounded stage input. It NEVER invents an object id, approval,
idempotency key, routing target, recovery state or plan identity, and it holds no
credential. Evidence MUST stay labelled scripted-keyless / non-real-LLM-quality.

Control endpoints (evidence only):
  GET /_calls  -> per-call root/child metrics and per-task call accounting
  GET /healthz
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PERSONA_TOOL = "byq_research_judgment_turn"
MAX_ROUNDS = 3
_STAGE_INPUT = re.compile(r"BOUNDED_STAGE_INPUT=(\{.*?\})(?:\s|$)", re.DOTALL)
_FORBIDDEN_RAW = ("bars_frame", "date_index", "signals", "signal_rows", "frame",
                  "benchmark_series", "equity_curve", "positions", "trades_frame")


def _summarize_stage_input(stage_input: object) -> dict:
    if not isinstance(stage_input, dict):
        return {}
    canonical = json.dumps(stage_input, sort_keys=True)
    return {
        "bounded_input_bytes": len(canonical.encode()),
        "bounded_input_fields": sorted(stage_input.keys()),
        "bounded_input_digest": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        "forbidden_raw_hits": [key for key in _FORBIDDEN_RAW if key in canonical],
        "input_task_id": stage_input.get("task_id"),
        "input_plan_version": stage_input.get("plan_version"),
        "input_task_version": stage_input.get("task_version"),
        "input_stage": stage_input.get("stage"),
        "input_iteration": stage_input.get("iteration"),
    }


def _message_text(messages: list) -> str:
    parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
    return "\n".join(parts)


def _extract_stage_input(messages: list) -> dict | None:
    match = _STAGE_INPUT.search(_message_text(messages))
    if not match:
        return None
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _proposal_from_stage_input(stage_input: dict | None) -> dict:
    """Build a valid, non-escalating research-proposal.v1 for the current stage."""

    if not isinstance(stage_input, dict):
        return {}
    stage = stage_input.get("stage")
    iteration = stage_input.get("iteration")
    kinds = stage_input.get("proposal_kinds") or []
    proposal = {
        "schema_version": "research-proposal.v1",
        "task_id": stage_input.get("task_id"),
        "plan_version": stage_input.get("plan_version"),
        "task_version": stage_input.get("task_version"),
        "stage": stage,
        "iteration": iteration,
        "evidence_sufficient": True,
        "escalate": False,
        "summary": "scripted bounded judgment (keyless, non-LLM-quality)",
    }
    if stage == "iteration_comparison":
        if isinstance(iteration, int) and iteration < MAX_ROUNDS and "propose_revision" in kinds:
            proposal["proposal_kind"] = "propose_revision"
            proposal["revision_direction"] = "improve_robustness"
        elif "select_iteration" in kinds:
            proposal["proposal_kind"] = "select_iteration"
            proposal["selected_iteration"] = min(iteration or 1, MAX_ROUNDS)
        else:
            return {}
    elif stage == "final_selection":
        if "select_iteration" not in kinds:
            return {}
        proposal["proposal_kind"] = "select_iteration"
        proposal["selected_iteration"] = 1
    else:
        kind = next((k for k in kinds if k != "escalate"), None)
        if kind is None:
            return {}
        proposal["proposal_kind"] = kind
    return proposal


class Handler(BaseHTTPRequestHandler):
    calls = 0
    root_calls = 0
    child_calls = 0
    tool_calls_emitted = 0
    last_available_tools: list[str] = []
    per_call: list[dict] = []
    calls_by_task: dict[str, int] = {}

    def log_message(self, *args: object) -> None:  # noqa: N802
        return

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _sse(self, payloads: list[dict]) -> None:
        encoded = "".join(
            f"data: {json.dumps(item, separators=(',', ':'))}\n\n" for item in payloads
        ) + "data: [DONE]\n\n"
        body = encoded.encode()
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        from urllib.parse import urlparse

        if urlparse(self.path).path in {"/_calls", "/healthz"}:
            self._json({
                "service": "byq-p4b-journey-provider", "calls": self.calls,
                "root_calls": self.root_calls, "child_calls": self.child_calls,
                "tool_calls_emitted": self.tool_calls_emitted,
                "calls_by_task": dict(self.calls_by_task),
                "last_available_tools": self.last_available_tools,
                "per_call": self.per_call[-80:],
            })
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        try:
            request = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            request = {}
        messages = request.get("messages") if isinstance(request, dict) else None
        messages = messages if isinstance(messages, list) else []
        tools = request.get("tools") if isinstance(request, dict) else None
        tool_names = []
        if isinstance(tools, list):
            for item in tools:
                if isinstance(item, dict) and isinstance(item.get("function"), dict) \
                        and isinstance(item["function"].get("name"), str):
                    tool_names.append(item["function"]["name"])
        is_root = PERSONA_TOOL in tool_names
        has_tool_result = any(isinstance(m, dict) and m.get("role") == "tool" for m in messages)
        stage_input = _extract_stage_input(messages)

        self.__class__.calls += 1
        self.__class__.last_available_tools = sorted(tool_names)
        task_key = (stage_input or {}).get("task_id") if isinstance(stage_input, dict) else None
        if isinstance(task_key, str):
            self.__class__.calls_by_task[task_key] = \
                self.__class__.calls_by_task.get(task_key, 0) + 1
        record = {"call": self.calls, "role": "root" if is_root else "child",
                  "has_tool_result": has_tool_result, "tools": sorted(tool_names),
                  "stage_input_stage": (stage_input or {}).get("stage")}
        record.update(_summarize_stage_input(stage_input))
        self.__class__.per_call.append(record)

        if is_root and not has_tool_result:
            self.__class__.root_calls += 1
            self.__class__.tool_calls_emitted += 1
            call_id = f"p4b-judgment-{self.tool_calls_emitted}"
            arguments = {
                "description": "bounded judgment",
                "prompt": ("Return ONLY the closed JSON result. "
                           f"BOUNDED_STAGE_INPUT={json.dumps(stage_input or {}, sort_keys=True)}"),
            }
            record["action"] = "tool_call"
            payloads = [
                {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {"tool_calls": [{
                    "index": 0, "id": call_id, "type": "function",
                    "function": {"name": PERSONA_TOOL, "arguments": json.dumps(arguments)},
                }]}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                 "usage": {"prompt_tokens": 5, "completion_tokens": 5}},
            ]
            self._sse(payloads)
            return

        if not is_root:
            self.__class__.child_calls += 1
            record["action"] = "closed_result"
            proposal = _proposal_from_stage_input(stage_input)
            record["proposal_kind"] = proposal.get("proposal_kind")
            text = json.dumps({"proposal": proposal, "durable_evidence": {"kind": "none"}})
        else:
            record["action"] = "final_text"
            text = "bounded judgment turn completed."
        payloads = [
            {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 5, "completion_tokens": 5}},
        ]
        self._sse(payloads)


def main() -> int:
    port = int(os.environ.get("JUDGMENT_PROVIDER_PORT", "8901"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"byq-p4b-journey-provider listening on {port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
