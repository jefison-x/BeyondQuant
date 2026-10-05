"""Adapt a signed isolated judgment-runner byte stream to the ACP client.

The process that owns a judgment root's ACP child lives behind the dedicated
judgment runner Unix socket. This module relays ACP bytes and treats cleanup as
proven only when the runner returns an authenticated signed EXIT; a lost
connection stays unknown. There is no local DSH subprocess or PID here.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from .compat.dsh_acp import AcpTransportError, _AcpProcess
from .research_judgment_acp_runner_client import (
    RunnerClientError,
    RunnerExit,
    RunnerRejected,
    RunnerStartupRejected,
)

_CLOSE_TIMEOUT_SECONDS = 6.0


class _JudgmentInput:
    def __init__(self, handle: "_JudgmentHandle") -> None:
        self.handle = handle
        self.closed = False

    def write(self, content: bytes) -> int:
        if self.closed:
            raise OSError("ACP judgment input is closed")
        try:
            self.handle.session.send_stdin(content)
        except (OSError, RunnerClientError):
            raise OSError("ACP judgment input was lost") from None
        return len(content)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.handle.session.cancel()


class _JudgmentOutput:
    def __init__(self, handle: "_JudgmentHandle") -> None:
        self.handle = handle
        self.buffer = bytearray()

    def readline(self, limit: int) -> bytes:
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0 or len(self.buffer) >= limit:
                size = min(newline + 1 if newline >= 0 else len(self.buffer), limit)
                result = bytes(self.buffer[:size])
                del self.buffer[:size]
                return result
            if self.handle.done.is_set():
                result = bytes(self.buffer)
                self.buffer.clear()
                return result
            try:
                event = self.handle.session.receive()
            except (OSError, RunnerClientError):
                self.handle.done.set()
                raise AcpTransportError("ACP judgment ended without a signed exit") from None
            if isinstance(event, bytes):
                self.buffer.extend(event)
            elif isinstance(event, RunnerExit):
                self.handle.exit = event
                self.handle.done.set()


class _JudgmentHandle:
    """Stream/exit view only; there is no local DSH subprocess or PID."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.done = threading.Event()
        self.exit: RunnerExit | None = None
        self.stdin = _JudgmentInput(self)
        self.stdout = _JudgmentOutput(self)

    def poll(self) -> int | None:
        if self.exit is None:
            return None
        if self.exit.code is not None:
            return self.exit.code
        return -(self.exit.signal or 1)


class JudgmentRunnerProcess(_AcpProcess):
    """ACP client over one authenticated judgment runner session."""

    def __init__(self, command, cwd, environment, *, runner_client, start) -> None:
        super().__init__(command, cwd, environment)
        self._runner_client = runner_client
        self._start = start
        self._startup_unknown = False
        self._safe_no_process_close = False
        self._cleanup_exit: RunnerExit | None = None
        self._exit_drain_attempted = False

    @property
    def no_process_cleanup_complete(self) -> bool:
        return self.process is None and self._safe_no_process_close

    def start(self) -> None:
        if self.process is not None:
            raise AcpTransportError("ACP judgment runner is already started")
        start = self._start
        try:
            session = self._runner_client.start(
                scope=start.scope, env=start.environment,
                proxy_token_env=start.proxy_token_env, proxy_token=start.proxy_token,
                overlay_b64=start.overlay_b64, deadline_at_ms=start.deadline_at_ms,
                expected_cwd=start.expected_cwd,
            )
        except RunnerRejected:
            # Authenticated pre-launch rejection: no child process was created.
            self._safe_no_process_close = True
            raise
        except (RunnerStartupRejected, RunnerClientError):
            self._startup_unknown = True
            raise
        except Exception:
            self._startup_unknown = True
            raise
        self.process = _JudgmentHandle(session)
        self._reader = threading.Thread(
            target=self._read_loop, name="byq-judgment-acp-reader", daemon=True)
        self._reader.start()
        self._initialize()

    def close(self) -> None:
        if self._cleanup_exit is not None:
            return
        handle = self.process
        if handle is None:
            if self._safe_no_process_close:
                self._closed = True
                return
            if self._startup_unknown:
                raise AcpTransportError("ACP judgment startup outcome remains unknown")
            return
        self._closed = True
        deadline = time.monotonic() + _CLOSE_TIMEOUT_SECONDS
        try:
            handle.stdin.close()
        except (OSError, RunnerClientError):
            # A signed EXIT already in flight can still prove cleanup.
            pass
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=max(0.0, deadline - time.monotonic()))
        if reader is not None and reader.is_alive():
            raise AcpTransportError("ACP judgment reader did not stop before cleanup deadline")
        if handle.exit is None:
            if self._exit_drain_attempted:
                raise AcpTransportError("ACP judgment cleanup receipt remains unavailable")
            self._exit_drain_attempted = True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AcpTransportError("ACP judgment cleanup receipt exceeded its deadline")
            try:
                handle.exit = handle.session.wait_exit(timeout_s=remaining)
                handle.done.set()
            except (OSError, RunnerClientError, TimeoutError):
                raise AcpTransportError("ACP judgment cleanup receipt is unavailable") from None
        if not isinstance(handle.exit, RunnerExit) or handle.exit.cleanup != "proven":
            raise AcpTransportError("ACP judgment cleanup remains unknown")
        self._cleanup_exit = handle.exit
