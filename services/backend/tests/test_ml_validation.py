from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.main import _ml_call, _research_call
from app.ml_strategy import normalize_ml_strategy
from app.ml_validation import MLValidationError
from tests.test_ml_strategy import valid_strategy, valid_strategy_v2


@pytest.mark.parametrize("factory,path,value", [
    (valid_strategy, ("target", "horizon_sessions"), "bad"),
    (valid_strategy, ("split", "train", "start"), "invalid"),
    (valid_strategy_v2, ("learner", "parameters", "alpha"), -1),
    (valid_strategy_v2, ("validation_plan", "parameters", "folds"), 100),
])
def test_ml_field_problem_is_value_free(factory, path, value):
    strategy = factory()
    target = strategy
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = value
    for route in (_ml_call, _research_call):
        with pytest.raises(HTTPException) as caught:
            route(lambda: normalize_ml_strategy(strategy))
        assert caught.value.status_code == 422
        assert caught.value.detail["field"] == ".".join(path)
        assert caught.value.detail["repair_limit"] == 1
        assert set(caught.value.detail) == {"schema_version", "field", "code", "repair_limit", "next_action"}


def test_unknown_input_fields_and_exception_text_are_not_public():
    strategy = valid_strategy()
    strategy["learner"]["private-secret-input"] = "token=synthetic-secret"
    with pytest.raises(MLValidationError) as caught:
        normalize_ml_strategy(strategy)
    problem = caught.value.public_problem()
    assert problem["field"] == "learner" and problem["code"] == "unknown_fields"
    assert "secret" not in str(problem)
    assert MLValidationError("secret", field="private-secret", code="secret").public_problem()["field"] == "strategy"
