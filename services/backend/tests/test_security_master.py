from __future__ import annotations

import hashlib
import json
import os

import pytest

from app.data_provider import Provenance, QuarantinedSecurityRecord, SecurityMasterResult, SecurityRecord
from app.security_master import SecurityMasterNotFound, SecurityMasterStore


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


def _record(
    symbol: str,
    name: str,
    *,
    status: str = "L",
    exchange: str | None = None,
    list_date: str = "19910403",
    delist_date: str | None = None,
) -> SecurityRecord:
    return SecurityRecord(
        symbol=symbol,
        local_symbol=symbol[:6],
        name=name,
        area="深圳" if symbol.endswith(".SZ") else "上海",
        industry="银行",
        market="主板",
        exchange=exchange or ("SZSE" if symbol.endswith(".SZ") else "SSE"),
        list_status=status,
        list_date=list_date,
        delist_date=delist_date,
        is_hs="N",
    )


def _result(records: tuple[SecurityRecord, ...], retrieved_at: str) -> SecurityMasterResult:
    ordered = tuple(sorted(records, key=lambda item: item.symbol))
    dataset_id = hashlib.sha256(json.dumps(
        [item.as_dict() for item in ordered],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()).hexdigest()
    return SecurityMasterResult(
        records=ordered,
        provenance=Provenance(
            provider="tushare",
            endpoint="stock_basic",
            request_fingerprint="fixture-request",
            retrieved_at=retrieved_at,
            cache_hit=False,
            row_count=len(ordered),
        ),
        dataset_id=dataset_id,
        statuses=("L", "P", "D"),
    )


def _result_with_quarantine(
    records: tuple[SecurityRecord, ...],
    quarantined: tuple[QuarantinedSecurityRecord, ...],
    retrieved_at: str,
) -> SecurityMasterResult:
    ordered = tuple(sorted(records, key=lambda item: item.symbol))
    ordered_quarantine = tuple(sorted(quarantined, key=lambda item: item.provider_symbol))
    dataset_id = hashlib.sha256(json.dumps(
        {
            "records": [item.as_dict() for item in ordered],
            "quarantined": [item.as_dict() for item in ordered_quarantine],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()).hexdigest()
    return SecurityMasterResult(
        records=ordered,
        provenance=Provenance(
            provider="tushare",
            endpoint="stock_basic",
            request_fingerprint="fixture-request-with-quarantine",
            retrieved_at=retrieved_at,
            cache_hit=False,
            row_count=len(ordered) + len(ordered_quarantine),
        ),
        dataset_id=dataset_id,
        statuses=("L", "P", "D"),
        quarantined=ordered_quarantine,
    )


class FakeProvider:
    def __init__(self, result: SecurityMasterResult) -> None:
        self.result = result
        self.requests = []

    def fetch_security_master(self, request):
        self.requests.append(request.normalized())
        return self.result


def test_atomic_security_master_sync_bootstraps_searchable_catalogue() -> None:
    store = SecurityMasterStore()
    result = _result((
        _record("000001.SZ", "平安银行"),
        _record("600000.SH", "浦发银行"),
        _record("600001.SH", "历史公司", status="D", delist_date="20200101"),
    ), "2026-08-24T01:00:00+00:00")
    provider = FakeProvider(result)

    job, created = store.create_sync_job({"idempotency_key": "security-master-1"}, actor="admin")
    assert created is True
    completed = store.run_sync_job(job["job_id"], provider_factory=lambda: provider)

    assert completed["status"] == "completed"
    assert completed["records_received"] == 3
    assert completed["records_imported"] == 3
    status = store.catalogue_status()
    assert status["total"] == 3
    assert status["status_counts"] == {"L": 2, "P": 0, "D": 1}
    page = store.list_securities(query="银行", statuses=("L",), exchanges=("SZSE",))
    assert page["total"] == 1
    assert page["securities"][0]["symbol"] == "000001.SZ"
    symbols, selection = store.resolve_symbols(statuses=("L",), exchanges=("SSE",))
    assert symbols == ["600000.SH"]
    assert selection["snapshot_id"] == completed["snapshot_id"]
    assert "requested_by" not in page["snapshot"]
    store.close()


def test_security_master_persists_bounded_quarantine_without_catalogue_pollution() -> None:
    store = SecurityMasterStore()
    result = _result_with_quarantine(
        (_record("600018.SH", "上港集团"),),
        (QuarantinedSecurityRecord(
            provider_symbol="T600018.SH",
            local_symbol="T600018",
            name="上港集箱(退)",
            exchange="SSE",
            list_status="D",
            list_date="20000719",
            delist_date="20061020",
        ),),
        "2026-08-25T01:00:00+00:00",
    )
    provider = FakeProvider(result)

    job, _ = store.create_sync_job({"idempotency_key": "security-master-quarantine"}, actor="admin")
    completed = store.run_sync_job(job["job_id"], provider_factory=lambda: provider)

    assert completed["status"] == "completed"
    assert completed["records_received"] == 2
    assert completed["records_imported"] == 1
    assert completed["records_quarantined"] == 1
    snapshot = store.get_snapshot(str(completed["snapshot_id"]))
    assert snapshot["row_count"] == 1
    assert snapshot["quarantined_count"] == 1
    assert store.catalogue_status()["total"] == 1
    quarantine = store._fetch_one(
        "SELECT provider_symbol, reason FROM security_master_snapshot_quarantine WHERE snapshot_id = :snapshot_id",
        {"snapshot_id": completed["snapshot_id"]},
    )
    assert quarantine == {"provider_symbol": "T600018.SH", "reason": "tushare_historical_alias"}
    store.close()


def test_security_master_sync_and_snapshot_import_are_idempotent() -> None:
    store = SecurityMasterStore()
    result = _result((_record("000001.SZ", "平安银行"),), "2026-08-24T01:00:00+00:00")
    provider = FakeProvider(result)
    first, _ = store.create_sync_job({"idempotency_key": "security-master-idempotent"}, actor="admin")
    completed = store.run_sync_job(first["job_id"], provider_factory=lambda: provider)

    replay, created = store.create_sync_job({"idempotency_key": "security-master-idempotent"}, actor="admin")
    assert created is False
    assert replay["job_id"] == completed["job_id"]
    snapshot, imported = store.import_result(result, actor="another-admin")
    assert imported is False
    assert snapshot["snapshot_id"] == completed["snapshot_id"]
    assert len(store.list_sync_jobs()) == 1
    store.close()


def test_latest_snapshot_changes_catalogue_without_destroying_history() -> None:
    store = SecurityMasterStore()
    first, created = store.import_result(
        _result((_record("000001.SZ", "旧名称"),), "2026-08-24T01:00:00+00:00"),
        actor="admin",
    )
    assert created is True
    second, created = store.import_result(
        _result((_record("000001.SZ", "新名称"), _record("600000.SH", "浦发银行")), "2026-08-24T02:00:00+00:00"),
        actor="admin",
    )
    assert created is True
    assert first["snapshot_id"] != second["snapshot_id"]
    assert store.list_securities(query="旧名称")["total"] == 0
    assert store.list_securities(query="新名称")["total"] == 1
    historical = store._fetch_one(
        "SELECT name FROM security_master_snapshot_members WHERE snapshot_id = :snapshot_id AND symbol = '000001.SZ'",
        {"snapshot_id": first["snapshot_id"]},
    )
    assert historical == {"name": "旧名称"}
    store.close()


def test_current_catalogue_drops_absent_rows_while_snapshot_history_remains() -> None:
    store = SecurityMasterStore()
    first, _ = store.import_result(
        _result((
            _record("000001.SZ", "平安银行"),
            _record("600000.SH", "浦发银行"),
        ), "2026-08-24T01:00:00+00:00"),
        actor="admin",
    )
    store.import_result(
        _result((_record("000001.SZ", "平安银行"),), "2026-08-24T02:00:00+00:00"),
        actor="admin",
    )

    assert store._fetch_one("SELECT COUNT(*) AS count FROM market_securities") == {"count": 1}
    historical = store._fetch_one(
        """SELECT COUNT(*) AS count FROM security_master_snapshot_members
           WHERE snapshot_id = :snapshot_id""",
        {"snapshot_id": first["snapshot_id"]},
    )
    assert historical == {"count": 2}
    store.close()


def test_catalogue_is_empty_before_first_complete_snapshot() -> None:
    store = SecurityMasterStore()
    assert store.catalogue_status()["quality"] == "empty"
    assert store.list_securities()["securities"] == []
    with pytest.raises(SecurityMasterNotFound, match="has not been synchronized"):
        store.resolve_symbols()
    store.close()
