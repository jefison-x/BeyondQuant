#!/usr/bin/env python3
"""Generate the 0.1.2rc1 BYQ SDK invocation patch and closed identity."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml"
TEMPLATE = ROOT / "plugins/dsh-byq/profiles/dsh-0.1.2rc1/byq-product.patch.template.yml"
OUTPUT = ROOT / "plugins/dsh-byq/profiles/dsh-0.1.2rc1/byq-product.patch.yml"
IDENTITY = ROOT / "plugins/dsh-byq/profiles/dsh-0.1.2rc1/byq-product.identity.json"
RUNTIME_PACKAGE = ROOT / "plugins/dsh-byq/runtime/package.json"
MARKER = "# @byq-candidate-insert@"
DELEGATES = (
    "byq_delegate_market_research",
    "byq_delegate_factor_research",
    "byq_delegate_strategy_research",
    "byq_delegate_backtest_analysis",
    "byq_delegate_ml_research",
)
FORBIDDEN_TOOLS = (
    "bash", "pwsh", "jobs", "fs", "fs_search", "str_replace_editor",
    "subagent", "subagent_fork", "workflow", "todo_write", "goal", "ralph",
    "web_fetch", "list_agents", "send_message",
)


def _block(text: str, start: str, end: str | None) -> str:
    start_at = text.index(start)
    end_at = len(text) if end is None else text.index(end, start_at)
    return text[start_at:end_at].rstrip()


def _indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line else line for line in text.splitlines())


def render_patch() -> str:
    runtime_package = json.loads(RUNTIME_PACKAGE.read_text(encoding="utf-8"))
    for field in ("name", "version"):
        if not isinstance(runtime_package.get(field), str) or not runtime_package[field]:
            raise ValueError(f"runtime plugin package must declare a non-empty {field}")
    source = SOURCE.read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(MARKER) != 1:
        raise ValueError("candidate template must contain exactly one insert marker")
    provider = _block(source, "- id: llm-opencode", "- id: skills")
    provider = provider.replace(
        "- id: llm-opencode\n  name: '@deepseek-ai/dsh-llm-pi-ai'\n",
        "- id: llm-pi-ai\n",
    )
    blocks = [
        _block(source, "- id: trusted-time-context", "# OpenCode Go"),
        _block(source, "- id: delegate-market-research", "# Qualified and Product-enabled"),
        _block(source, "- id: mcp-byq", None),
    ]
    inserted = "\n\n".join(blocks)
    inserted = inserted.replace(
        "name: '../runtime/byq-runtime-time-context.js'",
        "name: 'file:///opt/byq/runtime/byq-runtime-time-context.js'",
    )
    inserted = inserted.replace(
        "    enableRunInBackground: false\n",
        "    enableRunInBackground: false\n    backgroundMode: one-shot\n",
    )
    rendered = template.replace(
        MARKER,
        provider.rstrip() + "\n\n- insert:\n" + _indent(inserted, 4),
    )
    for tool in DELEGATES:
        if rendered.count(f"toolName: {tool}") != 1:
            raise ValueError(f"candidate patch must define exactly one {tool}")
    for required in (
        "failOnStartupError: true", "includeDefaultRoots: false", "watch: false",
        "fetch: false", "backgroundMode: one-shot", "maxDepth: 1",
    ):
        if required not in rendered:
            raise ValueError(f"candidate patch lacks required boundary: {required}")
    for inherited_security_service in ("subprocess", "bash-sandbox", "permission-presets"):
        if f"- id: {inherited_security_service}\n  disabled: true" in rendered:
            raise ValueError(
                f"candidate patch must preserve official {inherited_security_service} service"
            )
    return rendered.rstrip() + "\n"


def render_identity(patch: str) -> str:
    value = {
        "schema_version": "dsh-candidate-profile-identity.v1",
        "release_id": "dsh-0.1.2rc1",
        "base_profile": "sdk",
        "profile": "byq-product-candidate",
        "patch": str(OUTPUT.relative_to(ROOT)),
        "patch_sha256": "sha256:" + hashlib.sha256(patch.encode()).hexdigest(),
        "composition_hash": "sha256:" + hashlib.sha256(patch.encode()).hexdigest(),
        "enabled_plugin_ids": ["compaction", "guard", "web-search"],
        "telemetry": "disabled",
        "permission_mode": "read-only",
        "skills": {
            "include_default_roots": False,
            "watch": False,
            "root": "/opt/dsh/bundles/dsh-byq/skills",
        },
        "delegates": list(DELEGATES),
        "delegate_background_mode": "one-shot",
        "delegate_max_depth": 1,
        "forbidden_tools": list(FORBIDDEN_TOOLS),
        "mcp": {"server": "byq", "fail_on_startup_error": True},
    }
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("generate", "check"))
    args = parser.parse_args()
    patch = render_patch()
    identity = render_identity(patch)
    if args.command == "generate":
        OUTPUT.write_text(patch, encoding="utf-8")
        IDENTITY.write_text(identity, encoding="utf-8")
    else:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != patch:
            raise SystemExit("generated candidate patch is stale")
        if not IDENTITY.is_file() or IDENTITY.read_text(encoding="utf-8") != identity:
            raise SystemExit("generated candidate profile identity is stale")
    print(json.dumps({"status": "ok", "check": args.command == "check"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
