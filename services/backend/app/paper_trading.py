"""BYQ-owned simulation-only Paper Trading and Stock Pool contracts (ADR-0016 PG)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from .db import PgStoreMixin, ensure_column, execute, fetch_one


SYMBOL_PATTERN = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
TRADE_DATE_PATTERN = re.compile(r"^\d{8}$")
LOT_SIZE = 100


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
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


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
        description = payload.get("description")
        if description is not None:
            description = _text(description, field="description", max_length=2000)
        symbols_value = payload.get("symbols")
        if not isinstance(symbols_value, list) or not symbols_value:
            raise ValueError("symbols must be a non-empty list")
        symbols = sorted({_symbol(item) for item in symbols_value})
        weights = payload.get("weights", {})
        if not isinstance(weights, dict):
            raise ValueError("weights must be an object")
        unknown_weights = sorted(set(weights) - set(symbols))
        if unknown_weights:
            raise ValueError("weights contain symbols outside the pool membership")
        normalized_weights: dict[str, float] = {}
        for symbol, weight in weights.items():
            if isinstance(weight, bool) or not isinstance(weight, (int, float)):
                raise ValueError("weights must be numeric")
            value = float(weight)
            if not math.isfinite(value) or value < 0:
                raise ValueError("weights must be finite and non-negative")
            normalized_weights[symbol] = value
        provenance = payload.get("provenance", {})
        if not isinstance(provenance, dict):
            raise ValueError("provenance must be an object")
        pool_id = _new_id("stock_pool")
        now = _now()
        self._execute(
            """INSERT INTO stock_pools
            (pool_id, owner_principal, name, pool_type, description, weights_json,
             symbols_json, version, provenance_json, created_at)
            VALUES (:pool_id, :owner, :name, :pool_type, :description, :weights_json,
                    :symbols_json, 'v1', :provenance_json, :created_at)""",
            {
                "pool_id": pool_id,
                "owner": owner,
                "name": name,
                "pool_type": pool_type,
                "description": description,
                "weights_json": normalized_weights,
                "symbols_json": symbols,
                "provenance_json": provenance,
                "created_at": now,
            },
        )
        return self.get_pool(pool_id, trusted_owner=owner)

    def get_pool(self, pool_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        pool_id = _id(pool_id, prefix="stock_pool")
        row = self._fetch_one("SELECT * FROM stock_pools WHERE pool_id = :pool_id", {"pool_id": pool_id})
        if row is None:
            raise PaperTradingNotFound("stock pool not found")
        if trusted_owner and row["owner_principal"] != trusted_owner:
            raise PaperTradingForbidden("stock pool is not owned by this principal")
        return self._pool_row(row)

    def list_pools(self, *, trusted_owner: str | None = None) -> dict[str, object]:
        if trusted_owner:
            rows = self._execute(
                "SELECT * FROM stock_pools WHERE owner_principal = :owner_principal ORDER BY created_at DESC, pool_id DESC",
                {"owner_principal": trusted_owner},
            )
        else:
            rows = self._execute("SELECT * FROM stock_pools ORDER BY created_at DESC, pool_id DESC")
        return {"pools": [self._pool_row(row) for row in rows]}

    @staticmethod
    def _pool_row(row: dict[str, Any]) -> dict[str, object]:
        result = dict(row)
        result["symbols"] = result.pop("symbols_json") or []
        result["weights"] = result.pop("weights_json") or {}
        result["provenance"] = result.pop("provenance_json") or {}
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
        request_hash = _hash(request)
        with self._transaction() as connection:
            account = fetch_one(connection, "SELECT * FROM paper_accounts WHERE account_id = :account_id", {"account_id": account_id})
            if account is None or account["owner_principal"] != owner:
                raise PaperTradingForbidden("paper account is not owned by this principal")
            pool = fetch_one(connection, "SELECT * FROM stock_pools WHERE pool_id = :pool_id", {"pool_id": pool_id})
            if pool is None or pool["owner_principal"] != owner:
                raise PaperTradingForbidden("stock pool is not owned by this principal")
            symbols = pool["symbols_json"]
            if not isinstance(symbols, list) or symbol not in symbols:
                raise PaperTradingForbidden("symbol is not in the authorized stock pool")
            existing = fetch_one(
                connection,
                "SELECT * FROM paper_orders WHERE account_id = :account_id AND idempotency_key = :key",
                {"account_id": account_id, "key": key},
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise PaperTradingConflict("order idempotency key was reused")
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
                (order_id, account_id, symbol, side, quantity, price, status, blocked_reason,
                 fees, tax, cash_delta, trade_date, idempotency_key, request_hash, created_at)
                VALUES (:order_id, :account_id, :symbol, :side, :quantity, :price, :status, :blocked_reason,
                        :fees, :tax, :cash_delta, :trade_date, :idempotency_key, :request_hash, :created_at)""",
                {"order_id": order_id, "account_id": account_id, "symbol": symbol, "side": side, "quantity": quantity, "price": price, "status": status, "blocked_reason": blocked_reason, "fees": fees, "tax": tax, "cash_delta": cash_delta, "trade_date": trade_date, "idempotency_key": key, "request_hash": request_hash, "created_at": now},
            )
            order_row = fetch_one(connection, "SELECT * FROM paper_orders WHERE order_id = :order_id", {"order_id": order_id})
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
