#!/usr/bin/env python3
"""Validate and deterministically project BYQ DSH release descriptors."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = ROOT / "config/dsh"
RELEASE_ROOT = CONFIG_ROOT / "releases"
DEPLOYMENT_PATH = CONFIG_ROOT / "deployment.json"
OUTPUT_PATH = CONFIG_ROOT / "generated/deployment.identity.json"
RELEASE_KEYS = {"schema_version", "release_id", "compatibility_family", "python", "carrier", "profile", "build_inputs"}
DEPLOYMENT_KEYS = {"schema_version", "default_release", "candidate_releases"}
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
COMPATIBILITY_FAMILIES = {"byq-dsh-sdk-v1"}
OLD_PYTHON_KEYS = {"sdk", "runtime_bin"}
CANDIDATE_PYTHON_KEYS = OLD_PYTHON_KEYS | {
    "sdk_wheel_sha256", "linux_x86_64_runtime_wheel_sha256"
}
NPM_CARRIER_KEYS = {"kind", "npm_version", "entrypoint", "package", "integrity"}
BUNDLED_CARRIER_KEYS = {
    "kind", "profile", "entrypoint", "source_tag", "source_commit",
    "source_archive_sha256", "source_manifest_sha256", "bundled_package_count"
}


class ReleaseError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReleaseError(f"{path}: expected object")
    return value


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseError(message)


def validate_python_lock(path: Path, release_id: str, python_version: str) -> None:
    lock = load_json(path)
    _require(set(lock) == {"schema_version", "python", "release_id", "packages"},
             "Python lock has invalid closed schema")
    _require(lock["schema_version"] == "dsh-python-lock.v1", "unknown Python lock schema")
    _require(lock["release_id"] == release_id, "Python lock release mismatch")
    _require(lock["python"] == "3.11", "unsupported Python lock interpreter")
    packages = lock["packages"]
    _require(isinstance(packages, list) and bool(packages), "Python lock packages are required")
    names: set[str] = set()
    for package in packages:
        _require(isinstance(package, dict) and set(package) == {"name", "version", "sha256"},
                 "Python lock package has invalid closed schema")
        name = package["name"]
        _require(isinstance(name, str) and name not in names, "duplicate Python lock package")
        names.add(name)
        _require(isinstance(package["version"], str) and bool(package["version"]),
                 "Python lock package version is required")
        _require(re.fullmatch(r"[0-9a-f]{64}", str(package["sha256"])) is not None,
                 "invalid Python lock package hash")
    locked = {item["name"]: item["version"] for item in packages}
    _require(locked.get("deepseek-harness-sdk") == python_version,
             "Python lock SDK version mismatch")
    _require(locked.get("deepseek-harness-runtime-bin") == python_version,
             "Python lock runtime-bin version mismatch")


def validate_release(value: dict[str, Any], *, verify_files: bool) -> None:
    _require(set(value) == RELEASE_KEYS, "release descriptor has invalid closed schema")
    _require(value["schema_version"] == "dsh-release.v1", "unknown release schema")
    release_id = value["release_id"]
    _require(isinstance(release_id, str) and re.fullmatch(r"dsh-\d+\.\d+\.\d+rc\d+", release_id) is not None,
             "invalid release id")
    _require(value["compatibility_family"] in COMPATIBILITY_FAMILIES,
             "unknown compatibility family")
    python = value["python"]
    _require(isinstance(python, dict) and python.get("sdk") == python.get("runtime_bin"),
             "SDK/runtime-bin versions must match exactly")
    _require(release_id == f"dsh-{python['sdk']}", "release id/version mismatch")
    carrier = value["carrier"]
    _require(isinstance(carrier, dict) and carrier.get("kind") in {"npm-explicit-cli", "python-bundled-executable"},
             "unknown carrier")
    if carrier["kind"] == "npm-explicit-cli":
        _require(set(python) == OLD_PYTHON_KEYS, "npm Python metadata has invalid closed schema")
        _require(set(carrier) == NPM_CARRIER_KEYS, "npm carrier has invalid closed schema")
        _require(carrier["package"].startswith("@deepseek-ai/"), "invalid npm carrier package")
        _require(carrier["entrypoint"].startswith("node_modules/@deepseek-ai/"),
                 "invalid npm carrier entrypoint")
        _require(isinstance(carrier["integrity"], str) and carrier["integrity"].startswith("sha512-"),
                 "invalid npm carrier integrity")
    else:
        _require(set(python) == CANDIDATE_PYTHON_KEYS,
                 "bundled Python metadata has invalid closed schema")
        _require(set(carrier) == BUNDLED_CARRIER_KEYS,
                 "bundled carrier has invalid closed schema")
        _require(carrier["profile"] == "sdk", "unexpected bundled carrier profile")
        _require(re.fullmatch(r"[0-9a-f]{40}", str(carrier["source_commit"])) is not None,
                 "invalid upstream source commit")
        for key in ("source_archive_sha256", "source_manifest_sha256"):
            _require(re.fullmatch(r"[0-9a-f]{64}", str(carrier[key])) is not None,
                     f"invalid {key}")
        _require(isinstance(carrier["bundled_package_count"], int)
                 and carrier["bundled_package_count"] > 0,
                 "invalid bundled package count")
    profile = value["profile"]
    _require(isinstance(profile, dict) and set(profile) == {"name", "composition", "composition_hash", "identity"},
             "profile has invalid closed schema")
    if carrier["kind"] == "npm-explicit-cli":
        _require(all(isinstance(profile[key], str) and profile[key]
                     for key in ("name", "composition", "composition_hash", "identity")),
                 "active release profile must be complete")
        _require(SHA256.fullmatch(profile["composition_hash"]) is not None,
                 "invalid composition hash")
    else:
        _require(isinstance(profile["name"], str) and profile["name"],
                 "candidate profile name is required")
        _require(all(profile[key] is None
                     for key in ("composition", "composition_hash", "identity")),
                 "unbuilt candidate profile identity must be null")
    inputs = value["build_inputs"]
    _require(isinstance(inputs, dict), "build_inputs must be an object")
    for relative, expected in inputs.items():
        _require(isinstance(relative, str) and not Path(relative).is_absolute() and ".." not in Path(relative).parts,
                 "build input path must be repository-relative and contained")
        _require(isinstance(expected, str) and SHA256.fullmatch(expected) is not None,
                 "invalid build input SHA-256")
        path = (ROOT / relative).resolve()
        _require(path.is_relative_to(ROOT.resolve()) and path.is_file(), f"missing build input: {relative}")
        if verify_files:
            _require(digest(path) == expected, f"build input drift: {relative}")
    if carrier["kind"] == "npm-explicit-cli":
        _require(carrier.get("npm_version") == python["sdk"].replace("rc", "-rc."),
                 "Python/npm versions do not match")
        _require(bool(inputs), "active npm release must bind build inputs")
    else:
        for key in ("sdk_wheel_sha256", "linux_x86_64_runtime_wheel_sha256"):
            _require(re.fullmatch(r"[0-9a-f]{64}", str(python.get(key, ""))) is not None,
                     f"bundled carrier missing {key}")
        lock_paths = [ROOT / relative for relative in inputs if relative.endswith(".python.lock")]
        _require(len(lock_paths) == 1, "bundled release requires one Python lock")
        validate_python_lock(lock_paths[0], release_id, python["sdk"])


def load_all(*, verify_files: bool = True) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    deployment = load_json(DEPLOYMENT_PATH)
    _require(set(deployment) == DEPLOYMENT_KEYS, "deployment selector has invalid closed schema")
    _require(deployment["schema_version"] == "dsh-deployment.v1", "unknown deployment schema")
    files = sorted(RELEASE_ROOT.glob("*.json"))
    releases: dict[str, dict[str, Any]] = {}
    for path in files:
        value = load_json(path)
        validate_release(value, verify_files=verify_files)
        _require(path.stem == value["release_id"], "release filename/id mismatch")
        _require(value["release_id"] not in releases, "duplicate release id")
        releases[value["release_id"]] = value
    default = deployment["default_release"]
    candidates = deployment["candidate_releases"]
    _require(isinstance(candidates, list) and len(candidates) == len(set(candidates)), "candidate releases must be unique")
    _require(default in releases, "default release is not registered")
    _require(all(item in releases for item in candidates), "candidate release is not registered")
    _require(default not in candidates, "default release cannot also be a candidate")
    return deployment, releases


def render_release(release_id: str, deployment: dict[str, Any], releases: dict[str, dict[str, Any]]) -> str:
    _require(release_id in releases, "selected release is not registered")
    selected = releases[release_id]
    output = {
        "schema_version": "dsh-deployment-identity.v1",
        "default_release": selected["release_id"],
        "is_default": release_id == deployment["default_release"],
        "compatibility_family": selected["compatibility_family"],
        "python": selected["python"],
        "carrier": selected["carrier"],
        "profile": selected["profile"],
        "candidate_releases": deployment["candidate_releases"],
        "descriptor_hash": digest(RELEASE_ROOT / f"{selected['release_id']}.json"),
    }
    return json.dumps(output, indent=2, sort_keys=True) + "\n"


def render() -> str:
    deployment, releases = load_all()
    selected = releases[deployment["default_release"]]
    output = {
        "schema_version": "dsh-deployment-identity.v1",
        "default_release": selected["release_id"],
        "compatibility_family": selected["compatibility_family"],
        "python": selected["python"],
        "carrier": selected["carrier"],
        "profile": selected["profile"],
        "candidate_releases": deployment["candidate_releases"],
        "descriptor_hash": digest(RELEASE_ROOT / f"{selected['release_id']}.json"),
    }
    return json.dumps(output, indent=2, sort_keys=True) + "\n"


def candidate_output_path(release_id: str) -> Path:
    return CONFIG_ROOT / "generated" / f"{release_id}.identity.json"


def generated_outputs() -> dict[Path, str]:
    deployment, releases = load_all()
    outputs = {OUTPUT_PATH: render()}
    outputs.update({
        candidate_output_path(release_id): render_release(release_id, deployment, releases)
        for release_id in deployment["candidate_releases"]
    })
    return outputs


def write_new_output(output: Path, filename: str, content: str) -> None:
    if output.exists():
        raise ReleaseError(f"refusing to overwrite existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        (staging / filename).write_text(content, encoding="utf-8")
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("inspect", "generate", "check"))
    parser.add_argument("--release", help="exact registered release id")
    parser.add_argument("--output", type=Path, help="new output directory")
    args = parser.parse_args()
    deployment, releases = load_all()
    if args.command == "inspect":
        if not args.release or args.output is None:
            parser.error("inspect requires --release and --output")
        write_new_output(
            args.output,
            "release-inspection.json",
            render_release(args.release, deployment, releases),
        )
    elif args.release:
        selected = render_release(args.release, deployment, releases)
        if args.command == "generate":
            if args.output is None:
                parser.error("release-specific generate requires --output")
            write_new_output(args.output, "release.identity.json", selected)
        elif args.output is not None:
            identity = args.output / "release.identity.json"
            if not identity.is_file() or identity.read_text(encoding="utf-8") != selected:
                raise SystemExit("generated release identity is stale")
    elif args.output is not None:
        parser.error("--output requires --release")
    elif args.command == "generate":
        for path, rendered in generated_outputs().items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8")
    else:
        for path, rendered in generated_outputs().items():
            if not path.is_file() or path.read_text(encoding="utf-8") != rendered:
                raise SystemExit(
                    f"generated DSH identity is stale: {path}; "
                    "run scripts/dsh/release.py generate"
                )
    print(json.dumps({"status": "ok", "check": args.command == "check"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
