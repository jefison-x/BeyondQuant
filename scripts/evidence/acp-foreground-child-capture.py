#!/usr/bin/env python3
"""One-off, bounded observer for one foreground ACP delegated child.

The human creates the conversation and sends its single prompt through the
normal browser/Gateway flow. This script only reads Gateway, Backend and the
already running ACP containers. It never sends a model prompt or writes a Job.
Normal admin login writes auth_sessions; SSE reading may renew a consumer lease.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
_CAPTURE = Path(__file__).with_name("acp-ordinary-continuous-capture.py")
_SCOPE = Path(__file__).with_name("acp-child-scope-read.py")
_CLEANUP_CHILD = Path(
    "/home/jefison/.codex/worktrees/acp-artifact-summary-read/BeyondQuant/"
    ".ci-artifacts/summary-read-fix-20261012/cleanup-receipt-20261013/cleanup_receipt_child.py"
)
_CLEANUP_CHILD_SHA256 = "2aca17fa12636c25b64de5f1b792d44518a871f435f8b14d6d94f95a8ff5f4d5"
_DELEGATE_PACKAGE_SHA256 = "6eef1eabfac0b93fc49b4f51df855cd45aa83ec29db9ea22905814b0c27ad018"
_DELEGATE_SOURCE_SHA256 = "26a1e804aab4c6f9cb53a670c63b817fc8d9409569e6d68eda6fda33b966a840"
_PRODUCT_RUNNER_SOURCE_SHA256 = "abc8992083bca202d4e66354f254fb1ea095cd409b62fcbdc2d3b2e6b6912f31"
_OUTCOME = "byq-acp-foreground-child-observer.v1"
_BATCH_SECONDS = 240
_NATIVE_READER_SHA256 = "61f1942f8e24d8e44ae30ae8d5cb480fed66401c001f83f9a3d7da8661e5ea7e"
_ROOT_CALLS = ("byq_agent_run_start", "byq_delegate_market_research")
_CHILD_CALLS = (
    "byq_agent_run_start", "byq_agent_authorize", "byq_market_session_context", "byq_agent_audit",
)
_LIMITS = {
    "max_provider_calls": 16, "max_attempts": 16, "max_concurrent": 1,
    "max_input_bytes": 262144, "max_total_input_bytes": 4194304,
    "max_output_tokens": 8192, "max_total_output_tokens": 131072,
    "max_tool_payload_bytes": 131072, "max_total_tool_payload_bytes": 1048576,
    "max_tool_calls": 16, "deadline_ms": 180000,
}


class Stop(RuntimeError):
    pass


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Stop("required_existing_reader_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ordinary = _load(_CAPTURE, "ordinary_capture_helpers")
scope_reader = _load(_SCOPE, "acp_child_scope_reader")
from packages.contracts.product_turn_request import PRODUCT_TURN_PROFILE_SHA256


def _delegate_source_preflight(args, out: Path, *, deadline: float) -> None:
    code = r'''import hashlib,json,os,pathlib
root=pathlib.Path("/opt/dsh-runtime/packages/subagent/tool-subagent")
manifest=json.loads((root/"package.json").read_text())
source=(root/"lib/index.js").read_bytes()
runner=pathlib.Path("/opt/byq/acp_product_runner/server.py")
runner_sha=hashlib.sha256(runner.read_bytes()).hexdigest()
print(json.dumps({"schema_version":"byq-dsh-delegate-source-preflight.v1",
 "package_name":manifest.get("name"),"package_version":manifest.get("version"),
 "package_sha256":hashlib.sha256((root/"package.json").read_bytes()).hexdigest(),
 "source_sha256":hashlib.sha256(source).hexdigest(),
 "product_runner_source_path":str(runner),"product_runner_source_sha256":runner_sha,
 "reader_uid":os.geteuid(),"reader_gid":os.getegid()},sort_keys=True,separators=(",",":")))'''
    argv = ["docker", "exec", "--user", "10002:10002", "--workdir", "/app", "-i", args.runner_id,
            "python3", "-I", "-c", code]
    raw = ordinary._command(out, "delegate-source-preflight", argv, timeout=15, deadline=deadline)
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise Stop("delegate_source_preflight_json_invalid") from exc
    command = ordinary._json_read(out / "commands/delegate-source-preflight.json")
    if (not isinstance(command, dict) or command.get("returncode") != 0 or command.get("argv") != argv
            or command.get("stdout_sha256") != hashlib.sha256(raw).hexdigest()
            or not isinstance(value, dict) or set(value) != {"schema_version", "package_name", "package_version",
                "package_sha256", "source_sha256", "product_runner_source_path",
                "product_runner_source_sha256", "reader_uid", "reader_gid"}
            or value.get("schema_version") != "byq-dsh-delegate-source-preflight.v1"
            or value.get("package_name") != "@deepseek-ai/dsh-tool-subagent"
            or value.get("package_version") != "0.2.0-rc.2"
            or value.get("package_sha256") != _DELEGATE_PACKAGE_SHA256
            or value.get("source_sha256") != _DELEGATE_SOURCE_SHA256
            or value.get("product_runner_source_path") != "/opt/byq/acp_product_runner/server.py"
            or value.get("product_runner_source_sha256") != _PRODUCT_RUNNER_SOURCE_SHA256
            or value.get("reader_uid") != 10002 or value.get("reader_gid") != 10002):
        raise Stop("delegate_source_preflight_mismatch")
    ordinary._json_write(out / "delegate-source-preflight.json", value)


def _read_tool_guard(out: Path, adapter_id: str, cwd: str, root: str, *, deadline: float) -> dict:
    code = r'''import hashlib,json,os,pathlib,stat,sys
p=pathlib.Path(sys.argv[1]) / ("product-turn-tool-guard-"+sys.argv[2]+".jsonl")
try:
 st=os.lstat(p)
 if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode) or st.st_nlink!=1 or st.st_size<=0 or st.st_size>1048576: raise SystemExit("tool_guard_file_invalid")
 fd=os.open(p,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)); before=os.fstat(fd)
 with os.fdopen(fd,"rb") as f: raw=f.read(1048577)
 after=os.lstat(p)
 if len(raw)!=st.st_size or (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns): raise SystemExit("tool_guard_file_changed")
 rows=[json.loads(x) for x in raw.decode("utf-8").splitlines()]
 print(json.dumps({"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"rows":rows},separators=(",",":")))
except SystemExit: raise
except Exception: raise SystemExit("tool_guard_read_invalid")'''
    raw = ordinary._command(
        out, "product-tool-guard",
        ["docker", "exec", "--workdir", "/app", "-i", adapter_id,
         "python3", "-I", "-c", code, cwd, root],
        timeout=15, deadline=deadline)
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise Stop("tool_guard_json_invalid") from exc
    if not isinstance(value, dict) or set(value) != {"sha256", "bytes", "rows"}:
        raise Stop("tool_guard_projection_invalid")
    rows = value["rows"]
    if (not isinstance(rows, list) or not rows or not isinstance(rows[0], dict)
            or rows[0] != {"schema_version": "product-turn-tool-guard.v1",
                "execution_profile": {"profile_id": "product-turn.v1", "profile_version": 1,
                                       "profile_sha256": PRODUCT_TURN_PROFILE_SHA256},
                "request_limits": _LIMITS, "ready": True}):
        raise Stop("tool_guard_header_invalid")
    calls = rows[1:]
    if (len(calls) > 16 or any(not isinstance(row, dict)
            or set(row) != {"phase", "call", "tool_name"}
            or row.get("phase") != "tool" or type(row.get("call")) is not int
            or row["call"] != i or not isinstance(row.get("tool_name"), str)
            for i, row in enumerate(calls, 1))):
        raise Stop("tool_guard_calls_invalid")
    required = set(_ROOT_CALLS + _CHILD_CALLS)
    names = [row["tool_name"].removeprefix("mcp__byq__") for row in calls]
    if not required.issubset(set(names)):
        raise Stop("tool_guard_required_calls_missing")
    value["call_count"] = len(calls)
    value["tool_names"] = names
    return value


def _validate_provider_journal(raw: bytes, root: str, generation: str) -> dict:
    try:
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    except (UnicodeError, ValueError) as exc:
        raise Stop("provider_journal_invalid_jsonl") from exc
    if not rows:
        raise Stop("provider_journal_empty")
    pending: set[tuple[int, int]] = set()
    seen: set[tuple[int, int]] = set()
    admitted = completed = peak = inflight = 0
    total_input = total_declared_output = total_tool_payload = 0
    first_admitted_ms = last_completed_ms = previous_admission_ms = None
    expected_request = "product-turn-" + generation
    base = {"schema_version", "request_id", "phase", "role", "call", "attempt", "input_bytes",
            "declared_max_output_tokens", "tool_payload_bytes", "admitted", "reason", "at_ms"}
    completion = {"status", "forwarded", "elapsed_ms", "completed_at_ms", "actual_input_tokens",
                  "actual_cache_read_tokens", "actual_output_tokens", "usage_source"}
    for row in rows:
        if (not isinstance(row, dict) or row.get("schema_version") != "continuation-request-gate.v1"
                or row.get("request_id") != expected_request or not base.issubset(row)):
            raise Stop("provider_journal_schema_invalid")
        attempt, call = row.get("attempt"), row.get("call")
        if (type(attempt) is not int or attempt < 1 or type(call) is not int or call < 1
                or type(row.get("input_bytes")) is not int or row["input_bytes"] < 0
                or type(row.get("declared_max_output_tokens")) is not int
                or row["declared_max_output_tokens"] < 1
                or type(row.get("tool_payload_bytes")) is not int
                or row["tool_payload_bytes"] < 0
                or type(row.get("at_ms")) is not int
                or row.get("role") not in ("root", "subagent")
                or not isinstance(row.get("reason"), str)):
            raise Stop("provider_journal_fields_invalid")
        key = (call, attempt)
        if row["phase"] == "admitted":
            if (row.get("admitted") is not True or row.get("reason") != "within_request_budget"
                    or key in seen or call != admitted + 1 or attempt != admitted + 1
                    or admitted >= _LIMITS["max_provider_calls"]
                    or admitted >= _LIMITS["max_attempts"]
                    or (previous_admission_ms is not None and row["at_ms"] < previous_admission_ms)
                    or (last_completed_ms is not None and row["at_ms"] < last_completed_ms)
                    or row["input_bytes"] > _LIMITS["max_input_bytes"]
                    or row["declared_max_output_tokens"] > _LIMITS["max_output_tokens"]
                    or row["tool_payload_bytes"] > _LIMITS["max_tool_payload_bytes"]):
                raise Stop("provider_journal_admission_invalid")
            total_input += row["input_bytes"]
            total_declared_output += row["declared_max_output_tokens"]
            total_tool_payload += row["tool_payload_bytes"]
            if (total_input > _LIMITS["max_total_input_bytes"]
                    or total_declared_output > _LIMITS["max_total_output_tokens"]
                    or total_tool_payload > _LIMITS["max_total_tool_payload_bytes"]):
                raise Stop("provider_journal_cumulative_limit_exceeded")
            if first_admitted_ms is None:
                first_admitted_ms = row["at_ms"]
            previous_admission_ms = row["at_ms"]
            seen.add(key); pending.add(key); admitted += 1; inflight += 1; peak = max(peak, inflight)
        elif row["phase"] == "completed":
            status = row.get("status")
            if (not completion.issubset(row) or key not in pending
                    or type(status) is not int or not 100 <= status <= 599 or 300 <= status < 400
                    or row.get("forwarded") is not True
                    or row.get("reason") != "within_request_budget"):
                raise Stop("provider_journal_completion_invalid")
            usage_source = row.get("usage_source")
            usage_values = [row.get(field) for field in (
                "actual_input_tokens", "actual_cache_read_tokens", "actual_output_tokens")]
            if (type(row.get("elapsed_ms")) is not int or row["elapsed_ms"] < 0
                    or row["elapsed_ms"] > _LIMITS["deadline_ms"]
                    or type(row.get("completed_at_ms")) is not int
                    or row["completed_at_ms"] < row["at_ms"]
                    or usage_source not in ("provider_response", "unknown")
                    or any(not (type(value) is int and value >= 0) and value != "unknown"
                           for value in usage_values)
                    or (usage_source == "unknown" and any(value != "unknown" for value in usage_values))
                    or (type(usage_values[2]) is int
                        and usage_values[2] > row["declared_max_output_tokens"])):
                raise Stop("provider_journal_usage_invalid")
            if last_completed_ms is not None and row["completed_at_ms"] < last_completed_ms:
                raise Stop("provider_journal_time_order_invalid")
            last_completed_ms = row["completed_at_ms"]
            pending.remove(key); completed += 1; inflight -= 1
        else:
            raise Stop("provider_journal_nonterminal_phase")
    if (pending or inflight or not admitted or admitted != completed
            or admitted > _LIMITS["max_provider_calls"] or admitted > _LIMITS["max_attempts"]
            or peak > _LIMITS["max_concurrent"] or first_admitted_ms is None
            or last_completed_ms is None or last_completed_ms - first_admitted_ms > _LIMITS["deadline_ms"]):
        raise Stop("provider_journal_limits_or_settlement_invalid")
    completed_rows = [row for row in rows if row.get("phase") == "completed"]
    def usage_total(field: str):
        values = [row[field] for row in completed_rows]
        return sum(values) if all(type(value) is int for value in values) else "unknown"
    return {"schema_version": "byq-provider-aggregate.v1", "root_run_id": root,
            "provider_calls": admitted, "provider_attempts": admitted, "max_concurrent": peak,
            "input_bytes": total_input, "declared_output_tokens": total_declared_output,
            "tool_payload_bytes": total_tool_payload,
            "observed_elapsed_ms": last_completed_ms - first_admitted_ms,
            "actual_input_tokens": usage_total("actual_input_tokens"),
            "actual_cache_read_tokens": usage_total("actual_cache_read_tokens"),
            "actual_output_tokens": usage_total("actual_output_tokens"),
            "attribution": "root_aggregate_only_child_unknown"}


def _native_reader_source() -> str:
    return r'''import ctypes,hashlib,json,os,pathlib,re,stat,sys
cwd=pathlib.Path(sys.argv[1]); workspace,root_id,child_id,marker,root_run,child_run,producer=sys.argv[2:]
if os.geteuid()!=10002 or os.getegid()!=10002: raise SystemExit("native_reader_identity_mismatch")
if not cwd.is_absolute() or cwd.resolve()!=cwd or not cwd.is_relative_to(pathlib.Path("/var/lib/byq/dsh-sessions/dsh-v0.2.0-rc.2-acp")/workspace): raise SystemExit("native_cwd_scope_invalid")
def key(s):
 out=[]; sep=False
 for c in s:
  if c in "/\\:":
   if not sep: out.append("-")
   sep=True
  elif c!="~" and c.isascii() and (c.isalnum() or c in "._-"): out.append(c); sep=False
  else:
   n=ord(c)
   if n>65535: raise SystemExit("native_cwd_invalid")
   out.append("~%04X"%n); sep=False
 return "--"+("".join(out).lstrip("-") or "root")[:251]+"--"
def pairs(items):
 d={}
 for k,v in items:
  if k in d: raise ValueError("duplicate")
  d[k]=v
 return d
def canonical(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("ascii")
def sha(v): return hashlib.sha256(v).hexdigest()
class IB(ctypes.Structure): _fields_=[("src",ctypes.c_void_p),("size",ctypes.c_size_t),("pos",ctypes.c_size_t)]
class OB(ctypes.Structure): _fields_=[("dst",ctypes.c_void_p),("size",ctypes.c_size_t),("pos",ctypes.c_size_t)]
lib=ctypes.CDLL("libzstd.so.1"); lib.ZSTD_createDStream.restype=ctypes.c_void_p
lib.ZSTD_initDStream.argtypes=[ctypes.c_void_p]; lib.ZSTD_initDStream.restype=ctypes.c_size_t
lib.ZSTD_decompressStream.argtypes=[ctypes.c_void_p,ctypes.POINTER(OB),ctypes.POINTER(IB)]; lib.ZSTD_decompressStream.restype=ctypes.c_size_t
lib.ZSTD_isError.argtypes=[ctypes.c_size_t]; lib.ZSTD_isError.restype=ctypes.c_uint
lib.ZSTD_freeDStream.argtypes=[ctypes.c_void_p]
def safe_file(native):
 base=cwd/"sessions"/key(str(cwd)); p=base/native/"session.v4.jsonl.zstd"
 cur=cwd
 for part in ("sessions",key(str(cwd)),native):
  cur=cur/part; st=os.lstat(cur)
  if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode): raise ValueError("native_parent_invalid")
 st=os.lstat(p)
 if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode) or st.st_nlink!=1 or st.st_size<=0 or st.st_size>67108864: raise ValueError("native_file_invalid")
 fd=os.open(p,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)); before=os.fstat(fd)
 stamp=lambda x:(x.st_dev,x.st_ino,x.st_mode,x.st_nlink,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
 if stamp(st)!=stamp(before): os.close(fd); raise ValueError("native_file_changed")
 digest=hashlib.sha256(); compressed=0; stream=lib.ZSTD_createDStream()
 if not stream: os.close(fd); raise ValueError("native_zstd_unavailable")
 header=None; calls={}; users=[]; pending=bytearray(); decompressed=records=0; need_init=True; remaining=1
 try:
  while True:
   chunk=os.read(fd,65536)
   if chunk: compressed+=len(chunk); digest.update(chunk)
   ib=IB(ctypes.cast(ctypes.c_char_p(chunk),ctypes.c_void_p) if chunk else None,len(chunk),0)
   while ib.pos<ib.size:
    if need_init:
     if lib.ZSTD_isError(lib.ZSTD_initDStream(stream)): raise ValueError("native_zstd_unavailable")
     need_init=False
    outbuf=ctypes.create_string_buffer(131072); ob=OB(ctypes.cast(outbuf,ctypes.c_void_p),len(outbuf),0)
    remaining=lib.ZSTD_decompressStream(stream,ctypes.byref(ob),ctypes.byref(ib))
    if lib.ZSTD_isError(remaining): raise ValueError("native_zstd_invalid")
    if ob.pos:
     decompressed+=ob.pos
     if decompressed>67108864: raise ValueError("native_decompressed_oversize")
     pending.extend(outbuf.raw[:ob.pos])
     if len(pending)>8388608 and b"\n" not in pending: raise ValueError("native_record_oversize")
     while b"\n" in pending:
      line,_,rest=pending.partition(b"\n"); pending=bytearray(rest)
      if not line: continue
      records+=1
      if records>100000: raise ValueError("native_record_count_oversize")
      row=json.loads(line.decode("utf-8"),object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError("constant")))
      if records==1: header=row; continue
      if not isinstance(row,dict): raise ValueError("native_event_invalid")
      seq=row.get("seq"); typ=row.get("type"); data=row.get("data")
      if type(seq) is not int or seq<1 or not isinstance(typ,str) or not isinstance(data,dict): raise ValueError("native_event_invalid")
      if typ=="user/message" and isinstance(data.get("source"),dict) and data["source"].get("kind")=="user":
       content=data.get("content")
       if not isinstance(content,list): raise ValueError("native_user_content_invalid")
       text="".join(part.get("text","") for part in content if isinstance(part,dict) and part.get("type")=="text" and isinstance(part.get("text"),str))
       users.append({"seq":seq,"sha256":sha(text.encode()),"marker_present":marker in text})
      if typ=="assistant/message":
       msg=data.get("message"); content=msg.get("content") if isinstance(msg,dict) else None
       if not isinstance(content,list): raise ValueError("native_assistant_content_invalid")
       for block in content:
        if isinstance(block,dict) and block.get("type")=="tool-call":
         cid=block.get("id"); name=block.get("name"); args=block.get("arguments")
         if isinstance(args,str): args=json.loads(args,object_pairs_hook=pairs)
         if not isinstance(cid,str) or not cid or not isinstance(name,str) or not name or not isinstance(args,dict) or cid in calls: raise ValueError("native_tool_call_invalid")
         short=name.removeprefix("mcp__byq__"); valid=False
         if native==root_id and short=="byq_agent_run_start": valid=(args.get("role_id")=="quant_orchestrator" and args.get("parent_run_id") is None)
         elif native==root_id and short=="byq_delegate_market_research": valid=(set(args)=={"description","prompt"} and all(isinstance(args.get(k),str) for k in ("description","prompt")) and marker in args["description"]+"\\n"+args["prompt"] and "run_in_background" not in args)
         elif native==child_id and short=="byq_agent_run_start": valid=(args.get("role_id")=="market_researcher" and args.get("parent_run_id")==root_run)
         elif native==child_id and short=="byq_agent_authorize": valid=(args=={"run_id":child_run,"action":"byq_market_session_context"})
         elif native==child_id and short=="byq_market_session_context": valid=(args=={})
         elif native==child_id and short=="byq_agent_audit": valid=(args.get("run_id")==child_run and args.get("action")=="byq_market_session_context" and isinstance(args.get("outcome"),str) and set(args) in ({"run_id","action","outcome"},{"run_id","action","outcome","detail"}))
         audit_outcome_sha=sha(args["outcome"].encode()) if native==child_id and short=="byq_agent_audit" and isinstance(args.get("outcome"),str) else None
         calls[cid]={"call_id":cid,"tool_name":name,"arguments_sha256":sha(canonical(args)),"arguments_contract_valid":valid,"assistant_sequence":seq,"call_sequence":None,"result_sequence":None,"result_sha256":None,"result_error":None,"audit_outcome_sha256":audit_outcome_sha,"delegate_kind":None,"delegate_run_id_sha256":None,"delegate_output_sha256":None,"delegate_output_type":None,"delegate_output_count":None}
      elif typ=="tool/call":
       cid=data.get("callId"); call=calls.get(cid)
       if call is None or call["call_sequence"] is not None: raise ValueError("native_tool_call_event_unmatched")
       event_name=data.get("name"); event_args=data.get("arguments")
       if isinstance(event_args,str): event_args=json.loads(event_args,object_pairs_hook=pairs)
       if (event_name!=call["tool_name"] or not isinstance(event_args,dict)
           or sha(canonical(event_args))!=call["arguments_sha256"]): raise ValueError("native_tool_call_event_mismatch")
       call["call_sequence"]=seq
      elif typ=="tool/result":
       msg=data.get("message"); src=msg.get("source") if isinstance(msg,dict) else None
       cid=src.get("callId") if isinstance(src,dict) else None; call=calls.get(cid)
       if call is None or call["result_sequence"] is not None: raise ValueError("native_tool_result_unmatched")
       content=msg.get("content")
       result_blocks=[block for block in content if isinstance(block,dict) and block.get("type")=="tool-result"] if isinstance(content,list) else []
       if len(result_blocks)!=1 or result_blocks[0].get("toolCallId")!=cid: raise ValueError("native_tool_result_id_mismatch")
       result_block=result_blocks[0]
       call["result_sequence"]=seq; call["result_sha256"]=sha(canonical(msg))
       if type(result_block.get("isError",False)) is not bool: raise ValueError("native_tool_result_error_flag_invalid")
       call["result_error"]=result_block.get("isError",False)
       if call["tool_name"].removeprefix("mcp__byq__")=="byq_delegate_market_research":
        pieces=[]
        for part in result_block.get("content",[]):
         if isinstance(part,dict) and part.get("type")=="text" and isinstance(part.get("text"),str): pieces.append(part["text"])
        result=json.loads("".join(pieces),object_pairs_hook=pairs)
        if not isinstance(result,dict) or set(result)!={"kind","runId","output"} or result.get("kind")!="foreground" or not isinstance(result.get("runId"),str) or not result["runId"]: raise ValueError("native_delegate_result_invalid")
        output=result["output"]
        call["delegate_kind"]="foreground"; call["delegate_run_id_sha256"]=sha(result["runId"].encode()); call["delegate_output_sha256"]=sha(canonical(output)); call["delegate_output_type"]=("null" if output is None else "boolean" if isinstance(output,bool) else "number" if isinstance(output,(int,float)) else "string" if isinstance(output,str) else "array" if isinstance(output,list) else "object"); call["delegate_output_count"]=len(output) if isinstance(output,(list,dict,str)) else None
    if remaining==0: need_init=True
   if not chunk:
    if not need_init: raise ValueError("native_truncated")
    break
  if pending or records==0 or header is None: raise ValueError("native_truncated")
 finally:
  lib.ZSTD_freeDStream(stream); after=os.fstat(fd); os.close(fd)
 after_path=os.lstat(p)
 if stamp(before)!=stamp(after) or stamp(before)!=stamp(after_path) or compressed!=before.st_size: raise ValueError("native_file_changed")
 required={"type","version","id","createdAt","isSeeded","delegationDepth"}; allowed=required|{"cwd","parentSession","origin","agentPreset"}
 if (not isinstance(header,dict) or not required<=set(header) or not set(header)<=allowed
  or header.get("type")!="session" or type(header.get("version")) is not int or header["version"]!=4
  or header.get("id")!=native or type(header.get("createdAt")) is not int
  or type(header.get("isSeeded")) is not bool or type(header.get("delegationDepth")) is not int): raise ValueError("native_header_invalid")
 if header.get("parentSession") is not None and not isinstance(header.get("parentSession"),str): raise ValueError("native_header_invalid")
 return {"header":{"id":native,"version":4,"origin":header.get("origin"),"parentSession":header.get("parentSession"),"delegationDepth":header["delegationDepth"]},"relative_path":str(p.relative_to(cwd)),"compressed_sha256":digest.hexdigest(),"compressed_bytes":compressed,"user_inputs":users,"calls":list(calls.values())}
try:
 if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,127}",workspace): raise ValueError("native_workspace_invalid")
 if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",root_id) or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",child_id) or root_id==child_id: raise ValueError("native_session_identity_invalid")
 root=safe_file(root_id); child=safe_file(child_id)
 if root["header"]["id"]!=root_id or child["header"]["id"]!=child_id: raise ValueError("native_header_id_mismatch")
 if root["header"]["delegationDepth"]!=0 or child["header"]["origin"]!="subagent" or child["header"]["parentSession"]!=root_id or child["header"]["delegationDepth"]!=1: raise ValueError("native_child_lineage_mismatch")
 print(json.dumps({"schema_version":"byq-acp-native-foreground-child.v1","producer_source_sha256":producer,"root":root,"child":child},sort_keys=True,separators=(",",":")))
except Exception as exc:
 print("NATIVE_CHILD_STOP:"+(str(exc) if str(exc).startswith("native_") else "native_child_invalid"),file=sys.stderr); sys.exit(2)'''


def _read_native(out: Path, runner_id: str, cwd: str, workspace: str, root_native: str,
                 child_native: str, marker: str, root_run: str, child_run: str,
                 *, deadline: float) -> dict:
    reader = _native_reader_source()
    reader_sha = hashlib.sha256(reader.encode()).hexdigest()
    source = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    function = next((node for node in ast.walk(source)
                     if isinstance(node, ast.FunctionDef) and node.name == "_native_reader_source"), None)
    literal = None
    if function is not None:
        for child in function.body:
            if (isinstance(child, ast.Return) and isinstance(child.value, ast.Constant)
                    and isinstance(child.value.value, str)):
                literal = child.value.value
                break
    if (literal != reader or hashlib.sha256(reader.encode()).hexdigest() != reader_sha
            or reader_sha != _NATIVE_READER_SHA256):
        raise Stop("native_reader_source_changed")
    argv = [
        "docker", "exec", "--user", "10002:10002", "--workdir", "/app", "-i", runner_id,
        "python3", "-I", "-c", reader, cwd, workspace, root_native, child_native,
        marker, root_run, child_run, reader_sha]
    raw = ordinary._command(out, "native-child-projection", argv, timeout=35, deadline=deadline)
    command = ordinary._json_read(out / "commands/native-child-projection.json")
    if (not isinstance(command, dict) or command.get("returncode") != 0
            or command.get("argv") != argv or command.get("stdout_sha256") != hashlib.sha256(raw).hexdigest()):
        raise Stop("native_child_projection_command_mismatch")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise Stop("native_child_projection_json_invalid") from exc
    required = {"schema_version", "producer_source_sha256", "root", "child"}
    if (not isinstance(value, dict) or set(value) != required
            or value.get("schema_version") != "byq-acp-native-foreground-child.v1"
            or value.get("producer_source_sha256") != reader_sha):
        raise Stop("native_child_projection_schema_invalid")
    root, child = value.get("root"), value.get("child")
    if (not isinstance(root, dict) or not isinstance(child, dict)
            or root.get("header", {}).get("id") != root_native
            or child.get("header", {}).get("id") != child_native):
        raise Stop("native_child_projection_scope_mismatch")
    session_keys = {"header", "relative_path", "compressed_sha256", "compressed_bytes", "user_inputs", "calls"}
    header_keys = {"id", "version", "origin", "parentSession", "delegationDepth"}
    call_keys = {"call_id", "tool_name", "arguments_sha256", "arguments_contract_valid", "assistant_sequence",
        "call_sequence", "result_sequence", "result_sha256", "result_error", "audit_outcome_sha256",
        "delegate_kind", "delegate_run_id_sha256", "delegate_output_sha256", "delegate_output_type", "delegate_output_count"}
    for native_id, session in ((root_native, root), (child_native, child)):
        header, inputs, calls = session.get("header"), session.get("user_inputs"), session.get("calls")
        path = Path(session["relative_path"]) if isinstance(session.get("relative_path"), str) else Path("/")
        if (set(session) != session_keys or not isinstance(header, dict) or set(header) != header_keys
                or not isinstance(inputs, list) or len(inputs) > 256 or not isinstance(calls, list) or len(calls) > 16
                or path.is_absolute() or ".." in path.parts or len(path.parts) != 4
                or path.parts[0] != "sessions" or path.parts[2] != native_id
                or path.as_posix() != f"sessions/{ordinary._session_project_key(cwd)}/{native_id}/session.v4.jsonl.zstd"
                or path.parts[3] != "session.v4.jsonl.zstd"
                or not isinstance(session.get("compressed_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", session["compressed_sha256"])
                or type(session.get("compressed_bytes")) is not int or not 1 <= session["compressed_bytes"] <= 67108864):
            raise Stop("native_child_projection_shape_invalid")
        if (header.get("id") != native_id or header.get("version") != 4
                or (header.get("origin") is not None and not isinstance(header.get("origin"), str))
                or (header.get("parentSession") is not None and not isinstance(header.get("parentSession"), str))
                or type(header.get("delegationDepth")) is not int):
            raise Stop("native_child_projection_header_invalid")
        for row in inputs:
            if (not isinstance(row, dict) or set(row) != {"seq", "sha256", "marker_present"}
                    or type(row.get("seq")) is not int or row["seq"] < 1
                    or not isinstance(row.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                    or type(row.get("marker_present")) is not bool):
                raise Stop("native_child_projection_input_invalid")
        for row in calls:
            if (not isinstance(row, dict) or set(row) != call_keys
                    or not isinstance(row.get("call_id"), str) or not row["call_id"] or len(row["call_id"]) > 256
                    or not isinstance(row.get("tool_name"), str) or not row["tool_name"] or len(row["tool_name"]) > 128
                    or not isinstance(row.get("arguments_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["arguments_sha256"])
                    or row.get("arguments_contract_valid") is not True
                    or type(row.get("assistant_sequence")) is not int or row["assistant_sequence"] < 1
                    or type(row.get("call_sequence")) is not int or type(row.get("result_sequence")) is not int
                    or not isinstance(row.get("result_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["result_sha256"])
                    or type(row.get("result_error")) is not bool
                    or (row.get("audit_outcome_sha256") is not None and
                        (not isinstance(row["audit_outcome_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["audit_outcome_sha256"])) )
                    or row.get("delegate_kind") not in {None, "foreground"}
                    or any(row.get(key) is not None and
                           (not isinstance(row[key], str) or not re.fullmatch(r"[0-9a-f]{64}", row[key]))
                           for key in ("delegate_run_id_sha256", "delegate_output_sha256"))
                    or row.get("delegate_output_type") not in {None, "null", "boolean", "number", "string", "array", "object"}
                    or (row.get("delegate_output_count") is not None and
                        (type(row["delegate_output_count"]) is not int or row["delegate_output_count"] < 0))):
                raise Stop("native_child_projection_call_invalid")
    if (root["relative_path"].split("/")[1] != child["relative_path"].split("/")[1]
            or root["relative_path"] == child["relative_path"]):
        raise Stop("native_child_projection_paths_mismatch")
    return value


def _check_tool_chain(projection: dict, backend: dict, marker: str) -> dict:
    registrations = backend.get("registrations")
    ingress = backend.get("ingress")
    audits = backend.get("audits")
    if not isinstance(registrations, list) or not isinstance(ingress, list) or not isinstance(audits, list):
        raise Stop("backend_child_projection_invalid")
    root_reg = next((r for r in registrations if r.get("origin") == "root"), None)
    child_reg = next((r for r in registrations if r.get("origin") == "subagent"), None)
    if not isinstance(root_reg, dict) or not isinstance(child_reg, dict):
        raise Stop("backend_child_registration_missing")
    if (root_reg.get("run_role_id") != "quant_orchestrator"
            or child_reg.get("run_role_id") != "market_researcher"
            or root_reg.get("run_status") != "completed" or child_reg.get("run_status") != "completed"
            or root_reg.get("run_authority_status") != "closed"
            or child_reg.get("run_authority_status") != "closed"):
        raise Stop("backend_root_child_role_or_terminal_state_invalid")
    root_run, child_run = root_reg["agent_run_id"], child_reg["agent_run_id"]
    root_calls = projection["root"]["calls"]
    child_calls = projection["child"]["calls"]
    if (len(projection["root"].get("user_inputs", [])) != 1
            or len(projection["child"].get("user_inputs", [])) != 1):
        raise Stop("native_root_child_prompt_count_invalid")
    wanted_root, wanted_child = set(_ROOT_CALLS), set(_CHILD_CALLS)
    root_names = [call.get("tool_name", "").removeprefix("mcp__byq__") for call in root_calls]
    child_names = [call.get("tool_name", "").removeprefix("mcp__byq__") for call in child_calls]
    root_by_name = {call["tool_name"].removeprefix("mcp__byq__"): call for call in root_calls}
    child_by_name = {call["tool_name"].removeprefix("mcp__byq__"): call for call in child_calls}
    if set(root_by_name) != wanted_root or set(child_by_name) != wanted_child or len(root_names) != len(root_by_name) or len(child_names) != len(child_by_name):
        raise Stop("native_expected_tool_call_set_mismatch")
    delegated = root_by_name["byq_delegate_market_research"]
    if (any(call.get("arguments_contract_valid") is not True for call in root_calls + child_calls)
            or delegated.get("delegate_kind") != "foreground"
            or not isinstance(delegated.get("delegate_run_id_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", delegated["delegate_run_id_sha256"])
            or not isinstance(delegated.get("delegate_output_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", delegated["delegate_output_sha256"])
            or delegated.get("delegate_output_type") not in {"null", "boolean", "number", "string", "array", "object"}):
        raise Stop("native_tool_arguments_or_foreground_result_invalid")
    audit_call = child_by_name["byq_agent_audit"]
    expected_ingress = {"byq_agent_authorize", "byq_market_session_context", "byq_agent_audit"}
    if (len(ingress) != 3 or {row.get("tool_name") for row in ingress} != expected_ingress
            or any(row.get("status") != "settled" or row.get("origin") != "subagent"
                   or row.get("native_agent_session_id") != child_reg["native_agent_session_id"]
                   or row.get("agent_run_id") != child_run for row in ingress)):
        raise Stop("backend_child_ingress_not_exact_settled")
    call_by_tool = {call["tool_name"].removeprefix("mcp__byq__"): call for call in child_calls}
    for row in ingress:
        call = call_by_tool.get(row["tool_name"])
        if call is None or row.get("arguments_sha256") != call["arguments_sha256"]:
            raise Stop("native_backend_arguments_hash_mismatch")
    expected_native_by_run = {
        root_run: root_reg["native_agent_session_id"],
        child_run: child_reg["native_agent_session_id"],
    }
    context_audits = []
    binding_audits = {root_run: [], child_run: []}
    for row in audits:
        if not isinstance(row, dict):
            raise Stop("backend_child_audit_mismatch")
        run_id = row.get("run_id")
        outcome = row.get("outcome")
        if (run_id not in expected_native_by_run
                or row.get("native_agent_session_id") != expected_native_by_run[run_id]
                or not isinstance(outcome, str)):
            raise Stop("backend_child_audit_mismatch")
        action = row.get("action")
        if action == "byq_market_session_context":
            context_audits.append(row)
        elif action == "runtime_turn_binding":
            if outcome not in {"active", "completed"}:
                raise Stop("backend_child_audit_mismatch")
            binding_audits[run_id].append(outcome)
        else:
            raise Stop("backend_child_audit_mismatch")
    # Bound AgentRun creation writes one active binding audit per run. A
    # terminal lifecycle event writes one completed binding audit for each
    # changed run; close_runtime_root instead writes neither terminal audit.
    for outcomes in binding_audits.values():
        if outcomes.count("active") != 1 or outcomes.count("completed") > 1:
            raise Stop("backend_child_audit_mismatch")
    if binding_audits[root_run].count("completed") != binding_audits[child_run].count("completed"):
        raise Stop("backend_child_audit_mismatch")
    expected_audit_outcome_sha = audit_call.get("audit_outcome_sha256")
    completed_outcome_sha = hashlib.sha256(b"completed").hexdigest()
    matching_explicit = [row for row in context_audits
        if row["run_id"] == child_run and row["outcome"] == "completed"
        and hashlib.sha256(row["outcome"].encode()).hexdigest() == expected_audit_outcome_sha]
    authorized = [row for row in context_audits
        if row["run_id"] == child_run and row["outcome"] == "authorized"]
    if (expected_audit_outcome_sha != completed_outcome_sha or len(context_audits) != 2
            or len(matching_explicit) != 1 or len(authorized) != 1):
        raise Stop("backend_child_audit_mismatch")
    for call in root_calls + child_calls:
        if (type(call.get("call_sequence")) is not int or type(call.get("result_sequence")) is not int
                or call["call_sequence"] <= call["assistant_sequence"]
                or call["result_sequence"] <= call["call_sequence"] or call.get("result_error") is not False):
            raise Stop("native_tool_call_result_not_complete")
    marker_seen = (any(row.get("marker_present") is True for row in projection["root"]["user_inputs"])
                   and any(row.get("marker_present") is True for row in projection["child"]["user_inputs"]))
    if not marker_seen:
        raise Stop("case_marker_missing_from_root_or_child_input")
    return {"root_agent_run_id": root_run, "child_agent_run_id": child_run,
            "child_role_id": child_reg["run_role_id"], "child_role_version": child_reg["run_role_version"],
            "delegate_kind": "foreground", "delegate_dsh_run_id_sha256": delegated["delegate_run_id_sha256"],
            "delegate_output_sha256": delegated["delegate_output_sha256"],
            "delegate_output_count": delegated["delegate_output_count"],
            "case_marker_in_root_and_child_input": True}


def _scope_from(binding: dict, identity: dict, conversation: dict, root: str) -> dict:
    cwd = binding.get("cwd")
    if (binding.get("schema_version") != "byq-acp-root-binding.v1"
            or binding.get("owner_principal") != identity.get("subject")
            or binding.get("workspace_id") != identity.get("workspace_id")
            or binding.get("session_id") != conversation.get("runtime_session_id")
            or binding.get("trace_id") != conversation.get("trace_id")
            or binding.get("root_run_id") != root
            or binding.get("process_exit_confirmed") is not True
            or binding.get("cleanup_unconfirmed") is not False
            or not isinstance(binding.get("native_session_id"), str)
            or not isinstance(binding.get("runtime_generation"), str)
            or not isinstance(binding.get("previous_boot_id"), str)
            or not isinstance(cwd, str) or not Path(cwd).is_absolute()
            or Path(cwd).resolve() != Path(cwd)):
        raise Stop("root_binding_scope_or_cleanup_invalid")
    scope = {
        "workspace_id": identity["workspace_id"], "owner_principal": identity["subject"],
        "session_id": conversation["runtime_session_id"], "trace_id": conversation["trace_id"],
        "root_run_id": root, "runtime_boot_id": binding["previous_boot_id"],
        "generation_id": binding["runtime_generation"], "cwd_leaf": Path(cwd).name,
        "actor_principal": f"byq-product-agent-{conversation['runtime_session_id']}",
    }
    return scope_reader._validated_scope(scope)


def _capture(args, out: Path, deadline: float) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,127}", args.conversation_id):
        raise Stop("conversation_id_invalid")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", args.case_marker):
        raise Stop("case_marker_invalid")
    ordinary._verify_container_snapshot(args, out, "child", deadline=deadline)
    identity = ordinary._json_read(out / "identity.json")
    opener, current = ordinary._login(deadline=deadline)
    if identity != current or identity.get("role") != "admin" or identity.get("workspace_id") != ordinary.WORKSPACE:
        raise Stop("durable_identity_changed")
    status, public_response = ordinary._request(opener, "GET", f"/v1/agent/sessions/{args.conversation_id}", deadline=deadline)
    public = public_response.get("conversation") if isinstance(public_response, dict) else None
    if (status != 200 or not isinstance(public, dict) or public.get("session_id") != args.conversation_id
            or not isinstance(public.get("trace_id"), str)):
        raise Stop("conversation_scope_unavailable")
    clock = ordinary._json_read(out / "batch-clock.json")
    conversation = ordinary._pg(out, args.postgres_id, "child-conversation-scope",
        ordinary._runtime_scope_sql(args.conversation_id, identity["subject"], identity["workspace_id"],
                                    clock["started_utc"], 1), deadline=deadline)
    if (not isinstance(conversation, dict) or conversation.get("conversation_id") != args.conversation_id
            or conversation.get("owner_principal") != identity["subject"]
            or conversation.get("workspace_id") != identity["workspace_id"]
            or conversation.get("trace_id") != public["trace_id"]
            or conversation.get("user_message_count") != 1
            or not isinstance(conversation.get("runtime_session_id"), str)):
        raise Stop("conversation_backend_scope_mismatch")
    sse = ordinary._sse_events(opener, args.conversation_id, 0, 1, deadline=deadline)
    if any(row.get("session_id") != args.conversation_id or row.get("trace_id") != public["trace_id"] for row in sse):
        raise Stop("workflow_event_scope_mismatch")
    starts = [row for row in sse if row.get("kind") == "session.started"]
    terminals = [row for row in sse if row.get("kind") in ordinary.TERMINALS]
    if len(starts) != 1 or len(terminals) != 1:
        raise Stop("workflow_single_root_required")
    root = starts[0].get("payload", {}).get("run_id")
    if not isinstance(root, str) or not ordinary.ROOT_RE.fullmatch(root) or terminals[0].get("payload", {}).get("run_id") != root:
        raise Stop("workflow_root_identity_mismatch")
    status, delivery = ordinary._request(opener, "GET", f"/v1/agent/sessions/{args.conversation_id}/answer-delivery", deadline=deadline)
    if (status != 200 or not isinstance(delivery, dict)
            or delivery.get("schema_version") != "public-answer-delivery-status.v1"
            or delivery.get("state") != "up_to_date"
            or any(type(delivery.get(k)) is not int or delivery[k] != 0
                   for k in ("pending_events", "exhausted_events", "rejected_events"))):
        raise Stop("answer_delivery_not_up_to_date")
    status, final = ordinary._request(opener, "GET", f"/v1/agent/sessions/{args.conversation_id}", deadline=deadline)
    messages = final.get("messages") if isinstance(final, dict) else None
    if (status != 200 or not isinstance(messages, list)
            or sum(row.get("role") == "user" for row in messages if isinstance(row, dict)) != 1
            or not any(row.get("role") == "assistant" for row in messages if isinstance(row, dict))):
        raise Stop("durable_answer_not_persisted")
    roots = ordinary._pg(out, args.postgres_id, "child-backend-root",
        ordinary._roots_sql({"owner_principal": identity["subject"], "workspace_id": identity["workspace_id"],
            "runtime_session_id": conversation["runtime_session_id"], "trace_id": conversation["trace_id"]},
            clock["started_utc"]), deadline=deadline)
    root_rows = roots.get("roots") if isinstance(roots, dict) else None
    if (not isinstance(root_rows, list) or len(root_rows) != 1 or not isinstance(root_rows[0], dict)
            or root_rows[0].get("root_run_id") != root
            or root_rows[0].get("status") != "completed" or root_rows[0].get("authority_status") != "closed"
            or root_rows[0].get("terminal_unknown_claim_count") != 0):
        raise Stop("backend_root_not_closed_exactly")
    binding, provider_raw = ordinary._binding_and_journal(
        out, args.adapter_id, args.session_root, identity["workspace_id"],
        conversation["runtime_session_id"], root, deadline=deadline)
    ordinary._write(out / "journals" / f"product-turn-provider-request-{root}.jsonl", provider_raw)
    scope = _scope_from(binding, identity, conversation, root)
    backend_sql = scope_reader.build_sql(scope, "root_child")
    backend_raw = ordinary._command(out, "child-backend-scope", [
        "docker", "exec", "-i", args.postgres_id, "sh", "-c",
        'exec psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"',
        "capture", backend_sql], timeout=20, deadline=deadline)
    try:
        backend_projection = scope_reader.validate_projection(scope, "root_child", backend_raw.decode().strip())
    except Exception as exc:
        raise Stop("backend_child_scope_invalid") from exc
    scoped_root = backend_projection["root"]
    queried_root = root_rows[0]
    if (scoped_root.get("root_run_id") != root
            or scoped_root.get("status") != "completed" or scoped_root.get("authority_status") != "closed"
            or scoped_root.get("terminal_unknown_claim_count") != 0
            or scoped_root.get("terminal_sequence") != queried_root.get("terminal_sequence")
            or scoped_root.get("terminal_event_sha256") != queried_root.get("terminal_event_sha256")):
        raise Stop("backend_root_not_closed_exactly")
    root_reg = next(r for r in backend_projection["registrations"] if r["origin"] == "root")
    child_reg = next(r for r in backend_projection["registrations"] if r["origin"] == "subagent")
    if binding.get("native_session_id") != root_reg["native_agent_session_id"]:
        raise Stop("binding_root_native_mismatch")
    native = _read_native(out, args.runner_id, binding["cwd"], identity["workspace_id"],
        root_reg["native_agent_session_id"], child_reg["native_agent_session_id"],
        args.case_marker, root_reg["agent_run_id"], child_reg["agent_run_id"], deadline=deadline)
    chain = _check_tool_chain(native, backend_projection, args.case_marker)
    if chain["root_agent_run_id"] != root_reg["agent_run_id"] or chain["child_agent_run_id"] != child_reg["agent_run_id"]:
        raise Stop("native_backend_agent_run_mismatch")
    guard = _read_tool_guard(out, args.adapter_id, binding["cwd"], root, deadline=deadline)
    native_tool_names = sorted(
        call["tool_name"].removeprefix("mcp__byq__")
        for session in (native["root"], native["child"]) for call in session["calls"])
    if guard["call_count"] != len(native_tool_names) or sorted(guard["tool_names"]) != native_tool_names:
        raise Stop("native_tool_guard_call_set_mismatch")
    provider = _validate_provider_journal(provider_raw, root, binding["runtime_generation"])
    cleanup_source = _CLEANUP_CHILD.read_bytes()
    if hashlib.sha256(cleanup_source).hexdigest() != _CLEANUP_CHILD_SHA256:
        raise Stop("cleanup_verifier_source_changed")
    cleanup_raw = ordinary._command(out, "signed-product-cleanup", [
        "docker", "exec", "--workdir", "/app", "-i", args.runner_id,
        "python3", "-I", "-c", cleanup_source.decode("utf-8")],
        input_bytes=(json.dumps({key: scope[key] for key in (
            "workspace_id", "owner_principal", "session_id", "trace_id", "root_run_id",
            "runtime_boot_id", "generation_id", "cwd_leaf")}, sort_keys=True,
            separators=(",", ":")).encode()), timeout=20, deadline=deadline)
    try:
        cleanup = json.loads(cleanup_raw)
    except (ValueError, UnicodeError) as exc:
        raise Stop("signed_cleanup_proof_json_invalid") from exc
    proof_verifiers = cleanup.get("verifiers") if isinstance(cleanup, dict) else None
    if (not isinstance(cleanup, dict) or set(cleanup) != {
                "schema", "status", "digest", "receipt_sha256", "exact_scope", "cleanup",
                "runner_instance_id", "exit_fields", "verifiers"}
            or cleanup.get("schema") != "byq-cleanup-receipt-proof.v1"
            or cleanup.get("status") != "pass" or cleanup.get("cleanup") != "proven"
            or not isinstance(cleanup.get("digest"), str) or not re.fullmatch(r"[0-9a-f]{64}", cleanup["digest"])
            or not isinstance(cleanup.get("receipt_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", cleanup["receipt_sha256"])
            or not isinstance(proof_verifiers, dict) or set(proof_verifiers) != {
                "file_bounded", "strict_json", "key_set_valid", "mac_valid", "types_valid",
                "schema_valid", "scope_valid", "cleanup_proven", "runner_identity_valid", "exit_fields_valid"}
            or any(flag is not True for flag in proof_verifiers.values())
            or not isinstance(cleanup.get("runner_instance_id"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", cleanup["runner_instance_id"])
            or not isinstance(cleanup.get("exit_fields"), dict)
            or set(cleanup["exit_fields"]) != {"code", "signal", "reason"}
            or cleanup["exit_fields"].get("reason") not in {
                "process_exit", "cancelled", "deadline", "protocol_error", "transport_lost"}
            or cleanup.get("exact_scope") != {key: scope[key] for key in (
                "workspace_id", "owner_principal", "session_id", "trace_id", "root_run_id",
                "runtime_boot_id", "generation_id", "cwd_leaf")}):
        raise Stop("signed_cleanup_scope_mismatch")
    receipt = binding.get("settlement_receipt")
    if (not isinstance(receipt, dict) or set(receipt) != {"schema_version", "root_run_id", "sequence", "event_sha256"}
            or receipt.get("schema_version") != "agent-run-lifecycle-receipt.v1"
            or receipt.get("root_run_id") != root or receipt.get("sequence") != scoped_root["terminal_sequence"]
            or receipt.get("event_sha256") != scoped_root["terminal_event_sha256"]):
        raise Stop("persisted_terminal_receipt_mismatch")
    ack_expected = [{"schema_version": "byq-gateway-terminal-ack-observed.v1",
        "event": "terminal_ack_observed", "root_run_id": root,
        "session_id": scope["session_id"], "boot_id": scope["runtime_boot_id"],
        "trace_id": scope["trace_id"], "sequence": receipt["sequence"],
        "event_sha256": receipt["event_sha256"], "outcome": "completed"}]
    acks = ordinary._gateway_ack_events(out, args.gateway_id, clock["started_utc"], ack_expected, deadline=deadline)
    jobs_after = ordinary._pg(out, args.postgres_id, "jobs-after", ordinary._job_counts_sql(), deadline=deadline)
    jobs_before = ordinary._json_read(out / "jobs-before.json")
    if jobs_after != jobs_before:
        raise Stop("business_job_artifact_inventory_changed")
    _write_safe(out, "conversation-projection.json", {
        "schema_version": "byq-foreground-child-conversation.v1", "conversation_id": args.conversation_id,
        "runtime_session_id": conversation["runtime_session_id"],
        "trace_id": scope["trace_id"], "root_run_id": root, "user_message_count": 1,
        "assistant_message_count": sum(row.get("role") == "assistant" for row in messages if isinstance(row, dict)),
        "answer_delivery": "up_to_date", "case_marker_sha256": hashlib.sha256(args.case_marker.encode()).hexdigest()})
    _write_safe(out, "scope.json", scope)
    _write_safe(out, "backend-child-scope.json", backend_projection)
    _write_safe(out, "native-child-projection.json", native)
    _write_safe(out, "child-chain.json", chain)
    _write_safe(out, "tool-guard-summary.json", guard)
    _write_safe(out, "provider-aggregate.json", provider)
    _write_safe(out, "signed-cleanup-proof.json", cleanup)
    _write_safe(out, "gateway-ack.json", {"schema_version": "byq-gateway-terminal-ack-observed-set.v1", "events": acks})
    _write_safe(out, "jobs-after.json", jobs_after)
    _write_safe(out, "terminal-backend.json", roots)
    _write_safe(out, "binding.json", binding)
    _write_safe(out, "conversation-sse-projection.json", {
        "schema_version": "byq-workflow-trace-sanitized.v1", "event_count": len(sse),
        "events": [{"sequence": row.get("sequence"), "kind": row.get("kind"),
                    "session_id": row.get("session_id"), "trace_id": row.get("trace_id"),
                    "run_id": row.get("payload", {}).get("run_id") if isinstance(row.get("payload"), dict) else None}
                   for row in sse]})
    _write_safe(out, "provider-journal-summary.json", {**provider, "journal_sha256": hashlib.sha256(provider_raw).hexdigest(),
        "journal_bytes": len(provider_raw)})
    _write_safe(out, "observer-result.json", {"schema_version": _OUTCOME, "status": "PASS",
        "scope": {key: scope[key] for key in ("workspace_id", "owner_principal", "session_id", "trace_id", "root_run_id")},
        "child_run_id": child_reg["agent_run_id"], "child_native_session_id_sha256": hashlib.sha256(
            child_reg["native_agent_session_id"].encode()).hexdigest(), "child_role_id": child_reg["run_role_id"],
        "child_role_version": child_reg["run_role_version"], "terminal_ack_observed": True,
        "root_process_group_cleanup_proven": True, "individual_native_child_closed": "UNKNOWN",
        "per_child_provider_attribution": "UNKNOWN", "model_calls_claim": "root aggregate only"})
    return {"schema_version": _OUTCOME, "status": "PASS",
        "scope": {key: scope[key] for key in ("workspace_id", "owner_principal", "session_id", "trace_id", "root_run_id")},
        "child_run_id": child_reg["agent_run_id"], "child_native_session_id_sha256": hashlib.sha256(
            child_reg["native_agent_session_id"].encode()).hexdigest(), "child_role_id": child_reg["run_role_id"],
        "child_role_version": child_reg["run_role_version"], "terminal_ack_observed": True,
        "root_process_group_cleanup_proven": True, "individual_native_child_closed": "UNKNOWN",
        "per_child_provider_attribution": "UNKNOWN", "model_calls_claim": "root aggregate only"}


def _write_safe(out: Path, name: str, value: object) -> None:
    ordinary._json_write(out / name, value)


def _start_case_action(out: Path, action: str, prior: str) -> float:
    if (out / "capture-stop.json").exists():
        raise Stop("batch_already_stopped")
    deadline, _clock = ordinary._batch_deadline(out)
    if not (out / f"checkpoint-{prior}-pass.json").is_file():
        raise Stop("previous_action_not_complete")
    start = out / f"checkpoint-{action}-start.json"
    if start.exists():
        raise Stop("case_action_already_started")
    ordinary._json_write(start, {"action": action, "started_monotonic_ns": time.monotonic_ns()})
    return deadline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "capture-child", "finish"))
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--conversation-id")
    parser.add_argument("--case-marker")
    parser.add_argument("--gateway-id", required=True)
    parser.add_argument("--adapter-id", required=True)
    parser.add_argument("--runner-id", required=True)
    parser.add_argument("--postgres-id", required=True)
    parser.add_argument("--session-root", required=True)
    args = parser.parse_args()
    out = args.out_dir.resolve()
    if args.action == "preflight" and out.exists():
        print("STOP:capture_output_exists", file=sys.stderr); return 2
    try:
        if args.action == "preflight":
            if args.session_root != ordinary.SESSION_ROOT:
                raise Stop("session_root_not_authoritative")
            out.mkdir(mode=0o700, parents=True)
            start = time.monotonic_ns()
            ordinary._json_write(out / "batch-clock.json", {
                "schema_version": "byq-ordinary-capture-clock.v1", "boot_id": ordinary._boot_id(),
                "started_monotonic_ns": start, "deadline_monotonic_ns": start + _BATCH_SECONDS * 1_000_000_000,
                "started_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                "budget_seconds": _BATCH_SECONDS})
            deadline = ordinary._action_start(out, "preflight")
            facts = ordinary._container_snapshot(args, out, "preflight", deadline=deadline)
            ordinary._json_write(out / "container-facts-preflight.json", facts)
            ordinary._native_runtime_preflight(args, out, deadline=deadline)
            _delegate_source_preflight(args, out, deadline=deadline)
            cleanup_source = _CLEANUP_CHILD.read_bytes()
            if hashlib.sha256(cleanup_source).hexdigest() != _CLEANUP_CHILD_SHA256:
                raise Stop("cleanup_verifier_source_changed")
            identity_opener, identity = ordinary._login(deadline=deadline)
            if identity.get("role") != "admin" or identity.get("workspace_id") != ordinary.WORKSPACE:
                raise Stop("admin_personal_workspace_required")
            ordinary._json_write(out / "identity.json", identity)
            ordinary._json_write(out / "authorized-writes.json", {
                "durable_login_may_write_auth_sessions": True,
                "sse_read_may_renew_consumer_lease": True,
                "capture_sends_model_prompts": False, "capture_creates_business_jobs": False})
            ordinary._json_write(out / "jobs-before.json", ordinary._pg(
                out, args.postgres_id, "jobs-before", ordinary._job_counts_sql(), deadline=deadline))
            ordinary._checkpoint_pass(out, "preflight", deadline=deadline)
            print(json.dumps({"status": "PREFLIGHT_PASS", "out_dir": str(out)})); return 0
        if not out.is_dir() or out.stat().st_mode & 0o077:
            raise Stop("capture_directory_permissions_invalid")
        if args.session_root != ordinary.SESSION_ROOT:
            raise Stop("session_root_not_authoritative")
        if args.action == "capture-child":
            if not args.conversation_id or not args.case_marker or (out / "child-capture.json").exists():
                raise Stop("child_capture_arguments_or_reentry_invalid")
            deadline = _start_case_action(out, "child", "preflight")
            result = _capture(args, out, deadline)
            ordinary._json_write(out / "child-capture.json", result)
            ordinary._checkpoint_pass(out, "child", deadline=deadline)
            print(json.dumps({"status": "CHILD_CAPTURE_PASS", "observer": result})); return 0
        if not (out / "child-capture.json").is_file():
            raise Stop("child_capture_missing")
        if not args.conversation_id or not args.case_marker:
            raise Stop("finish_scope_arguments_required")
        conversation = ordinary._json_read(out / "conversation-projection.json")
        scope = ordinary._json_read(out / "scope.json")
        if (not isinstance(conversation, dict) or not isinstance(scope, dict)
                or conversation.get("conversation_id") != args.conversation_id
                or not isinstance(conversation.get("runtime_session_id"), str)
                or scope.get("session_id") != conversation.get("runtime_session_id")
                or scope.get("trace_id") != conversation.get("trace_id")
                or scope.get("root_run_id") != conversation.get("root_run_id")
                or conversation.get("case_marker_sha256") != hashlib.sha256(args.case_marker.encode()).hexdigest()):
            raise Stop("finish_scope_arguments_mismatch")
        deadline = _start_case_action(out, "finish", "child")
        ordinary._verify_container_snapshot(args, out, "finish-final", deadline=deadline)
        result = ordinary._json_read(out / "observer-result.json")
        capture = ordinary._json_read(out / "child-capture.json")
        if (not isinstance(result, dict) or result != capture
                or result.get("schema_version") != _OUTCOME or result.get("status") != "PASS"
                or not isinstance(result.get("scope"), dict)
                or result["scope"].get("session_id") != conversation["runtime_session_id"]
                or result["scope"].get("trace_id") != conversation["trace_id"]
                or result["scope"].get("root_run_id") != conversation["root_run_id"]):
            raise Stop("child_observer_result_invalid")
        ordinary._checkpoint_pass(out, "finish", deadline=deadline)
        print(json.dumps({"status": "FINISH_PASS", "observer": result})); return 0
    except (Stop, ordinary.Stop) as exc:
        if out.is_dir() and (out / "batch-clock.json").is_file() and not (out / "capture-stop.json").exists():
            try: ordinary._json_write(out / "capture-stop.json", {"status": "STOP", "reason": str(exc), "monotonic_ns": time.monotonic_ns()})
            except OSError: pass
        print(f"STOP:{exc}", file=sys.stderr); return 2
    except Exception as exc:
        reason = f"internal_{type(exc).__name__}"
        if out.is_dir() and (out / "batch-clock.json").is_file() and not (out / "capture-stop.json").exists():
            try: ordinary._json_write(out / "capture-stop.json", {"status": "STOP", "reason": reason, "monotonic_ns": time.monotonic_ns()})
            except OSError: pass
        print(f"STOP:{reason}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
