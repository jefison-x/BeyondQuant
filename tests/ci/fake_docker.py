#!/usr/bin/env python3
"""Strict fake `docker` used by the cleanup image-id behavior tests.

It models only the subcommands `scripts/ci/cleanup-resources.sh` uses and keeps a
tiny content-addressed image store so the tests can assert exactly which image
tags/ids were removed. State lives in ``$FAKE_DOCKER_STATE`` as ``id<TAB>tag,tag``
lines (empty tag list = dangling image); every invocation is appended to
``$FAKE_DOCKER_LOG``. Containers, volumes and networks are always absent.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _state_path() -> Path:
    return Path(os.environ["FAKE_DOCKER_STATE"])


def _log(args: list[str]) -> None:
    log = Path(os.environ["FAKE_DOCKER_LOG"])
    with log.open("a", encoding="utf-8") as stream:
        stream.write(" ".join(args) + "\n")


def _load() -> dict[str, list[str]]:
    images: dict[str, list[str]] = {}
    path = _state_path()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            image_id, _, tags = line.partition("\t")
            images[image_id] = [tag for tag in tags.split(",") if tag]
    return images


def _save(images: dict[str, list[str]]) -> None:
    _state_path().write_text(
        "".join(f"{image_id}\t{','.join(tags)}\n" for image_id, tags in images.items()),
        encoding="utf-8")


def _resolve(images: dict[str, list[str]], ref: str) -> str | None:
    if ref.startswith("sha256:"):
        return ref if ref in images else None
    for image_id, tags in images.items():
        if ref in tags:
            return image_id
    return None


def _format_arg(rest: list[str]) -> tuple[str | None, str | None]:
    fmt: str | None = None
    ref: str | None = None
    index = 0
    while index < len(rest):
        if rest[index] == "--format":
            fmt = rest[index + 1] if index + 1 < len(rest) else ""
            index += 2
        else:
            ref = rest[index]
            index += 1
    return fmt, ref


def _image(rest: list[str]) -> int:
    sub = rest[0] if rest else ""
    args = rest[1:]
    images = _load()
    if sub == "inspect":
        fmt, ref = _format_arg(args)
        image_id = _resolve(images, ref or "")
        if image_id is None:
            return 1
        if fmt and "json .RepoTags" in fmt:
            print(json.dumps(images[image_id]))
        elif fmt and "RepoTags" in fmt:
            for tag in images[image_id]:
                print(tag)
        elif fmt and ".Id" in fmt:
            print(image_id)
        return 0
    if sub == "rm":
        changed = False
        for ref in args:
            image_id = _resolve(images, ref)
            if image_id is None:
                continue
            if ref.startswith("sha256:"):
                del images[image_id]
            else:
                images[image_id] = [tag for tag in images[image_id] if tag != ref]
            changed = True
        if not changed:
            return 1
        _save(images)
        return 0
    return 0


def main(argv: list[str]) -> int:
    _log(argv)
    if not argv:
        return 0
    command, rest = argv[0], argv[1:]
    if command in {"info", "ps", "rm", "compose", "logs"}:
        return 0
    if command == "volume":
        return 1 if rest and rest[0] == "inspect" else 0
    if command == "network":
        return 1 if rest and rest[0] == "inspect" else 0
    if command == "image":
        return _image(rest)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
