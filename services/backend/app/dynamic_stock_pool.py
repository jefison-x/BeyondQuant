"""Closed, deterministic dynamic stock-pool rule contract (ADR-0041)."""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any


DYNAMIC_RULE_SCHEMA_VERSION = "dynamic-stock-pool-rule.v1"
SECURITY_FIELDS = {"exchange", "market", "industry", "area", "is_hs", "list_status"}
DAILY_BASIC_FIELDS = {
    "turnover_rate", "turnover_rate_f", "volume_ratio", "pe", "pe_ttm", "pb",
    "ps", "ps_ttm", "dv_ratio", "dv_ttm", "total_share", "float_share",
    "free_share", "total_mv", "circ_mv",
}
FINANCIAL_FIELDS = {
    "eps", "roe", "roa", "grossprofit_margin", "debt_to_assets", "or_yoy", "netprofit_yoy",
}
BAR_FIELDS = {"open", "high", "low", "close", "pre_close", "volume", "amount"}
WINDOW_PATTERN = re.compile(r"^window\.(avg_close|avg_volume|avg_amount)_(5|20|60)$")
OPERATORS = {"eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte"}
CADENCES = {"manual", "daily", "weekly", "monthly"}
WEIGHT_MODES = {"unweighted", "equal_weight"}
MAX_FILTERS = 20
MAX_TOP_N = 500


