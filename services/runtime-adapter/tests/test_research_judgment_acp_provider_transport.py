"""Bounded read and redirect policy without a real provider connection."""

from __future__ import annotations

import http.client
import time

import pytest

from app import research_judgment_acp_provider_proxy as proxy_module
from app.research_judgment_acp_provider_usage import MAX_SSE_BYTES


class _Socket:
    def __init__(self):
        self.timeouts = []

    def fileno(self):
        return 1

    def settimeout(self, value):
        self.timeouts.append(value)


class _Response:
    def __init__(self, body, *, claimed_length=None):
        self.data = body
        self.length = len(body) if claimed_length is None else claimed_length
        self.fp = object()

    def read1(self, size):
        chunk, self.data = self.data[:size], self.data[size:]
        self.length -= len(chunk)
        return chunk


def test_bounded_reader_rejects_truncated_and_oversized_provider_body(monkeypatch):
    sock = _Socket()
    monkeypatch.setattr(proxy_module, "_response_socket", lambda _: sock)
    with pytest.raises(http.client.IncompleteRead):
        proxy_module._read_bounded(_Response(b"partial", claimed_length=100),
                                   time.monotonic() + 3)
    closed_early = _Response(b"", claimed_length=3)
    closed_early.fp = None
    with pytest.raises(http.client.IncompleteRead):
        proxy_module._read_bounded(closed_early, time.monotonic() + 3)
    with pytest.raises(ValueError, match="bounded SSE size"):
        proxy_module._read_bounded(_Response(b"x" * (MAX_SSE_BYTES + 1)),
                                   time.monotonic() + 3)
    assert sock.timeouts and all(value > 0 for value in sock.timeouts)


def test_bounded_reader_enforces_deadline_and_redirect_handler_rejects_location(monkeypatch):
    monkeypatch.setattr(proxy_module, "_response_socket", lambda _: _Socket())
    with pytest.raises(TimeoutError):
        proxy_module._read_bounded(_Response(b"data"), time.monotonic() - 1)
    assert proxy_module._NoRedirect().redirect_request(
        None, None, 302, "redirect", {"location": "https://other.example"},
        "https://other.example") is None
    with pytest.raises(ValueError, match="HTTPS"):
        proxy_module._send_https("http://127.0.0.1/provider", {}, b"body",
                                 time.monotonic() + 3)
