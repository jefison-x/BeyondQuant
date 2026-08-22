"""Credential-free supervisor for one fresh signal child per invocation."""

from __future__ import annotations

import json
import math
import os
import resource
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI


app = FastAPI(title="BYQ Signal Sandbox", version="0.1.0")
RUNNER = Path(__file__).with_name("runner.py")
MAX_REQUEST_BYTES = 32 * 1024 * 1024


def _limits(timeout: float) -> None:
    cpu = max(1, math.ceil(timeout))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"service": "byq-signal-sandbox", "status": "ok"}


@app.post("/v1/execute")
def execute(payload: dict[str, Any]) -> dict[str, object]:
    encoded = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > MAX_REQUEST_BYTES:
        return {"ok": False, "error_code": "input_too_large", "error_detail": "sandbox input exceeds 32 MiB"}
    execution_timeout = payload.get("timeout_seconds", 10.0)
    try:
        timeout = float(execution_timeout)
    except (TypeError, ValueError):
        timeout = 10.0
    timeout = min(max(timeout, 0.1), 30.0)
    request = dict(payload)
    request.pop("timeout_seconds", None)
    environment = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONHASHSEED": "0",
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }
    try:
        completed = subprocess.run(
            [sys.executable, "-I", str(RUNNER)],
            input=json.dumps(request, ensure_ascii=False, allow_nan=False),
            text=True,
            capture_output=True,
            cwd="/tmp",
            env=environment,
            timeout=timeout + 1.0,
            check=False,
            preexec_fn=lambda: _limits(timeout),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error_code": "execution_timeout", "error_detail": "strategy exceeded wall-time limit"}
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1:] or ["strategy child failed"]
        return {"ok": False, "error_code": "execution_failed", "error_detail": detail[0][:300]}
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error_code": "invalid_output", "error_detail": "strategy child returned invalid JSON"}
    if not isinstance(response, dict):
        return {"ok": False, "error_code": "invalid_output", "error_detail": "strategy child returned invalid output"}
    return response
