#!/usr/bin/env python3
"""Fail-closed resolver for the ACP authoritative DSH build identity."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = "config/dsh/acp/authoritative.json"
SCHEMA = "byq-dsh-authoritative-version.v1"
RELEASE = "dsh-v0.2.0-rc.2"
COMPATIBILITY_FAMILY_BY_RELEASE = {RELEASE: "dsh-v0.2.0-rc.2-acp"}
ROLES = {"adapter", "ordinary_runner", "judgment_runner"}
PROFILES = {"product", "product_identity", "judgment", "judgment_identity", "release_identity"}
CAPABILITIES = {
    "ordinary_root_reuse", "f6_continuation", "judgment_acp_lifecycle",
    "interrupted_business_continuation_new_child",
}
PROFILE_ROOT = PurePosixPath("plugins/dsh-byq/profiles/acp-0.2.0-rc.2")
PATH_ROOTS = {name: PROFILE_ROOT for name in (
    "product", "product_identity", "judgment", "judgment_identity"
)}
PATH_ROOTS["release_identity"] = PurePosixPath("config/dsh")
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class AuthoritativeVersionError(ValueError):
    """The manifest or one of its pinned files is invalid."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AuthoritativeVersionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except AuthoritativeVersionError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuthoritativeVersionError(f"cannot read {context}") from exc
    if not isinstance(value, dict):
        raise AuthoritativeVersionError(f"{context} must be a JSON object")
    return value


