"""Real process loss after synthetic Backend commit; CI network only."""
import json
import multiprocessing
import os
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx

from app import main
from app.agent_lifecycle_delivery import LifecycleDelivery
from app.trace_store import TraceStore


with httpx.Client(base_url="http://backend:8000", timeout=10) as backend:
    login = backend.post("/v1/auth/login", json={"username": "ci-r2-admin", "password": "ci-r2-browser-only"})
    login.raise_for_status()
    identity = login.json()
    workspace = identity["workspace"]["workspace_id"]
    backend.headers.update({"x-byq-owner-principal": "ci-r2-admin", "x-byq-workspace-id": workspace})
    session_id, trace_id = "answer-http-" + uuid.uuid4().hex, "answer-http-trace"
    created = backend.post("/v1/product/conversations", json={"runtime_session_id": session_id, "trace_id": trace_id})
    created.raise_for_status()
    conversation = created.json()["conversation"]["conversation_id"]
    session = SimpleNamespace(session_id=session_id, trace_id=trace_id, conversation_id=conversation,
                              workspace_id=workspace, principal=main.Principal(subject="ci-r2-admin"))
    with tempfile.TemporaryDirectory(prefix="byq-answer-http-") as directory:
        traces = TraceStore(directory)
        for sequence in (9, 10):
            traces.append({"session_id": session_id, "trace_id": trace_id, "sequence": sequence,
                "timestamp": "2026-09-08T00:00:00+00:00", "source": "runtime-adapter", "kind": "agent.output.delta",
                "payload": {"schema_version": "workflow-answer.v1", "channel": "answer",
                            "delta": f"Synthetic durable answer {sequence}", "truncated": False}})
        def crash_after_commit(context, event):
            main._send_owned_answer(context, event)
            os._exit(17)  # No Python finally/ACK; OS releases the file lock.
        initial = LifecycleDelivery(directory, traces, crash_after_commit, clock=lambda: 1000, answers=True)
        initial.register(session)
        process = multiprocessing.get_context("fork").Process(target=initial.run_once)
        process.start()
        process.join(20)
        if process.is_alive():
            process.terminate()
            process.join(5)
            raise AssertionError("synthetic child did not exit")
        assert process.exitcode == 17, process.exitcode
        ledger = Path(directory) / f"{session_id}.answers.json"
        state = json.loads(ledger.read_text())
        assert state["pending"]["9"]["attempts"] == 1
        assert state["pending"]["10"]["attempts"] == 0
        restarted = LifecycleDelivery(directory, TraceStore(directory), main._send_owned_answer,
                                      clock=lambda: 1002, answers=True)
        restarted.run_once()
        assert json.loads(ledger.read_text())["pending"] == {}
        restarted.run_once()
    result = backend.get(f"/v1/product/conversations/{conversation}")
    result.raise_for_status()
    messages = result.json()["messages"]
    assert [message["workflow_sequence"] for message in messages] == [9, 10]
    assert [message["sequence"] for message in messages] == [1, 2]
    backend.post("/v1/auth/logout", json={"session_id": identity["session_id"]}).raise_for_status()
print("PASS: real process exit after Backend commit, durable attempt, exact replay, two ordered messages, no model")
