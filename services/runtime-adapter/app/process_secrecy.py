"""Hide trusted ACP Adapter/HTTPS-worker process state from same-UID DSH.

The ordinary Product DSH child currently runs under the Adapter's UID. Its
trimmed environment alone cannot protect the Adapter's own environment or
open descriptors from /proc inspection. Fail startup if Linux cannot disable
same-UID ptrace-style inspection before a Product DSH process is launched.
"""

from __future__ import annotations

import ctypes
import os
import sys

_PR_SET_DUMPABLE = 4
_PR_GET_DUMPABLE = 3
_ACP_RELEASE = "dsh-v0.2.0-rc.2-acp"


def require_private_process() -> None:
    """Require the Linux dumpable flag to be zero for this process."""
    if sys.platform != "linux":
        raise RuntimeError("ACP private process requires Linux")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(_PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        raise RuntimeError("ACP private process cannot disable /proc inspection")
    if libc.prctl(_PR_GET_DUMPABLE, 0, 0, 0, 0) != 0:
        raise RuntimeError("ACP private process remains inspectable")


def guard_candidate_adapter_process() -> None:
    if os.environ.get("BYQ_DSH_COMPATIBILITY_RELEASE") == _ACP_RELEASE:
        require_private_process()
