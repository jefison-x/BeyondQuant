"""Closed S3 single-snapshot planning; no provider calls or readiness claims."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .index_catalog import INDEX_WEIGHT_LOOKBACK_DAYS, SUPPORTED_INDEX_SYMBOLS


def index_snapshot_scope(
    index_symbol: object, requested_as_of: object, *, today: date | None = None,
) -> dict[str, object]:
    """Resolve an explicit date into a bounded, non-lookahead preparation scope.

    This does not certify cache coverage, schedule a download, or satisfy a
    historical-series request. Callers retain the existing data-demand authority.
    """
    if not isinstance(index_symbol, str) or index_symbol not in SUPPORTED_INDEX_SYMBOLS:
        raise ValueError("index snapshot preparation requires a canonical index")
    if not isinstance(requested_as_of, str) or not re.fullmatch(
        r"(?:[0-9]{8}|[0-9]{4}-[0-9]{2}-[0-9]{2})", requested_as_of,
    ):
        raise ValueError("requested_as_of must be an explicit YYYYMMDD or YYYY-MM-DD date")
    try:
        cutoff = date.fromisoformat(requested_as_of)
        start = cutoff - timedelta(days=INDEX_WEIGHT_LOOKBACK_DAYS - 1)
    except (ValueError, OverflowError) as error:
        raise ValueError("requested_as_of is invalid or outside the supported date range") from error
    current = today if today is not None else datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if cutoff > current:
        raise ValueError("requested_as_of must not be in the future")
    return {
        "kind": "index_snapshot", "index_symbol": index_symbol,
        "requested_as_of": cutoff.isoformat().replace("-", ""),
        "start_date": start.isoformat().replace("-", ""),
        "end_date": cutoff.isoformat().replace("-", ""),
        "datasets": ["index_weight"], "historical_series": False,
    }
