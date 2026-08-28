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
_INTERNAL_PUBLIC_TERMS = (
    (re.compile(r"\bmcp__[a-z0-9_:./-]+\b", re.IGNORECASE), "系统能力"),
    (re.compile(r"\bbyq_market_session_context\b", re.IGNORECASE), "交易日与数据截止查询"),
    (re.compile(r"\bbyq_market_daily\b", re.IGNORECASE), "日线行情查询"),
    (re.compile(r"\bbyq_market_valuation\b", re.IGNORECASE), "估值数据查询"),
    (re.compile(r"\bbyq_market_fundamentals\b", re.IGNORECASE), "基本面数据查询"),
    (re.compile(r"\bbyq_[a-z0-9_]+\b", re.IGNORECASE), "系统能力"),
    (re.compile(r"\bcoverage\.[a-z0-9_.-]+\b", re.IGNORECASE), "数据覆盖状态"),
    (re.compile(r"\bWorkflowTrace\b", re.IGNORECASE), "执行记录"),
    (re.compile(r"\bArtifact\s+IDs?\b", re.IGNORECASE), "研究成果编号"),
    (re.compile(r"\bDSH\b", re.IGNORECASE), "智能体运行环境"),
    (re.compile(r"\bMCP\b", re.IGNORECASE), "系统能力"),
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
    for pattern, public in _INTERNAL_PUBLIC_TERMS:
        projected = pattern.sub(public, projected)
    return projected


def contains_internal_public_token(value: str) -> bool:
    """Return whether text still exposes a closed internal Product/Agent token."""

    return _INTERNAL_TOKEN.search(value) is not None
