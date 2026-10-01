"""ML producer-owned CAS directories shared with Backend expiry (ADR-0091)."""
from __future__ import annotations

import os
from pathlib import Path
import stat


def prepare_ml_object_directories(root: str | Path) -> Path:
    """Producer only: prepare exactly three directories, never files or chown.

    Backend joins the producer GID as a supplementary group. Files keep the
    existing CAS 0640 mode; setgid directories preserve that GID for new blobs.
    Refuse symlinks/foreign owners before changing any existing directory.
    """
    root = Path(root).expanduser().absolute()
    root.mkdir(parents=True, exist_ok=True)
    directories = [root, root / "ml-features", root / "ml-models"]
    for directory in directories:
        if directory.exists() or directory.is_symlink():
            row = directory.lstat()
            if not stat.S_ISDIR(row.st_mode) or row.st_uid != os.geteuid() or row.st_gid != os.getegid():
                raise ValueError("ML CAS directory requires the producer owner/group")
    for directory in directories:
        directory.mkdir(mode=0o2770, exist_ok=True)
        directory.chmod(0o2770)
    return root
