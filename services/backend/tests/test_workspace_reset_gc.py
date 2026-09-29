"""Focused filesystem tests for offline workspace reset object GC."""

from __future__ import annotations

import hashlib

import pytest

from app.workspace_reset_gc import WorkspaceResetGcError, collect_unreferenced_objects


def _put(root, namespace: str, payload: bytes) -> tuple[str, object]:
    object_id = hashlib.sha256(payload).hexdigest()
    path = root / namespace / object_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return object_id, path


def _reference(namespace: str, object_id: str, payload: bytes) -> dict[str, object]:
    return {
        "namespace": namespace,
        "object_id": object_id,
        "sha256": object_id,
        "size": len(payload),
        "media_type": "application/octet-stream",
    }


def test_gc_removes_only_unreferenced_known_cas_objects(tmp_path) -> None:
    domain_root = tmp_path / "domain" / "backtest-objects"
    ml_root = tmp_path / "ml-objects"
    live_id, live_path = _put(domain_root, "backtest-results", b"retained result")
    orphan_id, orphan_path = _put(domain_root, "backtest-results", b"orphan result")
    feature_id, feature_path = _put(ml_root, "ml-features", b"feature snapshot")
    _, model_path = _put(ml_root, "ml-models", b"model artifact")
    unknown_dir = domain_root / "unknown-namespace"
    unknown_dir.mkdir(parents=True)
    (unknown_dir / orphan_id).write_bytes(b"must remain")
    (domain_root / "backtest-results" / ".byq-temporary").write_bytes(b"must remain")
    symlink = domain_root / "backtest-results" / hashlib.sha256(b"symlink").hexdigest()
    symlink.symlink_to(live_path)

    report = collect_unreferenced_objects(
        [_reference("backtest-results", live_id, b"retained result"),
         _reference("ml-features", feature_id, b"feature snapshot"),
         _reference("ml-models", hashlib.sha256(b"model artifact").hexdigest(), b"model artifact")],
        backtest_object_root=domain_root,
        ml_object_root=ml_root,
    )

    assert report["deleted_objects"] == 1
    assert report["deleted_bytes"] == len(b"orphan result")
    assert live_path.is_file()
    assert not orphan_path.exists()
    assert feature_path.is_file()
    assert model_path.is_file()
    assert (unknown_dir / orphan_id).is_file()
    assert (domain_root / "backtest-results" / ".byq-temporary").is_file()
    assert symlink.is_symlink()


@pytest.mark.parametrize("invalid_field", ["sha256", "namespace"])
def test_unknown_or_malformed_live_reference_fails_before_any_deletion(
    tmp_path, invalid_field: str,
) -> None:
    domain_root = tmp_path / "domain" / "backtest-objects"
    orphan_id, orphan_path = _put(domain_root, "backtest-results", b"orphan result")
    malformed = _reference("backtest-results", orphan_id, b"orphan result")
    malformed[invalid_field] = (
        "new-namespace" if invalid_field == "namespace" else ("f" * 64 if orphan_id != "f" * 64 else "e" * 64)
    )

    with pytest.raises(WorkspaceResetGcError, match="unknown or malformed"):
        collect_unreferenced_objects(
            [malformed],
            backtest_object_root=domain_root,
            ml_object_root=tmp_path / "ml-objects",
        )

    assert orphan_path.is_file()


def test_gc_retry_is_idempotent_after_objects_are_removed(tmp_path) -> None:
    ml_root = tmp_path / "ml-objects"
    orphan_id, orphan_path = _put(ml_root, "ml-features", b"orphan features")
    args = {
        "references": [],
        "backtest_object_root": tmp_path / "domain" / "backtest-objects",
        "ml_object_root": ml_root,
    }

    first = collect_unreferenced_objects(**args)
    second = collect_unreferenced_objects(**args)

    assert first["deleted_objects"] == 1
    assert second["deleted_objects"] == 0
    assert not orphan_path.exists()
