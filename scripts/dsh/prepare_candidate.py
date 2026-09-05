#!/usr/bin/env python3
"""Prepare and verify an exact, coherent DSH Python/npm candidate closure."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_MANIFEST = REPO_ROOT / "services/runtime-adapter/runtime/package.json"
RUNTIME_LOCK = REPO_ROOT / "services/runtime-adapter/runtime/package-lock.json"
DEEPSEEK_PACKAGE_PREFIX = "@deepseek-ai/"
DSH_PACKAGE_PREFIX = f"{DEEPSEEK_PACKAGE_PREFIX}dsh-"
REVIEWED_INSTALL_SCRIPTS = {
    "node_modules/@google/genai",
    "node_modules/koffi",
    "node_modules/protobufjs",
}
RELEASE_SCRIPT = REPO_ROOT / "scripts/dsh/release.py"
RELEASE_SPEC = importlib.util.spec_from_file_location("dsh_release", RELEASE_SCRIPT)
assert RELEASE_SPEC and RELEASE_SPEC.loader
RELEASE_MODULE = importlib.util.module_from_spec(RELEASE_SPEC)
RELEASE_SPEC.loader.exec_module(RELEASE_MODULE)


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


def nested_deepseek_nodes(lock: dict[str, Any]) -> list[str]:
    """Return scoped packages hidden below another node_modules directory."""

    marker = f"/node_modules/{DEEPSEEK_PACKAGE_PREFIX}"
    return sorted(
        path
        for path in lock.get("packages", {})
        if marker in path and not path.startswith(f"node_modules/{DEEPSEEK_PACKAGE_PREFIX}")
    )


def verify_closure(
    manifest: dict[str, Any], lock: dict[str, Any], npm_version: str
) -> dict[str, str]:
    nested = nested_deepseek_nodes(lock)
    if nested:
        raise ValueError(f"nested @deepseek-ai packages are forbidden: {nested}")
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
    for path, metadata in lock.get("packages", {}).items():
        if not path.startswith(f"node_modules/{DEEPSEEK_PACKAGE_PREFIX}"):
            continue
        for name, requirement in metadata.get("peerDependencies", {}).items():
            if name.startswith(DSH_PACKAGE_PREFIX) and npm_version not in requirement:
                raise ValueError(
                    f"unsatisfied DSH peer requirement in {path}: {name} {requirement}"
                )
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


def bundled_sbom(archive: Path, carrier: dict[str, Any]) -> dict[str, Any]:
    """Build an exact package inventory from the release's pinned source tree."""

    with tarfile.open(archive, "r:gz") as source:
        manifests: dict[str, tuple[dict[str, Any], bytes]] = {}
        runtime_manifest: bytes | None = None
        for member in source.getmembers():
            if not member.isfile() or not member.name.endswith("/package.json"):
                continue
            stream = source.extractfile(member)
            if stream is None:
                continue
            raw = stream.read()
            if member.name.endswith("/python/sdk-runtime/package.json"):
                runtime_manifest = raw
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and isinstance(value.get("name"), str):
                manifests[value["name"]] = (value, raw)
    if runtime_manifest is None:
        raise RuntimeError("source archive lacks python/sdk-runtime/package.json")
    manifest_hash = hashlib.sha256(runtime_manifest).hexdigest()
    if manifest_hash != carrier["source_manifest_sha256"]:
        raise RuntimeError("bundled source manifest differs from descriptor")
    closure = json.loads(runtime_manifest).get("dependencies", {})
    if len(closure) != carrier["bundled_package_count"]:
        raise RuntimeError("bundled package count differs from descriptor")
    missing = sorted(set(closure) - set(manifests))
    if missing:
        raise RuntimeError(f"bundled source packages missing manifests: {missing}")
    components = []
    for name in sorted(closure):
        package, raw = manifests[name]
        version = package.get("version")
        if not isinstance(version, str) or not version:
            raise RuntimeError(f"bundled source package lacks version: {name}")
        components.append({
            "type": "library",
            "name": name,
            "version": version,
            "hashes": [{"alg": "SHA-256", "content": hashlib.sha256(raw).hexdigest()}],
        })
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {"component": {
            "type": "application",
            "name": "deepseek-harness-runtime-bundled-closure",
            "version": carrier["source_tag"].removeprefix("dsh-v"),
        }},
        "components": components,
    }


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
    parser.add_argument("--release-id", required=True, help="registered release id")
    parser.add_argument("--output", type=Path, required=True, help="new, empty evidence directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _deployment, releases = RELEASE_MODULE.load_all()
    if args.release_id not in releases:
        raise SystemExit(f"unknown release: {args.release_id}")
    selected = releases[args.release_id]
    python_version = selected["python"]["sdk"]
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite existing output: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{args.output.name}.", dir=args.output.parent))
    downloads = staging / "artifacts"
    downloads.mkdir()

    try:
        sdk = fetch_json(f"https://pypi.org/pypi/deepseek-harness-sdk/{python_version}/json")
        runtime = fetch_json(
            f"https://pypi.org/pypi/deepseek-harness-runtime-bin/{python_version}/json"
        )
        required_runtime = f"deepseek-harness-runtime-bin=={python_version}"
        if required_runtime not in (sdk["info"].get("requires_dist") or []):
            raise RuntimeError(f"SDK does not exact-pin {required_runtime}")
        sdk_wheels = [item for item in sdk["urls"] if item["filename"].endswith("py3-none-any.whl")]
        if len(sdk_wheels) != 1:
            raise RuntimeError(f"expected one universal SDK wheel, found {len(sdk_wheels)}")
        artifacts = [sdk_wheels[0], selected_runtime_wheel(runtime["urls"])]
        expected_hashes = {
            sdk_wheels[0]["filename"]: selected["python"].get("sdk_wheel_sha256"),
            artifacts[1]["filename"]: selected["python"].get("linux_x86_64_runtime_wheel_sha256"),
        }
        for item in artifacts:
            if expected_hashes[item["filename"]] != item["digests"]["sha256"]:
                raise RuntimeError(f"published artifact differs from descriptor: {item['filename']}")
        artifact_report = [
            download_and_verify(item, downloads / item["filename"])
            for item in artifacts
        ]
        source_archive = downloads / f"DeepSeek-Harness-{selected['carrier']['source_commit']}.tar.gz"
        source_metadata = {
            "filename": source_archive.name,
            "url": (
                "https://github.com/deepseek-ai/DeepSeek-Harness/archive/"
                f"{selected['carrier']['source_commit']}.tar.gz"
            ),
            "digests": {"sha256": selected["carrier"]["source_archive_sha256"]},
        }
        source_report = download_and_verify(source_metadata, source_archive)
        sbom = bundled_sbom(source_archive, selected["carrier"])
        sbom_path = staging / "bundled-sbom.cdx.json"
        sbom_path.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n")

        accepted_lock = json.loads(RUNTIME_LOCK.read_text())
        accepted_manifest = json.loads(RUNTIME_MANIFEST.read_text())
        accepted_closure = verify_closure(
            accepted_manifest, accepted_lock, npm_version_for_python("0.1.1rc1")
        )
        install_scripts = sorted(
            path for path, metadata in accepted_lock["packages"].items()
            if metadata.get("hasInstallScript")
        )
        optional_dependencies = sorted({
            name
            for metadata in accepted_lock["packages"].values()
            for name in metadata.get("optionalDependencies", {})
        })
        if set(install_scripts) != REVIEWED_INSTALL_SCRIPTS:
            raise RuntimeError(f"install-script set changed: {install_scripts}")
        expected_optional = (
            f"@koromix/koffi-{platform.system().lower()}-"
            f"{'x64' if platform.machine().lower() in {'x86_64', 'amd64'} else platform.machine().lower()}"
        )
        if expected_optional not in optional_dependencies:
            raise RuntimeError(f"missing platform optional dependency: {expected_optional}")
        python_lock_paths = [
            REPO_ROOT / path
            for path in selected["build_inputs"]
            if path.endswith(".python.lock")
        ]
        if len(python_lock_paths) != 1:
            raise RuntimeError("candidate must bind exactly one Python lock")
        python_lock = json.loads(python_lock_paths[0].read_text())
        report = {
            "schema_version": "dsh-candidate-preparation.v1",
            "release_id": args.release_id,
            "descriptor_hash": RELEASE_MODULE.digest(RELEASE_MODULE.RELEASE_ROOT / f"{args.release_id}.json"),
            "python_version": python_version,
            "carrier": selected["carrier"],
            "python_requires_dist": sdk["info"].get("requires_dist"),
            "python_lock": {
                "path": str(python_lock_paths[0].relative_to(REPO_ROOT)),
                "sha256": hashlib.sha256(python_lock_paths[0].read_bytes()).hexdigest(),
                "packages": len(python_lock["packages"]),
            },
            "artifacts": artifact_report,
            "source_archive": source_report,
            "bundled_sbom": {
                "path": sbom_path.name,
                "sha256": hashlib.sha256(sbom_path.read_bytes()).hexdigest(),
                "components": len(sbom["components"]),
            },
            "bundled_package_count": selected["carrier"].get("bundled_package_count"),
            "accepted_external_npm_packages": len(accepted_closure),
            "dependency_diff": {
                "removed_external_npm_packages": sorted(accepted_closure),
                "added_external_npm_packages": [],
                "changed_external_npm_packages": [],
                "bundled_carrier": selected["carrier"]["entrypoint"],
            },
            "closure_checks": {
                "nested_deepseek_nodes": [],
                "peer_dependencies": "satisfied by accepted package-lock",
                "optional_dependencies": optional_dependencies,
                "selected_platform_optional_dependency": expected_optional,
                "install_scripts": install_scripts,
                "install_script_policy": (
                    "exact reviewed allowlist; accepted image uses --ignore-scripts; "
                    "unexpected additions fail closed"
                ),
                "bundled_sbom": "generated from exact source commit; image-installed comparison remains U4",
            },
        }
        (staging / "candidate-report.json").write_text(json.dumps(report, indent=2) + "\n")
        staging.rename(args.output)
        print(json.dumps(report, indent=2))
        return 0
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


if __name__ == "__main__":
    sys.exit(main())
