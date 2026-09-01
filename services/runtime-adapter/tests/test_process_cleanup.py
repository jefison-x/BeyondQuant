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
    finish_reason = "completed"

    def __init__(self, config: object) -> None:
        self.config = config
        self.started = False
        self.closed = False
        self.run_count = 0
        self.session_id = ""
        self.last_content = ""
        self.__class__.instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.instances.clear()
        cls.run_started.clear()
        cls.allow_run.clear()
        cls.finish_reason = "completed"

    def start(self) -> None:
        self.started = True

    def start_session(self, session_id: str) -> "FakeHarness":
        self.session_id = session_id
        return self

    def run(self, content: str, *, on_notification: object) -> SimpleNamespace:
        self.run_count += 1
        self.last_content = content
        self.__class__.run_started.set()
        self.__class__.allow_run.wait(timeout=2.0)
        return SimpleNamespace(finish_reason=self.__class__.finish_reason)

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
    monkeypatch.setenv("BYQ_DSH_RUN_TIMEOUT_SECONDS", "3600")
    monkeypatch.setenv("BYQ_DSH_SUBAGENT_TIMEOUT_SECONDS", "3600")
    monkeypatch.setenv("BYQ_DSH_NO_PROGRESS_TIMEOUT_SECONDS", "3600")
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


