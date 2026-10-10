"""ADR-0103 ACP continuation guard-patch composition (keyless)."""

from __future__ import annotations

import time

import pytest

from app.continuation_budget import create_acp_guard_overlay, create_acp_guard_patch


def _reservation():
    from packages.contracts.continuation_request import profile_binding, request_limits
    return {
        "reservation_id": "continuation_" + "a" * 32,
        "execution_profile": profile_binding(),
        "request_limits": request_limits(),
    }


def test_acp_guard_patch_composes_overlay_and_returns_journal(tmp_path):
    source = tmp_path / "byq-product.patch.yml"
    source.write_text("- id: base\n", encoding="utf-8")
    root = tmp_path / "session"
    reservation = _reservation()
    patch, journal = create_acp_guard_patch(
        source, root, reservation, deadline_epoch_ms=int(time.time() * 1000) + 60_000,
        root_run_id="b" * 32, mcp_reservation_id=reservation["reservation_id"],
        proxy_base_url="http://172.31.7.9:41337")
    text = patch.read_text(encoding="utf-8")
    assert "- id: base" in text
    assert "byq-continuation-budget" in text
    assert "deadlineEpochMs" in text
    assert reservation["reservation_id"] in text
    assert "http://172.31.7.9:41337" in text
    assert journal == root / f"continuation-tool-guard-{'b' * 32}.jsonl"


def test_acp_guard_patch_refuses_mismatched_mcp_carrier(tmp_path):
    source = tmp_path / "byq-product.patch.yml"
    source.write_text("- id: base\n", encoding="utf-8")
    reservation = _reservation()
    with pytest.raises(ValueError, match="MCP identity carrier"):
        create_acp_guard_patch(
            source, tmp_path / "s", reservation,
            deadline_epoch_ms=int(time.time() * 1000) + 60_000,
            root_run_id="b" * 32, mcp_reservation_id="continuation_" + "c" * 32,
            proxy_base_url="http://172.31.7.9:41337")


def test_acp_guard_overlay_is_the_exact_restricted_json():
    import json
    reservation = _reservation()
    raw = create_acp_guard_overlay(
        reservation, deadline_epoch_ms=int(time.time() * 1000) + 60_000,
        root_run_id="b" * 32, mcp_reservation_id=reservation["reservation_id"],
        proxy_base_url="http://172.31.7.9:41337",
        provider_session_id="123e4567-e89b-42d3-a456-426614174000")
    value = json.loads(raw)
    assert value[0] == {"id": "web-search-deepseek", "disabled": True}
    assert value[1] == {"id": "tool-web", "disabled": True}
    # The Product JSON overlay keeps llm-deepseek ACTIVE with a capped output:
    # the trusted Product runner validator requires exactly {id, config.maxTokens}
    # for this entry (DSH session/new needs a registered default-provider adapter).
    assert value[2] == {"id": "llm-deepseek", "config": {"maxTokens": 8192}}
    chat = value[3]["config"]["providers"]["opencode-go-chat"]
    assert value[3]["id"] == "llm-pi-ai"
    assert chat["api"] == "openai-completions"
    assert chat["apiKeyEnv"] == "OPENCODE_API_KEY"
    assert chat["baseURL"] == "http://172.31.7.9:41337"
    assert chat["retryPolicy"] == {"mode": "normal", "maxRetries": 0}
    # The OpenCode Go route requires the exact provider session header; the
    # overlay replaces the provider config, so it must carry the resolved value.
    assert chat["headers"] == {"x-opencode-session": "123e4567-e89b-42d3-a456-426614174000"}
    assert chat["models"] == [{"id": "deepseek-v4.1-flash", "maxTokens": 8192}]
    entry = value[4]["insert"][0]
    assert entry["id"] == "byq-continuation-budget"
    assert entry["name"] == "file:///opt/byq/runtime/byq-continuation-budget.js"
    assert set(entry["config"]) == {"deadlineEpochMs", "reservationId",
                                    "executionProfile", "requestLimits"}


def test_acp_guard_overlay_refuses_nonlocal_proxy():
    reservation = _reservation()
    with pytest.raises(ValueError, match="local continuation proxy"):
        create_acp_guard_overlay(
            reservation, deadline_epoch_ms=int(time.time() * 1000) + 60_000,
            root_run_id="b" * 32, mcp_reservation_id=reservation["reservation_id"],
            proxy_base_url="https://opencode.ai/zen/go/v1",
            provider_session_id="123e4567-e89b-42d3-a456-426614174000")


def test_acp_guard_patch_refuses_expired_deadline(tmp_path):
    source = tmp_path / "byq-product.patch.yml"
    source.write_text("- id: base\n", encoding="utf-8")
    reservation = _reservation()
    with pytest.raises(ValueError, match="future epoch"):
        create_acp_guard_patch(
            source, tmp_path / "s", reservation, deadline_epoch_ms=1,
            root_run_id="b" * 32, mcp_reservation_id=reservation["reservation_id"],
            proxy_base_url="http://172.31.7.9:41337")
