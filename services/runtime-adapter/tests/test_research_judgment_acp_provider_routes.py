"""Offline boundary contracts for the disabled ADR-0097 ACP provider path."""

from __future__ import annotations

import json

import pytest

from app.research_judgment_acp_provider_routes import (
    AcpProviderRouteRejected,
    admit_provider_request,
    selected_route,
)


_CASES = (
    ("deepseek-official", "/anthropic/v1/messages",
     "https://api.deepseek.com/anthropic/v1/messages", "messages"),
    ("opencode-go-responses", "/v1/responses",
     "https://opencode.ai/zen/go/v1/responses", "responses"),
    ("opencode-go-chat", "/v1/chat/completions",
     "https://opencode.ai/zen/go/v1/chat/completions", "chat"),
    ("opencode-go-messages", "/v1/messages?beta=true",
     "https://opencode.ai/zen/go/v1/messages?beta=true", "messages"),
    ("opencode-zen-responses", "/v1/responses",
     "https://opencode.ai/zen/v1/responses", "responses"),
    ("opencode-zen-chat", "/v1/chat/completions",
     "https://opencode.ai/zen/v1/chat/completions", "chat"),
    ("opencode-zen-messages", "/v1/messages?beta=true",
     "https://opencode.ai/zen/v1/messages?beta=true", "messages"),
)


def _headers(protocol: str) -> dict[str, str]:
    if protocol == "messages":
        return {"Content-Type": "application/json", "x-api-key": "synthetic-key",
                "anthropic-version": "2023-06-01", "x-byq-secret": "must-not-forward"}
    return {"Content-Type": "application/json", "Authorization": "Bearer synthetic-key",
            "x-byq-secret": "must-not-forward"}


def _body(protocol: str, *, model: str = "selected-model") -> bytes:
    limit = "max_output_tokens" if protocol == "responses" else "max_tokens"
    return json.dumps({"model": model, limit: 32}).encode()


@pytest.mark.parametrize("name,target,upstream,protocol", _CASES)
def test_exact_selected_route_maps_only_its_protocol_path(name, target, upstream, protocol):
    route = selected_route(name)
    assert route.protocol == protocol
    assert route.upstream_url == upstream
    url, headers = admit_provider_request(
        route, target=target, selected_model="selected-model",
        trusted_credential="synthetic-key", headers=_headers(protocol),
        body=_body(protocol))
    assert url == upstream
    assert "x-byq-secret" not in headers
    assert headers["content-type"] == "application/json"
    assert ("x-api-key" in headers) == (protocol == "messages")
    assert ("authorization" in headers) == (protocol != "messages")


@pytest.mark.parametrize("name", ["opencode-unknown", "deepseek-account", "opencode-"])
def test_unselected_route_rejected(name):
    with pytest.raises(AcpProviderRouteRejected, match="unselected"):
        selected_route(name)


@pytest.mark.parametrize("target", [
    "/v1/models", "/v1/files", "/v1/messages/../files",
    "/v1/messages?beta=true&extra=1", "https://example.test/v1/messages?beta=true",
    "/v1/messages%3Fbeta=true",
])
def test_messages_rejects_discovery_files_and_altered_paths(target):
    route = selected_route("opencode-go-messages")
    with pytest.raises(AcpProviderRouteRejected, match="path"):
        admit_provider_request(route, target=target, selected_model="selected-model",
                               trusted_credential="synthetic-key",
                               headers=_headers("messages"), body=_body("messages"))


@pytest.mark.parametrize("target", [
    "/anthropic/v1/files", "/anthropic/v1/models", "/anthropic/v1/messages/../files",
    "/anthropic/v1/messages?beta=true",
])
def test_deepseek_rejects_files_discovery_and_altered_messages(target):
    route = selected_route("deepseek-official")
    with pytest.raises(AcpProviderRouteRejected, match="path"):
        admit_provider_request(route, target=target, selected_model="selected-model",
                               trusted_credential="synthetic-key",
                               headers=_headers("messages"), body=_body("messages"))


@pytest.mark.parametrize("body", [
    b"not-json", b"[]", b'{"model":"other","max_tokens":32}',
    b'{"model":"selected-model"}', b'{"model":"selected-model","max_tokens":0}',
    b'{"model":"other","model":"selected-model","max_tokens":32}',
    b'{"model":"selected-model","max_tokens":16,"max_tokens":32}',
])
def test_model_and_declared_ceiling_are_closed(body):
    route = selected_route("opencode-go-messages")
    with pytest.raises(AcpProviderRouteRejected):
        admit_provider_request(route, target="/v1/messages?beta=true",
                               selected_model="selected-model",
                               trusted_credential="synthetic-key",
                               headers=_headers("messages"), body=body)


@pytest.mark.parametrize("headers", [
    {"Content-Type": "application/json", "x-api-key": "synthetic-key"},
    {"Content-Type": "application/json", "x-api-key": "synthetic-key",
     "anthropic-version": "2023-06-01", "Authorization": "Bearer mixed"},
    {"Content-Type": "text/plain", "x-api-key": "synthetic-key",
     "anthropic-version": "2023-06-01"},
    {"Content-Type": "application/json", "x-api-key": "synthetic-key",
     "anthropic-version": "2023-06-01", "X-API-KEY": "second-key"},
    {"Content-Type": "application/json", "x-api-key": "synthetic-key",
     "anthropic-version": "2023-06-01", 7: "unexpected-name"},
    {"Content-Type": "application/json", "x-api-key": "synthetic-key",
     "anthropic-version": "2023-06-01", "anthropic-beta": "unqualified-feature"},
])
def test_messages_rejects_missing_mixed_or_ambiguous_auth(headers):
    route = selected_route("opencode-go-messages")
    with pytest.raises(AcpProviderRouteRejected):
        admit_provider_request(route, target="/v1/messages?beta=true",
                               selected_model="selected-model",
                               trusted_credential="synthetic-key",
                               headers=headers, body=_body("messages"))


@pytest.mark.parametrize("name,target,protocol", [
    ("deepseek-official", "/anthropic/v1/messages", "messages"),
    ("opencode-go-chat", "/v1/chat/completions", "chat"),
])
def test_matching_shape_with_wrong_trusted_credential_is_rejected(name, target, protocol):
    with pytest.raises(AcpProviderRouteRejected, match="credential"):
        admit_provider_request(selected_route(name), target=target,
                               selected_model="selected-model", trusted_credential="other-key",
                               headers=_headers(protocol), body=_body(protocol))
