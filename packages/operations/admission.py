"""Read-only deployment-controlled admission; no Product write/control API.

Every serving Gateway/Adapter must share the same local-filesystem inode.
Shared locks cover admission; the operator's exclusive lock closes the drain race.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat


class AdmissionClosed(RuntimeError):
    pass


def _acquire(path: str) -> int:
    descriptor = None
    try:
        target = Path(path)
        if not target.is_absolute() or target.resolve(strict=True) != target:
            raise ValueError("invalid gate path")
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("gate is not a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        if os.read(descriptor, 16) != b"open\n":
            raise ValueError("gate is closed or malformed")
        return descriptor
    except (OSError, ValueError) as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise AdmissionClosed("Chat is temporarily paused for maintenance; retry later.") from exc


@contextmanager
def chat_admission():
    configured = os.environ.get("BYQ_CHAT_ADMISSION_FILE", "")
    if not configured:
        yield
        return
    descriptor = _acquire(configured)
    try:
        yield
    finally:
        os.close(descriptor)
