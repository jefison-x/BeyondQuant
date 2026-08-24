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
    parser.add_argument("--report-path", default=None)
    arguments = parser.parse_args(argv)
    store = WorkspaceTenancyStore(arguments.database_url)
    try:
        report = store.backfill(dry_run=arguments.dry_run)
        rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        if arguments.report_path:
            Path(arguments.report_path).write_text(rendered + "\n")
        print(rendered)
        return 0 if report["verified"] else 2
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
