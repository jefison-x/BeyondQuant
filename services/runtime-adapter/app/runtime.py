from __future__ import annotations

import os
import queue
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import httpx
from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig, Notification

from .contracts import WorkflowTraceEvent, make_workflow_trace_event
from .identifiers import contained_session_path, validate_identifier
from .normalization import NormalizationState, normalize_dsh_notification


class SessionConflict(RuntimeError):
    """The requested lifecycle operation is invalid for the current state."""


class ModelCredentialUnavailable(RuntimeError):
    """A model-keyed Product turn was requested without its provider secret."""


_OPENCODE_PROVIDERS = frozenset({
    "opencode-go-responses",
    "opencode-go-chat",
    "opencode-go-messages",
    "opencode-zen-responses",
    "opencode-zen-chat",
    "opencode-zen-messages",
})


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
    owner_principal: str | None = None
    workspace_id: str | None = None
    model_resolution: dict[str, object] = field(default_factory=dict, repr=False)
    status: str = SessionStatus.STARTING
    active_run: ActiveRun | None = None
    interrupted_run_id: str | None = None
    sequence: int = 0
    normalization: NormalizationState = field(default_factory=NormalizationState)
    usage_message_ids: set[str] = field(default_factory=set)
    history: list[WorkflowTraceEvent] = field(default_factory=list)
    subscribers: list[queue.Queue[WorkflowTraceEvent | None]] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)


