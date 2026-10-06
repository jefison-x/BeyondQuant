"""Focused, keyless construction of the ADR-0097 judgment runner START."""

from __future__ import annotations

import base64
import json
import secrets
import threading
from pathlib import Path

import pytest

import app.research_judgment_acp_turn as turn

from app.research_judgment import ResearchJudgmentError
from app.research_judgment_acp_identity_key import derive_judgment_root_signing_key
from app.research_judgment_acp_provider_profile import AcpJudgmentProviderProfile
from app.research_judgment_acp_runner_client import (
    _validate_environment,
    scope_digest,
)
from app.research_judgment_acp_turn import (
    DEFAULT_JUDGMENT_SESSION_ROOT,
    build_judgment_root_prompt,
    build_judgment_runner_start,
    judgment_expected_cwd,
    judgment_proxy_token_env,
    judgment_runner_environment,
    judgment_runner_overlay_b64,
    judgment_runner_scope,
)
from app.research_judgment_boundary import derive_call_identity

TASK = "task_" + "a" * 32
ATTEMPT = "1:strategy_draft:1"
CALL = derive_call_identity(TASK, ATTEMPT)
MASTER = "m" * 48
SESSION_ID = "byqjdg-" + "1" * 32
ACTOR = "byq-product-agent-" + SESSION_ID
PROXY_TOKEN = "byq-acp-proxy-" + secrets.token_urlsafe(32)
PROXY_BASE = "http://127.0.0.1:43117/anthropic"

BEGIN = {
    "schema_version": "byq-research-judgment-acp-root-receipt.v1",
    "status": "admitted", "task_id": TASK, "call_identity": CALL,
    "attempt_binding": ATTEMPT,
    "stage_input": {"allowed_tools": ["byq_agent_context", "byq_research_get"]},
    "root": {
        "root_run_id": "b" * 32, "runtime_boot_id": "c" * 32,
        "authority_epoch": 7, "dsh_run_id": "byqjudg-" + "2" * 32,
        "owner_principal": "user_synthetic", "workspace_id": "workspace_synthetic",
        "actor_principal": ACTOR, "session_id": SESSION_ID, "trace_id": "trace_synthetic",
    },
}


def _profile(*, limits=None):
    public = {"provider_route": "deepseek-official", "model": "deepseek-v4-flash",
              "limits": limits or {"deadline_at_ms": 4_000_000_000_000,
                                   "max_output_tokens": 8192}}
    return AcpJudgmentProviderProfile(
        json.dumps(public, sort_keys=True).encode(), "upstream-secret")


def test_root_prompt_names_only_the_stage_allowed_tools():
    begin = {**BEGIN, "stage_input": {
        "allowed_tools": ["byq_agent_context", "byq_research_get"]}}
    prompt = build_judgment_root_prompt(begin)
    assert "`byq_agent_context`" in prompt and "`byq_research_get`" in prompt
    assert "Do not create any subagent" in prompt
    assert '"durable_evidence": {"kind": "none"}' in prompt
    with pytest.raises(ResearchJudgmentError, match="allowed tools"):
        build_judgment_root_prompt({k: v for k, v in BEGIN.items() if k != "stage_input"})


def test_scope_is_exactly_the_six_runner_fields_and_digests():
    scope = judgment_runner_scope(BEGIN)
    assert set(scope) == {"task_id", "call_identity", "attempt_binding",
                          "root_run_id", "runtime_boot_id", "authority_epoch"}
    assert scope["root_run_id"] == BEGIN["root"]["root_run_id"]
    assert len(scope_digest(scope)) == 64


def test_environment_is_allowlisted_and_identity_matches_scope():
    env = judgment_runner_environment(
        BEGIN, mcp_url="http://mcp:8000", mcp_product_url="http://mcp-product:8000",
        signing_master=MASTER)
    assert env["BYQ_MCP_ACP_IDENTITY_MODE"] == "research-judgment-root-v1"
    assert env["BYQ_MCP_ACP_JUDGMENT_TASK_ID"] == TASK
    assert env["BYQ_MCP_ACP_JUDGMENT_CALL_IDENTITY"] == CALL
    assert env["BYQ_ROOT_RUN_ID"] == BEGIN["root"]["root_run_id"]
    assert env["BYQ_RUNTIME_BOOT_ID"] == BEGIN["root"]["runtime_boot_id"]
    assert env["BYQ_ACTOR_PRINCIPAL"] == ACTOR
    expected_key = derive_judgment_root_signing_key(MASTER, {
        **judgment_runner_scope(BEGIN),
        "owner_principal": BEGIN["root"]["owner_principal"],
        "workspace_id": BEGIN["root"]["workspace_id"],
        "session_id": SESSION_ID, "trace_id": "trace_synthetic",
        "dsh_run_id": BEGIN["root"]["dsh_run_id"],
    })
    assert env["BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY"] == expected_key
    # The runner client accepts exactly this environment for the same scope/token.
    _validate_environment(env, judgment_runner_scope(BEGIN), "DEEPSEEK_API_KEY",
                          PROXY_TOKEN)


