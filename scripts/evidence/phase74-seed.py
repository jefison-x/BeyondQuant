#!/usr/bin/env python3
"""Seed deterministic, provider-labelled inputs for the Phase 74 real browser journey."""
from datetime import date, datetime, timedelta, timezone

from app.market_data import MarketDataStore
from app.market_readiness import MarketReadinessStore
from app.market_automation import MarketAutomationStore
from app.security_master import SecurityMasterStore
from app.user_auth import UserAuthStore

SYMBOLS = ("000001.SZ", "600000.SH")
BENCHMARK = "000300.SH"

def main() -> None:
    users = UserAuthStore.from_env()
    if not any(item["username"] == "phase74-user" for item in users.list_users(actor_role="admin")["users"]):
        users.create_user({"username": "phase74-user", "password": "phase74-user-test-only", "display_name": "Phase 74 Isolation User", "role": "user"}, actor_role="admin")
    bars, sessions, benchmark_bars = [], [], []
    day, previous = date(2025, 5, 1), {SYMBOLS[0]: 10.0, SYMBOLS[1]: 12.0, BENCHMARK: 100.0}
    while day <= date(2026, 3, 30):
        stamp = day.strftime("%Y%m%d"); sessions.append(stamp)
        for index, symbol in enumerate(SYMBOLS):
            step = len(sessions) + index * 7
            close = round(previous[symbol] * (1 + (0.002 + index * .0004) + ((step % 9) - 4) * .0007), 4)
            bars.append({"symbol": symbol, "trade_date": stamp, "open": previous[symbol], "high": round(max(previous[symbol], close) * 1.01, 4), "low": round(min(previous[symbol], close) * .99, 4), "close": close, "pre_close": previous[symbol], "volume": 1_000_000 + step * 12_000, "amount": close * (1_000_000 + step * 12_000), "adjust": "none", "asset_type": "stock", "data_source": "tushare", "volume_unit": "share", "amount_unit": "CNY", "provenance": {"purpose": "phase74_browser_evidence", "provider": "tushare", "synthetic_fixture": True}})
            previous[symbol] = close
        benchmark_close = round(previous[BENCHMARK] * (1.001 + ((len(sessions) % 13) - 6) * .00015), 4)
        benchmark_bars.append({
            "symbol": BENCHMARK, "trade_date": stamp, "open": previous[BENCHMARK],
            "high": round(max(previous[BENCHMARK], benchmark_close) * 1.005, 4),
            "low": round(min(previous[BENCHMARK], benchmark_close) * .995, 4),
            "close": benchmark_close, "pre_close": previous[BENCHMARK],
            "volume": 10_000_000 + len(sessions) * 25_000,
            "amount": benchmark_close * (10_000_000 + len(sessions) * 25_000),
        })
        previous[BENCHMARK] = benchmark_close
        day += timedelta(days=1)
    MarketDataStore.from_env().import_bars(bars)
    master = SecurityMasterStore.from_env(); retrieved = datetime.now(timezone.utc)
    master._execute("""INSERT INTO security_master_snapshots (snapshot_id,provider,endpoint,dataset_id,request_fingerprint,statuses_json,row_count,quarantined_count,retrieved_at,requested_by,created_at) VALUES ('phase74-security','tushare','stock_basic','phase74-security','phase74-request',:statuses,2,0,:at,'phase74-evidence',:at) ON CONFLICT(snapshot_id) DO UPDATE SET retrieved_at=excluded.retrieved_at,row_count=excluded.row_count,statuses_json=excluded.statuses_json""", {"statuses": ["L"], "at": retrieved})
    for symbol, exchange in ((SYMBOLS[0], "SZSE"), (SYMBOLS[1], "SSE")):
        master._execute("""INSERT INTO security_master_snapshot_members (snapshot_id,symbol,local_symbol,name,exchange,list_status,list_date,asset_type,content_sha256) VALUES ('phase74-security',:symbol,substring(:symbol,1,6),:symbol,:exchange,'L','19910101','stock',:sha) ON CONFLICT(snapshot_id,symbol) DO NOTHING""", {"symbol": symbol, "exchange": exchange, "sha": f"phase74-member-{symbol}"})
    automation, readiness = MarketAutomationStore.from_env(), MarketReadinessStore.from_env()
    for row in benchmark_bars:
        readiness._execute("""INSERT INTO market_index_daily
            (index_symbol,trade_date,open,high,low,close,pre_close,volume,amount,
             data_source,provenance_json,content_sha256,updated_at)
            VALUES (:symbol,:trade_date,:open,:high,:low,:close,:pre_close,:volume,:amount,
                    'tushare',:provenance,:sha,now())
            ON CONFLICT(index_symbol,trade_date) DO UPDATE SET
              open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,
              pre_close=excluded.pre_close,volume=excluded.volume,amount=excluded.amount,
              data_source=excluded.data_source,provenance_json=excluded.provenance_json,
              content_sha256=excluded.content_sha256,updated_at=excluded.updated_at""", {
                **row, "provenance": {"purpose": "phase86_browser_evidence", "provider": "tushare", "synthetic_fixture": True},
                "sha": f"phase86-index-{row['trade_date']}",
            })
    for stamp in sessions:
        automation._execute("""INSERT INTO market_trading_sessions (trade_date,exchange,is_open,data_source,request_fingerprint,retrieved_at,content_sha256,updated_at) VALUES (:date,'SSE',TRUE,'tushare','phase74-calendar',now(),:sha,now()) ON CONFLICT(trade_date) DO UPDATE SET is_open=TRUE,content_sha256=excluded.content_sha256,updated_at=excluded.updated_at""", {"date": stamp, "sha": f"phase74-calendar-{stamp}"})
        for symbol in SYMBOLS:
            row = next(item for item in bars if item["symbol"] == symbol and item["trade_date"] == stamp)
            readiness._execute("""INSERT INTO market_daily_status (symbol,trade_date,is_suspended,pre_close,up_limit,down_limit,data_source,provenance_json,content_sha256,updated_at) VALUES (:symbol,:date,FALSE,:pre,:up,:down,'tushare',:provenance,:sha,now()) ON CONFLICT(symbol,trade_date) DO NOTHING""", {"symbol": symbol, "date": stamp, "pre": row["pre_close"], "up": row["pre_close"] * 1.1, "down": row["pre_close"] * .9, "provenance": {"purpose": "phase74_browser_evidence"}, "sha": f"phase74-status-{symbol}-{stamp}"})
            readiness._execute("""INSERT INTO market_adjustment_factors (symbol,trade_date,adj_factor,data_source,provenance_json,content_sha256,updated_at) VALUES (:symbol,:date,1,'tushare',:provenance,:sha,now()) ON CONFLICT(symbol,trade_date) DO NOTHING""", {"symbol": symbol, "date": stamp, "provenance": {"purpose": "phase74_browser_evidence"}, "sha": f"phase74-factor-{symbol}-{stamp}"})
        readiness._execute("""INSERT INTO market_session_supplement_completeness (trade_date,adjustment_complete,corporate_actions_complete,factor_row_count,corporate_action_row_count,content_sha256,provenance_json,verified_at) VALUES (:date,TRUE,TRUE,2,0,:sha,:provenance,now()) ON CONFLICT(trade_date) DO UPDATE SET adjustment_complete=TRUE,corporate_actions_complete=TRUE,factor_row_count=2,content_sha256=excluded.content_sha256,verified_at=excluded.verified_at""", {"date": stamp, "sha": f"phase74-supplement-{stamp}", "provenance": {"purpose": "phase74_browser_evidence"}})
    print(f"Phase 74/86 inputs ready: sessions={len(sessions)}, bars={len(bars)}, benchmark_bars={len(benchmark_bars)}, symbols={len(SYMBOLS)}, isolation_user=phase74-user")

if __name__ == "__main__": main()
