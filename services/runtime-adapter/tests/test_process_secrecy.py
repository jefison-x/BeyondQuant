"""ACP service credentials must not be readable through same-UID /proc."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "linux" or not os.path.isdir("/proc"),
                    reason="Linux procfs is required")
def test_default_acp_startup_guard_blocks_same_uid_environment_inspection():
    env = {**os.environ, "BYQ_SYNTHETIC_SECRET_PROBE": "only-a-local-test"}
    env.pop("BYQ_DSH_COMPATIBILITY_RELEASE", None)
    sentinel = b"BYQ_SYNTHETIC_SECRET_PROBE=only-a-local-test"

    def start(guard: bool) -> subprocess.Popen[str]:
        command = (
            "from app.process_secrecy import guard_candidate_adapter_process; "
            + ("guard_candidate_adapter_process(); " if guard else "")
            + "print('ready', flush=True); import time; time.sleep(5)"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", command], env=env, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True,
        )
        assert child.stdout is not None and child.stdout.readline().strip() == "ready"
        return child

    baseline = start(False)
    try:
        try:
            ordinary = open(f"/proc/{baseline.pid}/environ", "rb").read()
        except PermissionError:
            pytest.skip("procfs already hides same-UID environments")
        assert sentinel in ordinary, "the synthetic baseline must prove the test can observe /proc"
    finally:
        baseline.terminate()
        baseline.wait(timeout=3)

    guarded = start(True)
    try:
        with pytest.raises(PermissionError):
            open(f"/proc/{guarded.pid}/environ", "rb").read()
    finally:
        guarded.terminate()
        guarded.wait(timeout=3)
