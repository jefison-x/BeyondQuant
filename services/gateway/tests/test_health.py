import os

from fastapi.testclient import TestClient

from app import main


client = TestClient(main.app)


def test_healthz_is_local_and_stable() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "service": "byq-gateway",
        "status": "ok",
        "version": "0.1.0",
    }


def test_readyz_reports_runtime_adapter_integration() -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "service": "byq-gateway",
        "status": "ok",
        "version": "0.1.0",
        "dsh_runtime_integration": "runtime-adapter",
        "product_authentication": "configured" if os.environ.get("BYQ_PRODUCT_TOKEN") else "missing",
    }


def test_workflow_stream_is_byq_event_transport(monkeypatch) -> None:
    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self):
            yield b'event: workflow-trace\ndata: {"kind":"session.status","source":"dsh"}\n\n'

    class FakeStream:
        def __enter__(self):
            return FakeResponse()

        def __exit__(self, *_args) -> None:
            return None

    monkeypatch.setattr(main.httpx, "stream", lambda *_args, **_kwargs: FakeStream())

    response = client.get("/internal/workflows/session-1/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: workflow-trace" in response.text
    assert ("session." + "event") not in response.text
