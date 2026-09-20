"""Framework-neutral TerminalAttachment vocabulary.

ADR-0081 §5 redefines R4 as *attachment lifecycle, not a terminal runtime*.
D15-5 qualifies persistent terminals against DSH 0.1.5-rc.1 and this module
carries the framework-neutral vocabulary that keeps the ownership boundary
explicit:

* BYQ owns ``TerminalAttachment`` identity, state, authorization and reconnect.
* DSH owns the PTY process, the shell and the I/O.
* A terminal's lifetime MUST NOT define a conversation or durable-job lifetime.
* BYQ MUST NOT build a PTY runtime; it adapts, observes and fails down.

The four existence dimensions are distinct and must never be collapsed:

1. ``pty_process``    — the real external shell/PTY process exists.
2. ``attachment``     — a BYQ-owned attachment record exists and is live.
3. ``io_rebind``      — a client can re-bind I/O to the same terminal.
4. ``terminal_identity`` — the identity (attachment + session + terminal) is
   stable across a rebind.

The public status is one closed value. Diagnostics are evidence-only and MUST
NOT leak into a public status or become an identity. This module carries no DSH
session/process/event schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TERMINAL_ATTACHMENT_VERSION = "terminal-attachment.v1"

ATTACHED = "attached"
REATTACHED = "reattached"
REHYDRATED = "rehydrated"
LOST = "lost"
INTERRUPTED = "interrupted"
FENCED = "fenced"

STATUSES = frozenset({ATTACHED, REATTACHED, REHYDRATED, LOST, INTERRUPTED, FENCED})

EXISTENCE_DIMENSIONS = (
    "pty_process",
    "attachment",
    "io_rebind",
    "terminal_identity",
)

EXISTENCE_STATES = frozenset({"present", "absent", "unknown"})
IO_REBIND_STATES = frozenset({"ok", "rejected", "unknown"})
IDENTITY_STATES = frozenset({"stable", "new", "lost", "unknown"})

BYQ_OWNED = frozenset({"attachment_identity", "attachment_state", "authorization", "reconnect"})
DSH_OWNED = frozenset({"pty_process", "shell", "io"})

# BYQ must not build a PTY runtime, and terminal lifetime must not define
# conversation/job lifetime. These are asserted by tests and documented here.
BYQ_BUILDS_PTY_RUNTIME = False
TERMINAL_LIFETIME_DEFINES_CONVERSATION = False

DIAGNOSTIC_BYQ_ATTACHMENT_SURVIVED = "byq_attachment_survived"
DIAGNOSTIC_PTY_PROCESS_ALIVE = "pty_process_alive"
DIAGNOSTIC_IO_REBIND_AVAILABLE = "io_rebind_available"
DIAGNOSTIC_NATIVE_SESSION_SURVIVED = "native_session_survived"
DIAGNOSTIC_TERMINAL_IDENTITY_STABLE = "terminal_identity_stable"

DIAGNOSTIC_FIELDS = frozenset({
    DIAGNOSTIC_BYQ_ATTACHMENT_SURVIVED,
    DIAGNOSTIC_PTY_PROCESS_ALIVE,
    DIAGNOSTIC_IO_REBIND_AVAILABLE,
    DIAGNOSTIC_NATIVE_SESSION_SURVIVED,
    DIAGNOSTIC_TERMINAL_IDENTITY_STABLE,
})


def valid_status(value: object) -> bool:
    """Return whether ``value`` is one of the closed attachment statuses."""

    return isinstance(value, str) and value in STATUSES


def normalize_status(value: object, *, default: str = LOST) -> str:
    """Fail closed on an unknown status instead of inventing one."""

    if value is None:
        return default
    if not valid_status(value):
        raise ValueError("invalid terminal attachment status")
    return value


@dataclass(frozen=True)
class TerminalAttachmentRecord:
    """Minimal BYQ-owned attachment identity/state, with no PTY mechanics.

    ``attachment_id`` is BYQ-minted and is never a DSH session id or a pid. The
    ``generation``/``executor_epoch`` fence a stale reconnect; ``owner_principal``
    is the authorization subject. This record carries no terminal I/O.
    """

    attachment_id: str
    owner_principal: str
    generation: int
    executor_epoch: int
    status: str = ATTACHED
    pty_present: bool = False
    native_session_present: bool = False

    def __post_init__(self) -> None:
        if not (isinstance(self.attachment_id, str) and self.attachment_id.strip()):
            raise ValueError("attachment_id must be non-empty")
        if not (isinstance(self.owner_principal, str) and self.owner_principal.strip()):
            raise ValueError("owner_principal must be non-empty")
        if not (isinstance(self.generation, int) and not isinstance(self.generation, bool)
                and self.generation >= 0):
            raise ValueError("generation must be a non-negative int")
        if not (isinstance(self.executor_epoch, int) and not isinstance(self.executor_epoch, bool)
                and self.executor_epoch >= 0):
            raise ValueError("executor_epoch must be a non-negative int")
        if not valid_status(self.status):
            raise ValueError("invalid terminal attachment status")
        if not isinstance(self.pty_present, bool) or not isinstance(self.native_session_present, bool):
            raise ValueError("presence flags must be bools")


@dataclass(frozen=True)
class TerminalAttachmentDecision:
    """Public attachment status plus internal, evidence-only diagnostics."""

    status: str
    diagnostics: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not valid_status(self.status):
            raise ValueError("invalid terminal attachment status")
        if not set(self.diagnostics) <= DIAGNOSTIC_FIELDS:
            raise ValueError("unknown terminal attachment diagnostic field")


def _require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a bool")
    return value


def classify_terminal_transition(
    *,
    attachment_survived: bool,
    pty_process_alive: bool,
    io_rebind_available: bool,
    terminal_identity_stable: bool,
    native_session_survived: bool,
    stale_generation: bool = False,
    stale_epoch: bool = False,
    faulted: bool = False,
) -> TerminalAttachmentDecision:
    """Classify one terminal fault transition into the closed public status.

    Inputs are framework-neutral facts observed at the TerminalAttachment
    boundary. The classifier never fabricates a reattach: a lost BYQ attachment
    is never reported as ``reattached`` even when the raw PTY process survives,
    and a stale generation/epoch is fenced before any rebind decision.
    """

    _require_bool(attachment_survived, "attachment_survived")
    _require_bool(pty_process_alive, "pty_process_alive")
    _require_bool(io_rebind_available, "io_rebind_available")
    _require_bool(terminal_identity_stable, "terminal_identity_stable")
    _require_bool(native_session_survived, "native_session_survived")
    _require_bool(stale_generation, "stale_generation")
    _require_bool(stale_epoch, "stale_epoch")
    _require_bool(faulted, "faulted")

    diagnostics = {
        DIAGNOSTIC_BYQ_ATTACHMENT_SURVIVED: attachment_survived,
        DIAGNOSTIC_PTY_PROCESS_ALIVE: pty_process_alive,
        DIAGNOSTIC_IO_REBIND_AVAILABLE: io_rebind_available,
        DIAGNOSTIC_NATIVE_SESSION_SURVIVED: native_session_survived,
        DIAGNOSTIC_TERMINAL_IDENTITY_STABLE: terminal_identity_stable,
    }

    if stale_generation or stale_epoch:
        return TerminalAttachmentDecision(status=FENCED, diagnostics=diagnostics)

    if attachment_survived and io_rebind_available and terminal_identity_stable:
        return TerminalAttachmentDecision(status=REATTACHED if faulted else ATTACHED,
                                          diagnostics=diagnostics)

    if not attachment_survived:
        if native_session_survived and io_rebind_available and terminal_identity_stable:
            return TerminalAttachmentDecision(status=REHYDRATED, diagnostics=diagnostics)
        # A surviving PTY with no attachment is unreachable, not reattached.
        if pty_process_alive:
            return TerminalAttachmentDecision(status=LOST, diagnostics=diagnostics)

    if faulted:
        return TerminalAttachmentDecision(status=INTERRUPTED, diagnostics=diagnostics)
    return TerminalAttachmentDecision(status=LOST, diagnostics=diagnostics)
