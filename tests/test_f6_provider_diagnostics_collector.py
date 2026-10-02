"""Fail-closed upload boundary for private synthetic-provider diagnostics."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("f6_diagnostics", ROOT / "scripts/ci/f6-provider-diagnostics.py")
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
PROJECT = "byq-ci-stack-123-1-integration"
CID = "a" * 64
SOURCE = ROOT / "services/runtime-adapter/tests/f6_synthetic_runtime.py"


def row(sequence=1):
    return {"schema_version":collector.SCHEMA, "record_type":"dispatch", "sequence":sequence,
            "stage":"fg1", "outcome":"response_written", "response_kind":"tool_call",
            "rejection_code":None, "tool_call_count":3, "tool_call_count_capped":False}


def encode(rows):
    return b"".join(json.dumps(value).encode()+b"\n" for value in rows)


class Collection(unittest.TestCase):
    def run_collector(self, payload=b"", read_code=0, labels=None):
        calls = []
        answers = [(0, CID.encode()+b"\n"),
                   (0, json.dumps(labels or {"com.docker.compose.project":PROJECT,"com.docker.compose.service":"runtime-adapter"}).encode()),
                   (read_code,payload)]
        def runner(args, **kwargs):
            calls.append(args)
            code, stdout = answers[len(calls)-1]
            return subprocess.CompletedProcess(args, code, stdout, b"PRIVATE-STDERR-CANARY")
        with patch.dict(os.environ,{"COMPOSE_PROJECT_NAME":PROJECT}):
            result = collector.collect(PROJECT,SOURCE,runner=runner)
        return result, calls

    def test_read_targets_exact_scoped_runtime_and_prints_only_closed_record(self):
        result, calls = self.run_collector(encode([row()]))
        self.assertEqual(result["status"],"validated")
        self.assertEqual(result["records"],[row()])
        self.assertEqual(calls[0],["docker","compose","-p",PROJECT,"ps","-q","runtime-adapter"])
        self.assertEqual(calls[2][:3],["docker","exec",CID])
        self.assertNotIn("PRIVATE-STDERR-CANARY",json.dumps(result))
        self.assertEqual(result["total_provider_calls"],"unknown")

    def test_mismatch_scope_stops_before_docker(self):
        with patch.dict(os.environ,{"COMPOSE_PROJECT_NAME":"beyondquant"}):
            result = collector.collect(PROJECT,SOURCE,runner=lambda *_a,**_k:self.fail("Docker called"))
        self.assertEqual(result["status"],"scope_rejected")

    def test_wrong_service_label_stops_before_file_read(self):
        result,calls = self.run_collector(labels={"com.docker.compose.project":PROJECT,"com.docker.compose.service":"backend"})
        self.assertEqual(result["status"],"scope_rejected")
        self.assertEqual(len(calls),2)

    def test_missing_and_empty_do_not_claim_no_calls_or_effects(self):
        for code,status in [(3,"missing"),(0,"empty")]:
            result,_ = self.run_collector(read_code=code)
            self.assertEqual(result["status"],status)
            self.assertEqual(result["total_provider_calls"],"unknown")
            self.assertEqual(result["business_outcomes"],"unknown")

    def test_unknown_text_category_or_field_cannot_cross_upload_boundary(self):
        bad = row();bad["rejection_code"]="PRIVATE-CATEGORY-CANARY"
        extra = row();extra["raw_message"]="PRIVATE-MESSAGE-CANARY"
        for payload in [encode([bad]),encode([extra]),b"PRIVATE-NONJSON-CANARY"]:
            result,_ = self.run_collector(payload)
            self.assertEqual(result["status"],"unqualified")
            self.assertEqual(result["records"],[])
            self.assertNotIn("PRIVATE-",json.dumps(result))

    def test_duplicate_fields_cannot_hide_an_unknown_value(self):
        payload=encode([row()]).replace(b'"stage": "fg1"', b'"stage": "PRIVATE-CANARY", "stage": "fg1"')
        result,_=self.run_collector(payload)
        self.assertEqual(result["status"],"unqualified")
        self.assertNotIn("PRIVATE-CANARY",json.dumps(result))

    def test_ordinal_boolean_and_unhashable_fields_are_rejected(self):
        codes=collector.fixture_codes(SOURCE)
        for key,value in [("sequence",True),("sequence",2),("tool_call_count",True),("stage",[]),("response_kind",{})]:
            bad=row();bad[key]=value
            with self.assertRaises((ValueError,TypeError)):
                collector.validate_records(encode([bad]),codes)

    def test_exact_closed_fixture_rejection_is_retained(self):
        value=row();value.update(outcome="fixture_rejected",response_kind="none",rejection_code="provider_current_user_instruction_missing")
        result,_ = self.run_collector(encode([value]))
        self.assertEqual(result["records"],[value])

    def test_overflow_requires_255_dispatches_and_preserves_unknown_total(self):
        values=[row(i) for i in range(1,256)]
        overflow={"schema_version":collector.SCHEMA,"record_type":"overflow","dispatches_at_least":256,"first_omitted_dispatch":256}
        result,_=self.run_collector(encode(values+[overflow]))
        self.assertEqual(result["status"],"validated")
        self.assertTrue(result["overflow"])
        self.assertEqual(result["total_provider_calls"],"unknown")
        for rows in [[overflow],values+[row(256)],values+[overflow,row(257)]]:
            result,_=self.run_collector(encode(rows))
            self.assertEqual(result["status"],"unqualified")

    def test_partial_or_oversized_file_is_not_a_complete_receipt(self):
        for payload in [encode([row()])[:-1],b"x"*(collector.MAX_BYTES+1)]:
            result,_=self.run_collector(payload)
            self.assertEqual(result["status"],"unqualified")

    def test_reader_rejects_symlink_wrong_mode_and_hardlink(self):
        with tempfile.TemporaryDirectory(prefix="byq-f6-reader-") as temporary:
            directory=Path(temporary);target=directory/"owned.jsonl";target.write_bytes(encode([row()]));target.chmod(0o600)
            def read(path):
                code=collector.READER.replace("/tmp/byq-f6-provider-diagnostics.jsonl",str(path))
                return subprocess.run(["python3","-B","-c",code],capture_output=True,timeout=3)
            self.assertEqual(read(target).returncode,0)
            link=directory/"link";link.symlink_to(target)
            self.assertNotEqual(read(link).returncode,0)
            target.chmod(0o644);self.assertEqual(read(target).returncode,4);target.chmod(0o600)
            os.link(target,directory/"hardlink");self.assertEqual(read(target).returncode,4)


if __name__ == "__main__":
    unittest.main()
