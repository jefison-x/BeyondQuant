from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from deepseek_harness import Notification

import app.runtime as runtime_module
from app.identifiers import MAX_IDENTIFIER_LENGTH
from app.runtime import ModelCredentialUnavailable, RuntimeAdapter, SessionConflict, SessionStatus


class FakeHarness:
    instances: list["FakeHarness"] = []
    run_started = threading.Event()
    allow_run = threading.Event()

    def __init__(self, config: object) -> None:
        self.config = config
        self.started = False
        self.closed = False
        self.run_count = 0
        self.__class__.instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.instances.clear()
        cls.run_started.clear()
        cls.allow_run.clear()

    def start(self) -> None:
        self.started = True

    def start_session(self, _session_id: str) -> "FakeHarness":
        return self

    def run(self, _content: str, *, on_notification: object) -> SimpleNamespace:
        self.run_count += 1
        self.__class__.run_started.set()
        self.__class__.allow_run.wait(timeout=2.0)
        return SimpleNamespace(finish_reason="completed")

    def close(self) -> None:
        self.closed = True
        self.__class__.allow_run.set()


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> RuntimeAdapter:
    FakeHarness.reset()
    monkeypatch.setattr(runtime_module, "DeepSeekHarness", FakeHarness)
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(tmp_path / "composition.yml"))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    return RuntimeAdapter()


def wait_for_status(adapter: RuntimeAdapter, session_id: str, status: str) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        record = adapter._get(session_id)
        if adapter.describe_session(record)["status"] == status:
            return
        time.sleep(0.01)
    raise AssertionError(f"session did not reach {status}")


def test_lifecycle_has_single_active_prompt_and_duplicate_create_is_explicit(adapter: RuntimeAdapter) -> None:
    created = adapter.create_session("s-1", "t-1")
    assert created["status"] == SessionStatus.READY
    assert FakeHarness.instances[0].started is True

    first_run = adapter.submit_prompt("s-1", "first")
    assert first_run
    assert FakeHarness.run_started.wait(timeout=1.0)
    with pytest.raises(SessionConflict):
        adapter.submit_prompt("s-1", "concurrent")
    with pytest.raises(SessionConflict):
        adapter.create_session("s-1", "t-duplicate")

    FakeHarness.allow_run.set()
    wait_for_status(adapter, "s-1", SessionStatus.IDLE)
    released = adapter.release_session("s-1")
    assert released["status"] == SessionStatus.CLOSED
    assert FakeHarness.instances[0].closed is True

    recreated = adapter.create_session("s-1", "t-2")
    assert recreated["status"] == SessionStatus.READY
    adapter.release_session("s-1")


