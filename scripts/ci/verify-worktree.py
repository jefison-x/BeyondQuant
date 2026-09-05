#!/usr/bin/env python3
"""Host-side isolation check; never called by Product/Backend."""
import argparse
import os
from pathlib import Path
import subprocess


def verify(worktree: Path, root: Path) -> None:
    root = root.resolve(strict=True)
    worktree = worktree.resolve(strict=True)
    if not worktree.is_dir():
        raise ValueError("worktree directory required")
    if (root in (Path("/"), Path("/tmp"), Path("/var/tmp"), Path.home()) or len(root.parts) < 3
            or len(root.parts) == 3 and root.parts[1] == "home"):
        raise ValueError("dedicated worktree root required")
    if not worktree.is_relative_to(root) or worktree == root:
        raise ValueError("worktree escapes configured root")
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(worktree), *args], text=True).strip()
    if Path(git("rev-parse", "--show-toplevel")).resolve() != worktree:
        raise ValueError("not a worktree top-level")
    entries = git("worktree", "list", "--porcelain").split("\n\n")
    primary = Path(entries[0].splitlines()[0].removeprefix("worktree ")).resolve()
    if worktree == primary or root in (primary, primary.parent):
        raise ValueError("primary worktree forbidden")
    if primary.name in {"BeyondQuant-community", "BeyondQuant-legacy"}:
        raise ValueError("read-only reference repository forbidden")
    if not any(f"worktree {worktree}" in entry.splitlines() for entry in entries[1:]):
        raise ValueError("unregistered isolated worktree")
    branch = git("symbolic-ref", "--short", "HEAD")
    if branch in {"main", "master"}:
        raise ValueError("non-main feature branch required")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worktree", type=Path)
    args = parser.parse_args()
    verify(args.worktree, Path(os.environ.get("BYQ_ENGINEERING_WORKTREE_ROOT", "/home/jefison/projects/.byq-worktrees")))
    print("isolated worktree verified")
