#!/usr/bin/env python3
"""Run the captured ACP Adapter with a scoped, scripted F6 provider.

This Engineering-only entrypoint keeps the official ACP Product runner in the
execution path. It changes only the Adapter's test-stack provider destination;
the guarded ACP request and all Product/MCP/Backend/Worker calls remain real.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys


PROJECT = re.compile(r"byq-ci-stack-[A-Za-z0-9][A-Za-z0-9_-]{0,80}\Z")
ACP_FAMILY = "dsh-v0.2.0-rc.2-acp"


def _reject() -> None:
    raise SystemExit("ACP F6 scripted provider rejected its fixture scope")


def _validate_startup_identity(environ: dict[str, str], effective_uid: int,
                              effective_gid: int) -> None:
    """Fail before loading runtime/provider code outside the adapter identity."""
    role = environ.get("BYQ_ACP_ROLE")
    # An unset role is the accepted per-role image path. If role dispatch is
    # present, this fixture may only replace the unified image's adapter role.
    if ((role is not None and role != "adapter")
            or effective_uid != 10002 or effective_gid != 10002):
        _reject()


def main() -> int:
    # Keep this ahead of fixture imports, provider listener creation, and runtime
    # imports. The override must never bypass the adapter's effective identity.
    _validate_startup_identity(os.environ, os.geteuid(), os.getegid())
    project = os.environ.get("COMPOSE_PROJECT_NAME", "")
    if (not PROJECT.fullmatch(project)
            or os.environ.get("BYQ_F6_CI_PROJECT") != project
            or os.environ.get("BYQ_ACP_F6_RELEASE_FIXTURE") != "1"
            or os.environ.get("BYQ_F6_SYNTHETIC_RUNTIME") != "1"
            or os.environ.get("BYQ_F6_EXECUTOR_ENABLED") != "1"
            or os.environ.get("BYQ_DSH_COMPATIBILITY_RELEASE") != ACP_FAMILY
            or os.environ.get("BYQ_DSH_PROVIDER") != "opencode-go-chat"
            or os.environ.get("BYQ_DSH_MODEL") != "deepseek-v4.1-flash"):
        _reject()

    fixture_path = Path("/app/tests/f6_synthetic_runtime.py")
    spec = importlib.util.spec_from_file_location("byq_f6_provider_fixture", fixture_path)
    if spec is None or spec.loader is None:
        _reject()
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    if fixture.validate_environment() != project:
        _reject()

    from app import runtime as runtime_module
    from app.continuation_budget import PRODUCT_TURN_UPSTREAM_BASE_URL
    import uvicorn

    if getattr(runtime_module, "ACP_COMPATIBILITY_FAMILY", None) != ACP_FAMILY:
        _reject()
    allowed_upstreams = {
        str(runtime_module.CONTINUATION_UPSTREAM).rstrip("/"),
        str(PRODUCT_TURN_UPSTREAM_BASE_URL).rstrip("/"),
    }
    diagnostics = fixture._ProviderDiagnostics.create()

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            return

        def do_POST(self) -> None:
            stage = "unknown"
            outcome = "request_rejected"
            response_kind = "none"
            rejection_code = None
            tool_call_count = 0
            try:
                length = int(self.headers.get("content-length", "0"))
                if length <= 0 or length > 2 * 1024 * 1024:
                    raise fixture.F6FixtureRejected("provider_request_size_invalid")
                try:
                    body = json.loads(self.rfile.read(length))
                except (TypeError, ValueError):
                    raise fixture.F6FixtureRejected("provider_request_invalid") from None
                if not isinstance(body, dict):
                    raise fixture.F6FixtureRejected("provider_request_invalid")
                stage, _, _ = fixture._selected_instruction(body.get("messages"))
                action = fixture.next_action(body)
                tool_call_count = 1 if action is not None else 0
                response_kind = "tool_call" if action is not None else "completion"
                response = fixture._sse_completion(body, action)
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("content-length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                outcome = "response_written"
            except fixture.F6FixtureRejected as error:
                rejection_code = fixture._diagnostic_rejection_code(error)
                outcome = ("request_rejected" if rejection_code in {
                    "provider_request_invalid", "provider_request_size_invalid",
                } else "fixture_rejected")
                try:
                    self.send_error(400, "synthetic F6 contract rejected the request")
                except OSError:
                    pass
            except Exception:
                outcome = "handler_error"
                try:
                    self.send_error(400, "synthetic F6 contract rejected the request")
                except OSError:
                    pass
            finally:
                self.server.diagnostics.record_dispatch(  # type: ignore[attr-defined]
                    stage=stage, outcome=outcome, response_kind=response_kind,
                    rejection_code=rejection_code, tool_call_count=tool_call_count,
                )

        def do_GET(self) -> None:
            self.send_error(405, "method not allowed")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    server.diagnostics = diagnostics  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    upstream = f"http://127.0.0.1:{server.server_port}"

    proxy_type = runtime_module.RequestGateProxy
    original_init = proxy_type.__init__

    def init_with_scripted_upstream(self, gate, provider_upstream, *args, **kwargs):
        normalized = str(provider_upstream).rstrip("/")
        if normalized not in allowed_upstreams:
            raise ValueError("ACP F6 fixture provider route is unqualified")
        original_init(self, gate, provider_upstream, *args, **kwargs)
        # Preserve the production request gate, listener, journal, ACP config
        # overlay, and BYQ admission. Only the final test-stack upstream changes.
        self._upstream = upstream
        self._server.upstream = upstream

    proxy_type.__init__ = init_with_scripted_upstream

    try:
        from app import main as runtime_main
        print("ACP F6 scoped scripted provider is ready", flush=True)
        uvicorn.run(runtime_main.app, host="0.0.0.0", port=8400)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        diagnostics.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as error:
        print("ACP F6 scoped entrypoint failed: " + type(error).__name__, file=sys.stderr)
        raise SystemExit(2) from None
