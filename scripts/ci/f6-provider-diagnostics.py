"""Read bounded, closed F6 fixture diagnostics before the scoped runtime is replaced.

This Engineering-only collector never reads raw runtime logs or executes Product
requests. Its records do not establish business effects or total external calls.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

SCHEMA = "byq.f6.synthetic-provider-diagnostic.v1"
MAX_BYTES = 256 * 1024
MAX_ROWS = 256
READER = '''import os,stat,sys
p='/tmp/byq-f6-provider-diagnostics.jsonl'
try:
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
except FileNotFoundError:
 sys.exit(3)
try:
 s=os.fstat(fd)
 if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or stat.S_IMODE(s.st_mode)!=0o600 or s.st_size>262144:sys.exit(4)
 b=os.read(fd,262145)
 if len(b)>262144:sys.exit(4)
 sys.stdout.buffer.write(b)
finally:
 os.close(fd)
'''

class Unqualified(ValueError):
    pass


def fixture_codes(source: Path) -> set[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "FIXTURE_REJECTION_CODES" for t in node.targets)
                and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "frozenset" and len(node.value.args) == 1):
            values = ast.literal_eval(node.value.args[0])
            if not isinstance(values, set) or not values or any(type(v) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,79}", v) is None for v in values):
                raise Unqualified()
            return values | {"unclassified_fixture_rejection"}
    raise Unqualified()


def _unique_fields(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise Unqualified()
        value[key] = item
    return value


def validate_records(payload: bytes, codes: set[str]) -> list[dict]:
    if len(payload) > MAX_BYTES or (payload and not payload.endswith(b"\n")):
        raise Unqualified()
    lines = payload.splitlines()
    if len(lines) > MAX_ROWS:
        raise Unqualified()
    rows = []
    for index, line in enumerate(lines):
        value = json.loads(line, object_pairs_hook=_unique_fields)
        if not isinstance(value, dict) or value.get("schema_version") != SCHEMA:
            raise Unqualified()
        if value.get("record_type") == "overflow":
            if (set(value) != {"schema_version", "record_type", "dispatches_at_least", "first_omitted_dispatch"}
                    or index != 255 or len(lines) != 256
                    or type(value["dispatches_at_least"]) is not int or value["dispatches_at_least"] != 256
                    or type(value["first_omitted_dispatch"]) is not int or value["first_omitted_dispatch"] != 256):
                raise Unqualified()
        elif value.get("record_type") == "dispatch":
            if (set(value) != {"schema_version", "record_type", "sequence", "stage", "outcome", "response_kind", "rejection_code", "tool_call_count", "tool_call_count_capped"}
                    or index >= 255 or type(value["sequence"]) is not int or value["sequence"] != index + 1
                    or type(value["stage"]) is not str or value["stage"] not in {"fg1", "fg2", "background", "unknown"}
                    or type(value["outcome"]) is not str or value["outcome"] not in {"response_written", "fixture_rejected", "request_rejected", "handler_error"}
                    or type(value["response_kind"]) is not str or value["response_kind"] not in {"tool_call", "completion", "none"}
                    or value["rejection_code"] is not None and (type(value["rejection_code"]) is not str or value["rejection_code"] not in codes)
                    or type(value["tool_call_count"]) is not int or not 0 <= value["tool_call_count"] <= 256
                    or type(value["tool_call_count_capped"]) is not bool):
                raise Unqualified()
        else:
            raise Unqualified()
        rows.append(value)
    return rows


def collect(project: str, source: Path, runner=subprocess.run) -> dict:
    report = {"schema_version": "byq.f6.synthetic-provider-collection.v1", "status": "unqualified", "records": [],
              "total_provider_calls": "unknown", "business_outcomes": "unknown"}
    if (re.fullmatch(r"byq-ci-stack-[A-Za-z0-9][A-Za-z0-9_-]{0,80}", project) is None
            or os.environ.get("COMPOSE_PROJECT_NAME") != project):
        report["status"] = "scope_rejected"
        return report
    def run(args):
        return runner(args, capture_output=True, timeout=5, check=False)
    try:
        codes = fixture_codes(source)
        report["fixture_source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        response = run(["docker", "compose", "-p", project, "ps", "-q", "runtime-adapter"])
        cid = response.stdout.decode("ascii").strip()
        if response.returncode or re.fullmatch(r"[0-9a-f]{64}", cid) is None:
            return report
        response = run(["docker", "inspect", "--format", '{{json .Config.Labels}}', cid])
        labels = json.loads(response.stdout)
        if (response.returncode or not isinstance(labels, dict)
                or labels.get("com.docker.compose.project") != project
                or labels.get("com.docker.compose.service") != "runtime-adapter"):
            report["status"] = "scope_rejected"
            return report
        response = run(["docker", "exec", cid, "python3", "-B", "-c", READER])
        if response.returncode == 3:
            report["status"] = "missing"
            return report
        if response.returncode:
            return report
        records = validate_records(response.stdout, codes)
        report.update(status="validated" if records else "empty", records=records,
                      overflow=bool(records and records[-1]["record_type"] == "overflow"))
    except (ValueError, TypeError, KeyError, UnicodeError, OSError, SyntaxError, subprocess.SubprocessError):
        # No raw stdout/stderr, parser input, exception or unknown field escapes.
        report["status"] = "unqualified"
        report["records"] = []
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[2] / "services/runtime-adapter/tests/f6_synthetic_runtime.py"
    print("F6 provider diagnostics: " + json.dumps(collect(args.project, source), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
