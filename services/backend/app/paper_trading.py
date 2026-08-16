"""BYQ-owned simulation-only Paper Trading and Stock Pool contracts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


def _loads(value: str, *, field: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise PaperTradingPersistenceError(f"stored {field} is invalid") from exc


class PaperTradingStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = sqlite3.connect(self.path, timeout=10.0, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 10000")
            self._create_schema()
        except sqlite3.Error as exc:
            raise PaperTradingPersistenceError("paper trading storage is unavailable") from exc

    @classmethod
    def from_env(cls) -> "PaperTradingStore":
        return cls(os.getenv("BYQ_DOMAIN_DB_PATH", "/tmp/byq-domain.sqlite3"))

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_accounts (
                    account_id TEXT PRIMARY KEY,
                    owner_principal TEXT NOT NULL,
                    name TEXT NOT NULL,
                    cash REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS paper_accounts_owner_name
                    ON paper_accounts(owner_principal, name);
                CREATE TABLE IF NOT EXISTS stock_pools (
                    pool_id TEXT PRIMARY KEY,
                    owner_principal TEXT NOT NULL,
                    name TEXT NOT NULL,
                    symbols_json TEXT NOT NULL,
                    version TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_positions (
                    account_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    last_buy_date TEXT,
                    PRIMARY KEY(account_id, symbol)
                );
                CREATE TABLE IF NOT EXISTS paper_orders (
                    order_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price REAL NOT NULL,
                    status TEXT NOT NULL,
                    blocked_reason TEXT,
                    fees REAL NOT NULL DEFAULT 0,
                    tax REAL NOT NULL DEFAULT 0,
                    cash_delta REAL NOT NULL DEFAULT 0,
                    trade_date TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS paper_orders_idempotency
                    ON paper_orders(account_id, idempotency_key);
                CREATE TABLE IF NOT EXISTS paper_fills (
                    fill_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price REAL NOT NULL,
                    fees REAL NOT NULL,
                    tax REAL NOT NULL,
                    trade_date TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_account(self, payload: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("account request must be an object")
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        if owner is None:
            raise PaperTradingForbidden("account requires a trusted owner")
        name = _text(payload.get("name"), field="name", max_length=128)
        cash = _finite(payload.get("cash"), field="cash")
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT * FROM paper_accounts WHERE owner_principal = ? AND name = ?", (owner, name)
            ).fetchone()
            if existing is not None:
                raise PaperTradingConflict("account name already exists")
            now = _now()
            account_id = _new_id("paper_account")
            self._connection.execute(
                """INSERT INTO paper_accounts
                (account_id, owner_principal, name, cash, status, created_at, updated_at, version)
                VALUES (?, ?, ?, ?, 'active', ?, ?, 1)""",
                (account_id, owner, name, cash, now, now),
            )
            return self.get_account(account_id, trusted_owner=owner)

    def get_account(self, account_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        account_id = _id(account_id, prefix="paper_account")
        with self._lock:
            row = self._connection.execute("SELECT * FROM paper_accounts WHERE account_id = ?", (account_id,)).fetchone()
        if row is None:
            raise PaperTradingNotFound("paper account not found")
        if trusted_owner and row["owner_principal"] != trusted_owner:
            raise PaperTradingForbidden("paper account is not owned by this principal")
        result = dict(row)
        return result

    def list_accounts(self, *, trusted_owner: str | None = None) -> dict[str, object]:
        with self._lock:
            if trusted_owner:
                rows = self._connection.execute(
                    "SELECT * FROM paper_accounts WHERE owner_principal = ? ORDER BY created_at DESC, account_id DESC",
                    (trusted_owner,),
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT * FROM paper_accounts ORDER BY created_at DESC, account_id DESC"
                ).fetchall()
        return {"accounts": [dict(row) for row in rows]}

    def create_pool(self, payload: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("pool request must be an object")
        owner = _principal(trusted_owner, field="owner_principal") if trusted_owner else None
        if owner is None:
            raise PaperTradingForbidden("pool requires a trusted owner")
        name = _text(payload.get("name"), field="name", max_length=128)
        symbols_value = payload.get("symbols")
        if not isinstance(symbols_value, list) or not symbols_value:
            raise ValueError("symbols must be a non-empty list")
        symbols = sorted({_symbol(item) for item in symbols_value})
        provenance = payload.get("provenance", {})
        if not isinstance(provenance, dict):
            raise ValueError("provenance must be an object")
        symbols_json = json.dumps(symbols, separators=(",", ":"))
        provenance_json = json.dumps(provenance, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        pool_id = _new_id("stock_pool")
        now = _now()
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO stock_pools
                (pool_id, owner_principal, name, symbols_json, version, provenance_json, created_at)
                VALUES (?, ?, ?, ?, 'v1', ?, ?)""",
                (pool_id, owner, name, symbols_json, provenance_json, now),
            )
            return self.get_pool(pool_id, trusted_owner=owner)

    def get_pool(self, pool_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        pool_id = _id(pool_id, prefix="stock_pool")
        with self._lock:
            row = self._connection.execute("SELECT * FROM stock_pools WHERE pool_id = ?", (pool_id,)).fetchone()
        if row is None:
            raise PaperTradingNotFound("stock pool not found")
        if trusted_owner and row["owner_principal"] != trusted_owner:
            raise PaperTradingForbidden("stock pool is not owned by this principal")
        result = dict(row)
        result["symbols"] = _loads(result.pop("symbols_json"), field="symbols")
        result["provenance"] = _loads(result.pop("provenance_json"), field="provenance")
        return result

    def list_pools(self, *, trusted_owner: str | None = None) -> dict[str, object]:
        with self._lock:
            if trusted_owner:
                rows = self._connection.execute(
                    "SELECT * FROM stock_pools WHERE owner_principal = ? ORDER BY created_at DESC, pool_id DESC",
                    (trusted_owner,),
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT * FROM stock_pools ORDER BY created_at DESC, pool_id DESC"
                ).fetchall()
        pools = []
        for row in rows:
            item = dict(row)
            item["symbols"] = _loads(item.pop("symbols_json"), field="symbols")
            item["provenance"] = _loads(item.pop("provenance_json"), field="provenance")
            pools.append(item)
        return {"pools": pools}

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
        with self._lock, self._connection:
            account = self._connection.execute("SELECT * FROM paper_accounts WHERE account_id = ?", (account_id,)).fetchone()
            if account is None or account["owner_principal"] != owner:
                raise PaperTradingForbidden("paper account is not owned by this principal")
            pool = self._connection.execute("SELECT * FROM stock_pools WHERE pool_id = ?", (pool_id,)).fetchone()
            if pool is None or pool["owner_principal"] != owner:
                raise PaperTradingForbidden("stock pool is not owned by this principal")
            symbols = _loads(pool["symbols_json"], field="symbols")
            if not isinstance(symbols, list) or symbol not in symbols:
                raise PaperTradingForbidden("symbol is not in the authorized stock pool")
            existing = self._connection.execute(
                "SELECT * FROM paper_orders WHERE account_id = ? AND idempotency_key = ?",
                (account_id, key),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise PaperTradingConflict("order idempotency key was reused")
                return self._order_row(existing)

            blocked = self._blocked_reason(
                account, side, quantity, price, trade_date, is_suspended, up_limit, down_limit, symbol
            )
            now = _now()
            order_id = _new_id("paper_order")
            if blocked is None:
                fees, tax, cash_delta = self._execution_cost(side, quantity, price)
                status = "filled"
                new_cash = float(account["cash"]) + cash_delta
                self._connection.execute(
                    "UPDATE paper_accounts SET cash = ?, updated_at = ?, version = version + 1 WHERE account_id = ?",
                    (new_cash, now, account_id),
                )
                self._upsert_position(account_id, symbol, side, quantity, trade_date)
                fill_id = _new_id("paper_fill")
                self._connection.execute(
                    """INSERT INTO paper_fills
                    (fill_id, order_id, account_id, symbol, side, quantity, price, fees, tax, trade_date, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (fill_id, order_id, account_id, symbol, side, quantity, price, fees, tax, trade_date, now),
                )
                blocked_reason = None
            else:
                status = "blocked"
                fees = 0.0
                tax = 0.0
                cash_delta = 0.0
                blocked_reason = blocked
            self._connection.execute(
                """INSERT INTO paper_orders
                (order_id, account_id, symbol, side, quantity, price, status, blocked_reason,
                 fees, tax, cash_delta, trade_date, idempotency_key, request_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (order_id, account_id, symbol, side, quantity, price, status, blocked_reason, fees, tax, cash_delta, trade_date, key, request_hash, now),
            )
            return self._order_row(self._connection.execute("SELECT * FROM paper_orders WHERE order_id = ?", (order_id,)).fetchone())

    def list_orders(self, account_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        account_id = _id(account_id, prefix="paper_account")
        with self._lock:
            account = self._connection.execute("SELECT * FROM paper_accounts WHERE account_id = ?", (account_id,)).fetchone()
            if account is None or (trusted_owner and account["owner_principal"] != trusted_owner):
                raise PaperTradingForbidden("paper account is not owned by this principal")
            rows = self._connection.execute(
                "SELECT * FROM paper_orders WHERE account_id = ? ORDER BY created_at DESC, order_id DESC",
                (account_id,),
            ).fetchall()
        return {"orders": [self._order_row(row) for row in rows]}

    def list_positions(self, account_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        account_id = _id(account_id, prefix="paper_account")
        with self._lock:
            account = self._connection.execute("SELECT * FROM paper_accounts WHERE account_id = ?", (account_id,)).fetchone()
            if account is None or (trusted_owner and account["owner_principal"] != trusted_owner):
                raise PaperTradingForbidden("paper account is not owned by this principal")
            rows = self._connection.execute(
                "SELECT * FROM paper_positions WHERE account_id = ? ORDER BY symbol ASC",
                (account_id,),
            ).fetchall()
        return {"positions": [dict(row) for row in rows]}

    def list_fills(self, account_id: object, *, trusted_owner: str | None = None) -> dict[str, object]:
        account_id = _id(account_id, prefix="paper_account")
        with self._lock:
            account = self._connection.execute("SELECT * FROM paper_accounts WHERE account_id = ?", (account_id,)).fetchone()
            if account is None or (trusted_owner and account["owner_principal"] != trusted_owner):
                raise PaperTradingForbidden("paper account is not owned by this principal")
            rows = self._connection.execute(
                "SELECT * FROM paper_fills WHERE account_id = ? ORDER BY created_at DESC, fill_id DESC",
                (account_id,),
            ).fetchall()
        return {"fills": [dict(row) for row in rows]}

    def _blocked_reason(
        self,
        account: sqlite3.Row,
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
        position = self._connection.execute(
            "SELECT * FROM paper_positions WHERE account_id = ? AND symbol = ?",
            (account["account_id"], symbol),
        ).fetchone()
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

    def _upsert_position(self, account_id: str, symbol: str, side: str, quantity: int, trade_date: str) -> None:
        row = self._connection.execute(
            "SELECT * FROM paper_positions WHERE account_id = ? AND symbol = ?", (account_id, symbol)
        ).fetchone()
        if side == "buy":
            new_qty = (row["quantity"] if row else 0) + quantity
            last_buy_date = trade_date
        else:
            new_qty = (row["quantity"] if row else 0) - quantity
            last_buy_date = row["last_buy_date"] if row else None
        if new_qty == 0:
            self._connection.execute("DELETE FROM paper_positions WHERE account_id = ? AND symbol = ?", (account_id, symbol))
        else:
            self._connection.execute(
                """INSERT INTO paper_positions (account_id, symbol, quantity, last_buy_date)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(account_id, symbol)
                DO UPDATE SET quantity = excluded.quantity, last_buy_date = excluded.last_buy_date""",
                (account_id, symbol, new_qty, last_buy_date),
            )

    @staticmethod
    def _order_row(row: sqlite3.Row) -> dict[str, object]:
        result = dict(row)
        result.pop("idempotency_key", None)
        result.pop("request_hash", None)
        return result
