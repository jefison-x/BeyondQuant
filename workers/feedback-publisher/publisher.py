"""Minimal fixed-destination Product Feedback publisher (ADR-0049)."""

from __future__ import annotations

import base64
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


WORKER_VERSION = "feedback-publisher.v1"
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
SAFE_ORIGIN = "https://api.github.com"


class PublisherError(RuntimeError):
    def __init__(self, category: str, *, retry_after: int = 30) -> None:
        super().__init__(category)
        self.category = category
        self.retry_after = retry_after


@dataclass(frozen=True)
class Config:
    backend_url: str
    service_token: str
    repository: str | None
    github_origin: str
    github_token: str | None
    app_id: str | None
    installation_id: str | None
    private_key_file: str | None
    worker_id: str
    poll_seconds: int
    allow_test_origin: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        repository = os.getenv("BYQ_FEEDBACK_GITHUB_REPOSITORY", "").strip() or None
        origin = os.getenv("BYQ_FEEDBACK_GITHUB_API_ORIGIN", SAFE_ORIGIN).rstrip("/")
        allow_test = os.getenv("BYQ_FEEDBACK_ALLOW_TEST_ORIGIN") == "1"
        if origin != SAFE_ORIGIN and not allow_test:
            raise ValueError("non-default GitHub origin is test-only")
        if repository and REPOSITORY.fullmatch(repository) is None:
            raise ValueError("GitHub repository must be fixed owner/repo")
        return cls(
            backend_url=os.getenv("BYQ_FEEDBACK_BACKEND_URL", "http://backend:8000").rstrip("/"),
            service_token=os.getenv("BYQ_FEEDBACK_PUBLISHER_TOKEN", ""), repository=repository,
            github_origin=origin, github_token=os.getenv("BYQ_FEEDBACK_GITHUB_TOKEN", "").strip() or None,
            app_id=os.getenv("BYQ_FEEDBACK_GITHUB_APP_ID", "").strip() or None,
            installation_id=os.getenv("BYQ_FEEDBACK_GITHUB_INSTALLATION_ID", "").strip() or None,
            private_key_file=os.getenv("BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY_FILE", "").strip() or None,
            worker_id=os.getenv("BYQ_FEEDBACK_WORKER_ID", f"feedback-publisher-{socket.gethostname()[:32]}"),
            poll_seconds=max(2, min(int(os.getenv("BYQ_FEEDBACK_POLL_SECONDS", "10")), 60)),
            allow_test_origin=allow_test,
        )

    @property
    def credential_kind(self) -> str | None:
        if self.app_id and self.installation_id and self.private_key_file:
            return "github_app"
        if self.github_token:
            return "fine_grained_token"
        return None

    @property
    def configured(self) -> bool:
        return bool(self.service_token and self.repository and self.credential_kind)


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


class GitHubCredential:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._token: str | None = None
        self._expires_at = datetime.min.replace(tzinfo=timezone.utc)

    def token(self) -> str:
        app_configured = bool(self.config.app_id and self.config.installation_id and self.config.private_key_file)
        if not app_configured:
            if self.config.github_token:
                return self.config.github_token
            raise PublisherError("authentication_failed")
        now = datetime.now(timezone.utc)
        if self._token and now + timedelta(minutes=2) < self._expires_at:
            return self._token
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding

            key = serialization.load_pem_private_key(Path(self.config.private_key_file).read_bytes(), password=None)
            issued = int(now.timestamp()) - 30
            header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
            payload = _b64url(json.dumps({"iat": issued, "exp": issued + 540, "iss": self.config.app_id},
                                         separators=(",", ":")).encode())
            unsigned = f"{header}.{payload}".encode()
            jwt = f"{header}.{payload}.{_b64url(key.sign(unsigned, padding.PKCS1v15(), hashes.SHA256()))}"
            response = _json_request(
                f"{self.config.github_origin}/app/installations/{self.config.installation_id}/access_tokens",
                method="POST", payload={}, headers={"authorization": f"Bearer {jwt}"}, expected={201},
            )
            self._token = str(response["token"])
            self._expires_at = datetime.fromisoformat(str(response["expires_at"]).replace("Z", "+00:00"))
            return self._token
        except PublisherError:
            raise
        except Exception as exc:
            raise PublisherError("authentication_failed") from exc


