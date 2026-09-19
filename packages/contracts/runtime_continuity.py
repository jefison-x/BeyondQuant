"""Framework-neutral AgentSession / RuntimeGeneration continuity vocabulary.

ADR-0079 R2 separates durable session identity from ephemeral runtime
generations. A session create/resume/rebind reports one closed continuity status
so callers can distinguish a brand-new session from an in-process reattach and
from a truthful replacement generation. The vocabulary is BYQ-owned: it carries
no DSH session, process or event schema.
"""

from __future__ import annotations

CONTINUITY_VERSION = "runtime-continuity.v1"

FRESH = "fresh"
REATTACHED = "reattached"
REHYDRATED = "rehydrated"
INTERRUPTED = "interrupted"

STATUSES = frozenset({FRESH, REATTACHED, REHYDRATED, INTERRUPTED})


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
