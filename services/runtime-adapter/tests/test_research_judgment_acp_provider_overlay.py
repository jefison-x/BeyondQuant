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


@pytest.mark.parametrize("name", [
    "deepseek-official", "opencode-go-chat", "opencode-go-responses",
    "opencode-go-messages", "opencode-zen-chat", "opencode-zen-responses",
    "opencode-zen-messages",
])
def test_private_overlay_selects_only_one_fixed_route(tmp_path, name):
    route = selected_route(name)
    base = "http://127.0.0.1:43210" + route.local_base_path
    rows = private_provider_overlay(route_name=name, model="synthetic-model",
                                    proxy_base_url=base)
    assert {row["id"] for row in rows} == {"llm-deepseek", "llm-pi-ai"}
    if name == "deepseek-official":
        assert rows[0]["config"]["baseURL"] == base
        assert rows[1]["disabled"] is True
    else:
        assert rows[0]["disabled"] is True
        assert list(rows[1]["config"]["providers"]) == [name]
        selected = rows[1]["config"]["providers"][name]
        assert selected["baseURL"] == base
        assert selected["models"] == [{"id": "synthetic-model"}]
        assert selected["retryPolicy"]["maxRetries"] == 0
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    path = write_private_provider_overlay(directory, route_name=name,
                                          model="synthetic-model", proxy_base_url=base)
    assert json.loads(path.read_text()) == rows
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    with pytest.raises(FileExistsError):
        write_private_provider_overlay(directory, route_name=name,
                                       model="synthetic-model", proxy_base_url=base)


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
        proxy_base_url=base)
    assert rows[1]["config"]["providers"]["opencode-go-chat"]["baseURL"] == base
    for host in ("0.0.0.0", "8.8.8.8", "169.254.1.1", "localhost",
                 "172.32.0.1", "127.000.000.001", "::1"):
        assert not valid_local_proxy_bind_host(host)
        with pytest.raises(ValueError, match="exact selected"):
            private_provider_overlay(
                route_name="opencode-go-chat", model="synthetic-model",
                proxy_base_url=f"http://{host}:43210/v1")
