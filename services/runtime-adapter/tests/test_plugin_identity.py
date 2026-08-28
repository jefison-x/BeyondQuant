from __future__ import annotations

import json

from app.runtime import RuntimeAdapter


def test_readiness_reports_only_generated_plugin_identity(monkeypatch, tmp_path) -> None:
    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps({
        "profile": "research",
        "composition_hash": "sha256:" + "a" * 64,
        "enabled_plugin_ids": ["compaction", "guard", "web-search"],
        "credential": "must-not-be-projected",
    }))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION_IDENTITY", str(identity))
    adapter = RuntimeAdapter()
    readiness = adapter.readiness()
    assert readiness["plugin_profile"] == "research"
    assert readiness["composition_hash"] == "sha256:" + "a" * 64
    assert readiness["enabled_plugin_ids"] == ["compaction", "guard", "web-search"]
    assert "must-not-be-projected" not in str(readiness)


def test_invalid_plugin_identity_fails_closed(monkeypatch, tmp_path) -> None:
    identity = tmp_path / "identity.json"
    identity.write_text('{"profile":"research","composition_hash":"secret"}')
    monkeypatch.setenv("BYQ_DSH_COMPOSITION_IDENTITY", str(identity))
    readiness = RuntimeAdapter().readiness()
    assert readiness["plugin_profile"] == "unknown"
    assert readiness["composition_hash"] == "unavailable"
    assert readiness["enabled_plugin_ids"] == []
