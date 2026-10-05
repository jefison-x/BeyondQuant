"""Closed outbound route contract for the pinned ADR-0097 judgment candidate.

This is a pure admission helper. It does not start a proxy, count attempts, or
make ACP judgment executable. The eventual request gate must invoke it before
each external request and keep its own durable attempt/unknown journal.
"""

from __future__ import annotations

import json
import hmac
import re
from dataclasses import dataclass
from typing import Mapping

from .research_request_gate import resolve_declared_output_tokens


class AcpProviderRouteRejected(ValueError):
    """The request cannot be sent on the selected provider route."""


LOCAL_TOKEN_PREFIX = "byq-acp-proxy-"
_LOCAL_TOKEN = re.compile(r"byq-acp-proxy-[A-Za-z0-9_-]{43}\Z")


def valid_local_provider_token(value: object) -> bool:
    return isinstance(value, str) and _LOCAL_TOKEN.fullmatch(value) is not None


def _same_secret(received: str, expected: str) -> bool:
    return hmac.compare_digest(received.encode("utf-8"), expected.encode("utf-8"))


@dataclass(frozen=True)
class AcpProviderRoute:
    name: str
    protocol: str
    upstream_origin: str
    upstream_prefix: str
    local_base_path: str
    request_target: str

    @property
    def upstream_url(self) -> str:
        return self.upstream_origin + self.upstream_prefix + self.request_target


_ROUTES = {
    "deepseek-official": AcpProviderRoute(
        "deepseek-official", "messages", "https://api.deepseek.com",
        "/anthropic", "/anthropic", "/v1/messages"),
    "opencode-go-responses": AcpProviderRoute(
        "opencode-go-responses", "responses", "https://opencode.ai",
        "/zen/go/v1", "/v1", "/responses"),
    "opencode-go-chat": AcpProviderRoute(
        "opencode-go-chat", "chat", "https://opencode.ai",
        "/zen/go/v1", "/v1", "/chat/completions"),
    "opencode-go-messages": AcpProviderRoute(
        "opencode-go-messages", "messages", "https://opencode.ai",
        "/zen/go", "", "/v1/messages?beta=true"),
    "opencode-zen-responses": AcpProviderRoute(
        "opencode-zen-responses", "responses", "https://opencode.ai",
        "/zen/v1", "/v1", "/responses"),
    "opencode-zen-chat": AcpProviderRoute(
        "opencode-zen-chat", "chat",
        "https://opencode.ai", "/zen/v1", "/v1", "/chat/completions"),
    "opencode-zen-messages": AcpProviderRoute(
        "opencode-zen-messages", "messages", "https://opencode.ai",
        "/zen", "", "/v1/messages?beta=true"),
}


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    value: dict = {}
    for key, item in pairs:
        if key in value:
            raise AcpProviderRouteRejected("ACP provider body has duplicate fields")
        value[key] = item
    return value


def selected_route(name: str) -> AcpProviderRoute:
    try:
        return _ROUTES[name]
    except (KeyError, TypeError) as error:
        raise AcpProviderRouteRejected("unselected ACP provider route") from error


def admit_provider_request(
    route: AcpProviderRoute, *, target: str, selected_model: str,
    local_credential: str, upstream_credential: str,
    headers: Mapping[str, str], body: bytes,
) -> tuple[str, dict[str, str]]:
    """Return one exact upstream URL and credential headers or reject locally.

    The caller sends the original body only after a separate budget admission.
    No arbitrary Location, path, query or client-supplied upstream host is used.
    """
    if route.name not in _ROUTES or route != _ROUTES[route.name]:
        raise AcpProviderRouteRejected("unselected ACP provider route")
    if target != route.local_base_path + route.request_target:
        raise AcpProviderRouteRejected("ACP provider path is unqualified")
    if not isinstance(selected_model, str) or not selected_model or len(selected_model) > 128:
        raise AcpProviderRouteRejected("selected model is invalid")
    if (not valid_local_provider_token(local_credential)
            or not isinstance(upstream_credential, str) or not upstream_credential.strip()
            or _same_secret(local_credential, upstream_credential)):
        raise AcpProviderRouteRejected("distinct local and upstream credentials are required")
    try:
        payload = json.loads(body, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise AcpProviderRouteRejected("ACP provider body is invalid") from error
    if not isinstance(payload, dict) or payload.get("model") != selected_model:
        raise AcpProviderRouteRejected("ACP provider model differs from selection")
    if payload.get("stream") is not True:
        raise AcpProviderRouteRejected("ACP provider must use the qualified streaming path")
    if resolve_declared_output_tokens(payload)[1] is not None:
        raise AcpProviderRouteRejected("ACP provider output limit is missing or invalid")
    if route.protocol == "chat" and "n" in payload \
            and (type(payload["n"]) is not int or payload["n"] != 1):
        raise AcpProviderRouteRejected("ACP Chat requires exactly one choice")

    normalized: dict[str, str] = {}
    for name, value in headers.items():
        if not isinstance(name, str):
            raise AcpProviderRouteRejected("ACP provider headers are ambiguous")
        key = name.lower()
        if key in normalized or not isinstance(value, str) or "\r" in value or "\n" in value:
            raise AcpProviderRouteRejected("ACP provider headers are ambiguous")
        normalized[key] = value
    if normalized.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise AcpProviderRouteRejected("ACP provider content type is invalid")
    forwarded = {"content-type": "application/json"}
    if route.protocol == "messages":
        # The pinned SDK may add beta features for some model/tool combinations.
        # Their exact semantics are not qualified for this bounded text path.
        if "anthropic-beta" in normalized:
            raise AcpProviderRouteRejected("ACP Messages beta feature is unqualified")
        if (not _same_secret(normalized.get("x-api-key", ""), local_credential)
                or normalized.get("authorization")
                or normalized.get("anthropic-version") != "2023-06-01"):
            raise AcpProviderRouteRejected("ACP Messages credential or version is invalid")
        forwarded.update({"x-api-key": upstream_credential,
                          "anthropic-version": "2023-06-01"})
    else:
        authorization = normalized.get("authorization", "")
        if (not _same_secret(authorization, "Bearer " + local_credential)
                or normalized.get("x-api-key")):
            raise AcpProviderRouteRejected("ACP OpenAI credential is invalid")
        forwarded["authorization"] = "Bearer " + upstream_credential
    if "accept" in normalized:
        forwarded["accept"] = normalized["accept"]
    return route.upstream_url, forwarded
