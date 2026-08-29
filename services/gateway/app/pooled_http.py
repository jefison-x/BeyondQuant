"""Process-wide HTTP connection pool for Gateway service-to-service calls."""

from __future__ import annotations

import httpx as _httpx


class PooledHttp:
    HTTPError = _httpx.HTTPError
    HTTPStatusError = _httpx.HTTPStatusError
    Request = _httpx.Request
    Response = _httpx.Response

    def __init__(self) -> None:
        self._client = _httpx.Client(
            limits=_httpx.Limits(max_connections=100, max_keepalive_connections=20),
            timeout=_httpx.Timeout(8.0),
        )

    def get(self, *args: object, **kwargs: object) -> _httpx.Response:
        return self._client.get(*args, **kwargs)

    def post(self, *args: object, **kwargs: object) -> _httpx.Response:
        return self._client.post(*args, **kwargs)

    def request(self, *args: object, **kwargs: object) -> _httpx.Response:
        return self._client.request(*args, **kwargs)

    def stream(self, *args: object, **kwargs: object):
        return self._client.stream(*args, **kwargs)

    def close(self) -> None:
        self._client.close()


pooled_http = PooledHttp()
