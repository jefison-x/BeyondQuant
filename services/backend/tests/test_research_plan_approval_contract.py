"""Pure contracts for direct BYQ approval to execution-plan transitions."""

from packages.contracts.research_plan_approval import (
    apply_approval_decision,
    bind_command_digest,
    plan_command_digest,
    plan_command_idempotency_key,
)
from packages.contracts.research_execution_plan import plan_at_stage


TASK = "task_" + "a" * 32
STRATEGY = "artifact_" + "d" * 32


def _plan():
    return plan_at_stage(
        task_id=TASK, owner_principal="contract-owner", workspace_id="workspace-contract",
        conversation_id="conversation-contract", task_version=3,
        stage="waiting_for_strategy_approval", idempotency_key="contract-plan",
        references={"strategy_version": {"strategy_version": STRATEGY}},
        approval={
            "action": "strategy_approve", "resource_kind": "strategy_version",
            "resource_id": STRATEGY, "plan_version": 1, "task_version": 3,
        },
    )


def test_approval_contract_derives_exact_transition_without_an_event_envelope():
    plan = bind_command_digest(_plan())
    digest = plan_command_digest(
        plan, action="strategy_approve", resource_kind="strategy_version", resource_id=STRATEGY)
    key = plan_command_idempotency_key(
        plan, action="strategy_approve", resource_kind="strategy_version", resource_id=STRATEGY)
    outcome = apply_approval_decision(
        plan, decision="approved", action="strategy_approve",
        resource_kind="strategy_version", resource_id=STRATEGY, params_digest=digest)
    assert outcome["outcome"] == "advance"
    assert outcome["next_stage"] == "waiting_for_task_create_approval"
    assert outcome["approval"]["action"] == "backtest_task_create"
    assert key.startswith("plancmd_")


def test_rejection_is_terminal_for_the_exact_gate_and_mismatch_fails_closed():
    plan = bind_command_digest(_plan())
    digest = plan_command_digest(
        plan, action="strategy_approve", resource_kind="strategy_version", resource_id=STRATEGY)
    rejected = apply_approval_decision(
        plan, decision="rejected", action="strategy_approve",
        resource_kind="strategy_version", resource_id=STRATEGY, params_digest=digest)
    assert rejected["outcome"] == "applied" and rejected["next_stage"] == plan["stage"]
    mismatch = apply_approval_decision(
        plan, decision="approved", action="backtest_execute",
        resource_kind="backtest_task", resource_id="backtesttask_" + "e" * 32,
        params_digest=digest)
    assert mismatch == {"outcome": "needs_attention", "reason": "approval_binding_mismatch"}

