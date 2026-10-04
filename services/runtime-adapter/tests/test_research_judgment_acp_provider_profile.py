"""A frozen provider choice must come from one fresh exact Backend root."""

from __future__ import annotations

import copy
import time

import pytest

from app.research_judgment_acp_provider_profile import (
    build_provider_profile, require_current_model_resolution,
)
from app.research_judgment_boundary import derive_call_identity


TASK = "task_" + "a" * 32
ATTEMPT = "1:strategy_draft:1"
CALL = derive_call_identity(TASK, ATTEMPT)
BEGIN = {
    "schema_version": "byq-research-judgment-acp-root-receipt.v1",
    "status": "admitted", "created": True, "task_id": TASK,
    "call_identity": CALL, "attempt_binding": ATTEMPT,
    "stage": "strategy_draft", "plan_version": 1, "task_version": 1,
    "iteration": 1, "call_index": 1, "model_call_limit": 2,
    "root": {
        "root_run_id": "b" * 32, "runtime_boot_id": "c" * 32,
        "authority_epoch": 1, "dsh_run_id": "byqjudg-" + "d" * 32,
        "owner_principal": "owner-1", "workspace_id": "workspace-1",
        "session_id": "session-1", "trace_id": "trace-1",
        "actor_principal": "byq-product-agent-session-1",
    },
}
RESOLUTION = {
    "source": "environment", "provider": "deepseek-official",
    "model": "selected-model", "api_key": "synthetic-upstream-secret",
}


def select(begin=BEGIN, resolution=RESOLUTION, *, started_at_ms=None):
    if started_at_ms is None:
        started_at_ms = int(time.time() * 1000)
    return build_provider_profile(
        begin, resolution, request_started_at_ms=started_at_ms)


def test_fresh_root_selection_is_nonsecret_and_uses_closed_stage_profile():
    before = int(time.time() * 1000)
    selection = select(started_at_ms=before)
    after = int(time.time() * 1000)
    public = selection.public
    assert public["call_identity"] == CALL
    assert public["root_run_id"] == "b" * 32
    assert public["actor_principal"] == "byq-product-agent-session-1"
    assert public["provider_route"] == "deepseek-official"
    assert public["budget_profile_id"] == "strategy-draft-bounded.v1"
    assert {key: value for key, value in public["limits"].items()
            if key != "deadline_at_ms"} == {
        "max_calls": 3, "max_input_bytes": 131072,
        "max_total_input_bytes": 131072,
        "max_output_tokens": 8192, "max_total_output_tokens": 8192,
        "max_tool_payload_bytes": 65536,
        "max_total_tool_payload_bytes": 65536,
    }
    assert before + 180000 <= public["limits"]["deadline_at_ms"] <= after + 180000
    assert selection.upstream_credential == "synthetic-upstream-secret"
    assert "synthetic-upstream-secret" not in repr(selection)
    assert "synthetic-upstream-secret" not in str(public)
    public["limits"]["max_calls"] = 99
    assert selection.public["limits"]["max_calls"] == 3


def test_admission_setup_time_consumes_the_same_provider_deadline():
    started_at_ms = int(time.time() * 1000) - 10_000
    profile = select(started_at_ms=started_at_ms).public
    assert profile["limits"]["deadline_at_ms"] == started_at_ms + 180_000
    with pytest.raises(ValueError, match="deadline expired"):
        select(started_at_ms=started_at_ms - 180_000)
    with pytest.raises(ValueError, match="start time"):
        select(started_at_ms=int(time.time() * 1000) + 10_000)
    with pytest.raises(ValueError, match="start time"):
        select(started_at_ms=True)


@pytest.mark.parametrize("changed", [
    {"created": False},
    {"call_identity": "byq-judgment-" + "f" * 32},
    {"stage": "deterministic_stage"},
    {"call_index": 3},
    {"model_call_limit": 3},
    {"root": {**BEGIN["root"], "runtime_boot_id": "wrong"}},
    {"root": {**BEGIN["root"], "actor_principal": "other"}},
])
def test_replay_wrong_root_or_stage_cannot_select_provider(changed):
    begin = copy.deepcopy(BEGIN)
    begin.update(changed)
    with pytest.raises(ValueError):
        select(begin)


def test_user_binding_requires_nonsecret_credential_versions():
    user = {**RESOLUTION, "source": "user_binding", "provider": "opencode-go-chat"}
    with pytest.raises(ValueError, match="stable nonsecret version"):
        select(resolution=user)
    user.update({"profile_id": "profile_" + "1" * 32, "profile_version": 2,
                 "credential_id": "cred_" + "2" * 32, "credential_version": 3,
                 "binding_version": 4})
    profile = select(resolution=user).public
    assert profile["credential_reference"] == {
        "source": "user_binding", "profile_id": "profile_" + "1" * 32,
        "profile_version": 2,
        "credential_id": "cred_" + "2" * 32, "credential_version": 3,
        "binding_version": 4,
    }
    assert profile["provider_route"] == "opencode-go-chat"


def test_unselected_route_cannot_open_provider_profile():
    with pytest.raises(ValueError):
        select(resolution={**RESOLUTION, "provider": "opencode-unknown"})


def test_pre_dispatch_model_selection_must_match_frozen_profile():
    profile = select()
    require_current_model_resolution(profile, RESOLUTION)
    for changed in ({"provider": "opencode-go-chat"},
                    {"model": "different"},
                    {"api_key": "rotated-secret"},
                    {"source": "user_binding"},
                    {"api_key": ""}):
        with pytest.raises(ValueError, match="binding changed"):
            require_current_model_resolution(profile, {**RESOLUTION, **changed})
    user = {**RESOLUTION, "source": "user_binding",
            "profile_id": "profile_" + "1" * 32, "profile_version": 2,
            "credential_id": "cred_" + "2" * 32,
            "credential_version": 3, "binding_version": 4}
    user_profile = select(resolution=user)
    require_current_model_resolution(user_profile, user)
    for changed in ({"profile_version": 3}, {"credential_version": 4},
                    {"binding_version": 5}, {"credential_id": "cred_" + "3" * 32},
                    {"profile_id": "profile_" + "4" * 32},
                    {"source": "environment"}):
        with pytest.raises(ValueError, match="binding changed"):
            require_current_model_resolution(user_profile, {**user, **changed})
    with pytest.raises(ValueError, match="current trusted"):
        require_current_model_resolution(user_profile, None)
