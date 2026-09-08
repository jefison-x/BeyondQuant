"""Read-only verification of immutable release inputs in their exact Git trees.

This proves historical integrity, never current-image qualification. No fallback
to current files, moving refs, network fetch, or execution of historical code.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE_COMMITS = {
    "dsh-0.1.1rc1": "ce6493f006d9b857f38d81306bbccfcff1a8fbe4",
    "dsh-0.1.2rc1": "243f8ed6487301eae7a9062357d7060896fedf6f",
}


def read_blob(commit: str, path: str) -> bytes:
    relative = PurePosixPath(path)
    if (not re.fullmatch(r"[0-9a-f]{40}", commit) or not path
            or relative.is_absolute() or ".." in relative.parts
            or str(relative) != path or "\\" in path or "\x00" in path):
        raise ValueError("historical input must have exact commit and contained path")
    try:
        return subprocess.run(
            ["git", "--no-replace-objects", "cat-file", "blob", f"{commit}:{path}"],
            cwd=ROOT, check=True, capture_output=True, timeout=15,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"historical input unavailable: {path}") from exc


def verify(value: dict) -> str:
    release = value.get("release_id")
    if not isinstance(release, str) or release not in SOURCE_COMMITS:
        raise ValueError("unregistered historical release")
    commit = SOURCE_COMMITS[release]
    relative = f"config/dsh/releases/{release}.json"
    archived_bytes = read_blob(commit, relative)
    if (ROOT / relative).read_bytes() != archived_bytes or json.loads(archived_bytes) != value:
        raise ValueError("historical release descriptor changed")
    for path, expected in value["build_inputs"].items():
        actual = "sha256:" + hashlib.sha256(read_blob(commit, path)).hexdigest()
        if actual != expected:
            raise ValueError(f"historical build input drift: {path}")
    return commit
