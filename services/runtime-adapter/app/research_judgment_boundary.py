"""ADR-0085 P4: pure authentication/identity helpers for the judgment entry.

Kept free of FastAPI so the threat reproduction (unauthenticated/forged callers
never reach admission) is host-testable, and so the HTTP route stays a thin
adapter over one trusted boundary.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re

SERVICE_TOKEN_ENV = "BYQ_RUNTIME_JUDGMENT_TOKEN"
SERVICE_TOKEN_HEADER = "x-byq-runtime-judgment-token"
ATTEMPT_HEADER = "x-byq-judgment-attempt"

# Authoritative attempt binding derived from the persisted plan:
# "<plan_version>:<stage>:<iteration>". A retry of the SAME logical turn reuses
# the same value (and therefore the same durable stage-call admission), while a
# legitimate new stage/plan revision gets a new value.
_ATTEMPT_RE = re.compile(r"^[0-9]+:[a-z_]+:[0-9]+$")

_TRUSTED_HEADERS = {
    "x-byq-owner-principal": "owner_principal",
    "x-byq-workspace-id": "workspace_id",
    "x-byq-actor-principal": "actor_principal",
    "x-byq-trace-id": "trace_id",
    "x-byq-session-id": "session_id",
    "x-byq-dsh-run-id": "dsh_run_id",
}


class BoundaryError(RuntimeError):
    """A trusted judgment boundary was violated; carries the closed HTTP status."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def require_service_token(headers, env=None) -> None:
    """Reject unauthenticated or forged callers before any admission/model turn."""

    environment = os.environ if env is None else env
    expected = environment.get(SERVICE_TOKEN_ENV)
    if not expected:
        raise BoundaryError(503, "research judgment entry is disabled")
    supplied = headers.get(SERVICE_TOKEN_HEADER, "")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise BoundaryError(401, "trusted runtime service authentication failed")


def trusted_context(headers) -> tuple[dict, dict]:
    """Return (identity, trusted_headers) or fail closed on an incomplete context."""

    identity: dict = {}
    trusted_headers: dict = {}
    for header, field in _TRUSTED_HEADERS.items():
        value = headers.get(header)
        if not value:
            raise BoundaryError(401, "trusted judgment context required")
        identity[field] = value
        trusted_headers[header] = value
    return identity, trusted_headers


def valid_task_identity(task_id: object) -> bool:
    return isinstance(task_id, str) and task_id.startswith("task_") \
        and len(task_id) == len("task_") + 32


def require_attempt(headers) -> str:
    """Return the authoritative attempt binding or fail closed.

    The trusted service supplies the persisted plan's version/stage/iteration; it
    is NEVER derived from a model-visible value.
    """

    value = headers.get(ATTEMPT_HEADER, "")
    if not value or not _ATTEMPT_RE.fullmatch(value):
        raise BoundaryError(422, "exact authoritative judgment attempt binding required")
    return value


def derive_call_identity(task_id: str, attempt: str) -> str:
    """Retry-stable durable stage-call identity for one (task, attempt)."""

    digest = hashlib.sha256(f"{task_id}:{attempt}".encode()).hexdigest()[:32]
    return f"byq-judgment-{digest}"
