from __future__ import annotations

import json

import app.runtime as runtime_module
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


def test_release_identity_matches_installed_metadata_and_fails_closed(monkeypatch, tmp_path) -> None:
    identity = tmp_path / "release.json"
    identity.write_text(json.dumps({
        "schema_version": "dsh-deployment-identity.v1",
        "default_release": "dsh-0.1.1rc1",
        "python": {"sdk": "0.1.1rc1", "runtime_bin": "0.1.1rc1"},
    }))
    monkeypatch.setenv("BYQ_DSH_RELEASE_IDENTITY", str(identity))
    monkeypatch.setattr(runtime_module, "distribution_version", lambda _name: "0.1.1rc1")
    readiness = RuntimeAdapter().readiness()
    assert readiness["release_id"] == "dsh-0.1.1rc1"
    assert readiness["release_identity"] == "matched"
    assert readiness["runtime_adapter"] == "ready"

    identity.write_text(json.dumps({
        "schema_version": "dsh-deployment-identity.v1",
        "default_release": "dsh-0.1.2rc1",
        "python": {"sdk": "0.1.2rc1", "runtime_bin": "0.1.2rc1"},
    }))
    mismatch = RuntimeAdapter().readiness()
    assert mismatch["release_id"] == "dsh-0.1.2rc1"
    assert mismatch["release_identity"] == "mismatch"
    assert mismatch["runtime_adapter"] == "release-identity-mismatch"
    assert RuntimeAdapter().operations_snapshot()["runtime"]["status"] == "release-identity-mismatch"