class RuntimeAdapter:
    """Own one official DSH SDK subprocess per active BYQ session.

    DSH 0.1.1-rc.1 has no prompt-cancel or per-session close. A dedicated
    process makes hard cancellation and failure isolation explicit: hard
    cancel closes the owned process, while soft cancel marks only the current
    run and resets to idle when that run settles.
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
        self._model_api_key = os.environ.get("DEEPSEEK_API_KEY")
        self._backend_url = os.environ.get("BYQ_BACKEND_URL", "http://backend:8000")
        self._resolver_token = os.environ.get("BYQ_CREDENTIAL_RESOLVER_TOKEN")
        self._usage_totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "reasoning_tokens": 0,
            "model_calls": 0,
        }

    @property
    def runtime_command(self) -> tuple[str, ...]:
        node = shutil.which("node") or "node"
        runtime = self._runtime_root / "node_modules/@deepseek-ai/dsh-sdk-jsonrpc-demo/lib/bin.js"
        return (node, str(runtime))

    def readiness(self) -> dict[str, Any]:
        return {
            "runtime_adapter": "ready",
            "sdk": "deepseek-harness-sdk==0.1.1rc1",
            "runtime_bin": "deepseek-harness-runtime-bin==0.1.1rc1",
            "explicit_runtime": self.runtime_command[1],
            "composition": str(self._composition),
            "composition_exists": self._composition.is_file(),
            "model_credentials": (
                "configured" if self._model_api_key
                else "resolver" if self._resolver_token
                else "missing"
            ),
            "model_provider": self._provider,
            "model": self._model,
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

    def operations_snapshot(self) -> dict[str, Any]:
        """Return process-local, normalized runtime accounting only."""

        with self._lock:
            records = list(self._sessions.values())
            usage = dict(self._usage_totals)
        status_counts = {status: 0 for status in self.readiness()["session_states"]}
        active_prompts = 0
        for record in records:
            with record.lock:
                status_counts[record.status] = status_counts.get(record.status, 0) + 1
                active_prompts += int(record.active_run is not None)
        return {
            "schema_version": "runtime-operations.v1",
            "runtime": {
                "status": "ready",
                "sdk": "deepseek-harness-sdk==0.1.1rc1",
                "runtime_bin": "deepseek-harness-runtime-bin==0.1.1rc1",
                "process_ownership": "one-per-active-session",
                "provider": self._provider,
                "model": self._model,
            },
            "sessions": {
                "active": len(records),
                "active_prompts": active_prompts,
                "status_counts": status_counts,
            },
            "usage": {
                **usage,
                "total_tokens": (
                    usage["input_tokens"]
                    + usage["output_tokens"]
                    + usage["cache_read_tokens"]
                    + usage["cache_write_tokens"]
                ),
                "scope": "adapter_process_lifetime",
                "source": "normalized_dsh_token_usage",
            },
            "raw_dsh_events": False,
        }

    def create_session(
        self, session_id: str, trace_id: str, owner_principal: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        validate_identifier(session_id, field="session_id")
        validate_identifier(trace_id, field="trace_id")
        session_root = contained_session_path(self._session_root, session_id)
        model_resolution = self._resolve_model(
            owner_principal=owner_principal,
            session_id=session_id,
            trace_id=trace_id,
        )

        with self._lock:
            if session_id in self._sessions:
                raise SessionConflict(f"BYQ session already exists: {session_id}")
            harness = self._build_harness(
                session_id,
                session_root,
                trace_id=trace_id,
                owner_principal=owner_principal,
                workspace_id=workspace_id,
                model_resolution=model_resolution,
            )
            record = RuntimeSession(
                session_id=session_id,
                trace_id=trace_id,
                harness=harness,
                owner_principal=owner_principal,
                workspace_id=workspace_id,
                model_resolution=model_resolution,
            )
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

    def submit_prompt(self, session_id: str, content: str, *, require_model_key: bool = False) -> str:
        record = self._get(session_id)
        if require_model_key and not record.model_resolution.get("api_key"):
            raise ModelCredentialUnavailable("the configured model provider has no credential")
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
                record.interrupted_run_id = run.run_id
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

    def resume_session(self, session_id: str) -> dict[str, Any]:
        record = self._get(session_id)
        with record.lock:
            if record.status != SessionStatus.INTERRUPTED or record.active_run is not None:
                raise SessionConflict(f"session {session_id} is not interrupted")
            resumed_from_run_id = record.interrupted_run_id
            record.status = SessionStatus.STARTING
            self._emit(
                record,
                "session.resuming",
                "runtime-adapter",
                {"resumed_from_run_id": resumed_from_run_id},
            )

        harness = self._build_harness(
            record.session_id,
            contained_session_path(self._session_root, record.session_id),
            trace_id=record.trace_id,
            owner_principal=record.owner_principal,
            workspace_id=record.workspace_id,
            model_resolution=record.model_resolution,
        )
        try:
            harness.start()
        except Exception:
            harness.close()
            with record.lock:
                record.status = SessionStatus.FAILED
                self._emit(record, "session.failed", "runtime-adapter", {"error": "resume-initialize"})
            raise

        with record.lock:
            record.harness = harness
            record.status = SessionStatus.READY
            self._emit(
                record,
                "session.resumed",
                "runtime-adapter",
                {"resumed_from_run_id": resumed_from_run_id},
            )
        return {**self.describe_session(record), "resumed_from_run_id": resumed_from_run_id}

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

    def subscribe(self, session_id: str, *, replay: bool = False) -> queue.Queue[WorkflowTraceEvent | None]:
        record = self._get(session_id)
        subscriber: queue.Queue[WorkflowTraceEvent | None] = queue.Queue()
        with record.lock:
            if record.status == SessionStatus.CLOSED:
                raise KeyError(f"closed BYQ session: {session_id}")
            record.subscribers.append(subscriber)
            if replay:
                for event in record.history:
                    subscriber.put(event)
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
                "owner_context": "configured" if record.owner_principal else "missing",
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

    def _build_harness(
        self,
        session_id: str,
        session_root: Path,
        *,
        trace_id: str,
        owner_principal: str | None,
        workspace_id: str | None,
        model_resolution: dict[str, object],
    ) -> DeepSeekHarness:
        environment = {
            "BYQ_MCP_URL": os.environ.get("BYQ_MCP_URL", "http://mcp:8300/mcp/v1"),
            "BYQ_MCP_TOKEN": os.environ.get("BYQ_MCP_TOKEN", ""),
            "BYQ_OWNER_PRINCIPAL": owner_principal or "",
            "BYQ_WORKSPACE_ID": workspace_id or "",
            # The authenticated user owns the session, while the Product DSH
            # service is the initiating actor. Keeping these identities
            # distinct preserves the human-review anti-self-approval rule.
            "BYQ_ACTOR_PRINCIPAL": f"byq-product-agent-{session_id}" if owner_principal else "",
            "BYQ_TRACE_ID": trace_id,
            "BYQ_SESSION_ID": session_id,
            # The adapter uses the durable session as the stable DSH
            # correlation when DSH does not expose a per-MCP-call header.
            "BYQ_DSH_RUN_ID": session_id,
        }
        # The provider credential enters only the adapter-owned SDK child
        # environment. It is never returned in readiness, lifecycle responses,
        # trace payloads, or exception details.
        model_api_key = model_resolution.get("api_key")
        if isinstance(model_api_key, str) and model_api_key:
            runtime_provider = str(model_resolution.get("provider") or self._provider)
            if runtime_provider == "deepseek-official":
                environment["DEEPSEEK_API_KEY"] = model_api_key
            elif runtime_provider in _OPENCODE_PROVIDERS:
                environment["OPENCODE_API_KEY"] = model_api_key
            else:
                raise ModelCredentialUnavailable("selected model provider is unavailable")
        config = DeepSeekHarnessConfig(
            provider=str(model_resolution.get("provider") or self._provider),
            model=str(model_resolution.get("model") or self._model),
            cordis=str(self._composition),
            session_root=str(session_root),
            launch_args_override=self.runtime_command,
            env=environment,
            request_timeout_seconds=15.0,
            shutdown_timeout_seconds=2.0,
        )
        return DeepSeekHarness(config=config)

    def _resolve_model(
        self,
        *,
        owner_principal: str | None,
        session_id: str,
        trace_id: str,
    ) -> dict[str, object]:
        fallback: dict[str, object] = {
            "source": "environment",
            "provider": self._provider,
            "model": self._model,
        }
        if self._model_api_key:
            fallback["api_key"] = self._model_api_key
        if not owner_principal or not self._resolver_token:
            return fallback
        try:
            response = httpx.post(
                f"{self._backend_url}/internal/credentials/model-resolution",
                headers={"x-byq-credential-resolver-token": self._resolver_token},
                json={
                    "owner_principal": owner_principal,
                    "agent_id": "byq-product",
                    "session_id": session_id,
                    "trace_id": trace_id,
                },
                timeout=3.0,
            )
            if response.status_code == 404:
                return fallback
            response.raise_for_status()
            body = response.json()
            resolution = body.get("resolution") if isinstance(body, dict) else None
            if not isinstance(resolution, dict):
                raise ModelCredentialUnavailable("credential resolver returned an invalid response")
            provider = resolution.get("provider")
            model = resolution.get("model")
            api_key = resolution.get("api_key")
            if not all(isinstance(value, str) and value for value in (provider, model, api_key)):
                raise ModelCredentialUnavailable("credential resolver returned an invalid response")
            return {
                "source": "user_binding",
                "provider": provider,
                "model": model,
                "api_key": api_key,
            }
        except ModelCredentialUnavailable:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            # A configured resolver is authoritative. Only an explicit 404
            # means no personal selection and permits bootstrap fallback.
            raise ModelCredentialUnavailable("selected model binding is unavailable") from exc

    def _on_notification(self, record: RuntimeSession, notification: Notification) -> None:
        with record.lock:
            if record.status in {SessionStatus.INTERRUPTED, SessionStatus.CLOSED}:
                return
            self._record_usage(record, notification)
            events = normalize_dsh_notification(
                notification,
                trace_id=record.trace_id,
                session_id=record.session_id,
                sequence=record.sequence + 1,
                state=record.normalization,
            )
            for event in events:
                self._publish(record, event)

    def _record_usage(self, record: RuntimeSession, notification: Notification) -> None:
        """Extract the documented TokenUsage shape without retaining DSH data."""

        if notification.method != "session.event" or not isinstance(notification.payload, dict):
            return
        if notification.payload.get("sessionId") != record.session_id:
            return
        raw_event = notification.payload.get("event")
        if not isinstance(raw_event, dict) or raw_event.get("type") != "assistant/message":
            return
        data = raw_event.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("message"), dict):
            return
        message_id = data["message"].get("id")
        usage = data.get("usage")
        if not isinstance(message_id, str) or not message_id or not isinstance(usage, dict):
            return
        if message_id in record.usage_message_ids:
            return
        mapping = {
            "inputTokens": "input_tokens",
            "outputTokens": "output_tokens",
            "cacheReadTokens": "cache_read_tokens",
            "cacheWriteTokens": "cache_write_tokens",
            "reasoningTokens": "reasoning_tokens",
        }
        normalized: dict[str, int] = {}
        for source, target in mapping.items():
            value = usage.get(source, 0)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_000_000_000:
                return
            normalized[target] = value
        record.usage_message_ids.add(message_id)
        with self._lock:
            for key, value in normalized.items():
                self._usage_totals[key] += value
            self._usage_totals["model_calls"] += 1

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
        record.history.append(ordered_event)
        for subscriber in list(record.subscribers):
            subscriber.put(ordered_event)
