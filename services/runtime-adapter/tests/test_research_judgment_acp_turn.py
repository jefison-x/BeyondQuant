"""Focused, keyless construction of the ADR-0097 judgment runner START."""

from __future__ import annotations

import base64
import json
import secrets

import pytest

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
    "root": {
        "root_run_id": "b" * 32, "runtime_boot_id": "c" * 32,
        "authority_epoch": 7, "dsh_run_id": "byqjudg-" + "2" * 32,
        "owner_principal": "user_synthetic", "workspace_id": "workspace_synthetic",
        "actor_principal": ACTOR, "session_id": SESSION_ID, "trace_id": "trace_synthetic",
    },
}


def _profile(*, limits=None):
    public = {"provider_route": "deepseek-official", "model": "deepseek-v4-flash",
              "limits": limits or {"deadline_at_ms": 4_000_000_000_000}}
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
        build_judgment_root_prompt(BEGIN)


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
