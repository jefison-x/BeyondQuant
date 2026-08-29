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
MONEY_QUANTUM = Decimal("0.0001")
BUNDLE_SCHEMA_VERSION = "paper-account-bundle-v1"


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


def _money(value: object, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"{field} must be a decimal number")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal number") from exc
    if not result.is_finite() or result < 0 or (positive and result <= 0):
        qualifier = "positive " if positive else "non-negative "
        raise ValueError(f"{field} must be a {qualifier}decimal number")
    return result.quantize(MONEY_QUANTUM)


def _money_text(value: object) -> str:
    return format(Decimal(str(value)).quantize(MONEY_QUANTUM), "f")


def _signed_money(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"{field} must be a decimal number")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal number") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be a finite decimal number")
    return result.quantize(MONEY_QUANTUM)


def _hash(value: object) -> str:
    def encode(item: object) -> str:
        if isinstance(item, Decimal):
            return format(item, "f")
        if isinstance(item, datetime):
            return item.isoformat()
        raise TypeError(f"unsupported canonical value: {type(item).__name__}")
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=encode,
    ).encode("utf-8")).hexdigest()


def _bundle_json_value(value: object) -> object:
    """Return the exact JSON value covered by a portable bundle digest."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("paper account bundle contains a non-finite number")
        return repr(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _bundle_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_bundle_json_value(item) for item in value]
    return value


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
        """
        CREATE TABLE IF NOT EXISTS paper_account_controls (
            account_id TEXT PRIMARY KEY,
            kill_switch_engaged BOOLEAN NOT NULL DEFAULT FALSE,
            kill_switch_reason TEXT,
            max_order_notional NUMERIC(18,4),
            version INTEGER NOT NULL DEFAULT 1,
            updated_by TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS paper_ledger_entries (
            entry_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            entry_type TEXT NOT NULL,
            trade_date TEXT,
            order_id TEXT,
            fill_id TEXT,
            snapshot_id TEXT,
            symbol TEXT,
            side TEXT,
            quantity INTEGER NOT NULL DEFAULT 0,
            price NUMERIC(18,4),
            amount NUMERIC(18,4) NOT NULL DEFAULT 0,
            fees NUMERIC(18,4) NOT NULL DEFAULT 0,
            cash_delta NUMERIC(18,4) NOT NULL DEFAULT 0,
            realized_pnl NUMERIC(18,4) NOT NULL DEFAULT 0,
            details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS paper_ledger_account_created
            ON paper_ledger_entries(account_id, created_at, entry_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS paper_account_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            cash NUMERIC(18,4) NOT NULL,
            market_value NUMERIC(18,4) NOT NULL,
            equity NUMERIC(18,4) NOT NULL,
            realized_pnl NUMERIC(18,4) NOT NULL,
            unrealized_pnl NUMERIC(18,4) NOT NULL,
            daily_pnl NUMERIC(18,4) NOT NULL,
            daily_return NUMERIC(20,12),
            positions_json JSONB NOT NULL,
            mark_provenance_json JSONB NOT NULL,
            snapshot_fingerprint TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE(account_id, trade_date),
            UNIQUE(account_id, idempotency_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS paper_account_audit (
            audit_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            owner_principal TEXT NOT NULL,
            actor_principal TEXT NOT NULL,
            action TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE(owner_principal, idempotency_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS paper_transfer_audit (
            transfer_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            owner_principal TEXT NOT NULL,
            direction TEXT NOT NULL,
            bundle_sha256 TEXT NOT NULL,
            details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS paper_domain_migration_quarantine (
            account_id TEXT PRIMARY KEY,
            reason TEXT NOT NULL,
            details_json JSONB NOT NULL,
            quarantined_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS paper_domain_migration_runs (
            migration_id TEXT PRIMARY KEY,
            source_count INTEGER NOT NULL,
            migrated_count INTEGER NOT NULL,
            quarantined_count INTEGER NOT NULL,
            manifest_sha256 TEXT NOT NULL,
            completed_at TIMESTAMPTZ NOT NULL
        )
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
            ensure_column(connection, "paper_accounts", "initial_cash", "NUMERIC(18,4)")
            ensure_column(connection, "paper_accounts", "equity", "NUMERIC(18,4)")
            ensure_column(connection, "paper_accounts", "realized_pnl", "NUMERIC(18,4) NOT NULL DEFAULT 0")
            ensure_column(connection, "paper_accounts", "currency", "TEXT NOT NULL DEFAULT 'CNY'")
            ensure_column(connection, "paper_accounts", "last_settlement_date", "TEXT")
            ensure_column(connection, "paper_accounts", "bound_pool_id", "TEXT")
            ensure_column(connection, "paper_accounts", "bound_snapshot_id", "TEXT")
            ensure_column(connection, "paper_accounts", "deleted_at", "TIMESTAMPTZ")
            ensure_column(connection, "paper_positions", "sellable_quantity", "INTEGER NOT NULL DEFAULT 0")
            ensure_column(connection, "paper_positions", "locked_quantity", "INTEGER NOT NULL DEFAULT 0")
            ensure_column(connection, "paper_positions", "average_cost", "NUMERIC(18,4) NOT NULL DEFAULT 0")
            ensure_column(connection, "paper_positions", "market_price", "NUMERIC(18,4)")
            ensure_column(connection, "paper_positions", "mark_provenance_json", "JSONB NOT NULL DEFAULT '{}'::jsonb")
            ensure_column(connection, "paper_orders", "fill_id", "TEXT")
            ensure_column(connection, "paper_orders", "risk_evaluation_json", "JSONB NOT NULL DEFAULT '{}'::jsonb")
            ensure_column(connection, "paper_orders", "decision_provenance_json", "JSONB NOT NULL DEFAULT '{}'::jsonb")
            ensure_column(connection, "paper_orders", "events_json", "JSONB NOT NULL DEFAULT '[]'::jsonb")
            ensure_column(connection, "paper_orders", "execution_contract_version", "TEXT NOT NULL DEFAULT 'paper-execution-v1'")
            execute(connection, "UPDATE stock_pools SET updated_at = created_at WHERE updated_at IS NULL")
            self._migrate_paper_execution_v2(connection)
            self._backfill_pool_snapshots(connection)

    def _migrate_paper_execution_v2(self, connection: Any) -> None:
        rows = execute(connection, "SELECT * FROM paper_accounts ORDER BY account_id")
        migrated = 0
        quarantined = 0
        for account in rows:
            account_id = account["account_id"]
            if account.get("initial_cash") is not None:
                migrated += 1
                execute(connection, """INSERT INTO paper_account_controls
                        (account_id, kill_switch_engaged, version, updated_by, updated_at)
                        VALUES (:account_id, FALSE, 1, :owner, :at)
                        ON CONFLICT(account_id) DO NOTHING""",
                        {"account_id": account_id, "owner": account["owner_principal"], "at": _now()})
                continue
            orders = execute(connection, """SELECT * FROM paper_orders
                    WHERE account_id = :account_id AND status = 'filled'
                    ORDER BY created_at, order_id""", {"account_id": account_id})
            raw_delta = sum((Decimal(str(row.get("cash_delta") or 0)) for row in orders), Decimal("0"))
            initial_cash = Decimal(str(account["cash"])) - raw_delta
            normalized_delta = Decimal("0")
            for order in orders:
                amount = Decimal(str(order["price"])) * int(order["quantity"])
                fees = Decimal(str(order.get("fees") or 0))
                tax = Decimal(str(order.get("tax") or 0))
                normalized_delta += -(amount + fees + tax) if order["side"] == "buy" else amount - fees - tax
            corrected_cash = initial_cash + normalized_delta
            if initial_cash <= 0 or corrected_cash < 0:
                quarantined += 1
                execute(connection, """INSERT INTO paper_domain_migration_quarantine
                        (account_id, reason, details_json, quarantined_at)
                        VALUES (:account_id, 'unprovable_cash_state', :details, :at)
                        ON CONFLICT(account_id) DO UPDATE SET reason = excluded.reason,
                        details_json = excluded.details_json, quarantined_at = excluded.quarantined_at""",
                        {"account_id": account_id,
                         "details": {"stored_cash": _money_text(account["cash"]),
                                     "legacy_delta": _money_text(raw_delta)}, "at": _now()})
                execute(connection, "UPDATE paper_accounts SET status = 'inactive' WHERE account_id = :account_id",
                        {"account_id": account_id})
                continue
            migrated += 1
            execute(connection, """UPDATE paper_accounts SET initial_cash = :initial_cash,
                    cash = :cash, equity = :cash, currency = 'CNY', realized_pnl = 0
                    WHERE account_id = :account_id""",
                    {"initial_cash": initial_cash, "cash": corrected_cash, "account_id": account_id})
            execute(connection, """UPDATE paper_positions SET
                    sellable_quantity = CASE WHEN last_buy_date IS NULL THEN quantity ELSE 0 END,
                    locked_quantity = CASE WHEN last_buy_date IS NULL THEN 0 ELSE quantity END
                    WHERE account_id = :account_id""", {"account_id": account_id})
            execute(connection, """INSERT INTO paper_account_controls
                    (account_id, kill_switch_engaged, version, updated_by, updated_at)
                    VALUES (:account_id, FALSE, 1, :owner, :at)
                    ON CONFLICT(account_id) DO NOTHING""",
                    {"account_id": account_id, "owner": account["owner_principal"], "at": _now()})
            funding_id = f"paper_ledger_{_hash({'migration': 'paper-execution-v2', 'account_id': account_id, 'type': 'funding'})[:32]}"
            execute(connection, """INSERT INTO paper_ledger_entries
                    (entry_id, account_id, entry_type, amount, cash_delta, details_json, created_at)
                    VALUES (:entry_id, :account_id, 'initial_funding', :amount, :amount,
                            :details, :at) ON CONFLICT(entry_id) DO NOTHING""",
                    {"entry_id": funding_id, "account_id": account_id, "amount": initial_cash,
                     "details": {"migration": "paper-execution-v2"}, "at": account["created_at"]})
            for order in orders:
                fill = fetch_one(connection, "SELECT * FROM paper_fills WHERE order_id = :order_id", {"order_id": order["order_id"]})
                if fill is None:
                    continue
                amount = Decimal(str(fill["price"])) * int(fill["quantity"])
                fees = Decimal(str(fill["fees"])) + Decimal(str(fill["tax"]))
                cash_delta = -(amount + fees) if fill["side"] == "buy" else amount - fees
                entry_id = f"paper_ledger_{_hash({'migration': 'paper-execution-v2', 'fill_id': fill['fill_id']})[:32]}"
                execute(connection, """INSERT INTO paper_ledger_entries
                        (entry_id, account_id, entry_type, trade_date, order_id, fill_id,
                         symbol, side, quantity, price, amount, fees, cash_delta,
                         details_json, created_at)
                        VALUES (:entry_id, :account_id, 'fill', :trade_date, :order_id,
                                :fill_id, :symbol, :side, :quantity, :price, :amount,
                                :fees, :cash_delta, :details, :at)
                        ON CONFLICT(entry_id) DO NOTHING""",
                        {"entry_id": entry_id, "account_id": account_id,
                         "trade_date": fill["trade_date"], "order_id": order["order_id"],
                         "fill_id": fill["fill_id"], "symbol": fill["symbol"], "side": fill["side"],
                         "quantity": fill["quantity"], "price": fill["price"], "amount": amount,
                         "fees": fees, "cash_delta": cash_delta,
                         "details": {"migration": "paper-execution-v2"}, "at": fill["created_at"]})
                execute(connection, """UPDATE paper_orders SET cash_delta = :cash_delta,
                        fill_id = :fill_id, execution_contract_version = 'paper-execution-v2'
                        WHERE order_id = :order_id""",
                        {"cash_delta": cash_delta, "fill_id": fill["fill_id"], "order_id": order["order_id"]})
        identities = execute(connection, """SELECT account_id, owner_principal, status,
                initial_cash, cash FROM paper_accounts ORDER BY account_id""")
        execute(connection, """INSERT INTO paper_domain_migration_runs
                (migration_id, source_count, migrated_count, quarantined_count,
                 manifest_sha256, completed_at)
                VALUES ('paper-execution-v2', :source, :migrated, :quarantined, :sha, :at)
                ON CONFLICT(migration_id) DO UPDATE SET source_count = excluded.source_count,
                migrated_count = excluded.migrated_count,
                quarantined_count = excluded.quarantined_count,
                manifest_sha256 = excluded.manifest_sha256,
                completed_at = excluded.completed_at""",
                {"source": len(rows), "migrated": migrated, "quarantined": quarantined,
                 "sha": _hash(identities), "at": _now()})

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
        cash = _money(payload.get("cash"), "cash", positive=True)
        existing = self._fetch_one(
            "SELECT * FROM paper_accounts WHERE owner_principal = :owner AND name = :name AND status <> 'deleted'",
            {"owner": owner, "name": name},
        )
        if existing is not None:
            raise PaperTradingConflict("account name already exists")
        now = _now()
        account_id = _new_id("paper_account")
        with self._transaction() as connection:
            execute(
                connection,
                """INSERT INTO paper_accounts
                (account_id, owner_principal, name, cash, initial_cash, equity,
                 realized_pnl, currency, status, created_at, updated_at, version)
                VALUES (:account_id, :owner, :name, :cash, :cash, :cash,
                        0, 'CNY', 'active', :created_at, :updated_at, 1)""",
                {"account_id": account_id, "owner": owner, "name": name,
                 "cash": cash, "created_at": now, "updated_at": now},
            )
            execute(
                connection,
                """INSERT INTO paper_account_controls
                   (account_id, kill_switch_engaged, version, updated_by, updated_at)
                   VALUES (:account_id, FALSE, 1, :owner, :at)""",
                {"account_id": account_id, "owner": owner, "at": now},
            )
            execute(
                connection,
                """INSERT INTO paper_ledger_entries
                   (entry_id, account_id, entry_type, amount, cash_delta,
                    details_json, created_at)
                   VALUES (:entry_id, :account_id, 'initial_funding', :cash, :cash,
                           :details, :at)""",
                {"entry_id": _new_id("paper_ledger"), "account_id": account_id,
                 "cash": cash, "details": {"currency": "CNY"}, "at": now},
            )
        return self.get_account(account_id, trusted_owner=owner)

    def get_account(self, account_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        account_id = _id(account_id, prefix="paper_account")
        row = self._fetch_one(
            "SELECT * FROM paper_accounts WHERE account_id = :account_id AND status <> 'deleted'",
            {"account_id": account_id},
        )
        if row is None:
            raise PaperTradingNotFound("paper account not found")
        if trusted_owner and row["owner_principal"] != trusted_owner:
            raise PaperTradingNotFound("paper account not found")
        return dict(row)

    def list_accounts(self, *, trusted_owner: str | None = None) -> dict[str, object]:
        if trusted_owner:
            rows = self._execute(
                "SELECT * FROM paper_accounts WHERE owner_principal = :owner_principal AND status <> 'deleted' ORDER BY created_at DESC, account_id DESC",
                {"owner_principal": trusted_owner},
            )
        else:
            rows = self._execute("SELECT * FROM paper_accounts WHERE status <> 'deleted' ORDER BY created_at DESC, account_id DESC")
        return {"accounts": [dict(row) for row in rows]}

    def delete_account(
        self, account_id: object, payload: object, *, trusted_owner: str | None = None,
        trusted_actor: str | None = None,
    ) -> dict[str, object]:
        """Tombstone an account while retaining its immutable trading and audit history."""

        if not isinstance(payload, dict):
            raise ValueError("account deletion request must be an object")
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        if owner is None:
            raise PaperTradingForbidden("account deletion requires a trusted owner")
        actor = _principal(trusted_actor or owner, field="actor_principal")
        account_id = _id(account_id, prefix="paper_account")
        expected = _positive_int(payload.get("expected_version"), "expected_version")
        key = _idempotency(payload.get("idempotency_key"))
        reason = _text(payload.get("reason") or "用户删除模拟账户", field="reason", max_length=256)
        request_hash = _hash({
            "account_id": account_id,
            "expected_version": expected,
            "reason": reason,
        })
        with self._transaction() as connection:
            prior = fetch_one(
                connection,
                "SELECT * FROM paper_account_audit WHERE owner_principal = :owner AND idempotency_key = :key",
                {"owner": owner, "key": key},
            )
            if prior is not None:
                if prior["action"] != "account_deleted" or prior["request_hash"] != request_hash:
                    raise PaperTradingConflict("account deletion idempotency key was reused")
                return {"account_id": account_id, "deleted": True}
            account = fetch_one(
                connection,
                "SELECT * FROM paper_accounts WHERE account_id = :account_id",
                {"account_id": account_id},
            )
            if account is None or account["owner_principal"] != owner or account["status"] == "deleted":
                raise PaperTradingNotFound("paper account not found")
            if int(account["version"]) != expected:
                raise PaperTradingConflict("paper account version is stale")
            now = _now()
            tombstone_name = f"{account['name']} · deleted · {account_id[-8:]}"
            execute(
                connection,
                """UPDATE paper_accounts SET name = :name, status = 'deleted', deleted_at = :at,
                   updated_at = :at, version = version + 1 WHERE account_id = :account_id""",
                {"name": tombstone_name, "at": now, "account_id": account_id},
            )
            execute(
                connection,
                """INSERT INTO paper_account_audit
                   (audit_id, account_id, owner_principal, actor_principal, action,
                    idempotency_key, request_hash, details_json, created_at)
                   VALUES (:audit_id, :account_id, :owner, :actor, 'account_deleted',
                           :key, :request_hash, :details, :at)""",
                {"audit_id": _new_id("paper_audit"), "account_id": account_id,
                 "owner": owner, "actor": actor, "key": key, "request_hash": request_hash,
                 "details": {"reason": reason, "previous_name": account["name"],
                             "previous_status": account["status"], "version": expected + 1}, "at": now},
            )
        return {"account_id": account_id, "deleted": True}

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
        if domain not in {"paper_order", "backtest", "research", "signal_producer"}:
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
        price = float(_money(payload.get("price"), "price", positive=True))
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
            if account is None or account["owner_principal"] != owner or account["status"] != "active":
                raise PaperTradingNotFound("paper account not found")
            pool = fetch_one(connection, "SELECT * FROM stock_pools WHERE pool_id = :pool_id", {"pool_id": pool_id})
            if pool is None or pool["owner_principal"] != owner:
                raise PaperTradingForbidden("stock pool is not owned by this principal")
            if pool["status"] != "active" or not pool["current_snapshot_id"]:
                raise PaperTradingForbidden("stock pool is not active")
            snapshot_id = account.get("bound_snapshot_id") or pool["current_snapshot_id"]
            if account.get("bound_snapshot_id") and (
                account.get("bound_pool_id") != pool_id or account.get("bound_snapshot_id") != snapshot_id
            ):
                raise PaperTradingConflict("paper account is bound to another stock pool snapshot")
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

            controls = fetch_one(connection, "SELECT * FROM paper_account_controls WHERE account_id = :account_id", {"account_id": account_id})
            if controls is None:
                controls = {"kill_switch_engaged": False, "max_order_notional": None, "version": 1}
                execute(connection, """INSERT INTO paper_account_controls
                        (account_id, kill_switch_engaged, version, updated_by, updated_at)
                        VALUES (:account_id, FALSE, 1, :owner, :at)""",
                        {"account_id": account_id, "owner": owner, "at": _now()})
            notional = _money(price * quantity, "notional")
            risk_evaluation = {
                "control_version": int(controls["version"]),
                "kill_switch_engaged": bool(controls["kill_switch_engaged"]),
                "max_order_notional": _money_text(controls["max_order_notional"]) if controls.get("max_order_notional") is not None else None,
                "order_notional": _money_text(notional),
                "result": "passed",
            }
            if controls["kill_switch_engaged"]:
                blocked = "risk_kill_switch"
            elif controls.get("max_order_notional") is not None and notional > Decimal(str(controls["max_order_notional"])):
                blocked = "risk_max_order_notional"
            else:
                blocked = self._blocked_reason(
                    connection, account, side, quantity, price, trade_date, is_suspended, up_limit, down_limit, symbol
                )
            if blocked and blocked.startswith("risk_"):
                risk_evaluation["result"] = "blocked"
                risk_evaluation["reason"] = blocked
            now = _now()
            order_id = _new_id("paper_order")
            fill_id: str | None = None
            if blocked is None:
                fees, tax, cash_delta = self._execution_cost(side, quantity, price)
                status = "filled"
                new_cash = Decimal(str(account["cash"])) + Decimal(str(cash_delta))
                execute(
                    connection,
                    """UPDATE paper_accounts SET cash = :cash, equity = :cash,
                       bound_pool_id = COALESCE(bound_pool_id, :pool_id),
                       bound_snapshot_id = COALESCE(bound_snapshot_id, :snapshot_id),
                       updated_at = :updated_at, version = version + 1
                       WHERE account_id = :account_id""",
                    {"cash": new_cash, "pool_id": pool_id, "snapshot_id": snapshot_id,
                     "updated_at": now, "account_id": account_id},
                )
                self._upsert_position(connection, account_id, symbol, side, quantity, trade_date, price)
                fill_id = _new_id("paper_fill")
                execute(
                    connection,
                    """INSERT INTO paper_fills
                    (fill_id, order_id, account_id, symbol, side, quantity, price, fees, tax, trade_date, created_at)
                    VALUES (:fill_id, :order_id, :account_id, :symbol, :side, :quantity, :price, :fees, :tax, :trade_date, :created_at)""",
                    {"fill_id": fill_id, "order_id": order_id, "account_id": account_id, "symbol": symbol, "side": side, "quantity": quantity, "price": price, "fees": fees, "tax": tax, "trade_date": trade_date, "created_at": now},
                )
                execute(
                    connection,
                    """INSERT INTO paper_ledger_entries
                       (entry_id, account_id, entry_type, trade_date, order_id,
                        fill_id, symbol, side, quantity, price, amount, fees,
                        cash_delta, details_json, created_at)
                       VALUES (:entry_id, :account_id, 'fill', :trade_date, :order_id,
                               :fill_id, :symbol, :side, :quantity, :price, :amount,
                               :fees, :cash_delta, :details, :at)""",
                    {"entry_id": _new_id("paper_ledger"), "account_id": account_id,
                     "trade_date": trade_date, "order_id": order_id, "fill_id": fill_id,
                     "symbol": symbol, "side": side, "quantity": quantity, "price": price,
                     "amount": notional, "fees": Decimal(str(fees)) + Decimal(str(tax)),
                     "cash_delta": cash_delta, "details": {"fees": fees, "tax": tax}, "at": now},
                )
                blocked_reason = None
            else:
                status = "blocked"
                fees = 0.0
                tax = 0.0
                cash_delta = 0.0
                blocked_reason = blocked
            events = [{"event": "submitted", "at": now}, {"event": status, "at": now, "reason": blocked_reason}]
            decision_provenance = {
                "source": "product_owner" if payload.get("approval_id") is None else "approved_agent_action",
                "approval_id": payload.get("approval_id"),
                "stock_pool_snapshot_id": snapshot_id,
                "execution_contract_version": "paper-execution-v2",
            }
            execute(
                connection,
                """INSERT INTO paper_orders
                (order_id, account_id, pool_id, stock_pool_snapshot_id, symbol, side, quantity, price, status, blocked_reason,
                 fees, tax, cash_delta, trade_date, idempotency_key, request_hash, created_at,
                 fill_id, risk_evaluation_json, decision_provenance_json, events_json, execution_contract_version)
                VALUES (:order_id, :account_id, :pool_id, :snapshot_id, :symbol, :side, :quantity, :price, :status, :blocked_reason,
                        :fees, :tax, :cash_delta, :trade_date, :idempotency_key, :request_hash, :created_at,
                        :fill_id, :risk, :provenance, :events, 'paper-execution-v2')""",
                {"order_id": order_id, "account_id": account_id, "pool_id": pool_id, "snapshot_id": snapshot_id, "symbol": symbol, "side": side, "quantity": quantity, "price": price, "status": status, "blocked_reason": blocked_reason, "fees": fees, "tax": tax, "cash_delta": cash_delta, "trade_date": trade_date, "idempotency_key": key, "request_hash": request_hash, "created_at": now, "fill_id": fill_id, "risk": risk_evaluation, "provenance": decision_provenance, "events": events},
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
        if account is None or account["status"] == "deleted" or (trusted_owner and account["owner_principal"] != trusted_owner):
            raise PaperTradingNotFound("paper account not found")
        rows = self._execute(
            "SELECT * FROM paper_orders WHERE account_id = :account_id ORDER BY created_at DESC, order_id DESC",
            {"account_id": account_id},
        )
        return {"orders": [self._order_row(row) for row in rows]}

    def list_positions(self, account_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        account_id = _id(account_id, prefix="paper_account")
        account = self._fetch_one("SELECT * FROM paper_accounts WHERE account_id = :account_id", {"account_id": account_id})
        if account is None or account["status"] == "deleted" or (trusted_owner and account["owner_principal"] != trusted_owner):
            raise PaperTradingNotFound("paper account not found")
        rows = self._execute(
            "SELECT * FROM paper_positions WHERE account_id = :account_id ORDER BY symbol ASC",
            {"account_id": account_id},
        )
        return {"positions": [dict(row) for row in rows]}

    def list_fills(self, account_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        account_id = _id(account_id, prefix="paper_account")
        account = self._fetch_one("SELECT * FROM paper_accounts WHERE account_id = :account_id", {"account_id": account_id})
        if account is None or account["status"] == "deleted" or (trusted_owner and account["owner_principal"] != trusted_owner):
            raise PaperTradingNotFound("paper account not found")
        rows = self._execute(
            "SELECT * FROM paper_fills WHERE account_id = :account_id ORDER BY created_at DESC, fill_id DESC",
            {"account_id": account_id},
        )
        return {"fills": [dict(row) for row in rows]}

    def get_order(self, account_id: object, order_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        account = self.get_account(account_id, trusted_owner=trusted_owner)
        order_id = _id(order_id, prefix="paper_order")
        row = self._fetch_one(
            "SELECT * FROM paper_orders WHERE account_id = :account_id AND order_id = :order_id",
            {"account_id": account["account_id"], "order_id": order_id},
        )
        if row is None:
            raise PaperTradingNotFound("paper order not found")
        result = self._order_row(row)
        result["fill"] = self._fetch_one(
            "SELECT * FROM paper_fills WHERE order_id = :order_id", {"order_id": order_id}
        )
        return result

    def get_controls(self, account_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        account = self.get_account(account_id, trusted_owner=trusted_owner)
        row = self._fetch_one(
            "SELECT * FROM paper_account_controls WHERE account_id = :account_id",
            {"account_id": account["account_id"]},
        )
        if row is None:
            raise PaperTradingNotFound("paper account controls not found")
        return dict(row)

    def update_controls(
        self, account_id: object, payload: object, *, trusted_owner: str | None = None,
        trusted_actor: str | None = None,
    ) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("control request must be an object")
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        if owner is None:
            raise PaperTradingForbidden("control update requires a trusted owner")
        actor = _principal(trusted_actor or owner, field="actor_principal")
        account_id = _id(account_id, prefix="paper_account")
        expected = _positive_int(payload.get("expected_version"), "expected_version")
        key = _idempotency(payload.get("idempotency_key"))
        engaged = payload.get("kill_switch_engaged")
        if not isinstance(engaged, bool):
            raise ValueError("kill_switch_engaged must be a boolean")
        reason = _optional_text(payload.get("kill_switch_reason"), field="kill_switch_reason", max_length=256)
        raw_limit = payload.get("max_order_notional")
        limit = None if raw_limit is None or raw_limit == "" else _money(raw_limit, "max_order_notional", positive=True)
        request = {"account_id": account_id, "kill_switch_engaged": engaged,
                   "kill_switch_reason": reason, "max_order_notional": _money_text(limit) if limit is not None else None}
        request_hash = _hash(request)
        with self._transaction() as connection:
            account = fetch_one(connection, "SELECT * FROM paper_accounts WHERE account_id = :account_id", {"account_id": account_id})
            if account is None or account["owner_principal"] != owner or account["status"] != "active":
                raise PaperTradingNotFound("paper account not found")
            audit = fetch_one(connection, "SELECT * FROM paper_account_audit WHERE owner_principal = :owner AND idempotency_key = :key",
                              {"owner": owner, "key": key})
            if audit is not None:
                if audit["request_hash"] != request_hash:
                    raise PaperTradingConflict("control idempotency key was reused")
                return self.get_controls(account_id, trusted_owner=owner)
            controls = fetch_one(connection, "SELECT * FROM paper_account_controls WHERE account_id = :account_id", {"account_id": account_id})
            if controls is None or int(controls["version"]) != expected:
                raise PaperTradingConflict("paper control version is stale")
            new_version = expected + 1
            now = _now()
            execute(connection, """UPDATE paper_account_controls SET kill_switch_engaged = :engaged,
                    kill_switch_reason = :reason, max_order_notional = :limit, version = :version,
                    updated_by = :actor, updated_at = :at WHERE account_id = :account_id""",
                    {"engaged": engaged, "reason": reason, "limit": limit, "version": new_version,
                     "actor": actor, "at": now, "account_id": account_id})
            execute(connection, """INSERT INTO paper_account_audit
                    (audit_id, account_id, owner_principal, actor_principal, action,
                     idempotency_key, request_hash, details_json, created_at)
                    VALUES (:audit_id, :account_id, :owner, :actor, 'controls_updated',
                            :key, :request_hash, :details, :at)""",
                    {"audit_id": _new_id("paper_audit"), "account_id": account_id,
                     "owner": owner, "actor": actor, "key": key, "request_hash": request_hash,
                     "details": {"version": new_version}, "at": now})
        return self.get_controls(account_id, trusted_owner=owner)

    def rebind_account(
        self, account_id: object, payload: object, *, trusted_owner: str | None = None,
        trusted_actor: str | None = None,
    ) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("rebind request must be an object")
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        if owner is None:
            raise PaperTradingForbidden("rebind requires a trusted owner")
        actor = _principal(trusted_actor or owner, field="actor_principal")
        account_id = _id(account_id, prefix="paper_account")
        pool_id = _id(payload.get("pool_id"), prefix="stock_pool")
        expected = _positive_int(payload.get("expected_version"), "expected_version")
        key = _idempotency(payload.get("idempotency_key"))
        request_hash = _hash({"account_id": account_id, "pool_id": pool_id, "expected_version": expected})
        with self._transaction() as connection:
            account = fetch_one(connection, "SELECT * FROM paper_accounts WHERE account_id = :account_id", {"account_id": account_id})
            if account is None or account["owner_principal"] != owner or account["status"] != "active":
                raise PaperTradingNotFound("paper account not found")
            if int(account["version"]) != expected:
                raise PaperTradingConflict("paper account version is stale")
            position_count = fetch_one(connection, "SELECT COUNT(*) AS count FROM paper_positions WHERE account_id = :account_id",
                                       {"account_id": account_id})
            if int(position_count["count"] if position_count else 0) != 0:
                raise PaperTradingConflict("paper account with positions cannot be rebound")
            pool = fetch_one(connection, "SELECT * FROM stock_pools WHERE pool_id = :pool_id", {"pool_id": pool_id})
            if pool is None or pool["owner_principal"] != owner or pool["status"] != "active" or not pool["current_snapshot_id"]:
                raise PaperTradingForbidden("stock pool is not available for binding")
            existing = fetch_one(connection, "SELECT * FROM paper_account_audit WHERE owner_principal = :owner AND idempotency_key = :key",
                                 {"owner": owner, "key": key})
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise PaperTradingConflict("rebind idempotency key was reused")
                return self.get_account(account_id, trusted_owner=owner)
            now = _now()
            execute(connection, """UPDATE paper_accounts SET bound_pool_id = :pool_id,
                    bound_snapshot_id = :snapshot_id, version = version + 1,
                    updated_at = :at WHERE account_id = :account_id""",
                    {"pool_id": pool_id, "snapshot_id": pool["current_snapshot_id"], "at": now, "account_id": account_id})
            execute(connection, """INSERT INTO paper_account_audit
                    (audit_id, account_id, owner_principal, actor_principal, action,
                     idempotency_key, request_hash, details_json, created_at)
                    VALUES (:audit_id, :account_id, :owner, :actor, 'universe_rebound',
                            :key, :request_hash, :details, :at)""",
                    {"audit_id": _new_id("paper_audit"), "account_id": account_id, "owner": owner,
                     "actor": actor, "key": key, "request_hash": request_hash,
                     "details": {"pool_id": pool_id, "snapshot_id": pool["current_snapshot_id"]}, "at": now})
        return self.get_account(account_id, trusted_owner=owner)

    def list_ledger(self, account_id: object, *, trusted_owner: str | None = None, limit: int = 200) -> dict[str, object]:
        account = self.get_account(account_id, trusted_owner=trusted_owner)
        limit = max(1, min(int(limit), 500))
        rows = self._execute(
            """SELECT * FROM paper_ledger_entries WHERE account_id = :account_id
               ORDER BY created_at DESC, entry_id DESC LIMIT :limit""",
            {"account_id": account["account_id"], "limit": limit},
        )
        return {"ledger": [dict(row) for row in rows]}

    def list_snapshots(self, account_id: object, *, trusted_owner: str | None = None, limit: int = 200) -> dict[str, object]:
        account = self.get_account(account_id, trusted_owner=trusted_owner)
        limit = max(1, min(int(limit), 500))
        rows = self._execute(
            """SELECT * FROM paper_account_snapshots WHERE account_id = :account_id
               ORDER BY trade_date DESC LIMIT :limit""",
            {"account_id": account["account_id"], "limit": limit},
        )
        return {"snapshots": [dict(row) for row in rows]}

    def settle_account(
        self, account_id: object, payload: object, *, trusted_owner: str | None = None,
        trusted_actor: str | None = None,
    ) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("settlement request must be an object")
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        if owner is None:
            raise PaperTradingForbidden("settlement requires a trusted owner")
        actor = _principal(trusted_actor or owner, field="actor_principal")
        account_id = _id(account_id, prefix="paper_account")
        trade_date = _trade_date(payload.get("trade_date"))
        expected = _positive_int(payload.get("expected_version"), "expected_version")
        key = _idempotency(payload.get("idempotency_key"))
        raw_marks = payload.get("marks")
        if not isinstance(raw_marks, dict):
            raise ValueError("marks must be an object keyed by canonical symbol")
        marks = {_symbol(symbol): _money(value, f"marks.{symbol}", positive=True) for symbol, value in raw_marks.items()}
        request = {"account_id": account_id, "trade_date": trade_date,
                   "marks": {symbol: _money_text(value) for symbol, value in sorted(marks.items())}}
        request_hash = _hash(request)
        with self._transaction() as connection:
            account = fetch_one(connection, "SELECT * FROM paper_accounts WHERE account_id = :account_id", {"account_id": account_id})
            if account is None or account["owner_principal"] != owner or account["status"] != "active":
                raise PaperTradingNotFound("paper account not found")
            existing = fetch_one(connection, "SELECT * FROM paper_account_snapshots WHERE account_id = :account_id AND trade_date = :trade_date",
                                 {"account_id": account_id, "trade_date": trade_date})
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise PaperTradingConflict("paper settlement cannot rewrite a daily snapshot")
                return dict(existing)
            if int(account["version"]) != expected:
                raise PaperTradingConflict("paper account version is stale")
            if account.get("last_settlement_date") and trade_date <= account["last_settlement_date"]:
                raise PaperTradingConflict("settlement date must be later than the previous settlement")
            latest_trade = fetch_one(connection, "SELECT MAX(trade_date) AS trade_date FROM paper_orders WHERE account_id = :account_id",
                                     {"account_id": account_id})
            if latest_trade and latest_trade.get("trade_date") and trade_date < latest_trade["trade_date"]:
                raise PaperTradingConflict("settlement date cannot precede a recorded order")
            positions = execute(connection, "SELECT * FROM paper_positions WHERE account_id = :account_id ORDER BY symbol",
                                {"account_id": account_id})
            symbols = {row["symbol"] for row in positions}
            if set(marks) != symbols:
                raise ValueError("marks must contain every and only open position symbol")
            position_payload: list[dict[str, object]] = []
            market_value = Decimal("0")
            unrealized = Decimal("0")
            for row in positions:
                symbol = row["symbol"]
                mark = marks[symbol]
                quantity = int(row["quantity"])
                sellable = int(row.get("sellable_quantity") or 0)
                locked = int(row.get("locked_quantity") or 0)
                if locked and row.get("last_buy_date") and trade_date > row["last_buy_date"]:
                    sellable += locked
                    locked = 0
                cost = Decimal(str(row.get("average_cost") or 0))
                market_value += mark * quantity
                unrealized += (mark - cost) * quantity
                provenance = {"source": "manual", "trade_date": trade_date, "actor_principal": actor}
                execute(connection, """UPDATE paper_positions SET sellable_quantity = :sellable,
                        locked_quantity = :locked, market_price = :mark,
                        mark_provenance_json = :provenance WHERE account_id = :account_id AND symbol = :symbol""",
                        {"sellable": sellable, "locked": locked, "mark": mark, "provenance": provenance,
                         "account_id": account_id, "symbol": symbol})
                position_payload.append({"symbol": symbol, "quantity": quantity,
                                         "sellable_quantity": sellable, "locked_quantity": locked,
                                         "average_cost": _money_text(cost), "market_price": _money_text(mark)})
            cash = Decimal(str(account["cash"]))
            equity = (cash + market_value).quantize(MONEY_QUANTUM)
            previous = fetch_one(connection, """SELECT equity FROM paper_account_snapshots
                    WHERE account_id = :account_id ORDER BY trade_date DESC LIMIT 1""", {"account_id": account_id})
            baseline = Decimal(str(previous["equity"])) if previous else Decimal(str(account["initial_cash"]))
            daily_pnl = (equity - baseline).quantize(MONEY_QUANTUM)
            daily_return = None if baseline == 0 else (daily_pnl / baseline).quantize(Decimal("0.000000000001"))
            snapshot_content = {"account_id": account_id, "trade_date": trade_date, "cash": _money_text(cash),
                                "market_value": _money_text(market_value), "equity": _money_text(equity),
                                "positions": position_payload, "mark_source": "manual"}
            fingerprint = _hash(snapshot_content)
            snapshot_id = f"paper_snapshot_{fingerprint}"
            now = _now()
            execute(connection, """INSERT INTO paper_account_snapshots
                    (snapshot_id, account_id, trade_date, cash, market_value, equity,
                     realized_pnl, unrealized_pnl, daily_pnl, daily_return, positions_json,
                     mark_provenance_json, snapshot_fingerprint, request_hash,
                     idempotency_key, created_at)
                    VALUES (:snapshot_id, :account_id, :trade_date, :cash, :market_value,
                            :equity, :realized, :unrealized, :daily_pnl, :daily_return,
                            :positions, :provenance, :fingerprint, :request_hash, :key, :at)""",
                    {"snapshot_id": snapshot_id, "account_id": account_id, "trade_date": trade_date,
                     "cash": cash, "market_value": market_value, "equity": equity,
                     "realized": account.get("realized_pnl") or 0, "unrealized": unrealized,
                     "daily_pnl": daily_pnl, "daily_return": daily_return, "positions": position_payload,
                     "provenance": {"source": "manual", "actor_principal": actor},
                     "fingerprint": fingerprint, "request_hash": request_hash, "key": key, "at": now})
            execute(connection, """UPDATE paper_accounts SET equity = :equity,
                    last_settlement_date = :trade_date, version = version + 1,
                    updated_at = :at WHERE account_id = :account_id""",
                    {"equity": equity, "trade_date": trade_date, "at": now, "account_id": account_id})
            execute(connection, """INSERT INTO paper_ledger_entries
                    (entry_id, account_id, entry_type, trade_date, snapshot_id,
                     amount, cash_delta, details_json, created_at)
                    VALUES (:entry_id, :account_id, 'settlement', :trade_date,
                            :snapshot_id, 0, 0, :details, :at)""",
                    {"entry_id": _new_id("paper_ledger"), "account_id": account_id,
                     "trade_date": trade_date, "snapshot_id": snapshot_id,
                     "details": {"equity": _money_text(equity), "snapshot_fingerprint": fingerprint}, "at": now})
            execute(connection, """INSERT INTO paper_account_audit
                    (audit_id, account_id, owner_principal, actor_principal, action,
                     idempotency_key, request_hash, details_json, created_at)
                    VALUES (:audit_id, :account_id, :owner, :actor, 'settled',
                            :key, :request_hash, :details, :at)""",
                    {"audit_id": _new_id("paper_audit"), "account_id": account_id,
                     "owner": owner, "actor": actor, "key": key, "request_hash": request_hash,
                     "details": {"snapshot_id": snapshot_id}, "at": now})
            result = fetch_one(connection, "SELECT * FROM paper_account_snapshots WHERE snapshot_id = :snapshot_id",
                               {"snapshot_id": snapshot_id})
        return dict(result)

    def export_bundle(self, account_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        if owner is None:
            raise PaperTradingForbidden("bundle export requires a trusted owner")
        account = self.get_account(account_id, trusted_owner=owner)
        account_id = str(account["account_id"])
        public_account = {key: account.get(key) for key in (
            "name", "initial_cash", "cash", "equity", "realized_pnl", "currency",
            "status", "last_settlement_date", "bound_pool_id", "bound_snapshot_id",
        )}
        controls = self.get_controls(account_id, trusted_owner=owner)
        public_controls = {key: controls.get(key) for key in (
            "kill_switch_engaged", "kill_switch_reason", "max_order_notional", "version",
        )}
        sections = _bundle_json_value({
            "account": public_account,
            "controls": public_controls,
            "positions": self.list_positions(account_id, trusted_owner=owner)["positions"],
            "orders": self.list_orders(account_id, trusted_owner=owner)["orders"],
            "fills": self.list_fills(account_id, trusted_owner=owner)["fills"],
            "ledger": self.list_ledger(account_id, trusted_owner=owner, limit=500)["ledger"],
            "snapshots": self.list_snapshots(account_id, trusted_owner=owner, limit=500)["snapshots"],
        })
        assert isinstance(sections, dict)
        manifest = {
            name: {"count": len(value) if isinstance(value, list) else 1, "sha256": _hash(value)}
            for name, value in sections.items()
        }
        semantic = {"schema_version": BUNDLE_SCHEMA_VERSION, "manifest": manifest, "sections": sections}
        bundle_sha256 = _hash(semantic)
        self._execute(
            """INSERT INTO paper_transfer_audit
               (transfer_id, account_id, owner_principal, direction, bundle_sha256,
                details_json, created_at)
               VALUES (:transfer_id, :account_id, :owner, 'export', :sha, :details, :at)""",
            {"transfer_id": _new_id("paper_transfer"), "account_id": account_id,
             "owner": owner, "sha": bundle_sha256,
             "details": {"schema_version": BUNDLE_SCHEMA_VERSION}, "at": _now()},
        )
        return {**semantic, "bundle_sha256": bundle_sha256, "exported_at": _now()}

    def import_bundle(
        self, payload: object, *, trusted_owner: str | None = None,
        trusted_actor: str | None = None,
    ) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("paper account bundle must be an object")
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        if owner is None:
            raise PaperTradingForbidden("bundle import requires a trusted owner")
        actor = _principal(trusted_actor or owner, field="actor_principal")
        if payload.get("schema_version") != BUNDLE_SCHEMA_VERSION:
            raise ValueError("unsupported paper account bundle schema")
        manifest = payload.get("manifest")
        sections = payload.get("sections")
        if not isinstance(manifest, dict) or not isinstance(sections, dict):
            raise ValueError("paper account bundle manifest or sections are missing")
        expected_names = {"account", "controls", "positions", "orders", "fills", "ledger", "snapshots"}
        if set(sections) != expected_names or set(manifest) != expected_names:
            raise ValueError("paper account bundle section set is invalid")
        forbidden_fragments = ("owner", "password", "secret", "token", "credential", "authorization", "dsh")
        def reject_authority(value: object) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    normalized = str(key).lower().replace("_", "")
                    if any(fragment in normalized for fragment in forbidden_fragments):
                        raise ValueError("paper account bundle contains authority or credential fields")
                    reject_authority(nested)
            elif isinstance(value, list):
                for nested in value:
                    reject_authority(nested)
        reject_authority(sections)
        for name in expected_names:
            entry = manifest[name]
            value = sections[name]
            if not isinstance(entry, dict) or entry.get("sha256") != _hash(value):
                raise ValueError(f"paper account bundle section {name} failed digest validation")
            count = len(value) if isinstance(value, list) else 1
            if count > 500 or entry.get("count") != count:
                raise ValueError(f"paper account bundle section {name} failed count validation")
        semantic = {"schema_version": BUNDLE_SCHEMA_VERSION, "manifest": manifest, "sections": sections}
        bundle_sha256 = _hash(semantic)
        if payload.get("bundle_sha256") != bundle_sha256:
            raise ValueError("paper account bundle digest is invalid")
        account_data = sections["account"]
        controls_data = sections["controls"]
        if not isinstance(account_data, dict) or not isinstance(controls_data, dict):
            raise ValueError("paper account bundle account sections are invalid")
        source_name = _text(account_data.get("name"), field="name", max_length=96)
        name = f"{source_name} · 导入 {bundle_sha256[:8]}"
        if self._fetch_one("SELECT account_id FROM paper_accounts WHERE owner_principal = :owner AND name = :name",
                           {"owner": owner, "name": name}) is not None:
            raise PaperTradingConflict("paper account name already exists; import never overwrites")
        initial_cash = _money(account_data.get("initial_cash"), "initial_cash", positive=True)
        cash = _money(account_data.get("cash"), "cash")
        equity = _money(account_data.get("equity"), "equity")
        realized = _signed_money(account_data.get("realized_pnl", 0), "realized_pnl")
        pool_id = account_data.get("bound_pool_id")
        snapshot_id = account_data.get("bound_snapshot_id")
        if (pool_id is None) != (snapshot_id is None):
            raise ValueError("paper account bundle binding is incomplete")
        if pool_id is not None:
            pool_id = _id(pool_id, prefix="stock_pool")
            snapshot_id = _text(snapshot_id, field="bound_snapshot_id", max_length=96)
            if re.fullmatch(r"stock_pool_snapshot_[0-9a-f]{64}", snapshot_id) is None:
                raise ValueError("bound_snapshot_id is invalid")
            snapshot = self.get_pool_snapshot(snapshot_id, trusted_owner=owner, include_members=False)
            if snapshot["pool_id"] != pool_id:
                raise ValueError("paper account bundle binding is invalid")
        account_id = _new_id("paper_account")
        now = _now()
        with self._transaction() as connection:
            execute(connection, """INSERT INTO paper_accounts
                    (account_id, owner_principal, name, cash, initial_cash, equity,
                     realized_pnl, currency, status, last_settlement_date,
                     bound_pool_id, bound_snapshot_id, created_at, updated_at, version)
                    VALUES (:account_id, :owner, :name, :cash, :initial_cash, :equity,
                            :realized, 'CNY', 'active', :last_settlement_date,
                            :pool_id, :snapshot_id, :at, :at, 1)""",
                    {"account_id": account_id, "owner": owner, "name": name, "cash": cash,
                     "initial_cash": initial_cash, "equity": equity, "realized": realized,
                     "last_settlement_date": account_data.get("last_settlement_date"),
                     "pool_id": pool_id, "snapshot_id": snapshot_id, "at": now})
            limit_value = controls_data.get("max_order_notional")
            max_notional = None if limit_value is None or limit_value == "" else _money(limit_value, "max_order_notional", positive=True)
            execute(connection, """INSERT INTO paper_account_controls
                    (account_id, kill_switch_engaged, kill_switch_reason,
                     max_order_notional, version, updated_by, updated_at)
                    VALUES (:account_id, :engaged, :reason, :limit, 1, :actor, :at)""",
                    {"account_id": account_id, "engaged": bool(controls_data.get("kill_switch_engaged", False)),
                     "reason": controls_data.get("kill_switch_reason"), "limit": max_notional,
                     "actor": actor, "at": now})
            positions = sections["positions"]
            if not isinstance(positions, list):
                raise ValueError("positions section must be a list")
            for item in positions:
                if not isinstance(item, dict):
                    raise ValueError("position must be an object")
                symbol = _symbol(item.get("symbol"))
                quantity = _positive_int(item.get("quantity"), "quantity")
                sellable = int(item.get("sellable_quantity", 0))
                locked = int(item.get("locked_quantity", quantity - sellable))
                if min(sellable, locked) < 0 or sellable + locked != quantity:
                    raise ValueError("position quantity partition is invalid")
                execute(connection, """INSERT INTO paper_positions
                        (account_id, symbol, quantity, sellable_quantity, locked_quantity,
                         average_cost, market_price, mark_provenance_json, last_buy_date)
                        VALUES (:account_id, :symbol, :quantity, :sellable, :locked,
                                :cost, :mark, :provenance, :last_buy_date)""",
                        {"account_id": account_id, "symbol": symbol, "quantity": quantity,
                         "sellable": sellable, "locked": locked,
                         "cost": _money(item.get("average_cost", 0), "average_cost"),
                         "mark": _money(item["market_price"], "market_price", positive=True) if item.get("market_price") is not None else None,
                         "provenance": {"source": "bundle", "bundle_sha256": bundle_sha256},
                         "last_buy_date": item.get("last_buy_date")})
            order_map: dict[str, str] = {}
            orders = sections["orders"]
            if not isinstance(orders, list):
                raise ValueError("orders section must be a list")
            for item in orders:
                if not isinstance(item, dict) or item.get("status") not in {"filled", "blocked"}:
                    raise ValueError("order section contains an invalid order")
                old_id = str(item.get("order_id") or "")
                new_id = _new_id("paper_order")
                order_map[old_id] = new_id
                execute(connection, """INSERT INTO paper_orders
                        (order_id, account_id, pool_id, stock_pool_snapshot_id, symbol,
                         side, quantity, price, status, blocked_reason, fees, tax,
                         cash_delta, trade_date, idempotency_key, request_hash, created_at,
                         risk_evaluation_json, decision_provenance_json, events_json,
                         execution_contract_version)
                        VALUES (:order_id, :account_id, :pool_id, :snapshot_id, :symbol,
                                :side, :quantity, :price, :status, :blocked, :fees, :tax,
                                :cash_delta, :trade_date, :key, :request_hash, :created_at,
                                :risk, :provenance, :events, 'paper-execution-v2')""",
                        {"order_id": new_id, "account_id": account_id,
                         "pool_id": pool_id, "snapshot_id": snapshot_id,
                         "symbol": _symbol(item.get("symbol")), "side": item.get("side"),
                         "quantity": _positive_int(item.get("quantity"), "quantity"),
                         "price": _money(item.get("price"), "price", positive=True),
                         "status": item.get("status"), "blocked": item.get("blocked_reason"),
                         "fees": _money(item.get("fees", 0), "fees"), "tax": _money(item.get("tax", 0), "tax"),
                         "cash_delta": Decimal(str(item.get("cash_delta", 0))),
                         "trade_date": _trade_date(item.get("trade_date")),
                         "key": f"import-{uuid.uuid4().hex}", "request_hash": _hash(item),
                         "created_at": item.get("created_at") or now,
                         "risk": item.get("risk_evaluation_json") or {},
                         "provenance": {"source": "bundle", "bundle_sha256": bundle_sha256},
                         "events": item.get("events_json") or []})
            fill_map: dict[str, str] = {}
            fills = sections["fills"]
            if not isinstance(fills, list):
                raise ValueError("fills section must be a list")
            for item in fills:
                if not isinstance(item, dict) or str(item.get("order_id")) not in order_map:
                    raise ValueError("fill references an unknown order")
                new_fill = _new_id("paper_fill")
                fill_map[str(item.get("fill_id"))] = new_fill
                new_order = order_map[str(item.get("order_id"))]
                execute(connection, """INSERT INTO paper_fills
                        (fill_id, order_id, account_id, symbol, side, quantity,
                         price, fees, tax, trade_date, created_at)
                        VALUES (:fill_id, :order_id, :account_id, :symbol, :side,
                                :quantity, :price, :fees, :tax, :trade_date, :created_at)""",
                        {"fill_id": new_fill, "order_id": new_order, "account_id": account_id,
                         "symbol": _symbol(item.get("symbol")), "side": item.get("side"),
                         "quantity": _positive_int(item.get("quantity"), "quantity"),
                         "price": _money(item.get("price"), "price", positive=True),
                         "fees": _money(item.get("fees", 0), "fees"), "tax": _money(item.get("tax", 0), "tax"),
                         "trade_date": _trade_date(item.get("trade_date")), "created_at": item.get("created_at") or now})
                execute(connection, "UPDATE paper_orders SET fill_id = :fill_id WHERE order_id = :order_id",
                        {"fill_id": new_fill, "order_id": new_order})
            snapshot_map: dict[str, str] = {}
            snapshots = sections["snapshots"]
            if not isinstance(snapshots, list):
                raise ValueError("snapshots section must be a list")
            for item in snapshots:
                if not isinstance(item, dict):
                    raise ValueError("snapshot must be an object")
                content = {key: item.get(key) for key in ("trade_date", "cash", "market_value", "equity", "positions_json")}
                new_snapshot = f"paper_snapshot_{_hash({'account_id': account_id, **content})}"
                snapshot_map[str(item.get("snapshot_id"))] = new_snapshot
                execute(connection, """INSERT INTO paper_account_snapshots
                        (snapshot_id, account_id, trade_date, cash, market_value, equity,
                         realized_pnl, unrealized_pnl, daily_pnl, daily_return,
                         positions_json, mark_provenance_json, snapshot_fingerprint,
                         request_hash, idempotency_key, created_at)
                        VALUES (:snapshot_id, :account_id, :trade_date, :cash, :market_value,
                                :equity, :realized, :unrealized, :daily_pnl, :daily_return,
                                :positions, :provenance, :fingerprint, :request_hash, :key, :created_at)""",
                        {"snapshot_id": new_snapshot, "account_id": account_id,
                         "trade_date": _trade_date(item.get("trade_date")),
                         "cash": _money(item.get("cash"), "snapshot.cash"),
                         "market_value": _money(item.get("market_value"), "snapshot.market_value"),
                         "equity": _money(item.get("equity"), "snapshot.equity"),
                         "realized": _signed_money(item.get("realized_pnl", 0), "snapshot.realized_pnl"),
                         "unrealized": _signed_money(item.get("unrealized_pnl", 0), "snapshot.unrealized_pnl"),
                         "daily_pnl": _signed_money(item.get("daily_pnl", 0), "snapshot.daily_pnl"),
                         "daily_return": item.get("daily_return"), "positions": item.get("positions_json") or [],
                         "provenance": {"source": "bundle", "bundle_sha256": bundle_sha256},
                         "fingerprint": _hash({"account_id": account_id, **content}),
                         "request_hash": _hash(content), "key": f"import-{uuid.uuid4().hex}",
                         "created_at": item.get("created_at") or now})
            ledger = sections["ledger"]
            if not isinstance(ledger, list):
                raise ValueError("ledger section must be a list")
            for item in ledger:
                if not isinstance(item, dict):
                    raise ValueError("ledger entry must be an object")
                execute(connection, """INSERT INTO paper_ledger_entries
                        (entry_id, account_id, entry_type, trade_date, order_id, fill_id,
                         snapshot_id, symbol, side, quantity, price, amount, fees,
                         cash_delta, realized_pnl, details_json, created_at)
                        VALUES (:entry_id, :account_id, :entry_type, :trade_date,
                                :order_id, :fill_id, :snapshot_id, :symbol, :side,
                                :quantity, :price, :amount, :fees, :cash_delta,
                                :realized, :details, :created_at)""",
                        {"entry_id": _new_id("paper_ledger"), "account_id": account_id,
                         "entry_type": item.get("entry_type") or "imported", "trade_date": item.get("trade_date"),
                         "order_id": order_map.get(str(item.get("order_id"))), "fill_id": fill_map.get(str(item.get("fill_id"))),
                         "snapshot_id": snapshot_map.get(str(item.get("snapshot_id"))), "symbol": item.get("symbol"),
                         "side": item.get("side"), "quantity": int(item.get("quantity") or 0),
                         "price": item.get("price"), "amount": Decimal(str(item.get("amount", 0))),
                         "fees": Decimal(str(item.get("fees", 0))), "cash_delta": Decimal(str(item.get("cash_delta", 0))),
                         "realized": Decimal(str(item.get("realized_pnl", 0))),
                         "details": {"source": "bundle", "bundle_sha256": bundle_sha256},
                         "created_at": item.get("created_at") or now})
            execute(connection, """INSERT INTO paper_ledger_entries
                    (entry_id, account_id, entry_type, amount, cash_delta, details_json, created_at)
                    VALUES (:entry_id, :account_id, 'import', 0, 0, :details, :at)""",
                    {"entry_id": _new_id("paper_ledger"), "account_id": account_id,
                     "details": {"bundle_sha256": bundle_sha256}, "at": now})
            execute(connection, """INSERT INTO paper_transfer_audit
                    (transfer_id, account_id, owner_principal, direction,
                     bundle_sha256, details_json, created_at)
                    VALUES (:transfer_id, :account_id, :owner, 'import', :sha, :details, :at)""",
                    {"transfer_id": _new_id("paper_transfer"), "account_id": account_id,
                     "owner": owner, "sha": bundle_sha256,
                     "details": {"actor_principal": actor}, "at": now})
        return {"imported": True, "account": self.get_account(account_id, trusted_owner=owner),
                "bundle_sha256": bundle_sha256}

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
            if int(position.get("sellable_quantity") or 0) < quantity:
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
        cash_delta = -(amount + fees + tax) if side == "buy" else amount - fees - tax
        return fees, tax, cash_delta

    def _upsert_position(
        self, connection: Any, account_id: str, symbol: str, side: str,
        quantity: int, trade_date: str, price: float,
    ) -> None:
        row = fetch_one(
            connection,
            "SELECT * FROM paper_positions WHERE account_id = :account_id AND symbol = :symbol",
            {"account_id": account_id, "symbol": symbol},
        )
        if side == "buy":
            old_qty = int(row["quantity"] if row else 0)
            new_qty = old_qty + quantity
            sellable = int(row.get("sellable_quantity") or 0) if row else 0
            locked = int(row.get("locked_quantity") or 0) + quantity if row else quantity
            old_cost = Decimal(str(row.get("average_cost") or 0)) if row else Decimal("0")
            average_cost = ((old_cost * old_qty) + (Decimal(str(price)) * quantity)) / new_qty
            last_buy_date = trade_date
        else:
            new_qty = (row["quantity"] if row else 0) - quantity
            sellable = int(row.get("sellable_quantity") or 0) - quantity
            locked = int(row.get("locked_quantity") or 0)
            average_cost = Decimal(str(row.get("average_cost") or 0))
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
                """INSERT INTO paper_positions
                   (account_id, symbol, quantity, sellable_quantity,
                    locked_quantity, average_cost, market_price,
                    mark_provenance_json, last_buy_date)
                VALUES (:account_id, :symbol, :quantity, :sellable, :locked,
                        :average_cost, :market_price, :provenance, :last_buy_date)
                ON CONFLICT(account_id, symbol)
                DO UPDATE SET quantity = excluded.quantity,
                              sellable_quantity = excluded.sellable_quantity,
                              locked_quantity = excluded.locked_quantity,
                              average_cost = excluded.average_cost,
                              market_price = excluded.market_price,
                              mark_provenance_json = excluded.mark_provenance_json,
                              last_buy_date = excluded.last_buy_date""",
                {"account_id": account_id, "symbol": symbol, "quantity": new_qty,
                 "sellable": sellable, "locked": locked, "average_cost": average_cost,
                 "market_price": row.get("market_price") if row else price,
                 "provenance": row.get("mark_provenance_json") if row else {"source": "fill"},
                 "last_buy_date": last_buy_date},
            )

    @staticmethod
    def _order_row(row: dict[str, Any]) -> dict[str, object]:
        result = dict(row)
        result.pop("idempotency_key", None)
        result.pop("request_hash", None)
        return result
