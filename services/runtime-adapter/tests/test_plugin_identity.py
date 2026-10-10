from __future__ import annotations

import hashlib
import importlib.metadata
import json

import app.runtime as runtime_module
from app.runtime import RuntimeAdapter


ACP_RELEASE = "dsh-v0.2.0-rc.2"
ACP_COMMIT = "639ed015397290b3745d163aafe02ffee4aa3f84"


def _configure_acp_identity(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    entry = runtime_root / "apps" / "cli" / "lib" / "bin.js"
    entry.parent.mkdir(parents=True)
    entry.write_text("synthetic ACP entry", encoding="utf-8")
    lock = runtime_root / "pnpm-lock.yaml"
    lock.write_text("synthetic lock", encoding="utf-8")

    release_identity = tmp_path / "release.json"
    release_identity.write_text(json.dumps({
        "schema_version": "dsh-acp-deployment-identity.v1",
        "release_id": ACP_RELEASE,
        "source_commit": ACP_COMMIT,
        "pnpm_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
    }), encoding="utf-8")

    composition = tmp_path / "composition.yml"
    composition.write_text("profile: synthetic\n", encoding="utf-8")
    composition_identity = tmp_path / "composition-identity.json"
    composition_identity.write_text(json.dumps({
        "profile": "research",
        "composition_hash": "sha256:" + hashlib.sha256(composition.read_bytes()).hexdigest(),
        "enabled_plugin_ids": ["compaction", "guard", "web-search"],
    }), encoding="utf-8")

    monkeypatch.setenv("BYQ_DSH_COMPATIBILITY_RELEASE", "dsh-v0.2.0-rc.2-acp")
    monkeypatch.setenv("BYQ_DSH_ACP_PROCESS_TRANSPORT", "local")
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv("BYQ_DSH_RELEASE_IDENTITY", str(release_identity))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(composition))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION_IDENTITY", str(composition_identity))
    return release_identity, composition_identity, lock


def test_readiness_reports_only_generated_plugin_identity(monkeypatch, tmp_path) -> None:
    _configure_acp_identity(monkeypatch, tmp_path)
    identity = tmp_path / "composition-identity.json"
    value = json.loads(identity.read_text())
    value["credential"] = "must-not-be-projected"
    identity.write_text(json.dumps(value), encoding="utf-8")

    readiness = RuntimeAdapter().readiness()
    assert readiness["plugin_profile"] == "research"
    assert readiness["enabled_plugin_ids"] == ["compaction", "guard", "web-search"]
    assert "must-not-be-projected" not in str(readiness)


def test_invalid_plugin_identity_fails_closed(monkeypatch, tmp_path) -> None:
    _configure_acp_identity(monkeypatch, tmp_path)
    identity = tmp_path / "composition-identity.json"
    identity.write_text('{"profile":"research","composition_hash":"secret"}', encoding="utf-8")

    readiness = RuntimeAdapter().readiness()
    assert readiness["plugin_profile"] == "unknown"
    assert readiness["composition_hash"] == "unavailable"
    assert readiness["enabled_plugin_ids"] == []
    assert readiness["runtime_adapter"] == "release-identity-mismatch"


def test_acp_release_identity_is_verified_without_python_sdk_metadata(monkeypatch, tmp_path) -> None:
    release_identity, _composition_identity, _lock = _configure_acp_identity(monkeypatch, tmp_path)

    def no_python_dsh_distribution(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError("Python DSH SDK is not installed")

    monkeypatch.setattr(runtime_module, "distribution_version", no_python_dsh_distribution, raising=False)
    monkeypatch.setattr(importlib.metadata, "version", no_python_dsh_distribution)
    adapter = RuntimeAdapter()
    readiness = adapter.readiness()

    assert readiness["runtime_adapter"] == "ready"
    assert readiness["release_id"] == ACP_RELEASE
    assert readiness["release_identity"] == "matched"
    assert readiness["sdk"] == "deepseek-harness-sdk==not-applicable"
    assert readiness["runtime_bin"] == "deepseek-harness-runtime-bin==not-applicable"

    identity = json.loads(release_identity.read_text())
    identity["source_commit"] = "0" * 40
    release_identity.write_text(json.dumps(identity), encoding="utf-8")
    mismatch = adapter.readiness()
    assert mismatch["release_identity"] == "unavailable"
    assert mismatch["runtime_adapter"] == "release-identity-mismatch"
    assert adapter.operations_snapshot()["runtime"]["status"] == "release-identity-mismatch"
