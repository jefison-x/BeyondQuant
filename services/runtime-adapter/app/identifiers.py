from __future__ import annotations

import re
from pathlib import Path


MAX_IDENTIFIER_LENGTH = 64
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class InvalidIdentifier(ValueError):
    """A BYQ identifier is not safe for API and session-root use."""


def validate_identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidIdentifier(f"{field} must not be empty")
    if len(value) > MAX_IDENTIFIER_LENGTH:
        raise InvalidIdentifier(f"{field} exceeds {MAX_IDENTIFIER_LENGTH} characters")
    if _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise InvalidIdentifier(
            f"{field} must match {_IDENTIFIER_PATTERN.pattern}"
        )
    return value


def contained_session_path(root: Path, session_id: str) -> Path:
    """Resolve a session path and prove that it remains below the DSH root."""

    resolved_root = root.expanduser().resolve()
    candidate = (resolved_root / validate_identifier(session_id, field="session_id")).resolve()
    if candidate == resolved_root or not candidate.is_relative_to(resolved_root):
        raise InvalidIdentifier("session_id resolves outside DSH_SESSION_ROOT")
    return candidate
