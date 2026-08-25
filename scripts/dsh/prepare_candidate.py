#!/usr/bin/env python3
"""Prepare and verify an exact, coherent DSH Python/npm candidate closure."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_MANIFEST = REPO_ROOT / "services/runtime-adapter/runtime/package.json"
RUNTIME_LOCK = REPO_ROOT / "services/runtime-adapter/runtime/package-lock.json"
DEEPSEEK_PACKAGE_PREFIX = "@deepseek-ai/"
DSH_PACKAGE_PREFIX = f"{DEEPSEEK_PACKAGE_PREFIX}dsh-"


def npm_version_for_python(python_version: str) -> str:
    match = re.fullmatch(r"(\d+\.\d+\.\d+)rc(\d+)", python_version)
    if not match:
        raise ValueError(f"unsupported Python prerelease spelling: {python_version}")
    return f"{match.group(1)}-rc.{match.group(2)}"


def deepseek_lock_versions(lock: dict[str, Any]) -> dict[str, str]:
    return {
        path.removeprefix("node_modules/"): metadata["version"]
        for path, metadata in lock["packages"].items()
        if path.startswith(f"node_modules/{DEEPSEEK_PACKAGE_PREFIX}")
    }


def verify_closure(
    manifest: dict[str, Any], lock: dict[str, Any], npm_version: str
) -> dict[str, str]:
    dependencies = manifest.get("dependencies", {})
    if not dependencies or any(
        not name.startswith(DEEPSEEK_PACKAGE_PREFIX) for name in dependencies
    ):
        raise ValueError("candidate manifest must contain only explicit @deepseek-ai closure pins")
    invalid = {
        name: value
        for name, value in dependencies.items()
        if value.startswith(("^", "~"))
        or value == "latest"
        or (name.startswith(DSH_PACKAGE_PREFIX) and value != npm_version)
    }
    if invalid:
        raise ValueError(f"non-exact or mixed manifest pins: {invalid}")
    closure = deepseek_lock_versions(lock)
    if closure != dependencies:
        missing = sorted(set(closure) - set(dependencies))
        extra = sorted(set(dependencies) - set(closure))
        raise ValueError(f"manifest/lock closure mismatch: missing={missing}, extra={extra}")
    mixed = sorted(
        {
            version
            for name, version in closure.items()
            if name.startswith(DSH_PACKAGE_PREFIX) and version != npm_version
        }
    )
    if mixed:
        raise ValueError(f"mixed DSH prerelease closure: expected {npm_version}, found {mixed}")
    return closure


def fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def selected_runtime_wheel(urls: list[dict[str, Any]]) -> dict[str, Any]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux" and machine in {"x86_64", "amd64"}:
        marker = "manylinux_2_28_x86_64.whl"
    elif system == "linux" and machine in {"aarch64", "arm64"}:
        marker = "manylinux_2_28_aarch64.whl"
    elif system == "darwin" and machine == "arm64":
        marker = "macosx_14_0_arm64.whl"
    else:
        raise RuntimeError(f"no qualified runtime wheel selector for {system}/{machine}")
    matches = [item for item in urls if item["filename"].endswith(marker)]
    if len(matches) != 1:
        raise RuntimeError(f"expected one runtime wheel ending {marker}, found {len(matches)}")
    return matches[0]


def download_and_verify(file_metadata: dict[str, Any], destination: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with urllib.request.urlopen(file_metadata["url"], timeout=120) as response:
        with destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
    actual = digest.hexdigest()
    expected = file_metadata["digests"]["sha256"]
    if actual != expected:
        raise RuntimeError(f"SHA-256 mismatch for {file_metadata['filename']}: {actual} != {expected}")
    return {"filename": file_metadata["filename"], "sha256": actual, "size": destination.stat().st_size}


def run(command: list[str], cwd: Path, *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=capture)


def package_diff(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, str | None]]:
    old = deepseek_lock_versions(before)
    new = deepseek_lock_versions(after)
    return [
        {"package": name, "old": old.get(name), "new": new.get(name)}
        for name in sorted(set(old) | set(new))
        if old.get(name) != new.get(name)
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-version", required=True, help="PEP 440 version, for example 0.1.1rc1")
    parser.add_argument("--npm-version", required=True, help="npm version, for example 0.1.1-rc.1")
    parser.add_argument("--output", type=Path, required=True, help="new, empty evidence directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if npm_version_for_python(args.python_version) != args.npm_version:
        raise SystemExit("Python and npm versions do not identify the same prerelease")
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite existing output: {args.output}")
    args.output.mkdir(parents=True)
    downloads = args.output / "artifacts"
    downloads.mkdir()

    sdk = fetch_json(f"https://pypi.org/pypi/deepseek-harness-sdk/{args.python_version}/json")
    runtime = fetch_json(
        f"https://pypi.org/pypi/deepseek-harness-runtime-bin/{args.python_version}/json"
    )
    required_runtime = f"deepseek-harness-runtime-bin=={args.python_version}"
    if required_runtime not in (sdk["info"].get("requires_dist") or []):
        raise RuntimeError(f"SDK does not exact-pin {required_runtime}")
    sdk_wheels = [item for item in sdk["urls"] if item["filename"].endswith("py3-none-any.whl")]
    if len(sdk_wheels) != 1:
        raise RuntimeError(f"expected one universal SDK wheel, found {len(sdk_wheels)}")
    artifacts = [sdk_wheels[0], selected_runtime_wheel(runtime["urls"])]
    artifact_report = [
        download_and_verify(item, downloads / item["filename"])
        for item in artifacts
    ]

    accepted_manifest = json.loads(RUNTIME_MANIFEST.read_text())
    dependency_names = sorted(accepted_manifest["dependencies"])
    candidate_manifest = {
        "name": "byq-dsh-candidate-closure",
        "private": True,
        "version": "0.0.0",
        "dependencies": {
            name: (
                args.npm_version
                if name.startswith(DSH_PACKAGE_PREFIX)
                else accepted_manifest["dependencies"][name]
            )
            for name in dependency_names
        },
    }
    (args.output / "package.json").write_text(json.dumps(candidate_manifest, indent=2) + "\n")
    run(["npm", "install", "--package-lock-only", "--ignore-scripts"], args.output)
    candidate_lock = json.loads((args.output / "package-lock.json").read_text())
    closure = verify_closure(candidate_manifest, candidate_lock, args.npm_version)
    run(["npm", "ci", "--ignore-scripts"], args.output)
    run(["npm", "audit", "--audit-level=high"], args.output)
    sbom = run(
        ["npm", "sbom", "--omit=dev", "--sbom-format=cyclonedx"], args.output, capture=True
    )
    (args.output / "npm-sbom.cdx.json").write_text(sbom.stdout)

    accepted_lock = json.loads(RUNTIME_LOCK.read_text())
    report = {
        "python_version": args.python_version,
        "npm_version": args.npm_version,
        "python_requires_dist": sdk["info"].get("requires_dist"),
        "artifacts": artifact_report,
        "deepseek_closure_packages": len(closure),
        "dsh_closure_packages": sum(
            name.startswith(DSH_PACKAGE_PREFIX) for name in closure
        ),
        "dsh_closure_versions": sorted(
            {
                version
                for name, version in closure.items()
                if name.startswith(DSH_PACKAGE_PREFIX)
            }
        ),
        "dependency_diff": package_diff(accepted_lock, candidate_lock),
        "commands": {
            "lock": "npm install --package-lock-only --ignore-scripts",
            "install": "npm ci --ignore-scripts",
            "audit": "npm audit --audit-level=high",
        },
    }
    (args.output / "candidate-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
