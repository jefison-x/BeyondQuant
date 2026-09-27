"""Test-only Product MCP reverse proxy with an independent request counter.

Run only as a separate service in a disposable Phase 7 Compose project. It
forwards requests unchanged in meaning, records JSON-RPC method/tool names
without headers or payloads, and never publishes a host port.
"""
from __future__ import annotations

import http.client
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


if os.environ.get("BYQ_PHASE7_MCP_OBSERVER") != "1":
    raise SystemExit("isolated Phase 7 observer flag required")

_lock = threading.Lock()
_requests: list[dict[str, str]] = []
_hop_headers = {"connection", "content-length", "host", "transfer-encoding"}


def _mcp_error(raw: bytes) -> str:
    payloads = [raw]
    if any(line.startswith(b"data:") for line in raw.splitlines()):
        payloads = [line[5:].strip() for line in raw.splitlines() if line.startswith(b"data:")]
    for payload in payloads:
        try:
            value = json.loads(payload)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and isinstance(value.get("result"), dict):
            return str(bool(value["result"].get("isError", False))).lower()
        if isinstance(value, dict) and "error" in value:
            return "true"
    return "unknown"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        return

    def do_GET(self):  # noqa: N802
        if self.path == "/_phase7/observed":
            with _lock:
                calls = list(_requests)
            self._send_json({"requests": calls, "count": len(calls),
                             "tools_call_count": sum(item.get("method") == "tools/call" for item in calls),
                             "role_calls": sum(item.get("tool") == "byq_agent_roles" for item in calls),
                             "role_successes": sum(item.get("tool") == "byq_agent_roles"
                                                   and item.get("http_status") == "200"
                                                   and item.get("mcp_error") == "false" for item in calls)})
            return
        self._forward()

    def do_POST(self):  # noqa: N802
        self._forward()

    def do_DELETE(self):  # noqa: N802
        self._forward()

    def _send_json(self, value: object):
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _forward(self):
        if not self.path.startswith("/mcp/v1"):
            self.send_error(404)
            return
        size = int(self.headers.get("content-length", "0"))
        if size < 0 or size > 2_000_000:
            self.send_error(413)
            return
        body = self.rfile.read(size) if size else b""
        entry = None
        if body:
            try:
                request = json.loads(body)
                if isinstance(request, dict):
                    method = request.get("method")
                    tool = (request.get("params") or {}).get("name") if isinstance(request.get("params"), dict) else None
                    entry = {"method": str(method or ""), "tool": str(tool or "")}
                    with _lock:
                        _requests.append(entry)
            except (ValueError, TypeError):
                pass
        headers = {key: value for key, value in self.headers.items()
                   if key.lower() not in _hop_headers}
        headers["host"] = "mcp:8300"
        try:
            connection = http.client.HTTPConnection("mcp", 8300, timeout=20)
            connection.request(self.command, self.path, body=body or None, headers=headers)
            upstream = connection.getresponse()
            response_body = upstream.read()
            if entry is not None:
                entry["http_status"] = str(upstream.status)
                entry["mcp_error"] = _mcp_error(response_body)
            self.send_response(upstream.status)
            for key, value in upstream.getheaders():
                if key.lower() not in _hop_headers:
                    self.send_header(key, value)
            self.send_header("content-length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
            connection.close()
        except (OSError, http.client.HTTPException):
            self.send_error(502)


ThreadingHTTPServer(("0.0.0.0", 8350), Handler).serve_forever()
