"""Unwired, single-route outbound proxy for one ADR-0097 judgment root.

The selected route, model, credential, limits and journal must come from a
trusted admitted invocation. This module does not open the ACP entry itself.
"""

from __future__ import annotations

import http.client
import base64
import json
import os
from pathlib import Path
import selectors
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .research_judgment_acp_journal import AcpJudgmentJournal
from .research_judgment_acp_provider_routes import (
    LOCAL_TOKEN_PREFIX, AcpProviderRouteRejected, admit_provider_request, selected_route,
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


class _IsolatedHttpsTransport:
    """One killable HTTPS attempt; abort unblocks proxy close during DNS stalls."""

    def __init__(self, *, command=None) -> None:
        self._command = command or (sys.executable, "-m", "app.research_judgment_acp_provider_worker")
        self._require_private_ready = command is None
        self._lock = threading.Lock()
        self._active = None
        self._aborted = False

    @staticmethod
    def _worker_environment() -> dict[str, str]:
        service_root = Path(__file__).resolve().parents[1]
        packages_root = next(
            (path for path in (service_root, *service_root.parents)
             if (path / "packages" / "contracts").is_dir()), None)
        if packages_root is None:
            raise AcpJudgmentOutcomeUnknown("provider worker packages are unavailable")
        return {"PYTHONPATH": os.pathsep.join((str(service_root), str(packages_root))),
                "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}

    @staticmethod
    def _stop(process) -> None:
        if process.poll() is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
        if process.poll() is None:
            raise AcpJudgmentOutcomeUnknown("provider transport process did not stop")

    @staticmethod
    def _wait_private_worker(process, deadline_monotonic: float) -> None:
        """Never deliver a provider credential before the worker disables /proc."""
        assert process.stdout is not None
        marker = b"BYQ_ACP_WORKER_PRIVATE_V1\n"
        descriptor = process.stdout.fileno()
        os.set_blocking(descriptor, False)
        received = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while len(received) < len(marker):
                remaining = deadline_monotonic - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("provider worker private startup expired")
                if not selector.select(remaining):
                    raise TimeoutError("provider worker private startup expired")
                chunk = os.read(descriptor, len(marker) - len(received))
                if not chunk:
                    raise OSError("provider worker ended before private startup")
                received.extend(chunk)
                if not marker.startswith(received):
                    raise OSError("provider worker private startup is invalid")

    @staticmethod
    def _exchange(process, payload: bytes, deadline_monotonic: float) -> bytes:
        """Pump private stdin/stdout with an absolute deadline and memory cap."""
        assert process.stdin is not None and process.stdout is not None
        stdin, stdout = process.stdin, process.stdout
        os.set_blocking(stdin.fileno(), False)
        os.set_blocking(stdout.fileno(), False)
        result = bytearray()
        written = 0
        output_limit = MAX_SSE_BYTES * 2 + 4096
        with selectors.DefaultSelector() as selector:
            selector.register(stdin, selectors.EVENT_WRITE)
            selector.register(stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline_monotonic - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("provider transport deadline expired")
                events = selector.select(remaining)
                if not events:
                    raise TimeoutError("provider transport deadline expired")
                for key, _ in events:
                    if key.fileobj is stdin:
                        try:
                            size = os.write(stdin.fileno(), payload[written:written + 65536])
                        except BrokenPipeError as error:
                            raise OSError("provider worker ended before request delivery") from error
                        written += size
                        if written == len(payload):
                            selector.unregister(stdin)
                            stdin.close()
                    else:
                        chunk = os.read(stdout.fileno(), 65536)
                        if not chunk:
                            selector.unregister(stdout)
                            stdout.close()
                        else:
                            result.extend(chunk)
                            if len(result) > output_limit:
                                raise OSError("provider worker response exceeds bound")
        remaining = max(0.0, deadline_monotonic - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            raise TimeoutError("provider worker did not exit by deadline") from error
        return bytes(result)

    def __call__(self, url: str, headers: dict[str, str], body: bytes,
                 deadline_monotonic: float) -> ProviderHttpResponse:
        payload = json.dumps({
            "url": url, "headers": headers,
            "body_b64": base64.b64encode(body).decode("ascii"),
            "deadline_monotonic": deadline_monotonic,
        }, separators=(",", ":")).encode()
        if len(payload) > 12 * 1024 * 1024:
            raise ValueError("provider worker request exceeds bound")
        process = None
        try:
            if not self._lock.acquire(timeout=2):
                raise AcpJudgmentOutcomeUnknown("provider transport start did not settle")
            try:
                if self._aborted or time.monotonic() >= deadline_monotonic:
                    raise TimeoutError("provider transport is closed or expired")
                process = subprocess.Popen(
                    self._command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, close_fds=True,
                    env=self._worker_environment())
                self._active = process
            finally:
                self._lock.release()
            if self._aborted:
                raise TimeoutError("provider transport was closed before request delivery")
            if self._require_private_ready:
                self._wait_private_worker(process, deadline_monotonic)
            if self._aborted:
                raise TimeoutError("provider transport was closed before request delivery")
            raw = self._exchange(process, payload, deadline_monotonic)
            if process.returncode != 0 or len(raw) > (MAX_SSE_BYTES * 2 + 4096):
                raise OSError("provider transport ended without a bounded reply")
            try:
                result = json.loads(raw)
                response = ProviderHttpResponse(
                    result["status"], result["content_type"],
                    base64.b64decode(result["body_b64"], validate=True))
            except (KeyError, TypeError, ValueError) as error:
                raise OSError("provider transport reply is invalid") from error
            if (type(response.status) is not int or not isinstance(response.content_type, str)
                    or len(response.body) > MAX_SSE_BYTES):
                raise OSError("provider transport reply is unqualified")
            return response
        finally:
            if process is not None:
                self._stop(process)
                if process.stdin is not None:
                    process.stdin.close()
                if process.stdout is not None:
                    process.stdout.close()
                with self._lock:
                    if self._active is process:
                        self._active = None

    def abort(self) -> None:
        # This flag must become visible even if Popen itself is stuck while
        # holding the registration lock. The sender rechecks before stdin I/O.
        self._aborted = True
        if not self._lock.acquire(timeout=2):
            raise AcpJudgmentOutcomeUnknown("provider transport start did not stop")
        try:
            process = self._active
        finally:
            self._lock.release()
        if process is not None:
            self._stop(process)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def finish(self) -> None:
        try:
            super().finish()
        finally:
            self.server.proxy._untrack_client(self.connection)  # type: ignore[attr-defined]

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
            with proxy._client_lock:
                proxy._active_client = self.connection
            try:
                self._handle_post(proxy)
            finally:
                with proxy._client_lock:
                    if proxy._active_client is self.connection:
                        proxy._active_client = None


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
                local_credential=proxy.local_credential,
                upstream_credential=proxy.credential,
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
            response = proxy.transport(
                url, headers, body,
                min(proxy.deadline_monotonic, time.monotonic() + 120))
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
            remaining = proxy.deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("provider delivery deadline expired")
            self.connection.settimeout(min(remaining, 2.0))
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


class _TrackedServer(ThreadingHTTPServer):
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(2.0)
        if not self.proxy._track_client(connection):  # type: ignore[attr-defined]
            connection.close()
            raise OSError("provider proxy closed during accept")
        return connection, address


class AcpJudgmentProviderProxy:
    """Private local listener for one selected root and one provider route."""

    def __init__(self, journal: AcpJudgmentJournal, *, route_name: str,
                 model: str, credential: str, limits: dict, transport=None,
                 bind_host: str = "127.0.0.1") -> None:
        self.route = selected_route(route_name)
        if not isinstance(journal, AcpJudgmentJournal):
            raise ValueError("durable judgment journal is required")
        if not isinstance(model, str) or not model or not isinstance(credential, str) or not credential:
            raise ValueError("trusted provider model and credential are required")
        frozen = journal.snapshot()
        public = frozen.get("provider_profile") if isinstance(frozen, dict) else None
        # The listener may be constructed once the provider profile is frozen and
        # the root admitted (``begun``), because the private overlay it serves is
        # needed to launch the ACP root before the native Agent is bound. Actual
        # provider egress is still gated by the journal's ``reserve_provider_attempt``,
        # which refuses every call until the phase is ``prompt_may_have_dispatched``.
        if (not isinstance(public, dict)
                or frozen.get("phase") not in {"begun", "bound", "prompt_may_have_dispatched"}
                or public.get("provider_route") != route_name
                or public.get("model") != model or public.get("limits") != limits):
            raise ValueError("live proxy differs from frozen judgment provider profile")
        self.journal = journal
        self.model = model
        self.credential = credential
        self.local_credential = LOCAL_TOKEN_PREFIX + secrets.token_urlsafe(32)
        if self.local_credential == credential:
            raise ValueError("local proxy token must differ from provider credential")
        self.limits = dict(limits)
        self.transport = transport or _IsolatedHttpsTransport()
        self.deadline_monotonic = time.monotonic() + max(
            0.0, (self.limits["deadline_at_ms"] - time.time() * 1000) / 1000)
        from .research_judgment_acp_provider_overlay import valid_local_proxy_bind_host
        if not valid_local_proxy_bind_host(bind_host):
            raise ValueError("exact private ACP provider bind address required")
        self._server = _TrackedServer((bind_host, 0), _Handler)
        self._server.daemon_threads = True
        self._server.proxy = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._dispatch_lock = threading.Lock()
        self._client_lock = threading.Lock()
        self._active_client = None
        self._clients: set[socket.socket] = set()
        self._close_lock = threading.Lock()
        self._closed = False
        self._close_complete = False
        self._started = False

    @classmethod
    def from_frozen_profile(cls, journal: AcpJudgmentJournal, profile,
                            *, transport=None, bind_host: str = "127.0.0.1") -> "AcpJudgmentProviderProxy":
        """Keep the upstream key and journal choice from the same built profile."""
        from .research_judgment_acp_provider_profile import AcpJudgmentProviderProfile

        if not isinstance(profile, AcpJudgmentProviderProfile):
            raise ValueError("built ACP provider profile is required")
        public = profile.public
        if not isinstance(public, dict):
            raise ValueError("exact ACP provider profile is required")
        frozen = journal.snapshot()
        if not isinstance(frozen, dict) or frozen.get("provider_profile") != public:
            raise ValueError("provider profile differs from durable root")
        return cls(journal, route_name=public["provider_route"], model=public["model"],
                   credential=profile.upstream_credential, limits=public["limits"],
                   transport=transport, bind_host=bind_host)

    def _track_client(self, connection: socket.socket) -> bool:
        with self._client_lock:
            if self._closed:
                return False
            self._clients.add(connection)
            return True

    def _untrack_client(self, connection: socket.socket) -> None:
        with self._client_lock:
            self._clients.discard(connection)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}{self.route.local_base_path}"

    def write_private_overlay(self, directory: Path, *,
                              provider_session_id: str | None = None) -> Path:
        """Derive the last-layer DSH route from this running proxy instance."""
        from .research_judgment_acp_provider_overlay import write_private_provider_overlay

        with self._close_lock:
            if (not self._started or self._closed or not self._thread.is_alive()
                    or self._server.socket.fileno() < 0):
                raise ValueError("running ACP provider proxy is required")
            return write_private_provider_overlay(
                directory, route_name=self.route.name, model=self.model,
                proxy_base_url=self.base_url, provider_session_id=provider_session_id)

    def __enter__(self):
        with self._close_lock:
            if self._closed:
                raise RuntimeError("provider proxy is closed")
            if not self._started:
                self._thread.start()
                self._started = True
            if not self._thread.is_alive():
                raise RuntimeError("provider proxy listener is unavailable")
        return self

    def close(self) -> None:
        with self._close_lock:
            if self._close_complete:
                return
            with self._client_lock:
                self._closed = True
                clients = tuple(self._clients)
            abort_error = None
            try:
                if isinstance(self.transport, _IsolatedHttpsTransport):
                    self.transport.abort()
            except AcpJudgmentOutcomeUnknown as error:
                abort_error = error
            for client in clients:
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            # A handler holds this lock through provider transport, client
            # delivery and journal settlement. Waiting here makes return from
            # close a boundary after which no outbound call can begin.
            settled = self._dispatch_lock.acquire(timeout=2)
            if settled:
                self._dispatch_lock.release()
            if self._started:
                self._server.shutdown()
                self._thread.join(timeout=2)
            self._server.server_close()
            client_deadline = time.monotonic() + 2
            while True:
                with self._client_lock:
                    clients_left = bool(self._clients)
                if not clients_left or time.monotonic() >= client_deadline:
                    break
                time.sleep(0.005)
            if not settled:
                raise AcpJudgmentOutcomeUnknown("provider dispatch did not stop after close")
            if abort_error is not None:
                raise abort_error
            if self._started and self._thread.is_alive():
                raise AcpJudgmentOutcomeUnknown("provider listener did not stop")
            if clients_left:
                raise AcpJudgmentOutcomeUnknown("provider clients did not stop")
            self._close_complete = True

    def __exit__(self, *_args):
        self.close()
