#!/usr/bin/env python3
"""Immutable BYQ operational build revisions referencing unchanged releases."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
BUILDS = ROOT / "config/dsh/builds"
RELEASES = {"dsh-0.1.2rc1"}
RETIRED_BUILD = "dsh-0.1.1rc1-post-u8.30"
RETIRED_SOURCE = "b6c8034ed638447aa1d0ddd82af9738df830bbdf"
KEYS = {"schema_version", "build_id", "release_id", "release_descriptor_hash", "dockerfile", "inputs"}
SOURCE_ROOTS = (
    "services/runtime-adapter/app", "services/gateway/app", "services/backend/app",
    "services/mcp/src", "apps/frontend/src", "packages/contracts", "packages/operations",
    "plugins/dsh-byq",
    "services/runtime-adapter/tests", "services/runtime-adapter/runtime",
    "services/gateway/tests", "services/backend/tests", "services/mcp/tests",
    "apps/frontend/tests",
    "workers", "services/signal-sandbox", "infra/postgres/init",
    "scripts", "tests",
)
FIXED_INPUTS = (
    "services/gateway/Dockerfile", "services/gateway/pyproject.toml",
    "services/backend/Dockerfile", "services/backend/pyproject.toml",
    "services/mcp/Dockerfile", "services/mcp/package.json", "services/mcp/package-lock.json",
    "apps/frontend/Dockerfile", "apps/frontend/package.json", "apps/frontend/package-lock.json",
    "services/runtime-adapter/pyproject.toml", "services/runtime-adapter/requirements.candidate.lock",
    "config/dsh/archive/dsh-0.1.1rc1/package.json.archive",
    "config/dsh/archive/dsh-0.1.1rc1/package-lock.json.archive",
    "scripts/dsh/build_revision.py",
    "scripts/dsh/historical_inputs.py", "scripts/dsh/release.py",
    "scripts/ci/local-ci.sh", "compose.yml",
    ".dockerignore", "services/mcp/tsconfig.json", "apps/frontend/nginx.conf",
    "apps/frontend/index.html", "apps/frontend/vite.config.ts", "apps/frontend/tsconfig.app.json",
    "apps/frontend/tsconfig.json", "apps/frontend/tsconfig.node.json",
    "apps/frontend/vitest.config.ts", "apps/frontend/playwright.config.ts",
    "apps/frontend/playwright.real.config.ts", "apps/frontend/playwright.f6.config.ts", ".github/workflows/ci-selfhosted.yml",
    "docs/contracts/product-capability-catalog.v1.json",
    "config/dsh/generated/web-evidence-provenance.json",
    "config/dsh/deployment.json", "config/dsh/generated/dsh-0.1.1rc1.identity.json",
    "config/dsh/generated/product-plugin-registry.json",
    "config/dsh/generated/qualified-web-evidence-provenance.json",
    "config/dsh/generated/qualified-rollback-web-evidence-provenance.json",
    "scripts/dsh/promotion.py", "scripts/dsh/plugin_registry.py",
    "scripts/dsh/web_evidence_provenance.py",
)


def digest(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def selected_build_id(release):
    if release == "dsh-0.1.1rc1":
        return RETIRED_BUILD  # Historical identity only; never a current build.
    if release not in RELEASES:
        raise ValueError("unregistered release")
    return release + "-post-u8.33"


def identity(build_id):
    match = re.fullmatch(r"(dsh-0\.1\.[12]rc1)-(u6|u7|post-u8)\.([1-9][0-9]*)", str(build_id))
    if not match:
        raise ValueError("exact registered release and U6/U7/Post-U8 build revision required")
    release = match[1]
    dockerfile = "services/runtime-adapter/Dockerfile." + match[2] + ("-candidate" if release.endswith("2rc1") else "")
    return release, dockerfile


def inventory(release, dockerfile):
    descriptor_path = ROOT / "config/dsh/releases" / f"{release}.json"
    descriptor = json.loads(descriptor_path.read_text())
    paths = set(FIXED_INPUTS) | set(descriptor["build_inputs"]) | {dockerfile}
    paths.add(str(descriptor_path.relative_to(ROOT)))
    paths.add("config/dsh/generated/deployment.identity.json")
    paths.add("config/dsh/generated/dsh-0.1.2rc1.identity.json")
    paths.add("config/dsh/generated/dsh-0.1.2rc1.web-evidence-provenance.json")
    for source in SOURCE_ROOTS:
        directory = ROOT / source
        if not directory.is_dir():
            raise ValueError(f"missing source inventory: {source}")
        for path in directory.rglob("*"):
            if any(part in {"node_modules", "__pycache__", ".git"} for part in path.relative_to(directory).parts):
                continue
            if path.is_file():
                paths.add(str(path.relative_to(ROOT)))
    result = {}
    for relative in sorted(paths):
        path = ROOT / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError(f"invalid current build input: {relative}")
        result[relative] = digest(path)
    return result


def render(build_id):
    release, dockerfile = identity(build_id)
    if release not in RELEASES:
        raise ValueError("retired release cannot be rebuilt from current sources")
    if f"COPY config/dsh/builds/{build_id}.json /opt/byq/builds/build.identity.json" not in (ROOT / dockerfile).read_text():
        raise ValueError("Dockerfile must embed the exact selected build manifest")
    return {"schema_version": "byq-dsh-build.v1", "build_id": build_id, "release_id": release,
            "release_descriptor_hash": digest(ROOT / "config/dsh/releases" / f"{release}.json"),
            "dockerfile": dockerfile, "inputs": inventory(release, dockerfile)}


def validate(value):
    if not isinstance(value, dict) or set(value) != KEYS:
        raise ValueError("build revision has invalid closed schema")
    expected = render(value["build_id"])
    if value != expected:
        raise ValueError("build revision drift, missing input or release mismatch")
    return value


def check(build_id):
    identity(build_id)
    if build_id == RETIRED_BUILD:
        try:
            from scripts.dsh.historical_inputs import read_blob
        except ModuleNotFoundError:
            from historical_inputs import read_blob
        relative = f"config/dsh/builds/{build_id}.json"
        archived = read_blob(RETIRED_SOURCE, relative)
        if (ROOT / relative).read_bytes() != archived:
            raise ValueError("retired build manifest changed")
        return json.loads(archived)
    path = BUILDS / f"{build_id}.json"
    return validate(json.loads(path.read_text()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "check"))
    parser.add_argument("--build", required=True)
    args = parser.parse_args()
    identity(args.build)
    path = BUILDS / f"{args.build}.json"
    if args.action == "create":
        # No refresh/overwrite flag: historical revisions are immutable.
        value = render(args.build)
        with path.open("x") as output:
            json.dump(value, output, indent=2, sort_keys=True)
            output.write("\n")
    else:
        check(args.build)
    print(json.dumps({"build_id": args.build, "manifest_hash": digest(path), "status": "PASS"}))


if __name__ == "__main__":
    main()
