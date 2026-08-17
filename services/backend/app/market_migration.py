"""ADR-0013 logical Community market-data migration pipeline.

Accepts a bounded read-only audit snapshot (rows from a read-only Community
``SELECT``/``COPY OUT``), validates it with the dry-run contract
(``migration.dry_run_market_data_migration``), imports the accepted rows into
the BYQ durable target (``MarketDataStore``) with the ADR-0016 conflict policy
(never last-write-wins), and verifies counts + content fingerprints.

Community PostgreSQL is never connected to or mounted; it is read-only
evidence. BaoStock/AKShare/VectorBT rows are rejected by the dry-run contract
(only ``data_source = tushare`` is accepted).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import Engine

from .db import transaction, execute, fetch_one
from .market_data import MarketDataStore
from .migration import dry_run_market_data_migration
from .pg_import import KEEP_NEW


def migrate_market_data(
    engine: Engine,
    rows: list[dict[str, Any]],
    *,
    source_repository: str,
    source_table: str,
    source_filter: str,
    target_dataset: str,
    conflict_policy: str = KEEP_NEW,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the ADR-0013 pipeline and return a JSON-serializable report."""
    dry = dry_run_market_data_migration(
        rows,
        source_repository=source_repository,
        source_table=source_table,
        source_filter=source_filter,
        target_dataset=target_dataset,
    )
    accepted = dry["accepted"]
    manifest = dry["manifest"]
    provenance = provenance or {
        "source_repository": source_repository,
        "source_table": source_table,
        "source_filter": source_filter,
        "target_dataset": target_dataset,
        "migration_id": manifest["migration_id"],
    }

    # Bootstrap the durable target schema, then import.
    store = MarketDataStore(engine.url.render_as_string(hide_password=False))
    try:
        store.bootstrap_schema()
        import_report = store.import_bars(accepted, conflict_policy=conflict_policy)

        # Post-import verification: per (symbol, trade_date) content hashes.
        verified = True
        checks: dict[str, Any] = {}
        with transaction(engine) as connection:
            for row in accepted:
                symbol = row["symbol"]
                trade_date = row["trade_date"]
                stored = fetch_one(
                    connection,
                    "SELECT content_sha256 FROM market_daily_bars WHERE symbol = :symbol AND trade_date = :trade_date",
                    {"symbol": symbol, "trade_date": trade_date},
                )
                expected = store._content_sha256(row)
                ok = stored is not None and stored["content_sha256"] == expected
                verified = verified and ok
                checks[f"{symbol}:{trade_date}"] = {"ok": ok, "fingerprint_matches": ok}
        return {
            "manifest": manifest,
            "import": import_report,
            "quarantine": dry["quarantine"],
            "verification": {"all_ok": verified, "checks": checks},
            "verified": verified,
        }
    finally:
        store.close()


def migrate_market_data_from_snapshot(
    engine: Engine,
    snapshot: dict[str, Any],
    *,
    conflict_policy: str = KEEP_NEW,
) -> dict[str, Any]:
    """Convenience entry: accept a full audit-snapshot envelope with metadata.

    ``snapshot`` shape: ``{"rows": [...], "source_repository", "source_table",
    "source_filter", "target_dataset"}``.
    """
    for key in ("rows", "source_repository", "source_table", "source_filter", "target_dataset"):
        if key not in snapshot:
            raise ValueError(f"snapshot is missing required field {key}")
    return migrate_market_data(
        engine,
        snapshot["rows"],
        source_repository=snapshot["source_repository"],
        source_table=snapshot["source_table"],
        source_filter=snapshot["source_filter"],
        target_dataset=snapshot["target_dataset"],
        conflict_policy=conflict_policy,
    )
