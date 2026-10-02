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
    "dsh-0.1.5rc1-post-u8.232": "sha256:88433eed89a7cbf623d1561e0a9cc8c44753fb138eecd3bee4aecc48ed595b45",
    "dsh-0.1.5rc1-post-u8.233": "sha256:f2f05cf8bb337d43451071b30953efdd0cba61502eecab2d61a20c9f5f8de690",
    "dsh-0.1.5rc1-post-u8.234": "sha256:e02484721ca6c36b7be0caa1393e4b040db4c807b0a670e370ea4d65b77e75ae",
    "dsh-0.1.5rc1-post-u8.235": "sha256:f9c49474ffae4e2155ced40ed46db7c4135e728881e0222717e46504177f7735",
    "dsh-0.1.5rc1-post-u8.236": "sha256:b52f0e2631f62e81c5e2843073fc6b09a8f7e7ebaef3710c9c7fc22e909c4221",
    "dsh-0.1.5rc1-post-u8.237": "sha256:f8384b44707bb186b4329468dd1477c970ed47e4369dae024971e3caf600d3a0",
    "dsh-0.1.5rc1-post-u8.238": "sha256:b34652145492d741860def91bfc035b6f20bc5c5ebc18793e0c00fd6c1889a01",
    "dsh-0.1.5rc1-post-u8.239": "sha256:65a3eae15457923640c76a22cd04d44ff6a31b9336d79d23d02d0f5df71cc13b",
    "dsh-0.1.5rc1-post-u8.240": "sha256:954d8c0ebc263f9cd9ec0edf754c54d153e304c9e3ba4beeaeafb6f5c9d98e9d",
    "dsh-0.1.5rc1-post-u8.241": "sha256:56dba24b58d4f142668157d23aa4283ccbd60b7e62102a258f80d36d2dc810e7",
    "dsh-0.1.5rc1-post-u8.242": "sha256:741b98607250a12821bf758b8c77629f5f057c0b676ba93e9e3ce0e6e4704a4f",
    "dsh-0.1.5rc1-post-u8.243": "sha256:f24812519793326f0c0f5185247c417a4a393a7db7f08acf67e88342f29cd32a",
    "dsh-0.1.5rc1-post-u8.244": "sha256:ed48c935e48b977138b33cd4ca32c71331b65934bad85cb62f27caa231214de0",
    "dsh-0.1.5rc1-post-u8.245": "sha256:c4623f05c218385c50fde8ba671d789cbbcc8fe39aeec7bb11e4504edbbed5eb",
    "dsh-0.1.5rc1-post-u8.246": "sha256:70b38259243693f7e8000b17a79c6316b124d6bc2870b9f03565e2f3a9b88dfd",
    "dsh-0.1.5rc1-post-u8.247": "sha256:417ab771429cb55e1d2ccfdaa2ea0e6113ff5703b7b8a638ae129121ca995b5a",
    "dsh-0.1.5rc1-post-u8.248": "sha256:fe00ced20f7ad64799747726b32ec4517bf4065c7173f12aa9ca1c218f9db953",
    "dsh-0.1.5rc1-post-u8.249": "sha256:e47102fab8dbe2a265da2ab32e30a0325c8b56c8d229cd61fec00e40f0262bf7",
    "dsh-0.1.5rc1-post-u8.250": "sha256:a3a194786f7141fe69579b7d4a5cfbc794946a22922b3dc1d19453950290586d",
    "dsh-0.1.5rc1-post-u8.251": "sha256:0a4d6bf8024322ff22697faaa412cce75e77cbdd636c04cd1585f963c13ef432",
    "dsh-0.1.5rc1-post-u8.252": "sha256:75d9ed7d73410d1d5c47c331fbc75f1f4149ec91ce4859e21f9e7d5e38791588",
    "dsh-0.1.5rc1-post-u8.253": "sha256:b15c33a83be96ce8128ff70cd6a9ae28c7945108dfd806eec104da68044f9be9",
    "dsh-0.1.5rc1-post-u8.254": "sha256:981dca9a3d0e5827140b6f153a2984f3dc6be9d53a727a3bab54c1cb36baf766",
    "dsh-0.1.5rc1-post-u8.255": "sha256:bc7122df90ee1a16b91260345f1d5c25071e614e037a0e3fb27079b587d2e69f",
    "dsh-0.1.5rc1-post-u8.256": "sha256:504ea47acf0b0cedb928128ab6eeb64ac14d6305ada844ce24e1d53f91ef0ba2",
    "dsh-0.1.5rc1-post-u8.257": "sha256:2a2918f0df16dba85ce51d2595cfe2f436b58c70348afcbed1d9b7a9deb3a1e3",
    "dsh-0.1.5rc1-post-u8.258": "sha256:32b26b9aa1aff0476e9f09c2dbed6c0023b87d053c6caa109aba1d41a9be3527",
    "dsh-0.1.5rc1-post-u8.259": "sha256:88b011a3e86a9cbf1a94aefbbb0a19a53a5483029bdf452814df46f1cfbdc6de",
    "dsh-0.1.5rc1-post-u8.260": "sha256:71ff013f4407f9a96ff3fdba12a06f4f6e96bc664d22b172243f9cc1e67ad029",
    "dsh-0.1.5rc1-post-u8.261": "sha256:39b5c2cf3f0281e7ffc3f234d750ab150e5fa4c0574ed21efef03133a622f51e",
    "dsh-0.1.5rc1-post-u8.262": "sha256:7cb250b0481918c64b41d15c99a1cb16fd91d8623d254db809f367a3377b446d",
    "dsh-0.1.5rc1-post-u8.263": "sha256:6ae8b7fff4dcc8aaa60e90092771d99a3b2d383da24e440d046b53b101004903",
    "dsh-0.1.5rc1-post-u8.264": "sha256:c7b234b9e03f11cb7d09e3105a5a515eaef793289c75cf942f415eb6280d3f85",
    "dsh-0.1.5rc1-post-u8.265": "sha256:c5c6904d91c25c6765366182a21c15c836ef1210b525727d4e8c6f4b4f0e793f",
    "dsh-0.1.5rc1-post-u8.266": "sha256:34ee3d86b68cfbd9497f30e01eae0b1693d62e82d4c5ab2dd103c9b70f88a05f",
    "dsh-0.1.5rc1-post-u8.267": "sha256:e1b3a5626de1bf10130c047ac32c63580a7e7424b9f33e888d1b239ed096ec22",
    "dsh-0.1.5rc1-post-u8.268": "sha256:66cefc8b881f576e425904fcb2255d2bf0c6a9a15d7cc9c1da0fc534545b8cc0",
    "dsh-0.1.5rc1-post-u8.269": "sha256:56cc131e66c800798dce1d72bb895ffe9f378cce4e854376da0c567037810a08",
    "dsh-0.1.5rc1-post-u8.270": "sha256:1b65d0ffd84988e2675936d51957ec8c36d903a0cd71c5fce8245276391ec593",
    "dsh-0.1.5rc1-post-u8.271": "sha256:b16e18882b74431b25720b028a135ae1dd924382f8526cd2f87fa772c9dfecae",
    "dsh-0.1.5rc1-post-u8.272": "sha256:a4ea957ef6123d1b8c80882172c89b5b0857bdb4ab163028382d89b7291e3414",
    "dsh-0.1.5rc1-post-u8.273": "sha256:029eadcb55f4ed5a784d7eb3d5c87150d85e43e5abfd17240606db15ff2fe9a9",
    "dsh-0.1.5rc1-post-u8.274": "sha256:cf7f85fbf62219c58df2c9903164699891ec737f4b0c137d773c7adf26715b7b",
    "dsh-0.1.5rc1-post-u8.275": "sha256:c1ce46ac6ce876a0b2f4aeb1988d6381c8ab09bbf63b0458299eb847f4f5ff28",
    "dsh-0.1.5rc1-post-u8.276": "sha256:e4f6a417095baca1eea5b3291329004d63c6a1639fef973fa2d9f3b4bb388400",
    "dsh-0.1.5rc1-post-u8.277": "sha256:36d14cca3d16f0eed89060630e84177fa8d9193bda3132cf66aa66320d2dfbd5",
    "dsh-0.1.5rc1-post-u8.278": "sha256:8c9eeb1569643054a67e71e31ecab10d843035050de944b638b1485cd83afe3e",
    "dsh-0.1.5rc1-post-u8.279": "sha256:c6e65dd149ed9f195dc3909613d9b4d2a1045d915060fe2d5c23159b68b96f59",
    "dsh-0.1.5rc1-post-u8.280": "sha256:828b58684ae05f50f5e74995352ef30bc16295ce0740c44020426ca2f1c0d947",
    "dsh-0.1.5rc1-post-u8.281": "sha256:e78c5cab7d5e3f36bb8c2a7ac86ca490eae6826439dd63762bcb3caa1882dfcb",
    "dsh-0.1.5rc1-post-u8.282": "sha256:bba668a85ee068f3d0406c979230574e77b985de1d2f904604fdff7eaa59a12d",
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
    "scripts/ci/local-ci.sh", "compose.yml", "compose.override.yml", "compose.dev.yml",
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
        return release + "-post-u8.283"
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
