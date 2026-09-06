#!/usr/bin/env python3
"""Bounded real-process lifecycle benchmark for one installed DSH release."""

from __future__ import annotations

import json
import os
import statistics
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0, "/app")

from app.runtime import RuntimeAdapter, SessionStatus


CYCLES = 20
SENTINEL_KEY = "u5-benchmark-not-a-secret"


def _rss_snapshot() -> tuple[float, list[dict[str, object]]]:
    uid = os.getuid()
    total_kib = 0
    processes: list[dict[str, object]] = []
    for status_path in Path("/proc").glob("[0-9]*/status"):
        try:
            fields = status_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        owner = next((line for line in fields if line.startswith("Uid:")), "")
        rss = next((line for line in fields if line.startswith("VmRSS:")), "")
        if owner.split()[1:2] == [str(uid)] and len(rss.split()) >= 2:
            rss_kib = int(rss.split()[1])
            total_kib += rss_kib
            name = next((line.split(":", 1)[1].strip() for line in fields if line.startswith("Name:")), "unknown")
            processes.append({"name": name, "rss_mib": round(rss_kib / 1024, 3)})
    processes.sort(key=lambda item: float(item["rss_mib"]), reverse=True)
    return total_kib / 1024, processes


class Provider(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        self.rfile.read(length)
        payloads = [
            {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": None}]},
            {
                "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            },
        ]
        encoded = (
            "".join(f"data: {json.dumps(item, separators=(',', ':'))}\n\n" for item in payloads)
            + "data: [DONE]\n\n"
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *args: object) -> None:
        return


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    os.environ["DEEPSEEK_API_KEY"] = SENTINEL_KEY
    os.environ["DEEPSEEK_BASE_URL"] = f"http://127.0.0.1:{server.server_port}"
    samples: list[float] = []
    cycle_samples: list[dict[str, object]] = []
    sample_lock = threading.Lock()
    cycle_peak = 0.0
    peak_rss, peak_processes = _rss_snapshot()
    stop = threading.Event()

    def sample_rss() -> None:
        nonlocal peak_rss, peak_processes, cycle_peak
        while not stop.wait(0.02):
            with sample_lock:
                current, processes = _rss_snapshot()
                cycle_peak = max(cycle_peak, current)
                if current > peak_rss:
                    peak_rss = current
                    peak_processes = processes

    sampler = threading.Thread(target=sample_rss, daemon=True)
    sampler.start()
    try:
        for cycle in range(CYCLES):
            with sample_lock:
                cycle_peak = 0.0
            started = time.monotonic()
            adapter = RuntimeAdapter()
            session_id = f"u5-bench-{uuid.uuid4().hex}"
            try:
                adapter.create_session(session_id, f"u5-benchmark-{cycle}")
                adapter.submit_prompt(session_id, "reply ok")
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if adapter._get(session_id).status != SessionStatus.RUNNING:
                        break
                    time.sleep(0.01)
                record = adapter._get(session_id)
                if record.status != SessionStatus.IDLE:
                    raise RuntimeError(f"cycle {cycle} ended as {record.status}")
                public = [event for event in record.history if event["kind"] == "agent.output.delta"]
                if "".join(event["payload"]["delta"] for event in public) != "ok":
                    raise RuntimeError(f"cycle {cycle} did not publish the bounded answer")
                adapter.release_session(session_id)
                if adapter._sessions:
                    raise RuntimeError(f"cycle {cycle} retained an Adapter session")
            finally:
                adapter.close()
            samples.append(time.monotonic() - started)
            with sample_lock:
                cycle_samples.append({"cycle": cycle + 1, "seconds": round(samples[-1], 6),
                                      "peak_rss_mib": round(cycle_peak, 3)})
    finally:
        stop.set()
        sampler.join(timeout=1)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
    lingering = [
        thread.name for thread in threading.enumerate()
        if thread.name.startswith(("byq-dsh-session-", "byq-dsh-watchdog-"))
    ]
    if lingering:
        raise RuntimeError(f"owned lifecycle threads remain: {len(lingering)}")
    result = {
        "schema_version": "dsh-runtime-benchmark.v1",
        "release": version("deepseek-harness-sdk"),
        "runtime_bin": version("deepseek-harness-runtime-bin"),
        "cycles": CYCLES,
        "sample_count": len(samples),
        "samples": cycle_samples,
        "median_seconds": round(statistics.median(samples), 6),
        "minimum_seconds": round(min(samples), 6),
        "maximum_seconds": round(max(samples), 6),
        "peak_rss_mib": round(peak_rss, 3),
        "peak_processes": peak_processes,
        "retained_sessions": 0,
        "lingering_threads": 0,
    }
    rendered = json.dumps(result, sort_keys=True)
    if SENTINEL_KEY in rendered:
        raise RuntimeError("benchmark output contains the synthetic credential")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
