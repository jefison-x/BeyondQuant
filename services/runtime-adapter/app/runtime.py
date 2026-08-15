from __future__ import annotations

import os
import queue
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig, Notification

from .contracts import WorkflowTraceEvent, make_workflow_trace_event
from .identifiers import contained_session_path, validate_identifier
from .normalization import normalize_dsh_notification


class SessionConflict(RuntimeError):
    """The requested lifecycle operation is invalid for the current state."""


class SessionStatus:
    STARTING: ClassVar[str] = "starting"
    READY: ClassVar[str] = "ready"
    IDLE: ClassVar[str] = "idle"
    RUNNING: ClassVar[str] = "running"
    CANCELLING: ClassVar[str] = "cancelling"
    INTERRUPTED: ClassVar[str] = "interrupted"
    FAILED: ClassVar[str] = "failed"
    CLOSED: ClassVar[str] = "closed"

    ACTIVE_PROMPT: ClassVar[frozenset[str]] = frozenset({RUNNING, CANCELLING})
    PROMPTABLE: ClassVar[frozenset[str]] = frozenset({READY, IDLE})


@dataclass(slots=True)
class ActiveRun:
    run_id: str
    soft_cancel_requested: bool = False
    hard_cancelled: bool = False


@dataclass(slots=True)
class RuntimeSession:
    session_id: str
    trace_id: str
    harness: DeepSeekHarness
    status: str = SessionStatus.STARTING
    active_run: ActiveRun | None = None
    sequence: int = 0
    subscribers: list[queue.Queue[WorkflowTraceEvent | None]] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)


