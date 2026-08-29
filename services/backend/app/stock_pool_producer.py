"""Trusted index/dynamic stock-pool materialization contracts (ADR-0041)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, execute, fetch_one
from .paper_trading import PaperTradingStore, _now


INDEX_PATTERN = re.compile(r"^\d{6}\.(SH|SZ)$")
DATE_PATTERN = re.compile(r"^\d{8}$")
INDEX_NAMES = {
    "000300.SH": "沪深300",
    "000905.SH": "中证500",
    "000852.SH": "中证1000",
    "000001.SH": "上证指数",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
}
class StockPoolProducerError(RuntimeError):
    pass


class StockPoolProducerNotFound(StockPoolProducerError):
    pass


class StockPoolProducerConflict(StockPoolProducerError):
    pass


class StockPoolProducerForbidden(StockPoolProducerError):
    pass


class StockPoolProducerPersistenceError(StockPoolProducerError):
    pass


def _text(value: object, field: str, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return normalized


def _index_symbol(value: object) -> str:
    symbol = _text(value, "index_symbol", 16).upper()
    if INDEX_PATTERN.fullmatch(symbol) is None:
        raise ValueError("index_symbol must be canonical NNNNNN.SH/SZ")
    return symbol


def _date(value: object, field: str = "requested_as_of") -> str:
    result = _text(value, field, 8)
    if DATE_PATTERN.fullmatch(result) is None:
        raise ValueError(f"{field} must be YYYYMMDD")
    datetime.strptime(result, "%Y%m%d")
    return result


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class StockPoolProducerStore(PgStoreMixin):
    """Definition/run store plus the trusted canonical index materializer."""

    SCHEMA_DDL = [
        """
        CREATE TABLE IF NOT EXISTS stock_pool_producer_definitions (
            definition_id TEXT PRIMARY KEY,
            pool_id TEXT NOT NULL UNIQUE REFERENCES stock_pools(pool_id),
            workspace_id TEXT NOT NULL,
            owner_principal TEXT NOT NULL,
            producer_kind TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            version INTEGER NOT NULL,
            definition_json JSONB NOT NULL,
            schedule_json JSONB NOT NULL,
            status TEXT NOT NULL,
            definition_fingerprint TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS stock_pool_producer_owner_idx
            ON stock_pool_producer_definitions(workspace_id, owner_principal, updated_at DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS stock_pool_materialization_runs (
            run_id TEXT PRIMARY KEY,
            definition_id TEXT NOT NULL REFERENCES stock_pool_producer_definitions(definition_id),
            definition_version INTEGER NOT NULL,
            pool_id TEXT NOT NULL REFERENCES stock_pools(pool_id),
            workspace_id TEXT NOT NULL,
            owner_principal TEXT NOT NULL,
            requested_as_of TEXT NOT NULL,
            effective_trade_date TEXT,
            trigger_identity TEXT NOT NULL,
            producer_id TEXT NOT NULL,
            producer_version TEXT NOT NULL,
            input_manifest_json JSONB,
            input_hash TEXT,
            status TEXT NOT NULL,
            attempt_count INTEGER NOT NULL,
            lease_owner TEXT,
            lease_expires_at TIMESTAMPTZ,
            member_count INTEGER,
            error_code TEXT,
            error_message TEXT,
            snapshot_id TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            UNIQUE(definition_id, definition_version, requested_as_of, trigger_identity)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS stock_pool_materialization_claim_idx
            ON stock_pool_materialization_runs(status, created_at)
        """,
        """
        CREATE TABLE IF NOT EXISTS stock_pool_producer_idempotency (
            workspace_id TEXT NOT NULL,
            owner_principal TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            pool_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY(workspace_id, owner_principal, idempotency_key)
        )
        """,
    ]

    def __init__(self, database_url: str | None = None, *, paper_store: PaperTradingStore | None = None) -> None:
        try:
            self.paper_store = paper_store or PaperTradingStore(database_url)
            self._owns_paper_store = paper_store is None
            super().__init__(database_url)
        except SQLAlchemyError as exc:
            raise StockPoolProducerPersistenceError("stock-pool producer storage is unavailable") from exc

    def close(self) -> None:
        if self._owns_paper_store:
            self.paper_store.close()
        super().close()

    def list_index_catalog(self, *, limit: int = 50, offset: int = 0) -> dict[str, object]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("offset must be non-negative")
        rows = self._execute(
            """WITH latest AS (
                   SELECT index_symbol, MAX(snapshot_date) AS latest_snapshot_date
                   FROM market_index_weights GROUP BY index_symbol
               )
               SELECT l.index_symbol, l.latest_snapshot_date,
                      COUNT(w.constituent_symbol)::integer AS member_count,
                      c.content_sha256 AS completeness_hash, c.verified_at
               FROM latest l
               JOIN market_index_weights w ON w.index_symbol=l.index_symbol
                    AND w.snapshot_date=l.latest_snapshot_date
               JOIN market_index_weight_completeness c ON c.index_symbol=l.index_symbol
                    AND c.period=substring(l.latest_snapshot_date,1,6) AND c.row_count>0
               GROUP BY l.index_symbol,l.latest_snapshot_date,c.content_sha256,c.verified_at
               ORDER BY l.index_symbol LIMIT :limit OFFSET :offset""",
            {"limit": limit, "offset": offset},
        )
        count = self._fetch_one(
            """SELECT COUNT(DISTINCT w.index_symbol) AS total FROM market_index_weights w
               JOIN market_index_weight_completeness c ON c.index_symbol=w.index_symbol
                    AND c.period=substring(w.snapshot_date,1,6) AND c.row_count>0"""
        )
        items = [{
            **row,
            "name": INDEX_NAMES.get(str(row["index_symbol"]), str(row["index_symbol"])),
            "source": "tushare",
            "dataset_contract": "market-index-weights-v1",
        } for row in rows]
        return {"indices": items, "total": int(count["total"] if count else 0), "limit": limit, "offset": offset}

    def create_index_pool(
        self, payload: object, *, trusted_owner: str, trusted_workspace: str,
    ) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("index pool request must be an object")
        unknown = set(payload) - {"name", "description", "index_symbol", "requested_as_of", "idempotency_key"}
        if unknown:
            raise ValueError(f"index pool request has unknown fields: {', '.join(sorted(unknown))}")
        owner = _text(trusted_owner, "owner_principal")
        workspace = _text(trusted_workspace, "workspace_id")
        symbol = _index_symbol(payload.get("index_symbol"))
        name = _text(payload.get("name") or INDEX_NAMES.get(symbol) or symbol, "name")
        description = payload.get("description")
        if description not in {None, ""}:
            description = _text(description, "description", 2000)
        else:
            description = None
        key = _text(payload.get("idempotency_key"), "idempotency_key")
        requested_as_of = _date(payload.get("requested_as_of") or datetime.now(timezone.utc).strftime("%Y%m%d"))
        request = {"name": name, "description": description, "index_symbol": symbol, "requested_as_of": requested_as_of}
        request_hash = _hash(request)
        definition = {
            "index_symbol": symbol,
            "dataset_contract": "market-index-weights-v1",
            "refresh_policy": "on_validated_import",
            "weight_mode": "provider_weight",
        }
        now = _now()
        with self._transaction() as connection:
            previous = fetch_one(connection, """SELECT * FROM stock_pool_producer_idempotency
                WHERE workspace_id=:workspace AND owner_principal=:owner AND idempotency_key=:key""",
                {"workspace": workspace, "owner": owner, "key": key})
            if previous:
                if previous["request_hash"] != request_hash:
                    raise StockPoolProducerConflict("idempotency key was already used with different input")
                pool = fetch_one(connection, "SELECT pool_id FROM stock_pools WHERE pool_id=:pool", {"pool": previous["pool_id"]})
                if pool is None:
                    raise StockPoolProducerConflict("idempotent pool result is unavailable")
                return {"pool": self.paper_store.get_pool(previous["pool_id"], trusted_owner=owner),
                        "run": self.get_run(previous["run_id"], trusted_owner=owner, trusted_workspace=workspace)}
            catalogue = fetch_one(connection, """SELECT MAX(w.snapshot_date) AS latest_snapshot_date
                FROM market_index_weights w JOIN market_index_weight_completeness c
                  ON c.index_symbol=w.index_symbol AND c.period=substring(w.snapshot_date,1,6) AND c.row_count>0
                WHERE w.index_symbol=:symbol AND w.snapshot_date<=:requested""",
                {"symbol": symbol, "requested": requested_as_of})
            if catalogue is None or not catalogue.get("latest_snapshot_date"):
                raise StockPoolProducerNotFound("no validated index weights exist at or before requested_as_of")
            pool_id = _new_id("stock_pool")
            definition_id = _new_id("stock_pool_definition")
            run_id = _new_id("stock_pool_run")
            execute(connection, """INSERT INTO stock_pools
                (pool_id,workspace_id,owner_principal,name,pool_type,description,weights_json,symbols_json,
                 version,provenance_json,created_at,updated_at,status,metadata_version)
                VALUES (:pool,:workspace,:owner,:name,'index',:description,:weights,:symbols,
                        'pending',:provenance,:now,:now,'active',1)""",
                {"pool": pool_id, "workspace": workspace, "owner": owner, "name": name,
                 "description": description, "weights": {}, "symbols": [],
                 "provenance": {"source": "index", "index_symbol": symbol}, "now": now})
            fingerprint = _hash(definition)
            execute(connection, """INSERT INTO stock_pool_producer_definitions
                (definition_id,pool_id,workspace_id,owner_principal,producer_kind,schema_version,version,
                 definition_json,schedule_json,status,definition_fingerprint,created_at,updated_at)
                VALUES (:definition,:pool,:workspace,:owner,'index','stock-pool-producer.v1',1,
                        :document,:schedule,'active',:fingerprint,:now,:now)""",
                {"definition": definition_id, "pool": pool_id, "workspace": workspace, "owner": owner,
                 "document": definition, "schedule": {"cadence": "on_validated_import"},
                 "fingerprint": fingerprint, "now": now})
            self._insert_run(connection, run_id=run_id, definition_id=definition_id, pool_id=pool_id,
                             workspace=workspace, owner=owner, requested_as_of=requested_as_of,
                             trigger_identity=f"create:{key}", now=now)
            execute(connection, """INSERT INTO stock_pool_producer_idempotency
                (workspace_id,owner_principal,idempotency_key,request_hash,pool_id,run_id,created_at)
                VALUES (:workspace,:owner,:key,:hash,:pool,:run,:now)""",
                {"workspace": workspace, "owner": owner, "key": key, "hash": request_hash,
                 "pool": pool_id, "run": run_id, "now": now})
        return {"pool": self.paper_store.get_pool(pool_id, trusted_owner=owner),
                "run": self.get_run(run_id, trusted_owner=owner, trusted_workspace=workspace)}

    def _insert_run(self, connection: Any, *, run_id: str, definition_id: str, pool_id: str,
                    workspace: str, owner: str, requested_as_of: str, trigger_identity: str, now: str) -> None:
        execute(connection, """INSERT INTO stock_pool_materialization_runs
            (run_id,definition_id,definition_version,pool_id,workspace_id,owner_principal,requested_as_of,
             trigger_identity,producer_id,producer_version,status,attempt_count,created_at)
            VALUES (:run,:definition,1,:pool,:workspace,:owner,:requested,:trigger,
                    'byq-index-materializer','1','queued',0,:now)""",
            {"run": run_id, "definition": definition_id, "pool": pool_id, "workspace": workspace,
             "owner": owner, "requested": requested_as_of, "trigger": trigger_identity, "now": now})

    def enqueue_index_refresh(self, pool_id: object, payload: object, *, trusted_owner: str,
                              trusted_workspace: str) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("refresh request must be an object")
        unknown = set(payload) - {"requested_as_of", "idempotency_key"}
        if unknown:
            raise ValueError(f"refresh request has unknown fields: {', '.join(sorted(unknown))}")
        owner, workspace = _text(trusted_owner, "owner_principal"), _text(trusted_workspace, "workspace_id")
        pool = _text(pool_id, "pool_id", 80)
        key = _text(payload.get("idempotency_key"), "idempotency_key")
        requested = _date(payload.get("requested_as_of") or datetime.now(timezone.utc).strftime("%Y%m%d"))
        with self._transaction() as connection:
            definition = fetch_one(connection, """SELECT * FROM stock_pool_producer_definitions
                WHERE pool_id=:pool AND owner_principal=:owner AND workspace_id=:workspace AND producer_kind='index'""",
                {"pool": pool, "owner": owner, "workspace": workspace})
            if definition is None:
                raise StockPoolProducerNotFound("index pool definition not found")
            existing = fetch_one(connection, """SELECT * FROM stock_pool_materialization_runs
                WHERE definition_id=:definition AND definition_version=:version
                  AND requested_as_of=:requested AND trigger_identity=:trigger""",
                {"definition": definition["definition_id"], "version": definition["version"],
                 "requested": requested, "trigger": f"manual:{key}"})
            if existing:
                return self._public_run(existing)
            run_id, now = _new_id("stock_pool_run"), _now()
            self._insert_run(connection, run_id=run_id, definition_id=definition["definition_id"],
                             pool_id=pool, workspace=workspace, owner=owner, requested_as_of=requested,
                             trigger_identity=f"manual:{key}", now=now)
        return self.get_run(run_id, trusted_owner=owner, trusted_workspace=workspace)

    def get_definition(self, pool_id: object, *, trusted_owner: str, trusted_workspace: str) -> dict[str, object]:
        row = self._fetch_one("""SELECT * FROM stock_pool_producer_definitions
            WHERE pool_id=:pool AND owner_principal=:owner AND workspace_id=:workspace""",
            {"pool": _text(pool_id, "pool_id", 80), "owner": trusted_owner, "workspace": trusted_workspace})
        if row is None:
            raise StockPoolProducerNotFound("stock pool producer definition not found")
        result = dict(row)
        result["definition"] = result.pop("definition_json")
        result["schedule"] = result.pop("schedule_json")
        result.pop("workspace_id", None)
        result.pop("owner_principal", None)
        return result

    def list_runs(self, pool_id: object, *, trusted_owner: str, trusted_workspace: str,
                  limit: int = 50, offset: int = 0) -> dict[str, object]:
        if limit < 1 or limit > 100 or offset < 0:
            raise ValueError("invalid pagination")
        pool = _text(pool_id, "pool_id", 80)
        definition = self.get_definition(pool, trusted_owner=trusted_owner, trusted_workspace=trusted_workspace)
        rows = self._execute("""SELECT * FROM stock_pool_materialization_runs
            WHERE definition_id=:definition ORDER BY created_at DESC,run_id DESC LIMIT :limit OFFSET :offset""",
            {"definition": definition["definition_id"], "limit": limit, "offset": offset})
        count = self._fetch_one("SELECT COUNT(*) AS total FROM stock_pool_materialization_runs WHERE definition_id=:definition",
                                {"definition": definition["definition_id"]})
        return {"runs": [self._public_run(row) for row in rows], "total": int(count["total"] if count else 0),
                "limit": limit, "offset": offset}

    def get_run(self, run_id: object, *, trusted_owner: str, trusted_workspace: str) -> dict[str, object]:
        row = self._fetch_one("""SELECT * FROM stock_pool_materialization_runs
            WHERE run_id=:run AND owner_principal=:owner AND workspace_id=:workspace""",
            {"run": _text(run_id, "run_id", 80), "owner": trusted_owner, "workspace": trusted_workspace})
        if row is None:
            raise StockPoolProducerNotFound("stock pool materialization run not found")
        return self._public_run(row)

    @staticmethod
    def _public_run(row: dict[str, Any]) -> dict[str, object]:
        result = dict(row)
        result["input_manifest"] = result.pop("input_manifest_json", None) or {}
        result.pop("lease_owner", None)
        result.pop("lease_expires_at", None)
        result.pop("workspace_id", None)
        result.pop("owner_principal", None)
        return result

    def recover_stale_runs(self) -> int:
        result = self._execute("""UPDATE stock_pool_materialization_runs
            SET status='queued',lease_owner=NULL,lease_expires_at=NULL,error_code='worker_restart',
                error_message='运行任务已在工作进程重启后恢复'
            WHERE status='running' AND lease_expires_at<now() RETURNING run_id""")
        return len(result)

    def claim_next_run(self, *, worker_id: str, lease_seconds: int = 60) -> dict[str, object] | None:
        worker = _text(worker_id, "worker_id")
        with self._transaction() as connection:
            row = fetch_one(connection, """SELECT * FROM stock_pool_materialization_runs
                WHERE status='queued' ORDER BY created_at,run_id FOR UPDATE SKIP LOCKED LIMIT 1""")
            if row is None:
                return None
            expires = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
            execute(connection, """UPDATE stock_pool_materialization_runs SET status='running',
                attempt_count=attempt_count+1,lease_owner=:worker,lease_expires_at=:expires,
                started_at=COALESCE(started_at,now()),error_code=NULL,error_message=NULL WHERE run_id=:run""",
                {"worker": worker, "expires": expires, "run": row["run_id"]})
            row.update({"status": "running", "attempt_count": int(row["attempt_count"]) + 1,
                        "lease_owner": worker, "lease_expires_at": expires})
            return row

    def materialize_claimed_index(self, run: dict[str, object], *, worker_id: str) -> dict[str, object]:
        if run.get("status") != "running" or run.get("lease_owner") != worker_id:
            raise StockPoolProducerForbidden("run is not leased to this worker")
        run_id = str(run["run_id"])
        try:
            with self._transaction() as connection:
                locked = fetch_one(connection, "SELECT * FROM stock_pool_materialization_runs WHERE run_id=:run FOR UPDATE",
                                   {"run": run_id})
                if locked is None or locked["status"] != "running" or locked["lease_owner"] != worker_id:
                    raise StockPoolProducerConflict("materialization lease was lost")
                definition = fetch_one(connection, "SELECT * FROM stock_pool_producer_definitions WHERE definition_id=:id",
                                       {"id": locked["definition_id"]})
                if definition is None or definition["producer_kind"] != "index":
                    raise StockPoolProducerNotFound("index producer definition not found")
                symbol = str(definition["definition_json"]["index_symbol"])
                latest = fetch_one(connection, """SELECT MAX(w.snapshot_date) AS snapshot_date
                    FROM market_index_weights w JOIN market_index_weight_completeness c
                      ON c.index_symbol=w.index_symbol AND c.period=substring(w.snapshot_date,1,6) AND c.row_count>0
                    WHERE w.index_symbol=:symbol AND w.snapshot_date<=:requested""",
                    {"symbol": symbol, "requested": locked["requested_as_of"]})
                if latest is None or not latest.get("snapshot_date"):
                    execute(connection, """UPDATE stock_pool_materialization_runs SET status='waiting_for_data',
                        error_code='index_weights_missing',error_message='请求日期前没有已验证的指数权重',
                        lease_owner=NULL,lease_expires_at=NULL,finished_at=now() WHERE run_id=:run""", {"run": run_id})
                    waiting = {**locked, "status": "waiting_for_data", "error_code": "index_weights_missing",
                               "error_message": "请求日期前没有已验证的指数权重", "lease_owner": None,
                               "lease_expires_at": None, "finished_at": _now()}
                    return self._public_run(waiting)
                snapshot_date = str(latest["snapshot_date"])
                completeness = fetch_one(connection, """SELECT * FROM market_index_weight_completeness
                    WHERE index_symbol=:symbol AND period=:period""", {"symbol": symbol, "period": snapshot_date[:6]})
                rows = execute(connection, """SELECT constituent_symbol,weight,data_source,content_sha256
                    FROM market_index_weights WHERE index_symbol=:symbol AND snapshot_date=:date
                    ORDER BY constituent_symbol""", {"symbol": symbol, "date": snapshot_date})
                if not rows or completeness is None:
                    raise ValueError("validated index snapshot is incomplete")
                weights = self._normalize_percent_weights(rows)
                input_manifest = {
                    "dataset_contract": "market-index-weights-v1", "index_symbol": symbol,
                    "effective_trade_date": snapshot_date, "completeness_hash": completeness["content_sha256"],
                    "row_hashes": [row["content_sha256"] for row in rows],
                }
                input_hash = _hash(input_manifest)
                provenance = {
                    "source": "index", "index_symbol": symbol, "provider": "tushare",
                    "dataset_id": str(completeness["content_sha256"]), "source_weight_unit": "percent",
                    "normalization_contract": "index-weight-percent-normalized-v1",
                    "ingestion_manifest": input_hash,
                }
                payload = {"symbols": [str(row["constituent_symbol"]) for row in rows], "weights": weights,
                           "definition": definition["definition_json"], "provenance": provenance,
                           "effective_trade_date": snapshot_date}
                snapshot_id = self.paper_store._insert_snapshot(connection, locked["pool_id"], "index", payload, provenance)
                snapshot = fetch_one(connection, "SELECT * FROM stock_pool_snapshots WHERE snapshot_id=:snapshot",
                                     {"snapshot": snapshot_id})
                pool = fetch_one(connection, "SELECT current_snapshot_id FROM stock_pools WHERE pool_id=:pool FOR UPDATE",
                                 {"pool": locked["pool_id"]})
                current = fetch_one(connection, "SELECT effective_trade_date FROM stock_pool_snapshots WHERE snapshot_id=:snapshot",
                                    {"snapshot": pool["current_snapshot_id"]}) if pool and pool.get("current_snapshot_id") else None
                if current is None or snapshot_date >= str(current.get("effective_trade_date") or ""):
                    execute(connection, """UPDATE stock_pools SET current_snapshot_id=:snapshot,version=:version,
                        updated_at=now(),symbols_json=:symbols,weights_json=:weights,provenance_json=:provenance
                        WHERE pool_id=:pool""", {"snapshot": snapshot_id, "version": f"v{snapshot['version_number']}",
                        "symbols": payload["symbols"], "weights": weights, "provenance": provenance, "pool": locked["pool_id"]})
                execute(connection, """UPDATE stock_pool_materialization_runs SET status='succeeded',
                    effective_trade_date=:date,input_manifest_json=:manifest,input_hash=:hash,
                    member_count=:count,snapshot_id=:snapshot,lease_owner=NULL,lease_expires_at=NULL,
                    finished_at=now() WHERE run_id=:run""", {"date": snapshot_date, "manifest": input_manifest,
                    "hash": input_hash, "count": len(rows), "snapshot": snapshot_id, "run": run_id})
            return self.get_run(run_id, trusted_owner=str(run["owner_principal"]), trusted_workspace=str(run["workspace_id"]))
        except StockPoolProducerError:
            raise
        except Exception as error:
            self._execute("""UPDATE stock_pool_materialization_runs SET status='failed',error_code=:code,
                error_message='指数股票池物化失败',lease_owner=NULL,lease_expires_at=NULL,finished_at=now()
                WHERE run_id=:run AND status='running'""", {"code": type(error).__name__, "run": run_id})
            return self.get_run(run_id, trusted_owner=str(run["owner_principal"]), trusted_workspace=str(run["workspace_id"]))

    @staticmethod
    def _normalize_percent_weights(rows: list[dict[str, Any]]) -> dict[str, str]:
        parsed: list[tuple[str, Decimal]] = []
        total = Decimal("0")
        for row in rows:
            try:
                value = Decimal(str(row["weight"]))
            except InvalidOperation as exc:
                raise ValueError("index weight is not decimal") from exc
            if not value.is_finite() or value <= 0 or value > 100:
                raise ValueError("index weight is outside percent range")
            parsed.append((str(row["constituent_symbol"]), value))
            total += value
        if total < Decimal("99") or total > Decimal("101"):
            raise ValueError("index percent weights do not form a complete snapshot")
        quantum = Decimal("0.000000000001")
        normalized: dict[str, str] = {}
        running = Decimal("0")
        for symbol, value in parsed[:-1]:
            fraction = (value / total).quantize(quantum)
            normalized[symbol] = format(fraction, "f")
            running += fraction
        last_symbol, _ = parsed[-1]
        normalized[last_symbol] = format((Decimal("1") - running).quantize(quantum), "f")
        return normalized
