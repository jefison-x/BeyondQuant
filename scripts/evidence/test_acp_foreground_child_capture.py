"""Offline contracts for the foreground-child capture's complete CLI path.

The whole-entry fixture runs the real preflight, capture-child, finish,
scope/native/provider validators, and zstd/JSON parser. Only HTTP, Docker/psql,
runner identity, and mounted-filesystem facts are synthetic transports. The
cleanup proof is a scoped synthetic response; this suite does not claim to
verify the production daemon MAC or actual container DAC identity.
"""

from __future__ import annotations

import hashlib
import importlib.util
import contextlib
from collections import Counter
import ctypes
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from datetime import datetime, timezone


CAPTURE_PATH = Path(__file__).with_name("acp-foreground-child-capture.py")
SPEC = importlib.util.spec_from_file_location("acp_foreground_child_capture", CAPTURE_PATH)
assert SPEC is not None and SPEC.loader is not None
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


ROOT_NATIVE = "11111111-1111-4111-8111-111111111111"
CHILD_NATIVE = "22222222-2222-4222-8222-222222222222"
MARKER = "synthetic-child-case-20261013"
ROOT_RUN = "a" * 32
CHILD_RUN = "b" * 32
WORKSPACE = "workspace-test-12345678"
CWD = "/var/lib/byq/dsh-sessions/dsh-v0.2.0-rc.2-acp/" + WORKSPACE + "/home"
PUBLIC_ID = "public-conversation-20261013"
RUNTIME_ID = "runtime-session-20261013"
TRACE_ID = "trace-foreground-child"
CONTAINER_IDS = {"gateway": "1" * 12, "adapter": "2" * 12,
                 "runner": "3" * 12, "postgres": "4" * 12}
PG_SHELL = ('exec psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" '
            '-d "$POSTGRES_DB" -c "$1"')
INSPECT_FORMAT = ('{{.Id}}|{{.Image}}|{{.State.StartedAt}}|{{.State.Running}}|'
                  '{{index .Config.Labels "com.docker.compose.project"}}|'
                  '{{index .Config.Labels "com.docker.compose.service"}}')
_REAL_SUBPROCESS_RUN = subprocess.run
EXPECTED_DELEGATE_PACKAGE_SHA = "6eef1eabfac0b93fc49b4f51df855cd45aa83ec29db9ea22905814b0c27ad018"
EXPECTED_DELEGATE_SOURCE_SHA = "26a1e804aab4c6f9cb53a670c63b817fc8d9409569e6d68eda6fda33b966a840"
EXPECTED_RUNNER_SOURCE_SHA = "abc8992083bca202d4e66354f254fb1ea095cd409b62fcbdc2d3b2e6b6912f31"
EXPECTED_NATIVE_READER_SHA = "bdbb671b8bbae65641ab04faa9094b5bec711264b48a80b4c961c7a0f938ac8e"
EXPECTED_SCOPE_SCHEMA = "byq-acp-child-scope-read.v1"
EXPECTED_CAPTURE_SOURCE_SHA = "d13a2f459ec5ec9ea38662bbe49fe154d99e8aabf8ccb64cec91c9f2bc7498d1"


