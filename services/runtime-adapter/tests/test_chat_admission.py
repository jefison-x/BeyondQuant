from pathlib import Path
import queue

from fastapi.testclient import TestClient

from app import main


def test_runtime_maintenance_blocks_admission_but_keeps_release_and_events(monkeypatch, tmp_path: Path):
    gate = tmp_path / "admission.state"
    gate.write_text("closed\n")
    monkeypatch.setenv("BYQ_CHAT_ADMISSION_FILE", str(gate))
    for name in ("create_session", "submit_prompt", "resume_session"):
        monkeypatch.setattr(main.adapter, name, lambda *_, **__: (_ for _ in ()).throw(AssertionError("admitted")))
    client = TestClient(main.app)
    for path, payload in (
        ("/internal/runtime/sessions", {"session_id": "synthetic", "trace_id": "synthetic"}),
        ("/internal/runtime/sessions/synthetic/prompt", {"content": "synthetic"}),
        ("/internal/runtime/sessions/synthetic/resume", {}),
    ):
        response = client.post(path, json=payload)
        assert response.status_code == 503
        assert str(gate) not in response.text
    monkeypatch.setattr(main.adapter, "release_session", lambda _: {"status": "closed"})
    assert client.post("/internal/runtime/sessions/synthetic/release").status_code == 200
    assert client.get("/healthz").status_code == 200
    subscriber = queue.Queue()
    subscriber.put({"type": "run.completed", "sequence": 1})
    subscriber.put(None)
    released = []
    monkeypatch.setattr(main.adapter, "subscribe", lambda *_, **__: subscriber)
    monkeypatch.setattr(main.adapter, "unsubscribe", lambda *args: released.append(args))
    response = client.get("/internal/runtime/sessions/synthetic/events")
    assert response.status_code == 200
    assert "event: workflow-trace" in response.text
    assert "run.completed" in response.text
    assert released == [("synthetic", subscriber)]
