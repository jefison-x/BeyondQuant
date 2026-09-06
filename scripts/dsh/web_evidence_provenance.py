#!/usr/bin/env python3
"""Generate bounded Web Research Evidence producer provenance policies."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
GENERATED = ROOT / "config/dsh/generated"
DEFAULT_OUTPUT = GENERATED / "web-evidence-provenance.json"
DEPLOYMENT = GENERATED / "deployment.identity.json"
REGISTRY = ROOT / "plugins/dsh-byq/registry/plugins.json"
RELEASES = ROOT / "config/dsh/releases"


class ProvenanceError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProvenanceError(f"{path}: expected object")
    return value


def _digest(value: object) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _release_hash(release_id: str) -> str:
    return "sha256:" + hashlib.sha256((RELEASES / f"{release_id}.json").read_bytes()).hexdigest()


def _default_producer() -> dict[str, str]:
    deployment = _load(DEPLOYMENT)
    registry = _load(REGISTRY)
    plugin = next((item for item in registry.get("plugins", []) if item.get("id") == "web-search"), None)
    if not isinstance(plugin, dict):
        raise ProvenanceError("qualified web-search plugin is missing")
    qualification = plugin.get("qualification", {})
    policy = plugin.get("product_policy", {})
    packages = plugin.get("packages", [])
    versions = {item.get("version") for item in packages if isinstance(item, dict)}
    if qualification.get("state") != "QUALIFIED" or policy.get("enabled") is not True:
        raise ProvenanceError("default web-search producer is not enabled and QUALIFIED")
    if len(versions) != 1:
        raise ProvenanceError("default web-search package versions are not exact and uniform")
    release_id = deployment.get("default_release")
    version = next(iter(versions))
    if version != deployment.get("carrier", {}).get("npm_version"):
        raise ProvenanceError("web-search producer version does not match deployment")
    attestation = {
        "release_descriptor": deployment.get("descriptor_hash"),
        "composition_hash": deployment.get("profile", {}).get("composition_hash"),
        "packages": sorted(
            [
                {"name": item["name"], "version": item["version"], "integrity": item["integrity"]}
                for item in packages
            ],
            key=lambda item: item["name"],
        ),
        "qualification_evidence": qualification.get("evidence"),
    }
    return {
        "plugin_id": "web-search",
        "plugin_version": version,
        "release_id": release_id,
        "qualification_state": "QUALIFIED",
        "attestation_sha256": _digest(attestation),
    }


def _candidate_producer(release_id: str) -> dict[str, str]:
    release = _load(RELEASES / f"{release_id}.json")
    carrier = release.get("carrier", {})
    if carrier.get("kind") != "python-bundled-executable":
        raise ProvenanceError("candidate provenance requires the inspected bundled carrier")
    version = str(release.get("python", {}).get("sdk", "")).replace("rc", "-rc.")
    if not version or not carrier.get("source_manifest_sha256"):
        raise ProvenanceError("candidate source attestation is incomplete")
    attestation = {
        "release_descriptor": _release_hash(release_id),
        "source_commit": carrier.get("source_commit"),
        "source_manifest_sha256": carrier.get("source_manifest_sha256"),
        "bundled_package_count": carrier.get("bundled_package_count"),
    }
    return {
        "plugin_id": "web-search",
        "plugin_version": version,
        "release_id": release_id,
        "qualification_state": "CANDIDATE",
        "attestation_sha256": _digest(attestation),
    }


def render(release_id: str | None = None) -> str:
    old = _default_producer()
    if release_id is None:
        active = old
        recognized = [old]
        mode = "qualified"
    else:
        active = _candidate_producer(release_id)
        recognized = [old, active]
        mode = "candidate"
    value = {
        "schema_version": "web-evidence-provenance-policy.v1",
        "mode": mode,
        "active_producer": active,
        "recognized_producers": recognized,
    }
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def outputs() -> dict[Path, str]:
    deployment = _load(DEPLOYMENT)
    result = {DEFAULT_OUTPUT: render()}
    for release_id in deployment.get("candidate_releases", []):
        result[GENERATED / f"{release_id}.web-evidence-provenance.json"] = render(release_id)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("generate", "check"))
    args = parser.parse_args()
    for path, expected in outputs().items():
        if args.command == "generate":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
        elif not path.is_file() or path.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"generated provenance policy is stale: {path}")
    print(json.dumps({"status": "ok", "check": args.command == "check"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
