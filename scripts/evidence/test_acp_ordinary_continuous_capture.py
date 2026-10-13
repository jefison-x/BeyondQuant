"""Offline end-to-end contracts for ordinary two-turn ACP capture.

All effects stop at the HTTP opener and subprocess transport boundaries. The
real CLI, parsing, persistence, ACK matching, binding checks and observer run.
No credentials, containers, database, model, Job, or network are used.
"""
from __future__ import annotations

import hashlib
import ctypes
import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import shutil
from unittest.mock import patch
from datetime import datetime, timezone

SCRIPT = Path(__file__).with_name("acp-ordinary-continuous-capture.py")
SPEC = importlib.util.spec_from_file_location("ordinary_capture", SCRIPT)
capture = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(capture)

ROOTS = ("a" * 32, "b" * 32)
CONVERSATION = "conversation_123"
RUNTIME_SESSION = "runtime_session_123"
TRACE = "trace-123"
OWNER = "admin"
NATIVE = "86" * 16
IDS = {"gateway": "1" * 12, "adapter": "2" * 12,
       "runner": "3" * 64, "postgres": "4" * 12}
USER_TEXT = ("first user input", "second user input")
_REAL_RUN = subprocess.run
CONTAINER_INSPECT_FMT = ('{{.Id}}|{{.Image}}|{{.State.StartedAt}}|{{.State.Running}}|'
    '{{index .Config.Labels "com.docker.compose.project"}}|'
    '{{index .Config.Labels "com.docker.compose.service"}}')
PG_SHELL = 'exec psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"'


class _HTTPResponse:
    def __init__(self, body: bytes, status: int = 200, content_type: str = "application/json"):
        self.body, self.status = body, status
        self.headers = {"content-type": content_type}
        self.closed = False

    def read(self, size=-1):
        return self.body if size < 0 else self.body[:size]

    def readline(self):
        if not hasattr(self, "_lines"):
            self._lines = iter(self.body.splitlines(keepends=True))
        return next(self._lines, b"")

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _event(sequence: int, kind: str, root: str, **payload) -> dict:
    data = dict(payload)
    if kind in {"session.started", "session.result"}:
        data["run_id"] = root
    return {"sequence": sequence, "kind": kind, "session_id": CONVERSATION,
            "trace_id": TRACE, "timestamp": "2026-10-13T00:00:01Z",
            "source": "runtime-adapter", "payload": data}


def _sse(rows: list[dict]) -> bytes:
    return b"".join(("event: workflow-trace\ndata: " + json.dumps(row, separators=(",", ":")) + "\n\n").encode()
                   for row in rows)


def _official_project_key(cwd: str) -> str:
    """Independent fixture implementation of the pinned DSH v4 projectKey."""
    readable, separator = [], False
    for char in cwd:
        if char in "/\\:":
            if not separator:
                readable.append("-")
            separator = True
        elif char != "~" and char.isascii() and (char.isalnum() or char in "._-"):
            readable.append(char)
            separator = False
        else:
            code = ord(char)
            if code > 0xFFFF:
                raise AssertionError("test cwd must use BMP characters")
            readable.append(f"~{code:04X}")
            separator = False
    return "--" + ("".join(readable).lstrip("-") or "root")[:251] + "--"


class _Opener:
    """Fake auth and public Product endpoints; no network transport is used."""
    def __init__(self, fixture):
        self.fixture = fixture
        self.requests = []
        self.session_gets = 0

    def open(self, request, data=None, timeout=None, **kwargs):
        if kwargs:
            raise AssertionError(f"unsupported urllib opener arguments: {sorted(kwargs)}")
        if data is not None:
            raise AssertionError("request data must be carried by urllib Request, not opener.open")
        self.requests.append((request, timeout))
        path = request.full_url.removeprefix(capture.ORIGIN)
        method = request.get_method()
        self.fixture.assert_request(request, timeout)
        if path == "/api/auth/login" and method == "POST":
            if request.get_header("Content-type") != "application/json":
                raise AssertionError("login request did not use JSON")
            body = json.loads(request.data.decode())
            if body != {"username": "admin", "password": "synthetic-test-only-password"}:
                raise AssertionError("fake login did not receive the synthetic admin credentials")
            self.fixture.login_count += 1
            self.fixture.cookie_jar.cookies = [type("Cookie", (), {"name": "byq_session"})()]
            login_result = {
                "user": {"username": "admin", "display_name": "Synthetic Admin", "role": "admin"},
                "workspace": {"contract": "personal-workspace.v1",
                              "workspace_id": capture.WORKSPACE, "kind": "personal",
                              "display_name": "Synthetic Admin Workspace", "role": "owner"},
            }
            return _HTTPResponse(json.dumps(login_result).encode())
        if path == "/api/auth/me" and method == "GET":
            role = "user" if self.fixture.login_change and self.fixture.login_count >= 2 else "admin"
            body = {"subject": OWNER, "display_name": "Synthetic Admin", "role": role,
                    "workspace": {"contract": "personal-workspace.v1",
                                  "workspace_id": capture.WORKSPACE, "kind": "personal",
                                  "display_name": "Synthetic Admin Workspace", "role": "owner"}}
            return _HTTPResponse(json.dumps(body).encode())
        if path == f"/v1/agent/sessions/{CONVERSATION}":
            if method != "GET":
                raise AssertionError("public session was not read with GET")
            self.session_gets += 1
            body = self.fixture.conversation(1 if self.session_gets <= 2 else 2)
            return _HTTPResponse(json.dumps(body).encode())
        if path == f"/v1/agent/sessions/{CONVERSATION}/answer-delivery":
            if method != "GET":
                raise AssertionError("answer delivery was not read with GET")
            body = {"schema_version": "public-answer-delivery-status.v1", "state": "up_to_date",
                    "pending_events": 0, "exhausted_events": 0, "rejected_events": 0}
            return _HTTPResponse(json.dumps(body).encode())
        if path == f"/v1/workflows/{CONVERSATION}/events":
            if method != "GET" or request.get_header("Accept") != "text/event-stream":
                raise AssertionError("workflow events did not use the expected read-only SSE request")
            turn = 1 if request.get_header("Last-event-id") == "0" else 2
            return _HTTPResponse(_sse(self.fixture.events(turn)), content_type="text/event-stream")
        raise AssertionError(f"unexpected fake HTTP path: {path}")


