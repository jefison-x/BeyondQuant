"""ADR-0016 CLI: logical, idempotent SQLite -> PostgreSQL domain migration.

Pipeline (repeatable and fail-safe):
  1. read-only SQLite export (never modifies the source file)
  2. validation + quarantine (invalid rows are reported, never silently repaired)
  3. deterministic manifest (row counts + fingerprints + source hash)
  4. idempotent PostgreSQL import with conflict policy
     (KEEP_NEW | VERIFY_EQUAL | REPORT_MISMATCH; never last-write-wins)
  5. post-import verification against the manifest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from sqlalchemy.engine import Engine

from . import db as db_module
from .agent_research import AgentResearchStore
from .backtest import BacktestJobStore
from .engineering import EngineeringTaskStore
from .learning_loop import LearningLoopStore
from .paper_trading import PaperTradingStore
from .product_feedback import ProductFeedbackStore
from .pg_import import KEEP_NEW, CONFLICT_POLICIES, adapt_export, import_to_pg, verify_import
from .research import ResearchStore
from .sqlite_export import build_manifest, export_sqlite, quarantine_rows
from .user_auth import UserAuthStore
from .user_policy import UserPolicyStore


ALL_SCHEMA_DDL: list[str] = [
    *UserAuthStore.SCHEMA_DDL,
    *ProductFeedbackStore.SCHEMA_DDL,
    *UserPolicyStore.SCHEMA_DDL,
    *PaperTradingStore.SCHEMA_DDL,
    *BacktestJobStore.SCHEMA_DDL,
    *AgentResearchStore.SCHEMA_DDL,
    *EngineeringTaskStore.SCHEMA_DDL,
    *LearningLoopStore.SCHEMA_DDL,
    *ResearchStore.SCHEMA_DDL,
]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bootstrap_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        db_module.run_ddl(connection, ALL_SCHEMA_DDL)


def migrate(
    sqlite_path: str | Path,
    engine: Engine,
    *,
    conflict_policy: str = KEEP_NEW,
    quarantine_path: str | None = None,
) -> dict[str, object]:
    """Run the full migration pipeline and return a JSON-serializable report."""
    sqlite_path = Path(sqlite_path).expanduser().resolve()
    export = export_sqlite(sqlite_path)
    separated = quarantine_rows(export)
    quarantined = separated["quarantined"]
    if quarantine_path:
        Path(quarantine_path).write_text(json.dumps(quarantined, ensure_ascii=False, indent=2))
    source_sha256 = _file_sha256(sqlite_path)
    adapted = adapt_export(separated["valid"])
    manifest = build_manifest(adapted, source_sha256=source_sha256)

    bootstrap_schema(engine)
    import_report = import_to_pg(engine, separated["valid"], conflict_policy=conflict_policy)
    checks = verify_import(engine, adapted, manifest)

    report: dict[str, object] = {
        "source": str(sqlite_path),
        "source_sha256": source_sha256,
        "conflict_policy": conflict_policy,
        "quarantined_tables": {table: len(rows) for table, rows in quarantined.items()},
        "quarantine_details": quarantined,
        "import": import_report,
        "verification": checks,
        "verified": all(check.get("ok") and check.get("fingerprint_matches") for check in checks.values()),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate BYQ domain data from SQLite to PostgreSQL (ADR-0016)")
    parser.add_argument("--sqlite-path", required=True, help="Read-only source SQLite database path")
    parser.add_argument("--database-url", default=None, help="Target BYQ_DATABASE_URL (defaults to env)")
    parser.add_argument("--conflict-policy", default=KEEP_NEW, choices=sorted(CONFLICT_POLICIES))
    parser.add_argument("--quarantine-path", default=None, help="Write quarantine details to this JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Export/validate/manifest only (no import)")
    arguments = parser.parse_args(argv)

    engine = db_module.create_db_engine(arguments.database_url)
    try:
        if arguments.dry_run:
            export = export_sqlite(arguments.sqlite_path)
            separated = quarantine_rows(export)
            source_sha256 = _file_sha256(Path(arguments.sqlite_path).expanduser().resolve())
            adapted = adapt_export(separated["valid"])
            manifest = build_manifest(adapted, source_sha256=source_sha256)
            print(json.dumps(
                {
                    "dry_run": True,
                    "source_sha256": source_sha256,
                    "quarantined_tables": {table: len(rows) for table, rows in separated["quarantined"].items()},
                    "manifest": manifest,
                },
                ensure_ascii=False,
                indent=2,
            ))
            return 0
        report = migrate(arguments.sqlite_path, engine, conflict_policy=arguments.conflict_policy, quarantine_path=arguments.quarantine_path)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["verified"] else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
