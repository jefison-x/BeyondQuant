#!/usr/bin/env python3
"""Keyless deterministic OpenAI-compatible provider for D15 runtime qualification.

Non-LLM: it streams a fixed assistant message, or (when armed) a single real
OpenAI-style tool call so the real BYQ MCP server and Backend are exercised
through the runtime-adapter. The evidence MUST be labelled non-real-LLM-quality.

Control endpoints (evidence only):
  GET  /_calls              -> {"calls": <int>, "tool_calls_emitted": <int>, ...}
  GET  /_delay?seconds=N    -> set an artificial delay before each completion
  POST /_tool_call          -> arm one tool call: {"name":..., "arguments":{...}}
  DELETE /_tool_call        -> disarm
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    calls = 0
    delay_seconds = 0.0
    tool_call: dict | None = None
    tool_calls_emitted = 0
    last_tool_name: str | None = None
    last_available_tools: list[str] = []

    def log_message(self, *args: object) -> None:  # noqa: N802
        return

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self) -> None:  # noqa: N802
        if urllib.parse.urlparse(self.path).path == "/_tool_call":
            self.__class__.tool_call = None
            self._json({"tool_call": None})
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path in {"/_calls", "/healthz"}:
            self._json({"service": "byq-d15-scripted-provider", "calls": self.calls,
                        "delay_seconds": self.delay_seconds,
                        "tool_calls_emitted": self.tool_calls_emitted,
                        "last_tool_name": self.last_tool_name,
                        "last_available_tools": self.last_available_tools,
                        "armed_tool_call": self.tool_call})
            return
        if parsed.path == "/_delay":
            if "seconds" in query:
                try:
                    self.__class__.delay_seconds = max(0.0, min(120.0, float(query["seconds"][0])))
                except ValueError:
                    self._json({"error": "invalid delay"}, 400)
                    return
            self._json({"delay_seconds": self.delay_seconds})
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("content-length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        if parsed.path == "/_delay":
            query = urllib.parse.parse_qs(parsed.query)
            if "seconds" in query:
                try:
                    self.__class__.delay_seconds = max(0.0, min(120.0, float(query["seconds"][0])))
                except ValueError:
                    self._json({"error": "invalid delay"}, 400)
                    return
            self._json({"delay_seconds": self.delay_seconds})
            return
        if parsed.path == "/_tool_call":
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._json({"error": "invalid json"}, 400)
                return
            if not isinstance(body, dict) or not isinstance(body.get("name"), str):
                self._json({"error": "name is required"}, 400)
                return
            self.__class__.tool_call = {"name": body["name"],
                                        "arguments": body.get("arguments") or {}}
            self._json({"tool_call": self.tool_call})
            return

        self.__class__.calls += 1
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
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
        self.__class__.last_available_tools = sorted(tool_names)
        has_tool_result = any(isinstance(m, dict) and m.get("role") == "tool" for m in messages)

        armed = self.tool_call
        if armed is not None and not has_tool_result:
            name = armed["name"]
            self.__class__.tool_calls_emitted += 1
            self.__class__.last_tool_name = name
            call_id = f"d15-tool-{self.tool_calls_emitted}"
            payloads = [
                {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {"tool_calls": [{
                    "index": 0, "id": call_id, "type": "function",
                    "function": {"name": name, "arguments": json.dumps(armed["arguments"])},
                }]}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ]
        else:
            if armed is not None and has_tool_result:
                self.__class__.tool_call = None
            payloads = [
                {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {"content": "D15 runtime continuity synthetic answer"},
                              "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 5, "completion_tokens": 6}},
            ]
        encoded = "".join(
            f"data: {json.dumps(item, separators=(',', ':'))}\n\n" for item in payloads
        ) + "data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(encoded.encode())))
        self.end_headers()
        self.wfile.write(encoded.encode())


def main() -> int:
    port = int(os.environ.get("SCRIPTED_PROVIDER_PORT", "8900"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"byq-d15-scripted-provider listening on {port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
