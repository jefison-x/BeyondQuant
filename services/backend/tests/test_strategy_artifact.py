from __future__ import annotations

import pytest

from app.strategy_artifact import (
    StrategyValidationError,
    export_strategy_version,
    prepare_strategy,
    strategy_version_content,
    validate_version_content,
)


VALID_SCRIPT = """
import pandas as pd

class CustomStrategy:
    def generate_signals(self, data, parameters=None):
        return {}
"""


def strategy_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "strategy_id": "MomentumStrategy",
        "name": "Momentum Strategy",
        "category": "momentum",
        "description": "A bounded strategy fixture.",
        "parameters": {"lookback": 20},
        "parameter_schema": {"lookback": {"type": "integer", "minimum": 1}},
        "source_type": "python_script",
        "script": VALID_SCRIPT,
    }
    payload.update(overrides)
    return payload


def test_strategy_version_identity_is_deterministic_and_excludes_runtime_time() -> None:
    first = prepare_strategy(strategy_payload())
    second = prepare_strategy(strategy_payload())

    assert first["version_id"] == second["version_id"]
    assert first["source_fingerprint"] == second["source_fingerprint"]
    assert first["validation"]["execution_check"]["status"] == "deferred"
    content = strategy_version_content(first)
    assert validate_version_content(content) == content
    assert export_strategy_version(content) == content["export"]


def test_optional_description_survives_validated_draft_to_version_round_trip() -> None:
    without_description = {
        key: value for key, value in strategy_payload().items() if key != "description"
    }
    draft = prepare_strategy(without_description)
    assert draft["snapshot"]["description"] == ""
    version = prepare_strategy(draft["snapshot"])
    assert version["version_id"] == draft["version_id"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"strategy_id": "1bad"}, "strategy_id"),
        ({"category": "unknown"}, "category"),
        ({"script": "import os\nclass CustomStrategy:\n    def generate_signals(self, data, parameters=None):\n        return {}"}, "import os"),
        ({"script": "class CustomStrategy:\n    def generate_signals(self, data, parameters=None):\n        return open('x')"}, "forbidden call open"),
        ({"script": "class CustomStrategy:\n    async def generate_signals(self, data, parameters=None):\n        return {}"}, "synchronous"),
        (
            {"script": "class CustomStrategy:\n    def generate_target_weights(self, data, portfolio_state, parameters):\n        for row in data:\n            model.fit(row)\n        return {}"},
            "model.fit",
        ),
        (
            {"script": "class CustomStrategy:\n    def generate_target_weights(self, data, portfolio_state, parameters):\n        return portfolio_state.current_date"},
            "current_date",
        ),
    ],
)
def test_invalid_strategy_is_rejected_before_artifact_materialization(change: dict[str, object], message: str) -> None:
    with pytest.raises(StrategyValidationError, match=message):
        prepare_strategy({**strategy_payload(), **change})


def test_export_rejects_credential_keys_without_copying_runtime_fields() -> None:
    prepared = prepare_strategy(strategy_payload())
    content = strategy_version_content(prepared)
    exported = export_strategy_version(content)
    assert "execution_outcome" not in exported
    assert "trace_id" not in exported
    with pytest.raises(StrategyValidationError, match="credential"):
        prepare_strategy({**strategy_payload(), "parameters": {"runtime_token": "never"}})


def test_strategy_version_freezes_only_closed_declared_data_dependencies() -> None:
    prepared = prepare_strategy(strategy_payload(data_requirements={
        "benchmark": "000300.SH",
        "index_universe": "000300.SH",
        "daily_basic": ["pb", "pe_ttm", "pb"],
        "fundamentals": ["roe", "netprofit_yoy"],
    }))

    assert prepared["snapshot"]["data_requirements"] == {
        "benchmark": "000300.SH", "index_universe": "000300.SH",
        "daily_basic": ["pb", "pe_ttm"],
        "fundamentals": ["netprofit_yoy", "roe"],
    }
    with pytest.raises(StrategyValidationError, match="unsupported fields"):
        prepare_strategy(strategy_payload(data_requirements={"daily_basic": ["future_magic"]}))
