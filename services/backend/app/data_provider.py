from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Callable, Protocol


DAILY_FIELDS = (
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
)
SECURITY_MASTER_FIELDS = (
    "ts_code",
    "symbol",
    "name",
    "area",
    "industry",
    "market",
    "exchange",
    "list_status",
    "list_date",
    "delist_date",
    "is_hs",
)
MAX_DAILY_ROWS = 6000
MAX_SECURITY_MASTER_ROWS = 10_000
MAX_QUARANTINED_SECURITY_MASTER_ROWS = 100
_SYMBOL_PATTERN = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
_TUSHARE_HISTORICAL_ALIAS_PATTERN = re.compile(r"^T[0-9]{6}\.(?:SH|SZ|BJ)$")
_DATE_PATTERN = re.compile(r"^[0-9]{8}$")
_SECURITY_STATUSES = ("L", "P", "D")
_EXCHANGE_BY_SUFFIX = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}


class ProviderError(RuntimeError):
    """Safe internal base class for provider failures."""


class ProviderCredentialsMissing(ProviderError):
    pass


class ProviderAuthorizationError(ProviderError):
    pass


class ProviderRateLimited(ProviderError):
    pass


class ProviderUnavailable(ProviderError):
    pass


class ProviderProtocolError(ProviderError):
    pass


class ProviderTransport(Protocol):
    def post(self, url: str, payload: dict[str, object], timeout: float) -> "TransportResponse":
        ...


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    body: bytes


class UrlLibTransport:
    """Small stdlib transport so the provider does not need a new SDK."""

    def post(self, url: str, payload: dict[str, object], timeout: float) -> TransportResponse:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return TransportResponse(response.status, response.read())
        except urllib.error.HTTPError as error:
            return TransportResponse(error.code, error.read())
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ProviderUnavailable("provider transport unavailable") from error


def _validate_date(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not _DATE_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"{field} is not a calendar date") from error
    return value


