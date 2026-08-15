from __future__ import annotations

import os
import queue
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig, Notification

from .contracts import WorkflowTraceEvent, make_workflow_trace_event
from .normalization import normalize_dsh_notification


@dataclass(slots=True)
class RuntimeSession:
    session_id: str
    trace_id: str
    harness: DeepSeekHarness
    status: str = "starting"
    cancelled: bool = False
    sequence: int = 0
    subscribers: list[queue.Queue[WorkflowTraceEvent | None]] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)


class RuntimeAdapter:
    """Own one official DSH SDK subprocess per active BYQ session.

    The per-session process is deliberate for rc.6: the official SDK exposes
    runtime close but no prompt cancellation or per-session close. Hard cancel
    therefore closes the owned process and leaves DSH persistence with the
    Agent Plane. This prototype keeps only BYQ identity and trace state here.
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
        self._session_root = Path(os.environ.get("DSH_SESSION_ROOT", "/var/lib/byq/dsh-sessions"))
        self._provider = os.environ.get("BYQ_DSH_PROVIDER", "deepseek-official")
        self._model = os.environ.get("BYQ_DSH_MODEL", "deepseek-v4-flash")

    @property
    def runtime_command(self) -> tuple[str, ...]:
        node = shutil.which("node") or "node"
        runtime = self._runtime_root / "node_modules/@deepseek-ai/dsh-sdk-jsonrpc-demo/lib/packaged-bin.js"
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
        }

    def create_session(self, session_id: str, trace_id: str) -> dict[str, Any]:
        with self._lock:
            if session_id in self._sessions:
                raise ValueError(f"BYQ session already exists: {session_id}")
            session_root = self._session_root / session_id
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
            self._emit(record, "session.ready", "runtime-adapter", {"status": "ready"})
            with record.lock:
                record.status = "ready"
            return self.describe_session(record)
        except Exception:
            with self._lock:
                self._sessions.pop(session_id, None)
            harness.close()
            raise

    def submit_prompt(self, session_id: str, content: str) -> None:
        record = self._get(session_id)
        worker = threading.Thread(
            target=self._run_prompt,
            args=(record, content),
            name=f"byq-dsh-session-{session_id}",
            daemon=True,
        )
        worker.start()

    def _run_prompt(self, record: RuntimeSession, content: str) -> None:
        try:
            result = record.harness.start_session(record.session_id).run(
                content,
                on_notification=lambda notification: self._on_notification(record, notification),
            )
            with record.lock:
                cancelled = record.cancelled
                if not cancelled:
                    record.status = "idle"
            if cancelled:
                self._emit(record, "session.result.discarded", "runtime-adapter", {"reason": "cancelled"})
            else:
                self._emit(
                    record,
                    "session.result",
                    "runtime-adapter",
                    {"finish_reason": result.finish_reason},
                )
        except Exception as exc:
            with record.lock:
                cancelled = record.cancelled
                if not cancelled:
                    record.status = "failed"
            if not cancelled:
                self._emit(record, "session.failed", "runtime-adapter", {"error": type(exc).__name__})

    def cancel_session(self, session_id: str, mode: str) -> dict[str, Any]:
        if mode not in {"soft", "hard"}:
            raise ValueError("cancel mode must be soft or hard")
        record = self._get(session_id)
        with record.lock:
            record.cancelled = True
            record.status = "interrupted" if mode == "hard" else "cancelling"
        self._emit(
            record,
            "session.cancelled",
            "runtime-adapter",
            {"mode": mode, "persistence": "dsh-owned", "resume": "new-run-after-interrupted"},
        )
        if mode == "hard":
            record.harness.close()
        return self.describe_session(record)

    def subscribe(self, session_id: str) -> queue.Queue[WorkflowTraceEvent | None]:
        record = self._get(session_id)
        subscriber: queue.Queue[WorkflowTraceEvent | None] = queue.Queue()
        with record.lock:
            record.subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, session_id: str, subscriber: queue.Queue[WorkflowTraceEvent | None]) -> None:
        record = self._get(session_id)
        with record.lock:
            if subscriber in record.subscribers:
                record.subscribers.remove(subscriber)

    def describe_session(self, record: RuntimeSession) -> dict[str, Any]:
        with record.lock:
            return {
                "session_id": record.session_id,
                "trace_id": record.trace_id,
                "status": record.status,
                "process_ownership": "dedicated",
                "persistence": "dsh-owned",
            }

    def close(self) -> None:
        with self._lock:
            records = list(self._sessions.values())
            self._sessions.clear()
        for record in records:
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
        with record.lock:
            next_sequence = record.sequence + 1
        event = normalize_dsh_notification(
            notification,
            trace_id=record.trace_id,
            session_id=record.session_id,
            sequence=next_sequence,
        )
        if event is None:
            return
        with record.lock:
            record.sequence = next_sequence
        self._publish(record, event)

    def _emit(self, record: RuntimeSession, kind: str, source: str, payload: dict[str, Any]) -> None:
        with record.lock:
            record.sequence += 1
            event = make_workflow_trace_event(
                trace_id=record.trace_id,
                session_id=record.session_id,
                sequence=record.sequence,
                kind=kind,
                source=source,  # type: ignore[arg-type]
                payload=payload,
            )
        self._publish(record, event)

    @staticmethod
    def _publish(record: RuntimeSession, event: WorkflowTraceEvent) -> None:
        with record.lock:
            for subscriber in list(record.subscribers):
                subscriber.put(event)
