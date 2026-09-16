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


INDEX_SNAPSHOT_REQUIREMENT = 'index-snapshot-requirement.v1'


def index_snapshot_requirement(index_symbol, requested_as_of):
    """Closed single-point demand; explicitly distinct from historical series."""
    import hashlib
    import json
    scope = index_snapshot_scope(index_symbol, requested_as_of)
    first = datetime.strptime(scope['start_date'][:6] + '01', '%Y%m%d').date()
    last = datetime.strptime(scope['end_date'][:6] + '01', '%Y%m%d').date()
    periods = []
    while first <= last:
        periods.append(first.strftime('%Y%m'))
        first = first.replace(year=first.year + 1, month=1) if first.month == 12 else first.replace(month=first.month + 1)
    requirement = {'schema_version':INDEX_SNAPSHOT_REQUIREMENT, **scope,
                   'index_weight_periods':periods, 'declared':{'index_universe':index_symbol}}
    requirement['requirement_sha256'] = hashlib.sha256(json.dumps(requirement,
        sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    return scope, requirement


def assess_index_snapshot(store, requirement):
    from calendar import monthrange
    from .db import execute, fetch_one
    scope, expected = index_snapshot_requirement(requirement.get('index_symbol'), requirement.get('requested_as_of'))
    if requirement != expected:
        raise ValueError('index snapshot requirement does not match its frozen scope')
    missing = []
    with store._transaction() as connection:
        execute(connection, 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        for period in requirement['index_weight_periods']:
            end = period + str(monthrange(int(period[:4]), int(period[4:]))[1])
            through = min(end, scope['end_date'])
            if not store.has_verified_index_month(scope['index_symbol'], period,
                    through_date=through, _connection=connection):
                missing.append(period)
        snapshot = fetch_one(connection, '''SELECT snapshot_date,content_sha256,member_count
            FROM market_index_weight_snapshots WHERE index_symbol=:symbol AND status='verified'
            AND snapshot_date BETWEEN :start AND :end ORDER BY snapshot_date DESC LIMIT 1''',
            {'symbol':scope['index_symbol'], 'start':scope['start_date'], 'end':scope['end_date']})
    ready = not missing and snapshot is not None
    return {'schema_version':'index-snapshot-readiness.v1', 'state':'ready' if ready else 'missing',
        'kind':'index_snapshot', 'historical_series':False, 'requested_as_of':scope['requested_as_of'],
        'required_cell_count':1, 'missing_count':0 if ready else 1, 'missing_trade_dates':[],
        'missing_periods':missing, 'snapshot':snapshot if ready else None,
        'next_action':'create_historical_snapshot_pool' if ready else 'prepare_index_weights'}