@dataclass(frozen=True)
class DailyRequest:
    """BYQ-owned bounded request semantics for unadjusted A-share daily bars."""

    ts_code: str | None = None
    trade_date: str | None = None
    start_date: str | None = None
    end_date: str | None = None

    def normalized(self) -> "DailyRequest":
        symbol = self.ts_code.upper() if self.ts_code else None
        if symbol is not None and not _SYMBOL_PATTERN.fullmatch(symbol):
            raise ValueError("ts_code must match NNNNNN.SH, NNNNNN.SZ, or NNNNNN.BJ")

        trade_date = _validate_date(self.trade_date, "trade_date")
        start_date = _validate_date(self.start_date, "start_date")
        end_date = _validate_date(self.end_date, "end_date")

        if (start_date is None) != (end_date is None):
            raise ValueError("start_date and end_date must be provided together")
        if trade_date is not None and start_date is not None:
            raise ValueError("trade_date cannot be combined with a date range")
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if symbol is None and trade_date is None:
            if start_date is not None:
                raise ValueError("a date range requires ts_code")
            raise ValueError("an exact trade_date or one ts_code is required")
        if trade_date is None and start_date is None:
            raise ValueError("an exact trade_date or bounded date range is required")

        return DailyRequest(symbol, trade_date, start_date, end_date)

    def provider_params(self) -> dict[str, str]:
        request = self.normalized()
        return {
            key: value
            for key, value in {
                "ts_code": request.ts_code,
                "trade_date": request.trade_date,
                "start_date": request.start_date,
                "end_date": request.end_date,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class DailyBar:
    ts_code: str
    trade_date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    pre_close: float | None
    change: float | None
    pct_chg: float | None
    vol: float | None
    amount: float | None

    @classmethod
    def from_row(cls, fields: list[str], row: list[Any]) -> "DailyBar":
        try:
            values = dict(zip(fields, row, strict=True))
        except ValueError as error:
            raise ProviderProtocolError("provider row does not match its fields") from error
        missing = [field for field in DAILY_FIELDS if field not in values]
        if missing:
            raise ProviderProtocolError("provider response omitted daily fields")
        return cls(
            ts_code=str(values["ts_code"]),
            trade_date=str(values["trade_date"]),
            open=_number(values["open"]),
            high=_number(values["high"]),
            low=_number(values["low"]),
            close=_number(values["close"]),
            pre_close=_number(values["pre_close"]),
            change=_number(values["change"]),
            pct_chg=_number(values["pct_chg"]),
            vol=_number(values["vol"]),
            amount=_number(values["amount"]),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "ts_code": self.ts_code,
            "trade_date": self.trade_date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "pre_close": self.pre_close,
            "change": self.change,
            "pct_chg": self.pct_chg,
            "vol": self.vol,
            "amount": self.amount,
        }


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ProviderProtocolError("provider returned a boolean numeric value")
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ProviderProtocolError("provider returned an invalid numeric value") from error


@dataclass(frozen=True)
class Provenance:
    provider: str
    endpoint: str
    request_fingerprint: str
    retrieved_at: str
    cache_hit: bool
    row_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "endpoint": self.endpoint,
            "request_fingerprint": self.request_fingerprint,
            "retrieved_at": self.retrieved_at,
            "cache_hit": self.cache_hit,
            "row_count": self.row_count,
        }


@dataclass(frozen=True)
class DailyResult:
    bars: tuple[DailyBar, ...]
    provenance: Provenance


@dataclass(frozen=True)
class SecurityMasterRequest:
    """Closed, provider-neutral request for the complete A-share stock master."""

    statuses: tuple[str, ...] = _SECURITY_STATUSES

    def normalized(self) -> "SecurityMasterRequest":
        if not isinstance(self.statuses, tuple) or not self.statuses:
            raise ValueError("security master statuses must be a non-empty tuple")
        normalized = tuple(status.upper() for status in self.statuses)
        if len(set(normalized)) != len(normalized) or any(status not in _SECURITY_STATUSES for status in normalized):
            raise ValueError("security master statuses must be unique L, P, or D values")
        return SecurityMasterRequest(tuple(status for status in _SECURITY_STATUSES if status in normalized))


def _bounded_provider_text(value: object, field: str, *, required: bool = False) -> str | None:
    if value is None or str(value).strip() == "":
        if required:
            raise ProviderProtocolError(f"provider returned an empty {field}")
        return None
    text = str(value).strip()
    if len(text) > 128:
        raise ProviderProtocolError(f"provider returned an oversized {field}")
    return text


def _optional_provider_date(value: object, field: str) -> str | None:
    text = _bounded_provider_text(value, field)
    if text is None:
        return None
    try:
        return _validate_date(text, field)
    except ValueError as error:
        raise ProviderProtocolError(f"provider returned an invalid {field}") from error


@dataclass(frozen=True)
class SecurityRecord:
    symbol: str
    local_symbol: str
    name: str
    area: str | None
    industry: str | None
    market: str | None
    exchange: str
    list_status: str
    list_date: str
    delist_date: str | None
    is_hs: str | None
    asset_type: str = "stock"

    @classmethod
    def from_row(cls, fields: list[str], row: list[Any], *, expected_status: str) -> "SecurityRecord":
        try:
            values = dict(zip(fields, row, strict=True))
        except ValueError as error:
            raise ProviderProtocolError("provider security row does not match its fields") from error
        missing = [field for field in SECURITY_MASTER_FIELDS if field not in values]
        if missing:
            raise ProviderProtocolError("provider response omitted security-master fields")
        symbol = str(values["ts_code"] or "").strip().upper()
        if not _SYMBOL_PATTERN.fullmatch(symbol):
            raise ProviderProtocolError("provider returned a non-canonical security symbol")
        local_symbol = str(values["symbol"] or "").strip()
        if local_symbol != symbol[:6]:
            raise ProviderProtocolError("provider returned a mismatched local security symbol")
        exchange = str(values["exchange"] or "").strip().upper()
        if exchange != _EXCHANGE_BY_SUFFIX[symbol[-2:]]:
            raise ProviderProtocolError("provider returned a mismatched security exchange")
        list_status = str(values["list_status"] or "").strip().upper()
        if list_status != expected_status:
            raise ProviderProtocolError("provider returned a security outside the requested status")
        list_date = _optional_provider_date(values["list_date"], "list_date")
        if list_date is None:
            raise ProviderProtocolError("provider returned an empty list_date")
        delist_date = _optional_provider_date(values["delist_date"], "delist_date")
        if delist_date is not None and list_date > delist_date:
            raise ProviderProtocolError("provider returned an invalid security lifecycle")
        return cls(
            symbol=symbol,
            local_symbol=local_symbol,
            name=_bounded_provider_text(values["name"], "name", required=True) or "",
            area=_bounded_provider_text(values["area"], "area"),
            industry=_bounded_provider_text(values["industry"], "industry"),
            market=_bounded_provider_text(values["market"], "market"),
            exchange=exchange,
            list_status=list_status,
            list_date=list_date,
            delist_date=delist_date,
            is_hs=_bounded_provider_text(values["is_hs"], "is_hs"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "local_symbol": self.local_symbol,
            "name": self.name,
            "area": self.area,
            "industry": self.industry,
            "market": self.market,
            "exchange": self.exchange,
            "list_status": self.list_status,
            "list_date": self.list_date,
            "delist_date": self.delist_date,
            "is_hs": self.is_hs,
            "asset_type": self.asset_type,
        }


@dataclass(frozen=True)
class QuarantinedSecurityRecord:
    """Bounded evidence for a provider identity outside BYQ's canonical universe."""

    provider_symbol: str
    local_symbol: str
    name: str
    exchange: str
    list_status: str
    list_date: str
    delist_date: str | None
    reason: str = "tushare_historical_alias"

    @classmethod
    def from_row(cls, fields: list[str], row: list[Any], *, expected_status: str) -> "QuarantinedSecurityRecord":
        try:
            values = dict(zip(fields, row, strict=True))
        except ValueError as error:
            raise ProviderProtocolError("provider security row does not match its fields") from error
        missing = [field for field in SECURITY_MASTER_FIELDS if field not in values]
        if missing:
            raise ProviderProtocolError("provider response omitted security-master fields")
        symbol = str(values["ts_code"] or "").strip().upper()
        if not _TUSHARE_HISTORICAL_ALIAS_PATTERN.fullmatch(symbol):
            raise ProviderProtocolError("provider returned a non-canonical security symbol")
        local_symbol = str(values["symbol"] or "").strip().upper()
        if local_symbol != symbol.rsplit(".", 1)[0]:
            raise ProviderProtocolError("provider returned a mismatched local security symbol")
        exchange = str(values["exchange"] or "").strip().upper()
        if exchange != _EXCHANGE_BY_SUFFIX[symbol[-2:]]:
            raise ProviderProtocolError("provider returned a mismatched security exchange")
        list_status = str(values["list_status"] or "").strip().upper()
        if list_status != expected_status:
            raise ProviderProtocolError("provider returned a security outside the requested status")
        list_date = _optional_provider_date(values["list_date"], "list_date")
        if list_date is None:
            raise ProviderProtocolError("provider returned an empty list_date")
        delist_date = _optional_provider_date(values["delist_date"], "delist_date")
        if delist_date is not None and list_date > delist_date:
            raise ProviderProtocolError("provider returned an invalid security lifecycle")
        return cls(
            provider_symbol=symbol,
            local_symbol=local_symbol,
            name=_bounded_provider_text(values["name"], "name", required=True) or "",
            exchange=exchange,
            list_status=list_status,
            list_date=list_date,
            delist_date=delist_date,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "provider_symbol": self.provider_symbol,
            "local_symbol": self.local_symbol,
            "name": self.name,
            "exchange": self.exchange,
            "list_status": self.list_status,
            "list_date": self.list_date,
            "delist_date": self.delist_date,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SecurityMasterResult:
    records: tuple[SecurityRecord, ...]
    provenance: Provenance
    dataset_id: str
    statuses: tuple[str, ...]
    quarantined: tuple[QuarantinedSecurityRecord, ...] = ()


@dataclass(frozen=True)
class TushareConfig:
    token: str
    api_url: str = "http://api.tushare.pro"
    timeout_seconds: float = 8.0
    max_retries: int = 2
    backoff_seconds: float = 0.25
    cache_ttl_seconds: float = 300.0
    cache_max_entries: int = 128

    @classmethod
    def from_env(cls) -> "TushareConfig":
        return cls(
            token=os.getenv("TUSHARE_TOKEN", "").strip(),
            api_url=os.getenv("TUSHARE_API_URL", "http://api.tushare.pro").strip(),
            timeout_seconds=float(os.getenv("TUSHARE_TIMEOUT_SECONDS", "8")),
            max_retries=int(os.getenv("TUSHARE_MAX_RETRIES", "2")),
            backoff_seconds=float(os.getenv("TUSHARE_BACKOFF_SECONDS", "0.25")),
            cache_ttl_seconds=float(os.getenv("TUSHARE_CACHE_TTL_SECONDS", "300")),
            cache_max_entries=int(os.getenv("TUSHARE_CACHE_MAX_ENTRIES", "128")),
        )


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    bars: tuple[DailyBar, ...]
    provenance: Provenance


class TushareProvider:
    """Tushare adapter behind the BYQ-owned provider contract."""

    def __init__(
        self,
        config: TushareConfig,
        *,
        transport: ProviderTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._transport = transport or UrlLibTransport()
        self._clock = clock
        self._sleep = sleep
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._cache_lock = threading.RLock()

    @classmethod
    def from_env(cls) -> "TushareProvider":
        return cls(TushareConfig.from_env())

    def fetch_daily(self, request: DailyRequest) -> DailyResult:
        normalized = request.normalized()
        fingerprint = self._fingerprint(normalized)
        cached = self._get_cached(fingerprint)
        if cached is not None:
            provenance = Provenance(
                provider=cached.provenance.provider,
                endpoint=cached.provenance.endpoint,
                request_fingerprint=fingerprint,
                retrieved_at=cached.provenance.retrieved_at,
                cache_hit=True,
                row_count=len(cached.bars),
            )
            return DailyResult(cached.bars, provenance)

        if not self._config.token:
            raise ProviderCredentialsMissing("Tushare credentials are not configured")

        payload = {
            "api_name": "daily",
            "token": self._config.token,
            "params": normalized.provider_params(),
            "fields": ",".join(DAILY_FIELDS),
        }
        fields, rows = self._request(payload)
        if len(rows) > MAX_DAILY_ROWS:
            raise ProviderProtocolError("provider returned too many daily rows")
        bars = tuple(DailyBar.from_row(fields, row) for row in rows)
        provenance = Provenance(
            provider="tushare",
            endpoint="daily",
            request_fingerprint=fingerprint,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            cache_hit=False,
            row_count=len(bars),
        )
        self._set_cached(fingerprint, bars, provenance)
        return DailyResult(bars, provenance)

    def fetch_security_master(self, request: SecurityMasterRequest | None = None) -> SecurityMasterResult:
        normalized = (request or SecurityMasterRequest()).normalized()
        if not self._config.token:
            raise ProviderCredentialsMissing("Tushare credentials are not configured")
        fingerprint = sha256(json.dumps(
            {"api_name": "stock_basic", "statuses": normalized.statuses, "fields": SECURITY_MASTER_FIELDS},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        records: list[SecurityRecord] = []
        quarantined: list[QuarantinedSecurityRecord] = []
        seen: set[str] = set()
        rows_seen = 0
        for status in normalized.statuses:
            payload = {
                "api_name": "stock_basic",
                "token": self._config.token,
                "params": {"exchange": "", "list_status": status},
                "fields": ",".join(SECURITY_MASTER_FIELDS),
            }
            fields, rows = self._request(payload)
            rows_seen += len(rows)
            if rows_seen > MAX_SECURITY_MASTER_ROWS:
                raise ProviderProtocolError("provider returned too many security-master rows")
            for row in rows:
                try:
                    values = dict(zip(fields, row, strict=True))
                except ValueError as error:
                    raise ProviderProtocolError("provider security row does not match its fields") from error
                provider_symbol = str(values.get("ts_code") or "").strip().upper()
                if provider_symbol in seen:
                    raise ProviderProtocolError("provider returned duplicate security-master identities")
                seen.add(provider_symbol)
                if not _SYMBOL_PATTERN.fullmatch(provider_symbol):
                    quarantined.append(QuarantinedSecurityRecord.from_row(fields, row, expected_status=status))
                    if len(quarantined) > MAX_QUARANTINED_SECURITY_MASTER_ROWS:
                        raise ProviderProtocolError("provider returned too many quarantined security identities")
                    continue
                record = SecurityRecord.from_row(fields, row, expected_status=status)
                records.append(record)
        ordered = tuple(sorted(records, key=lambda item: item.symbol))
        ordered_quarantine = tuple(sorted(quarantined, key=lambda item: item.provider_symbol))
        dataset_payload: object = [record.as_dict() for record in ordered]
        if ordered_quarantine:
            dataset_payload = {
                "records": dataset_payload,
                "quarantined": [record.as_dict() for record in ordered_quarantine],
            }
        dataset_id = sha256(json.dumps(
            dataset_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        provenance = Provenance(
            provider="tushare",
            endpoint="stock_basic",
            request_fingerprint=fingerprint,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            cache_hit=False,
            row_count=len(ordered) + len(ordered_quarantine),
        )
        return SecurityMasterResult(ordered, provenance, dataset_id, normalized.statuses, ordered_quarantine)

    def _request(self, payload: dict[str, object]) -> tuple[list[str], list[list[Any]]]:
        last_status: int | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                response = self._transport.post(
                    self._config.api_url,
                    payload,
                    self._config.timeout_seconds,
                )
            except ProviderUnavailable:
                if attempt >= self._config.max_retries:
                    raise
                self._backoff(attempt)
                continue

            last_status = response.status_code
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= self._config.max_retries:
                    if response.status_code == 429:
                        raise ProviderRateLimited("Tushare request was rate limited")
                    raise ProviderUnavailable("Tushare service is unavailable")
                self._backoff(attempt)
                continue
            if response.status_code >= 400:
                raise ProviderUnavailable("Tushare request returned an HTTP error")
            try:
                return self._decode(response.body)
            except ProviderRateLimited:
                if attempt >= self._config.max_retries:
                    raise
                self._backoff(attempt)
                continue

        raise ProviderUnavailable(f"Tushare request failed with status {last_status}")

    def _decode(self, body: bytes) -> tuple[list[str], list[list[Any]]]:
        try:
            envelope = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderProtocolError("Tushare returned invalid JSON") from error
        if not isinstance(envelope, dict):
            raise ProviderProtocolError("Tushare returned an invalid envelope")

        code = envelope.get("code")
        if code not in (0, None):
            if code in (2002, 401, 403):
                raise ProviderAuthorizationError("Tushare rejected the configured credentials")
            if code in (429, -429):
                raise ProviderRateLimited("Tushare rejected the request rate")
            raise ProviderUnavailable("Tushare rejected the request")

        data = envelope.get("data")
        if data is None:
            return list(DAILY_FIELDS), []
        if not isinstance(data, dict):
            raise ProviderProtocolError("Tushare data is not an object")
        fields = data.get("fields")
        items = data.get("items")
        if not isinstance(fields, list) or not all(isinstance(field, str) for field in fields):
            raise ProviderProtocolError("Tushare fields are invalid")
        if not isinstance(items, list) or not all(isinstance(row, list) for row in items):
            raise ProviderProtocolError("Tushare items are invalid")
        return fields, items

    def _backoff(self, attempt: int) -> None:
        self._sleep(min(self._config.backoff_seconds * (2**attempt), 2.0))

    def _fingerprint(self, request: DailyRequest) -> str:
        canonical = json.dumps(
            {
                "api_name": "daily",
                "params": request.provider_params(),
                "fields": DAILY_FIELDS,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(canonical).hexdigest()

    def _get_cached(self, fingerprint: str) -> _CacheEntry | None:
        now = self._clock()
        with self._cache_lock:
            entry = self._cache.get(fingerprint)
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._cache.pop(fingerprint, None)
                return None
            self._cache.move_to_end(fingerprint)
            return entry

    def _set_cached(self, fingerprint: str, bars: tuple[DailyBar, ...], provenance: Provenance) -> None:
        with self._cache_lock:
            self._cache[fingerprint] = _CacheEntry(
                expires_at=self._clock() + self._config.cache_ttl_seconds,
                bars=bars,
                provenance=provenance,
            )
            self._cache.move_to_end(fingerprint)
            while len(self._cache) > self._config.cache_max_entries:
                self._cache.popitem(last=False)
