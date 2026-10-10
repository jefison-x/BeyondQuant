from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from app.compat.dsh_acp import (
    AcpTransportError,
    _create_guard_patch_exclusive,
    retire_prepared_guard_patch,
)


ROOT = "a" * 32


def _home(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def _patch(home: Path, root: str = ROOT) -> bytes:
    value = [None, {"insert": [{"config": {
        "journalPath": str(home / f"product-turn-tool-guard-{root}.jsonl")
    }}]}]
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    _create_guard_patch_exclusive(home, payload)
    return payload


def _retire(home: Path, payload: bytes, root: str = ROOT) -> None:
    retire_prepared_guard_patch(
        home, expected_root_id=root, expected_sha256=hashlib.sha256(payload).hexdigest(),
    )


def _archive(home: Path, payload: bytes, root: str = ROOT) -> Path:
    digest = hashlib.sha256(payload).hexdigest()
    return home / f"continuation-guard.prepared-{root}-{digest}.patch.json"


def test_prepared_guard_retirement_archives_exact_bytes_and_is_retry_idempotent(tmp_path):
    home = _home(tmp_path / "private")
    payload = _patch(home)
    source = home / "continuation-guard.patch.json"
    _retire(home, payload)
    archive = _archive(home, payload)
    assert not source.exists()
    assert archive.read_bytes() == payload
    info = os.lstat(archive)
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert info.st_nlink == 1
    _retire(home, payload)
    assert archive.read_bytes() == payload


def test_prepared_guard_retirement_recovers_same_inode_link_unlink_window(tmp_path):
    home = _home(tmp_path / "private")
    payload = _patch(home)
    source = home / "continuation-guard.patch.json"
    archive = _archive(home, payload)
    os.link(source, archive, follow_symlinks=False)
    before_source, before_archive = os.lstat(source), os.lstat(archive)
    assert before_source.st_ino == before_archive.st_ino
    assert before_source.st_nlink == 2

    _retire(home, payload)

    assert not source.exists()
    after = os.lstat(archive)
    assert after.st_nlink == 1
    assert archive.read_bytes() == payload


@pytest.mark.parametrize("mutate", ["root", "digest"])
def test_prepared_guard_retirement_rejects_mismatched_identity(tmp_path, mutate):
    home = _home(tmp_path / "private")
    payload = _patch(home)
    source = home / "continuation-guard.patch.json"
    kwargs = {"expected_root_id": ROOT,
              "expected_sha256": hashlib.sha256(payload).hexdigest()}
    if mutate == "root":
        kwargs["expected_root_id"] = "b" * 32
    else:
        kwargs["expected_sha256"] = "0" * 64
    with pytest.raises(AcpTransportError):
        retire_prepared_guard_patch(home, **kwargs)
    assert source.read_bytes() == payload
    assert not _archive(home, payload).exists()


def test_prepared_guard_retirement_rejects_unexpected_hardlink(tmp_path):
    home = _home(tmp_path / "private")
    payload = _patch(home)
    source = home / "continuation-guard.patch.json"
    os.link(source, home / "unrelated-link", follow_symlinks=False)
    with pytest.raises(AcpTransportError):
        _retire(home, payload)
    assert source.exists()
    assert not _archive(home, payload).exists()


def test_prepared_guard_retirement_rejects_nonprivate_home_and_symlink(tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir(mode=0o755)
    loose.chmod(0o755)
    with pytest.raises(AcpTransportError):
        retire_prepared_guard_patch(
            loose, expected_root_id=ROOT, expected_sha256="0" * 64)

    private = _home(tmp_path / "private")
    target = _home(tmp_path / "target")
    (private / "continuation-guard.patch.json").symlink_to(
        target / "continuation-guard.patch.json")
    with pytest.raises(AcpTransportError):
        retire_prepared_guard_patch(
            private, expected_root_id=ROOT, expected_sha256="0" * 64)


# Reuse the established synthetic Product-slot compatibility fixture instead of
# creating a second runtime fake for the retry lifecycle.
def _slot_fixture_module():
    module_name = "_acp_prepared_guard_slot_fixture"
    spec = importlib.util.spec_from_file_location(
        module_name, Path(__file__).with_name("test_acp_product_slot_runtime.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def slot_runtime(monkeypatch, tmp_path):
    fixture_module = _slot_fixture_module()
    generator = fixture_module.slot_runtime.__wrapped__(monkeypatch, tmp_path)
    value = next(generator)
    try:
        yield value
    finally:
        try:
            next(generator)
        except StopIteration:
            pass


def test_group_admission_rejection_retires_guard_and_allows_retry(slot_runtime):
    runtime, compatibility, registry = slot_runtime
    fixture_module = sys.modules["_acp_prepared_guard_slot_fixture"]
    _SLOT_FIXTURE = fixture_module
    _SLOT_FIXTURE._create(runtime, "prepared-admission", "workspace_slot_a")
    record = runtime._get("prepared-admission")

    def reject(_record, _root):
        raise _SLOT_FIXTURE.SessionConflict("synthetic group admission rejection")

    runtime._require_group_admission = reject
    with pytest.raises(_SLOT_FIXTURE.SessionConflict, match="group admission rejection"):
        runtime.submit_prompt("prepared-admission", "first attempt", conversation_context=[])

    assert not record.cleanup_unconfirmed
    assert record.cleanup_harness is None
    assert not runtime._acp_binding_path(record.session_id, record.workspace_id).exists()
    assert compatibility.start_attempts == []
    assert "workspace_slot_a" not in registry._leases
    assert not (Path(record.recovery_cwd) / "continuation-guard.patch.json").exists()
    assert list(Path(record.recovery_cwd).glob("continuation-guard.prepared-*.patch.json"))

    runtime._require_group_admission = lambda _record, _root: None
    root, receipt = _SLOT_FIXTURE._run_to_idle(
        runtime, "prepared-admission", "retry after admission rejection")
    assert compatibility.successful_starts[-1].environment["BYQ_ROOT_RUN_ID"] == root
    runtime.acknowledge_terminal("prepared-admission", receipt)


def test_unknown_start_outcome_keeps_guard_and_fences_retry(slot_runtime, monkeypatch):
    runtime, compatibility, _registry = slot_runtime
    _SLOT_FIXTURE = sys.modules["_acp_prepared_guard_slot_fixture"]
    _SLOT_FIXTURE._create(runtime, "prepared-unknown-start", "workspace_slot_a")
    record = runtime._get("prepared-unknown-start")

    observed_binding = []

    def unknown_start(harness):
        binding_path = runtime._acp_binding_path(record.session_id, record.workspace_id)
        raw = binding_path.read_bytes()
        value = json.loads(raw)
        observed_binding.append((raw, value))
        harness.process = object()
        harness.slot_scope = {"root_run_id": harness.environment["BYQ_ROOT_RUN_ID"]}
        raise RuntimeError("synthetic unknown START outcome")

    monkeypatch.setattr(compatibility, "start", unknown_start)
    with pytest.raises(_SLOT_FIXTURE.SessionConflict, match="requires reconciliation"):
        runtime.submit_prompt("prepared-unknown-start", "may have started", conversation_context=[])

    home = Path(record.recovery_cwd)
    assert observed_binding
    before_start_raw, before_start = observed_binding[0]
    assert before_start["cleanup_unconfirmed"] is True
    assert before_start["root_run_id"] == record.process_root_id
    assert before_start["previous_authority_epoch"] == 7
    assert record.cleanup_unconfirmed
    assert record.cleanup_harness is record.harness
    binding_path = runtime._acp_binding_path(record.session_id, record.workspace_id)
    assert binding_path.read_bytes() == before_start_raw
    assert (home / "continuation-guard.patch.json").is_file()
    assert not list(home.glob("continuation-guard.prepared-*.patch.json"))
    with pytest.raises(_SLOT_FIXTURE.SessionConflict, match="cleanup is unconfirmed"):
        runtime.submit_prompt("prepared-unknown-start", "must not retry", conversation_context=[])


def test_repeated_credential_rejection_archives_each_guard_and_then_retries(slot_runtime):
    import time

    runtime, compatibility, _registry = slot_runtime
    _SLOT_FIXTURE = sys.modules["_acp_prepared_guard_slot_fixture"]
    _SLOT_FIXTURE._create(runtime, "prepared-credential", "workspace_slot_a")
    record = runtime._get("prepared-credential")
    record.model_resolution.pop("api_key")
    record.harness.environment.pop("OPENCODE_API_KEY", None)

    for _attempt in range(2):
        with pytest.raises(_SLOT_FIXTURE.SessionConflict, match="retry later"):
            runtime.submit_prompt("prepared-credential", "credential rejection", conversation_context=[])
        assert not record.cleanup_unconfirmed
        time.sleep(0.01)

    home = Path(record.recovery_cwd)
    archives = list(home.glob("continuation-guard.prepared-*.patch.json"))
    assert len(archives) == 2
    assert len({path.name for path in archives}) == 2
    assert not (home / "continuation-guard.patch.json").exists()
    assert len(compatibility.start_attempts) == 2

    record.model_resolution["api_key"] = "synthetic-provider-key"
    root, receipt = _SLOT_FIXTURE._run_to_idle(
        runtime, "prepared-credential", "retry after credentials restored")
    assert compatibility.successful_starts[-1].environment["BYQ_ROOT_RUN_ID"] == root
    runtime.acknowledge_terminal("prepared-credential", receipt)


def test_repeated_busy_rejection_archives_each_guard_then_retries(slot_runtime):
    import time

    runtime, compatibility, registry = slot_runtime
    _SLOT_FIXTURE = sys.modules["_acp_prepared_guard_slot_fixture"]
    _SLOT_FIXTURE._create(runtime, "prepared-busy-owner", "workspace_slot_a")
    _SLOT_FIXTURE._create(runtime, "prepared-busy-retry", "workspace_slot_a")
    _owner_root, owner_receipt = _SLOT_FIXTURE._run_to_idle(
        runtime, "prepared-busy-owner", "hold slot")
    record = runtime._get("prepared-busy-retry")

    for _attempt in range(2):
        with pytest.raises(_SLOT_FIXTURE.SessionConflict, match="slot is busy"):
            runtime.submit_prompt("prepared-busy-retry", "slot busy", conversation_context=[])
        assert not record.cleanup_unconfirmed
        time.sleep(0.01)

    home = Path(record.recovery_cwd)
    archives = list(home.glob("continuation-guard.prepared-*.patch.json"))
    assert len(archives) == 2
    assert len({path.name for path in archives}) == 2
    assert len(compatibility.start_attempts) == 3
    runtime.acknowledge_terminal("prepared-busy-owner", owner_receipt)
    assert "workspace_slot_a" not in registry._leases

    root, receipt = _SLOT_FIXTURE._run_to_idle(
        runtime, "prepared-busy-retry", "retry after slot release")
    assert compatibility.successful_starts[-1].environment["BYQ_ROOT_RUN_ID"] == root
    runtime.acknowledge_terminal("prepared-busy-retry", receipt)


def test_create_session_failure_after_start_retains_guard_and_fences(slot_runtime, monkeypatch):
    runtime, compatibility, _registry = slot_runtime
    _SLOT_FIXTURE = sys.modules["_acp_prepared_guard_slot_fixture"]
    _SLOT_FIXTURE._create(runtime, "prepared-create-unknown", "workspace_slot_a")
    record = runtime._get("prepared-create-unknown")

    def unknown_create_session(*_args, **_kwargs):
        raise RuntimeError("synthetic ACP create_session outcome unknown")

    monkeypatch.setattr(compatibility, "create_session", unknown_create_session)
    with pytest.raises(_SLOT_FIXTURE.SessionConflict, match="requires reconciliation"):
        runtime.submit_prompt("prepared-create-unknown", "may have created session", conversation_context=[])

    home = Path(record.recovery_cwd)
    assert compatibility.successful_starts
    assert record.cleanup_unconfirmed
    assert record.cleanup_harness is record.harness
    assert (home / "continuation-guard.patch.json").is_file()
    assert not list(home.glob("continuation-guard.prepared-*.patch.json"))


def test_guard_retirement_failure_fences_busy_retry(slot_runtime, monkeypatch):
    import app.compat.dsh_acp as dsh_acp_module

    runtime, _compatibility, _registry = slot_runtime
    _SLOT_FIXTURE = sys.modules["_acp_prepared_guard_slot_fixture"]
    _SLOT_FIXTURE._create(runtime, "prepared-retire-owner", "workspace_slot_a")
    _SLOT_FIXTURE._create(runtime, "prepared-retire-fail", "workspace_slot_a")
    _owner_root, _owner_receipt = _SLOT_FIXTURE._run_to_idle(
        runtime, "prepared-retire-owner", "hold slot")
    record = runtime._get("prepared-retire-fail")

    def fail_retirement(*_args, **_kwargs):
        raise dsh_acp_module.AcpTransportError("synthetic retirement anomaly")

    monkeypatch.setattr(dsh_acp_module, "retire_prepared_guard_patch", fail_retirement)
    with pytest.raises(_SLOT_FIXTURE.SessionConflict, match="requires reconciliation"):
        runtime.submit_prompt("prepared-retire-fail", "slot busy", conversation_context=[])
    home = Path(record.recovery_cwd)
    assert record.cleanup_unconfirmed
    assert (home / "continuation-guard.patch.json").is_file()
    with pytest.raises(_SLOT_FIXTURE.SessionConflict, match="cleanup is unconfirmed"):
        runtime.submit_prompt("prepared-retire-fail", "blocked", conversation_context=[])


def test_unqualified_route_rejection_before_guard_keeps_original_error(slot_runtime):
    runtime, compatibility, _registry = slot_runtime
    _SLOT_FIXTURE = sys.modules["_acp_prepared_guard_slot_fixture"]
    _SLOT_FIXTURE._create(runtime, "prepared-unqualified", "workspace_slot_a")
    record = runtime._get("prepared-unqualified")
    record.model_resolution["provider"] = "deepseek-official"
    record.model_resolution["model"] = "deepseek-v4-flash"

    import app.runtime as runtime_module

    with pytest.raises(runtime_module.ModelCredentialUnavailable, match="NOT_QUALIFIED"):
        runtime.submit_prompt("prepared-unqualified", "unqualified model", conversation_context=[])

    home = Path(record.recovery_cwd)
    assert not record.cleanup_unconfirmed
    assert compatibility.start_attempts == []
    assert not (home / "continuation-guard.patch.json").exists()
    assert not list(home.glob("continuation-guard.prepared-*.patch.json"))


def test_busy_exception_with_active_harness_state_is_not_treated_as_no_start(
    slot_runtime, monkeypatch,
):
    runtime, compatibility, _registry = slot_runtime
    _SLOT_FIXTURE = sys.modules["_acp_prepared_guard_slot_fixture"]
    _SLOT_FIXTURE._create(runtime, "prepared-busy-ambiguous", "workspace_slot_a")
    record = runtime._get("prepared-busy-ambiguous")

    def busy_with_active_state(harness):
        harness.process = object()
        harness.slot_scope = {"root_run_id": harness.environment["BYQ_ROOT_RUN_ID"]}
        raise _SLOT_FIXTURE.ProductSlotBusy("synthetic busy with active state")

    monkeypatch.setattr(compatibility, "start", busy_with_active_state)
    with pytest.raises(_SLOT_FIXTURE.SessionConflict, match="requires reconciliation"):
        runtime.submit_prompt("prepared-busy-ambiguous", "ambiguous busy", conversation_context=[])

    home = Path(record.recovery_cwd)
    assert record.cleanup_unconfirmed
    assert (home / "continuation-guard.patch.json").is_file()
    assert not list(home.glob("continuation-guard.prepared-*.patch.json"))


def test_changed_prestart_binding_is_never_removed(slot_runtime):
    runtime, _compatibility, _registry = slot_runtime
    _SLOT_FIXTURE = sys.modules["_acp_prepared_guard_slot_fixture"]
    _SLOT_FIXTURE._create(runtime, "prepared-binding-change", "workspace_slot_a")
    record = runtime._get("prepared-binding-change")
    record.authority_epoch = 7
    record.cleanup_harness = record.harness
    record.cleanup_unconfirmed = True
    digest = runtime._persist_acp_binding(record)
    assert isinstance(digest, str)

    path = runtime._acp_binding_path(record.session_id, record.workspace_id)
    value = json.loads(path.read_bytes())
    value["model_id"] = "changed-after-prestart"
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))

    with pytest.raises(_SLOT_FIXTURE.SessionConflict, match="changed"):
        runtime._remove_prestart_acp_binding(record, expected_sha256=digest)
    assert path.is_file()
    assert record.cleanup_unconfirmed


def test_prestart_binding_write_failure_never_starts_and_keeps_reconciliation_fence(
    slot_runtime, monkeypatch,
):
    runtime, compatibility, _registry = slot_runtime
    _SLOT_FIXTURE = sys.modules["_acp_prepared_guard_slot_fixture"]
    _SLOT_FIXTURE._create(runtime, "prepared-binding-write-failure", "workspace_slot_a")
    record = runtime._get("prepared-binding-write-failure")
    original_persist = runtime._persist_acp_binding
    calls = 0

    def fail_once(target_record):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _SLOT_FIXTURE.SessionConflict("synthetic prestart binding write failure")
        return original_persist(target_record)

    monkeypatch.setattr(runtime, "_persist_acp_binding", fail_once)
    with pytest.raises(_SLOT_FIXTURE.SessionConflict, match="requires reconciliation"):
        runtime.submit_prompt("prepared-binding-write-failure", "do not start", conversation_context=[])

    home = Path(record.recovery_cwd)
    assert calls == 1
    assert compatibility.start_attempts == []
    assert record.cleanup_unconfirmed
    assert record.cleanup_harness is record.harness
    assert record.continuation_request_proxy is None
    assert not runtime._acp_binding_path(record.session_id, record.workspace_id).exists()
    assert not (home / "continuation-guard.patch.json").exists()
    assert list(home.glob("continuation-guard.prepared-*.patch.json"))


def test_changed_binding_during_real_no_start_path_is_preserved_and_fenced(
    slot_runtime,
):
    runtime, compatibility, _registry = slot_runtime
    _SLOT_FIXTURE = sys.modules["_acp_prepared_guard_slot_fixture"]
    _SLOT_FIXTURE._create(runtime, "prepared-binding-race", "workspace_slot_a")
    record = runtime._get("prepared-binding-race")
    path = runtime._acp_binding_path(record.session_id, record.workspace_id)
    changed_bytes = []

    def change_binding_then_reject(_record, _root):
        value = json.loads(path.read_bytes())
        value["model_id"] = "foreign-binding-must-survive"
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        path.write_bytes(raw)
        changed_bytes.append(raw)
        raise _SLOT_FIXTURE.SessionConflict("synthetic group admission rejection")

    runtime._require_group_admission = change_binding_then_reject
    with pytest.raises(_SLOT_FIXTURE.SessionConflict, match="requires reconciliation"):
        runtime.submit_prompt("prepared-binding-race", "no start", conversation_context=[])

    assert changed_bytes
    assert path.read_bytes() == changed_bytes[0]
    assert record.cleanup_unconfirmed
    assert record.cleanup_harness is record.harness
    assert compatibility.start_attempts == []
    with pytest.raises(_SLOT_FIXTURE.SessionConflict, match="cleanup is unconfirmed"):
        runtime.submit_prompt("prepared-binding-race", "must not retry", conversation_context=[])
