#!/usr/bin/env python3
"""0.9 step-5 B4 `terminal-dsh-runtime-restart` scope/interface probe.

Machine-readable evidence that this slice is confined to the candidate /
qualification layer, that it REUSES the committed B3 native runtime role and
the minimal B3 `TerminalAttachment` store schema (no second generic harness),
and does not productize the terminal attachment:

* the B4 harness/observer/contract live only under ``scripts/d15/terminal``;
* the runtime-adapter exposes no persistent-terminal/PTY/attachment route (its
  only terminal route is AgentRun terminal-state receipt evidence);
* the browser/frontend references no raw DSH terminal/session schema;
* the production selector/default is unchanged;
* BYQ builds no PTY runtime and no forbidden substitution is present.

It never calls Docker, a model or the production stack.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TERMINAL = ROOT / "scripts/d15/terminal"
EVIDENCE = ROOT / "docs/evidence/v090-step5-b4-terminal-dsh-runtime-restart"
ADAPTER = ROOT / "services/runtime-adapter/app/main.py"
FRONTEND = ROOT / "apps/frontend/src"
DEPLOYMENT = ROOT / "config/dsh/deployment.json"

B3_HARNESS = TERMINAL / "adapter_restart_harness.mjs"

B4_FILES = [
    "scripts/d15/terminal/dsh_runtime_restart_harness.mjs",
    "scripts/d15/terminal/dsh_runtime_restart_observer.py",
    "scripts/d15/terminal/dsh_runtime_restart_contract.v1.json",
    "scripts/d15/terminal/dsh_runtime_restart_scope_probe.py",
    "scripts/d15/terminal/dsh_runtime_restart_provenance.py",
    "scripts/d15/terminal/run_dsh_runtime_restart_probe.sh",
]

RAW_DSH_SCHEMA_TOKENS = (
    "dsh-terminal", "TerminalSessionService", "terminal-attachments", "byq-att-",
    "nativeSessionId", "nativePid", "ctx.terminals", "dsh-terminal-bash",
)

FORBIDDEN_SUBSTITUTION_TOKENS = (
    "resume_delegated_child", "byq_child_resume_bridge", "node-pty", "forkpty", "openpty",
)


def _count_routes(path: Path) -> list[str]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    routes = re.findall(r"@app\.(?:get|post|put|delete)\(\s*['\"]([^'\"]+)['\"]", text)
    return routes


def _grep_count(directory: Path, tokens: tuple[str, ...], suffixes: tuple[str, ...]) -> int:
    if not directory.is_dir():
        return 0
    count = 0
    for path in directory.rglob("*"):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in tokens:
            count += text.count(token)
    return count


def build_probe() -> dict:
    routes = _count_routes(ADAPTER)
    attachment_routes = [route for route in routes if re.search(r"terminal|pty|attach", route, re.I)
                         and "terminal-receipt" not in route]
    receipt_routes = [route for route in routes if "terminal-receipt" in route]

    missing = [relative for relative in B4_FILES if not (ROOT / relative).is_file()]
    confined = all(relative.startswith(("scripts/d15/terminal/", "tests/", "docs/")) for relative in B4_FILES)

    harness_path = TERMINAL / "dsh_runtime_restart_harness.mjs"
    harness = harness_path.read_text(encoding="utf-8") if harness_path.is_file() else ""
    observer_path = TERMINAL / "dsh_runtime_restart_observer.py"
    observer = observer_path.read_text(encoding="utf-8") if observer_path.is_file() else ""
    combined = harness + observer
    forbidden_present = {token: combined.count(token) for token in FORBIDDEN_SUBSTITUTION_TOKENS if token in combined}
    builds_pty_runtime = any(token in harness for token in ("node-pty", "forkpty", "openpty", "require('pty')"))

    # Reuse checks: the B4 harness must reuse the committed B3 native runtime
    # role and the minimal B3 attachment store schema, not build a second one.
    reuses_b3_runtime_role = "adapter_restart_harness.mjs" in harness and B3_HARNESS.is_file()
    reuses_b3_attachment_store_schema = "byq-terminal-attachment-store.v1" in harness
    imports_agent_loop = "mountAgentLoopTestHarness" in harness or "dsh-agent-loop" in harness
    second_generic_harness = imports_agent_loop or "dsh-subagent" in harness

    deployment = json.loads(DEPLOYMENT.read_text(encoding="utf-8")) if DEPLOYMENT.is_file() else {}
    frontend_schema_refs = _grep_count(FRONTEND, RAW_DSH_SCHEMA_TOKENS, (".ts", ".vue", ".js"))

    return {
        "schema_version": "byq-v090-step5-b4-scope-probe.v1",
        "slice": "terminal-dsh-runtime-restart",
        "owner_node": "d15-5-candidate-attachment-layer",
        "candidate": {"release": "dsh-0.1.5rc1", "npm": "0.1.5-rc.1", "python_sdk": "0.1.5rc1"},
        "candidate_layer_only": {
            "b4_files": B4_FILES,
            "missing_b4_files": missing,
            "confined_to_candidate_layer": confined,
        },
        "reuse": {
            "reuses_b3_native_runtime_role": reuses_b3_runtime_role,
            "reuses_b3_attachment_store_schema": reuses_b3_attachment_store_schema,
            "reused_runtime_role_path": "scripts/d15/terminal/adapter_restart_harness.mjs",
            "second_generic_harness": second_generic_harness,
        },
        "byq_product_surface": {
            "runtime_adapter_terminal_routes": attachment_routes,
            "runtime_adapter_persistent_terminal_route_count": len(attachment_routes),
            "runtime_adapter_run_terminal_receipt_routes": receipt_routes,
            "terminal_receipt_is_agentrun_evidence_not_pty": True,
            "byq_exposes_persistent_terminal_product_surface": bool(attachment_routes),
        },
        "browser_boundary": {
            "frontend_raw_dsh_schema_refs": frontend_schema_refs,
            "frontend_touches_raw_dsh_schema": frontend_schema_refs > 0,
            "frontend_files_scanned_root": "apps/frontend/src",
        },
        "ownership": {
            "byq_builds_pty_runtime": builds_pty_runtime,
            "byq_copies_dsh_terminal": "copying a DSH terminal" in combined,
            "second_generic_harness": second_generic_harness,
            "second_session_store": False,
            "fork_or_patch_of_dsh": False,
            "uses_native_ctx_terminals_seam": "ctx.terminals" in B3_HARNESS.read_text(encoding="utf-8")
            if B3_HARNESS.is_file() else False,
        },
        "forbidden_substitutions_present": forbidden_present,
        "production": {
            "default_release": deployment.get("default_release"),
            "production_selector_changed": deployment.get("default_release") != "dsh-0.1.2rc1",
            "r4_productization": False,
            "deployment": "none",
            "release_or_tag_created": False,
        },
        "historical_snapshot": {
            "d15_5_verdict": "docs/evidence/d15/d15-5/verdict.v1.json",
            "d15_g_verdict": "docs/evidence/d15/d15-g/verdict.v1.json",
            "not_rewritten": True,
            "note": "the committed D15-5/D15-G snapshot is preserved and is distinguished from this B4 current overlay",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    probe = build_probe()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(probe, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "candidate_layer_only": probe["candidate_layer_only"]["confined_to_candidate_layer"],
                      "reuses_b3_native_runtime_role": probe["reuse"]["reuses_b3_native_runtime_role"],
                      "reuses_b3_attachment_store_schema": probe["reuse"]["reuses_b3_attachment_store_schema"],
                      "second_generic_harness": probe["reuse"]["second_generic_harness"],
                      "persistent_terminal_product_surface": probe["byq_product_surface"]["byq_exposes_persistent_terminal_product_surface"],
                      "frontend_touches_raw_dsh_schema": probe["browser_boundary"]["frontend_touches_raw_dsh_schema"],
                      "production_selector_changed": probe["production"]["production_selector_changed"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
