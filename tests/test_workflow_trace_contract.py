from __future__ import annotations

from copy import deepcopy
import unittest

from packages.contracts.workflow_trace import validate_workflow_trace_event


def event(kind: str, payload: dict[str, object], *, source: str = "runtime-adapter") -> dict[str, object]:
    return {
        "trace_id": "byq-trace-1",
        "session_id": "byq-session-1",
        "sequence": 1,
        "timestamp": "2026-08-22T00:00:00+00:00",
        "kind": kind,
        "source": source,
        "payload": payload,
    }


def common(**extra: object) -> dict[str, object]:
    return {
        "schema_version": "workflow-card.v1",
        "card_id": f"card_{'a' * 32}",
        "revision": 1,
        "authority": "proposal",
        "title": "候选卡片",
        "truncated": False,
        **extra,
    }


class WorkflowTraceProjectionTests(unittest.TestCase):
    def test_proposal_cards_accept_only_exact_bounded_shapes(self) -> None:
        cases = [
            (
                "agent.card.strategy_draft",
                common(name="动量策略", summary="验证 20 日突破假设", validation_status="draft"),
            ),
            (
                "agent.card.stock_candidates",
                common(items=[{"symbol": "600000.SH", "name": "浦发银行", "reason": "候选"}]),
            ),
            (
                "agent.card.optimization",
                common(
                    objective="降低回撤",
                    changes=[{"area": "止损", "before": "无", "after": "8%", "reason": "限制尾部风险"}],
                    metrics={"max_drawdown": -0.12},
                ),
            ),
        ]
        for kind, payload in cases:
            with self.subTest(kind=kind):
                self.assertEqual(validate_workflow_trace_event(event(kind, payload))["payload"], payload)
                invalid = deepcopy(payload)
                invalid["raw_tool_result"] = {"secret_token": "forbidden"}
                with self.assertRaises(ValueError):
                    validate_workflow_trace_event(event(kind, invalid))

    def test_domain_cards_require_gateway_authority(self) -> None:
        payload = common(
            authority="domain",
            title="回测上下文",
            job_id=f"backtest_{'b' * 32}",
            status="completed",
            metrics={"total_return": 0.15, "trade_count": 8},
        )
        with self.assertRaisesRegex(ValueError, "byq-domain"):
            validate_workflow_trace_event(event("agent.card.backtest_context", payload))
        self.assertEqual(
            validate_workflow_trace_event(
                event("agent.card.backtest_context", payload, source="byq-domain")
            )["source"],
            "byq-domain",
        )

    def test_approval_status_and_execution_outcome_stay_separate(self) -> None:
        payload = common(
            authority="domain",
            title="人工审批",
            approval_id=f"agent_approval_{'c' * 32}",
            action="byq_backtest_task_execute",
            status="approved",
            execution_outcome="authorized",
        )
        validate_workflow_trace_event(event("agent.card.approval", payload, source="byq-domain"))
        payload["status"] = "executed"
        with self.assertRaisesRegex(ValueError, "status"):
            validate_workflow_trace_event(event("agent.card.approval", payload, source="byq-domain"))

    def test_public_answer_is_bounded_and_reasoning_fields_are_rejected(self) -> None:
        payload = {
            "schema_version": "workflow-answer.v1",
            "channel": "answer",
            "delta": "公开回答",
            "truncated": False,
        }
        validate_workflow_trace_event(event("agent.output.delta", payload))
        payload["reasoning"] = "hidden"
        with self.assertRaises(ValueError):
            validate_workflow_trace_event(event("agent.output.delta", payload))

    def test_activity_is_public_semantic_progress_only(self) -> None:
        payload = {
            "schema_version": "workflow-activity.v1",
            "activity_id": f"activity_{'d' * 32}",
            "phase": "strategy",
            "state": "completed",
            "label": "策略校验完成",
            "agent_label": "量化研究 Agent",
            "plugin_label": "BeyondQuant MCP",
            "skill_label": "策略研究 Skill",
        }
        validate_workflow_trace_event(event("agent.activity", payload))
        payload["arguments"] = {"source": "private"}
        with self.assertRaises(ValueError):
            validate_workflow_trace_event(event("agent.activity", payload))

    def test_non_finite_duplicate_and_oversized_values_fail_closed(self) -> None:
        duplicate = common(items=[{"symbol": "000001.SZ"}, {"symbol": "000001.SZ"}])
        with self.assertRaisesRegex(ValueError, "duplicated"):
            validate_workflow_trace_event(event("agent.card.stock_candidates", duplicate))

        metrics = common(
            objective="提升稳定性",
            changes=[{"area": "仓位", "after": "50%", "reason": "控制风险"}],
            metrics={"sharpe_ratio": float("nan")},
        )
        with self.assertRaises(ValueError):
            validate_workflow_trace_event(event("agent.card.optimization", metrics))

        answer = {
            "schema_version": "workflow-answer.v1",
            "channel": "answer",
            "delta": "中" * 3_000,
            "truncated": False,
        }
        with self.assertRaisesRegex(ValueError, "byte limit"):
            validate_workflow_trace_event(event("agent.output.delta", answer))
