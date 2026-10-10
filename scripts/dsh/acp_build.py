#!/usr/bin/env python3
"""Resolve and verify build identity for the explicit ACP candidate lane."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dsh.authoritative_version import (  # noqa: E402
    AuthoritativeVersionError,
    load_authoritative_version,
)


ROLE_PROFILE_KEYS = {
    "adapter": ("product", "product_identity", "release_identity"),
    "ordinary_runner": ("product", "product_identity", "release_identity"),
    "judgment_runner": ("judgment", "judgment_identity", None),
}


def _role_environment_prefix(role: str) -> str:
    return {
        "adapter": "BYQ_DSH_BUILD_ADAPTER",
        "ordinary_runner": "BYQ_DSH_BUILD_ORDINARY_RUNNER",
        "judgment_runner": "BYQ_DSH_BUILD_JUDGMENT_RUNNER",
    }[role]


def build_environment(selection: dict[str, object]) -> dict[str, str]:
    """Flatten resolver output into explicit, non-secret Compose build inputs."""
    profiles = selection["profiles"]
    if not isinstance(profiles, dict):
        raise AuthoritativeVersionError("resolved profiles are invalid")
    compatibility_family = str(selection["compatibility_family"])
    env = {
        "BYQ_DSH_BUILD_RELEASE_ID": str(selection["release_id"]),
        "BYQ_DSH_BUILD_SOURCE_COMMIT": str(selection["source_commit"]),
        "BYQ_DSH_BUILD_PNPM_LOCK_SHA256": str(selection["pnpm_lock_sha256"]),
        "BYQ_DSH_BUILD_COMPATIBILITY_FAMILY": compatibility_family,
        "BYQ_DSH_BUILD_SESSION_ROOT": f"/var/lib/byq/dsh-sessions/{compatibility_family}",
    }
    for role, (profile_name, identity_name, release_identity_name) in ROLE_PROFILE_KEYS.items():
        prefix = _role_environment_prefix(role)
        for suffix, key in (("PROFILE", profile_name), ("PROFILE_IDENTITY", identity_name)):
            entry = profiles.get(key)
            if not isinstance(entry, dict):
                raise AuthoritativeVersionError(f"resolved profile {key} is invalid")
            env[f"{prefix}_{suffix}_PATH"] = str(entry["path"])
            env[f"{prefix}_{suffix}_SHA256"] = str(entry["sha256"])
        if release_identity_name is not None:
            entry = profiles.get(release_identity_name)
            if not isinstance(entry, dict):
                raise AuthoritativeVersionError("resolved release identity is invalid")
            env[f"{prefix}_RELEASE_IDENTITY_PATH"] = str(entry["path"])
            env[f"{prefix}_RELEASE_IDENTITY_SHA256"] = str(entry["sha256"])
    return env


def _expected_build_args(selection: dict[str, object], role: str) -> dict[str, str]:
    if role not in ROLE_PROFILE_KEYS:
        raise AuthoritativeVersionError("unknown ACP DSH build role")
    profile_name, identity_name, release_identity_name = ROLE_PROFILE_KEYS[role]
    profiles = selection["profiles"]
    if not isinstance(profiles, dict):
        raise AuthoritativeVersionError("resolved profiles are invalid")

    expected = {
        "BYQ_DSH_BUILD_RELEASE_ID": str(selection["roles"][role]),
        "BYQ_DSH_BUILD_SOURCE_COMMIT": str(selection["source_commit"]),
        "BYQ_DSH_BUILD_PNPM_LOCK_SHA256": str(selection["pnpm_lock_sha256"]),
        "BYQ_DSH_BUILD_COMPATIBILITY_FAMILY": str(selection["compatibility_family"]),
    }
    for suffix, key in (("PROFILE", profile_name), ("PROFILE_IDENTITY", identity_name)):
        entry = profiles.get(key)
        if not isinstance(entry, dict):
            raise AuthoritativeVersionError(f"resolved profile {key} is invalid")
        expected[f"BYQ_DSH_BUILD_{suffix}_PATH"] = str(entry["path"])
        expected[f"BYQ_DSH_BUILD_{suffix}_SHA256"] = str(entry["sha256"])
    if release_identity_name is not None:
        entry = profiles.get(release_identity_name)
        if not isinstance(entry, dict):
            raise AuthoritativeVersionError("resolved release identity is invalid")
        expected["BYQ_DSH_BUILD_RELEASE_IDENTITY_PATH"] = str(entry["path"])
        expected["BYQ_DSH_BUILD_RELEASE_IDENTITY_SHA256"] = str(entry["sha256"])
    return expected


def docker_build_arguments(selection: dict[str, object], role: str) -> dict[str, str]:
    """Return the single role-specific argument map expected by a Dockerfile."""
    return _expected_build_args(selection, role)


def verify_build_inputs(selection: dict[str, object], role: str, environ: dict[str, str]) -> None:
    """Require every Docker build argument to match the validated manifest."""
    for name, expected in _expected_build_args(selection, role).items():
        if environ.get(name) != expected:
            raise AuthoritativeVersionError(f"Docker build input {name} is missing or mismatched")


def command_environment(
    selection: dict[str, object], inherited: dict[str, str] | None = None
) -> dict[str, str]:
    """Preserve credentials while replacing caller-supplied ACP selectors."""
    env = dict(os.environ if inherited is None else inherited)
    for name in tuple(env):
        if name.startswith("BYQ_DSH_BUILD_"):
            del env[name]
    resolved = build_environment(selection)
    env.update(resolved)
    env["BYQ_DSH_COMPATIBILITY_RELEASE"] = resolved[
        "BYQ_DSH_BUILD_COMPATIBILITY_FAMILY"
    ]
    env["BYQ_DSH_SESSION_ROOT"] = resolved["BYQ_DSH_BUILD_SESSION_ROOT"]
    env["DSH_SESSION_ROOT"] = resolved["BYQ_DSH_BUILD_SESSION_ROOT"]
    return env


def _run_command(command: list[str]) -> int:
    if not command:
        raise AuthoritativeVersionError("a command after -- is required")
    selection = load_authoritative_version(ROOT)
    env = command_environment(selection)
    os.execvpe(command[0], command, env)
    return 127


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args and args[0] == "--verify-build-inputs":
            parser = argparse.ArgumentParser()
            parser.add_argument("--role", required=True, choices=tuple(ROLE_PROFILE_KEYS))
            parser.add_argument("--root", type=Path, default=ROOT)
            parsed = parser.parse_args(args[1:])
            selection = load_authoritative_version(parsed.root)
            verify_build_inputs(selection, parsed.role, dict(os.environ))
            return 0
        if not args or args[0] != "--":
            raise AuthoritativeVersionError(
                "usage: acp_build.py -- <candidate build command> | "
                "--verify-build-inputs --role ROLE [--root ROOT]"
            )
        return _run_command(args[1:])
    except AuthoritativeVersionError as exc:
        print(f"ACP DSH build rejected: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ACP DSH build command could not start: {exc}", file=sys.stderr)
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
