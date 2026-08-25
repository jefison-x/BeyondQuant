from __future__ import annotations

import json

import pytest

from app.data_provider import (
    DailyRequest,
    ProviderAuthorizationError,
    ProviderCredentialsMissing,
    ProviderProtocolError,
    ProviderRateLimited,
    ProviderUnavailable,
    SecurityMasterRequest,
    TradingCalendarRequest,
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


def test_trading_calendar_is_bounded_normalized_and_secret_free() -> None:
    transport = FakeTransport([TransportResponse(200, envelope(
        [
            ["SSE", "20240831", 0, "20240830"],
            ["SSE", "20240830", 1, "20240829"],
        ],
        fields=["exchange", "cal_date", "is_open", "pretrade_date"],
    ))])

    result = provider(transport).fetch_trading_calendar(
        TradingCalendarRequest("20240830", "20240831"),
    )

    assert [item.trade_date for item in result.sessions] == ["20240830", "20240831"]
    assert result.sessions[0].is_open is True
    assert result.sessions[1].is_open is False
    assert result.provenance.endpoint == "trade_cal"
    assert transport.calls[0][1]["params"] == {
        "exchange": "SSE", "start_date": "20240830", "end_date": "20240831",
    }
    assert "fixture-token" not in json.dumps(result.provenance.as_dict())


def test_trading_calendar_rejects_duplicate_and_invalid_rows() -> None:
    duplicate = ["SSE", "20240830", 1, "20240829"]
    transport = FakeTransport([TransportResponse(200, envelope(
        [duplicate, duplicate], fields=["exchange", "cal_date", "is_open", "pretrade_date"],
    ))])
    with pytest.raises(ProviderProtocolError, match="duplicate"):
        provider(transport).fetch_trading_calendar(TradingCalendarRequest("20240830", "20240831"))

    with pytest.raises(ValueError, match="401 days"):
        TradingCalendarRequest("20240101", "20250205").normalized()


def security_envelope(items: list[list[object]]) -> bytes:
    return envelope(items, fields=[
        "ts_code", "symbol", "name", "area", "industry", "market",
        "exchange", "list_status", "list_date", "delist_date", "is_hs",
    ])


def test_security_master_fetches_all_lifecycle_states_and_is_content_addressed() -> None:
    transport = FakeTransport([
        TransportResponse(200, security_envelope([
            ["600000.SH", "600000", "浦发银行", "上海", "银行", "主板", "SSE", "L", "19991110", None, "H"],
        ])),
        TransportResponse(200, security_envelope([
            ["000001.SZ", "000001", "平安银行", "深圳", "银行", "主板", "SZSE", "P", "19910403", None, "S"],
        ])),
        TransportResponse(200, security_envelope([
            ["430001.BJ", "430001", "历史样本", "北京", None, "北交所", "BSE", "D", "20120101", "20200101", "N"],
            ["T600018.SH", "T600018", "上港集箱(退)", None, None, None, "SSE", "D", "20000719", "20061020", "N"],
        ])),
    ])

    result = provider(transport).fetch_security_master()

    assert [item.symbol for item in result.records] == ["000001.SZ", "430001.BJ", "600000.SH"]
    assert result.statuses == ("L", "P", "D")
    assert [item.provider_symbol for item in result.quarantined] == ["T600018.SH"]
    assert result.quarantined[0].reason == "tushare_historical_alias"
    assert len(result.dataset_id) == 64
    assert result.provenance.endpoint == "stock_basic"
    assert result.provenance.row_count == 4
    assert [call[1]["params"]["list_status"] for call in transport.calls] == ["L", "P", "D"]
    assert "fixture-token" not in json.dumps({
        "records": [item.as_dict() for item in result.records],
        "provenance": result.provenance.as_dict(),
    }, ensure_ascii=False)


def test_security_master_request_and_rows_fail_closed() -> None:
    with pytest.raises(ValueError, match="unique L, P, or D"):
        SecurityMasterRequest(("L", "L")).normalized()

    wrong_status = FakeTransport([
        TransportResponse(200, security_envelope([
            ["600000.SH", "600000", "浦发银行", "上海", "银行", "主板", "SSE", "D", "19991110", None, "H"],
        ])),
    ])
    with pytest.raises(ProviderProtocolError, match="outside the requested status"):
        provider(wrong_status).fetch_security_master(SecurityMasterRequest(("L",)))

    wrong_exchange = FakeTransport([
        TransportResponse(200, security_envelope([
            ["600000.SH", "600000", "浦发银行", "上海", "银行", "主板", "SZSE", "L", "19991110", None, "H"],
        ])),
    ])
    with pytest.raises(ProviderProtocolError, match="mismatched security exchange"):
        provider(wrong_exchange).fetch_security_master(SecurityMasterRequest(("L",)))

    unknown_identity = FakeTransport([
        TransportResponse(200, security_envelope([
            ["X600000.SH", "X600000", "未知别名", "上海", None, None, "SSE", "L", "19991110", None, "N"],
        ])),
    ])
    with pytest.raises(ProviderProtocolError, match="non-canonical security symbol"):
        provider(unknown_identity).fetch_security_master(SecurityMasterRequest(("L",)))


def test_security_master_rejects_duplicate_identity_across_statuses() -> None:
    row = ["600000.SH", "600000", "浦发银行", "上海", "银行", "主板", "SSE", "L", "19991110", None, "H"]
    duplicate = row.copy()
    duplicate[7] = "D"
    transport = FakeTransport([
        TransportResponse(200, security_envelope([row])),
        TransportResponse(200, security_envelope([duplicate])),
    ])

    with pytest.raises(ProviderProtocolError, match="duplicate security-master identities"):
        provider(transport).fetch_security_master(SecurityMasterRequest(("L", "D")))


def test_exact_session_status_contracts_are_closed_and_validated() -> None:
    transport = FakeTransport([
        TransportResponse(200, envelope(
            [["20240102", "000001.SZ", 10, 11, 9]],
            fields=["trade_date", "ts_code", "pre_close", "up_limit", "down_limit"],
        )),
        TransportResponse(200, envelope(
            [["000002.SZ", "20240102", "全天", "S"]],
            fields=["ts_code", "trade_date", "suspend_timing", "suspend_type"],
        )),
    ])
    instance = provider(transport)
    limits = instance.fetch_price_limits("20240102")
    suspensions = instance.fetch_suspensions("20240102")

    assert limits.limits[0].up_limit == 11
    assert suspensions.suspensions[0].suspend_type == "S"
    assert [call[1]["api_name"] for call in transport.calls] == ["stk_limit", "suspend_d"]
    assert all(call[1]["params"] == {"trade_date": "20240102"} for call in transport.calls)


def test_adjustment_and_implemented_action_contracts_are_exact_and_secret_free() -> None:
    transport = FakeTransport([
        TransportResponse(200, envelope(
            [["000001.SZ", "20240103", 2.0]],
            fields=["ts_code", "trade_date", "adj_factor"],
        )),
        TransportResponse(200, envelope(
            [["000001.SZ", "20231231", "20230301", "实施", 1.0, 0.4, 0.6,
              0.2, 0.25, "20240102", "20240103", "20240104", "20240105", "20231220"]],
            fields=["ts_code", "end_date", "ann_date", "div_proc", "stk_div",
                    "stk_bo_rate", "stk_co_rate", "cash_div", "cash_div_tax",
                    "record_date", "ex_date", "pay_date", "div_listdate", "imp_ann_date"],
        )),
    ])
    instance = provider(transport)

    factors = instance.fetch_adjustment_factors("20240103")
    actions = instance.fetch_corporate_actions("20240103")

    assert factors.factors[0].adj_factor == 2
    assert actions.actions[0].cash_dividend_net == 0.2
    assert actions.actions[0].cash_dividend_gross == 0.25
    assert actions.actions[0].as_dict()["share_ratio"] == 1
    assert [call[1]["api_name"] for call in transport.calls] == ["adj_factor", "dividend"]
    assert transport.calls[0][1]["params"] == {"trade_date": "20240103"}
    assert transport.calls[1][1]["params"] == {"ex_date": "20240103"}
    assert "fixture-token" not in json.dumps([
        factors.provenance.as_dict(), actions.provenance.as_dict(), actions.actions[0].as_dict(),
    ], ensure_ascii=False)


def test_adjustment_and_corporate_actions_fail_closed() -> None:
    bad_factor = FakeTransport([TransportResponse(200, envelope(
        [["000001.SZ", "20240103", 0]], fields=["ts_code", "trade_date", "adj_factor"],
    ))])
    with pytest.raises(ProviderProtocolError, match="invalid adjustment factor"):
        provider(bad_factor).fetch_adjustment_factors("20240103")

    proposal = FakeTransport([TransportResponse(200, envelope(
        [["000001.SZ", "20231231", "20230301", "预案", 0, 0, 0, 0.2, 0.25,
          "20240102", "20240103", "20240104", None, None]],
        fields=["ts_code", "end_date", "ann_date", "div_proc", "stk_div",
                "stk_bo_rate", "stk_co_rate", "cash_div", "cash_div_tax",
                "record_date", "ex_date", "pay_date", "div_listdate", "imp_ann_date"],
    ))])
    with pytest.raises(ProviderProtocolError, match="non-implemented"):
        provider(proposal).fetch_corporate_actions("20240103")


def test_declared_research_input_contracts_are_bounded_and_point_in_time() -> None:
    transport = FakeTransport([
        TransportResponse(200, envelope(
            [["000300.SH", "20240102", 3500, 3520, 3490, 3510, 3480, 30, .86, 100, 2000]],
            fields=["ts_code", "trade_date", "open", "high", "low", "close", "pre_close",
                    "change", "pct_chg", "vol", "amount"],
        )),
        TransportResponse(200, envelope(
            [["000300.SH", "000001.SZ", "20240102", 1.5]],
            fields=["index_code", "con_code", "trade_date", "weight"],
        )),
        TransportResponse(200, envelope(
            [["000001.SZ", "20240102", 1, 1.1, 1.2, 10, 9, 1, 2, 2.1, .5, .6, 100, 80, 70, 1000, 800]],
            fields=["ts_code", "trade_date", "turnover_rate", "turnover_rate_f", "volume_ratio",
                    "pe", "pe_ttm", "pb", "ps", "ps_ttm", "dv_ratio", "dv_ttm",
                    "total_share", "float_share", "free_share", "total_mv", "circ_mv"],
        )),
        TransportResponse(200, envelope(
            [["000001.SZ", "20240420", "20240331", 1.0, 12.0, 1.1, 30.0, 40.0, 5.0, 6.0, "1"]],
            fields=["ts_code", "ann_date", "end_date", "eps", "roe", "roa",
                    "grossprofit_margin", "debt_to_assets", "or_yoy", "netprofit_yoy", "update_flag"],
        )),
    ])
    instance = provider(transport)

    assert instance.fetch_index_daily("000300.SH", "20240102", "20240102").bars[0].close == 3510
    assert instance.fetch_index_weights("000300.SH", "20240101", "20240131").weights[0].weight == 1.5
    assert instance.fetch_daily_basic("20240102").rows[0].values["pe_ttm"] == 9
    assert instance.fetch_financial_indicators("000001.SZ", "20230101", "20241231").rows[0].announcement_date == "20240420"
    assert [call[1]["api_name"] for call in transport.calls] == [
        "index_daily", "index_weight", "daily_basic", "fina_indicator",
    ]
    assert transport.calls[3][1]["params"] == {
        "ts_code": "000001.SZ", "start_date": "20230101", "end_date": "20241231",
    }
