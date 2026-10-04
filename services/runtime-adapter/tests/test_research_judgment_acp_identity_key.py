"""The DSH-held judgment MCP key must be unable to sign another root scope."""

from __future__ import annotations

import pytest

from app.research_judgment_acp_identity_key import derive_judgment_root_signing_key

MASTER = "synthetic-judgment-master-with-at-least-32-bytes"
SCOPE = {
    "task_id": "task_" + "a" * 32,
    "call_identity": "byq-judgment-" + "b" * 32,
    "root_run_id": "c" * 32,
    "runtime_boot_id": "d" * 32,
    "owner_principal": "alice",
    "workspace_id": "workspace_1",
    "session_id": "session_1",
    "trace_id": "trace_1",
    "dsh_run_id": "byqjudg-" + "e" * 32,
}


def test_judgment_key_is_deterministic_and_scope_specific():
    key = derive_judgment_root_signing_key(MASTER, SCOPE)
    assert key == "5e46d07590d6aa0b71601a29453c008eeb770c28230b2720cb70212fda1025d7"
    assert len(key) == 64
    assert key == key.lower()
    assert key == derive_judgment_root_signing_key(MASTER, dict(reversed(list(SCOPE.items()))))
    replacements = {
        "task_id": "task_" + "f" * 32,
        "call_identity": "byq-judgment-" + "f" * 32,
        "root_run_id": "f" * 32,
        "runtime_boot_id": "f" * 32,
        "owner_principal": "bob",
        "workspace_id": "workspace_2",
        "session_id": "session_2",
        "trace_id": "trace_2",
        "dsh_run_id": "byqjudg-" + "f" * 32,
    }
    for field, replacement in replacements.items():
        assert derive_judgment_root_signing_key(
            MASTER, {**SCOPE, field: replacement}) != key
    assert derive_judgment_root_signing_key(MASTER + "rotated", SCOPE) != key


@pytest.mark.parametrize("field,bad", [
    ("task_id", "task_other"), ("call_identity", "wrong"),
    ("root_run_id", "not-a-root"), ("owner_principal", "alice\nbob"),
    ("workspace_id", "with/slash"), ("session_id", ""), ("trace_id", "空"),
])
def test_judgment_key_rejects_noncanonical_scope(field, bad):
    with pytest.raises(ValueError, match="exact judgment"):
        derive_judgment_root_signing_key(MASTER, {**SCOPE, field: bad})
    with pytest.raises(ValueError):
        derive_judgment_root_signing_key(MASTER, {key: value for key, value in SCOPE.items()
                                                 if key != field})


def test_judgment_key_requires_private_master():
    with pytest.raises(ValueError, match="private judgment"):
        derive_judgment_root_signing_key("short", SCOPE)
