from __future__ import annotations

import json
import hashlib
import os
import queue
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as distribution_version
from pathlib import Path
from typing import Any, ClassVar

import httpx
from packages.contracts.conversation_rehydration import (
    ConversationContextMessage,
    normalize_conversation_context,
    rehydrated_prompt,
)
from packages.contracts.conversation_recovery import normalize_recovery
from packages.contracts.agent_run_lifecycle import registration_fingerprint, lifecycle_receipt, project_lifecycle_event
from packages.contracts.domain_call_admission import request_evidence

from .contracts import WorkflowTraceEvent, make_workflow_trace_event
from .child_lease import ChildLease
from .normalization import close_public_activities
from .compat import RuntimeCompatibility, RuntimeObservation, compatibility_for_release
from .identifiers import contained_session_path, validate_identifier
from .lifecycle_journal import LifecycleJournal, JournalBusy
from .continuation_budget import persist_settlement, recovered_settlement, validate_reservation, create_guard_patch, read_guard
from .normalization import NormalizationState, normalize_runtime_observation


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
    started_at: float
    last_runtime_activity_at: float
    continuation_deadline: float | None = None
    soft_cancel_requested: bool = False
    hard_cancelled: bool = False
    active_subagent_calls: dict[str, float] = field(default_factory=dict)
    child_leases: dict[str, ChildLease] = field(default_factory=dict)
    finished_children: set[str] = field(default_factory=set)
    last_root_sequence: int = -1
    observed_registrations: set[str] = field(default_factory=set, repr=False)
    domain_calls: set[str] = field(default_factory=set, repr=False)
    domain_stop_code: str | None = field(default=None, repr=False)
    model_failure_code: str | None = None
    model_failure_retryable: bool = False
    domain_stop_dispatched: bool = field(default=False, repr=False)
    last_wait_notice_at: float = 0.0
    watchdog_stop: threading.Event = field(default_factory=threading.Event, repr=False)


