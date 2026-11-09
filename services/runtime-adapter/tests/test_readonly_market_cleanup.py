"""ADR-0117 must not turn the old exact-scope verifier into a generic bypass."""

import hashlib
from types import SimpleNamespace

import pytest

from app import historical_audit_cleanup as cleanup
from packages.contracts.acp_product_slot import canonical_product_json


def scope_file(tmp_path, root):
    scope = {
        "owner_principal": "admin",
        "workspace_id": "workspace_4c5b803209d549019b7804976f6930c6",
        "session_id": "byq-session-e84ae897741647b7b27881de996cc06c",
        "trace_id": "byq-trace-06a38817a2bc4a34839fd1111795f387",
        "root_run_id": root, "runtime_boot_id": "a" * 32,
        "generation_id": "generation-" + "b" * 32,
    }
    raw = canonical_product_json({
        "schema_version": cleanup.EXPECTED_SCOPE_SCHEMA, "scope": scope,
        "native_root_session_id": "11111111-1111-4111-8111-111111111111",
        "backend_snapshot_sha256": "c" * 64,
    })
    path = tmp_path / "scope.json"
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("readonly,root,allowed", [
    (True, cleanup.READONLY_MARKET_ROOT_RUN_ID, True),
    (False, cleanup.HISTORICAL_ROOT_RUN_ID, True),
    (True, cleanup.HISTORICAL_ROOT_RUN_ID, False),
    (False, cleanup.READONLY_MARKET_ROOT_RUN_ID, False),
    (True, "d" * 32, False),
])
def test_explicit_modes_cannot_cross_roots(tmp_path, readonly, root, allowed):
    path, digest = scope_file(tmp_path, root)
    if allowed:
        scope, _, _ = cleanup._read_expected_scope(path, digest, readonly_market_error=readonly)
        assert scope["root_run_id"] == root
    else:
        with pytest.raises(cleanup.HistoricalCleanupHold, match="outside"):
            cleanup._read_expected_scope(path, digest, readonly_market_error=readonly)


def test_changed_frozen_scope_is_rejected(tmp_path):
    path, digest = scope_file(tmp_path, cleanup.READONLY_MARKET_ROOT_RUN_ID)
    path.write_bytes(path.read_bytes().replace(b'"admin"', b'"other"'))
    with pytest.raises(cleanup.HistoricalCleanupHold, match="digest changed"):
        cleanup._read_expected_scope(path, digest, readonly_market_error=True)


def test_readonly_mode_requires_its_separate_readonly_engineering_manifest(tmp_path, monkeypatch):
    path = tmp_path / "readonly-market-manifest.json"
    monkeypatch.setattr(cleanup, "READONLY_MARKET_MANIFEST_PATH", path)
    # Model the privileged, read-only bind mount. The content stays a real file.
    original_lstat = cleanup.os.lstat
    def lstat(value, *args, **kwargs):
        actual = original_lstat(value, *args, **kwargs)
        if str(value) == str(tmp_path):
            return SimpleNamespace(st_mode=actual.st_mode, st_uid=0)
        return actual
    monkeypatch.setattr(cleanup.os, "lstat", lstat)
    monkeypatch.setattr(cleanup.os, "statvfs", lambda value: SimpleNamespace(f_flag=cleanup.os.ST_RDONLY))
    manifest = {key: "e" * 64 for key in cleanup._MANIFEST_KEYS}
    manifest.update(schema_version=cleanup.READONLY_MARKET_MANIFEST_SCHEMA,
                    native_root_session_id="11111111-1111-4111-8111-111111111111")
    path.write_bytes(canonical_product_json(manifest))
    path.chmod(0o444)
    assert cleanup._read_trusted_manifest(readonly_market_error=True) == manifest
    path.chmod(0o644)
    manifest["schema_version"] = cleanup.EXPECTED_MANIFEST_SCHEMA
    path.write_bytes(canonical_product_json(manifest))
    path.chmod(0o444)
    with pytest.raises(cleanup.HistoricalCleanupHold, match="schema"):
        cleanup._read_trusted_manifest(readonly_market_error=True)
    monkeypatch.setattr(cleanup.os, "statvfs", lambda value: SimpleNamespace(f_flag=0))
    with pytest.raises(cleanup.HistoricalCleanupHold, match="not read-only"):
        cleanup._read_trusted_manifest(readonly_market_error=True)