class _Response:
    def __init__(self, body: bytes, *, status=200, content_type="application/json"):
        self.body, self.status = body, status
        self.headers = {"content-type": content_type}
        self._lines = iter(body.splitlines(keepends=True))

    def read(self, size=-1):
        return self.body if size < 0 else self.body[:size]

    def readline(self):
        return next(self._lines, b"")

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _canonical_sha(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def _session(native_id: str, depth: int, origin=None, parent=None, *, input_seq=2, calls=None):
    return {
        "header": {"id": native_id, "version": 4, "origin": origin,
                   "parentSession": parent, "delegationDepth": depth},
        "relative_path": (f"sessions/{capture.ordinary._session_project_key(CWD)}/"
                          f"{native_id}/session.v4.jsonl.zstd"),
        "compressed_sha256": "c" * 64,
        "compressed_bytes": 100,
        "user_inputs": [{"seq": input_seq, "sha256": "d" * 64, "marker_present": True}],
        "calls": [] if calls is None else calls,
    }


def _provider_rows(*, usage="unknown", usage_source="unknown", output=128,
                   admitted_ms=1_780_000_000_000, completed_ms=1_780_000_000_025):
    common = {
        "schema_version": "continuation-request-gate.v1",
        "request_id": "product-turn-generation-test",
        "role": "root", "call": 1, "attempt": 1,
        "input_bytes": 128, "declared_max_output_tokens": output,
        "tool_payload_bytes": 64, "reason": "within_request_budget",
    }
    admitted = {**common, "phase": "admitted", "admitted": True, "at_ms": admitted_ms}
    completed = {**common, "phase": "completed", "admitted": True,
                 "status": 200, "forwarded": True, "elapsed_ms": completed_ms-admitted_ms,
                 "completed_at_ms": completed_ms,
                 "actual_input_tokens": usage, "actual_cache_read_tokens": usage,
                 "actual_output_tokens": usage, "usage_source": usage_source,
                 "at_ms": admitted_ms}
    return (json.dumps(admitted, separators=(",", ":")) + "\n"
            + json.dumps(completed, separators=(",", ":")) + "\n").encode()


def _provider_call_pair(call, admitted_ms, *, elapsed_ms=25, input_bytes=128,
                        declared_output=128, tool_payload_bytes=64):
    common = {
        "schema_version": "continuation-request-gate.v1",
        "request_id": "product-turn-generation-test",
        "role": "root", "call": call, "attempt": call,
        "input_bytes": input_bytes, "declared_max_output_tokens": declared_output,
        "tool_payload_bytes": tool_payload_bytes, "reason": "within_request_budget",
    }
    admitted = {**common, "phase": "admitted", "admitted": True, "at_ms": admitted_ms}
    completed_ms = admitted_ms + elapsed_ms
    completed = {**common, "phase": "completed", "admitted": True,
        "status": 200, "forwarded": True, "elapsed_ms": elapsed_ms,
        "completed_at_ms": completed_ms, "actual_input_tokens": "unknown",
        "actual_cache_read_tokens": "unknown", "actual_output_tokens": "unknown",
        "usage_source": "unknown", "at_ms": admitted_ms}
    return admitted, completed


def _provider_journal(rows):
    return ("\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n").encode()


class _WholeEntryFixture:
    """Synthetic HTTP/process/filesystem transport for the real three-stage CLI."""

    def __init__(self, *, failure=None, completed_binding=True, sequence_start=1):
        self.failure = failure
        self.completed_binding = completed_binding
        self.sequence_start = sequence_start
        self.commands = []
        self.command_results = []
        self.receipt_result_matches = set()
        self.requests = []
        self.jars = []
        self.started_utc = None
        self.inspect_counts = {name: 0 for name in CONTAINER_IDS}
        self.job_queries = 0
        self.started_at = "2026-10-13T00:00:00Z"
        self.native_root = ROOT_NATIVE
        self.native_child = CHILD_NATIVE
        self.runtime_generation = "generation-" + "9" * 32
        self.boot_id = "f" * 32
        self.terminal_sequence = 8
        self.terminal_sha = "c" * 64
        self.audit_outcome = ("failed" if failure in {"audit_native_failed", "audit_backend_failed"} else
                              "unknown" if failure in {"audit_native_unknown", "audit_backend_unknown"} else "completed")
        self.session_tmp = tempfile.TemporaryDirectory()
        try:
            base = Path(self.session_tmp.name).resolve(strict=True)
            self.cwd = (base / "mounted-session-root" / WORKSPACE / ("session-" + "e" * 32)).resolve()
            self.native_files = {}
            for native_id, child in ((self.native_root, False), (self.native_child, True)):
                directory = self.cwd / "sessions" / capture.ordinary._session_project_key(str(self.cwd)) / native_id
                directory.mkdir(parents=True, mode=0o700)
                for part in (self.cwd, self.cwd / "sessions",
                             self.cwd / "sessions" / capture.ordinary._session_project_key(str(self.cwd)), directory):
                    os.chmod(part, 0o700)
                path = directory / "session.v4.jsonl.zstd"
                self._write_native(path, native_id, child)
                os.chmod(path, 0o600)
                self.native_files[native_id] = path
            os.chmod(base, 0o700)
        except BaseException:
            self.session_tmp.cleanup()
            raise
        self.baseline = self.container_snapshot()

    def container_snapshot(self):
        services = {"gateway": "gateway", "adapter": "runtime-adapter",
                    "runner": "acp-product-runner", "postgres": "postgres"}
        return {"project": capture.ordinary.PROJECT,
                "requested_ids": dict(CONTAINER_IDS),
                "containers": {name: {"id": cid, "image_id": "sha256:" + name * 64,
                    "started_at": self.started_at, "running": "true",
                    "project": capture.ordinary.PROJECT, "service": services[name]}
                    for name, cid in CONTAINER_IDS.items()}}

    def cleanup(self):
        self.session_tmp.cleanup()

    def _record_result(self, result):
        self.command_results.append({"argv": tuple(result.args), "returncode": result.returncode,
                                     "stdout": result.stdout, "stderr": result.stderr})
        return result

    def cookie_jar_factory(self):
        jar = type("SyntheticJar", (), {"cookies": []})()
        jar.__class__.__iter__ = lambda value: iter(value.cookies)
        self.jars.append(jar)
        return jar

    def build_opener(self, jar):
        if jar not in self.jars:
            raise AssertionError("HTTP opener did not use the fresh synthetic cookie jar")
        return self

    def open(self, request, data=None, timeout=None, **kwargs):
        if kwargs or data is not None or timeout is None or timeout <= 0:
            raise AssertionError("HTTP opener arguments were not bounded read-only requests")
        self.requests.append(request)
        path = request.full_url.removeprefix(capture.ordinary.ORIGIN)
        method = request.get_method()
        if path == "/api/auth/login" and method == "POST":
            body = json.loads(request.data.decode())
            if body != {"username": "admin", "password": "synthetic-only-password"}:
                raise AssertionError("login did not use the fixture-only durable identity")
            self.jars[-1].cookies.append(type("Cookie", (), {"name": "byq_session"})())
            return _Response(json.dumps({"user": {"username": "admin"},
                "workspace": {"contract": "personal-workspace.v1", "workspace_id": capture.ordinary.WORKSPACE,
                              "kind": "personal", "display_name": "Synthetic", "role": "owner"}}).encode())
        if path == "/api/auth/me" and method == "GET":
            body = {"subject": "admin", "display_name": "Synthetic", "role": "admin",
                    "workspace": {"contract": "personal-workspace.v1",
                        "workspace_id": capture.ordinary.WORKSPACE, "kind": "personal",
                        "display_name": "Synthetic", "role": "owner"}}
            return _Response(json.dumps(body).encode())
        if path == f"/v1/agent/sessions/{PUBLIC_ID}" and method == "GET":
            messages = [{"message_id": "u1", "sequence": 1, "role": "user", "content": MARKER},
                        {"message_id": "a1", "sequence": 2, "role": "assistant", "content": "synthetic answer"}]
            return _Response(json.dumps({"conversation": {"session_id": PUBLIC_ID, "trace_id": TRACE_ID},
                                         "messages": messages}).encode())
        if path == f"/v1/agent/sessions/{PUBLIC_ID}/answer-delivery" and method == "GET":
            if self.failure == "delivery_stale":
                state = "pending"
            else:
                state = "up_to_date"
            return _Response(json.dumps({"schema_version": "public-answer-delivery-status.v1",
                "state": state, "pending_events": 0 if state == "up_to_date" else 1,
                "exhausted_events": 0, "rejected_events": 0}).encode())
        if path == f"/v1/workflows/{PUBLIC_ID}/events" and method == "GET":
            if request.get_header("Accept") != "text/event-stream":
                raise AssertionError("workflow read did not request SSE")
            event_rows = [self.event(1, "session.started", ROOT_RUN),
                          self.event(2, "session.result", ROOT_RUN)]
            if self.failure == "foreign_root":
                event_rows[-1] = self.event(2, "session.result", "e" * 32)
            body = b"".join(("event: workflow-trace\ndata: " + json.dumps(row, separators=(",", ":")) + "\n\n").encode()
                            for row in event_rows)
            return _Response(body, content_type="text/event-stream")
        raise AssertionError(f"unexpected fake Gateway request: {method} {path}")

    @staticmethod
    def event(sequence, kind, root):
        return {"sequence": sequence, "kind": kind, "session_id": PUBLIC_ID,
                "trace_id": TRACE_ID, "timestamp": "2026-10-13T00:00:01Z",
                "source": "runtime-adapter", "payload": {"run_id": root}}

    def _write_native(self, path, native_id, child):
        if child:
            header = {"type": "session", "version": 4, "id": native_id,
                      "createdAt": 1781308800000, "isSeeded": False,
                      "delegationDepth": 1, "origin": "subagent", "parentSession": ROOT_NATIVE}
            if self.failure == "native_header_extra":
                header["unrecognized_optional_mix"] = True
            calls = [
                ("byq_agent_run_start", {"role_id": "market_researcher",
                    "parent_run_id": "e" * 32 if self.failure == "native_bad_call_parent" else ROOT_RUN}, "{}"),
                ("byq_agent_authorize", {"run_id": CHILD_RUN, "action": "byq_market_session_context"}, "{}"),
                ("byq_market_session_context", {}, "{}"),
                ("byq_agent_audit", {"run_id": CHILD_RUN, "action": "byq_market_session_context",
                                     "outcome": self.audit_outcome}, "{}"),
            ]
        else:
            header = {"type": "session", "version": 4, "id": native_id,
                      "createdAt": 1781308800000, "isSeeded": False, "delegationDepth": 0}
            calls = [
                ("byq_agent_run_start", {"role_id": "quant_orchestrator", "parent_run_id": None}, "{}"),
                ("byq_delegate_market_research", {"description": MARKER, "prompt": MARKER},
                 json.dumps({"kind": "foreground", "runId": "dsh-child-session",
                             "output": {"summary": "synthetic"}}, separators=(",", ":"))),
            ]
        rows = [header, {"type": "user/message", "seq": self.sequence_start,
                "data": {"source": {"kind": "user"}, "content": [{"type": "text", "text": MARKER}]}}]
        sequence = self.sequence_start + 1
        for index, (name, arguments, result_text) in enumerate(calls, 1):
            call_id = f"call-{native_id[:4]}-{index}"
            # The delegate is a local DSH tool exposed under its actual short
            # name; only BYQ MCP tools carry the mcp__byq__ namespace.
            tool_name = (name if name == "byq_delegate_market_research"
                         else "mcp__byq__" + name)
            rows.append({"type": "assistant/message", "seq": sequence,
                "data": {"message": {"content": [{"type": "tool-call", "id": call_id,
                    "name": tool_name, "arguments": arguments}]}}})
            sequence += 1
            rows.append({"type": "tool/call", "seq": sequence,
                "data": {"callId": call_id, "name": tool_name, "arguments": arguments}})
            sequence += 1
            rows.append({"type": "tool/result", "seq": sequence,
                "data": {"message": {"source": {"callId": call_id}, "content": [
                    {"type": "tool-result", "toolCallId": call_id, "isError": False,
                     "content": [{"type": "text", "text": result_text}]}]}}})
            sequence += 1
        if self.failure in {"native_event_seq_negative", "native_event_seq_bool",
                            "native_event_seq_oversafe"} and native_id == self.native_root:
            rows[1]["seq"] = {"native_event_seq_negative": -1,
                              "native_event_seq_bool": True,
                              "native_event_seq_oversafe": (1 << 53)}[self.failure]
        elif self.failure == "native_call_sequence_not_after_assistant" and native_id == self.native_root:
            rows[3]["seq"] = rows[2]["seq"]
        elif self.failure == "native_result_sequence_not_after_call" and native_id == self.native_root:
            rows[4]["seq"] = rows[3]["seq"]
        raw = ("\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n").encode()
        lib = ctypes.CDLL("libzstd.so.1")
        lib.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
        lib.ZSTD_compressBound.restype = ctypes.c_size_t
        lib.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.c_int]
        lib.ZSTD_compress.restype = ctypes.c_size_t
        lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
        lib.ZSTD_isError.restype = ctypes.c_uint
        capacity = lib.ZSTD_compressBound(len(raw))
        output = ctypes.create_string_buffer(capacity)
        source = ctypes.create_string_buffer(raw)
        size = lib.ZSTD_compress(output, capacity, source, len(raw), 1)
        if lib.ZSTD_isError(size):
            raise AssertionError("synthetic native frame compression failed")
        path.write_bytes(output.raw[:size])

    def scope(self):
        return {"workspace_id": capture.ordinary.WORKSPACE, "owner_principal": "admin",
            "session_id": RUNTIME_ID, "trace_id": TRACE_ID, "root_run_id": ROOT_RUN,
            "runtime_boot_id": self.boot_id, "generation_id": self.runtime_generation,
            "cwd_leaf": Path(self.cwd).name, "actor_principal": "byq-product-agent-" + RUNTIME_ID}

    def _registration(self, *, child):
        scope = self.scope()
        native = self.native_child if child else self.native_root
        run = CHILD_RUN if child else ROOT_RUN
        parent = ROOT_RUN if child else None
        native_root = self.native_root
        return {"root_run_id": ROOT_RUN, "native_agent_session_id": native,
            "native_root_session_id": native_root, "native_parent_session_id": native_root if child else None,
            "owner_principal": scope["owner_principal"], "workspace_id": scope["workspace_id"],
            "actor_principal": scope["actor_principal"], "session_id": scope["session_id"],
            "trace_id": scope["trace_id"], "dsh_run_id": scope["generation_id"],
            "runtime_boot_id": scope["runtime_boot_id"], "origin": "subagent" if child else "root",
            "depth": 1 if child else 0, "agent_run_id": run, "parent_run_id": parent,
            "registration_status": "bound", "joined_run_id": run,
            "run_owner": scope["owner_principal"], "run_actor": scope["actor_principal"],
            "run_trace": scope["trace_id"], "run_session": scope["session_id"],
            "run_generation": scope["generation_id"], "run_root": ROOT_RUN,
            "run_parent": parent, "run_boot": scope["runtime_boot_id"],
            "run_role_id": "market_researcher" if child else "quant_orchestrator",
            "run_role_version": "1.4.0" if child else "2.5.0",
            "run_status": "completed", "run_authority_status": "closed"}

    def backend_projection(self):
        scope = self.scope()
        args = [
            {"run_id": CHILD_RUN, "action": "byq_market_session_context"},
            {},
            {"run_id": CHILD_RUN, "action": "byq_market_session_context", "outcome": self.audit_outcome},
        ]
        tools = ["byq_agent_authorize", "byq_market_session_context", "byq_agent_audit"]
        ingress = []
        for index, (tool, arguments) in enumerate(zip(tools, args), 1):
            ingress.append({"mcp_request_id": f"{index:032x}", "root_run_id": ROOT_RUN,
                "owner_principal": scope["owner_principal"], "workspace_id": scope["workspace_id"],
                "actor_principal": scope["actor_principal"], "session_id": scope["session_id"],
                "trace_id": scope["trace_id"], "dsh_run_id": scope["generation_id"],
                "runtime_boot_id": scope["runtime_boot_id"],
                "native_root_session_id": self.native_root, "native_agent_session_id": self.native_child,
                "native_parent_session_id": self.native_root, "origin": "subagent", "depth": 1,
                "agent_run_id": CHILD_RUN, "tool_name": tool,
                "arguments_sha256": _canonical_sha(arguments), "sequence": index,
                "event_sha256": hashlib.sha256(f"event-{index}".encode()).hexdigest(),
                "status": "settled", "settlement_outcome": "settled",
                "settlement_sha256": hashlib.sha256(f"settlement-{index}".encode()).hexdigest()})
        terminal_sha = self.terminal_sha
        root = {"root_run_id": ROOT_RUN, "owner_principal": scope["owner_principal"],
            "workspace_id": scope["workspace_id"], "session_id": scope["session_id"],
            "trace_id": scope["trace_id"], "status": "completed", "authority_status": "closed",
            "authority_boot_id": scope["runtime_boot_id"], "terminal_sequence": self.terminal_sequence,
            "terminal_event_sha256": terminal_sha, "terminal_acp_ingress_sequence": 0,
            "terminal_acp_ingress_sha256": "d" * 64, "terminal_unknown_claim_count": 0,
            "terminal_unknown_claims_sha256": "e" * 64}
        audits = []
        for run_id, native_id in ((ROOT_RUN, self.native_root), (CHILD_RUN, self.native_child)):
            audits.append({"root_run_id": ROOT_RUN, "native_agent_session_id": native_id,
                "audit_id": f"audit-binding-active-{run_id[:4]}", "run_id": run_id,
                "owner_principal": scope["owner_principal"], "actor_principal": scope["actor_principal"],
                "action": "runtime_turn_binding", "outcome": "active",
                "created_at": "2026-10-13T00:00:00+00:00"})
            if self.completed_binding:
                if self.failure != "audit_terminal_completed_missing" or run_id != CHILD_RUN:
                    audits.append({"root_run_id": ROOT_RUN, "native_agent_session_id": native_id,
                        "audit_id": f"audit-binding-completed-{run_id[:4]}", "run_id": run_id,
                        "owner_principal": scope["owner_principal"], "actor_principal": scope["actor_principal"],
                        "action": "runtime_turn_binding", "outcome": "completed",
                        "created_at": "2026-10-13T00:00:01+00:00"})
        if self.failure != "audit_authorized_missing":
            authorized_row = {"root_run_id": ROOT_RUN, "native_agent_session_id": self.native_child,
                "audit_id": "audit-context-authorized", "run_id": CHILD_RUN,
                "owner_principal": scope["owner_principal"], "actor_principal": scope["actor_principal"],
                "action": "byq_market_session_context",
                "outcome": "wrong" if self.failure == "audit_authorized_wrong" else "authorized",
                "created_at": "2026-10-13T00:00:02+00:00"}
            audits.append(authorized_row)
            if self.failure == "audit_authorized_duplicate":
                audits.append({**authorized_row, "audit_id": "audit-context-authorized-duplicate"})
        explicit_row = {"root_run_id": ROOT_RUN, "native_agent_session_id": self.native_child,
            "audit_id": "audit-context-explicit", "run_id": CHILD_RUN,
            "owner_principal": scope["owner_principal"], "actor_principal": scope["actor_principal"],
            "action": "byq_market_session_context", "outcome": self.audit_outcome,
            "created_at": "2026-10-13T00:00:03+00:00"}
        if self.failure != "audit_explicit_missing":
            audits.append(explicit_row)
        if self.failure == "audit_explicit_duplicate":
            audits.append({**explicit_row, "audit_id": "audit-context-explicit-duplicate"})
        if self.failure == "audit_terminal_completed_duplicate":
            audits.append(dict(audits[1], audit_id="audit-binding-completed-duplicate"))
        elif self.failure == "audit_unknown_action":
            audits.append({**audits[-1], "audit_id": "audit-unknown", "action": "unknown_action"})
        elif self.failure == "audit_cross_run_native":
            audits[-1] = dict(audits[-1], native_agent_session_id=self.native_root)
        return {"schema_version": EXPECTED_SCOPE_SCHEMA, "mode": "root_child",
            "foreign_mismatch_count": 0, "root_count": 1, "roots": [root],
            "registration_count": 2,
            "registrations": [self._registration(child=False), self._registration(child=True)],
            "ingress_count": 3, "ingress": ingress, "audit_count": len(audits), "audits": audits}

    def provider_journal(self):
        common = {"schema_version": "continuation-request-gate.v1",
            "request_id": "product-turn-" + self.runtime_generation,
            "role": "root", "call": 1, "attempt": 1,
            "input_bytes": 128, "declared_max_output_tokens": 128,
            "tool_payload_bytes": 64, "reason": "within_request_budget"}
        admitted = {**common, "phase": "admitted", "admitted": True,
                    "at_ms": 1_780_000_000_000}
        completed = {**common, "phase": "completed", "admitted": True,
            "status": 200, "forwarded": True, "elapsed_ms": 25,
            "completed_at_ms": 1_780_000_000_025, "actual_input_tokens": "unknown",
            "actual_cache_read_tokens": "unknown", "actual_output_tokens": "unknown",
            "usage_source": "unknown", "at_ms": 1_780_000_000_000}
        return "\n".join(json.dumps(row, separators=(",", ":"))
                          for row in (admitted, completed)) + "\n"

    def binding(self):
        return {"schema_version": "byq-acp-root-binding.v1", "session_id": RUNTIME_ID,
            "trace_id": TRACE_ID, "owner_principal": "admin",
            "workspace_id": capture.ordinary.WORKSPACE, "root_run_id": ROOT_RUN,
            "native_session_id": self.native_root, "runtime_generation": self.runtime_generation,
            "previous_boot_id": self.boot_id, "cwd": str(self.cwd),
            "process_exit_confirmed": True, "cleanup_unconfirmed": False,
            "settlement_receipt": {"schema_version": "agent-run-lifecycle-receipt.v1",
                "root_run_id": ROOT_RUN, "sequence": self.terminal_sequence,
                "event_sha256": self.terminal_sha}}

    def cleanup_proof(self, scope):
        exact_scope = {key: scope[key] for key in (
            "workspace_id", "owner_principal", "session_id", "trace_id", "root_run_id",
            "runtime_boot_id", "generation_id", "cwd_leaf")}
        verifiers = {name: True for name in (
            "file_bounded", "strict_json", "key_set_valid", "mac_valid", "types_valid",
            "schema_valid", "scope_valid", "cleanup_proven", "runner_identity_valid",
            "exit_fields_valid")}
        return {"schema": "byq-cleanup-receipt-proof.v1", "status": "pass",
            "digest": "a" * 64, "receipt_sha256": "b" * 64,
            "exact_scope": exact_scope, "cleanup": "proven", "runner_instance_id": "c" * 64,
            "exit_fields": {"code": 0, "signal": None, "reason": "process_exit"},
            "verifiers": verifiers}

    def _native_exec(self, argv, *, stdout, stderr, timeout, check):
        source = argv[argv.index("-c") + 1]
        args = argv[argv.index("-c") + 2:]
        if source != capture._native_reader_source():
            raise AssertionError("native reader source changed before the fake transport")
        if args[0] != str(self.cwd) or args[1] != capture.ordinary.WORKSPACE:
            raise AssertionError("native reader cwd/workspace scope mismatch")
        if args[2:6] != [self.native_root, self.native_child, MARKER, ROOT_RUN]:
            raise AssertionError("native reader root/child/marker/run argv mismatch")
        if args[6:] != [CHILD_RUN, EXPECTED_NATIVE_READER_SHA]:
            raise AssertionError("native reader child AgentRun/source pin argv mismatch")
        wrapper = r'''import os,sys,pathlib
real=pathlib.Path.is_relative_to
root=pathlib.Path(sys.argv[1]); workspace=sys.argv[2]
uid=1000 if os.environ.get("BYQ_FAKE_READER_UID") == "1000" else 10002
gid=9999 if os.environ.get("BYQ_FAKE_READER_GID") == "9999" else 10002
os.geteuid=lambda:uid
os.getegid=lambda:gid
pathlib.Path.is_relative_to=lambda self,other: (self==root and str(other).endswith("/"+workspace)) or real(self,other)
source=sys.argv[3]
sys.argv=["-c",*sys.argv[4:]]
exec(compile(source,"<frozen-native-reader>","exec"))'''
        local = [sys.executable, "-I", "-c", wrapper,
                 str(self.cwd), capture.ordinary.WORKSPACE, source, *args]
        env = {"PATH": os.defpath}
        if self.failure == "reader_uid_wrong":
            env["BYQ_FAKE_READER_UID"] = "1000"
        elif self.failure == "reader_gid_wrong":
            env["BYQ_FAKE_READER_GID"] = "9999"
        return _REAL_SUBPROCESS_RUN(local, stdout=stdout, stderr=stderr,
                                    timeout=timeout, check=check,
                                    env=env)

    def run(self, argv, *, input=None, stdout=None, stderr=None, timeout=None, check=False, **kwargs):
        if kwargs or stdout != subprocess.PIPE or stderr != subprocess.PIPE or check is not False:
            raise AssertionError(f"unexpected process options: {kwargs}")
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise AssertionError("all fake transport subprocess calls must be bounded")
        self.commands.append(list(argv))
        if argv[:3] == ["docker", "inspect", "--format"]:
            fmt, cid = argv[3], argv[4]
            if fmt == "{{.HostConfig.LogConfig.Type}}":
                if cid != CONTAINER_IDS["gateway"]:
                    raise AssertionError("log driver inspect escaped gateway scope")
                return self._record_result(subprocess.CompletedProcess(argv, 0, b"json-file\n", b""))
            if fmt != INSPECT_FORMAT:
                raise AssertionError("container inspect format mismatch")
            name = next((key for key, value in CONTAINER_IDS.items() if value == cid), None)
            if name is None:
                raise AssertionError("container inspect escaped four pinned ids")
            row = self.baseline["containers"][name]
            self.inspect_counts[name] += 1
            if self.failure == "container_drift" and name == "runner" and self.inspect_counts[name] > 1:
                row = dict(row, started_at="2026-10-13T00:00:09Z")
            value = "|".join(row[key] for key in (
                "id", "image_id", "started_at", "running", "project", "service"))
            return self._record_result(subprocess.CompletedProcess(argv, 0, (value + "\n").encode(), b""))
        if argv[:2] == ["docker", "logs"]:
            if argv != ["docker", "logs", "--since", self.started_utc,
                        "--timestamps", CONTAINER_IDS["gateway"]]:
                raise AssertionError("Gateway ACK log query escaped exact scope")
            ack = {"schema_version": "byq-gateway-terminal-ack-observed.v1",
                "event": "terminal_ack_observed", "root_run_id": ROOT_RUN,
                "session_id": RUNTIME_ID, "boot_id": self.boot_id, "trace_id": TRACE_ID,
                "sequence": self.terminal_sequence, "event_sha256": self.terminal_sha,
                "outcome": "completed"}
            if self.failure == "ack_missing":
                lines = b""
            elif self.failure == "ack_conflict":
                conflict = dict(ack, boot_id="e" * 32)
                lines = (b"2026-10-13T00:00:01Z INFO terminal_ack_observed "
                         + json.dumps(conflict, separators=(",", ":")).encode() + b"\n")
            else:
                lines = (b"2026-10-13T00:00:01Z INFO terminal_ack_observed "
                         + json.dumps(ack, separators=(",", ":")).encode() + b"\n")
            return self._record_result(subprocess.CompletedProcess(argv, 0, b"", lines))
        if argv[:3] != ["docker", "exec", "-i"] and argv[:2] != ["docker", "exec"]:
            raise AssertionError(f"unexpected process command: {argv[:5]!r}")
        if len(argv) == 9 and argv[:7] == ["docker", "exec", "-i", CONTAINER_IDS["postgres"],
                "sh", "-c", PG_SHELL] and argv[7] == "capture":
            sql = argv[8]
            if sql == capture.ordinary._job_counts_sql():
                self.job_queries += 1
                delta = 1 if self.failure == "job_delta" and self.job_queries > 1 else 0
                value = {name: 3 + delta for name in (
                    "backtest_jobs", "data_sync_jobs", "factor_jobs", "market_session_sync_jobs",
                    "ml_prediction_runs", "ml_training_runs", "optimization_jobs",
                    "security_master_sync_jobs", "signal_producer_jobs", "research_tasks", "artifacts")}
            elif "FROM product_conversations c" in sql:
                match = re.search(r"c\.created_at >= '([^']+)'::timestamptz", sql)
                if not match or "role='user')=1;" not in sql:
                    raise AssertionError("conversation SQL did not bind batch start/one user")
                self.started_utc = match.group(1)
                value = {"conversation_id": PUBLIC_ID, "runtime_session_id": RUNTIME_ID,
                    "trace_id": TRACE_ID, "owner_principal": "admin",
                    "workspace_id": capture.ordinary.WORKSPACE, "status": "active",
                    "created_at": "2026-10-13T00:00:00+00:00", "user_message_count": 1}
            elif "WITH root_candidates" in sql:
                if self.failure == "foreign_sql":
                    projection = self.backend_projection(); projection["foreign_mismatch_count"] = 1
                else:
                    projection = self.backend_projection()
                value = projection
            elif "FROM agent_runtime_turns WHERE owner_principal=" in sql:
                value = {"schema_version": "byq-business-root-status.v1", "roots": [{
                    "root_run_id": ROOT_RUN, "status": "completed", "authority_status": "closed",
                    "terminal_sequence": self.terminal_sequence,
                    "terminal_event_sha256": self.terminal_sha,
                    "terminal_acp_ingress_sequence": 0, "terminal_acp_ingress_sha256": "d" * 64,
                    "terminal_unknown_claim_count": 0, "terminal_unknown_claims_sha256": "e" * 64}]}
            else:
                raise AssertionError("unrecognized SQL category")
            return self._record_result(subprocess.CompletedProcess(
                argv, 0, (json.dumps(value) + "\n").encode(), b""))
        if len(argv) == 13 and argv[:5] == ["docker", "exec", "--workdir", "/app", "-i"] \
                and argv[5] == CONTAINER_IDS["adapter"] and argv[6:9] == ["python3", "-I", "-c"]:
            binding = self.binding()
            return self._record_result(subprocess.CompletedProcess(argv, 0, json.dumps({"binding": binding,
                "journal": self.provider_journal()}, separators=(",", ":")).encode(), b""))
        if len(argv) == 12 and argv[:7] == ["docker", "exec", "--user", "10002:10002",
                "--workdir", "/app", "-i"] and argv[7] == CONTAINER_IDS["runner"] \
                and argv[8:11] == ["python3", "-I", "-c"]:
            code = argv[11]
            if ("/opt/dsh-runtime/packages/subagent/tool-subagent" not in code
                    or "/opt/byq/acp_product_runner/server.py" not in code):
                raise AssertionError("delegate preflight did not use the pinned runner paths")
            runner_source_sha = ("0" * 64 if self.failure == "runner_source_drift"
                                 else EXPECTED_RUNNER_SOURCE_SHA)
            value = {"schema_version": "byq-dsh-delegate-source-preflight.v1",
                "package_name": "@deepseek-ai/dsh-tool-subagent", "package_version": "0.2.0-rc.2",
                "package_sha256": EXPECTED_DELEGATE_PACKAGE_SHA,
                "source_sha256": EXPECTED_DELEGATE_SOURCE_SHA,
                "product_runner_source_path": "/opt/byq/acp_product_runner/server.py",
                "product_runner_source_sha256": runner_source_sha,
                "reader_uid": 10002, "reader_gid": 10002}
            return self._record_result(subprocess.CompletedProcess(argv, 0, json.dumps(value).encode(), b""))
        if len(argv) >= 11 and argv[:6] == ["docker", "exec", "--user", "10002:10002", "--workdir", "/app"] \
                and argv[6] == CONTAINER_IDS["runner"] and argv[7:10] == ["python3", "-I", "-c"]:
            code = argv[10]
            if "native_source_identity_mismatch" in code:
                value = {"schema_version": "byq-native-projector-preflight.v1",
                    "workspace_mount": argv[-1], "zstd_stream_api": True,
                    "reader_uid": 10002, "reader_gid": 10002,
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
                return self._record_result(subprocess.CompletedProcess(argv, 0, json.dumps(value).encode(), b""))
        if len(argv) >= 12 and argv[:7] == ["docker", "exec", "--user", "10002:10002",
                "--workdir", "/app", "-i"] and argv[7] == CONTAINER_IDS["runner"] \
                and argv[8:11] == ["python3", "-I", "-c"]:
            code = argv[11]
            if "safe_file(native)" in code:
                if self.failure == "source_native" or code != capture._native_reader_source():
                    return self._record_result(subprocess.CompletedProcess(argv, 1, b"", b"source mismatch"))
                result = self._native_exec(argv, stdout=stdout, stderr=stderr,
                                           timeout=timeout, check=check)
                return self._record_result(subprocess.CompletedProcess(
                    argv, result.returncode, result.stdout, result.stderr))
        if len(argv) >= 10 and argv[:5] == ["docker", "exec", "--workdir", "/app", "-i"] \
                and argv[6:9] == ["python3", "-I", "-c"]:
            container, code = argv[5], argv[9]
            if container == CONTAINER_IDS["adapter"] and "b=pathlib.Path(sys.argv[1])" in code:
                if argv[10:] != [
                    str(Path(capture.ordinary.SESSION_ROOT) / capture.ordinary.WORKSPACE
                        / "byq-acp-bindings" / f"{RUNTIME_ID}.json"),
                    str(Path(capture.ordinary.SESSION_ROOT) / capture.ordinary.WORKSPACE), ROOT_RUN]:
                    raise AssertionError("binding reader argv did not bind runtime session and root")
                value = {"binding": self.binding(), "journal": self.provider_journal()}
                return self._record_result(subprocess.CompletedProcess(argv, 0, json.dumps(value).encode(), b""))
            if container == CONTAINER_IDS["adapter"] and "product-turn-tool-guard-" in code:
                if argv[10:] != [str(self.cwd), ROOT_RUN]:
                    raise AssertionError("tool guard reader did not use binding cwd/root")
                names = ["byq_agent_run_start", "byq_delegate_market_research",
                         "byq_agent_run_start", "byq_agent_authorize",
                         "byq_market_session_context", "byq_agent_audit"]
                rows = [{"schema_version": "product-turn-tool-guard.v1",
                    "execution_profile": {"profile_id": "product-turn.v1", "profile_version": 1,
                        "profile_sha256": capture.PRODUCT_TURN_PROFILE_SHA256},
                    "request_limits": capture._LIMITS, "ready": True}]
                rows.extend({"phase": "tool", "call": index,
                             "tool_name": (name if name == "byq_delegate_market_research"
                                           else "mcp__byq__" + name)}
                            for index, name in enumerate(names, 1))
                value = {"sha256": "9" * 64, "bytes": 1000, "rows": rows}
                return self._record_result(subprocess.CompletedProcess(argv, 0, json.dumps(value).encode(), b""))
            if container == CONTAINER_IDS["runner"] and "cleanup-receipt-proof.v1" in code:
                scope = json.loads(input.decode())
                if self.failure == "cleanup_scope":
                    scope["session_id"] = "wrong-session"
                return self._record_result(subprocess.CompletedProcess(argv, 0,
                    json.dumps(self.cleanup_proof(scope), separators=(",", ":")).encode(), b""))
        raise AssertionError(f"unrecognized fake Docker command: {argv!r}")


class ForegroundChildValidatorContractTests(unittest.TestCase):
    def test_frozen_capture_source_matches_reviewed_pin(self):
        self.assertEqual(hashlib.sha256(CAPTURE_PATH.read_bytes()).hexdigest(),
                         EXPECTED_CAPTURE_SOURCE_SHA)

    def test_native_source_extractor_uses_return_literal_and_keeps_distinct_identities(self):
        """Exercise _read_native's AST extraction and projection validation."""
        reader_source = capture._native_reader_source()
        reader_sha = hashlib.sha256(reader_source.encode()).hexdigest()
        self.assertEqual(reader_sha, EXPECTED_NATIVE_READER_SHA)
        root = _session(ROOT_NATIVE, 0)
        child = _session(CHILD_NATIVE, 1, "subagent", ROOT_NATIVE)
        raw = json.dumps({"schema_version": "byq-acp-native-foreground-child.v1",
                          "producer_source_sha256": reader_sha,
                          "root": root, "child": child}, separators=(",", ":")).encode()
        calls = []

        def fake_command(out, label, argv, *, timeout, deadline):
            calls.append((label, argv, timeout, deadline))
            return raw

        command = {"returncode": 0, "argv": None, "stdout_sha256": hashlib.sha256(raw).hexdigest()}
        def json_read(path):
            if Path(path).name == "native-child-projection.json":
                command["argv"] = calls[-1][1]
                return command
            raise AssertionError(f"unexpected evidence read: {path}")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(capture.ordinary, "_command", side_effect=fake_command), \
                 patch.object(capture.ordinary, "_json_read", side_effect=json_read):
                result = capture._read_native(
                    Path(tmp), "runner-fixed-id", CWD, WORKSPACE, ROOT_NATIVE,
                    CHILD_NATIVE, MARKER, ROOT_RUN, CHILD_RUN, deadline=123.0)

        self.assertEqual(len(calls), 1)
        argv = calls[0][1]
        self.assertEqual(argv[:7], ["docker", "exec", "--user", "10002:10002",
                                    "--workdir", "/app", "-i"])
        self.assertEqual(argv[7], "runner-fixed-id")
        self.assertEqual(argv[11], reader_source)
        self.assertEqual(argv[-1], reader_sha)
        self.assertEqual(result["root"]["header"]["id"], ROOT_NATIVE)
        self.assertEqual(result["child"]["header"]["id"], CHILD_NATIVE)
        self.assertNotEqual("public-conversation-id", "runtime-session-id")

    def test_native_projection_sequence_bounds_and_zero_ordering(self):
        reader_source = capture._native_reader_source()
        reader_sha = hashlib.sha256(reader_source.encode()).hexdigest()

        def call_row(assistant=0, call=1, result=2):
            return {
                "call_id": "call-1", "tool_name": "mcp__byq__byq_agent_run_start",
                "arguments_sha256": "a" * 64, "arguments_contract_valid": True,
                "assistant_sequence": assistant, "call_sequence": call,
                "result_sequence": result, "result_sha256": "b" * 64,
                "result_error": False, "audit_outcome_sha256": None,
                "delegate_kind": None, "delegate_run_id_sha256": None,
                "delegate_output_sha256": None, "delegate_output_type": None,
                "delegate_output_count": None,
            }

        def read_projection(root, child):
            raw = json.dumps({"schema_version": "byq-acp-native-foreground-child.v1",
                "producer_source_sha256": reader_sha, "root": root, "child": child},
                separators=(",", ":")).encode()
            command = {"returncode": 0, "argv": None,
                       "stdout_sha256": hashlib.sha256(raw).hexdigest()}
            seen = []

            def fake_command(_out, _label, argv, *, timeout, deadline):
                seen.append(argv)
                return raw

            def json_read(path):
                if Path(path).name != "native-child-projection.json":
                    raise AssertionError(f"unexpected evidence read: {path}")
                command["argv"] = seen[-1]
                return command

            with tempfile.TemporaryDirectory() as tmp:
                with patch.object(capture.ordinary, "_command", side_effect=fake_command), \
                     patch.object(capture.ordinary, "_json_read", side_effect=json_read):
                    return capture._read_native(Path(tmp), "runner-fixed-id", CWD, WORKSPACE,
                        ROOT_NATIVE, CHILD_NATIVE, MARKER, ROOT_RUN, CHILD_RUN, deadline=123.0)

        def projection(*, input_seq=0, call=None):
            root = _session(ROOT_NATIVE, 0, input_seq=input_seq,
                            calls=[] if call is None else [call])
            child = _session(CHILD_NATIVE, 1, "subagent", ROOT_NATIVE,
                             input_seq=input_seq, calls=[] if call is None else [call])
            return root, child

        # seq=0 and assistant=0 are valid when call/result retain strict order.
        root, child = projection(call=call_row(assistant=0, call=1, result=2))
        accepted = read_projection(root, child)
        self.assertEqual(accepted["root"]["user_inputs"][0]["seq"], 0)
        self.assertEqual(accepted["root"]["calls"][0]["assistant_sequence"], 0)

        max_safe = (1 << 53) - 1
        for invalid in (-1, True, max_safe + 1):
            with self.subTest(field="user_input.seq", invalid=invalid):
                root, child = projection(input_seq=invalid)
                with self.assertRaisesRegex(capture.Stop, "native_child_projection_input_invalid"):
                    read_projection(root, child)
        for field in ("assistant_sequence", "call_sequence", "result_sequence"):
            for invalid in (-1, True, max_safe + 1):
                with self.subTest(field=field, invalid=invalid):
                    call = call_row()
                    call[field] = invalid
                    root, child = projection(call=call)
                    with self.assertRaisesRegex(capture.Stop, "native_child_projection_call_invalid"):
                        read_projection(root, child)

    def test_delegate_preflight_requires_current_product_runner_source_pin(self):
        args = type("Args", (), {"runner_id": "3" * 12})()
        runner_sha = "abc8992083bca202d4e66354f254fb1ea095cd409b62fcbdc2d3b2e6b6912f31"
        value = {
            "schema_version": "byq-dsh-delegate-source-preflight.v1",
            "package_name": "@deepseek-ai/dsh-tool-subagent", "package_version": "0.2.0-rc.2",
            "package_sha256": EXPECTED_DELEGATE_PACKAGE_SHA,
            "source_sha256": EXPECTED_DELEGATE_SOURCE_SHA,
            "product_runner_source_path": "/opt/byq/acp_product_runner/server.py",
            "product_runner_source_sha256": runner_sha,
            "reader_uid": 10002, "reader_gid": 10002,
        }
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        seen = []
        def fake_command(out, label, argv, *, timeout, deadline):
            seen.append((label, argv, timeout))
            return raw
        receipt = {"returncode": 0, "argv": None,
                   "stdout_sha256": hashlib.sha256(raw).hexdigest()}
        def json_read(path):
            if Path(path).name != "delegate-source-preflight.json":
                raise AssertionError(f"unexpected receipt path: {path}")
            receipt["argv"] = seen[-1][1]
            return receipt
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(capture.ordinary, "_command", side_effect=fake_command), \
                 patch.object(capture.ordinary, "_json_read", side_effect=json_read):
                capture._delegate_source_preflight(args, Path(tmp), deadline=123.0)
        self.assertEqual(runner_sha, EXPECTED_RUNNER_SOURCE_SHA)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], "delegate-source-preflight")
        argv = seen[0][1]
        self.assertEqual(argv[:7], ["docker", "exec", "--user", "10002:10002",
                                    "--workdir", "/app", "-i"])
        self.assertEqual(argv[7], args.runner_id)
        self.assertEqual(argv[8:11], ["python3", "-I", "-c"])
        self.assertIn("/opt/byq/acp_product_runner/server.py", argv[11])
        self.assertIn("/opt/dsh-runtime/packages/subagent/tool-subagent", argv[11])

    def test_finish_main_accepts_public_conversation_and_distinct_runtime_session(self):
        """Exercise the real finish entry against a synthetic read-only transport."""
        public_id = "public-conversation-20261013"
        runtime_id = "runtime-session-distinct-20261013"
        trace_id = "trace-child-test"
        root_id = "a" * 32
        marker_sha = hashlib.sha256(MARKER.encode()).hexdigest()
        ids = {"gateway": "1" * 12, "adapter": "2" * 12,
               "runner": "3" * 12, "postgres": "4" * 12}
        services = {"gateway": "gateway", "adapter": "runtime-adapter",
                    "runner": "acp-product-runner", "postgres": "postgres"}
        started = "2026-10-13T00:00:00Z"
        baseline = {"project": capture.ordinary.PROJECT, "requested_ids": ids,
                    "containers": {name: {"id": cid, "image_id": "sha256:" + name * 64,
                        "started_at": started, "running": "true",
                        "project": capture.ordinary.PROJECT, "service": services[name]}
                        for name, cid in ids.items()}}
        identity_scope = {"workspace_id": capture.ordinary.WORKSPACE,
                          "owner_principal": "admin", "session_id": runtime_id,
                          "trace_id": trace_id, "root_run_id": root_id}
        result = {"schema_version": capture._OUTCOME, "status": "PASS",
                  "scope": identity_scope, "child_run_id": "b" * 32,
                  "child_native_session_id_sha256": "c" * 64,
                  "child_role_id": "market_researcher", "child_role_version": "1.4.0",
                  "terminal_ack_observed": True, "root_process_group_cleanup_proven": True,
                  "individual_native_child_closed": "UNKNOWN",
                  "per_child_provider_attribution": "UNKNOWN",
                  "model_calls_claim": "root aggregate only"}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "capture"
            out.mkdir(mode=0o700)
            os.chmod(out, 0o700)
            now = time.monotonic_ns()
            capture.ordinary._json_write(out / "batch-clock.json", {
                "schema_version": "byq-ordinary-capture-clock.v1",
                "boot_id": capture.ordinary._boot_id(),
                "started_monotonic_ns": now - 1_000_000_000,
                "deadline_monotonic_ns": now + 60_000_000_000,
                "started_utc": "2026-10-13T00:00:00+00:00", "budget_seconds": 240})
            capture.ordinary._json_write(out / "container-facts-preflight.json", baseline)
            capture.ordinary._json_write(out / "checkpoint-preflight-pass.json", {"status": "PASS"})
            capture.ordinary._json_write(out / "checkpoint-child-pass.json", {"status": "PASS"})
            capture.ordinary._json_write(out / "child-capture.json", result)
            capture.ordinary._json_write(out / "observer-result.json", result)
            capture.ordinary._json_write(out / "conversation-projection.json", {
                "conversation_id": public_id, "runtime_session_id": runtime_id,
                "trace_id": trace_id, "root_run_id": root_id,
                "case_marker_sha256": marker_sha})
            capture.ordinary._json_write(out / "scope.json", {
                **identity_scope, "generation_id": "d" * 32,
                "cwd_leaf": "session-" + "e" * 32,
                "runtime_boot_id": "f" * 32,
                "actor_principal": "byq-product-agent-session-test"})

            def fake_run(argv, *, input=None, stdout=None, stderr=None, timeout=None,
                         check=False, **kwargs):
                if kwargs or input is not None or stdout != subprocess.PIPE or stderr != subprocess.PIPE:
                    raise AssertionError("finish must use the bounded captured Docker transport")
                if argv[:3] != ["docker", "inspect", "--format"]:
                    raise AssertionError(f"unexpected finish transport: {argv!r}")
                cid = argv[4]
                name = next((key for key, value in ids.items() if value == cid), None)
                if name is None:
                    raise AssertionError("finish inspected a container outside its fixed scope")
                row = baseline["containers"][name]
                value = "|".join(row[key] for key in (
                    "id", "image_id", "started_at", "running", "project", "service"))
                return subprocess.CompletedProcess(argv, 0, (value + "\n").encode(), b"")

            argv = ["capture", "finish", "--out-dir", str(out),
                    "--conversation-id", public_id, "--case-marker", MARKER,
                    "--gateway-id", ids["gateway"], "--adapter-id", ids["adapter"],
                    "--runner-id", ids["runner"], "--postgres-id", ids["postgres"],
                    "--session-root", capture.ordinary.SESSION_ROOT]
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(capture.sys, "argv", argv), \
                 patch.object(capture.ordinary.subprocess, "run", side_effect=fake_run), \
                 contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                rc = capture.main()

            self.assertEqual(rc, 0, stderr.getvalue())
            self.assertIn('"status": "FINISH_PASS"', stdout.getvalue())
            self.assertTrue((out / "checkpoint-finish-pass.json").is_file())
            self.assertFalse((out / "capture-stop.json").exists())

    def test_provider_journal_allows_unknown_usage_without_claiming_actual_tokens(self):
        aggregate = capture._validate_provider_journal(
            _provider_rows(), ROOT_RUN, "generation-test")
        self.assertEqual(aggregate["provider_calls"], 1)
        self.assertEqual(aggregate["actual_input_tokens"], "unknown")
        self.assertEqual(aggregate["actual_cache_read_tokens"], "unknown")
        self.assertEqual(aggregate["actual_output_tokens"], "unknown")
        self.assertEqual(aggregate["attribution"], "root_aggregate_only_child_unknown")

    def test_provider_journal_uses_epoch_timestamps_and_checks_elapsed_difference(self):
        start_ms = 1_780_000_000_000
        aggregate = capture._validate_provider_journal(_provider_rows(
            admitted_ms=start_ms, completed_ms=start_ms + 180_000),
            ROOT_RUN, "generation-test")
        self.assertEqual(aggregate["observed_elapsed_ms"], 180_000)

    def test_provider_journal_rejects_unknown_source_with_numeric_usage(self):
        raw = json.loads(_provider_rows().splitlines()[1])
        raw["actual_output_tokens"] = 1
        malformed = _provider_rows().splitlines()[0] + b"\n" + json.dumps(raw).encode() + b"\n"
        with self.assertRaisesRegex(capture.Stop, "provider_journal_usage_invalid"):
            capture._validate_provider_journal(malformed, ROOT_RUN, "generation-test")

    def test_provider_journal_rejects_output_above_declared_request_ceiling(self):
        raw = json.loads(_provider_rows(usage=129, usage_source="provider_response",
                                        output=128).splitlines()[1])
        malformed = _provider_rows(usage=129, usage_source="provider_response",
                                   output=128).splitlines()[0] + b"\n" + json.dumps(raw).encode() + b"\n"
        with self.assertRaisesRegex(capture.Stop, "provider_journal_usage_invalid"):
            capture._validate_provider_journal(malformed, ROOT_RUN, "generation-test")

    def test_provider_journal_enforces_per_request_admission_budgets(self):
        for field, invalid_value in (
            ("input_bytes", 262145),
            ("declared_max_output_tokens", 8193),
            ("tool_payload_bytes", 131073),
        ):
            with self.subTest(field=field):
                rows = [json.loads(line) for line in _provider_rows().decode().splitlines()]
                rows[0][field] = invalid_value
                malformed = (json.dumps(rows[0]).encode() + b"\n"
                             + json.dumps(rows[1]).encode() + b"\n")
                with self.assertRaises(capture.Stop):
                    capture._validate_provider_journal(malformed, ROOT_RUN, "generation-test")

    def test_provider_journal_rejects_elapsed_window_over_three_minutes(self):
        start_ms = 1_780_000_000_000
        first = _provider_call_pair(1, start_ms, elapsed_ms=25)
        second = _provider_call_pair(2, start_ms + 180_000, elapsed_ms=25)
        # Each request is legal and serial. Only the aggregate first-to-last
        # observation span exceeds the three-minute window.
        raw = _provider_journal([first[0], first[1], second[0], second[1]])
        with self.assertRaisesRegex(capture.Stop, "provider_journal_limits_or_settlement_invalid"):
            capture._validate_provider_journal(raw, ROOT_RUN, "generation-test")

    def test_provider_journal_accepts_exact_cumulative_input_output_and_call_caps(self):
        start_ms = 1_780_000_000_000
        rows = []
        for call in range(1, 17):
            rows.extend(_provider_call_pair(call, start_ms + (call - 1) * 25,
                input_bytes=262_144, declared_output=8_192, tool_payload_bytes=0))
        aggregate = capture._validate_provider_journal(_provider_journal(rows), ROOT_RUN,
                                                        "generation-test")
        self.assertEqual(aggregate["provider_calls"], 16)
        self.assertEqual(aggregate["input_bytes"], 4_194_304)
        self.assertEqual(aggregate["declared_output_tokens"], 131_072)

    def test_provider_journal_cumulative_tool_payload_limit_and_exact_boundary(self):
        start_ms = 1_780_000_000_000
        at_limit = []
        for call in range(1, 9):
            at_limit.extend(_provider_call_pair(call, start_ms + (call - 1) * 25,
                input_bytes=0, declared_output=1, tool_payload_bytes=131_072))
        aggregate = capture._validate_provider_journal(_provider_journal(at_limit), ROOT_RUN,
                                                        "generation-test")
        self.assertEqual(aggregate["tool_payload_bytes"], 1_048_576)

        over_limit = list(at_limit)
        over_limit.extend(_provider_call_pair(9, start_ms + 8 * 25,
            input_bytes=0, declared_output=1, tool_payload_bytes=131_072))
        with self.assertRaisesRegex(capture.Stop, "provider_journal_cumulative_limit_exceeded"):
            capture._validate_provider_journal(_provider_journal(over_limit), ROOT_RUN,
                                                "generation-test")

    def test_provider_journal_rejects_seventeenth_call_and_attempt(self):
        start_ms = 1_780_000_000_000
        rows = []
        for call in range(1, 18):
            rows.extend(_provider_call_pair(call, start_ms + (call - 1) * 25,
                input_bytes=0, declared_output=1, tool_payload_bytes=0))
        # The contract requires call == attempt == admission ordinal and both
        # caps are 16, so the seventeenth admission reaches both equal limits.
        with self.assertRaisesRegex(capture.Stop, "provider_journal_admission_invalid"):
            capture._validate_provider_journal(_provider_journal(rows), ROOT_RUN,
                                                "generation-test")

    def test_provider_journal_rejects_peak_concurrency_above_one(self):
        start_ms = 1_780_000_000_000
        first = _provider_call_pair(1, start_ms, elapsed_ms=25,
            input_bytes=0, declared_output=1, tool_payload_bytes=0)
        second = _provider_call_pair(2, start_ms + 1, elapsed_ms=25,
            input_bytes=0, declared_output=1, tool_payload_bytes=0)
        rows = [first[0], second[0], first[1], second[1]]
        with self.assertRaisesRegex(capture.Stop, "provider_journal_limits_or_settlement_invalid"):
            capture._validate_provider_journal(_provider_journal(rows), ROOT_RUN,
                                                "generation-test")


class ForegroundChildWholeMainContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.outputs = []

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _argv(out, action, *extra):
        return ["capture", action, "--out-dir", str(out),
            "--gateway-id", CONTAINER_IDS["gateway"],
            "--adapter-id", CONTAINER_IDS["adapter"],
            "--runner-id", CONTAINER_IDS["runner"],
            "--postgres-id", CONTAINER_IDS["postgres"],
            "--session-root", capture.ordinary.SESSION_ROOT, *extra]

    def _execute(self, fixture, out, action, *extra):
        if out not in self.outputs:
            self.outputs.append(out)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(capture.sys, "argv", self._argv(out, action, *extra)), \
             patch.object(capture.ordinary, "CookieJar", side_effect=fixture.cookie_jar_factory), \
             patch.object(capture.ordinary, "HTTPCookieProcessor", side_effect=lambda jar: jar), \
             patch.object(capture.ordinary, "build_opener", side_effect=fixture.build_opener), \
             patch.object(capture.ordinary.subprocess, "run", side_effect=fixture.run), \
             patch.dict(os.environ, {"BYQ_E2E_ADMIN_USERNAME": "admin",
                                    "BYQ_E2E_ADMIN_PASSWORD": "synthetic-only-password"}), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = capture.main()
        return rc, stdout.getvalue(), stderr.getvalue()

    def _run_preflight_and_child(self, fixture, out):
        preflight = self._execute(fixture, out, "preflight")
        self.assertEqual(preflight[0], 0, preflight[2])
        return self._execute(fixture, out, "capture-child",
                             "--conversation-id", PUBLIC_ID, "--case-marker", MARKER)

    def _assert_command_receipt(self, out, label, fixture, expected_rc):
        receipt_path = out / "commands" / f"{label}.json"
        self.assertTrue(receipt_path.is_file(), f"missing command receipt: {label}")
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt.get("returncode"), expected_rc, label)
        self.assertIsInstance(receipt.get("argv"), list, label)
        self.assertIn(receipt["argv"], fixture.commands, label)
        matching = []
        for index, result in enumerate(fixture.command_results):
            if index in fixture.receipt_result_matches or list(result["argv"]) != receipt["argv"]:
                continue
            stdout, stderr = result["stdout"], result["stderr"]
            if (result["returncode"] == receipt["returncode"]
                    and receipt.get("stdout_bytes") == len(stdout)
                    and receipt.get("stdout_sha256") == hashlib.sha256(stdout).hexdigest()
                    and receipt.get("stderr_bytes") == len(stderr)
                    and receipt.get("stderr_sha256") == hashlib.sha256(stderr).hexdigest()):
                matching.append((index, result))
        self.assertGreaterEqual(len(matching), 1,
                                f"{label}: receipt does not join to an actual fake response")
        index, result = matching[0]
        fixture.receipt_result_matches.add(index)
        stem = receipt_path.stem
        if label != "gateway-terminal-ack-log":
            stdout = (receipt_path.parent / f"{stem}.stdout.raw").read_bytes()
            stderr = (receipt_path.parent / f"{stem}.stderr.raw").read_bytes()
            self.assertEqual(stdout, result["stdout"], label)
            self.assertEqual(stderr, result["stderr"], label)
        return receipt

    def _assert_all_success_command_receipts(self, out, fixture):
        receipts = sorted((out / "commands").glob("*.json"))
        receipt_argvs = []
        for path in receipts:
            label = path.stem
            receipt = self._assert_command_receipt(out, label, fixture, 0)
            receipt_argvs.append(tuple(receipt["argv"]))
        self.assertEqual(Counter(receipt_argvs), Counter(tuple(argv) for argv in fixture.commands))
        self.assertEqual(len(fixture.command_results), len(fixture.commands))
        self.assertEqual(len(fixture.receipt_result_matches), len(fixture.command_results))

    @staticmethod
    def _request_path(request):
        return request.full_url.removeprefix(capture.ordinary.ORIGIN)

    def test_real_main_preflight_capture_child_finish_full_chain_synthetic_transport(self):
        fixture = _WholeEntryFixture()
        self.addCleanup(fixture.cleanup)
        out = self.root / "success"
        capture_rc = self._run_preflight_and_child(fixture, out)
        self.assertEqual(capture_rc[0], 0, capture_rc[2])
        finish = self._execute(fixture, out, "finish",
                               "--conversation-id", PUBLIC_ID, "--case-marker", MARKER)
        self.assertEqual(finish[0], 0, finish[2])
        self.assertIn("FINISH_PASS", finish[1])
        self.assertTrue((out / "checkpoint-preflight-pass.json").is_file())
        self.assertTrue((out / "checkpoint-child-pass.json").is_file())
        self.assertTrue((out / "checkpoint-finish-pass.json").is_file())
        self.assertFalse((out / "capture-stop.json").exists())
        conversation = json.loads((out / "conversation-projection.json").read_text())
        result = json.loads((out / "observer-result.json").read_text())
        self.assertEqual(conversation["conversation_id"], PUBLIC_ID)
        self.assertEqual(conversation["runtime_session_id"], RUNTIME_ID)
        self.assertNotEqual(conversation["conversation_id"], conversation["runtime_session_id"])
        self.assertEqual(result["scope"]["session_id"], RUNTIME_ID)
        self.assertEqual(result["individual_native_child_closed"], "UNKNOWN")
        self.assertEqual(result["per_child_provider_attribution"], "UNKNOWN")
        self.assertEqual(result["model_calls_claim"], "root aggregate only")
        native = json.loads((out / "native-child-projection.json").read_text())
        backend = json.loads((out / "commands/child-backend-scope.stdout.raw").read_bytes())
        self.assertEqual(native["root"]["header"]["id"], ROOT_NATIVE)
        self.assertEqual(native["child"]["header"]["id"], CHILD_NATIVE)
        self.assertEqual(len(native["root"]["calls"]), 2)
        self.assertEqual(len(native["child"]["calls"]), 4)
        audits = backend["audits"]
        self.assertEqual(Counter((row["action"], row["outcome"]) for row in audits), Counter({
            ("runtime_turn_binding", "active"): 2,
            ("runtime_turn_binding", "completed"): 2,
            ("byq_market_session_context", "authorized"): 1,
            ("byq_market_session_context", "completed"): 1,
        }))
        self.assertEqual((out / "signed-cleanup-proof.json").is_file(), True)
        self.assertEqual(fixture.inspect_counts["runner"], 3)
        self.assertIn("--user", " ".join(" ".join(argv) for argv in fixture.commands))
        self._assert_all_success_command_receipts(out, fixture)

    def test_real_main_accepts_zero_native_user_sequences(self):
        fixture = _WholeEntryFixture(sequence_start=0)
        self.addCleanup(fixture.cleanup)
        out = self.root / "zero-native-sequences"
        capture_rc = self._run_preflight_and_child(fixture, out)
        self.assertEqual(capture_rc[0], 0, capture_rc[2])
        finish = self._execute(fixture, out, "finish",
                               "--conversation-id", PUBLIC_ID, "--case-marker", MARKER)
        self.assertEqual(finish[0], 0, finish[2])
        native = json.loads((out / "native-child-projection.json").read_text())
        for side in ("root", "child"):
            session = native[side]
            self.assertEqual(session["user_inputs"][0]["seq"], 0)
            self.assertTrue(all(call["assistant_sequence"] < call["call_sequence"]
                                < call["result_sequence"] for call in session["calls"]))
        self._assert_all_success_command_receipts(out, fixture)

    def test_real_main_accepts_close_runtime_root_without_terminal_binding_audits(self):
        fixture = _WholeEntryFixture(completed_binding=False)
        self.addCleanup(fixture.cleanup)
        out = self.root / "close-runtime-root-path"
        capture_rc = self._run_preflight_and_child(fixture, out)
        self.assertEqual(capture_rc[0], 0, capture_rc[2])
        finish = self._execute(fixture, out, "finish",
                               "--conversation-id", PUBLIC_ID, "--case-marker", MARKER)
        self.assertEqual(finish[0], 0, finish[2])
        self.assertTrue((out / "checkpoint-finish-pass.json").is_file())
        self._assert_all_success_command_receipts(out, fixture)

    def test_whole_main_fail_stop_matrix_preserves_first_stop(self):
        audit_chain_later = ("commands/product-tool-guard.json",
                             "commands/signed-product-cleanup.json",
                             "commands/gateway-terminal-ack-log.json")
        audit_scope_later = ("commands/native-child-projection.json", *audit_chain_later)
        cases = {
            "native_bad_call_parent": ("native_child_projection_call_invalid",
                                        "native-child-projection", 0),
            "native_event_seq_negative": ("native-child-projection_process_failed",
                                           "native-child-projection", 2),
            "native_event_seq_bool": ("native-child-projection_process_failed",
                                      "native-child-projection", 2),
            "native_event_seq_oversafe": ("native-child-projection_process_failed",
                                          "native-child-projection", 2),
            "native_call_sequence_not_after_assistant": (
                "native_tool_call_result_not_complete", "native-child-projection", 0),
            "native_result_sequence_not_after_call": (
                "native_tool_call_result_not_complete", "native-child-projection", 0),
            "reader_uid_wrong": ("native-child-projection_process_failed", "native-child-projection", 1),
            "reader_gid_wrong": ("native-child-projection_process_failed", "native-child-projection", 1),
            "native_header_extra": ("native-child-projection_process_failed", "native-child-projection", 2),
            "source_native": ("native-child-projection_process_failed", "native-child-projection", 1),
            "foreign_root": ("workflow_root_identity_mismatch", None, None),
            "delivery_stale": ("answer_delivery_not_up_to_date", None, None),
            "ack_missing": ("gateway_ack_missing_or_conflicting", "gateway-terminal-ack-log", 0),
            "ack_conflict": ("gateway_ack_missing_or_conflicting", "gateway-terminal-ack-log", 0),
            "cleanup_scope": ("signed_cleanup_scope_mismatch", "signed-product-cleanup", 0),
            "foreign_sql": ("backend_child_scope_invalid", "child-backend-scope", 0),
            "job_delta": ("business_job_artifact_inventory_changed", "jobs-after", 0),
            "container_drift": ("container_identity_or_start_changed", "container-child-runner", 0),
            "audit_terminal_completed_missing": ("backend_child_audit_mismatch", "child-backend-scope", 0),
            "audit_terminal_completed_duplicate": ("backend_child_audit_mismatch", "child-backend-scope", 0),
            "audit_authorized_missing": ("backend_child_audit_mismatch", "child-backend-scope", 0),
            "audit_authorized_wrong": ("backend_child_audit_mismatch", "child-backend-scope", 0),
            "audit_authorized_duplicate": ("backend_child_audit_mismatch", "child-backend-scope", 0),
            "audit_explicit_missing": ("backend_child_audit_mismatch", "child-backend-scope", 0),
            "audit_explicit_duplicate": ("backend_child_audit_mismatch", "child-backend-scope", 0),
            "audit_unknown_action": ("backend_child_audit_mismatch", "child-backend-scope", 0),
            "audit_cross_run_native": ("backend_child_scope_invalid", "child-backend-scope", 0),
            "audit_native_failed": ("backend_child_audit_mismatch", "child-backend-scope", 0),
            "audit_native_unknown": ("backend_child_audit_mismatch", "child-backend-scope", 0),
        }
        no_later_receipts = {
            "native_header_extra": ("commands/product-tool-guard.json",
                                     "commands/signed-product-cleanup.json",
                                     "commands/gateway-terminal-ack-log.json"),
            "native_bad_call_parent": ("commands/product-tool-guard.json",
                                       "commands/signed-product-cleanup.json",
                                       "commands/gateway-terminal-ack-log.json"),
            "native_event_seq_negative": ("commands/product-tool-guard.json",
                                           "commands/signed-product-cleanup.json",
                                           "commands/gateway-terminal-ack-log.json"),
            "native_event_seq_bool": ("commands/product-tool-guard.json",
                                      "commands/signed-product-cleanup.json",
                                      "commands/gateway-terminal-ack-log.json"),
            "native_event_seq_oversafe": ("commands/product-tool-guard.json",
                                          "commands/signed-product-cleanup.json",
                                          "commands/gateway-terminal-ack-log.json"),
            "native_call_sequence_not_after_assistant": (
                "commands/product-tool-guard.json", "commands/signed-product-cleanup.json",
                "commands/gateway-terminal-ack-log.json"),
            "native_result_sequence_not_after_call": (
                "commands/product-tool-guard.json", "commands/signed-product-cleanup.json",
                "commands/gateway-terminal-ack-log.json"),
            "reader_uid_wrong": ("commands/product-tool-guard.json",
                                 "commands/signed-product-cleanup.json",
                                 "commands/gateway-terminal-ack-log.json"),
            "reader_gid_wrong": ("commands/product-tool-guard.json",
                                 "commands/signed-product-cleanup.json",
                                 "commands/gateway-terminal-ack-log.json"),
            "source_native": ("commands/product-tool-guard.json",
                              "commands/signed-product-cleanup.json",
                              "commands/gateway-terminal-ack-log.json"),
            "foreign_root": ("commands/child-backend-scope.json",
                             "commands/native-child-projection.json"),
            "delivery_stale": ("commands/child-backend-scope.json",
                               "commands/native-child-projection.json"),
            "ack_missing": ("commands/jobs-after.json", "observer-result.json"),
            "ack_conflict": ("commands/jobs-after.json", "observer-result.json"),
            "cleanup_scope": ("commands/gateway-terminal-ack-log.json",
                              "commands/jobs-after.json"),
            "foreign_sql": ("commands/native-child-projection.json",
                             "commands/signed-product-cleanup.json"),
            "job_delta": ("observer-result.json", "checkpoint-child-pass.json"),
            "container_drift": ("conversation-projection.json",
                                 "commands/child-backend-scope.json"),
            "audit_terminal_completed_missing": audit_chain_later,
            "audit_terminal_completed_duplicate": audit_chain_later,
            "audit_authorized_missing": audit_chain_later,
            "audit_authorized_wrong": audit_chain_later,
            "audit_authorized_duplicate": audit_chain_later,
            "audit_explicit_missing": audit_chain_later,
            "audit_explicit_duplicate": audit_chain_later,
            "audit_unknown_action": audit_chain_later,
            "audit_cross_run_native": audit_scope_later,
            "audit_native_failed": audit_chain_later,
            "audit_native_unknown": audit_chain_later,
        }
        self.assertEqual(set(cases), set(no_later_receipts))
        audit_chain_keys = {key for key in cases if key.startswith("audit_")} - {"audit_cross_run_native"}
        self.assertTrue(all(no_later_receipts[key] == audit_chain_later for key in audit_chain_keys))
        self.assertEqual(no_later_receipts["audit_cross_run_native"], audit_scope_later)
        for failure, (expected_reason, target_label, target_rc) in cases.items():
            with self.subTest(failure=failure):
                fixture = _WholeEntryFixture(failure=failure)
                self.addCleanup(fixture.cleanup)
                out = self.root / failure
                rc, _stdout, stderr = self._run_preflight_and_child(fixture, out)
                self.assertEqual(rc, 2, f"{failure}: unexpectedly passed")
                self.assertTrue((out / "checkpoint-preflight-pass.json").is_file(), failure)
                self.assertTrue((out / "checkpoint-child-start.json").is_file(), failure)
                stop_path = out / "capture-stop.json"
                self.assertTrue(stop_path.is_file(), failure)
                self.assertEqual(json.loads(stop_path.read_text()).get("reason"),
                                 expected_reason, f"{failure}: wrong STOP stage/reason; {stderr}")
                self.assertFalse((out / "checkpoint-child-pass.json").exists())
                self.assertFalse((out / "checkpoint-finish-start.json").exists())
                self.assertFalse((out / "checkpoint-finish-pass.json").exists())
                self.assertFalse((out / "observer-result.json").exists())
                for path in no_later_receipts[failure]:
                    self.assertFalse((out / path).exists(), f"{failure}: later stage ran: {path}")
                if target_label is not None:
                    receipt = self._assert_command_receipt(out, target_label, fixture, target_rc)
                else:
                    receipt = None
                request_paths = [self._request_path(request) for request in fixture.requests]
                if failure == "foreign_root":
                    self.assertIn(f"/v1/workflows/{PUBLIC_ID}/events", request_paths)
                    self.assertNotIn(f"/v1/agent/sessions/{PUBLIC_ID}/answer-delivery", request_paths)
                elif failure == "delivery_stale":
                    self.assertIn(f"/v1/agent/sessions/{PUBLIC_ID}/answer-delivery", request_paths)
                    self.assertEqual(request_paths.count(f"/v1/agent/sessions/{PUBLIC_ID}"), 1)
                elif failure == "container_drift":
                    self.assertEqual(request_paths.count("/api/auth/login"), 1)
                    self.assertNotIn(f"/v1/workflows/{PUBLIC_ID}/events", request_paths)
                    facts = json.loads((out / "container-facts-child.json").read_text())
                    self.assertNotEqual(facts["containers"]["runner"]["started_at"],
                                        fixture.started_at)
                elif failure == "native_bad_call_parent":
                    projection = json.loads((out / "commands/native-child-projection.stdout.raw").read_bytes())
                    invalid = [call for call in projection["child"]["calls"]
                               if call["tool_name"] == "mcp__byq__byq_agent_run_start"
                               and call["arguments_contract_valid"] is False]
                    self.assertEqual(len(invalid), 1)
                elif failure in ("reader_uid_wrong", "reader_gid_wrong"):
                    # The inner reader exits 1 before its protected parser block;
                    # the collector records rc 2 with its stable projection STOP.
                    raw_stderr = (out / "commands/native-child-projection.stderr.raw").read_bytes()
                    self.assertEqual(raw_stderr, b"native_reader_identity_mismatch\n")
                    self.assertEqual(receipt["returncode"], 1)
                    self.assertEqual(json.loads(stop_path.read_text())["reason"],
                                     "native-child-projection_process_failed")
                elif failure == "native_header_extra":
                    raw_stderr = (out / "commands/native-child-projection.stderr.raw").read_bytes()
                    self.assertEqual(raw_stderr, b"NATIVE_CHILD_STOP:native_header_invalid\n")
                    self.assertEqual(receipt["returncode"], 2)
                    self.assertEqual(json.loads(stop_path.read_text())["reason"],
                                     "native-child-projection_process_failed")
                elif failure in {"native_event_seq_negative", "native_event_seq_bool",
                                 "native_event_seq_oversafe"}:
                    raw_stdout = (out / "commands/native-child-projection.stdout.raw").read_bytes()
                    raw_stderr = (out / "commands/native-child-projection.stderr.raw").read_bytes()
                    self.assertEqual(raw_stdout, b"")
                    self.assertEqual(raw_stderr, b"NATIVE_CHILD_STOP:native_event_invalid\n")
                    self.assertEqual(receipt["returncode"], 2)
                    self.assertEqual(json.loads(stop_path.read_text())["reason"],
                                     "native-child-projection_process_failed")
                elif failure in {"native_call_sequence_not_after_assistant",
                                 "native_result_sequence_not_after_call"}:
                    projection = json.loads(
                        (out / "commands/native-child-projection.stdout.raw").read_bytes())
                    first = projection["root"]["calls"][0]
                    self.assertEqual(receipt["returncode"], 0)
                    if failure == "native_call_sequence_not_after_assistant":
                        self.assertEqual(first["assistant_sequence"], first["call_sequence"])
                    else:
                        self.assertEqual(first["call_sequence"], first["result_sequence"])
                    self.assertEqual(json.loads(stop_path.read_text())["reason"],
                                     "native_tool_call_result_not_complete")
                elif failure == "cleanup_scope":
                    cleanup = json.loads((out / "commands/signed-product-cleanup.stdout.raw").read_bytes())
                    self.assertEqual(cleanup["exact_scope"]["session_id"], "wrong-session")
                elif failure == "foreign_sql":
                    projection = json.loads((out / "commands/child-backend-scope.stdout.raw").read_bytes())
                    self.assertEqual(projection["foreign_mismatch_count"], 1)
                elif failure == "job_delta":
                    before = json.loads((out / "jobs-before.json").read_text())
                    after = json.loads((out / "commands/jobs-after.stdout.raw").read_bytes())
                    self.assertNotEqual(before, after)
                elif failure in ("ack_missing", "ack_conflict"):
                    filtered = json.loads((out / "gateway-ack-filtered.json").read_text())
                    self.assertEqual(len(filtered["events"]), 0 if failure == "ack_missing" else 1)
                elif failure.startswith("audit_"):
                    if failure == "audit_cross_run_native":
                        self.assertFalse((out / "commands/native-child-projection.json").exists())
                    else:
                        self._assert_command_receipt(out, "native-child-projection", fixture, 0)
                    projection = json.loads(
                        (out / "commands/child-backend-scope.stdout.raw").read_bytes())
                    audits = projection["audits"]
                    bindings = [row for row in audits if row["action"] == "runtime_turn_binding"]
                    contexts = [row for row in audits if row["action"] == "byq_market_session_context"]
                    if failure == "audit_terminal_completed_missing":
                        self.assertEqual(Counter((row["run_id"], row["outcome"]) for row in bindings),
                            Counter({(ROOT_RUN, "active"): 1, (ROOT_RUN, "completed"): 1,
                                     (CHILD_RUN, "active"): 1}))
                    elif failure == "audit_terminal_completed_duplicate":
                        self.assertEqual(Counter((row["run_id"], row["outcome"]) for row in bindings),
                            Counter({(ROOT_RUN, "active"): 1, (ROOT_RUN, "completed"): 2,
                                     (CHILD_RUN, "active"): 1, (CHILD_RUN, "completed"): 1}))
                    elif failure == "audit_authorized_missing":
                        self.assertEqual([row["outcome"] for row in contexts], ["completed"])
                    elif failure == "audit_authorized_wrong":
                        self.assertEqual(Counter(row["outcome"] for row in contexts),
                                         Counter({"wrong": 1, "completed": 1}))
                    elif failure == "audit_authorized_duplicate":
                        self.assertEqual(Counter(row["outcome"] for row in contexts),
                                         Counter({"authorized": 2, "completed": 1}))
                    elif failure == "audit_explicit_missing":
                        self.assertEqual(Counter(row["outcome"] for row in contexts),
                                         Counter({"authorized": 1}))
                    elif failure == "audit_explicit_duplicate":
                        self.assertEqual(Counter(row["outcome"] for row in contexts),
                                         Counter({"authorized": 1, "completed": 2}))
                    elif failure == "audit_unknown_action":
                        self.assertTrue(any(row["action"] == "unknown_action" for row in audits))
                    elif failure == "audit_cross_run_native":
                        self.assertTrue(any(row["run_id"] == CHILD_RUN
                                            and row["native_agent_session_id"] == ROOT_NATIVE
                                            for row in contexts))
                    elif failure in ("audit_native_failed", "audit_native_unknown"):
                        self.assertEqual(Counter(row["outcome"] for row in contexts),
                            Counter({"authorized": 1,
                                     "failed" if failure == "audit_native_failed" else "unknown": 1}))
                self.assertTrue((out / "commands").is_dir(), failure)
                command_count = len(fixture.commands)
                request_count = len(fixture.requests)
                stop_first = (out / "capture-stop.json").read_bytes()
                retry_rc, _retry_stdout, retry_stderr = self._execute(
                    fixture, out, "capture-child", "--conversation-id", PUBLIC_ID,
                    "--case-marker", MARKER)
                self.assertEqual(retry_rc, 2, retry_stderr)
                self.assertEqual((out / "capture-stop.json").read_bytes(), stop_first)
                self.assertEqual(len(fixture.commands), command_count, failure)
                self.assertEqual(len(fixture.requests), request_count, failure)
                self.assertFalse((out / "checkpoint-finish-pass.json").exists())

    def test_runner_source_drift_stops_in_preflight_before_capture(self):
        fixture = _WholeEntryFixture(failure="runner_source_drift")
        self.addCleanup(fixture.cleanup)
        out = self.root / "runner-source-drift"
        rc, _stdout, stderr = self._execute(fixture, out, "preflight")
        self.assertEqual(rc, 2, stderr)
        stop = json.loads((out / "capture-stop.json").read_text())
        self.assertEqual(stop["reason"], "delegate_source_preflight_mismatch")
        self.assertFalse((out / "checkpoint-preflight-pass.json").exists())
        self.assertFalse((out / "checkpoint-child-start.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
