"""ADR-0103 ACP continuation guard-patch composition (keyless)."""

from __future__ import annotations

import time

import pytest

from app.continuation_budget import create_acp_guard_patch


def _reservation():
    return {
        "reservation_id": "continuation_" + "a" * 32,
        "execution_profile": "continuation-bounded.v1",
        "request_limits": {"max_tool_calls": 4},
    }


def test_acp_guard_patch_composes_overlay_and_returns_journal(tmp_path):
    source = tmp_path / "byq-product.patch.yml"
    source.write_text("- id: base\n", encoding="utf-8")
    root = tmp_path / "session"
    reservation = _reservation()
    patch, journal = create_acp_guard_patch(
        source, root, reservation, deadline_epoch_ms=int(time.time() * 1000) + 60_000,
        root_run_id="b" * 32, mcp_reservation_id=reservation["reservation_id"])
    text = patch.read_text(encoding="utf-8")
    assert "- id: base" in text
    assert "byq-continuation-budget" in text
    assert "deadlineEpochMs" in text
    assert reservation["reservation_id"] in text
    assert journal == root / "continuation-tool-guard.jsonl"


def test_acp_guard_patch_refuses_mismatched_mcp_carrier(tmp_path):
    source = tmp_path / "byq-product.patch.yml"
    source.write_text("- id: base\n", encoding="utf-8")
    reservation = _reservation()
    with pytest.raises(ValueError, match="MCP identity carrier"):
        create_acp_guard_patch(
            source, tmp_path / "s", reservation,
            deadline_epoch_ms=int(time.time() * 1000) + 60_000,
            root_run_id="b" * 32, mcp_reservation_id="continuation_" + "c" * 32)


def test_acp_guard_patch_refuses_expired_deadline(tmp_path):
    source = tmp_path / "byq-product.patch.yml"
    source.write_text("- id: base\n", encoding="utf-8")
    reservation = _reservation()
    with pytest.raises(ValueError, match="future epoch"):
        create_acp_guard_patch(
            source, tmp_path / "s", reservation, deadline_epoch_ms=1,
            root_run_id="b" * 32, mcp_reservation_id=reservation["reservation_id"])
