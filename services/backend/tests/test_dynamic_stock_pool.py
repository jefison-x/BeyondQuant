from __future__ import annotations

import pytest

from app.dynamic_stock_pool import evaluate_dynamic_rule, normalize_dynamic_rule


def _rule() -> dict[str, object]:
    return {
        "schema_version": "dynamic-stock-pool-rule.v1",
        "base_universe": {"kind": "security_master"},
        "filters": [
            {"field": "security.exchange", "operator": "in", "value": ["SSE", "SZSE"]},
            {"field": "daily_basic.pb", "operator": "lte", "value": 2.0},
        ],
        "ranking": {"field": "daily_basic.total_mv", "direction": "desc"},
        "top_n": 2,
        "missing_policy": "exclude",
        "weight_mode": "equal_weight",
        "cadence": "weekly",
    }


def test_closed_rule_is_normalized_and_evaluated_deterministically() -> None:
    rule = normalize_dynamic_rule(_rule())
    records = {
        "600000.SH": {"security.exchange": "SSE", "daily_basic.pb": 1.2, "daily_basic.total_mv": 20.0},
        "000001.SZ": {"security.exchange": "SZSE", "daily_basic.pb": 1.5, "daily_basic.total_mv": 20.0},
        "300750.SZ": {"security.exchange": "SZSE", "daily_basic.pb": 5.0, "daily_basic.total_mv": 99.0},
        "000002.SZ": {"security.exchange": "SZSE", "daily_basic.pb": None, "daily_basic.total_mv": 30.0},
    }
    symbols, weights = evaluate_dynamic_rule(rule, records)
    assert symbols == ["000001.SZ", "600000.SH"]
    assert weights == {"000001.SZ": "0.500000000000", "600000.SH": "0.500000000000"}


@pytest.mark.parametrize("mutation", [
    {"filters": [{"field": "sql.drop_table", "operator": "eq", "value": 1}]},
    {"filters": [{"field": "daily_basic.pb", "operator": "exec", "value": 1}]},
    {"base_universe": {"kind": "url", "snapshot_id": "https://example.com"}},
    {"missing_policy": "fill_zero"},
    {"top_n": 501},
])
def test_closed_rule_rejects_code_sql_url_and_unbounded_shapes(mutation: dict[str, object]) -> None:
    value = _rule()
    value.update(mutation)
    with pytest.raises(ValueError):
        normalize_dynamic_rule(value)
