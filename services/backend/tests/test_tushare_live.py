from __future__ import annotations

import os

import pytest

from app.data_provider import DailyRequest, TushareConfig, TushareProvider


TOKEN = os.getenv("TUSHARE_TOKEN", "").strip()
RUN_LIVE = os.getenv("TUSHARE_LIVE_TEST") == "1"


@pytest.mark.skipif(not TOKEN or not RUN_LIVE, reason="Tushare live test is opt-in")
def test_tushare_daily_live_smoke() -> None:
    provider = TushareProvider(TushareConfig(token=TOKEN, max_retries=1))
    result = provider.fetch_daily(
        DailyRequest(ts_code="000001.SZ", start_date="20240102", end_date="20240103")
    )

    assert all(bar.ts_code == "000001.SZ" for bar in result.bars)
    assert result.provenance.provider == "tushare"
    assert TOKEN not in repr(result)
