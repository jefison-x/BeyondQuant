from __future__ import annotations

import hmac
from dataclasses import dataclass


class AuthenticationUnavailable(RuntimeError):
    """The Gateway has not been configured with a product authentication secret."""


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str


def authenticate_bearer(
    authorization: str | None,
    *,
    configured_token: str | None,
    subject: str,
) -> Principal:
    """Authenticate the Phase 7 opaque product token without exposing it."""

    if not configured_token:
        raise AuthenticationUnavailable("product authentication is not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise PermissionError("a Bearer token is required")
    presented = authorization.removeprefix("Bearer ")
    if not presented or not hmac.compare_digest(presented, configured_token):
        raise PermissionError("invalid product credentials")
    return Principal(subject=subject)
