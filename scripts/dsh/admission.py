#!/usr/bin/env python3
"""Trusted operator-only gate writer, never installed in Product images.

Bind-mount its directory read-only into all serving Gateway/Adapter replicas.
Do not replace/unlink admission.state while services are running. Only a single
host with local shared file locking is supported. Closing waits for admission,
not model completion: separately verify Runtime drain before switching.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import stat
import time


def _target(path: Path) -> Path:
    if (not path.is_absolute() or path.name != "admission.state"
            or path.resolve() != path or not path.parent.is_dir()):
        raise ValueError("a dedicated absolute regular admission.state path is required")
    return path


def initialize(path: Path):
    descriptor = os.open(_target(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        os.write(descriptor, b"closed\n")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def set_state(path: Path, state: str, *, timeout: float = 30):
    target = _target(path)
    if state not in {"open", "closed"} or not 0 < timeout <= 120:
        raise ValueError("invalid state or bounded lock timeout")
    descriptor = os.open(target, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("gate is not a regular file")
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("in-flight admission has not finished; gate unchanged")
                time.sleep(0.01)
        if os.read(descriptor, 16) not in {b"open\n", b"closed\n"}:
            raise ValueError("invalid existing gate contents")
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.write(descriptor, (state + "\n").encode())
        os.ftruncate(descriptor, len(state) + 1)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "open", "close"))
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    if args.action == "init":
        initialize(args.file)
    else:
        set_state(args.file, "open" if args.action == "open" else "closed", timeout=args.timeout)
    print(json.dumps({"schema_version": "byq-chat-admission.v1", "state": "open" if args.action == "open" else "closed"}))


if __name__ == "__main__":
    main()
