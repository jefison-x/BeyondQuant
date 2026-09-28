"""Compose-only Backend gate for the Phase 7 unknown-claim proof.

This launcher wraps the real domain-call operation callback. The real Backend
claim is committed as ``executing`` first; the callback then waits on a private
loopback control endpoint and exits through a generic exception when released.
No business callback runs and no artifact is created.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


if os.environ.get("BYQ_PHASE7_UNKNOWN_CLAIM_BACKEND") != "1":
    raise SystemExit("isolated Phase 7 unknown-claim Backend opt-in required")

sys.path.insert(0, "/app")

from app import main as backend_main  # noqa: E402
import uvicorn  # noqa: E402


_entered = threading.Event()
_release = threading.Event()
_finished = threading.Event()
_original_execute = backend_main.agent_store.execute_domain_call


def _reply(handler: BaseHTTPRequestHandler, status: int, value: dict[str, object]) -> None:
    body = json.dumps(value, separators=(",", ":")).encode()
    handler.send_response(status)
    handler.send_header("content-type", "application/json")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class _PrivateControl(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/_phase7/unknown-claim":
            _reply(self, 404, {"status": "not_found"})
            return
        _reply(self, 200, {"entered": _entered.is_set(),
                           "released": _release.is_set(),
                           "finished": _finished.is_set()})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/_phase7/unknown-claim/release":
            _reply(self, 404, {"status": "not_found"})
            return
        if not _entered.is_set():
            _reply(self, 409, {"status": "callback_not_entered"})
            return
        _release.set()
        _reply(self, 200, {"released": True})


def _controlled_execute(claim: dict[str, object], operation):
    if claim.get("state") != "claimed":
        return _original_execute(claim, operation)

    def _blocked_callback(_connection):
        _entered.set()
        print(json.dumps({"phase7_unknown_claim_backend": "CALLBACK_ENTERED"}), flush=True)
        if not _release.wait(timeout=1800):
            raise RuntimeError("Phase 7 unknown-claim fixture control timed out")
        print(json.dumps({"phase7_unknown_claim_backend": "CALLBACK_RELEASED"}), flush=True)
        raise RuntimeError("Phase 7 unknown-claim fixture released after unknown outcome")

    try:
        return _original_execute(claim, _blocked_callback)
    finally:
        _finished.set()


backend_main.agent_store.execute_domain_call = _controlled_execute

_control = ThreadingHTTPServer(("127.0.0.1", 8351), _PrivateControl)
_control.daemon_threads = True
threading.Thread(target=_control.serve_forever, name="phase7-private-control", daemon=True).start()

uvicorn.run(backend_main.app, host="0.0.0.0", port=8000)
