"""Opt-in test-only Gateway-to-Backend proxy for Phase 7 lost-response proof.

All Gateway requests pass through this independent server. Exactly one close
receipt is deliberately discarded; the identical retry is held until the host
arms it through /_phase7/allow. No request or response payloads are logged.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


if os.environ.get("BYQ_PHASE7_TERMINAL_CLOSE_PROXY") != "1":
    raise SystemExit("isolated Phase 7 close proxy opt-in required")

_BACKEND_URL = os.environ.get("BYQ_PHASE7_BACKEND_URL", "http://backend:8000")
_BACKEND = urlsplit(_BACKEND_URL)
if (_BACKEND.scheme != "http" or not _BACKEND.hostname
        or _BACKEND.hostname != "backend" or _BACKEND.port not in (None, 8000)
        or _BACKEND.username is not None or _BACKEND.password is not None
        or _BACKEND.path not in ("", "/") or _BACKEND.query or _BACKEND.fragment):
    raise SystemExit("test close proxy requires an http backend origin")

_CLOSE_ROUTE = re.compile(r"/internal/runtime-authority/roots/([0-9a-f]{32})/close")
_HEX32 = re.compile(r"[0-9a-f]{32}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_HOP_HEADERS = {
    "connection", "content-length", "host", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade",
}
_CONDITION = threading.Condition()
_STATE: dict[str, object] = {
    "close_requests": 0,
    "first_forwarded": 0,
    "dropped_responses": 0,
    "pre_allow_rejections": 0,
    "withheld_rejections": 0,
    "retry_forwarded": 0,
    "allow_armed": False,
    "allow_count": 0,
    "first_status": None,
    "pre_allow_status": None,
    "retry_status": None,
    "root_run_id": None,
    "first_receipt": None,
    "retry_receipt": None,
    "first_body": None,
    "first_attempt_complete": False,
    "retry_inflight": False,
}


def _receipt(value: object, root_id: str, request_body: dict[str, object]) -> dict[str, object] | None:
    if not isinstance(value, dict) or set(value) != {"receipt"}:
        return None
    receipt = value["receipt"]
    if (not isinstance(receipt, dict)
            or set(receipt) != {"schema_version", "sequence", "root_run_id", "event_sha256"}
            or receipt.get("schema_version") != "agent-run-lifecycle-receipt.v1"
            or receipt.get("root_run_id") != root_id
            or type(receipt.get("sequence")) is not int
            or receipt.get("sequence") != request_body.get("sequence")
            or receipt.get("event_sha256") != request_body.get("event_sha256")
            or not isinstance(receipt.get("event_sha256"), str)
            or _HEX64.fullmatch(receipt["event_sha256"]) is None):
        return None
    # This exact minimal receipt is intentionally observable so the host can
    # compare Backend state, the Adapter journal, and the retry acknowledgement.
    return {
        "schema_version": receipt["schema_version"],
        "root_run_id": receipt["root_run_id"],
        "sequence": receipt["sequence"],
        "event_sha256": receipt["event_sha256"],
    }


def _safe_json(handler: BaseHTTPRequestHandler, status: int, value: object) -> None:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    handler.send_response(status)
    handler.send_header("content-type", "application/json")
    handler.send_header("content-length", str(len(encoded)))
    handler.send_header("cache-control", "no-store")
    handler.end_headers()
    handler.wfile.write(encoded)


def _status_only(handler: BaseHTTPRequestHandler, status: int, reason: str) -> None:
    _safe_json(handler, status, {"error": reason})


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/_phase7/observed":
            with _CONDITION:
                observed = {
                    key: value for key, value in _STATE.items()
                    if key not in {"first_body", "first_attempt_complete", "retry_inflight"}
                }
                # Bytes, credential headers, and full request/response bodies are
                # never exposed by this metadata endpoint.
                observed["allow_armed"] = bool(_STATE["allow_armed"])
            _safe_json(self, 200, observed)
            return
        self._forward()

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/_phase7/allow":
            self._allow_retry()
            return
        match = _CLOSE_ROUTE.fullmatch(self.path)
        if match is not None:
            self._intercept_close(match.group(1))
            return
        self._forward()

    def do_PUT(self) -> None:  # noqa: N802
        self._forward()

    def do_PATCH(self) -> None:  # noqa: N802
        self._forward()

    def do_DELETE(self) -> None:  # noqa: N802
        self._forward()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._forward()

    def do_HEAD(self) -> None:  # noqa: N802
        self._forward()

    def _read_request_body(self) -> bytes | None:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            _status_only(self, 400, "valid content length required")
            return None
        if size < 0 or size > 8 * 1024 * 1024:
            _status_only(self, 413, "request too large")
            return None
        return self.rfile.read(size) if size else b""

    def _request_headers(self) -> dict[str, str]:
        connection_tokens = {
            token.strip().lower()
            for token in self.headers.get("Connection", "").split(",")
            if token.strip()
        }
        excluded = _HOP_HEADERS | connection_tokens | {"expect"}
        headers = {
            key: value for key, value in self.headers.items()
            if key.lower() not in excluded
        }
        headers["Host"] = _BACKEND.netloc
        return headers

    def _forward_raw(self, body: bytes) -> tuple[int, list[tuple[str, str]], bytes]:
        connection = http.client.HTTPConnection(
            _BACKEND.hostname,
            _BACKEND.port or 80,
            timeout=30,
        )
        try:
            path = self.path
            connection.request(
                self.command,
                path,
                body=body if body else None,
                headers=self._request_headers(),
            )
            response = connection.getresponse()
            response_body = response.read()
            response_headers = response.getheaders()
            return response.status, response_headers, response_body
        finally:
            connection.close()

    def _relay(self, status: int, headers: list[tuple[str, str]], body: bytes) -> None:
        self.send_response(status)
        for key, value in headers:
            lowered = key.lower()
            if lowered in _HOP_HEADERS or lowered == "content-length":
                continue
            self.send_header(key, value)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _forward(self) -> None:
        body = self._read_request_body()
        if body is None:
            return
        try:
            status, headers, response_body = self._forward_raw(body)
        except (OSError, http.client.HTTPException):
            _status_only(self, 502, "Backend unavailable through Phase 7 proxy")
            return
        self._relay(status, headers, response_body)

    @staticmethod
    def _parse_close(root_id: str, raw: bytes) -> dict[str, object] | None:
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if (not isinstance(value, dict)
                or set(value) != {"schema_version", "boot_id", "sequence", "outcome", "event_sha256"}
                or value.get("schema_version") != "byq-runtime-root-close.v1"
                or not isinstance(value.get("boot_id"), str)
                or _HEX32.fullmatch(value["boot_id"]) is None
                or type(value.get("sequence")) is not int
                or value["sequence"] < 1
                or value.get("outcome") not in {"completed", "failed", "cancelled", "interrupted"}
                or not isinstance(value.get("event_sha256"), str)
                or _HEX64.fullmatch(value["event_sha256"]) is None
                or root_id != _STATE.get("root_run_id") and _STATE.get("root_run_id") is not None):
            return None
        return value

    def _intercept_close(self, root_id: str) -> None:
        raw = self._read_request_body()
        if raw is None:
            return
        parsed = self._parse_close(root_id, raw)
        if parsed is None:
            _status_only(self, 400, "exact Phase 7 root close request required")
            return

        with _CONDITION:
            _STATE["close_requests"] = int(_STATE["close_requests"]) + 1
            known_root = _STATE["root_run_id"]
            first_receipt = _STATE["first_receipt"]
            first_body = _STATE["first_body"]
            if known_root is None:
                _STATE["root_run_id"] = root_id
                _STATE["first_body"] = raw
                _STATE["first_attempt_complete"] = False
                action = "first"
            elif (root_id != known_root or raw != first_body):
                _STATE["withheld_rejections"] = int(_STATE["withheld_rejections"]) + 1
                action = "mismatch"
            elif first_receipt is None:
                # One in-flight first close owns the receipt-drop slot.
                action = "first_busy"
            elif _STATE["retry_receipt"] is not None:
                action = "already_complete"
            elif not _STATE["allow_armed"]:
                # This immediate 503 is only a test gate that gives the host
                # time to verify Backend commit and the absent Adapter ACK.
                # The first request already reached Backend and its exact 200
                # receipt was deliberately dropped above.
                _STATE["pre_allow_rejections"] = int(_STATE["pre_allow_rejections"]) + 1
                _STATE["withheld_rejections"] = int(_STATE["withheld_rejections"]) + 1
                _STATE["pre_allow_status"] = 503
                action = "retry_withheld"
            else:
                _STATE["allow_armed"] = False
                _STATE["retry_inflight"] = True
                _STATE["retry_forwarded"] = int(_STATE["retry_forwarded"]) + 1
                action = "retry_forward"

        if action == "mismatch":
            _status_only(self, 409, "close retry does not match the observed root evidence")
            return
        if action == "first_busy":
            _status_only(self, 503, "first close receipt is still being observed")
            return
        if action == "retry_withheld":
            _status_only(self, 503, "host has not released the identical close retry")
            return
        if action == "already_complete":
            _status_only(self, 503, "the single released close retry was already consumed")
            return
        if action not in {"first", "retry_forward"}:
            _status_only(self, 503, "Phase 7 close proxy is not ready")
            return

        try:
            status, headers, response_body = self._forward_raw(raw)
        except (OSError, http.client.HTTPException):
            with _CONDITION:
                if action == "first":
                    _STATE["first_status"] = 502
                    _STATE["first_attempt_complete"] = True
                else:
                    _STATE["retry_status"] = 502
                    _STATE["retry_inflight"] = False
                _CONDITION.notify_all()
            _status_only(self, 502, "Backend close request failed through Phase 7 proxy")
            return

        parsed_receipt: dict[str, object] | None = None
        if status == 200:
            try:
                parsed_receipt = _receipt(json.loads(response_body), root_id, parsed)
            except (ValueError, TypeError):
                parsed_receipt = None

        if action == "first":
            with _CONDITION:
                _STATE["first_forwarded"] = int(_STATE["first_forwarded"]) + 1
                _STATE["first_status"] = status
                _STATE["first_attempt_complete"] = True
                if status == 200 and parsed_receipt is not None:
                    _STATE["first_receipt"] = parsed_receipt
                    _STATE["dropped_responses"] = int(_STATE["dropped_responses"]) + 1
                _CONDITION.notify_all()
            if status == 200 and parsed_receipt is not None:
                # Deliberately close without sending status line or headers:
                # Gateway observes a lost response after Backend committed.
                self.close_connection = True
                return
            if status == 200:
                _status_only(self, 502, "Backend returned a non-matching close receipt")
            else:
                self._relay(status, headers, response_body)
            return

        with _CONDITION:
            _STATE["retry_status"] = status
            _STATE["retry_inflight"] = False
            if (status == 200 and parsed_receipt is not None
                    and parsed_receipt == _STATE["first_receipt"]):
                _STATE["retry_receipt"] = parsed_receipt
            _CONDITION.notify_all()
        if status == 200 and parsed_receipt is not None:
            if parsed_receipt == _STATE["first_receipt"]:
                self._relay(status, headers, response_body)
            else:
                _status_only(self, 502, "Backend retry receipt changed")
        elif status == 200:
            _status_only(self, 502, "Backend returned a non-matching retry receipt")
        else:
            self._relay(status, headers, response_body)

    def _allow_retry(self) -> None:
        raw = self._read_request_body()
        if raw is None:
            return
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            _status_only(self, 400, "root_run_id required")
            return
        if (not isinstance(payload, dict) or set(payload) != {"root_run_id"}
                or not isinstance(payload.get("root_run_id"), str)
                or _HEX32.fullmatch(payload["root_run_id"]) is None):
            _status_only(self, 400, "root_run_id required")
            return
        root_id = payload["root_run_id"]
        with _CONDITION:
            if (_STATE["root_run_id"] != root_id or _STATE["first_receipt"] is None
                    or _STATE["retry_receipt"] is not None or _STATE["allow_armed"]
                    or _STATE["retry_inflight"]):
                _status_only(self, 409, "no matching pending lost-response retry")
                return
            _STATE["allow_armed"] = True
            _STATE["allow_count"] = int(_STATE["allow_count"]) + 1
            _CONDITION.notify_all()
        _safe_json(self, 200, {"allowed": True, "root_run_id": root_id})

    def _do_observed(self) -> None:
        with _CONDITION:
            observed = {
                key: value for key, value in _STATE.items()
                if key not in {"first_body", "first_attempt_complete", "retry_inflight"}
            }
            observed["allow_armed"] = bool(_STATE["allow_armed"])
        _safe_json(self, 200, observed)


ThreadingHTTPServer(("0.0.0.0", 8351), Handler).serve_forever()
