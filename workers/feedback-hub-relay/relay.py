"""Durable local Product Feedback relay to the official central Hub (ADR-0052)."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


WORKER_VERSION = "feedback-hub-relay.v1"


class RelayError(RuntimeError):
    def __init__(self, category: str, retry_after: int = 30) -> None:
        super().__init__(category)
        self.category = category
        self.retry_after = retry_after


@dataclass(frozen=True)
class Config:
    backend_url: str
    service_token: str
    hub_url: str | None
    worker_id: str
    poll_seconds: int

    @classmethod
    def from_env(cls) -> "Config":
        hub_url = os.getenv("BYQ_FEEDBACK_HUB_URL", "").strip().rstrip("/") or None
        allow_http = os.getenv("BYQ_FEEDBACK_HUB_ALLOW_HTTP") == "1"
        if hub_url and not hub_url.startswith("https://") and not (allow_http and hub_url.startswith("http://")):
            raise ValueError("BYQ_FEEDBACK_HUB_URL must use HTTPS")
        return cls(
            backend_url=os.getenv("BYQ_FEEDBACK_BACKEND_URL", "http://backend:8000").rstrip("/"),
            service_token=os.getenv("BYQ_FEEDBACK_HUB_RELAY_TOKEN", ""),
            hub_url=hub_url,
            worker_id=os.getenv("BYQ_FEEDBACK_HUB_RELAY_WORKER_ID", f"feedback-hub-relay-{socket.gethostname()[:24]}"),
            poll_seconds=max(5, min(int(os.getenv("BYQ_FEEDBACK_HUB_POLL_SECONDS", "15")), 300)),
        )


def _json_request(url: str, *, method: str = "GET", payload: object | None = None,
                  headers: dict[str, str] | None = None, expected: int = 200) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    outgoing = {"accept": "application/json", "user-agent": "BeyondQuant-Feedback-Hub-Relay/1", **(headers or {})}
    if body is not None:
        outgoing["content-type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=outgoing, method=method)
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            if response.status != expected:
                raise RelayError("hub_unavailable")
            raw = response.read(64 * 1024)
            result = json.loads(raw) if raw else {}
            if not isinstance(result, dict):
                raise RelayError("validation_rejected")
            return result
    except urllib.error.HTTPError as exc:
        category = "rate_limited" if exc.code == 429 else "validation_rejected" if exc.code in {400, 409, 413, 422} else "hub_unavailable"
        raise RelayError(category, 60 if exc.code == 429 else 30) from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise RelayError("hub_unavailable") from exc


def _backend(config: Config, path: str, *, method: str = "POST", payload: object | None = None) -> dict[str, Any]:
    return _json_request(
        f"{config.backend_url}{path}", method=method, payload=payload,
        headers={"x-byq-feedback-hub-relay-token": config.service_token},
    )


def _deliver(config: Config, event: dict[str, Any]) -> None:
    assert config.hub_url
    try:
        receipt = _json_request(f"{config.hub_url}/v1/intake", method="POST", expected=202, payload={
            "schema_version": "central-feedback-intake.v1",
            "installation_id": event["installation_id"], "event_id": event["event_id"],
            "snapshot_hash": event["snapshot_hash"], "snapshot": event["snapshot"],
        })
        _backend(config, f"/internal/feedback-hub/{event['event_id']}/complete", payload={
            "worker_id": config.worker_id, "lease_fence": event["lease_fence"],
            "receipt_id": receipt["receipt_id"], "status_token": receipt["status_token"],
        })
    except (RelayError, KeyError) as caught:
        exc = caught if isinstance(caught, RelayError) else RelayError("validation_rejected")
        _backend(config, f"/internal/feedback-hub/{event['event_id']}/retry", payload={
            "worker_id": config.worker_id, "lease_fence": event["lease_fence"],
            "error_category": exc.category, "retry_after_seconds": exc.retry_after,
        })


def _refresh_statuses(config: Config) -> None:
    assert config.hub_url
    candidates = _backend(config, "/internal/feedback-hub/status-candidates?limit=10", method="GET")
    for item in candidates.get("items", []):
        try:
            status = _json_request(
                f"{config.hub_url}/v1/status/{item['receipt_id']}",
                headers={"authorization": f"Bearer {item['status_token']}"},
            )
            _backend(config, f"/internal/feedback-hub/{item['event_id']}/status", payload=status)
        except (RelayError, KeyError):
            continue


class _Health(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        status = 200 if self.path == "/healthz" else 404
        body = b'{"service":"feedback-hub-relay","status":"ok"}' if status == 200 else b"{}"
        self.send_response(status); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def run(config: Config) -> None:
    if not config.service_token:
        raise ValueError("feedback hub relay service token is required")
    health = ThreadingHTTPServer(("127.0.0.1", 8750), _Health)
    threading.Thread(target=health.serve_forever, daemon=True).start()
    while True:
        try:
            _backend(config, "/internal/feedback-hub/heartbeat", payload={
                "configured": bool(config.hub_url), "hub_origin": config.hub_url,
                "worker_version": WORKER_VERSION,
            })
            if config.hub_url:
                claimed = _backend(config, "/internal/feedback-hub/claim", payload={
                    "worker_id": config.worker_id, "limit": 5, "lease_seconds": 60,
                })
                for event in claimed.get("events", []):
                    _deliver(config, event)
                _refresh_statuses(config)
        except Exception:
            pass
        time.sleep(config.poll_seconds)


if __name__ == "__main__":
    run(Config.from_env())
