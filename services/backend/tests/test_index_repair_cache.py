"""Only missing, unproven index months require provider repair."""
import os
import pytest
from app.data_provider import IndexWeight, IndexWeightResult, Provenance
from app.market_readiness import MarketReadinessStore
from app.market_automation import sync_declared_inputs

pytestmark = pytest.mark.skipif(not os.environ.get('BYQ_DATABASE_URL'), reason='isolated PostgreSQL required')


def weights(period):
    from calendar import monthrange
    date = period + str(monthrange(int(period[:4]), int(period[4:]))[1])
    return [IndexWeight('000300.SH','000001.SZ',date,60), IndexWeight('000300.SH','600000.SH',date,40)]


def provenance():
    return Provenance(provider='tushare',endpoint='index_weight',request_fingerprint='synthetic-cache',
        retrieved_at='2026-09-01T00:00:00+00:00',cache_hit=False,row_count=2)


class Provider:
    def __init__(self): self.calls = []
    def fetch_index_weights(self, symbol, start, end):
        self.calls.append((symbol,start,end))
        return IndexWeightResult(weights=tuple(weights(start[:6])),provenance=provenance())


def requirement():
    return {'declared':{'index_universe':'000300.SH'}, 'start_date':'20260701',
        'end_date':'20260831', 'index_weight_periods':['202607','202608']}


def test_repair_only_fetches_missing_month_and_restart_reuses_cache():
    store = MarketReadinessStore()
    store.import_index_weights('000300.SH','202607',weights('202607'),provenance().as_dict())
    provider = Provider()
    sync_declared_inputs(requirement(),provider=provider,readiness_store=store)
    assert provider.calls == [('000300.SH','20260801','20260831')]
    store.close()
    reopened = MarketReadinessStore()
    sync_declared_inputs(requirement(),provider=provider,readiness_store=reopened)
    assert len(provider.calls) == 1
    reopened.close()


@pytest.mark.parametrize('damage', ['weight','row_count','snapshot_hash','source','missing_snapshot'])
def test_unproven_cache_stops_before_download_or_overwrite(damage):
    store = MarketReadinessStore()
    store.import_index_weights('000300.SH','202607',weights('202607'),provenance().as_dict())
    changes = {
        'weight': "UPDATE market_index_weights SET weight=50 WHERE constituent_symbol='000001.SZ'",
        'row_count': "UPDATE market_index_weight_completeness SET row_count=row_count+1",
        'snapshot_hash': "UPDATE market_index_weight_snapshots SET content_sha256='corrupted'",
        'source': "UPDATE market_index_weight_completeness SET provenance_json=jsonb_set(provenance_json,'{provider}','\"unknown\"')",
        'missing_snapshot': "DELETE FROM market_index_weight_snapshots",
    }
    store._execute(changes[damage])
    provider = Provider()
    with pytest.raises(ValueError):
        sync_declared_inputs(requirement(),provider=provider,readiness_store=store)
    assert provider.calls == []
    store.close()


def test_in_month_retrieval_is_not_treated_as_complete_month():
    store = MarketReadinessStore()
    partial = {**provenance().as_dict(), 'retrieved_at':'2026-07-31T10:00:00+00:00'}
    store.import_index_weights('000300.SH','202607',weights('202607'),partial)
    provider = Provider()
    sync_declared_inputs(requirement(),provider=provider,readiness_store=store)
    assert provider.calls == [('000300.SH','20260701','20260731'), ('000300.SH','20260801','20260831')]
    store.close()
