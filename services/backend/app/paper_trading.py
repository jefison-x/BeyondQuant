"""BYQ-owned simulation-only Paper Trading and Stock Pool contracts (ADR-0016 PG)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, ensure_column, execute, fetch_one


SYMBOL_PATTERN = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
TRADE_DATE_PATTERN = re.compile(r"^\d{8}$")
LOT_SIZE = 100
WEIGHT_QUANTUM = Decimal("0.000000000001")
WEIGHT_TOLERANCE = Decimal("0.00000001")


class PaperTradingError(RuntimeError):
    pass


class PaperTradingNotFound(PaperTradingError):
    pass


class PaperTradingConflict(PaperTradingError):
    pass


class PaperTradingForbidden(PaperTradingError):
    pass


class PaperTradingPersistenceError(PaperTradingError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object, *, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _principal(value: object, *, field: str) -> str:
    return _text(value, field=field, max_length=128)


def _id(value: object, *, prefix: str) -> str:
    normalized = _text(value, field="id", max_length=64)
    if normalized.startswith(f"{prefix}_") and re.fullmatch(rf"{prefix}_[0-9a-f]{{32}}", normalized):
        return normalized
    raise ValueError("id is invalid")


def _idempotency(value: object) -> str:
    return _text(value, field="idempotency_key", max_length=128)


def _symbol(value: object) -> str:
    normalized = _text(value, field="symbol", max_length=16)
    if SYMBOL_PATTERN.fullmatch(normalized) is None:
        raise ValueError("symbol must be canonical NNNNNN.SH/SZ/BJ")
    return normalized


def _trade_date(value: object) -> str:
    normalized = _text(value, field="trade_date", max_length=8)
    if TRADE_DATE_PATTERN.fullmatch(normalized) is None:
        raise ValueError("trade_date must be YYYYMMDD")
    return normalized


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _finite(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError(f"{field} must be a finite number")
    result = float(value)
    if result <= 0:
        raise ValueError(f"{field} must be positive")
    return result


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _optional_text(value: object, *, field: str, max_length: int) -> str | None:
    if value is None or value == "":
        return None
    return _text(value, field=field, max_length=max_length)


def _pool_members(payload: dict[str, Any]) -> tuple[list[str], dict[str, str], str, str | None]:
    raw_symbols = payload.get("symbols")
    if not isinstance(raw_symbols, list) or not raw_symbols:
        raise ValueError("symbols must be a non-empty list")
    symbols = [_symbol(item) for item in raw_symbols]
    if len(set(symbols)) != len(symbols):
        raise ValueError("symbols must not contain duplicates")
    symbols.sort()
    raw_weights = payload.get("weights", {})
    if not isinstance(raw_weights, dict):
        raise ValueError("weights must be an object")
    if set(raw_weights) - set(symbols):
        raise ValueError("weights contain symbols outside the pool membership")
    if raw_weights and set(raw_weights) != set(symbols):
        raise ValueError("weighted pools require a weight for every member")
    weights: dict[str, str] = {}
    if raw_weights:
        total = Decimal("0")
        for symbol in symbols:
            raw = raw_weights[symbol]
            if isinstance(raw, bool) or not isinstance(raw, (str, int, float, Decimal)):
                raise ValueError("weights must be decimal numbers")
            try:
                value = Decimal(str(raw))
            except InvalidOperation as exc:
                raise ValueError("weights must be decimal numbers") from exc
            if not value.is_finite() or value <= 0 or value > 1:
                raise ValueError("weights must be finite decimal fractions in (0, 1]")
            if value.as_tuple().exponent < -12:
                raise ValueError("weights support at most 12 decimal places")
            normalized = value.quantize(WEIGHT_QUANTUM)
            weights[symbol] = format(normalized, "f")
            total += normalized
        if abs(total - Decimal("1")) > WEIGHT_TOLERANCE:
            raise ValueError("weighted pool weights must sum to one")
        return symbols, weights, "weighted", format(total, "f")
    return symbols, {}, "unweighted", None


def _snapshot_content(
    pool_id: str,
    pool_type: str,
    payload: dict[str, Any],
    provenance: dict[str, Any],
) -> tuple[dict[str, Any], list[str], dict[str, str], str, str | None]:
    symbols, weights, weight_mode, weight_sum = _pool_members(payload)
    definition = payload.get("definition", payload.get("filters", {}))
    if not isinstance(definition, dict):
        raise ValueError("definition must be an object")
    effective_date = payload.get("effective_trade_date")
    if effective_date is not None:
        effective_date = _trade_date(effective_date)
    members = [{"symbol": symbol, "weight": weights.get(symbol)} for symbol in symbols]
    content = {
        "schema_version": "stock-pool-snapshot-v1",
        "pool_id": pool_id,
        "pool_type": pool_type,
        "definition": definition,
        "provenance": provenance,
        "effective_trade_date": effective_date,
        "members": members,
    }
    return content, symbols, weights, weight_mode, weight_sum


class PaperTradingStore(PgStoreMixin):
    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS paper_accounts (
            account_id TEXT PRIMARY KEY,
            owner_principal TEXT NOT NULL,
            name TEXT NOT NULL,
            cash NUMERIC(18,4) NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            version INTEGER NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS paper_accounts_owner_name
            ON paper_accounts(owner_principal, name)
        """,
        """
        CREATE TABLE IF NOT EXISTS stock_pools (
            pool_id TEXT PRIMARY KEY,
            owner_principal TEXT NOT NULL,
            name TEXT NOT NULL,
            pool_type TEXT NOT NULL,
            description TEXT,
            weights_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            symbols_json JSONB NOT NULL,
            version TEXT NOT NULL,
            provenance_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stock_pool_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            pool_id TEXT NOT NULL,
            version_number INTEGER NOT NULL,
            schema_version TEXT NOT NULL,
            pool_type TEXT NOT NULL,
            membership_fingerprint TEXT NOT NULL,
            snapshot_fingerprint TEXT NOT NULL,
            definition_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            provenance_json JSONB NOT NULL,
            effective_trade_date TEXT,
            weight_mode TEXT NOT NULL,
            weight_sum NUMERIC(20,12),
            member_count INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE(pool_id, version_number),
            UNIQUE(pool_id, snapshot_fingerprint)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stock_pool_snapshot_members (
            snapshot_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            weight NUMERIC(20,12),
            PRIMARY KEY(snapshot_id, symbol)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS stock_pool_snapshot_members_symbol_idx
            ON stock_pool_snapshot_members(symbol)
        """,
        """
        CREATE TABLE IF NOT EXISTS stock_pool_lifecycle_audit (
            audit_id TEXT PRIMARY KEY,
            pool_id TEXT NOT NULL,
            owner_principal TEXT NOT NULL,
            actor_principal TEXT NOT NULL,
            previous_status TEXT NOT NULL,
            new_status TEXT NOT NULL,
            reason TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE(owner_principal, idempotency_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stock_pool_write_idempotency (
            owner_principal TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            action TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            result_id TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY(owner_principal, idempotency_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stock_pool_migration_quarantine (
            pool_id TEXT PRIMARY KEY,
            reason TEXT NOT NULL,
            payload_json JSONB NOT NULL,
            quarantined_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stock_pool_migration_runs (
            migration_id TEXT PRIMARY KEY,
            source_count INTEGER NOT NULL,
            migrated_count INTEGER NOT NULL,
            quarantined_count INTEGER NOT NULL,
            manifest_sha256 TEXT NOT NULL,
            completed_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stock_pool_domain_references (
            domain TEXT NOT NULL,
            reference_id TEXT NOT NULL,
            pool_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            owner_principal TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY(domain, reference_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS paper_positions (
            account_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            last_buy_date TEXT,
            PRIMARY KEY(account_id, symbol)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS paper_orders (
            order_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price NUMERIC(18,4) NOT NULL,
            status TEXT NOT NULL,
            blocked_reason TEXT,
            fees NUMERIC(18,4) NOT NULL DEFAULT 0,
            tax NUMERIC(18,4) NOT NULL DEFAULT 0,
            cash_delta NUMERIC(18,4) NOT NULL DEFAULT 0,
            trade_date TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS paper_orders_idempotency
            ON paper_orders(account_id, idempotency_key)
        """,
        """
        CREATE TABLE IF NOT EXISTS paper_fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price NUMERIC(18,4) NOT NULL,
            fees NUMERIC(18,4) NOT NULL,
            tax NUMERIC(18,4) NOT NULL,
            trade_date TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS paper_fills_account_created
            ON paper_fills(account_id, created_at)
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as exc:
            raise PaperTradingPersistenceError("paper trading storage is unavailable") from exc

    def bootstrap_schema(self) -> None:
        super().bootstrap_schema()
        # Column back-migration parity with the former SQLite schema.
        with self.engine.begin() as connection:
            ensure_column(connection, "stock_pools", "pool_type", "TEXT")
            ensure_column(connection, "stock_pools", "description", "TEXT")
            ensure_column(connection, "stock_pools", "weights_json", "JSONB")
            ensure_column(connection, "stock_pools", "status", "TEXT NOT NULL DEFAULT 'active'")
            ensure_column(connection, "stock_pools", "current_snapshot_id", "TEXT")
            ensure_column(connection, "stock_pools", "updated_at", "TIMESTAMPTZ")
            ensure_column(connection, "stock_pools", "metadata_version", "INTEGER NOT NULL DEFAULT 1")
            ensure_column(connection, "stock_pools", "deleted_at", "TIMESTAMPTZ")
            ensure_column(connection, "paper_orders", "pool_id", "TEXT")
            ensure_column(connection, "paper_orders", "stock_pool_snapshot_id", "TEXT")
            execute(connection, "UPDATE stock_pools SET updated_at = created_at WHERE updated_at IS NULL")
            self._backfill_pool_snapshots(connection)

    @classmethod
    def from_env(cls) -> "PaperTradingStore":
        return cls()

    def create_account(self, payload: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("account request must be an object")
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        if owner is None:
            raise PaperTradingForbidden("account requires a trusted owner")
        name = _text(payload.get("name"), field="name", max_length=128)
        cash = _finite(payload.get("cash"), field="cash")
        existing = self._fetch_one(
            "SELECT * FROM paper_accounts WHERE owner_principal = :owner AND name = :name",
            {"owner": owner, "name": name},
        )
        if existing is not None:
            raise PaperTradingConflict("account name already exists")
        now = _now()
        account_id = _new_id("paper_account")
        self._execute(
            """INSERT INTO paper_accounts
            (account_id, owner_principal, name, cash, status, created_at, updated_at, version)
            VALUES (:account_id, :owner, :name, :cash, 'active', :created_at, :updated_at, 1)""",
            {"account_id": account_id, "owner": owner, "name": name, "cash": cash, "created_at": now, "updated_at": now},
        )
        return self.get_account(account_id, trusted_owner=owner)

    def get_account(self, account_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        account_id = _id(account_id, prefix="paper_account")
        row = self._fetch_one("SELECT * FROM paper_accounts WHERE account_id = :account_id", {"account_id": account_id})
        if row is None:
            raise PaperTradingNotFound("paper account not found")
        if trusted_owner and row["owner_principal"] != trusted_owner:
            raise PaperTradingForbidden("paper account is not owned by this principal")
        return dict(row)

    def list_accounts(self, *, trusted_owner: str | None = None) -> dict[str, object]:
        if trusted_owner:
            rows = self._execute(
                "SELECT * FROM paper_accounts WHERE owner_principal = :owner_principal ORDER BY created_at DESC, account_id DESC",
                {"owner_principal": trusted_owner},
            )
        else:
            rows = self._execute("SELECT * FROM paper_accounts ORDER BY created_at DESC, account_id DESC")
        return {"accounts": [dict(row) for row in rows]}

    def _backfill_pool_snapshots(self, connection: Any) -> None:
        rows = execute(connection, "SELECT * FROM stock_pools WHERE current_snapshot_id IS NULL ORDER BY pool_id")
        for row in rows:
            payload = {
                "symbols": row.get("symbols_json") or [],
                "weights": row.get("weights_json") or {},
                "definition": {},
            }
            try:
                pool_type = row.get("pool_type") or "custom"
                if pool_type != "custom":
                    raise ValueError("legacy non-custom pool lacks trusted provenance")
                provenance = {"source": "custom", "migration": "legacy-stock-pool-v1"}
                snapshot_id = self._insert_snapshot(connection, row["pool_id"], pool_type, payload, provenance)
                execute(
                    connection,
                    """UPDATE stock_pools SET current_snapshot_id = :snapshot_id,
                       provenance_json = :provenance, status = 'active', updated_at = COALESCE(updated_at, created_at)
                       WHERE pool_id = :pool_id""",
                    {"snapshot_id": snapshot_id, "provenance": provenance, "pool_id": row["pool_id"]},
                )
            except ValueError as exc:
                execute(
                    connection,
                    """INSERT INTO stock_pool_migration_quarantine
                       (pool_id, reason, payload_json, quarantined_at)
                       VALUES (:pool_id, :reason, :payload, :at)
                       ON CONFLICT(pool_id) DO UPDATE SET reason = excluded.reason,
                       payload_json = excluded.payload_json, quarantined_at = excluded.quarantined_at""",
                    {"pool_id": row["pool_id"], "reason": str(exc), "payload": payload, "at": _now()},
                )
        source = fetch_one(connection, "SELECT COUNT(*) AS count FROM stock_pools")
        migrated = fetch_one(connection, "SELECT COUNT(*) AS count FROM stock_pools WHERE current_snapshot_id IS NOT NULL")
        quarantined = fetch_one(connection, "SELECT COUNT(*) AS count FROM stock_pool_migration_quarantine")
        identities = execute(connection, """SELECT pool_id, owner_principal, current_snapshot_id
                FROM stock_pools ORDER BY pool_id""")
        manifest_sha256 = _hash(identities)
        execute(connection, """INSERT INTO stock_pool_migration_runs
                (migration_id, source_count, migrated_count, quarantined_count, manifest_sha256, completed_at)
                VALUES ('legacy-stock-pool-v1', :source, :migrated, :quarantined, :sha, :at)
                ON CONFLICT(migration_id) DO NOTHING""",
                {"source": int(source["count"] if source else 0), "migrated": int(migrated["count"] if migrated else 0),
                 "quarantined": int(quarantined["count"] if quarantined else 0), "sha": manifest_sha256, "at": _now()})

    def _insert_snapshot(
        self,
        connection: Any,
        pool_id: str,
        pool_type: str,
        payload: dict[str, Any],
        provenance: dict[str, Any],
    ) -> str:
        content, symbols, weights, weight_mode, weight_sum = _snapshot_content(
            pool_id, pool_type, payload, provenance
        )
        snapshot_fingerprint = _hash(content)
        membership_fingerprint = _hash(content["members"])
        existing = fetch_one(
            connection,
            "SELECT snapshot_id FROM stock_pool_snapshots WHERE pool_id = :pool_id AND snapshot_fingerprint = :fingerprint",
            {"pool_id": pool_id, "fingerprint": snapshot_fingerprint},
        )
        if existing:
            return str(existing["snapshot_id"])
        version_row = fetch_one(
            connection,
            "SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version FROM stock_pool_snapshots WHERE pool_id = :pool_id",
            {"pool_id": pool_id},
        )
        version_number = int(version_row["next_version"] if version_row else 1)
        snapshot_id = f"stock_pool_snapshot_{snapshot_fingerprint}"
        now = _now()
        execute(
            connection,
            """INSERT INTO stock_pool_snapshots
               (snapshot_id, pool_id, version_number, schema_version, pool_type,
                membership_fingerprint, snapshot_fingerprint, definition_json,
                provenance_json, effective_trade_date, weight_mode, weight_sum,
                member_count, created_at)
               VALUES (:snapshot_id, :pool_id, :version_number, :schema_version, :pool_type,
                       :membership_fingerprint, :snapshot_fingerprint, :definition,
                       :provenance, :effective_trade_date, :weight_mode, :weight_sum,
                       :member_count, :created_at)""",
            {
                "snapshot_id": snapshot_id,
                "pool_id": pool_id,
                "version_number": version_number,
                "schema_version": content["schema_version"],
                "pool_type": pool_type,
                "membership_fingerprint": membership_fingerprint,
                "snapshot_fingerprint": snapshot_fingerprint,
                "definition": content["definition"],
                "provenance": provenance,
                "effective_trade_date": content["effective_trade_date"],
                "weight_mode": weight_mode,
                "weight_sum": weight_sum,
                "member_count": len(symbols),
                "created_at": now,
            },
        )
        for symbol in symbols:
            execute(
                connection,
                "INSERT INTO stock_pool_snapshot_members (snapshot_id, symbol, weight) VALUES (:snapshot_id, :symbol, :weight)",
                {"snapshot_id": snapshot_id, "symbol": symbol, "weight": weights.get(symbol)},
            )
        return snapshot_id

    def create_pool(self, payload: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("pool request must be an object")
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        if owner is None:
            raise PaperTradingForbidden("pool requires a trusted owner")
        name = _text(payload.get("name"), field="name", max_length=128)
        pool_type = _text(payload.get("pool_type", "custom"), field="pool_type", max_length=16)
        if pool_type not in {"custom", "index", "dynamic"}:
            raise ValueError("pool_type must be custom, index, or dynamic")
        if pool_type != "custom":
            raise PaperTradingForbidden("Product callers may create custom pools only")
        description = _optional_text(payload.get("description"), field="description", max_length=2000)
        symbols, weights, _, _ = _pool_members(payload)
        provenance = {"source": "custom"}
        pool_id = _new_id("stock_pool")
        now = _now()
        with self._transaction() as connection:
            execute(connection, """INSERT INTO stock_pools
                (pool_id, owner_principal, name, pool_type, description, weights_json,
                 symbols_json, version, provenance_json, created_at, updated_at, status, metadata_version)
                VALUES (:pool_id, :owner, :name, :pool_type, :description, :weights,
                        :symbols, 'v1', :provenance, :created_at, :created_at, 'active', 1)""",
                {"pool_id": pool_id, "owner": owner, "name": name, "pool_type": pool_type,
                 "description": description, "weights": weights, "symbols": symbols,
                 "provenance": provenance, "created_at": now})
            snapshot_id = self._insert_snapshot(connection, pool_id, pool_type, payload, provenance)
            execute(connection, "UPDATE stock_pools SET current_snapshot_id = :snapshot_id WHERE pool_id = :pool_id",
                    {"snapshot_id": snapshot_id, "pool_id": pool_id})
        return self.get_pool(pool_id, trusted_owner=owner)

    def create_trusted_pool(self, payload: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        """Trusted domain/data-plane fixture boundary; never exposed to Product callers."""
        if not isinstance(payload, dict):
            raise ValueError("pool request must be an object")
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        if owner is None:
            raise PaperTradingForbidden("trusted pool requires an owner")
        pool_type = _text(payload.get("pool_type"), field="pool_type", max_length=16)
        if pool_type not in {"index", "dynamic"}:
            raise ValueError("trusted pool type must be index or dynamic")
        provenance = payload.get("provenance")
        if not isinstance(provenance, dict):
            raise ValueError("trusted provenance must be an object")
        if pool_type == "index":
            required = {"index_symbol", "provider", "dataset_id", "source_weight_unit", "normalization_contract"}
            if not required.issubset(provenance) or provenance.get("provider") != "tushare":
                raise ValueError("index provenance is incomplete or provider is not tushare")
            if payload.get("effective_trade_date") is None:
                raise ValueError("index pool requires effective_trade_date")
        else:
            required = {"producer_id", "producer_version", "rule_fingerprint", "evaluated_at", "input_references"}
            if not required.issubset(provenance):
                raise ValueError("dynamic provenance is incomplete")
        name = _text(payload.get("name"), field="name", max_length=128)
        description = _optional_text(payload.get("description"), field="description", max_length=2000)
        symbols, weights, _, _ = _pool_members(payload)
        pool_id = _new_id("stock_pool")
        now = _now()
        with self._transaction() as connection:
            execute(connection, """INSERT INTO stock_pools
                (pool_id, owner_principal, name, pool_type, description, weights_json,
                 symbols_json, version, provenance_json, created_at, updated_at, status, metadata_version)
                VALUES (:pool_id, :owner, :name, :pool_type, :description, :weights,
                        :symbols, 'v1', :provenance, :created_at, :created_at, 'active', 1)""",
                {"pool_id": pool_id, "owner": owner, "name": name, "pool_type": pool_type,
                 "description": description, "weights": weights, "symbols": symbols,
                 "provenance": provenance, "created_at": now})
            snapshot_id = self._insert_snapshot(connection, pool_id, pool_type, payload, provenance)
            execute(connection, "UPDATE stock_pools SET current_snapshot_id = :snapshot_id WHERE pool_id = :pool_id",
                    {"snapshot_id": snapshot_id, "pool_id": pool_id})
        return self.get_pool(pool_id, trusted_owner=owner)

    def get_pool(self, pool_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        pool_id = _id(pool_id, prefix="stock_pool")
        row = self._fetch_one("SELECT * FROM stock_pools WHERE pool_id = :pool_id", {"pool_id": pool_id})
        if row is None:
            raise PaperTradingNotFound("stock pool not found")
        if trusted_owner and row["owner_principal"] != trusted_owner:
            raise PaperTradingNotFound("stock pool not found")
        return self._pool_detail(row)

    def list_pools(self, *, trusted_owner: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, object]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("offset must be non-negative")
        if trusted_owner:
            rows = self._execute(
                """SELECT * FROM stock_pools WHERE owner_principal = :owner_principal AND status <> 'deleted'
                   ORDER BY updated_at DESC, pool_id DESC LIMIT :limit OFFSET :offset""",
                {"owner_principal": trusted_owner, "limit": limit, "offset": offset},
            )
            total_row = self._fetch_one("SELECT COUNT(*) AS total FROM stock_pools WHERE owner_principal = :owner AND status <> 'deleted'", {"owner": trusted_owner})
        else:
            rows = self._execute("SELECT * FROM stock_pools WHERE status <> 'deleted' ORDER BY updated_at DESC, pool_id DESC LIMIT :limit OFFSET :offset", {"limit": limit, "offset": offset})
            total_row = self._fetch_one("SELECT COUNT(*) AS total FROM stock_pools WHERE status <> 'deleted'")
        return {"pools": [self._pool_detail(row, include_members=False) for row in rows], "total": int(total_row["total"] if total_row else 0), "limit": limit, "offset": offset}

    def _pool_detail(self, row: dict[str, Any], *, include_members: bool = True) -> dict[str, object]:
        result = dict(row)
        result.pop("symbols_json", None)
        result.pop("weights_json", None)
        result.pop("provenance_json", None)
        snapshot_id = result.get("current_snapshot_id")
        snapshot = self.get_pool_snapshot(snapshot_id, trusted_owner=row["owner_principal"], include_members=include_members) if snapshot_id else None
        result["snapshot"] = snapshot
        result["version"] = f"v{snapshot['version_number']}" if snapshot else None
        result["member_count"] = snapshot["member_count"] if snapshot else 0
        if include_members and snapshot:
            result["symbols"] = [item["symbol"] for item in snapshot["members"]]
            result["weights"] = {item["symbol"]: item["weight"] for item in snapshot["members"] if item["weight"] is not None}
        return result

    def get_pool_snapshot(
        self, snapshot_id: object, *, trusted_owner: str | None = None, include_members: bool = True
    ) -> dict[str, object]:
        snapshot_id = _text(snapshot_id, field="snapshot_id", max_length=96)
        row = self._fetch_one(
            """SELECT s.*, p.owner_principal FROM stock_pool_snapshots s
               JOIN stock_pools p ON p.pool_id = s.pool_id WHERE s.snapshot_id = :snapshot_id""",
            {"snapshot_id": snapshot_id},
        )
        if row is None:
            raise PaperTradingNotFound("stock pool snapshot not found")
        if trusted_owner and row["owner_principal"] != trusted_owner:
            raise PaperTradingNotFound("stock pool snapshot not found")
        result = dict(row)
        result.pop("owner_principal", None)
        result["definition"] = result.pop("definition_json") or {}
        result["provenance"] = result.pop("provenance_json") or {}
        result["weight_sum"] = None if result["weight_sum"] is None else format(Decimal(str(result["weight_sum"])), "f")
        if include_members:
            rows = self._execute(
                """SELECT symbol, weight::text AS weight FROM stock_pool_snapshot_members
                   WHERE snapshot_id = :snapshot_id ORDER BY symbol""",
                {"snapshot_id": snapshot_id},
            )
            result["members"] = [dict(item) for item in rows]
        return result

    def list_pool_snapshots(self, pool_id: object, *, trusted_owner: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, object]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("offset must be non-negative")
        pool = self.get_pool(pool_id, trusted_owner=trusted_owner)
        rows = self._execute(
            """SELECT snapshot_id, version_number, membership_fingerprint, snapshot_fingerprint,
                      effective_trade_date, weight_mode, weight_sum::text AS weight_sum,
                      member_count, created_at
               FROM stock_pool_snapshots WHERE pool_id = :pool_id ORDER BY version_number DESC
               LIMIT :limit OFFSET :offset""",
            {"pool_id": pool["pool_id"], "limit": limit, "offset": offset},
        )
        total = self._fetch_one("SELECT COUNT(*) AS total FROM stock_pool_snapshots WHERE pool_id = :pool_id", {"pool_id": pool["pool_id"]})
        return {"snapshots": rows, "total": int(total["total"] if total else 0), "limit": limit, "offset": offset}

    def get_pool_as_of(self, pool_id: object, trade_date: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        pool = self.get_pool(pool_id, trusted_owner=trusted_owner)
        if pool["pool_type"] != "index":
            raise ValueError("as-of resolution is available for index pools only")
        normalized_date = _trade_date(trade_date)
        row = self._fetch_one(
            """SELECT snapshot_id FROM stock_pool_snapshots
               WHERE pool_id = :pool_id AND effective_trade_date <= :trade_date
               ORDER BY effective_trade_date DESC, version_number DESC LIMIT 1""",
            {"pool_id": pool["pool_id"], "trade_date": normalized_date},
        )
        if row is None:
            raise PaperTradingNotFound("no index snapshot exists at or before the requested date")
        return self.get_pool_snapshot(row["snapshot_id"], trusted_owner=trusted_owner)

    def append_trusted_pool_snapshot(self, pool_id: object, payload: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("snapshot request must be an object")
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        pool_id = _id(pool_id, prefix="stock_pool")
        provenance = payload.get("provenance")
        if not isinstance(provenance, dict):
            raise ValueError("trusted provenance must be an object")
        with self._transaction() as connection:
            pool = fetch_one(connection, "SELECT * FROM stock_pools WHERE pool_id = :pool_id FOR UPDATE", {"pool_id": pool_id})
            if pool is None or pool["owner_principal"] != owner:
                raise PaperTradingForbidden("stock pool is not owned by this principal")
            if pool["pool_type"] not in {"index", "dynamic"} or pool["status"] == "deleted":
                raise PaperTradingForbidden("trusted snapshot writer is not allowed for this pool")
            if pool["pool_type"] == "index":
                required = {"index_symbol", "provider", "dataset_id", "source_weight_unit", "normalization_contract"}
                if not required.issubset(provenance) or provenance.get("provider") != "tushare" or payload.get("effective_trade_date") is None:
                    raise ValueError("index provenance is incomplete or provider is not tushare")
            snapshot_id = self._insert_snapshot(connection, pool_id, pool["pool_type"], payload, provenance)
            new_snapshot = fetch_one(connection, "SELECT * FROM stock_pool_snapshots WHERE snapshot_id = :snapshot_id", {"snapshot_id": snapshot_id})
            current = fetch_one(connection, "SELECT effective_trade_date FROM stock_pool_snapshots WHERE snapshot_id = :snapshot_id", {"snapshot_id": pool["current_snapshot_id"]})
            if pool["pool_type"] == "dynamic" or current is None or (new_snapshot["effective_trade_date"] or "") >= (current["effective_trade_date"] or ""):
                execute(connection, "UPDATE stock_pools SET current_snapshot_id = :snapshot_id, version = :version, updated_at = :at WHERE pool_id = :pool_id",
                        {"snapshot_id": snapshot_id, "version": f"v{new_snapshot['version_number']}", "at": _now(), "pool_id": pool_id})
        return self.get_pool_snapshot(snapshot_id, trusted_owner=owner)

    def replace_pool_snapshot(
        self, pool_id: object, payload: object, *, trusted_owner: str | None = None
    ) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("snapshot request must be an object")
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        if owner is None:
            raise PaperTradingForbidden("snapshot update requires a trusted owner")
        pool_id = _id(pool_id, prefix="stock_pool")
        key = _idempotency(payload.get("idempotency_key"))
        expected = _text(payload.get("expected_current_snapshot_id"), field="expected_current_snapshot_id", max_length=96)
        request_hash = _hash({key: value for key, value in payload.items() if key != "idempotency_key"})
        with self._transaction() as connection:
            pool = fetch_one(connection, "SELECT * FROM stock_pools WHERE pool_id = :pool_id FOR UPDATE", {"pool_id": pool_id})
            if pool is None or pool["owner_principal"] != owner:
                raise PaperTradingForbidden("stock pool is not owned by this principal")
            if pool["status"] == "deleted":
                raise PaperTradingConflict("deleted stock pool cannot be edited")
            previous = fetch_one(connection, "SELECT * FROM stock_pool_write_idempotency WHERE owner_principal = :owner AND idempotency_key = :key",
                                 {"owner": owner, "key": key})
            if previous:
                if previous["request_hash"] != request_hash:
                    raise PaperTradingConflict("stock pool idempotency key was reused")
                return self.get_pool_snapshot(previous["result_id"], trusted_owner=owner)
            if pool["current_snapshot_id"] != expected:
                raise PaperTradingConflict("current stock pool snapshot changed")
            provenance = {"source": "custom"}
            snapshot_id = self._insert_snapshot(connection, pool_id, pool["pool_type"], payload, provenance)
            snapshot = fetch_one(connection, "SELECT * FROM stock_pool_snapshots WHERE snapshot_id = :snapshot_id", {"snapshot_id": snapshot_id})
            members = execute(connection, "SELECT symbol, weight::text AS weight FROM stock_pool_snapshot_members WHERE snapshot_id = :snapshot_id ORDER BY symbol", {"snapshot_id": snapshot_id})
            symbols = [item["symbol"] for item in members]
            weights = {item["symbol"]: item["weight"] for item in members if item["weight"] is not None}
            execute(connection, """UPDATE stock_pools SET current_snapshot_id = :snapshot_id,
                    symbols_json = :symbols, weights_json = :weights, version = :version,
                    provenance_json = :provenance, updated_at = :updated_at WHERE pool_id = :pool_id""",
                    {"snapshot_id": snapshot_id, "symbols": symbols, "weights": weights,
                     "version": f"v{snapshot['version_number']}", "provenance": provenance,
                     "updated_at": _now(), "pool_id": pool_id})
            execute(connection, """INSERT INTO stock_pool_write_idempotency
                    (owner_principal, idempotency_key, action, request_hash, result_id, created_at)
                    VALUES (:owner, :key, 'snapshot_replace', :request_hash, :result_id, :created_at)""",
                    {"owner": owner, "key": key, "request_hash": request_hash, "result_id": snapshot_id, "created_at": _now()})
        return self.get_pool_snapshot(snapshot_id, trusted_owner=owner)

    def update_pool_metadata(self, pool_id: object, payload: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("metadata request must be an object")
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        pool_id = _id(pool_id, prefix="stock_pool")
        expected = _positive_int(payload.get("expected_metadata_version"), "expected_metadata_version")
        name = _text(payload.get("name"), field="name", max_length=128)
        description = _optional_text(payload.get("description"), field="description", max_length=2000)
        rows = self._execute(
            """UPDATE stock_pools SET name = :name, description = :description,
                      metadata_version = metadata_version + 1, updated_at = :updated_at
               WHERE pool_id = :pool_id AND owner_principal = :owner AND status <> 'deleted'
                     AND metadata_version = :expected RETURNING pool_id""",
            {"name": name, "description": description, "updated_at": _now(), "pool_id": pool_id,
             "owner": owner, "expected": expected},
        )
        if not rows:
            raise PaperTradingConflict("stock pool metadata changed or pool is unavailable")
        return self.get_pool(pool_id, trusted_owner=owner)

    def set_pool_lifecycle(self, pool_id: object, payload: object, *, trusted_owner: str | None = None, trusted_actor: str | None = None) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("lifecycle request must be an object")
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        actor = _principal(trusted_actor or owner, field="actor_principal") if owner else None
        pool_id = _id(pool_id, prefix="stock_pool")
        target = _text(payload.get("status"), field="status", max_length=16)
        if target not in {"active", "inactive", "deleted"}:
            raise ValueError("status must be active, inactive, or deleted")
        reason = _text(payload.get("reason"), field="reason", max_length=500)
        key = _idempotency(payload.get("idempotency_key"))
        with self._transaction() as connection:
            pool = fetch_one(connection, "SELECT * FROM stock_pools WHERE pool_id = :pool_id FOR UPDATE", {"pool_id": pool_id})
            if pool is None or pool["owner_principal"] != owner:
                raise PaperTradingForbidden("stock pool is not owned by this principal")
            prior_audit = fetch_one(connection, "SELECT * FROM stock_pool_lifecycle_audit WHERE owner_principal = :owner AND idempotency_key = :key", {"owner": owner, "key": key})
            if prior_audit:
                if prior_audit["pool_id"] != pool_id or prior_audit["new_status"] != target:
                    raise PaperTradingConflict("stock pool lifecycle idempotency key was reused")
                return self.get_pool(pool_id, trusted_owner=owner)
            current = pool["status"]
            if current == "deleted" and target != "deleted":
                raise PaperTradingConflict("deleted stock pool cannot be reactivated")
            if current == target:
                return self.get_pool(pool_id, trusted_owner=owner)
            now = _now()
            execute(connection, "UPDATE stock_pools SET status = :status, updated_at = :at, deleted_at = CASE WHEN :status = 'deleted' THEN :at ELSE deleted_at END WHERE pool_id = :pool_id",
                    {"status": target, "at": now, "pool_id": pool_id})
            execute(connection, """INSERT INTO stock_pool_lifecycle_audit
                    (audit_id, pool_id, owner_principal, actor_principal, previous_status,
                     new_status, reason, idempotency_key, created_at)
                    VALUES (:audit_id, :pool_id, :owner, :actor, :previous, :new,
                            :reason, :key, :created_at)""",
                    {"audit_id": _new_id("pool_audit"), "pool_id": pool_id, "owner": owner,
                     "actor": actor, "previous": current, "new": target, "reason": reason,
                     "key": key, "created_at": now})
        return self.get_pool(pool_id, trusted_owner=owner)

    def pool_references(self, pool_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        pool = self.get_pool(pool_id, trusted_owner=trusted_owner)
        rows = self._execute(
            """SELECT domain, snapshot_id, COUNT(*) AS reference_count,
                      MIN(created_at) AS first_referenced_at, MAX(created_at) AS last_referenced_at
               FROM stock_pool_domain_references WHERE pool_id = :pool_id
               GROUP BY domain, snapshot_id ORDER BY last_referenced_at DESC""",
            {"pool_id": pool["pool_id"]},
        )
        return {"references": rows}

    def record_pool_reference(
        self, snapshot_id: object, *, domain: str, reference_id: str, trusted_owner: str
    ) -> dict[str, object]:
        snapshot = self.get_pool_snapshot(snapshot_id, trusted_owner=trusted_owner, include_members=False)
        if domain not in {"paper_order", "backtest", "research"}:
            raise ValueError("stock pool reference domain is invalid")
        pool = self.get_pool(snapshot["pool_id"], trusted_owner=trusted_owner)
        if pool["status"] != "active":
            raise PaperTradingConflict("stock pool must be active for a new reference")
        self._execute(
            """INSERT INTO stock_pool_domain_references
               (domain, reference_id, pool_id, snapshot_id, owner_principal, created_at)
               VALUES (:domain, :reference_id, :pool_id, :snapshot_id, :owner, :created_at)
               ON CONFLICT(domain, reference_id) DO NOTHING""",
            {"domain": domain, "reference_id": reference_id, "pool_id": snapshot["pool_id"],
             "snapshot_id": snapshot["snapshot_id"], "owner": trusted_owner, "created_at": _now()},
        )
        return {"domain": domain, "reference_id": reference_id, "pool_id": snapshot["pool_id"], "snapshot_id": snapshot["snapshot_id"]}
        return result

    def submit_order(self, payload: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("order request must be an object")
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        if owner is None:
            raise PaperTradingForbidden("order requires a trusted owner")
        account_id = _id(payload.get("account_id"), prefix="paper_account")
        pool_id = _id(payload.get("pool_id"), prefix="stock_pool")
        symbol = _symbol(payload.get("symbol"))
        side = _text(payload.get("side"), field="side", max_length=4)
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        quantity = _positive_int(payload.get("quantity"), "quantity")
        price = _finite(payload.get("price"), "price")
        trade_date = _trade_date(payload.get("trade_date"))
        is_suspended = bool(payload.get("is_suspended", False))
        up_limit = payload.get("up_limit")
        down_limit = payload.get("down_limit")
        key = _idempotency(payload.get("idempotency_key"))
        request = {
            "account_id": account_id,
            "pool_id": pool_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "trade_date": trade_date,
            "is_suspended": is_suspended,
            "up_limit": up_limit,
            "down_limit": down_limit,
            "idempotency_key": key,
        }
        with self._transaction() as connection:
            account = fetch_one(connection, "SELECT * FROM paper_accounts WHERE account_id = :account_id", {"account_id": account_id})
            if account is None or account["owner_principal"] != owner:
                raise PaperTradingForbidden("paper account is not owned by this principal")
            pool = fetch_one(connection, "SELECT * FROM stock_pools WHERE pool_id = :pool_id", {"pool_id": pool_id})
            if pool is None or pool["owner_principal"] != owner:
                raise PaperTradingForbidden("stock pool is not owned by this principal")
            if pool["status"] != "active" or not pool["current_snapshot_id"]:
                raise PaperTradingForbidden("stock pool is not active")
            snapshot_id = pool["current_snapshot_id"]
            member = fetch_one(connection, """SELECT symbol FROM stock_pool_snapshot_members
                    WHERE snapshot_id = :snapshot_id AND symbol = :symbol""",
                    {"snapshot_id": snapshot_id, "symbol": symbol})
            if member is None:
                raise PaperTradingForbidden("symbol is not in the authorized stock pool")
            request["stock_pool_snapshot_id"] = snapshot_id
            request_hash = _hash(request)
            existing = fetch_one(
                connection,
                "SELECT * FROM paper_orders WHERE account_id = :account_id AND idempotency_key = :key",
                {"account_id": account_id, "key": key},
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise PaperTradingConflict("order idempotency key was reused")
                execute(connection, """INSERT INTO stock_pool_domain_references
                        (domain, reference_id, pool_id, snapshot_id, owner_principal, created_at)
                        VALUES ('paper_order', :reference_id, :pool_id, :snapshot_id, :owner, :created_at)
                        ON CONFLICT(domain, reference_id) DO NOTHING""",
                        {"reference_id": existing["order_id"], "pool_id": pool_id, "snapshot_id": snapshot_id,
                         "owner": owner, "created_at": existing["created_at"]})
                return self._order_row(existing)

            blocked = self._blocked_reason(
                connection, account, side, quantity, price, trade_date, is_suspended, up_limit, down_limit, symbol
            )
            now = _now()
            order_id = _new_id("paper_order")
            if blocked is None:
                fees, tax, cash_delta = self._execution_cost(side, quantity, price)
                status = "filled"
                new_cash = float(account["cash"]) + cash_delta
                execute(
                    connection,
                    "UPDATE paper_accounts SET cash = :cash, updated_at = :updated_at, version = version + 1 WHERE account_id = :account_id",
                    {"cash": new_cash, "updated_at": now, "account_id": account_id},
                )
                self._upsert_position(connection, account_id, symbol, side, quantity, trade_date)
                fill_id = _new_id("paper_fill")
                execute(
                    connection,
                    """INSERT INTO paper_fills
                    (fill_id, order_id, account_id, symbol, side, quantity, price, fees, tax, trade_date, created_at)
                    VALUES (:fill_id, :order_id, :account_id, :symbol, :side, :quantity, :price, :fees, :tax, :trade_date, :created_at)""",
                    {"fill_id": fill_id, "order_id": order_id, "account_id": account_id, "symbol": symbol, "side": side, "quantity": quantity, "price": price, "fees": fees, "tax": tax, "trade_date": trade_date, "created_at": now},
                )
                blocked_reason = None
            else:
                status = "blocked"
                fees = 0.0
                tax = 0.0
                cash_delta = 0.0
                blocked_reason = blocked
            execute(
                connection,
                """INSERT INTO paper_orders
                (order_id, account_id, pool_id, stock_pool_snapshot_id, symbol, side, quantity, price, status, blocked_reason,
                 fees, tax, cash_delta, trade_date, idempotency_key, request_hash, created_at)
                VALUES (:order_id, :account_id, :pool_id, :snapshot_id, :symbol, :side, :quantity, :price, :status, :blocked_reason,
                        :fees, :tax, :cash_delta, :trade_date, :idempotency_key, :request_hash, :created_at)""",
                {"order_id": order_id, "account_id": account_id, "pool_id": pool_id, "snapshot_id": snapshot_id, "symbol": symbol, "side": side, "quantity": quantity, "price": price, "status": status, "blocked_reason": blocked_reason, "fees": fees, "tax": tax, "cash_delta": cash_delta, "trade_date": trade_date, "idempotency_key": key, "request_hash": request_hash, "created_at": now},
            )
            order_row = fetch_one(connection, "SELECT * FROM paper_orders WHERE order_id = :order_id", {"order_id": order_id})
            execute(connection, """INSERT INTO stock_pool_domain_references
                    (domain, reference_id, pool_id, snapshot_id, owner_principal, created_at)
                    VALUES ('paper_order', :reference_id, :pool_id, :snapshot_id, :owner, :created_at)""",
                    {"reference_id": order_id, "pool_id": pool_id, "snapshot_id": snapshot_id,
                     "owner": owner, "created_at": now})
        return self._order_row(order_row)

    def list_orders(self, account_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        account_id = _id(account_id, prefix="paper_account")
        account = self._fetch_one("SELECT * FROM paper_accounts WHERE account_id = :account_id", {"account_id": account_id})
        if account is None or (trusted_owner and account["owner_principal"] != trusted_owner):
            raise PaperTradingForbidden("paper account is not owned by this principal")
        rows = self._execute(
            "SELECT * FROM paper_orders WHERE account_id = :account_id ORDER BY created_at DESC, order_id DESC",
            {"account_id": account_id},
        )
        return {"orders": [self._order_row(row) for row in rows]}

    def list_positions(self, account_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        account_id = _id(account_id, prefix="paper_account")
        account = self._fetch_one("SELECT * FROM paper_accounts WHERE account_id = :account_id", {"account_id": account_id})
        if account is None or (trusted_owner and account["owner_principal"] != trusted_owner):
            raise PaperTradingForbidden("paper account is not owned by this principal")
        rows = self._execute(
            "SELECT * FROM paper_positions WHERE account_id = :account_id ORDER BY symbol ASC",
            {"account_id": account_id},
        )
        return {"positions": [dict(row) for row in rows]}

    def list_fills(self, account_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        account_id = _id(account_id, prefix="paper_account")
        account = self._fetch_one("SELECT * FROM paper_accounts WHERE account_id = :account_id", {"account_id": account_id})
        if account is None or (trusted_owner and account["owner_principal"] != trusted_owner):
            raise PaperTradingForbidden("paper account is not owned by this principal")
        rows = self._execute(
            "SELECT * FROM paper_fills WHERE account_id = :account_id ORDER BY created_at DESC, fill_id DESC",
            {"account_id": account_id},
        )
        return {"fills": [dict(row) for row in rows]}

    def _blocked_reason(
        self,
        connection: Any,
        account: dict[str, Any],
        side: str,
        quantity: int,
        price: float,
        trade_date: str,
        is_suspended: bool,
        up_limit: object,
        down_limit: object,
        symbol: str,
    ) -> str | None:
        if quantity % LOT_SIZE != 0:
            return "lot_size"
        if is_suspended:
            return "suspended"
        if side == "buy" and up_limit is not None and price > float(up_limit):
            return "limit_up"
        if side == "sell" and down_limit is not None and price < float(down_limit):
            return "limit_down"
        position = fetch_one(
            connection,
            "SELECT * FROM paper_positions WHERE account_id = :account_id AND symbol = :symbol",
            {"account_id": account["account_id"], "symbol": symbol},
        )
        if side == "sell":
            if position is None or position["quantity"] < quantity:
                return "insufficient_position"
            if position["last_buy_date"] == trade_date:
                return "t_plus_one"
        if side == "buy":
            estimated = price * quantity * 1.0003
            if float(account["cash"]) < estimated:
                return "insufficient_cash"
        return None

    @staticmethod
    def _execution_cost(side: str, quantity: int, price: float) -> tuple[float, float, float]:
        amount = price * quantity
        fees = max(5.0, amount * 0.0003)
        tax = amount * 0.0005 if side == "sell" else 0.0
        cash_delta = amount + fees + tax if side == "buy" else -(amount - fees - tax)
        return fees, tax, cash_delta

    def _upsert_position(self, connection: Any, account_id: str, symbol: str, side: str, quantity: int, trade_date: str) -> None:
        row = fetch_one(
            connection,
            "SELECT * FROM paper_positions WHERE account_id = :account_id AND symbol = :symbol",
            {"account_id": account_id, "symbol": symbol},
        )
        if side == "buy":
            new_qty = (row["quantity"] if row else 0) + quantity
            last_buy_date = trade_date
        else:
            new_qty = (row["quantity"] if row else 0) - quantity
            last_buy_date = row["last_buy_date"] if row else None
        if new_qty == 0:
            execute(
                connection,
                "DELETE FROM paper_positions WHERE account_id = :account_id AND symbol = :symbol",
                {"account_id": account_id, "symbol": symbol},
            )
        else:
            execute(
                connection,
                """INSERT INTO paper_positions (account_id, symbol, quantity, last_buy_date)
                VALUES (:account_id, :symbol, :quantity, :last_buy_date)
                ON CONFLICT(account_id, symbol)
                DO UPDATE SET quantity = excluded.quantity, last_buy_date = excluded.last_buy_date""",
                {"account_id": account_id, "symbol": symbol, "quantity": new_qty, "last_buy_date": last_buy_date},
            )

    @staticmethod
    def _order_row(row: dict[str, Any]) -> dict[str, object]:
        result = dict(row)
        result.pop("idempotency_key", None)
        result.pop("request_hash", None)
        return result
