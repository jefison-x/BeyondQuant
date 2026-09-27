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
RELEASES = {"dsh-0.1.5rc1"}
# Frozen rollback revisions retained for the historical U5/U6/U7 stacks and
# previous Clean Break defaults. They are referenced by exact identity only and
# are never re-rendered from current sources.
HISTORICAL_BUILDS = {"dsh-0.1.2rc1": "dsh-0.1.2rc1-post-u8.199"}
RETIRED_BUILD = "dsh-0.1.1rc1-post-u8.30"
RETIRED_SOURCE = "b6c8034ed638447aa1d0ddd82af9738df830bbdf"
# Previous defaults remain bound to their original revision-specific Dockerfiles.
# They are historical evidence only; current source changes get a new immutable
# Dockerfile and manifest.
FROZEN_BUILDS = {
    "dsh-0.1.5rc1-post-u8.215": "sha256:81a7631851ca3d90caa8ce15b27911b45e3d1cb8537189ca973a534271106c56",
    "dsh-0.1.5rc1-post-u8.216": "sha256:0a28e9c6037f82caf367df1928217439f7e3936669f334c60fc1603226aa57ee",
    "dsh-0.1.5rc1-post-u8.217": "sha256:249ef7d02019b52596f74182164a323a902a7597ba9f5f41f12ddc19c98bcb19",
    "dsh-0.1.5rc1-post-u8.218": "sha256:c169e2a340ccf83a1b59d1c79a42e8d969ca478601df004dd1df94e306cd30a4",
    "dsh-0.1.5rc1-post-u8.219": "sha256:9e2c09fa832d8dca6fa989bf9a83adb2ebf8f66b2f6ceb79cf1cebe44219357d",
    "dsh-0.1.5rc1-post-u8.220": "sha256:9f02f3649ff5dc968157d4fc87d1907e1df04ff95e0cc7024e40b5077ce45eed",
    "dsh-0.1.5rc1-post-u8.221": "sha256:cf0000e93c1616db0640667eb91329fc02b01d95d32003fbf3701903075979c7",
    "dsh-0.1.5rc1-post-u8.222": "sha256:f615206b481c0914dc8c53ab8b632c4cf507d6bd1ca77ff51c601ffc5e225a66",
    "dsh-0.1.5rc1-post-u8.223": "sha256:969e4629dfa95ad494d28a958d9e40b3401393c99acff7d0d8425f3d9b1c1660",
    "dsh-0.1.5rc1-post-u8.224": "sha256:14728a669b4285fd99b0fffeea035010a6dfbc01355a6ccaf6a5f4520bb2e762",
    "dsh-0.1.5rc1-post-u8.225": "sha256:ffca2b671d3de7967195d75cd6be689f217caea452117bb9cf825e7d04a4a824",
    "dsh-0.1.5rc1-post-u8.226": "sha256:d5b2dc0f1c606d1ae7e063e832f50820d797b9f4f26c9c61fbb6d00bda0d0a14",
    "dsh-0.1.5rc1-post-u8.227": "sha256:13e0c76bce80fcb46e86617cbf40cd0f67dd699a5391f4fd938edf08f1be6961",
    "dsh-0.1.5rc1-post-u8.228": "sha256:5a05e4ef0609ac148c98a21b2d18565020591e9db4c12b00636aa18980585afd",
    "dsh-0.1.5rc1-post-u8.229": "sha256:c249fedeef8894c532afd2c16e7e850be68910fd6a85447434611d0aed7ad293",
    "dsh-0.1.5rc1-post-u8.230": "sha256:8738222d9e4f216921f93fb8c28730e6858582e6bf8fd80c3d8b141c64211113",
    "dsh-0.1.5rc1-post-u8.231": "sha256:3adc54d054145cd0f6d8b67b055f57edab5e3bc28acfd055a692ace922c1f2ac",
}
KEYS = {"schema_version", "build_id", "release_id", "release_descriptor_hash", "dockerfile", "inputs"}
SOURCE_ROOTS = (
    "services/runtime-adapter/app", "services/gateway/app", "services/backend/app",
    "services/mcp/src", "apps/frontend/src", "packages/contracts", "packages/operations",
    "plugins/dsh-byq",
    "services/runtime-adapter/tests", "services/runtime-adapter/runtime",
    "services/gateway/tests", "services/backend/tests", "services/mcp/tests",
    "apps/frontend/tests",
    "workers", "services/signal-sandbox", "infra/postgres/init",
    "services/feedback-hub-cloudflare/src", "deploy/feedback-hub-cloudflare/migrations",
    "deploy/feedback-hub-cloudflare/tests", "deploy/feedback-hub-cloudflare/scripts",
    "scripts", "tests", ".github/workflows",
)
FIXED_INPUTS = (
    "deploy/feedback-hub-cloudflare/package.json", "deploy/feedback-hub-cloudflare/package-lock.json",
    "deploy/feedback-hub-cloudflare/tsconfig.json", "deploy/feedback-hub-cloudflare/vitest.config.ts",
    "deploy/feedback-hub-cloudflare/wrangler.hub.jsonc", "deploy/feedback-hub-cloudflare/wrangler.publisher.jsonc",
    "services/gateway/Dockerfile", "services/gateway/pyproject.toml",
    "services/backend/Dockerfile", "services/backend/pyproject.toml",
    "services/mcp/Dockerfile", "services/mcp/package.json", "services/mcp/package-lock.json",
    "apps/frontend/Dockerfile", "apps/frontend/package.json", "apps/frontend/package-lock.json",
    "services/runtime-adapter/pyproject.toml", "services/runtime-adapter/requirements.candidate.lock",
    "services/runtime-adapter/Dockerfile.dsh-0.1.5rc1-candidate",
    "services/runtime-adapter/Dockerfile.dsh-0.1.5rc1-continuable-candidate",
    "services/runtime-adapter/requirements.dsh-0.1.5rc1-candidate.lock",
    "config/dsh/archive/dsh-0.1.1rc1/package.json.archive",
    "config/dsh/archive/dsh-0.1.1rc1/package-lock.json.archive",
    "scripts/dsh/build_revision.py",
    "scripts/dsh/historical_inputs.py", "scripts/dsh/release.py",
    "scripts/ci/local-ci.sh", "compose.yml", "compose.override.yml",
    ".dockerignore", "services/mcp/tsconfig.json", "apps/frontend/nginx.conf",
    "apps/frontend/index.html", "apps/frontend/vite.config.ts", "apps/frontend/tsconfig.app.json",
    "apps/frontend/tsconfig.json", "apps/frontend/tsconfig.node.json",
    "apps/frontend/vitest.config.ts", "apps/frontend/playwright.config.ts",
    "apps/frontend/playwright.real.config.ts", "apps/frontend/playwright.f6.config.ts", ".github/workflows/ci-selfhosted.yml",
    "docs/contracts/product-capability-catalog.v1.json",
    "docs/contracts/product-api.openapi.yaml",
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
    if release in RELEASES:
        return release + "-post-u8.232"
    if release in HISTORICAL_BUILDS:
        return HISTORICAL_BUILDS[release]
    raise ValueError("unregistered release")


def identity(build_id):
    match = re.fullmatch(r"(dsh-0\.1\.[125]rc1)-(u6|u7|post-u8)\.([1-9][0-9]*)", str(build_id))
    if not match:
        raise ValueError("exact registered release and U6/U7/Post-U8 build revision required")
    release = match[1]
    if release == "dsh-0.1.5rc1" and match[2] == "post-u8" and int(match[3]) >= 216:
        dockerfile = f"services/runtime-adapter/Dockerfile.post-u8-{match[3]}-candidate"
    else:
        dockerfile = "services/runtime-adapter/Dockerfile." + match[2] + (
            "-candidate" if release.endswith(("2rc1", "5rc1")) else ""
        )
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
    if build_id in FROZEN_BUILDS:
        path = BUILDS / f"{build_id}.json"
        value = json.loads(path.read_text())
        release, dockerfile = identity(build_id)
        if (digest(path) != FROZEN_BUILDS[build_id]
                or value.get("release_id") != release
                or value.get("dockerfile") != dockerfile
                or value.get("release_descriptor_hash")
                != digest(ROOT / "config/dsh/releases" / f"{release}.json")):
            raise ValueError("frozen build manifest drift")
        return value
    release, _ = identity(build_id)
    if HISTORICAL_BUILDS.get(release) == build_id:
        # Frozen rollback revision: its inputs were recorded against a prior
        # tree and are never re-rendered from current sources. Bind it to the
        # preserved (archived) release descriptor only.
        path = BUILDS / f"{build_id}.json"
        value = json.loads(path.read_text())
        if (value.get("release_id") != release
                or value.get("release_descriptor_hash")
                != digest(ROOT / "config/dsh/releases" / f"{release}.json")):
            raise ValueError("historical build manifest drift")
        return value
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