def test_environment_rejects_a_non_admitted_or_deranged_root():
    with pytest.raises(ResearchJudgmentError, match="admitted"):
        judgment_runner_environment({**BEGIN, "status": "agent_bound"},
                                    mcp_url="http://mcp", mcp_product_url="http://p",
                                    signing_master=MASTER)
    with pytest.raises(ResearchJudgmentError, match="differs from its attempt"):
        judgment_runner_environment(
            {**BEGIN, "call_identity": "byq-judgment-" + "0" * 32},
            mcp_url="http://mcp", mcp_product_url="http://p", signing_master=MASTER)


def test_proxy_token_env_is_single_provider_credential():
    assert judgment_proxy_token_env("deepseek-official") == "DEEPSEEK_API_KEY"
    assert judgment_proxy_token_env("opencode-go-chat") == "OPENCODE_API_KEY"
    assert judgment_proxy_token_env("opencode-zen-messages") == "OPENCODE_API_KEY"
    with pytest.raises(ResearchJudgmentError, match="unknown"):
        judgment_proxy_token_env("openai-direct")


def test_overlay_is_the_single_selected_route_bound_to_the_proxy():
    encoded = judgment_runner_overlay_b64(_profile(), proxy_base_url=PROXY_BASE)
    overlay = json.loads(base64.b64decode(encoded))
    assert isinstance(overlay, list) and overlay
    deepseek = next(item for item in overlay if item["id"] == "llm-deepseek")
    assert deepseek["config"]["baseURL"] == PROXY_BASE
    assert deepseek["config"]["retryPolicy"] == {"mode": "normal", "maxRetries": 0}
    assert deepseek["config"]["apiKeyEnv"] == "DEEPSEEK_API_KEY"
    assert {"id": "llm-pi-ai", "disabled": True} in overlay


def test_expected_cwd_is_the_scope_digest_leaf():
    scope = judgment_runner_scope(BEGIN)
    assert judgment_expected_cwd(scope) == \
        f"{DEFAULT_JUDGMENT_SESSION_ROOT}/{scope_digest(scope)}"


def test_build_start_assembles_all_inputs_and_rejects_bad_token():
    start = build_judgment_runner_start(
        BEGIN, _profile(), mcp_url="http://mcp:8000",
        mcp_product_url="http://mcp-product:8000", signing_master=MASTER,
        proxy_base_url=PROXY_BASE, proxy_token=PROXY_TOKEN)
    assert start.proxy_token_env == "DEEPSEEK_API_KEY"
    assert start.deadline_at_ms == 4_000_000_000_000
    assert start.expected_cwd == judgment_expected_cwd(start.scope)
    assert start.environment["BYQ_MCP_ACP_JUDGMENT_CALL_IDENTITY"] == CALL
    with pytest.raises(ResearchJudgmentError, match="local ACP provider token"):
        build_judgment_runner_start(
            BEGIN, _profile(), mcp_url="http://mcp", mcp_product_url="http://p",
            signing_master=MASTER, proxy_base_url=PROXY_BASE, proxy_token="not-a-token")


NATIVE = "00000000-0000-4000-8000-000000000001"
BINDING = {"schema_version": "byq-acp-agent-bind-receipt.v1", "status": "bound",
           "root_run_id": "b" * 32, "runtime_boot_id": "c" * 32,
           "native_agent_session_id": NATIVE, "native_parent_session_id": None,
           "origin": "root", "depth": 0, "agent_run_id": "agent_run_" + "e" * 32}
PROFILE_PUBLIC = {"provider_route": "deepseek-official", "model": "deepseek-v4-flash",
                  "limits": {"deadline_at_ms": 4_000_000_000_000}}


class _FakeJournal:
    def __init__(self, path):
        self.path = path
        self.calls = []
        self.phase = None
        self.binding = None
        self.begin = None

    def record_request_start(self, ms):
        self.calls.append("request_start")

    def record_begin(self, begin):
        self.calls.append("begin")
        self.phase = "begun"
        self.begin = begin

    def record_provider_profile(self, profile):
        self.calls.append("provider_profile")

    def record_binding(self, binding):
        self.calls.append("binding")
        self.phase = "bound"
        self.binding = binding

    def mark_prompt_may_dispatch(self):
        self.calls.append("mark")
        self.phase = "prompt_may_have_dispatched"

    def record_result_request(self, request):
        self.calls.append("result_request")
        self.phase = "result_prepared"

    def record_result_receipt(self, receipt):
        self.calls.append("result_receipt")

    def record_terminal_receipt(self, receipt):
        self.calls.append("terminal_receipt")
        self.phase = "terminal_closed"

    def snapshot(self):
        return {"phase": self.phase, "binding": self.binding, "begin": self.begin}


