"""Thread-confined HTTP pools for Gateway service-to-service calls.

Gateway routes are synchronous and FastAPI dispatches them through an AnyIO
worker pool.  A single process-wide ``httpx.Client`` couples every route to the
same httpcore pool state: a cancelled or stale service-to-service exchange can
then strand unrelated authentication and Product API workers while health
checks continue to pass.  Keep clients lazy and thread-local so each long-lived
worker still gets keep-alive reuse without sharing mutable connection state
across workers.
"""

from __future__ import annotations

import httpx as _httpx
import threading


class PooledHttp:
    HTTPError = _httpx.HTTPError
    HTTPStatusError = _httpx.HTTPStatusError
    Request = _httpx.Request
    Response = _httpx.Response

    def __init__(self) -> None:
        self._local = threading.local()
        self._clients: list[_httpx.Client] = []
        self._clients_lock = threading.Lock()

    def _get_client(self) -> _httpx.Client:
        client = getattr(self._local, "client", None)
        if client is None:
            client = _httpx.Client(
                # A synchronous route issues only one request at a time. Keep
                # the per-thread budget deliberately small; aggregate
                # concurrency is bounded by FastAPI's worker pool.
                limits=_httpx.Limits(max_connections=4, max_keepalive_connections=2),
                timeout=_httpx.Timeout(8.0),
            )
            self._local.client = client
            with self._clients_lock:
                self._clients.append(client)
        return client

    def get(self, *args: object, **kwargs: object) -> _httpx.Response:
        return self._get_client().get(*args, **kwargs)

    def post(self, *args: object, **kwargs: object) -> _httpx.Response:
        return self._get_client().post(*args, **kwargs)

    def request(self, *args: object, **kwargs: object) -> _httpx.Response:
        return self._get_client().request(*args, **kwargs)

    def stream(self, *args: object, **kwargs: object):
        return self._get_client().stream(*args, **kwargs)

    def close(self) -> None:
        with self._clients_lock:
            clients, self._clients = self._clients, []
        for client in clients:
            client.close()


pooled_http = PooledHttp()
