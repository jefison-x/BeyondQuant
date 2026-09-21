#!/usr/bin/env python3
"""Version/package provenance and full dependency closure for an examined DSH release.

Produces a machine-readable provenance artifact for one published npm release:

* npm dist-tags, publish time and the exact root tarball integrity/shasum;
* the complete resolved dependency closure (every package the release resolves to,
  with a canonical ``name@version`` digest);
* the subagent-provider closure detail (package, version, resolved tarball, integrity);
* the Python pairing check against PyPI ``deepseek-harness-sdk`` /
  ``deepseek-harness-runtime-bin``: a release without a matching Python SDK is not a
  coherent pairing (ADR-0081 / D15 target decision) and cannot be a production default.

This is a read-only monitoring probe. It is network-gated by the qualification
switch and never mutates the repository, the DSH packages or any production file.

Usage:
  python3 version_provenance.py --npm-version 0.1.5-rc.2 --version-id rc2 \\
      --channel next --out <provenance.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

REGISTRY = "https://registry.npmjs.org"
PYPI = "https://pypi.org/pypi"
ROOT_PACKAGE = "@deepseek-ai/dsh-subagent"
PROVIDER_PACKAGES = [
    "@deepseek-ai/dsh-subagent-spawn-in-process",
    "@deepseek-ai/dsh-subagent-fork-in-process",
    "@deepseek-ai/dsh-subagent-acp",
    "@deepseek-ai/dsh-subagent-codex",
    "@deepseek-ai/dsh-subagent-claude-code",
    "@deepseek-ai/dsh-subagent-dsh-sdk",
]
PYTHON_SDK = "deepseek-harness-sdk"
PYTHON_RUNTIME_BIN = "deepseek-harness-runtime-bin"


class Failure(Exception):
    pass


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "byq-provider-qualification"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def pypi_versions(package: str) -> list[str]:
    try:
        payload = fetch_json(f"{PYPI}/{package}/json")
    except Exception:
        return []
    return sorted(payload.get("releases", {}).keys(), key=lambda item: item)


def expected_python_version(npm_version: str) -> str:
    """Map an npm semver prerelease to the expected PEP 440 spelling."""
    if "-" not in npm_version:
        return npm_version
    base, pre = npm_version.split("-", 1)
    label, _, number = pre.partition(".")
    cooked = {"alpha": "a", "beta": "b", "rc": "rc"}.get(label, label)
    return f"{base}{cooked}{number}"


def npm_packument(package: str) -> dict:
    return fetch_json(f"{REGISTRY}/{package.replace('/', '%2F')}")


def root_provenance(npm_version: str) -> dict:
    packument = npm_packument(ROOT_PACKAGE)
    version = packument.get("versions", {}).get(npm_version)
    if version is None:
        raise Failure(f"{ROOT_PACKAGE}@{npm_version} is not published")
    dist = version.get("dist", {})
    return {
        "package": ROOT_PACKAGE,
        "version": npm_version,
        "dist_tags": packument.get("dist-tags", {}),
        "published_at": packument.get("time", {}).get(npm_version),
        "tarball": dist.get("tarball"),
        "shasum": dist.get("shasum"),
        "integrity": dist.get("integrity"),
        "file_count": dist.get("fileCount"),
        "unpacked_size": dist.get("unpackedSize"),
        "license": version.get("license"),
    }


def provider_closure(npm_version: str) -> list[dict]:
    closure = []
    for package in PROVIDER_PACKAGES:
        packument = npm_packument(package)
        version = packument.get("versions", {}).get(npm_version)
        if version is None:
            closure.append({"package": package, "version": None, "published": False})
            continue
        dist = version.get("dist", {})
        closure.append({
            "package": package,
            "version": npm_version,
            "published": True,
            "boundary": "in-process" if package.endswith("-in-process") else "out-of-process",
            "tarball": dist.get("tarball"),
            "integrity": dist.get("integrity"),
        })
    return closure


CLOSURE_MANIFEST = Path(__file__).resolve().parents[1] / "subagent" / "package.json"


def _closure_dependencies(npm_version: str) -> dict[str, str]:
    """The real boot closure: the D15 subagent harness manifest re-versioned.

    A ``--package-lock-only`` resolution of the single root package omits the peer
    dependency closure; pinning the same manifest the runtime boot uses resolves
    the complete set needed to instantiate ``SubagentRuntime``.
    """
    template = json.loads(CLOSURE_MANIFEST.read_text(encoding="utf-8"))
    template_version = "0.1.5-rc.1"
    dependencies: dict[str, str] = {}
    for name, pinned in template["dependencies"].items():
        dependencies[name] = npm_version if pinned == template_version else pinned
    dependencies[ROOT_PACKAGE] = npm_version
    return dependencies


def resolved_closure(npm_version: str) -> dict:
    npm = shutil.which("npm")
    if npm is None:
        raise Failure("npm is required to resolve the full closure")
    with tempfile.TemporaryDirectory(prefix="byq-provider-closure-") as tmp:
        manifest = Path(tmp) / "package.json"
        manifest.write_text(json.dumps({
            "name": "byq-provider-closure",
            "version": "0.0.0",
            "private": True,
            "dependencies": _closure_dependencies(npm_version),
        }, indent=2), encoding="utf-8")
        result = subprocess.run(
            [npm, "install", "--package-lock-only", "--no-audit", "--no-fund",
             "--legacy-peer-deps"],
            cwd=tmp, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise Failure(f"npm closure resolution failed: {result.stderr[-500:]}")
        lock = json.loads((Path(tmp) / "package-lock.json").read_text(encoding="utf-8"))
    entries = []
    for path, meta in sorted(lock.get("packages", {}).items()):
        if not path.startswith("node_modules/"):
            continue
        name = meta.get("name") or path[len("node_modules/"):]
        if not name or meta.get("link"):
            continue
        entries.append({
            "name": name,
            "version": meta.get("version"),
            "integrity": meta.get("integrity"),
            "dev": bool(meta.get("dev")),
        })
    canonical = "\n".join(sorted(f"{item['name']}@{item['version']}" for item in entries))
    return {
        "count": len(entries),
        "canonical_sha256": "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "packages": entries,
    }


def python_pairing(npm_version: str) -> dict:
    expected = expected_python_version(npm_version)
    sdk_versions = pypi_versions(PYTHON_SDK)
    runtime_versions = pypi_versions(PYTHON_RUNTIME_BIN)
    sdk_match = expected if expected in sdk_versions else None
    runtime_match = expected if expected in runtime_versions else None
    return {
        "expected_python_version": expected,
        "sdk_package": PYTHON_SDK,
        "sdk_match": sdk_match,
        "sdk_versions_tail": sdk_versions[-8:],
        "runtime_bin_package": PYTHON_RUNTIME_BIN,
        "runtime_bin_match": runtime_match,
        "runtime_bin_versions_tail": runtime_versions[-8:],
        "coherent_pairing": bool(sdk_match and runtime_match),
        "reason": ("matching Python SDK and bundled runtime published"
                   if sdk_match and runtime_match
                   else f"no PyPI {PYTHON_SDK}/{PYTHON_RUNTIME_BIN} == {expected}; "
                        "npm-only release is not a coherent pairing"),
    }


def build(npm_version: str, version_id: str, channel: str) -> dict:
    return {
        "schema_version": "byq-v090-dsh-provider-qualification-provenance.v1",
        "slice": "v090-dsh-provider-qualification",
        "examined_version": {"id": version_id, "npm": npm_version, "channel": channel},
        "root": root_provenance(npm_version),
        "provider_closure": provider_closure(npm_version),
        "resolved_closure": resolved_closure(npm_version),
        "python_pairing": python_pairing(npm_version),
        "source_registry": REGISTRY,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--npm-version", required=True)
    parser.add_argument("--version-id", required=True)
    parser.add_argument("--channel", default="unknown")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        payload = build(args.npm_version, args.version_id, args.channel)
    except Failure as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}))
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "OK",
        "examined_version": payload["examined_version"],
        "coherent_pairing": payload["python_pairing"]["coherent_pairing"],
        "closure_count": payload["resolved_closure"]["count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
