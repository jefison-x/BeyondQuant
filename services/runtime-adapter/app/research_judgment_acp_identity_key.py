"""Derive one DSH-held judgment MCP key from the Adapter's private master.

MCP verifies tokens with the same scoped derivation. This pure helper does not
prove its caller used the exact current Backend root receipt; the trusted ACP
entry must supply that receipt before launching DSH.
"""

from __future__ import annotations

import hashlib
import hmac
import re

_PREFIX = b"byq-acp-judgment-root-key-v1\n"
_FIELDS = (
    "task_id", "call_identity", "root_run_id", "runtime_boot_id",
    "owner_principal", "workspace_id", "session_id", "trace_id", "dsh_run_id",
)
_PATTERNS = {
    "task_id": re.compile(r"task_[0-9a-f]{32}\Z"),
    "call_identity": re.compile(r"byq-judgment-[0-9a-f]{32}\Z"),
    "root_run_id": re.compile(r"[0-9a-f]{32}\Z"),
    "runtime_boot_id": re.compile(r"[0-9a-f]{32}\Z"),
    "owner_principal": re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}\Z"),
    "workspace_id": re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z"),
    "session_id": re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z"),
    "trace_id": re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z"),
    "dsh_run_id": re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z"),
}


def derive_judgment_root_signing_key(master: str, scope: dict) -> str:
    if (not isinstance(master, str) or len(master.encode("utf-8")) < 32
            or not isinstance(scope, dict)):
        raise ValueError("private judgment MCP master and exact root scope required")
    values = []
    for field in _FIELDS:
        value = scope.get(field)
        if not isinstance(value, str) or _PATTERNS[field].fullmatch(value) is None:
            raise ValueError("exact judgment MCP root scope required")
        values.append(value)
    message = _PREFIX + "\n".join(values).encode("ascii")
    return hmac.new(master.encode("utf-8"), message, hashlib.sha256).hexdigest()
