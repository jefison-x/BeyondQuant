#!/usr/bin/env python3
"""Run the complete Backend test files concurrently in isolated CI databases."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile


SHARDS = 3


def partition_test_files(tests_dir: Path, count: int = SHARDS) -> list[list[Path]]:
    """Assign every test module exactly once, balancing rough test counts."""
    files = sorted(tests_dir.glob("test_*.py"))
    if count < 1 or len(files) < count or any(not path.is_file() or path.is_symlink() for path in files):
        raise ValueError("Backend test module inventory is unavailable")
    groups: list[list[Path]] = [[] for _ in range(count)]
    weights = [0] * count
    weighted = [(path, sum(line.lstrip().startswith(("def test_", "async def test_"))
                           for line in path.read_text(encoding="utf-8").splitlines()))
                for path in files]
    for path, weight in sorted(weighted, key=lambda item: (-item[1], item[0].name)):
        shard = min(range(count), key=lambda index: (weights[index], index))
        groups[shard].append(path)
        weights[shard] += max(weight, 1)
    if any(not group for group in groups):
        raise ValueError("Backend test inventory is too small for requested shards")
    return groups


def run(*command: str) -> None:
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--network", required=True)
    parser.add_argument("--postgres", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.scope):
        parser.error("invalid CI scope")
    repo = args.repo_root.resolve(strict=True)
    groups = partition_test_files(repo / "services/backend/tests")
    processes: list[subprocess.Popen[bytes]] = []
    names: list[str] = []
    logs: list[object] = []

    def terminate(signum: int, _frame: object) -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for name in names:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)

    try:
        for index in range(SHARDS):
            database = f"byq_domain_test_shard_{index}"
            run("docker", "exec", args.postgres, "psql", "-U", "byq_app", "-d", "postgres",
                "-v", "ON_ERROR_STOP=1", "-c", f"CREATE DATABASE {database} OWNER byq_test")
        for index, files in enumerate(groups):
            name = f"byq-ci-backend-test-{args.scope}-shard-{index}"
            database = f"byq_domain_test_shard_{index}"
            log = tempfile.TemporaryFile()
            logs.append(log)
            command = [
                "docker", "run", "--pull=never", "--rm", "--name", name,
                "--label", f"byq.ci.scope={args.scope}", "--network", args.network,
                "-e", f"BYQ_DATABASE_URL=postgresql+psycopg://byq_test:byq-test-dev@{args.postgres}:5432/{database}",
                "-e", "PYTHONDONTWRITEBYTECODE=1",
                "-w", "/app",
                "-v", f"{repo}/workers:/app/workers:ro",
                "-e", "BYQ_WEB_EVIDENCE_PROVENANCE_POLICY=/app/web-evidence-provenance.json",
                args.image, "python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                *(f"tests/{path.name}" for path in files),
                "--durations=20", "--durations-min=1.0",
            ]
            names.append(name)
            processes.append(subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT))
        statuses = [process.wait() for process in processes]
        for index, (log, status, files) in enumerate(zip(logs, statuses, groups, strict=True)):
            print(f"[backend-shard] index={index} files={len(files)} exit={status}", flush=True)
            log.seek(0)
            sys.stdout.buffer.write(log.read())
            sys.stdout.flush()
        return 0 if all(status == 0 for status in statuses) else 1
    finally:
        for log in logs:
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
