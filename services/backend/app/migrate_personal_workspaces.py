"""CLI for the ADR-0025 additive personal-workspace backfill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .workspace_tenancy import WorkspaceTenancyStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision and backfill BYQ personal workspaces")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--contract", action="store_true")
    parser.add_argument("--report-path", default=None)
    arguments = parser.parse_args(argv)
    store = WorkspaceTenancyStore(arguments.database_url)
    try:
        if arguments.contract and arguments.dry_run:
            parser.error("--contract and --dry-run are mutually exclusive")
        report = store.enforce_contract() if arguments.contract else store.backfill(dry_run=arguments.dry_run)
        rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        if arguments.report_path:
            Path(arguments.report_path).write_text(rendered + "\n")
        print(rendered)
        return 0 if report.get("verified", report.get("status") == "enforced") else 2
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
