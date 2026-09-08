#!/usr/bin/env python3
"""Derive ADR-0067 profiles without rewriting historical release profiles."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILES = {
    "dsh-0.1.1rc1": (
        "plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml",
        "plugins/dsh-byq/compositions/byq-product-sdk.identity.json",
    ),
    "dsh-0.1.2rc1": (
        "plugins/dsh-byq/profiles/dsh-0.1.2rc1/byq-product.patch.yml",
        "plugins/dsh-byq/profiles/dsh-0.1.2rc1/byq-product.identity.json",
    ),
}


def render(source: str, identity: dict, release: str) -> tuple[str, dict]:
    if release not in PROFILES:
        raise ValueError("unsupported root profile release")
    marker = "X-BYQ-DSH-Run-ID: !!js process.env.BYQ_DSH_RUN_ID"
    lines = source.splitlines()
    matching = [line for line in lines if line.strip() == marker]
    if len(matching) != 1 or "BYQ_ROOT_RUN_ID" in source or "X-BYQ-Root-Run-ID" in source:
        raise ValueError("root profile requires one unmodified generation header")
    source_hash = "sha256:" + hashlib.sha256(source.encode()).hexdigest()
    if release == "dsh-0.1.1rc1":
        # Registry v1 hashes canonical policy metadata plus the YAML body,
        # excluding its three generated comment lines (not raw file bytes).
        metadata = {key: value for key, value in identity.items() if key != "composition_hash"}
        canonical = json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        if len(lines) < 3 or not lines[2].startswith("# composition-hash: "):
            raise ValueError("source registry profile header mismatch")
        body = "\n".join(lines[3:]) + "\n"
        source_hash = "sha256:" + hashlib.sha256(canonical + b"\n" + body.encode()).hexdigest()
    if identity.get("composition_hash") != source_hash:
        raise ValueError("source profile identity mismatch")
    line = matching[0]
    indent = line[:len(line) - len(line.lstrip())]
    result = source.replace(line, line + "\n" + indent + "X-BYQ-Root-Run-ID: !!js process.env.BYQ_ROOT_RUN_ID")
    digest = "sha256:" + hashlib.sha256(result.encode()).hexdigest()
    derived = dict(identity)
    derived.update({
        "composition_hash": digest,
        "process_ownership": "one-per-root-turn",
        "root_identity_contract": "byq-root-process.v1",
        "source_composition_hash": source_hash,
    })
    if "patch_sha256" in derived:
        derived["patch_sha256"] = digest
        derived["patch"] = f"plugins/dsh-byq/profiles/root-scoped/{release}/byq-product.yml"
    return result, derived


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("generate", "check"))
    args = parser.parse_args()
    for release, (profile_path, identity_path) in PROFILES.items():
        profile, identity = render(
            (ROOT / profile_path).read_text(encoding="utf-8"),
            json.loads((ROOT / identity_path).read_text(encoding="utf-8")), release,
        )
        directory = ROOT / "plugins/dsh-byq/profiles/root-scoped" / release
        outputs = {"byq-product.yml": profile,
                   "byq-product.identity.json": json.dumps(identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n"}
        for name, content in outputs.items():
            path = directory / name
            if args.command == "generate":
                directory.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            elif not path.is_file() or path.read_text(encoding="utf-8") != content:
                raise SystemExit(f"root-scoped profile is stale: {release}/{name}")
    print(json.dumps({"status": "ok", "check": args.command == "check"}))


if __name__ == "__main__":
    main()
