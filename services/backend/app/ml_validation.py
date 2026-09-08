"""Closed, value-free ML correction hints; never serialize exception text."""

_FIELDS = frozenset("strategy schema_version name learner kind profile parameters learner_parameters feature_set id target horizon_sessions split train validation prediction start end signal_policy top_n rebalance validation_plan development_window prediction_window portfolio_policy mode train_sessions validation_sessions step_sessions folds purge_sessions embargo_sessions alpha fit_intercept num_leaves learning_rate max_depth min_data_in_leaf feature_fraction bagging_fraction num_boost_round early_stopping_rounds regime definition enabled routing_policy fallback experts risk_on neutral risk_off training_regimes".split())
_CODES = frozenset({"object_required", "unknown_fields", "text_required", "date_format", "integer_required",
                    "number_required", "boolean_required", "out_of_range", "unsupported_value"})


class MLValidationError(ValueError):
    def __init__(self, message: str, *, field: str, code: str):
        super().__init__(message)
        segments = field.split(".")
        self.field = field if len(segments) <= 6 and all(part in _FIELDS or part in {"0", "1", "2", "3"} for part in segments) else "strategy"
        self.code = code if code in _CODES else "unsupported_value"

    def public_problem(self) -> dict[str, object]:
        return {"schema_version": "ml-validation-problem.v1", "field": self.field, "code": self.code,
                "repair_limit": 1, "next_action": "read_capabilities_then_correct_once"}
