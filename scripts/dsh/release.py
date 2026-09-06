#!/usr/bin/env python3
"""Validate and deterministically project BYQ DSH release descriptors."""

from __future__ import annotations

import argparse
import datetime as dt
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
QUALIFICATION_EVIDENCE_PATH = (
    ROOT / "docs/evidence/dsh-012rc1/u5/qualification-evidence.json"
)
QUALIFICATION_KEYS = {
    "schema_version", "release_id", "baseline_release_id", "git_commit",
    "image_digest", "artifact_hashes", "composition_hash", "policy_hash",
    "started_at", "finished_at", "platform",
    "provider_model_metadata_without_secrets", "checks", "metrics",
    "capability_diff", "dependency_diff", "limitations", "threshold_exceptions",
    "qualification_scope",
}
QUALIFICATION_CHECK_KEYS = {
    "id", "layer", "result", "test_name", "evidence_reference", "failure_category",
}
QUALIFICATION_RESULTS = {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}
QUALIFICATION_SCOPES = {"keyless", "preproduction", "production-observed"}
QUALIFICATION_ARTIFACT_KEYS = {
    "candidate_descriptor", "baseline_descriptor", "candidate_identity",
}
QUALIFICATION_PROVIDER_KEYS = {"provider", "model", "protocol", "runs"}
SECRET_LIKE = re.compile(
    r"(?i)(bearer\s+\S+|-----BEGIN [A-Z ]*PRIVATE KEY|sk-[a-z0-9_-]{8,})"
)
SECRET_KEY_NAME = re.compile(
    r"(?i)(?:^|[_-])(?:api[_-]?key|access[_-]?token|password|secret|credential)(?:$|[_-])"
)


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
        candidate_values = tuple(
            profile[key] for key in ("composition", "composition_hash", "identity")
        )
        is_unbuilt = all(value is None for value in candidate_values)
        is_built = all(isinstance(value, str) and bool(value) for value in candidate_values)
        _require(is_unbuilt or is_built,
                 "candidate profile identity must be entirely null or complete")
        if is_built:
            _require(SHA256.fullmatch(profile["composition_hash"]) is not None,
                     "invalid candidate composition hash")
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


def _number(value: object, message: str) -> float:
    _require(not isinstance(value, bool) and isinstance(value, (int, float)), message)
    number = float(value)
    _require(number >= 0, message)
    return number


def _timestamp(value: object, field: str) -> dt.datetime:
    _require(isinstance(value, str) and value.endswith("Z"), f"invalid {field}")
    try:
        parsed = dt.datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ReleaseError(f"invalid {field}") from exc
    return parsed


