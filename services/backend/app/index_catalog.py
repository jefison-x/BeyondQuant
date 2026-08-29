"""Closed canonical index catalogue owned by the BYQ Data Plane."""

from __future__ import annotations


INDEX_CATALOG_CONTRACT = "index-catalogue.v1"
INDEX_WEIGHT_LOOKBACK_DAYS = 62

# Provider aliases such as 399300.SZ/399905.SZ are deliberately excluded.
# A Product index identity must have one canonical symbol and independently
# verified index-weight evidence before it becomes selectable.
SUPPORTED_INDEXES: tuple[dict[str, str], ...] = (
    {"index_symbol": "000016.SH", "name": "上证50", "family": "SSE"},
    {"index_symbol": "000300.SH", "name": "沪深300", "family": "CSI"},
    {"index_symbol": "000688.SH", "name": "科创50", "family": "SSE"},
    {"index_symbol": "000852.SH", "name": "中证1000", "family": "CSI"},
    {"index_symbol": "000905.SH", "name": "中证500", "family": "CSI"},
    {"index_symbol": "399006.SZ", "name": "创业板指", "family": "SZSE"},
)

INDEX_NAMES = {item["index_symbol"]: item["name"] for item in SUPPORTED_INDEXES}
SUPPORTED_INDEX_SYMBOLS = tuple(item["index_symbol"] for item in SUPPORTED_INDEXES)

