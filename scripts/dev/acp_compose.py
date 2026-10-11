#!/usr/bin/env python3
"""Canonical ACP Compose build/up for local Engineering entry points.

ADR-0110 single-image: the adapter / product / judgment services share one build
and one image tag. A plain ``docker compose build`` (or ``up --build``) would try
to build that one tag three times, which fails or exports conflicting artifacts.
This helper derives the merged topology from the checked-in Compose route and:

* single-image: builds the selected services and their dependency closure once,
  minus the two non-canonical ACP role targets (``runtime-adapter`` is the single
  ACP build), then runs the action with ``--no-build``;
* per-role route: passes through unchanged.

A missing, partial or unknown ACP declaration fails closed. This is a small
Engineering helper, not a second generic harness: it only reorders the existing
``docker compose`` calls around the one shared ACP build.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.release.images import (  # noqa: E402
    ACP_ROLE_ENVIRONMENT,
    ACP_UNIFIED_DOCKERFILE,
    classify_acp_topology,
)

ACP_ROLE_SERVICES = ("runtime-adapter", "acp-product-runner", "acp-judgment-runner")
ACP_CANONICAL_TARGET = "runtime-adapter"
ACP_EXTRA_ROLE_TARGETS = ("acp-product-runner", "acp-judgment-runner")
SINGLE_IMAGE = "single-image"
PER_ROLE_IMAGE = "per-role-image"


class ComposeError(Exception):
    pass


def default_compose_prefix() -> list[str]:
    """The same resolver-fed Compose entry the Makefile uses by default."""
    return [
        sys.executable, str(ROOT / "scripts/dsh/acp_build.py"), "--",
        "docker", "compose",
        "-f", str(ROOT / "compose.yml"),
        "-f", str(ROOT / "compose.override.yml"),
    ]


def parse_compose_command(value: str) -> list[str]:
    """Split an explicit Compose command prefix with shlex, never shell eval.

    A Makefile ``COMPOSE`` may carry a custom prefix including ``-f`` files and
    profiles; the tokens must be preserved exactly. An empty or unbalanced
    command fails closed.
    """
    if not isinstance(value, str) or not value.strip():
        raise ComposeError("--compose-command must not be empty")
    try:
        command = shlex.split(value)
    except ValueError as exc:
        raise ComposeError("--compose-command is not a valid shell-quoted command") from exc
    if not command:
        raise ComposeError("--compose-command must not be empty")
    return command


def parse_config(prefix: list[str], *, env: dict[str, str] | None = None) -> dict:
    result = subprocess.run(
        [*prefix, "config", "--format", "json"],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False,
    )
    if result.returncode:
        raise ComposeError("Compose configuration failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ComposeError("invalid Compose configuration") from exc


def acp_topology(config: dict) -> str:
    """Return single-image or per-role-image; fail closed on a partial route.

    ADR-0110: this merged-config helper reuses the one central classification in
    ``scripts/release/images.py`` so the two derivations cannot drift. A
    single-image route must additionally build the known unified Dockerfile and
    declare the correct fail-closed ``BYQ_ACP_ROLE`` dispatch for each role; an
    unknown shared Dockerfile or a missing/incorrect role mapping fails closed
    instead of being accepted as the shared image.
    """
    services = config.get("services")
    if not isinstance(services, dict):
        raise ComposeError("Compose configuration lacks services")
    builds: dict[str, object] = {}
    images: dict[str, object] = {}
    for name in ACP_ROLE_SERVICES:
        service = services.get(name)
        if not isinstance(service, dict):
            raise ComposeError(f"Compose configuration lacks ACP role service {name}")
        build = service.get("build")
        builds[name] = build if isinstance(build, dict) else None
        image = service.get("image")
        images[name] = image if isinstance(image, str) and image else None
    try:
        topology = classify_acp_topology(builds, images)
    except ValueError as exc:
        raise ComposeError(str(exc)) from exc
    if topology == SINGLE_IMAGE:
        for name in ACP_ROLE_SERVICES:
            if builds[name].get("dockerfile") != ACP_UNIFIED_DOCKERFILE:
                raise ComposeError(
                    "single-image ACP route must build the known unified "
                    "Dockerfile; a stale ACP role build is not accepted")
            environment = services[name].get("environment")
            if (not isinstance(environment, dict)
                    or environment.get("BYQ_ACP_ROLE") != ACP_ROLE_ENVIRONMENT[name]):
                raise ComposeError(
                    "single-image ACP route must declare the correct "
                    f"BYQ_ACP_ROLE={ACP_ROLE_ENVIRONMENT[name]} dispatch for {name}")
    return topology


def dependency_closure(config: dict, services: list[str]) -> list[str]:
    known = config.get("services") or {}
    ordered: list[str] = []
    pending = list(services)
    while pending:
        name = pending.pop(0)
        if name in ordered:
            continue
        ordered.append(name)
        depends_on = known.get(name, {}).get("depends_on") or {}
        pending.extend(depends_on)
    return ordered


def build_targets(config: dict, services: list[str]) -> list[str]:
    """Return the exact ``compose build`` target list for the selected services.

    Under single-image the two non-canonical ACP role targets are removed and one
    canonical ACP target is ensured, so the shared image is built exactly once.
    """
    if services:
        selected = dependency_closure(config, services)
    else:
        selected = list((config.get("services") or {}).keys())
    if acp_topology(config) == SINGLE_IMAGE:
        # Decide "any ACP present" from the dependency closure BEFORE removing
        # the non-canonical role targets. A selected non-ACP service that
        # depends on a runner still pulls a role into the closure, so the one
        # shared canonical image must still be built exactly once.
        has_acp = any(name in ACP_ROLE_SERVICES for name in selected)
        selected = [name for name in selected if name not in ACP_EXTRA_ROLE_TARGETS]
        if has_acp and ACP_CANONICAL_TARGET not in selected:
            selected.append(ACP_CANONICAL_TARGET)
    known = config.get("services") or {}
    return [name for name in selected if "build" in (known.get(name) or {})]


def canonical_build(prefix: list[str], config: dict, services: list[str],
                    *, env: dict[str, str] | None = None) -> int:
    targets = build_targets(config, services)
    if not targets:
        return 0
    return subprocess.run([*prefix, "build", *targets], cwd=ROOT, env=env,
                          check=False).returncode


def canonical_up(prefix: list[str], config: dict, services: list[str],
                 *, env: dict[str, str] | None = None) -> int:
    """Build the one shared ACP image once, then start with ``--no-build``."""
    status = canonical_build(prefix, config, services, env=env)
    if status:
        return status
    command = [*prefix, "up", "-d", "--wait", "--no-build", *services]
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "up"))
    parser.add_argument("services", nargs="*")
    parser.add_argument(
        "--compose-command", default=None,
        help="explicit Compose command prefix (shell-quoted); defaults to the "
             "resolver-fed default Compose entry")
    args = parser.parse_args(argv)
    try:
        if args.compose_command is not None:
            prefix = parse_compose_command(args.compose_command)
        else:
            prefix = default_compose_prefix()
        config = parse_config(prefix)
        if args.action == "build":
            return canonical_build(prefix, config, args.services)
        return canonical_up(prefix, config, args.services)
    except ComposeError as exc:
        print(f"ACP Compose helper: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
