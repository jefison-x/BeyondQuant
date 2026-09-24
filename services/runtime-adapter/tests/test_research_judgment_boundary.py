"""ADR-0085 P4: host-runnable threat reproduction for the judgment boundary.

No carrier, no FastAPI. It proves unauthenticated/forged callers are rejected
before any admission/model turn, and the trusted context is complete.
"""
from __future__ import annotations

import pytest

from app import research_judgment_boundary as boundary

TOKEN = "p4-runtime-service-token"
ENV = {"BYQ_RUNTIME_JUDGMENT_TOKEN": TOKEN}
HEADERS = {
    "x-byq-runtime-judgment-token": TOKEN,
    "x-byq-judgment-attempt": "3:backtest_analysis:1",
    "x-byq-owner-principal": "owner", "x-byq-workspace-id": "workspace",
    "x-byq-actor-principal": "owner", "x-byq-trace-id": "trace",
    "x-byq-session-id": "runtime-session", "x-byq-dsh-run-id": "caller-generation",
}


def test_non_trusted_caller_can_never_pass_the_boundary():
    # No token at all.
    with pytest.raises(boundary.BoundaryError) as missing:
        boundary.require_service_token({}, ENV)
    assert missing.value.status_code == 401
    # Forged token.
    with pytest.raises(boundary.BoundaryError) as forged:
        boundary.require_service_token(
            {"x-byq-runtime-judgment-token": "forged"}, ENV)
    assert forged.value.status_code == 401
    # Disabled entry.
    with pytest.raises(boundary.BoundaryError) as disabled:
        boundary.require_service_token(HEADERS, {})
    assert disabled.value.status_code == 503


def test_authenticated_but_incomplete_context_is_rejected():
    for missing in boundary._TRUSTED_HEADERS:
        broken = {k: v for k, v in HEADERS.items() if k != missing}
        with pytest.raises(boundary.BoundaryError) as error:
            boundary.trusted_context(broken)
        assert error.value.status_code == 401


def test_valid_context_returns_the_trusted_headers():
    identity, trusted = boundary.trusted_context(HEADERS)
    assert identity["owner_principal"] == "owner"
    assert identity["workspace_id"] == "workspace"
    assert trusted["x-byq-session-id"] == "runtime-session"


def test_task_identity_is_exact():
    assert boundary.valid_task_identity("task_" + "a" * 32)
    for bad in ("task_short", "task_" + "a" * 31, "task_" + "a" * 33, None, 5):
        assert not boundary.valid_task_identity(bad)


def test_attempt_binding_is_required_and_exact():
    for bad in ({}, {"x-byq-judgment-attempt": ""},
                {"x-byq-judgment-attempt": "3:backtest_analysis"},
                {"x-byq-judgment-attempt": "plan_version:stage:iteration"},
                {"x-byq-judgment-attempt": "3:Backtest:1"}):
        with pytest.raises(boundary.BoundaryError) as error:
            boundary.require_attempt(bad)
        assert error.value.status_code == 422
    assert boundary.require_attempt({"x-byq-judgment-attempt": "3:backtest_analysis:1"}) \
        == "3:backtest_analysis:1"


def test_call_identity_is_retry_stable_and_attempt_scoped():
    task = "task_" + "a" * 32
    first = boundary.derive_call_identity(task, "3:backtest_analysis:1")
    # A retry of the SAME authoritative attempt reuses the SAME durable identity.
    assert boundary.derive_call_identity(task, "3:backtest_analysis:1") == first
    # A legitimate new stage/plan revision/iteration gets a NEW identity.
    for other in ("4:backtest_analysis:1", "3:iteration_comparison:1",
                  "3:backtest_analysis:2"):
        assert boundary.derive_call_identity(task, other) != first
    assert boundary.derive_call_identity("task_" + "b" * 32,
                                         "3:backtest_analysis:1") != first
