"""Unwired, single-route outbound proxy for one ADR-0097 judgment root.

The selected route, model, credential, limits and journal must come from a
trusted admitted invocation. This module does not open the ACP entry itself.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .research_judgment_acp_journal import AcpJudgmentJournal
from .research_judgment_acp_provider_routes import (
    AcpProviderRouteRejected, admit_provider_request, selected_route,
)
from .research_judgment_acp_provider_usage import MAX_SSE_BYTES, parse_acp_provider_stream
from .research_judgment_acp_control import AcpJudgmentOutcomeUnknown
from .research_request_gate import _response_socket, resolve_declared_output_tokens


@dataclass(frozen=True)
class ProviderHttpResponse:
    status: int
    content_type: str
    body: bytes


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_bounded(response, deadline_monotonic: float) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("provider response deadline expired")
        if getattr(response, "fp", object()) is None:
            if getattr(response, "length", None) not in (None, 0):
                raise http.client.IncompleteRead(b"".join(chunks))
            return b"".join(chunks)
        if getattr(response, "length", None) == 0:
            return b"".join(chunks)
        sock = _response_socket(response)
        if sock is None:
            raise OSError("provider response socket is unavailable")
        if sock.fileno() >= 0:
            sock.settimeout(remaining)
        chunk = response.read1(min(64 * 1024, MAX_SSE_BYTES + 1 - total))
        if not chunk:
            if getattr(response, "length", None) not in (None, 0):
                raise http.client.IncompleteRead(b"".join(chunks))
            return b"".join(chunks)
        total += len(chunk)
        if total > MAX_SSE_BYTES:
            raise ValueError("provider response exceeds bounded SSE size")
        chunks.append(chunk)


def _send_https(url: str, headers: dict[str, str], body: bytes,
                deadline_monotonic: float) -> ProviderHttpResponse:
    if not url.startswith("https://"):
        raise ValueError("provider upstream must use HTTPS")
    remaining = deadline_monotonic - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("provider request deadline expired")
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    # Disable environment proxy selection and all redirects. The exact route
    # helper has already fixed the upstream origin, path and forwarded headers.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=remaining) as response:
        status = response.status
        if status != 200:
            raise ValueError("provider returned an unqualified status")
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise ValueError("compressed provider response is unqualified")
        content_type = response.headers.get("content-type", "")
        data = _read_bounded(response, deadline_monotonic)
        return ProviderHttpResponse(status, content_type, data)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: object) -> None:
        return

    def handle_expect_100(self) -> bool:
        self.send_error(417)
        return False

    def _fail(self) -> None:
        data = b'{"error":{"type":"byq_acp_provider_gate_closed"}}'
        try:
            self.send_response(502)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.send_header("connection", "close")
            self.end_headers()
            self.wfile.write(data)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        self.close_connection = True

    def do_POST(self) -> None:  # noqa: N802
        proxy: AcpJudgmentProviderProxy = self.server.proxy  # type: ignore[attr-defined]
        # A following model call may arrive as soon as DSH reads the terminal
        # bytes. Keep it waiting until delivery and durable settlement finish.
        with proxy._dispatch_lock:
            self._handle_post(proxy)

    def _handle_post(self, proxy: "AcpJudgmentProviderProxy") -> None:
        if proxy.closed or self.path != proxy.route.local_base_path + proxy.route.request_target:
            self._fail()
            return
        raw_headers = list(self.headers.raw_items())
        names = [name.lower() for name, _ in raw_headers]
        if (len(names) != len(set(names)) or "transfer-encoding" in names
                or names.count("content-length") != 1):
            self._fail()
            return
        try:
            length = int(self.headers["content-length"])
        except (TypeError, ValueError):
            self._fail()
            return
        if length <= 0 or length > proxy.limits["max_input_bytes"]:
            self._fail()
            return
        chunks: list[bytes] = []
        left = length
        try:
            while left:
                remaining = proxy.deadline_monotonic - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("provider request body deadline expired")
                self.connection.settimeout(remaining)
                chunk = self.rfile.read(min(left, 64 * 1024))
                if not chunk:
                    raise OSError("provider request body ended early")
                chunks.append(chunk)
                left -= len(chunk)
            body = b"".join(chunks)
            url, headers = admit_provider_request(
                proxy.route, target=self.path, selected_model=proxy.model,
                trusted_credential=proxy.credential,
                headers=dict(raw_headers), body=body)
            parsed = json.loads(body)
            declared, reason = resolve_declared_output_tokens(parsed)
            if reason is not None or declared is None or proxy.closed:
                raise AcpProviderRouteRejected("provider declaration is invalid")
            attempt = proxy.journal.reserve_provider_attempt(
                route=proxy.route.name, body=body, declared_output_tokens=declared,
                limits=proxy.limits)
        except (AcpProviderRouteRejected, AcpJudgmentOutcomeUnknown, ValueError,
                TimeoutError, OSError, socket.timeout):
            self._fail()
            return

        response: ProviderHttpResponse | None = None
        receipt = None
        try:
            if proxy.closed:
                raise OSError("provider proxy closed before dispatch")
            response = proxy.transport(url, headers, body, proxy.deadline_monotonic)
            if (not isinstance(response, ProviderHttpResponse)
                    or type(response.status) is not int or response.status != 200
                    or not isinstance(response.body, bytes)
                    or len(response.body) > MAX_SSE_BYTES):
                raise ValueError("provider response is unqualified")
            receipt = parse_acp_provider_stream(
                protocol=proxy.route.protocol, content_type=response.content_type,
                body=response.body)
            if (not receipt.output_proven or receipt.usage_state != "known"
                    or receipt.actual_output_tokens > attempt["declared_output_tokens"]
                    or proxy.closed):
                raise ValueError("provider terminal or usage is unproven")
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(response.body)))
            self.end_headers()
            self.wfile.write(response.body)
            self.wfile.flush()
            settled = proxy.journal.settle_provider_attempt(
                index=attempt["index"], status=200, receipt=receipt,
                transport_complete=True)
            if settled["phase"] != "completed":
                raise AcpJudgmentOutcomeUnknown("provider completion was not durably accepted")
        except (urllib.error.URLError, urllib.error.HTTPError, http.client.HTTPException,
                AcpJudgmentOutcomeUnknown, BrokenPipeError, ConnectionResetError,
                OSError, TimeoutError, ValueError):
            # The pre-dispatch marker is already durable. A failed transport,
            # partial response or failed client delivery leaves it unknown.
            try:
                proxy.journal.settle_provider_attempt(
                    index=attempt["index"], status=response.status if response else 0,
                    receipt=receipt, transport_complete=False)
            except (AcpJudgmentOutcomeUnknown, OSError):
                pass
            self._fail()


class AcpJudgmentProviderProxy:
    """Private loopback listener for one selected root and one provider route."""

    def __init__(self, journal: AcpJudgmentJournal, *, route_name: str,
                 model: str, credential: str, limits: dict, transport=None) -> None:
        self.route = selected_route(route_name)
        if not isinstance(journal, AcpJudgmentJournal):
            raise ValueError("durable judgment journal is required")
        if not isinstance(model, str) or not model or not isinstance(credential, str) or not credential:
            raise ValueError("trusted provider model and credential are required")
        self.journal = journal
        self.model = model
        self.credential = credential
        self.limits = dict(limits)
        self.transport = transport or _send_https
        self.deadline_monotonic = time.monotonic() + max(
            0.0, (self.limits["deadline_at_ms"] - time.time() * 1000) / 1000)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.daemon_threads = True
        self._server.proxy = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._dispatch_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._closed = False
        self._started = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}{self.route.local_base_path}"

    def __enter__(self):
        if self._closed:
            raise RuntimeError("provider proxy is closed")
        if not self._started:
            self._thread.start()
            self._started = True
        return self

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            # A handler holds this lock through provider transport, client
            # delivery and journal settlement. Waiting here makes return from
            # close a boundary after which no outbound call can begin.
            with self._dispatch_lock:
                pass
            if self._started:
                self._server.shutdown()
                self._thread.join(timeout=2)
            self._server.server_close()

    def __exit__(self, *_args):
        self.close()
