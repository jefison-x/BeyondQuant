#!/usr/bin/env python3
"""Read-only observer for ordinary uninterrupted two-turn ACP evidence.

It validates captured Product API/SSE artifacts, current BYQ binding and gate
receipts, and the pinned DSH v4 compressed native log. An offline contract
fixture can test the parser but cannot qualify a real conversation. The tool
has no network, provider, Job, database, Docker, or mutation code.

Usage: python3 scripts/evidence/acp-ordinary-continuous-observer.py --capture DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

_ROOT = re.compile(r"^[0-9a-f]{32}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_NATIVE_STORE_SOURCE_SHA256 = "0845707017acc2b4a8a75eab2244fa3fd88587b8094ab32014321dce7ca1e31b"
_NATIVE_HEADER_SOURCE_SHA256 = "87ea85e2fb5318bf1f826db9a1c88c1b26d3ea328027a7f32b211880c4d62b9d"
_NATIVE_BASE_PROFILE_SOURCE_SHA256 = "9c2be64f46a193eff3cca190c26e697e8e8eee25c9b40149dfdb56f8142c252d"
_PRODUCT_PROFILE_SHA256 = "10396c708651b24e3012df51e13cbb0e1eaf8178cda9547c91d682c189eacd45"
_PRODUCT_PROFILE_IDENTITY_SHA256 = "0e1f5494f99b4fba433f5f86653b6848377372c7308561bceaaddc3ea3f2f69b"
_DSH_SOURCE_COMMIT = "639ed015397290b3745d163aafe02ffee4aa3f84"
_STORE_PACKAGE_VERSION = "0.2.0-rc.2"
_NATIVE_PREFLIGHT_SOURCE_SHA256 = "9edc3029d7f4b897e44e8f753b687bd0751ec432ef12b4c96fcaeb940195073f"
_NATIVE_PROJECTION_SCHEMA = "byq-native-session-input-projection.v1"
_NATIVE_PROJECTION_SOURCE_SHA256 = "88703ff77934153095606ce81d3be1befc3b8eb79528e18e9c20074e1418ae36"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _session_project_key(cwd: str) -> str:
    readable = []
    separator = False
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
                return ""
            readable.append(f"~{code:04X}")
            separator = False
    return "--" + ("".join(readable).lstrip("-") or "root")[:251] + "--"


def _native_source_receipt(capture: Path) -> bool:
    value = _json(capture / "native-runtime-preflight.json")
    command = _json(capture / "commands" / "native-runtime-preflight.json")
    scope = _json(capture / "scope.json")
    containers = _json(capture / "container-facts-preflight.json")
    raw_path = capture / "commands" / "native-runtime-preflight.stdout.raw"
    try:
        raw = raw_path.read_bytes()
        raw_hash = _sha(raw)
        pairs = json.loads(raw.decode("utf-8"), object_pairs_hook=lambda items: _unique_pairs(items))
    except OSError:
        return False
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return False
    if (not isinstance(value, dict) or not isinstance(command, dict) or not isinstance(scope, dict)
            or not isinstance(containers, dict)
            or not isinstance(pairs, dict)
            or not isinstance(value.get("workspace_mount"), str)):
        return False
    argv = command.get("argv")
    requested = containers.get("requested_ids")
    runner_id = requested.get("runner") if isinstance(requested, dict) else None
    expected_command_hash = (_sha(json.dumps(argv, separators=(",", ":")).encode())
                             if isinstance(argv, list) else None)
    expected_record_hash = _sha(json.dumps(command, sort_keys=True, separators=(",", ":")).encode())
    raw_join = ({key: item for key, item in value.items() if not key.startswith("source_read_")} == pairs
                and set(value) == set(pairs) | {"source_read_command_sha256", "source_read_returncode",
                                                "source_read_stdout_sha256", "source_read_command_receipt_sha256"})
    return (value.get("schema_version") == "byq-native-projector-preflight.v1"
            and raw_join
            and value.get("reader_uid") == 10002 and value.get("reader_gid") == 10002
            and value.get("dsh_source_commit") == _DSH_SOURCE_COMMIT
            and value.get("store_package_version") == _STORE_PACKAGE_VERSION
            and value.get("store_source_sha256") == _NATIVE_STORE_SOURCE_SHA256
            and value.get("header_schema_source_sha256") == _NATIVE_HEADER_SOURCE_SHA256
            and value.get("base_profile_source_sha256") == _NATIVE_BASE_PROFILE_SOURCE_SHA256
            and value.get("product_profile_sha256") == _PRODUCT_PROFILE_SHA256
            and value.get("product_profile_identity_sha256") == _PRODUCT_PROFILE_IDENTITY_SHA256
            and value.get("product_profile") == "byq-product-acp-0.2.0-rc.2"
            and value.get("product_composition_hash") == f"sha256:{_PRODUCT_PROFILE_SHA256}"
            and value.get("dsh_home_contract") == "binding.cwd"
            and value.get("store_root_contract") == "dshHomePath(sessions)"
            and value.get("zstd_stream_api") is True
            and isinstance(scope.get("workspace_id"), str)
            and value.get("workspace_mount", "").endswith("/" + scope["workspace_id"])
            and command.get("returncode") == 0
            and isinstance(argv, list) and len(argv) == 13
            and argv[:6] == ["docker", "exec", "--user", "10002:10002", "--workdir", "/app"]
            and isinstance(runner_id, str) and argv[6] == runner_id
            and isinstance(argv[6], str) and _HASH.fullmatch(argv[6]) is not None and argv[7] == "python3"
            and argv[8:10] == ["-I", "-c"]
            and isinstance(argv[10], str) and _sha(argv[10].encode()) == _NATIVE_PREFLIGHT_SOURCE_SHA256
            and isinstance(argv[-2], str)
            and value.get("workspace_mount") == argv[-2].rstrip("/") + "/" + scope["workspace_id"]
            and argv[-1] == value.get("workspace_mount")
            and command.get("stderr_bytes") == 0
            and command.get("stderr_sha256") == _sha(b"")
            and command.get("stdout_bytes") == len(raw)
            and value.get("source_read_command_sha256") == expected_command_hash
            and value.get("source_read_returncode") == command.get("returncode")
            and value.get("source_read_stdout_sha256") == command.get("stdout_sha256") == raw_hash
            and value.get("source_read_command_receipt_sha256") == expected_record_hash)


def _native_projection_receipt(capture: Path, projection: dict) -> bool:
    command = _json(capture / "commands" / "native-projection.json")
    raw_path = capture / "commands" / "native-projection.stdout.raw"
    containers = _json(capture / "container-facts-preflight.json")
    try:
        raw = raw_path.read_bytes()
        pairs = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except OSError:
        return False
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(command, dict) or not isinstance(containers, dict) or not isinstance(pairs, dict):
        return False
    argv = command.get("argv")
    requested = containers.get("requested_ids")
    runner_id = requested.get("runner") if isinstance(requested, dict) else None
    if not isinstance(argv, list) or len(argv) != 16:
        return False
    cwd, native_id, workspace_id = (projection.get("binding_cwd"), projection.get("native_session_id"),
                                    projection.get("workspace_id"))
    return (pairs == projection
            and command.get("returncode") == 0
            and command.get("stdout_bytes") == len(raw)
            and command.get("stdout_sha256") == _sha(raw)
            and command.get("stderr_bytes") == 0
            and command.get("stderr_sha256") == _sha(b"")
            and argv[:7] == ["docker", "exec", "--user", "10002:10002", "--workdir", "/app", "-i"]
            and argv[7] == runner_id and isinstance(runner_id, str)
            and argv[8:11] == ["python3", "-I", "-c"]
            and isinstance(argv[11], str) and _sha(argv[11].encode()) == _NATIVE_PROJECTION_SOURCE_SHA256
            and argv[12:16] == [cwd, native_id, workspace_id, _NATIVE_PROJECTION_SOURCE_SHA256]
            and projection.get("schema_version") == _NATIVE_PROJECTION_SCHEMA
            and projection.get("producer_source_sha256") == _NATIVE_PROJECTION_SOURCE_SHA256)


def _native_intake(native_root: Path) -> dict:
    """Read sanitized projection, or legacy compressed input, without content."""
    projection_path = native_root.parent / "native-projection.json"
    if projection_path.is_file():
        value = _json(projection_path)
        safe_value = value if isinstance(value, dict) else {}
        required = {"schema_version", "producer_source_sha256", "native_session_id",
                    "binding_cwd", "workspace_id", "relative_path", "compressed_sha256",
                    "compressed_bytes", "header_id", "header_version", "human_input_sha256_order"}
        bindings = [_json(native_root.parent / f"turn-{turn}" / "binding.json") for turn in (1, 2)]
        scope = _json(native_root.parent / "scope.json")
        source = _json(native_root.parent / "native-runtime-preflight.json")
        mount = source.get("workspace_mount") if isinstance(source, dict) else None
        binding_join = (all(isinstance(row, dict) for row in bindings)
                        and isinstance(scope, dict) and isinstance(mount, str)
                        and bindings[0].get("cwd") == bindings[1].get("cwd") == safe_value.get("binding_cwd")
                        and bindings[0].get("workspace_id") == bindings[1].get("workspace_id") == safe_value.get("workspace_id")
                        and safe_value.get("workspace_id") == scope.get("workspace_id")
                        and isinstance(safe_value.get("binding_cwd"), str)
                        and safe_value["binding_cwd"].startswith(mount.rstrip("/") + "/")
                        and bindings[0].get("native_session_id") == bindings[1].get("native_session_id") == safe_value.get("native_session_id"))
        expected_relative = (f"sessions/{_session_project_key(safe_value['binding_cwd'])}/"
                             f"{safe_value['native_session_id']}/session.v4.jsonl.zstd"
                             if isinstance(safe_value.get("binding_cwd"), str)
                             and isinstance(safe_value.get("native_session_id"), str) else None)
        valid = (isinstance(value, dict) and set(value) == required
                 and value.get("schema_version") == _NATIVE_PROJECTION_SCHEMA
                 and value.get("producer_source_sha256") == _NATIVE_PROJECTION_SOURCE_SHA256
                 and _native_source_receipt(native_root.parent)
                 and _native_projection_receipt(native_root.parent, safe_value)
                 and binding_join is True and value.get("relative_path") == expected_relative
                 and isinstance(value.get("native_session_id"), str) and bool(value["native_session_id"])
                 and isinstance(value.get("compressed_sha256"), str) and _HASH.fullmatch(value["compressed_sha256"])
                 and type(value.get("compressed_bytes")) is int and value["compressed_bytes"] > 0
                 and value.get("header_id") == value.get("native_session_id")
                 and type(value.get("header_version")) is int and value["header_version"] == 4
                 and isinstance(value.get("human_input_sha256_order"), list)
                 and len(value["human_input_sha256_order"]) == 2
                 and all(isinstance(item, str) and _HASH.fullmatch(item)
                         for item in value["human_input_sha256_order"]))
        return {"schema_confirmed": bool(valid), "candidate_count": 1,
                "candidates": [{"relative_path": "native-projection.json",
                                  "compressed_sha256": safe_value.get("compressed_sha256"),
                                  "compressed_bytes": safe_value.get("compressed_bytes"),
                                  "decompressed": True, "record_count": None,
                                  "first_record_keys": [], "header_valid": bool(valid),
                                  "header_identity_matches_binding": (safe_value.get("header_id") == safe_value.get("native_session_id")),
                                  "native_session_id": safe_value.get("native_session_id"),
                                  "user_message_record_count": len(safe_value.get("human_input_sha256_order", []))
                                      if isinstance(safe_value.get("human_input_sha256_order"), list) else 0,
                                  "native_input_hashes": safe_value.get("human_input_sha256_order", []),
                                  "malformed_record_count": 0, "projection_valid": bool(valid)}],
                "tool_available": None, "projection_valid": bool(valid)}
    files = sorted(native_root.rglob("session.v4.jsonl.zstd")) if native_root.is_dir() else []
    result = {"schema_confirmed": False,
              "candidate_count": len(files), "candidates": [], "tool_available": bool(shutil.which("zstd"))}
    for path in files:
        row = {"relative_path": str(path.relative_to(native_root)),
               "compressed_sha256": _sha(path.read_bytes()), "decompressed": False,
               "record_count": 0, "first_record_keys": [], "header_valid": False,
               "header_ids_match_directory": None, "user_message_record_count": 0,
               "native_input_hashes": [], "malformed_record_count": 0}
        if shutil.which("zstd"):
            try:
                proc = subprocess.run(["zstd", "-q", "-d", "-c", str(path)],
                                      check=True, capture_output=True, timeout=10)
                row["decompressed"] = True
                lines = proc.stdout.splitlines()
                row["record_count"] = len(lines)
                records = []
                for line in lines:
                    try:
                        records.append(json.loads(line))
                    except (UnicodeError, json.JSONDecodeError):
                        records.append(None)
                row["malformed_record_count"] = sum(record is None for record in records)
                first = records[0] if records else None
                if isinstance(first, dict):
                    row["first_record_keys"] = sorted(first.keys())
                required_header = {"type", "version", "id", "createdAt", "isSeeded", "delegationDepth"}
                allowed_header = required_header | {"cwd", "parentSession", "origin", "agentPreset"}
                row["header_valid"] = (isinstance(first, dict) and required_header <= set(first)
                                        and set(first) <= allowed_header and first.get("type") == "session"
                                        and type(first.get("version")) is int and first["version"] == 4
                                        and isinstance(first.get("id"), str) and bool(first["id"]))
                row["header_ids_match_directory"] = (
                    first.get("id") == path.parent.name if row["header_valid"] else False
                )
                for record in records[1:]:
                    if not isinstance(record, dict) or record.get("type") != "user/message":
                        continue
                    data = record.get("data")
                    if (not isinstance(data, dict) or not isinstance(data.get("source"), dict)
                            or data["source"].get("kind") != "user"):
                        continue
                    if not isinstance(data.get("content"), list):
                        row["native_input_hashes"].append("INVALID_CONTENT")
                        continue
                    text_parts = []
                    for part in data["content"]:
                        if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                            text_parts.append(part["text"])
                    row["native_input_hashes"].append(_sha("".join(text_parts).encode("utf-8")))
                row["user_message_record_count"] = len(row["native_input_hashes"])
            except (OSError, subprocess.SubprocessError):
                row["decompression_error"] = "zstd decompression failed"
        result["candidates"].append(row)
    return result


def _known_contract_checks(capture: Path, native: dict) -> list[str]:
    """Check only locally sourced contracts; never treats absence as zero."""
    failures: list[str] = []
    scope = _json(capture / "scope.json")
    clock = _json(capture / "batch-clock.json")
    expected_jobs = {"backtest_jobs", "data_sync_jobs", "factor_jobs", "market_session_sync_jobs",
                     "ml_prediction_runs", "ml_training_runs", "optimization_jobs",
                     "security_master_sync_jobs", "signal_producer_jobs", "research_tasks", "artifacts"}
    if (not isinstance(clock, dict) or clock.get("schema_version") != "byq-ordinary-capture-clock.v1"
            or type(clock.get("started_monotonic_ns")) is not int
            or type(clock.get("deadline_monotonic_ns")) is not int
            or clock.get("deadline_monotonic_ns") - clock.get("started_monotonic_ns") != 240_000_000_000
            or not isinstance(clock.get("boot_id"), str)
            or not isinstance(clock.get("started_utc"), str)):
        failures.append("batch-clock.json must preserve one Linux monotonic 240-second batch deadline")
    login_writes = _json(capture / "authorized-login-writes.json")
    if (not isinstance(login_writes, dict)
            or login_writes.get("schema_version") != "byq-ordinary-capture-authorized-login-writes.v1"
            or login_writes.get("durable_login_may_write_auth_sessions") is not True
            or login_writes.get("business_jobs_created_by_capture") is not False):
        failures.append("authorized login writes must be disclosed separately from business job effects")
    if (capture / "capture-stop.json").exists():
        failures.append("capture batch has a preserved STOP receipt")
    for action in ("preflight", "turn-1", "turn-2"):
        checkpoint = _json(capture / f"checkpoint-{action}-pass.json")
        if not isinstance(checkpoint, dict) or checkpoint.get("status") != "PASS":
            failures.append(f"capture batch checkpoint missing PASS: {action}")
    before_jobs, after_jobs = _json(capture / "jobs-before.json"), _json(capture / "jobs-after.json")
    if (not isinstance(before_jobs, dict) or not isinstance(after_jobs, dict)
            or set(before_jobs) != expected_jobs or set(after_jobs) != expected_jobs
            or any(type(v) is not int or v < 0 for v in before_jobs.values())
            or any(type(v) is not int or v < 0 for v in after_jobs.values())
            or before_jobs != after_jobs):
        failures.append("the fixed nine job tables plus research_tasks/artifacts must have exact unchanged counts")
    containers_before = _json(capture / "container-facts-preflight.json")
    containers_after = _json(capture / "container-facts-finish-final.json")
    if (not isinstance(containers_before, dict) or not isinstance(containers_after, dict)
            or containers_before != containers_after):
        failures.append("project/container identity and started_at must match at batch start and finish")
    required_scope = {"conversation_id", "runtime_session_id", "trace_id",
                      "workspace_id", "owner_principal", "actor_principal"}
    if not isinstance(scope, dict) or not required_scope <= set(scope):
        failures.append("scope.json must capture conversation/runtime/trace/workspace/principal request identity")
    elif any(not isinstance(scope[k], str) or not scope[k].strip() for k in required_scope):
        failures.append("scope.json contains missing or empty request identity")
    elif scope["owner_principal"] != scope["actor_principal"]:
        failures.append("ordinary user turn actor must match the owner principal")

    for turn in (1, 2):
        delivery = _json(capture / f"delivery-turn-{turn}.json")
        if (not isinstance(delivery, dict)
                or delivery.get("schema_version") != "public-answer-delivery-status.v1"
                or delivery.get("state") != "up_to_date"
                or any(type(delivery.get(key)) is not int or delivery[key] != 0
                       for key in ("pending_events", "exhausted_events", "rejected_events"))):
            failures.append(f"turn {turn} answer delivery is not up_to_date with zero pending/exhausted/rejected events")

    conversation = _json(capture / "conversation.json")
    if not isinstance(conversation, dict) or not isinstance(conversation.get("messages"), list):
        failures.append("conversation.json must contain the actual Product API messages array")
    else:
        rows = conversation["messages"]
        if any(not isinstance(m, dict) for m in rows):
            failures.append("Product API message row is not an object")
        else:
            ids = [m.get("message_id") for m in rows]
            sequences = [m.get("sequence") for m in rows]
            if any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
                failures.append("Product API messages require unique nonempty message_id values")
            if any(type(x) is not int or x < 1 for x in sequences) or len(sequences) != len(set(sequences)):
                failures.append("Product API messages require unique positive integer sequence values")

    trace = _json(capture / "trace.json")
    if not isinstance(trace, list):
        failures.append("trace.json must be the actual SSE extracted WorkflowTrace event array, not a wrapper")
        trace = []
    if any(not isinstance(e, dict) for e in trace):
        failures.append("normalized trace contains a non-object event")
    else:
        for e in trace:
            if (set(e) != {"trace_id", "session_id", "sequence", "timestamp", "kind", "source", "payload"}
                    or not isinstance(e.get("session_id"), str) or not isinstance(e.get("trace_id"), str)
                    or type(e.get("sequence")) is not int or not isinstance(e.get("payload"), dict)):
                failures.append("normalized WorkflowTrace event is missing identity, sequence, or payload")
                break
            if e.get("source") not in {"dsh", "runtime-adapter", "byq-domain"}:
                failures.append("normalized WorkflowTrace event has unsupported source")
                break
        seqs = [e.get("sequence") for e in trace if isinstance(e, dict)]
        if len(seqs) != len(trace) or any(type(x) is not int or x < 1 for x in seqs) or len(seqs) != len(set(seqs)):
            failures.append("normalized trace requires unique positive integer event sequence values")
        if isinstance(scope, dict) and any(e.get("session_id") != scope.get("conversation_id")
                                           or e.get("trace_id") != scope.get("trace_id") for e in trace if isinstance(e, dict)):
            failures.append("Product API trace contains a foreign conversation or trace identity")

    # The production binding is one atomically overwritten file per public
    # session. Require two raw snapshots captured at each root's termination;
    # never accept a reconstructed list of turns.
    snapshots = capture / "binding-snapshots"
    snapshot_files = sorted(snapshots.glob("*.json")) if snapshots.is_dir() else []
    if len(snapshot_files) != 2:
        failures.append("need exactly two raw byq-acp-bindings/<session>.json terminal-time snapshots")
    else:
        bindings = [_json(p) for p in snapshot_files]
        fields = {"schema_version", "session_id", "trace_id", "owner_principal",
                  "workspace_id", "root_run_id", "native_session_id", "runtime_generation",
                  "settlement_receipt"}
        if any(not isinstance(b, dict) or not fields <= set(b) for b in bindings):
            failures.append("binding snapshots must preserve actual byq-acp-root-binding.v1 fields")
        else:
            if any(b.get("schema_version") != "byq-acp-root-binding.v1" for b in bindings):
                failures.append("binding snapshot schema_version is not byq-acp-root-binding.v1")
            if len({b.get("root_run_id") for b in bindings}) != 2:
                failures.append("binding snapshots must show two distinct roots")
            if len({b.get("native_session_id") for b in bindings}) != 1:
                failures.append("ordinary uninterrupted turns must bind to one native session")
            if len({b.get("runtime_generation") for b in bindings}) != 2:
                failures.append("the two roots must have distinct runtime_generation values")
            for binding in bindings:
                receipt = binding.get("settlement_receipt")
                if (not isinstance(receipt, dict)
                        or set(receipt) != {"schema_version", "root_run_id", "sequence", "event_sha256"}
                        or receipt.get("schema_version") != "agent-run-lifecycle-receipt.v1"
                        or receipt.get("root_run_id") != binding.get("root_run_id")
                        or type(receipt.get("sequence")) is not int or receipt.get("sequence", 0) <= 0
                        or not isinstance(receipt.get("event_sha256"), str)
                        or not _HASH.fullmatch(receipt["event_sha256"])):
                    failures.append("binding lacks the exact persisted settlement receipt")
            for key in ("session_id", "trace_id", "owner_principal", "workspace_id"):
                if len({b.get(key) for b in bindings}) != 1 or (isinstance(scope, dict) and bindings[0].get(key) != scope.get(key if key != "session_id" else "runtime_session_id")):
                    failures.append(f"binding identity does not match request scope: {key}")

    terminal_response = _json(capture / "terminal.json")
    terminal = terminal_response.get("roots") if isinstance(terminal_response, dict) else None
    if (not isinstance(terminal_response, dict)
            or terminal_response.get("schema_version") != "byq-business-root-status.v1"
            or not isinstance(terminal, list) or len(terminal) != 2):
        failures.append("terminal.json must be the scoped read-only byq-business-root-status.v1 SQL projection with two roots")
    ack_projection = _json(capture / "gateway-ack-observed.json")
    ack_rows = (ack_projection.get("events") if isinstance(ack_projection, dict)
                and ack_projection.get("schema_version") == "byq-gateway-terminal-ack-observed-set.v1"
                else None)
    if not isinstance(ack_rows, list):
        failures.append("gateway-ack-observed.json must contain sanitized observed Gateway ACK log tuples")
        ack_rows = []
    ack_lines = _json(capture / "gateway-ack-original-matches.json")
    line_rows = ack_lines.get("lines") if isinstance(ack_lines, dict) else None
    if (not isinstance(ack_lines, dict)
            or ack_lines.get("schema_version") != "byq-gateway-terminal-ack-lines.v1"
            or not isinstance(line_rows, list) or len(line_rows) != len(ack_rows)):
        failures.append("Gateway ACK tuple records must retain their bounded original marker lines")
    else:
        marker = "terminal_ack_observed "
        for index, line in enumerate(line_rows):
            matched = line.get("matched_line") if isinstance(line, dict) else None
            if (not isinstance(matched, str) or not matched.startswith("terminal_ack_observed ")
                    or type(line.get("line_bytes")) is not int
                    or line.get("line_bytes") != len(matched.encode("utf-8"))
                    or not isinstance(line.get("line_sha256"), str)
                    or _sha(matched.encode("utf-8")) != line.get("line_sha256")):
                failures.append("Gateway ACK original marker line does not match its saved hash/length")
                break
            try:
                parsed = json.loads(matched[len(marker):])
            except json.JSONDecodeError:
                failures.append("Gateway ACK original marker line does not contain valid tuple JSON")
                break
            if parsed != ack_rows[index]:
                failures.append("Gateway ACK original marker line tuple differs from the saved observation")
                break
    if isinstance(terminal, list):
        terminal_by_root = {r.get("root_run_id"): r for r in terminal if isinstance(r, dict)}
        binding_files = sorted((capture / "binding-snapshots").glob("*.json")) if (capture / "binding-snapshots").is_dir() else []
        binding_rows = [_json(p) for p in binding_files]
        persisted_by_root = {b.get("root_run_id"): b.get("settlement_receipt")
                       for b in binding_rows if isinstance(b, dict)}
        observed_by_root: dict[str, list[dict]] = {}
        for row in ack_rows:
            if isinstance(row, dict) and isinstance(row.get("root_run_id"), str):
                observed_by_root.setdefault(row["root_run_id"], []).append(row)
        if len(terminal_by_root) != 2 or len(persisted_by_root) != 2 or set(terminal_by_root) != set(persisted_by_root):
            failures.append("Backend terminal roots and persisted binding receipt roots must match one-to-one")
        if set(terminal_by_root) != set(observed_by_root):
            failures.append("Backend terminal roots and Gateway observed ACK log roots must match one-to-one")
        for root, row in terminal_by_root.items():
            receipt = persisted_by_root.get(root)
            if not isinstance(root, str) or not _ROOT.fullmatch(root):
                failures.append("Backend terminal has invalid root_run_id")
                continue
            digest, seq = row.get("terminal_event_sha256"), row.get("terminal_sequence")
            if row.get("status") != "completed" or row.get("authority_status") != "closed":
                failures.append(f"root {root} is not completed/closed")
            if row.get("terminal_unknown_claim_count") != 0:
                failures.append(f"root {root} has unknown terminal claims")
            if type(seq) is not int or seq <= 0 or not isinstance(digest, str) or not _HASH.fullmatch(digest):
                failures.append(f"root {root} has missing/invalid Backend terminal sequence/hash")
            if not isinstance(receipt, dict) or set(receipt) != {"schema_version", "root_run_id", "sequence", "event_sha256"}:
                failures.append(f"root {root} lacks the exact persisted settlement receipt fields")
            elif (receipt.get("schema_version") != "agent-run-lifecycle-receipt.v1"
                  or receipt.get("root_run_id") != root or type(receipt.get("sequence")) is not int
                  or receipt.get("sequence") != seq or receipt.get("event_sha256") != digest):
                failures.append(f"root {root} persisted settlement receipt does not match Backend terminal")
            observed = observed_by_root.get(root, [])
            binding = next((b for b in binding_rows if isinstance(b, dict) and b.get("root_run_id") == root), {})
            expected_ack = {
                "schema_version": "byq-gateway-terminal-ack-observed.v1",
                "event": "terminal_ack_observed", "root_run_id": root,
                "session_id": binding.get("session_id"), "boot_id": binding.get("previous_boot_id"),
                "trace_id": binding.get("trace_id"), "sequence": seq,
                "event_sha256": digest, "outcome": "completed",
            }
            if not observed or any(row != expected_ack for row in observed):
                failures.append(f"root {root} lacks a matching observed Gateway terminal ACK tuple")

    # Reconstruct two completed roots and their saved public answer rows from
    # normalized trace deltas; Product messages intentionally have no root id.
    if isinstance(trace, list):
        roots: list[dict] = []
        current = None
        for event in trace:
            if not isinstance(event, dict):
                continue
            kind, payload = event.get("kind"), event.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            if kind == "session.started":
                if current is not None:
                    failures.append("new root started before the prior root terminated")
                rid = payload.get("run_id")
                current = {"root": rid, "deltas": {}}
            elif kind == "agent.output.delta" and current is not None:
                if payload.get("schema_version") != "workflow-answer.v1" or payload.get("channel") != "answer" or not isinstance(payload.get("delta"), str):
                    failures.append("trace answer delta does not match workflow-answer.v1/channel=answer")
                else:
                    current["deltas"][event.get("sequence")] = payload["delta"]
            elif kind == "session.result" and current is not None and payload.get("run_id") == current.get("root"):
                roots.append(current)
                current = None
            elif kind in {"session.failed", "session.cancelled", "session.closed", "session.result.discarded"}:
                failures.append(f"ordinary two-turn slice contains terminal event {kind}")
                current = None
        if current is not None:
            failures.append("last root has no terminal result")
        if len(roots) != 2 or any(not isinstance(r["root"], str) or not _ROOT.fullmatch(r["root"]) for r in roots):
            failures.append("trace must show exactly two completed roots with valid run_id")
        if len({r["root"] for r in roots}) != 2:
            failures.append("ordinary turns must use distinct roots")
        conv = _json(capture / "conversation.json")
        public_conversation = conv.get("conversation") if isinstance(conv, dict) else None
        messages = conv.get("messages", []) if isinstance(conv, dict) else []
        if not isinstance(public_conversation, dict):
            failures.append("conversation.json must be raw Product API session response with conversation object")
        elif isinstance(scope, dict) and (public_conversation.get("session_id") != scope.get("conversation_id")
                                           or public_conversation.get("trace_id") != scope.get("trace_id")):
            failures.append("Product API conversation identity differs from request scope")
        user_rows = [m for m in messages if isinstance(m, dict) and m.get("role") == "user"]
        if len(user_rows) != 2 or any(not isinstance(m.get("content"), str) for m in user_rows):
            failures.append("ordinary capture must contain exactly two Product API user messages")
        if len(roots) == 2:
            assistant_rows = [m for m in messages if isinstance(m, dict) and m.get("role") == "assistant"]
            if len({m.get("message_id") for m in assistant_rows}) != len(assistant_rows):
                failures.append("duplicate persisted assistant message_id")
            all_deltas = {seq: delta for root in roots for seq, delta in root["deltas"].items()}
            workflow_sequences = [m.get("workflow_sequence") for m in assistant_rows]
            if (any(type(seq) is not int or seq not in all_deltas for seq in workflow_sequences)
                    or len(workflow_sequences) != len(set(workflow_sequences))
                    or set(workflow_sequences) != set(all_deltas)):
                failures.append("persisted assistant workflow_sequence set differs from all trace answer deltas")
            for message in assistant_rows:
                seq = message.get("workflow_sequence")
                if type(seq) is int and seq in all_deltas and message.get("content") != all_deltas[seq].strip():
                    failures.append("persisted assistant content differs from its WorkflowTrace delta")
            for root in roots:
                found = [m for m in messages if isinstance(m, dict) and m.get("role") == "assistant"
                         and type(m.get("workflow_sequence")) is int and m["workflow_sequence"] in root["deltas"]]
                if not found:
                    failures.append(f"root {root['root']} has no persisted assistant answer delta")
                for m in found:
                    if m.get("content") != root["deltas"][m["workflow_sequence"]].strip():
                        failures.append(f"persisted answer content differs from trace delta for root {root['root']}")
            if (all(isinstance(m, dict) and type(m.get("sequence")) is int and m["sequence"] > 0
                    for m in messages)
                    and all(isinstance(m, dict) for m in messages)):
                ordered_messages = sorted(messages, key=lambda m: m["sequence"])
                root1_sequences = set(roots[0]["deltas"])
                root2_sequences = set(roots[1]["deltas"])
                roles = [m.get("role") for m in ordered_messages]
                split = next((i for i, m in enumerate(ordered_messages) if m.get("role") == "user"), None)
                second_user = next((i for i, m in enumerate(ordered_messages)
                                    if i > (split if split is not None else -1) and m.get("role") == "user"), None)
                ordered_answers = (
                    ordered_messages[1:second_user] if split == 0 and second_user is not None else []
                )
                trailing_answers = ordered_messages[second_user + 1:] if second_user is not None else []
                if (roles != ["user"] + ["assistant"] * len(ordered_answers) + ["user"] + ["assistant"] * len(trailing_answers)
                        or not ordered_answers or not trailing_answers
                        or any(m.get("role") != "assistant"
                               or type(m.get("workflow_sequence")) is not int
                               or m.get("workflow_sequence") not in root1_sequences for m in ordered_answers)
                        or any(m.get("role") != "assistant"
                               or type(m.get("workflow_sequence")) is not int
                               or m.get("workflow_sequence") not in root2_sequences for m in trailing_answers)):
                    failures.append("Product message sequence must be user1, all root1 answers, user2, all root2 answers")
            public_hashes = [_sha(m["content"].encode("utf-8")) for m in user_rows if isinstance(m.get("content"), str)]
            native_hashes = native["candidates"][0].get("native_input_hashes", []) if native["candidate_count"] == 1 else []
            if len(native_hashes) != 2 or native_hashes != public_hashes:
                failures.append("native human input hashes/order differ from the two persisted Product inputs")
            binding_paths = sorted((capture / "binding-snapshots").glob("*.json")) if (capture / "binding-snapshots").is_dir() else []
            snapshot_rows = [_json(p) for p in binding_paths]
            if all(isinstance(b, dict) for b in snapshot_rows):
                if {b.get("root_run_id") for b in snapshot_rows} != {r["root"] for r in roots}:
                    failures.append("terminal binding snapshots do not bind exactly the two trace roots")
                if native["candidate_count"] == 1 and any(
                    b.get("native_session_id") != native["candidates"][0].get(
                        "native_session_id", Path(native["candidates"][0]["relative_path"]).parent.name)
                    for b in snapshot_rows
                ):
                    failures.append("native directory id differs from persisted binding native_session_id")
        journal_dir = capture / "journals"
        journal_files = sorted(journal_dir.glob("product-turn-provider-request-*.jsonl")) if journal_dir.is_dir() else []
        expected_roots = {r["root"] for r in roots}
        binding_files = sorted((capture / "binding-snapshots").glob("*.json")) if (capture / "binding-snapshots").is_dir() else []
        bindings_by_root = {b.get("root_run_id"): b for b in (_json(p) for p in binding_files) if isinstance(b, dict)}
        observed_roots: set[str] = set()
        for path in journal_files:
            match = re.fullmatch(r"product-turn-provider-request-([0-9a-f]{32})\.jsonl", path.name)
            if match is None:
                failures.append("provider journal filename has invalid root id")
                continue
            rid = match.group(1)
            observed_roots.add(rid)
            rows = []
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except (UnicodeError, json.JSONDecodeError):
                    failures.append(f"provider journal {rid} contains malformed JSONL")
                    continue
                expected_request_id = "product-turn-" + str(bindings_by_root.get(rid, {}).get("runtime_generation", ""))
                base_fields = {"schema_version", "request_id", "phase", "role", "call", "attempt",
                               "input_bytes", "declared_max_output_tokens", "tool_payload_bytes",
                               "admitted", "reason", "at_ms"}
                completion_fields = {"status", "forwarded", "elapsed_ms", "completed_at_ms",
                                     "actual_input_tokens", "actual_cache_read_tokens",
                                     "actual_output_tokens", "usage_source"}
                if (not isinstance(item, dict)
                        or item.get("schema_version") != "continuation-request-gate.v1"
                        or item.get("request_id") != expected_request_id
                        or not base_fields <= set(item)
                        or (item.get("phase") == "completed" and not (base_fields | completion_fields) <= set(item))):
                    failures.append(f"provider journal {rid} contains invalid row schema")
                    continue
                rows.append(item)
            inflight = peak = 0
            pending: dict[tuple, int] = {}
            max_attempt = 0
            seen_keys: set[tuple] = set()
            admitted_count = completed_count = 0
            for row in rows:
                phase = row.get("phase")
                attempt, call = row.get("attempt"), row.get("call")
                if type(attempt) is not int or attempt < 1 or type(call) is not int or call < 1:
                    failures.append(f"provider journal {rid} has missing/invalid attempt or call")
                    continue
                if (type(row.get("input_bytes")) is not int or row["input_bytes"] < 0
                        or type(row.get("declared_max_output_tokens")) is not int or row["declared_max_output_tokens"] < 0
                        or type(row.get("tool_payload_bytes")) is not int or row["tool_payload_bytes"] < 0
                        or type(row.get("at_ms")) is not int or row["at_ms"] < 0
                        or row.get("role") not in {"root", "subagent"}
                        or not isinstance(row.get("reason"), str)):
                    failures.append(f"provider journal {rid} has invalid continuation receipt values")
                    continue
                max_attempt = max(max_attempt, attempt)
                key = (call, attempt)
                if phase == "admitted":
                    if row.get("admitted") is not True or key in pending or key in seen_keys:
                        failures.append(f"provider journal {rid} has invalid or duplicate admission")
                    seen_keys.add(key)
                    if call != admitted_count + 1 or attempt != admitted_count + 1:
                        failures.append(f"provider journal {rid} call/attempt counters are not sequential")
                    pending[key] = 1
                    admitted_count += 1
                    inflight += 1
                    peak = max(peak, inflight)
                elif phase == "completed":
                    completed_count += 1
                    if key not in pending:
                        failures.append(f"provider journal {rid} has out-of-order/duplicate completion")
                    else:
                        del pending[key]
                        inflight -= 1
                    if row.get("status") != 200 or row.get("forwarded") is not True:
                        failures.append(f"provider journal {rid} request was not completed HTTP 200/forwarded")
                    if (type(row.get("elapsed_ms")) is not int or row["elapsed_ms"] < 0
                            or type(row.get("completed_at_ms")) is not int or row["completed_at_ms"] < 0
                            or row.get("usage_source") not in {"provider_response", "unknown"}
                            or any(type(row.get(field)) is not int and row.get(field) != "unknown"
                                   for field in ("actual_input_tokens", "actual_cache_read_tokens", "actual_output_tokens"))):
                        failures.append(f"provider journal {rid} has invalid completed usage receipt")
                else:
                    failures.append(f"provider journal {rid} has rejected/aborted/unknown phase {phase}")
            if pending or inflight:
                failures.append(f"provider journal {rid} has admitted requests without completion")
            if admitted_count < 1 or completed_count < 1:
                failures.append(f"provider journal {rid} must contain at least one admitted/completed request pair")
            if max_attempt > 16 or peak > 1:
                failures.append(f"provider journal {rid} exceeded attempts=16 or concurrency=1")
            if any(row.get("call", 0) > 16 for row in rows if type(row.get("call")) is int):
                failures.append(f"provider journal {rid} exceeded call limit 16")
        if observed_roots != expected_roots:
            failures.append("provider journal file roots do not equal the two actual trace roots")

    return failures


def inspect(capture: Path) -> dict:
    native = _native_intake(capture / "native")
    failures = _known_contract_checks(capture, native)
    if native["candidate_count"] != 1:
        failures.append("ordinary two-turn capture must contain exactly one native compressed source or validated projection")
    if native["candidate_count"] == 1:
        row = native["candidates"][0]
        if row.get("projection_valid") is False:
            failures.append("native session input projection does not match its pinned schema/source")
        if not row["decompressed"]:
            failures.append("native compressed source/projection was not successfully decoded")
        if row["malformed_record_count"]:
            failures.append("native v4 session contains malformed JSONL records")
        if not row["header_valid"]:
            failures.append("native v4 session header does not match the official header schema")
        if row.get("header_identity_matches_binding", row.get("header_ids_match_directory")) is not True:
            failures.append("native header.id does not match the binding identity, or header shape is unknown")
        if row["user_message_record_count"] != 2:
            failures.append("native user/message data.source.kind=user count is not exactly two, or shape is unknown")
    return {"status": "FAIL" if failures else "PASS",
            "failures": failures, "native_intake": native,
            "native_source_identities": {"store": _NATIVE_STORE_SOURCE_SHA256,
                "header": _NATIVE_HEADER_SOURCE_SHA256, "base_profile": _NATIVE_BASE_PROFILE_SOURCE_SHA256,
                "product_profile": _PRODUCT_PROFILE_SHA256,
                "product_profile_identity": _PRODUCT_PROFILE_IDENTITY_SHA256}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    args = parser.parse_args()
    result = inspect(args.capture)
    print(json.dumps(result, sort_keys=True))
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
