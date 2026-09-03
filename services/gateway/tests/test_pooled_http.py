from __future__ import annotations

import threading

from app.pooled_http import PooledHttp


def test_client_is_reused_within_thread_and_isolated_between_threads(monkeypatch) -> None:
    created: list[FakeClient] = []

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            self.closed = False
            created.append(self)

        def get(self, *_args: object, **_kwargs: object) -> object:
            return self

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr("app.pooled_http._httpx.Client", FakeClient)
    pooled = PooledHttp()

    main_first = pooled.get("http://backend/healthz")
    main_second = pooled.get("http://backend/healthz")
    worker_result: list[object] = []
    worker = threading.Thread(
        target=lambda: worker_result.append(pooled.get("http://backend/healthz")),
    )
    worker.start()
    worker.join()

    assert main_first is main_second
    assert worker_result[0] is not main_first
    assert len(created) == 2

    pooled.close()
    assert all(client.closed for client in created)
