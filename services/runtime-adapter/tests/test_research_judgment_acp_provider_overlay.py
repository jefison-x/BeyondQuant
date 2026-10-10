"""One-route private ACP provider overlay, no DSH process or model call."""

from __future__ import annotations

import json
import os
import stat

import pytest

from app.research_judgment_acp_provider_overlay import (
    private_provider_overlay, valid_local_proxy_bind_host,
    write_private_provider_overlay,
)
from app.research_judgment_acp_provider_routes import selected_route

SESSION = "11111111-2222-4333-8444-555555555555"


@pytest.mark.parametrize("name", [
    "deepseek-official", "opencode-go-chat", "opencode-go-responses",
    "opencode-go-messages", "opencode-zen-chat", "opencode-zen-responses",
    "opencode-zen-messages",
])
def test_private_overlay_selects_only_one_fixed_route(tmp_path, name):
    route = selected_route(name)
    base = "http://127.0.0.1:43210" + route.local_base_path
    rows = private_provider_overlay(route_name=name, model="synthetic-model",
                                    proxy_base_url=base, provider_session_id=SESSION)
    assert {row["id"] for row in rows} == {"llm-deepseek", "llm-pi-ai"}
    if name == "deepseek-official":
        assert rows[0]["config"]["baseURL"] == base
        assert rows[1]["disabled"] is True
    else:
        # ADR-0097/0099: the selected route is the only provider egress, but the
        # default-provider adapter (llm-deepseek) MUST stay registered because
        # the pinned DSH `session/new` requires it; only its output is capped and
        # it is never rebound to the proxy.
        assert rows[0].get("disabled") is not True
        assert "baseURL" not in rows[0].get("config", {})
        assert list(rows[1]["config"]["providers"]) == [name]
        selected = rows[1]["config"]["providers"][name]
        assert selected["baseURL"] == base
        assert selected["headers"] == {"x-opencode-session": SESSION}
        assert selected["models"] == [{"id": "synthetic-model"}]
        assert selected["retryPolicy"]["maxRetries"] == 0
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    path = write_private_provider_overlay(directory, route_name=name,
                                          model="synthetic-model", proxy_base_url=base,
                                          provider_session_id=SESSION)
    assert json.loads(path.read_text()) == rows
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    with pytest.raises(FileExistsError):
        write_private_provider_overlay(directory, route_name=name,
                                       model="synthetic-model", proxy_base_url=base,
                                       provider_session_id=SESSION)


@pytest.mark.parametrize("base", [
    "https://opencode.ai/zen/v1", "http://localhost:43210/v1",
    "http://127.0.0.1:0/v1", "http://127.0.0.1:43210/other",
    "http://127.0.0.1:43210/v1?redirect=true",
])
def test_private_overlay_refuses_nonexact_loopback_base(base):
    with pytest.raises(ValueError, match="exact selected"):
        private_provider_overlay(route_name="opencode-go-chat",
                                 model="synthetic-model", proxy_base_url=base)


def test_internal_runner_proxy_overlay_requires_a_private_literal_address():
    base = "http://172.20.0.7:43210/v1"
    rows = private_provider_overlay(
        route_name="opencode-go-chat", model="synthetic-model",
        proxy_base_url=base, provider_session_id=SESSION)
    assert rows[1]["config"]["providers"]["opencode-go-chat"]["baseURL"] == base
    for host in ("0.0.0.0", "8.8.8.8", "169.254.1.1", "localhost",
                 "172.32.0.1", "127.000.000.001", "::1"):
        assert not valid_local_proxy_bind_host(host)
        with pytest.raises(ValueError, match="exact selected"):
            private_provider_overlay(
                route_name="opencode-go-chat", model="synthetic-model",
                proxy_base_url=f"http://{host}:43210/v1")


def test_private_overlay_keeps_the_default_adapter_registered_and_capped():
    # The pinned DSH session/new needs the default-provider adapter, so the
    # selected opencode route must keep llm-deepseek active and output-capped
    # (never disabled, never rebound to the proxy).
    base = "http://172.20.0.7:43210/v1"
    rows = private_provider_overlay(
        route_name="opencode-go-chat", model="deepseek-v4.1-flash",
        proxy_base_url=base, max_output_tokens=8192, provider_session_id=SESSION)
    assert rows[0] == {"id": "llm-deepseek", "config": {"maxTokens": 8192}}
    selected = rows[1]["config"]["providers"]["opencode-go-chat"]
    assert selected["headers"] == {"x-opencode-session": SESSION}
    assert selected["models"] == [{"id": "deepseek-v4.1-flash", "maxTokens": 8192}]
