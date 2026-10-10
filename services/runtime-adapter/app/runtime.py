from __future__ import annotations

import base64
import json
import hashlib
import hmac
import fcntl
import os
import queue
import re
import secrets
import stat
import shutil
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

import httpx
from packages.contracts.conversation_rehydration import (
    ConversationContextMessage,
    normalize_conversation_context,
    rehydrated_prompt,
)
from packages.contracts.agent_run_lifecycle import registration_fingerprint, lifecycle_receipt, project_lifecycle_event
from packages.contracts.domain_call_admission import (
    ACTIONS as DOMAIN_CALL_ACTIONS,
    call_evidence_receipt,
    request_evidence,
    validate_call_evidence,
)
from packages.contracts import runtime_continuity as continuity
from packages.contracts import session_failure_containment as containment_contract
from packages.contracts.continuation_request import (
    ALLOWED_MODEL as CONTINUATION_MODEL,
    ALLOWED_PROVIDER as CONTINUATION_PROVIDER,
    UPSTREAM_BASE_URL as CONTINUATION_UPSTREAM,
    exceeded_request_limits,
)

from .contracts import WorkflowTraceEvent, make_workflow_trace_event
from .child_lease import ChildLease
from .normalization import close_public_activities
from .compat import (
    ACP_COMPATIBILITY_FAMILY, RuntimeCompatibility, RuntimeObservation,
    compatibility_for_release,
)
from .identifiers import contained_session_path, validate_identifier
from .continuation_budget import (
    CONTINUATION_MAX_OUTPUT_TOKENS,
    validate_reservation,
    create_guard_patch,
    create_acp_guard_patch,
    create_acp_guard_overlay,
    create_acp_product_budget_overlay,
    read_request_guard,
)
from packages.contracts.product_turn_request import product_turn_limits, product_turn_profile
from .continuation_budget import PRODUCT_TURN_PROVIDER, PRODUCT_TURN_MODEL
from .research_request_gate import RequestGateProxy, build_continuation_request_gate
from .normalization import NormalizationState, normalize_runtime_observation


_PROCESS_BOOT_PID = os.getpid()
_PROCESS_BOOT_ID = secrets.token_hex(16)
_ACK_TOMBSTONE_LIMIT = 512


def _process_boot_id() -> str:
    """Return one random identity per OS process, including after a fork."""

    global _PROCESS_BOOT_PID, _PROCESS_BOOT_ID
    pid = os.getpid()
    if pid != _PROCESS_BOOT_PID:
        _PROCESS_BOOT_PID = pid
        _PROCESS_BOOT_ID = secrets.token_hex(16)
    return _PROCESS_BOOT_ID


class SessionConflict(RuntimeError):
    """The requested lifecycle operation is invalid for the current state."""


SESSION_LOST_DETAIL = "BYQ runtime session was interrupted; start a new Agent session"
SESSION_FAILED_DETAIL = "BYQ runtime session failed; start a new Agent session"


class ModelCredentialUnavailable(RuntimeError):
    """A model-keyed Product turn was requested without its provider secret."""


class RuntimeAuthorityUnavailable(RuntimeError):
    """Backend has not fenced this Adapter process for Agent traffic."""


_OPENCODE_PROVIDERS = frozenset({
    "opencode-go-responses",
    "opencode-go-chat",
    "opencode-go-messages",
    "opencode-zen-responses",
    "opencode-zen-chat",
    "opencode-zen-messages",
})

# ADR-0075: any credential-backed model on a closed DSH runtime provider may be
# used for background continuation. The Backend resolver has already enforced an
# active credential and a discovered/supported model, so the adapter only has to
# reject unknown routes here.
def _continuation_proxy_advertise_host() -> str:
    """Address the DSH child (in the runner container) must use to reach the proxy.

    The ACP product slot runs the DSH child in a separate container, so the
    Adapter's loopback address is not reachable. Prefer an explicit deployment
    address; otherwise advertise the Adapter's own routable IPv4.
    """
    import socket as _socket
    configured = os.environ.get("BYQ_CONTINUATION_PROXY_ADVERTISE_HOST")
    candidates: list[str] = []
    if isinstance(configured, str) and configured.strip():
        candidates.append(configured.strip())
    candidates.append(_socket.gethostname())
    for candidate in candidates:
        try:
            resolved = _socket.gethostbyname(candidate)
        except OSError:
            continue
        if resolved:
            return resolved
    return "127.0.0.1"


def _continuation_route_qualified(model_resolution: dict, provider: str, model: str) -> bool:
    """ADR-0090 grants one exact provider/model pair for this request profile."""

    resolved_provider = str(model_resolution.get("provider") or provider)
    resolved_model = model_resolution.get("model", model)
    return resolved_provider == CONTINUATION_PROVIDER and resolved_model == CONTINUATION_MODEL


def _root_journal_path(session_root: Path, stem: str, root_run_id: str) -> Path:
    """Bind a DSH guard/provider journal to exactly one fresh BYQ root."""

    if re.fullmatch(r"[0-9a-f]{32}", root_run_id) is None:
        raise SessionConflict("ACP root journal identity is invalid")
    return session_root / f"{stem}-{root_run_id}.jsonl"


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
    last_progress_check_at: float = 0.0
    watchdog_stop: threading.Event = field(default_factory=threading.Event, repr=False)


class GenerationState:
    STARTING: ClassVar[str] = "starting"
    READY: ClassVar[str] = "ready"
    RUNNING: ClassVar[str] = "running"
    CLOSED: ClassVar[str] = "closed"
    INTERRUPTED: ClassVar[str] = "interrupted"


@dataclass(slots=True)
class RuntimeGeneration:
    """Ephemeral DSH execution generation for one live BYQ Adapter session.

    A generation is disposable execution capacity, never session identity.
    Replacing it within the current Adapter process creates a fresh private
    DSH session and leaves cross-process recovery to the runtime owner.
    """

    generation_id: str
    session_id: str
    native_session_id: str
    executor_epoch: int = 0
    state: str = GenerationState.STARTING
    process_root_id: str = field(default="", repr=False)
    harness: Any = field(default=None, repr=False)
    process_used: bool = field(default=False, repr=False)
    process_closed: bool = field(default=False, repr=False)
    process_closing: bool = field(default=False, repr=False)
    native_session_close_confirmed: bool = field(default=False, repr=False)
    process_exit_confirmed: bool = field(default=False, repr=False)
    close_attempt_in_progress: bool = field(default=False, repr=False)
    close_attempt_event: threading.Event = field(default_factory=threading.Event, repr=False)
    continuation_budget: dict | None = field(default=None, repr=False)
    budget_journal: Path | None = field(default=None, repr=False)
    budget_run_id: str | None = field(default=None, repr=False)
    continuation_request_gate: Any = field(default=None, repr=False)
    continuation_request_proxy: Any = field(default=None, repr=False)
    continuation_proxy_closed: bool = True
    active_run: ActiveRun | None = None
    normalization: NormalizationState = field(default_factory=NormalizationState)
    usage_message_ids: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.close_attempt_event.set()

    def describe(self) -> dict[str, Any]:
        """Framework-neutral identity only; no DSH native/process schema."""

        return {
            "generation_id": self.generation_id,
            "session_id": self.session_id,
            "executor_epoch": self.executor_epoch,
            "state": self.state,
        }


@dataclass(slots=True)
class RuntimeSession:
    """Live Adapter binding for one DSH session in this Adapter boot."""

    session_id: str
    trace_id: str
    boot_id: str
    owner_principal: str | None = None
    workspace_id: str | None = None
    model_resolution: dict[str, object] = field(default_factory=dict, repr=False)
    pending_conversation_context: list[ConversationContextMessage] = field(default_factory=list, repr=False)
    status: str = SessionStatus.STARTING
    prompt_idempotency: dict[str, tuple[str, str]] = field(default_factory=dict, repr=False)
    terminal_receipts: dict[str, dict] = field(default_factory=dict, repr=False)
    pending_terminal_receipts: set[str] = field(default_factory=set, repr=False)
    domain_call_evidence: list[dict[str, object]] = field(default_factory=list, repr=False)
    domain_call_sequence: int = 0
    # Advances only after Backend returns the exact receipt for each row.
    domain_call_drained_sequence: int = 0
    release_finalized: bool = False
    # Public conversation termination is distinct from releasing this
    # Adapter-owned process. It is persisted only by the explicit release
    # intent; ordinary idle cleanup may preserve the Product conversation.
    conversation_ended: bool = False
    # Continuation settlement facts outlive an execution generation, but only
    # for this live Adapter session; missing sessions reconcile as unknown.
    budget_receipts: dict[str, dict] = field(default_factory=dict, repr=False)
    interrupted_run_id: str | None = None
    sequence: int = 0
    history: list[WorkflowTraceEvent] = field(default_factory=list)
    subscribers: list[queue.Queue[WorkflowTraceEvent | None]] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)
    executor_epoch: int = 0
    continuity: str | None = None
    authority_epoch: int | None = None
    recovery_cwd: str | None = None
    settlement_receipt: dict[str, Any] | None = None
    # Set only for a normal completed root whose exact Backend receipt was
    # accepted and whose ACP session close and process exit were both proven.
    # It is deliberately in-memory only: Adapter restart falls back to a fresh
    # ACP session and the Gateway's public history projection.
    reuse_native_session_ready: bool = False
    cleanup_unconfirmed: bool = False
    cleanup_harness: Any = field(default=None, repr=False)
    current_generation: RuntimeGeneration | None = field(default=None, repr=False)

    def _generation(self) -> RuntimeGeneration:
        """Return the active generation, creating an unbound placeholder."""

        if self.current_generation is None:
            self.current_generation = RuntimeGeneration(
                generation_id=f"generation-{uuid.uuid4().hex}",
                session_id=self.session_id,
                native_session_id=f"resume-{uuid.uuid4().hex}",
                executor_epoch=self.executor_epoch,
            )
        return self.current_generation

    @property
    def harness(self) -> Any:
        return self.current_generation.harness if self.current_generation is not None else None

    @harness.setter
    def harness(self, value: Any) -> None:
        self._generation().harness = value

    @property
    def runtime_session_id(self) -> str:
        return self.current_generation.native_session_id if self.current_generation is not None else ""

    @runtime_session_id.setter
    def runtime_session_id(self, value: str) -> None:
        self._generation().native_session_id = value

    @property
    def runtime_generation(self) -> str:
        return self.current_generation.generation_id if self.current_generation is not None else ""

    @runtime_generation.setter
    def runtime_generation(self, value: str) -> None:
        self._generation().generation_id = value

    @property
    def process_root_id(self) -> str:
        return self.current_generation.process_root_id if self.current_generation is not None else ""

    @process_root_id.setter
    def process_root_id(self, value: str) -> None:
        self._generation().process_root_id = value

    @property
    def process_used(self) -> bool:
        return self.current_generation.process_used if self.current_generation is not None else False

    @process_used.setter
    def process_used(self, value: bool) -> None:
        self._generation().process_used = value

    @property
    def process_closed(self) -> bool:
        return self.current_generation.process_closed if self.current_generation is not None else False

    @process_closed.setter
    def process_closed(self, value: bool) -> None:
        self._generation().process_closed = value

    @property
    def process_closing(self) -> bool:
        return self.current_generation.process_closing if self.current_generation is not None else False

    @process_closing.setter
    def process_closing(self, value: bool) -> None:
        self._generation().process_closing = value

    @property
    def continuation_budget(self) -> dict | None:
        return self.current_generation.continuation_budget if self.current_generation is not None else None

    @continuation_budget.setter
    def continuation_budget(self, value: dict | None) -> None:
        self._generation().continuation_budget = value

    @property
    def budget_journal(self) -> Path | None:
        return self.current_generation.budget_journal if self.current_generation is not None else None

    @budget_journal.setter
    def budget_journal(self, value: Path | None) -> None:
        self._generation().budget_journal = value

    @property
    def budget_run_id(self) -> str | None:
        return self.current_generation.budget_run_id if self.current_generation is not None else None

    @budget_run_id.setter
    def budget_run_id(self, value: str | None) -> None:
        self._generation().budget_run_id = value

    @property
    def continuation_request_gate(self):
        return self.current_generation.continuation_request_gate if self.current_generation is not None else None

    @continuation_request_gate.setter
    def continuation_request_gate(self, value) -> None:
        self._generation().continuation_request_gate = value

    @property
    def continuation_request_proxy(self):
        return self.current_generation.continuation_request_proxy if self.current_generation is not None else None

    @continuation_request_proxy.setter
    def continuation_request_proxy(self, value) -> None:
        self._generation().continuation_request_proxy = value

    @property
    def continuation_proxy_closed(self) -> bool:
        return self.current_generation.continuation_proxy_closed if self.current_generation is not None else True

    @continuation_proxy_closed.setter
    def continuation_proxy_closed(self, value: bool) -> None:
        self._generation().continuation_proxy_closed = value

    @property
    def active_run(self) -> ActiveRun | None:
        return self.current_generation.active_run if self.current_generation is not None else None

    @active_run.setter
    def active_run(self, value: ActiveRun | None) -> None:
        self._generation().active_run = value

    @property
    def normalization(self) -> NormalizationState:
        return self._generation().normalization

    @normalization.setter
    def normalization(self, value: NormalizationState) -> None:
        self._generation().normalization = value

    @property
    def usage_message_ids(self) -> set[str]:
        return self._generation().usage_message_ids

    @usage_message_ids.setter
    def usage_message_ids(self, value: set[str]) -> None:
        self._generation().usage_message_ids = value