class RuntimeAdapter:
    """Own one official DSH SDK subprocess per active BYQ session.

    rc.6 has no prompt-cancel or per-session close. A dedicated process makes
    hard cancellation and failure isolation explicit: hard cancel closes the
    owned process, while soft cancel marks only the current run and resets to
    idle when that run settles.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, RuntimeSession] = {}
        self._lock = threading.RLock()
        self._runtime_root = Path(os.environ.get("BYQ_DSH_RUNTIME_ROOT", "/opt/dsh-runtime"))
        self._composition = Path(
            os.environ.get(
                "BYQ_DSH_COMPOSITION",
                "/opt/byq/compositions/byq-product-sdk.cordis.yml",
            )
        )
        self._session_root = Path(
            os.environ.get("DSH_SESSION_ROOT", "/var/lib/byq/dsh-sessions")
        ).expanduser().resolve()
        self._provider = os.environ.get("BYQ_DSH_PROVIDER", "deepseek-official")
        self._model = os.environ.get("BYQ_DSH_MODEL", "deepseek-v4-flash")

    @property
    def runtime_command(self) -> tuple[str, ...]:
        node = shutil.which("node") or "node"
        runtime = self._runtime_root / "node_modules/@deepseek-ai/dsh-sdk-jsonrpc-demo/lib/bin.js"
        return (node, str(runtime))

    def readiness(self) -> dict[str, Any]:
        return {
            "runtime_adapter": "ready",
            "sdk": "deepseek-harness-sdk==0.1.0rc6",
            "runtime_bin": "deepseek-harness-runtime-bin==0.1.0rc6",
            "explicit_runtime": self.runtime_command[1],
            "composition": str(self._composition),
            "composition_exists": self._composition.is_file(),
            "process_ownership": "one-per-active-session",
            "session_states": [
                SessionStatus.STARTING,
                SessionStatus.READY,
                SessionStatus.IDLE,
                SessionStatus.RUNNING,
                SessionStatus.CANCELLING,
                SessionStatus.INTERRUPTED,
                SessionStatus.FAILED,
                SessionStatus.CLOSED,
            ],
        }

    def create_session(self, session_id: str, trace_id: str) -> dict[str, Any]:
        validate_identifier(session_id, field="session_id")
        validate_identifier(trace_id, field="trace_id")
        session_root = contained_session_path(self._session_root, session_id)

        with self._lock:
            if session_id in self._sessions:
                raise SessionConflict(f"BYQ session already exists: {session_id}")
            config = DeepSeekHarnessConfig(
                provider=self._provider,
                model=self._model,
                cordis=str(self._composition),
                session_root=str(session_root),
                launch_args_override=self.runtime_command,
                env={
                    "BYQ_MCP_URL": os.environ.get("BYQ_MCP_URL", "http://mcp:8300/mcp/v1"),
                    "BYQ_MCP_TOKEN": os.environ.get("BYQ_MCP_TOKEN", ""),
                },
                request_timeout_seconds=15.0,
                shutdown_timeout_seconds=2.0,
            )
            harness = DeepSeekHarness(config=config)
            record = RuntimeSession(session_id=session_id, trace_id=trace_id, harness=harness)
            self._sessions[session_id] = record

        try:
            harness.start()
            with record.lock:
                record.status = SessionStatus.READY
                self._emit(record, "session.ready", "runtime-adapter", {"status": "ready"})
            return self.describe_session(record)
        except Exception:
            with self._lock:
                self._sessions.pop(session_id, None)
            harness.close()
            raise

    def submit_prompt(self, session_id: str, content: str) -> str:
        record = self._get(session_id)
        with record.lock:
            if record.status not in SessionStatus.PROMPTABLE or record.active_run is not None:
                raise SessionConflict(
                    f"session {session_id} cannot accept a prompt in state {record.status}"
                )
            run = ActiveRun(run_id=uuid.uuid4().hex)
            record.active_run = run
            record.status = SessionStatus.RUNNING
            self._emit(record, "session.started", "runtime-adapter", {"run_id": run.run_id})

        worker = threading.Thread(
            target=self._run_prompt,
            args=(record, run, content),
            name=f"byq-dsh-session-{session_id}",
            daemon=True,
        )
        try:
            worker.start()
        except Exception:
            with record.lock:
                if record.active_run is run:
                    record.active_run = None
                    record.status = SessionStatus.FAILED
                    self._emit(record, "session.failed", "runtime-adapter", {"error": "thread-start"})
            raise
        return run.run_id

    def _run_prompt(self, record: RuntimeSession, run: ActiveRun, content: str) -> None:
        try:
            result = record.harness.start_session(record.session_id).run(
                content,
                on_notification=lambda notification: self._on_notification(record, notification),
            )
        except Exception as exc:
            with record.lock:
                if record.active_run is not run:
                    return
                record.active_run = None
                if run.hard_cancelled or record.status in {SessionStatus.INTERRUPTED, SessionStatus.CLOSED}:
                    return
                if run.soft_cancel_requested:
                    record.status = SessionStatus.IDLE
                    self._emit(record, "session.result.discarded", "runtime-adapter", {"reason": "soft-cancelled"})
                    return
                record.status = SessionStatus.FAILED
                self._emit(record, "session.failed", "runtime-adapter", {"error": type(exc).__name__})
            return

        with record.lock:
            if record.active_run is not run:
                return
            record.active_run = None
            if run.hard_cancelled or record.status in {SessionStatus.INTERRUPTED, SessionStatus.CLOSED}:
                return
            if run.soft_cancel_requested:
                record.status = SessionStatus.IDLE
                self._emit(record, "session.result.discarded", "runtime-adapter", {"reason": "soft-cancelled"})
                return
            record.status = SessionStatus.IDLE
            self._emit(
                record,
                "session.result",
                "runtime-adapter",
                {"finish_reason": result.finish_reason},
            )

    def cancel_session(self, session_id: str, mode: str) -> dict[str, Any]:
        if mode not in {"soft", "hard"}:
            raise ValueError("cancel mode must be soft or hard")
        record = self._get(session_id)
        with record.lock:
            run = record.active_run
            if run is None or record.status not in SessionStatus.ACTIVE_PROMPT:
                raise SessionConflict(f"session {session_id} has no active prompt")
            if mode == "soft":
                run.soft_cancel_requested = True
                record.status = SessionStatus.CANCELLING
            else:
                run.hard_cancelled = True
                record.status = SessionStatus.INTERRUPTED
                # The owned process is closed synchronously below. Detach the
                # run now so no post-close result can be accepted or emitted.
                record.active_run = None
            self._emit(
                record,
                "session.cancelled",
                "runtime-adapter",
                {"mode": mode, "persistence": "dsh-owned", "resume": "new-run-after-interrupted"},
            )
        if mode == "hard":
            record.harness.close()
        return self.describe_session(record)

    def release_session(self, session_id: str) -> dict[str, Any]:
        record = self._get(session_id)
        with record.lock:
            if record.active_run is not None or record.status in SessionStatus.ACTIVE_PROMPT:
                raise SessionConflict(f"session {session_id} has an active prompt")
            record.status = SessionStatus.CLOSED
            self._emit(record, "session.closed", "runtime-adapter", {"reason": "released"})
        record.harness.close()
        with self._lock:
            if self._sessions.get(session_id) is record:
                del self._sessions[session_id]
        with record.lock:
            for subscriber in list(record.subscribers):
                subscriber.put(None)
        return self.describe_session(record)

    def subscribe(self, session_id: str) -> queue.Queue[WorkflowTraceEvent | None]:
        record = self._get(session_id)
        subscriber: queue.Queue[WorkflowTraceEvent | None] = queue.Queue()
        with record.lock:
            if record.status == SessionStatus.CLOSED:
                raise KeyError(f"closed BYQ session: {session_id}")
            record.subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, session_id: str, subscriber: queue.Queue[WorkflowTraceEvent | None]) -> None:
        with self._lock:
            record = self._sessions.get(session_id)
        if record is None:
            return
        with record.lock:
            if subscriber in record.subscribers:
                record.subscribers.remove(subscriber)

    def describe_session(self, record: RuntimeSession) -> dict[str, Any]:
        with record.lock:
            return {
                "session_id": record.session_id,
                "trace_id": record.trace_id,
                "status": record.status,
                "active_prompt": record.active_run is not None,
                "process_ownership": "dedicated",
                "persistence": "dsh-owned",
            }

    def close(self) -> None:
        with self._lock:
            records = list(self._sessions.values())
            self._sessions.clear()
        for record in records:
            with record.lock:
                record.active_run = None
                record.status = SessionStatus.CLOSED
                self._emit(record, "session.closed", "runtime-adapter", {"reason": "adapter-shutdown"})
            record.harness.close()
            with record.lock:
                for subscriber in record.subscribers:
                    subscriber.put(None)

    def _get(self, session_id: str) -> RuntimeSession:
        with self._lock:
            record = self._sessions.get(session_id)
        if record is None:
            raise KeyError(f"unknown BYQ session: {session_id}")
        return record

    def _on_notification(self, record: RuntimeSession, notification: Notification) -> None:
        event = normalize_dsh_notification(
            notification,
            trace_id=record.trace_id,
            session_id=record.session_id,
            sequence=0,
        )
        if event is None:
            return
        with record.lock:
            if record.status in {SessionStatus.INTERRUPTED, SessionStatus.CLOSED}:
                return
            self._publish(record, event)

    def _emit(self, record: RuntimeSession, kind: str, source: str, payload: dict[str, Any]) -> None:
        event = make_workflow_trace_event(
            trace_id=record.trace_id,
            session_id=record.session_id,
            sequence=0,
            kind=kind,
            source=source,  # type: ignore[arg-type]
            payload=payload,
        )
        with record.lock:
            self._publish(record, event)

    @staticmethod
    def _publish(record: RuntimeSession, event: WorkflowTraceEvent) -> None:
        """Allocate and publish while holding the one session ordering lock."""

        record.sequence += 1
        ordered_event = {**event, "sequence": record.sequence}
        for subscriber in list(record.subscribers):
            subscriber.put(ordered_event)
