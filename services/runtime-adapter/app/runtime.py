from __future__ import annotations
from contextlib import nullcontext

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
from typing import Any, ClassVar, Mapping
from urllib.parse import quote

import httpx
from packages.contracts.acp_product_prebind import (
    START_BINDING_FIELDS,
    START_BINDING_SCHEMA,
    digest as prebind_digest,
)
from packages.contracts.acp_product_slot import (
    PRODUCT_SCOPE_KEYS,
    canonical_product_json,
    product_scope_digest,
    validate_product_scope,
)
from packages.contracts.acp_operator_process_fence import (
    COMPLETED_CLEANUP_REQUEST_SCHEMA as _R2_COMPLETED_CLEANUP_REQUEST_SCHEMA,
    PROCESS_FENCE_HANDOFF_SCHEMA as _R2_HANDOFF_SCHEMA,
    PROCESS_FENCE_HANDOFF_REQUEST_SCHEMA as _R2_HANDOFF_REQUEST_SCHEMA,
    PROCESS_FENCE_HANDOFF_OBSERVATION_SCHEMA as _R2_HANDOFF_OBSERVATION_SCHEMA,
    COMPLETED_CLEANUP_DIGEST_FIELD as _R2_COMPLETED_CLEANUP_DIGEST_FIELD,
    FENCE_CLOSE_RECEIPT_SCHEMA as _R2_CLOSE_RECEIPT_SCHEMA,
    LOCAL_VALIDATION_ACK_INTENT_SCHEMA as _LOCAL_VALIDATION_ACK_INTENT_SCHEMA,
    LOCAL_VALIDATION_ACK_REQUEST_SCHEMA as _LOCAL_VALIDATION_ACK_REQUEST_SCHEMA,
    LOCAL_VALIDATION_HANDOFF_REQUEST_SCHEMA as _LOCAL_VALIDATION_HANDOFF_REQUEST_SCHEMA,
    LOCAL_VALIDATION_HANDOFF_INPUT_SCHEMA as _LOCAL_VALIDATION_HANDOFF_INPUT_SCHEMA,
    LOCAL_VALIDATION_HANDOFF_INTENT_SCHEMA as _LOCAL_VALIDATION_HANDOFF_INTENT_SCHEMA,
    LOCAL_VALIDATION_HANDOFF_OBSERVATION_SCHEMA as _LOCAL_VALIDATION_HANDOFF_OBSERVATION_SCHEMA,
    LOCAL_VALIDATION_HANDOFF_OBSERVATION_SCHEMA as _LOCAL_VALIDATION_HANDOFF_OBS_SCHEMA,
    LOCAL_VALIDATION_PRE_ACK_SCHEMA as _LOCAL_VALIDATION_PRE_ACK_SCHEMA,
    LOCAL_VALIDATION_PRE_ACK_STOP_SCHEMA as _LOCAL_VALIDATION_PRE_ACK_STOP_SCHEMA,
    LOCAL_VALIDATION_RELEASE_OBSERVATION_SCHEMA as _LOCAL_VALIDATION_RELEASE_OBSERVATION_SCHEMA,
    OPERATOR_OBSERVATION_SCHEMA as _R2_OPERATOR_OBSERVATION_SCHEMA,
    OperatorProcessFenceContractError as _R2FenceContractError,
    digest as _r2_digest,
    validate_fence_close_receipt as _r2_validate_close_receipt,
    validate_completed_cleanup_request as _r2_validate_completed_cleanup_request,
    validate_local_validation_ack_intent as _local_validate_ack_intent,
    validate_local_validation_final_receipt as _local_validate_final,
    validate_local_validation_backend_confirmation as _local_validate_backend_confirmation,
    validate_local_validation_ack_request as _local_validate_ack_request,
    validate_local_validation_handoff_request as _local_validate_handoff_request,
    validate_local_validation_handoff as _local_validate_handoff,
    validate_local_validation_handoff_intent as _local_validate_handoff_intent,
    validate_local_validation_handoff_observation as _local_validate_handoff_observation,
    validate_local_validation_pre_ack_request as _local_validate_pre_ack_request,
    validate_local_validation_pre_ack_evidence as _local_validate_pre_ack_evidence,
    validate_local_validation_pre_ack_stop as _local_validate_pre_ack_stop,
    validate_local_validation_release_observation as _local_validate_ack_observation,
    validate_operator_observation as _r2_validate_operator_observation,
    validate_operator_observation_record as _r2_validate_operator_observation_record,
    validate_process_fence_request as _r2_validate_request,
    validate_process_fence_handoff as _r2_validate_handoff,
    validate_process_fence_handoff_request as _r2_validate_handoff_request,
    validate_process_fence_handoff_observation as _r2_validate_handoff_observation,
    validate_process_fence_handoff_confirmation as _r2_validate_handoff_confirmation,
)
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
from packages.contracts.agent_execution_options import validate_agent_execution_options
from packages.contracts.continuation_request import (
    ALLOWED_MODEL as CONTINUATION_MODEL,
    ALLOWED_PROVIDER as CONTINUATION_PROVIDER,
    UPSTREAM_BASE_URL as CONTINUATION_UPSTREAM,
    exceeded_request_limits,
    exceeded_request_limits_v2,
    validate_request_usage_v2,
    validate_reservation_v3,
)

from .contracts import WorkflowTraceEvent, make_workflow_trace_event, validate_workflow_trace_event
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
    create_acp_task_ready_execution_overlay,
    create_acp_product_execution_overlay,
    read_request_guard,
    read_task_ready_v2_guard,
)
from packages.contracts.product_turn_request import (
    OFFICIAL_PRODUCT_TURN_PROVIDER,
    OFFICIAL_PRODUCT_TURN_MODEL,
    OFFICIAL_PRODUCT_TURN_UPSTREAM_BASE_URL,
    PRODUCT_TURN_UPSTREAM_BASE_URL,
    official_product_turn_execution_profile,
    product_turn_execution_output_cap,
    product_turn_execution_profile,
    validate_ordinary_product_execution_profile,
)
from .continuation_budget import PRODUCT_TURN_PROVIDER, PRODUCT_TURN_MODEL
from .research_request_gate import (
    KNOWN_BLOCKED, SETTLED_OK, UNKNOWN_OR_UNPAIRED,
    RequestGateProxy, build_continuation_request_gate, build_product_turn_request_gate,
    build_task_ready_v2_request_gate,
)
from .normalization import NormalizationState, normalize_runtime_observation


_PROCESS_BOOT_PID = os.getpid()
_PROCESS_BOOT_ID = secrets.token_hex(16)
_ACK_TOMBSTONE_LIMIT = 512
_TASK_READY_IDEMPOTENCY_KEY_RE = re.compile(r'task-ready-event:([0-9a-f]{64})')
_ACP_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_ACP_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_ACP_ROOT_BINDING_V2_SCHEMA = "byq-acp-root-binding.v2"
_ACP_ROOT_BINDING_V3_SCHEMA = "byq-acp-root-binding.v3"
_ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA = "byq-acp-root-binding.local-validation-ack.v1"
_ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA = "byq-acp-root-binding.local-validation-pre-ack.v1"
_ACP_ROOT_BINDING_LOCAL_VALIDATION_HANDOFF_SCHEMA = "byq-acp-root-binding.local-validation-handoff.v1"
_ACP_RECOVERY_BOUNDARY_SCHEMA = "byq-acp-recovery-boundary.v1"
_ACP_RECOVERY_BOUNDARY_EVENT_SCHEMA = "runtime-recovery-boundary-event.v1"


def _process_boot_id() -> str:
    """Return one random identity per OS process, including after a fork."""

    global _PROCESS_BOOT_PID, _PROCESS_BOOT_ID
    pid = os.getpid()
    if pid != _PROCESS_BOOT_PID:
        _PROCESS_BOOT_PID = pid
        _PROCESS_BOOT_ID = secrets.token_hex(16)
    return _PROCESS_BOOT_ID


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON field")
        value[key] = item
    return value


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


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


def _task_ready_reservation_id(reservation_v3: object) -> str:
    """Bind the separate ledger reservation ID to the v3 event identity."""

    reservation = validate_reservation_v3(reservation_v3)
    match = _TASK_READY_IDEMPOTENCY_KEY_RE.fullmatch(reservation['idempotency_key'])
    if match is None:
        raise ValueError('task-ready event idempotency identity is invalid')
    digest = match[1]
    if reservation['event_key'] != 'ready-v1:' + digest:
        raise ValueError('task-ready event and reservation identities conflict')
    return 'continuation_' + digest[:32]


