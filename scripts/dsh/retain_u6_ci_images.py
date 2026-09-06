"""Explicit local U6 artifact handoff; normal CI cleanup is unchanged.

Keep only seven already-tested non-secret application images, under new operator
artifact tags and a checksummed archive. This is not a qualification or deployment
receipt. The caller must separately verify the full CI exit and cleanup result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile

try:
    from scripts.dsh import build_revision
except ModuleNotFoundError:
    import build_revision

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ("backend", "gateway", "runtime-adapter", "runtime-candidate", "mcp", "frontend", "feedback-hub-relay")


def stage(scope):
    matched = re.fullmatch(r"local-(u[67])-[a-z0-9-]{3,60}", scope)
    if matched is None:
        raise ValueError("exact local U6/U7 CI scope required")
    return matched[1]


def names(scope):
    lane = stage(scope)
    return {name: {"ci_tag": f"byq-ci-stack-{scope}-{name}:latest",
                   "retained_tag": f"byq-{lane}-artifact-{scope}-{name}:retained"} for name in SERVICES}


def builds():
    result = {}
    for release in sorted(build_revision.RELEASES):
        identity = build_revision.selected_build_id(release)
        build_revision.check(identity)
        result[release] = {"build_id": identity,
            "manifest_hash": build_revision.digest(build_revision.BUILDS / f"{identity}.json")}
    return result


def image_id(tag):
    value = subprocess.check_output(["docker", "image", "inspect", tag, "--format", "{{.Id}}"], text=True).strip()
    if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError("invalid local image identity")
    return value


def archive_hash(path):
    with path.open("rb") as source:
        return "sha256:" + hashlib.file_digest(source, "sha256").hexdigest()


def retain(scope):
    images = names(scope)
    revisions = builds()
    directory = ROOT / ".ci-artifacts" / scope / ("retained-" + stage(scope))
    if directory.exists() or directory.resolve() != directory:
        raise ValueError("artifact output must be a new canonical directory")
    # Resolve every source and reject any existing artifact target before writing.
    for item in images.values():
        item["image_id"] = image_id(item["ci_tag"])
        existing = subprocess.check_output(["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}",
                                           "--filter", f"reference={item['retained_tag']}"], text=True).strip()
        if existing:
            raise ValueError("refusing to overwrite an operator artifact tag")
    directory.mkdir(mode=0o700)
    for item in images.values():
        subprocess.run(["docker", "image", "tag", item["image_id"], item["retained_tag"]], check=True)
        if image_id(item["retained_tag"]) != item["image_id"]:
            raise ValueError("retained image differs from tested artifact")
    archive = directory / "images.tar"
    with archive.open("xb") as output:
        subprocess.run(["docker", "image", "save", *[item["retained_tag"] for item in images.values()]],
                       stdout=output, check=True, timeout=300)
    receipt = {"schema_version": f"dsh-{stage(scope)}-retained-artifacts.v1", "ci_scope": scope,
               "build_revisions": revisions, "images": images,
               "archive": {"name": "images.tar", "bytes": archive.stat().st_size, "sha256": archive_hash(archive)}}
    with (directory / "receipt.json").open("x") as output:
        json.dump(receipt, output, indent=2, sort_keys=True)
        output.write("\n")
    return receipt


def load_receipt(scope):
    expected = names(scope)
    directory = ROOT / ".ci-artifacts" / scope / ("retained-" + stage(scope))
    path, archive = directory / "receipt.json", directory / "images.tar"
    if any(p.is_symlink() or not p.is_file() or p.resolve() != p for p in (path, archive)):
        raise ValueError("missing or non-canonical retained artifact")
    receipt = json.loads(path.read_text())
    if (set(receipt) != {"schema_version", "ci_scope", "build_revisions", "images", "archive"}
            or receipt["schema_version"] != f"dsh-{stage(scope)}-retained-artifacts.v1"
            or receipt["ci_scope"] != scope or receipt["build_revisions"] != builds()
            or set(receipt["images"]) != set(expected)):
        raise ValueError("retained artifact receipt identity mismatch")
    for name, item in receipt["images"].items():
        if (set(item) != {"ci_tag", "retained_tag", "image_id"}
                or any(item[key] != value for key, value in expected[name].items())
                or re.fullmatch(r"sha256:[0-9a-f]{64}", item["image_id"]) is None):
            raise ValueError("retained image reference mismatch")
    if receipt["archive"] != {"name": "images.tar", "bytes": archive.stat().st_size,
                              "sha256": archive_hash(archive)}:
        raise ValueError("retained archive integrity mismatch")
    return receipt


def validate_archive_metadata(archive, receipt):
    expected = {item["retained_tag"]: item["image_id"] for item in receipt["images"].values()}
    with tarfile.open(archive, "r:") as source:
        members = source.getmembers()
        if len({item.name for item in members}) != len(members):
            raise ValueError("duplicate archive entry")
        for item in members:
            allowed_directory = item.isdir() and item.name.rstrip("/") in {"blobs", "blobs/sha256"}
            allowed_file = item.isfile() and (item.name in {"index.json", "manifest.json", "oci-layout"}
                or re.fullmatch(r"blobs/sha256/[a-f0-9]{64}", item.name) is not None)
            if not (allowed_directory or allowed_file):
                raise ValueError("unexpected archive path or link")
        def metadata(name):
            member = source.getmember(name)
            if member.size > 2097152:
                raise ValueError("archive metadata exceeds bound")
            return json.load(source.extractfile(member))
        index, legacy = metadata("index.json"), metadata("manifest.json")
        entries = index.get("manifests", [])
        observed = {}
        for item in entries:
            annotation = item.get("annotations", {})
            name = annotation.get("io.containerd.image.name", "")
            if name in observed or annotation.get("org.opencontainers.image.ref.name") != "retained":
                raise ValueError("unexpected OCI tag")
            observed[name] = item.get("digest")
        if observed != {"docker.io/library/" + tag: digest for tag, digest in expected.items()}:
            raise ValueError("OCI archive identity/tag mismatch")
        tags = [tag for item in legacy for tag in item.get("RepoTags", [])]
        if len(tags) != len(expected) or set(tags) != set(expected):
            raise ValueError("Docker archive tag mismatch")


def restore(scope):
    receipt = load_receipt(scope)
    archive = ROOT / ".ci-artifacts" / scope / ("retained-" + stage(scope)) / "images.tar"
    validate_archive_metadata(archive, receipt)
    missing = False
    for item in receipt["images"].values():
        existing = subprocess.check_output(["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}",
            "--filter", f"reference={item['retained_tag']}"], text=True).strip()
        if existing and image_id(item["retained_tag"]) != item["image_id"]:
            raise ValueError("refusing to overwrite a different retained image")
        missing |= not bool(existing)
    if missing:
        subprocess.run(["docker", "image", "load", "--input", str(archive)], check=True,
                       stdout=subprocess.DEVNULL, timeout=300)
    for item in receipt["images"].values():
        if image_id(item["retained_tag"]) != item["image_id"]:
            raise ValueError("restored image differs from the tested artifact")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--restore", action="store_true", help="restore only a validated exact U6 archive")
    args = parser.parse_args()
    value = restore(args.scope) if args.restore else retain(args.scope)
    print(json.dumps({"stage": "u6-artifacts-restored" if args.restore else "u6-artifacts-retained", "scope": args.scope,
                      "image_count": len(value["images"]), "archive": value["archive"]}))