class _FakeProxy:
    base_url = PROXY_BASE
    local_credential = PROXY_TOKEN

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeOutput:
    def __init__(self, result):
        self._result = result

    def result(self, finish_reason):
        if self._result is None:
            raise ResearchJudgmentError("no result")
        return self._result


class _FakeAcp:
    def __init__(self, *, finish="completed", result=None, fail_open=False,
                 fail_prompt=False, fail_close=False):
        self.finish = finish
        self._result = result
        self.fail_open = fail_open
        self.fail_prompt = fail_prompt
        self.fail_close = fail_close
        self.closed = False

    def open(self, start):
        if self.fail_open:
            raise RuntimeError("synthetic open failure")
        return NATIVE, "transport"

    def prompt(self, transport, native, prompt, *, cancel_event=None):
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("synthetic cancellation")
        if self.fail_prompt:
            raise RuntimeError("synthetic prompt failure")
        return self.finish, _FakeOutput(self._result)

    def close(self, transport):
        self.closed = True
        return None if self.fail_close else "sha256:" + "f" * 64


def _run(tmp_path, monkeypatch, *, acp, fail_register=False, journal=None,
         cancel_intent_receipt=None, captured=None, cancel_event=None):
    if journal is None:
        journal = _FakeJournal(tmp_path / "journal.json")
    journal.path.write_text("{}")
    monkeypatch.setattr(turn, "build_provider_profile", lambda *a, **k: _profile())
    monkeypatch.setattr(turn._control, "begin_root_once",
                        lambda **k: {**BEGIN, "created": True})
    if fail_register:
        def _boom(**k):
            raise RuntimeError("synthetic register failure")
        monkeypatch.setattr(turn._control, "register_root_agent_once", _boom)
    else:
        monkeypatch.setattr(turn._control, "register_root_agent_once", lambda **k: BINDING)
    monkeypatch.setattr(turn._control, "result_request",
                        lambda *a, **k: {"sentinel": "result-request"})
    monkeypatch.setattr(turn._control, "submit_result_once",
                        lambda **k: {"schema_version": "research-judgment-result-receipt.v1"})
    monkeypatch.setattr(turn._control, "close_result_root_once",
                        lambda **k: {"schema_version": "agent-run-lifecycle-receipt.v1"})
    if captured is not None:
        def _settlement_request(*a, **k):
            captured.append(k)
            return {"sentinel": "settlement-request"}
        monkeypatch.setattr(turn._control, "settlement_request", _settlement_request)
    else:
        monkeypatch.setattr(turn._control, "settlement_request",
                            lambda *a, **k: {"sentinel": "settlement-request"})
    monkeypatch.setattr(turn._control, "submit_settlement_once",
                        lambda **k: {"schema_version": "byq-research-judgment-acp-settlement-receipt.v1"})
    monkeypatch.setattr(turn._control, "close_settled_root_once",
                        lambda **k: {"schema_version": "agent-run-lifecycle-receipt.v1"})
    return turn.run_judgment_acp_root(
        task_id=TASK, call_identity=CALL, attempt=ATTEMPT, journal=journal,
        resolution={"source": "environment", "model": "deepseek-v4-flash", "api_key": "k"},
        backend_url="http://backend", trusted_headers={}, proxy_factory=lambda *_: _FakeProxy(),
        acp=acp, mcp_url="http://mcp", mcp_product_url="http://mp",
        signing_master=MASTER, now_ms=1_000, timeout=1.0,
        cancel_intent_receipt=cancel_intent_receipt, cancel_event=cancel_event), journal


def test_orchestrator_commits_completed_result_in_exact_order(tmp_path, monkeypatch):
    outcome, journal = _run(tmp_path, monkeypatch, acp=_FakeAcp(
        finish="completed", result={"proposal": None, "durable_evidence": {"kind": "none"}}))
    assert outcome["status"] == "completed"
    assert journal.calls == ["request_start", "begin", "provider_profile", "binding",
                             "mark", "result_request", "result_receipt", "terminal_receipt"]
    assert journal.phase == "terminal_closed"


def test_orchestrator_settles_never_dispatched_when_registration_fails(tmp_path, monkeypatch):
    journal = _FakeJournal(tmp_path / "journal.json")
    with pytest.raises(RuntimeError, match="register failure"):
        _run(tmp_path, monkeypatch, acp=_FakeAcp(), fail_register=True, journal=journal)
    # registration failed before the prompt fence; the journal never advanced to mark
    assert "mark" not in journal.calls
    assert journal.phase == "begun"