def _json_request(url: str, *, method: str = "GET", payload: object | None = None,
                  headers: dict[str, str] | None = None, expected: set[int] | None = None,
                  timeout: float = 12) -> dict[str, Any] | list[Any]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    outgoing = {"accept": "application/vnd.github+json", "user-agent": "BeyondQuant-Feedback-Publisher/1",
                "x-github-api-version": "2022-11-28", **(headers or {})}
    if body is not None:
        outgoing["content-type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=outgoing, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if expected and response.status not in expected:
                raise PublisherError("provider_unavailable")
            raw = response.read(256 * 1024)
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        retry_after = exc.headers.get("retry-after", "30")
        try:
            bounded_retry = max(5, min(int(retry_after), 3600))
        except ValueError:
            bounded_retry = 30
        rate_limited_403 = exc.code == 403 and (
            exc.headers.get("retry-after") is not None or exc.headers.get("x-ratelimit-remaining") == "0"
        )
        category = {
            401: "authentication_failed", 403: "permission_denied", 404: "repository_unavailable",
            410: "issues_disabled", 422: "validation_rejected", 429: "rate_limited",
        }.get(exc.code, "provider_unavailable" if exc.code >= 500 else "validation_rejected")
        if rate_limited_403:
            category = "rate_limited"
        raise PublisherError(category, retry_after=bounded_retry) from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise PublisherError("transport_ambiguous") from exc


def _backend(config: Config, path: str, payload: object) -> dict[str, Any]:
    result = _json_request(
        f"{config.backend_url}{path}", method="POST", payload=payload,
        headers={"x-byq-feedback-publisher-token": config.service_token}, expected={200},
    )
    if not isinstance(result, dict):
        raise PublisherError("provider_unavailable")
    return result


def marker(event: dict[str, Any]) -> str:
    return f"<!-- byq-feedback:{event['event_id']}:{event['snapshot_hash']} -->"


def render(event: dict[str, Any]) -> tuple[str, str]:
    public = event["snapshot"]["public_content"]
    prefix = {"bug": "[Bug]", "feature": "[Feature]", "performance": "[Performance]",
              "usability": "[UX]", "other": "[Feedback]"}[public["category"]]
    safe = lambda value: str(value).replace("@", "＠").replace("<!--", "&lt;!--")
    sections = [f"## Summary\n\n{safe(public['description'])}"]
    steps = public.get("reproduction_steps") or []
    if steps:
        sections.append("## Reproduction\n\n" + "\n".join(f"{index}. {safe(item)}" for index, item in enumerate(steps, 1)))
    if public.get("expected_behavior"):
        sections.append(f"## Expected\n\n{safe(public['expected_behavior'])}")
    if public.get("actual_behavior"):
        sections.append(f"## Actual\n\n{safe(public['actual_behavior'])}")
    environment = public.get("environment") or {}
    if environment:
        sections.append("## Environment\n\n" + "\n".join(f"- {safe(key)}: `{safe(value)}`" for key, value in environment.items()))
    sections.append("_Submitted through BeyondQuant's privacy-reviewed Product Feedback flow._")
    sections.append(marker(event))
    return f"{prefix} {safe(public['title'])}"[:256], "\n\n".join(sections)


class GitHubIssues:
    def __init__(self, config: Config, credential: GitHubCredential | None = None) -> None:
        if not config.repository:
            raise ValueError("fixed repository is required")
        self.config = config
        self.credential = credential or GitHubCredential(config)
        self.base = f"{config.github_origin}/repos/{config.repository}/issues"

    def _headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.credential.token()}"}

    def reconcile(self, event: dict[str, Any]) -> dict[str, Any] | None:
        result = _json_request(f"{self.base}?state=all&per_page=100&page=1", headers=self._headers(), expected={200})
        if not isinstance(result, list):
            raise PublisherError("provider_unavailable")
        matches = [item for item in result if marker(event) in str(item.get("body", ""))]
        if len(matches) > 1:
            raise PublisherError("reconciliation_conflict")
        return matches[0] if matches else None

    def create(self, event: dict[str, Any]) -> dict[str, Any]:
        title, body = render(event)
        result = _json_request(self.base, method="POST", payload={"title": title, "body": body},
                               headers=self._headers(), expected={201})
        if not isinstance(result, dict):
            raise PublisherError("provider_unavailable")
        return result


def _complete(config: Config, event: dict[str, Any], issue: dict[str, Any]) -> None:
    number = issue.get("number")
    provider_id = issue.get("id")
    expected_url = f"https://github.com/{config.repository}/issues/{number}"
    if not isinstance(number, int) or number < 1 or not provider_id or issue.get("html_url") != expected_url:
        raise PublisherError("validation_rejected")
    _backend(config, f"/internal/feedback-publications/{event['event_id']}/complete", {
        "worker_id": config.worker_id, "lease_fence": event["lease_fence"], "repository": config.repository,
        "issue_number": number, "html_url": expected_url, "provider_identity": str(provider_id),
    })


def process_event(config: Config, github: GitHubIssues, event: dict[str, Any]) -> None:
    try:
        existing = github.reconcile(event)
        _complete(config, event, existing or github.create(event))
    except PublisherError as exc:
        _backend(config, f"/internal/feedback-publications/{event['event_id']}/retry", {
            "worker_id": config.worker_id, "lease_fence": event["lease_fence"],
            "error_category": exc.category, "retry_after_seconds": exc.retry_after,
        })


class _Health(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        status = 200 if self.path == "/healthz" else 404
        body = b'{"service":"feedback-publisher","status":"ok"}' if status == 200 else b"{}"
        self.send_response(status); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def run(config: Config) -> None:
    if not config.service_token:
        raise ValueError("publisher service token is required")
    health = ThreadingHTTPServer(("127.0.0.1", 8700), _Health)
    threading.Thread(target=health.serve_forever, daemon=True).start()
    github = GitHubIssues(config) if config.configured else None
    while True:
        try:
            _backend(config, "/internal/feedback-publications/heartbeat", {
                "configured": config.configured, "credential_kind": config.credential_kind,
                "repository": config.repository, "worker_version": WORKER_VERSION,
            })
            if github:
                claimed = _backend(config, "/internal/feedback-publications/claim", {
                    "worker_id": config.worker_id, "limit": 5, "lease_seconds": 60,
                })
                for event in claimed.get("events", []):
                    process_event(config, github, event)
        except Exception:
            pass
        time.sleep(config.poll_seconds)


if __name__ == "__main__":
    run(Config.from_env())
