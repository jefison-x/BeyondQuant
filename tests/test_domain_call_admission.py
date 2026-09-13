import json
import unittest

from packages.contracts.domain_call_admission import (
    MAX_INPUT_BYTES, call_evidence_receipt, parse_observed_arguments, request_evidence, validate_call_evidence,
)


class DomainCallAdmissionTests(unittest.TestCase):
    def request(self, **changes):
        return {"task_id": "task_original", "agent_run_id": "agent_original", "idempotency_key": "original",
                "strategy": {"参数": {"weight": 1, "label": "合成测试"}}, **changes}

    def evidence(self, payload=None, action="byq_strategy_validate"):
        return request_evidence(action, self.request() if payload is None else payload, trace_id="trusted-trace")

    def test_version_replay_cannot_buy_correction_with_new_run_or_key(self):
        payload = {"task_id": "task_original", "agent_run_id": "run_original",
                   "idempotency_key": "original", "draft_artifact_id": "draft_original"}
        def evidence(value):
            return request_evidence("byq_strategy_version_create", value, trace_id="trusted")
        original = evidence(payload)
        replay = evidence({**payload, "agent_run_id": "new_run", "idempotency_key": "new_key"})
        self.assertEqual(original["input_sha256"], replay["input_sha256"])
        self.assertNotEqual(original["request_sha256"], replay["request_sha256"])
        self.assertNotEqual(original["input_sha256"], evidence({**payload, "draft_artifact_id": "different"})["input_sha256"])
        for field in payload:
            incomplete = {key: value for key, value in payload.items() if key != field}
            with self.subTest(field=field), self.assertRaises(ValueError):
                evidence(incomplete)
        for extra in ({"root_run_id": "guessed"}, {"strategy": {}}, {"owner_id": "guessed"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                evidence({**payload, **extra})

    def test_factor_tables_have_separate_bounded_evidence(self):
        payload = {"task_id": "task_one", "agent_run_id": "run_one", "idempotency_key": "key",
            "as_of_date": "20260901", "factor": {"name": "momentum", "version": "1", "lookback": 2},
            "securities": [{"symbol": "000001.SZ", "asset_type": "stock"}] * 64,
            "sessions": [{"trade_date": "20260831", "is_open": True}] * 512,
            "bars": [{"symbol": "000001.SZ", "trade_date": "20260831", "open": 1, "high": 1, "low": 1, "close": 1}] * 2048,
            "statuses": [{"symbol": "000001.SZ", "trade_date": "20260831", "state": "suspended", "reason": "x" * 256}] * 4096,
            "universe_snapshots": [{"snapshot_date": "20260831", "symbols": ["000001.SZ"] * 64}] * 64,
            "sources": [{"provider": "tushare", "endpoint": "daily", "request_fingerprint": "x" * 256, "dataset_id": "x" * 256}] * 64}
        raw = json.dumps(payload)
        self.assertEqual(parse_observed_arguments(raw, action="byq_factor_compute"), payload)
        original = request_evidence("byq_factor_compute", payload, trace_id="trusted")
        changed = request_evidence("byq_factor_compute", {**payload, "idempotency_key": "another", "agent_run_id": "child"}, trace_id="trusted")
        self.assertEqual(original["input_sha256"], changed["input_sha256"])
        with self.assertRaises(ValueError):
            parse_observed_arguments(raw)
        with self.assertRaises(ValueError):
            parse_observed_arguments(json.dumps({"x": "x" * (4 * 1024 * 1024)}), action="byq_factor_compute")

    def test_trace_enrichment_order_and_numeric_spelling_are_stable(self):
        first = self.request(trace_id="model-guessed-trace")
        second = dict(reversed(list(json.loads(json.dumps(first)).items())))
        second["trace_id"] = "trusted-trace"
        second["strategy"]["参数"]["weight"] = 1.0
        self.assertEqual(self.evidence(first), self.evidence(second))
        self.assertEqual(self.evidence(self.request(strategy={"x": -0.0})),
                         self.evidence(self.request(strategy={"x": 0})))

    def test_replay_identity_is_not_correction_progress(self):
        original = self.evidence()
        changed = self.evidence(self.request(agent_run_id="another-child", idempotency_key="new-key"))
        self.assertNotEqual(original["request_sha256"], changed["request_sha256"])
        self.assertEqual(original["input_sha256"], changed["input_sha256"])
        for payload in (self.request(task_id="other-task"), self.request(strategy={"参数": 2})):
            self.assertNotEqual(original["input_sha256"], self.evidence(payload)["input_sha256"])
        self.assertNotEqual(original["input_sha256"], self.evidence(action="byq_ml_strategy_create")["input_sha256"])

    def test_input_digest_does_not_collapse_json_types(self):
        hashes = {self.evidence(self.request(strategy=value))["input_sha256"] for value in (None, True, 1, "1", [], {})}
        self.assertEqual(len(hashes), 6)

    def test_missing_references_never_become_proof(self):
        for key in ("task_id", "agent_run_id", "idempotency_key", "strategy"):
            value = self.request()
            del value[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.evidence(value)
        with self.assertRaises(ValueError):
            self.evidence(self.request(root_run_id="model-root"))

    def test_unrepresentable_or_unbounded_inputs_are_rejected(self):
        nested = None
        for _ in range(30):
            nested = [nested]
        for value in (float("nan"), float("inf"), 2**53, 10**1000, "\ud800", [0] * 8193,
                      "大" * MAX_INPUT_BYTES, nested):
            with self.subTest(kind=type(value).__name__), self.assertRaises(ValueError):
                self.evidence(self.request(strategy=value))

    def test_observed_json_is_strict_and_bounded(self):
        self.assertEqual(parse_observed_arguments(json.dumps(self.request())), self.request())
        for raw in ("{", "[]", '{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}',
                    '{"x":9007199254740992}', '{"x":"\\ud800"}', {}, " " * (MAX_INPUT_BYTES + 1)):
            with self.subTest(raw_type=type(raw).__name__), self.assertRaises(ValueError):
                parse_observed_arguments(raw)

    def test_private_contract_rejects_additional_raw_fields_and_tampering(self):
        event = {"schema_version": "domain-call-observed.v1", "sequence": 1, "root_run_id": "a" * 32,
                 "generation": "generation", "call_id": "call", **self.evidence()}
        self.assertEqual(validate_call_evidence(event), event)
        receipt = call_evidence_receipt(event)
        self.assertNotEqual(receipt, call_evidence_receipt({**event, "call_id": "other"}))
        for changes in ({"arguments": self.request()}, {"sequence": True}, {"root_run_id": "model-root"},
                        {"request_sha256": ""}, {"call_id": "\ninvalid"}):
            with self.subTest(changes=tuple(changes)), self.assertRaises(ValueError):
                validate_call_evidence({**event, **changes})


if __name__ == "__main__":
    unittest.main()
