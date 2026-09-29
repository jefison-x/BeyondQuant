"""Approval-policy levels for the existing BYQ Agent tool surface.

A policy level classifies the kind of operation. It does not grant the
operation: role authorization, existing approval-required declarations, and
domain-specific Artifact/plan checks remain independent gates.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Literal

ApprovalLevel = Literal["AUTO", "DECISION", "ACTION"]

# These tools request or record an explicit user choice.
_DECISION_TOOLS = frozenset({
    "byq_agent_approval_decide",
    "byq_agent_approval_request",
})

# Consequential writes retain explicit action-level review.
_ACTION_TOOLS = frozenset({
    "byq_backtest_task_cancel",
    "byq_feedback_submit",
    "byq_ml_strategy_approve",
    "byq_ml_training_cancel",
    "byq_strategy_approve",
})


def approval_level_for_tool(
    tool_name: object, *, known_tools: Collection[str],
) -> ApprovalLevel:
    """Classify a registered Agent tool; unknown names fail closed.

    AUTO describes authorized research and compute. It does not override an
    existing approval_required role declaration or a domain grant such as a
    typed strategy Artifact or plan-bound ResearchTask approval.
    """
    if not isinstance(tool_name, str) or tool_name not in known_tools:
        raise ValueError("unknown Agent tool has no approval policy")
    if tool_name in _ACTION_TOOLS:
        return "ACTION"
    if tool_name in _DECISION_TOOLS:
        return "DECISION"
    return "AUTO"
