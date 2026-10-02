"""Continuation limits and usage contracts run in the stdlib architecture lane."""
import unittest
from packages.contracts.continuation_request import USAGE_SCHEMA_VERSION, profile_binding, request_limits, unknown_actual_usage, validate_request_usage, validate_profile_binding, validate_limits, exceeded_request_limits

def receipt():
    return dict(schema_version=USAGE_SCHEMA_VERSION, execution_profile=profile_binding(), request_limits=request_limits(), limit_violations=[], admission_usage=dict(provider_calls=1, provider_attempts=1, input_bytes=100, declared_output_tokens=8192, tool_payload_bytes=20, max_input_bytes=100, max_declared_output_tokens=8192, max_tool_payload_bytes=20, tool_calls=1, max_concurrent=1, elapsed_ms=100), actual_usage=unknown_actual_usage())

class ContinuationRequestContractTests(unittest.TestCase):

    def test_unknown_actual_usage_is_not_replaced_by_safe_output_allowance(self):
        value = receipt()
        self.assertTrue(validate_request_usage(value) == value)
        self.assertTrue(exceeded_request_limits(value) == [])
        self.assertTrue(value['actual_usage']['output_tokens'] == 'unknown')
        result = validate_request_usage(value)
        result['request_limits']['max_attempts'] = 999
        self.assertTrue(value['request_limits']['max_attempts'] == 16)

    def test_profile_limits_cannot_be_raised_or_lowered_by_carrier(self):
        for bound in list(request_limits()):
            with self.subTest(bound=bound):
                limits = request_limits()
                limits[bound] += 1
                with self.assertRaisesRegex(ValueError, 'overridden'):
                    validate_limits(limits)

    def test_profile_version_boolean_is_not_integer_identity(self):
        profile = profile_binding()
        profile['profile_version'] = True
        with self.assertRaisesRegex(ValueError, 'profile'):
            validate_profile_binding(profile)

    def test_terminal_overrun_is_preserved_and_classified(self):
        for measurement, bound in [('provider_calls', 'max_provider_calls'), ('provider_attempts', 'max_attempts'), ('input_bytes', 'max_total_input_bytes'), ('declared_output_tokens', 'max_total_output_tokens'), ('tool_payload_bytes', 'max_total_tool_payload_bytes'), ('tool_calls', 'max_tool_calls'), ('max_concurrent', 'max_concurrent'), ('elapsed_ms', 'deadline_ms'), ('max_input_bytes', 'max_input_bytes'), ('max_declared_output_tokens', 'max_output_tokens'), ('max_tool_payload_bytes', 'max_tool_payload_bytes')]:
            with self.subTest(measurement=measurement, bound=bound):
                value = receipt()
                admission = value['admission_usage']
                admission[measurement] = request_limits()[bound] + 1
                if measurement in {'provider_calls', 'provider_attempts'}:
                    admission.update(provider_calls=17, provider_attempts=17)
                for peak, total in [('max_input_bytes', 'input_bytes'), ('max_declared_output_tokens', 'declared_output_tokens'), ('max_tool_payload_bytes', 'tool_payload_bytes')]:
                    admission[total] = max(admission[peak], admission[total])
                self.assertTrue(validate_request_usage(value) == value)
                self.assertTrue(bound in exceeded_request_limits(value))

    def test_actual_counts_require_nonnegative_builtin_integer_or_unknown(self):
        for count in ['input_tokens', 'cache_read_tokens', 'output_tokens', 'provider_attempts']:
            for bad in [True, -1, 1.5]:
                with self.subTest(count=count, bad=bad):
                    value = receipt()
                    value['actual_usage'][count] = bad
                    with self.assertRaises(ValueError):
                        validate_request_usage(value)

    def test_usage_source_and_completeness_are_factual(self):
        value = receipt()
        actual = value['actual_usage']
        actual.update(input_tokens=10, cache_read_tokens=0, output_tokens='unknown', provider_attempts=1, usage_source='provider_response', completeness='partial')
        self.assertTrue(validate_request_usage(value) == value)
        actual['completeness'] = 'known'
        with self.assertRaisesRegex(ValueError, 'cannot be complete'):
            validate_request_usage(value)
        actual['completeness'] = 'partial'
        actual['usage_source'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'factual source'):
            validate_request_usage(value)

    def test_proven_no_calls_is_zero_and_known_only(self):
        value = receipt()
        value['admission_usage'] = {k: 0 for k in value['admission_usage']}
        value['actual_usage'] = dict(input_tokens=0, cache_read_tokens=0, output_tokens=0, provider_attempts=0, usage_source='no_provider_calls', completeness='known')
        self.assertTrue(validate_request_usage(value) == value)
        value['admission_usage'].update(provider_calls=1, provider_attempts=1)
        with self.assertRaisesRegex(ValueError, 'proven zero'):
            validate_request_usage(value)

    def test_schema_and_attempt_identity_do_not_allow_receipt_reinterpretation(self):
        value = receipt()
        value['schema_version'] = 'task-continuation-budget.v1'
        with self.assertRaises(ValueError):
            validate_request_usage(value)
        value = receipt()
        value['admission_usage']['provider_calls'] = 0
        with self.assertRaisesRegex(ValueError, 'HTTP attempts'):
            validate_request_usage(value)
        value = receipt()
        value['admission_usage']['max_input_bytes'] = 101
        with self.assertRaisesRegex(ValueError, 'peak exceeds'):
            validate_request_usage(value)

    def test_per_call_provider_violation_is_retained_when_totals_are_below_profile_caps(self):
        value = receipt()
        value['limit_violations'] = ['provider_declared_output_exceeded']
        self.assertTrue(validate_request_usage(value) == value)
        self.assertTrue(exceeded_request_limits(value) == ['provider_declared_output_exceeded'])

    def test_violation_names_are_closed_facts(self):
        for violations in [['unknown'], ['max_attempts', 'max_attempts'], [True], 'max_attempts']:
            with self.subTest(violations=violations):
                value = receipt()
                value['limit_violations'] = violations
                with self.assertRaisesRegex(ValueError, 'limit violations'):
                    validate_request_usage(value)
