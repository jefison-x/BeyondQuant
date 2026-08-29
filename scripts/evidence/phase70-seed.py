#!/usr/bin/env python3
"""Seed six verified index snapshots for isolated Phase 70 Product evidence."""

from app.data_provider import IndexWeight
from app.index_catalog import SUPPORTED_INDEXES
from app.market_readiness import MarketReadinessStore


def main() -> None:
    store = MarketReadinessStore.from_env()
    try:
        for definition in SUPPORTED_INDEXES:
            symbol = definition["index_symbol"]
            store.import_index_weights(
                symbol,
                "202608",
                [
                    IndexWeight(symbol, "000001.SZ", "20260828", 60.0),
                    IndexWeight(symbol, "600000.SH", "20260828", 40.0),
                ],
                {
                    "purpose": "phase70_browser_evidence",
                    "provider": "tushare",
                    "endpoint": "index_weight",
                    "request_fingerprint": f"phase70-{symbol}",
                },
            )
    finally:
        store.close()
    print("Phase 70 verified index catalogue ready: 6 indices")


if __name__ == "__main__":
    main()
