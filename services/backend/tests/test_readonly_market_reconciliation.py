"""ADR-0117 exact scope and independent cleanup trust checks (synthetic keys)."""
import base64
import hashlib
import hmac

import pytest

from app import readonly_market_reconciliation as recovery
from packages.contracts.acp_product_slot import (
    PRODUCT_RUNNER_REPLY_HMAC_PREFIX, canonical_product_json, product_scope_digest,
)


def signed_result(envelope, cwd_leaf, key):
    scope = envelope['scope'] | {'cwd_leaf': cwd_leaf}
    cleanup = dict(schema_version='byq-acp-product-runner-cleanup.v1',
        **scope, scope_digest=product_scope_digest(scope), runner_instance_id='a' * 64,
        code=0, signal=None, reason='transport_lost', cleanup='proven')
    cleanup['mac'] = hmac.new(key, PRODUCT_RUNNER_REPLY_HMAC_PREFIX +
        canonical_product_json(cleanup), hashlib.sha256).hexdigest()
    raw = canonical_product_json(cleanup)
    return dict(status='supplemented', root_run_id=recovery.ROOT_ID,
        backend_snapshot_sha256=envelope['backend_snapshot_sha256'],
        native_root_session_id=envelope['native_root_session_id'], scope=scope,
        binding_sha256_before='b' * 64, binding_sha256_after='c' * 64,
        product_cleanup_receipt_sha256=hashlib.sha256(raw).hexdigest(),
        product_cleanup_scope_digest=cleanup['scope_digest'],
        product_cleanup_receipt_raw_b64=base64.b64encode(raw).decode())


@pytest.fixture
def proof(monkeypatch):
    key = b'synthetic-test-key-only-0000000000'
    monkeypatch.setenv('BYQ_ACP_PRODUCT_CONTROL_KEY_SHA256', hashlib.sha256(key).hexdigest())
    envelope = dict(schema_version=recovery.SCOPE_SCHEMA,
        scope=dict(owner_principal='admin', workspace_id=recovery.WORKSPACE_ID,
            root_run_id=recovery.ROOT_ID, runtime_boot_id=recovery.BOOT_ID,
            session_id=recovery.SESSION_ID, trace_id=recovery.TRACE_ID,
            generation_id=recovery.GENERATION_ID),
        native_root_session_id=recovery.NATIVE_ROOT_ID, backend_snapshot_sha256='d' * 64)
    return envelope, signed_result(envelope, 'session-' + 'e' * 32, key), key


def test_cleanup_requires_real_mac_and_trusted_key(proof, monkeypatch):
    envelope, result, key = proof
    assert recovery._validate_runtime_result(result, envelope=envelope, control_key=key)[0] == result['scope']
    monkeypatch.delenv('BYQ_ACP_PRODUCT_CONTROL_KEY_SHA256')
    with pytest.raises(recovery.ReadonlyReconciliationHold, match='trust anchor'):
        recovery._validate_runtime_result(result, envelope=envelope, control_key=key)


@pytest.mark.parametrize('field,value', [
    ('root_run_id', 'f' * 32), ('backend_snapshot_sha256', 'e' * 64),
    ('native_root_session_id', '11111111-1111-4111-8111-111111111111'),
    ('product_cleanup_receipt_sha256', '0' * 64),
    ('product_cleanup_receipt_raw_b64', 'e30='),
    ('product_cleanup_scope_digest', '0' * 64),
])
def test_changed_helper_result_is_rejected(proof, field, value):
    envelope, result, key = proof
    result[field] = value
    with pytest.raises(ValueError if field == 'scope' else recovery.ReadonlyReconciliationHold):
        recovery._validate_runtime_result(result, envelope=envelope, control_key=key)


def test_forged_cleanup_even_with_updated_digest_is_rejected(proof):
    envelope, result, key = proof
    raw = base64.b64decode(result['product_cleanup_receipt_raw_b64'])
    raw = raw.replace(b'"code":0', b'"code":1')
    result['product_cleanup_receipt_raw_b64'] = base64.b64encode(raw).decode()
    result['product_cleanup_receipt_sha256'] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(recovery.ReadonlyReconciliationHold, match='signed cleanup'):
        recovery._validate_runtime_result(result, envelope=envelope, control_key=key)


@pytest.mark.parametrize('arguments', [ {}, {'other': {'ts_code': '600036.SH'}},
    {recovery.REQUEST_ID: {'ts_code': '600036.SH', 'start_date': '20260101'}},
    {recovery.REQUEST_ID: {'ts_code': '000001.SZ'}}])
def test_only_original_daily_arguments_allowed(arguments):
    with pytest.raises(recovery.ReadonlyReconciliationHold):
        recovery._validate_arguments(arguments)


def test_ordinary_audit_cannot_create_recovery_proof():
    from app.agent_research import _reject_reserved_acp_control
    with pytest.raises(ValueError, match='reserved'):
        _reject_reserved_acp_control({'nested': {'acp_control': {'schema_version': recovery.SCHEMA}}})


def test_unrelated_root_cannot_read_or_create_recovery_proof():
    assert recovery.readonly_market_reconciliation_row(None, 'f' * 32) is None
    with pytest.raises(recovery.ReadonlyReconciliationHold):
        recovery.readonly_market_reconciliation_id('f' * 32)
