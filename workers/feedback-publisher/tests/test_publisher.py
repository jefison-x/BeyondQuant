from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "publisher.py"
SPEC = importlib.util.spec_from_file_location("feedback_publisher", MODULE_PATH)
assert SPEC and SPEC.loader
publisher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = publisher
SPEC.loader.exec_module(publisher)


class FakeGitHub(BaseHTTPRequestHandler):
    issues: list[dict[str, object]] = []
    post_status = 201
    get_status = 200
    retry_header = False
    requests: list[tuple[str, str, dict[str, object] | None]] = []

    def do_GET(self) -> None:  # noqa: N802
        type(self).requests.append(("GET", self.path, None))
        body = json.dumps(type(self).issues).encode()
        self.send_response(type(self).get_status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        type(self).requests.append(("POST", self.path, payload))
        body = json.dumps({"id": 9001, "number": 321,
                           "html_url": "https://github.com/jefison-x/BeyondQuant/issues/321",
                           "body": payload.get("body", "")}).encode()
        self.send_response(type(self).post_status)
        if type(self).post_status == 429 or type(self).retry_header:
            self.send_header("retry-after", "17")
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


@pytest.fixture
def github_server():
    FakeGitHub.issues, FakeGitHub.requests = [], []
    FakeGitHub.post_status, FakeGitHub.get_status, FakeGitHub.retry_header = 201, 200, False
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown(); server.server_close()


def config(origin: str):
    return publisher.Config(
        backend_url="http://backend.invalid", service_token="service-token",
        repository="jefison-x/BeyondQuant", github_origin=origin, github_token="github-token",
        app_id=None, installation_id=None, private_key_file=None, worker_id="worker-test",
        poll_seconds=2, allow_test_origin=True,
    )


def event():
    return {
        "event_id": "feedback_outbox_" + "a" * 32, "snapshot_hash": "b" * 64,
        "lease_fence": 1,
        "snapshot": {"public_content": {"category": "bug", "component": "data_center", "severity": "normal",
            "title": "Data view @mention is slow", "description": "Opening the page takes too long.",
            "reproduction_steps": ["Open data center"], "expected_behavior": "Fast page",
            "actual_behavior": "Slow page", "environment": {"browser_family": "chrome"}}},
    }


def test_renderer_is_versioned_bounded_and_neutralizes_mentions() -> None:
    title, body = publisher.render(event())
    assert title.startswith("[Bug]") and "＠mention" in title and "@mention" not in title
    assert publisher.marker(event()) in body
    assert "raw" not in body and "github-token" not in body


def test_fixed_repository_reconcile_then_create(github_server) -> None:
    client = publisher.GitHubIssues(config(github_server))
    assert client.reconcile(event()) is None
    created = client.create(event())
    assert created["number"] == 321
    assert FakeGitHub.requests[0][0:2] == ("GET", "/repos/jefison-x/BeyondQuant/issues?state=all&per_page=100&page=1")
    assert FakeGitHub.requests[1][0:2] == ("POST", "/repos/jefison-x/BeyondQuant/issues")
    FakeGitHub.issues = [created]
    assert client.reconcile(event())["number"] == 321


def test_reconciliation_conflict_and_provider_error_matrix(github_server) -> None:
    client = publisher.GitHubIssues(config(github_server))
    duplicate = {"body": publisher.marker(event()), "number": 1}
    FakeGitHub.issues = [duplicate, duplicate]
    with pytest.raises(publisher.PublisherError, match="reconciliation_conflict"):
        client.reconcile(event())
    FakeGitHub.issues = []
    for status, category in ((401, "authentication_failed"), (403, "permission_denied"),
                             (404, "repository_unavailable"), (410, "issues_disabled"),
                             (422, "validation_rejected"), (429, "rate_limited"),
                             (500, "provider_unavailable")):
        FakeGitHub.post_status = status
        with pytest.raises(publisher.PublisherError) as caught:
            client.create(event())
        assert caught.value.category == category
        if status == 429:
            assert caught.value.retry_after == 17
    FakeGitHub.post_status, FakeGitHub.retry_header = 403, True
    with pytest.raises(publisher.PublisherError) as rate_limited:
        client.create(event())
    assert rate_limited.value.category == "rate_limited" and rate_limited.value.retry_after == 17


def test_non_default_origin_and_arbitrary_repository_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("BYQ_FEEDBACK_GITHUB_API_ORIGIN", "http://attacker.invalid")
    with pytest.raises(ValueError, match="test-only"):
        publisher.Config.from_env()
    monkeypatch.setenv("BYQ_FEEDBACK_GITHUB_API_ORIGIN", publisher.SAFE_ORIGIN)
    monkeypatch.setenv("BYQ_FEEDBACK_GITHUB_REPOSITORY", "https://attacker.invalid/repo")
    with pytest.raises(ValueError, match="owner/repo"):
        publisher.Config.from_env()


def test_ambiguous_create_is_retried_then_reconciled_without_second_create(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(publisher, "_backend", lambda _config, path, payload: calls.append((path, payload)) or {})

    class AmbiguousThenExisting:
        def __init__(self):
            self.existing = None
            self.creates = 0

        def reconcile(self, _event):
            return self.existing

        def create(self, _event):
            self.creates += 1
            raise publisher.PublisherError("transport_ambiguous")

    cfg = config(publisher.SAFE_ORIGIN)
    github = AmbiguousThenExisting()
    publisher.process_event(cfg, github, event())
    assert calls[-1][0].endswith("/retry")
    assert calls[-1][1]["error_category"] == "transport_ambiguous"
    github.existing = {"id": 9001, "number": 321,
                       "html_url": "https://github.com/jefison-x/BeyondQuant/issues/321"}
    publisher.process_event(cfg, github, event())
    assert calls[-1][0].endswith("/complete") and github.creates == 1


def test_github_app_is_preferred_over_fallback_token() -> None:
    cfg = publisher.Config(
        backend_url="http://backend", service_token="service", repository="jefison-x/BeyondQuant",
        github_origin=publisher.SAFE_ORIGIN, github_token="fallback", app_id="1", installation_id="2",
        private_key_file="/run/secrets/key.pem", worker_id="worker-test", poll_seconds=2,
    )
    assert cfg.credential_kind == "github_app"
