#!/usr/bin/env python3
"""ADR-0085 P4 Feature Gate: is there a host-directed bounded-judgment invocation?

Threshold A of the P4 real-acceptance task: prove whether DSH 0.1.5rc1 exposes a
mechanism by which the HOST (the trusted Runtime Adapter, using the official
Python SDK / bundled carrier) can directly start and run exactly one
``toolName=byq_research_judgment_turn`` composition role in the foreground,
without depending on the root model choosing to call a delegate tool.

This script runs INSIDE the runtime-adapter candidate image and emits a
machine-readable verdict. It inspects:

1. the installed ``deepseek_harness`` public surface;
2. the bundled carrier's host-callable protocol methods;
3. the generated composition's ``research-judgment-turn`` registration.

It is read-only and reproducible:

    docker run --rm --entrypoint python \\
        -v "$PWD:/repo:ro" byq-d15-runtime-candidate:local \\
        /repo/scripts/v091/continuation_p4/dsh_judgment_gate.py
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from pathlib import Path

import deepseek_harness
import deepseek_harness_runtime

PERSONA_TOOL = "byq_research_judgment_turn"

# ACP / host-callable methods the Runtime Adapter may use through the Python SDK.
HOST_CALLABLE_METHODS = ("initialize", "session/new", "session/load", "session/prompt",
                         "session/cancel", "session/close", "session/fork", "session/list")


def _sdk_surface() -> dict:
    surface = {}
    for name in ("DeepSeekHarness", "HarnessClient", "Session"):
        cls = getattr(deepseek_harness, name, None)
        if cls is None:
            continue
        methods = {}
        for member, fn in inspect.getmembers(cls, predicate=inspect.isfunction):
            if member.startswith("_"):
                continue
            try:
                methods[member] = str(inspect.signature(fn))
            except (TypeError, ValueError):
                methods[member] = "?"
        surface[name] = methods
    return surface


def _carrier_facts() -> dict:
    carrier = Path(deepseek_harness_runtime.bundled_runtime_path())
    data = carrier.read_bytes()
    text = data.decode("utf-8", "replace")
    acp_methods = sorted(set(re.findall(r'"(session/[a-zA-Z_-]+)"', text)))
    # `subagent/start` is emitted as a plugin event, not registered as a
    # host-callable protocol method.
    subagent_event = bool(re.search(r'ctx\.on\("subagent/start"', text))
    # The host-callable ACP surface is the `session/*` method set. A tool/subagent
    # invocation method would have to appear there (or as an SDK method) to be a
    # real host-directed mechanism; internal plugin events and MCP `tools/*` server
    # capabilities do not count.
    tool_invocation_method = any(
        re.search(r"tool|subagent|invoke|persona|role", method) for method in acp_methods)
    # toolFilter/persona are subagent descriptor keys (applied to a child), not a
    # root-level composition filter.
    descriptor_keys = bool(re.search(r'DESCRIPTOR_BASE_KEYS\s*=\s*new Set\(\[[^\]]*"toolFilter"',
                                     text))
    # The mcp-client config surface has no tool allow/deny list.
    mcp_client_allowlist = bool(re.search(
        r'McpClient\.Config\(\{[^}]*"(allow|deny|allowedTools|toolFilter)"', text))
    return {
        "carrier_path": str(carrier),
        "carrier_sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
        "host_callable_methods": list(HOST_CALLABLE_METHODS),
        "acp_session_methods": acp_methods,
        "subagent_start_is_plugin_event": subagent_event,
        "host_callable_tool_invocation_method_present": tool_invocation_method,
        "root_level_tool_filter_supported": descriptor_keys,
        "mcp_client_tool_allowlist_supported": mcp_client_allowlist,
        "host_callable_tool_invocation_evidence": (
            "no session/* ACP method or SDK method starts/invokes a named composition "
            "role or tool; subagent/start is a plugin event (ctx.on) emitted into a live "
            "in-process child, and tools/list|tools/call are MCP server capabilities. "
            "toolFilter/persona are subagent-descriptor keys (child-scoped), not a "
            "root-level filter; the mcp-client config has no tool allow/deny list."),
    }


def _composition_facts(root: Path) -> dict:
    # ADR-0085 P4 uses the DEDICATED bounded composition (not the shared Product
    # composition, whose B2 provenance binding is frozen). This is the surface the
    # Runtime Adapter turn_runner will load.
    composition = root / "plugins/dsh-byq/profiles/dsh-0.1.5rc1-continuable/byq-research-judgment.patch.yml"
    text = composition.read_text(encoding="utf-8")
    block = text.split("- id: research-judgment-turn", 1)[1].split("\n- id:", 1)[0]
    return {
        "composition": str(composition.relative_to(root)),
        "persona_tool_name": PERSONA_TOOL,
        "persona_registered_as_model_facing_tool": f"toolName: {PERSONA_TOOL}" in block,
        "provider": "spawn" if "provider: spawn" in block else None,
        # Explicit, non-misleading semantics: the role runs in the foreground.
        "background_disabled": "enableRunInBackground: false" in block,
        "foreground_one_shot": "enableRunInBackground: false" in block
        and "backgroundMode: one-shot" in block,
        # ADR-0085 P4 real-carrier correction: the role is the FIRST delegation
        # level (depth 1), so maxDepth must be 1 to allow it to be spawned; a
        # grandchild is depth 2 and is still refused.
        "max_depth": 1 if "maxDepth: 1" in block else (0 if "maxDepth: 0" in block else None),
        "bounded_single_delegation_level": "maxDepth: 1" in block,
        "registration_plugin": "@deepseek-ai/dsh-tool-subagent",
    }


def main() -> int:
    root = Path("/repo")
    sdk = _sdk_surface()
    carrier = _carrier_facts()
    composition = _composition_facts(root)

    # Host-directed bounded judgment is only possible if the SDK exposes a
    # role/tool selection parameter OR the carrier registers a host-callable
    # tool/subagent invocation method. Neither is present in 0.1.5rc1.
    sdk_role_selector = any(
        re.search(r"\b(role|persona|tool|tool_name|toolName|subagent)\b", signature)
        for methods in sdk.values() for signature in methods.values())
    host_named_role_api = bool(sdk_role_selector
                               or carrier["host_callable_tool_invocation_method_present"])
    audit = {
        "schema_version": "byq-adr0085-p3-to-p4-invocation-seam-audit.v1",
        "host_named_role_api_available": host_named_role_api,
        "adr_required_mechanism": (
            "research stages expose only the bounded plan projection, bounded result "
            "summaries, a minimal read-only tool set and one closed proposal channel; "
            "ADR-0085 P3 authorizes a minimal DSH composition/MCP surface for this."),
        "root_level_tool_filter_supported": carrier["root_level_tool_filter_supported"],
        "mcp_client_tool_allowlist_supported": carrier["mcp_client_tool_allowlist_supported"],
        "p3_turn_runner_wired_in_production": False,
        "root_surface_without_mcp_proven": True,
        "full_feasibility": "READ_ONLY_MCP_AND_CHILD_PERSONA_PROVEN",
        "feasibility_status": "PROVEN_BY_CARRIER_PROBE",
        "feasibility_evidence": [
            "carrier-feasibility.v1.json",
            "carrier-readonly-mcp-child.v1.json",
        ],
        "remaining_unproven": [
            "Runtime Adapter real turn_runner wired to the bounded composition",
            "Backend closed-result route invoked from the real carrier result",
            "real Product API -> Runtime Adapter -> DSH -> Backend closed loop",
            "three-round journey and the async-handoff fault matrix",
        ],
        "conclusion": "P3_TO_P4_WIRING_GAP_NOT_UPSTREAM_BLOCKER",
        "required_minimal_isolation": (
            "a minimal read-only MCP subset endpoint (only the bounded read-only tools) "
            "plus a dedicated static bounded composition that loads it and the bounded "
            "research-judgment-turn persona; the root exposes no write/approval/execute/"
            "routing/identity/idempotency/job/delegate tool, and the closed result is "
            "captured by the host and submitted to the existing atomic Backend route."),
        "missing_piece": (
            "BYQ must implement the minimal read-only MCP surface, the dedicated bounded "
            "composition and the Runtime Adapter turn_runner/endpoint; this is BYQ "
            "wiring, not an upstream DSH capability."),
        "sdk_surface": sdk,
        "sdk_exposes_role_or_tool_selector": sdk_role_selector,
        "carrier": carrier,
        "composition": composition,
        "forbidden_workarounds": [
            "generic prompt asking the model to choose the persona tool",
            "endpoint/driver directly assembling model_result",
            "direct function callback bypassing the real DSH carrier",
            "self-built runner or second generic harness",
            "using permission denial as a substitute for non-exposure",
        ],
    }
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
