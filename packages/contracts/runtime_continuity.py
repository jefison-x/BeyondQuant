"""Framework-neutral AgentSession / RuntimeGeneration continuity vocabulary.

ADR-0079 R2 separates durable session identity from ephemeral runtime
generations. A session create/resume/rebind reports one closed continuity status
so callers can distinguish a brand-new session from an in-process reattach and
from a truthful replacement generation. The vocabulary is BYQ-owned: it carries
no DSH session, process or event schema.

D15-3 adds an *evidence-only* classification helper for the Runtime Continuity
failure matrix. It maps framework-neutral observations (did the generation
survive? was a run lost? is the persisted session natively resumable?) onto the
same closed public status. The extra detail is kept in an internal diagnostics
dict and MUST NOT replace or leak into the public ``continuity`` value. The DSH
session id is never part of an AgentSession identity here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CONTINUITY_VERSION = "runtime-continuity.v1"

FRESH = "fresh"
REATTACHED = "reattached"
REHYDRATED = "rehydrated"
INTERRUPTED = "interrupted"

STATUSES = frozenset({FRESH, REATTACHED, REHYDRATED, INTERRUPTED})

# Internal, evidence-only diagnostic keys. These are deliberately NOT part of
# the public framework-neutral continuity contract: they distinguish how a
# rehydrate happened for qualification evidence, but a browser/API consumer
# only ever sees ``fresh | reattached | rehydrated | interrupted``.
DIAGNOSTIC_NATIVE_RESUME_USED = "native_resume_used"
DIAGNOSTIC_BYQ_FALLBACK_USED = "byq_fallback_used"
DIAGNOSTIC_PREVIOUS_GENERATION_STATE = "previous_generation_state"
DIAGNOSTIC_NATIVE_SESSION_PRESENT = "native_session_present"

DIAGNOSTIC_FIELDS = frozenset({
    DIAGNOSTIC_NATIVE_RESUME_USED,
    DIAGNOSTIC_BYQ_FALLBACK_USED,
    DIAGNOSTIC_PREVIOUS_GENERATION_STATE,
    DIAGNOSTIC_NATIVE_SESSION_PRESENT,
})

# RuntimeGeneration states used only by the D15-3 evidence classification.
GENERATION_ALIVE = "alive"
GENERATION_ABSENT = "absent"
GENERATION_INTERRUPTED = "interrupted"
GENERATION_CLOSED = "closed"
GENERATION_REPLACED = "replaced"

GENERATION_STATES = frozenset({
    GENERATION_ALIVE, GENERATION_ABSENT, GENERATION_INTERRUPTED,
    GENERATION_CLOSED, GENERATION_REPLACED,
})


def valid_continuity(value: object) -> bool:
    """Return whether ``value`` is one of the closed continuity statuses."""

    return isinstance(value, str) and value in STATUSES


def normalize_continuity(value: object, *, default: str = FRESH) -> str:
    """Fail closed on an unknown status instead of inventing one."""

    if value is None:
        return default
    if not valid_continuity(value):
        raise ValueError("invalid runtime continuity status")
    return value


@dataclass(frozen=True)
class ContinuityDecision:
    """Public continuity status plus internal, evidence-only diagnostics.

    ``continuity`` is always one of the closed public statuses. ``diagnostics``
    is not part of the public contract and must not be projected to a browser or
    used as session identity.
    """

    continuity: str
    diagnostics: dict = field(default_factory=dict)
    byq_fallback_required: bool = False

    def __post_init__(self) -> None:
        if not valid_continuity(self.continuity):
            raise ValueError("invalid runtime continuity status")
        if not set(self.diagnostics) <= DIAGNOSTIC_FIELDS:
            raise ValueError("unknown continuity diagnostic field")
        state = self.diagnostics.get(DIAGNOSTIC_PREVIOUS_GENERATION_STATE)
        if state is not None and state not in GENERATION_STATES:
            raise ValueError("invalid previous generation state")


def _require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a bool")
    return value


def classify_generation_transition(
    *,
    generation_survived: bool,
    lost_run: bool,
    native_session_persisted: bool,
    native_resume_available: bool,
    byq_fallback_available: bool,
    previous_generation_state: str | None = None,
) -> ContinuityDecision:
    """Classify one failure-matrix transition into the public continuity status.

    Inputs are framework-neutral facts observed at the AgentSession /
    RuntimeGeneration boundary:

    - ``generation_survived``: the original in-process generation is still
      alive and is reused (Path A reattach).
    - ``lost_run``: an active run was terminated by the fault.
    - ``native_session_persisted``: the DSH session store is durably present.
    - ``native_resume_available``: a new generation can natively open the same
      persisted DSH session and read its log.
    - ``byq_fallback_available``: the BYQ conversation-rehydration path can
      serve the session if native resume is not possible.

    The public status never fabricates a reattach and never disguises a BYQ
    fallback as native resume; the mechanism is recorded only in diagnostics.
    """

    _require_bool(generation_survived, "generation_survived")
    _require_bool(lost_run, "lost_run")
    _require_bool(native_session_persisted, "native_session_persisted")
    _require_bool(native_resume_available, "native_resume_available")
    _require_bool(byq_fallback_available, "byq_fallback_available")
    if previous_generation_state is not None and previous_generation_state not in GENERATION_STATES:
        raise ValueError("invalid previous generation state")

    if generation_survived:
        state = previous_generation_state or GENERATION_ALIVE
        return ContinuityDecision(
            continuity=REATTACHED,
            diagnostics={
                DIAGNOSTIC_NATIVE_RESUME_USED: False,
                DIAGNOSTIC_BYQ_FALLBACK_USED: False,
                DIAGNOSTIC_PREVIOUS_GENERATION_STATE: state,
                DIAGNOSTIC_NATIVE_SESSION_PRESENT: native_session_persisted,
            },
        )

    native_used = bool(native_resume_available)
    fallback_used = (not native_used) and bool(byq_fallback_available)
    if lost_run:
        continuity = INTERRUPTED
        state = GENERATION_INTERRUPTED
    elif native_used or fallback_used:
        continuity = REHYDRATED
        state = previous_generation_state or (
            GENERATION_REPLACED if native_session_persisted else GENERATION_ABSENT)
    else:
        # No recovery path exists: report the truthful interruption rather than
        # inventing a session.
        continuity = INTERRUPTED
        state = previous_generation_state or GENERATION_ABSENT

    return ContinuityDecision(
        continuity=continuity,
        diagnostics={
            DIAGNOSTIC_NATIVE_RESUME_USED: native_used,
            DIAGNOSTIC_BYQ_FALLBACK_USED: fallback_used,
            DIAGNOSTIC_PREVIOUS_GENERATION_STATE: state,
            DIAGNOSTIC_NATIVE_SESSION_PRESENT: native_session_persisted,
        },
        byq_fallback_required=(not native_used) and bool(byq_fallback_available),
    )
