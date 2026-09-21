#!/usr/bin/env python3
"""Machine check: the H4 reliability ledger diff is digest-only.

Proves that a change to the fail-closed ledger
(``docs/evidence/research-handoff-h4/INTERFACE-REVIEW.json``) changed ONLY the
``source_sha256`` / ``dependencies_sha256`` values, with the entry identity
multiset, entry count and manual-surface identity set unchanged. Exits non-zero
otherwise, so an unrelated structural rewrite cannot hide behind "hash refresh".

Usage:
    python3 scripts/v090/business_recovery/check_ledger_diff.py --base origin/main
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LEDGER = "docs/evidence/research-handoff-h4/INTERFACE-REVIEW.json"


def _identity(entry: dict) -> tuple:
    return tuple(entry.get(key) for key in ("kind", "file", "method", "path", "handler", "name"))


def _strip_digests(value: dict) -> dict:
    stripped = json.loads(json.dumps(value))
    for entry in stripped.get("entries", []):
        entry.pop("source_sha256", None)
        entry.pop("dependencies_sha256", None)
    for surface in stripped.get("manual_surfaces", []):
        surface.pop("source_sha256", None)
        surface.pop("dependencies_sha256", None)
    return stripped


def check(base: str) -> dict:
    baseline = json.loads(subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{base}:{LEDGER}"],
        capture_output=True, text=True, check=True).stdout)
    current = json.loads((ROOT / LEDGER).read_text(encoding="utf-8"))
    base_ids = sorted(str(_identity(entry)) for entry in baseline.get("entries", []))
    cur_ids = sorted(str(_identity(entry)) for entry in current.get("entries", []))
    base_manual = [surface.get("name") for surface in baseline.get("manual_surfaces", [])]
    cur_manual = [surface.get("name") for surface in current.get("manual_surfaces", [])]
    result = {
        "schema_version": "byq-ledger-digest-diff.v1",
        "base": base,
        "entry_count_base": len(base_ids),
        "entry_count_current": len(cur_ids),
        "entry_count_unchanged": len(base_ids) == len(cur_ids),
        "entry_identity_multiset_unchanged": base_ids == cur_ids,
        "manual_surface_identity_unchanged": base_manual == cur_manual,
        "non_digest_content_identical": _strip_digests(baseline) == _strip_digests(current),
    }
    result["digest_only"] = all(value for key, value in result.items() if key.endswith("unchanged")
                                or key == "non_digest_content_identical")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    args = parser.parse_args(argv)
    result = check(args.base)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["digest_only"] else 1


if __name__ == "__main__":
    sys.exit(main())