def _field(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("dynamic field must be a string")
    field = value.strip()
    prefix, _, name = field.partition(".")
    allowed = (
        prefix == "security" and name in SECURITY_FIELDS
        or prefix == "daily_basic" and name in DAILY_BASIC_FIELDS
        or prefix == "financial" and name in FINANCIAL_FIELDS
        or prefix == "bar" and name in BAR_FIELDS
        or WINDOW_PATTERN.fullmatch(field) is not None
    )
    if not allowed:
        raise ValueError(f"dynamic field is not allowlisted: {field}")
    return field


def _scalar(value: object, field: str) -> str | float | bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{field} must be finite")
        return number
    if isinstance(value, str) and value.strip() and len(value.strip()) <= 128:
        return value.strip()
    raise ValueError(f"{field} must be a bounded scalar")


def normalize_dynamic_rule(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("rule must be an object")
    unknown = set(value) - {
        "schema_version", "base_universe", "filters", "ranking", "top_n",
        "missing_policy", "weight_mode", "cadence",
    }
    if unknown:
        raise ValueError(f"rule has unknown fields: {', '.join(sorted(unknown))}")
    if value.get("schema_version", DYNAMIC_RULE_SCHEMA_VERSION) != DYNAMIC_RULE_SCHEMA_VERSION:
        raise ValueError("unsupported dynamic rule schema_version")
    base = value.get("base_universe")
    if not isinstance(base, dict) or set(base) - {"kind", "snapshot_id"}:
        raise ValueError("base_universe must use the closed schema")
    kind = base.get("kind")
    if kind == "security_master":
        normalized_base = {"kind": kind}
    elif kind == "stock_pool_snapshot":
        snapshot_id = base.get("snapshot_id")
        if not isinstance(snapshot_id, str) or not snapshot_id.strip() or len(snapshot_id.strip()) > 96:
            raise ValueError("base_universe.snapshot_id is invalid")
        normalized_base = {"kind": kind, "snapshot_id": snapshot_id.strip()}
    else:
        raise ValueError("base_universe.kind must be security_master or stock_pool_snapshot")

    raw_filters = value.get("filters", [])
    if not isinstance(raw_filters, list) or len(raw_filters) > MAX_FILTERS:
        raise ValueError(f"filters must contain at most {MAX_FILTERS} items")
    filters: list[dict[str, Any]] = []
    for index, item in enumerate(raw_filters):
        if not isinstance(item, dict) or set(item) != {"field", "operator", "value"}:
            raise ValueError(f"filters[{index}] must contain field, operator and value")
        field = _field(item["field"])
        operator = item["operator"]
        if operator not in OPERATORS:
            raise ValueError(f"filters[{index}].operator is not allowlisted")
        if operator in {"in", "not_in"}:
            raw_values = item["value"]
            if not isinstance(raw_values, list) or not raw_values or len(raw_values) > 50:
                raise ValueError(f"filters[{index}].value must be a non-empty bounded list")
            operand: object = [_scalar(entry, f"filters[{index}].value") for entry in raw_values]
        else:
            operand = _scalar(item["value"], f"filters[{index}].value")
        filters.append({"field": field, "operator": operator, "value": operand})

    ranking = value.get("ranking")
    normalized_ranking = None
    if ranking is not None:
        if not isinstance(ranking, dict) or set(ranking) != {"field", "direction"}:
            raise ValueError("ranking must contain field and direction")
        direction = ranking.get("direction")
        if direction not in {"asc", "desc"}:
            raise ValueError("ranking.direction must be asc or desc")
        normalized_ranking = {"field": _field(ranking.get("field")), "direction": direction}

    top_n = value.get("top_n")
    if not isinstance(top_n, int) or isinstance(top_n, bool) or not 1 <= top_n <= MAX_TOP_N:
        raise ValueError(f"top_n must be between 1 and {MAX_TOP_N}")
    missing_policy = value.get("missing_policy", "exclude")
    if missing_policy != "exclude":
        raise ValueError("missing_policy must be exclude")
    weight_mode = value.get("weight_mode", "unweighted")
    if weight_mode not in WEIGHT_MODES:
        raise ValueError("weight_mode must be unweighted or equal_weight")
    cadence = value.get("cadence", "manual")
    if cadence not in CADENCES:
        raise ValueError("cadence must be manual, daily, weekly or monthly")
    return {
        "schema_version": DYNAMIC_RULE_SCHEMA_VERSION,
        "base_universe": normalized_base,
        "filters": filters,
        "ranking": normalized_ranking,
        "top_n": top_n,
        "missing_policy": missing_policy,
        "weight_mode": weight_mode,
        "cadence": cadence,
    }


def required_fields(rule: dict[str, Any]) -> set[str]:
    fields = {str(item["field"]) for item in rule["filters"]}
    if rule.get("ranking"):
        fields.add(str(rule["ranking"]["field"]))
    return fields


def _compare(actual: object, operator: str, expected: object) -> bool:
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "in":
        return actual in expected  # type: ignore[operator]
    if operator == "not_in":
        return actual not in expected  # type: ignore[operator]
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        return False
    if isinstance(expected, bool) or not isinstance(expected, (int, float)):
        return False
    if operator == "gt":
        return actual > expected
    if operator == "gte":
        return actual >= expected
    if operator == "lt":
        return actual < expected
    return actual <= expected


def evaluate_dynamic_rule(
    rule: dict[str, Any], records: dict[str, dict[str, object]],
) -> tuple[list[str], dict[str, str]]:
    selected: list[tuple[str, object]] = []
    ranking = rule.get("ranking")
    for symbol in sorted(records):
        record = records[symbol]
        if any(
            item["field"] not in record
            or record[item["field"]] is None
            or not _compare(record[item["field"]], item["operator"], item["value"])
            for item in rule["filters"]
        ):
            continue
        rank_value = record.get(ranking["field"]) if ranking else symbol
        if rank_value is None:
            continue
        selected.append((symbol, rank_value))
    if ranking:
        reverse = ranking["direction"] == "desc"
        selected.sort(key=lambda item: (item[1], item[0]), reverse=reverse)
        if reverse:
            # Preserve canonical symbol ascending for equal descending values.
            selected.sort(key=lambda item: item[0])
            selected.sort(key=lambda item: item[1], reverse=True)
    symbols = [item[0] for item in selected[: rule["top_n"]]]
    if rule["weight_mode"] == "unweighted" or not symbols:
        return symbols, {}
    quantum = Decimal("0.000000000001")
    equal = (Decimal("1") / Decimal(len(symbols))).quantize(quantum)
    weights = {symbol: format(equal, "f") for symbol in symbols[:-1]}
    weights[symbols[-1]] = format((Decimal("1") - equal * (len(symbols) - 1)).quantize(quantum), "f")
    return symbols, weights
