"""Private one-attempt HTTPS worker for the unwired ADR-0097 provider gate.

The parent sends credentials and request bytes through stdin, never argv. A
blocked resolver, TLS handshake or read is terminated with this whole process.
"""

from __future__ import annotations

import base64
import json
import sys

from .research_judgment_acp_provider_proxy import _send_https
from .research_judgment_acp_provider_usage import MAX_SSE_BYTES
from .process_secrecy import require_private_process

PRIVATE_READY = b"BYQ_ACP_WORKER_PRIVATE_V1\n"


def main() -> int:
    try:
        require_private_process()
        # Parent must observe this only after /proc access is closed, before
        # sending the provider credential and request body through stdin.
        sys.stdout.buffer.write(PRIVATE_READY)
        sys.stdout.buffer.flush()
        raw = sys.stdin.buffer.read(12 * 1024 * 1024 + 1)
        if len(raw) > 12 * 1024 * 1024:
            return 1
        payload = json.loads(raw)
        if (not isinstance(payload, dict)
                or set(payload) != {"url", "headers", "body_b64", "deadline_monotonic"}
                or not isinstance(payload["url"], str)
                or not isinstance(payload["headers"], dict)
                or any(not isinstance(k, str) or not isinstance(v, str)
                       for k, v in payload["headers"].items())
                or not isinstance(payload["body_b64"], str)
                or type(payload["deadline_monotonic"]) not in (int, float)):
            return 1
        body = base64.b64decode(payload["body_b64"], validate=True)
        if len(body) > 8 * 1024 * 1024:
            return 1
        response = _send_https(payload["url"], payload["headers"], body,
                               payload["deadline_monotonic"])
        if len(response.body) > MAX_SSE_BYTES:
            return 1
        sys.stdout.buffer.write(json.dumps({
            "status": response.status, "content_type": response.content_type,
            "body_b64": base64.b64encode(response.body).decode("ascii"),
        }, separators=(",", ":")).encode())
        sys.stdout.buffer.flush()
        return 0
    except Exception:  # noqa: BLE001
        # The parent already durably marked the attempt may-have-dispatched.
        # No credential, prompt, provider body or exception is logged here.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