def _object(value: Any, keys: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuthoritativeVersionError(f"{context} must be an object")
    actual = set(value)
    if actual != keys:
        raise AuthoritativeVersionError(
            f"{context} schema mismatch (missing={sorted(keys - actual)}, unknown={sorted(actual - keys)})"
        )
    return value


def _text(value: Any, context: str) -> str:
    if type(value) is not str or not value:
        raise AuthoritativeVersionError(f"{context} must be a non-empty string")
    return value


def _repo_file(root: Path, relative: Any, context: str) -> Path:
    if type(relative) is not str or not relative or not re.fullmatch(r"[A-Za-z0-9._/-]+", relative):
        raise AuthoritativeVersionError(f"{context} path must be a restricted repository-relative path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or pure.as_posix() != relative or any(part in {"", ".", ".."} for part in pure.parts):
        raise AuthoritativeVersionError(f"{context} path escapes the repository")
    candidate = root
    try:
        for part in pure.parts:
            candidate = candidate / part
            if stat.S_ISLNK(candidate.lstat().st_mode):
                raise AuthoritativeVersionError(f"{context} path contains a symlink")
        candidate.resolve(strict=True).relative_to(root)
        if not stat.S_ISREG(candidate.stat().st_mode):
            raise AuthoritativeVersionError(f"{context} path is not a regular file")
    except AuthoritativeVersionError:
        raise
    except (OSError, ValueError) as exc:
        raise AuthoritativeVersionError(f"{context} path is missing or escapes the repository") from exc
    return candidate


def _sha(value: Any, context: str) -> str:
    if type(value) is not str or not SHA256_RE.fullmatch(value):
        raise AuthoritativeVersionError(f"{context} must be a lowercase 64-hex SHA-256")
    return value


def _profile_identity(path: Path, name: str) -> dict[str, Any]:
    identity = _read_json(path, f"{name} identity")
    expected = {
        "product_identity": "byq-product-acp-0.2.0-rc.2",
        "judgment_identity": "byq-research-judgment-acp-0.2.0-rc.2",
    }[name]
    if identity.get("schema_version") != "byq-dsh-composition-identity.v1":
        raise AuthoritativeVersionError(f"{name} identity schema is unsupported")
    if identity.get("profile") != expected:
        raise AuthoritativeVersionError(f"{name} identity names another profile")
    return identity


def load_authoritative_version(root: Path | None = None) -> dict[str, Any]:
    """Validate the manifest and return safe, non-secret build selection values."""
    try:
        repository = (Path(root) if root is not None else ROOT).resolve(strict=True)
        if not repository.is_dir():
            raise AuthoritativeVersionError("repository root is not a directory")
    except (OSError, RuntimeError) as exc:
        raise AuthoritativeVersionError("repository root is unavailable") from exc

    manifest = _read_json(
        _repo_file(repository, MANIFEST_PATH, "authoritative manifest"),
        "authoritative manifest",
    )
    manifest = _object(manifest, {
        "schema_version", "release_id", "source_commit", "pnpm_lock_sha256",
        "roles", "profiles", "capabilities", "rollback",
    }, "authoritative manifest")
    if manifest["schema_version"] != SCHEMA:
        raise AuthoritativeVersionError("unsupported authoritative manifest schema")
    release = _text(manifest["release_id"], "manifest.release_id")
    if release != RELEASE or release not in COMPATIBILITY_FAMILY_BY_RELEASE:
        raise AuthoritativeVersionError("manifest.release_id is not the fixed ACP release")
    commit = _text(manifest["source_commit"], "manifest.source_commit")
    if not COMMIT_RE.fullmatch(commit):
        raise AuthoritativeVersionError("manifest.source_commit must be lowercase 40-hex")
    lock_sha = _sha(manifest["pnpm_lock_sha256"], "manifest.pnpm_lock_sha256")

    roles = _object(manifest["roles"], ROLES, "manifest.roles")
    for role, value in roles.items():
        if _text(value, f"manifest.roles.{role}") != release:
            raise AuthoritativeVersionError(f"manifest.roles.{role} differs from manifest.release_id")

    raw_profiles = _object(manifest["profiles"], PROFILES, "manifest.profiles")
    profiles: dict[str, dict[str, str]] = {}
    files: dict[str, Path] = {}
    for name, raw in raw_profiles.items():
        entry = _object(raw, {"path", "sha256"}, f"manifest.profiles.{name}")
        relative = _text(entry["path"], f"manifest.profiles.{name}.path")
        pure = PurePosixPath(relative)
        prefix = PATH_ROOTS[name]
        if pure.parts[:len(prefix.parts)] != prefix.parts:
            raise AuthoritativeVersionError(f"manifest.profiles.{name}.path is outside its allowed directory")
        expected_sha = _sha(entry["sha256"], f"manifest.profiles.{name}.sha256")
        path = _repo_file(repository, relative, f"manifest.profiles.{name}")
        try:
            actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise AuthoritativeVersionError(f"cannot hash profile {name}") from exc
        if actual_sha != expected_sha:
            raise AuthoritativeVersionError(f"manifest.profiles.{name} SHA-256 does not match the file")
        profiles[name] = {"path": relative, "sha256": expected_sha}
        files[name] = path

    if PurePosixPath(profiles["product"]["path"]).parent != PurePosixPath(profiles["product_identity"]["path"]).parent:
        raise AuthoritativeVersionError("product profile and identity must share a directory")
    if PurePosixPath(profiles["judgment"]["path"]).parent != PurePosixPath(profiles["judgment_identity"]["path"]).parent:
        raise AuthoritativeVersionError("judgment profile and identity must share a directory")

    product_id = _profile_identity(files["product_identity"], "product_identity")
    if product_id.get("composition_hash") != "sha256:" + profiles["product"]["sha256"]:
        raise AuthoritativeVersionError("product identity does not bind the product profile hash")
    judgment_id = _profile_identity(files["judgment_identity"], "judgment_identity")
    if judgment_id.get("composition_hash") != "sha256:" + profiles["judgment"]["sha256"]:
        raise AuthoritativeVersionError("judgment identity does not bind the judgment profile hash")
    if judgment_id.get("release_id") != release or judgment_id.get("source_commit") != commit:
        raise AuthoritativeVersionError("judgment identity differs from the manifest release")

    release_id = _object(
        _read_json(files["release_identity"], "release identity"),
        {"schema_version", "release_id", "source_commit", "pnpm_lock_sha256"},
        "release identity",
    )
    if release_id != {
        "schema_version": "dsh-acp-deployment-identity.v1",
        "release_id": release,
        "source_commit": commit,
        "pnpm_lock_sha256": lock_sha,
    }:
        raise AuthoritativeVersionError("release identity differs from the authoritative manifest")

    capabilities = _object(manifest["capabilities"], CAPABILITIES, "manifest.capabilities")
    for name, raw in capabilities.items():
        cap = _object(raw, {"adr", "evidence"}, f"manifest.capabilities.{name}")
        _text(cap["adr"], f"manifest.capabilities.{name}.adr")
        _text(cap["evidence"], f"manifest.capabilities.{name}.evidence")
    rollback = _object(manifest["rollback"], {"release_id", "offline_only", "note"}, "manifest.rollback")
    if rollback["release_id"] != "dsh-0.1.5rc1" or rollback["offline_only"] is not True:
        raise AuthoritativeVersionError("SDK rollback must remain offline-only")
    _text(rollback["note"], "manifest.rollback.note")

    return {
        "schema_version": SCHEMA,
        "release_id": release,
        "source_commit": commit,
        "pnpm_lock_sha256": lock_sha,
        "roles": {name: release for name in sorted(ROLES)},
        "profiles": profiles,
        "compatibility_family": COMPATIBILITY_FAMILY_BY_RELEASE[release],
        "sdk_online_fallback": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve the authoritative ACP DSH selection.")
    parser.parse_args(argv)
    try:
        selection = load_authoritative_version()
    except AuthoritativeVersionError as exc:
        print(f"authoritative DSH version rejected: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(selection, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
