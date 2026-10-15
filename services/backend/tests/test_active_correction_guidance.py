"""Value-free validation DTOs do not impose a default correction count."""

from app.factor_research import FactorValidationError
from app.ml_validation import MLValidationError
from app.optimization_job import OptimizationValidationError
from app.strategy_artifact import StrategyValidationError


def test_active_validation_problems_have_no_fixed_correction_count() -> None:
    problems = [
        StrategyValidationError("private strategy detail", field="strategy.name", code="text_required").public_problem(),
        FactorValidationError("private factor detail", field="factor.name", code="unsupported_value").public_problem(),
        MLValidationError("private ML detail", field="target.horizon_sessions", code="integer_required").public_problem(),
        OptimizationValidationError("private optimization detail", field="candidate", code="object_required").public_problem(),
    ]
    expected = [
        {"schema_version": "strategy-validation-problem.v1", "field": "strategy.name", "code": "text_required"},
        {"schema_version": "factor-validation-problem.v1", "field": "factor.name", "code": "unsupported_value",
         "allowed_values": ["daily_return", "momentum"]},
        {"schema_version": "ml-validation-problem.v1", "field": "target.horizon_sessions", "code": "integer_required"},
        {"schema_version": "optimization-validation-problem.v1", "field": "candidate", "code": "object_required"},
    ]

    for problem, expected_problem in zip(problems, expected, strict=True):
        assert problem == expected_problem
        assert "repair_limit" not in problem
        assert "next_action" not in problem
        assert "private" not in str(problem)
