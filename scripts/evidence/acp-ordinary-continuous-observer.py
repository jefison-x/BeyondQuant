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
_NATIVE_SCHEMA_CONFIRMED = True
_NATIVE_SOURCE_SHA256 = "5d665a976a9d6fdeca964ca487b6adea187962b256ef47c2fcf1fe7656222aab"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _native_intake(native_root: Path) -> dict:
    """Decompress native candidates and report shape metadata without content."""
    files = sorted(native_root.rglob("session.v4.jsonl.zstd")) if native_root.is_dir() else []
    result = {"schema_confirmed": _NATIVE_SCHEMA_CONFIRMED,
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
    required_scope = {"conversation_id", "runtime_session_id", "trace_id",
                      "workspace_id", "owner_principal", "actor_principal"}
    if not isinstance(scope, dict) or not required_scope <= set(scope):
        failures.append("scope.json must capture conversation/runtime/trace/workspace/principal request identity")
    elif any(not isinstance(scope[k], str) or not scope[k].strip() for k in required_scope):
        failures.append("scope.json contains missing or empty request identity")
    elif scope["owner_principal"] != scope["actor_principal"]:
        failures.append("ordinary user turn actor must match the owner principal")

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
                    failures.append("binding lacks the exact persisted terminal ACK receipt")
            for key in ("session_id", "trace_id", "owner_principal", "workspace_id"):
                if len({b.get(key) for b in bindings}) != 1 or (isinstance(scope, dict) and bindings[0].get(key) != scope.get(key if key != "session_id" else "runtime_session_id")):
                    failures.append(f"binding identity does not match request scope: {key}")

    terminal_response = _json(capture / "terminal.json")
    terminal = terminal_response.get("roots") if isinstance(terminal_response, dict) else None
    if (not isinstance(terminal_response, dict)
            or terminal_response.get("schema_version") != "byq-business-root-status.v1"
            or not isinstance(terminal, list) or len(terminal) != 2):
        failures.append("terminal.json must be the raw byq-business-root-status.v1 response with two roots")
    if isinstance(terminal, list):
        terminal_by_root = {r.get("root_run_id"): r for r in terminal if isinstance(r, dict)}
        binding_files = sorted((capture / "binding-snapshots").glob("*.json")) if (capture / "binding-snapshots").is_dir() else []
        binding_rows = [_json(p) for p in binding_files]
        ack_by_root = {b.get("root_run_id"): b.get("settlement_receipt")
                       for b in binding_rows if isinstance(b, dict)}
        if len(terminal_by_root) != 2 or len(ack_by_root) != 2 or set(terminal_by_root) != set(ack_by_root):
            failures.append("Backend terminal roots and exact ACK roots must match one-to-one")
        for root, row in terminal_by_root.items():
            ack = ack_by_root.get(root)
            if not isinstance(root, str) or not _ROOT.fullmatch(root):
                failures.append("Backend terminal has invalid root_run_id")
                continue
            digest, seq = row.get("terminal_event_sha256"), row.get("terminal_sequence")
            if row.get("status") != "completed" or row.get("authority_status") != "closed":
                failures.append(f"root {root} is not completed/closed")
            if type(seq) is not int or seq <= 0 or not isinstance(digest, str) or not _HASH.fullmatch(digest):
                failures.append(f"root {root} has missing/invalid Backend terminal sequence/hash")
            if not isinstance(ack, dict) or set(ack) != {"schema_version", "root_run_id", "sequence", "event_sha256"}:
                failures.append(f"root {root} lacks the exact ACK receipt fields")
            elif (ack.get("schema_version") != "agent-run-lifecycle-receipt.v1"
                  or ack.get("root_run_id") != root or type(ack.get("sequence")) is not int
                  or ack.get("sequence") != seq or ack.get("event_sha256") != digest):
                failures.append(f"root {root} ACK does not exactly match Backend terminal")

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
                    b.get("native_session_id") != Path(native["candidates"][0]["relative_path"]).parent.name
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
        failures.append("ordinary two-turn capture must contain exactly one saved session.v4.jsonl.zstd")
    if native["candidate_count"] == 1:
        row = native["candidates"][0]
        if not row["decompressed"]:
            failures.append("native session did not decompress with zstd")
        if row["malformed_record_count"]:
            failures.append("native v4 session contains malformed JSONL records")
        if not row["header_valid"]:
            failures.append("native v4 session header does not match the official header schema")
        if row["header_ids_match_directory"] is not True:
            failures.append("native header.id does not match its session directory, or header shape is unknown")
        if row["user_message_record_count"] != 2:
            failures.append("native user/message data.source.kind=user count is not exactly two, or shape is unknown")
    return {"status": "FAIL" if failures else "PASS",
            "failures": failures, "native_intake": native,
            "native_schema_source_sha256": _NATIVE_SOURCE_SHA256}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.capture), sort_keys=True))
    result = inspect(args.capture)
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