def test_orchestrator_settles_outcome_unknown_when_prompt_fails_after_mark(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="prompt failure"):
        _run(tmp_path, monkeypatch, acp=_FakeAcp(fail_prompt=True))


def test_orchestrator_settles_cancelled_after_dispatch_with_owner_receipt(tmp_path, monkeypatch):
    captured = []
    with pytest.raises(RuntimeError, match="prompt failure"):
        _run(tmp_path, monkeypatch, acp=_FakeAcp(fail_prompt=True),
             cancel_intent_receipt={"intent_id": "byqcancel-" + "a" * 32},
             captured=captured)
    assert captured and captured[0]["settlement_kind"] == "cancelled_after_dispatch"
    assert captured[0]["terminal_outcome"] == "cancelled"


def test_orchestrator_reads_the_owner_cancel_receipt_from_status(tmp_path, monkeypatch):
    captured = []
    receipt = {"schema_version": "byq-research-judgment-acp-cancel-intent-receipt.v1",
               "intent_id": "byqcancel-" + "a" * 32}
    monkeypatch.setattr(turn._control, "exact_status",
                        lambda **k: {"cancellation_intent_receipt": receipt})
    with pytest.raises(RuntimeError, match="prompt failure"):
        _run(tmp_path, monkeypatch, acp=_FakeAcp(fail_prompt=True), captured=captured)
    assert captured and captured[0]["settlement_kind"] == "cancelled_after_dispatch"


def test_orchestrator_refuses_cancel_without_a_proven_process_fence(tmp_path, monkeypatch):
    captured = []
    with pytest.raises(turn.AcpJudgmentOutcomeUnknown, match="proven process fence"):
        _run(tmp_path, monkeypatch, acp=_FakeAcp(fail_prompt=True, fail_close=True),
             cancel_intent_receipt={"intent_id": "byqcancel-" + "a" * 32},
             captured=captured)
    assert captured == []


def test_cancel_event_aborts_the_live_turn_and_settles_unknown(tmp_path, monkeypatch):
    event = threading.Event()
    event.set()
    captured = []
    with pytest.raises(RuntimeError, match="synthetic cancellation"):
        _run(tmp_path, monkeypatch, acp=_FakeAcp(), cancel_event=event, captured=captured)
    assert captured and captured[0]["settlement_kind"] == "outcome_unknown"


def _recovery_journal(tmp_path, phase, begin=None):
    journal = _FakeJournal(tmp_path / "journal.json")
    journal.path.write_text("{}")
    journal.phase = phase
    journal.begin = begin
    return journal


def test_recover_settles_outcome_unknown_without_replay(tmp_path, monkeypatch):
    journal = _recovery_journal(tmp_path, "prompt_may_have_dispatched", BEGIN)
    captured = []
    monkeypatch.setattr(turn._control, "exact_status", lambda **k: {})
    monkeypatch.setattr(turn._control, "settlement_request",
                        lambda *a, **k: captured.append(k) or {"sentinel": "settlement"})
    monkeypatch.setattr(turn._control, "submit_settlement_once", lambda **k: {"sentinel": "sub"})
    monkeypatch.setattr(turn._control, "close_settled_root_once", lambda **k: {"sentinel": "close"})
    out = turn.recover_judgment_acp_root(
        journal=journal, backend_url="http://backend", task_id=TASK, trusted_headers={})
    assert out["status"] == "settled" and out["settlement_kind"] == "outcome_unknown"
    assert captured[0]["settlement_kind"] == "outcome_unknown"
    assert "mark" not in journal.calls  # never re-dispatches a prompt


def test_recover_is_a_noop_for_an_absent_journal(tmp_path):
    journal = _recovery_journal(tmp_path, None)
    journal.snapshot = lambda: None
    assert turn.recover_judgment_acp_root(
        journal=journal, backend_url="http://backend", task_id=TASK,
        trusted_headers={})["status"] == "none"


def test_recover_is_a_noop_for_an_unprepared_journal(tmp_path):
    journal = _recovery_journal(tmp_path, "prepared", BEGIN)
    assert turn.recover_judgment_acp_root(
        journal=journal, backend_url="http://backend", task_id=TASK,
        trusted_headers={})["status"] == "not_dispatched"


def test_recover_refuses_a_result_prepared_root(tmp_path):
    journal = _recovery_journal(tmp_path, "result_prepared", BEGIN)
    with pytest.raises(turn.AcpJudgmentOutcomeUnknown, match="exact Backend reconciliation"):
        turn.recover_judgment_acp_root(
            journal=journal, backend_url="http://backend", task_id=TASK, trusted_headers={})
