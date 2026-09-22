#!/usr/bin/env python3
"""Validate the offline Jev P3 benchmark using only the Python standard library."""
from __future__ import annotations
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BENCHMARK = HERE / "benchmark.v1.jsonl"
RUBRIC = HERE / "decision-rubric.v1.json"
REQUIRED_CATEGORIES = {
    "three_round_backtest_comparison", "evidence_sufficiency",
    "strategy_revision_direction", "escalation_to_llm",
    "robustness_regime_conflict", "adversarial_calibration",
}
TOP_KEYS = {"case_id","category","state","question","choices","expected","source_basis","tags"}
EXPECTED_KEYS = {"preferred_choice","acceptable_alternatives","should_escalate","confidence_band","rationale"}
SECRET_PATTERNS = [re.compile(p, re.I) for p in (r"sk-[A-Za-z0-9]{16,}", r"ghp_[A-Za-z0-9]{16,}", r"AKIA[0-9A-Z]{16}", r"bearer\s+[A-Za-z0-9._-]{16,}", r"begin (?:rsa |ec |openssh )?private key", r"(?:tushare[_-]?token|api[_-]?key|password)\s*[:=]\s*[^,}\s]{8,}")]
RAW_KEYS = {"raw_signal_snapshot","signal_snapshot_rows","bars_frame","symbol_index","date_index","full_event_log"}

def fail(errors, case_id, message): errors.append(f"{case_id}: {message}")

def walk(value, path="state"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield f"{path}.{key}", key, child
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value): yield from walk(child, f"{path}[{index}]")