def test_hard_cancel_closes_runtime_and_rejects_later_prompt(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-1", "t-1")
    adapter.submit_prompt("s-1", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)

    cancelled = adapter.cancel_session("s-1", "hard")
    assert cancelled["status"] == SessionStatus.INTERRUPTED
    assert cancelled["active_prompt"] is False
    assert FakeHarness.instances[0].closed is True
    with pytest.raises(SessionConflict):
        adapter.submit_prompt("s-1", "must-not-run")

    released = adapter.release_session("s-1")
    assert released["status"] == SessionStatus.CLOSED


def test_hard_cancel_resume_uses_a_new_owned_runtime(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-1", "t-1")
    adapter.submit_prompt("s-1", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)

    adapter.cancel_session("s-1", "hard")
    resumed = adapter.resume_session("s-1")

    assert resumed["status"] == SessionStatus.READY
    assert resumed["resumed_from_run_id"]
    assert len(FakeHarness.instances) == 2
    assert FakeHarness.instances[0].closed is True
    adapter.release_session("s-1")


def test_product_turn_requires_a_model_credential_without_exposing_it(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-1", "t-1")
    with pytest.raises(ModelCredentialUnavailable):
        adapter.submit_prompt("s-1", "product turn", require_model_key=True)
    assert "DEEPSEEK_API_KEY" not in str(adapter.readiness())
    assert "DEEPSEEK_API_KEY" not in str(adapter.describe_session(adapter._get("s-1")))
    adapter.release_session("s-1")


def test_operations_snapshot_normalizes_and_deduplicates_dsh_usage(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-1", "t-1")
    record = adapter._get("s-1")
    notification = Notification(
        method="session.event",
        payload={
            "sessionId": "s-1",
            "event": {
                "type": "assistant/message",
                "data": {
                    "message": {"id": "message-usage-1", "content": []},
                    "usage": {
                        "inputTokens": 100,
                        "outputTokens": 20,
                        "cacheReadTokens": 30,
                        "cacheWriteTokens": 5,
                        "reasoningTokens": 10,
                    },
                    "private": {"apiKey": "must-not-escape"},
                },
            },
        },
    )
    adapter._on_notification(record, notification)
    adapter._on_notification(record, notification)

    snapshot = adapter.operations_snapshot()
    assert snapshot["usage"] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "cache_read_tokens": 30,
        "cache_write_tokens": 5,
        "reasoning_tokens": 10,
        "model_calls": 1,
        "total_tokens": 155,
        "scope": "adapter_process_lifetime",
        "source": "normalized_dsh_token_usage",
    }
    assert snapshot["raw_dsh_events"] is False
    assert "must-not-escape" not in str(snapshot)
    adapter.release_session("s-1")


def test_invalid_usage_is_dropped_atomically(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-1", "t-1")
    record = adapter._get("s-1")
    adapter._on_notification(record, Notification(
        method="session.event",
        payload={
            "sessionId": "s-1",
            "event": {
                "type": "assistant/message",
                "data": {
                    "message": {"id": "message-usage-invalid", "content": []},
                    "usage": {"inputTokens": -1, "outputTokens": 2},
                },
            },
        },
    ))
    assert adapter.operations_snapshot()["usage"]["model_calls"] == 0
    adapter.release_session("s-1")


def test_configured_model_credential_is_scoped_to_the_owned_sdk_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    FakeHarness.reset()
    monkeypatch.setattr(runtime_module, "DeepSeekHarness", FakeHarness)
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(tmp_path / "composition.yml"))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-provider-secret")

    adapter = RuntimeAdapter()
    adapter.create_session("s-1", "t-1")
    sdk_environment = FakeHarness.instances[0].config.env
    assert sdk_environment["DEEPSEEK_API_KEY"] == "test-provider-secret"
    assert "test-provider-secret" not in str(adapter.readiness())
    assert "test-provider-secret" not in str(adapter.describe_session(adapter._get("s-1")))
    adapter.release_session("s-1")


def test_personal_model_binding_is_resolved_directly_without_public_exposure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    FakeHarness.reset()
    monkeypatch.setattr(runtime_module, "DeepSeekHarness", FakeHarness)
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(tmp_path / "composition.yml"))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("BYQ_BACKEND_URL", "http://backend.test")
    monkeypatch.setenv("BYQ_CREDENTIAL_RESOLVER_TOKEN", "resolver-test-only")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "system-fallback-must-not-win")
    captured: dict[str, object] = {}

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "resolution": {
                    "source": "user_binding",
                    "provider": "deepseek-official",
                    "model": "deepseek-reasoner",
                    "api_key": "personal-provider-secret",
                }
            }

    def post(url: str, **kwargs: object) -> Response:
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(runtime_module.httpx, "post", post)
    adapter = RuntimeAdapter()
    adapter.create_session("s-1", "t-1", "alice")

    assert captured["url"] == "http://backend.test/internal/credentials/model-resolution"
    assert captured["headers"] == {"x-byq-credential-resolver-token": "resolver-test-only"}
    assert captured["json"]["owner_principal"] == "alice"
    config = FakeHarness.instances[0].config
    assert config.provider == "deepseek-official"
    assert config.model == "deepseek-reasoner"
    assert config.env["DEEPSEEK_API_KEY"] == "personal-provider-secret"
    assert "personal-provider-secret" not in str(adapter.readiness())
    assert "personal-provider-secret" not in str(adapter.describe_session(adapter._get("s-1")))
    adapter.release_session("s-1")


