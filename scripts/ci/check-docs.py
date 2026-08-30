#!/usr/bin/env python3
"""Fast, dependency-free checks for changed Markdown documents."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def changed_markdown(base: str) -> list[Path]:
    compare_target = "HEAD" if os.environ.get("GITHUB_ACTIONS") == "true" else None
    command = ["git", "diff", "--name-only", "--diff-filter=ACMR", base]
    if compare_target:
        command.append(compare_target)
    command.extend(["--", "*.md"])
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = {line for line in result.stdout.splitlines() if line}
    if compare_target is None:
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "--", "*.md"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        paths.update(line for line in untracked.stdout.splitlines() if line)
    return [ROOT / line for line in sorted(paths)]


def link_target(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<") and ">" in raw:
        return raw[1 : raw.index(">")]
    return raw.split(maxsplit=1)[0]


def check_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        contents = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return [f"{path.relative_to(ROOT)}: invalid UTF-8: {exc}"]
    relative = path.relative_to(ROOT)
    if contents and not contents.endswith("\n"):
        errors.append(f"{relative}: missing final newline")
    for match in LINK.finditer(contents):
        target = unquote(link_target(match.group(1)))
        if not target or target.startswith(("#", "http://", "https://", "mailto:", "data:")):
            continue
        target = target.split("#", 1)[0]
        if not target or any(token in target for token in ("${", "{{", "*")):
            continue
        resolved = (ROOT / target.lstrip("/")) if target.startswith("/") else (path.parent / target)
        if not resolved.resolve().exists():
            line = contents.count("\n", 0, match.start()) + 1
            errors.append(f"{relative}:{line}: missing local link target: {target}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    paths = changed_markdown(args.base)
    errors = [error for path in paths for error in check_file(path)]
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"docs check passed: {len(paths)} changed Markdown file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