class RuntimeAdapter:
    """Own one official DSH ACP subprocess per active BYQ session.

    An owned process makes hard cancellation and failure isolation explicit: hard
    cancel closes the owned process, while soft cancel marks only the current
    run and resets to idle when that run settles.
    """

    def __init__(self, compatibility: RuntimeCompatibility | None = None) -> None:
        if compatibility is None:
            release = os.environ.get(
                "BYQ_DSH_COMPATIBILITY_RELEASE", ACP_COMPATIBILITY_FAMILY)
            self._compatibility = compatibility_for_release(release)
        else:
            # Explicit injection remains available to isolated synthetic tests;
            # production startup never selects a compatibility by test injection.
            self._compatibility = compatibility
        self._acp = self._compatibility.family == ACP_COMPATIBILITY_FAMILY
        self._acp_product_slots = (
            self._acp and getattr(self._compatibility, "product_slots", None) is not None)
        self._sessions: dict[str, RuntimeSession] = {}
        # Lost ACK responses can be retried after a released session is reaped,
        # but this receipt cache never crosses an Adapter boot.
        self._ack_tombstones: OrderedDict[tuple[str, str, str, str, int], dict[str, Any]] = OrderedDict()
        # Retain no event rows after reap; the marker permits only the exact
        # final private evidence cursor to receive an empty idle page.
        self._released_domain_sessions: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
        self._lock = threading.RLock()
        self._runtime_root = Path(os.environ.get("BYQ_DSH_RUNTIME_ROOT", "/opt/dsh-runtime"))
        self._composition = Path(
            os.environ.get(
                "BYQ_DSH_COMPOSITION",
                "/opt/byq/profiles/byq-product.patch.yml",
            )
        )
        self._composition_identity = Path(
            os.environ.get(
                "BYQ_DSH_COMPOSITION_IDENTITY",
                "/opt/byq/profiles/byq-product.identity.json",
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
        if self._root_scoped and not self._acp:
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
        # The fallback credential follows the selected runtime provider so an
        # OpenCode route never receives the DeepSeek key (and vice versa).
        if self._provider in _OPENCODE_PROVIDERS:
            self._model_api_key = os.environ.get("OPENCODE_API_KEY")
        else:
            self._model_api_key = os.environ.get("DEEPSEEK_API_KEY")
        self._backend_url = os.environ.get("BYQ_BACKEND_URL", "http://backend:8000")
        # Process identity is deliberately ephemeral: all Adapter instances in
        # this OS process share it, while a new process gets a fresh 128-bit token.
        self.boot_id = _process_boot_id()
        self._resolver_token = os.environ.get("BYQ_CREDENTIAL_RESOLVER_TOKEN")
        self._run_timeout_seconds = self._guard_seconds(
            "BYQ_DSH_RUN_TIMEOUT_SECONDS", default=0.0, allow_disabled=True, maximum=86400.0,
        )
        self._progress_check_interval_seconds = self._guard_seconds(
            "BYQ_DSH_PROGRESS_CHECK_INTERVAL_SECONDS", default=900.0,
        )
        self._subagent_timeout_seconds = self._guard_seconds(
            "BYQ_DSH_SUBAGENT_TIMEOUT_SECONDS", default=180.0,
        )
        self._subagent_hard_cap_seconds = self._guard_seconds(
            "BYQ_DSH_SUBAGENT_HARD_CAP_SECONDS", default=0.0, allow_disabled=True, maximum=86400.0,
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
            "ready" if self._acp and release_identity["status"] == "matched"
            and composition_identity["composition_hash"] != "unavailable"
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
                "progress_check_interval_seconds": self._progress_check_interval_seconds,
                "subagent_hard_cap_seconds": self._subagent_hard_cap_seconds,
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

    def authority_identity(self) -> dict[str, str]:
        """Return the transport identity used by Gateway to fence this process."""

        return {
            "schema_version": "byq-runtime-adapter-authority.v1",
            "boot_id": self.boot_id,
            "status": "ready",
        }

    def require_current_backend_authority(self) -> int:
        """Fail closed unless Backend has committed this exact Adapter boot."""

        try:
            response = httpx.get(
                f"{self._backend_url.rstrip('/')}/internal/runtime-authority/current",
                timeout=2.0,
            )
            response.raise_for_status()
            current = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeAuthorityUnavailable("Backend runtime authority is unavailable") from exc
        if (not isinstance(current, dict)
                or set(current) != {"schema_version", "boot_id", "authority_epoch", "status"}
                or current.get("schema_version") != "byq-runtime-authority-current.v1"
                or not isinstance(current.get("boot_id"), str)
                or re.fullmatch(r"[0-9a-f]{32}", current["boot_id"]) is None
                or type(current.get("authority_epoch")) is not int
                or current["authority_epoch"] < 1
                or current.get("status") != "current"
                or current.get("boot_id") != self.boot_id):
            raise RuntimeAuthorityUnavailable("Backend runtime authority is not current")
        return current["authority_epoch"]

    def _require_group_admission(self, record: RuntimeSession, root_run_id: str) -> None:
        """Keep unresolved Backend roots fenced after the slot client restarts."""
        if not self._acp_product_slots:
            return
        token = os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
        if not token:
            raise RuntimeAuthorityUnavailable("workspace Agent authority is unavailable")
        try:
            response = httpx.get(
                f"{self._backend_url.rstrip('/')}/internal/runtime-authority/workspaces/"
                f"{record.workspace_id}/agent-admission",
                params={"root_run_id": root_run_id, "session_id": record.session_id},
                headers={"Authorization": f"Bearer {token}",
                    "X-BYQ-Owner-Principal": record.owner_principal,
                    "X-BYQ-Runtime-Boot-ID": self.boot_id}, timeout=2.0)
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            raise RuntimeAuthorityUnavailable("workspace Agent admission is unavailable") from None
        if (not isinstance(result, dict) or set(result) != {
                "schema_version", "workspace_id", "boot_id", "root_run_id", "can_start"}
                or result["schema_version"] != "byq-workspace-agent-admission.v1"
                or result["workspace_id"] != record.workspace_id
                or result["boot_id"] != self.boot_id
                or result["root_run_id"] != root_run_id
                or type(result["can_start"]) is not bool):
            raise RuntimeAuthorityUnavailable("workspace Agent admission is unproven")
        if not result["can_start"]:
            raise SessionConflict("workspace has an unsettled Agent turn")

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
                    "ready" if self._acp and release_identity["status"] == "matched"
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
        if self._acp:
            try:
                actual = "sha256:" + hashlib.sha256(self._composition.read_bytes()).hexdigest()
            except OSError:
                return fallback
            if actual != digest:
                return fallback
        return {"profile": profile, "composition_hash": digest, "enabled_plugin_ids": plugin_ids}

    def _safe_release_identity(self) -> dict[str, str]:
        """Match the installed ACP source and lock to its deployment identity."""

        fallback = {
            "release_id": "dsh-v0.2.0-rc.2" if self._acp else "unknown",
            "installed_sdk": "not-applicable",
            "installed_runtime_bin": "not-applicable",
            "status": "unavailable",
        }
        if not self._acp:
            return fallback
        try:
            value = json.loads(self._release_identity.read_text(encoding="utf-8"))
            lock_hash = hashlib.sha256(
                (self._runtime_root / "pnpm-lock.yaml").read_bytes()
            ).hexdigest()
        except (OSError, ValueError):
            return fallback
        if (not isinstance(value, dict)
                or value.get("schema_version") != "dsh-acp-deployment-identity.v1"
                or value.get("release_id") != "dsh-v0.2.0-rc.2"
                or value.get("source_commit") != "639ed015397290b3745d163aafe02ffee4aa3f84"
                or value.get("pnpm_lock_sha256") != lock_hash
                or not (self._runtime_root / "apps/cli/lib/bin.js").is_file()):
            return fallback
        return {**fallback, "status": "matched"}

    @staticmethod
    def _terminal_fenced(record: RuntimeSession, generation_id: str, executor_epoch: int) -> bool:
        """A run may only settle state for its own live generation.

        A late terminal from a replaced in-process generation fails closed
        instead of overwriting the newer generation's state.
        """

        current = record.current_generation
        if current is None:
            return False
        try:
            containment_contract.assert_generation_fenced(
                authoritative_epoch=record.executor_epoch,
                authoritative_generation=current.generation_id,
                write_epoch=executor_epoch,
                write_generation=generation_id,
            )
        except containment_contract.FencedWrite:
            return True
        return False

    def _close_generation(self, record: RuntimeSession, generation_id: str, state: str) -> None:
        """Update the active generation state after a fenced terminal."""

        if not generation_id:
            return
        current = record.current_generation
        if current is not None and current.generation_id == generation_id:
            current.state = state

    def _retire_generation(self, record: RuntimeSession, state: str) -> RuntimeGeneration | None:
        """Retire the active generation without changing its live session record."""

        generation = record.current_generation
        if generation is None:
            return None
        generation.state = state
        record.current_generation = None
        return generation

    def _install_generation(
        self, record: RuntimeSession, *, native_session_id: str, executor_epoch: int,
        process_root_id: str = "",
        retired_state: str = GenerationState.CLOSED, generation_id: str | None = None,
    ) -> RuntimeGeneration:
        """Replace the live DSH generation with a new private native session."""

        self._retire_generation(record, retired_state)
        generation = RuntimeGeneration(
            generation_id=generation_id or f"generation-{uuid.uuid4().hex}",
            session_id=record.session_id,
            native_session_id=native_session_id,
            executor_epoch=executor_epoch or record.executor_epoch,
            process_root_id=process_root_id,
            state=GenerationState.STARTING,
        )
        record.current_generation = generation
        record.executor_epoch = generation.executor_epoch
        return generation

    def create_session(
        self, session_id: str, trace_id: str, owner_principal: str | None = None,
        workspace_id: str | None = None, initial_sequence: int = 0,
        conversation_context: object = None,
    ) -> dict[str, Any]:
        validate_identifier(session_id, field="session_id")
        validate_identifier(trace_id, field="trace_id")
        if (type(initial_sequence) is not int or initial_sequence < 0
                or (not self._acp and initial_sequence != 0)):
            raise SessionConflict(SESSION_LOST_DETAIL)
        with self._lock:
            if session_id in self._sessions:
                raise SessionConflict(f"BYQ session already exists: {session_id}")
        if self._acp and self._acp_binding_path(session_id, workspace_id).exists():
            raise SessionConflict("BYQ session has a persistent ACP recovery binding")
        context = normalize_conversation_context([] if conversation_context is None else conversation_context)
        # DSH session files are private execution state. Give every fresh BYQ
        # session a new native identity; the Adapter never reopens old state.
        runtime_session_id = f"session-{uuid.uuid4().hex}"
        storage_root = (self._compatibility.session_storage_root(self._session_root, workspace_id)
                        if self._acp_product_slots else self._session_root)
        session_root = contained_session_path(storage_root, runtime_session_id)
        model_resolution = self._resolve_model(
            owner_principal=owner_principal,
            session_id=session_id,
            trace_id=trace_id,
        )

        with self._lock:
            if session_id in self._sessions:
                raise SessionConflict(f"BYQ session already exists: {session_id}")
            runtime_generation = f"generation-{uuid.uuid4().hex}"
            process_root_id = uuid.uuid4().hex if self._root_scoped else ""
            try:
                harness = self._build_harness(
                    session_id, session_root, trace_id=trace_id, owner_principal=owner_principal,
                    workspace_id=workspace_id, model_resolution=model_resolution,
                    runtime_generation=runtime_generation, root_run_id=process_root_id)
            except BaseException:
                raise
            record = RuntimeSession(
                session_id=session_id,
                trace_id=trace_id,
                boot_id=self.boot_id,
                owner_principal=owner_principal,
                workspace_id=workspace_id,
                model_resolution=model_resolution,
                pending_conversation_context=context,
                sequence=initial_sequence,
                history=[],
                recovery_cwd=str(session_root),
            )
            self._install_generation(
                record, native_session_id=runtime_session_id,
                executor_epoch=record.executor_epoch,
                process_root_id=process_root_id, generation_id=runtime_generation,
            )
            record.harness = harness
            record.continuity = continuity.FRESH
            self._sessions[session_id] = record

        try:
            # A saved conversation does not reserve an execution container.
            # The slot candidate creates its native ACP session on first input.
            if not self._acp_product_slots:
                self._compatibility.start(harness)
            if self._acp and not self._acp_product_slots:
                native_id = self._compatibility.create_session(harness, cwd=session_root)
                with record.lock:
                    record.runtime_session_id = native_id
            with record.lock:
                if record.status != SessionStatus.STARTING:
                    raise SessionConflict("session closed during initialization")
                if record.current_generation is not None:
                    record.current_generation.state = GenerationState.READY
                record.status = SessionStatus.READY
                self._emit(record, "session.ready", "runtime-adapter", {"status": "ready"})
            return self.describe_session(record)
        except Exception:
            with self._lock:
                if self._sessions.get(session_id) is record:
                    del self._sessions[session_id]
            self._compatibility.close(harness)
            raise

    def submit_prompt(
        self, session_id: str, content: str, *, require_model_key: bool = False,
        idempotency_key: str | None = None,
        conversation_context: object = None,
        continuation_budget: object = None,
    ) -> str:
        record = self._get(session_id)
        with record.lock:
            if record.cleanup_unconfirmed:
                raise SessionConflict("previous ACP root startup cleanup is unconfirmed")
        if not record.model_resolution:
            with record.lock:
                if not record.model_resolution:
                    record.model_resolution = self._resolve_model(
                        owner_principal=record.owner_principal,
                        session_id=record.session_id,
                        trace_id=record.trace_id,
                    )
        first_lazy_prestart_binding = False
        with record.lock:
            identity_content = content if continuation_budget is None else json.dumps(
                {'content': content, 'reservation': continuation_budget}, sort_keys=True, separators=(',', ':'))
            if idempotency_key is not None:
                if not 8 <= len(idempotency_key) <= 128:
                    raise ValueError("prompt idempotency key has invalid length")
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
            if (record.workspace_id or self._acp) and record.pending_terminal_receipts:
                raise SessionConflict("previous turn domain cleanup is not yet acknowledged")
            if (self._acp and record.domain_call_drained_sequence != record.domain_call_sequence):
                raise SessionConflict("previous turn domain-call evidence is not yet acknowledged")
            budget = None
            if continuation_budget is not None:
                if not self.continuation_qualified(record):
                    raise ValueError('continuation executor is not enabled')
                budget = validate_reservation(continuation_budget,
                    owner=record.owner_principal, workspace=record.workspace_id)
                if idempotency_key != budget['reservation_id']:
                    raise ValueError('continuation requires its original reservation key')
                if not _continuation_route_qualified(record.model_resolution, self._provider, self._model):
                    raise ValueError('selected continuation model is unqualified')
            if record.status not in SessionStatus.PROMPTABLE or record.active_run is not None:
                raise SessionConflict(
                    f"session {session_id} cannot accept a prompt in state {record.status}"
                )
            if self._acp_product_slots and not record.process_used and budget is None:
                # ADR-0106: the first ordinary submit starts the ACP product slot.
                # The create_session harness carries no provider budget. This ACP
                # candidate qualifies ONLY the OpenCode Go / `deepseek-v4.1-flash`
                # route; any other resolved model is rejected BEFORE any proxy or
                # process start (no unbudgeted egress, no silent switch). Any
                # failure (including group admission/start) closes the proxy.
                first_provider = str(record.model_resolution.get('provider') or self._provider)
                first_model = str(record.model_resolution.get('model') or self._model)
                first_proxy = None
                no_start_proven = False
                start_invoked = False
                prestart_binding_attempted = False
                prestart_binding_sha256 = None
                try:
                    if (first_provider != PRODUCT_TURN_PROVIDER
                            or first_model != PRODUCT_TURN_MODEL):
                        raise ModelCredentialUnavailable(
                            "ordinary ACP Product model is not qualified (NOT_QUALIFIED)")
                    first_gate = build_continuation_request_gate(
                        request_id='product-turn-' + record.runtime_generation,
                        execution_profile=product_turn_profile(),
                        limits=product_turn_limits(),
                        journal=_root_journal_path(
                            Path(record.recovery_cwd), 'product-turn-provider-request',
                            record.process_root_id),
                    )
                    first_proxy = RequestGateProxy(
                        first_gate, CONTINUATION_UPSTREAM, bind_host="0.0.0.0",
                        advertise_host=_continuation_proxy_advertise_host())
                    first_proxy.__enter__()
                    first_overlay = base64.b64encode(create_acp_product_budget_overlay(
                        proxy_base_url=first_proxy.base_url,
                        provider_session_id=str(uuid.uuid5(uuid.NAMESPACE_URL,
                            "beyondquant:provider-session:" + record.session_id)),
                        provider=first_provider, model=first_model)).decode('ascii')
                    record.harness = self._build_harness(
                        record.session_id, Path(record.recovery_cwd), trace_id=record.trace_id,
                        owner_principal=record.owner_principal, workspace_id=record.workspace_id,
                        model_resolution=record.model_resolution,
                        runtime_generation=record.runtime_generation,
                        root_run_id=record.process_root_id,
                        continuation_proxy_url=first_proxy.base_url,
                        continuation_deadline_epoch_ms=int(
                            time.time() * 1000 + first_gate.remaining_seconds() * 1000),
                        product_turn_overlay_b64=first_overlay)
                    record.continuation_request_gate = first_gate
                    record.continuation_request_proxy = first_proxy
                    # Bind the first lazy Product root to the current Backend
                    # authority before START. Unknown start outcomes must be
                    # recoverable from this exact durable root binding.
                    no_start_proven = True
                    record.authority_epoch = self.require_current_backend_authority()
                    record.cleanup_harness = record.harness
                    record.cleanup_unconfirmed = True
                    prestart_binding_attempted = True
                    first_lazy_prestart_binding = True
                    prestart_binding_sha256 = self._persist_acp_binding(record)
                    # A continuation (budget is not None) starts its own ACP root
                    # below; starting the slot here would hold the workspace lease
                    # and make the continuation's availability check report busy.
                    from .acp_product_slot_client import ProductSlotBusy
                    try:
                        self._require_group_admission(record, record.process_root_id)
                    except BaseException:
                        # Admission rejection is a positive proof that start() was
                        # never invoked for this prepared root.
                        no_start_proven = True
                        raise
                    no_start_proven = False
                    start_invoked = True
                    try:
                        self._compatibility.start(record.harness)
                    except ProductSlotBusy:
                        if (getattr(record.harness, "process", None) is None
                                and getattr(record.harness, "slot_scope", None) is None):
                            no_start_proven = True
                            raise SessionConflict(
                                "workspace Agent execution slot is busy") from None
                        record.cleanup_harness = record.harness
                        record.cleanup_unconfirmed = True
                        raise SessionConflict(
                            "workspace Agent execution requires reconciliation") from None
                    except Exception:
                        if (getattr(record.harness, "process", None) is None
                                and getattr(record.harness, "slot_scope", None) is None):
                            no_start_proven = True
                            raise SessionConflict(
                                "workspace Agent execution is unavailable; retry later") from None
                        record.cleanup_harness = record.harness
                        record.cleanup_unconfirmed = True
                        raise SessionConflict(
                            "workspace Agent execution requires reconciliation") from None
                    # create_session can execute ACP requests; every failure from
                    # this point is ambiguous and must retain the prepared guard.
                    record.runtime_session_id = self._compatibility.create_session(
                        record.harness, cwd=record.recovery_cwd)
                except BaseException:
                    close_failed = False
                    if first_proxy is not None:
                        try:
                            first_proxy.close()
                        except BaseException:
                            close_failed = True
                    record.continuation_request_gate = None
                    record.continuation_request_proxy = None
                    if close_failed:
                        no_start_proven = False
                    if no_start_proven and not close_failed:
                        try:
                            from .compat.dsh_acp import retire_prepared_guard_patch
                            prepared_digest = getattr(
                                record.harness, "prepared_guard_sha256", None)
                            if not isinstance(prepared_digest, str):
                                raise SessionConflict(
                                    "ACP prepared guard identity is unavailable")
                            retire_prepared_guard_patch(
                                Path(record.harness.session_root),
                                expected_root_id=record.process_root_id,
                                expected_sha256=prepared_digest,
                            )
                        except BaseException:
                            record.cleanup_harness = record.harness
                            record.cleanup_unconfirmed = True
                            raise SessionConflict(
                                "workspace Agent execution requires reconciliation") from None
                        if prestart_binding_attempted:
                            # A failed write has an unknown durable outcome. Do
                            # not infer safety from a missing file or replace a
                            # possibly foreign marker; keep this record fenced.
                            if not isinstance(prestart_binding_sha256, str):
                                record.cleanup_harness = record.harness
                                record.cleanup_unconfirmed = True
                                raise SessionConflict(
                                    "workspace Agent execution requires reconciliation") from None
                            try:
                                self._remove_prestart_acp_binding(
                                    record, expected_sha256=prestart_binding_sha256)
                            except BaseException:
                                record.cleanup_harness = record.harness
                                record.cleanup_unconfirmed = True
                                raise SessionConflict(
                                    "workspace Agent execution requires reconciliation") from None
                            record.cleanup_harness = None
                            record.cleanup_unconfirmed = False
                    elif start_invoked or close_failed:
                        # START, create_session, or proxy-close uncertainty may
                        # require reconciliation before another attempt.
                        record.cleanup_harness = record.harness
                        record.cleanup_unconfirmed = True
                        raise SessionConflict(
                            "workspace Agent execution requires reconciliation") from None
                    raise
            # A Gateway-owned projection can refresh a new root without a
            # separate resume race. Omission retains the prepared create/resume
            # context; an explicit empty list intentionally clears it.
            context = record.pending_conversation_context
            if conversation_context is not None:
                context = normalize_conversation_context(conversation_context)
            reuse_native = bool(
                self._acp and self._root_scoped and record.process_used
                and record.reuse_native_session_ready
            )
            # A resumed ACP root already owns the complete native history.
            # Reinjecting Gateway's public projection would duplicate turns.
            effective_content = content if reuse_native else rehydrated_prompt(context, content)
            if budget is not None and not record.process_used:
                self._compatibility.close(record.harness)
                record.process_closed = True
                if self._acp and record.current_generation is not None:
                    record.current_generation.process_exit_confirmed = True
            if self._root_scoped and (record.process_used or budget is not None):
                if record.workspace_id and conversation_context is None and not reuse_native:
                    raise SessionConflict("new root requires a fresh public conversation projection")
                if (record.process_closing or not record.process_closed
                        or not record.continuation_proxy_closed):
                    raise SessionConflict("previous runtime process cleanup is not complete")
                if (self._acp and record.process_used and record.current_generation is not None
                        and not record.current_generation.process_exit_confirmed):
                    raise SessionConflict("previous ACP process exit is not confirmed")
                if record.continuation_budget is not None:
                    old_id = record.continuation_budget['reservation_id']
                    old_receipt = self._budget_receipt(record)
                    if old_receipt.get('status') == 'settled':
                        record.budget_receipts[old_id] = old_receipt
                    while len(record.budget_receipts) > 64:
                        del record.budget_receipts[next(iter(record.budget_receipts))]
                previous_native_session = record.runtime_session_id
                previous_process_root_id = record.process_root_id
                if self._acp_product_slots:
                    from .acp_product_slot_client import ProductSlotBusy
                    try:
                        self._compatibility.product_slots.get_available_binding(record.workspace_id)
                    except ProductSlotBusy:
                        raise SessionConflict("workspace Agent execution slot is busy") from None
                private_session = f"root-{uuid.uuid4().hex}"
                generation = f"generation-{uuid.uuid4().hex}"
                root_id = uuid.uuid4().hex
                storage_root = (self._compatibility.session_storage_root(
                    self._session_root, record.workspace_id)
                    if self._acp_product_slots else self._session_root)
                session_root = (Path(record.recovery_cwd) if reuse_native and record.recovery_cwd
                                else contained_session_path(storage_root, private_session))
                if not session_root.resolve().is_relative_to(self._session_root):
                    raise SessionConflict("reused ACP working directory is not contained")
                if self._acp_product_slots and reuse_native:
                    # The fixed runner patch is invocation configuration, not
                    # persistent DSH state. Rotate it only after the exact ACK
                    # and process/native close gate above has made this root
                    # reusable. Failure is fail-closed before a new runner starts.
                    from .compat.dsh_acp import archive_previous_continuation_guard_patch
                    archive_previous_continuation_guard_patch(
                        session_root, previous_root_id=previous_process_root_id,
                    )
                request_gate = None
                request_proxy = None
                tool_journal = None
                product_turn_overlay_b64 = None
                self._require_group_admission(record, root_id)
                try:
                    if budget is not None:
                        request_gate = build_continuation_request_gate(
                            request_id=budget['reservation_id'],
                            execution_profile=budget['execution_profile'],
                            limits=budget['request_limits'],
                            journal=(_root_journal_path(
                                session_root, 'continuation-provider-request', root_id)
                                if self._acp else
                                session_root / 'continuation-provider-request.jsonl'),
                        )
                        request_proxy = RequestGateProxy(
                            request_gate, CONTINUATION_UPSTREAM,
                            bind_host="0.0.0.0" if self._acp_product_slots else "127.0.0.1",
                            advertise_host=(_continuation_proxy_advertise_host()
                                            if self._acp_product_slots else None),
                        )
                        request_proxy.__enter__()
                        tool_journal = (_root_journal_path(
                            session_root, 'continuation-tool-guard', root_id)
                            if self._acp else
                            session_root / 'continuation-tool-guard.jsonl')
                    elif self._acp and self._acp_product_slots:
                        # ADR-0106: this ACP candidate qualifies ONLY the OpenCode Go
                        # / `deepseek-v4.1-flash` route; any other resolved model is
                        # rejected before any proxy is created (no unbudgeted egress,
                        # no silent switch). All construction stays inside this try so
                        # a failure closes an opened proxy.
                        runtime_provider = str(record.model_resolution.get('provider') or self._provider)
                        runtime_model = str(record.model_resolution.get('model') or self._model)
                        if (runtime_provider != PRODUCT_TURN_PROVIDER
                                or runtime_model != PRODUCT_TURN_MODEL):
                            raise ModelCredentialUnavailable(
                                "ordinary ACP Product model is not qualified (NOT_QUALIFIED)")
                        product_provider_session_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                            "beyondquant:provider-session:" + record.session_id))
                        request_gate = build_continuation_request_gate(
                            request_id='product-turn-' + generation,
                            execution_profile=product_turn_profile(),
                            limits=product_turn_limits(),
                            journal=_root_journal_path(
                                session_root, 'product-turn-provider-request', root_id),
                        )
                        request_proxy = RequestGateProxy(
                            request_gate, CONTINUATION_UPSTREAM,
                            bind_host="0.0.0.0",
                            advertise_host=_continuation_proxy_advertise_host(),
                        )
                        request_proxy.__enter__()
                        product_turn_overlay_b64 = base64.b64encode(
                            create_acp_product_budget_overlay(
                                proxy_base_url=request_proxy.base_url,
                                provider_session_id=product_provider_session_id,
                                provider=runtime_provider, model=runtime_model)).decode('ascii')
                    harness = self._build_harness(record.session_id, session_root,
                        trace_id=record.trace_id, owner_principal=record.owner_principal,
                        workspace_id=record.workspace_id, model_resolution=record.model_resolution,
                        runtime_generation=generation, root_run_id=root_id, continuation_budget=budget,
                        continuation_proxy_url=request_proxy.base_url if request_proxy is not None else None,
                        continuation_deadline_epoch_ms=(
                            int(time.time() * 1000 + request_gate.remaining_seconds() * 1000)
                            if request_gate is not None else None
                        ),
                        product_turn_overlay_b64=product_turn_overlay_b64,
                        native_root_session_id=(previous_native_session if reuse_native else None))
                except BaseException:
                    if request_proxy is not None:
                        request_proxy.close()
                    raise
                if self._acp:
                    # Write a durable fail-closed marker before a replacement
                    # ACP process can own the new root identity. The new root and
                    # its current authority epoch must be bound first.
                    record.process_root_id = root_id
                    record.authority_epoch = self.require_current_backend_authority()
                    record.cleanup_harness = harness
                    record.cleanup_unconfirmed = True
                    try:
                        self._persist_acp_binding(record)
                    except BaseException:
                        record.cleanup_harness = None
                        record.cleanup_unconfirmed = False
                        if request_proxy is not None:
                            request_proxy.close()
                        raise
                    try:
                        self._compatibility.start(harness)
                        if reuse_native:
                            private_session = self._compatibility.resume_session(
                                harness, previous_native_session, cwd=session_root)
                            if private_session != previous_native_session:
                                raise SessionConflict("ACP resumed another native session")
                        else:
                            private_session = self._compatibility.create_session(harness, cwd=session_root)
                    except BaseException as exc:
                        from .acp_product_slot_client import ProductSlotBusy
                        if self._acp_product_slots and (isinstance(exc, ProductSlotBusy)
                                or (getattr(harness, "process", None) is None
                                    and getattr(harness, "slot_scope", None) is None)):
                            # No START was dispatched; restore the settled binding.
                            record.cleanup_harness = None
                            record.cleanup_unconfirmed = False
                            self._persist_acp_binding(record)
                            message = ("workspace Agent execution slot is busy"
                                if isinstance(exc, ProductSlotBusy)
                                else "workspace Agent execution is unavailable; retry later")
                            raise SessionConflict(message) from None
                        # Do not block on ACP teardown while holding the
                        # RuntimeSession lock. Keep the process handle and
                        # permanently fence this record until cleanup can be
                        # confirmed by an operator/runtime restart.
                        record.cleanup_harness = harness
                        record.cleanup_unconfirmed = True
                        if request_proxy is not None:
                            request_proxy.close()
                        raise
                # Every BYQ root gets a fresh process generation and MCP
                # identity. Only a normally completed, exactly acknowledged,
                # cleanly closed ACP root may carry its native transcript.
                self._install_generation(
                    record, native_session_id=private_session,
                    executor_epoch=record.executor_epoch, process_root_id=root_id,
                    generation_id=generation,
                )
                installed = record.current_generation
                record.reuse_native_session_ready = False
                installed.harness = harness
                record.recovery_cwd = str(session_root)
                record.settlement_receipt = None
                record.cleanup_unconfirmed = False
                record.cleanup_harness = None
                installed.continuation_budget = budget
                installed.budget_journal = tool_journal
                installed.budget_run_id = root_id if budget else None
                installed.continuation_request_gate = request_gate
                installed.continuation_request_proxy = request_proxy
                installed.continuation_proxy_closed = request_proxy is None
            if record.harness is None:
                raise SessionConflict("runtime process is unavailable for this Agent session")
            now = time.monotonic()
            run = ActiveRun(run_id=record.process_root_id if self._root_scoped else uuid.uuid4().hex,
                            started_at=now, last_runtime_activity_at=now)
            if budget:
                # The monotonic one-request deadline includes prompt construction,
                # provider retries/compaction, tool work and idle gaps. The
                # business authorization expiry is validated separately above.
                run.continuation_deadline = record.continuation_request_gate.deadline_monotonic
            record.process_used = True
            record.pending_conversation_context = []
            record.active_run = run
            if record.current_generation is not None:
                record.current_generation.state = GenerationState.RUNNING
            record.status = SessionStatus.RUNNING
            if idempotency_key is not None:
                record.prompt_idempotency[idempotency_key] = (identity_content, run.run_id)
            try:
                if self._acp:
                    if not first_lazy_prestart_binding:
                        record.authority_epoch = self.require_current_backend_authority()
                    if first_lazy_prestart_binding:
                        # The durable cleanup fence stays set until the accepted
                        # root binding replaces it with the now-active root.
                        record.cleanup_unconfirmed = False
                        record.cleanup_harness = None
                    self._persist_acp_binding(record)
                self._emit(record, "session.started", "runtime-adapter", {"run_id": run.run_id})
            except BaseException:
                record.active_run = None
                record.status = SessionStatus.FAILED
                if first_lazy_prestart_binding:
                    record.cleanup_harness = record.harness
                    record.cleanup_unconfirmed = True
                    try:
                        self._persist_acp_binding(record)
                    except BaseException:
                        pass
                if idempotency_key:
                    record.prompt_idempotency.pop(idempotency_key, None)
                self._close_continuation_proxy(record, record.runtime_generation, record.harness)
                raise

            # Capture the execution owner while admission is still locked.
            # A worker may be scheduled only after cancellation and resume.
            prompt_harness = record.harness
            prompt_runtime_session_id = record.runtime_session_id
            prompt_generation = record.runtime_generation
            prompt_executor_epoch = record.executor_epoch
        worker = threading.Thread(
            target=self._run_prompt,
            args=(record, run, effective_content, prompt_harness, prompt_runtime_session_id,
                  prompt_generation, prompt_executor_epoch),
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
                self._close_continuation_proxy(record, prompt_generation, prompt_harness)
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
            return {"schema_version": "prompt-receipt.v1", "state": "outcome_unknown"}
        with record.lock:
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
        generation_id: str = "", executor_epoch: int = 0,
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
                    read_request_guard(record.budget_journal, record.continuation_budget)
            try:
                finish_reason = self._compatibility.run_prepared_prompt(
                    prepared, content,
                    lambda notification: self._on_notification(record, notification,
                        source_run=run, source_runtime_session_id=runtime_session_id),
                )
            finally:
                try:
                    if self._root_scoped and not self._acp:
                        with record.lock:
                            if record.harness is harness and not record.process_closing and not record.process_closed:
                                record.process_closing = True
                                self._compatibility.close(harness)
                                record.process_closed = True
                                record.process_closing = False
                finally:
                    self._close_continuation_proxy(record, generation_id, harness)
        except Exception as exc:
            with record.lock:
                if record.active_run is not run:
                    return
                if self._terminal_fenced(record, generation_id, executor_epoch):
                    # A newer generation owns this session; this late failure must
                    # not overwrite its state or emit a stale terminal.
                    record.active_run = None
                    run.watchdog_stop.set()
                    return
                if self._root_scoped and not self._acp and not record.process_closed and not record.process_closing:
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
                self._close_continuation_proxy(record, generation_id, harness)
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
                self._close_generation(record, generation_id, "failed")
            return

        with record.lock:
            if record.active_run is not run:
                return
            if self._terminal_fenced(record, generation_id, executor_epoch):
                # ADR-0084: never let a late success from a replaced generation
                # settle completed over a newer generation's authoritative state.
                record.active_run = None
                run.watchdog_stop.set()
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
                    tool_receipt = read_request_guard(
                        record.budget_journal, record.continuation_budget, terminal=True)
                    gate = record.continuation_request_gate
                    if gate is None:
                        raise ValueError('continuation provider gate is missing')
                    usage = gate.request_usage(tool_calls=tool_receipt['tool_calls'])
                    budget_blocked = bool(
                        tool_receipt['blocked_reason'] or gate.has_blocked_request()
                        or exceeded_request_limits(usage)
                    )
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
                # ADR-0085 P0: a failed/budget-exhausted terminal updates the
                # active generation state with the accurate outcome.
                self._close_generation(
                    record, generation_id, "budget_exhausted" if budget_blocked else "failed")
            else:
                record.status = SessionStatus.IDLE
                self._emit(
                    record,
                    "session.result",
                    "runtime-adapter",
                    {"finish_reason": finish_reason, "run_id": run.run_id},
                )
                # The generation is terminal even when ACP remains alive for
                # Gateway's exact Backend receipt. That receipt path closes
                # ACP outside this worker before another root is admitted.
                if self._root_scoped:
                    self._close_generation(record, generation_id, "completed")

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
                cancelled_harness = record.harness
                cancelled_native_session = record.runtime_session_id
            else:
                run.hard_cancelled = True
                run.watchdog_stop.set()
                # Gateway projects a hard cancel as a public conversation end.
                # Persist that decision with the exact terminal ACK; an idle
                # release intent must never reopen this conversation.
                record.conversation_ended = True
                record.interrupted_run_id = run.run_id
                record.status = SessionStatus.INTERRUPTED
                # The owned process is closed synchronously below. Detach the
                # run now so no post-close result can be accepted or emitted.
                record.active_run = None
                record.process_closing = True
                if record.current_generation is not None:
                    record.current_generation.close_attempt_in_progress = True
                    record.current_generation.close_attempt_event.clear()
                cancelled_harness = record.harness
                cancelled_generation = record.runtime_generation
            cancellation = {"mode": mode, "persistence": "dsh-owned", "run_id": run.run_id}
            if mode == "hard":
                cancellation["resume"] = "new-agent-session-after-interrupted"
            else:
                cancellation["resume"] = "same-session-after-soft-cancel"
            self._emit(record, "session.cancelled", "runtime-adapter", cancellation)
            if mode == "hard":
                # ADR-0085 P0: an interrupted terminal closes the generation.
                self._close_generation(record, record.runtime_generation, "interrupted")
        if mode == "soft" and self._acp:
            self._compatibility.cancel_session(cancelled_harness, cancelled_native_session)
        if mode == "hard":
            # Interrupt any active upstream read before waiting for DSH process
            # teardown; both resources are dedicated to this one request.
            self._close_continuation_proxy(record, cancelled_generation, cancelled_harness)
            try:
                self._compatibility.close(cancelled_harness)
                with record.lock:
                    record.process_closing = False
                    record.process_closed = True
                    if record.current_generation is not None:
                        record.current_generation.process_exit_confirmed = True
                        record.current_generation.close_attempt_in_progress = False
                        record.current_generation.close_attempt_event.set()
            except Exception:
                with record.lock:
                    record.process_closing = True
                    record.process_closed = False
                    if record.current_generation is not None:
                        record.current_generation.process_exit_confirmed = False
                        record.current_generation.close_attempt_in_progress = False
                        record.current_generation.close_attempt_event.set()
                raise
            finally:
                self._close_continuation_proxy(record, cancelled_generation, cancelled_harness)
        return self.describe_session(record)

    def domain_call_evidence(self, context: dict, after_sequence: int = 0) -> dict:
        """Private bounded control evidence, never a public trace/replay source."""
        self._validate_evidence_context(context)
        if type(after_sequence) is not int or not 0 <= after_sequence < 2**63:
            raise ValueError("invalid private evidence cursor")
        try:
            record = self._get(context["session_id"])
        except KeyError as exc:
            key = (context["session_id"], self.boot_id)
            with self._lock:
                released = self._released_domain_sessions.get(key)
                if released is not None:
                    self._released_domain_sessions.move_to_end(key)
            if released is None or released["boot_id"] != self.boot_id:
                raise ValueError("private evidence session is not live") from exc
            expected_context = (
                context["session_id"], context["trace_id"], context["owner"], context["workspace_id"])
            if released["context"] != expected_context:
                raise ValueError("private evidence context mismatch")
            if after_sequence != released["drained_sequence"]:
                raise ValueError("private evidence cursor is not the final drained sequence")
            return {"schema_version": "domain-call-page.v1", "events": [], "more": False, "idle": True}
        with record.lock:
            if self._ack_context(record) != (context["session_id"], context["trace_id"],
                                             context["owner"], context["workspace_id"]):
                raise ValueError("private evidence context mismatch")
            rows = record.domain_call_evidence[after_sequence:after_sequence + 256]
            more = len(record.domain_call_evidence) > after_sequence + len(rows)
            idle = record.active_run is None
            page = {"schema_version": "domain-call-page.v1", "events": [dict(row) for row in rows],
                    "more": more, "idle": idle}
        return page

    def acknowledge_domain_call_evidence(self, context: dict, receipt: object) -> dict:
        """Acknowledge one exact private domain-call row after Backend acceptance."""
        self._validate_evidence_context(context)
        if not isinstance(receipt, dict) or set(receipt) != {
                "schema_version", "sequence", "root_run_id", "event_sha256"}:
            raise SessionConflict("private evidence receipt shape mismatch")
        ack_context = (context["session_id"], context["trace_id"], context["owner"], context["workspace_id"])
        try:
            record = self._get(context["session_id"])
        except KeyError:
            return self._retry_ack("domain-call", context["session_id"], receipt, ack_context)
        with record.lock:
            if self._ack_context(record) != ack_context:
                raise SessionConflict("private evidence acknowledgement context mismatch")
            sequence = receipt.get("sequence")
            if type(sequence) is not int or not 1 <= sequence <= record.domain_call_sequence:
                raise SessionConflict("private evidence receipt sequence is unknown")
            event = record.domain_call_evidence[sequence - 1]
            try:
                expected = call_evidence_receipt(event)
            except (TypeError, ValueError) as exc:
                raise SessionConflict("private evidence row is invalid") from exc
            if expected != receipt:
                raise SessionConflict("private evidence receipt does not match the observed row")
            if sequence <= record.domain_call_drained_sequence:
                # Exact retries are harmless while another terminal or later
                # private row still pins this boot's session evidence.
                return {"receipt": dict(expected)}
            if sequence != record.domain_call_drained_sequence + 1:
                raise SessionConflict("private evidence receipts must be acknowledged in sequence")
            record.domain_call_drained_sequence = sequence
            self._remember_ack("domain-call", record, expected)
            if self._acp:
                self._persist_acp_binding(record)
            acknowledged = {"receipt": dict(expected)}
        self._maybe_reap_released(record)
        return acknowledged

    def acknowledge_terminal(self, session_id: str, receipt: object) -> dict:
        """Private Gateway acknowledgement of an exact Backend terminal receipt.

        This opens no domain capability: it permits the next root only after
        the previous BYQ root has been closed by Backend. Its retry receipt is
        bounded to the same Adapter boot.
        """
        try:
            record = self._get(session_id)
        except KeyError:
            validate_identifier(session_id, field="session_id")
            return self._retry_ack("terminal", session_id, receipt)
        with record.lock:
            root = receipt.get("root_run_id") if isinstance(receipt, dict) else None
            if (not isinstance(root, str) or type(receipt.get("sequence")) is not int
                    or record.terminal_receipts.get(root) != receipt):
                raise SessionConflict("terminal receipt does not match this runtime turn")
            evidence = self._terminal_evidence_for(record, root)
            current_root = record.process_root_id
            if self._acp and root == current_root:
                record.settlement_receipt = dict(receipt)
                # Persist the exact Backend result before ACP teardown. Keep
                # the root admission fence asserted until process exit is
                # confirmed below; retries can safely resume this sequence.
                self._persist_acp_binding(record)
                if self._acp_product_slots:
                    self._compatibility.acknowledge_slot(record.harness)
            else:
                record.pending_terminal_receipts.discard(root)
                self._remember_ack("terminal", record, receipt, terminal_evidence=evidence)
            acknowledged = {"receipt": dict(receipt)}
        if self._acp and root == current_root:
            self._close_acp_after_terminal_ack(record, root, receipt)
            with record.lock:
                record.pending_terminal_receipts.discard(root)
                self._remember_ack("terminal", record, receipt, terminal_evidence=evidence)
                record.reuse_native_session_ready = self._acp_native_reuse_is_proven(
                    record, root, receipt,
                )
                # Close proof may have been unavailable for an interrupted or
                # failed process, but the exact Backend receipt is still
                # durably acknowledged after process cleanup completes.
                try:
                    self._persist_acp_binding(record)
                except Exception:
                    record.reuse_native_session_ready = False
        self._maybe_reap_released(record)
        return acknowledged

    def _acp_native_reuse_is_proven(
        self, record: RuntimeSession, root_run_id: str, receipt: object,
    ) -> bool:
        """Require terminal ACK, close/drain proof and known completion to reuse."""

        generation = record.current_generation
        if (generation is None or generation.process_root_id != root_run_id
                or record.settlement_receipt != receipt
                or record.terminal_receipts.get(root_run_id) != receipt
                or record.pending_terminal_receipts
                or not generation.native_session_close_confirmed
                or not generation.process_closed or not generation.process_exit_confirmed
                or generation.process_closing or not generation.continuation_proxy_closed
                or record.status != SessionStatus.IDLE
                or record.release_finalized or not record.recovery_cwd
                or record.domain_call_drained_sequence != record.domain_call_sequence):
            return False
        terminal_success = any(
            event.get("kind") == "session.result"
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("run_id") == root_run_id
            for event in record.history
        )
        cancelled = any(
            event.get("kind") in {"session.cancelled", "session.result.discarded"}
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("run_id") == root_run_id
            for event in record.history
        )
        if not terminal_success or cancelled:
            return False
        if generation.continuation_budget is not None:
            budget_receipt = self._budget_receipt(record)
            if (budget_receipt.get("status") != "settled"
                    or budget_receipt.get("outcome") != "completed"
                    or budget_receipt.get("run_id") != root_run_id):
                return False
        return True

    def _close_acp_after_terminal_ack(
        self, record: RuntimeSession, root_run_id: str, receipt: object,
    ) -> None:
        """Close the exact ACP root only after its Backend terminal receipt.

        The Gateway waits for this bounded close path before accepting a new
        user turn. The DSH request may drain or callback while close runs, so
        no RuntimeSession lock is held across ACP RPC or process teardown.
        """

        deadline = time.monotonic() + 68.0
        while True:
            with record.lock:
                generation = record.current_generation
                if generation is None or generation.process_root_id != root_run_id:
                    raise SessionConflict("ACP root binding changed before terminal close")
                if record.settlement_receipt != receipt:
                    raise SessionConflict("ACP terminal settlement receipt changed before close")
                if generation.process_closed and not generation.process_closing:
                    if generation.process_exit_confirmed:
                        return
                    raise SessionConflict("prior ACP process exit is not confirmed")
                if generation.close_attempt_in_progress:
                    wait_for = generation.close_attempt_event
                    owns_attempt = False
                else:
                    generation.close_attempt_in_progress = True
                    generation.close_attempt_event.clear()
                    generation.process_closing = True
                    harness = generation.harness
                    native_session_id = generation.native_session_id
                    native_closed = generation.native_session_close_confirmed
                    owns_attempt = True
            if not owns_attempt:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not wait_for.wait(remaining):
                    raise SessionConflict("ACP root close is still in progress")
                continue

            close_error = None
            if harness is None:
                close_error = SessionConflict("ACP root process is unavailable for close")
            else:
                if not native_closed:
                    try:
                        self._compatibility.close_session(harness, native_session_id)
                    except Exception:
                        # A failed/ambiguous session-close response cannot
                        # prove that DSH closed its native conversation. Kill
                        # the dedicated process below and use a fresh native
                        # session on the next root.
                        native_closed = False
                    else:
                        native_closed = True
                try:
                    # DshAcpCompatibility.close returns only after poll()
                    # confirms process exit; a mere close call is insufficient
                    # evidence for reuse.
                    self._compatibility.close(harness)
                except Exception as exc:
                    close_error = exc

            with record.lock:
                current = record.current_generation
                if current is not generation:
                    generation.close_attempt_in_progress = False
                    generation.close_attempt_event.set()
                    raise SessionConflict("ACP generation changed before prior process exit was confirmed")
                generation.native_session_close_confirmed = native_closed
                generation.close_attempt_in_progress = False
                generation.close_attempt_event.set()
                if close_error is not None:
                    # Keep process_closing asserted. An exact receipt retry
                    # may retry cleanup, but no new root can pass the gate.
                    generation.process_closed = False
                    generation.process_closing = True
                    record.reuse_native_session_ready = False
                else:
                    generation.process_closed = True
                    generation.process_exit_confirmed = True
                    generation.process_closing = False
                    generation.process_exit_confirmed = True
                    # Exact ACK is being processed by the caller; budget
                    # settlement cannot be proven until its pending marker is
                    # cleared there. Reuse is decided only after that step.
                    record.reuse_native_session_ready = False
                try:
                    self._persist_acp_binding(record)
                except Exception:
                    # The pre-close exact ACK binding remains durable. Without
                    # durable close proof, keep this boot safe by disabling
                    # reuse; fresh-native recovery is the fallback.
                    record.reuse_native_session_ready = False
            if close_error is not None:
                raise SessionConflict("ACP root process exit could not be confirmed") from None
            return

    def terminal_evidence(self, session_id: str, root_run_id: str, boot_id: str) -> dict:
        """Return the exact observed terminal and its stored receipt for Gateway."""

        if re.fullmatch(r"[0-9a-f]{32}", boot_id) is None:
            raise SessionConflict("terminal evidence boot identity is invalid")
        if re.fullmatch(r"[0-9a-f]{32}", root_run_id) is None:
            raise SessionConflict("terminal evidence root identity is invalid")
        if boot_id != self.boot_id:
            raise SessionConflict("terminal evidence belongs to another Adapter boot")
        with self._lock:
            record = self._sessions.get(session_id)
            records = list(self._sessions.items())
            tombstones = list(self._ack_tombstones.items())
        for other_session_id, other in records:
            if other_session_id == session_id:
                continue
            with other.lock:
                active_root = other.active_run.run_id if other.active_run is not None else None
                if root_run_id in other.terminal_receipts or active_root == root_run_id:
                    raise SessionConflict("terminal root belongs to another session")
        if record is None:
            matching: dict[str, Any] | None = None
            matching_key: tuple[str, str, str, str, int] | None = None
            for key, entry in tombstones:
                kind, candidate_session, candidate_boot, candidate_root, _sequence = key
                if (kind != "terminal" or candidate_boot != boot_id or candidate_root != root_run_id
                        or entry.get("terminal_evidence") is None):
                    continue
                if candidate_session != session_id:
                    raise SessionConflict("terminal root belongs to another session")
                matching, matching_key = entry, key
            if matching is not None and matching_key is not None:
                evidence = matching["terminal_evidence"]
                receipt = matching["receipt"]
                if (matching["boot_id"] != boot_id or evidence["session_id"] != session_id
                        or evidence["boot_id"] != boot_id or evidence["root_run_id"] != root_run_id
                        or evidence["receipt"] != receipt or receipt.get("root_run_id") != root_run_id
                        or receipt.get("sequence") != evidence["sequence"]
                        or matching_key[-1] != evidence["sequence"]):
                    raise SessionConflict("stored terminal evidence identity mismatch")
                with self._lock:
                    self._ack_tombstones.move_to_end(matching_key)
                return {**evidence, "receipt": dict(receipt)}
            raise KeyError(f"terminal evidence unavailable for {session_id}")
        with record.lock:
            if record.boot_id != boot_id:
                raise SessionConflict("terminal evidence belongs to another Adapter boot")
            return self._terminal_evidence_for(record, root_run_id)

    @staticmethod
    def _terminal_evidence_for(record: RuntimeSession, root_run_id: str) -> dict[str, Any]:
        receipt = record.terminal_receipts.get(root_run_id)
        if receipt is None:
            raise KeyError(root_run_id)
        terminal = None
        for event in reversed(record.history):
            projected = project_lifecycle_event(event, record.session_id, record.trace_id)
            if (projected is not None and projected["root_run_id"] == root_run_id
                    and projected["outcome"] != "active"):
                terminal = projected
                break
        if terminal is None or lifecycle_receipt(terminal) != receipt:
            raise SessionConflict("stored terminal receipt has no matching terminal event")
        return {
            "schema_version": "byq-runtime-terminal-evidence.v1",
            "session_id": record.session_id,
            "boot_id": record.boot_id,
            "root_run_id": root_run_id,
            "sequence": terminal["sequence"],
            "outcome": terminal["outcome"],
            "receipt": dict(receipt),
        }

    def resume_session(
        self, session_id: str, *, conversation_context: object = None,
    ) -> dict[str, Any]:
        record = self._get(session_id)
        context = normalize_conversation_context([] if conversation_context is None else conversation_context)
        with record.lock:
            if record.cleanup_unconfirmed:
                raise SessionConflict("previous ACP root startup cleanup is unconfirmed")
            if record.process_closing:
                raise SessionConflict("previous runtime process cleanup is not complete")
            if (record.status == SessionStatus.READY and record.active_run is None
                    and record.current_generation is not None and record.harness is not None):
                # Path A: the original in-process runtime generation is still
                # alive and is reused. Never manufacture a reattach when the
                # harness is gone.
                record.pending_conversation_context = context
                record.continuity = continuity.REATTACHED
                return {**self.describe_session(record), "resumed_from_run_id": None}
            if record.status == SessionStatus.INTERRUPTED or (
                record.status == SessionStatus.FAILED and record.interrupted_run_id is not None
            ):
                raise SessionConflict(SESSION_LOST_DETAIL)
            if record.status == SessionStatus.FAILED:
                raise SessionConflict(SESSION_FAILED_DETAIL)
            if (record.status == SessionStatus.READY
                    and (record.current_generation is None or record.harness is None)):
                raise SessionConflict(SESSION_LOST_DETAIL)
            raise SessionConflict(f"session {session_id} cannot be resumed")

    def release_session(
        self, session_id: str, *, preserve_conversation: bool = False,
    ) -> dict[str, Any]:
        record = self._get(session_id)
        with record.lock:
            # Creation/resumption publishes the record before SDK initialize
            # completes outside this lock. Releasing it in that interval would
            # detach the process that the initializer is still acquiring.
            if record.status == SessionStatus.STARTING:
                raise SessionConflict(f"session {session_id} is still initializing")
            if record.process_closing or record.active_run is not None or record.status in SessionStatus.ACTIVE_PROMPT:
                raise SessionConflict(f"session {session_id} has an active prompt")
            if self._acp and record.pending_terminal_receipts:
                raise SessionConflict("Backend terminal receipt must be acknowledged before ACP release")
            if record.cleanup_unconfirmed:
                raise SessionConflict("previous ACP root startup cleanup is unconfirmed")
            if record.conversation_ended and preserve_conversation:
                raise SessionConflict("BYQ session was ended")
            if record.continuation_budget:
                self._budget_receipt(record)
            if not preserve_conversation:
                record.conversation_ended = True
            record.status = SessionStatus.CLOSED
        try:
            with record.lock:
                self._emit(record, "session.closed", "runtime-adapter", {"reason": "released"})
                if self._acp and record.authority_epoch is not None:
                    self._persist_acp_binding(record)
        finally:
            try:
                if record.harness is not None:
                    self._compatibility.close(record.harness)
            finally:
                self._close_continuation_proxy(record, record.runtime_generation, record.harness)
                with record.lock:
                    for subscriber in list(record.subscribers):
                        subscriber.put(None)
                    record.release_finalized = True
                self._maybe_reap_released(record)
        return self.describe_session(record)

    def _maybe_reap_released(self, record: RuntimeSession) -> bool:
        """Keep private evidence through this boot for lost ACK-response retries."""

        with record.lock:
            if (record.status != SessionStatus.CLOSED or not record.release_finalized
                    or record.pending_terminal_receipts
                    or record.domain_call_drained_sequence != record.domain_call_sequence):
                return False
        with self._lock:
            if self._sessions.get(record.session_id) is not record:
                return False
            key = (record.session_id, record.boot_id)
            self._released_domain_sessions[key] = {
                "boot_id": record.boot_id,
                "context": self._ack_context(record),
                "drained_sequence": record.domain_call_drained_sequence,
            }
            self._released_domain_sessions.move_to_end(key)
            while len(self._released_domain_sessions) > _ACK_TOMBSTONE_LIMIT:
                self._released_domain_sessions.popitem(last=False)
            del self._sessions[record.session_id]
        return True

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
                "boot_id": record.boot_id,
                "status": record.status,
                "active_prompt": record.active_run is not None,
                "process_ownership": "dedicated",
                "persistence": "dsh-owned",
                "owner_context": "configured" if record.owner_principal else "missing",
                # ADR-0079 R2: report how continuity was established without
                # exposing the ephemeral generation/native process identity.
                "continuity": record.continuity,
            }

    def _acp_binding_path(self, session_id: str, workspace_id: str | None = None) -> Path:
        validate_identifier(session_id, field="session_id")
        # ADR-0100: each group's durable recovery bindings live inside that
        # group's own mounted session volume. The Adapter only mounts the
        # authenticated Workspace subtree, so a shared parent directory is
        # neither writable nor persistent.
        if not self._acp_product_slots:
            directory = contained_session_path(self._session_root, "byq-acp-bindings")
            return directory / f"{session_id}.json"
        configured = self._compatibility.product_slots.configured_workspaces()
        if workspace_id is not None:
            base = self._compatibility.session_storage_root(self._session_root, workspace_id)
            return contained_session_path(base, "byq-acp-bindings") / f"{session_id}.json"
        # Recovery reads do not carry a workspace before the binding is opened.
        # The exact session file name is unique per group, so search the
        # statically configured groups and fail closed if the identity is not
        # unique or cannot be resolved.
        found = [
            contained_session_path(
                self._compatibility.session_storage_root(self._session_root, candidate),
                "byq-acp-bindings") / f"{session_id}.json"
            for candidate in configured
        ]
        existing = [path for path in found if path.exists()]
        if len(existing) > 1:
            raise SessionConflict("ACP recovery binding is ambiguous across groups")
        if existing:
            return existing[0]
        if len(configured) != 1:
            raise SessionConflict("ACP recovery binding workspace is ambiguous")
        return found[0]

    def _persist_acp_binding(self, record: RuntimeSession) -> str | None:
        """Store the exact root/native binding; return its persisted payload digest."""

        if not self._acp:
            return
        root = record.process_root_id
        if re.fullmatch(r"[0-9a-f]{32}", root) is None or record.authority_epoch is None:
            raise SessionConflict("ACP recovery binding has no exact root authority")
        cwd = record.recovery_cwd
        if not cwd or not Path(cwd).resolve().is_relative_to(self._session_root):
            raise SessionConflict("ACP recovery working directory is not contained")
        value = {
            "schema_version": "byq-acp-root-binding.v1",
            "session_id": record.session_id,
            "trace_id": record.trace_id,
            "owner_principal": record.owner_principal,
            "workspace_id": record.workspace_id,
            "root_run_id": root,
            "native_session_id": record.runtime_session_id,
            "runtime_generation": record.runtime_generation,
            "model_provider": str(record.model_resolution.get("provider") or self._provider),
            "model_id": str(record.model_resolution.get("model") or self._model),
            "cwd": str(Path(cwd).resolve()),
            "previous_boot_id": record.boot_id,
            "previous_authority_epoch": record.authority_epoch,
            "sequence": record.sequence,
            "settlement_receipt": record.settlement_receipt,
            "domain_call_sequence": record.domain_call_sequence,
            "domain_call_drained_sequence": record.domain_call_drained_sequence,
            "native_session_close_confirmed": bool(
                record.current_generation and record.current_generation.native_session_close_confirmed),
            "process_exit_confirmed": bool(
                record.current_generation and record.current_generation.process_exit_confirmed),
            "cleanup_unconfirmed": record.cleanup_unconfirmed,
            "closed": record.conversation_ended,
        }
        path = self._acp_binding_path(record.session_id, record.workspace_id)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        lock_path = path.with_suffix(".lock")
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            # A superseded Adapter boot must never overwrite the new boot's
            # native/root binding after Backend authority rotation.
            if self.require_current_backend_authority() != record.authority_epoch:
                raise SessionConflict("ACP binding writer lost Backend authority")
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".binding-", delete=False) as stream:
                    temporary = Path(stream.name)
                    os.chmod(temporary, 0o600)
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        return hashlib.sha256(payload).hexdigest()

    def _remove_prestart_acp_binding(
        self, record: RuntimeSession, *, expected_sha256: str,
    ) -> None:
        """Remove only this exact first-root fence after proven no-START."""

        if (not self._acp_product_slots
                or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
                or record.authority_epoch is None
                or record.process_used or record.active_run is not None
                or not record.cleanup_unconfirmed or record.cleanup_harness is not record.harness
                or record.terminal_receipts or record.pending_terminal_receipts
                or record.settlement_receipt is not None or record.conversation_ended):
            raise SessionConflict("ACP prepared root binding is not removable")
        path = self._acp_binding_path(record.session_id, record.workspace_id)
        lock_path = path.with_suffix(".lock")
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT
                          | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            if self.require_current_backend_authority() != record.authority_epoch:
                raise SessionConflict("ACP prepared binding writer lost Backend authority")
            try:
                before = os.lstat(path)
            except OSError:
                raise SessionConflict("ACP prepared root binding is unavailable") from None
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                    or before.st_gid != os.getgid() or stat.S_IMODE(before.st_mode) != 0o600
                    or before.st_nlink != 1):
                raise SessionConflict("ACP prepared root binding is unsafe")
            try:
                binding_fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    opened = os.fstat(binding_fd)
                    if (not stat.S_ISREG(opened.st_mode) or opened.st_dev != before.st_dev
                            or opened.st_ino != before.st_ino or opened.st_nlink != 1
                            or opened.st_uid != os.getuid() or opened.st_gid != os.getgid()
                            or stat.S_IMODE(opened.st_mode) != 0o600):
                        raise SessionConflict("ACP prepared root binding is unsafe")
                    chunks = bytearray()
                    while len(chunks) <= 1024 * 1024:
                        chunk = os.read(binding_fd, min(65536, 1024 * 1024 + 1 - len(chunks)))
                        if not chunk:
                            break
                        chunks.extend(chunk)
                    if len(chunks) != before.st_size or len(chunks) > 1024 * 1024:
                        raise SessionConflict("ACP prepared root binding is unsafe")
                finally:
                    os.close(binding_fd)
            except OSError:
                raise SessionConflict("ACP prepared root binding is unavailable") from None
            raw = bytes(chunks)
            if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_sha256):
                raise SessionConflict("ACP prepared root binding changed")
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeError, ValueError):
                raise SessionConflict("ACP prepared root binding is invalid") from None
            if (not isinstance(value, dict)
                    or value.get("schema_version") != "byq-acp-root-binding.v1"
                    or value.get("session_id") != record.session_id
                    or value.get("trace_id") != record.trace_id
                    or value.get("owner_principal") != record.owner_principal
                    or value.get("workspace_id") != record.workspace_id
                    or value.get("root_run_id") != record.process_root_id
                    or value.get("native_session_id") != record.runtime_session_id
                    or value.get("runtime_generation") != record.runtime_generation
                    or value.get("model_provider") != str(
                        record.model_resolution.get("provider") or self._provider)
                    or value.get("model_id") != str(
                        record.model_resolution.get("model") or self._model)
                    or value.get("cwd") != str(Path(record.recovery_cwd).resolve())
                    or value.get("previous_boot_id") != record.boot_id
                    or value.get("previous_authority_epoch") != record.authority_epoch
                    or value.get("sequence") != record.sequence
                    or value.get("settlement_receipt") is not None
                    or value.get("domain_call_sequence") != record.domain_call_sequence
                    or value.get("domain_call_drained_sequence") != record.domain_call_drained_sequence
                    or value.get("native_session_close_confirmed") is not False
                    or value.get("process_exit_confirmed") is not False
                    or value.get("cleanup_unconfirmed") is not True
                    or value.get("closed") is not False):
                raise SessionConflict("ACP prepared root binding is not an empty pre-START fence")
            after = os.lstat(path)
            if (after.st_dev != before.st_dev or after.st_ino != before.st_ino
                    or after.st_nlink != 1 or after.st_size != before.st_size):
                raise SessionConflict("ACP prepared root binding changed")
            if self.require_current_backend_authority() != record.authority_epoch:
                raise SessionConflict("ACP prepared binding writer lost Backend authority")
            os.unlink(path)
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            try:
                os.lstat(path)
            except FileNotFoundError:
                return
            raise SessionConflict("ACP prepared root binding was not removed")
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def _read_acp_binding(self, session_id: str) -> dict[str, Any]:
        if not self._acp:
            raise KeyError(session_id)
        path = self._acp_binding_path(session_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise KeyError(session_id) from exc
        # Additive v1 compatibility: older bindings omit close proofs and are
        # always treated as non-reusable. A process restart never transfers the
        # in-memory normal-completion reuse gate.
        if isinstance(value, dict):
            value.setdefault("native_session_close_confirmed", False)
            value.setdefault("process_exit_confirmed", False)
            value.setdefault("cleanup_unconfirmed", False)
        if (not isinstance(value, dict)
                or set(value) != {"schema_version", "session_id", "trace_id", "owner_principal",
                                      "workspace_id", "root_run_id", "native_session_id",
                                      "runtime_generation", "model_provider", "model_id", "cwd",
                                      "previous_boot_id", "previous_authority_epoch", "sequence",
                                      "settlement_receipt", "domain_call_sequence",
                                      "domain_call_drained_sequence", "native_session_close_confirmed",
                                      "process_exit_confirmed", "cleanup_unconfirmed", "closed"}
                or value["schema_version"] != "byq-acp-root-binding.v1"
                or value["session_id"] != session_id
                or re.fullmatch(r"[0-9a-f]{32}", str(value["root_run_id"])) is None
                or re.fullmatch(r"[0-9a-f]{32}", str(value["previous_boot_id"])) is None
                or type(value["previous_authority_epoch"]) is not int
                or type(value["sequence"]) is not int
                or type(value["domain_call_sequence"]) is not int
                or type(value["domain_call_drained_sequence"]) is not int
                or not 0 <= value["domain_call_drained_sequence"] <= value["domain_call_sequence"]
                or type(value["native_session_close_confirmed"]) is not bool
                or type(value["process_exit_confirmed"]) is not bool
                or type(value["cleanup_unconfirmed"]) is not bool
                or type(value["closed"]) is not bool):
            raise SessionConflict("ACP recovery binding is invalid")
        cwd = Path(value["cwd"])
        if not cwd.is_absolute() or cwd.resolve() != cwd or not cwd.is_relative_to(self._session_root):
            raise SessionConflict("ACP recovery working directory is invalid")
        if self._acp_product_slots:
            if not cwd.is_relative_to(
                    self._compatibility.session_storage_root(self._session_root, value["workspace_id"])):
                raise SessionConflict("ACP recovery working directory belongs to another resource group")
            # The binding must live in the resource group it declares; a file
            # found under a different group's volume is not proof of authority.
            if path != self._acp_binding_path(session_id, value["workspace_id"]):
                raise SessionConflict("ACP recovery binding is not in its declared resource group")
        return value

    def recovery_binding(self, session_id: str) -> dict[str, Any]:
        binding = self._read_acp_binding(session_id)
        if binding["closed"]:
            raise SessionConflict("BYQ session was ended")
        if binding["cleanup_unconfirmed"]:
            raise SessionConflict("ACP recovery is blocked by unconfirmed process cleanup")
        if not binding["process_exit_confirmed"]:
            raise SessionConflict("ACP recovery is blocked until prior process exit is confirmed")
        public = {key: binding[key] for key in (
            "session_id", "trace_id", "owner_principal", "workspace_id", "root_run_id",
            "previous_boot_id", "previous_authority_epoch", "sequence")}
        settled = binding["settlement_receipt"] is not None
        return {"schema_version": "byq-runtime-recovery-binding.v1",
                "state": "settled" if settled else "transfer_required",
                **public,
                **({"settlement_receipt": binding["settlement_receipt"]} if settled else {})}

    def recover_acp_session(self, session_id: str, receipt: object,
                            initial_sequence: int) -> dict[str, Any]:
        """Reattach one exact root after Backend transfer, without prompt replay."""

        with self._lock:
            existing = self._sessions.get(session_id)
        if existing is not None:
            with existing.lock:
                exact_root = receipt.get("root_run_id") if isinstance(receipt, dict) else None
                if (existing.boot_id != self.boot_id or exact_root != existing.process_root_id
                        or (receipt != existing.settlement_receipt
                            and not (existing.interrupted_run_id == exact_root
                                     and receipt.get("boot_id") == self.boot_id))):
                    raise SessionConflict("ACP recovery retry does not match the live binding")
                return {**self.describe_session(existing),
                        "resumed_from_run_id": existing.interrupted_run_id}
        binding = self._read_acp_binding(session_id)
        if binding["closed"]:
            raise SessionConflict("BYQ session was ended")
        if binding["cleanup_unconfirmed"]:
            raise SessionConflict("ACP recovery is blocked by unconfirmed process cleanup")
        if (type(initial_sequence) is not int or initial_sequence < binding["sequence"]
                or initial_sequence >= 2**63):
            raise SessionConflict("recovery event sequence is not proven")
        if binding["domain_call_sequence"] != binding["domain_call_drained_sequence"]:
            raise SessionConflict("undrained domain-call evidence blocks recovery")
        persisted_settled = binding["settlement_receipt"] is not None
        if persisted_settled:
            if receipt != binding["settlement_receipt"]:
                raise SessionConflict("settled root receipt mismatch")
            if not binding["process_exit_confirmed"]:
                raise SessionConflict("settled ACP binding has no confirmed prior process exit")
        elif (isinstance(receipt, dict)
              and set(receipt) == {"schema_version", "root_run_id", "sequence", "event_sha256"}
              and receipt.get("schema_version") == "agent-run-lifecycle-receipt.v1"
              and receipt.get("root_run_id") == binding["root_run_id"]
              and type(receipt.get("sequence")) is int and receipt["sequence"] > 0
              and isinstance(receipt.get("event_sha256"), str)
              and re.fullmatch(r"[0-9a-f]{64}", receipt["event_sha256"])):
            if not binding["process_exit_confirmed"]:
                raise SessionConflict("Backend-closed ACP binding has no confirmed prior process exit")
            # Gateway proved Backend closed this root just before the old
            # Adapter could persist its terminal ACK. Reattach the public
            # session without replaying the ACP prompt or transferring a
            # root that Backend already closed.
            pass
        else:
            expected = {
                "schema_version": "byq-runtime-root-authority-transfer-receipt.v1",
                "root_run_id": binding["root_run_id"],
                "previous_boot_id": binding["previous_boot_id"],
                "previous_authority_epoch": binding["previous_authority_epoch"],
                "boot_id": self.boot_id,
                "authority_epoch": self.require_current_backend_authority(),
                "status": "transferred",
            }
            if receipt != expected:
                raise SessionConflict("Backend root transfer receipt mismatch")
            if not binding["process_exit_confirmed"]:
                # The transfer receipt fences the old root's Backend authority,
                # but does not prove its ACP process stopped. Do not publish a
                # reattached session while that old process may still emit late
                # requests; a repair process cannot provide this old-boot proof.
                raise SessionConflict("transferred ACP binding has no confirmed prior process exit")
        settled = persisted_settled or receipt.get("schema_version") == "agent-run-lifecycle-receipt.v1"
        model_resolution = self._resolve_model(
            owner_principal=binding["owner_principal"],
            session_id=session_id, trace_id=binding["trace_id"],
        )
        if (str(model_resolution.get("provider") or self._provider) != binding["model_provider"]
                or str(model_resolution.get("model") or self._model) != binding["model_id"]):
            raise SessionConflict("recovered root model route changed")
        with self._lock:
            if session_id in self._sessions:
                raise SessionConflict("BYQ session already exists in this Adapter boot")
        record = RuntimeSession(
            session_id=session_id, trace_id=binding["trace_id"], boot_id=self.boot_id,
            owner_principal=binding["owner_principal"], workspace_id=binding["workspace_id"],
            model_resolution=model_resolution, status=SessionStatus.IDLE,
            sequence=initial_sequence, continuity=continuity.REATTACHED,
            authority_epoch=self.require_current_backend_authority(),
            recovery_cwd=binding["cwd"], settlement_receipt=dict(receipt) if settled else None,
            domain_call_sequence=binding["domain_call_sequence"],
            domain_call_drained_sequence=binding["domain_call_drained_sequence"],
        )
        self._install_generation(
            record, native_session_id=binding["native_session_id"], executor_epoch=0,
            process_root_id=binding["root_run_id"],
            generation_id=binding["runtime_generation"],
        )
        record.current_generation.native_session_close_confirmed = binding["native_session_close_confirmed"]
        record.current_generation.process_exit_confirmed = binding["process_exit_confirmed"]
        record.process_used = True
        record.process_closed = True
        if not settled:
            cwd = Path(binding["cwd"])
            self._require_group_admission(record, binding["root_run_id"])
            harness = self._build_harness(
                session_id, cwd, trace_id=record.trace_id,
                owner_principal=record.owner_principal, workspace_id=record.workspace_id,
                model_resolution=model_resolution,
                runtime_generation=binding["runtime_generation"],
                root_run_id=binding["root_run_id"],
                native_root_session_id=binding["native_session_id"],
            )
            if self._acp_product_slots:
                # The repair process owns a same-root slot until the eventual
                # exact Backend ACK, even though it closes before publication.
                record.current_generation.harness = harness
            try:
                self._compatibility.start(harness)
                resumed_id = self._compatibility.resume_session(
                    harness, binding["native_session_id"], cwd=cwd)
                if resumed_id != binding["native_session_id"]:
                    raise SessionConflict("ACP resumed another native session")
            finally:
                self._compatibility.close(harness)
                # This confirms only the repair process started above. The
                # old-boot process was independently required to be confirmed
                # exited before entering this branch.
                record.current_generation.process_exit_confirmed = True
        if settled and not persisted_settled:
            with record.lock:
                self._persist_acp_binding(record)
        with self._lock:
            if session_id in self._sessions:
                raise SessionConflict("BYQ session already exists in this Adapter boot")
            self._sessions[session_id] = record
        if not settled:
            # ACP resume repairs its own log but never replays the interrupted
            # prompt. BYQ records an interrupted terminal for the same root;
            # Gateway must close it in Backend and ACK before another input.
            with record.lock:
                record.interrupted_run_id = binding["root_run_id"]
                self._emit(record, "session.failed", "runtime-adapter", {
                    "code": "runtime-interrupted", "retryable": False,
                    "run_id": binding["root_run_id"],
                })
                self._persist_acp_binding(record)
        return {**self.describe_session(record),
                "resumed_from_run_id": None if settled else binding["root_run_id"]}

    def attach_live_session(
        self, session_id: str, trace_id: str, owner_principal: str | None,
        workspace_id: str | None,
    ) -> dict[str, Any]:
        """Attach a Gateway to an existing in-memory Adapter session only."""
        try:
            record = self._get(session_id)
        except KeyError as exc:
            raise SessionConflict(SESSION_LOST_DETAIL) from exc
        with record.lock:
            if (record.trace_id, record.owner_principal, record.workspace_id) != (
                trace_id, owner_principal, workspace_id,
            ):
                raise SessionConflict("live runtime session identity conflicts")
            return self.describe_session(record)

    def close(self) -> None:
        with self._lock:
            records = list(self._sessions.values())
            self._sessions.clear()
        failure = None

        def remember_failure(exc: Exception) -> None:
            nonlocal failure
            if failure is None:
                failure = exc

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
                remember_failure(exc)
            finally:
                try:
                    self._close_continuation_proxy(record, record.runtime_generation, record.harness)
                except Exception as exc:
                    remember_failure(exc)
                seen_harnesses: set[int] = set()
                for harness in (record.harness, record.cleanup_harness):
                    if harness is None or id(harness) in seen_harnesses:
                        continue
                    seen_harnesses.add(id(harness))
                    try:
                        self._compatibility.close(harness)
                    except Exception as exc:
                        remember_failure(exc)
                try:
                    self._close_continuation_proxy(record, record.runtime_generation, record.harness)
                except Exception as exc:
                    remember_failure(exc)
                finally:
                    with record.lock:
                        for subscriber in record.subscribers:
                            subscriber.put(None)
        if failure is not None:
            raise failure

    def _get(self, session_id: str) -> RuntimeSession:
        with self._lock:
            record = self._sessions.get(session_id)
        if record is not None:
            return record
        raise KeyError(f"unknown BYQ session: {session_id}")

    @staticmethod
    def _ack_key(kind: str, session_id: str, boot_id: str, receipt: dict) -> tuple[str, str, str, str, int]:
        root = receipt.get("root_run_id")
        sequence = receipt.get("sequence")
        if not isinstance(root, str) or type(sequence) is not int:
            raise SessionConflict("acknowledgement receipt identity is invalid")
        return kind, session_id, boot_id, root, sequence

    @staticmethod
    def _ack_context(record: RuntimeSession) -> tuple[str, str, str | None, str | None]:
        return record.session_id, record.trace_id, record.owner_principal, record.workspace_id

    @staticmethod
    def _validate_evidence_context(context: object) -> dict[str, str]:
        if not isinstance(context, dict) or set(context) != {"session_id", "trace_id", "owner", "workspace_id"}:
            raise ValueError("invalid private evidence context")
        for name in ("session_id", "trace_id"):
            validate_identifier(context[name], field=name)
        for name in ("owner", "workspace_id"):
            value = context[name]
            if not isinstance(value, str) or not value or value != value.strip() or len(value) > 128:
                raise ValueError("invalid private evidence context")
        return context

    def _remember_ack(
        self, kind: str, record: RuntimeSession, receipt: dict,
        *, terminal_evidence: dict[str, Any] | None = None,
    ) -> None:
        key = self._ack_key(kind, record.session_id, record.boot_id, receipt)
        entry = {
            "boot_id": record.boot_id,
            "context": self._ack_context(record),
            "receipt": dict(receipt),
        }
        if terminal_evidence is not None:
            entry["terminal_evidence"] = {
                **terminal_evidence,
                "receipt": dict(terminal_evidence["receipt"]),
            }
        with self._lock:
            self._ack_tombstones[key] = entry
            self._ack_tombstones.move_to_end(key)
            while len(self._ack_tombstones) > _ACK_TOMBSTONE_LIMIT:
                self._ack_tombstones.popitem(last=False)

    def _retry_ack(self, kind: str, session_id: str, receipt: object,
                   context: tuple[str, str, str | None, str | None] | None = None) -> dict:
        if not isinstance(receipt, dict):
            raise SessionConflict("acknowledgement receipt is invalid")
        key = self._ack_key(kind, session_id, self.boot_id, receipt)
        with self._lock:
            entry = self._ack_tombstones.get(key)
            if entry is None:
                raise SessionConflict("acknowledgement is not owned by this Adapter boot")
            if (entry["boot_id"] != self.boot_id or entry["receipt"] != receipt
                    or (context is not None and entry["context"] != context)):
                raise SessionConflict("acknowledgement receipt context mismatch")
            self._ack_tombstones.move_to_end(key)
            return {"receipt": dict(entry["receipt"])}

    def continuation_qualified(self, record: RuntimeSession) -> bool:
        if (os.environ.get('BYQ_F6_EXECUTOR_ENABLED') != '1' or not self._root_scoped
                or not bool(record.model_resolution.get('api_key'))
                or not _continuation_route_qualified(
                    record.model_resolution, self._provider, self._model)):
            return False
        # ADR-0103: only the fixed ACP family has the root guard and request
        # proxy contract. Keep the existing opt-in and BYQ route/credential gates
        # above; no Python SDK version can qualify this online continuation path.
        return self._compatibility.family == ACP_COMPATIBILITY_FAMILY

    def _close_continuation_proxy(
        self, record: RuntimeSession, generation_id: str, harness: Any,
    ) -> None:
        generation = record.current_generation
        if (generation is None or generation.generation_id != generation_id
                or generation.harness is not harness):
            return
        proxy = generation.continuation_request_proxy
        if proxy is None:
            generation.continuation_proxy_closed = True
            return
        try:
            proxy.close()
        except Exception:
            generation.continuation_proxy_closed = False
        else:
            generation.continuation_proxy_closed = True

    def _budget_receipt(self, record: RuntimeSession) -> dict:
        reservation = record.continuation_budget
        reservation_id = reservation['reservation_id']
        cached = record.budget_receipts.get(reservation_id)
        if cached is not None:
            return cached
        if record.active_run is not None:
            return {'reservation_id': reservation_id, 'status': 'accepted',
                    'run_id': record.budget_run_id}
        if (not record.process_closed or record.process_closing
                or not record.continuation_proxy_closed):
            return {'reservation_id': reservation_id, 'status': 'outcome_unknown'}
        # ADR-0105 §5: an execution receipt may close only when every business
        # call is reconciled and the exact Backend terminal ACK is present. A
        # hard cancel or watchdog can set process_closed without either, so
        # require them explicitly here and stay outcome_unknown otherwise.
        if (record.domain_call_drained_sequence != record.domain_call_sequence
                or record.pending_terminal_receipts
                or (self._acp and (
                    not isinstance(record.settlement_receipt, dict)
                    or record.settlement_receipt.get('root_run_id') != record.budget_run_id))):
            return {'reservation_id': reservation_id, 'status': 'outcome_unknown'}
        # ADR-0105 §5: an unprovable outbound result keeps the execution receipt
        # unresolved; it must never settle as a known outcome.
        if record.continuation_request_gate is not None and record.continuation_request_gate.has_unknown_outcome():
            return {'reservation_id': reservation_id, 'status': 'outcome_unknown'}
        try:
            tool_receipt = read_request_guard(record.budget_journal, reservation, terminal=True)
            gate = record.continuation_request_gate
            if gate is None:
                raise ValueError('continuation provider gate is missing')
            request_usage = gate.request_usage(tool_calls=tool_receipt['tool_calls'])
            violations = exceeded_request_limits(request_usage)
            completed = any(event['kind'] == 'session.result'
                and event['payload'].get('run_id') == record.budget_run_id for event in record.history)
            needs_attention = bool(
                not completed or tool_receipt['blocked_reason'] or gate.has_blocked_request() or violations
            )
            receipt = {
                'reservation_id': reservation_id,
                'status': 'settled',
                'run_id': record.budget_run_id,
                'outcome': 'needs_attention' if needs_attention else 'completed',
                'request_usage': request_usage,
            }
            receipt['settlement_sha256'] = hashlib.sha256(json.dumps(
                receipt, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            record.budget_receipts[reservation_id] = receipt
            while len(record.budget_receipts) > 64:
                del record.budget_receipts[next(iter(record.budget_receipts))]
            return receipt
        except (OSError, ValueError, TypeError, KeyError):
            return {'reservation_id': reservation_id, 'status': 'outcome_unknown'}

    def continuation_receipt(self, session_id: str, reservation_id: str) -> dict:
        validate_identifier(session_id, field='session_id')
        try:
            record = self._get(session_id)
        except KeyError:
            return {'reservation_id': reservation_id, 'status': 'outcome_unknown'}
        with record.lock:
            if record.continuation_budget and record.continuation_budget['reservation_id'] == reservation_id:
                return self._budget_receipt(record)
            return record.budget_receipts.get(reservation_id) or {
                'reservation_id': reservation_id, 'status': 'outcome_unknown'}

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
        native_root_session_id: str | None = None,
        continuation_budget: dict | None = None,
        continuation_proxy_url: str | None = None,
        continuation_deadline_epoch_ms: int | None = None,
        product_turn_overlay_b64: str | None = None,
    ) -> Any:
        if self._root_scoped and re.fullmatch(r"[0-9a-f]{32}", root_run_id) is None:
            raise ValueError("root-scoped process requires a reserved root identity")
        environment = {
            "BYQ_MCP_URL": os.environ.get("BYQ_MCP_URL", "http://mcp:8300/mcp/v1"),
            "BYQ_MCP_TOKEN": os.environ.get("BYQ_MCP_TOKEN", ""),
            # Bind every DSH process launched by this Adapter process to its
            # process authority identity; root-scoped children inherit the same
            # boot identity through this owned environment.
            "BYQ_RUNTIME_BOOT_ID": self.boot_id,
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
        # ACP owns MCP identity inside DSH's official per-Agent composition.
        # These credentials are passed only to that pinned candidate; the ACP
        # transport strips the legacy execution bearer and Backend proof token
        # before starting DSH. A resumed root additionally pins its persisted
        # native session identity before DSH restores it.
        if self._acp:
            environment["BYQ_MCP_ACP_DISCOVERY_TOKEN"] = os.environ.get(
                "BYQ_MCP_ACP_DISCOVERY_TOKEN", "")
            environment["BYQ_MCP_ACP_SIGNING_KEY"] = os.environ.get(
                "BYQ_MCP_ACP_SIGNING_KEY", "")
            if native_root_session_id is not None:
                environment["BYQ_NATIVE_ROOT_SESSION_ID"] = native_root_session_id
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
        max_tokens = None
        guard_b64 = None
        if continuation_budget is not None:
            if continuation_proxy_url is None or continuation_deadline_epoch_ms is None:
                raise ValueError('continuation provider gate is required')
            if self._acp:
                environment['BYQ_CONTINUATION_RESERVATION_ID'] = continuation_budget['reservation_id']
                if self._acp_product_slots:
                    # The Product slot keeps the fixed Product composition; the
                    # restricted guard is applied by the trusted runner as an
                    # additional patch (tightening-only).
                    guard_b64 = base64.b64encode(create_acp_guard_overlay(
                        continuation_budget,
                        deadline_epoch_ms=continuation_deadline_epoch_ms,
                        root_run_id=root_run_id,
                        mcp_reservation_id=environment['BYQ_CONTINUATION_RESERVATION_ID'],
                        proxy_base_url=continuation_proxy_url,
                        provider_session_id=environment['BYQ_PROVIDER_SESSION_ID'],
                    )).decode('ascii')
                else:
                    guard_b64 = None
                    composition, _ = create_acp_guard_patch(
                        composition, session_root, continuation_budget,
                        deadline_epoch_ms=continuation_deadline_epoch_ms,
                        root_run_id=root_run_id,
                        mcp_reservation_id=environment['BYQ_CONTINUATION_RESERVATION_ID'],
                        proxy_base_url=continuation_proxy_url,
                    )
            else:
                guard_b64 = None
                composition, _ = create_guard_patch(
                    composition, session_root, continuation_budget,
                    deadline_epoch_ms=continuation_deadline_epoch_ms,
                    proxy_base_url=continuation_proxy_url,
                )
            # The request proxy is the only provider egress for this exact route.
            # The per-call output declaration is a safety ceiling, never a usage
            # charge; actual provider usage is recorded by the proxy.
            max_tokens = CONTINUATION_MAX_OUTPUT_TOKENS
            runtime_provider = str(model_resolution.get('provider') or self._provider)
            runtime_model = str(model_resolution.get('model') or self._model)
            if runtime_provider != CONTINUATION_PROVIDER or runtime_model != CONTINUATION_MODEL:
                raise ValueError('selected continuation model is unqualified')
            if runtime_provider == 'deepseek-official':
                # Legacy direct-route continuation (disabled under ADR-0105).
                environment['DEEPSEEK_BASE_URL'] = continuation_proxy_url
            # ADR-0105: the selected OpenCode Go chat route reads baseURL from the
            # runner-applied guard overlay, which pins it to this same local proxy.
            environment['DEEPSEEK_SEARCH_BASE_URL'] = ''
            environment['DEEPSEEK_SEARCH_API_KEY'] = ''
        elif product_turn_overlay_b64 is not None:
            # ADR-0106: ordinary Product route-only overlay. No continuation
            # reservation and no tool allowlist; the ordinary MCP tool authority
            # is unchanged.
            guard_b64 = product_turn_overlay_b64
            max_tokens = product_turn_limits()['max_output_tokens']
        return self._compatibility.build_harness(
            provider=str(model_resolution.get("provider") or self._provider),
            model=str(model_resolution.get("model") or self._model),
            composition=composition,
            session_root=session_root,
            runtime_command=self.runtime_command,
            environment=environment,
            max_tokens=max_tokens,
            continuation_guard_b64=guard_b64,
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
                **{key: resolution.get(key) for key in (
                    "profile_id", "profile_version", "credential_id",
                    "credential_version", "binding_version")},
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
                    if (observation.kind == "tool.call"
                            and observation.tool_name in {f"mcp__byq__{action}" for action in DOMAIN_CALL_ACTIONS}):
                        if (len(run.domain_calls) >= 1024
                                or record.domain_call_sequence >= 1024):
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
                # ACP child tool updates do not reach this parent stream. Its
                # domain proof is durably recorded by MCP/Backend for both root
                # and child, so do not create a second, in-memory-only Adapter
                # evidence cursor that cannot be drained after process restart.
                if (self._root_scoped and not self._acp and source_run is run and runtime_activity and not run.domain_stop_code
                        and observation.domain_arguments is not None and observation.event_sequence is not None
                        and record.process_root_id == run.run_id):
                    try:
                        evidence = request_evidence(observation.tool_name.removeprefix("mcp__byq__"),
                            observation.domain_arguments, trace_id=record.trace_id)
                    except ValueError:
                        evidence = None
                    if evidence is not None:
                        observed_call = {"schema_version": "domain-call-observed.v1",
                            "sequence": record.domain_call_sequence + 1,
                            "root_run_id": run.run_id, "generation": record.runtime_generation,
                            "call_id": observation.call_id, **evidence}
                        validate_call_evidence(observed_call)
                        record.domain_call_evidence.append(observed_call)
                        record.domain_call_sequence = observed_call["sequence"]
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
                "correction_budget_exhausted", "call_retention_bound", "correction_failed",
                "recovery_envelope_violation"})

    @staticmethod
    def _guard_seconds(name: str, *, default: float, allow_disabled: bool = False, maximum: float = 3600.0) -> float:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be a number") from exc
        if allow_disabled and value == 0:
            return 0.0
        if not 1.0 <= value <= maximum:
            raise ValueError(f"{name} must be between 1 and {maximum:g} seconds" + (" or 0 to disable" if allow_disabled else ""))
        return value

    def _watch_run(self, record: RuntimeSession, run: ActiveRun) -> None:
        while True:
            timeout = self._watchdog_wait_timeout(run.continuation_deadline, time.monotonic())
            if run.watchdog_stop.wait(timeout=timeout):
                return
            now = time.monotonic()
            if self._enforce_run_guards(record, run, now=now):
                return
            self._emit_wait_notice(record, run, now=now)

    @staticmethod
    def _watchdog_wait_timeout(deadline: float | None, now: float) -> float:
        if deadline is None:
            return 1.0
        return min(1.0, max(0.0, deadline - now))

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
            # A periodic observation, never a new model call or lease renewal.
            if now - max(run.started_at, run.last_progress_check_at) >= self._progress_check_interval_seconds:
                run.last_progress_check_at = now
                self._emit_wait_notice(record, run, now=now)
            if run.domain_stop_code:
                code = run.domain_stop_code
            elif ((self._run_timeout_seconds > 0 and now - run.started_at > self._run_timeout_seconds)
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
            failed_generation = record.runtime_generation
            needs_close = not record.process_closed and not record.process_closing
            record.process_closing = needs_close or record.process_closing
            if needs_close and record.current_generation is not None:
                record.current_generation.close_attempt_in_progress = True
                record.current_generation.close_attempt_event.clear()
            self._emit(
                record,
                "session.failed",
                "runtime-adapter",
                {"code": code, "retryable": not bool(run.domain_stop_code), "run_id": run.run_id},
            )
        # A session owns its DSH process, so closing it cannot interrupt any
        # other Product conversation. The detached worker will discard any
        # late result and resume creates a fresh private generation.
        # The request deadline also owns the in-flight upstream socket. Close
        # it before waiting for this DSH process to stop.
        self._close_continuation_proxy(record, failed_generation, failed_harness)
        try:
            if needs_close:
                self._compatibility.close(failed_harness)
                with record.lock:
                    record.process_closing = False
                    record.process_closed = True
                    if record.current_generation is not None:
                        record.current_generation.process_exit_confirmed = True
                        record.current_generation.close_attempt_in_progress = False
                        record.current_generation.close_attempt_event.set()
        except Exception:
            with record.lock:
                record.process_closing = True
                record.process_closed = False
                if record.current_generation is not None:
                    record.current_generation.process_exit_confirmed = False
            raise
        finally:
            if needs_close:
                with record.lock:
                    if record.current_generation is not None:
                        record.current_generation.close_attempt_in_progress = False
                        record.current_generation.close_attempt_event.set()
            self._close_continuation_proxy(record, failed_generation, failed_harness)
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
