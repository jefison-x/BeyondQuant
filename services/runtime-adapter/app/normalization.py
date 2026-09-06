"""Convert private DSH notifications into bounded BYQ-owned projections."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from .compat.types import RuntimeObservation
from .contracts import (
    MAX_ACTIVITIES_PER_TURN,
    MAX_ANSWER_FRAGMENT_BYTES,
    MAX_CARDS_PER_TURN,
    WORKFLOW_ACTIVITY_VERSION,
    WORKFLOW_ANSWER_VERSION,
    WORKFLOW_CARD_VERSION,
    WorkflowTraceEvent,
    make_workflow_trace_event,
    project_public_answer_text,
    validate_workflow_trace_event,
)


_CAPABILITIES: dict[str, tuple[str, str]] = {
    "byq_product_help_query": ("review", "查询产品使用说明"),
    "byq_delegate_market_research": ("select", "开展市场研究"),
    "byq_delegate_factor_research": ("strategy", "开展因子研究"),
    "byq_delegate_strategy_research": ("strategy", "开展策略研究"),
    "byq_delegate_backtest_analysis": ("backtest", "分析回测证据"),
    "byq_delegate_ml_research": ("strategy", "开展模型研究"),
    "byq_workflow_card_propose": ("strategy", "整理工作台建议"),
    "byq_backtest_submit": ("backtest", "提交回测"),
    "byq_backtest_run": ("backtest", "运行回测"),
    "byq_backtest_get": ("backtest", "读取回测状态"),
    "byq_backtest_analysis_get": ("backtest", "读取回测分析证据"),
    "byq_backtest_cancel": ("backtest", "取消回测"),
    "byq_backtest_task_prepare": ("backtest", "准备回测任务"),
    "byq_backtest_task_create": ("backtest", "创建回测任务"),
    "byq_backtest_task_get": ("backtest", "跟踪回测任务"),
    "byq_backtest_task_execute": ("backtest", "执行回测任务"),
    "byq_backtest_task_cancel": ("backtest", "取消回测任务"),
    "byq_ml_capabilities": ("strategy", "查询模型能力"),
    "byq_ml_workspace_get": ("strategy", "定位模型研究对象"),
    "byq_ml_strategy_create": ("strategy", "创建模型研究策略"),
    "byq_ml_training_create": ("strategy", "创建模型训练任务"),
    "byq_ml_training_get": ("review", "跟踪模型训练任务"),
    "byq_ml_training_cancel": ("review", "取消模型训练任务"),
    "byq_ml_prediction_create": ("strategy", "生成样本外预测与冻结信号"),
    "byq_ml_prediction_get": ("review", "跟踪模型预测任务"),
    "byq_agent_approval_request": ("review", "发起审批"),
    "byq_agent_approval_get": ("review", "读取审批状态"),
    "byq_agent_approval_decide": ("review", "记录审批决定"),
    "byq_market_daily": ("select", "读取市场数据"),
    "byq_market_session_context": ("select", "确认交易日与数据截止"),
    "byq_market_valuation": ("select", "读取估值数据"),
    "byq_market_fundamentals": ("select", "读取基本面数据"),
    "byq_web_evidence_create": ("select", "保存网页研究来源"),
    "web_search": ("select", "检索公开网页"),
    "byq_pool_list": ("select", "读取股票池"),
    "byq_pool_get": ("select", "读取股票池详情"),
    "byq_pool_history": ("select", "读取股票池历史"),
    "byq_pool_create": ("select", "创建股票池"),
    "byq_pool_snapshot_replace": ("select", "更新股票池快照"),
    "byq_pool_lifecycle": ("select", "更新股票池状态"),
    "byq_strategy_draft_save": ("strategy", "保存策略草稿"),
    "byq_strategy_draft_delete": ("strategy", "归档策略草稿"),
    "byq_strategy_validate": ("strategy", "校验策略"),
    "byq_strategy_version_create": ("strategy", "创建策略版本"),
    "byq_strategy_approve": ("review", "审批策略"),
    "byq_strategy_export": ("strategy", "导出策略"),
    "byq_signal_snapshot_get": ("strategy", "读取信号快照"),
    "byq_research_get": ("strategy", "读取研究对象"),
    "byq_research_task_create": ("strategy", "保存研究计划"),
    "byq_research_transition": ("strategy", "推进研究状态"),
    "byq_artifact_create": ("strategy", "保存研究结论"),
    "byq_experiment_create": ("strategy", "记录研究验证"),
    "byq_factor_compute": ("strategy", "计算因子"),
    "byq_experiment_compare": ("review", "比较实验"),
    "byq_paper_account_get": ("review", "读取模拟账户"),
    "byq_paper_account_list": ("review", "读取模拟账户列表"),
    "byq_paper_order_get": ("review", "读取模拟订单"),
    "byq_paper_snapshot_list": ("review", "读取模拟快照"),
    "byq_agent_roles": ("tool", "读取 Agent 角色"),
    "byq_agent_run_start": ("tool", "启动 Agent 运行"),
    "byq_agent_authorize": ("review", "检查动作授权"),
    "byq_agent_audit": ("review", "记录 Agent 审计"),
    "byq_agent_audit_get": ("review", "读取 Agent 审计"),
    "byq_learning_run_start": ("strategy", "启动学习运行"),
    "byq_learning_run_get": ("review", "读取学习运行"),
    "byq_learning_run_review": ("review", "审阅学习运行"),
    "byq_learning_iteration_list": ("review", "读取学习迭代"),
    "byq_learning_iteration_record": ("strategy", "记录学习迭代"),
    "byq_evaluation_signal_create": ("strategy", "创建评估信号"),
    "byq_evaluation_signal_get": ("review", "读取评估信号"),
    "byq_lesson_propose": ("strategy", "提出研究经验"),
    "byq_lesson_get": ("review", "读取研究经验"),
    "byq_lesson_review": ("review", "审阅研究经验"),
}
_INTERNAL_CONTROL_CAPABILITIES = frozenset(
    {
        "byq_agent_context",
        "byq_agent_roles",
        "byq_agent_run_start",
        "byq_agent_authorize",
        "byq_agent_audit",
        "byq_agent_audit_get",
    }
)
_BACKTEST_TOOLS = frozenset(name for name in _CAPABILITIES if name.startswith("byq_backtest_"))
_APPROVAL_TOOLS = frozenset(name for name in _CAPABILITIES if name.startswith("byq_agent_approval_"))
@dataclass(slots=True)
class NormalizationState:
    """Per-session correlation state; counters reset at each DSH turn."""

    tool_names: dict[str, str] = field(default_factory=dict)
    seen_messages: set[str] = field(default_factory=set)
    activity_count: int = 0
    card_count: int = 0
    activity_truncated: bool = False
    card_truncated: bool = False
    turn_activity_id: str | None = None

    def reset_turn(self) -> None:
        self.tool_names.clear()
        self.seen_messages.clear()
        self.activity_count = 0
        self.card_count = 0
        self.activity_truncated = False
        self.card_truncated = False
        self.turn_activity_id = None


def normalize_runtime_observation(
    observation: RuntimeObservation,
    *,
    trace_id: str,
    session_id: str,
    sequence: int,
    state: NormalizationState | None = None,
) -> list[WorkflowTraceEvent]:
    """Project a bounded internal observation into BYQ-owned public events."""

    current = state or NormalizationState()
    if not observation.root_session:
        return []
    if observation.kind == "session.status" and observation.status is not None:
        return [_event(trace_id, session_id, sequence, "session.status", "dsh", {"status": observation.status})]
    if observation.kind == "turn.start":
        current.reset_turn()
        current.turn_activity_id = _stable_id("activity", trace_id, str(sequence), "turn")
        return _bounded_activity(
            current,
            trace_id,
            session_id,
            sequence,
            activity_id=current.turn_activity_id,
            phase="understand",
            activity_state="started",
            label="理解请求",
        )
    if observation.kind == "turn.end":
        safe_reason = observation.terminal_reason or "failed"
        events: list[WorkflowTraceEvent] = []
        if current.turn_activity_id is not None:
            events.extend(
                _bounded_activity(
                    current,
                    trace_id,
                    session_id,
                    sequence,
                    activity_id=current.turn_activity_id,
                    phase="understand",
                    activity_state="completed" if safe_reason == "completed" else "failed",
                    label="理解请求",
                )
            )
        events.append(
            _event(
                trace_id,
                session_id,
                sequence + len(events),
                "turn.completed",
                "dsh",
                {"reason": safe_reason},
            )
        )
        return events
    if observation.kind == "assistant.message":
        return _answer_events(current, observation, trace_id, session_id, sequence)
    if observation.kind == "tool.call":
        return _tool_call_events(current, observation, trace_id, session_id, sequence)
    if observation.kind == "tool.result":
        return _tool_result_events(current, observation, trace_id, session_id, sequence)
    return []


def _answer_events(
    state: NormalizationState,
    observation: RuntimeObservation,
    trace_id: str,
    session_id: str,
    sequence: int,
) -> list[WorkflowTraceEvent]:
    message_id = observation.message_id
    if message_id is not None:
        if message_id in state.seen_messages:
            return []
        state.seen_messages.add(message_id)
    text = observation.answer_text or ""
    if not text:
        return []
    text = project_public_answer_text(text)
    fragments = _split_utf8(text, MAX_ANSWER_FRAGMENT_BYTES)
    return [
        _event(
            trace_id,
            session_id,
            sequence + index,
            "agent.output.delta",
            "runtime-adapter",
            {
                "schema_version": WORKFLOW_ANSWER_VERSION,
                "channel": "answer",
                "delta": fragment,
                "truncated": False,
            },
        )
        for index, fragment in enumerate(fragments)
    ]


def _tool_call_events(
    state: NormalizationState,
    observation: RuntimeObservation,
    trace_id: str,
    session_id: str,
    sequence: int,
) -> list[WorkflowTraceEvent]:
    call_id = observation.call_id
    name = observation.tool_name
    if not isinstance(call_id, str) or not call_id:
        return []
    capability = _canonical_capability(name)
    if capability:
        state.tool_names[call_id] = capability
    if capability is None or capability in _INTERNAL_CONTROL_CAPABILITIES:
        return []
    phase, label = _CAPABILITIES.get(capability or "", ("tool", "调用受控能力"))
    return _bounded_activity(
        state,
        trace_id,
        session_id,
        sequence,
        activity_id=_stable_id("activity", trace_id, call_id),
        phase=phase,
        activity_state="started",
        label=label,
        **_execution_context(capability),
    )


def _tool_result_events(
    state: NormalizationState,
    observation: RuntimeObservation,
    trace_id: str,
    session_id: str,
    sequence: int,
) -> list[WorkflowTraceEvent]:
    call_id = observation.call_id
    if not isinstance(call_id, str):
        return []
    capability = state.tool_names.pop(call_id, None)
    if capability is None or capability in _INTERNAL_CONTROL_CAPABILITIES:
        return []
    phase, label = _CAPABILITIES.get(capability or "", ("tool", "受控能力已返回"))
    failed = observation.tool_failed
    events = _bounded_activity(
        state,
        trace_id,
        session_id,
        sequence,
        activity_id=_stable_id("activity", trace_id, call_id),
        phase=phase,
        activity_state="failed" if failed else "completed",
        label=label,
        **_execution_context(capability),
    )
    if failed or capability is None:
        return events
    result = observation.tool_result
    candidate = _card_candidate(capability, result, trace_id, sequence)
    if candidate is None:
        return events
    if state.card_count >= MAX_CARDS_PER_TURN:
        if not state.card_truncated:
            state.card_truncated = True
            events.append(_progress(trace_id, session_id, sequence + len(events), "card-limit", True))
        return events
    state.card_count += 1
    kind, source, payload = candidate
    card_event = _event(trace_id, session_id, sequence + len(events), kind, source, payload)
    if kind not in {"agent.card.backtest_context", "agent.card.approval"}:
        try:
            validate_workflow_trace_event(card_event)
        except ValueError:
            events.append(_progress(trace_id, session_id, sequence + len(events), "card-rejected"))
            return events
    events.append(card_event)
    return events


def _card_candidate(
    capability: str,
    result: dict[str, Any] | None,
    trace_id: str,
    sequence: int,
) -> tuple[str, str, dict[str, Any]] | None:
    if result is None or result.get("status") != "ok":
        return None
    if capability == "byq_workflow_card_propose":
        candidate = result.get("candidate")
        if not isinstance(candidate, dict):
            return None
        kind = candidate.get("kind")
        body = candidate.get("payload")
        if kind not in {
            "agent.card.strategy_draft",
            "agent.card.stock_candidates",
            "agent.card.optimization",
        } or not isinstance(body, dict):
            return None
        payload = {
            "schema_version": WORKFLOW_CARD_VERSION,
            "card_id": _stable_id("card", trace_id, str(sequence), kind),
            "revision": 1,
            "authority": "proposal",
            "truncated": False,
            **body,
        }
        return kind, "runtime-adapter", payload
    if capability in _BACKTEST_TOOLS:
        resource_key, identifier_key = "job", "job_id"
    elif capability in _APPROVAL_TOOLS:
        resource_key, identifier_key = "approval", "approval_id"
    else:
        return None
    resource = result.get(resource_key)
    identifier = resource.get(identifier_key) if isinstance(resource, dict) else None
    if not isinstance(identifier, str) or not identifier:
        return None
    kind = "agent.card.backtest_context" if capability in _BACKTEST_TOOLS else "agent.card.approval"
    # This is intentionally an internal reference candidate. Gateway replaces
    # every field after an owner-scoped Product/Backend read before persistence.
    return kind, "runtime-adapter", {identifier_key: identifier}


def _bounded_activity(
    state: NormalizationState,
    trace_id: str,
    session_id: str,
    sequence: int,
    *,
    activity_id: str,
    phase: str,
    activity_state: str,
    label: str,
    agent_label: str | None = None,
    plugin_label: str | None = None,
    skill_label: str | None = None,
) -> list[WorkflowTraceEvent]:
    if state.activity_count >= MAX_ACTIVITIES_PER_TURN:
        if state.activity_truncated:
            return []
        state.activity_truncated = True
        return [_progress(trace_id, session_id, sequence, "activity-limit", True)]
    state.activity_count += 1
    payload: dict[str, Any] = {
        "schema_version": WORKFLOW_ACTIVITY_VERSION,
        "activity_id": activity_id,
        "phase": phase,
        "state": activity_state,
        "label": label,
    }
    if agent_label:
        payload["agent_label"] = agent_label
    if plugin_label:
        payload["plugin_label"] = plugin_label
    if skill_label:
        payload["skill_label"] = skill_label
    event = _event(trace_id, session_id, sequence, "agent.activity", "runtime-adapter", payload)
    validate_workflow_trace_event(event)
    return [event]


def _split_utf8(value: str, maximum: int) -> list[str]:
    fragments: list[str] = []
    remaining = value
    while remaining:
        encoded = remaining.encode("utf-8")
        if len(encoded) <= maximum:
            fragments.append(remaining)
            break
        boundary = maximum
        while boundary > 0:
            try:
                fragment = encoded[:boundary].decode("utf-8")
                break
            except UnicodeDecodeError:
                boundary -= 1
        fragments.append(fragment)
        remaining = encoded[boundary:].decode("utf-8")
    return fragments


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()
    return f"{prefix}_{digest}"


def _canonical_capability(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if value in _CAPABILITIES:
        return value
    for capability in _CAPABILITIES:
        prefix = value[: -len(capability)] if value.endswith(capability) else ""
        if prefix.endswith(("__", "/", ":", ".")):
            return capability
    return None


def _execution_context(capability: str) -> dict[str, str]:
    """Map an observed allow-listed call to product-owned execution labels."""

    delegates = {
        "byq_delegate_market_research": ("市场研究 Agent", "子 Agent 编排插件", "市场研究 Skill"),
        "byq_delegate_factor_research": ("因子研究 Agent", "子 Agent 编排插件", "因子研究 Skill"),
        "byq_delegate_strategy_research": ("策略研究 Agent", "子 Agent 编排插件", "策略研究 Skill"),
        "byq_delegate_backtest_analysis": ("回测分析 Agent", "子 Agent 编排插件", "回测分析 Skill"),
        "byq_delegate_ml_research": ("模型研究 Agent", "子 Agent 编排插件", "模型研究 Skill"),
    }
    if capability in delegates:
        agent, plugin, skill = delegates[capability]
    elif capability == "web_search":
        agent, plugin, skill = "市场研究 Agent", "网页研究插件", "市场研究 Skill"
    elif capability.startswith("byq_market_") or capability == "byq_web_evidence_create":
        agent, plugin, skill = "量化研究 Agent", "BeyondQuant MCP", "市场研究 Skill"
    elif capability.startswith("byq_factor_"):
        agent, plugin, skill = "量化研究 Agent", "BeyondQuant MCP", "因子研究 Skill"
    elif capability.startswith("byq_strategy_"):
        agent, plugin, skill = "量化研究 Agent", "BeyondQuant MCP", "策略研究 Skill"
    elif capability.startswith("byq_ml_"):
        agent, plugin, skill = "模型研究 Agent", "BeyondQuant MCP", "模型研究 Skill"
    elif capability.startswith("byq_backtest_"):
        agent, plugin, skill = "量化研究 Agent", "BeyondQuant MCP", "回测分析 Skill"
    elif capability.startswith("byq_pool_"):
        agent, plugin, skill = "小巴协调 Agent", "BeyondQuant MCP", "股票池管理 Skill"
    else:
        agent, plugin, skill = "小巴协调 Agent", "BeyondQuant MCP", "量化研究职责 Skill"
    return {"agent_label": agent, "plugin_label": plugin, "skill_label": skill}


def _progress(
    trace_id: str,
    session_id: str,
    sequence: int,
    reason: str,
    truncated: bool = False,
) -> WorkflowTraceEvent:
    return _event(
        trace_id,
        session_id,
        sequence,
        "session.progress",
        "runtime-adapter",
        {"reason": reason, "truncated": truncated},
    )


def _event(
    trace_id: str,
    session_id: str,
    sequence: int,
    kind: str,
    source: str,
    payload: dict[str, Any],
) -> WorkflowTraceEvent:
    return make_workflow_trace_event(
        trace_id=trace_id,
        session_id=session_id,
        sequence=sequence,
        kind=kind,
        source=source,  # type: ignore[arg-type]
        payload=payload,
    )