def test_broken_personal_resolution_never_falls_back_to_system_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    FakeHarness.reset()
    monkeypatch.setattr(runtime_module, "DeepSeekHarness", FakeHarness)
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(tmp_path / "composition.yml"))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("BYQ_CREDENTIAL_RESOLVER_TOKEN", "resolver-test-only")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "system-fallback-must-not-win")

    class Response:
        status_code = 409

        def raise_for_status(self) -> None:
            raise runtime_module.httpx.HTTPStatusError(
                "conflict",
                request=runtime_module.httpx.Request("POST", "http://backend"),
                response=runtime_module.httpx.Response(409),
            )

    monkeypatch.setattr(runtime_module.httpx, "post", lambda *args, **kwargs: Response())
    adapter = RuntimeAdapter()
    with pytest.raises(ModelCredentialUnavailable):
        adapter.create_session("s-1", "t-1", "alice")
    assert FakeHarness.instances == []


def test_product_context_is_scoped_to_the_owned_sdk_environment(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-1", "t-1", "alice")
    sdk_environment = FakeHarness.instances[0].config.env
    assert sdk_environment["BYQ_OWNER_PRINCIPAL"] == "alice"
    assert sdk_environment["BYQ_ACTOR_PRINCIPAL"] == "byq-product-agent-s-1"
    assert sdk_environment["BYQ_TRACE_ID"] == "t-1"
    assert sdk_environment["BYQ_SESSION_ID"] == "s-1"
    assert sdk_environment["BYQ_DSH_RUN_ID"] == "s-1"
    adapter.release_session("s-1")


def test_soft_cancel_is_scoped_to_current_run_and_returns_to_idle(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-1", "t-1")
    adapter.submit_prompt("s-1", "first")
    assert FakeHarness.run_started.wait(timeout=1.0)
    assert adapter.cancel_session("s-1", "soft")["status"] == SessionStatus.CANCELLING
    with pytest.raises(SessionConflict):
        adapter.submit_prompt("s-1", "while-cancelling")

    FakeHarness.allow_run.set()
    wait_for_status(adapter, "s-1", SessionStatus.IDLE)
    FakeHarness.run_started.clear()
    FakeHarness.allow_run.clear()
    second_run = adapter.submit_prompt("s-1", "second")
    assert second_run
    assert FakeHarness.run_started.wait(timeout=1.0)
    assert FakeHarness.instances[0].run_count == 2
    FakeHarness.allow_run.set()
    wait_for_status(adapter, "s-1", SessionStatus.IDLE)
    adapter.release_session("s-1")


@pytest.mark.parametrize(
    "value",
    ["../escape", "/absolute", "", "a" * (MAX_IDENTIFIER_LENGTH + 1), "has space", "ümlaut"],
)
def test_session_and_trace_identifiers_are_controlled(adapter: RuntimeAdapter, value: str) -> None:
    with pytest.raises(ValueError):
        adapter.create_session(value, "trace-ok")
    with pytest.raises(ValueError):
        adapter.create_session("session-ok", value)


def test_workflow_trace_sequence_and_publish_order_are_atomic(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-1", "t-1")
    record = adapter._get("s-1")
    subscriber = adapter.subscribe("s-1")
    assert record.sequence == 1

    barrier = threading.Barrier(33)

    def emit(index: int) -> None:
        barrier.wait()
        if index % 2:
            adapter._on_notification(
                record,
                Notification(
                    method="session.status",
                    payload={"sessionId": "s-1", "status": "idle"},
                ),
            )
        else:
            adapter._emit(record, "session.result", "runtime-adapter", {"index": index})

    workers = [threading.Thread(target=emit, args=(index,)) for index in range(32)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=1.0)

    events = [subscriber.get(timeout=1.0) for _ in workers]
    sequences = [event["sequence"] for event in events]
    assert sequences == list(range(2, 34))
    assert len(set(sequences)) == len(sequences)
    adapter.release_session("s-1")
