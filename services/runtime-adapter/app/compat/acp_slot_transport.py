"""Adapt a signed single-root runner byte stream to the existing ACP client."""

from __future__ import annotations

import threading
import time
from typing import Any

from packages.contracts.acp_product_slot import PRODUCT_ENV_ALLOWLIST

from ..acp_product_slot_client import (
    ProductRunnerClient,
    ProductSlotError,
)
from ..research_judgment_acp_runner_client import RunnerClientError, RunnerExit
from .dsh_acp import AcpTransportError, _AcpProcess

_CLOSE_TIMEOUT_SECONDS = 6.0


class _SlotInput:
    def __init__(self, handle: _SlotHandle) -> None:
        self.handle = handle
        self.closed = False

    def write(self, content: bytes) -> int:
        if self.closed:
            raise OSError("ACP slot input is closed")
        try:
            self.handle.session.send_stdin(content)
        except (OSError, RunnerClientError):
            raise OSError("ACP slot input was lost") from None
        return len(content)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.handle.session.cancel()


class _SlotOutput:
    def __init__(self, handle: _SlotHandle) -> None:
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
                raise AcpTransportError("ACP slot ended without a signed exit") from None
            if isinstance(event, bytes):
                self.buffer.extend(event)
            elif isinstance(event, RunnerExit):
                self.handle.exit = event
                self.handle.done.set()


class _SlotHandle:
    """Stream/exit view only; there is no local DSH subprocess or PID."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.done = threading.Event()
        self.exit: RunnerExit | None = None
        self.stdin = _SlotInput(self)
        self.stdout = _SlotOutput(self)

    def poll(self) -> int | None:
        if self.exit is None:
            return None
        if self.exit.code is not None:
            return self.exit.code
        return -(self.exit.signal or 1)


class SlotAcpProcess(_AcpProcess):
    def __init__(self, command, cwd, environment, *, registry, guard_b64=None) -> None:
        super().__init__(command, cwd, environment)
        self.registry = registry
        self.guard_b64 = guard_b64
        self.scope: dict[str, str] = {
            "workspace_id": environment.get("BYQ_WORKSPACE_ID", ""),
            "owner_principal": environment.get("BYQ_OWNER_PRINCIPAL", ""),
            "session_id": environment.get("BYQ_SESSION_ID", ""),
            "trace_id": environment.get("BYQ_TRACE_ID", ""),
            "root_run_id": environment.get("BYQ_ROOT_RUN_ID", ""),
            "runtime_boot_id": environment.get("BYQ_RUNTIME_BOOT_ID", ""),
            "generation_id": environment.get("BYQ_DSH_RUN_ID", ""),
            "cwd_leaf": self.cwd.name,
        }
        self._startup_unknown = False
        self._safe_no_process_close = False
        self._cleanup_exit: RunnerExit | None = None
        self._exit_drain_attempted = False

    @property
    def no_process_cleanup_complete(self) -> bool:
        return self.process is None and self._safe_no_process_close

    def start(self) -> None:
        if self.process is not None:
            raise AcpTransportError("ACP slot is already started")
        env = self.environment
        child_env = {key: value for key, value in env.items() if key in PRODUCT_ENV_ALLOWLIST}
        try:
            session = ProductRunnerClient(self.registry).start(
                scope=self.scope, env=child_env,
                deadline_at_ms=int(time.time() * 1000) + 3_600_000,
                expected_cwd=str(self.cwd),
                guard_b64=self.guard_b64,
            )
        except Exception as error:
            try:
                owns_scope = self.registry.owns(self.scope)
            except (TypeError, ValueError):
                owns_scope = False
            if not owns_scope:
                self._safe_no_process_close = True
            else:
                self._startup_unknown = True
            raise
        self.process = _SlotHandle(session)
        self._reader = threading.Thread(target=self._read_loop,
            name="byq-dsh-acp-reader", daemon=True)
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
                raise AcpTransportError("ACP slot startup outcome remains unknown")
            return
        self._closed = True
        deadline = time.monotonic() + _CLOSE_TIMEOUT_SECONDS
        try:
            handle.stdin.close()
        except (OSError, RunnerClientError):
            # A signed EXIT already in flight can still prove cleanup even if
            # the cancel frame could not be written.
            pass
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=max(0.0, deadline - time.monotonic()))
        if reader is not None and reader.is_alive():
            raise AcpTransportError("ACP slot reader did not stop before cleanup deadline")
        if handle.exit is None:
            if self._exit_drain_attempted:
                raise AcpTransportError("ACP slot cleanup receipt remains unavailable")
            self._exit_drain_attempted = True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AcpTransportError("ACP slot cleanup receipt exceeded its deadline")
            try:
                handle.exit = handle.session.wait_exit(timeout_s=remaining)
                handle.done.set()
            except (OSError, RunnerClientError, TimeoutError):
                raise AcpTransportError("ACP slot cleanup receipt is unavailable") from None
        try:
            self.registry.cleanup(self.scope, handle.exit)
        except ProductSlotError:
            raise AcpTransportError("ACP slot cleanup is unconfirmed") from None
        self._cleanup_exit = handle.exit
