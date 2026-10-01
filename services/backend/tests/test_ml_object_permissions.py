from pathlib import Path
import os
import stat

import pytest

from app.ml_object_permissions import prepare_ml_object_directories


def test_producer_preparation_preserves_existing_objects_and_setgid(tmp_path):
    root=tmp_path/'ml';namespace=root/'ml-models';namespace.mkdir(parents=True)
    blob=namespace/('a'*64);blob.write_bytes(b'existing immutable result');blob.chmod(0o640)
    prior=blob.stat()
    assert prepare_ml_object_directories(root)==root
    for directory in (root,root/'ml-features',namespace):
        row=directory.stat();assert stat.S_IMODE(row.st_mode)==0o2770
        assert row.st_uid==os.geteuid() and row.st_gid==os.getegid()
    assert blob.read_bytes()==b'existing immutable result'
    assert blob.stat().st_ino==prior.st_ino and blob.stat().st_mode==prior.st_mode


def test_symlink_namespace_is_rejected_without_changing_target_or_root(tmp_path):
    root=tmp_path/'ml';root.mkdir();target=tmp_path/'foreign';target.mkdir()
    (root/'ml-models').symlink_to(target,target_is_directory=True)
    previous=(root.stat().st_mode,target.stat().st_mode)
    with pytest.raises(ValueError,match='producer owner/group'):
        prepare_ml_object_directories(root)
    assert (root.stat().st_mode,target.stat().st_mode)==previous
    assert not (root/'ml-features').exists()
