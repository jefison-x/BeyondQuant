#!/usr/bin/env python3
"""0.9 step-5 B3 `terminal-adapter-restart` provenance builder.

Hashes the committed probe/observer/contract/scope artifacts and records the
isolation facts so the evidence can be independently checked. It performs no
network, Docker, model or production action.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TERMINAL = ROOT / "scripts/d15/terminal"


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    artifacts = {
        "harness": TERMINAL / "adapter_restart_harness.mjs",
        "observer": TERMINAL / "adapter_restart_observer.py",
        "contract": TERMINAL / "adapter_restart_contract.v1.json",
        "scope_probe": TERMINAL / "adapter_restart_scope_probe.py",
        "runner": TERMINAL / "run_adapter_restart_probe.sh",
        "package_lock": TERMINAL / "package-lock.json",
        "package": TERMINAL / "package.json",
    }
    missing = [name for name, path in artifacts.items() if not path.is_file()]
    node = "unavailable"
    try:
        node = subprocess.check_output(["node", "--version"], text=True).strip()
    except Exception:  # noqa: BLE001
        pass
    return {
        "schema_version": "byq-v090-step5-b3-provenance.v1",
        "slice": "terminal-adapter-restart",
        "owner_node": "d15-5-candidate-attachment-layer",
        "candidate": {"release": "dsh-0.1.5rc1", "npm": "0.1.5-rc.1", "python_sdk": "0.1.5rc1"},
        "artifacts": {name: {"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)}
                      for name, path in artifacts.items() if path.is_file()},
        "missing_artifacts": missing,
        "isolation": {
            "evidence_class": "native-runtime-isolated-b3",
            "runtime": "real native @deepseek-ai/dsh-terminal + @deepseek-ai/dsh-terminal-bash closure via npm",
            "processes": "separate OS processes per native runtime generation, per BYQ adapter generation and per client action",
            "network": "none required at run time (npm install only)",
            "production_selector": "dsh-0.1.2rc1",
            "production_selector_changed": False,
            "fork_or_patch_of_dsh": False,
            "docker_image_used": False,
            "database_changes": "none",
            "release_or_tag_created": False,
            "deployment": "none",
            "r3_resume": "NO",
        },
        "environment": {
            "node": node,
            "python": platform.python_version(),
            "os": os.uname().sysname if hasattr(os, "uname") else platform.system(),
        },
        "constraints": {
            "byq_builds_pty_runtime": False,
            "byq_copies_dsh_terminal": False,
            "second_generic_harness": False,
            "second_session_store": False,
            "r4_productization": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    provenance = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "missing_artifacts": provenance["missing_artifacts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