class _FakeClock:
    def __init__(self, seconds=10):
        self.ns = seconds * 1_000_000_000

    def monotonic(self):
        return self.ns / 1_000_000_000

    def monotonic_ns(self):
        return self.ns


class _Fixture:
    def __init__(self, *, ack="ok", drift=False, login_change=False, command_failure=None,
                 third_terminal=False, third_sse_root=False):
        self.ack = ack
        self.drift = drift
        self.login_change = login_change
        self.command_failure = command_failure
        self.third_terminal = third_terminal
        self.third_sse_root = third_sse_root
        self.commands = []
        self.inspect_counts = {name: 0 for name in IDS}
        self.login_count = 0
        self.started_utc = None
        self.opener = _Opener(self)
        self.cookie_jar = None
        # The fake Docker runner's mounted session root intentionally aliases
        # this isolated temporary host directory. The producer receives the
        # exact DSH_HOME from each binding and reads this tree directly; there
        # is no path rewrite that could mask a wrong binding_cwd in its output.
        # These offline tests validate the requested Docker UID in argv, while
        # the local producer subprocess uses the test UID; they do not claim to
        # verify container DAC behavior.
        self.native_tmp = tempfile.TemporaryDirectory()
        try:
            temp_root = Path(self.native_tmp.name).resolve(strict=True)
            self.session_root = (temp_root / "session-store").resolve()
            self.native_cwd = (self.session_root / capture.WORKSPACE / "dsh-home").resolve()
            self.project_key = _official_project_key(str(self.native_cwd))
            self.native_dir = (self.native_cwd / "sessions" / self.project_key / NATIVE).resolve()
            # The synthetic mount must contain the complete official DSH_HOME
            # path before the producer opens its v4 session file.
            self.native_dir.mkdir(parents=True, mode=0o700)
            for directory in (temp_root, self.session_root,
                              self.session_root / capture.WORKSPACE, self.native_cwd,
                              self.native_cwd / "sessions",
                              self.native_cwd / "sessions" / self.project_key, self.native_dir):
                os.chmod(directory, 0o700)
            self.native_file = self.native_dir / "session.v4.jsonl.zstd"
            self.native_failure = None
            self.preflight_reader_uid = 10002
            self.foreign_binding_cwd = False
            self._write_native_fixture()
            os.chmod(self.native_file, 0o600)
        except BaseException:
            self.native_tmp.cleanup()
            raise
        try:
            self.identity = {"subject": OWNER, "role": "admin", "workspace_id": capture.WORKSPACE}
            self.started_at = "2026-10-13T00:00:00Z"
            self.facts = {
                "project": capture.PROJECT,
                "requested_ids": dict(IDS),
                "containers": {
                    name: {"id": cid, "image_id": "sha256:" + name * 64,
                           "started_at": self.started_at, "running": "true",
                           "project": capture.PROJECT,
                           "service": {"gateway": "gateway", "adapter": "runtime-adapter",
                                       "runner": "acp-product-runner", "postgres": "postgres"}[name]}
                    for name, cid in IDS.items()
                },
            }
        except BaseException:
            self.native_tmp.cleanup()
            raise

    def cookie_jar_factory(self):
        self.cookie_jar = type("FakeCookieJar", (), {"cookies": []})()
        self.cookie_jar.__class__.__iter__ = lambda jar: iter(jar.cookies)
        return self.cookie_jar

    def build_opener(self, processor):
        if processor is not self.cookie_jar:
            raise AssertionError("cookie processor did not receive the fresh fake jar")
        return self.opener

    def assert_request(self, request, timeout):
        if timeout <= 0:
            raise AssertionError("HTTP request had no positive timeout")
        path = request.full_url.removeprefix(capture.ORIGIN)
        if path != f"/v1/workflows/{CONVERSATION}/events":
            if request.get_header("Accept") != "application/json":
                raise AssertionError("JSON endpoint did not request application/json")

    def cleanup(self):
        self.native_tmp.cleanup()

    def _write_native_fixture(self):
        header = {"type": "session", "version": 4, "id": NATIVE, "createdAt": 1,
                  "isSeeded": False, "delegationDepth": 0}
        records = [header,
                   {"type": "user/message", "data": {"source": {"kind": "user"},
                    "content": [{"type": "text", "text": USER_TEXT[0]}]}},
                   {"type": "future/unknown-frame", "data": {"opaque": [1, 2, 3]}},
                   {"type": "assistant/message", "data": {"content": "not retained"}},
                   {"type": "user/message", "data": {"source": {"kind": "user"},
                    "content": [{"type": "text", "text": USER_TEXT[1]}]}}]
        raw = ("\n".join(json.dumps(row, separators=(",", ":")) for row in records) + "\n").encode()
        lib = ctypes.CDLL("libzstd.so.1")
        lib.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
        lib.ZSTD_compressBound.restype = ctypes.c_size_t
        lib.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.c_int]
        lib.ZSTD_compress.restype = ctypes.c_size_t
        lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
        lib.ZSTD_isError.restype = ctypes.c_uint
        capacity = lib.ZSTD_compressBound(len(raw))
        compressed = ctypes.create_string_buffer(capacity)
        source = ctypes.create_string_buffer(raw)
        size = lib.ZSTD_compress(compressed, capacity, source, len(raw), 1)
        if lib.ZSTD_isError(size):
            raise AssertionError("synthetic zstd fixture compression failed")
        self.native_file.write_bytes(compressed.raw[:size])
        os.chmod(self.native_file, 0o600)

    def conversation(self, user_count):
        # runtime_session_id is deliberately absent from the normal public API.
        messages = [
            {"message_id": "u1", "sequence": 1, "role": "user", "content": USER_TEXT[0]},
            {"message_id": "a1", "sequence": 2, "role": "assistant", "content": "answer one", "workflow_sequence": 2},
            {"message_id": "u2", "sequence": 3, "role": "user", "content": USER_TEXT[1]},
            {"message_id": "a2", "sequence": 4, "role": "assistant", "content": "answer two", "workflow_sequence": 5},
        ]
        return {"conversation": {"session_id": CONVERSATION, "trace_id": TRACE},
                "messages": messages[:2] if user_count == 1 else messages}

    def events(self, turn):
        root = ROOTS[turn - 1]
        base = (turn - 1) * 3 + 1
        answer = "answer one" if turn == 1 else "answer two"
        rows = [_event(base, "session.started", root),
                _event(base + 1, "agent.output.delta", root,
                       schema_version="workflow-answer.v1", channel="answer", delta=answer, truncated=False)]
        if turn == 2 and self.third_sse_root:
            rows.append(_event(base + 2, "session.started", "f" * 32))
            rows.append(_event(base + 3, "session.result", "f" * 32))
        else:
            rows.append(_event(base + 2, "session.result", root))
        return rows

    def binding(self, root):
        turn = ROOTS.index(root) + 1
        return {"schema_version": "byq-acp-root-binding.v1", "session_id": RUNTIME_SESSION,
                "trace_id": TRACE, "owner_principal": OWNER, "workspace_id": capture.WORKSPACE,
                "root_run_id": root, "native_session_id": NATIVE,
                "runtime_generation": f"generation-{turn}", "previous_boot_id": "boot-123",
                "cwd": str(self.native_tmp.name) if self.foreign_binding_cwd else str(self.native_cwd),
                "settlement_receipt": {"schema_version": "agent-run-lifecycle-receipt.v1",
                    "root_run_id": root, "sequence": turn * 3,
                    "event_sha256": ("c" if turn == 1 else "d") * 64}}

    def journal(self, root):
        turn = ROOTS.index(root) + 1
        generation = f"generation-{turn}"
        base = {"schema_version": "continuation-request-gate.v1",
                "request_id": "product-turn-" + generation, "role": "root", "call": 1,
                "attempt": 1, "input_bytes": 10, "declared_max_output_tokens": 128,
                "tool_payload_bytes": 0, "admitted": True,
                "reason": "within_request_budget", "at_ms": 1000}
        admitted = dict(base, phase="admitted")
        completed = dict(base, phase="completed", status=200, forwarded=True,
                         elapsed_ms=25, completed_at_ms=1025, actual_input_tokens=10,
                         actual_cache_read_tokens=0, actual_output_tokens=4,
                         usage_source="provider_response")
        return "\n".join(json.dumps(row) for row in (admitted, completed)) + "\n"

    def terminal(self):
        roots = [
            {"root_run_id": ROOTS[i], "status": "completed", "authority_status": "closed",
             "terminal_sequence": (i + 1) * 3,
             "terminal_event_sha256": ("c" if i == 0 else "d") * 64,
             "terminal_acp_ingress_sequence": None, "terminal_acp_ingress_sha256": None,
             "terminal_unknown_claim_count": 0, "terminal_unknown_claims_sha256": None}
            for i in range(2)]
        if self.third_terminal:
            roots.append({"root_run_id": "f" * 32, "status": "completed", "authority_status": "closed",
                          "terminal_sequence": 9, "terminal_event_sha256": "f" * 64,
                          "terminal_acp_ingress_sequence": None, "terminal_acp_ingress_sha256": None,
                          "terminal_unknown_claim_count": 0, "terminal_unknown_claims_sha256": None})
        return {"schema_version": "byq-business-root-status.v1", "roots": roots}

    def ack_rows(self):
        rows = []
        for i, root in enumerate(ROOTS):
            binding = self.binding(root)
            receipt = binding["settlement_receipt"]
            rows.append({"schema_version": "byq-gateway-terminal-ack-observed.v1",
                "event": "terminal_ack_observed", "root_run_id": root,
                "session_id": RUNTIME_SESSION, "boot_id": "boot-123", "trace_id": TRACE,
                "sequence": receipt["sequence"], "event_sha256": receipt["event_sha256"],
                "outcome": "completed"})
        if self.ack == "missing":
            rows.pop()
        elif self.ack == "conflict":
            rows.append(dict(rows[0], boot_id="foreign-boot"))
        return rows

    def run(self, argv, *, input=None, stdout=None, stderr=None, timeout=None, check=False, **kwargs):
        if kwargs:
            raise AssertionError(f"unsupported subprocess.run arguments: {sorted(kwargs)}")
        if (input is not None or stdout != subprocess.PIPE or stderr != subprocess.PIPE
                or check is not False or not isinstance(timeout, (int, float)) or timeout <= 0):
            raise AssertionError("subprocess must be captured, noninteractive, and bounded")
        self.commands.append(list(argv))
        command_text = " ".join(argv)
        if argv[:3] == ["docker", "inspect", "--format"]:
            fmt, cid = argv[3], argv[4]
            if fmt == "{{.HostConfig.LogConfig.Type}}":
                if argv != ["docker", "inspect", "--format", fmt, IDS["gateway"]]:
                    raise AssertionError("gateway log-driver inspect argv mismatch")
                return subprocess.CompletedProcess(argv, 0, b"json-file\n", b"")
            if fmt != CONTAINER_INSPECT_FMT or len(argv) != 5 or cid not in IDS.values():
                raise AssertionError("container inspect target/argv mismatch")
            name = next((key for key, value in IDS.items() if value == cid), None)
            if name is None:
                raise AssertionError("unexpected container inspect id")
            row = self.facts["containers"][name]
            self.inspect_counts[name] += 1
            if self.drift and name == "runner" and self.inspect_counts[name] > 1:
                row = dict(row, started_at="2026-10-13T00:00:09Z")
            value = "|".join(str(row[key]) for key in
                ("id", "image_id", "started_at", "running", "project", "service"))
            return subprocess.CompletedProcess(argv, 0, (value + "\n").encode(), b"")
        if argv[:2] == ["docker", "logs"]:
            if (self.started_utc is None
                    or argv != ["docker", "logs", "--since", self.started_utc, "--timestamps", IDS["gateway"]]):
                raise AssertionError("gateway logs argv mismatch")
            lines = b"2026-10-13T00:00:00Z INFO uvicorn started\n"
            ack_lines = b"".join((b"2026-10-13T00:00:01Z INFO terminal_ack_observed "
                + json.dumps(row, separators=(",", ":")).encode() + b"\n") for row in self.ack_rows())
            # Uvicorn logs on stderr are supported by the real collector.
            return subprocess.CompletedProcess(argv, 0, lines, ack_lines)
        if argv[:2] != ["docker", "exec"]:
            raise AssertionError(f"unexpected process: {argv[:4]}")
        if len(argv) == 9 and argv[:7] == ["docker", "exec", "-i", IDS["postgres"], "sh", "-c", PG_SHELL] and argv[7] == "capture":
            sql = argv[8]
            if self.command_failure == "jobs-before" and sql == capture._job_counts_sql():
                return subprocess.CompletedProcess(argv, 17, b"partial secret-free output", b"transport failed")
            if sql == capture._job_counts_sql():
                value = {name: 4 for name in self.expected_job_tables()}
                if set(value) != self.expected_job_tables() or any(type(v) is not int for v in value.values()):
                    raise AssertionError("job/artifact count result schema mismatch")
            elif "FROM product_conversations c" in sql:
                if ("c.owner_principal='admin'" not in sql
                        or f"c.workspace_id='{capture.WORKSPACE}'" not in sql
                        or "c.created_at >= '" not in sql or "c.status='active'" not in sql
                        or "u.status='active'" not in sql or "m.status='active'" not in sql):
                    raise AssertionError("runtime-scope SQL omitted required identity/time/status scope")
                expected_users = 2 if "role='user')=2;" in sql else 1
                match = re.search(r"c\.created_at >= '([^']+)'::timestamptz", sql)
                if not match:
                    raise AssertionError("runtime scope SQL did not bind the batch start time")
                self.started_utc = match.group(1)
                value = {"conversation_id": CONVERSATION, "runtime_session_id": RUNTIME_SESSION,
                         "trace_id": TRACE, "owner_principal": OWNER,
                         "workspace_id": capture.WORKSPACE, "status": "active",
                         "created_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                         "user_message_count": expected_users}
                if set(value) != {"conversation_id", "runtime_session_id", "trace_id", "owner_principal",
                                  "workspace_id", "status", "created_at", "user_message_count"}:
                    raise AssertionError("runtime scope result schema mismatch")
            elif "agent_runtime_turns" in sql:
                for required_scope in ("owner_principal='admin'", f"workspace_id='{capture.WORKSPACE}'",
                                       f"session_id='{RUNTIME_SESSION}'", f"trace_id='{TRACE}'",
                                       "created_at >= '"):
                    if required_scope not in sql:
                        raise AssertionError("backend roots SQL omitted exact scope/time restriction")
                value = self.terminal()
                match = re.search(r"created_at >= '([^']+)'::timestamptz", sql)
                if not match or match.group(1) != self.started_utc:
                    raise AssertionError("roots query batch time differs from runtime scope")
                if any(row.get("terminal_unknown_claim_count") != 0 for row in value["roots"]):
                    raise AssertionError("backend root reports unknown terminal claims")
                if any(set(row) != {"root_run_id", "status", "authority_status", "terminal_sequence",
                                    "terminal_event_sha256", "terminal_acp_ingress_sequence",
                                    "terminal_acp_ingress_sha256", "terminal_unknown_claim_count",
                                    "terminal_unknown_claims_sha256"} for row in value["roots"]):
                    raise AssertionError("backend roots response schema mismatch")
            else:
                raise AssertionError("unknown SQL query category")
            return subprocess.CompletedProcess(argv, 0, (json.dumps(value) + "\n").encode(), b"")
        if (len(argv) == 13 and argv[:5] == ["docker", "exec", "--workdir", "/app", "-i"]
                and argv[5] == IDS["adapter"] and argv[6:9] == ["python3", "-I", "-c"]
                and argv[9] == self.expected_binding_reader()
                and argv[10] == str(Path(capture.SESSION_ROOT) / capture.WORKSPACE / "byq-acp-bindings" / f"{RUNTIME_SESSION}.json")
                and argv[11] == str(Path(capture.SESSION_ROOT) / capture.WORKSPACE)):
            root = argv[12]
            if root not in ROOTS or not re.fullmatch(r"[0-9a-f]{32}", root):
                raise AssertionError("binding reader root scope mismatch")
            value = {"binding": self.binding(root), "journal": self.journal(root)}
            return subprocess.CompletedProcess(argv, 0, (json.dumps(value) + "\n").encode(), b"")
        if (len(argv) == 13 and argv[:6] == ["docker", "exec", "--user", "10002:10002", "--workdir", "/app"]
                and argv[6] == IDS["runner"] and argv[7:10] == ["python3", "-I", "-c"]
                and argv[10] == self.expected_runtime_preflight()
                and argv[11] == str(capture.SESSION_ROOT)
                and argv[12] == str(Path(capture.SESSION_ROOT) / capture.WORKSPACE)):
            value = self.native_preflight_value()
            value["reader_uid"] = self.preflight_reader_uid
            return subprocess.CompletedProcess(argv, 0, (json.dumps(value) + "\n").encode(), b"")
        if (len(argv) == 16 and argv[:7] == ["docker", "exec", "--user", "10002:10002", "--workdir", "/app", "-i"]
                and argv[7] == IDS["runner"] and argv[8:11] == ["python3", "-I", "-c"]
                and argv[11] == self.expected_projector_source()
                and argv[12] == str(self.native_cwd) and argv[13] == NATIVE
                and argv[14] == capture.WORKSPACE and argv[15] == capture.PROJECTOR_SHA256):
            if argv[12] != str(self.native_cwd):
                raise AssertionError("native projector did not use the binding DSH_HOME")
            if self.native_failure == "missing":
                self.native_file.unlink(missing_ok=True)
            elif self.native_failure == "permission":
                # Keep all parent directories traversable so the producer reaches
                # the actual session file and receives a real OS PermissionError.
                current = self.native_file.parent
                while current != Path(self.native_tmp.name).parent:
                    os.chmod(current, 0o755)
                    current = current.parent
                os.chmod(self.native_file, 0)
            elif self.native_failure == "invalid_schema":
                return subprocess.CompletedProcess(argv, 0, b"{}\n", b"")
            if argv[11] != self.expected_projector_source():
                raise AssertionError("native projector differs from frozen source")
            code = argv[11]
            if self.native_failure == "changed":
                needle = "  opened_after=os.fstat(fd)\n finally:"
                replacement = ("  opened_after=os.fstat(fd)\n"
                               "  os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns+5000000000))\n finally:")
                if needle not in code:
                    raise AssertionError("producer source lost deterministic file-change checkpoint")
                code = code.replace(needle, replacement, 1)
            run_argv = [sys.executable, "-I", "-c", code, str(self.native_cwd), NATIVE,
                        capture.WORKSPACE, capture.PROJECTOR_SHA256]
            run_options = {"stdout": stdout, "stderr": stderr, "timeout": timeout,
                           # Avoid passing the synthetic login credentials to
                           # the standalone native projector subprocess.
                           "check": check, "env": {"PATH": os.defpath}}
            if self.native_failure == "permission" and os.geteuid() == 0:
                def drop_to_reader():
                    os.setgroups([])
                    os.setgid(10002)
                    os.setuid(10002)
                run_options["preexec_fn"] = drop_to_reader
            completed = _REAL_RUN(run_argv, **run_options)
            if self.native_failure is None and completed.returncode == 0:
                # Check the real inline producer's output before the fake
                # transport returns it to capture._command. Do not rewrite
                # cwd/path fields to make the transport fixture appear valid.
                projected = json.loads(completed.stdout)
                expected_relative = (
                    f"sessions/{_official_project_key(str(self.native_cwd))}/"
                    f"{NATIVE}/session.v4.jsonl.zstd"
                )
                if (projected.get("binding_cwd") != argv[12]
                        or projected.get("binding_cwd") != str(self.native_cwd)
                        or projected.get("workspace_id") != argv[14]
                        or projected.get("relative_path") != expected_relative):
                    raise AssertionError("native producer output did not preserve the binding scope")
            return completed
        raise AssertionError(f"unrecognized docker exec command: {argv[4:7]}")

    @staticmethod
    def expected_job_tables():
        return {"backtest_jobs", "data_sync_jobs", "factor_jobs", "market_session_sync_jobs",
                "ml_prediction_runs", "ml_training_runs", "optimization_jobs",
                "security_master_sync_jobs", "signal_producer_jobs", "research_tasks", "artifacts"}

    @staticmethod
    def expected_projector_source():
        source = Path(capture.__file__).read_text(encoding="utf-8")
        module = ast.parse(source)
        return next(ast.literal_eval(node.value) for node in ast.walk(module)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "projector" for target in node.targets)
            and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))

    @staticmethod
    def expected_binding_reader():
        source = Path(capture.__file__).read_text(encoding="utf-8")
        module = ast.parse(source)
        return next(ast.literal_eval(node.value) for node in ast.walk(module)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "py" for target in node.targets)
            and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))

    @staticmethod
    def expected_runtime_preflight():
        source = Path(capture.__file__).read_text(encoding="utf-8")
        module = ast.parse(source)
        return next(ast.literal_eval(node.value) for node in ast.walk(module)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "code" for target in node.targets)
            and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))

    def native_preflight_value(self):
        return {"schema_version": "byq-native-projector-preflight.v1",
                "workspace_mount": str(self.session_root / capture.WORKSPACE),
                "zstd_stream_api": True, "reader_uid": 10002, "reader_gid": 10002,
                "dsh_source_commit": "639ed015397290b3745d163aafe02ffee4aa3f84",
                "store_package_version": "0.2.0-rc.2",
                "store_source_sha256": "0845707017acc2b4a8a75eab2244fa3fd88587b8094ab32014321dce7ca1e31b",
                "header_schema_source_sha256": "87ea85e2fb5318bf1f826db9a1c88c1b26d3ea328027a7f32b211880c4d62b9d",
                "base_profile_source_sha256": "9c2be64f46a193eff3cca190c26e697e8e8eee25c9b40149dfdb56f8142c252d",
                "product_profile_sha256": "10396c708651b24e3012df51e13cbb0e1eaf8178cda9547c91d682c189eacd45",
                "product_profile_identity_sha256": "0e1f5494f99b4fba433f5f86653b6848377372c7308561bceaaddc3ea3f2f69b",
                "product_profile": "byq-product-acp-0.2.0-rc.2",
                "product_composition_hash": "sha256:10396c708651b24e3012df51e13cbb0e1eaf8178cda9547c91d682c189eacd45",
                "dsh_home_contract": "binding.cwd", "store_root_contract": "dshHomePath(sessions)"}


class OrdinaryCaptureMainContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.out = Path(self.temp.name) / "capture"
        self.fixtures = []

    def tearDown(self):
        result = getattr(getattr(self, "_outcome", None), "result", None)
        failed = bool(result and any(getattr(test, "test_case", test) is self
                                     for test, _ in result.failures + result.errors))
        if failed:
            repo = Path(__file__).resolve().parents[2]
            evidence_root = repo / ".ci-artifacts/ordinary-continuous-offline-20261013/synthetic-failure-artifacts"
            evidence_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(evidence_root, 0o700)
            preserved = Path(tempfile.mkdtemp(prefix="capture-", dir=evidence_root))
            source = Path(self.temp.name)
            shutil.copytree(source, preserved / "workspace")
            native_inputs = preserved / "native-inputs"
            for index, fixture in enumerate(self.fixtures):
                native_inputs.mkdir(mode=0o700, exist_ok=True)
                if fixture.native_file.exists():
                    os.chmod(fixture.native_file, 0o600)
                shutil.copytree(fixture.native_tmp.name, native_inputs / f"fixture-{index}")
            (preserved / "test-id.txt").write_text(self.id() + "\n", encoding="utf-8")
            for path in sorted(preserved.rglob("*"), reverse=True):
                os.chmod(path, 0o700 if path.is_dir() else 0o600)
            print(f"PRESERVED_SYNTHETIC_CAPTURE:{preserved}", file=sys.stderr)
        self.temp.cleanup()

    def args(self, fixture, action, *extra):
        return ["capture", action, "--out-dir", str(self.out), "--gateway-id", IDS["gateway"],
                "--adapter-id", IDS["adapter"], "--runner-id", IDS["runner"],
                "--postgres-id", IDS["postgres"], "--session-root", str(fixture.session_root), *extra]

    def execute(self, fixture, actions):
        if fixture not in self.fixtures:
            self.fixtures.append(fixture)
        self.addCleanup(fixture.cleanup)
        def main_with(args):
            with patch.object(sys, "argv", args), \
                 patch.object(capture, "SESSION_ROOT", str(fixture.session_root)), \
                 patch.object(capture, "CookieJar", side_effect=fixture.cookie_jar_factory), \
                 patch.object(capture, "HTTPCookieProcessor", side_effect=lambda jar: jar), \
                 patch.object(capture, "build_opener", side_effect=fixture.build_opener), \
                 patch.dict(os.environ, {"BYQ_E2E_ADMIN_USERNAME": "admin",
                                         "BYQ_E2E_ADMIN_PASSWORD": "synthetic-test-only-password"}):
                return capture.main()

        with patch.object(capture.subprocess, "run", side_effect=fixture.run):
            results = [main_with(self.args(fixture, *action)) for action in actions]
        return results

    def execute_clocked(self, fixture, actions, clock, *, expire_before=None):
        if fixture not in self.fixtures:
            self.fixtures.append(fixture)
        self.addCleanup(fixture.cleanup)
        def main_with(args):
            with patch.object(sys, "argv", args), \
                 patch.object(capture, "SESSION_ROOT", str(fixture.session_root)), \
                 patch.object(capture, "CookieJar", side_effect=fixture.cookie_jar_factory), \
                 patch.object(capture, "HTTPCookieProcessor", side_effect=lambda jar: jar), \
                 patch.object(capture, "build_opener", side_effect=fixture.build_opener), \
                 patch.dict(os.environ, {"BYQ_E2E_ADMIN_USERNAME": "admin",
                                         "BYQ_E2E_ADMIN_PASSWORD": "synthetic-test-only-password"}):
                return capture.main()
        results = []
        with patch.object(capture.subprocess, "run", side_effect=fixture.run), \
             patch.object(capture.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(capture.time, "monotonic_ns", side_effect=clock.monotonic_ns):
            for index, action in enumerate(actions):
                if index == expire_before:
                    clock.ns += (capture.BATCH_SECONDS + 10) * 1_000_000_000
                results.append(main_with(self.args(fixture, *action)))
        return results

    def test_real_main_chain_preflight_two_turns_finish_passes_without_runtime_id_in_public(self):
        fixture = _Fixture()
        actions = [("preflight",),
                   ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "1"),
                   ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "2"),
                   ("finish",)]
        self.assertEqual([0, 0, 0, 0], self.execute(fixture, actions))
        self.assertEqual(4, fixture.login_count)
        requests = [(r.get_method(), r.full_url.removeprefix(capture.ORIGIN), r)
                    for r, _timeout in fixture.opener.requests]
        expected_requests = []
        for action in ("preflight", "turn-1", "turn-2", "finish"):
            expected_requests.extend([("POST", "/api/auth/login"), ("GET", "/api/auth/me")])
            if action.startswith("turn-"):
                expected_requests.extend([("GET", f"/v1/agent/sessions/{CONVERSATION}"),
                    ("GET", f"/v1/workflows/{CONVERSATION}/events"),
                    ("GET", f"/v1/agent/sessions/{CONVERSATION}/answer-delivery"),
                    ("GET", f"/v1/agent/sessions/{CONVERSATION}")])
        self.assertEqual(expected_requests, [(method, path) for method, path, _r in requests])
        event_requests = [r for _method, path, r in requests if path.endswith("/events")]
        self.assertEqual(["0", "3"], [r.get_header("Last-event-id") for r in event_requests])
        self.assertNotIn("runtime_session_id", json.loads((self.out / "conversation-turn-1.json").read_text())["conversation"])
        self.assertEqual(2, len(list((self.out / "binding-snapshots").glob("*.json"))))
        self.assertEqual({"a" * 32, "b" * 32}, {p.stem for p in (self.out / "binding-snapshots").glob("*.json")})
        self.assertEqual("PASS", json.loads((self.out / "observer-result.json").read_text())["status"])
        native = json.loads((self.out / "native-projection.json").read_text())
        self.assertEqual(hashlib.sha256((fixture.native_dir / "session.v4.jsonl.zstd").read_bytes()).hexdigest(),
                         native["compressed_sha256"])
        self.assertEqual(str(fixture.native_cwd), native["binding_cwd"])
        self.assertEqual(capture.WORKSPACE, native["workspace_id"])
        self.assertEqual(f"sessions/{_official_project_key(str(fixture.native_cwd))}/{NATIVE}/session.v4.jsonl.zstd",
                         native["relative_path"])
        self.assertEqual([hashlib.sha256(x.encode()).hexdigest() for x in USER_TEXT],
                         native["human_input_sha256_order"])
        self.assertEqual(4, native["header_version"])
        self.assertEqual(str(fixture.native_cwd), json.loads(
            (self.out / "turn-1/binding.json").read_text())["cwd"])
        self.assertEqual(str(fixture.native_cwd), json.loads(
            (self.out / "turn-2/binding.json").read_text())["cwd"])
        self.assertEqual(capture.WORKSPACE, json.loads(
            (self.out / "turn-1/binding.json").read_text())["workspace_id"])
        self.assertEqual(capture.WORKSPACE, json.loads(
            (self.out / "turn-2/binding.json").read_text())["workspace_id"])
        self.assert_native_preflight_receipt(fixture)
        self.assert_native_projection_receipt(fixture)
        self.assertTrue((self.out / "commands/jobs-before.stdout.raw").is_file())
        self.assertTrue((self.out / "commands/jobs-after.stdout.raw").is_file())
        self.assertFalse(any("BYQ_E2E_ADMIN_PASSWORD" in p.read_text(errors="ignore")
                             for p in self.out.rglob("*") if p.is_file()))
        self.assertFalse(any("synthetic-test-only-password" in p.read_text(errors="ignore")
                             for p in self.out.rglob("*") if p.is_file()))

    def assert_native_preflight_receipt(self, fixture):
        raw_path = self.out / "commands/native-runtime-preflight.stdout.raw"
        command_path = self.out / "commands/native-runtime-preflight.json"
        receipt_path = self.out / "native-runtime-preflight.json"
        raw = raw_path.read_bytes()
        command = json.loads(command_path.read_text())
        raw_value = json.loads(raw)
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(fixture.native_preflight_value(), raw_value)
        source_read = {key: value for key, value in receipt.items() if key.startswith("source_read_")}
        self.assertEqual({
            "source_read_command_sha256": hashlib.sha256(json.dumps(
                command["argv"], separators=(",", ":")).encode()).hexdigest(),
            "source_read_returncode": 0,
            "source_read_stdout_sha256": command["stdout_sha256"],
            "source_read_command_receipt_sha256": hashlib.sha256(json.dumps(
                command, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        }, source_read)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), command["stdout_sha256"])
        self.assertEqual(len(raw), command["stdout_bytes"])
        self.assertEqual(0, command["returncode"])
        self.assertEqual(0, command["stderr_bytes"])
        self.assertEqual(["docker", "exec", "--user", "10002:10002", "--workdir", "/app"],
                         command["argv"][:6])
        self.assertEqual(IDS["runner"], command["argv"][6])
        self.assertEqual(["python3", "-I", "-c"], command["argv"][7:10])
        self.assertEqual("9edc3029d7f4b897e44e8f753b687bd0751ec432ef12b4c96fcaeb940195073f",
                         hashlib.sha256(command["argv"][10].encode()).hexdigest())
        self.assertEqual(str(fixture.session_root), command["argv"][11])
        self.assertEqual(str(fixture.session_root / capture.WORKSPACE), command["argv"][12])
        self.assertEqual(fixture.native_preflight_value(),
                         {key: value for key, value in receipt.items() if not key.startswith("source_read_")})

    def assert_native_projection_receipt(self, fixture):
        raw_path = self.out / "commands/native-projection.stdout.raw"
        command_path = self.out / "commands/native-projection.json"
        projection_path = self.out / "native-projection.json"
        raw = raw_path.read_bytes()
        command = json.loads(command_path.read_text())
        projection = json.loads(projection_path.read_text())
        self.assertEqual(projection, json.loads(raw))
        self.assertEqual(0, command["returncode"])
        self.assertEqual(len(raw), command["stdout_bytes"])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), command["stdout_sha256"])
        self.assertEqual(0, command["stderr_bytes"])
        self.assertEqual(["docker", "exec", "--user", "10002:10002", "--workdir", "/app", "-i"],
                         command["argv"][:7])
        self.assertEqual(IDS["runner"], command["argv"][7])
        self.assertEqual(["python3", "-I", "-c"], command["argv"][8:11])
        self.assertEqual("88703ff77934153095606ce81d3be1befc3b8eb79528e18e9c20074e1418ae36",
                         hashlib.sha256(command["argv"][11].encode()).hexdigest())
        self.assertEqual([str(fixture.native_cwd), NATIVE, capture.WORKSPACE,
                          "88703ff77934153095606ce81d3be1befc3b8eb79528e18e9c20074e1418ae36"],
                         command["argv"][12:16])

    def test_native_projection_missing_permission_and_changed_files_fail_closed(self):
        expected_stderr = {"missing": None, "permission": None,
                           "changed": "native_file_changed"}
        for fault, marker in expected_stderr.items():
            with self.subTest(native_failure=fault):
                self.out = Path(self.temp.name) / f"capture-native-{fault}"
                fixture = _Fixture()
                fixture.native_failure = fault
                results = self.execute(fixture, [
                    ("preflight",),
                    ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "1"),
                    ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "2"),
                ])
                self.assertEqual([0, 0, 2], results)
                self.assertIn("native-projection_process_failed",
                              json.loads((self.out / "capture-stop.json").read_text())["reason"])
                meta = json.loads((self.out / "commands/native-projection.json").read_text())
                self.assertNotEqual(0, meta["returncode"])
                raw_stdout = (self.out / "commands/native-projection.stdout.raw").read_bytes()
                raw_stderr = (self.out / "commands/native-projection.stderr.raw").read_bytes()
                self.assertEqual(len(raw_stdout), meta["stdout_bytes"])
                self.assertEqual(len(raw_stderr), meta["stderr_bytes"])
                self.assertTrue(raw_stderr, "failed native read must preserve stderr")
                if marker is not None:
                    self.assertIn(marker.encode(), raw_stderr)
                self.assertFalse((self.out / "native-projection.json").exists())
                self.assertFalse((self.out / "observer-result.json").exists())

    def test_native_projection_zero_exit_invalid_schema_preserves_raw_without_publishing(self):
        fixture = _Fixture()
        fixture.native_failure = "invalid_schema"
        results = self.execute(fixture, [
            ("preflight",),
            ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "1"),
            ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "2"),
        ])
        self.assertEqual([0, 0, 2], results)
        stop = json.loads((self.out / "capture-stop.json").read_text())
        self.assertEqual("native_projection_schema_invalid", stop["reason"])
        command = json.loads((self.out / "commands/native-projection.json").read_text())
        raw_stdout = (self.out / "commands/native-projection.stdout.raw").read_bytes()
        raw_stderr = (self.out / "commands/native-projection.stderr.raw").read_bytes()
        self.assertEqual(0, command["returncode"])
        self.assertEqual(b"{}\n", raw_stdout)
        self.assertEqual(hashlib.sha256(raw_stdout).hexdigest(), command["stdout_sha256"])
        self.assertEqual(len(raw_stdout), command["stdout_bytes"])
        self.assertEqual(b"", raw_stderr)
        self.assertEqual(0, command["stderr_bytes"])
        self.assertFalse((self.out / "native-projection.json").exists())
        self.assertFalse((self.out / "observer-result.json").exists())

    def test_native_preflight_wrong_reader_identity_stops_before_business_inventory(self):
        fixture = _Fixture()
        fixture.preflight_reader_uid = 0
        results = self.execute(fixture, [("preflight",)])
        self.assertEqual([2], results)
        self.assertIn("native_runtime_preflight_invalid",
                      json.loads((self.out / "capture-stop.json").read_text())["reason"])
        self.assertEqual(0, json.loads(
            (self.out / "commands/native-runtime-preflight.json").read_text())["returncode"])
        self.assertTrue((self.out / "commands/native-runtime-preflight.stdout.raw").is_file())
        self.assertFalse((self.out / "native-runtime-preflight.json").exists())
        self.assertFalse((self.out / "jobs-before.json").exists())

    def test_foreign_dsh_home_binding_is_rejected_before_native_projection(self):
        fixture = _Fixture()
        fixture.foreign_binding_cwd = True
        results = self.execute(fixture, [
            ("preflight",),
            ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "1"),
            ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "2"),
        ])
        self.assertEqual([0, 0, 2], results)
        self.assertIn("native_cwd_outside_workspace_volume",
                      json.loads((self.out / "capture-stop.json").read_text())["reason"])
        self.assertFalse((self.out / "native-projection.json").exists())
        self.assertFalse(any("native-projection" in " ".join(command)
                             for command in fixture.commands))

    def test_missing_or_conflicting_ack_stops_without_overwriting_prior_snapshot(self):
        for ack in ("missing", "conflict"):
            with self.subTest(ack=ack):
                self.out = Path(self.temp.name) / ("capture-" + ack)
                fixture = _Fixture(ack=ack)
                actions = [("preflight",),
                           ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "1"),
                           ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "2")]
                results = self.execute(fixture, actions)
                self.assertEqual([0, 0, 2], results)
                self.assertTrue((self.out / "capture-stop.json").exists())
                self.assertFalse((self.out / "observer-result.json").exists())
                self.assertEqual(1, len(list((self.out / "binding-snapshots").glob("*.json"))))
                log_meta = json.loads((self.out / "commands/gateway-terminal-ack-log.json").read_text())
                self.assertEqual(0, log_meta["returncode"])
                self.assertGreater(log_meta["stderr_bytes"], 0)
                stop_before = (self.out / "capture-stop.json").read_bytes()
                snapshots_before = {p.name: p.read_bytes() for p in (self.out / "binding-snapshots").glob("*.json")}
                repeated = self.execute(fixture, [("capture-turn", "--conversation-id", CONVERSATION,
                                                   "--turn", "2")])
                self.assertEqual([2], repeated)
                self.assertEqual(stop_before, (self.out / "capture-stop.json").read_bytes())
                self.assertEqual(snapshots_before,
                    {p.name: p.read_bytes() for p in (self.out / "binding-snapshots").glob("*.json")})

    def test_container_drift_or_changed_login_identity_stops_before_turn_artifacts(self):
        for index, (kwargs, expected) in enumerate(((
                {"drift": True}, "container_identity_or_start_changed"),
                ({"login_change": True}, "durable_identity_changed")), 1):
            with self.subTest(kwargs=kwargs):
                self.out = Path(self.temp.name) / f"capture-isolation-{index}"
                fixture = _Fixture(**kwargs)
                actions = [("preflight",), ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "1")]
                results = self.execute(fixture, actions)
                self.assertEqual([0, 2], results)
                stop = json.loads((self.out / "capture-stop.json").read_text())["reason"]
                self.assertIn(expected, stop)
                self.assertFalse((self.out / "turn-1/binding.json").exists())

    def test_nonzero_subprocess_is_recorded_before_stop_without_parsing_partial_stdout(self):
        fixture = _Fixture(command_failure="jobs-before")
        result = self.execute(fixture, [("preflight",)])
        self.assertEqual([2], result)
        meta = json.loads((self.out / "commands/jobs-before.json").read_text())
        self.assertEqual(17, meta["returncode"])
        self.assertTrue((self.out / "commands/jobs-before.stdout.raw").exists())
        self.assertFalse((self.out / "jobs-before.json").exists())

    def test_sse_third_root_stops_before_it_can_be_counted_as_two_turn_success(self):
        fixture = _Fixture(third_sse_root=True)
        results = self.execute(fixture, [("preflight",),
            ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "1"),
            ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "2")])
        self.assertEqual([0, 0, 2], results)
        self.assertIn("workflow_root_count_mismatch",
                      json.loads((self.out / "capture-stop.json").read_text())["reason"])
        self.assertEqual(1, len(list((self.out / "binding-snapshots").glob("*.json"))))
        self.assertFalse((self.out / "observer-result.json").exists())

    def test_backend_third_root_cannot_be_silently_projected_away(self):
        fixture = _Fixture(third_terminal=True)
        results = self.execute(fixture, [("preflight",),
            ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "1"),
            ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "2")])
        self.assertEqual([0, 0, 2], results)
        stop = json.loads((self.out / "capture-stop.json").read_text())["reason"]
        self.assertIn("backend", stop)
        self.assertFalse((self.out / "observer-result.json").exists())

    def test_deadline_is_shared_across_cli_calls_and_late_stage_does_not_run(self):
        fixture, clock = _Fixture(), _FakeClock()
        actions = [("preflight",),
                   ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "1"),
                   ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "2")]
        results = self.execute_clocked(fixture, actions, clock, expire_before=2)
        self.assertEqual([0, 0, 2], results)
        stop = json.loads((self.out / "capture-stop.json").read_text())["reason"]
        self.assertIn("deadline", stop)
        self.assertEqual(1, len(list((self.out / "binding-snapshots").glob("*.json"))))
        self.assertFalse((self.out / "turn-2").exists())

    def test_completed_stage_reentry_cannot_overwrite_capture_or_clock(self):
        fixture = _Fixture()
        actions = [("preflight",),
                   ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "1"),
                   ("capture-turn", "--conversation-id", CONVERSATION, "--turn", "2"),
                   ("finish",)]
        self.assertEqual([0, 0, 0, 0], self.execute(fixture, actions))
        snapshot_before = {p.name: p.read_bytes() for p in (self.out / "binding-snapshots").glob("*.json")}
        clock_before = (self.out / "batch-clock.json").read_bytes()
        repeated = self.execute(fixture, [("capture-turn", "--conversation-id", CONVERSATION, "--turn", "2")])
        self.assertEqual([2], repeated)
        self.assertEqual(snapshot_before,
                         {p.name: p.read_bytes() for p in (self.out / "binding-snapshots").glob("*.json")})
        self.assertEqual(clock_before, (self.out / "batch-clock.json").read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
