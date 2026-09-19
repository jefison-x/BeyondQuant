#!/usr/bin/env python3
"""Explicit, audited runtime executor takeover (ADR-0079).

The runtime lifecycle-journal lease is bound to a stable deployment identity and
a monotonic ``executor_epoch``. Normal process restart, container restart and
host reboot never change the epoch. It changes ONLY through this explicit
operation, used for operator takeover, executor replacement or storage ownership
reassignment. Every increment writes a permanent audit record beside the
volume-owned epoch state.

Invariants:
  * Audit-first: without ``--apply`` nothing is mutated.
  * Explicit reason: ``--apply`` requires a specific ``--reason``.
  * Single winner: concurrent takeovers are serialized; the loser fails closed
    with ``ExecutorTakeoverBusy`` and never advances the epoch.
  * Fail closed: a missing/corrupt epoch record or a deployment-identity
    mismatch aborts; the epoch is never silently re-initialized.
  * Monotonic: the new epoch is strictly greater than the current volume epoch
    and any epoch recorded in a stable journal.
  * No domain mutation: no database row is written or deleted.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_ROOT / "services/runtime-adapter"))

from app import executor_identity  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="increment the executor epoch (default: audit only)")
    parser.add_argument("--reason", default=None,
                        help="required, specific reason for the takeover")
    parser.add_argument("--operator", default=None,
                        help="optional operator identity recorded in the audit")
    parser.add_argument("--session-root", type=Path,
                        default=Path(os.environ.get("DSH_SESSION_ROOT", "/var/lib/byq/dsh-sessions")))
    args = parser.parse_args(argv)

    session_root = args.session_root.expanduser().resolve()
    evidence_root = session_root / "byq-lifecycle-evidence"
    if not session_root.is_dir():
        parser.error(f"--session-root is not a directory: {session_root}")

    if args.apply and (not isinstance(args.reason, str) or len(args.reason.strip()) < 8):
        parser.error("--apply requires a specific --reason of at least 8 characters")

    try:
        state = executor_identity.read_epoch_state(evidence_root)
    except executor_identity.ExecutorIdentityError as exc:
        print(json.dumps({"error": str(exc), "database_rows_modified": False}))
        return 2

    if not args.apply:
        print(json.dumps({
            "mode": "audit",
            "session_root": str(session_root),
            "evidence_root": str(evidence_root),
            "executor_state": state,
            "database_rows_modified": False,
        }, indent=2, sort_keys=True))
        return 0

    try:
        result = executor_identity.takeover(
            evidence_root, reason=args.reason, operator=args.operator)
    except executor_identity.ExecutorTakeoverBusy as exc:
        print(json.dumps({"error": str(exc), "code": "executor_takeover_busy",
                          "database_rows_modified": False}))
        return 2
    except executor_identity.ExecutorIdentityError as exc:
        print(json.dumps({"error": str(exc), "database_rows_modified": False}))
        return 2
    print(json.dumps({"mode": "takeover", **result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