def validate_qualification_evidence(
    value: dict[str, Any], *, release_id: str, baseline_release_id: str,
) -> None:
    _require(set(value) == QUALIFICATION_KEYS, "qualification evidence has invalid closed schema")
    _require(value["schema_version"] == "dsh-qualification-evidence.v1",
             "unknown qualification evidence schema")
    _require(
        value["release_id"] == release_id and value["baseline_release_id"] == baseline_release_id,
        "qualification release identity mismatch",
    )
    _require(re.fullmatch(r"[0-9a-f]{40}", str(value["git_commit"])) is not None,
             "invalid qualification Git commit")
    for field in ("image_digest", "composition_hash", "policy_hash"):
        _require(isinstance(value[field], str) and SHA256.fullmatch(value[field]) is not None,
                 f"invalid qualification {field}")
    _, releases = load_all()
    candidate_release = releases[release_id]
    baseline_release = releases[baseline_release_id]
    _require(value["composition_hash"] == candidate_release["profile"]["composition_hash"],
             "qualification composition hash does not match candidate release")
    policy_path = CONFIG_ROOT / "generated" / f"{release_id}.web-evidence-provenance.json"
    _require(policy_path.is_file() and value["policy_hash"] == digest(policy_path),
             "qualification policy hash does not match generated provenance policy")
    artifact_hashes = value["artifact_hashes"]
    _require(isinstance(artifact_hashes, dict)
             and set(artifact_hashes) == QUALIFICATION_ARTIFACT_KEYS,
             "qualification artifact hashes have invalid closed schema")
    _require(all(isinstance(name, str) and name and isinstance(digest_value, str)
                 and SHA256.fullmatch(digest_value) is not None
                 for name, digest_value in artifact_hashes.items()),
             "invalid qualification artifact hash")
    _require(artifact_hashes["candidate_descriptor"] == digest(RELEASE_ROOT / f"{release_id}.json")
             and artifact_hashes["baseline_descriptor"] == digest(RELEASE_ROOT / f"{baseline_release_id}.json")
             and artifact_hashes["candidate_identity"] == digest(candidate_output_path(release_id)),
             "qualification artifact hashes do not match registered release files")
    started = _timestamp(value["started_at"], "started_at")
    finished = _timestamp(value["finished_at"], "finished_at")
    _require(finished >= started, "qualification finish precedes start")
    platform = value["platform"]
    _require(isinstance(platform, dict) and set(platform) == {"os", "arch"}
             and all(isinstance(item, str) and item for item in platform.values()),
             "invalid qualification platform")
    scope = value["qualification_scope"]
    _require(scope in QUALIFICATION_SCOPES, "invalid qualification scope")
    checks = value["checks"]
    _require(isinstance(checks, list) and len(checks) == 40,
             "qualification checks must contain exactly T01-T40")
    expected_ids = [f"T{number:02d}" for number in range(1, 41)]
    _require([item.get("id") if isinstance(item, dict) else None for item in checks] == expected_ids,
             "qualification checks must contain exactly T01-T40 in order")
    for item in checks:
        _require(set(item) == QUALIFICATION_CHECK_KEYS,
                 f"{item.get('id', 'unknown')} has invalid closed schema")
        _require(isinstance(item["layer"], str)
                 and re.fullmatch(r"L[0-4](?:[+/]L[0-4])*", item["layer"]) is not None,
                 f"{item['id']} has invalid evidence layer")
        _require(item["result"] in QUALIFICATION_RESULTS,
                 f"{item['id']} has invalid result")
        _require(isinstance(item["test_name"], str) and bool(item["test_name"]),
                 f"{item['id']} test name is required")
        _require(isinstance(item["evidence_reference"], str)
                 and bool(item["evidence_reference"])
                 and not Path(item["evidence_reference"].split("#", 1)[0]).is_absolute()
                 and ".." not in Path(item["evidence_reference"].split("#", 1)[0]).parts,
                 f"{item['id']} evidence reference must be repository-relative")
        evidence_path = ROOT / item["evidence_reference"].split("#", 1)[0]
        _require(evidence_path.is_file(), f"{item['id']} evidence reference does not exist")
        if item["result"] == "PASS":
            _require(item["failure_category"] is None,
                     f"{item['id']} PASS cannot have a failure category")
        else:
            _require(isinstance(item["failure_category"], str)
                     and bool(item["failure_category"]),
                     f"{item['id']} non-PASS requires a failure category")
    pass_through = {"keyless": 30, "preproduction": 37, "production-observed": 40}[scope]
    _require(all(item["result"] == "PASS" for item in checks[:pass_through]),
             f"{scope} qualification requires T01-T{pass_through:02d} PASS")
    if scope != "production-observed":
        _require(all(item["result"] == "NOT_RUN" for item in checks[pass_through:]),
                 f"{scope} qualification requires T{pass_through + 1:02d}-T40 NOT_RUN")
    for field in (
        "provider_model_metadata_without_secrets", "capability_diff", "dependency_diff",
        "limitations", "threshold_exceptions",
    ):
        _require(isinstance(value[field], list), f"qualification {field} must be an array")
    if scope in {"preproduction", "production-observed"}:
        _require(bool(value["provider_model_metadata_without_secrets"]),
                 "credentialed qualification requires provider/model metadata")
    for provider in value["provider_model_metadata_without_secrets"]:
        _require(isinstance(provider, dict) and set(provider) == QUALIFICATION_PROVIDER_KEYS,
                 "provider/model metadata has invalid closed schema")
        _require(all(isinstance(provider[field], str) and provider[field]
                     for field in ("provider", "model", "protocol"))
                 and isinstance(provider["runs"], int) and provider["runs"] > 0,
                 "provider/model metadata is invalid")
    metrics = value["metrics"]
    _require(isinstance(metrics, dict) and set(metrics) == {
        "raw_sample_counts", "timing_summary", "peak_rss_mib", "cleanup_counts"
    }, "qualification metrics have invalid closed schema")
    samples = metrics["raw_sample_counts"]
    _require(isinstance(samples, dict), "qualification sample counts are required")
    if pass_through >= 37:
        _require(_number(samples.get("baseline_l1"), "baseline sample count is invalid") >= 10
                 and _number(samples.get("candidate_l1"), "candidate sample count is invalid") >= 10
                 and _number(samples.get("lifecycle_cycles"), "lifecycle sample count is invalid") >= 20,
                 "qualification performance/lifecycle sample counts are insufficient")
    timing = metrics["timing_summary"]
    _require(isinstance(timing, dict), "qualification timing summary is required")
    baseline_time = _number(timing.get("baseline_median_seconds"), "baseline latency is invalid")
    candidate_time = _number(timing.get("candidate_median_seconds"), "candidate latency is invalid")
    latency_threshold = baseline_time * 1.2 + 1.0
    rss = metrics["peak_rss_mib"]
    _require(isinstance(rss, dict), "qualification RSS summary is required")
    baseline_rss = _number(rss.get("baseline"), "baseline RSS is invalid")
    candidate_rss = _number(rss.get("candidate"), "candidate RSS is invalid")
    rss_threshold = baseline_rss * 1.2 + 32.0
    if pass_through >= 37:
        exceeded = {}
        if candidate_time > latency_threshold:
            exceeded["median_latency_seconds"] = (candidate_time, latency_threshold)
        if candidate_rss > rss_threshold:
            exceeded["peak_rss_mib"] = (candidate_rss, rss_threshold)
        exceptions = value["threshold_exceptions"]
        _require(len(exceptions) == len(exceeded),
                 "every exceeded performance threshold requires one explicit exception")
        seen: set[str] = set()
        for exception in exceptions:
            _require(isinstance(exception, dict) and set(exception) == {
                "metric", "observed", "threshold", "reason"
            }, "performance threshold exception has invalid closed schema")
            metric = exception["metric"]
            _require(metric in exceeded and metric not in seen,
                     "performance threshold exception does not match an exceeded metric")
            observed, threshold = exceeded[metric]
            _require(abs(_number(exception["observed"], "exception observed value is invalid") - observed) < 0.001
                     and abs(_number(exception["threshold"], "exception threshold is invalid") - threshold) < 0.001,
                     "performance threshold exception values do not match evidence")
            _require(isinstance(exception["reason"], str) and len(exception["reason"].strip()) >= 40,
                     "performance threshold exception requires a specific reason")
            seen.add(metric)
    cleanup = metrics["cleanup_counts"]
    _require(isinstance(cleanup, dict) and set(cleanup) == {
        "containers", "networks", "volumes", "owned_processes"
    }, "qualification cleanup counts have invalid closed schema")
    _require(all(_number(amount, "cleanup count is invalid") == 0 for amount in cleanup.values()),
             "qualification cleanup counts must be zero")
    serialized = json.dumps(value, ensure_ascii=False)
    _require(SECRET_LIKE.search(serialized) is None,
             "qualification evidence contains secret-like material")
    def contains_secret_key(item: object) -> bool:
        if isinstance(item, dict):
            return any(SECRET_KEY_NAME.search(str(key)) or contains_secret_key(nested)
                       for key, nested in item.items())
        if isinstance(item, list):
            return any(contains_secret_key(nested) for nested in item)
        return False
    _require(not contains_secret_key(value),
             "qualification evidence contains a secret-bearing field name")


