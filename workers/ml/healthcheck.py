"""Lightweight ML worker health check without loading training libraries."""

from __future__ import annotations

from pathlib import Path

from app.ml_capabilities import LIGHTGBM_RUNTIME_IDENTITY


READY_PATH = Path("/tmp/byq-ml-worker-ready")


def healthcheck(ready_path: Path = READY_PATH) -> int:
    if (
        not ready_path.is_file()
        or ready_path.read_text(encoding="utf-8") != LIGHTGBM_RUNTIME_IDENTITY
    ):
        raise RuntimeError("ML worker initialization is incomplete")
    return 0


if __name__ == "__main__":
    healthcheck()
