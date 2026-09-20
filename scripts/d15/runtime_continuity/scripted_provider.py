#!/usr/bin/env python3
"""Keyless deterministic OpenAI-compatible provider for D15 runtime qualification.

This server is intentionally simple and non-LLM: it streams a fixed assistant
message so the real BYQ runtime-adapter + bundled DSH 0.1.5 candidate can be
driven across restarts without any model credential or external network. The
evidence MUST be labelled non-real-LLM-quality.

Control endpoints (evidence only):
  GET  /_calls              -> {"calls": <int>}
  GET  /_delay?seconds=N    -> {"delay_seconds": N}
  POST /_delay?seconds=N    -> set an artificial delay before each completion

The delay lets the qualification interrupt an *active* run truthfully instead of
racing a provider that would otherwise answer instantly.
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

    def log_message(self, *args: object) -> None:  # noqa: N802
        return

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path in {"/_calls", "/healthz"}:
            self._json({"service": "byq-d15-scripted-provider", "calls": self.calls,
                        "delay_seconds": self.delay_seconds})
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
        length = int(self.headers.get("content-length", "0") or "0")
        try:
            self.rfile.read(length)
        except Exception:  # noqa: BLE001
            pass
        self.__class__.calls += 1
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
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