def test_no_progress_watchdog_fails_and_closes_only_the_stuck_runtime(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-stuck", "t-stuck")
    adapter.submit_prompt("s-stuck", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("s-stuck")
    run = record.active_run
    assert run is not None

    run.last_public_progress_at = 10.0
    assert adapter._enforce_run_guards(record, run, now=3611.0) is True

    wait_for_status(adapter, "s-stuck", SessionStatus.FAILED)
    assert FakeHarness.instances[0].closed is True
    assert record.active_run is None
    assert record.history[-1]["kind"] == "session.failed"
    assert record.history[-1]["payload"] == {
        "code": "runtime-no-progress-timeout",
        "retryable": True,
    }
    history_length = len(record.history)
    adapter._on_notification(record, Notification(
        method="session.status",
        payload={"sessionId": record.runtime_session_id, "status": "idle"},
    ))
    assert len(record.history) == history_length


def test_subagent_wall_clock_timeout_wins_even_when_public_progress_continues(
    adapter: RuntimeAdapter,
) -> None:
    adapter.create_session("s-child", "t-child")
    adapter.submit_prompt("s-child", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("s-child")
    run = record.active_run
    assert run is not None
    run.last_public_progress_at = 3600.0
    run.active_subagent_calls["delegate-call"] = 10.0

    assert adapter._enforce_run_guards(record, run, now=3611.0) is True

    wait_for_status(adapter, "s-child", SessionStatus.FAILED)
    assert record.history[-1]["payload"] == {
        "code": "runtime-subagent-timeout",
        "retryable": True,
    }


def test_total_run_wall_clock_is_a_final_ceiling(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-run-limit", "t-run-limit")
    adapter.submit_prompt("s-run-limit", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("s-run-limit")
    run = record.active_run
    assert run is not None
    run.started_at = 10.0
    run.last_public_progress_at = 3_610.0

    assert adapter._enforce_run_guards(record, run, now=3_611.0) is True

    wait_for_status(adapter, "s-run-limit", SessionStatus.FAILED)
    assert record.history[-1]["payload"] == {
        "code": "runtime-run-timeout",
        "retryable": True,
    }


def test_delegate_notifications_track_subagent_lifetime_without_exposing_raw_names(
    adapter: RuntimeAdapter,
) -> None:
    adapter.create_session("s-child-events", "t-child-events")
    adapter.submit_prompt("s-child-events", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("s-child-events")
    run = record.active_run
    assert run is not None

    adapter._on_notification(record, Notification(
        method="session.event",
        payload={
            "sessionId": record.runtime_session_id,
            "event": {"type": "tool/call", "data": {
                "callId": "delegate-1", "name": "byq_delegate_backtest_analysis",
            }},
        },
    ))
    assert set(run.active_subagent_calls) == {"delegate-1"}

    adapter._on_notification(record, Notification(
        method="session.event",
        payload={
            "sessionId": record.runtime_session_id,
            "event": {"type": "tool/result", "data": {"message": {"content": [{
                "type": "tool-result", "toolCallId": "delegate-1", "content": [],
            }]}}},
        },
    ))
    assert run.active_subagent_calls == {}
    assert "byq_delegate_backtest_analysis" not in str(record.history)
    adapter.cancel_session("s-child-events", "hard")


def test_session_creation_can_continue_a_durable_trace_sequence(adapter: RuntimeAdapter) -> None:
    created = adapter.create_session("s-sequence", "t-sequence", initial_sequence=41)

    record = adapter._get("s-sequence")
    assert created["status"] == SessionStatus.READY
    assert record.history[0]["sequence"] == 42
    assert record.sequence == 42
    assert record.runtime_session_id.startswith("resume-")
    adapter.release_session("s-sequence")


def test_recreated_runtime_uses_private_generation_and_bounded_public_context(
    adapter: RuntimeAdapter,
) -> None:
    FakeHarness.allow_run.set()
    adapter.create_session(
        "s-durable",
        "t-durable",
        initial_sequence=9,
        conversation_context=[
            {"role": "user", "content": "第一轮问题"},
            {"role": "assistant", "content": "第一轮回答"},
        ],
    )

    record = adapter._get("s-durable")
    assert record.runtime_session_id.startswith("resume-")
    assert record.runtime_session_id != record.session_id
    adapter.submit_prompt("s-durable", "第二轮追问")
    wait_for_status(adapter, "s-durable", SessionStatus.IDLE)

    harness = FakeHarness.instances[0]
    assert harness.session_id == record.runtime_session_id
    assert '"role":"user","content":"第一轮问题"' in harness.last_content
    assert '"role":"assistant","content":"第一轮回答"' in harness.last_content
    assert "[CURRENT_USER_MESSAGE]\n第二轮追问" in harness.last_content
    assert record.pending_conversation_context == []
    adapter.release_session("s-durable")


def test_conversation_context_rejects_private_or_unbounded_shapes(adapter: RuntimeAdapter) -> None:
    with pytest.raises(ValueError, match="field set"):
        adapter.create_session(
            "s-private", "t-private", initial_sequence=1,
            conversation_context=[{"role": "user", "content": "问题", "raw_dsh": "no"}],
        )
    with pytest.raises(ValueError, match="character limit"):
        adapter.create_session(
            "s-large", "t-large", initial_sequence=1,
            conversation_context=[{"role": "assistant", "content": "x" * 6_001}],
        )


def test_resume_is_idempotent_after_runtime_recreation(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-ready", "t-ready", initial_sequence=7)

    resumed = adapter.resume_session("s-ready")

    assert resumed["status"] == SessionStatus.READY
    assert resumed["resumed_from_run_id"] is None
    assert len(FakeHarness.instances) == 1
    adapter.release_session("s-ready")


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
    record = adapter._get("s-1")
    assert record.runtime_session_id != "s-1"
    adapter.release_session("s-1")


def test_resume_private_id_remains_valid_for_maximum_public_id(adapter: RuntimeAdapter) -> None:
    public_session_id = "s" * MAX_IDENTIFIER_LENGTH
    adapter.create_session(public_session_id, "t-1")
    adapter.submit_prompt(public_session_id, "running")
    assert FakeHarness.run_started.wait(timeout=1.0)

    adapter.cancel_session(public_session_id, "hard")
    resumed = adapter.resume_session(public_session_id)

    record = adapter._get(public_session_id)
    assert resumed["status"] == SessionStatus.READY
    assert len(record.runtime_session_id) <= MAX_IDENTIFIER_LENGTH
    assert record.runtime_session_id != public_session_id
    adapter.release_session(public_session_id)


def test_error_finish_reason_is_failed_and_can_resume_with_fresh_runtime(adapter: RuntimeAdapter) -> None:
    FakeHarness.finish_reason = "error"
    FakeHarness.allow_run.set()
    adapter.create_session("s-1", "t-1")
    adapter.submit_prompt("s-1", "fails")
    wait_for_status(adapter, "s-1", SessionStatus.FAILED)

    record = adapter._get("s-1")
    assert record.history[-1]["kind"] == "session.failed"
    assert record.history[-1]["payload"] == {
        "code": "model-run-failed",
        "retryable": True,
    }
    assert "error" not in str(record.history[-1]["payload"]).lower()

    previous_runtime_session_id = record.runtime_session_id
    resumed = adapter.resume_session("s-1")
    assert resumed["status"] == SessionStatus.READY
    assert record.runtime_session_id != previous_runtime_session_id
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


@pytest.mark.parametrize("provider", [
    "opencode-go-responses",
    "opencode-go-chat",
    "opencode-go-messages",
    "opencode-zen-responses",
    "opencode-zen-chat",
    "opencode-zen-messages",
])
def test_opencode_personal_key_is_scoped_to_each_reviewed_runtime_route(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider: str,
) -> None:
    FakeHarness.reset()
    monkeypatch.setattr(runtime_module, "DeepSeekHarness", FakeHarness)
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(tmp_path / "composition.yml"))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    adapter = RuntimeAdapter()
    harness = adapter._build_harness(
        "s-1",
        tmp_path / "sessions" / "s-1",
        trace_id="t-1",
        owner_principal="alice",
        workspace_id="workspace_alice",
        model_resolution={
            "provider": provider,
            "model": "catalog-model",
            "api_key": "opencode-personal-secret",
        },
    )

    assert harness.config.provider == provider
    assert harness.config.env["OPENCODE_API_KEY"] == "opencode-personal-secret"
    assert "DEEPSEEK_API_KEY" not in harness.config.env
    assert "opencode-personal-secret" not in str(adapter.readiness())


def test_unreviewed_runtime_provider_cannot_receive_a_personal_key(
    adapter: RuntimeAdapter,
    tmp_path: Path,
) -> None:
    with pytest.raises(ModelCredentialUnavailable, match="provider is unavailable"):
        adapter._build_harness(
            "s-1",
            tmp_path / "sessions" / "s-1",
            trace_id="t-1",
            owner_principal="alice",
            workspace_id="workspace_alice",
            model_resolution={
                "provider": "browser-controlled-provider",
                "model": "arbitrary-model",
                "api_key": "must-not-enter-child-env",
            },
        )


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
    adapter.create_session("s-1", "t-1", "alice", "workspace_alice")
    sdk_environment = FakeHarness.instances[0].config.env
    assert sdk_environment["BYQ_WORKSPACE_ID"] == "workspace_alice"
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