def render_qualification_report(
    release_id: str, baseline_release_id: str, evidence: dict[str, Any],
) -> str:
    deployment, releases = load_all()
    _require(release_id in deployment["candidate_releases"],
             "qualification release must be a registered candidate")
    _require(baseline_release_id == deployment["default_release"]
             and baseline_release_id in releases,
             "qualification baseline must be the current default release")
    validate_qualification_evidence(
        evidence, release_id=release_id, baseline_release_id=baseline_release_id,
    )
    report = {
        **evidence,
        "schema_version": "dsh-qualification-report.v1",
        "qualification_state": "QUALIFIED",
    }
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("inspect", "generate", "check", "qualify"))
    parser.add_argument("--release", help="exact registered release id")
    parser.add_argument("--baseline", help="exact registered baseline release id")
    parser.add_argument("--output", type=Path, help="new output directory")
    args = parser.parse_args()
    deployment, releases = load_all()
    if args.command == "qualify":
        if not args.release or not args.baseline or args.output is None:
            parser.error("qualify requires --release, --baseline and --output")
        evidence = load_json(QUALIFICATION_EVIDENCE_PATH)
        write_new_output(
            args.output,
            "qualification-report.json",
            render_qualification_report(args.release, args.baseline, evidence),
        )
    elif args.baseline is not None:
        parser.error("--baseline is only valid with qualify")
    elif args.command == "inspect":
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