@dataclass(slots=True)
class RuntimeSession:
    session_id: str
    trace_id: str
    harness: Any
    runtime_session_id: str
    runtime_generation: str = field(default="", repr=False)
    process_root_id: str = field(default="", repr=False)
    process_used: bool = field(default=False, repr=False)
    process_closed: bool = field(default=False, repr=False)
    continuation_budget: dict | None = field(default=None, repr=False)
    budget_journal: Path | None = field(default=None, repr=False)
    budget_run_id: str | None = field(default=None, repr=False)
    budget_receipts: dict[str, dict] = field(default_factory=dict, repr=False)
    owner_principal: str | None = None
    workspace_id: str | None = None
    model_resolution: dict[str, object] = field(default_factory=dict, repr=False)
    pending_conversation_context: list[ConversationContextMessage] = field(default_factory=list, repr=False)
    pending_conversation_recovery: dict | None = field(default=None, repr=False)
    status: str = SessionStatus.STARTING
    active_run: ActiveRun | None = None
    prompt_idempotency: dict[str, tuple[str, str]] = field(default_factory=dict, repr=False)
    terminal_receipts: dict[str, dict] = field(default_factory=dict, repr=False)
    pending_terminal_receipts: set[str] = field(default_factory=set, repr=False)
    process_closing: bool = field(default=False, repr=False)
    journal: Any = field(default=None, repr=False)
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

    def __init__(self, compatibility: RuntimeCompatibility | None = None) -> None:
        self._compatibility = compatibility or compatibility_for_release(
            os.environ.get("BYQ_DSH_COMPATIBILITY_RELEASE", "dsh-0.1.1rc1")
        )
        self._sessions: dict[str, RuntimeSession] = {}
        self._lock = threading.RLock()
        self._runtime_root = Path(os.environ.get("BYQ_DSH_RUNTIME_ROOT", "/opt/dsh-runtime"))
        self._composition = Path(
            os.environ.get(
                "BYQ_DSH_COMPOSITION",
                "/opt/byq/compositions/byq-product-sdk.cordis.yml",
            )
        )
        self._composition_identity = Path(
            os.environ.get(
                "BYQ_DSH_COMPOSITION_IDENTITY",
                "/opt/byq/compositions/byq-product-sdk.identity.json",
            )
        )
        self._release_identity = Path(
            os.environ.get(
                "BYQ_DSH_RELEASE_IDENTITY",
                "/opt/byq/releases/deployment.identity.json",
            )
        )
        ownership = os.environ.get("BYQ_DSH_PROCESS_OWNERSHIP", "session")
        if ownership not in {"session", "root-turn"}:
            raise ValueError("unsupported runtime process ownership")
        self._root_scoped = ownership == "root-turn"
        if self._root_scoped:
            identity = json.loads(self._composition_identity.read_text())
            composition = self._composition.read_text()
            if (not isinstance(identity, dict) or identity.get("root_identity_contract") != "byq-root-process.v1"
                    or identity.get("composition_hash") != "sha256:" + hashlib.sha256(composition.encode()).hexdigest()
                    or composition.count("X-BYQ-Root-Run-ID: !!js process.env.BYQ_ROOT_RUN_ID") != 1):
                raise ValueError("root-scoped runtime requires its independent verified configuration")
        self._session_root = Path(
            os.environ.get("DSH_SESSION_ROOT", "/var/lib/byq/dsh-sessions")
        ).expanduser().resolve()
        self._provider = os.environ.get("BYQ_DSH_PROVIDER", "deepseek-official")
        self._model = os.environ.get("BYQ_DSH_MODEL", "deepseek-v4-flash")
        self._model_api_key = os.environ.get("DEEPSEEK_API_KEY")
        self._backend_url = os.environ.get("BYQ_BACKEND_URL", "http://backend:8000")
        self._resolver_token = os.environ.get("BYQ_CREDENTIAL_RESOLVER_TOKEN")
        self._run_timeout_seconds = self._guard_seconds(
            "BYQ_DSH_RUN_TIMEOUT_SECONDS", default=900.0,
        )
        self._subagent_timeout_seconds = self._guard_seconds(
            "BYQ_DSH_SUBAGENT_TIMEOUT_SECONDS", default=180.0,
        )
        self._subagent_hard_cap_seconds = self._guard_seconds(
            "BYQ_DSH_SUBAGENT_HARD_CAP_SECONDS", default=600.0,
        )
        self._no_progress_timeout_seconds = self._guard_seconds(
            "BYQ_DSH_NO_PROGRESS_TIMEOUT_SECONDS", default=120.0,
        )
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
        return self._compatibility.runtime_command(self._runtime_root, node)

    def readiness(self) -> dict[str, Any]:
        composition_identity = self._safe_composition_identity()
        release_identity = self._safe_release_identity()
        adapter_status = (
            "ready" if release_identity["status"] == "matched"
            else "release-identity-mismatch"
        )
        return {
            "runtime_adapter": adapter_status,
            "sdk": f"deepseek-harness-sdk=={release_identity['installed_sdk']}",
            "runtime_bin": f"deepseek-harness-runtime-bin=={release_identity['installed_runtime_bin']}",
            "release_id": release_identity["release_id"],
            "release_identity": release_identity["status"],
            "explicit_runtime": self.runtime_command[-1],
            "composition": str(self._composition),
            "composition_exists": self._composition.is_file(),
            "plugin_profile": composition_identity["profile"],
            "composition_hash": composition_identity["composition_hash"],
            "enabled_plugin_ids": composition_identity["enabled_plugin_ids"],
            "model_credentials": (
                "configured" if self._model_api_key
                else "resolver" if self._resolver_token
                else "missing"
            ),
            "model_provider": self._provider,
            "model": self._model,
            "process_ownership": "one-per-root-turn" if self._root_scoped else "one-per-active-session",
            "run_guards": {
                "run_timeout_seconds": self._run_timeout_seconds,
                "subagent_timeout_seconds": self._subagent_timeout_seconds,
                "no_progress_timeout_seconds": self._no_progress_timeout_seconds,
            },
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
        composition_identity = self._safe_composition_identity()
        release_identity = self._safe_release_identity()
        return {
            "schema_version": "runtime-operations.v1",
            "runtime": {
                "status": (
                    "ready" if release_identity["status"] == "matched"
                    else "release-identity-mismatch"
                ),
                "sdk": f"deepseek-harness-sdk=={release_identity['installed_sdk']}",
                "runtime_bin": f"deepseek-harness-runtime-bin=={release_identity['installed_runtime_bin']}",
                "release_id": release_identity["release_id"],
                "release_identity": release_identity["status"],
                "process_ownership": "one-per-root-turn" if self._root_scoped else "one-per-active-session",
                "provider": self._provider,
                "model": self._model,
                "plugin_profile": composition_identity["profile"],
                "composition_hash": composition_identity["composition_hash"],
                "enabled_plugin_ids": composition_identity["enabled_plugin_ids"],
                "model_credentials": (
                    "configured" if self._model_api_key
                    else "resolver" if self._resolver_token
                    else "missing"
                ),
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

    def _safe_composition_identity(self) -> dict[str, Any]:
        """Load only the public, secret-free generated composition identity."""

        fallback = {"profile": "unknown", "composition_hash": "unavailable", "enabled_plugin_ids": []}
        try:
            value = json.loads(self._composition_identity.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return fallback
        if not isinstance(value, dict):
            return fallback
        profile = value.get("profile")
        digest = value.get("composition_hash")
        plugin_ids = value.get("enabled_plugin_ids")
        if not isinstance(profile, str) or not profile:
            return fallback
        if not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
            return fallback
        if not isinstance(plugin_ids, list) or not all(
            isinstance(item, str) and re.fullmatch(r"[a-z0-9-]+", item) is not None
            for item in plugin_ids
        ):
            return fallback
        return {"profile": profile, "composition_hash": digest, "enabled_plugin_ids": plugin_ids}

    def _safe_release_identity(self) -> dict[str, str]:
        """Match deployment-controlled identity to installed distribution metadata."""

        try:
            installed_sdk = distribution_version("deepseek-harness-sdk")
            installed_runtime = distribution_version("deepseek-harness-runtime-bin")
        except PackageNotFoundError:
            installed_sdk = installed_runtime = "unknown"
        fallback = {
            "release_id": "unknown",
            "installed_sdk": installed_sdk,
            "installed_runtime_bin": installed_runtime,
            "status": "unavailable",
        }
        try:
            value = json.loads(self._release_identity.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return fallback
        if not isinstance(value, dict) or value.get("schema_version") != "dsh-deployment-identity.v1":
            return fallback
        release_id = value.get("default_release")
        expected = value.get("python")
        if not isinstance(release_id, str) or re.fullmatch(r"dsh-\d+\.\d+\.\d+rc\d+", release_id) is None:
            return fallback
        if not isinstance(expected, dict):
            return fallback
        matches = expected.get("sdk") == installed_sdk and expected.get("runtime_bin") == installed_runtime
        return {
            **fallback,
            "release_id": release_id,
            "status": "matched" if matches else "mismatch",
        }

    def create_session(
        self, session_id: str, trace_id: str, owner_principal: str | None = None,
        workspace_id: str | None = None, initial_sequence: int = 0,
        conversation_context: object = None,
        conversation_recovery: object = None,
    ) -> dict[str, Any]:
        validate_identifier(session_id, field="session_id")
        validate_identifier(trace_id, field="trace_id")
        if isinstance(initial_sequence, bool) or not isinstance(initial_sequence, int) or initial_sequence < 0:
            raise ValueError("initial_sequence must be a non-negative integer")
        context = normalize_conversation_context([] if conversation_context is None else conversation_context)
        recovery = normalize_recovery(conversation_recovery, session_id, trace_id)
        # The official rc.1 JSON-RPC carrier creates sessions but exposes no
        # persisted-session resume operation. Never recreate a released DSH
        # session over its append-only identity; use a fresh private generation
        # while keeping the stable BYQ session and trace identities public.
        runtime_session_id = session_id if initial_sequence == 0 else f"resume-{uuid.uuid4().hex}"
        session_root = contained_session_path(self._session_root, runtime_session_id)
        model_resolution = self._resolve_model(
            owner_principal=owner_principal,
            session_id=session_id,
            trace_id=trace_id,
        )

        with self._lock:
            if session_id in self._sessions:
                raise SessionConflict(f"BYQ session already exists: {session_id}")
            journal = None
            if workspace_id:
                try:
                    journal = LifecycleJournal.claim(self._session_root / "byq-lifecycle-evidence",
                        {"session_id": session_id, "trace_id": trace_id, "owner": owner_principal,
                         "workspace_id": workspace_id}, create=True)
                except JournalBusy as exc:
                    raise SessionConflict("runtime evidence is owned by another executor") from exc
                initial_sequence = max(initial_sequence, journal.state["sequence"])
                if journal.state["sequence"]:
                    runtime_session_id = f"resume-{uuid.uuid4().hex}"
                    session_root = contained_session_path(self._session_root, runtime_session_id)
            runtime_generation = f"generation-{uuid.uuid4().hex}"
            process_root_id = uuid.uuid4().hex if self._root_scoped else ""
            try:
                harness = self._build_harness(
                    session_id, session_root, trace_id=trace_id, owner_principal=owner_principal,
                    workspace_id=workspace_id, model_resolution=model_resolution,
                    runtime_generation=runtime_generation, root_run_id=process_root_id)
            except BaseException:
                if journal:
                    journal.close()
                raise
            record = RuntimeSession(
                session_id=session_id,
                trace_id=trace_id,
                harness=harness,
                runtime_session_id=runtime_session_id,
                runtime_generation=runtime_generation,
                process_root_id=process_root_id,
                owner_principal=owner_principal,
                workspace_id=workspace_id,
                model_resolution=model_resolution,
                pending_conversation_context=context,
                pending_conversation_recovery=recovery,
                sequence=initial_sequence,
                journal=journal,
                history=[] if journal is None else list(journal.state["events"]),
            )
            for event in record.history:
                terminal = project_lifecycle_event(event, session_id, trace_id)
                if terminal and terminal["outcome"] != "active":
                    record.terminal_receipts.setdefault(terminal["root_run_id"], lifecycle_receipt(terminal))
                    if journal and terminal["root_run_id"] not in journal.state["terminal_acks"]:
                        record.pending_terminal_receipts.add(terminal["root_run_id"])
            self._sessions[session_id] = record

        try:
            self._compatibility.start(harness)
            with record.lock:
                if record.status != SessionStatus.STARTING:
                    raise SessionConflict("session closed during initialization")
                record.status = SessionStatus.READY
                self._emit(record, "session.ready", "runtime-adapter", {"status": "ready"})
            return self.describe_session(record)
        except Exception:
            with self._lock:
                if self._sessions.get(session_id) is record:
                    del self._sessions[session_id]
            try:
                self._compatibility.close(harness)
            finally:
                if journal:
                    journal.close()
            raise

    def submit_prompt(
        self, session_id: str, content: str, *, require_model_key: bool = False,
        idempotency_key: str | None = None,
        conversation_context: object = None,
        conversation_recovery: object = None,
        continuation_budget: object = None,
    ) -> str:
        record = self._get(session_id)
        with record.lock:
            identity_content = content if continuation_budget is None else json.dumps(
                {'content': content, 'reservation': continuation_budget}, sort_keys=True, separators=(',', ':'))
            if idempotency_key is not None:
                if not 8 <= len(idempotency_key) <= 128:
                    raise ValueError("prompt idempotency key has invalid length")
                if record.journal is not None:
                    try:
                        durable = record.journal.receipt(idempotency_key, hashlib.sha256(identity_content.encode()).hexdigest())
                    except ValueError as exc:
                        raise SessionConflict("prompt receipt identity conflicts") from exc
                    if durable["state"] == "accepted":
                        return durable["run_id"]
                existing = record.prompt_idempotency.get(idempotency_key)
                if existing is not None:
                    existing_content, existing_run_id = existing
                    if existing_content != identity_content:
                        raise SessionConflict("prompt idempotency key was reused with different content")
                    return existing_run_id
            # An accepted original receipt remains authoritative even if model
            # credentials are subsequently absent. Reject only a new admission.
            if require_model_key and not record.model_resolution.get("api_key"):
                raise ModelCredentialUnavailable("the configured model provider has no credential")
            if record.workspace_id and record.pending_terminal_receipts:
                raise SessionConflict("previous turn domain cleanup is not yet acknowledged")
            budget = None
            if continuation_budget is not None:
                if not self.continuation_qualified(record):
                    raise ValueError('continuation executor is not enabled')
                budget = validate_reservation(continuation_budget,
                    owner=record.owner_principal, workspace=record.workspace_id)
                if idempotency_key != budget['reservation_id']:
                    raise ValueError('continuation requires its original reservation key')
                if (record.model_resolution.get('provider', self._provider), record.model_resolution.get('model', self._model)) != (
                        'deepseek-official', 'deepseek-v4-flash'):
                    raise ValueError('selected continuation model is unqualified')
            if record.status not in SessionStatus.PROMPTABLE or record.active_run is not None:
                raise SessionConflict(
                    f"session {session_id} cannot accept a prompt in state {record.status}"
                )
            # A Gateway-owned projection can refresh a new root without a
            # separate resume race. Omission retains the prepared create/resume
            # context; an explicit empty list intentionally clears it.
            context = record.pending_conversation_context
            recovery = record.pending_conversation_recovery
            if conversation_context is not None:
                context = normalize_conversation_context(conversation_context)
                recovery = normalize_recovery(conversation_recovery, record.session_id, record.trace_id)
            elif conversation_recovery is not None:
                raise ValueError("conversation recovery requires an explicit context projection")
            effective_content = rehydrated_prompt(context, content, recovery)
            if budget is not None and not record.process_used:
                self._compatibility.close(record.harness)
                record.process_closed = True
            if self._root_scoped and (record.process_used or budget is not None):
                if record.workspace_id and conversation_context is None:
                    raise SessionConflict("new root requires a fresh public conversation projection")
                if record.process_closing or not record.process_closed:
                    raise SessionConflict("previous runtime process cleanup is not complete")
                if record.continuation_budget is not None:
                    old_id = record.continuation_budget['reservation_id']
                    record.budget_receipts[old_id] = self._budget_receipt(record)
                    while len(record.budget_receipts) > 64:
                        del record.budget_receipts[next(iter(record.budget_receipts))]
                private_session = f"root-{uuid.uuid4().hex}"
                generation = f"generation-{uuid.uuid4().hex}"
                root_id = uuid.uuid4().hex
                harness = self._build_harness(record.session_id,
                    contained_session_path(self._session_root, private_session),
                    trace_id=record.trace_id, owner_principal=record.owner_principal,
                    workspace_id=record.workspace_id, model_resolution=record.model_resolution,
                    runtime_generation=generation, root_run_id=root_id, continuation_budget=budget)
                record.harness = harness
                record.runtime_session_id = private_session
                record.runtime_generation = generation
                record.process_root_id = root_id
                record.process_closed = False
                record.normalization = NormalizationState()
                record.usage_message_ids.clear()
                record.continuation_budget = budget
                record.budget_journal = contained_session_path(self._session_root, private_session) / 'continuation-budget.jsonl' if budget else None
                record.budget_run_id = root_id if budget else None
            now = time.monotonic()
            run = ActiveRun(run_id=record.process_root_id if self._root_scoped else uuid.uuid4().hex,
                            started_at=now, last_runtime_activity_at=now)
            if budget:
                run.continuation_deadline = now + max(0, (datetime.fromisoformat(budget['expires_at']) - datetime.now(timezone.utc)).total_seconds())
            record.process_used = True
            record.pending_conversation_context = []
            record.pending_conversation_recovery = None
            record.active_run = run
            record.status = SessionStatus.RUNNING
            if idempotency_key is not None:
                record.prompt_idempotency[idempotency_key] = (identity_content, run.run_id)
            try:
                self._emit(record, "session.started", "runtime-adapter", {"run_id": run.run_id})
            except BaseException:
                record.active_run = None
                record.status = SessionStatus.FAILED
                if idempotency_key:
                    record.prompt_idempotency.pop(idempotency_key, None)
                raise

            # Capture the execution owner while admission is still locked.
            # A worker may be scheduled only after cancellation and resume.
            prompt_harness = record.harness
            prompt_runtime_session_id = record.runtime_session_id
        worker = threading.Thread(
            target=self._run_prompt,
            args=(record, run, effective_content, prompt_harness, prompt_runtime_session_id),
            name=f"byq-dsh-session-{session_id}",
            daemon=True,
        )
        try:
            worker.start()
        except Exception:
            with record.lock:
                if record.active_run is run:
                    record.active_run = None
                    if idempotency_key is not None:
                        record.prompt_idempotency.pop(idempotency_key, None)
                    record.status = SessionStatus.FAILED
                    self._emit(record, "session.failed", "runtime-adapter", {"error": "thread-start", "run_id": run.run_id})
            raise
        watchdog = threading.Thread(
            target=self._watch_run,
            args=(record, run),
            name=f"byq-dsh-watchdog-{session_id}",
            daemon=True,
        )
        watchdog.start()
        return run.run_id

    def reconcile_prompt(self, session_id: str, idempotency_key: str, content_sha256: str) -> dict[str, object]:
        try:
            record = self._get(session_id)
        except KeyError:
            validate_identifier(session_id, field="session_id")
            try:
                state = LifecycleJournal.read(self._session_root / "byq-lifecycle-evidence" / f"{session_id}.json")
            except FileNotFoundError:
                return {"schema_version": "prompt-receipt.v1", "state": "outcome_unknown"}
            if state["context"]["session_id"] != session_id:
                raise SessionConflict("durable prompt session identity conflicts")
            try:
                return LifecycleJournal.lookup(state, idempotency_key, content_sha256)
            except ValueError as exc:
                raise SessionConflict("prompt receipt identity conflicts") from exc
        with record.lock:
            if record.journal:
                try:
                    return record.journal.receipt(idempotency_key, content_sha256)
                except ValueError as exc:
                    raise SessionConflict("prompt receipt identity conflicts") from exc
            existing = record.prompt_idempotency.get(idempotency_key)
            if existing is None:
                return {"schema_version": "prompt-receipt.v1", "state": "outcome_unknown"}
            content, run_id = existing
            if hashlib.sha256(content.encode("utf-8")).hexdigest() != content_sha256:
                raise SessionConflict("prompt receipt identity conflicts with original content")
            return {"schema_version": "prompt-receipt.v1", "state": "accepted", "run_id": run_id}

    def _run_prompt(
        self, record: RuntimeSession, run: ActiveRun, content: str,
        harness: Any, runtime_session_id: str,
    ) -> None:
        try:
            with record.lock:
                if record.active_run is not run or record.harness is not harness:
                    return
                # The official start_session may start a closed process. Fence
                # that operation with cancellation; Session.run only sends to
                # the existing transport and cannot restart it after close.
                prepared = self._compatibility.prepare_prompt(harness, runtime_session_id)
                if record.continuation_budget is not None:
                    # Startup must demonstrate the guard registered before
                    # any model prompt is sent; a failed plugin cannot silently
                    # fall back to an unguarded runtime.
                    read_guard(record.budget_journal, record.continuation_budget)
            try:
                finish_reason = self._compatibility.run_prepared_prompt(
                    prepared, content,
                    lambda notification: self._on_notification(record, notification,
                        source_run=run, source_runtime_session_id=runtime_session_id),
                )
            finally:
                if self._root_scoped:
                    with record.lock:
                        if record.harness is harness and not record.process_closing and not record.process_closed:
                            record.process_closing = True
                            self._compatibility.close(harness)
                            record.process_closed = True
                            record.process_closing = False
        except Exception as exc:
            with record.lock:
                if record.active_run is not run:
                    return
                if self._root_scoped and not record.process_closed and not record.process_closing:
                    record.process_closing = True
                    try:
                        self._compatibility.close(harness)
                    except Exception:
                        # Keep admission fenced when process cleanup itself is
                        # unconfirmed. Never replace that process speculatively.
                        pass
                    else:
                        record.process_closed = True
                        record.process_closing = False
                record.active_run = None
                run.watchdog_stop.set()
                if run.hard_cancelled or record.status in {SessionStatus.INTERRUPTED, SessionStatus.CLOSED}:
                    return
                if run.soft_cancel_requested:
                    record.status = SessionStatus.IDLE
                    self._emit(record, "session.result.discarded", "runtime-adapter", {"reason": "soft-cancelled", "run_id": run.run_id})
                    return
                record.status = SessionStatus.FAILED
                self._emit(record, "session.failed", "runtime-adapter", {"error": type(exc).__name__, "run_id": run.run_id})
            return

        with record.lock:
            if record.active_run is not run:
                return
            record.active_run = None
            run.watchdog_stop.set()
            if run.hard_cancelled or record.status in {SessionStatus.INTERRUPTED, SessionStatus.CLOSED}:
                return
            if run.soft_cancel_requested:
                record.status = SessionStatus.IDLE
                self._emit(record, "session.result.discarded", "runtime-adapter", {"reason": "soft-cancelled", "run_id": run.run_id})
                return
            # A returned SDK call is not necessarily a completed model run.
            # Token exhaustion, cancellation and unknown reasons must not
            # resolve the user's unanswered request as a successful result.
            budget_blocked = False
            if record.continuation_budget:
                try:
                    budget_blocked = bool(read_guard(record.budget_journal, record.continuation_budget,
                        terminal=True)['blocked_reason'])
                except (OSError, ValueError, TypeError, KeyError):
                    budget_blocked = True
                if budget_blocked:
                    run.model_failure_code = 'model-run-failed'
                    run.model_failure_retryable = False
            if finish_reason != "completed" or run.domain_stop_code or budget_blocked:
                record.status = SessionStatus.FAILED
                self._emit(
                    record,
                    "session.failed",
                    "runtime-adapter",
                    {"code": run.domain_stop_code or run.model_failure_code or "model-run-failed",
                     "retryable": False if run.domain_stop_code else (
                         run.model_failure_retryable if run.model_failure_code else True), "run_id": run.run_id},
                )
            else:
                record.status = SessionStatus.IDLE
                self._emit(
                    record,
                    "session.result",
                    "runtime-adapter",
                    {"finish_reason": finish_reason, "run_id": run.run_id},
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
                run.watchdog_stop.set()
                record.interrupted_run_id = run.run_id
                record.status = SessionStatus.INTERRUPTED
                # The owned process is closed synchronously below. Detach the
                # run now so no post-close result can be accepted or emitted.
                record.active_run = None
                record.process_closing = True
                cancelled_harness = record.harness
            self._emit(
                record,
                "session.cancelled",
                "runtime-adapter",
                {"mode": mode, "persistence": "dsh-owned", "resume": "new-run-after-interrupted", "run_id": run.run_id},
            )
        if mode == "hard":
            self._compatibility.close(cancelled_harness)
            with record.lock:
                record.process_closing = False
                record.process_closed = True
        return self.describe_session(record)

    def recover_evidence(self, context: dict, after_sequence: int = 0) -> dict:
        """Replays BYQ evidence only. Never constructs a harness or runs a model."""
        LifecycleJournal._context(context)
        if type(after_sequence) is not int or after_sequence < 0:
            raise ValueError("invalid recovery cursor")
        with self._lock:
            if context["session_id"] in self._sessions:
                record = self._sessions[context["session_id"]]
                if (record.trace_id, record.owner_principal, record.workspace_id) != (
                        context["trace_id"], context["owner"], context["workspace_id"]):
                    raise ValueError("recovery identity mismatch")
                return {"state": "owned", "events": [], "more": False}
            try:
                journal = LifecycleJournal.claim(self._session_root / "byq-lifecycle-evidence", context)
            except JournalBusy:
                return {"state": "owned", "events": [], "more": False}
            except FileNotFoundError:
                return {"state": "unknown", "events": [], "more": False}
            try:
                events = [e for e in journal.state["events"] if e["sequence"] > after_sequence]
                return {"state": "recovered", "events": events[:256], "more": len(events) > 256}
            finally:
                journal.close()

    def domain_call_evidence(self, context: dict, after_sequence: int = 0) -> dict:
        """Private bounded control evidence, never a public trace/replay source."""
        LifecycleJournal._context(context)
        if type(after_sequence) is not int or not 0 <= after_sequence < 2**63:
            raise ValueError("invalid private evidence cursor")

        def page(state):
            if state["context"] != context:
                raise ValueError("private evidence context mismatch")
            rows = state["calls"][after_sequence:after_sequence + 256]
            return {"schema_version": "domain-call-page.v1", "events": [dict(row) for row in rows],
                    "more": len(state["calls"]) > after_sequence + len(rows), "idle": state["open_root"] is None}

        try:
            record = self._get(context["session_id"])
        except KeyError:
            journal = LifecycleJournal.claim(self._session_root / "byq-lifecycle-evidence", context)
            try:
                return page(journal.state)
            finally:
                journal.close()
        with record.lock:
            if record.journal is None:
                raise ValueError("private evidence requires durable owned context")
            return page(record.journal.state)

    def acknowledge_terminal(self, session_id: str, receipt: object) -> dict:
        """Private Gateway acknowledgement of an exact Backend terminal receipt.

        This opens no domain capability: it permits the next root only after
        the previous BYQ root has been durably closed, including across restart.
        """
        try:
            record = self._get(session_id)
        except KeyError:
            validate_identifier(session_id, field="session_id")
            root_path = self._session_root / "byq-lifecycle-evidence"
            try:
                state = LifecycleJournal.read(root_path / f"{session_id}.json")
            except FileNotFoundError as exc:
                raise KeyError(f"no durable terminal evidence for {session_id}") from exc
            if state["context"]["session_id"] != session_id:
                raise SessionConflict("terminal evidence session identity conflicts")
            try:
                journal = LifecycleJournal.claim(root_path, state["context"])
            except JournalBusy as exc:
                raise SessionConflict("terminal evidence is still owned by another executor") from exc
            try:
                journal.acknowledge_terminal(receipt)
            except ValueError as exc:
                raise SessionConflict("terminal receipt does not match durable evidence") from exc
            finally:
                journal.close()
            return {"receipt": dict(receipt)}
        with record.lock:
            root = receipt.get("root_run_id") if isinstance(receipt, dict) else None
            if (not isinstance(root, str) or type(receipt.get("sequence")) is not int
                    or record.terminal_receipts.get(root) != receipt):
                raise SessionConflict("terminal receipt does not match this runtime turn")
            if record.journal is not None:
                record.journal.acknowledge_terminal(receipt)
            record.pending_terminal_receipts.discard(root)
            return {"receipt": dict(receipt)}

    def resume_session(
        self, session_id: str, *, conversation_context: object = None,
        conversation_recovery: object = None,
    ) -> dict[str, Any]:
        record = self._get(session_id)
        context = normalize_conversation_context([] if conversation_context is None else conversation_context)
        recovery = normalize_recovery(conversation_recovery, record.session_id, record.trace_id)
        with record.lock:
            if record.process_closing:
                raise SessionConflict("previous runtime process cleanup is not complete")
            if record.status == SessionStatus.READY and record.active_run is None:
                record.pending_conversation_context = context
                record.pending_conversation_recovery = recovery
                return {**self.describe_session(record), "resumed_from_run_id": None}
            if record.status not in {SessionStatus.INTERRUPTED, SessionStatus.FAILED} or record.active_run is not None:
                raise SessionConflict(f"session {session_id} cannot be resumed")
            previous_status = record.status
            resumed_from_run_id = record.interrupted_run_id
            previous_harness = record.harness
            # The public BYQ identifier may already use the full 64-character
            # contract allowance, so the private generation ID must not append
            # to it. The stable public identity remains on RuntimeSession.
            runtime_session_id = f"resume-{uuid.uuid4().hex}"
            record.status = SessionStatus.STARTING
            self._emit(
                record,
                "session.resuming",
                "runtime-adapter",
                {"resumed_from_run_id": resumed_from_run_id},
            )

        runtime_generation = f"generation-{uuid.uuid4().hex}"
        process_root_id = uuid.uuid4().hex if self._root_scoped else ""
        harness = None
        try:
            if previous_status == SessionStatus.FAILED:
                self._compatibility.close(previous_harness)
            harness = self._build_harness(
                record.session_id,
                contained_session_path(self._session_root, runtime_session_id),
                trace_id=record.trace_id,
                owner_principal=record.owner_principal,
                workspace_id=record.workspace_id,
                model_resolution=record.model_resolution,
                runtime_generation=runtime_generation,
                root_run_id=process_root_id,
            )
            self._compatibility.start(harness)
        except Exception:
            try:
                if harness is not None:
                    self._compatibility.close(harness)
            finally:
                with record.lock:
                    if record.status == SessionStatus.STARTING:
                        record.status = SessionStatus.FAILED
                        self._emit(record, "session.failed", "runtime-adapter", {"error": "resume-initialize"})
            raise

        with record.lock:
            if record.status != SessionStatus.STARTING:
                self._compatibility.close(harness)
                raise SessionConflict("session closed during resume initialization")
            record.harness = harness
            record.runtime_session_id = runtime_session_id
            record.runtime_generation = runtime_generation
            record.process_root_id = process_root_id
            record.process_used = False
            record.process_closed = False
            # ADR-0067: closing a process is not evidence that its domain
            # operations were settled. Only the exact Backend terminal receipt
            # may release the previous root's admission barrier.
            record.pending_conversation_context = context
            record.pending_conversation_recovery = recovery
            record.normalization = NormalizationState()
            record.interrupted_run_id = None
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
            # Creation/resumption publishes the record before SDK initialize
            # completes outside this lock. Releasing it in that interval would
            # detach the process that the initializer is still acquiring.
            if record.status == SessionStatus.STARTING:
                raise SessionConflict(f"session {session_id} is still initializing")
            if record.process_closing or record.active_run is not None or record.status in SessionStatus.ACTIVE_PROMPT:
                raise SessionConflict(f"session {session_id} has an active prompt")
            if record.continuation_budget:
                self._budget_receipt(record)
            record.status = SessionStatus.CLOSED
        try:
            with record.lock:
                self._emit(record, "session.closed", "runtime-adapter", {"reason": "released"})
        finally:
            try:
                self._compatibility.close(record.harness)
            finally:
                if record.journal:
                    record.journal.close()
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
        failure = None
        for record in records:
            try:
                with record.lock:
                    closing_run = record.active_run
                    if record.active_run is not None:
                        record.active_run.watchdog_stop.set()
                    record.active_run = None
                    record.status = SessionStatus.CLOSED
                    self._emit(record, "session.closed", "runtime-adapter", {
                        "reason": "adapter-shutdown", **({"run_id": closing_run.run_id} if closing_run is not None else {}),
                    })
            except Exception as exc:
                failure = exc
            finally:
                try:
                    self._compatibility.close(record.harness)
                except Exception as exc:
                    failure = exc
                finally:
                    if record.journal:
                        record.journal.close()
                    with record.lock:
                        for subscriber in record.subscribers:
                            subscriber.put(None)
        if failure is not None:
            raise failure

    def _get(self, session_id: str) -> RuntimeSession:
        with self._lock:
            record = self._sessions.get(session_id)
        if record is None:
            raise KeyError(f"unknown BYQ session: {session_id}")
        return record

    def continuation_qualified(self, record: RuntimeSession) -> bool:
        try:
            exact = (distribution_version('deepseek-harness-sdk') == '0.1.2rc1'
                and distribution_version('deepseek-harness-runtime-bin') == '0.1.2rc1')
        except PackageNotFoundError:
            exact = False
        return (os.environ.get('BYQ_F6_EXECUTOR_ENABLED') == '1' and self._root_scoped
            and self._compatibility.family == 'dsh-0.1.2' and exact
            and (record.model_resolution.get('provider', self._provider), record.model_resolution.get('model', self._model))
                == ('deepseek-official', 'deepseek-v4-flash'))

    def _budget_receipt(self, record: RuntimeSession) -> dict:
        reservation = record.continuation_budget
        unknown = {'reservation_id': reservation['reservation_id'], 'status': 'outcome_unknown'}
        if record.active_run is not None or not record.process_closed or record.process_closing:
            return unknown
        try:
            receipt = read_guard(record.budget_journal, reservation, terminal=True)
            completed = any(event['kind'] == 'session.result'
                and event['payload'].get('run_id') == record.budget_run_id for event in record.history)
            receipt = {**receipt, 'run_id': record.budget_run_id,
                'outcome': 'completed' if completed else 'needs_attention'}
            if record.journal:
                persist_settlement(self._session_root, record.journal.state['context'], receipt)
            return receipt
        except (OSError, ValueError, TypeError, KeyError):
            return unknown

    def continuation_receipt(self, session_id: str, reservation_id: str) -> dict:
        validate_identifier(session_id, field='session_id')
        def recover():
            try:
                state = LifecycleJournal.read(self._session_root / 'byq-lifecycle-evidence' / f'{session_id}.json')
                return recovered_settlement(self._session_root, session_id, reservation_id, state)
            except (OSError, ValueError, TypeError, KeyError):
                return {'reservation_id': reservation_id, 'status': 'outcome_unknown'}
        try:
            record = self._get(session_id)
        except KeyError:
            return recover()
        with record.lock:
            if record.continuation_budget and record.continuation_budget['reservation_id'] == reservation_id:
                return self._budget_receipt(record)
            return record.budget_receipts.get(reservation_id) or recover()

    def _build_harness(
        self,
        session_id: str,
        session_root: Path,
        *,
        trace_id: str,
        owner_principal: str | None,
        workspace_id: str | None,
        model_resolution: dict[str, object],
        runtime_generation: str,
        root_run_id: str = "",
        continuation_budget: dict | None = None,
    ) -> Any:
        if self._root_scoped and re.fullmatch(r"[0-9a-f]{32}", root_run_id) is None:
            raise ValueError("root-scoped process requires a reserved root identity")
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
            # Stable across root process changes; no owner or public ID is
            # exposed in the explicitly authorized provider routing header.
            "BYQ_PROVIDER_SESSION_ID": str(uuid.uuid5(uuid.NAMESPACE_URL,
                "beyondquant:provider-session:" + session_id)),
            # Official MCP headers are process-scoped, not root-turn-scoped.
            # Give each owned process a BYQ identity so resumed generations
            # cannot authorize against an earlier process's AgentRun. This is
            # deliberately distinct from both the public session and DSH ID.
            "BYQ_DSH_RUN_ID": runtime_generation,
            "BYQ_ROOT_RUN_ID": root_run_id,
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
        composition = self._composition
        if continuation_budget is not None:
            composition, _ = create_guard_patch(composition, session_root, continuation_budget)
            environment['DEEPSEEK_BASE_URL'] = 'https://api.deepseek.com'
        return self._compatibility.build_harness(
            provider=str(model_resolution.get("provider") or self._provider),
            model=str(model_resolution.get("model") or self._model),
            composition=composition,
            session_root=session_root,
            runtime_command=self.runtime_command,
            environment=environment,
        )

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

    def _on_notification(
        self,
        record: RuntimeSession,
        notification: object,
        *,
        source_run: ActiveRun | None = None,
        source_runtime_session_id: str | None = None,
    ) -> None:
        with record.lock:
            if source_runtime_session_id is not None and source_runtime_session_id != record.runtime_session_id:
                return
            if source_run is not None and source_run is not record.active_run:
                return
        observation = self._compatibility.observe(
            notification,
            root_session_id=record.runtime_session_id,
        )
        with record.lock:
            if source_runtime_session_id is not None and source_runtime_session_id != record.runtime_session_id:
                return
            if source_run is not None and source_run is not record.active_run:
                return
            if record.status in {
                SessionStatus.INTERRUPTED, SessionStatus.FAILED, SessionStatus.CLOSED,
            }:
                return
            run = record.active_run
            runtime_activity = False
            if run is not None:
                if observation.root_session and observation.kind == "turn.end" and observation.failure_code:
                    run.model_failure_code = observation.failure_code
                    run.model_failure_retryable = observation.failure_retryable
                runtime_activity = self._observe_run_observation(
                    record, run, observation,
                )
                if self._root_scoped and source_run is run and runtime_activity:
                    if observation.kind == "tool.call" and observation.tool_name in {
                            "mcp__byq__byq_strategy_validate", "mcp__byq__byq_ml_strategy_create"}:
                        if (len(run.domain_calls) >= 1024
                                or record.journal is not None and len(record.journal.state["calls"]) >= 1024):
                            run.domain_stop_code = "domain-call-retention-bound"
                        else:
                            run.domain_calls.add(observation.call_id)
                        try:
                            request_evidence(observation.tool_name.removeprefix("mcp__byq__"),
                                observation.domain_arguments, trace_id=record.trace_id)
                        except ValueError:
                            run.domain_stop_code = "domain-call-reference-unproven"
                    for result in observation.tool_results:
                        if result.call_id in run.domain_calls and result.failed and self._domain_stop_result(result.result):
                            run.domain_stop_code = "domain-correction-stopped"
                    if run.domain_stop_code and not run.domain_stop_dispatched and not run.watchdog_stop.is_set():
                        run.domain_stop_dispatched = True
                        # Use the existing owned-process guard/official close,
                        # outside the SDK notification reader to avoid deadlock.
                        threading.Thread(target=self._enforce_run_guards,
                            args=(record, run), kwargs={"now": time.monotonic()}, daemon=True,
                            name="byq-domain-stop").start()
                if (self._root_scoped and source_run is run and runtime_activity and not run.domain_stop_code
                        and observation.domain_arguments is not None and observation.event_sequence is not None
                        and record.journal is not None and record.process_root_id == run.run_id):
                    try:
                        evidence = request_evidence(observation.tool_name.removeprefix("mcp__byq__"),
                            observation.domain_arguments, trace_id=record.trace_id)
                    except ValueError:
                        evidence = None
                    if evidence is not None:
                        record.journal.observe_call({"schema_version": "domain-call-observed.v1",
                            "sequence": len(record.journal.state["calls"]) + 1,
                            "root_run_id": run.run_id, "generation": record.runtime_generation,
                            "call_id": observation.call_id, **evidence})
                if (runtime_activity and observation.registration_key and record.owner_principal
                        and record.workspace_id and record.runtime_generation):
                    fingerprint = registration_fingerprint(
                        record.owner_principal, record.workspace_id, f"byq-product-agent-{record.session_id}",
                        record.trace_id, record.session_id, record.runtime_generation, observation.registration_key,
                    )
                    if fingerprint not in run.observed_registrations and len(run.observed_registrations) < 128:
                        run.observed_registrations.add(fingerprint)
                        self._emit(record, "agent.run.registration", "runtime-adapter", {
                            "schema_version": "agent-run-registration-observed.v1",
                            "run_id": run.run_id, "registration_fingerprint": fingerprint,
                        })
            self._record_usage(record, observation)
            events = normalize_runtime_observation(
                observation,
                trace_id=record.trace_id,
                session_id=record.session_id,
                sequence=record.sequence + 1,
                state=record.normalization,
            )
            if run is not None and runtime_activity:
                run.last_runtime_activity_at = time.monotonic()
            for event in events:
                self._publish(record, event)

    @staticmethod
    def _domain_stop_result(value):
        if not isinstance(value, dict) or value.get("service") != "beyondquant-mcp" or value.get("status") != "error":
            return False
        backend = value.get("backend")
        admission = backend.get("admission") if isinstance(backend, dict) else None
        if (not isinstance(admission, dict) or admission.get("schema_version") != "domain-call-admission.v1"
                or admission.get("stop") is not True):
            return False
        if admission.get("state") == "unknown":
            return set(admission) == {"schema_version", "state", "stop"}
        return (set(admission) == {"schema_version", "state", "stop", "reason"}
            and admission.get("state") in {"blocked", "correctable_failure"}
            and admission.get("reason") in {"call_evidence_pending", "prior_call_outcome_unknown", "unchanged_failed_input",
                "correction_budget_exhausted", "call_retention_bound", "correction_failed"})

    @staticmethod
    def _guard_seconds(name: str, *, default: float) -> float:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be a number") from exc
        if not 1.0 <= value <= 3600.0:
            raise ValueError(f"{name} must be between 1 and 3600 seconds")
        return value

    def _watch_run(self, record: RuntimeSession, run: ActiveRun) -> None:
        while not run.watchdog_stop.wait(timeout=1.0):
            now = time.monotonic()
            if self._enforce_run_guards(record, run, now=now):
                return
            self._emit_wait_notice(record, run, now=now)

    def _emit_wait_notice(self, record: RuntimeSession, run: ActiveRun, *, now: float) -> None:
        with record.lock:
            if (record.active_run is not run or record.status != SessionStatus.RUNNING
                    or now - max(run.started_at, run.last_wait_notice_at) < 60):
                return
            run.last_wait_notice_at = now
            self._emit(record, "session.waiting", "runtime-adapter", {
                "run_id": run.run_id,
                "elapsed_seconds": max(0, int(now - run.started_at)),
                "last_activity_seconds": max(0, int(now - run.last_runtime_activity_at)),
            })

    def _enforce_run_guards(
        self, record: RuntimeSession, run: ActiveRun, *, now: float,
    ) -> bool:
        with record.lock:
            if record.active_run is not run or record.status not in SessionStatus.ACTIVE_PROMPT:
                run.watchdog_stop.set()
                return False
            oldest_subagent = min(run.active_subagent_calls.values(), default=None)
            if run.domain_stop_code:
                code = run.domain_stop_code
            elif (now - run.started_at > self._run_timeout_seconds
                    or (run.continuation_deadline is not None and now >= run.continuation_deadline)):
                code = "runtime-run-timeout"
            elif (
                (oldest_subagent is not None and now - oldest_subagent > self._subagent_timeout_seconds)
                or any(child.expired(now, self._subagent_timeout_seconds, self._subagent_hard_cap_seconds)
                       for child in run.child_leases.values())
            ):
                code = "runtime-subagent-timeout"
            elif oldest_subagent is not None or run.child_leases:
                # A delegated child owns a separate, longer bound. Do not let
                # the parent's quiet interval mislabel active child work as a
                # no-progress failure before that dedicated deadline.
                return False
            elif now - run.last_runtime_activity_at > self._no_progress_timeout_seconds:
                code = "runtime-no-progress-timeout"
            else:
                return False
            run.hard_cancelled = True
            run.watchdog_stop.set()
            record.interrupted_run_id = run.run_id
            record.active_run = None
            record.status = SessionStatus.FAILED
            failed_harness = record.harness
            needs_close = not record.process_closed and not record.process_closing
            record.process_closing = needs_close or record.process_closing
            self._emit(
                record,
                "session.failed",
                "runtime-adapter",
                {"code": code, "retryable": not bool(run.domain_stop_code), "run_id": run.run_id},
            )
        # A session owns its DSH process, so closing it cannot interrupt any
        # other Product conversation. The detached worker will discard any
        # late result and resume creates a fresh private generation.
        if needs_close:
            self._compatibility.close(failed_harness)
            with record.lock:
                record.process_closing = False
                record.process_closed = True
        return True

    @staticmethod
    def _observe_run_observation(
        record: RuntimeSession, run: ActiveRun, observation: RuntimeObservation,
    ) -> bool:
        now = time.monotonic()
        if observation.kind == "subagent.started":
            child_id = observation.child_session_id
            # The official notification has no call ID. Only a unique pending
            # root delegation can be associated; ambiguity never renews a lease.
            if (observation.parent_session_id != record.runtime_session_id or not child_id
                    or child_id in run.child_leases or child_id in run.finished_children
                    or len(run.active_subagent_calls) != 1):
                return False
            call_id, started_at = next(iter(run.active_subagent_calls.items()))
            run.child_leases[child_id] = ChildLease(
                record.runtime_session_id, child_id, call_id, started_at, now,
            )
            run.active_subagent_calls.pop(call_id)
            return True
        if observation.kind == "subagent.finished":
            child_id = observation.child_session_id
            if observation.parent_session_id != record.runtime_session_id or child_id not in run.child_leases:
                return False
            run.child_leases.pop(child_id)
            run.finished_children.add(child_id)
            return True
        if not observation.root_session:
            child = run.child_leases.get(observation.session_id)
            return bool(child and observation.runtime_activity and child.observe(observation.event_sequence, now))
        if observation.runtime_activity and observation.event_sequence is not None:
            if observation.event_sequence <= run.last_root_sequence:
                return False
            run.last_root_sequence = observation.event_sequence
        if observation.kind == "tool.call":
            call_id = observation.call_id
            name = observation.tool_name
            if (
                observation.root_session
                and isinstance(call_id, str) and call_id
                and isinstance(name, str)
                and name.removeprefix("mcp__byq__").startswith("byq_delegate_")
            ):
                run.active_subagent_calls.setdefault(call_id, now)
        elif observation.kind == "tool.result" and observation.root_session:
            for call_id in observation.completed_call_ids:
                run.active_subagent_calls.pop(call_id, None)
        return observation.runtime_activity

    def _record_usage(self, record: RuntimeSession, observation: RuntimeObservation) -> None:
        """Aggregate a bounded compatibility observation without retaining DSH data."""

        if not observation.root_session or observation.kind != "assistant.message":
            return
        message_id = observation.message_id
        usage = observation.usage
        if message_id is None or not usage:
            return
        if message_id in record.usage_message_ids:
            return
        record.usage_message_ids.add(message_id)
        with self._lock:
            for key, value in usage.items():
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
            if kind in {"session.result", "session.failed", "session.cancelled", "session.closed"}:
                outcome = {"session.failed": "failed", "session.cancelled": "cancelled"}.get(kind, "unknown")
                for closure in close_public_activities(record.normalization, record.trace_id,
                                                       record.session_id, record.sequence + 1, outcome):
                    self._publish(record, closure)
            self._publish(record, event)
            if record.continuation_budget and kind in {'session.result', 'session.failed', 'session.cancelled', 'session.result.discarded'}:
                self._budget_receipt(record)

    @staticmethod
    def _publish(record: RuntimeSession, event: WorkflowTraceEvent) -> None:
        """Allocate and publish while holding the one session ordering lock."""

        record.sequence += 1
        ordered_event = {**event, "sequence": record.sequence}
        if record.journal:
            prompt = None
            if event["kind"] == "session.started":
                for key, (content, root) in record.prompt_idempotency.items():
                    if root == event["payload"]["run_id"]:
                        prompt = (key, hashlib.sha256(content.encode()).hexdigest())
                        break
            record.journal.observe(ordered_event, generation=record.runtime_generation, prompt=prompt)
        if record.workspace_id:
            terminal = project_lifecycle_event(ordered_event, record.session_id, record.trace_id)
            if terminal and terminal["outcome"] != "active":
                root = terminal["root_run_id"]
                if root not in record.terminal_receipts:
                    record.terminal_receipts[root] = lifecycle_receipt(terminal)
                    record.pending_terminal_receipts.add(root)
        record.history.append(ordered_event)
        for subscriber in list(record.subscribers):
            subscriber.put(ordered_event)
