#!/usr/bin/env python3
"""Build the final 0.9 development closeout provenance record.

For every source artifact named in the final-closeout contract, record the
current file sha256 plus the commit that introduced the file in Git history.
The observer re-verifies the sha256 at assessment time, so a later edit to any
reused evidence (the audit ledger/matrix, the F2 slice evidence, the
full-interface audit snapshot, the composite regression verdict/matrix, the ADR
decision record, the D15 superseding evidence and the repository default
configuration) invalidates the closeout instead of being silently accepted.

This script writes create-only: it refuses to overwrite an existing provenance
record (use a new versioned filename instead).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_CONTRACT = HERE / "contract.v1.json"


def _git(path: str) -> tuple[str, str]:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H%x09%cs", "--", path],
        cwd=ROOT, check=True, capture_output=True, text=True)
    commit, _, date = result.stdout.strip().partition("\t")
    if not commit:
        return "uncommitted", "unknown"
    return commit, date


def _modified_in_worktree(path: str) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", path],
        cwd=ROOT, check=True, capture_output=True, text=True)
    return bool(result.stdout.strip())


def build(contract_path: Path) -> dict:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()
    artifacts = []
    for artifact in contract["source_artifacts"]:
        path = ROOT / artifact["path"]
        if not path.is_file():
            raise SystemExit(f"missing source artifact: {artifact['path']}")
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        commit, date = _git(artifact["path"])
        artifacts.append({
            "id": artifact["id"],
            "kind": artifact.get("kind", "json"),
            "stage": artifact["stage"],
            "layer": artifact["layer"],
            "path": artifact["path"],
            "sha256": digest,
            "introduced_by": commit,
            "introduced_date": date,
            "modified_in_closeout_commit": _modified_in_worktree(artifact["path"]),
        })
    return {
        "schema_version": "byq-v090-final-closeout-provenance.v1",
        "generated_at": "2026-09-22",
        "generated_from_head": head,
        "note": ("Source evidence reused by the final 0.9 development closeout. "
                 "introduced_by is the last commit that touched the path; "
                 "modified_in_closeout_commit marks paths changed by the closeout "
                 "commit itself. The historical D15-4/D15-5/D15-G verdicts are "
                 "referenced through the D15 superseding evidence and are never "
                 "rewritten."),
        "artifacts": artifacts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        print(f"refusing to overwrite existing provenance: {args.out}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(build(args.contract), indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
