from __future__ import annotations

import json

import pytest

from app.data_provider import (
    DailyRequest,
    ProviderAuthorizationError,
    ProviderCredentialsMissing,
    ProviderRateLimited,
    ProviderUnavailable,
    TransportResponse,
    TushareConfig,
    TushareProvider,
)


def envelope(items: list[list[object]], *, fields: list[str] | None = None) -> bytes:
    return json.dumps(
        {
            "code": 0,
            "msg": "",
            "data": {
                "fields": fields or [
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
                ],
                "items": items,
            },
        }
    ).encode()


class FakeTransport:
    def __init__(self, responses: list[TransportResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, object], float]] = []

    def post(self, url: str, payload: dict[str, object], timeout: float) -> TransportResponse:
        self.calls.append((url, payload, timeout))
        return self.responses.pop(0)


def provider(transport: FakeTransport, **kwargs: object) -> TushareProvider:
    return TushareProvider(
        TushareConfig(token="fixture-token", **kwargs),
        transport=transport,
        sleep=lambda _seconds: None,
    )


def test_daily_request_requires_bounded_symbol_or_exact_date() -> None:
    assert DailyRequest(ts_code="000001.sz", start_date="20240101", end_date="20240102").normalized() == DailyRequest(
        ts_code="000001.SZ", start_date="20240101", end_date="20240102"
    )
    DailyRequest(trade_date="20240102").normalized()

    with pytest.raises(ValueError, match="exact trade_date"):
        DailyRequest().normalized()
    with pytest.raises(ValueError, match="bounded date range"):
        DailyRequest(ts_code="000001.SZ").normalized()
    with pytest.raises(ValueError, match="requires ts_code"):
        DailyRequest(start_date="20240101", end_date="20240102").normalized()
    with pytest.raises(ValueError, match="calendar date"):
        DailyRequest(trade_date="20240231").normalized()
    with pytest.raises(ValueError, match="cannot be combined"):
        DailyRequest(ts_code="000001.SZ", trade_date="20240102", start_date="20240101", end_date="20240103").normalized()


def test_provider_translates_daily_rows_and_redacts_token_from_provenance() -> None:
    transport = FakeTransport(
        [
            TransportResponse(
                200,
                envelope([["000001.SZ", "20240102", 10, 11, 9, 10.5, 10.2, 0.3, 2.94, 100, 2000]]),
            )
        ]
    )
    result = provider(transport).fetch_daily(DailyRequest(ts_code="000001.SZ", trade_date="20240102"))

    assert result.bars[0].close == 10.5
    assert result.provenance.provider == "tushare"
    assert result.provenance.cache_hit is False
    assert result.provenance.row_count == 1
    assert "fixture-token" not in json.dumps(result.provenance.as_dict())
    assert transport.calls[0][1]["token"] == "fixture-token"
    assert transport.calls[0][1]["fields"] == "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"


def test_provider_caches_success_and_marks_cache_hit() -> None:
    transport = FakeTransport(
        [TransportResponse(200, envelope([["000001.SZ", "20240102", 10, 11, 9, 10.5, 10.2, 0.3, 2.94, 100, 2000]]))]
    )
    provider_instance = provider(transport, cache_ttl_seconds=60)
    request = DailyRequest(ts_code="000001.SZ", trade_date="20240102")

    first = provider_instance.fetch_daily(request)
    second = provider_instance.fetch_daily(request)

    assert len(transport.calls) == 1
    assert first.provenance.cache_hit is False
    assert second.provenance.cache_hit is True
    assert second.bars == first.bars


def test_provider_retries_http_rate_limit_with_bounded_backoff() -> None:
    transport = FakeTransport(
        [
            TransportResponse(429, b"{}"),
            TransportResponse(200, envelope([])),
        ]
    )
    sleeps: list[float] = []
    provider_instance = TushareProvider(
        TushareConfig(token="fixture-token", max_retries=1, backoff_seconds=0.5),
        transport=transport,
        sleep=sleeps.append,
    )

    result = provider_instance.fetch_daily(DailyRequest(trade_date="20240102"))

    assert result.bars == ()
    assert len(transport.calls) == 2
    assert sleeps == [0.5]


def test_provider_retries_http_server_error_then_reports_unavailable() -> None:
    transport = FakeTransport(
        [
            TransportResponse(503, b"{}"),
            TransportResponse(503, b"{}"),
        ]
    )
    provider_instance = TushareProvider(
        TushareConfig(token="fixture-token", max_retries=1, backoff_seconds=0.5),
        transport=transport,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(ProviderUnavailable):
        provider_instance.fetch_daily(DailyRequest(trade_date="20240102"))
    assert len(transport.calls) == 2


def test_provider_does_not_retry_permission_failure() -> None:
    transport = FakeTransport(
        [TransportResponse(200, json.dumps({"code": 2002, "msg": "permission denied"}).encode())]
    )
    with pytest.raises(ProviderAuthorizationError):
        provider(transport).fetch_daily(DailyRequest(trade_date="20240102"))
    assert len(transport.calls) == 1


def test_provider_requires_credentials_before_transport() -> None:
    transport = FakeTransport([])
    provider_instance = TushareProvider(TushareConfig(token=""), transport=transport)

    with pytest.raises(ProviderCredentialsMissing):
        provider_instance.fetch_daily(DailyRequest(trade_date="20240102"))
    assert transport.calls == []


def test_provider_code_rate_limit_is_retried() -> None:
    transport = FakeTransport(
        [
            TransportResponse(200, json.dumps({"code": 429, "msg": "too fast"}).encode()),
            TransportResponse(200, envelope([])),
        ]
    )
    provider_instance = TushareProvider(
        TushareConfig(token="fixture-token", max_retries=1, backoff_seconds=0),
        transport=transport,
        sleep=lambda _seconds: None,
    )

    result = provider_instance.fetch_daily(DailyRequest(trade_date="20240102"))

    assert result.bars == ()
    assert len(transport.calls) == 2
