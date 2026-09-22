#!/usr/bin/env python3
"""Fail-closed verifier for the 0.9 formal DSH default upgrade.

Read-only. It proves the repository default dependency/selector is the coherent
DSH ``0.1.5-rc.1`` pairing (Python ``0.1.5rc1`` + bundled npm ``0.1.5-rc.1``),
that the deployed runtime-adapter image defaults to it, and that the prior
``dsh-0.1.2rc1`` baseline is preserved byte-for-byte for rollback.

Exit code is non-zero on any drift. ``--selfcheck`` applies defect-targeting
mutations and requires every one of them to be rejected, so a result-trusting
gate that ignores the checks cannot pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RELEASES = ROOT / "config/dsh/releases"
GENERATED = ROOT / "config/dsh/generated"
CANDIDATE = "dsh-0.1.5rc1"
ROLLBACK = "dsh-0.1.2rc1"
PROMOTED_BUILD = "dsh-0.1.5rc1-post-u8.209"
ROLLBACK_BUILD = "dsh-0.1.2rc1-post-u8.199"
BASE_ROLLBACK_BLOBS = {
    "config/dsh/releases/dsh-0.1.2rc1.json": "77bb4cfc0d4c0c25a3b085529cd240a9f77e23e4",
    "config/dsh/releases/dsh-0.1.2rc1.python.lock": "9bc54d16792e171bb8d20c9ed7656b94049326c3",
    "config/dsh/builds/dsh-0.1.2rc1-post-u8.199.json": "6e8aba1a3d90b9882211e726cf40599a41c532f0",
}
PRIOR_DOCKERFILE_SHA256 = (
    "sha256:a03a97b6dfe5fbaf058dfc5b3e7117367e55497107e78fc7f6aead7e4efd1dc8"
)
PRIOR_PRODUCTION_IMAGE = (
    "sha256:301bcd5ac3e7d26a6b61f4f5646ad44409e50f2cd3ab058a37b2bb5605a980ea"
)


class Drift(ValueError):
    pass


def _read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _read_json(path: str) -> dict:
    return json.loads(_read_text(path))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Drift(message)


def check_deployment(deployment: dict) -> None:
    _require(deployment.get("schema_version") == "dsh-deployment.v1",
             "deployment schema changed")
    _require(deployment.get("default_release") == CANDIDATE,
             f"default release is not {CANDIDATE}")
    _require(deployment.get("candidate_releases") == [ROLLBACK],
             f"rollback candidate must be exactly [{ROLLBACK}]")


def check_promoted_release(release: dict, candidate: dict) -> None:
    _require(release.get("schema_version") == "dsh-release.v1", "release schema changed")
    _require(release.get("release_id") == CANDIDATE, "release id mismatch")
    _require(release.get("compatibility_family") == "byq-dsh-sdk-v1",
             "compatibility family changed")
    python = release.get("python", {})
    _require(python.get("sdk") == "0.1.5rc1" and python.get("runtime_bin") == "0.1.5rc1",
             "release does not pin the coherent 0.1.5rc1 Python pairing")
    carrier = release.get("carrier", {})
    _require(carrier.get("kind") == "python-bundled-executable",
             "carrier kind changed")
    _require(carrier.get("source_tag") == "dsh-v0.1.5-rc.1"
             and carrier.get("bundled_package_count") == 126,
             "upstream bundled carrier identity changed")
    # The promoted declaration must agree with the registered release.
    _require(candidate.get("status") == "promoted", "candidate is not promoted")
    _require(candidate.get("production_default") == CANDIDATE,
             "candidate production_default does not name the promoted default")
    _require(candidate.get("python", {}).get("sdk") == "0.1.5rc1"
             and candidate.get("upstream", {}).get("source_commit")
             == carrier.get("source_commit"),
             "candidate and release upstream identity disagree")
    _require(candidate.get("runtime", {}).get("selector_value") == CANDIDATE,
             "candidate selector value changed")
    boundary = candidate.get("production_boundary", {})
    _require(boundary.get("default_release_unchanged") is False
             and boundary.get("default_env_unchanged") is False,
             "promoted candidate must declare the default moved")
    _require(boundary.get("historical_evidence_untouched") is True,
             "promoted candidate must not claim historical evidence changed")
    _require(boundary.get("database_changes") == "none"
             and boundary.get("worker_restarts") == "none",
             "promotion must not change the database or restart workers")
    _require(boundary.get("rollback_release") == ROLLBACK,
             "rollback release changed")


def check_selector_identity(identity: dict) -> None:
    _require(identity.get("schema_version") == "dsh-deployment-identity.v1",
             "deployment identity schema changed")
    _require(identity.get("default_release") == CANDIDATE,
             "default selector identity is not the promoted release")
    python = identity.get("python", {})
    _require(python.get("sdk") == "0.1.5rc1" and python.get("runtime_bin") == "0.1.5rc1",
             "default selector identity does not pin 0.1.5rc1")


def check_dependencies(pyproject: str, lock: str) -> None:
    _require('"deepseek-harness-sdk==0.1.5rc1"' in pyproject
             and '"deepseek-harness-runtime-bin==0.1.5rc1"' in pyproject,
             "pyproject does not pin the promoted default")
    _require("deepseek-harness-sdk==0.1.5rc1" in lock
             and "deepseek-harness-runtime-bin==0.1.5rc1" in lock,
             "default requirement lock does not pin the promoted default")


def check_image(dockerfile: str, build_id: str) -> None:
    _require("BYQ_DSH_COMPATIBILITY_RELEASE=dsh-0.1.5rc1" in dockerfile,
             "runtime image selector is not the promoted default")
    _require(f"config/dsh/builds/{build_id}.json" in dockerfile,
             "runtime image does not embed the promoted build manifest")
    _require("version('deepseek-harness-sdk') == '0.1.5rc1'" in dockerfile,
             "runtime image does not assert the promoted SDK version")


def check_build(build_id: str, manifest: dict, descriptor_hash: str) -> None:
    _require(build_id == PROMOTED_BUILD, "promoted build id changed")
    _require(manifest.get("release_id") == CANDIDATE,
             "build manifest release mismatch")
    _require(manifest.get("release_descriptor_hash") == descriptor_hash,
             "build manifest does not bind the promoted descriptor")


def check_rollback(deployment: dict, release: dict, identity: dict) -> None:
    _require(ROLLBACK in deployment.get("candidate_releases", []),
             "rollback release is not registered as a candidate")
    _require(release.get("release_id") == ROLLBACK, "rollback descriptor missing")
    _require(release.get("python", {}).get("sdk") == "0.1.2rc1",
             "rollback descriptor Python pin changed")
    _require(identity.get("default_release") == ROLLBACK
             and identity.get("python", {}).get("sdk") == "0.1.2rc1",
             "rollback identity is not intact")
    for relative, expected in BASE_ROLLBACK_BLOBS.items():
        data = (ROOT / relative).read_bytes()
        actual = hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()
        _require(actual == expected, f"rollback artifact changed: {relative}")
    _require((ROOT / "config/dsh/builds" / f"{ROLLBACK_BUILD}.json").is_file(),
             "rollback build manifest is missing")


def verify() -> dict:
    deployment = _read_json("config/dsh/deployment.json")
    release = _read_json(f"config/dsh/releases/{CANDIDATE}.json")
    candidate = _read_json(f"config/dsh/candidates/{CANDIDATE}/candidate.json")
    identity = _read_json("config/dsh/generated/deployment.identity.json")
    rollback_release = _read_json(f"config/dsh/releases/{ROLLBACK}.json")
    rollback_identity = _read_json(f"config/dsh/generated/{ROLLBACK}.identity.json")
    descriptor_hash = "sha256:" + hashlib.sha256(
        (RELEASES / f"{CANDIDATE}.json").read_bytes()).hexdigest()
    manifest = _read_json(f"config/dsh/builds/{PROMOTED_BUILD}.json")
    check_deployment(deployment)
    check_promoted_release(release, candidate)
    check_selector_identity(identity)
    check_dependencies(
        _read_text("services/runtime-adapter/pyproject.toml"),
        _read_text("services/runtime-adapter/requirements.candidate.lock"),
    )
    check_image(_read_text("services/runtime-adapter/Dockerfile.post-u8-candidate"),
                PROMOTED_BUILD)
    check_build(PROMOTED_BUILD, manifest, descriptor_hash)
    check_rollback(deployment, rollback_release, rollback_identity)
    compose = _read_text("compose.yml")
    _require("BYQ_DSH_COMPATIBILITY_RELEASE:-dsh-0.1.5rc1" in compose,
             "compose default selector is not the promoted release")
    return {
        "status": "PASS",
        "default_release": CANDIDATE,
        "rollback_release": ROLLBACK,
        "promoted_build": PROMOTED_BUILD,
        "rollback_build": ROLLBACK_BUILD,
        "promoted_descriptor_hash": descriptor_hash,
    }


def _selfcheck() -> int:
    deployment = _read_json("config/dsh/deployment.json")
    release = _read_json(f"config/dsh/releases/{CANDIDATE}.json")
    candidate = _read_json(f"config/dsh/candidates/{CANDIDATE}/candidate.json")
    identity = _read_json("config/dsh/generated/deployment.identity.json")
    rollback_release = _read_json(f"config/dsh/releases/{ROLLBACK}.json")
    rollback_identity = _read_json(f"config/dsh/generated/{ROLLBACK}.identity.json")
    build_id = PROMOTED_BUILD
    manifest = _read_json(f"config/dsh/builds/{PROMOTED_BUILD}.json")
    descriptor_hash = "sha256:" + hashlib.sha256(
        (RELEASES / f"{CANDIDATE}.json").read_bytes()).hexdigest()
    import copy

    negatives = []
    for field in ("default_release", "candidate_releases"):
        value = copy.deepcopy(deployment)
        value[field] = "dsh-0.1.1rc1" if field == "default_release" else []
        negatives.append(("deployment-" + field, lambda v=value: check_deployment(v)))
    value = copy.deepcopy(release); value["python"]["runtime_bin"] = "0.1.2rc1"
    negatives.append(("release-mixed-pair", lambda v=value: check_promoted_release(v, candidate)))
    value = copy.deepcopy(candidate); value["status"] = "candidate-unqualified"
    negatives.append(("candidate-not-promoted", lambda v=value: check_promoted_release(release, v)))
    value = copy.deepcopy(candidate); value["production_boundary"]["default_release_unchanged"] = True
    negatives.append(("candidate-false-boundary", lambda v=value: check_promoted_release(release, v)))
    value = copy.deepcopy(identity); value["default_release"] = ROLLBACK
    negatives.append(("identity-wrong-default", lambda v=value: check_selector_identity(v)))
    negatives.append(("pyproject-drift", lambda: check_dependencies(
        "deepseek-harness-sdk==0.1.2rc1", "deepseek-harness-sdk==0.1.5rc1 deepseek-harness-runtime-bin==0.1.5rc1")))
    negatives.append(("lock-drift", lambda: check_dependencies(
        '"deepseek-harness-sdk==0.1.5rc1" "deepseek-harness-runtime-bin==0.1.5rc1"',
        "deepseek-harness-sdk==0.1.2rc1")))
    negatives.append(("image-selector-drift", lambda: check_image(
        "BYQ_DSH_COMPATIBILITY_RELEASE=dsh-0.1.2rc1", build_id)))
    negatives.append(("build-release-drift", lambda: check_build(
        build_id, {**manifest, "release_id": ROLLBACK}, descriptor_hash)))
    negatives.append(("build-descriptor-drift", lambda: check_build(
        build_id, manifest, "sha256:" + "0" * 64)))
    value = copy.deepcopy(deployment); value["candidate_releases"] = []
    negatives.append(("rollback-not-candidate", lambda v=value: check_rollback(
        v, rollback_release, rollback_identity)))
    value = copy.deepcopy(rollback_identity); value["default_release"] = CANDIDATE
    negatives.append(("rollback-identity-drift", lambda v=value: check_rollback(
        deployment, rollback_release, v)))
    failures = []
    for name, call in negatives:
        try:
            call()
        except Drift:
            continue
        failures.append(name)
    if failures:
        print(json.dumps({"status": "FAIL", "undetected_negatives": failures}))
        return 1
    print(json.dumps({"status": "PASS", "negative_controls": len(negatives),
                      "defect_targeting": len(negatives)}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args()
    if args.selfcheck:
        return _selfcheck()
    try:
        print(json.dumps(verify(), indent=2))
    except Drift as error:
        print(json.dumps({"status": "FAIL", "reason": str(error)}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