def _runtime_reservation_id(reservation: dict) -> str:
    if reservation.get('schema_version') == 'task-continuation-reservation.v3':
        return _task_ready_reservation_id(reservation)
    return reservation['reservation_id']


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
    ordinary_execution_options: dict[str, object] | None = field(default=None, repr=False)
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
    ordinary_execution_profile: dict[str, object] | None = field(default=None, repr=False)
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
    recovery_boundary: dict[str, Any] | None = field(default=None, repr=False)
    # Set only for a normal completed root whose exact Backend receipt was
    # accepted and whose ACP session close and process exit were both proven.
    # It is deliberately in-memory only: Adapter restart falls back to a fresh
    # ACP session and the Gateway's public history projection.
    reuse_native_session_ready: bool = False
    cleanup_unconfirmed: bool = False
    cleanup_harness: Any = field(default=None, repr=False)
    qualified_operator_scope: dict[str, str] | None = field(default=None, repr=False)
    qualified_operator_binding: dict[str, Any] | None = field(default=None, repr=False)
    qualified_runtime_generation: str | None = field(default=None, repr=False)
    qualified_cwd: str | None = field(default=None, repr=False)
    qualified_authority_epoch: int | None = field(default=None, repr=False)
    operator_observation: dict[str, Any] | None = field(default=None, repr=False)
    operator_superseded_terminal_receipts: dict[str, str] = field(default_factory=dict, repr=False)
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

    def _require_group_admission(
        self, record: RuntimeSession, root_run_id: str, *,
        runner_identity: dict[str, str] | None = None,
        operator_scope: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        """Keep unresolved Backend roots fenced after the slot client restarts."""
        if not self._acp_product_slots:
            return None
        qualified = runner_identity is not None or operator_scope is not None
        if qualified and (runner_identity is None or operator_scope is None):
            raise RuntimeAuthorityUnavailable("qualified workspace Agent admission is incomplete")
        token = os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
        if not token:
            raise RuntimeAuthorityUnavailable("workspace Agent authority is unavailable")
        params: dict[str, str] = {
            "root_run_id": root_run_id,
            "session_id": record.session_id,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "X-BYQ-Owner-Principal": record.owner_principal or "",
            "X-BYQ-Runtime-Boot-ID": self.boot_id,
        }
        if qualified:
            if (set(runner_identity or {}) != {
                    "runner_instance_id", "runner_boot_id", "state_generation",
                    "signed_instance_sha256"}
                    or set(operator_scope or {}) != PRODUCT_SCOPE_KEYS):
                raise RuntimeAuthorityUnavailable("qualified workspace Agent identity is invalid")
            params["runner_identity"] = canonical_product_json(runner_identity).decode("ascii")
            params["operator_scope"] = canonical_product_json(operator_scope).decode("ascii")
            headers["X-BYQ-Trace-ID"] = record.trace_id
        try:
            response = httpx.get(
                f"{self._backend_url.rstrip('/')}/internal/runtime-authority/workspaces/"
                f"{record.workspace_id}/agent-admission",
                params=params, headers=headers, timeout=2.0)
            response.raise_for_status()
            if qualified:
                if len(response.content) > 64 * 1024:
                    raise ValueError("admission response is oversized")
                result = json.loads(response.content.decode("utf-8"),
                                    object_pairs_hook=_strict_json_object,
                                    parse_constant=_reject_json_constant)
            else:
                result = response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            raise RuntimeAuthorityUnavailable("workspace Agent admission is unavailable") from None
        if qualified:
            try:
                checked_scope = validate_product_scope(operator_scope)
            except (TypeError, ValueError):
                raise RuntimeAuthorityUnavailable("qualified workspace Agent scope is invalid") from None
            if (not isinstance(result, dict) or set(result) != {
                    "schema_version", "workspace_id", "boot_id", "authority_epoch",
                    "root_run_id", "can_start", "operator_scope", "operator_binding"}
                    or result.get("schema_version") != "byq-workspace-agent-admission.v2"
                    or result.get("workspace_id") != record.workspace_id
                    or result.get("boot_id") != self.boot_id
                    or result.get("root_run_id") != root_run_id
                    or type(result.get("authority_epoch")) is not int
                    or result.get("authority_epoch") != record.authority_epoch
                    or type(result.get("can_start")) is not bool
                    or result.get("operator_scope") != checked_scope):
                raise RuntimeAuthorityUnavailable("qualified workspace Agent admission is unproven")
            binding = result.get("operator_binding")
            if (not isinstance(binding, dict) or set(binding) != START_BINDING_FIELDS
                    or binding.get("schema_version") != START_BINDING_SCHEMA
                    or any(binding.get(field) != runner_identity.get(field) for field in (
                        "runner_instance_id", "runner_boot_id", "state_generation",
                        "signed_instance_sha256"))
                    or any(not isinstance(binding.get(field), str)
                           or _ACP_HEX64.fullmatch(binding[field]) is None for field in (
                               "signed_instance_sha256", "prepared_receipt_sha256",
                               "backend_binding_nonce", "install_receipt_sha256",
                               "backend_activation_receipt_sha256"))
                    or not isinstance(binding.get("runner_instance_id"), str)
                    or _ACP_HEX64.fullmatch(binding["runner_instance_id"]) is None
                    or not isinstance(binding.get("runner_boot_id"), str)
                    or _ACP_HEX32.fullmatch(binding["runner_boot_id"]) is None
                    or not isinstance(binding.get("state_generation"), str)
                    or _ACP_HEX64.fullmatch(binding["state_generation"]) is None
                    or not isinstance(binding.get("backend_activation_id"), str)
                    or _ACP_HEX32.fullmatch(binding["backend_activation_id"]) is None):
                raise RuntimeAuthorityUnavailable("qualified workspace Agent binding is unproven")
            if not result["can_start"]:
                raise SessionConflict("workspace has an unsettled Agent turn")
            if self.require_current_backend_authority() != record.authority_epoch:
                raise RuntimeAuthorityUnavailable("workspace Agent authority changed during admission")
            return dict(binding)
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
        return None

    def _configure_qualified_product_start(
        self, record: RuntimeSession, harness: Any, *, root_run_id: str,
        runtime_generation: str, cwd: str, base_binding_sha256: str | None,
        predecessor_raw: bytes | None = None, predecessor_sha256: str | None = None,
        allow_missing_predecessor: bool = True,
        prestart_proxy: Any = None,
        runtime_restore: dict[str, Any] | None = None,
    ) -> None:
        """Bind one fresh root harness to the configured qualified START seam."""
        if (not self._acp_product_slots or not record.workspace_id
                or not self._compatibility.product_slots.requires_prebind(record.workspace_id)):
            return
        from .acp_product_slot_client import (
            ProductSlotPrebindNoStart,
            ProductSlotPrebindRetirement,
            ProductSlotPrebindUncertain,
        )

        if _ACP_HEX64.fullmatch(base_binding_sha256 or "") is None:
            raise SessionConflict("ACP qualified start has no prepared root binding")
        expected_cwd = str(Path(cwd).resolve())
        expected_scope = {
            "workspace_id": record.workspace_id,
            "owner_principal": record.owner_principal,
            "session_id": record.session_id,
            "trace_id": record.trace_id,
            "root_run_id": root_run_id,
            "runtime_boot_id": self.boot_id,
            "generation_id": runtime_generation,
            "cwd_leaf": Path(expected_cwd).name,
        }
        expected_record_generation = record.runtime_generation
        expected_native_session_id = record.runtime_session_id
        harness.product_start_retirement_receipt = None
        guard_sha256 = getattr(harness, "prepared_guard_sha256", None)
        if _ACP_HEX64.fullmatch(guard_sha256 or "") is None:
            raise SessionConflict("ACP prepared guard identity is unavailable")
        prepared: dict[str, Any] = {}

        def restore_runtime_snapshot() -> None:
            if runtime_restore is not None:
                for name, value in runtime_restore.items():
                    setattr(record, name, value)

        def retire_no_start(scope: dict[str, str]) -> ProductSlotPrebindRetirement:
            if prestart_proxy is not None:
                prestart_proxy.close()
            from .compat.dsh_acp import retire_prepared_guard_patch
            retire_prepared_guard_patch(
                Path(harness.session_root), expected_root_id=root_run_id,
                expected_sha256=guard_sha256,
            )
            if predecessor_raw is None:
                retired_sha = None
                if not allow_missing_predecessor:
                    raise SessionConflict("ACP predecessor binding is unavailable")
                self._restore_prestart_acp_binding(
                    record, expected_sha256=str(base_binding_sha256),
                    predecessor_raw=None,
                    expected_root_id=root_run_id,
                    expected_runtime_generation=runtime_generation,
                    expected_cwd=expected_cwd,
                    expected_native_session_id=expected_native_session_id,
                )
                disposition = "removed"
            else:
                if (not isinstance(predecessor_sha256, str)
                        or not hmac.compare_digest(
                            hashlib.sha256(predecessor_raw).hexdigest(), predecessor_sha256)):
                    raise SessionConflict("ACP predecessor binding receipt is invalid")
                self._restore_prestart_acp_binding(
                    record, expected_sha256=str(base_binding_sha256),
                    predecessor_raw=predecessor_raw,
                    expected_root_id=root_run_id,
                    expected_runtime_generation=runtime_generation,
                    expected_cwd=expected_cwd,
                    expected_native_session_id=expected_native_session_id,
                )
                retired_sha = predecessor_sha256
                disposition = "restored"
            restore_runtime_snapshot()
            prepared.clear()
            return ProductSlotPrebindRetirement(
                scope_digest=product_scope_digest(scope), root_run_id=root_run_id,
                base_binding_sha256=str(base_binding_sha256),
                prepared_guard_sha256=guard_sha256,
                retired_binding_sha256=retired_sha, disposition=disposition,
            )

        def prepare_start(scope, requested_cwd, read_instance):
            safe_prestart_guard = False
            write_attempted = False
            try:
                self._assert_qualified_prestart_binding(
                    record, expected_sha256=base_binding_sha256,
                    root_run_id=root_run_id,
                    runtime_generation=runtime_generation,
                    cwd=expected_cwd,
                    native_session_id=expected_native_session_id,
                )
                safe_prestart_guard = True
                if (record.process_root_id != root_run_id
                        or record.runtime_generation != expected_record_generation
                        or record.authority_epoch is None
                        or not hmac.compare_digest(
                            str(record.workspace_id), str(expected_scope["workspace_id"]))
                        or record.session_id != expected_scope["session_id"]
                        or record.trace_id != expected_scope["trace_id"]
                        or record.owner_principal != expected_scope["owner_principal"]
                        or Path(requested_cwd).resolve() != Path(expected_cwd)
                        or Path(harness.session_root).resolve() != Path(expected_cwd)):
                    raise SessionConflict("ACP qualified start closure is stale")
                environment_scope = {
                    "workspace_id": harness.environment.get("BYQ_WORKSPACE_ID"),
                    "owner_principal": harness.environment.get("BYQ_OWNER_PRINCIPAL"),
                    "session_id": harness.environment.get("BYQ_SESSION_ID"),
                    "trace_id": harness.environment.get("BYQ_TRACE_ID"),
                    "root_run_id": harness.environment.get("BYQ_ROOT_RUN_ID"),
                    "runtime_boot_id": harness.environment.get("BYQ_RUNTIME_BOOT_ID"),
                    "generation_id": harness.environment.get("BYQ_DSH_RUN_ID"),
                    "cwd_leaf": Path(expected_cwd).name,
                }
                try:
                    checked_scope = validate_product_scope(scope)
                except (TypeError, ValueError):
                    raise SessionConflict("ACP qualified start scope is invalid") from None
                if (checked_scope != expected_scope or checked_scope != environment_scope
                        or dict(scope) != checked_scope):
                    raise SessionConflict("ACP qualified start scope is stale")
                instance = read_instance()
                if (not isinstance(instance, dict)
                        or instance.get("workspace_id") != record.workspace_id
                        or instance.get("operator_qualified") is not False
                        or instance.get("deployment_binding_sha256") is not None
                        or instance.get("backend_binding_nonce") is not None):
                    raise SessionConflict("ACP qualified runner identity is invalid")
                runner_identity = {
                    "runner_instance_id": instance.get("runner_instance_id"),
                    "runner_boot_id": instance.get("runner_boot_id"),
                    "state_generation": instance.get("state_generation"),
                    "signed_instance_sha256": prebind_digest(instance),
                }
                if (not isinstance(runner_identity["runner_instance_id"], str)
                        or _ACP_HEX64.fullmatch(runner_identity["runner_instance_id"]) is None
                        or not isinstance(runner_identity["runner_boot_id"], str)
                        or _ACP_HEX32.fullmatch(runner_identity["runner_boot_id"]) is None
                        or not isinstance(runner_identity["state_generation"], str)
                        or _ACP_HEX64.fullmatch(runner_identity["state_generation"]) is None
                        or not isinstance(runner_identity["signed_instance_sha256"], str)
                        or _ACP_HEX64.fullmatch(runner_identity["signed_instance_sha256"]) is None):
                    raise SessionConflict("ACP qualified runner identity is invalid")
                binding = self._require_group_admission(
                    record, root_run_id, runner_identity=runner_identity,
                    operator_scope=checked_scope,
                )
                if binding is None:
                    raise RuntimeAuthorityUnavailable("qualified workspace Agent binding is missing")
                write_attempted = True
                v2_sha256, previous_raw = self._persist_qualified_acp_binding(
                    record, base_sha256=base_binding_sha256,
                    root_run_id=root_run_id, runtime_generation=runtime_generation,
                    cwd=expected_cwd, operator_scope=checked_scope,
                    operator_binding=binding,
                )
                prepared.update({
                    "scope": checked_scope,
                    "binding": binding,
                    "v2_sha256": v2_sha256,
                    "previous_raw": previous_raw,
                })
                return binding
            except (ProductSlotPrebindNoStart, ProductSlotPrebindUncertain):
                raise
            except BaseException as exc:
                if not write_attempted and safe_prestart_guard:
                    try:
                        retirement = retire_no_start(expected_scope)
                    except BaseException as retire_error:
                        raise ProductSlotPrebindUncertain(
                            "qualified Product ACP start requires reconciliation"
                        ) from retire_error
                    raise ProductSlotPrebindNoStart(
                        "qualified Product ACP start was not admitted", retirement,
                    ) from exc
                raise ProductSlotPrebindUncertain(
                    "qualified Product ACP start requires reconciliation"
                ) from exc

        def prelaunch_reject(scope, code, binding):
            allowed = {
                "workspace_mismatch", "environment_rejected", "deadline_expired",
                "operator_binding_invalid", "prebind_activation_unavailable",
                "prebind_not_enabled",
            }
            if (code not in allowed or not prepared
                    or dict(scope) != prepared.get("scope")
                    or dict(binding) != prepared.get("binding")):
                raise SessionConflict("ACP qualified rejection does not match its prepared root")
            self._retire_qualified_prestart_binding(
                record, expected_sha256=prepared["v2_sha256"],
                previous_sha256=base_binding_sha256,
                previous_raw=prepared["previous_raw"],
                operator_scope=prepared["scope"],
                operator_binding=prepared["binding"],
            )
            retirement = retire_no_start(prepared["scope"])
            return retirement

        harness.product_start_prepare = prepare_start
        harness.product_start_prelaunch_reject = prelaunch_reject

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
        snapshot = {
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
        product_slots = getattr(self._compatibility, "product_slots", None)
        if self._acp and product_slots is not None:
            snapshot["product_slot_leases"] = product_slots.operations_counts()
        return snapshot

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

    def _known_ordinary_budget_block(
        self, record: RuntimeSession, generation_id: str, run: ActiveRun,
    ) -> bool:
        """One strict predicate for a known ordinary Product pre-dispatch budget block.

        True only for the ordinary ACP Product path (no F6 continuation budget)
        when the exact current generation's provider proxy is provably closed, no
        domain stop occurred, and the sealed request gate's ONLY refusals are
        pre-dispatch configured limits. It never bypasses the
        storage/unknown/unpaired/process fence and never inspects ``_cancelled``
        (a budget rejection itself sets it). Callers must hold ``record.lock``.
        """

        if not (self._acp_product_slots and record.continuation_budget is None):
            return False
        generation = record.current_generation
        if (generation is None or generation.generation_id != generation_id
                or generation.continuation_proxy_closed is not True):
            return False
        if run.domain_stop_code:
            return False
        gate = record.continuation_request_gate
        if gate is None:
            return False
        try:
            return gate.known_budget_block_reason() is not None
        except Exception:  # noqa: BLE001 — damaged receipts fail closed
            return False

    def _known_ordinary_postdispatch_runtime_limit(
        self, record: RuntimeSession, generation_id: str, run: ActiveRun,
    ) -> bool:
        """Allow a fresh root after a paired, explicitly bounded v2 runtime stop.

        This does not reopen or replay the stopped root. The normal terminal
        receipt, process cleanup, and exact Backend acknowledgement still gate a
        later prompt, which is admitted as a new root with a fresh options read.
        """

        if (not self._acp_product_slots or record.continuation_budget is not None
                or run.domain_stop_code):
            return False
        generation = record.current_generation
        if (generation is None or generation.generation_id != generation_id
                or generation.continuation_proxy_closed is not True):
            return False
        gate = record.continuation_request_gate
        if gate is None:
            return False
        try:
            return gate.known_postdispatch_product_runtime_limit()
        except Exception:  # noqa: BLE001 — damaged receipts fail closed
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
        if self._acp_product_slots and workspace_id:
            self._require_workspace_acp_cleanup_fence(workspace_id)
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
            if (record.recovery_boundary is not None
                    and record.recovery_boundary.get("state") != "acknowledged"):
                raise SessionConflict("recovery trace boundary is not acknowledged")
            if self._acp and self._acp_binding_path(session_id, record.workspace_id).exists():
                try:
                    prior_binding = self._read_acp_binding(session_id)
                except KeyError:
                    prior_binding = None
                if (prior_binding is not None and prior_binding.get("schema_version")
                        == _ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA):
                    observation = prior_binding.get("local_validation_release_observation")
                    if observation is None:
                        raise SessionConflict("local validation ACK release is not durable")
                    row = self._read_backend_local_validation_final(
                        record, observation["ack_intent"]["final_receipt"])
                    if row["local_validation"].get("runtime_observation") != observation:
                        raise SessionConflict("local validation Backend observation differs from Runtime readback")
                    raw_confirmation = row["local_validation"].get("confirmation_receipt")
                    if raw_confirmation is None:
                        raise SessionConflict("local validation Backend confirmation is not complete")
                    try:
                        confirmation = _local_validate_backend_confirmation(raw_confirmation)
                    except (TypeError, ValueError):
                        raise SessionConflict("local validation Backend confirmation is invalid") from None
                    if confirmation["runtime_observation"] != observation:
                        raise SessionConflict("local validation Backend confirmation changed its Runtime proof")
            if (record.cleanup_unconfirmed
                    and not self._operator_fence_matches_current_root(record)):
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
            task_ready_budget = None
            if continuation_budget is not None:
                if (isinstance(continuation_budget, dict)
                        and continuation_budget.get('schema_version') == 'task-continuation-reservation.v3'):
                    task_ready_budget = validate_reservation_v3(continuation_budget)
                    if (task_ready_budget['owner_principal'] != record.owner_principal
                            or task_ready_budget['workspace_id'] != record.workspace_id):
                        raise ValueError('task-ready carrier does not match the Runtime owner/workspace')
                    reservation_id = _task_ready_reservation_id(task_ready_budget)
                    if idempotency_key != reservation_id:
                        raise ValueError('task-ready reservation identity does not match the prompt key')
                    if not self.task_ready_qualified(record):
                        raise ValueError('task-ready executor is not qualified')
                else:
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
            if self._acp_product_slots and record.workspace_id:
                # Reject before either lazy START or replacement prepares a
                # new Root, proxy, durable binding, or Backend admission.
                self._require_workspace_acp_cleanup_fence(record.workspace_id)
            if (self._acp_product_slots and not record.process_used
                    and budget is None and task_ready_budget is None):
                # ADR-0111: the first ordinary submit starts the ACP product slot.
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
                prestart_predecessor_raw = None
                prestart_predecessor_sha256 = None
                qualified_prebind = bool(
                    self._acp_product_slots and record.workspace_id
                    and self._compatibility.product_slots.requires_prebind(record.workspace_id))
                prestart_runtime_restore = {
                    name: getattr(record, name) for name in (
                        "process_root_id", "authority_epoch", "cleanup_harness",
                        "cleanup_unconfirmed", "settlement_receipt",
                        "qualified_operator_scope", "qualified_operator_binding",
                        "qualified_runtime_generation", "qualified_cwd",
                        "qualified_authority_epoch", "operator_observation",
                        "recovery_boundary",
                    )
                }
                try:
                    first_upstream = self._ordinary_product_upstream(record.model_resolution)
                    first_profile = self._load_product_execution_profile(
                        record, record.process_root_id,
                        runtime_generation=record.runtime_generation,
                    )
                    first_gate = build_product_turn_request_gate(
                        request_id='product-turn-' + record.runtime_generation,
                        execution_profile=first_profile,
                        journal=_root_journal_path(
                            Path(record.recovery_cwd), 'product-turn-provider-request',
                            record.process_root_id),
                    )
                    first_proxy = RequestGateProxy(
                        first_gate, first_upstream, bind_host="0.0.0.0",
                        advertise_host=_continuation_proxy_advertise_host())
                    first_proxy.__enter__()
                    first_overlay = base64.b64encode(create_acp_product_execution_overlay(
                        proxy_base_url=first_proxy.base_url,
                        provider_session_id=str(uuid.uuid5(uuid.NAMESPACE_URL,
                            "beyondquant:provider-session:" + record.session_id)),
                        provider=first_provider, model=first_model,
                        execution_profile=first_profile)).decode('ascii')
                    first_search_key = (
                        self._resolve_search_credential(
                            owner_principal=record.owner_principal,
                            session_id=record.session_id,
                            trace_id=record.trace_id,
                        ) if first_provider in {PRODUCT_TURN_PROVIDER, OFFICIAL_PRODUCT_TURN_PROVIDER} else None
                    )
                    record.harness = self._build_harness(
                        record.session_id, Path(record.recovery_cwd), trace_id=record.trace_id,
                        owner_principal=record.owner_principal, workspace_id=record.workspace_id,
                        model_resolution=record.model_resolution,
                        runtime_generation=record.runtime_generation,
                        root_run_id=record.process_root_id,
                        continuation_proxy_url=first_proxy.base_url,
                        product_turn_overlay_b64=first_overlay,
                        product_execution_profile=first_profile,
                        search_api_key=first_search_key)
                    record.continuation_request_gate = first_gate
                    record.continuation_request_proxy = first_proxy
                    if record.current_generation is None:
                        raise RuntimeAuthorityUnavailable("ordinary execution generation is unavailable")
                    record.current_generation.ordinary_execution_profile = first_profile
                    # Bind the first lazy Product root to the current Backend
                    # authority before START. Unknown start outcomes must be
                    # recoverable from this exact durable root binding.
                    if qualified_prebind:
                        prestart_predecessor_raw, prestart_predecessor_sha256 = (
                            self._capture_prestart_predecessor(
                                record, expected_root_id=record.process_root_id))
                    no_start_proven = True
                    record.authority_epoch = self.require_current_backend_authority()
                    record.cleanup_harness = record.harness
                    record.cleanup_unconfirmed = True
                    prestart_binding_attempted = True
                    first_lazy_prestart_binding = True
                    if qualified_prebind:
                        prestart_binding_sha256 = self._persist_acp_binding(
                            record, clear_qualified=True,
                            root_run_id=record.process_root_id,
                            runtime_generation=record.runtime_generation,
                            cwd=record.recovery_cwd or "", starting_new_root=True,
                            expected_previous=(prestart_predecessor_raw,
                                               prestart_predecessor_sha256),
                        )
                    else:
                        prestart_binding_sha256 = self._persist_acp_binding(record)
                    self._configure_qualified_product_start(
                        record, record.harness, root_run_id=record.process_root_id,
                        runtime_generation=record.runtime_generation,
                        cwd=record.recovery_cwd or "",
                        base_binding_sha256=prestart_binding_sha256,
                        predecessor_raw=prestart_predecessor_raw,
                        predecessor_sha256=prestart_predecessor_sha256,
                        allow_missing_predecessor=not record.process_used,
                        prestart_proxy=first_proxy if qualified_prebind else None,
                        runtime_restore=prestart_runtime_restore if qualified_prebind else None,
                    )
                    # A continuation (budget is not None) starts its own ACP root
                    # below; starting the slot here would hold the workspace lease
                    # and make the continuation's availability check report busy.
                    from .acp_product_slot_client import ProductSlotBusy
                    try:
                        self._require_workspace_acp_cleanup_fence(record.workspace_id)
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
                        receipt = getattr(
                            record.harness, "product_start_retirement_receipt", None)
                        try:
                            if qualified_prebind and receipt is not None:
                                expected_scope = {
                                    "workspace_id": record.harness.environment.get("BYQ_WORKSPACE_ID"),
                                    "owner_principal": record.harness.environment.get("BYQ_OWNER_PRINCIPAL"),
                                    "session_id": record.harness.environment.get("BYQ_SESSION_ID"),
                                    "trace_id": record.harness.environment.get("BYQ_TRACE_ID"),
                                    "root_run_id": record.harness.environment.get("BYQ_ROOT_RUN_ID"),
                                    "runtime_boot_id": record.harness.environment.get("BYQ_RUNTIME_BOOT_ID"),
                                    "generation_id": record.harness.environment.get("BYQ_DSH_RUN_ID"),
                                    "cwd_leaf": Path(record.harness.session_root).name,
                                }
                                self._verify_prestart_retirement_receipt(
                                    record, receipt, scope=expected_scope,
                                    base_sha256=prestart_binding_sha256,
                                    guard_sha256=getattr(
                                        record.harness, "prepared_guard_sha256", None),
                                    predecessor_raw=prestart_predecessor_raw,
                                    predecessor_sha256=prestart_predecessor_sha256,
                                )
                                for name, value in prestart_runtime_restore.items():
                                    setattr(record, name, value)
                            else:
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
                                if prestart_binding_attempted:
                                    if not isinstance(prestart_binding_sha256, str):
                                        raise SessionConflict(
                                            "ACP prepared root binding outcome is uncertain")
                                    if qualified_prebind:
                                        self._restore_prestart_acp_binding(
                                            record,
                                            expected_sha256=prestart_binding_sha256,
                                            predecessor_raw=prestart_predecessor_raw,
                                            expected_root_id=record.process_root_id,
                                            expected_runtime_generation=record.runtime_generation,
                                            expected_cwd=record.recovery_cwd or "",
                                            expected_native_session_id=record.runtime_session_id,
                                        )
                                        for name, value in prestart_runtime_restore.items():
                                            setattr(record, name, value)
                                    else:
                                        self._remove_prestart_acp_binding(
                                            record, expected_sha256=prestart_binding_sha256)
                                elif qualified_prebind:
                                    for name, value in prestart_runtime_restore.items():
                                        setattr(record, name, value)
                                record.cleanup_harness = prestart_runtime_restore["cleanup_harness"]
                                record.cleanup_unconfirmed = prestart_runtime_restore[
                                    "cleanup_unconfirmed"]
                        except BaseException:
                            record.cleanup_harness = record.harness
                            record.cleanup_unconfirmed = True
                            raise SessionConflict(
                                "workspace Agent execution requires reconciliation") from None
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
            has_continuation = budget is not None or task_ready_budget is not None
            if has_continuation and not record.process_used:
                self._compatibility.close(record.harness)
                record.process_closed = True
                if self._acp and record.current_generation is not None:
                    record.current_generation.process_exit_confirmed = True
            if self._root_scoped and (record.process_used or has_continuation):
                if record.workspace_id and conversation_context is None and not reuse_native:
                    raise SessionConflict("new root requires a fresh public conversation projection")
                operator_fenced_previous = self._operator_fence_matches_current_root(record)
                if (record.process_closing or not record.continuation_proxy_closed
                        or (not operator_fenced_previous and not record.process_closed)):
                    raise SessionConflict("previous runtime process cleanup is not complete")
                if (self._acp and record.process_used and record.current_generation is not None
                        and not record.current_generation.process_exit_confirmed
                        and not operator_fenced_previous):
                    raise SessionConflict("previous ACP process exit is not confirmed")
                if record.continuation_budget is not None:
                    old_reservation = record.continuation_budget
                    old_id = _runtime_reservation_id(old_reservation)
                    old_receipt = self._budget_receipt(record)
                    if (old_receipt.get('status') == 'settled'
                            or (isinstance(old_reservation, dict)
                                and old_reservation.get('schema_version') == 'task-continuation-reservation.v3'
                                and old_receipt.get('status') == 'outcome_unknown')):
                        record.budget_receipts[old_id] = old_receipt
                    while len(record.budget_receipts) > 64:
                        del record.budget_receipts[next(iter(record.budget_receipts))]
                previous_native_session = record.runtime_session_id
                previous_process_root_id = record.process_root_id
                qualified_prebind = bool(
                    self._acp_product_slots and record.workspace_id
                    and self._compatibility.product_slots.requires_prebind(record.workspace_id))
                replacement_predecessor_raw = None
                replacement_predecessor_sha256 = None
                replacement_runtime_restore = {
                    name: getattr(record, name) for name in (
                        "process_root_id", "authority_epoch", "cleanup_harness",
                        "cleanup_unconfirmed", "settlement_receipt",
                        "qualified_operator_scope", "qualified_operator_binding",
                        "qualified_runtime_generation", "qualified_cwd",
                        "qualified_authority_epoch", "operator_observation",
                        "recovery_boundary",
                    )
                }
                if qualified_prebind:
                    replacement_predecessor_raw, replacement_predecessor_sha256 = (
                        self._capture_prestart_predecessor(
                            record, expected_root_id=previous_process_root_id))
                if self._acp_product_slots:
                    from .acp_product_slot_client import ProductSlotBusy
                    # Recheck immediately before replacement START in case a
                    # binding changed after the synchronous prompt admission.
                    self._require_workspace_acp_cleanup_fence(record.workspace_id)
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
                task_ready_overlay_b64 = None
                product_execution_profile = None
                self._require_group_admission(record, root_id)
                try:
                    if task_ready_budget is not None:
                        reservation_id = _task_ready_reservation_id(task_ready_budget)
                        request_gate = build_task_ready_v2_request_gate(
                            request_id=reservation_id,
                            execution_profile=task_ready_budget['execution_profile'],
                            journal=(_root_journal_path(
                                session_root, 'continuation-provider-request', root_id)
                                if self._acp else
                                session_root / 'continuation-provider-request.jsonl'),
                        )
                        request_proxy = RequestGateProxy(
                            request_gate, CONTINUATION_UPSTREAM,
                            bind_host="0.0.0.0",
                            advertise_host=_continuation_proxy_advertise_host(),
                        )
                        request_proxy.__enter__()
                        tool_journal = _root_journal_path(
                            session_root, 'continuation-tool-guard', root_id)
                        provider_session_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                            "beyondquant:provider-session:" + record.session_id))
                        task_ready_overlay_b64 = base64.b64encode(
                            create_acp_task_ready_execution_overlay(
                                proxy_base_url=request_proxy.base_url,
                                provider_session_id=provider_session_id,
                                reservation_v3=task_ready_budget,
                                root_run_id=root_id,
                            )).decode('ascii')
                    elif budget is not None:
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
                        # ADR-0111: the ordinary ACP root uses this conversation's
                        # exact trusted option revision. Missing or cross-scope
                        # options stop before the provider proxy or slot START.
                        # F6 continuation requests stay on their separate closed
                        # legacy profile branch above.
                        # This ACP candidate qualifies ONLY the OpenCode Go
                        # / `deepseek-v4.1-flash` route; any other resolved model is
                        # rejected before any proxy is created (no unbudgeted egress,
                        # no silent switch). All construction stays inside this try so
                        # a failure closes an opened proxy.
                        runtime_provider = str(record.model_resolution.get('provider') or self._provider)
                        runtime_model = str(record.model_resolution.get('model') or self._model)
                        ordinary_upstream = self._ordinary_product_upstream(record.model_resolution)
                        product_provider_session_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                            "beyondquant:provider-session:" + record.session_id))
                        product_execution_profile = self._load_product_execution_profile(
                            record, root_id, runtime_generation=generation)
                        request_gate = build_product_turn_request_gate(
                            request_id='product-turn-' + generation,
                            execution_profile=product_execution_profile,
                            journal=_root_journal_path(
                                session_root, 'product-turn-provider-request', root_id),
                        )
                        request_proxy = RequestGateProxy(
                            request_gate, ordinary_upstream,
                            bind_host="0.0.0.0",
                            advertise_host=_continuation_proxy_advertise_host(),
                        )
                        request_proxy.__enter__()
                        product_turn_overlay_b64 = base64.b64encode(
                            create_acp_product_execution_overlay(
                                proxy_base_url=request_proxy.base_url,
                                provider_session_id=product_provider_session_id,
                                provider=runtime_provider, model=runtime_model,
                                execution_profile=product_execution_profile)).decode('ascii')
                    search_api_key = None
                    if (self._acp_product_slots and budget is None
                            and task_ready_budget is None
                            and product_turn_overlay_b64 is not None
                            and runtime_provider in {PRODUCT_TURN_PROVIDER, OFFICIAL_PRODUCT_TURN_PROVIDER}):
                        search_api_key = self._resolve_search_credential(
                            owner_principal=record.owner_principal,
                            session_id=record.session_id,
                            trace_id=record.trace_id,
                        )
                    harness = self._build_harness(record.session_id, session_root,
                        trace_id=record.trace_id, owner_principal=record.owner_principal,
                        workspace_id=record.workspace_id, model_resolution=record.model_resolution,
                        runtime_generation=generation, root_run_id=root_id, continuation_budget=budget,
                        task_ready_overlay_b64=task_ready_overlay_b64,
                        task_ready_reservation_id=(
                            _task_ready_reservation_id(task_ready_budget)
                            if task_ready_budget is not None else None
                        ),
                        continuation_proxy_url=request_proxy.base_url if request_proxy is not None else None,
                        continuation_deadline_epoch_ms=(
                            int(time.time() * 1000 + remaining_seconds * 1000)
                            if request_gate is not None
                            and (remaining_seconds := request_gate.remaining_seconds()) is not None
                            else None
                        ),
                        product_turn_overlay_b64=product_turn_overlay_b64,
                        product_execution_profile=product_execution_profile,
                        search_api_key=search_api_key,
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
                        if qualified_prebind:
                            prestart_binding_sha256 = self._persist_acp_binding(
                                record, clear_qualified=True,
                                root_run_id=root_id, runtime_generation=generation,
                                cwd=str(session_root), starting_new_root=True,
                                expected_previous=(replacement_predecessor_raw,
                                                   replacement_predecessor_sha256),
                            )
                        else:
                            prestart_binding_sha256 = self._persist_acp_binding(
                                record, clear_qualified=True)
                    except BaseException:
                        if qualified_prebind:
                            record.cleanup_harness = harness
                            record.cleanup_unconfirmed = True
                        else:
                            record.cleanup_harness = None
                            record.cleanup_unconfirmed = False
                        if request_proxy is not None:
                            request_proxy.close()
                        raise
                    self._configure_qualified_product_start(
                        record, harness, root_run_id=root_id,
                        runtime_generation=generation, cwd=str(session_root),
                        base_binding_sha256=prestart_binding_sha256,
                        predecessor_raw=replacement_predecessor_raw,
                        predecessor_sha256=replacement_predecessor_sha256,
                        allow_missing_predecessor=not record.process_used,
                        prestart_proxy=request_proxy if qualified_prebind else None,
                        runtime_restore=replacement_runtime_restore if qualified_prebind else None,
                    )
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
                            if qualified_prebind:
                                receipt = getattr(
                                    harness, "product_start_retirement_receipt", None)
                                try:
                                    if receipt is not None:
                                        expected_scope = {
                                            "workspace_id": harness.environment.get("BYQ_WORKSPACE_ID"),
                                            "owner_principal": harness.environment.get("BYQ_OWNER_PRINCIPAL"),
                                            "session_id": harness.environment.get("BYQ_SESSION_ID"),
                                            "trace_id": harness.environment.get("BYQ_TRACE_ID"),
                                            "root_run_id": harness.environment.get("BYQ_ROOT_RUN_ID"),
                                            "runtime_boot_id": harness.environment.get("BYQ_RUNTIME_BOOT_ID"),
                                            "generation_id": harness.environment.get("BYQ_DSH_RUN_ID"),
                                            "cwd_leaf": Path(harness.session_root).name,
                                        }
                                        self._verify_prestart_retirement_receipt(
                                            record, receipt, scope=expected_scope,
                                            base_sha256=prestart_binding_sha256,
                                            guard_sha256=getattr(
                                                harness, "prepared_guard_sha256", None),
                                            predecessor_raw=replacement_predecessor_raw,
                                            predecessor_sha256=replacement_predecessor_sha256,
                                        )
                                        for name, value in replacement_runtime_restore.items():
                                            setattr(record, name, value)
                                    else:
                                        if request_proxy is not None:
                                            request_proxy.close()
                                        from .compat.dsh_acp import retire_prepared_guard_patch
                                        prepared_digest = getattr(
                                            harness, "prepared_guard_sha256", None)
                                        if not isinstance(prepared_digest, str):
                                            raise SessionConflict(
                                                "ACP prepared guard identity is unavailable")
                                        retire_prepared_guard_patch(
                                            Path(harness.session_root), expected_root_id=root_id,
                                            expected_sha256=prepared_digest,
                                        )
                                        if not isinstance(prestart_binding_sha256, str):
                                            raise SessionConflict(
                                                "ACP prepared root binding outcome is uncertain")
                                        self._restore_prestart_acp_binding(
                                            record, expected_sha256=prestart_binding_sha256,
                                            predecessor_raw=replacement_predecessor_raw,
                                            expected_root_id=root_id,
                                            expected_runtime_generation=generation,
                                            expected_cwd=str(session_root),
                                            expected_native_session_id=previous_native_session,
                                        )
                                        for name, value in replacement_runtime_restore.items():
                                            setattr(record, name, value)
                                except BaseException:
                                    record.cleanup_harness = harness
                                    record.cleanup_unconfirmed = True
                                    if request_proxy is not None:
                                        request_proxy.close()
                                    raise SessionConflict(
                                        "workspace Agent execution requires reconciliation") from None
                            else:
                                record.cleanup_harness = None
                                record.cleanup_unconfirmed = False
                                self._persist_acp_binding(record, clear_qualified=True)
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
                record.operator_observation = None
                record.cleanup_unconfirmed = False
                record.cleanup_harness = None
                installed.continuation_budget = budget if budget is not None else task_ready_budget
                installed.budget_journal = tool_journal
                installed.budget_run_id = root_id if has_continuation else None
                installed.continuation_request_gate = request_gate
                installed.continuation_request_proxy = request_proxy
                installed.continuation_proxy_closed = request_proxy is None
                installed.ordinary_execution_profile = product_execution_profile
            if record.harness is None:
                raise SessionConflict("runtime process is unavailable for this Agent session")
            now = time.monotonic()
            run = ActiveRun(run_id=record.process_root_id if self._root_scoped else uuid.uuid4().hex,
                            started_at=now, last_runtime_activity_at=now)
            if (record.current_generation is not None
                    and record.current_generation.ordinary_execution_profile is not None):
                execution_profile = validate_ordinary_product_execution_profile(
                    record.current_generation.ordinary_execution_profile)
                run.ordinary_execution_options = dict(execution_profile['options'])
            if budget is not None:
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
                    self._read_continuation_tool_guard(record)
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
                if self._known_ordinary_budget_block(record, generation_id, run):
                    # The exception was raised under a known, fully-settled
                    # ordinary Product pre-dispatch budget refusal (the retained
                    # batch1 AcpRpcError signature). The root stays truthfully
                    # failed, the original error is retained, and the live
                    # conversation stays promptable for an explicit new
                    # instruction. The failed turn is never replayed and no
                    # native/child state is reused.
                    run.model_failure_code = 'budget-exhausted'
                    record.status = SessionStatus.IDLE
                    self._emit(record, "session.failed", "runtime-adapter", {
                        "error": type(exc).__name__, "code": "budget-exhausted",
                        "retryable": False, "run_id": run.run_id})
                    self._close_generation(record, generation_id, "budget_exhausted")
                    return
                if self._known_ordinary_postdispatch_runtime_limit(
                    record, generation_id, run,
                ):
                    # The provider result is paired and the exact proxy cleanup
                    # is proven, but DSH may surface its withheld response as an
                    # ACP prompt exception. Keep the root failed and fenced;
                    # after terminal ACK only a distinct user instruction may
                    # create a fresh root. Unknown, mixed, cancelled, and
                    # unconfirmed-cleanup outcomes never reach this branch.
                    record.status = SessionStatus.IDLE
                    self._emit(record, "session.failed", "runtime-adapter", {
                        "error": type(exc).__name__, "code": "model-run-failed",
                        "retryable": False, "run_id": run.run_id})
                    self._close_generation(record, generation_id, "runtime_limited")
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
                    tool_receipt = self._read_continuation_tool_guard(record, terminal=True)
                    gate = record.continuation_request_gate
                    if gate is None:
                        raise ValueError('continuation provider gate is missing')
                    usage = gate.request_usage(tool_calls=tool_receipt['tool_calls'])
                    if record.continuation_budget.get('schema_version') == 'task-continuation-reservation.v3':
                        usage = validate_request_usage_v2(usage)
                        violations = exceeded_request_limits_v2(usage)
                    else:
                        violations = exceeded_request_limits(usage)
                    budget_blocked = bool(
                        tool_receipt['blocked_reason'] or gate.has_blocked_request()
                        or violations
                    )
                except (OSError, ValueError, TypeError, KeyError):
                    budget_blocked = True
                if budget_blocked:
                    run.model_failure_code = 'model-run-failed'
                    run.model_failure_retryable = False
            # Terminal provider settlement: a returned SDK call is a successful
            # root only when the request-scoped provider gate is provably
            # settled. The proxy close above only seals the gate; it neither
            # joins an in-flight handler nor proves that every admitted request
            # has a unique matching forwarded completion. The classification is
            # evaluated atomically (one gate lock) so a late receipt cannot slip
            # between separate checks. A physical settlement failure closes the
            # generation `failed`, distinct from a provider-budget exhaustion.
            settlement_failed = False
            settlement_gate = record.continuation_request_gate
            settlement_required = (
                self._acp_product_slots
                or record.continuation_budget is not None
                or settlement_gate is not None
            )
            proxy_closed = False
            if settlement_required:
                generation = record.current_generation
                proxy_closed = (generation is not None
                                and generation.continuation_proxy_closed is True)
                try:
                    settlement_state = (settlement_gate.settlement_state()
                                        if settlement_gate is not None
                                        else UNKNOWN_OR_UNPAIRED)
                except Exception:  # noqa: BLE001 — damaged receipts fail closed
                    settlement_state = UNKNOWN_OR_UNPAIRED
                if not proxy_closed or settlement_state != SETTLED_OK:
                    settlement_failed = True
                    run.model_failure_code = 'model-run-failed'
                    run.model_failure_retryable = False
            # A pre-dispatch ordinary budget refusal, or a fully paired v2
            # post-dispatch runtime stop, may leave the public conversation ready
            # for a *new* instruction after the exact terminal ACK and cleanup.
            # Neither path reopens the old root. A post-dispatch stop is not
            # mislabeled as a budget exhaustion; the fresh root reads a new
            # trusted options revision. Unknown/unpaired results and every other
            # refusal remain failed and fenced.
            known_budget_block = self._known_ordinary_budget_block(record, generation_id, run)
            known_runtime_stop = self._known_ordinary_postdispatch_runtime_limit(
                record, generation_id, run)
            if (finish_reason != "completed" or run.domain_stop_code
                    or budget_blocked or settlement_failed):
                allow_new_root = (known_budget_block or known_runtime_stop) and not budget_blocked
                if allow_new_root:
                    if known_budget_block:
                        run.model_failure_code = 'budget-exhausted'
                    record.status = SessionStatus.IDLE
                else:
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
                    record, generation_id,
                    "budget_exhausted" if (budget_blocked or known_budget_block) else "failed")
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

    def cancel_session(
            self, session_id: str, mode: str,
            expected_root_run_id: str | None = None) -> dict[str, Any]:
        if mode not in {"soft", "hard"}:
            raise ValueError("cancel mode must be soft or hard")
        if (expected_root_run_id is not None
                and (not isinstance(expected_root_run_id, str)
                     or re.fullmatch(r"[0-9a-f]{32}", expected_root_run_id) is None)):
            raise ValueError("invalid expected root run id")
        record = self._get(session_id)
        with record.lock:
            run = record.active_run
            if (expected_root_run_id is not None
                    and (run is None or run.run_id != expected_root_run_id)):
                raise SessionConflict("active prompt does not match expected root run id")
            if (expected_root_run_id is not None and mode == "soft"
                    and record.status == SessionStatus.CANCELLING):
                raise SessionConflict(
                    "root cancellation outcome is unconfirmed; reconcile terminal status")
            if run is None or record.status not in SessionStatus.ACTIVE_PROMPT:
                raise SessionConflict(f"session {session_id} has no active prompt")
            if mode == "soft":
                run.soft_cancel_requested = True
                record.status = SessionStatus.CANCELLING
                cancelled_harness = record.harness
                cancelled_native_session = record.runtime_session_id
                # Commit the CANCELLING state and fail-close the request-scoped
                # provider gate in the SAME record.lock critical section, so a
                # request already serialized on the single upstream slot cannot
                # be dispatched in a window after CANCELLING is marked. The lock
                # order is record.lock -> gate lock; the gate never acquires
                # record.lock, so this cannot deadlock.
                cancelled_gate = record.continuation_request_gate
                if cancelled_gate is not None:
                    cancelled_gate.cancel()
            else:
                run.hard_cancelled = True
                run.watchdog_stop.set()
                # Commit the INTERRUPTED state and fail-close the request-scoped
                # provider gate in the SAME record.lock critical section, so a
                # request queued on the single upstream slot cannot be dispatched
                # in the window before the proxy/process close below (which only
                # runs after this lock is released). Lock order is
                # record.lock -> gate lock; the gate never acquires record.lock.
                cancelled_gate = record.continuation_request_gate
                if cancelled_gate is not None:
                    cancelled_gate.cancel()
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
        response = self.describe_session(record)
        if expected_root_run_id is not None:
            response["cancelled_root_run_id"] = expected_root_run_id
        return response

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

    def reserve_operator_process_fence(
        self, session_id: str, raw_request: object,
    ) -> dict[str, str]:
        """Fence the current slot before Backend validates the protected preimage."""
        if (isinstance(raw_request, dict)
                and raw_request.get("schema_version") == _LOCAL_VALIDATION_HANDOFF_REQUEST_SCHEMA):
            try:
                request = _local_validate_handoff_request(raw_request)
            except (TypeError, ValueError) as exc:
                raise SessionConflict("local validation handoff reservation is invalid") from exc
            final, handoff = request["final_receipt"], request["handoff"]
            scope = final["scope"]
            epoch = self.require_current_backend_authority()
            if not self._acp or not self._acp_product_slots or session_id != scope["session_id"]:
                raise SessionConflict("local validation handoff does not name this Runtime session")
            binding = self._read_acp_binding(session_id)
            row = self._read_backend_local_validation_final({
                key: scope[key] for key in ("session_id", "trace_id", "owner_principal", "workspace_id")
            }, final)
            local = row["local_validation"]
            if local.get("handoff_receipt") != handoff:
                raise SessionConflict("Backend has not protected this exact local handoff")
            if (local.get("confirmation_receipt") is not None
                    and local["confirmation_receipt"].get("handoff") != handoff):
                raise SessionConflict("Backend already confirmed a different local handoff")
            if binding.get("schema_version") == _ACP_ROOT_BINDING_LOCAL_VALIDATION_HANDOFF_SCHEMA:
                intent = binding.get("local_validation_handoff_intent")
                observation = binding.get("local_validation_handoff_observation")
                if (binding.get("local_validation_handoff") != handoff or intent is None
                        or intent.get("final_receipt") != final):
                    raise SessionConflict("Runtime local handoff binding changed")
                if observation is not None:
                    _local_validate_handoff_observation(observation)
                    if (self.boot_id != handoff["new_authority"]["boot_id"]
                            or epoch != handoff["new_authority"]["epoch"]):
                        raise SessionConflict("Runtime handoff observation is outside the successor authority")
                    return {"state": "observed", "operation_id": handoff["operation_id"]}
            else:
                raw_path = self._acp_binding_path(session_id, scope["workspace_id"])
                raw_binding = self._read_locked_acp_binding_payload(raw_path)
                binding_scope = binding.get("operator_scope") or {
                    "workspace_id": binding["workspace_id"], "owner_principal": binding["owner_principal"],
                    "session_id": binding["session_id"], "trace_id": binding["trace_id"],
                    "root_run_id": binding["root_run_id"], "runtime_boot_id": binding["previous_boot_id"],
                    "generation_id": binding["runtime_generation"], "cwd_leaf": Path(binding["cwd"]).name,
                }
                pre_ack = binding.get("local_validation_pre_ack")
                if (binding.get("schema_version") != _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA
                        or binding_scope != scope or binding.get("root_run_id") != handoff["root_run_id"]
                        or binding.get("previous_boot_id") != handoff["old_authority"]["boot_id"]
                        or binding.get("previous_authority_epoch") != handoff["old_authority"]["epoch"]
                        or hashlib.sha256(raw_binding).hexdigest() != handoff["original_binding_sha256"]
                        or binding.get("settlement_receipt") is not None
                        or binding.get("domain_call_sequence") != binding.get("domain_call_drained_sequence")
                        or not isinstance(pre_ack, dict)
                        or pre_ack.get("terminal_event_receipt") != final["terminal_event_receipt"]
                        or pre_ack.get("cleanup_receipt_sha256") != final["cleanup_receipt_sha256"]
                        or row["local_validation"].get("runtime_observation") is not None):
                    raise SessionConflict("original stopped Runtime binding differs from the exact handoff")
            if (handoff["new_authority"]["boot_id"] != self.boot_id
                    or handoff["new_authority"]["epoch"] != epoch):
                raise SessionConflict("local validation handoff lease requires its exact successor authority")
            try:
                self._compatibility.product_slots.reserve_operator_fence(
                    scope, operation_id=handoff["operation_id"],
                    request_sha256=handoff["handoff_sha256"], allow_existing_live_lease=False)
            except Exception as exc:
                raise SessionConflict("current Runtime could not reserve the exact confirmation lease") from exc
            return {"state": "reserved", "operation_id": handoff["operation_id"]}
        if (isinstance(raw_request, dict)
                and raw_request.get("schema_version") == _R2_HANDOFF_REQUEST_SCHEMA):
            try:
                handoff_request = _r2_validate_handoff_request(raw_request)
                handoff, close = handoff_request["handoff"], handoff_request["close_receipt"]
            except _R2FenceContractError as exc:
                raise SessionConflict("operator cleanup handoff request is invalid") from exc
            scope = handoff["scope"]
            current_epoch = self.require_current_backend_authority()
            if (not self._acp_product_slots or scope["session_id"] != session_id
                    or handoff["new_authority"] != {"boot_id": self.boot_id, "epoch": current_epoch}):
                raise SessionConflict("handoff does not name current Runtime authority")
            binding = self._read_acp_binding(session_id)
            if (binding.get("schema_version") == _ACP_ROOT_BINDING_V3_SCHEMA
                    and isinstance(binding.get("operator_handoff_observation"), dict)):
                observation = binding["operator_handoff_observation"]
                if (observation.get("operation_id") == handoff["operation_id"]
                        and observation.get("handoff_sha256") == handoff["handoff_sha256"]
                        and observation.get("scope") == scope):
                    return {"state": "observed", "operation_id": handoff["operation_id"]}
                raise SessionConflict("Runtime already has another process-fence handoff observation")
            completed = close.get("operator_completed_cleanup")
            terminal = binding.get("settlement_receipt")
            raw_path = self._acp_binding_path(session_id, scope["workspace_id"])
            raw_binding = self._read_locked_acp_binding_payload(raw_path)
            if (binding.get("schema_version") != _ACP_ROOT_BINDING_V2_SCHEMA
                    or binding.get("operator_scope") != scope
                    or binding.get("root_run_id") != scope["root_run_id"]
                    or binding.get("previous_boot_id") != close["authority"]["previous_boot_id"]
                    or binding.get("previous_authority_epoch") != close["authority"]["previous_epoch"]
                    or handoff["old_authority"] != {"boot_id": close["authority"]["current_boot_id"],
                                                     "epoch": close["authority"]["current_epoch"]}
                    or not isinstance(terminal, dict)
                    or _r2_digest(terminal) != completed.get("original_terminal_receipt_sha256")
                    or terminal.get("sequence") != 344
                    or terminal.get("event_sha256") != "0763e967f42dc958edbf3fb832b1dc5f84b4dfc2455cc4a774debc763fe45e1e"
                    or hashlib.sha256(raw_binding).hexdigest() != handoff["runtime_binding_sha256"]
                    or binding.get("closed") is not False or binding.get("native_session_close_confirmed") is not True
                    or binding.get("process_exit_confirmed") is not False or binding.get("cleanup_unconfirmed") is not False
                    or binding.get("domain_call_sequence") != binding.get("domain_call_drained_sequence")
                    or handoff["preflight"]["binding_sha256"] != hashlib.sha256(raw_binding).hexdigest()
                    or not self._compatibility.product_slots):
                raise SessionConflict("original stopped Runtime binding differs from the exact handoff")
            try:
                self._compatibility.product_slots.reserve_operator_fence(
                    scope, operation_id=handoff["operation_id"],
                    request_sha256=handoff["handoff_sha256"], allow_existing_live_lease=False)
            except Exception as exc:
                raise SessionConflict("current Runtime could not reserve the exact handoff slot") from exc
            return {"state": "reserved", "operation_id": handoff["operation_id"]}
        cleanup_request = None
        if isinstance(raw_request, dict) and raw_request.get("schema_version") == _R2_COMPLETED_CLEANUP_REQUEST_SCHEMA:
            try:
                cleanup_request = _r2_validate_completed_cleanup_request(raw_request)
                if cleanup_request["process_fence_request"] != raw_request.get("process_fence_request"):
                    raise _R2FenceContractError("completed cleanup request inner request changed")
                request = cleanup_request["process_fence_request"]
            except _R2FenceContractError as exc:
                raise SessionConflict("completed cleanup reservation is invalid") from exc
        else:
            try:
                request = _r2_validate_request(raw_request)
            except _R2FenceContractError as exc:
                raise SessionConflict("operator process-fence request is invalid") from exc
        scope = request["scope"]
        if (not self._acp_product_slots or scope["session_id"] != session_id
                or request["authority"]["current_boot_id"] != self.boot_id
                or request["authority"]["current_epoch"] != self.require_current_backend_authority()):
            raise SessionConflict("operator process-fence reservation lacks current authority")
        binding = self._read_acp_binding(session_id)
        if binding.get("schema_version") == _ACP_ROOT_BINDING_V3_SCHEMA:
            observation = binding["operator_observation"]
            if (observation["operation_id"] != request["operation_id"]
                    or observation["scope"] != scope
                    or observation["runtime_binding_sha256"]
                    != request["runtime_binding_observation"]["raw_sha256"]):
                raise SessionConflict("operator process-fence retry targets another observation")
            return {"state": "observed", "operation_id": request["operation_id"]}
        if cleanup_request is not None:
            original_terminal = cleanup_request["original_terminal_receipt"]
            binding_valid = (
                binding.get("schema_version") == _ACP_ROOT_BINDING_V2_SCHEMA
                and binding.get("operator_scope") == scope
                and binding.get("operator_binding") == request["prestart_binding"]
                and binding.get("previous_authority_epoch") == request["authority"]["previous_epoch"]
                and binding.get("closed") is False
                and binding.get("native_session_close_confirmed") is True
                and binding.get("process_exit_confirmed") is False
                and binding.get("cleanup_unconfirmed") is False
                and binding.get("settlement_receipt") == original_terminal
                and binding.get("domain_call_sequence") == binding.get("domain_call_drained_sequence")
            )
        else:
            binding_valid = (
                binding.get("schema_version") == _ACP_ROOT_BINDING_V2_SCHEMA
                and binding.get("operator_scope") == scope
                and binding.get("operator_binding") == request["prestart_binding"]
                and binding.get("previous_authority_epoch") == request["authority"]["previous_epoch"]
                and binding.get("closed") is False
                and binding.get("native_session_close_confirmed") is False
                and binding.get("process_exit_confirmed") is False
                and binding.get("cleanup_unconfirmed") is False
            )
        if (not binding_valid
                ):
            raise SessionConflict("operator process-fence reservation binding changed")
        raw_path = self._acp_binding_path(session_id, scope["workspace_id"])
        actual_raw = self._read_locked_acp_binding_payload(raw_path)
        if (hashlib.sha256(actual_raw).hexdigest()
                != request["runtime_binding_observation"]["raw_sha256"]):
            raise SessionConflict("operator process-fence reservation binding bytes changed")
        from .acp_product_slot_client import ProductSlotError
        try:
            try:
                live = self._get(session_id)
            except KeyError:
                live = None
            if cleanup_request is not None and live is not None:
                raise SessionConflict("completed cleanup requires the exact cold Runtime binding")
            with live.lock if live is not None else nullcontext():
                if live is not None and not self._operator_live_scope_identity_exact(
                        live, binding, scope):
                    raise SessionConflict("operator process-fence existing lease changed")
                self._compatibility.product_slots.reserve_operator_fence(
                    scope, operation_id=request["operation_id"],
                    request_sha256=_r2_digest(request),
                    allow_existing_live_lease=live is not None)
        except ProductSlotError as exc:
            raise SessionConflict("operator process-fence Workspace slot is occupied") from exc
        return {"state": "reserved", "operation_id": request["operation_id"]}

    def acknowledge_terminal(self, session_id: str, receipt: object) -> dict:
        """Private Gateway acknowledgement of an exact Backend terminal receipt.

        This opens no domain capability: it permits the next root only after
        the previous BYQ root has been closed by Backend. Its retry receipt is
        bounded to the same Adapter boot.
        """
        if (isinstance(receipt, dict)
                and receipt.get("schema_version") == _R2_CLOSE_RECEIPT_SCHEMA):
            return self._acknowledge_operator_process_fence(session_id, receipt)
        if (isinstance(receipt, dict)
                and receipt.get("schema_version") == _R2_HANDOFF_REQUEST_SCHEMA):
            return self._acknowledge_operator_process_fence_handoff(session_id, receipt)
        if (isinstance(receipt, dict)
                and receipt.get("schema_version") == _LOCAL_VALIDATION_HANDOFF_REQUEST_SCHEMA):
            return self._acknowledge_local_validation_handoff(session_id, receipt)
        if (isinstance(receipt, dict)
                and receipt.get("schema_version") == _LOCAL_VALIDATION_ACK_REQUEST_SCHEMA):
            return self._acknowledge_local_validation(session_id, receipt)
        if (isinstance(receipt, dict)
                and receipt.get("schema_version") == _LOCAL_VALIDATION_PRE_ACK_SCHEMA):
            return self._stop_local_validation_pre_ack(session_id, receipt)
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
            if root in record.operator_superseded_terminal_receipts:
                raise SessionConflict("terminal receipt was superseded by an operator process-fence ACK")
            evidence = self._terminal_evidence_for(record, root)
            current_root = record.process_root_id
            if self._acp and root == current_root:
                binding = self._read_acp_binding(session_id)
                request = {"schema_version": _LOCAL_VALIDATION_PRE_ACK_SCHEMA,
                    "root_run_id": root, "session_id": session_id, "boot_id": self.boot_id}
                if self._read_backend_local_validation_pre_ack(record, request) is not None:
                    raise SessionConflict("local validation reservation requires its pre-ACK close branch")
                if (binding.get("schema_version") == _ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA
                        or binding.get("schema_version") == _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA
                        or self._backend_has_local_validation_final(record, root)):
                    raise SessionConflict("local validation Root requires its independent ACK branch")
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

    def _read_backend_local_validation_final(
        self, record: RuntimeSession | Mapping[str, str], requested_final: dict[str, Any],
    ) -> dict[str, Any] | None:
        identity = (record if isinstance(record, Mapping)
                    else {key: getattr(record, key) for key in (
                        "session_id", "workspace_id", "owner_principal", "trace_id")})
        token = os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
        if not token or not identity["workspace_id"] or not identity["owner_principal"]:
            raise SessionConflict("local validation Backend authority is unavailable")
        try:
            response = httpx.get(
                f"{self._backend_url.rstrip('/')}/internal/runtime-authority/sessions/"
                f"{quote(identity['session_id'], safe='')}/roots",
                headers={"Authorization": f"Bearer {token}",
                    "X-BYQ-Owner-Principal": identity["owner_principal"],
                    "X-BYQ-Workspace-ID": identity["workspace_id"],
                    "X-BYQ-Trace-ID": identity["trace_id"]}, timeout=2.0)
            response.raise_for_status()
            if len(response.content) > 64 * 1024:
                raise ValueError("Backend roots response is oversized")
            body = json.loads(response.content.decode("utf-8"),
                object_pairs_hook=_strict_json_object, parse_constant=_reject_json_constant)
        except (httpx.HTTPError, UnicodeError, ValueError, TypeError, RecursionError):
            raise SessionConflict("local validation Backend final is unavailable") from None
        if (not isinstance(body, dict) or set(body) != {"schema_version", "roots"}
                or body.get("schema_version") != "byq-business-root-status.v1"
                or not isinstance(body.get("roots"), list)):
            raise SessionConflict("local validation Backend roots projection is invalid")
        matches = [row for row in body["roots"] if isinstance(row, dict)
                   and row.get("root_run_id") == requested_final["root_run_id"]]
        if len(matches) != 1:
            raise SessionConflict("local validation Backend final Root is unavailable")
        row = matches[0]
        local = row.get("local_validation")
        if (not isinstance(local, dict)
                or set(local) != {"final_receipt", "runtime_observation", "confirmation_receipt", "handoff_receipt"}
                or local.get("final_receipt") != requested_final
                or row.get("authority_status") != "closed"
                or row.get("status") not in {"completed", "failed", "cancelled", "interrupted"}
                or row.get("terminal_sequence") != requested_final["terminal_event_receipt"]["sequence"]
                or row.get("terminal_event_sha256") != requested_final["terminal_event_receipt"]["event_sha256"]
                or row.get("terminal_acp_ingress_sequence")
                   != requested_final["terminal_acp_ingress_sequence"]
                or row.get("terminal_acp_ingress_sha256")
                   != requested_final["terminal_acp_ingress_sha256"]
                or row.get("terminal_unknown_claim_count")
                   != requested_final["terminal_unknown_claim_count"]
                or row.get("terminal_unknown_claims_sha256")
                   != requested_final["terminal_unknown_claims_sha256"]):
            raise SessionConflict("local validation Backend final differs from the exact Root")
        if local["handoff_receipt"] is not None:
            try:
                checked_handoff = _local_validate_handoff(local["handoff_receipt"], final_receipt=requested_final)
            except (TypeError, ValueError) as exc:
                raise SessionConflict("Backend local validation handoff projection is invalid") from exc
            if checked_handoff != local["handoff_receipt"]:
                raise SessionConflict("Backend local validation handoff projection changed")
        scope = requested_final["scope"]
        if (scope["session_id"] != identity["session_id"] or scope["trace_id"] != identity["trace_id"]
                or scope["owner_principal"] != identity["owner_principal"]
                or scope["workspace_id"] != identity["workspace_id"]):
            raise SessionConflict("local validation final scope differs from the Runtime session")
        return row

    def _backend_has_local_validation_final(self, record: RuntimeSession, root_run_id: str) -> bool:
        """Identify a reserved local final before an ordinary ACK can release its lease."""
        token = os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
        if not token or not record.workspace_id or not record.owner_principal:
            raise SessionConflict("Backend authority is unavailable for terminal ACK classification")
        try:
            response = httpx.get(
                f"{self._backend_url.rstrip('/')}/internal/runtime-authority/sessions/"
                f"{quote(record.session_id, safe='')}/roots",
                headers={"Authorization": f"Bearer {token}",
                    "X-BYQ-Owner-Principal": record.owner_principal,
                    "X-BYQ-Workspace-ID": record.workspace_id,
                    "X-BYQ-Trace-ID": record.trace_id}, timeout=2.0)
            response.raise_for_status()
            if len(response.content) > 64 * 1024:
                raise ValueError("Backend roots response is oversized")
            body = json.loads(response.content.decode("utf-8"),
                object_pairs_hook=_strict_json_object, parse_constant=_reject_json_constant)
        except (httpx.HTTPError, UnicodeError, ValueError, TypeError, RecursionError):
            raise SessionConflict("Backend terminal ACK classification is unavailable") from None
        if (not isinstance(body, dict) or set(body) != {"schema_version", "roots"}
                or body.get("schema_version") != "byq-business-root-status.v1"
                or not isinstance(body.get("roots"), list)):
            raise SessionConflict("Backend terminal ACK classification is invalid")
        rows = [row for row in body["roots"] if isinstance(row, dict)
                and row.get("root_run_id") == root_run_id]
        if len(rows) != 1:
            raise SessionConflict("Backend terminal Root is unavailable for ACK classification")
        local = rows[0].get("local_validation")
        if local is None:
            return False
        if (not isinstance(local, dict)
                or set(local) not in ({"final_receipt", "runtime_observation", "confirmation_receipt"},
                    {"final_receipt", "runtime_observation", "confirmation_receipt", "handoff_receipt"})):
            raise SessionConflict("Backend local validation projection is malformed")
        try:
            final = _local_validate_final(local["final_receipt"])
        except (TypeError, ValueError):
            raise SessionConflict("Backend local validation final is malformed") from None
        if (final["root_run_id"] != root_run_id
                or final["scope"]["session_id"] != record.session_id
                or final["scope"]["trace_id"] != record.trace_id
                or final["scope"]["owner_principal"] != record.owner_principal
                or final["scope"]["workspace_id"] != record.workspace_id):
            raise SessionConflict("Backend local validation final scope changed")
        if "handoff_receipt" in local and local["handoff_receipt"] is not None:
            try:
                handoff = _local_validate_handoff(local["handoff_receipt"], final_receipt=final)
            except (TypeError, ValueError) as exc:
                raise SessionConflict("Backend local validation handoff projection changed") from exc
            if (handoff != local["handoff_receipt"]
                    or (local.get("confirmation_receipt") is not None
                        and local["confirmation_receipt"].get("handoff") != handoff)):
                raise SessionConflict("Backend local validation handoff projection is inconsistent")
        return True

    def _read_backend_operator_handoff_confirmation(
        self, binding: Mapping[str, Any], handoff_request: dict[str, Any],
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        """Require Backend's durable handoff ACK before consuming an old V3 handoff."""
        token = os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
        if not token or not binding.get("workspace_id") or not binding.get("owner_principal"):
            raise SessionConflict("Backend handoff confirmation is unavailable")
        handoff, close = handoff_request["handoff"], handoff_request["close_receipt"]
        completed = close["operator_completed_cleanup"]
        try:
            response = httpx.get(
                f"{self._backend_url.rstrip('/')}/internal/runtime-authority/sessions/"
                f"{quote(binding['session_id'], safe='')}/roots",
                headers={"Authorization": f"Bearer {token}",
                    "X-BYQ-Owner-Principal": binding["owner_principal"],
                    "X-BYQ-Workspace-ID": binding["workspace_id"],
                    "X-BYQ-Trace-ID": binding["trace_id"]}, timeout=2.0)
            response.raise_for_status()
            if len(response.content) > 64 * 1024:
                raise ValueError("Backend roots response is oversized")
            body = json.loads(response.content.decode("utf-8"),
                object_pairs_hook=_strict_json_object, parse_constant=_reject_json_constant)
        except (httpx.HTTPError, UnicodeError, ValueError, TypeError, RecursionError):
            raise SessionConflict("Backend handoff confirmation is unavailable") from None
        if (not isinstance(body, dict) or set(body) != {"schema_version", "roots"}
                or body.get("schema_version") != "byq-business-root-status.v1"
                or not isinstance(body.get("roots"), list)):
            raise SessionConflict("Backend handoff projection is invalid")
        roots = [row for row in body["roots"] if isinstance(row, dict)
                 and row.get("root_run_id") == handoff["root_run_id"]]
        if len(roots) != 1:
            raise SessionConflict("Backend handoff Root is unavailable")
        row = roots[0]
        expected_row = {
            "root_run_id": handoff["root_run_id"], "status": "completed", "authority_status": "closed",
            "terminal_sequence": 344,
            "terminal_event_sha256": "0763e967f42dc958edbf3fb832b1dc5f84b4dfc2455cc4a774debc763fe45e1e",
            "terminal_acp_ingress_sequence": completed["terminal_acp_ingress_sequence"],
            "terminal_acp_ingress_sha256": completed["terminal_acp_ingress_sha256"],
            "terminal_unknown_claim_count": 0,
            "terminal_unknown_claims_sha256": completed["terminal_unknown_claims_sha256"],
        }
        row_fields = set(expected_row) | {"operator_process_fence"}
        if (set(row) != row_fields
                or any(row.get(key) != value for key, value in expected_row.items())):
            raise SessionConflict("Backend handoff Root differs from the completed terminal")
        fence = row.get("operator_process_fence")
        if not isinstance(fence, dict):
            raise SessionConflict("Backend handoff ACK is still pending")
        try:
            confirmation = _r2_validate_handoff_confirmation(
                fence.get("handoff_confirmation"), handoff=handoff)
        except (_R2FenceContractError, TypeError, ValueError):
            raise SessionConflict("Backend handoff confirmation is invalid") from None
        expected_fence = {
            "schema_version": "byq-business-root-operator-process-fence.v1",
            "operation_id": handoff["operation_id"], "outcome": "completed",
            "ack_status": "confirmed", "slot_release_status": "released",
            "process_fence_receipt_sha256": handoff["process_fence_receipt_sha256"],
            "operator_completed_cleanup_receipt_sha256": completed["receipt_sha256"],
            "close_receipt_sha256": handoff["close_receipt_sha256"],
            "runtime_ack_sha256": _r2_digest(observation),
            "proof_receipt_sha256": handoff["proof_receipt_sha256"],
            "ack_receipt_sha256": confirmation["receipt_sha256"], "superseded_terminal": None,
            "original_terminal_receipt_sha256": handoff["terminal_receipt_sha256"],
            "scope": handoff["scope"],
            "terminal_acp_ingress_sequence": completed["terminal_acp_ingress_sequence"],
            "terminal_acp_ingress_sha256": completed["terminal_acp_ingress_sha256"],
            "terminal_unknown_claim_count": completed["terminal_unknown_claim_count"],
            "terminal_unknown_claims_sha256": completed["terminal_unknown_claims_sha256"],
            "handoff_receipt_sha256": handoff["handoff_sha256"], "handoff": handoff,
            "close_receipt": close, "runtime_observation": observation,
            "handoff_confirmation": confirmation,
        }
        if (not isinstance(fence, dict) or fence != expected_fence
                or confirmation["runtime_observation"] != observation
                or confirmation["proof_receipt_sha256"] != handoff["proof_receipt_sha256"]
                or confirmation["close_receipt_sha256"] != handoff["close_receipt_sha256"]):
            raise SessionConflict("Backend handoff confirmation differs from the exact handoff")
        return confirmation

    def _read_backend_local_validation_pre_ack(
        self, record: RuntimeSession, request: dict[str, Any],
    ) -> dict[str, Any]:
        token = os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
        if not token or not record.owner_principal or not record.workspace_id:
            raise SessionConflict("local validation Backend reservation authority is unavailable")
        try:
            response = httpx.get(
                f"{self._backend_url.rstrip('/')}/internal/runtime-authority/sessions/"
                f"{quote(record.session_id, safe='')}/roots",
                headers={"Authorization": f"Bearer {token}",
                    "X-BYQ-Owner-Principal": record.owner_principal,
                    "X-BYQ-Workspace-ID": record.workspace_id,
                    "X-BYQ-Trace-ID": record.trace_id}, timeout=2.0)
            response.raise_for_status()
            if len(response.content) > 64 * 1024:
                raise ValueError("Backend roots response is oversized")
            body = json.loads(response.content.decode("utf-8"),
                object_pairs_hook=_strict_json_object, parse_constant=_reject_json_constant)
        except (httpx.HTTPError, UnicodeError, ValueError, TypeError, RecursionError):
            raise SessionConflict("local validation Backend reservation is unavailable") from None
        if (not isinstance(body, dict) or set(body) != {"schema_version", "roots"}
                or body.get("schema_version") != "byq-business-root-status.v1"
                or not isinstance(body.get("roots"), list)):
            raise SessionConflict("local validation Backend reservation projection is invalid")
        matches = [row for row in body["roots"] if isinstance(row, dict)
                   and row.get("root_run_id") == request["root_run_id"]]
        if len(matches) != 1:
            raise SessionConflict("local validation Backend reservation Root is unavailable")
        row = matches[0]
        if row.get("local_validation") is not None:
            return None
        candidate = row.get("local_validation_pre_ack")
        if candidate is None:
            return None
        if (row.get("status") != "active" or row.get("authority_status") != "active"
                or row.get("terminal_sequence") is not None or row.get("terminal_event_sha256") is not None):
            raise SessionConflict("local validation Root is not exactly pre-final")
        try:
            evidence = _local_validate_pre_ack_evidence(
                candidate, request=request)
        except (TypeError, ValueError):
            raise SessionConflict("Backend local validation reservation or callback proof is malformed") from None
        reservation = evidence["reservation"]
        scope = reservation["scope"]
        if (scope["owner_principal"] != record.owner_principal
                or scope["workspace_id"] != record.workspace_id
                or scope["session_id"] != record.session_id
                or scope["trace_id"] != record.trace_id
                or scope["generation"] != record.runtime_generation
                or reservation["authority_boot_id"] != self.boot_id
                or record.authority_epoch is None):
            raise SessionConflict("Backend local validation reservation differs from live Runtime scope")
        return evidence

    def _stop_local_validation_pre_ack(self, session_id: str, raw_request: object) -> dict[str, Any]:
        try:
            request = _local_validate_pre_ack_request(raw_request)
        except (TypeError, ValueError) as exc:
            raise SessionConflict("local validation pre-ACK request is malformed") from exc
        if (not self._acp or not self._acp_product_slots or request["session_id"] != session_id
                or request["boot_id"] != self.boot_id):
            raise SessionConflict("local validation pre-ACK request scope is unavailable")
        try:
            record = self._get(session_id)
        except KeyError as exc:
            raise SessionConflict("local validation pre-ACK requires the live Runtime record") from exc
        with record.lock:
            epoch = self.require_current_backend_authority()
            if (record.boot_id != self.boot_id or record.authority_epoch != epoch
                    or record.process_root_id != request["root_run_id"]
                    or record.domain_call_sequence != record.domain_call_drained_sequence
                    or record.active_run is not None or record.status in SessionStatus.ACTIVE_PROMPT
                    or record.owner_principal is None or record.workspace_id is None):
                raise SessionConflict("local validation Runtime Root is not terminal and drained")
            evidence = self._terminal_evidence_for(record, request["root_run_id"])
            if evidence.get("boot_id") != self.boot_id:
                raise SessionConflict("local validation Runtime terminal belongs to another boot")
            projection = self._read_backend_local_validation_pre_ack(record, request)
            reservation, callback = projection["reservation"], projection["callback_exit"]
            binding = self._read_acp_binding(session_id)
            scope = binding.get("operator_scope")
            if scope is None:
                scope = {"workspace_id": binding["workspace_id"],
                    "owner_principal": binding["owner_principal"], "session_id": binding["session_id"],
                    "trace_id": binding["trace_id"], "root_run_id": binding["root_run_id"],
                    "runtime_boot_id": binding["previous_boot_id"],
                    "generation_id": binding["runtime_generation"], "cwd_leaf": Path(binding["cwd"]).name}
            if (binding.get("schema_version") not in {"byq-acp-root-binding.v1", _ACP_ROOT_BINDING_V2_SCHEMA,
                    _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA}
                    or binding.get("root_run_id") != request["root_run_id"]
                    or binding.get("session_id") != session_id
                    or binding.get("previous_boot_id") != self.boot_id
                    or binding.get("previous_authority_epoch") != epoch
                    or binding.get("runtime_generation") != record.runtime_generation
                    or binding.get("closed") is not False or binding.get("settlement_receipt") is not None
                    or binding.get("domain_call_sequence") != record.domain_call_sequence
                    or binding.get("domain_call_drained_sequence") != record.domain_call_drained_sequence
                    or scope.get("workspace_id") != record.workspace_id
                    or scope.get("owner_principal") != record.owner_principal
                    or scope.get("session_id") != session_id or scope.get("trace_id") != record.trace_id
                    or scope.get("root_run_id") != request["root_run_id"]
                    or scope.get("runtime_boot_id") != self.boot_id
                    or scope.get("generation_id") != record.runtime_generation
                    or callback["root_run_id"] != request["root_run_id"]
                    or callback["scope"] != reservation["scope"]
                    or reservation["scope"]["owner_principal"] != record.owner_principal
                    or reservation["scope"]["workspace_id"] != record.workspace_id
                    or reservation["scope"]["trace_id"] != record.trace_id
                    or reservation["scope"]["generation"] != record.runtime_generation):
                raise SessionConflict("local validation pre-ACK binding or reservation scope changed")
            if not self._compatibility.product_slots.owns(scope):
                raise SessionConflict("local validation pre-ACK Workspace slot lease is not exact and live")
            existing_stop = binding.get("local_validation_pre_ack")
            if existing_stop is not None:
                try:
                    existing_stop = _local_validate_pre_ack_stop(existing_stop, allow_stopping=True)
                except (TypeError, ValueError) as exc:
                    raise SessionConflict("local validation pre-ACK stop binding is malformed") from exc
                if (existing_stop["root_run_id"] != request["root_run_id"]
                        or existing_stop["reservation_sha256"] != reservation["reservation_sha256"]
                        or existing_stop["callback_exit_sha256"] != callback["receipt_sha256"]
                        or existing_stop["terminal_event_receipt"] != evidence["receipt"]):
                    raise SessionConflict("local validation pre-ACK retry changed its exact proof")
                stop = existing_stop
            else:
                if (binding.get("process_exit_confirmed") is not False
                        or binding.get("native_session_close_confirmed") is not False):
                    raise SessionConflict("pre-final process already stopped without its durable local proof")
                base = {"schema_version": _LOCAL_VALIDATION_PRE_ACK_STOP_SCHEMA,
                    "root_run_id": request["root_run_id"],
                    "reservation_sha256": reservation["reservation_sha256"],
                    "callback_exit_sha256": callback["receipt_sha256"],
                    "terminal_event_receipt": evidence["receipt"],
                    "state": "stopping", "cleanup_receipt_sha256": None}
                stop = base | {"stop_sha256": _r2_digest(base)}
                self._write_local_validation_pre_ack_binding(session_id, binding, stop)
            terminal = {"schema_version": "byq-runtime-terminal-evidence.v1",
                "session_id": session_id, "boot_id": self.boot_id,
                "root_run_id": request["root_run_id"], "sequence": evidence["sequence"],
                "outcome": evidence["outcome"], "receipt": evidence["receipt"]}

        if stop["state"] != "stopped":
            self._close_acp_after_terminal_ack(record, request["root_run_id"], evidence["receipt"],
                                               local_validation_pre_ack=stop)
        with record.lock:
            if (record.current_generation is None or record.current_generation.process_root_id != request["root_run_id"]
                    or not record.process_closed or not record.current_generation.process_exit_confirmed
                    or record.current_generation.process_closing):
                raise SessionConflict("local validation native process exit is unconfirmed")
            try:
                cleanup, cleanup_sha = self._compatibility.verify_local_validation_cleanup(scope)
            except (OSError, ValueError, RuntimeError) as exc:
                raise SessionConflict("local validation signed cleanup is unavailable after stop") from exc
            if cleanup.get("cleanup") != "proven":
                raise SessionConflict("local validation signed cleanup does not prove runner exit")
            from packages.contracts.acp_product_slot import PRODUCT_CLEANUP_RECEIPT_DIRECTORY, PRODUCT_CLEANUP_RECEIPT_MAX_BYTES
            raw_path = Path(self._compatibility.product_slots.assert_workspace(
                scope["workspace_id"]).socket_path).parent / PRODUCT_CLEANUP_RECEIPT_DIRECTORY / (
                product_scope_digest(scope) + ".json")
            try:
                fd = os.open(raw_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > PRODUCT_CLEANUP_RECEIPT_MAX_BYTES:
                        raise OSError("unsafe cleanup receipt")
                    raw_cleanup = bytearray()
                    while len(raw_cleanup) <= PRODUCT_CLEANUP_RECEIPT_MAX_BYTES:
                        block = os.read(fd, min(4096, PRODUCT_CLEANUP_RECEIPT_MAX_BYTES + 1 - len(raw_cleanup)))
                        if not block:
                            break
                        raw_cleanup.extend(block)
                finally:
                    os.close(fd)
            except OSError as exc:
                raise SessionConflict("local validation raw signed cleanup bytes are unavailable") from exc
            if (len(raw_cleanup) > PRODUCT_CLEANUP_RECEIPT_MAX_BYTES
                    or not hmac.compare_digest(hashlib.sha256(raw_cleanup).hexdigest(), cleanup_sha)):
                raise SessionConflict("local validation raw cleanup bytes changed after verification")
            record.cleanup_unconfirmed = False
            stopped_base = dict(stop)
            stopped_base.update(state="stopped", cleanup_receipt_sha256=cleanup_sha)
            stopped_base.pop("stop_sha256")
            stopped = stopped_base | {"stop_sha256": _r2_digest(stopped_base)}
            self._write_local_validation_pre_ack_binding(session_id,
                self._read_acp_binding(session_id), stopped, expected_previous=stop)
            projection = self._local_validation_terminal_projection(record, terminal)
            return {"schema_version": "byq-local-validation-pre-ack-stop-result.v1",
                "root_run_id": request["root_run_id"],
                "cleanup_receipt_raw_b64": base64.b64encode(raw_cleanup).decode("ascii"),
                "cleanup_receipt_sha256": cleanup_sha,
                "runtime_binding_sha256": projection["binding_sha256"]}

    def _write_local_validation_pre_ack_binding(
        self, session_id: str, previous: dict[str, Any], stop: dict[str, Any],
        *, expected_previous: dict[str, Any] | None = None,
    ) -> None:
        checked = _local_validate_pre_ack_stop(stop, allow_stopping=True)
        path = self._acp_binding_path(session_id, previous["workspace_id"])
        fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            if self.require_current_backend_authority() != previous["previous_authority_epoch"]:
                raise SessionConflict("local validation pre-ACK binding writer lost authority")
            raw = self._read_locked_acp_binding_payload(path)
            current = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_json_object,
                                 parse_constant=_reject_json_constant)
            if current.get("schema_version") == "byq-acp-root-binding.v1":
                current.setdefault("native_session_close_confirmed", False)
                current.setdefault("process_exit_confirmed", False)
                current.setdefault("cleanup_unconfirmed", False)
            if (current != previous or expected_previous is not None
                    and current.get("local_validation_pre_ack") != expected_previous):
                raise SessionConflict("local validation pre-ACK binding changed before write")
            updated = dict(current)
            updated["schema_version"] = _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA
            updated["local_validation_pre_ack"] = checked
            if checked["state"] == "stopped":
                updated["cleanup_unconfirmed"] = False
            payload = json.dumps(updated, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self._replace_acp_binding_payload(path, payload)
            if (not hmac.compare_digest(self._read_locked_acp_binding_payload(path), payload)
                    or self.require_current_backend_authority() != previous["previous_authority_epoch"]):
                raise SessionConflict("local validation pre-ACK binding write is uncertain")
            self._read_acp_binding(session_id)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _acknowledge_local_validation_handoff(
        self, session_id: str, raw_request: object,
    ) -> dict[str, Any]:
        try:
            request = _local_validate_handoff_request(raw_request)
        except (TypeError, ValueError) as exc:
            raise SessionConflict("local validation handoff ACK is invalid") from exc
        final, handoff = request["final_receipt"], request["handoff"]
        scope = final["scope"]
        epoch = self.require_current_backend_authority()
        if (not self._acp or not self._acp_product_slots or session_id != scope["session_id"]
                ):
            raise SessionConflict("local validation handoff ACK is outside current Runtime authority")
        identity = {key: scope[key] for key in ("session_id", "trace_id", "owner_principal", "workspace_id")}
        row = self._read_backend_local_validation_final(identity, final)
        local = row["local_validation"]
        if local.get("handoff_receipt") != handoff:
            raise SessionConflict("Backend has not protected this exact local handoff")
        prior_confirmation = local.get("confirmation_receipt")
        if prior_confirmation is not None and prior_confirmation.get("handoff") != handoff:
            raise SessionConflict("Backend has a conflicting local validation handoff confirmation")
        binding = self._read_acp_binding(session_id)
        schema = binding.get("schema_version")
        observation = None
        if schema == _ACP_ROOT_BINDING_LOCAL_VALIDATION_HANDOFF_SCHEMA:
            if binding.get("local_validation_handoff") != handoff:
                raise SessionConflict("durable Runtime handoff differs from request")
            intent = _local_validate_handoff_intent(binding.get("local_validation_handoff_intent"))
            if intent.get("final_receipt") != final:
                raise SessionConflict("durable Runtime handoff intent differs from final")
            observation = binding.get("local_validation_handoff_observation")
            if observation is not None:
                observation = _local_validate_handoff_observation(observation)
                if (self.boot_id != handoff["new_authority"]["boot_id"]
                        or epoch != handoff["new_authority"]["epoch"]):
                    raise SessionConflict("Runtime handoff observation is outside the successor authority")
        elif schema == _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA:
            raw_path = self._acp_binding_path(session_id, scope["workspace_id"])
            raw = self._read_locked_acp_binding_payload(raw_path)
            if (hashlib.sha256(raw).hexdigest() != handoff["original_binding_sha256"]
                    or binding.get("root_run_id") != handoff["root_run_id"]
                    or binding.get("previous_boot_id") != handoff["old_authority"]["boot_id"]
                    or binding.get("previous_authority_epoch") != handoff["old_authority"]["epoch"]
                    or binding.get("settlement_receipt") is not None
                    or binding.get("domain_call_sequence") != binding.get("domain_call_drained_sequence")
                    or binding.get("local_validation_pre_ack", {}).get("terminal_event_receipt")
                       != final["terminal_event_receipt"]
                    or binding.get("local_validation_pre_ack", {}).get("cleanup_receipt_sha256")
                       != final["cleanup_receipt_sha256"]):
                raise SessionConflict("original Runtime binding changed before handoff intent")
            base = {"schema_version": _LOCAL_VALIDATION_HANDOFF_INTENT_SCHEMA,
                "handoff": handoff, "final_receipt": final, "runtime_boot_id": self.boot_id,
                "runtime_authority_epoch": epoch,
                "domain_call_sequence": binding["domain_call_sequence"],
                "domain_call_drained_sequence": binding["domain_call_drained_sequence"]}
            intent = _local_validate_handoff_intent(base | {"intent_sha256": _r2_digest(base)})
            path = self._acp_binding_path(session_id, scope["workspace_id"])
            lock_fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                current_raw = self._read_locked_acp_binding_payload(path)
                if (hashlib.sha256(current_raw).hexdigest() != handoff["original_binding_sha256"]
                        or json.loads(current_raw.decode("utf-8"), object_pairs_hook=_strict_json_object) != binding
                        or self.require_current_backend_authority() != epoch):
                    raise SessionConflict("original binding changed before durable handoff intent")
                updated = dict(binding)
                updated["schema_version"] = _ACP_ROOT_BINDING_LOCAL_VALIDATION_HANDOFF_SCHEMA
                updated["settlement_receipt"] = final["terminal_event_receipt"]
                updated["local_validation_handoff"] = handoff
                updated["local_validation_handoff_intent"] = intent
                payload = json.dumps(updated, sort_keys=True, separators=(",", ":")).encode("utf-8")
                self._replace_acp_binding_payload(path, payload)
                binding = self._read_acp_binding(session_id)
                if (self._read_locked_acp_binding_payload(path) != payload
                        or binding.get("local_validation_handoff_intent") != intent):
                    raise SessionConflict("Runtime handoff intent persistence is uncertain")
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
        else:
            raise SessionConflict("local validation handoff requires the exact pre-ACK binding")

        if observation is not None:
            if self._compatibility.product_slots.owns(scope):
                try:
                    cleanup, cleanup_sha = self._compatibility.verify_local_validation_cleanup(scope)
                    if cleanup.get("cleanup") != "proven" or cleanup_sha != handoff["cleanup_receipt_sha256"]:
                        raise SessionConflict("signed local cleanup changed before lease release")
                    def verify_durable_observation() -> None:
                        path = self._acp_binding_path(session_id, scope["workspace_id"])
                        lock_fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT
                                          | getattr(os, "O_NOFOLLOW", 0), 0o600)
                        try:
                            fcntl.flock(lock_fd, fcntl.LOCK_EX)
                            current_raw = self._read_locked_acp_binding_payload(path)
                            current = json.loads(current_raw.decode("utf-8"),
                                object_pairs_hook=_strict_json_object, parse_constant=_reject_json_constant)
                            if (current.get("schema_version") != _ACP_ROOT_BINDING_LOCAL_VALIDATION_HANDOFF_SCHEMA
                                    or current.get("local_validation_handoff") != handoff
                                    or current.get("local_validation_handoff_intent") != intent
                                    or current.get("local_validation_handoff_observation") != observation
                                    or self.require_current_backend_authority() != epoch):
                                raise SessionConflict("durable handoff observation changed before lease retry")
                        finally:
                            fcntl.flock(lock_fd, fcntl.LOCK_UN)
                            os.close(lock_fd)
                    self._compatibility.product_slots.release_local_validation_ack(
                        scope, cleanup_receipt_sha256=cleanup_sha,
                        persist_observation=verify_durable_observation,
                        operation_id=handoff["operation_id"], request_sha256=handoff["handoff_sha256"])
                except (OSError, ValueError, RuntimeError) as exc:
                    raise SessionConflict("exact local handoff lease release is unconfirmed") from exc
            return {"runtime_handoff_observation": observation}

        if (handoff["new_authority"]["boot_id"] != self.boot_id
                or handoff["new_authority"]["epoch"] != epoch):
            raise SessionConflict("handoff release requires the exact successor authority")

        try:
            cleanup, cleanup_sha = self._compatibility.verify_local_validation_cleanup(scope)
            if cleanup.get("cleanup") != "proven" or cleanup_sha != handoff["cleanup_receipt_sha256"]:
                raise SessionConflict("signed local cleanup differs from the protected final")
            if not self._compatibility.product_slots.owns(scope):
                raise SessionConflict("new exact confirmation lease or cleanup fields are unavailable")
        except (OSError, ValueError, RuntimeError) as exc:
            raise SessionConflict("signed local cleanup or confirmation lease is unavailable") from exc
        obs_base = {"schema_version": _LOCAL_VALIDATION_HANDOFF_OBSERVATION_SCHEMA,
            "ack_intent": intent, "slot_scope_sha256": product_scope_digest(scope),
            "cleanup_receipt_sha256": cleanup_sha, "state": "released"}
        observation = _local_validate_handoff_observation(
            obs_base | {"observation_sha256": _r2_digest(obs_base)})

        def persist_observation() -> None:
            path = self._acp_binding_path(session_id, scope["workspace_id"])
            lock_fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                raw = self._read_locked_acp_binding_payload(path)
                current = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_json_object,
                                     parse_constant=_reject_json_constant)
                if (current.get("schema_version") != _ACP_ROOT_BINDING_LOCAL_VALIDATION_HANDOFF_SCHEMA
                        or current.get("local_validation_handoff") != handoff
                        or current.get("local_validation_handoff_intent") != intent
                        or current.get("local_validation_handoff_observation") not in (None, observation)
                        or self.require_current_backend_authority() != epoch):
                    raise SessionConflict("local handoff binding changed before release observation")
                current["local_validation_handoff_observation"] = observation
                payload = json.dumps(current, sort_keys=True, separators=(",", ":")).encode("utf-8")
                self._replace_acp_binding_payload(path, payload)
                if self._read_locked_acp_binding_payload(path) != payload:
                    raise SessionConflict("local handoff release observation persistence is uncertain")
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)

        try:
            released = self._compatibility.product_slots.release_local_validation_ack(
                scope, cleanup_receipt_sha256=cleanup_sha, persist_observation=persist_observation,
                operation_id=handoff["operation_id"], request_sha256=handoff["handoff_sha256"])
        except (OSError, ValueError, RuntimeError) as exc:
            raise SessionConflict("local handoff slot release is unconfirmed") from exc
        if not released:
            raise SessionConflict("local handoff lease is absent without a durable observation")
        readback = self._read_acp_binding(session_id)
        if readback.get("local_validation_handoff_observation") != observation:
            raise SessionConflict("local handoff release observation is not durable")
        return {"runtime_handoff_observation": observation}

    def _acknowledge_local_validation(self, session_id: str, raw_request: object) -> dict[str, Any]:
        try:
            request = _local_validate_ack_request(raw_request)
        except (TypeError, ValueError) as exc:
            raise SessionConflict("local validation ACK request is invalid") from exc
        final = request["final_receipt"]
        scope = final["scope"]
        if (not self._acp or not self._acp_product_slots
                or session_id != scope["session_id"]
                or scope["runtime_boot_id"] != self.boot_id):
            raise SessionConflict("local validation ACK scope is unavailable")
        try:
            record = self._get(session_id)
        except KeyError as exc:
            raise SessionConflict("local validation ACK requires the live Runtime record") from exc
        with record.lock:
            epoch = self.require_current_backend_authority()
            row = self._read_backend_local_validation_final(record, final)
            evidence = self._terminal_evidence_for(record, scope["root_run_id"])
            if (record.boot_id != self.boot_id or record.authority_epoch != epoch
                    or evidence.get("boot_id") != self.boot_id
                    or evidence.get("receipt") != final["terminal_event_receipt"]
                    or record.process_root_id != scope["root_run_id"]
                    or record.trace_id != scope["trace_id"]
                    or record.owner_principal != scope["owner_principal"]
                    or record.workspace_id != scope["workspace_id"]
                    or record.runtime_generation != scope["generation_id"]
                    or record.domain_call_sequence != record.domain_call_drained_sequence
                    or record.active_run is not None
                    or record.status in SessionStatus.ACTIVE_PROMPT):
                raise SessionConflict("local validation terminal or Runtime drain changed")
            binding = self._read_acp_binding(session_id)
            binding_scope = binding.get("operator_scope")
            if (binding.get("schema_version") == "byq-acp-root-binding.v1"
                    or binding.get("schema_version") in {_ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA,
                                                            _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA}
                    and "operator_scope" not in binding):
                binding_scope = {
                    "workspace_id": binding["workspace_id"],
                    "owner_principal": binding["owner_principal"],
                    "session_id": binding["session_id"], "trace_id": binding["trace_id"],
                    "root_run_id": binding["root_run_id"],
                    "runtime_boot_id": binding["previous_boot_id"],
                    "generation_id": binding["runtime_generation"],
                    "cwd_leaf": Path(binding["cwd"]).name,
                }
            if (binding.get("root_run_id") != scope["root_run_id"]
                    or binding_scope != scope
                    or binding.get("runtime_generation") != scope["generation_id"]
                    or binding.get("previous_boot_id") != self.boot_id
                    or binding.get("previous_authority_epoch") != epoch
                    or binding.get("closed") is not False
                    or binding.get("domain_call_sequence") != record.domain_call_sequence
                    or binding.get("domain_call_drained_sequence") != record.domain_call_drained_sequence):
                raise SessionConflict("local validation binding does not match the exact Runtime Root")
            projection = self._local_validation_terminal_projection(record, evidence)
            if (projection["binding_sha256"] != final["runtime_binding_sha256"]
                    or _r2_digest(projection) != final["runtime_projection_sha256"]):
                raise SessionConflict("local validation terminal projection changed")
            try:
                cleanup, cleanup_sha = self._compatibility.verify_local_validation_cleanup(scope)
            except (OSError, ValueError, RuntimeError) as exc:
                raise SessionConflict("local validation signed cleanup is unavailable") from exc
            if cleanup.get("cleanup") != "proven" or cleanup_sha != final["cleanup_receipt_sha256"]:
                raise SessionConflict("local validation cleanup does not match the Backend final")

            if binding["schema_version"] == _ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA:
                intent = binding["local_validation_ack_intent"]
                if intent["final_receipt"] != final:
                    raise SessionConflict("local validation ACK retry changed its final receipt")
                observation = binding.get("local_validation_release_observation")
                if (intent["runtime_authority_epoch"] != epoch
                        or intent["runtime_boot_id"] != self.boot_id
                        or intent["final_live_sequence"] != record.sequence
                        or intent["domain_call_sequence"] != record.domain_call_sequence
                        or intent["domain_call_drained_sequence"] != record.domain_call_drained_sequence):
                    raise SessionConflict("local validation ACK retry changed Runtime facts")
            else:
                if (binding["schema_version"] not in {
                        "byq-acp-root-binding.v1", _ACP_ROOT_BINDING_V2_SCHEMA,
                        _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA}
                        or binding.get("settlement_receipt") not in (None, final["terminal_event_receipt"])):
                    raise SessionConflict("local validation pre-ACK binding hash changed")
                if binding["schema_version"] == _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA:
                    stop = binding.get("local_validation_pre_ack")
                    try:
                        stop = _local_validate_pre_ack_stop(stop)
                    except (TypeError, ValueError) as exc:
                        raise SessionConflict("local validation stop proof is not durable") from exc
                    if (stop["root_run_id"] != final["root_run_id"]
                            or stop["reservation_sha256"] != final["reservation_sha256"]
                            or stop["terminal_event_receipt"] != final["terminal_event_receipt"]
                            or stop["cleanup_receipt_sha256"] != final["cleanup_receipt_sha256"]):
                        raise SessionConflict("local validation stop proof differs from Backend final")
                intent_base = {
                    "schema_version": _LOCAL_VALIDATION_ACK_INTENT_SCHEMA,
                    "final_receipt": final,
                    "runtime_boot_id": self.boot_id,
                    "runtime_authority_epoch": epoch,
                    "final_live_sequence": record.sequence,
                    "domain_call_sequence": record.domain_call_sequence,
                    "domain_call_drained_sequence": record.domain_call_drained_sequence,
                }
                intent = intent_base | {"intent_sha256": _r2_digest(intent_base)}
                try:
                    intent = _local_validate_ack_intent(intent)
                except (TypeError, ValueError) as exc:
                    raise SessionConflict("local validation ACK intent is invalid") from exc
                observation = None
                self._persist_local_validation_ack_binding(
                    session_id, scope, binding, intent, None,
                    expected_raw_sha256=final["runtime_binding_sha256"],
                )

            obs_base = {
                "schema_version": _LOCAL_VALIDATION_RELEASE_OBSERVATION_SCHEMA,
                "ack_intent": intent,
                "slot_scope_sha256": product_scope_digest(scope),
                "cleanup_receipt_sha256": cleanup_sha,
                "state": "released",
            }
            expected_observation = obs_base | {"observation_sha256": _r2_digest(obs_base)}
            try:
                expected_observation = _local_validate_ack_observation(expected_observation)
            except (TypeError, ValueError) as exc:
                raise SessionConflict("local validation release observation is invalid") from exc
            backend_observation = row["local_validation"].get("runtime_observation")
            if backend_observation not in (None, expected_observation):
                raise SessionConflict("Backend local validation observation differs on retry")
            if observation is not None and observation != expected_observation:
                raise SessionConflict("local validation durable observation differs on retry")
            if observation is None and not self._compatibility.product_slots.owns(scope):
                raise SessionConflict("local validation lease is absent before durable observation")
            try:
                released = self._persist_local_validation_ack_binding(
                    session_id, scope, binding, intent, expected_observation,
                    release_slot=True, cleanup_receipt_sha256=cleanup_sha,
                )
            except (OSError, ValueError, RuntimeError) as exc:
                raise SessionConflict("local validation slot release is unconfirmed") from exc
            if not released and observation is None:
                raise SessionConflict("local validation lease is absent without durable observation")
            readback = self._read_acp_binding(session_id)
            if readback.get("local_validation_release_observation") != expected_observation:
                raise SessionConflict("local validation release observation is not durable")
            return {"runtime_observation": expected_observation}

    def _persist_local_validation_ack_binding(
        self, session_id: str, scope: dict[str, str], binding: dict[str, Any],
        intent: dict[str, Any], observation: dict[str, Any] | None,
        *, expected_raw_sha256: str | None = None, release_slot: bool = False,
        cleanup_receipt_sha256: str | None = None,
    ) -> bool | None:
        path = self._acp_binding_path(session_id, scope["workspace_id"])
        lock_path = path.with_suffix(".lock")
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            if self.require_current_backend_authority() != intent["runtime_authority_epoch"]:
                raise SessionConflict("local validation ACK writer lost Backend authority")
            raw = self._read_locked_acp_binding_payload(path)
            try:
                current = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_json_object,
                                     parse_constant=_reject_json_constant)
            except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
                raise SessionConflict("local validation ACK binding is invalid") from exc
            if expected_raw_sha256 is not None:
                if (current != binding
                        or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_raw_sha256)
                        or current.get("schema_version") not in {
                        "byq-acp-root-binding.v1", _ACP_ROOT_BINDING_V2_SCHEMA,
                        _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA}):
                    raise SessionConflict("local validation pre-ACK binding changed before intent")
                updated = dict(current)
                updated.pop("local_validation_pre_ack", None)
                updated["schema_version"] = _ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA
                updated["settlement_receipt"] = intent["final_receipt"]["terminal_event_receipt"]
                updated["local_validation_ack_intent"] = intent
            else:
                if (not isinstance(current, dict)
                        or current.get("schema_version") != _ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA
                        or current.get("local_validation_ack_intent") != intent
                        or binding.get("local_validation_ack_intent") != intent):
                    raise SessionConflict("local validation ACK intent changed before observation")
                existing = current.get("local_validation_release_observation")
                if existing not in (None, observation):
                    raise SessionConflict("local validation release observation changed")
                if existing == observation:
                    file_fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                    try:
                        os.fsync(file_fd)
                    finally:
                        os.close(file_fd)
                        dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                        try:
                            os.fsync(dir_fd)
                        finally:
                            os.close(dir_fd)
                    if release_slot:
                        return self._compatibility.release_local_validation_ack(
                            scope, cleanup_receipt_sha256=cleanup_receipt_sha256 or "",
                            persist_observation=lambda: None,
                        )
                    return
                updated = dict(current)
                updated["local_validation_release_observation"] = observation
            payload = json.dumps(updated, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self._replace_acp_binding_payload(path, payload)
            persisted = self._read_locked_acp_binding_payload(path)
            checked = self._read_acp_binding(session_id)
            expected_observation = observation
            if (not hmac.compare_digest(persisted, payload)
                    or checked.get("local_validation_ack_intent") != intent
                    or checked.get("local_validation_release_observation") != expected_observation
                    or self.require_current_backend_authority() != intent["runtime_authority_epoch"]):
                raise SessionConflict("local validation durable binding write is uncertain")
            if release_slot:
                return self._compatibility.release_local_validation_ack(
                    scope, cleanup_receipt_sha256=cleanup_receipt_sha256 or "",
                    persist_observation=lambda: None,
                )
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def _acknowledge_operator_process_fence_handoff(
        self, session_id: str, raw_request: object,
    ) -> dict[str, Any]:
        """Persist a one-operation cleanup handoff observation before exact slot release."""
        try:
            request = _r2_validate_handoff_request(raw_request)
            handoff, close = request["handoff"], request["close_receipt"]
        except _R2FenceContractError as exc:
            raise SessionConflict("operator cleanup handoff is invalid") from exc
        scope = handoff["scope"]
        epoch = self.require_current_backend_authority()
        if (scope["session_id"] != session_id or not self._acp_product_slots
                or handoff["new_authority"] != {"boot_id": self.boot_id, "epoch": epoch}):
            raise SessionConflict("operator cleanup handoff is not current")
        try:
            live = self._get(session_id)
        except KeyError:
            live = None
        if live is not None:
            raise SessionConflict("cleanup handoff requires the stopped old Runtime process")
        binding = self._read_acp_binding(session_id)
        if binding.get("schema_version") == _ACP_ROOT_BINDING_V3_SCHEMA:
            try:
                saved_request = _r2_validate_handoff_request(binding.get("operator_handoff"))
                saved_handoff = saved_request["handoff"]
                observation = _r2_validate_handoff_observation(
                    binding.get("operator_handoff_observation"), handoff=saved_handoff)
            except (_R2FenceContractError, TypeError, ValueError):
                raise SessionConflict("Runtime handoff retry binding is malformed") from None
            if (saved_request != request or saved_handoff != handoff
                    or observation.get("operation_id") != handoff["operation_id"]
                    or observation.get("handoff_sha256") != handoff["handoff_sha256"]
                    or observation.get("scope") != scope
                    or handoff["new_authority"] != {"boot_id": self.boot_id, "epoch": epoch}
                    or binding.get("final_live_sequence") != 344
                    or not isinstance(binding.get("settlement_receipt"), dict)
                    or _r2_digest(binding["settlement_receipt"])
                       != close["operator_completed_cleanup"]["original_terminal_receipt_sha256"]):
                raise SessionConflict("Runtime handoff retry differs from its exact durable observation")
            raw_path = self._acp_binding_path(session_id, scope["workspace_id"])
            lock_path = raw_path.with_suffix(".lock")

            def verify_durable_handoff() -> None:
                fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                    if self.require_current_backend_authority() != epoch:
                        raise SessionConflict("Runtime handoff retry lost current authority")
                    raw = self._read_locked_acp_binding_payload(raw_path)
                    current = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_json_object,
                                         parse_constant=_reject_json_constant)
                    checked_request = _r2_validate_handoff_request(current.get("operator_handoff"))
                    checked_handoff = checked_request["handoff"]
                    checked_observation = _r2_validate_handoff_observation(
                        current.get("operator_handoff_observation"), handoff=checked_handoff)
                    if (current.get("schema_version") != _ACP_ROOT_BINDING_V3_SCHEMA
                            or checked_request != request or checked_handoff != handoff
                            or checked_observation != observation
                            or current.get("final_live_sequence") != 344
                            or current.get("settlement_receipt") != binding.get("settlement_receipt")):
                        raise SessionConflict("Runtime handoff durable observation changed")
                    file_fd = os.open(raw_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                    try:
                        os.fsync(file_fd)
                    finally:
                        os.close(file_fd)
                    dir_fd = os.open(raw_path.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)

            released = self._compatibility.product_slots.release_operator_fence(
                scope, persist_observation=verify_durable_handoff,
                operation_id=handoff["operation_id"])
            if not released:
                verify_durable_handoff()
            return {"operator_handoff_observation": observation}

        raw_path = self._acp_binding_path(session_id, scope["workspace_id"])
        lock_path = raw_path.with_suffix(".lock")
        original_raw = self._read_locked_acp_binding_payload(raw_path)
        original_sha = hashlib.sha256(original_raw).hexdigest()
        if (binding.get("schema_version") != _ACP_ROOT_BINDING_V2_SCHEMA
                or original_sha != handoff["runtime_binding_sha256"]
                or binding.get("operator_scope") != scope
                or binding.get("previous_boot_id") != close["authority"]["previous_boot_id"]
                or binding.get("previous_authority_epoch") != close["authority"]["previous_epoch"]
                or handoff["old_authority"] != {"boot_id": close["authority"]["current_boot_id"],
                                                 "epoch": close["authority"]["current_epoch"]}
                or binding.get("native_session_close_confirmed") is not True
                or binding.get("process_exit_confirmed") is not False
                or binding.get("cleanup_unconfirmed") is not False
                or binding.get("domain_call_sequence") != binding.get("domain_call_drained_sequence")
                or not isinstance(binding.get("settlement_receipt"), dict)
                or _r2_digest(binding["settlement_receipt"])
                    != close["operator_completed_cleanup"]["original_terminal_receipt_sha256"]
                or not self._compatibility.product_slots):
            raise SessionConflict("stopped V2 binding differs from the handoff preimage")
        self._compatibility.product_slots.reserve_operator_fence(
            scope, operation_id=handoff["operation_id"],
            request_sha256=handoff["handoff_sha256"], allow_existing_live_lease=False)
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        last_sequence = binding["domain_call_sequence"]
        drain = {"schema_version": "byq-runtime-domain-call-drain.v1",
                 "root_run_id": handoff["root_run_id"], "last_domain_sequence": last_sequence,
                 "drained_sequence": last_sequence}
        drain["drain_receipt_sha256"] = _r2_digest(drain)
        release = {"schema_version": "byq-acp-operator-process-fence-slot-release.v1",
                   "workspace_id": scope["workspace_id"], "root_run_id": scope["root_run_id"],
                   "scope_sha256": _r2_digest(scope),
                   "process_fence_receipt_sha256": handoff["process_fence_receipt_sha256"],
                   "tombstone_sha256": close["runner"]["tombstone_sha256"],
                   "drained_sequence": last_sequence, "status": "released", "released_at": now}
        release["release_receipt_sha256"] = _r2_digest(release)
        observation = {"schema_version": _R2_HANDOFF_OBSERVATION_SCHEMA,
            "operation_id": handoff["operation_id"], "handoff_sha256": handoff["handoff_sha256"],
            "root_run_id": handoff["root_run_id"], "scope": scope,
            "runtime_boot_id": self.boot_id, "runtime_authority_epoch": epoch,
            "original_binding_sha256": original_sha, "domain_call_drain": drain,
            "slot_release": release, "observed_at": now}
        observation["receipt_sha256"] = _r2_digest(observation)
        try:
            observation = _r2_validate_handoff_observation(observation, handoff=handoff)
        except _R2FenceContractError as exc:
            raise SessionConflict("constructed handoff observation is invalid") from exc

        def persist_observation() -> None:
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                if self.require_current_backend_authority() != epoch:
                    raise SessionConflict("Runtime handoff lost current authority")
                current_raw = self._read_locked_acp_binding_payload(raw_path)
                if not hmac.compare_digest(current_raw, original_raw):
                    raise SessionConflict("Runtime handoff binding changed before observation")
                current = json.loads(current_raw.decode("utf-8"), object_pairs_hook=_strict_json_object,
                                     parse_constant=_reject_json_constant)
                if not isinstance(current, dict) or current.get("schema_version") != _ACP_ROOT_BINDING_V2_SCHEMA:
                    raise SessionConflict("Runtime handoff predecessor binding changed")
                current["schema_version"] = _ACP_ROOT_BINDING_V3_SCHEMA
                current["final_live_sequence"] = max(current["sequence"], 344)
                current["operator_handoff"] = request
                current["operator_handoff_observation"] = observation
                payload = json.dumps(current, sort_keys=True, separators=(",", ":")).encode("utf-8")
                self._replace_acp_binding_payload(raw_path, payload)
                if (not hmac.compare_digest(self._read_locked_acp_binding_payload(raw_path), payload)
                        or self.require_current_backend_authority() != epoch):
                    raise SessionConflict("Runtime handoff observation durability is uncertain")
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

        released = self._compatibility.product_slots.release_operator_fence(
            scope, persist_observation=persist_observation, operation_id=handoff["operation_id"])
        if not released:
            raise SessionConflict("exact cleanup handoff lease is unavailable")
        return {"operator_handoff_observation": observation}

    def _acknowledge_operator_process_fence(
        self, session_id: str, raw_close_receipt: object,
    ) -> dict[str, Any]:
        """Persist and return one exact R2 observation, then release its slot."""
        try:
            close = _r2_validate_close_receipt(raw_close_receipt)
        except _R2FenceContractError as exc:
            raise SessionConflict("operator process-fence close receipt is invalid") from exc
        scope = close["scope"]
        if (not self._acp or not self._acp_product_slots
                or close["workspace_id"] != scope["workspace_id"]
                or scope["session_id"] != session_id):
            raise SessionConflict("operator process-fence scope is unavailable")
        try:
            record = self._get(session_id)
        except KeyError:
            record = None

        # A persisted V3 is the only retry authority after the initial
        # in-memory drain/lease handoff. It is bound to the exact close receipt.
        binding = self._read_acp_binding(session_id)
        if binding["schema_version"] == _ACP_ROOT_BINDING_V3_SCHEMA:
            try:
                observation = _r2_validate_operator_observation(
                    binding["operator_observation"], close_receipt=close)
            except _R2FenceContractError as exc:
                raise SessionConflict("operator process-fence retry does not match its durable observation") from exc
            current_epoch = self.require_current_backend_authority()
            if (binding["session_id"] != session_id
                    or binding["workspace_id"] != scope["workspace_id"]
                    or binding["root_run_id"] != scope["root_run_id"]
                    or observation["runtime_binding_sha256"] != close["runtime_binding_sha256"]
                    or close["authority"]["current_boot_id"] != self.boot_id
                    or close["authority"]["current_epoch"] != current_epoch):
                raise SessionConflict("operator process-fence retry binding changed")
            raw_path = self._acp_binding_path(session_id, scope["workspace_id"])
            lock_path = raw_path.with_suffix(".lock")
            expected_v3_raw = json.dumps(
                binding, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
            lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT
                              | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                file_before = os.lstat(raw_path)
                parent_before = os.lstat(raw_path.parent)
                raw_before = self._read_locked_acp_binding_payload(raw_path)
                file_after = os.lstat(raw_path)
                parent_after = os.lstat(raw_path.parent)
                try:
                    parsed_before = json.loads(
                        raw_before.decode("utf-8"), object_pairs_hook=_strict_json_object,
                        parse_constant=_reject_json_constant,
                    )
                except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
                    raise SessionConflict("operator process-fence retry binding is invalid") from exc
                if (not isinstance(parsed_before, dict)
                        or parsed_before != binding
                        or not hmac.compare_digest(raw_before, expected_v3_raw)
                        or parsed_before.get("schema_version") != _ACP_ROOT_BINDING_V3_SCHEMA
                        or not stat.S_ISREG(file_before.st_mode)
                        or file_before.st_uid != os.getuid() or file_before.st_gid != os.getgid()
                        or stat.S_IMODE(file_before.st_mode) != 0o600 or file_before.st_nlink != 1
                        or not stat.S_ISDIR(parent_before.st_mode)
                        or (file_after.st_dev, file_after.st_ino, file_after.st_size)
                        != (file_before.st_dev, file_before.st_ino, file_before.st_size)
                        or (parent_after.st_dev, parent_after.st_ino)
                        != (parent_before.st_dev, parent_before.st_ino)
                        or self.require_current_backend_authority() != current_epoch):
                    raise SessionConflict("operator process-fence retry binding changed")
                file_identity = (file_before.st_dev, file_before.st_ino)
                parent_identity = (parent_before.st_dev, parent_before.st_ino)
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)

            def confirm_existing_observation() -> None:
                writer_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT
                                    | getattr(os, "O_NOFOLLOW", 0), 0o600)
                try:
                    fcntl.flock(writer_fd, fcntl.LOCK_EX)
                    if self.require_current_backend_authority() != current_epoch:
                        raise SessionConflict("operator process-fence retry lost current authority")
                    current_path = os.lstat(raw_path)
                    current_parent = os.lstat(raw_path.parent)
                    if ((current_path.st_dev, current_path.st_ino) != file_identity
                            or (current_parent.st_dev, current_parent.st_ino) != parent_identity):
                        raise SessionConflict("operator process-fence retry file identity changed")
                    file_fd = os.open(raw_path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
                    try:
                        opened = os.fstat(file_fd)
                        if ((opened.st_dev, opened.st_ino) != file_identity
                                or not stat.S_ISREG(opened.st_mode)
                                or opened.st_uid != os.getuid() or opened.st_gid != os.getgid()
                                or stat.S_IMODE(opened.st_mode) != 0o600 or opened.st_nlink != 1
                                or opened.st_size != len(raw_before)
                                or not hmac.compare_digest(
                                    self._read_locked_acp_binding_payload(raw_path), raw_before)):
                            raise SessionConflict("operator process-fence retry file is unsafe")
                        os.fsync(file_fd)
                        after_file = os.fstat(file_fd)
                        path_after_file = os.lstat(raw_path)
                        if ((after_file.st_dev, after_file.st_ino) != file_identity
                                or after_file.st_uid != os.getuid() or after_file.st_gid != os.getgid()
                                or stat.S_IMODE(after_file.st_mode) != 0o600 or after_file.st_nlink != 1
                                or after_file.st_size != len(raw_before)
                                or (path_after_file.st_dev, path_after_file.st_ino) != file_identity
                                or not hmac.compare_digest(
                                    self._read_locked_acp_binding_payload(raw_path), raw_before)
                                or self.require_current_backend_authority() != current_epoch):
                            raise SessionConflict("operator process-fence retry file durability is uncertain")
                    finally:
                        os.close(file_fd)
                    parent_fd = os.open(raw_path.parent, os.O_RDONLY | os.O_DIRECTORY
                                        | getattr(os, "O_NOFOLLOW", 0))
                    try:
                        opened_parent = os.fstat(parent_fd)
                        if ((opened_parent.st_dev, opened_parent.st_ino) != parent_identity
                                or not stat.S_ISDIR(opened_parent.st_mode)):
                            raise SessionConflict("operator process-fence retry parent changed")
                        os.fsync(parent_fd)
                        after_parent = os.fstat(parent_fd)
                        final_path = os.lstat(raw_path)
                        if ((after_parent.st_dev, after_parent.st_ino) != parent_identity
                                or (final_path.st_dev, final_path.st_ino) != file_identity
                                or not hmac.compare_digest(
                                    self._read_locked_acp_binding_payload(raw_path), raw_before)
                                or self.require_current_backend_authority() != current_epoch):
                            raise SessionConflict("operator process-fence retry parent durability is uncertain")
                    finally:
                        os.close(parent_fd)
                finally:
                    fcntl.flock(writer_fd, fcntl.LOCK_UN)
                    os.close(writer_fd)

            # The callback completes positive file and parent durability while
            # the registry lock still protects any exact lease deletion.
            released = self._compatibility.product_slots.release_operator_fence(
                scope, persist_observation=confirm_existing_observation,
                operation_id=(observation["operation_id"]
                              if observation.get("operator_completed_cleanup") is not None else None))
            if not released:
                # No lease remained to delete; still prove durability before
                # confirming this idempotent retry.
                confirm_existing_observation()
            if record is not None:
                with record.lock:
                    self._adopt_operator_observation(record, binding, observation)
            return {"operator_observation": observation}

        failed_fact = close.get("operator_failed_terminal")
        completed_fact = close.get("operator_completed_cleanup")
        cleanup_only = completed_fact is not None
        failed_live_record = record if failed_fact is not None else None
        if cleanup_only and record is not None:
            raise SessionConflict("completed cleanup cannot attach to a live Runtime record")
        if binding["schema_version"] != _ACP_ROOT_BINDING_V2_SCHEMA:
            raise SessionConflict("operator process-fence requires the qualified Runtime binding")
        if failed_fact is not None or cleanup_only:
            if (record is not None and (record.process_root_id != scope["root_run_id"]
                    or record.active_run is not None)):
                raise SessionConflict("failed-terminal Runtime record is not idle and exact")
            record = None
        elif record is None:
            raise SessionConflict("operator process-fence requires the live qualified Runtime root")
        with (record.lock if record is not None else nullcontext()):
            current_epoch = self.require_current_backend_authority()
            expected_failed_receipt = ({
                "schema_version": "agent-run-lifecycle-receipt.v1",
                "root_run_id": scope["root_run_id"], "sequence": failed_fact["sequence"],
                "event_sha256": failed_fact["event_sha256"],
            } if failed_fact is not None else None)
            expected_completed_receipt = binding.get("settlement_receipt") if cleanup_only else None
            if record is not None:
                self._validate_operator_close_record(record, binding, close, current_epoch)
            elif (binding.get("operator_scope") != scope
                    or (cleanup_only and (not isinstance(expected_completed_receipt, dict)
                        or _r2_digest(expected_completed_receipt)
                            != completed_fact.get("original_terminal_receipt_sha256")
                        or expected_completed_receipt.get("root_run_id") != scope["root_run_id"]))
                    or (not cleanup_only and binding.get("settlement_receipt") not in (None, expected_failed_receipt))
                    or (failed_live_record is not None
                        and failed_live_record.settlement_receipt
                            != binding.get("settlement_receipt"))
                    or binding.get("closed") is not False
                    or binding.get("native_session_close_confirmed") is not cleanup_only
                    or binding.get("process_exit_confirmed") is not False
                    or binding.get("cleanup_unconfirmed") is not False
                    or binding.get("domain_call_sequence") != binding.get("domain_call_drained_sequence")
                    or binding.get("operator_binding", {}).get("runner_instance_id")
                       != close["runner"]["old_runner_instance_id"]
                    or close["authority"]["current_boot_id"] != self.boot_id
                    or close["authority"]["current_epoch"] != current_epoch
                    or not self._compatibility.product_slots.owns(scope)):
                raise SessionConflict("failed-terminal cleanup fence is not exact")
            raw_path = self._acp_binding_path(session_id, scope["workspace_id"])
            lock_path = raw_path.with_suffix(".lock")
            lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT
                              | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                original_raw = self._read_locked_acp_binding_payload(raw_path)
                original_sha256 = hashlib.sha256(original_raw).hexdigest()
                if (not hmac.compare_digest(
                        original_sha256, close["runtime_binding_sha256"])
                        or self.require_current_backend_authority() != current_epoch):
                    raise SessionConflict("operator process-fence binding changed before acknowledgement")
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)

            observation = (self._build_operator_observation(record, close, original_sha256)
                if record is not None else
                self._build_completed_cleanup_observation(binding, close, original_sha256)
                if cleanup_only else self._build_failed_terminal_observation(binding, close, original_sha256))

            def persist_observation() -> None:
                writer_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT
                                    | getattr(os, "O_NOFOLLOW", 0), 0o600)
                try:
                    fcntl.flock(writer_fd, fcntl.LOCK_EX)
                    if self.require_current_backend_authority() != current_epoch:
                        raise SessionConflict("operator process-fence writer lost current authority")
                    current_raw = self._read_locked_acp_binding_payload(raw_path)
                    if not hmac.compare_digest(current_raw, original_raw):
                        raise SessionConflict("operator process-fence binding changed before write")
                    try:
                        current_value = json.loads(
                            current_raw.decode("utf-8"),
                            object_pairs_hook=_strict_json_object,
                            parse_constant=_reject_json_constant,
                        )
                    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
                        raise SessionConflict(
                            "operator process-fence binding is invalid before write") from exc
                    if (not isinstance(current_value, dict)
                            or current_value != binding
                            or current_value.get("schema_version") != _ACP_ROOT_BINDING_V2_SCHEMA):
                        raise SessionConflict(
                            "operator process-fence binding changed before write")
                    # Preserve the original V2 anchor bytes; carry the later
                    # observed cursor separately in the Runtime-only V3 record.
                    current_value["schema_version"] = _ACP_ROOT_BINDING_V3_SCHEMA
                    current_value["final_live_sequence"] = (
                        record.sequence if record is not None else
                        max(binding["sequence"], failed_fact["sequence"]) if failed_fact is not None else
                        max(binding["sequence"], expected_completed_receipt["sequence"]))
                    current_value["operator_observation"] = observation
                    payload = json.dumps(
                        current_value, sort_keys=True, separators=(",", ":"),
                    ).encode("utf-8")
                    self._replace_acp_binding_payload(raw_path, payload)
                    persisted = self._read_locked_acp_binding_payload(raw_path)
                    if (not hmac.compare_digest(persisted, payload)
                            or self.require_current_backend_authority() != current_epoch):
                        raise SessionConflict("operator process-fence durable write is uncertain")
                    if record is not None:
                        self._adopt_operator_observation(record, current_value, observation)
                    elif failed_live_record is not None:
                        with failed_live_record.lock:
                            self._adopt_operator_observation(
                                failed_live_record, current_value, observation)
                finally:
                    fcntl.flock(writer_fd, fcntl.LOCK_UN)
                    os.close(writer_fd)

            released = self._compatibility.product_slots.release_operator_fence(
                scope, persist_observation=persist_observation,
                operation_id=(observation["operation_id"]
                              if observation.get("operator_completed_cleanup") is not None else None))
            if not released:
                raise SessionConflict("operator process-fence slot lease is unavailable")
            return {"operator_observation": observation}

    def _operator_live_scope_identity_exact(
        self, record: RuntimeSession, binding: dict[str, Any], scope: dict[str, str],
    ) -> bool:
        """Match a current live record to its qualified V2 scope before lease use."""
        generation = record.current_generation
        return (binding.get("schema_version") == _ACP_ROOT_BINDING_V2_SCHEMA
                and binding.get("operator_scope") == scope
                and binding.get("operator_binding") == record.qualified_operator_binding
                and binding.get("previous_boot_id") == scope["runtime_boot_id"]
                and binding.get("previous_authority_epoch") == record.qualified_authority_epoch
                and record.boot_id == self.boot_id
                and record.session_id == scope["session_id"]
                and record.trace_id == scope["trace_id"]
                and record.owner_principal == scope["owner_principal"]
                and record.workspace_id == scope["workspace_id"]
                and record.process_root_id == scope["root_run_id"]
                and record.runtime_generation == scope["generation_id"]
                and record.qualified_runtime_generation == scope["generation_id"]
                and record.qualified_operator_scope == scope
                and record.settlement_receipt == binding.get("settlement_receipt")
                and not record.conversation_ended
                and not record.release_finalized
                and generation is not None
                and generation.process_root_id == scope["root_run_id"]
                and generation.generation_id == scope["generation_id"]
                and record.active_run is None
                and record.status not in SessionStatus.ACTIVE_PROMPT)

    def _validate_operator_close_record(
        self, record: RuntimeSession, binding: dict[str, Any],
        close: dict[str, Any], current_epoch: int,
    ) -> None:
        scope = close["scope"]
        authority = close["authority"]
        generation = record.current_generation
        start_binding = binding.get("operator_binding")
        # The V2 lifecycle cursor is a before-START anchor and may trail live
        # events. Domain cursors are checkpointed by each evidence ACK, so both
        # domain values must still match the live Runtime record exactly.
        if (not self._operator_live_scope_identity_exact(record, binding, scope)
                or not isinstance(start_binding, dict)
                or not isinstance(record.recovery_cwd, str)
                or Path(record.recovery_cwd).name != scope["cwd_leaf"]
                or record.qualified_authority_epoch != authority["previous_epoch"]
                or binding.get("previous_authority_epoch") != authority["previous_epoch"]
                or binding.get("previous_boot_id") != authority["previous_boot_id"]
                or binding.get("native_session_close_confirmed") is not generation.native_session_close_confirmed
                or binding.get("process_exit_confirmed") is not generation.process_exit_confirmed
                or binding.get("cleanup_unconfirmed") is not record.cleanup_unconfirmed
                or binding.get("closed") is not False
                or binding.get("domain_call_sequence") != record.domain_call_sequence
                or binding.get("domain_call_drained_sequence") != record.domain_call_drained_sequence
                or type(binding.get("sequence")) is not int
                or binding.get("sequence") > record.sequence
                or binding.get("settlement_receipt") is not None
                or record.settlement_receipt is not None
                or record.conversation_ended or record.release_finalized
                or generation.process_closing
                or generation.continuation_proxy_closed is not True
                or start_binding.get("runner_instance_id") != close["runner"]["old_runner_instance_id"]
                or authority["current_boot_id"] != self.boot_id
                or authority["current_epoch"] != current_epoch):
            raise SessionConflict("operator process-fence does not match the live Runtime root")
        pending = record.pending_terminal_receipts
        if pending not in (set(), {scope["root_run_id"]}):
            raise SessionConflict("operator process-fence has unrelated pending terminal receipts")
        if pending:
            receipt = record.terminal_receipts.get(scope["root_run_id"])
            if (not isinstance(receipt, dict)
                    or set(receipt) != {"schema_version", "root_run_id", "sequence", "event_sha256"}
                    or receipt.get("schema_version") != "agent-run-lifecycle-receipt.v1"
                    or receipt.get("root_run_id") != scope["root_run_id"]
                    or type(receipt.get("sequence")) is not int
                    or receipt["sequence"] > record.sequence
                    or not isinstance(receipt.get("event_sha256"), str)):
                raise SessionConflict("operator process-fence pending terminal receipt is unproven")
            evidence = self._terminal_evidence_for(record, scope["root_run_id"])
            terminal_event = None
            for event in reversed(record.history):
                projected = project_lifecycle_event(event, record.session_id, record.trace_id)
                if (projected is not None
                        and projected["root_run_id"] == scope["root_run_id"]
                        and projected["outcome"] != "active"):
                    terminal_event = event
                    break
            if (evidence["receipt"] != receipt
                    or evidence["outcome"] != "failed"
                    or not isinstance(terminal_event, dict)
                    or terminal_event.get("kind") != "session.failed"):
                raise SessionConflict("operator process-fence pending terminal receipt is unproven")
        elif scope["root_run_id"] in record.terminal_receipts:
            raise SessionConflict("operator process-fence terminal receipt is not pending")

    def _build_operator_observation(
        self, record: RuntimeSession, close: dict[str, Any], root_binding_sha256: str,
    ) -> dict[str, Any]:
        scope = close["scope"]
        root_run_id = scope["root_run_id"]
        now = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        close_sha256 = _r2_digest(close)
        superseded_terminal = None
        if record.pending_terminal_receipts:
            receipt = record.terminal_receipts[root_run_id]
            superseded_terminal = {
                "schema_version": "byq-runtime-superseded-terminal.v1",
                "root_run_id": root_run_id,
                "sequence": receipt["sequence"],
                "event_sha256": receipt["event_sha256"],
                "receipt_sha256": _r2_digest(receipt),
            }
        drain = {
            "schema_version": "byq-runtime-domain-call-drain.v1",
            "root_run_id": root_run_id,
            "last_domain_sequence": record.domain_call_sequence,
            "drained_sequence": record.domain_call_drained_sequence,
        }
        drain["drain_receipt_sha256"] = _r2_digest(drain)
        runtime_ack = {
            "schema_version": "byq-runtime-operator-terminal-ack.v1",
            "root_run_id": root_run_id,
            "runtime_boot_id": scope["runtime_boot_id"],
            "scope_sha256": _r2_digest(scope),
            "process_fence_receipt_sha256": close["process_fence_receipt_sha256"],
            "operator_interruption_receipt_sha256": close["operator_interruption"]["receipt_sha256"],
            "root_binding_sha256": root_binding_sha256,
            "terminal_ack_sha256": close_sha256,
            "acknowledged_at": now,
        }
        slot_release = {
            "schema_version": "byq-acp-operator-process-fence-slot-release.v1",
            "workspace_id": scope["workspace_id"],
            "root_run_id": root_run_id,
            "scope_sha256": _r2_digest(scope),
            "process_fence_receipt_sha256": close["process_fence_receipt_sha256"],
            "tombstone_sha256": close["runner"]["tombstone_sha256"],
            "drained_sequence": record.domain_call_drained_sequence,
            "status": "released",
            "released_at": now,
        }
        slot_release["release_receipt_sha256"] = _r2_digest(slot_release)
        observation = {
            "schema_version": _R2_OPERATOR_OBSERVATION_SCHEMA,
            "operation_id": close["operation_id"],
            "close_receipt_sha256": close_sha256,
            "process_fence_receipt_sha256": close["process_fence_receipt_sha256"],
            "operator_interruption_receipt_sha256": close["operator_interruption"]["receipt_sha256"],
            "scope": scope,
            "authority": close["authority"],
            "runner": close["runner"],
            "engineering_evidence_sha256": close["engineering_evidence_sha256"],
            "runtime_binding_sha256": root_binding_sha256,
            "runtime_ack": runtime_ack,
            "domain_call_drain": drain,
            "slot_release": slot_release,
            "observed_at": now,
            "superseded_terminal": superseded_terminal,
        }
        try:
            return _r2_validate_operator_observation(observation, close_receipt=close)
        except _R2FenceContractError as exc:
            raise SessionConflict("operator process-fence observation is inconsistent") from exc

    def _build_failed_terminal_observation(
        self, binding: dict[str, Any], close: dict[str, Any], root_binding_sha256: str,
    ) -> dict[str, Any]:
        """Build a cleanup-only ACK from frozen V2 and the original Backend failed fact."""
        scope = close["scope"]
        fact = close["operator_failed_terminal"]
        now = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        close_sha256 = _r2_digest(close)
        drained = binding["domain_call_drained_sequence"]
        drain = {"schema_version": "byq-runtime-domain-call-drain.v1",
                 "root_run_id": scope["root_run_id"], "last_domain_sequence": drained,
                 "drained_sequence": drained}
        drain["drain_receipt_sha256"] = _r2_digest(drain)
        runtime_ack = {
            "schema_version": "byq-runtime-operator-terminal-ack.v1",
            "root_run_id": scope["root_run_id"], "runtime_boot_id": scope["runtime_boot_id"],
            "scope_sha256": _r2_digest(scope),
            "process_fence_receipt_sha256": close["process_fence_receipt_sha256"],
            "operator_failed_terminal_receipt_sha256": fact["receipt_sha256"],
            "root_binding_sha256": root_binding_sha256,
            "terminal_ack_sha256": close_sha256, "acknowledged_at": now,
        }
        slot_release = {
            "schema_version": "byq-acp-operator-process-fence-slot-release.v1",
            "workspace_id": scope["workspace_id"], "root_run_id": scope["root_run_id"],
            "scope_sha256": _r2_digest(scope),
            "process_fence_receipt_sha256": close["process_fence_receipt_sha256"],
            "tombstone_sha256": close["runner"]["tombstone_sha256"],
            "drained_sequence": drained, "status": "released", "released_at": now,
        }
        slot_release["release_receipt_sha256"] = _r2_digest(slot_release)
        observation = {
            "schema_version": _R2_OPERATOR_OBSERVATION_SCHEMA,
            "operation_id": close["operation_id"], "close_receipt_sha256": close_sha256,
            "process_fence_receipt_sha256": close["process_fence_receipt_sha256"],
            "operator_failed_terminal_receipt_sha256": fact["receipt_sha256"],
            "scope": scope, "authority": close["authority"], "runner": close["runner"],
            "engineering_evidence_sha256": close["engineering_evidence_sha256"],
            "runtime_binding_sha256": root_binding_sha256,
            "runtime_ack": runtime_ack, "domain_call_drain": drain,
            "slot_release": slot_release, "observed_at": now,
            "superseded_terminal": None,
            "operator_failed_terminal": fact,
        }
        try:
            return _r2_validate_operator_observation(observation, close_receipt=close)
        except _R2FenceContractError as exc:
            raise SessionConflict("failed-terminal cleanup observation is inconsistent") from exc

    def _build_completed_cleanup_observation(
        self, binding: dict[str, Any], close: dict[str, Any], root_binding_sha256: str,
    ) -> dict[str, Any]:
        fact = close["operator_completed_cleanup"]
        scope = close["scope"]
        now = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        close_sha256 = _r2_digest(close)
        drained = binding["domain_call_drained_sequence"]
        drain = {"schema_version": "byq-runtime-domain-call-drain.v1",
                 "root_run_id": scope["root_run_id"], "last_domain_sequence": drained,
                 "drained_sequence": drained}
        drain["drain_receipt_sha256"] = _r2_digest(drain)
        runtime_ack = {
            "schema_version": "byq-runtime-operator-completed-cleanup-ack.v1",
            "root_run_id": scope["root_run_id"], "runtime_boot_id": self.boot_id,
            "scope_sha256": _r2_digest(scope),
            "process_fence_receipt_sha256": close["process_fence_receipt_sha256"],
            _R2_COMPLETED_CLEANUP_DIGEST_FIELD: fact["receipt_sha256"],
            "root_binding_sha256": root_binding_sha256,
            "terminal_ack_sha256": close_sha256, "acknowledged_at": now,
        }
        slot_release = {
            "schema_version": "byq-acp-operator-process-fence-slot-release.v1",
            "workspace_id": scope["workspace_id"], "root_run_id": scope["root_run_id"],
            "scope_sha256": _r2_digest(scope),
            "process_fence_receipt_sha256": close["process_fence_receipt_sha256"],
            "tombstone_sha256": close["runner"]["tombstone_sha256"],
            "drained_sequence": drained, "status": "released", "released_at": now,
        }
        slot_release["release_receipt_sha256"] = _r2_digest(slot_release)
        observation = {
            "schema_version": _R2_OPERATOR_OBSERVATION_SCHEMA,
            "operation_id": close["operation_id"], "close_receipt_sha256": close_sha256,
            "process_fence_receipt_sha256": close["process_fence_receipt_sha256"],
            _R2_COMPLETED_CLEANUP_DIGEST_FIELD: fact["receipt_sha256"],
            "operator_completed_cleanup": fact,
            "scope": scope, "authority": close["authority"], "runner": close["runner"],
            "engineering_evidence_sha256": close["engineering_evidence_sha256"],
            "runtime_binding_sha256": root_binding_sha256,
            "runtime_ack": runtime_ack, "domain_call_drain": drain,
            "slot_release": slot_release, "observed_at": now, "superseded_terminal": None,
        }
        try:
            return _r2_validate_operator_observation(observation, close_receipt=close)
        except _R2FenceContractError as exc:
            raise SessionConflict("completed cleanup observation is inconsistent") from exc

    @staticmethod
    def _adopt_operator_observation(
        record: RuntimeSession, binding: dict[str, Any], observation: dict[str, Any],
    ) -> None:
        scope = observation["scope"]
        failed_fact = observation.get("operator_failed_terminal")
        expected_failed_receipt = ({
            "schema_version": "agent-run-lifecycle-receipt.v1",
            "root_run_id": scope["root_run_id"], "sequence": failed_fact["sequence"],
            "event_sha256": failed_fact["event_sha256"],
        } if failed_fact is not None else None)
        if (record.session_id != scope["session_id"]
                or record.trace_id != scope["trace_id"]
                or record.workspace_id != scope["workspace_id"]
                or record.process_root_id != scope["root_run_id"]
                or binding.get("root_run_id") != scope["root_run_id"]
                or binding.get("operator_observation") != observation
                or binding.get("settlement_receipt") not in (None, expected_failed_receipt)
                or record.settlement_receipt != binding.get("settlement_receipt")
                or (record.operator_observation is not None
                    and record.operator_observation != observation)):
            raise SessionConflict("operator process-fence observation belongs to another Runtime root")
        pending = record.pending_terminal_receipts
        if pending not in (set(), {scope["root_run_id"]}):
            raise SessionConflict("operator process-fence observation has unrelated pending receipts")
        superseded = observation["superseded_terminal"]
        if (failed_fact is not None and not pending
                and scope["root_run_id"] in record.terminal_receipts
                and record.operator_observation is None):
            raise SessionConflict("failed-terminal receipt was already acknowledged")
        if pending:
            receipt = record.terminal_receipts.get(scope["root_run_id"])
            terminal = failed_fact if failed_fact is not None else superseded
            if (terminal is None or not isinstance(receipt, dict)
                    or receipt.get("sequence") != terminal["sequence"]
                    or receipt.get("event_sha256") != terminal["event_sha256"]
                    or (superseded is not None
                        and _r2_digest(receipt) != superseded["receipt_sha256"])):
                raise SessionConflict("operator process-fence receipt conflicts with Runtime pending state")
        record.operator_observation = dict(observation)
        if superseded is not None:
            record.operator_superseded_terminal_receipts[scope["root_run_id"]] = superseded["receipt_sha256"]
            record.pending_terminal_receipts.discard(scope["root_run_id"])
        elif failed_fact is not None:
            record.pending_terminal_receipts.discard(scope["root_run_id"])
        record.reuse_native_session_ready = False
        if record.current_generation is not None:
            record.current_generation.state = GenerationState.INTERRUPTED
            if failed_fact is not None:
                record.current_generation.harness = None
                record.current_generation.process_closing = False
                record.current_generation.continuation_proxy_closed = True
        record.status = SessionStatus.IDLE

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
        *, local_validation_pre_ack: dict[str, Any] | None = None,
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
                if (local_validation_pre_ack is None and record.settlement_receipt != receipt):
                    raise SessionConflict("ACP terminal settlement receipt changed before close")
                if local_validation_pre_ack is not None:
                    binding = self._read_acp_binding(record.session_id)
                    if (binding.get("schema_version") != _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA
                            or binding.get("local_validation_pre_ack") != local_validation_pre_ack
                            or binding.get("settlement_receipt") is not None):
                        raise SessionConflict("local validation pre-ACK binding changed before close")
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
                    self._persist_acp_binding(record,
                        local_validation_pre_ack=local_validation_pre_ack)
                except Exception:
                    # The pre-close exact ACK binding remains durable. Without
                    # durable close proof, keep this boot safe by disabling
                    # reuse; fresh-native recovery is the fallback.
                    record.reuse_native_session_ready = False
            if close_error is not None:
                raise SessionConflict("ACP root process exit could not be confirmed") from None
            return

    def terminal_evidence(self, session_id: str, root_run_id: str, boot_id: str,
                          *, local_validation: bool = False) -> dict:
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
                result = {**evidence, "receipt": dict(receipt)}
                if local_validation:
                    raise SessionConflict("local validation projection requires a live Runtime session")
                return result
            raise KeyError(f"terminal evidence unavailable for {session_id}")
        with record.lock:
            if record.boot_id != boot_id:
                raise SessionConflict("terminal evidence belongs to another Adapter boot")
            result = self._terminal_evidence_for(record, root_run_id)
            return self._local_validation_terminal_projection(record, result) if local_validation else result

    def _local_validation_terminal_projection(
        self, record: RuntimeSession, terminal: dict[str, Any],
    ) -> dict[str, Any]:
        """Opt-in closed terminal summary bound to the validated persisted Product scope."""
        binding = self._read_acp_binding(terminal["session_id"])
        if (binding.get("schema_version") not in {"byq-acp-root-binding.v1", _ACP_ROOT_BINDING_V2_SCHEMA,
                                                     _ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA,
                                                     _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA}
                or binding.get("root_run_id") != terminal["root_run_id"]
                or binding.get("session_id") != terminal["session_id"]
                or binding.get("previous_boot_id") != terminal["boot_id"]
                or binding.get("trace_id") != record.trace_id
                or binding.get("workspace_id") != record.workspace_id
                or binding.get("owner_principal") != record.owner_principal
                or record.process_root_id != terminal["root_run_id"]
                or binding.get("runtime_generation") != record.runtime_generation
                or binding.get("cwd") != str(Path(record.qualified_cwd or record.recovery_cwd or "").resolve())
                or binding.get("settlement_receipt") not in (None, terminal["receipt"])):
            raise SessionConflict("local validation terminal binding differs from exact terminal")
        path = self._acp_binding_path(terminal["session_id"], binding["workspace_id"])
        lock_path = path.with_suffix(".lock")
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_SH)
            raw = self._read_locked_acp_binding_payload(path)
            try:
                actual = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_json_object,
                                    parse_constant=_reject_json_constant)
            except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
                raise SessionConflict("local validation binding bytes are invalid") from exc
            validated = self._read_acp_binding(terminal["session_id"])
            if actual != binding or validated != binding:
                raise SessionConflict("local validation binding changed during projection")
            scope = binding.get("operator_scope")
            if binding["schema_version"] == "byq-acp-root-binding.v1" or (
                    binding["schema_version"] == _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA
                    and "operator_scope" not in binding):
                scope = {"workspace_id": binding["workspace_id"],
                    "owner_principal": binding["owner_principal"], "session_id": binding["session_id"],
                    "trace_id": binding["trace_id"], "root_run_id": binding["root_run_id"],
                    "runtime_boot_id": binding["previous_boot_id"],
                    "generation_id": binding["runtime_generation"], "cwd_leaf": Path(binding["cwd"]).name}
            elif (binding["schema_version"] in {_ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA,
                                                  _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA}
                    and "operator_scope" not in binding):
                if binding["schema_version"] == _ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA:
                    scope = binding["local_validation_ack_intent"]["final_receipt"]["scope"]
            if (not isinstance(scope, dict) or scope.get("root_run_id") != terminal["root_run_id"]
                    or scope.get("session_id") != terminal["session_id"]
                    or scope.get("runtime_boot_id") != terminal["boot_id"]
                    or scope.get("generation_id") != binding.get("runtime_generation")):
                raise SessionConflict("local validation Product scope is not exact")
            if (binding["schema_version"] in {_ACP_ROOT_BINDING_V2_SCHEMA,
                                                _ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA,
                                                _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA}
                    and "operator_scope" in binding
                    and scope != binding.get("operator_scope")):
                raise SessionConflict("local validation operator scope differs from its Runtime binding")
            binding_sha256 = hashlib.sha256(raw).hexdigest()
            if binding["schema_version"] == _ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA:
                final = binding["local_validation_ack_intent"]["final_receipt"]
                if (terminal["receipt"] != final["terminal_event_receipt"]
                        or scope != final["scope"]):
                    raise SessionConflict("local validation ACK final differs from terminal projection")
                binding_sha256 = final["runtime_binding_sha256"]
            return {"schema_version": "byq-runtime-local-validation-terminal-evidence.v1",
                "terminal": dict(terminal), "scope": dict(scope),
                "binding_sha256": binding_sha256}
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

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
            described = {
                "session_id": record.session_id,
                "trace_id": record.trace_id,
                "boot_id": record.boot_id,
                "status": record.status,
                "active_prompt": record.active_run is not None,
                "sequence": record.sequence,
                "process_ownership": "dedicated",
                "persistence": "dsh-owned",
                "owner_context": "configured" if record.owner_principal else "missing",
                # ADR-0079 R2: report how continuity was established without
                # exposing the ephemeral generation/native process identity.
                "continuity": record.continuity,
            }
            if record.recovery_boundary is not None:
                described["recovery_boundary"] = dict(record.recovery_boundary)
            return described

    def _require_workspace_acp_cleanup_fence(self, workspace_id: str) -> None:
        """Read this Workspace's durable qualified bindings before ordinary START."""
        binding_dir = contained_session_path(
            self._compatibility.session_storage_root(self._session_root, workspace_id),
            "byq-acp-bindings")
        if not binding_dir.exists():
            return
        for binding_path in binding_dir.glob("*.json"):
            previous = self._read_acp_binding(binding_path.stem)
            if previous.get("workspace_id") != workspace_id:
                raise SessionConflict("workspace ACP binding scope changed")
            if (previous.get("schema_version") == _ACP_ROOT_BINDING_V2_SCHEMA
                    and (previous.get("process_exit_confirmed") is not True
                         or previous.get("cleanup_unconfirmed") is True)):
                raise SessionConflict("workspace prior ACP cleanup is unconfirmed")

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

    def _acp_binding_value(
        self, record: RuntimeSession, *, root_run_id: str | None = None,
        runtime_generation: str | None = None, cwd: str | None = None,
        operator_scope: dict[str, str] | None = None,
        operator_binding: dict[str, Any] | None = None,
        include_qualified: bool = True,
        starting_new_root: bool = False,
    ) -> dict[str, Any]:
        root = root_run_id or record.process_root_id
        qualified_scope = (operator_scope if operator_scope is not None
                           else record.qualified_operator_scope if include_qualified else None)
        qualified_binding = (operator_binding if operator_binding is not None
                             else record.qualified_operator_binding if include_qualified else None)
        qualified_generation = (runtime_generation if runtime_generation is not None
                               else record.qualified_runtime_generation if include_qualified else None)
        actual_cwd = (cwd if cwd is not None else
                      record.qualified_cwd if include_qualified and record.qualified_cwd is not None
                      else record.recovery_cwd)
        if (qualified_scope is None) != (qualified_binding is None):
            raise SessionConflict("ACP qualified recovery binding is incomplete")
        qualified = qualified_scope is not None
        if qualified and (qualified_generation is None or actual_cwd is None):
            raise SessionConflict("ACP qualified recovery binding is incomplete")
        qualified_boot_id = (
            qualified_scope["runtime_boot_id"] if qualified else record.boot_id)
        qualified_authority_epoch = (
            record.authority_epoch if operator_scope is not None or not qualified else
            record.qualified_authority_epoch
            if record.qualified_authority_epoch is not None else record.authority_epoch)
        if not actual_cwd or not Path(actual_cwd).resolve().is_relative_to(self._session_root):
            raise SessionConflict("ACP recovery working directory is not contained")
        value: dict[str, Any] = {
            "schema_version": (_ACP_ROOT_BINDING_V2_SCHEMA if qualified
                               else "byq-acp-root-binding.v1"),
            "session_id": record.session_id,
            "trace_id": record.trace_id,
            "owner_principal": record.owner_principal,
            "workspace_id": record.workspace_id,
            "root_run_id": root,
            "native_session_id": record.runtime_session_id,
            "runtime_generation": qualified_generation or record.runtime_generation,
            "model_provider": str(record.model_resolution.get("provider") or self._provider),
            "model_id": str(record.model_resolution.get("model") or self._model),
            "cwd": str(Path(actual_cwd).resolve()),
            "previous_boot_id": qualified_boot_id,
            "previous_authority_epoch": qualified_authority_epoch,
            "sequence": record.sequence,
            "settlement_receipt": None if starting_new_root else record.settlement_receipt,
            "domain_call_sequence": record.domain_call_sequence,
            "domain_call_drained_sequence": record.domain_call_drained_sequence,
            "native_session_close_confirmed": (False if starting_new_root else bool(
                record.current_generation and record.current_generation.native_session_close_confirmed)),
            "process_exit_confirmed": (False if starting_new_root else bool(
                record.current_generation and record.current_generation.process_exit_confirmed)),
            "cleanup_unconfirmed": True if starting_new_root else record.cleanup_unconfirmed,
            "closed": False if starting_new_root else record.conversation_ended,
        }
        if record.recovery_boundary is not None and not starting_new_root:
            boundary = record.recovery_boundary
            value["sequence"] = boundary["binding_sequence"]
            value["previous_boot_id"] = boundary["previous_boot_id"]
            value["previous_authority_epoch"] = boundary["previous_authority_epoch"]
            value["recovery_boundary"] = dict(boundary)
        if qualified:
            value["operator_scope"] = dict(qualified_scope)
            value["operator_binding"] = dict(qualified_binding)
        return value

    @staticmethod
    def _operator_fence_matches_current_root(record: RuntimeSession) -> bool:
        observation = record.operator_observation
        if not isinstance(observation, dict):
            return False
        if observation.get("schema_version") == _LOCAL_VALIDATION_HANDOFF_OBS_SCHEMA:
            try:
                checked = _local_validate_handoff_observation(observation)
            except (TypeError, ValueError):
                return False
            scope = checked["ack_intent"]["handoff"]["scope"]
        else:
            scope = observation.get("scope")
        return (
            isinstance(scope, dict)
            and scope.get("session_id") == record.session_id
            and scope.get("workspace_id") == record.workspace_id
            and scope.get("root_run_id") == record.process_root_id
            and scope.get("generation_id") == record.qualified_runtime_generation
            and record.qualified_operator_scope == scope
        )

    @staticmethod
    def _read_locked_acp_binding_payload(path: Path) -> bytes:
        try:
            before = os.lstat(path)
        except OSError as exc:
            raise SessionConflict("ACP recovery binding is unavailable") from exc
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or before.st_gid != os.getgid() or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_nlink != 1 or before.st_size > 1024 * 1024):
            raise SessionConflict("ACP recovery binding is unsafe")
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                opened = os.fstat(fd)
                if ((opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                        or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                        or opened.st_uid != os.getuid() or opened.st_gid != os.getgid()
                        or stat.S_IMODE(opened.st_mode) != 0o600
                        or opened.st_size != before.st_size or opened.st_size > 1024 * 1024):
                    raise SessionConflict("ACP recovery binding changed")
                chunks = bytearray()
                while len(chunks) <= 1024 * 1024:
                    chunk = os.read(fd, min(65536, 1024 * 1024 + 1 - len(chunks)))
                    if not chunk:
                        break
                    chunks.extend(chunk)
                after = os.lstat(path)
                if (len(chunks) != opened.st_size
                        or (after.st_dev, after.st_ino, after.st_size)
                        != (before.st_dev, before.st_ino, before.st_size)):
                    raise SessionConflict("ACP recovery binding changed")
                return bytes(chunks)
            finally:
                os.close(fd)
        except OSError as exc:
            raise SessionConflict("ACP recovery binding is unavailable") from exc

    @staticmethod
    def _replace_acp_binding_payload(path: Path, payload: bytes) -> None:
        temporary: Path | None = None
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

    def _capture_acp_binding_digest(self, session_id: str,
                                    expected: dict[str, Any]) -> str:
        path = self._acp_binding_path(session_id, expected.get("workspace_id"))
        lock_fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT
                          | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            raw = self._read_locked_acp_binding_payload(path)
            try:
                value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_json_object,
                                   parse_constant=_reject_json_constant)
            except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
                raise SessionConflict("ACP recovery binding changed") from exc
            if value != expected:
                raise SessionConflict("ACP recovery binding changed before settlement")
            return hashlib.sha256(raw).hexdigest()
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def _persist_qualified_settlement(
        self, record: RuntimeSession, *, expected_sha256: str,
        expected_binding: dict[str, Any], receipt: dict[str, Any],
    ) -> str:
        """CAS only the exact historical v2 settlement without rebinding its scope."""
        if (record.authority_epoch is None
                or expected_binding.get("schema_version") != _ACP_ROOT_BINDING_V2_SCHEMA
                or expected_binding.get("settlement_receipt") is not None
                or record.settlement_receipt != receipt
                or not hmac.compare_digest(hashlib.sha256(
                    canonical_product_json(expected_binding)).hexdigest(), expected_sha256)):
            raise SessionConflict("ACP qualified settlement identity is invalid")
        path = self._acp_binding_path(record.session_id, record.workspace_id)
        lock_fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT
                          | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            if self.require_current_backend_authority() != record.authority_epoch:
                raise SessionConflict("ACP settlement writer lost current Backend authority")
            raw = self._read_locked_acp_binding_payload(path)
            if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_sha256):
                raise SessionConflict("ACP qualified binding changed before settlement")
            try:
                current = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_json_object,
                                     parse_constant=_reject_json_constant)
            except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
                raise SessionConflict("ACP qualified binding changed before settlement") from exc
            if (current != expected_binding
                    or current.get("session_id") != record.session_id
                    or current.get("root_run_id") != record.process_root_id
                    or current.get("operator_scope") != record.qualified_operator_scope
                    or current.get("operator_binding") != record.qualified_operator_binding):
                raise SessionConflict("ACP qualified binding changed before settlement")
            updated = dict(current)
            updated["settlement_receipt"] = dict(receipt)
            payload = json.dumps(updated, sort_keys=True, separators=(",", ":")).encode()
            self._replace_acp_binding_payload(path, payload)
            persisted = self._read_locked_acp_binding_payload(path)
            if (not hmac.compare_digest(persisted, payload)
                    or self.require_current_backend_authority() != record.authority_epoch):
                raise SessionConflict("ACP qualified settlement write is uncertain")
            return hashlib.sha256(payload).hexdigest()
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def _persist_acp_binding(
        self, record: RuntimeSession, *, clear_qualified: bool = False,
        expected_previous: tuple[bytes | None, str | None] | None = None,
        root_run_id: str | None = None, runtime_generation: str | None = None,
        cwd: str | None = None, starting_new_root: bool = False,
        local_validation_pre_ack: dict[str, Any] | None = None,
    ) -> str | None:
        """Store the exact root/native binding; return its persisted payload digest."""

        if not self._acp:
            return
        if self._operator_fence_matches_current_root(record) and not starting_new_root:
            raise SessionConflict("operator-fenced ACP root cannot be rewritten as a normal binding")
        root = record.process_root_id
        if re.fullmatch(r"[0-9a-f]{32}", root) is None or record.authority_epoch is None:
            raise SessionConflict("ACP recovery binding has no exact root authority")
        if (type(starting_new_root) is not bool
                or (starting_new_root and (
                    not isinstance(root_run_id, str)
                    or not isinstance(runtime_generation, str)
                    or not isinstance(cwd, str)
                    or root_run_id != root
                    or not runtime_generation.startswith("generation-")
                    or not cwd
                    or not clear_qualified
                    or expected_previous is None
                    or root_run_id != record.process_root_id
                ))):
            raise SessionConflict("ACP prepared root binding identity is incomplete")
        value = self._acp_binding_value(
            record, root_run_id=root_run_id, runtime_generation=runtime_generation,
            cwd=cwd, include_qualified=not clear_qualified,
            starting_new_root=starting_new_root,
        )
        if local_validation_pre_ack is not None:
            value["schema_version"] = _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA
            value["local_validation_pre_ack"] = _local_validate_pre_ack_stop(
                local_validation_pre_ack, allow_stopping=True)
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
            if expected_previous is not None:
                expected_raw, expected_digest = expected_previous
                try:
                    previous_raw = self._read_locked_acp_binding_payload(path)
                except SessionConflict as exc:
                    if (expected_raw is not None or expected_digest is not None
                            or not isinstance(exc.__cause__, FileNotFoundError)):
                        raise SessionConflict(
                            "ACP predecessor binding changed before prepared root write") from None
                else:
                    if (not isinstance(expected_raw, bytes)
                            or not isinstance(expected_digest, str)
                            or not hmac.compare_digest(
                                hashlib.sha256(expected_raw).hexdigest(), expected_digest)
                            or not hmac.compare_digest(previous_raw, expected_raw)):
                        raise SessionConflict(
                            "ACP predecessor binding changed before prepared root write")
                if self.require_current_backend_authority() != record.authority_epoch:
                    raise SessionConflict("ACP prepared root writer lost Backend authority")
            self._replace_acp_binding_payload(path, payload)
            if (expected_previous is not None
                    and self.require_current_backend_authority() != record.authority_epoch):
                raise SessionConflict("ACP prepared root write lost Backend authority")
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        if clear_qualified:
            record.qualified_operator_scope = None
            record.qualified_operator_binding = None
            record.qualified_runtime_generation = None
            record.qualified_cwd = None
            record.qualified_authority_epoch = None
        if starting_new_root:
            record.recovery_boundary = None
        return hashlib.sha256(payload).hexdigest()

    def _assert_qualified_prestart_binding(
        self, record: RuntimeSession, *, expected_sha256: str, root_run_id: str,
        runtime_generation: str, cwd: str, native_session_id: str | None,
    ) -> None:
        path = self._acp_binding_path(record.session_id, record.workspace_id)
        lock_fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT
                          | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            raw = self._read_locked_acp_binding_payload(path)
            if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_sha256):
                raise SessionConflict("ACP prepared binding changed before qualified admission")
            try:
                value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_json_object,
                                   parse_constant=_reject_json_constant)
            except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
                raise SessionConflict("ACP prepared binding is invalid") from exc
            if (not isinstance(value, dict)
                    or value.get("schema_version") != "byq-acp-root-binding.v1"
                    or value.get("session_id") != record.session_id
                    or value.get("trace_id") != record.trace_id
                    or value.get("owner_principal") != record.owner_principal
                    or value.get("workspace_id") != record.workspace_id
                    or value.get("root_run_id") != root_run_id
                    or value.get("native_session_id") != native_session_id
                    or value.get("runtime_generation") != runtime_generation
                    or value.get("cwd") != str(Path(cwd).resolve())
                    or value.get("previous_boot_id") != record.boot_id
                    or value.get("previous_authority_epoch") != record.authority_epoch
                    or value.get("settlement_receipt") is not None
                    or value.get("native_session_close_confirmed") is not False
                    or value.get("process_exit_confirmed") is not False
                    or value.get("cleanup_unconfirmed") is not True
                    or value.get("closed") is not False):
                raise SessionConflict("ACP prepared binding is not the exact open root fence")
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def _persist_qualified_acp_binding(
        self, record: RuntimeSession, *, base_sha256: str, root_run_id: str,
        runtime_generation: str, cwd: str, operator_scope: dict[str, str],
        operator_binding: dict[str, Any],
    ) -> tuple[str, bytes]:
        """CAS one exact pre-START v1 fence to a qualified v2 binding."""
        if not self._acp_product_slots or record.authority_epoch is None:
            raise SessionConflict("ACP qualified binding has no current authority")
        if (_ACP_HEX64.fullmatch(base_sha256) is None
                or _ACP_HEX32.fullmatch(root_run_id) is None
                or not runtime_generation.startswith("generation-")
                or set(operator_scope) != PRODUCT_SCOPE_KEYS
                or set(operator_binding) != START_BINDING_FIELDS):
            raise SessionConflict("ACP qualified binding identity is invalid")
        checked_scope = validate_product_scope(operator_scope)
        if (checked_scope["workspace_id"] != record.workspace_id
                or checked_scope["owner_principal"] != record.owner_principal
                or checked_scope["session_id"] != record.session_id
                or checked_scope["trace_id"] != record.trace_id
                or checked_scope["root_run_id"] != root_run_id
                or checked_scope["runtime_boot_id"] != self.boot_id
                or checked_scope["generation_id"] != runtime_generation
                or checked_scope["cwd_leaf"] != Path(cwd).name):
            raise SessionConflict("ACP qualified binding scope is stale")
        path = self._acp_binding_path(record.session_id, record.workspace_id)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT
                          | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            if self.require_current_backend_authority() != record.authority_epoch:
                raise SessionConflict("ACP qualified binding writer lost Backend authority")
            previous_raw = self._read_locked_acp_binding_payload(path)
            if not hmac.compare_digest(hashlib.sha256(previous_raw).hexdigest(), base_sha256):
                raise SessionConflict("ACP prepared binding changed before v2 write")
            try:
                previous = json.loads(previous_raw.decode("utf-8"),
                                      object_pairs_hook=_strict_json_object,
                                      parse_constant=_reject_json_constant)
            except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
                raise SessionConflict("ACP prepared binding is invalid") from exc
            if (not isinstance(previous, dict)
                    or previous.get("schema_version") != "byq-acp-root-binding.v1"
                    or previous.get("session_id") != record.session_id
                    or previous.get("trace_id") != record.trace_id
                    or previous.get("owner_principal") != record.owner_principal
                    or previous.get("workspace_id") != record.workspace_id
                    or previous.get("root_run_id") != root_run_id
                    or previous.get("native_session_id") != record.runtime_session_id
                    or previous.get("runtime_generation") != runtime_generation
                    or previous.get("cwd") != str(Path(cwd).resolve())
                    or previous.get("previous_boot_id") != record.boot_id
                    or previous.get("previous_authority_epoch") != record.authority_epoch
                    or previous.get("settlement_receipt") is not None
                    or previous.get("native_session_close_confirmed") is not False
                    or previous.get("process_exit_confirmed") is not False
                    or previous.get("cleanup_unconfirmed") is not True
                    or previous.get("closed") is not False):
                raise SessionConflict("ACP prepared binding is not the exact open root fence")
            value = self._acp_binding_value(
                record, root_run_id=root_run_id, runtime_generation=runtime_generation,
                cwd=cwd, operator_scope=checked_scope, operator_binding=operator_binding,
                starting_new_root=True,
            )
            payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            self._replace_acp_binding_payload(path, payload)
            if self.require_current_backend_authority() != record.authority_epoch:
                raise SessionConflict("ACP qualified binding writer lost Backend authority")
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        record.qualified_operator_scope = checked_scope
        record.qualified_operator_binding = dict(operator_binding)
        record.qualified_runtime_generation = runtime_generation
        record.qualified_cwd = str(Path(cwd).resolve())
        record.qualified_authority_epoch = record.authority_epoch
        return hashlib.sha256(payload).hexdigest(), previous_raw

    def _retire_qualified_prestart_binding(
        self, record: RuntimeSession, *, expected_sha256: str,
        previous_sha256: str, previous_raw: bytes, operator_scope: dict[str, str],
        operator_binding: dict[str, Any],
    ) -> None:
        """Restore the exact v1 fence only after an authenticated prelaunch REJECT."""
        if (not hmac.compare_digest(hashlib.sha256(previous_raw).hexdigest(), previous_sha256)
                or _ACP_HEX64.fullmatch(expected_sha256) is None):
            raise SessionConflict("ACP qualified prestart receipt is invalid")
        path = self._acp_binding_path(record.session_id, record.workspace_id)
        lock_fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT
                          | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            if self.require_current_backend_authority() != record.authority_epoch:
                raise SessionConflict("ACP qualified retirement lost Backend authority")
            current_raw = self._read_locked_acp_binding_payload(path)
            if not hmac.compare_digest(hashlib.sha256(current_raw).hexdigest(), expected_sha256):
                raise SessionConflict("ACP qualified binding changed before retirement")
            try:
                current = json.loads(current_raw.decode("utf-8"),
                                     object_pairs_hook=_strict_json_object,
                                     parse_constant=_reject_json_constant)
            except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
                raise SessionConflict("ACP qualified binding is invalid") from exc
            if (not isinstance(current, dict)
                    or current.get("schema_version") != _ACP_ROOT_BINDING_V2_SCHEMA
                    or current.get("session_id") != record.session_id
                    or current.get("trace_id") != record.trace_id
                    or current.get("owner_principal") != record.owner_principal
                    or current.get("workspace_id") != record.workspace_id
                    or current.get("root_run_id") != operator_scope["root_run_id"]
                    or current.get("runtime_generation") != operator_scope["generation_id"]
                    or current.get("operator_scope") != operator_scope
                    or current.get("operator_binding") != operator_binding
                    or current.get("previous_boot_id") != self.boot_id
                    or current.get("previous_authority_epoch") != record.authority_epoch
                    or current.get("native_session_close_confirmed") is not False
                    or current.get("process_exit_confirmed") is not False
                    or current.get("cleanup_unconfirmed") is not True
                    or current.get("settlement_receipt") is not None
                    or current.get("closed") is not False):
                raise SessionConflict("ACP qualified binding is not the exact prepared root")
            self._replace_acp_binding_payload(path, previous_raw)
            if self.require_current_backend_authority() != record.authority_epoch:
                raise SessionConflict("ACP qualified retirement lost Backend authority")
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        record.qualified_operator_scope = None
        record.qualified_operator_binding = None
        record.qualified_runtime_generation = None
        record.qualified_cwd = None
        record.qualified_authority_epoch = None

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

    def _capture_prestart_predecessor(
        self, record: RuntimeSession, *, expected_root_id: str,
    ) -> tuple[bytes | None, str | None]:
        """Freeze the exact safe predecessor before replacing a Runtime fence."""
        path = self._acp_binding_path(record.session_id, record.workspace_id)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT
                          | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                raw = self._read_locked_acp_binding_payload(path)
            except SessionConflict as exc:
                if isinstance(exc.__cause__, FileNotFoundError):
                    if record.process_used:
                        raise SessionConflict("settled ACP predecessor is unavailable") from None
                    return None, None
                raise
            try:
                parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_json_object,
                                    parse_constant=_reject_json_constant)
                checked = self._read_acp_binding(record.session_id)
            except (UnicodeError, ValueError, TypeError, RecursionError, KeyError) as exc:
                raise SessionConflict("ACP predecessor binding is invalid") from exc
            handoff_v3 = (
                isinstance(parsed, dict)
                and parsed.get("schema_version") == _ACP_ROOT_BINDING_V3_SCHEMA
                and "operator_handoff" in parsed
            )
            observation = (checked.get("operator_handoff_observation") if handoff_v3 else
                           parsed.get("operator_observation") if isinstance(parsed, dict) else None)
            operator_candidate = (
                isinstance(parsed, dict)
                and parsed.get("schema_version") == _ACP_ROOT_BINDING_V3_SCHEMA
                and isinstance(observation, dict)
                and observation == record.operator_observation
                and observation.get("scope", {}).get("root_run_id") == expected_root_id
                and record.process_root_id == expected_root_id
            )
            if (not isinstance(parsed, dict)
                    or parsed.get("session_id") != record.session_id
                    or parsed.get("trace_id") != record.trace_id
                    or parsed.get("owner_principal") != record.owner_principal
                    or parsed.get("workspace_id") != record.workspace_id
                    or parsed.get("root_run_id") != expected_root_id
                    or parsed.get("closed") is not False
                    or (parsed.get("cleanup_unconfirmed") is not False and not operator_candidate)
                    or checked.get("root_run_id") != expected_root_id):
                raise SessionConflict("ACP predecessor binding does not match this Runtime root")
            normalized = dict(parsed)
            if normalized.get("schema_version") == "byq-acp-root-binding.v1":
                normalized.setdefault("native_session_close_confirmed", False)
                normalized.setdefault("process_exit_confirmed", False)
                normalized.setdefault("cleanup_unconfirmed", False)
            if normalized != checked:
                raise SessionConflict("ACP predecessor binding changed during capture")
            if record.process_used:
                operator_retired = (
                    operator_candidate
                    and record.active_run is None
                    and not record.pending_terminal_receipts
                    and record.domain_call_sequence == record.domain_call_drained_sequence
                    and parsed.get("cleanup_unconfirmed") is record.cleanup_unconfirmed
                    and parsed.get("settlement_receipt") == record.settlement_receipt
                )
                if not operator_retired and (
                        parsed.get("settlement_receipt") != record.settlement_receipt
                        or not parsed.get("settlement_receipt")
                        or parsed.get("native_session_close_confirmed") is not True
                        or parsed.get("process_exit_confirmed") is not True
                        or parsed.get("domain_call_sequence")
                        != parsed.get("domain_call_drained_sequence")):
                    raise SessionConflict("ACP predecessor is not exactly settled and closed")
            elif (parsed.get("settlement_receipt") is not None
                    or parsed.get("native_session_close_confirmed") is not False
                    or parsed.get("process_exit_confirmed") is not False):
                raise SessionConflict("ACP unused predecessor has unexpected close facts")
            return raw, hashlib.sha256(raw).hexdigest()
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def _restore_prestart_acp_binding(
        self, record: RuntimeSession, *, expected_sha256: str,
        predecessor_raw: bytes | None, expected_root_id: str,
        expected_runtime_generation: str, expected_cwd: str,
        expected_native_session_id: str | None,
    ) -> None:
        """CAS only this exact unlaunched base fence back to its frozen predecessor."""
        if _ACP_HEX64.fullmatch(expected_sha256) is None:
            raise SessionConflict("ACP prepared binding digest is invalid")
        path = self._acp_binding_path(record.session_id, record.workspace_id)
        lock_fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT
                          | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            if self.require_current_backend_authority() != record.authority_epoch:
                raise SessionConflict("ACP prepared binding writer lost Backend authority")
            current_raw = self._read_locked_acp_binding_payload(path)
            if not hmac.compare_digest(hashlib.sha256(current_raw).hexdigest(), expected_sha256):
                raise SessionConflict("ACP prepared binding changed before retirement")
            try:
                current = json.loads(current_raw.decode("utf-8"),
                                     object_pairs_hook=_strict_json_object,
                                     parse_constant=_reject_json_constant)
            except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
                raise SessionConflict("ACP prepared binding is invalid") from exc
            if (not isinstance(current, dict)
                    or current.get("schema_version") != "byq-acp-root-binding.v1"
                    or current.get("session_id") != record.session_id
                    or current.get("trace_id") != record.trace_id
                    or current.get("owner_principal") != record.owner_principal
                    or current.get("workspace_id") != record.workspace_id
                    or current.get("root_run_id") != expected_root_id
                    or current.get("native_session_id") != expected_native_session_id
                    or current.get("runtime_generation") != expected_runtime_generation
                    or current.get("model_provider") != str(
                        record.model_resolution.get("provider") or self._provider)
                    or current.get("model_id") != str(
                        record.model_resolution.get("model") or self._model)
                    or current.get("cwd") != str(Path(expected_cwd).resolve())
                    or current.get("previous_boot_id") != record.boot_id
                    or current.get("previous_authority_epoch") != record.authority_epoch
                    or current.get("sequence") != record.sequence
                    or current.get("domain_call_sequence") != record.domain_call_sequence
                    or current.get("domain_call_drained_sequence")
                    != record.domain_call_drained_sequence
                    or current.get("native_session_close_confirmed") is not False
                    or current.get("process_exit_confirmed") is not False
                    or current.get("cleanup_unconfirmed") is not True
                    or current.get("settlement_receipt") is not None
                    or current.get("closed") is not False):
                raise SessionConflict("ACP prepared binding is not the exact open root fence")
            if predecessor_raw is None:
                if record.process_used:
                    raise SessionConflict("settled ACP predecessor cannot be removed")
                os.unlink(path)
                directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                target_sha256 = None
            else:
                self._replace_acp_binding_payload(path, predecessor_raw)
                target_sha256 = hashlib.sha256(predecessor_raw).hexdigest()
            if self.require_current_backend_authority() != record.authority_epoch:
                raise SessionConflict("ACP prepared binding writer lost Backend authority")
            if target_sha256 is None:
                try:
                    os.lstat(path)
                except FileNotFoundError:
                    pass
                else:
                    raise SessionConflict("ACP prepared binding was not removed")
            elif not hmac.compare_digest(
                    hashlib.sha256(self._read_locked_acp_binding_payload(path)).hexdigest(),
                    target_sha256):
                raise SessionConflict("ACP predecessor binding was not restored")
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def _verify_prestart_retirement_receipt(
        self, record: RuntimeSession, receipt: object, *, scope: dict[str, str],
        base_sha256: str | None, guard_sha256: str | None,
        predecessor_raw: bytes | None, predecessor_sha256: str | None,
    ) -> None:
        from .acp_product_slot_client import ProductSlotPrebindRetirement
        try:
            checked_scope = validate_product_scope(scope)
        except (TypeError, ValueError):
            raise SessionConflict("ACP no-start retirement scope is invalid") from None
        expected_target = predecessor_sha256
        disposition = "restored" if predecessor_raw is not None else "removed"
        if (not isinstance(receipt, ProductSlotPrebindRetirement)
                or _ACP_HEX64.fullmatch(base_sha256 or "") is None
                or _ACP_HEX64.fullmatch(guard_sha256 or "") is None
                or receipt.scope_digest != product_scope_digest(checked_scope)
                or receipt.root_run_id != checked_scope["root_run_id"]
                or receipt.base_binding_sha256 != base_sha256
                or receipt.prepared_guard_sha256 != guard_sha256
                or receipt.disposition != disposition
                or receipt.retired_binding_sha256 != expected_target
                or (predecessor_raw is not None
                    and (not isinstance(predecessor_sha256, str)
                         or not hmac.compare_digest(
                             hashlib.sha256(predecessor_raw).hexdigest(), predecessor_sha256)))):
            raise SessionConflict("ACP no-start retirement receipt does not match this root")
        path = self._acp_binding_path(record.session_id, record.workspace_id)
        if predecessor_raw is None:
            try:
                os.lstat(path)
            except FileNotFoundError:
                return
            raise SessionConflict("ACP no-start binding retirement is incomplete")
        lock_fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT
                          | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            current = self._read_locked_acp_binding_payload(path)
            if (not hmac.compare_digest(current, predecessor_raw)
                    or not hmac.compare_digest(
                        hashlib.sha256(current).hexdigest(), predecessor_sha256 or "")):
                raise SessionConflict("ACP no-start predecessor binding is not restored")
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def _read_acp_binding(self, session_id: str) -> dict[str, Any]:
        if not self._acp:
            raise KeyError(session_id)
        path = self._acp_binding_path(session_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"),
                               object_pairs_hook=_strict_json_object,
                               parse_constant=_reject_json_constant)
        except FileNotFoundError as exc:
            raise KeyError(session_id) from exc
        # Additive v1 compatibility: older bindings omit close proofs and are
        # always treated as non-reusable. A process restart never transfers the
        # in-memory normal-completion reuse gate.
        if (isinstance(value, dict)
                and value.get("schema_version") == "byq-acp-root-binding.v1"):
            value.setdefault("native_session_close_confirmed", False)
            value.setdefault("process_exit_confirmed", False)
            value.setdefault("cleanup_unconfirmed", False)
        base_fields = {"schema_version", "session_id", "trace_id", "owner_principal",
                       "workspace_id", "root_run_id", "native_session_id",
                       "runtime_generation", "model_provider", "model_id", "cwd",
                       "previous_boot_id", "previous_authority_epoch", "sequence",
                       "settlement_receipt", "domain_call_sequence",
                       "domain_call_drained_sequence", "native_session_close_confirmed",
                       "process_exit_confirmed", "cleanup_unconfirmed", "closed"}
        schema_version = value.get("schema_version") if isinstance(value, dict) else None
        qualified_fields = base_fields | {"operator_scope", "operator_binding"}
        expected_fields = (
            qualified_fields | ({"operator_handoff", "operator_handoff_observation", "final_live_sequence"}
                if isinstance(value, dict) and "operator_handoff" in value
                else {"operator_observation", "final_live_sequence"})
            if schema_version == _ACP_ROOT_BINDING_V3_SCHEMA else
            ((qualified_fields if "operator_scope" in value else base_fields)
             | {"local_validation_ack_intent", "local_validation_release_observation"})
            if schema_version == _ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA
            and isinstance(value, dict) and "local_validation_release_observation" in value else
            ((qualified_fields if "operator_scope" in value else base_fields)
             | {"local_validation_ack_intent"})
            if schema_version == _ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA else
            ((qualified_fields if "operator_scope" in value else base_fields)
             | {"local_validation_pre_ack", "local_validation_handoff", "local_validation_handoff_intent"}
             | ({"local_validation_handoff_observation"}
                if isinstance(value, dict) and "local_validation_handoff_observation" in value else set()))
            if schema_version == _ACP_ROOT_BINDING_LOCAL_VALIDATION_HANDOFF_SCHEMA else
            (qualified_fields if "operator_scope" in value else base_fields)
                | {"local_validation_pre_ack"}
            if schema_version == _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA
            and isinstance(value, dict) else
            qualified_fields if schema_version == _ACP_ROOT_BINDING_V2_SCHEMA else base_fields
        )
        if isinstance(value, dict) and "recovery_boundary" in value:
            if schema_version not in {"byq-acp-root-binding.v1", _ACP_ROOT_BINDING_V2_SCHEMA}:
                raise SessionConflict("ACP recovery boundary is not valid for this binding schema")
            expected_fields = set(expected_fields) | {"recovery_boundary"}
        if (not isinstance(value, dict)
                or set(value) != expected_fields
                or schema_version not in {
                    "byq-acp-root-binding.v1", _ACP_ROOT_BINDING_V2_SCHEMA,
                    _ACP_ROOT_BINDING_V3_SCHEMA, _ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA,
                    _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA,
                    _ACP_ROOT_BINDING_LOCAL_VALIDATION_HANDOFF_SCHEMA,
                }
                or value["session_id"] != session_id
                or re.fullmatch(r"[0-9a-f]{32}", str(value["root_run_id"])) is None
                or re.fullmatch(r"[0-9a-f]{32}", str(value["previous_boot_id"])) is None
                or type(value["previous_authority_epoch"]) is not int
                or type(value["sequence"]) is not int
                or not 0 <= value["sequence"] < 2**63
                or type(value["domain_call_sequence"]) is not int
                or type(value["domain_call_drained_sequence"]) is not int
                or not 0 <= value["domain_call_drained_sequence"] <= value["domain_call_sequence"]
                or (schema_version == _ACP_ROOT_BINDING_V3_SCHEMA
                    and (type(value.get("final_live_sequence")) is not int
                         or not value["sequence"] <= value["final_live_sequence"] < 2**63))
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
        if schema_version in {_ACP_ROOT_BINDING_V2_SCHEMA, _ACP_ROOT_BINDING_V3_SCHEMA,
                              _ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA,
                              _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA,
                              _ACP_ROOT_BINDING_LOCAL_VALIDATION_HANDOFF_SCHEMA}:
            local_intent = None
            local_observation = None
            if schema_version == _ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA:
                try:
                    local_intent = _local_validate_ack_intent(value["local_validation_ack_intent"])
                    local_observation = (None if "local_validation_release_observation" not in value else
                        _local_validate_ack_observation(value["local_validation_release_observation"]))
                except (KeyError, TypeError, ValueError) as exc:
                    raise SessionConflict("ACP local validation ACK binding is invalid") from exc
                local_final = local_intent["final_receipt"]
                local_scope = value.get("operator_scope")
                if local_scope is None:
                    local_scope = {
                        "workspace_id": value["workspace_id"],
                        "owner_principal": value["owner_principal"],
                        "session_id": value["session_id"], "trace_id": value["trace_id"],
                        "root_run_id": value["root_run_id"],
                        "runtime_boot_id": value["previous_boot_id"],
                        "generation_id": value["runtime_generation"],
                        "cwd_leaf": cwd.name,
                    }
                if (local_final["scope"] != local_scope
                        or local_intent["runtime_boot_id"] != value.get("previous_boot_id")
                        or local_intent["runtime_authority_epoch"] != value.get("previous_authority_epoch")
                        or value.get("settlement_receipt") != local_final["terminal_event_receipt"]
                        or (local_observation is not None
                            and local_observation["ack_intent"] != local_intent)):
                    raise SessionConflict("ACP local validation ACK binding identity changed")
            if schema_version == _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA:
                try:
                    pre_ack = _local_validate_pre_ack_stop(value["local_validation_pre_ack"], allow_stopping=True)
                except (KeyError, TypeError, ValueError) as exc:
                    raise SessionConflict("ACP local validation pre-ACK binding is invalid") from exc
                if (pre_ack["root_run_id"] != value["root_run_id"]
                        or value.get("settlement_receipt") is not None
                        or pre_ack["state"] == "stopped" and (
                            value.get("process_exit_confirmed") is not True
                            or value.get("cleanup_unconfirmed") is not False)):
                    raise SessionConflict("ACP local validation pre-ACK binding facts changed")
            if schema_version == _ACP_ROOT_BINDING_LOCAL_VALIDATION_HANDOFF_SCHEMA:
                try:
                    handoff = _local_validate_handoff(value["local_validation_handoff"])
                    intent = _local_validate_handoff_intent(value["local_validation_handoff_intent"])
                    observation = (None if "local_validation_handoff_observation" not in value else
                        _local_validate_handoff_observation(value["local_validation_handoff_observation"]))
                    pre_ack = _local_validate_pre_ack_stop(value["local_validation_pre_ack"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise SessionConflict("ACP local validation handoff binding is invalid") from exc
                handoff_scope = handoff["scope"]
                if (intent["handoff"] != handoff
                        or intent["runtime_boot_id"] != handoff["new_authority"]["boot_id"]
                        or intent["runtime_authority_epoch"] != handoff["new_authority"]["epoch"]
                        or handoff_scope["session_id"] != session_id
                        or handoff_scope["root_run_id"] != value["root_run_id"]
                        or handoff_scope["owner_principal"] != value["owner_principal"]
                        or handoff_scope["workspace_id"] != value["workspace_id"]
                        or handoff_scope["trace_id"] != value["trace_id"]
                        or handoff_scope["generation_id"] != value["runtime_generation"]
                        or intent["final_receipt"]["terminal_event_receipt"] != value["settlement_receipt"]
                        or pre_ack["root_run_id"] != value["root_run_id"]
                        or pre_ack["reservation_sha256"] != handoff["reservation_sha256"]
                        or pre_ack["cleanup_receipt_sha256"] != handoff["cleanup_receipt_sha256"]
                        or value.get("native_session_close_confirmed") is not True
                        or value.get("process_exit_confirmed") is not True
                        or value.get("cleanup_unconfirmed") is not False
                        or value.get("closed") is not False
                        or (observation is not None and observation["ack_intent"] != intent)):
                    raise SessionConflict("ACP local validation handoff identity changed")
            settlement = value["settlement_receipt"]
            settlement_limit = (intent["final_receipt"]["terminal_event_receipt"]["sequence"]
                                if schema_version == _ACP_ROOT_BINDING_LOCAL_VALIDATION_HANDOFF_SCHEMA
                                else local_intent["final_live_sequence"] if local_intent is not None
                                else value.get("final_live_sequence", value["sequence"]))
            if settlement is not None and (
                    not isinstance(settlement, dict)
                    or set(settlement) != {"schema_version", "root_run_id", "sequence", "event_sha256"}
                    or settlement.get("schema_version") != "agent-run-lifecycle-receipt.v1"
                    or settlement.get("root_run_id") != value["root_run_id"]
                    or type(settlement.get("sequence")) is not int
                    or not 1 <= settlement["sequence"] <= settlement_limit
                    or not isinstance(settlement.get("event_sha256"), str)
                    or _ACP_HEX64.fullmatch(settlement["event_sha256"]) is None):
                raise SessionConflict("ACP qualified settlement receipt is invalid")
            if (schema_version in {_ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA,
                                    _ACP_ROOT_BINDING_LOCAL_VALIDATION_PRE_ACK_SCHEMA,
                                    _ACP_ROOT_BINDING_LOCAL_VALIDATION_HANDOFF_SCHEMA}
                    and "operator_scope" not in value):
                return value
            try:
                scope = validate_product_scope(value["operator_scope"])
            except (TypeError, ValueError):
                raise SessionConflict("ACP qualified recovery scope is invalid") from None
            binding = value["operator_binding"]
            if (not isinstance(binding, dict) or set(binding) != START_BINDING_FIELDS
                    or binding.get("schema_version") != START_BINDING_SCHEMA):
                # The exact signed instance is checked by Runner on START. Here
                # validate the persisted closed shape and its root scope only.
                raise SessionConflict("ACP qualified recovery binding is invalid")
            if (scope["workspace_id"] != value["workspace_id"]
                    or scope["owner_principal"] != value["owner_principal"]
                    or scope["session_id"] != value["session_id"]
                    or scope["trace_id"] != value["trace_id"]
                    or scope["root_run_id"] != value["root_run_id"]
                    or scope["runtime_boot_id"] != value["previous_boot_id"]
                    or scope["generation_id"] != value["runtime_generation"]
                    or scope["cwd_leaf"] != cwd.name
                    or any(not isinstance(binding.get(field), str)
                           or _ACP_HEX64.fullmatch(binding[field]) is None for field in (
                               "runner_instance_id", "state_generation", "signed_instance_sha256",
                               "prepared_receipt_sha256", "backend_binding_nonce",
                               "install_receipt_sha256", "backend_activation_receipt_sha256"))
                    or not isinstance(binding.get("runner_boot_id"), str)
                    or _ACP_HEX32.fullmatch(binding["runner_boot_id"]) is None
                    or not isinstance(binding.get("backend_activation_id"), str)
                    or _ACP_HEX32.fullmatch(binding["backend_activation_id"]) is None):
                raise SessionConflict("ACP qualified recovery binding scope is invalid")
            value["operator_scope"] = scope
            if schema_version == _ACP_ROOT_BINDING_V3_SCHEMA:
                if "operator_handoff" in value:
                    try:
                        handoff_request = _r2_validate_handoff_request(value["operator_handoff"])
                        handoff = handoff_request["handoff"]
                        handoff_observation = _r2_validate_handoff_observation(
                            value["operator_handoff_observation"], handoff=handoff)
                    except (_R2FenceContractError, KeyError, TypeError, ValueError) as exc:
                        raise SessionConflict("ACP handoff recovery observation is invalid") from exc
                    predecessor = dict(value)
                    predecessor.pop("operator_handoff")
                    predecessor.pop("operator_handoff_observation")
                    predecessor.pop("final_live_sequence")
                    predecessor["schema_version"] = _ACP_ROOT_BINDING_V2_SCHEMA
                    predecessor_sha = hashlib.sha256(canonical_product_json(predecessor)).hexdigest()
                    close = handoff_request["close_receipt"]
                    completed = close.get("operator_completed_cleanup")
                    if (handoff["scope"] != scope
                            or handoff["runtime_binding_sha256"] != predecessor_sha
                            or handoff_observation["original_binding_sha256"] != predecessor_sha
                            or value["previous_boot_id"] != close["authority"]["previous_boot_id"]
                            or value["previous_authority_epoch"] != close["authority"]["previous_epoch"]
                            or handoff["old_authority"] != {
                                "boot_id": close["authority"]["current_boot_id"],
                                "epoch": close["authority"]["current_epoch"]}
                            or handoff["new_authority"] != {
                                "boot_id": handoff_observation["runtime_boot_id"],
                                "epoch": handoff_observation["runtime_authority_epoch"]}
                            or value["final_live_sequence"] != 344
                            or value["native_session_close_confirmed"] is not True
                            or value["process_exit_confirmed"] is not False
                            or value["cleanup_unconfirmed"] is not False
                            or value["domain_call_sequence"] != value["domain_call_drained_sequence"]
                            or not isinstance(settlement, dict)
                            or _r2_digest(settlement) != completed["original_terminal_receipt_sha256"]
                            or settlement.get("sequence") != 344
                            or settlement.get("event_sha256")
                                != "0763e967f42dc958edbf3fb832b1dc5f84b4dfc2455cc4a774debc763fe45e1e"
                            or handoff_observation["domain_call_drain"]["drained_sequence"]
                                != value["domain_call_drained_sequence"]
                            or handoff_observation["slot_release"]["tombstone_sha256"]
                                != close["runner"]["tombstone_sha256"]):
                        raise SessionConflict("ACP cleanup handoff no longer matches its exact V2 predecessor")
                    value["operator_handoff"] = handoff_request
                    value["operator_handoff_observation"] = handoff_observation
                    return value
                try:
                    observation = _r2_validate_operator_observation_record(
                        value["operator_observation"])
                except _R2FenceContractError as exc:
                    raise SessionConflict("ACP operator recovery observation is invalid") from exc
                predecessor = dict(value)
                predecessor.pop("operator_observation")
                predecessor.pop("final_live_sequence")
                predecessor["schema_version"] = _ACP_ROOT_BINDING_V2_SCHEMA
                predecessor_sha256 = hashlib.sha256(
                    canonical_product_json(predecessor)).hexdigest()
                drain = observation["domain_call_drain"]
                release = observation["slot_release"]
                failed_fact = observation.get("operator_failed_terminal")
                completed_fact = observation.get("operator_completed_cleanup")
                exact_failed_receipt = ({
                    "schema_version": "agent-run-lifecycle-receipt.v1",
                    "root_run_id": value["root_run_id"],
                    "sequence": failed_fact["sequence"],
                    "event_sha256": failed_fact["event_sha256"],
                } if failed_fact is not None else None)
                exact_completed_receipt = (settlement if completed_fact is not None
                    and isinstance(settlement, dict)
                    and settlement.get("root_run_id") == value["root_run_id"]
                    and _r2_digest(settlement) == completed_fact["original_terminal_receipt_sha256"]
                    else None)
                if (observation["scope"] != scope
                        or (settlement not in (None, exact_failed_receipt)
                            and settlement != exact_completed_receipt)
                        or (completed_fact is not None and exact_completed_receipt is None)
                        or observation["runtime_binding_sha256"] != predecessor_sha256
                        or observation["runtime_ack"]["root_binding_sha256"] != predecessor_sha256
                        or observation["runtime_ack"]["root_run_id"] != value["root_run_id"]
                        or observation["runtime_ack"]["runtime_boot_id"] != (
                            observation["authority"]["current_boot_id"]
                            if completed_fact is not None else value["previous_boot_id"])
                        or observation["authority"]["previous_boot_id"] != value["previous_boot_id"]
                        or observation["authority"]["previous_epoch"] != value["previous_authority_epoch"]
                        or drain["root_run_id"] != value["root_run_id"]
                        or drain["last_domain_sequence"] != value["domain_call_sequence"]
                        or drain["drained_sequence"] != value["domain_call_drained_sequence"]
                        or release["workspace_id"] != value["workspace_id"]
                        or release["root_run_id"] != value["root_run_id"]
                        or release["scope_sha256"] != _r2_digest(scope)
                        or release["drained_sequence"] != value["domain_call_drained_sequence"]
                        or release["tombstone_sha256"] != observation["runner"]["tombstone_sha256"]
                        or ("operator_failed_terminal" in observation
                            and observation["operator_failed_terminal"]["sequence"]
                                > value["final_live_sequence"])
                        or (observation["superseded_terminal"] is not None
                            and (observation["superseded_terminal"]["sequence"]
                                 > value["final_live_sequence"]))):
                    raise SessionConflict("ACP operator recovery observation binding changed")
                value["operator_observation"] = observation
        if "recovery_boundary" in value:
            boundary = value["recovery_boundary"]
            boundary_fields = {
                "schema_version", "binding_sequence", "previous_boot_id",
                "previous_authority_epoch", "runtime_boot_id", "runtime_authority_epoch",
                "next_sequence", "event_json_b64", "event_sha256", "state",
            }
            try:
                event_raw = base64.b64decode(boundary["event_json_b64"], validate=True)
                event = json.loads(event_raw.decode("utf-8"), object_pairs_hook=_strict_json_object,
                                   parse_constant=_reject_json_constant)
                event = validate_workflow_trace_event(event)
            except (KeyError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
                raise SessionConflict("ACP recovery boundary event is invalid") from exc
            receipt = value.get("settlement_receipt")
            receipt_sha256 = (hashlib.sha256(json.dumps(
                receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                if isinstance(receipt, dict) else None)
            if (not isinstance(boundary, dict) or set(boundary) != boundary_fields
                    or boundary.get("schema_version") != _ACP_RECOVERY_BOUNDARY_SCHEMA
                    or type(boundary.get("binding_sequence")) is not int
                    or not 0 <= boundary["binding_sequence"] < 2**63 - 1
                    or boundary["binding_sequence"] != value["sequence"]
                    or boundary.get("previous_boot_id") != value["previous_boot_id"]
                    or boundary.get("previous_authority_epoch") != value["previous_authority_epoch"]
                    or type(boundary.get("previous_authority_epoch")) is not int
                    or type(boundary.get("runtime_authority_epoch")) is not int
                    or boundary["runtime_authority_epoch"] < 1
                    or _ACP_HEX32.fullmatch(str(boundary.get("runtime_boot_id"))) is None
                    or type(boundary.get("next_sequence")) is not int
                    or boundary["next_sequence"] != boundary["binding_sequence"] + 1
                    or boundary.get("state") not in {"pending", "acknowledged"}
                    or not isinstance(boundary.get("event_json_b64"), str)
                    or not isinstance(boundary.get("event_sha256"), str)
                    or _ACP_HEX64.fullmatch(boundary["event_sha256"]) is None
                    or not hmac.compare_digest(hashlib.sha256(event_raw).hexdigest(),
                                               boundary["event_sha256"])
                    or json.dumps(event, sort_keys=True, separators=(",", ":")).encode() != event_raw
                    or value.get("settlement_receipt") is None
                    or receipt_sha256 is None
                    or event["trace_id"] != value["trace_id"]
                    or event["session_id"] != value["session_id"]
                    or event["sequence"] != boundary["next_sequence"]
                    or event["kind"] != "session.reattached"
                    or event["source"] != "runtime-adapter"
                    or event["payload"] != {
                        "schema_version": _ACP_RECOVERY_BOUNDARY_EVENT_SCHEMA,
                        "root_run_id": value["root_run_id"],
                        "settlement_receipt_sha256": receipt_sha256,
                        "prior_sequence": boundary["binding_sequence"],
                        "runtime_boot_id": boundary["runtime_boot_id"],
                        "authority_epoch": boundary["runtime_authority_epoch"],
                    }
                    or value["native_session_close_confirmed"] is not True
                    or value["process_exit_confirmed"] is not True
                    or value["cleanup_unconfirmed"] is not False
                    or value["closed"] is not False):
                raise SessionConflict("ACP recovery boundary binding is invalid")
            value["recovery_boundary"] = boundary
        return value

    def recovery_binding(self, session_id: str) -> dict[str, Any]:
        binding = self._read_acp_binding(session_id)
        if binding["closed"]:
            raise SessionConflict("BYQ session was ended")
        if binding["schema_version"] == _ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA:
            try:
                live = self._get(session_id)
            except KeyError as exc:
                raise SessionConflict("local validation ACK cannot recover without its live Runtime record") from exc
            intent = binding["local_validation_ack_intent"]
            if (binding["previous_boot_id"] != self.boot_id
                    or live.boot_id != self.boot_id
                    or live.authority_epoch != intent["runtime_authority_epoch"]
                    or live.process_root_id != binding["root_run_id"]
                    or live.sequence != intent["final_live_sequence"]
                    or live.domain_call_sequence != intent["domain_call_sequence"]
                    or live.domain_call_drained_sequence != intent["domain_call_drained_sequence"]):
                raise SessionConflict("local validation ACK recovery facts changed")
            observation = binding.get("local_validation_release_observation")
            if observation is None:
                raise SessionConflict("local validation ACK intent is not durably released")
            row = self._read_backend_local_validation_final({
                key: binding[key] for key in ("session_id", "trace_id", "owner_principal", "workspace_id")
            }, observation["ack_intent"]["final_receipt"])
            return {
                "schema_version": "byq-runtime-local-validation-recovery-binding.v1",
                "state": "local_validation_ack_released",
                "session_id": binding["session_id"],
                "trace_id": binding["trace_id"],
                "owner_principal": binding["owner_principal"],
                "workspace_id": binding["workspace_id"],
                "root_run_id": binding["root_run_id"],
                "previous_boot_id": binding["previous_boot_id"],
                "previous_authority_epoch": binding["previous_authority_epoch"],
                "final_receipt": observation["ack_intent"]["final_receipt"],
                "runtime_observation": observation,
                "confirmation_receipt": row["local_validation"].get("confirmation_receipt"),
            }
        if binding["schema_version"] == _ACP_ROOT_BINDING_LOCAL_VALIDATION_HANDOFF_SCHEMA:
            observation = binding.get("local_validation_handoff_observation")
            if observation is None:
                raise SessionConflict("local validation handoff is not durably released")
            intent = binding["local_validation_handoff_intent"]
            handoff = binding["local_validation_handoff"]
            current_epoch = self.require_current_backend_authority()
            if ((self.boot_id == handoff["new_authority"]["boot_id"]
                    and current_epoch != handoff["new_authority"]["epoch"])
                    or (self.boot_id != handoff["new_authority"]["boot_id"]
                        and current_epoch <= handoff["new_authority"]["epoch"])):
                raise SessionConflict("local handoff confirmation does not cover current Runtime authority")
            row = self._read_backend_local_validation_final({
                key: binding[key] for key in ("session_id", "trace_id", "owner_principal", "workspace_id")
            }, intent["final_receipt"])
            confirmation = row["local_validation"].get("confirmation_receipt")
            if confirmation is None:
                raise SessionConflict("Backend has not confirmed the local handoff observation")
            confirmation = _local_validate_backend_confirmation(confirmation)
            if (confirmation["handoff"] != handoff
                    or confirmation["runtime_observation"] != observation
                    or confirmation["final_receipt_sha256"] != intent["final_receipt"]["receipt_sha256"]):
                raise SessionConflict("Backend local handoff confirmation differs from Runtime observation")
            return {
                "schema_version": "byq-runtime-local-validation-recovery-binding.v1",
                "state": "local_validation_handoff_confirmed",
                "session_id": binding["session_id"], "trace_id": binding["trace_id"],
                "owner_principal": binding["owner_principal"], "workspace_id": binding["workspace_id"],
                "root_run_id": binding["root_run_id"],
                "previous_boot_id": handoff["old_authority"]["boot_id"],
                "previous_authority_epoch": handoff["old_authority"]["epoch"],
                "sequence": intent["final_receipt"]["terminal_event_receipt"]["sequence"],
                "final_receipt": intent["final_receipt"], "handoff": handoff,
                "runtime_observation": observation, "confirmation_receipt": confirmation,
            }
        if binding["schema_version"] == _ACP_ROOT_BINDING_V3_SCHEMA:
            if "operator_handoff" in binding:
                try:
                    handoff_request = _r2_validate_handoff_request(binding["operator_handoff"])
                    handoff = handoff_request["handoff"]
                    observation = _r2_validate_handoff_observation(
                        binding["operator_handoff_observation"], handoff=handoff)
                except (_R2FenceContractError, KeyError, TypeError, ValueError) as exc:
                    raise SessionConflict("ACP cleanup handoff recovery binding is invalid") from exc
                completed = handoff_request["close_receipt"]["operator_completed_cleanup"]
                return {
                    "schema_version": "byq-runtime-recovery-binding.v1",
                    "state": "operator_cleanup_handoff_confirmed",
                    "session_id": binding["session_id"],
                    "trace_id": binding["trace_id"],
                    "owner_principal": binding["owner_principal"],
                    "workspace_id": binding["workspace_id"],
                    "root_run_id": binding["root_run_id"],
                    "previous_boot_id": binding["previous_boot_id"],
                    "previous_authority_epoch": binding["previous_authority_epoch"],
                    "sequence": binding["final_live_sequence"],
                    "operator_completed_cleanup": {
                        "operation_id": handoff["operation_id"],
                        "process_fence_receipt_sha256": handoff["process_fence_receipt_sha256"],
                        "close_receipt_sha256": handoff["close_receipt_sha256"],
                        "runtime_ack_sha256": _r2_digest(observation),
                        "original_terminal_receipt_sha256": handoff["terminal_receipt_sha256"],
                        "completed_cleanup_receipt_sha256": completed["receipt_sha256"],
                    },
                    "settlement_receipt": binding["settlement_receipt"],
                    "superseded_terminal": None,
                    "handoff_request": handoff_request,
                    "runtime_observation": observation,
                }
            observation = binding["operator_observation"]
            failed_fact = observation.get("operator_failed_terminal")
            completed_fact = observation.get("operator_completed_cleanup")
            state = ("operator_completed_cleanup" if completed_fact is not None else
                     "operator_failed_terminal" if failed_fact is not None else "operator_interrupted")
            return {
                "schema_version": "byq-runtime-recovery-binding.v1",
                "state": state,
                "session_id": binding["session_id"],
                "trace_id": binding["trace_id"],
                "owner_principal": binding["owner_principal"],
                "workspace_id": binding["workspace_id"],
                "root_run_id": binding["root_run_id"],
                "previous_boot_id": binding["previous_boot_id"],
                "previous_authority_epoch": binding["previous_authority_epoch"],
                "sequence": binding["final_live_sequence"],
                **({"settlement_receipt": binding["settlement_receipt"]}
                   if completed_fact is not None else {}),
                **({"runtime_observation": observation} if completed_fact is not None else {}),
                ("operator_completed_cleanup" if completed_fact is not None else
                 "operator_failed_terminal" if failed_fact is not None else "operator_interruption"): {
                    "operation_id": observation["operation_id"],
                    "process_fence_receipt_sha256": observation["process_fence_receipt_sha256"],
                    "close_receipt_sha256": observation["close_receipt_sha256"],
                    "runtime_ack_sha256": _r2_digest(observation["runtime_ack"]),
                    **({"sequence": failed_fact["sequence"],
                        "event_sha256": failed_fact["event_sha256"],
                        "failed_terminal_receipt_sha256": failed_fact["receipt_sha256"]}
                       if failed_fact is not None else {}),
                    **({"original_terminal_receipt_sha256": completed_fact["original_terminal_receipt_sha256"],
                        "completed_cleanup_receipt_sha256": completed_fact["receipt_sha256"]}
                       if completed_fact is not None else {}),
                },
                "superseded_terminal": observation["superseded_terminal"],
            }
        if binding["cleanup_unconfirmed"]:
            raise SessionConflict("ACP recovery is blocked by unconfirmed process cleanup")
        if not binding["process_exit_confirmed"]:
            raise SessionConflict("ACP recovery is blocked until prior process exit is confirmed")
        public = {key: binding[key] for key in (
            "session_id", "trace_id", "owner_principal", "workspace_id", "root_run_id",
            "previous_boot_id", "previous_authority_epoch", "sequence")}
        settled = binding["settlement_receipt"] is not None
        result = {"schema_version": "byq-runtime-recovery-binding.v1",
                  "state": "settled" if settled else "transfer_required",
                  **public,
                  **({"settlement_receipt": binding["settlement_receipt"]} if settled else {})}
        if binding.get("recovery_boundary") is not None:
            result["recovery_boundary"] = dict(binding["recovery_boundary"])
        return result

    def _recover_operator_interrupted_session(
        self, session_id: str, receipt: dict[str, Any], initial_sequence: int,
        *, trace_tail: int,
    ) -> dict[str, Any]:
        """Attach the public session without restoring its interrupted ACP child."""
        binding = self._read_acp_binding(session_id)
        if binding.get("schema_version") == _ACP_ROOT_BINDING_LOCAL_VALIDATION_HANDOFF_SCHEMA:
            handoff = _local_validate_handoff(binding["local_validation_handoff"])
            intent = _local_validate_handoff_intent(binding["local_validation_handoff_intent"])
            observation = _local_validate_handoff_observation(binding["local_validation_handoff_observation"])
            exact = self.recovery_binding(session_id)
            epoch = self.require_current_backend_authority()
            if (receipt != exact or receipt.get("state") != "local_validation_handoff_confirmed"
                    or handoff["new_authority"]["boot_id"] == handoff["old_authority"]["boot_id"]
                    or (self.boot_id == handoff["new_authority"]["boot_id"]
                        and epoch != handoff["new_authority"]["epoch"])
                    or (self.boot_id != handoff["new_authority"]["boot_id"]
                        and epoch <= handoff["new_authority"]["epoch"])
                    or initial_sequence != intent["final_receipt"]["terminal_event_receipt"]["sequence"]
                    or trace_tail != intent["final_receipt"]["terminal_event_receipt"]["sequence"]):
                raise SessionConflict("local validation handoff recovery differs from its confirmed terminal")
            final = intent["final_receipt"]
            row = self._read_backend_local_validation_final({
                key: binding[key] for key in ("session_id", "trace_id", "owner_principal", "workspace_id")
            }, final)
            confirmation = _local_validate_backend_confirmation(row["local_validation"]["confirmation_receipt"])
            if (confirmation["handoff"] != handoff or confirmation["runtime_observation"] != observation):
                raise SessionConflict("local validation handoff is not confirmed by Backend")
            if (not isinstance(binding.get("operator_binding"), dict)
                    or binding.get("operator_scope") != handoff["scope"]
                    or binding.get("runtime_generation") != handoff["scope"]["generation_id"]):
                raise SessionConflict("local validation predecessor qualification is incomplete")
            model_resolution = self._resolve_model(owner_principal=binding["owner_principal"],
                session_id=session_id, trace_id=binding["trace_id"])
            with self._lock:
                existing = self._sessions.get(session_id)
                if existing is not None:
                    with existing.lock:
                        if (existing.boot_id != self.boot_id or existing.active_run is not None
                                or existing.process_root_id != binding["root_run_id"]):
                            raise SessionConflict("local validation fresh Runtime identity changed")
                        return {**self.describe_session(existing), "resumed_from_run_id": None}
                record = RuntimeSession(session_id=session_id, trace_id=binding["trace_id"],
                    boot_id=self.boot_id, owner_principal=binding["owner_principal"],
                    workspace_id=binding["workspace_id"], model_resolution=model_resolution,
                    status=SessionStatus.IDLE, sequence=initial_sequence,
                    continuity=continuity.REATTACHED, authority_epoch=epoch,
                    recovery_cwd=binding["cwd"], settlement_receipt=dict(final["terminal_event_receipt"]),
                    domain_call_sequence=intent["domain_call_sequence"],
                    domain_call_drained_sequence=intent["domain_call_drained_sequence"],
                    cleanup_unconfirmed=False, qualified_operator_scope=dict(handoff["scope"]),
                    qualified_operator_binding=dict(binding["operator_binding"]),
                    qualified_runtime_generation=binding["runtime_generation"],
                    qualified_cwd=binding["cwd"], qualified_authority_epoch=handoff["old_authority"]["epoch"],
                    operator_observation=dict(observation))
                self._install_generation(record, native_session_id=binding["native_session_id"],
                    executor_epoch=0, process_root_id=binding["root_run_id"],
                    generation_id=binding["runtime_generation"])
                generation = record.current_generation
                if generation is None:
                    raise SessionConflict("local validation predecessor generation is unavailable")
                generation.state = GenerationState.INTERRUPTED
                generation.harness = None
                generation.native_session_close_confirmed = True
                generation.process_exit_confirmed = True
                generation.process_closed = True
                generation.process_closing = False
                generation.continuation_proxy_closed = True
                record.process_used = True
                record.reuse_native_session_ready = False
                self._sessions[session_id] = record
            return {**self.describe_session(record), "resumed_from_run_id": None}
        handoff_request = None
        handoff = None
        if "operator_handoff" in binding:
            try:
                handoff_request = _r2_validate_handoff_request(binding["operator_handoff"])
                handoff = handoff_request["handoff"]
                observation = _r2_validate_handoff_observation(
                    binding["operator_handoff_observation"], handoff=handoff)
            except (_R2FenceContractError, KeyError, TypeError, ValueError) as exc:
                raise SessionConflict("operator cleanup handoff binding is malformed") from exc
        else:
            observation = binding.get("operator_observation", {})
        failed_fact = observation.get("operator_failed_terminal")
        completed_fact = (handoff_request["close_receipt"]["operator_completed_cleanup"]
                          if handoff is not None else observation.get("operator_completed_cleanup"))
        cleanup_only = completed_fact is not None or handoff is not None
        if (binding.get("schema_version") != _ACP_ROOT_BINDING_V3_SCHEMA
                or binding.get("closed") is not False
                or (failed_fact is None and not cleanup_only and binding.get("settlement_receipt") is not None)
                or (cleanup_only and (not isinstance(binding.get("settlement_receipt"), dict)
                    or _r2_digest(binding["settlement_receipt"])
                       != completed_fact["original_terminal_receipt_sha256"]))
                or (cleanup_only and (binding.get("native_session_close_confirmed") is not True
                    or binding.get("process_exit_confirmed") is not False
                    or binding.get("cleanup_unconfirmed") is not False))
                or binding.get("domain_call_sequence") != binding.get("domain_call_drained_sequence")):
            raise SessionConflict("operator-interrupted ACP binding is not eligible for fresh execution")
        expected = self.recovery_binding(session_id)
        if receipt != expected:
            raise SessionConflict("operator-interrupted recovery receipt does not match the durable binding")
        if (type(initial_sequence) is not int or type(trace_tail) is not int
                or initial_sequence != binding["final_live_sequence"]
                or trace_tail != binding["final_live_sequence"]):
            raise SessionConflict("operator-interrupted recovery sequence is not proven")
        current_epoch = self.require_current_backend_authority()
        if handoff is None and cleanup_only and (
                observation.get("authority", {}).get("current_boot_id") != self.boot_id
                or observation.get("authority", {}).get("current_epoch") != current_epoch):
            raise SessionConflict("completed cleanup proof belongs to another Runtime authority")
        model_resolution = self._resolve_model(
            owner_principal=binding["owner_principal"],
            session_id=session_id,
            trace_id=binding["trace_id"],
        )
        if (handoff is None and (
                str(model_resolution.get("provider") or self._provider) != binding["model_provider"]
                or str(model_resolution.get("model") or self._model) != binding["model_id"])):
            raise SessionConflict("operator-interrupted session model route changed")
        observation = (binding["operator_handoff_observation"] if handoff is not None
                       else binding["operator_observation"])
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                with existing.lock:
                    if (existing.boot_id != self.boot_id
                            or existing.process_root_id != binding["root_run_id"]
                            or existing.operator_observation != observation
                            or existing.active_run is not None):
                        raise SessionConflict("operator-interrupted Runtime session changed")
                    return {**self.describe_session(existing), "resumed_from_run_id": None}

            if handoff is not None:
                confirmation = self._read_backend_operator_handoff_confirmation(
                    binding, handoff_request, observation)
                confirmation_authority = handoff["new_authority"]
                if (self.boot_id == confirmation_authority["boot_id"]
                        and current_epoch != confirmation_authority["epoch"]
                        or self.boot_id != confirmation_authority["boot_id"]
                        and current_epoch <= confirmation_authority["epoch"]):
                    raise SessionConflict("cleanup handoff confirmation is not valid for current Runtime authority")

            record = RuntimeSession(
                session_id=session_id,
                trace_id=binding["trace_id"],
                boot_id=self.boot_id,
                owner_principal=binding["owner_principal"],
                workspace_id=binding["workspace_id"],
                model_resolution=model_resolution,
                status=SessionStatus.IDLE,
                sequence=initial_sequence,
                continuity=continuity.REATTACHED,
                authority_epoch=current_epoch,
                recovery_cwd=binding["cwd"],
                settlement_receipt=(dict(binding["settlement_receipt"])
                                    if binding["settlement_receipt"] is not None else None),
                domain_call_sequence=binding["domain_call_sequence"],
                domain_call_drained_sequence=binding["domain_call_drained_sequence"],
                cleanup_unconfirmed=binding["cleanup_unconfirmed"],
                qualified_operator_scope=dict(binding["operator_scope"]),
                qualified_operator_binding=dict(binding["operator_binding"]),
                qualified_runtime_generation=binding["runtime_generation"],
                qualified_cwd=binding["cwd"],
                qualified_authority_epoch=binding["previous_authority_epoch"],
                operator_observation=dict(observation),
            )
            # This identity is retained only as the exact predecessor for the
            # next V2 CAS. No harness is built or resumed for the old native ID.
            self._install_generation(
                record,
                native_session_id=binding["native_session_id"],
                executor_epoch=0,
                process_root_id=binding["root_run_id"],
                generation_id=binding["runtime_generation"],
            )
            generation = record.current_generation
            if generation is None:
                raise SessionConflict("operator-interrupted Runtime generation is unavailable")
            generation.state = GenerationState.INTERRUPTED
            generation.harness = None
            generation.native_session_close_confirmed = binding["native_session_close_confirmed"]
            generation.process_exit_confirmed = binding["process_exit_confirmed"]
            generation.process_closed = binding["process_exit_confirmed"]
            generation.process_closing = False
            generation.continuation_proxy_closed = True
            record.process_used = True
            record.reuse_native_session_ready = False
            superseded = observation.get("superseded_terminal")
            if superseded is not None:
                record.operator_superseded_terminal_receipts[
                    binding["root_run_id"]] = superseded["receipt_sha256"]
            self._sessions[session_id] = record
        return {**self.describe_session(record), "resumed_from_run_id": None}

    def recover_acp_session(self, session_id: str, receipt: object,
                            initial_sequence: int, *, trace_tail: int | None = None,
                            boundary_ack_sha256: str | None = None) -> dict[str, Any]:
        """Reattach one exact root after Backend transfer, without prompt replay."""

        if trace_tail is None:
            trace_tail = initial_sequence
        if (type(trace_tail) is not int or not 0 <= trace_tail < 2**63
                or type(initial_sequence) is not int or not 0 <= initial_sequence < 2**63
                or (boundary_ack_sha256 is not None
                    and (not isinstance(boundary_ack_sha256, str)
                         or _ACP_HEX64.fullmatch(boundary_ack_sha256) is None))):
            raise SessionConflict("recovery trace cursor is invalid")

        if isinstance(receipt, dict) and receipt.get("state") in {
                "operator_interrupted", "operator_failed_terminal", "operator_completed_cleanup",
                "operator_cleanup_handoff_confirmed", "local_validation_handoff_confirmed"}:
            return self._recover_operator_interrupted_session(
                session_id, receipt, initial_sequence, trace_tail=trace_tail)

        existing_binding = None
        if self._acp:
            try:
                existing_binding = self._read_acp_binding(session_id)
            except KeyError:
                existing_binding = None
            if (existing_binding is not None
                    and existing_binding["schema_version"] == _ACP_ROOT_BINDING_LOCAL_VALIDATION_ACK_SCHEMA):
                raise SessionConflict("local validation ACK recovery requires completed Backend confirmation")

        with self._lock:
            existing = self._sessions.get(session_id)
        if existing is not None:
            with existing.lock:
                if existing.recovery_boundary is not None:
                    boundary = existing.recovery_boundary
                    binding = self._read_acp_binding(session_id)
                    if (receipt != existing.settlement_receipt
                            or binding.get("recovery_boundary") != boundary
                            or boundary.get("runtime_boot_id") != self.boot_id
                            or boundary.get("runtime_authority_epoch") != self.require_current_backend_authority()
                            or boundary.get("binding_sequence") != binding.get("sequence")
                            or boundary.get("previous_boot_id") != binding.get("previous_boot_id")
                            or boundary.get("previous_authority_epoch") != binding.get("previous_authority_epoch")
                            or trace_tail not in {boundary.get("binding_sequence"), boundary.get("next_sequence")}
                            or initial_sequence != max(trace_tail, boundary.get("binding_sequence", -1))):
                        raise SessionConflict("recovery boundary retry does not match its durable binding")
                    if boundary_ack_sha256 is not None:
                        if (not hmac.compare_digest(boundary_ack_sha256, boundary["event_sha256"])
                                or trace_tail != boundary["next_sequence"]):
                            raise SessionConflict("recovery boundary ACK does not match the durable event")
                        if boundary["state"] != "acknowledged":
                            path = self._acp_binding_path(session_id, binding["workspace_id"])
                            lock_fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT
                                              | getattr(os, "O_NOFOLLOW", 0), 0o600)
                            try:
                                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                                if self.require_current_backend_authority() != boundary["runtime_authority_epoch"]:
                                    raise SessionConflict("recovery boundary ACK lost Backend authority")
                                raw = self._read_locked_acp_binding_payload(path)
                                try:
                                    current = json.loads(raw.decode("utf-8"),
                                        object_pairs_hook=_strict_json_object,
                                        parse_constant=_reject_json_constant)
                                except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
                                    raise SessionConflict("recovery boundary binding changed") from exc
                                if current != binding or current.get("recovery_boundary") != boundary:
                                    raise SessionConflict("recovery boundary binding changed")
                                acknowledged = dict(boundary)
                                acknowledged["state"] = "acknowledged"
                                current["recovery_boundary"] = acknowledged
                                payload = json.dumps(current, sort_keys=True, separators=(",", ":")).encode()
                                self._replace_acp_binding_payload(path, payload)
                                persisted = self._read_locked_acp_binding_payload(path)
                                if (persisted != payload
                                        or self.require_current_backend_authority()
                                           != boundary["runtime_authority_epoch"]):
                                    raise SessionConflict("recovery boundary ACK persistence is uncertain")
                                existing.recovery_boundary = acknowledged
                            finally:
                                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                                os.close(lock_fd)
                    return {**self.describe_session(existing), "resumed_from_run_id": None}
                recoverable_failed = (existing.status == SessionStatus.FAILED
                                      and existing.interrupted_run_id is None)
                generation = existing.current_generation
                cold_recovered_record = (
                    existing.status == SessionStatus.IDLE
                    and existing.boot_id == self.boot_id
                    and generation is not None
                    and generation.state == GenerationState.STARTING
                    and generation.harness is None
                    and isinstance(existing_binding, dict)
                    and existing_binding.get("schema_version") in {
                        "byq-acp-root-binding.v1", _ACP_ROOT_BINDING_V2_SCHEMA}
                    and existing_binding.get("previous_boot_id") != self.boot_id
                )
                settled_retry = (existing.status == SessionStatus.IDLE
                                 and not cold_recovered_record
                                 and isinstance(receipt, dict)
                                 and receipt == existing.settlement_receipt)
                if recoverable_failed or settled_retry:
                    binding = self._read_acp_binding(session_id)
                    generation = existing.current_generation
                    current_authority = self.require_current_backend_authority()
                    exact_root = receipt.get("root_run_id") if isinstance(receipt, dict) else None
                    settled = existing.settlement_receipt
                    if (binding["schema_version"] not in {
                            "byq-acp-root-binding.v1", _ACP_ROOT_BINDING_V2_SCHEMA}
                            or binding["closed"] is not False
                            or binding["cleanup_unconfirmed"] is not False
                            or binding["native_session_close_confirmed"] is not True
                            or binding["process_exit_confirmed"] is not True
                            or binding["settlement_receipt"] is None
                            or binding["settlement_receipt"] != receipt
                            or settled != receipt
                            or type(initial_sequence) is not int
                            or not binding["sequence"] <= initial_sequence < 2**63
                            or existing.boot_id != self.boot_id
                            or binding["previous_boot_id"] != self.boot_id
                            or existing.authority_epoch != current_authority
                            or binding["previous_authority_epoch"] != current_authority
                            or binding["session_id"] != existing.session_id
                            or binding["trace_id"] != existing.trace_id
                            or binding["owner_principal"] != existing.owner_principal
                            or binding["workspace_id"] != existing.workspace_id
                            or binding["root_run_id"] != existing.process_root_id
                            or binding["root_run_id"] != exact_root
                            or binding["runtime_generation"] != existing.runtime_generation
                            or binding["native_session_id"] != existing.runtime_session_id
                            or (not settled_retry
                                and existing.sequence != binding["sequence"])
                            or (settled_retry
                                and existing.sequence < binding["sequence"])
                            or settled.get("sequence") != binding["sequence"]
                            or existing.terminal_receipts.get(binding["root_run_id"]) != receipt
                            or existing.cleanup_unconfirmed
                            or existing.active_run is not None
                            or existing.process_closing
                            or existing.pending_terminal_receipts
                            or existing.domain_call_sequence != existing.domain_call_drained_sequence
                            or binding["domain_call_sequence"] != binding["domain_call_drained_sequence"]
                            or generation is None
                            or generation.process_root_id != binding["root_run_id"]
                            or not generation.process_closed
                            or generation.process_closing
                            or not generation.native_session_close_confirmed
                            or not generation.process_exit_confirmed):
                        raise SessionConflict("failed ACP session lacks exact settled recovery proof")
                    if (type(initial_sequence) is not int
                            or initial_sequence < existing.sequence):
                        raise SessionConflict("settled recovery sequence would move backwards")
                    existing.sequence = initial_sequence
                    existing.status = SessionStatus.IDLE
                    existing.continuity = continuity.REATTACHED
                    existing.reuse_native_session_ready = False
                    return {**self.describe_session(existing), "resumed_from_run_id": None}
                exact_root = receipt.get("root_run_id") if isinstance(receipt, dict) else None
                if (existing.boot_id != self.boot_id or exact_root != existing.process_root_id
                        or (receipt != existing.settlement_receipt
                            and not (existing.interrupted_run_id == exact_root
                                     and receipt.get("boot_id") == self.boot_id))):
                    raise SessionConflict("ACP recovery retry does not match the live binding")
                return {**self.describe_session(existing),
                        "resumed_from_run_id": existing.interrupted_run_id}
        binding = self._read_acp_binding(session_id)
        boundary = binding.get("recovery_boundary")
        qualified_binding_sha256 = (
            self._capture_acp_binding_digest(session_id, binding)
            if binding["schema_version"] == _ACP_ROOT_BINDING_V2_SCHEMA else None)
        if binding["closed"]:
            raise SessionConflict("BYQ session was ended")
        if binding["cleanup_unconfirmed"]:
            raise SessionConflict("ACP recovery is blocked by unconfirmed process cleanup")
        if (type(initial_sequence) is not int or initial_sequence < binding["sequence"]
                or initial_sequence >= 2**63):
            raise SessionConflict("recovery event sequence is not proven")
        if boundary is not None:
            if (boundary["runtime_boot_id"] != self.boot_id
                    or boundary["runtime_authority_epoch"] != self.require_current_backend_authority()
                    or receipt != binding["settlement_receipt"]
                    or trace_tail not in {boundary["binding_sequence"], boundary["next_sequence"]}
                    or initial_sequence != max(trace_tail, boundary["binding_sequence"])):
                raise SessionConflict("durable recovery boundary belongs to another trace or Runtime boot")
        elif trace_tail != binding["sequence"] or initial_sequence != binding["sequence"]:
            raise SessionConflict("recovery trace does not meet its durable binding")
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
        if (not settled and binding["schema_version"] == _ACP_ROOT_BINDING_V2_SCHEMA):
            # This Adapter boot cannot reuse the prior root's scoped admission
            # callback. Keep an unsettled qualified binding fenced until a
            # recovery path can create a fresh scope-bound callback.
            raise SessionConflict("qualified ACP recovery requires a fresh scoped admission")
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
            sequence=(boundary["binding_sequence"] if boundary is not None else initial_sequence),
            continuity=continuity.REATTACHED,
            authority_epoch=self.require_current_backend_authority(),
            recovery_cwd=binding["cwd"], settlement_receipt=dict(receipt) if settled else None,
            domain_call_sequence=binding["domain_call_sequence"],
            domain_call_drained_sequence=binding["domain_call_drained_sequence"],
            qualified_operator_scope=(dict(binding["operator_scope"])
                if binding["schema_version"] == _ACP_ROOT_BINDING_V2_SCHEMA else None),
            qualified_operator_binding=(dict(binding["operator_binding"])
                if binding["schema_version"] == _ACP_ROOT_BINDING_V2_SCHEMA else None),
            qualified_runtime_generation=(binding["runtime_generation"]
                if binding["schema_version"] == _ACP_ROOT_BINDING_V2_SCHEMA else None),
            qualified_cwd=(binding["cwd"]
                if binding["schema_version"] == _ACP_ROOT_BINDING_V2_SCHEMA else None),
            qualified_authority_epoch=(binding["previous_authority_epoch"]
                if binding["schema_version"] == _ACP_ROOT_BINDING_V2_SCHEMA else None),
        )
        if settled:
            record.terminal_receipts[binding["root_run_id"]] = dict(receipt)
        if boundary is not None:
            record.recovery_boundary = dict(boundary)
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
                if binding["schema_version"] == _ACP_ROOT_BINDING_V2_SCHEMA:
                    if not isinstance(qualified_binding_sha256, str):
                        raise SessionConflict("qualified ACP settlement binding digest is unavailable")
                    self._persist_qualified_settlement(
                        record, expected_sha256=qualified_binding_sha256,
                        expected_binding=binding, receipt=dict(receipt),
                    )
                else:
                    self._persist_acp_binding(record)
        if boundary is None and settled:
            binding = self._read_acp_binding(session_id)
            if binding["settlement_receipt"] != record.settlement_receipt:
                raise SessionConflict("settled recovery receipt was not durably persisted")
            if binding["sequence"] >= 2_147_483_647:
                raise SessionConflict("settled recovery trace sequence is exhausted")
            event = make_workflow_trace_event(
                trace_id=record.trace_id, session_id=record.session_id,
                sequence=binding["sequence"] + 1, kind="session.reattached",
                source="runtime-adapter", payload={
                    "schema_version": _ACP_RECOVERY_BOUNDARY_EVENT_SCHEMA,
                    "root_run_id": binding["root_run_id"],
                    "settlement_receipt_sha256": hashlib.sha256(json.dumps(
                        record.settlement_receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                    "prior_sequence": binding["sequence"],
                    "runtime_boot_id": self.boot_id,
                    "authority_epoch": record.authority_epoch,
                },
            )
            event_raw = json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
            boundary = {
                "schema_version": _ACP_RECOVERY_BOUNDARY_SCHEMA,
                "binding_sequence": binding["sequence"],
                "previous_boot_id": binding["previous_boot_id"],
                "previous_authority_epoch": binding["previous_authority_epoch"],
                "runtime_boot_id": self.boot_id,
                "runtime_authority_epoch": record.authority_epoch,
                "next_sequence": binding["sequence"] + 1,
                "event_json_b64": base64.b64encode(event_raw).decode("ascii"),
                "event_sha256": hashlib.sha256(event_raw).hexdigest(),
                "state": "pending",
            }
            path = self._acp_binding_path(session_id, binding["workspace_id"])
            lock_fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT
                              | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                binding_raw = self._read_locked_acp_binding_payload(path)
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
            try:
                disk_binding = json.loads(binding_raw.decode("utf-8"),
                    object_pairs_hook=_strict_json_object, parse_constant=_reject_json_constant)
            except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
                raise SessionConflict("ACP recovery binding changed before trace boundary") from exc
            if (disk_binding != binding
                    or (persisted_settled and binding["schema_version"] == _ACP_ROOT_BINDING_V2_SCHEMA
                        and hashlib.sha256(binding_raw).hexdigest() != qualified_binding_sha256)):
                raise SessionConflict("ACP recovery binding changed before trace boundary")
            record.recovery_boundary = boundary
            candidate = self._acp_binding_value(record)
            candidate_without_boundary = dict(candidate)
            candidate_without_boundary.pop("recovery_boundary", None)
            if candidate_without_boundary != disk_binding:
                record.recovery_boundary = None
                raise SessionConflict("recovery boundary would alter the original ACP binding")
            self._persist_acp_binding(record, expected_previous=(
                binding_raw, hashlib.sha256(binding_raw).hexdigest()))
            persisted_boundary = self._read_acp_binding(session_id)
            if ({key: value for key, value in persisted_boundary.items()
                 if key != "recovery_boundary"} != disk_binding
                    or persisted_boundary.get("recovery_boundary") != boundary):
                raise SessionConflict("recovery boundary changed the original ACP binding")
            self._publish(record, event)
        elif boundary is not None:
            event_raw = base64.b64decode(boundary["event_json_b64"], validate=True)
            event = json.loads(event_raw.decode("utf-8"), object_pairs_hook=_strict_json_object,
                               parse_constant=_reject_json_constant)
            self._publish(record, event)
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

    def task_ready_qualified(self, record: RuntimeSession) -> bool:
        """Qualify the default task-ready profile on the ordinary Product ACP route."""

        if (not self._root_scoped or not self._acp_product_slots
                or not record.owner_principal or not record.workspace_id
                or not bool(record.model_resolution.get('api_key'))
                or not _continuation_route_qualified(
                    record.model_resolution, self._provider, self._model)):
            return False
        return self._compatibility.family == ACP_COMPATIBILITY_FAMILY

    @staticmethod
    def _read_continuation_tool_guard(
        record: RuntimeSession, *, terminal: bool = False,
    ) -> dict:
        reservation = record.continuation_budget
        if (isinstance(reservation, dict)
                and reservation.get('schema_version') == 'task-continuation-reservation.v3'):
            if (not isinstance(record.budget_journal, Path)
                    or record.budget_run_id is None):
                raise ValueError('task-ready root identity is unavailable')
            return read_task_ready_v2_guard(
                record.budget_journal, reservation, record.budget_run_id,
                terminal=terminal,
            )
        return read_request_guard(
            record.budget_journal, reservation, terminal=terminal,
        )

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
        if (isinstance(reservation, dict)
                and reservation.get('schema_version') == 'task-continuation-reservation.v3'):
            return self._task_ready_budget_receipt(record, reservation)
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
        # ADR-0105 §5: an unprovable outbound result or an admitted request with
        # no unique matching completion keeps the execution receipt unresolved;
        # it must never settle as a known outcome. The same atomic
        # classification used for the terminal decision is reused here so an
        # in-flight/unpaired request not yet written as unknown cannot settle.
        gate = record.continuation_request_gate
        if gate is None:
            return {'reservation_id': reservation_id, 'status': 'outcome_unknown'}
        try:
            state = gate.settlement_state()
        except Exception:  # noqa: BLE001 — damaged receipts stay unresolved
            return {'reservation_id': reservation_id, 'status': 'outcome_unknown'}
        if state == UNKNOWN_OR_UNPAIRED:
            return {'reservation_id': reservation_id, 'status': 'outcome_unknown'}
        gate_blocked = state == KNOWN_BLOCKED
        try:
            tool_receipt = read_request_guard(record.budget_journal, reservation, terminal=True)
            request_usage = gate.request_usage(tool_calls=tool_receipt['tool_calls'])
            violations = exceeded_request_limits(request_usage)
            completed = any(event['kind'] == 'session.result'
                and event['payload'].get('run_id') == record.budget_run_id for event in record.history)
            needs_attention = bool(
                not completed or tool_receipt['blocked_reason'] or gate_blocked
                or violations
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

    def _task_ready_budget_receipt(self, record: RuntimeSession, reservation_v3: dict) -> dict:
        """Settle a task-ready receipt only after all exact close/ACK evidence."""

        reservation_id = _task_ready_reservation_id(reservation_v3)
        idempotency_key = reservation_v3['idempotency_key']
        identity = {
            'reservation_id': reservation_id,
            'idempotency_key': idempotency_key,
        }
        cached = record.budget_receipts.get(reservation_id)
        if cached is not None:
            return cached
        if record.active_run is not None:
            return {**identity, 'status': 'accepted', 'run_id': record.budget_run_id}

        generation = record.current_generation
        if (record.cleanup_unconfirmed or not record.process_closed or record.process_closing
                or not record.continuation_proxy_closed
                or generation is None
                or generation.process_root_id != record.budget_run_id
                or not generation.process_exit_confirmed):
            return {**identity, 'status': 'outcome_unknown'}
        if (record.domain_call_drained_sequence != record.domain_call_sequence
                or record.pending_terminal_receipts
                or not isinstance(record.settlement_receipt, dict)
                or record.settlement_receipt.get('root_run_id') != record.budget_run_id
                or record.settlement_receipt != record.terminal_receipts.get(record.budget_run_id)):
            return {**identity, 'status': 'outcome_unknown'}

        gate = record.continuation_request_gate
        if gate is None:
            return {**identity, 'status': 'outcome_unknown'}
        try:
            state = gate.settlement_state()
        except Exception:  # noqa: BLE001 — damaged receipts stay unresolved
            return {**identity, 'status': 'outcome_unknown'}
        if state == UNKNOWN_OR_UNPAIRED:
            return {**identity, 'status': 'outcome_unknown'}
        try:
            tool_receipt = self._read_continuation_tool_guard(record, terminal=True)
            request_usage = validate_request_usage_v2(
                gate.request_usage(tool_calls=tool_receipt['tool_calls']))
            if (request_usage['execution_profile'] != reservation_v3['execution_profile']
                    or request_usage['request_limits'] != reservation_v3['request_limits']):
                raise ValueError('task-ready request usage does not match its carrier')
            violations = exceeded_request_limits_v2(request_usage)
            completed = any(
                event['kind'] == 'session.result'
                and event['payload'].get('run_id') == record.budget_run_id
                for event in record.history
            )
            needs_attention = bool(
                not completed or tool_receipt['blocked_reason']
                or state == KNOWN_BLOCKED or violations
            )
            receipt = {
                **identity,
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
            return {**identity, 'status': 'outcome_unknown'}

    def continuation_receipt(self, session_id: str, reservation_id: str) -> dict:
        validate_identifier(session_id, field='session_id')
        try:
            record = self._get(session_id)
        except KeyError:
            return {'reservation_id': reservation_id, 'status': 'outcome_unknown'}
        with record.lock:
            if record.continuation_budget:
                try:
                    current_id = _runtime_reservation_id(record.continuation_budget)
                except (ValueError, TypeError, KeyError):
                    current_id = None
                if current_id == reservation_id:
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
        task_ready_overlay_b64: str | None = None,
        task_ready_reservation_id: str | None = None,
        continuation_proxy_url: str | None = None,
        continuation_deadline_epoch_ms: int | None = None,
        product_turn_overlay_b64: str | None = None,
        product_execution_profile: dict[str, object] | None = None,
        search_api_key: str | None = None,
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
        if task_ready_overlay_b64 is None and task_ready_reservation_id is not None:
            raise ValueError('task-ready reservation identity requires its guard overlay')
        if task_ready_overlay_b64 is not None:
            if (continuation_budget is not None or not self._acp_product_slots
                    or not isinstance(task_ready_reservation_id, str)
                    or re.fullmatch(r'continuation_[0-9a-f]{32}', task_ready_reservation_id) is None
                    or continuation_proxy_url is None or search_api_key is not None):
                raise ValueError('task-ready Product ACP execution identity is invalid')
            environment['BYQ_CONTINUATION_RESERVATION_ID'] = task_ready_reservation_id
            environment['DEEPSEEK_SEARCH_BASE_URL'] = ''
            environment['DEEPSEEK_SEARCH_API_KEY'] = ''
            guard_b64 = task_ready_overlay_b64
            # The task-ready overlay carries only output caps explicitly present
            # in its trusted profile; no legacy/default max_tokens is injected.
        elif continuation_budget is not None:
            if search_api_key is not None:
                raise ValueError('search credentials cannot enter a continuation process')
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
            # ADR-0111 ordinary options are trusted BYQ parameters, not a grant.
            # The strict v2 binding carries the options revision into the
            # request proxy and tool guard; an old v1 overlay cannot be selected
            # by silently omitting this profile.
            if product_execution_profile is None:
                raise ValueError('ordinary product execution profile is required')
            profile = validate_ordinary_product_execution_profile(product_execution_profile)
            # The official web-search plugin has a separate credential
            # reference. Do not enable it from the model provider key, and do
            # not pass it to the distinct F6 continuation path above.
            if search_api_key is not None:
                if (not self._acp or str(model_resolution.get("provider") or self._provider)
                        not in {PRODUCT_TURN_PROVIDER, OFFICIAL_PRODUCT_TURN_PROVIDER}
                        or not isinstance(search_api_key, str)
                        or not search_api_key or len(search_api_key.encode("utf-8")) > 16_384
                        or "\0" in search_api_key):
                    raise ValueError('ordinary search credential is invalid')
                environment["DEEPSEEK_SEARCH_API_KEY"] = search_api_key
            guard_b64 = product_turn_overlay_b64
            max_tokens = product_turn_execution_output_cap(profile['options'])
        elif search_api_key is not None:
            raise ValueError('search credentials require an ordinary Product root')
        return self._compatibility.build_harness(
            provider=str(model_resolution.get("provider") or self._provider),
            model=str(model_resolution.get("model") or self._model),
            composition=composition,
            session_root=session_root,
            runtime_command=self.runtime_command,
            environment=environment,
            max_tokens=max_tokens,
            continuation_guard_b64=guard_b64,
            product_execution_profile=product_execution_profile,
        )

    def _ordinary_product_upstream(self, resolution: dict[str, object]) -> str:
        provider = str(resolution.get('provider') or self._provider)
        model = str(resolution.get('model') or self._model)
        if provider == PRODUCT_TURN_PROVIDER and model == PRODUCT_TURN_MODEL:
            return PRODUCT_TURN_UPSTREAM_BASE_URL
        if provider == OFFICIAL_PRODUCT_TURN_PROVIDER and model == OFFICIAL_PRODUCT_TURN_MODEL:
            if (resolution.get('source') != 'user_binding'
                    or not isinstance(resolution.get('api_key'), str)
                    or not resolution.get('api_key')
                    or not isinstance(resolution.get('profile_id'), str)
                    or not resolution.get('profile_id')
                    or type(resolution.get('profile_version')) is not int
                    or type(resolution.get('credential_version')) is not int
                    or type(resolution.get('binding_version')) is not int
                    or not isinstance(resolution.get('credential_id'), str)
                    or not resolution.get('credential_id')):
                raise ModelCredentialUnavailable(
                    'official ordinary model requires a trusted user credential binding')
            return OFFICIAL_PRODUCT_TURN_UPSTREAM_BASE_URL
        raise ModelCredentialUnavailable(
            'ordinary ACP Product model is not qualified (NOT_QUALIFIED)')

    def _load_product_execution_profile(
        self, record: RuntimeSession, root_run_id: str, *, runtime_generation: str,
    ) -> dict[str, object]:
        """Load the exact trusted conversation settings for one ordinary root.

        Both reads are owner/workspace scoped and fenced to this Adapter boot.
        Any missing identity, transport error, malformed projection or scope
        mismatch stops before a provider proxy or DSH root is started; no error
        path falls back to unbounded defaults.
        """
        owner = record.owner_principal
        workspace = record.workspace_id
        if (not isinstance(owner, str) or not owner
                or not isinstance(workspace, str) or not workspace
                or not re.fullmatch(r"[0-9a-f]{32}", root_run_id)):
            raise RuntimeAuthorityUnavailable("ordinary execution options scope is unavailable")
        token = os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
        if not token:
            raise RuntimeAuthorityUnavailable("ordinary execution options service is unavailable")
        headers = {
            "Authorization": f"Bearer {token}",
            "X-BYQ-Owner-Principal": owner,
            "X-BYQ-Workspace-ID": workspace,
            "X-BYQ-Actor-Principal": f"byq-product-agent-{record.session_id}",
            "X-BYQ-Trace-ID": record.trace_id,
            "X-BYQ-Session-ID": record.session_id,
            "X-BYQ-DSH-Run-ID": runtime_generation,
            "X-BYQ-Runtime-Boot-ID": self.boot_id,
            "X-BYQ-Root-Run-ID": root_run_id,
        }
        base = self._backend_url.rstrip("/")
        try:
            conversation_response = httpx.get(
                f"{base}/v1/product/conversations/by-runtime/"
                f"{quote(record.session_id, safe='')}",
                headers=headers, timeout=2.0,
            )
            conversation_response.raise_for_status()
            conversation_body = conversation_response.json()
            conversation = (conversation_body.get("conversation")
                            if isinstance(conversation_body, dict) else None)
            if (not isinstance(conversation, dict)
                    or conversation.get("runtime_session_id") != record.session_id
                    or conversation.get("owner_principal") != owner
                    or conversation.get("workspace_id") != workspace
                    or conversation.get("trace_id") != record.trace_id
                    or conversation.get("status") != "active"):
                raise ValueError("conversation scope does not match")
            conversation_id = conversation.get("conversation_id")
            validate_identifier(conversation_id, field="conversation_id")
            options_response = httpx.get(
                f"{base}/v1/product/conversations/"
                f"{quote(conversation_id, safe='')}/execution-options",
                headers=headers, timeout=2.0,
            )
            options_response.raise_for_status()
            projection = options_response.json()
            if (not isinstance(projection, dict)
                    or set(projection) != {
                        "schema_version", "conversation_id", "owner_principal",
                        "workspace_id", "revision", "options", "updated_at",
                    }
                    or projection.get("schema_version") != "agent-execution-options.v1"
                    or projection.get("conversation_id") != conversation_id
                    or projection.get("owner_principal") != owner
                    or projection.get("workspace_id") != workspace
                    or type(projection.get("revision")) is not int
                    or projection["revision"] < 0
                    or (projection.get("updated_at") is not None
                        and not isinstance(projection.get("updated_at"), str))):
                raise ValueError("execution options projection does not match")
            options = validate_agent_execution_options(projection.get("options"))
            upstream = self._ordinary_product_upstream(record.model_resolution)
            if upstream == OFFICIAL_PRODUCT_TURN_UPSTREAM_BASE_URL:
                return official_product_turn_execution_profile(
                    options, revision=projection['revision'],
                    owner_principal=owner, session_id=record.session_id,
                    trace_id=record.trace_id, root_run_id=root_run_id,
                    runtime_boot_id=self.boot_id,
                    runtime_generation=runtime_generation,
                )
            return product_turn_execution_profile(options, revision=projection["revision"])
        except RuntimeAuthorityUnavailable:
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            raise RuntimeAuthorityUnavailable(
                "ordinary execution options are unavailable or unproven"
            ) from None

    def _resolve_search_credential(
        self,
        *,
        owner_principal: str | None,
        session_id: str,
        trace_id: str,
    ) -> str | None:
        if not owner_principal or not self._resolver_token:
            raise RuntimeAuthorityUnavailable("search credential resolver is unavailable")
        try:
            response = httpx.post(
                f"{self._backend_url}/internal/credentials/search-resolution",
                headers={"x-byq-credential-resolver-token": self._resolver_token},
                json={
                    "owner_principal": owner_principal,
                    "session_id": session_id,
                    "trace_id": trace_id,
                },
                timeout=3.0,
            )
            if response.status_code == 404:
                try:
                    missing_body = response.json()
                except (ValueError, TypeError):
                    raise RuntimeAuthorityUnavailable(
                        "search credential resolution is unavailable"
                    ) from None
                if missing_body == {
                    "detail": {"code": "search_credential_not_configured"}
                }:
                    return None
                raise RuntimeAuthorityUnavailable(
                    "search credential resolution is unavailable"
                )
            response.raise_for_status()
            body = response.json()
            resolution = body.get("resolution") if isinstance(body, dict) else None
            if not isinstance(resolution, dict):
                raise RuntimeAuthorityUnavailable("search credential resolution is invalid")
            credential_id = resolution.get("credential_id")
            credential_version = resolution.get("credential_version")
            api_key = resolution.get("api_key")
            if (
                resolution.get("purpose") != "web_search_api_key"
                or resolution.get("provider") != "deepseek"
                or resolution.get("scope") != "user"
                or resolution.get("owner_principal") != owner_principal
                or resolution.get("session_id") != session_id
                or resolution.get("trace_id") != trace_id
                or not isinstance(credential_id, str)
                or re.fullmatch(r"cred_[0-9a-f]{32}", credential_id) is None
                or type(credential_version) is not int or credential_version < 1
                or not isinstance(api_key, str) or not api_key or "\0" in api_key
                or len(api_key.encode("utf-8")) > 16_384
            ):
                raise RuntimeAuthorityUnavailable("search credential resolution is invalid")
            return api_key
        except RuntimeAuthorityUnavailable:
            raise
        except (httpx.HTTPError, ValueError, TypeError, UnicodeError):
            raise RuntimeAuthorityUnavailable(
                "search credential resolution is unavailable"
            ) from None

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
        options = run.ordinary_execution_options
        if options is not None and not any(options.get(name) is not None for name in (
            "max_runtime_seconds", "max_no_progress_seconds",
            "max_child_runtime_seconds", "max_child_no_progress_seconds",
        )) and run.continuation_deadline is None:
            # Counts and byte/token settings are enforced at their own request
            # boundaries. With no user-supplied time settings, do not run an
            # Adapter execution/no-progress watchdog for an ordinary root.
            run.watchdog_stop.wait()
            return
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
            options = run.ordinary_execution_options
            if options is None:
                root_timeout = self._run_timeout_seconds or None
                root_no_progress = self._no_progress_timeout_seconds
                child_runtime = self._subagent_hard_cap_seconds or None
                child_no_progress = self._subagent_timeout_seconds
            else:
                root_timeout = options["max_runtime_seconds"]
                root_no_progress = options["max_no_progress_seconds"]
                child_runtime = options["max_child_runtime_seconds"]
                child_no_progress = options["max_child_no_progress_seconds"]
            # A periodic observation, never a new model call or lease renewal.
            if now - max(run.started_at, run.last_progress_check_at) >= self._progress_check_interval_seconds:
                run.last_progress_check_at = now
                self._emit_wait_notice(record, run, now=now)
            if run.domain_stop_code:
                code = run.domain_stop_code
            elif ((root_timeout is not None and now - run.started_at > root_timeout)
                    or (run.continuation_deadline is not None and now >= run.continuation_deadline)):
                code = "runtime-run-timeout"
            elif (
                (oldest_subagent is not None and (
                    (child_no_progress is not None and now - oldest_subagent > child_no_progress)
                    or (child_runtime is not None and now - oldest_subagent > child_runtime)))
                or any(
                    ((child_no_progress is not None
                      and now - child.last_activity_at > child_no_progress)
                     or (child_runtime is not None
                         and now - child.started_at > child_runtime))
                    for child in run.child_leases.values())
            ):
                code = "runtime-subagent-timeout"
            elif (options is None and (oldest_subagent is not None or run.child_leases)):
                # A delegated child owns a separate, longer bound. Do not let
                # the parent's quiet interval mislabel active child work as a
                # no-progress failure before that dedicated deadline.
                return False
            elif (root_no_progress is not None
                    and now - run.last_runtime_activity_at > root_no_progress):
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