def main() -> int:
    errors=[]
    rubric=json.loads(RUBRIC.read_text(encoding="utf-8"))
    benchmark_bytes=BENCHMARK.read_bytes()
    if rubric.get("benchmark_sha256") != hashlib.sha256(benchmark_bytes).hexdigest():
        errors.append("benchmark: sha256 does not match rubric")
    rule_ids=set(rubric.get("rules", {}))
    rule_escalation=rubric.get("rule_escalation", {})
    thresholds=rubric.get("thresholds", {})
    state_limit=int(thresholds.get("bounded_state_max_bytes", 0))
    case_limit=int(thresholds.get("bounded_case_max_bytes", 0))
    cases=[]
    for line_no,line in enumerate(BENCHMARK.read_text(encoding="utf-8").splitlines(),1):
        if not line.strip(): continue
        try: cases.append(json.loads(line))
        except json.JSONDecodeError as exc: errors.append(f"line {line_no}: invalid JSON: {exc}")
    if len(cases) < 50: errors.append(f"benchmark: expected >=50 cases, found {len(cases)}")
    ids=[]; counts=Counter(); pairs=defaultdict(list)
    for case in cases:
        cid=case.get("case_id", "<missing>") if isinstance(case,dict) else "<non-object>"
        if not isinstance(case,dict): fail(errors,cid,"case must be object"); continue
        if set(case)!=TOP_KEYS: fail(errors,cid,f"top-level keys must equal {sorted(TOP_KEYS)}")
        ids.append(cid); counts[case.get("category")]+=1
        if not isinstance(cid,str) or not re.fullmatch(r"[A-F]\d{2}",cid): fail(errors,cid,"invalid case_id")
        state=case.get("state")
        if not isinstance(state,dict) or state.get("dataset_scope")!="offline_synthetic": fail(errors,cid,"state must be offline_synthetic object")
        state_bytes=len(json.dumps(state,ensure_ascii=False,separators=(",",":")).encode()) if isinstance(state,dict) else 0
        case_bytes=len(json.dumps(case,ensure_ascii=False,separators=(",",":")).encode())
        if state_bytes>state_limit: fail(errors,cid,f"state exceeds {state_limit} bytes")
        if case_bytes>case_limit: fail(errors,cid,f"case exceeds {case_limit} bytes")
        choices=case.get("choices")
        if not isinstance(choices,list) or not 2<=len(choices)<=6: fail(errors,cid,"choices must contain 2..6 entries"); choices=[]
        choice_ids=[]
        for item in choices:
            if not isinstance(item,dict) or set(item)!={"id","text"} or not all(isinstance(item.get(k),str) and item[k].strip() for k in ("id","text")): fail(errors,cid,"invalid choice")
            else: choice_ids.append(item["id"])
        if len(choice_ids)!=len(set(choice_ids)): fail(errors,cid,"choice ids are not unique")
        exp=case.get("expected")
        if not isinstance(exp,dict) or set(exp)!=EXPECTED_KEYS: fail(errors,cid,"invalid expected object"); exp={}
        preferred=exp.get("preferred_choice")
        if preferred not in choice_ids: fail(errors,cid,"preferred_choice does not exist")
        alternatives=exp.get("acceptable_alternatives")
        if not isinstance(alternatives,list) or any(x not in choice_ids or x==preferred for x in alternatives): fail(errors,cid,"invalid acceptable_alternatives")
        if not isinstance(exp.get("should_escalate"),bool): fail(errors,cid,"should_escalate must be boolean")
        if exp.get("confidence_band") not in {"high","medium","low"}: fail(errors,cid,"invalid confidence_band")
        tags=case.get("tags")
        if not isinstance(tags,list) or not all(isinstance(x,str) for x in tags): fail(errors,cid,"tags must be strings"); tags=[]
        rule_tags=[x[5:] for x in tags if x.startswith("rule:")]
        if len(rule_tags)!=1 or rule_tags[0] not in rule_ids: fail(errors,cid,"must reference exactly one rubric rule")
        if rule_tags and f"[{rule_tags[0]}]" not in str(exp.get("rationale","")): fail(errors,cid,"rationale must name rule id")
        if rule_tags:
            policy=rule_escalation.get(rule_tags[0])
            if policy not in {"required","forbidden","contextual"}: fail(errors,cid,"rubric rule lacks escalation policy")
            if policy=="required" and exp.get("should_escalate") is not True: fail(errors,cid,"rubric requires escalation")
            if policy=="forbidden" and exp.get("should_escalate") is not False: fail(errors,cid,"rubric forbids escalation")
        expected_esc="escalation:required" if exp.get("should_escalate") is True else "escalation:not_required"
        if expected_esc not in tags: fail(errors,cid,"escalation tag disagrees with expected")
        sources=case.get("source_basis")
        if not isinstance(sources,list) or not sources: fail(errors,cid,"source_basis must be non-empty"); sources=[]
        for source in sources:
            if not isinstance(source,str) or source.startswith(("/","http:" ,"https:")) or ".." in Path(source).parts or not (ROOT/source).is_file(): fail(errors,cid,f"invalid source_basis: {source!r}")
        encoded=json.dumps(case,ensure_ascii=False)
        for pattern in SECRET_PATTERNS:
            if pattern.search(encoded): fail(errors,cid,"possible production secret or credential")
        if isinstance(state,dict):
            for path,key,value in walk(state):
                if key.lower() in RAW_KEYS: fail(errors,cid,f"raw/unbounded payload key at {path}")
                if isinstance(value,list) and len(value)>500: fail(errors,cid,f"unbounded list at {path}")
        for tag in tags:
            if tag.startswith("pair:"): pairs[tag[5:]].append((cid,tags,state))
    duplicates=[key for key,count in Counter(ids).items() if count>1]
    if duplicates: errors.append(f"benchmark: duplicate case_id: {duplicates}")
    if set(counts)!=REQUIRED_CATEGORIES: errors.append(f"benchmark: category set mismatch: {dict(counts)}")
    for category in REQUIRED_CATEGORIES:
        if counts[category]<5: errors.append(f"benchmark: category {category} has only {counts[category]} cases")
    pair=pairs.get("choice-set-01",[])
    if len(pair)!=2 or not any("option:insufficient_absent" in tags for _,tags,_ in pair) or not any("option:insufficient_present" in tags for _,tags,_ in pair): errors.append("benchmark: missing paired insufficient-evidence calibration cases")
    if len(pair)==2 and pair[0][2]!=pair[1][2]: errors.append("benchmark: paired choice-set states differ")
    if errors:
        print("Jev benchmark validation FAILED", file=sys.stderr)
        for error in errors: print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Jev benchmark validation passed: {len(cases)} cases; " + ", ".join(f"{k}={counts[k]}" for k in sorted(counts)))
    return 0
if __name__=="__main__": raise SystemExit(main())
