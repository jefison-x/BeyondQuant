"""Framework-neutral public language projection for Product Agent answers."""

from __future__ import annotations

import re


_PRODUCT_TERMS = {
    "orchestration & governance": "任务管理",
    "backtest analysis": "回测分析",
    "strategy research": "策略研究",
    "factor research": "因子研究",
    "market research": "市场研究",
    "coverage.usable=false": "当前数据覆盖不足，暂不适合比较",
    "coverage.usable=true": "当前数据覆盖已验证",
    "coverage_unverified": "覆盖完整性尚未验证",
    "grossprofit_margin": "销售毛利率",
    "turnover_rate_f": "自由流通股换手率",
    "netprofit_yoy": "净利润同比增速",
    "debt_to_assets": "资产负债率",
    "turnover_rate": "换手率",
    "volume_ratio": "量比",
    "total_share": "总股本",
    "float_share": "流通股本",
    "free_share": "自由流通股本",
    "total_mv": "总市值",
    "circ_mv": "流通市值",
    "pe_ttm": "市盈率（TTM）",
    "ps_ttm": "市销率（TTM）",
    "dv_ratio": "股息率",
    "dv_ttm": "股息率（TTM）",
    "or_yoy": "营业收入同比增速",
    "ann_date": "公告日期",
    "end_date": "报告期",
    "update_flag": "报告更新标记",
}
_INTERNAL_TOKEN = re.compile(
    r"(?:\bbyq_[a-z0-9_]+\b|\bmcp__[a-z0-9_:./-]+\b|\bcoverage\.[a-z0-9_.-]+\b|"
    r"\bWorkflowTrace\b|\bArtifact\s+IDs?\b|\bDSH\b|\bMCP\b)",
    re.IGNORECASE,
)


def project_public_answer_text(value: str) -> str:
    """Translate closed domain field names without altering financial evidence."""

    projected = value
    for internal, public in sorted(
        _PRODUCT_TERMS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        projected = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(internal)}(?![A-Za-z0-9_])",
            public,
            projected,
            flags=re.IGNORECASE,
        )
    return projected


def contains_internal_public_token(value: str) -> bool:
    """Return whether text still exposes a closed internal Product/Agent token."""

    return _INTERNAL_TOKEN.search(value) is not None
