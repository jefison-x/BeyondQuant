import pytest
from fastapi import HTTPException

from app.main import _ml_call, _research_call
from app.ml_strategy import normalize_ml_strategy
from app.ml_validation import MLValidationError
from tests.test_ml_strategy import valid_strategy, valid_strategy_v2, valid_regime_strategy_v2


@pytest.mark.parametrize("factory,path,value,field", [
    (valid_strategy, ("signal_policy", "rebalance"), [], "signal_policy"),
    (valid_strategy, ("learner_parameters", "learning_rate"), 10**400, "learner_parameters.learning_rate"),
    (valid_strategy, ("learner_parameters", "num_leaves"), 10**400, "learner_parameters.num_leaves"),
    (valid_strategy_v2, ("learner", "parameters", "alpha"), 10**400, "learner.parameters.alpha"),
    (valid_strategy_v2, ("validation_plan", "parameters", "folds"), 10**400, "validation_plan.parameters.folds"),
    (valid_regime_strategy_v2, ("experts", 0, "training_regimes"), [{}], "experts.0.training_regimes"),
    (valid_regime_strategy_v2, ("experts", 0, "learner", "parameters", "alpha"), "private-input", "experts.0.learner.parameters.alpha"),
])
def test_malformed_inputs_have_closed_value_free_validation(factory, path, value, field):
    strategy = factory()
    target = strategy
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(MLValidationError) as caught:
        normalize_ml_strategy(strategy)
    problem = caught.value.public_problem()
    assert problem["field"] == field
    assert problem["schema_version"] == "ml-validation-problem.v1"
    assert "private-input" not in str(problem)
    assert str(10**400) not in str(problem)
    for boundary in (_ml_call, _research_call):
        with pytest.raises(HTTPException) as response:
            boundary(lambda: normalize_ml_strategy(strategy))
        assert response.value.status_code == 422
        assert response.value.detail == problem
