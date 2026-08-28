#!/usr/bin/env python3
"""Validate BYQ's DSH plugin registry and build the Product composition.

The registry is declarative and Git-managed.  This command never downloads,
installs, or mutates the running DSH runtime; package installation remains a
normal image build step guarded by the exact npm manifest and lockfile.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DIR = ROOT / "plugins/dsh-byq/registry"
REGISTRY_PATH = REGISTRY_DIR / "plugins.json"
PROFILE_PATH = REGISTRY_DIR / "profiles.json"
AGENT_PATH = REGISTRY_DIR / "agent-capabilities.json"
TEMPLATE_PATH = ROOT / "plugins/dsh-byq/compositions/templates/byq-product-sdk.cordis.yml"
OUTPUT_PATH = ROOT / "plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml"
IDENTITY_PATH = ROOT / "plugins/dsh-byq/compositions/byq-product-sdk.identity.json"
MANIFEST_PATH = ROOT / "services/runtime-adapter/runtime/package.json"
LOCK_PATH = ROOT / "services/runtime-adapter/runtime/package-lock.json"

STATES = {"AVAILABLE", "QUALIFIED", "BLOCKED", "REJECTED", "DEPRECATED"}
RISKS = {"LOW", "MEDIUM", "HIGH", "PROHIBITED"}
COMPATIBILITY = {"COMPATIBLE", "BLOCKED_BY_RUNTIME_VERSION", "BLOCKED_BY_SECURITY_BOUNDARY"}
CAPABILITIES = {
    "network", "web_search", "web_fetch", "filesystem_read", "filesystem_write",
    "shell", "terminal", "code_execution", "git", "database", "subprocess",
    "persistent_storage", "runtime_mutation", "user_interaction",
}
PROHIBITED_CAPABILITIES = {
    "filesystem_write", "shell", "terminal", "code_execution", "git", "database",
    "subprocess", "runtime_mutation",
}
EXACT_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$")
INTEGRITY = re.compile(r"^sha512-[A-Za-z0-9+/]+={0,2}$")
PLUGIN_MARKER = "# @byq-plugin-entries@"
AGENT_MARKER = re.compile(r"^(?P<indent>\s*)# @byq-agent-tools:(?P<agent>[a-z0-9_-]+)@\s*$")


class RegistryError(ValueError):
    """A fail-closed registry, qualification, or composition error."""


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot load {path.relative_to(ROOT)}: {exc}") from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RegistryError(message)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def load_and_validate(*, profile_name: str | None = None) -> dict[str, Any]:
    registry = _load(REGISTRY_PATH)
    profiles = _load(PROFILE_PATH)
    agents = _load(AGENT_PATH)
    manifest = _load(MANIFEST_PATH)
    lock = _load(LOCK_PATH)

    _require(registry.get("schema_version") == "dsh-plugin-registry.v1", "unknown registry schema")
    baseline = registry.get("runtime_baseline")
    _require(isinstance(baseline, dict), "runtime_baseline is required")
    _require(baseline.get("python_sdk") == "0.1.1rc1", "unexpected Python SDK baseline")
    _require(baseline.get("runtime_bin") == "0.1.1rc1", "unexpected runtime-bin baseline")
    _require(baseline.get("npm_runtime") == "0.1.1-rc.1", "unexpected npm runtime baseline")

    known_agents = agents.get("agents")
    _require(isinstance(known_agents, dict) and known_agents, "agent capability mapping is required")
    plugins = registry.get("plugins")
    _require(isinstance(plugins, list) and plugins, "registry plugins must be a non-empty list")
    by_id: dict[str, dict[str, Any]] = {}
    all_packages: dict[str, dict[str, str]] = {}

    for plugin in plugins:
        _require(isinstance(plugin, dict), "each plugin descriptor must be an object")
        plugin_id = plugin.get("id")
        _require(isinstance(plugin_id, str) and re.fullmatch(r"[a-z0-9-]+", plugin_id) is not None,
                 "plugin id must be kebab-case")
        _require(plugin_id not in by_id, f"duplicate plugin id: {plugin_id}")
        by_id[plugin_id] = plugin
        _require(isinstance(plugin.get("display_name"), str) and plugin["display_name"],
                 f"{plugin_id}: display_name is required")
        source = plugin.get("source")
        _require(source == {"kind": "official_npm", "publisher": "deepseek-ai"},
                 f"{plugin_id}: only the official DeepSeek npm source is accepted")
        qualification = plugin.get("qualification")
        _require(isinstance(qualification, dict), f"{plugin_id}: qualification is required")
        state = qualification.get("state")
        _require(state in STATES, f"{plugin_id}: unknown qualification state {state!r}")
        evidence = qualification.get("evidence")
        _require(isinstance(evidence, list) and evidence and all(isinstance(x, str) and x for x in evidence),
                 f"{plugin_id}: qualification evidence is required")
        checks = qualification.get("checks")
        _require(isinstance(checks, dict), f"{plugin_id}: qualification checks are required")
        required_checks = {
            "package", "integrity", "dependency_closure", "peer_compatibility", "capability_audit",
            "credential_audit", "secret_leakage", "agent_boundary", "mcp_boundary",
        }
        _require(required_checks <= set(checks), f"{plugin_id}: incomplete qualification checks")
        if state == "QUALIFIED":
            _require(all(checks.get(name) is True for name in required_checks),
                     f"{plugin_id}: QUALIFIED requires every mandatory check to pass")
            for name in ("startup", "composition_initialize", "lifecycle", "contract_tests", "architecture_tests"):
                _require(checks.get(name) is True, f"{plugin_id}: QUALIFIED requires {name}")

        compatibility = plugin.get("compatibility")
        _require(isinstance(compatibility, dict), f"{plugin_id}: compatibility is required")
        _require(compatibility.get("status") in COMPATIBILITY,
                 f"{plugin_id}: invalid compatibility status")
        _require(compatibility.get("dsh_runtime") == baseline["npm_runtime"],
                 f"{plugin_id}: runtime version mismatch")
        _require(compatibility.get("python_sdk") == baseline["python_sdk"],
                 f"{plugin_id}: Python SDK version mismatch")
        _require(compatibility.get("runtime_bin") == baseline["runtime_bin"],
                 f"{plugin_id}: runtime-bin version mismatch")

        capabilities = plugin.get("capabilities")
        _require(isinstance(capabilities, dict) and set(capabilities) == CAPABILITIES,
                 f"{plugin_id}: capability set must be complete and closed")
        _require(all(isinstance(value, bool) for value in capabilities.values()),
                 f"{plugin_id}: capability values must be booleans")
        risk = plugin.get("risk")
        _require(isinstance(risk, dict) and risk.get("level") in RISKS,
                 f"{plugin_id}: valid risk metadata is required")
        _require(isinstance(risk.get("reasons"), list) and risk["reasons"],
                 f"{plugin_id}: risk reasons are required")
        policy = plugin.get("product_policy")
        _require(isinstance(policy, dict) and isinstance(policy.get("enabled"), bool),
                 f"{plugin_id}: product policy is required")
        credentials = plugin.get("credentials")
        _require(isinstance(credentials, dict) and isinstance(credentials.get("required"), bool),
                 f"{plugin_id}: credential policy is required")
        credential_refs = credentials.get("references")
        _require(isinstance(credential_refs, list) and all(
            isinstance(item, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*", item) is not None
            for item in credential_refs
        ), f"{plugin_id}: credential references must be environment identifiers")
        _require(not credentials["required"] or bool(credential_refs),
                 f"{plugin_id}: required credential reference is missing")
        _require(credentials["required"] or not credential_refs,
                 f"{plugin_id}: optional-free plugin cannot declare credential references")
        if policy["enabled"]:
            _require(state == "QUALIFIED", f"{plugin_id}: AVAILABLE/BLOCKED cannot be enabled")
            _require(risk["level"] != "PROHIBITED", f"{plugin_id}: prohibited risk cannot be enabled")
            dangerous = sorted(name for name in PROHIBITED_CAPABILITIES if capabilities[name])
            _require(not dangerous, f"{plugin_id}: prohibited capability escalation: {dangerous}")
            _require(compatibility["status"] == "COMPATIBLE", f"{plugin_id}: incompatible plugin cannot be enabled")

        assignments = plugin.get("agents")
        _require(isinstance(assignments, dict), f"{plugin_id}: agent assignments are required")
        allowed = assignments.get("allowed")
        denied = assignments.get("denied")
        _require(isinstance(allowed, list) and isinstance(denied, list),
                 f"{plugin_id}: allowed/denied agents must be lists")
        _require(not (set(allowed) & set(denied)), f"{plugin_id}: agent assignment overlaps")
        _require(set(allowed) | set(denied) <= set(known_agents), f"{plugin_id}: unknown agent assignment")

        packages = plugin.get("packages")
        _require(isinstance(packages, list) and packages, f"{plugin_id}: exact packages are required")
        for package in packages:
            _require(isinstance(package, dict), f"{plugin_id}: package entry must be an object")
            name, version, integrity = package.get("name"), package.get("version"), package.get("integrity")
            _require(isinstance(name, str) and name.startswith("@deepseek-ai/dsh-"),
                     f"{plugin_id}: unknown package source")
            _require(isinstance(version, str) and EXACT_VERSION.fullmatch(version) is not None,
                     f"{plugin_id}: package version must be exact")
            _require(version == baseline["npm_runtime"], f"{plugin_id}: accidental prerelease mixing")
            _require(isinstance(integrity, str) and INTEGRITY.fullmatch(integrity) is not None,
                     f"{plugin_id}: package integrity is invalid")
            prior = all_packages.get(name)
            current = {"version": version, "integrity": integrity}
            _require(prior in (None, current), f"{plugin_id}: conflicting package declaration for {name}")
            all_packages[name] = current

    dependencies = manifest.get("dependencies", {})
    lock_packages = lock.get("packages", {})
    for name, package in all_packages.items():
        _require(dependencies.get(name) == package["version"], f"manifest missing exact pin for {name}")
        locked = lock_packages.get(f"node_modules/{name}")
        _require(isinstance(locked, dict), f"lockfile missing {name}")
        _require(locked.get("version") == package["version"], f"lockfile version mismatch for {name}")
        _require(locked.get("integrity") == package["integrity"], f"lockfile integrity mismatch for {name}")

    for name, version in dependencies.items():
        if name.startswith("@deepseek-ai/dsh-"):
            _require(version == baseline["npm_runtime"], f"manifest mixes DSH version for {name}")
            _require(EXACT_VERSION.fullmatch(version) is not None, f"manifest range forbidden for {name}")
    for path, package in lock_packages.items():
        name = path.removeprefix("node_modules/")
        if name.startswith("@deepseek-ai/dsh-"):
            _require(package.get("version") == baseline["npm_runtime"], f"lockfile mixes DSH version for {name}")
            optional_peers = package.get("peerDependenciesMeta", {})
            for peer_name, peer_range in package.get("peerDependencies", {}).items():
                if optional_peers.get(peer_name, {}).get("optional") is True:
                    continue
                peer = lock_packages.get(f"node_modules/{peer_name}")
                _require(isinstance(peer, dict), f"peer dependency missing for {name}: {peer_name}")
                if peer_name.startswith("@deepseek-ai/dsh-"):
                    _require(peer.get("version") == baseline["npm_runtime"],
                             f"peer dependency version mismatch for {name}: {peer_name}")
                    _require(isinstance(peer_range, str) and baseline["npm_runtime"] in peer_range,
                             f"peer dependency range mismatch for {name}: {peer_name}")

    profile_name = profile_name or profiles.get("product_default")
    profile = profiles.get("profiles", {}).get(profile_name)
    _require(isinstance(profile, dict), f"unknown Product plugin profile: {profile_name}")
    profile_plugins = profile.get("plugins")
    _require(isinstance(profile_plugins, list) and len(profile_plugins) == len(set(profile_plugins)),
             f"{profile_name}: duplicate or invalid profile plugin")
    for plugin_id in profile_plugins:
        _require(plugin_id in by_id, f"{profile_name}: unknown plugin {plugin_id}")
        _require(by_id[plugin_id]["product_policy"]["enabled"],
                 f"{profile_name}: disabled plugin {plugin_id} cannot enter composition")

    for agent_id, mapping in known_agents.items():
        assigned = mapping.get("plugins")
        _require(isinstance(assigned, list) and len(assigned) == len(set(assigned)),
                 f"{agent_id}: invalid plugin assignment")
        for plugin_id in assigned:
            _require(plugin_id in by_id, f"{agent_id}: unknown assigned plugin {plugin_id}")
            _require(agent_id in by_id[plugin_id]["agents"]["allowed"],
                     f"{agent_id}: plugin assignment exceeds registry allowlist for {plugin_id}")
        for plugin_id in profile_plugins:
            plugin = by_id[plugin_id]
            exposed = plugin.get("tools", {}).get("exposed", [])
            if exposed and agent_id in plugin["agents"]["denied"]:
                _require(plugin_id not in assigned, f"{agent_id}: denied plugin assigned: {plugin_id}")

    return {
        "registry": registry, "profiles": profiles, "agents": agents, "manifest": manifest,
        "lock": lock, "plugins": by_id, "profile_name": profile_name, "profile": profile,
    }


def _yaml_scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _yaml_lines(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key in sorted(value):
            child = value[key]
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(_yaml_lines(child, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(child)}")
        return lines
    if isinstance(value, list):
        lines = []
        for child in value:
            if isinstance(child, dict):
                keys = sorted(child)
                first = keys[0]
                first_value = child[first]
                if isinstance(first_value, (dict, list)):
                    lines.append(f"{prefix}- {first}:")
                    lines.extend(_yaml_lines(first_value, indent + 4))
                else:
                    lines.append(f"{prefix}- {first}: {_yaml_scalar(first_value)}")
                for key in keys[1:]:
                    item = child[key]
                    if isinstance(item, (dict, list)):
                        lines.append(f"{prefix}  {key}:")
                        lines.extend(_yaml_lines(item, indent + 4))
                    else:
                        lines.append(f"{prefix}  {key}: {_yaml_scalar(item)}")
            else:
                lines.append(f"{prefix}- {_yaml_scalar(child)}")
        return lines
    return [f"{prefix}{_yaml_scalar(value)}"]


def build(profile_name: str | None = None, policy: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    data = load_and_validate(profile_name=profile_name)
    managed_assignments: dict[str, list[str]] | None = None
    if policy is None:
        enabled_ids = sorted(data["profile"]["plugins"])
        identity_profile = data["profile_name"]
    else:
        _require(set(policy) == {"schema_version", "policy_version", "enabled_plugin_ids", "agent_assignments"},
                 "managed policy snapshot has an invalid closed schema")
        _require(policy["schema_version"] == "plugin-deployment-policy.v1", "unknown managed policy schema")
        _require(isinstance(policy["policy_version"], int) and policy["policy_version"] > 0,
                 "managed policy version must be positive")
        enabled_ids = policy["enabled_plugin_ids"]
        _require(isinstance(enabled_ids, list) and len(enabled_ids) == len(set(enabled_ids)),
                 "managed policy plugin IDs must be a unique array")
        enabled_ids = sorted(enabled_ids)
        managed_assignments = policy["agent_assignments"]
        _require(isinstance(managed_assignments, dict) and set(managed_assignments) == set(enabled_ids),
                 "managed policy assignments must exactly match enabled plugins")
        for plugin_id in enabled_ids:
            _require(plugin_id in data["plugins"], f"managed policy has unknown plugin {plugin_id}")
            plugin = data["plugins"][plugin_id]
            _require(plugin["qualification"]["state"] == "QUALIFIED",
                     f"managed policy plugin is not QUALIFIED: {plugin_id}")
            _require(plugin["risk"]["level"] not in {"HIGH", "PROHIBITED"},
                     f"managed policy plugin risk is forbidden: {plugin_id}")
            _require(not any(plugin["capabilities"][name] for name in PROHIBITED_CAPABILITIES),
                     f"managed policy plugin capability is forbidden: {plugin_id}")
            assigned = managed_assignments[plugin_id]
            _require(isinstance(assigned, list) and len(assigned) == len(set(assigned)),
                     f"managed policy assignment is invalid: {plugin_id}")
            _require(set(assigned) <= set(plugin["agents"]["allowed"]),
                     f"managed policy assignment exceeds allowlist: {plugin_id}")
        identity_profile = f"managed-v{policy['policy_version']}"
    entries: list[dict[str, Any]] = []
    tools_by_agent: dict[str, set[str]] = {agent: set() for agent in data["agents"]["agents"]}
    versions: dict[str, str] = {}
    for plugin_id in enabled_ids:
        plugin = data["plugins"][plugin_id]
        entries.extend(plugin.get("composition", {}).get("entries", []))
        for package in plugin["packages"]:
            versions[package["name"]] = package["version"]
        assigned_agents = managed_assignments[plugin_id] if managed_assignments is not None else plugin["agents"]["allowed"]
        for agent_id in assigned_agents:
            if managed_assignments is not None or plugin_id in data["agents"]["agents"][agent_id]["plugins"]:
                tools_by_agent[agent_id].update(plugin.get("tools", {}).get("exposed", []))
    ids = [entry.get("id") for entry in entries]
    _require(all(isinstance(item, str) and item for item in ids), "composition entry id is required")
    _require(len(ids) == len(set(ids)), "duplicate generated composition entry id")
    entries.sort(key=lambda item: item["id"])

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    _require(template.count(PLUGIN_MARKER) == 1, "composition template plugin marker is invalid")
    plugin_yaml = "\n".join(_yaml_lines(entries))
    body = template.replace(PLUGIN_MARKER, plugin_yaml)
    rendered: list[str] = []
    seen_agent_markers: set[str] = set()
    for line in body.splitlines():
        match = AGENT_MARKER.match(line)
        if not match:
            rendered.append(line)
            continue
        agent_id = match.group("agent")
        _require(agent_id in tools_by_agent, f"composition template has unknown agent marker {agent_id}")
        seen_agent_markers.add(agent_id)
        indent = match.group("indent")
        rendered.extend(f"{indent}- {tool}" for tool in sorted(tools_by_agent[agent_id]))
    body = "\n".join(rendered).rstrip() + "\n"
    required_markers = {
        agent for agent, tools in tools_by_agent.items()
        if tools and data["agents"]["agents"][agent].get("kind") == "subagent"
    }
    _require(required_markers <= seen_agent_markers,
             f"composition template missing agent tool markers: {sorted(required_markers - seen_agent_markers)}")

    identity_input = {
        "schema_version": "dsh-composition-identity.v1",
        "profile": identity_profile,
        "runtime_baseline": data["registry"]["runtime_baseline"],
        "enabled_plugin_ids": enabled_ids,
        "qualified_versions": dict(sorted(versions.items())),
        "agent_assignments": (
            {agent_id: {**mapping, "plugins": sorted(
                plugin_id for plugin_id in enabled_ids if agent_id in (managed_assignments or {}).get(plugin_id, [])
            )} for agent_id, mapping in data["agents"]["agents"].items()}
            if managed_assignments is not None else data["agents"]["agents"]
        ),
    }
    digest = hashlib.sha256(_canonical(identity_input) + b"\n" + body.encode()).hexdigest()
    identity = {**identity_input, "composition_hash": f"sha256:{digest}"}
    header = (
        "# GENERATED by scripts/dsh/plugin_registry.py; do not edit directly.\n"
        f"# plugin-profile: {identity_profile}\n"
        f"# composition-hash: sha256:{digest}\n"
    )
    return header + body, identity


def write_or_check(*, profile_name: str | None, check: bool, policy_path: Path | None = None,
                   output_path: Path = OUTPUT_PATH, identity_path: Path = IDENTITY_PATH) -> None:
    policy = _load(policy_path) if policy_path is not None else None
    composition, identity = build(profile_name, policy)
    identity_text = json.dumps(identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if check:
        _require(output_path.read_text(encoding="utf-8") == composition, "generated composition is stale")
        _require(identity_path.read_text(encoding="utf-8") == identity_text, "composition identity is stale")
        return
    output_path.write_text(composition, encoding="utf-8")
    identity_path.write_text(identity_text, encoding="utf-8")


def qualification_report(data: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for plugin_id in sorted(data["plugins"]):
        plugin = data["plugins"][plugin_id]
        state = plugin["qualification"]["state"]
        enabled = plugin["product_policy"]["enabled"] and plugin_id in data["profile"]["plugins"]
        rows.append({
            "id": plugin_id,
            "state": "ENABLED" if enabled else state,
            "qualification_state": state,
            "enabled": enabled,
            "risk": plugin["risk"]["level"],
            "allowed_agents": plugin["agents"]["allowed"],
            "reason": plugin["qualification"]["reason"],
        })
    return {"profile": data["profile_name"], "plugins": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "qualify", "catalog"):
        command = sub.add_parser(name)
        command.add_argument("--profile")
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--profile")
    build_parser.add_argument("--check", action="store_true")
    build_parser.add_argument("--policy-file", type=Path)
    build_parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    build_parser.add_argument("--identity-output", type=Path, default=IDENTITY_PATH)
    args = parser.parse_args()
    try:
        if args.command == "build":
            _require(not (args.profile and args.policy_file), "profile and managed policy are mutually exclusive")
            write_or_check(profile_name=args.profile, check=args.check, policy_path=args.policy_file,
                           output_path=args.output, identity_path=args.identity_output)
            result: Any = {"status": "ok", "check": args.check}
        else:
            data = load_and_validate(profile_name=args.profile)
            result = qualification_report(data) if args.command in {"qualify", "catalog"} else {"status": "ok"}
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (RegistryError, OSError) as exc:
        print(f"plugin-registry: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
