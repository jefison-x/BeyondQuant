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


# Exact non-secret original identity; synthetic test never contacts a Runner.
_ORIGINAL = {'binding': {'cleanup_unconfirmed': False, 'closed': False, 'cwd': '/var/lib/byq/dsh-sessions/dsh-v0.2.0-rc.2-acp/workspace_4c5b803209d549019b7804976f6930c6/session-5c2bdd1e8ea247f083724213013d8957', 'domain_call_drained_sequence': 0, 'domain_call_sequence': 0, 'model_id': 'deepseek-flash', 'model_provider': 'deepseek-official', 'native_session_close_confirmed': False, 'native_session_id': 'a1d158ec-b89b-45c6-8846-92ee9e8b6567', 'owner_principal': 'admin', 'previous_authority_epoch': 51, 'previous_boot_id': '33e339aa0f16c1d4f0604f9f75bdb33d', 'process_exit_confirmed': True, 'root_run_id': 'f6dc48f8c4e446c6912eed772a47493f', 'runtime_generation': 'generation-cca499003b9948c998f0a977dbee34be', 'schema_version': 'byq-acp-root-binding.v1', 'sequence': 1, 'session_id': 'byq-session-e84ae897741647b7b27881de996cc06c', 'settlement_receipt': None, 'trace_id': 'byq-trace-06a38817a2bc4a34839fd1111795f387', 'workspace_id': 'workspace_4c5b803209d549019b7804976f6930c6'}, 'terminal': {'schema_version': 'byq-runtime-terminal-evidence.v1', 'session_id': 'byq-session-e84ae897741647b7b27881de996cc06c', 'boot_id': '33e339aa0f16c1d4f0604f9f75bdb33d', 'root_run_id': 'f6dc48f8c4e446c6912eed772a47493f', 'sequence': 38, 'outcome': 'completed', 'receipt': {'schema_version': 'agent-run-lifecycle-receipt.v1', 'sequence': 38, 'root_run_id': 'f6dc48f8c4e446c6912eed772a47493f', 'event_sha256': '3d33d004ca54667c98b1588ecb4a9838e93f47d05b236a5f5d533848141b29b6'}}}


@pytest.mark.parametrize("field", list(_ORIGINAL["binding"]))
def test_terminal_cursor_rejects_any_changed_binding_field(field):
    from app.runtime import _adr0117_original_terminal_cursor
    binding = dict(_ORIGINAL["binding"])
    binding[field] = "changed"
    assert not _adr0117_original_terminal_cursor(binding, _ORIGINAL["terminal"]["receipt"], 38, 38)


def test_exact_terminal_cursor_only():
    from app.runtime import _adr0117_original_terminal_cursor
    binding, receipt = _ORIGINAL["binding"], _ORIGINAL["terminal"]["receipt"]
    assert _adr0117_original_terminal_cursor(binding, receipt, 38, 38)
    for initial, tail in [(1, 1), (38, 39), (39, 38), (38.0, 38)]:
        assert not _adr0117_original_terminal_cursor(binding, receipt, initial, tail)
    for field in receipt:
        assert not _adr0117_original_terminal_cursor(binding, {**receipt, field: "changed"}, 38, 38)


def test_original_terminal_recovery_persists_38_then_acknowledges_39(tmp_path, monkeypatch):
    import json
    from app.compat import compatibility_for_release
    from app.runtime import RuntimeAdapter
    monkeypatch.setenv('BYQ_DSH_ACP_PROCESS_TRANSPORT', 'local')
    monkeypatch.setenv('BYQ_DSH_PROCESS_OWNERSHIP', 'root-turn')
    adapter = RuntimeAdapter(compatibility_for_release('dsh-v0.2.0-rc.2-acp'))
    binding = dict(_ORIGINAL['binding'])
    path = tmp_path / 'binding.json'
    path.write_text(json.dumps(binding))
    monkeypatch.setattr(adapter, '_acp_binding_path', lambda *args: path)
    monkeypatch.setattr(adapter, '_read_acp_binding', lambda *args: json.loads(path.read_text()))
    monkeypatch.setattr(adapter, 'require_current_backend_authority', lambda: 52)
    monkeypatch.setattr(adapter, '_resolve_model', lambda **kwargs: {
        'provider': 'deepseek-official', 'model': 'deepseek-flash', 'api_key': 'synthetic'})
    monkeypatch.setattr(adapter, '_build_harness', lambda *args, **kwargs: pytest.fail('must not replay old native child'))
    try:
        reply = adapter.recover_acp_session(binding['session_id'], _ORIGINAL['terminal']['receipt'],
            initial_sequence=38, trace_tail=38)
        saved = json.loads(path.read_text())
        assert saved['sequence'] == 38
        assert saved['settlement_receipt'] == _ORIGINAL['terminal']['receipt']
        boundary = reply['recovery_boundary']
        assert boundary['binding_sequence'] == 38 and boundary['next_sequence'] == 39
        assert boundary['state'] == 'pending'
        ack = adapter.recover_acp_session(binding['session_id'], _ORIGINAL['terminal']['receipt'],
            initial_sequence=39, trace_tail=39, boundary_ack_sha256=boundary['event_sha256'])
        assert ack['recovery_boundary']['state'] == 'acknowledged'
        assert json.loads(path.read_text())['sequence'] == 39
    finally:
        adapter.close()
