#!/usr/bin/env python3
"""Validate and select isolated DSH candidate declarations (D15).

Candidates live outside the immutable ``config/dsh/releases`` registry on
purpose: that registry pins every release to an archived Git tree
(``scripts/dsh/historical_inputs.py``) and must not be extended before a
candidate is qualified. A candidate declaration is a closed, machine-auditable
record that (a) proves the Python/npm/bundled pairing, (b) proves the production
default is untouched, and (c) names the compatibility selector path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = ROOT / "config/dsh/candidates"
KEYS = {
    "schema_version", "declaration_id", "status", "production_default",
    "qualification_target", "target_npm_version", "target_decision",
    "requested_npm_version", "coherent_npm_version", "upstream", "python",
    "runtime", "production_boundary", "qualification", "evidence",
}
STATUSES = {"candidate-unqualified", "candidate-qualified", "rejected", "promoted"}
UPSTREAM_KEYS = {
    "source_tag", "source_commit", "source_archive_sha256",
    "source_manifest_sha256", "bundled_package_count", "bundled_npm_version",
}
PYTHON_KEYS = {"sdk", "runtime_bin", "sdk_wheel_sha256",
               "linux_x86_64_runtime_wheel_sha256", "lock"}
RUNTIME_KEYS = {
    "entrypoint", "carrier_kind", "profile", "compatibility_module",
    "selector_env", "selector_value", "session_root", "isolated",
}
BOUNDARY_KEYS = {
    "default_release_unchanged", "default_env_unchanged",
    "existing_artifacts_untouched", "historical_evidence_untouched",
    "database_changes", "worker_restarts", "rollback_release",
}
QUALIFICATION_KEYS = {"state", "live_start_verified", "native_resume_verified",
                      "reason", "blocking_finding"}
EVIDENCE_KEYS = {"ledger", "recon"}


class CandidateError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CandidateError(message)


def _hex64(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value
    )


def load_candidate(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict) and set(value) == KEYS,
             f"{path}: candidate has invalid closed schema")
    _require(value["schema_version"] == "byq-dsh-candidate.v1",
             f"{path}: unknown candidate schema")
    identifier = value["declaration_id"]
    _require(isinstance(identifier, str) and identifier == path.parent.name,
             f"{path}: candidate id must match its directory")
    _require(value["status"] in STATUSES, f"{path}: unknown candidate status")
    promoted = value["status"] == "promoted"
    if promoted:
        # A promoted declaration records that this candidate became the current
        # repository default; the default pointer must agree with it.
        _require(value["production_default"] == identifier,
                 f"{path}: promoted candidate must name itself as the current default")
    else:
        _require(value["production_default"] != identifier,
                 f"{path}: candidate cannot be the production default")
    _require(isinstance(value["qualification_target"], str)
             and value["qualification_target"].startswith("dsh-v"),
             f"{path}: qualification target must be a dsh-v release tag")
    _require(isinstance(value["target_npm_version"], str)
             and value["target_npm_version"] == value["coherent_npm_version"],
             f"{path}: target npm version must equal the coherent npm version")
    _require((ROOT / value["target_decision"]).is_file(),
             f"{path}: target decision record is missing")
    upstream = value["upstream"]
    _require(isinstance(upstream, dict) and set(upstream) == UPSTREAM_KEYS,
             f"{path}: invalid upstream block")
    _require(isinstance(upstream["source_tag"], str) and upstream["source_tag"],
             f"{path}: source tag is required")
    _require(isinstance(upstream["source_commit"], str)
             and len(upstream["source_commit"]) == 40,
             f"{path}: source commit must be a 40-hex commit")
    for key in ("source_archive_sha256", "source_manifest_sha256"):
        _require(_hex64(upstream[key]), f"{path}: {key} must be a sha256 hex digest")
    _require(isinstance(upstream["bundled_package_count"], int)
             and upstream["bundled_package_count"] > 0,
             f"{path}: bundled package count must be positive")
    python = value["python"]
    _require(isinstance(python, dict) and set(python) == PYTHON_KEYS,
             f"{path}: invalid python block")
    _require(python["sdk"] == python["runtime_bin"],
             f"{path}: SDK and runtime-bin must match")
    _require(_hex64(python["sdk_wheel_sha256"])
             and _hex64(python["linux_x86_64_runtime_wheel_sha256"]),
             f"{path}: wheel hashes must be sha256 hex digests")
    lock = ROOT / python["lock"]
    _require(lock.is_file(), f"{path}: declared Python lock is missing")
    locked = json.loads(lock.read_text(encoding="utf-8"))
    _require(locked.get("release_id") == identifier,
             f"{path}: Python lock release mismatch")
    versions = {item["name"]: item["version"] for item in locked.get("packages", [])}
    _require(versions.get("deepseek-harness-sdk") == python["sdk"]
             and versions.get("deepseek-harness-runtime-bin") == python["runtime_bin"],
             f"{path}: Python lock does not pin the declared DSH versions")
    runtime = value["runtime"]
    _require(isinstance(runtime, dict) and set(runtime) == RUNTIME_KEYS,
             f"{path}: invalid runtime block")
    _require(runtime["selector_value"] == identifier,
             f"{path}: selector value must equal the candidate id")
    _require(runtime["isolated"] is True, f"{path}: candidate must be isolated")
    module = ROOT / runtime["compatibility_module"]
    _require(module.is_file(), f"{path}: compatibility module is missing")
    boundary = value["production_boundary"]
    _require(isinstance(boundary, dict) and set(boundary) == BOUNDARY_KEYS,
             f"{path}: invalid production boundary block")
    for key in ("default_release_unchanged", "default_env_unchanged",
                "existing_artifacts_untouched", "historical_evidence_untouched"):
        if promoted:
            # Promotion intentionally moves the default and adds release
            # artifacts; historical evidence is still never rewritten.
            if key in {"default_release_unchanged", "default_env_unchanged"}:
                _require(boundary[key] is False,
                         f"{path}: {key} must be false for a promoted candidate")
        else:
            _require(boundary[key] is True, f"{path}: {key} must be true for a candidate")
    _require(boundary["database_changes"] == "none"
             and boundary["worker_restarts"] == "none",
             f"{path}: candidate must not change the database or restart workers")
    _require(boundary["rollback_release"] != identifier,
             f"{path}: rollback release must differ from the candidate")
    qualification = value["qualification"]
    _require(isinstance(qualification, dict) and set(qualification) == QUALIFICATION_KEYS,
             f"{path}: invalid qualification block")
    _require(qualification["state"] in {"not-qualified", "qualified", "blocked"},
             f"{path}: unknown qualification state")
    if qualification["state"] == "qualified":
        _require(qualification["live_start_verified"] is True
                 and qualification["native_resume_verified"] is True,
                 f"{path}: qualified candidate requires live start and native resume evidence")
    _require((value["status"] in {"candidate-qualified", "promoted"})
             == (qualification["state"] == "qualified"),
             f"{path}: candidate status must agree with the qualification state")
    for relative in value["evidence"].values():
        _require(isinstance(relative, str) and (ROOT / relative).is_file(),
                 f"{path}: evidence reference is missing: {relative}")
    return value


def load_candidates() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for path in sorted(CANDIDATES.glob("*/candidate.json")):
        value = load_candidate(path)
        _require(value["declaration_id"] not in result, f"duplicate candidate: {path}")
        result[value["declaration_id"]] = value
    return result


def compatibility_selector(release: str) -> dict | None:
    """Return the isolation descriptor for a candidate release, if declared."""
    candidate = load_candidates().get(release)
    if candidate is None:
        return None
    return {
        "release": release,
        "compatibility_module": candidate["runtime"]["compatibility_module"],
        "selector_env": candidate["runtime"]["selector_env"],
        "selector_value": candidate["runtime"]["selector_value"],
        "status": candidate["status"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "selector"))
    parser.add_argument("--release")
    args = parser.parse_args()
    if args.command == "check":
        candidates = load_candidates()
        print(json.dumps({"status": "ok", "candidates": sorted(candidates)}))
        return 0
    if not args.release:
        raise SystemExit("--release is required for selector")
    print(json.dumps(compatibility_selector(args.release), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
