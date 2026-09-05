#!/usr/bin/env python3
"""Deterministic declaration inventory, not a binary-distribution legal attestation."""
import argparse
import json
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[2]
LOCKS = ("apps/frontend/package-lock.json", "services/mcp/package-lock.json",
         "services/runtime-adapter/runtime/package-lock.json", "deploy/feedback-hub-cloudflare/package-lock.json")
REVIEWED = {"MIT", "MIT-0", "ISC", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "PSF-2.0",
            "Python-2.0", "0BSD", "BlueOak-1.0.0", "CC0-1.0", "MPL-2.0", "(MPL-2.0 OR Apache-2.0)",
            "MIT OR Apache-2.0", "LGPL-3.0-or-later", "Apache-2.0 AND LGPL-3.0-or-later",
            "Apache-2.0 AND LGPL-3.0-or-later AND MIT"}


def inventories(root=ROOT):
    npm = []
    for filename in LOCKS:
        lock = json.loads((root / filename).read_text())
        for path, package in sorted(lock["packages"].items()):
            if not path:
                continue
            license_id = package.get("license")
            if license_id not in REVIEWED:
                raise ValueError(f"Unreviewed/missing license: {filename}: {path}")
            npm.append({"lock": filename, "path": path, "version": package["version"],
                        "license": license_id, "dev": bool(package.get("dev")), "optional": bool(package.get("optional"))})
    python = []
    sources = sorted(root.glob("services/*/pyproject.toml"))
    for path in sources:
        project = tomllib.loads(path.read_text())["project"]
        groups = {"runtime": project.get("dependencies", []), **project.get("optional-dependencies", {})}
        for group, requirements in groups.items():
            for requirement in sorted(requirements):
                python.append({"source": path.relative_to(root).as_posix(), "group": group, "requirement": requirement})
    for path in sorted([*root.glob("workers/*/Dockerfile"), *root.glob("services/*/Dockerfile")]):
        for requirement in sorted(set(re.findall(r"[A-Za-z0-9_.-]+(?:\[[\w,.-]+\])?==[A-Za-z0-9_.+-]+", path.read_text()))):
            python.append({"source": path.relative_to(root).as_posix(), "group": "build-declaration", "requirement": requirement})
    return {
        "npm-license-inventory.json": {"schema_version": "byq-npm-license-inventory.v1", "packages": npm},
        "python-dependency-inventory.json": {"schema_version": "byq-python-declaration-inventory.v1",
             "scope": "Direct declarations only; installed transitives and binary notices require release SBOM review.", "dependencies": python},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    failed = False
    for name, value in inventories().items():
        expected = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        path = ROOT / "docs/legal" / name
        if args.check:
            if not path.exists() or path.read_text() != expected:
                print(f"STALE: {path.relative_to(ROOT)}")
                failed = True
        else:
            path.write_text(expected)
    if not failed:
        print("License declaration inventory PASS (not a complete distribution attestation)")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
