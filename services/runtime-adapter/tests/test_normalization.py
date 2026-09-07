import json

import pytest

from deepseek_harness import Notification

from app.compat import Dsh011Compatibility
from app.normalization import NormalizationState, normalize_runtime_observation


compatibility = Dsh011Compatibility()


@pytest.mark.parametrize("family", ["dsh-0.1.1", "dsh-0.1.2"])
def test_batched_tool_results_close_each_exact_activity(family: str) -> None:
    adapter = (pytest.importorskip("app.compat.dsh_012").Dsh012Compatibility()
               if family == "dsh-0.1.2" else Dsh011Compatibility())
    state = NormalizationState()

    def project(kind: str, data: dict, sequence: int):
        return normalize_runtime_observation(
            adapter.observe(notify(kind, data), root_session_id="s-1"),
            trace_id="t-1", session_id="s-1", sequence=sequence, state=state,
        )

    started = []
    for index, call_id in enumerate(("first", "second", "third"), 1):
        started.extend(project("tool/call", {"callId": call_id, "name": "byq_market_daily"}, index))
    results = [
        {"type": "tool-result", "toolCallId": call_id, "isError": failed,
         "content": [{"type": "text", "text": json.dumps({"status": status, "private": "not-public"})}]}
        for call_id, failed, status in [
            ("first", False, "ok"), ("second", True, "error"), ("third", False, "outcome_unknown"),
        ]
    ]
    # A hidden control result and malformed/duplicate blocks must not hide
    # later public results or allocate duplicate terminal events.
    project("tool/call", {"callId": "control", "name": "byq_agent_authorize"}, 4)
    results = [
        {"type": "text", "text": "private-not-a-result"},
        {"type": "tool-result", "toolCallId": "", "content": []},
        {"type": "tool-result", "toolCallId": "control", "content": []},
        results[0], results[0], *results[1:],
    ]
    events = project("tool/result", {"message": {"content": results}}, 4)
    assert [item["payload"]["state"] for item in events] == ["completed", "failed", "unknown"]
    assert [item["payload"]["activity_id"] for item in events] == [item["payload"]["activity_id"] for item in started]
    assert [item["sequence"] for item in events] == [4, 5, 6]
    assert state.tool_names == {}
    assert "not-public" not in json.dumps(events)
    assert project("tool/result", {"message": {"content": results}}, 7) == []


@pytest.mark.parametrize("terminal", ["result", "cancelled"])
def test_activity_limit_reserves_closure_for_visible_steps(terminal: str) -> None:
    from app.compat.types import RuntimeObservation
    from app.contracts import MAX_ACTIVITIES_PER_TURN
    from app.normalization import close_public_activities

    state = NormalizationState()
    events = []
    for index in range(MAX_ACTIVITIES_PER_TURN + 5):
        events.extend(normalize_runtime_observation(
            RuntimeObservation(kind="tool.call", root_session=True, call_id=f"call-{index}",
                               tool_name="byq_market_daily"),
            trace_id="t", session_id="s", sequence=len(events) + 1, state=state,
        ))
    if terminal == "result":
        for index in range(MAX_ACTIVITIES_PER_TURN + 5):
            events.extend(normalize_runtime_observation(
                RuntimeObservation(kind="tool.result", root_session=True, call_id=f"call-{index}",
                                   tool_result={"status": "ok"}),
                trace_id="t", session_id="s", sequence=len(events) + 1, state=state,
            ))
    else:
        events.extend(close_public_activities(state, "t", "s", len(events) + 1, "cancelled"))
    activities = [item["payload"] for item in events if item["kind"] == "agent.activity"]
    started = [item["activity_id"] for item in activities if item["state"] == "started"]
    ended = [item["activity_id"] for item in activities if item["state"] != "started"]
    assert started
    assert ended == started
    assert len(activities) <= MAX_ACTIVITIES_PER_TURN
    assert [item["sequence"] for item in events] == list(range(1, len(events) + 1))
    assert close_public_activities(state, "t", "s", len(events) + 1, "failed") == []


def test_next_turn_does_not_forget_a_tool_with_no_result() -> None:
    from app.compat.types import RuntimeObservation

    state = NormalizationState()

    def project(observation, sequence):
        return normalize_runtime_observation(observation, trace_id="t", session_id="s",
                                             sequence=sequence, state=state)

    project(RuntimeObservation(kind="turn.start", root_session=True), 1)
    started = project(RuntimeObservation(kind="tool.call", root_session=True, call_id="lost",
                                       tool_name="byq_market_daily"), 2)
    project(RuntimeObservation(kind="turn.end", root_session=True, terminal_reason="completed"), 3)
    next_turn = project(RuntimeObservation(kind="turn.start", root_session=True), 5)
    assert next_turn[0]["payload"]["activity_id"] == started[0]["payload"]["activity_id"]
    assert next_turn[0]["payload"]["state"] == "unknown"
    assert next_turn[1]["payload"]["state"] == "started"
    assert [item["sequence"] for item in next_turn] == [5, 6]


def notify(event_type: str, data: dict | None = None) -> Notification:
    return Notification(
        method="session.event",
        payload={"sessionId": "s-1", "event": {"type": event_type, "data": data or {}}},
    )


def normalize(notification: Notification, state: NormalizationState | None = None):
    return normalize_runtime_observation(
        compatibility.observe(notification, root_session_id="s-1"),
        trace_id="t-1",
        session_id="s-1",
        sequence=4,
        state=state,
    )


def test_session_status_is_a_byq_owned_event() -> None:
    events = normalize(
        Notification(method="session.status", payload={"sessionId": "s-1", "status": "idle"})
    )

    assert len(events) == 1
    assert events[0] == {
        "trace_id": "t-1",
        "session_id": "s-1",
        "sequence": 4,
        "timestamp": events[0]["timestamp"],
        "kind": "session.status",
        "source": "dsh",
        "payload": {"status": "idle"},
    }


def test_resumed_runtime_identity_is_correlated_to_the_stable_byq_session() -> None:
    events = normalize_runtime_observation(
        compatibility.observe(
            Notification(
                method="session.status",
                payload={"sessionId": "s-1-resume-private", "status": "idle"},
            ),
            root_session_id="s-1-resume-private",
        ),
        trace_id="t-1",
        session_id="s-1",
        sequence=5,
    )

    assert events[0]["session_id"] == "s-1"
    assert "resume-private" not in json.dumps(events)


def test_turn_does_not_forward_raw_event_data() -> None:
    events = normalize(notify("turn/end", {"reason": {"kind": "completed"}, "private": "no"}))

    assert events[0]["kind"] == "turn.completed"
    assert events[0]["payload"] == {"reason": "completed"}
    assert "event" not in events[0]


def test_turn_activity_reaches_a_terminal_public_state() -> None:
    state = NormalizationState()
    started = normalize(notify("turn/start", {"turn": 1}), state)
    completed = normalize(notify("turn/end", {"reason": {"kind": "completed"}}), state)

    assert started[0]["payload"]["activity_id"] == completed[0]["payload"]["activity_id"]
    assert started[0]["payload"]["state"] == "started"
    assert completed[0]["payload"]["state"] == "completed"
    assert completed[1]["kind"] == "turn.completed"


def test_dsh_error_turn_is_never_projected_as_completed() -> None:
    state = NormalizationState()
    normalize(notify("turn/start", {"turn": 1}), state)

    failed = normalize(notify("turn/end", {"reason": {"kind": "error"}}), state)

    assert failed[0]["payload"]["state"] == "failed"
    assert failed[1]["kind"] == "turn.completed"
    assert failed[1]["payload"] == {"reason": "failed"}


def test_answer_excludes_reasoning_and_duplicate_messages() -> None:
    state = NormalizationState()
    message = notify(
        "assistant/message",
        {
            "message": {
                "id": "m-1",
                "content": [
                    {"type": "reasoning", "text": "private chain"},
                    {"type": "text", "text": "公开答案"},
                ],
            }
        },
    )
    events = normalize(message, state)

    assert [event["kind"] for event in events] == ["agent.output.delta"]
    assert events[0]["payload"]["delta"] == "公开答案"
    assert normalize(message, state) == []


def test_tool_bearing_assistant_step_is_not_a_public_answer() -> None:
    events = normalize(
        notify(
            "assistant/message",
            {
                "message": {
                    "id": "m-tool",
                    "content": [
                        {
                            "type": "text",
                            "text": "Data retrieved. Now I'll authorize and audit the next call.",
                        },
                        {"type": "tool-call", "name": "byq_agent_authorize", "arguments": {}},
                    ],
                }
            },
        ),
        NormalizationState(),
    )

    assert events == []


def test_final_answer_translates_raw_research_terms_and_preserves_evidence() -> None:
    events = normalize(
        notify(
            "assistant/message",
            {
                "message": {
                    "id": "m-final",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "截至 20260825，coverage.usable=false；600036.SH 的 roe 与 "
                                "debt_to_assets 缺失，近五日收益为 -2.31%。"
                            ),
                        }
                    ],
                }
            },
        ),
        NormalizationState(),
    )

    answer = events[0]["payload"]["delta"]
    assert "coverage.usable" not in answer
    assert "debt_to_assets" not in answer
    assert "当前数据覆盖不足，暂不适合比较" in answer
    assert "资产负债率" in answer
    assert "20260825" in answer
    assert "-2.31%" in answer


def test_unknown_submission_is_not_completed_and_unclosed_steps_are_closed():
    from app.compat.types import RuntimeObservation
    from app.normalization import close_public_activities, normalize_runtime_observation
    state = NormalizationState()
    def project(observation, sequence):
        return normalize_runtime_observation(observation, trace_id="t", session_id="s", sequence=sequence, state=state)
    project(RuntimeObservation(kind="turn.start", root_session=True), 1)
    started = project(RuntimeObservation(kind="tool.call", root_session=True, call_id="call",
                                         tool_name="byq_ml_training_create"), 2)
    result = project(RuntimeObservation(kind="tool.result", root_session=True, call_id="call",
                                        tool_result={"status": "outcome_unknown"}), 3)
    assert result[0]["payload"]["state"] == "unknown"
    assert result[0]["payload"]["activity_id"] == started[0]["payload"]["activity_id"]
    project(RuntimeObservation(kind="tool.call", root_session=True, call_id="accepted",
                               tool_name="byq_ml_training_create"), 4)
    accepted = project(RuntimeObservation(kind="tool.result", root_session=True, call_id="accepted",
                                          tool_result={"status": "ok", "training_run": {"status": "waiting_for_data"}}), 5)
    assert accepted[0]["payload"]["state"] == "waiting"
    project(RuntimeObservation(kind="tool.call", root_session=True, call_id="pending",
                               tool_name="byq_ml_training_create"), 4)
    closures = close_public_activities(state, "t", "s", 5, "cancelled")
    assert len(closures) == 2
    assert all(event["payload"]["state"] == "cancelled" for event in closures)
    assert close_public_activities(state, "t", "s", 7, "failed") == []
    project(RuntimeObservation(kind="turn.start", root_session=True), 8)
    later = project(RuntimeObservation(kind="tool.call", root_session=True, call_id="call",
                                       tool_name="byq_ml_training_create"), 9)
    assert later[0]["payload"]["activity_id"] != started[0]["payload"]["activity_id"]


def test_known_tool_emits_curated_activity_and_proposal_card() -> None:
    state = NormalizationState()
    started = normalize(
        notify(
            "tool/call",
            {"callId": "call-1", "name": "mcp__byq__byq_workflow_card_propose", "arguments": {"secret": "x"}},
        ),
        state,
    )
    result = {
        "service": "beyondquant-mcp",
        "status": "ok",
        "candidate": {
            "kind": "agent.card.strategy_draft",
            "payload": {"title": "策略草稿", "name": "双均线", "summary": "趋势跟随草稿"},
        },
    }
    completed = normalize(
        notify(
            "tool/result",
            {
                "message": {
                    "content": [
                        {
                            "type": "tool-result",
                            "toolCallId": "call-1",
                            "isError": False,
                            "content": [{"type": "text", "text": json.dumps(result)}],
                        }
                    ]
                }
            },
        ),
        state,
    )

    assert started[0]["payload"] == {
        "schema_version": "workflow-activity.v1",
        "activity_id": started[0]["payload"]["activity_id"],
        "phase": "strategy",
        "state": "started",
        "label": "整理工作台建议",
        "agent_label": "小巴协调 Agent",
        "plugin_label": "BeyondQuant MCP",
        "skill_label": "量化研究职责 Skill",
    }
    assert [event["kind"] for event in completed] == [
        "agent.activity",
        "agent.card.strategy_draft",
    ]
    assert completed[1]["payload"]["authority"] == "proposal"


def test_domain_tool_result_is_only_an_internal_reference_candidate() -> None:
    state = NormalizationState()
    normalize(
        notify("tool/call", {"callId": "call-2", "name": "byq_backtest_analysis_get"}),
        state,
    )
    events = normalize(
        notify(
            "tool/result",
            {
                "message": {
                    "content": [
                        {
                            "type": "tool-result",
                            "toolCallId": "call-2",
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(
                                        {"status": "ok", "job": {"job_id": "job-1", "owner": "leak"}}
                                    ),
                                }
                            ],
                        }
                    ]
                }
            },
        ),
        state,
    )

    assert events[1]["kind"] == "agent.card.backtest_context"
    assert events[1]["payload"] == {"job_id": "job-1"}
    assert "owner" not in str(events)


def test_unknown_tool_never_exposes_name_or_arguments() -> None:
    events = normalize(
        notify("tool/call", {"callId": "call-x", "name": "shell", "arguments": {"password": "x"}}),
        NormalizationState(),
    )

    assert events == []


def test_internal_control_activity_is_hidden_but_domain_research_is_public() -> None:
    state = NormalizationState()
    assert normalize(
        notify("tool/call", {"callId": "auth-1", "name": "byq_agent_authorize"}), state
    ) == []
    assert normalize(
        notify("tool/result", {"message": {"content": [{"type": "tool-result", "toolCallId": "auth-1"}]}}),
        state,
    ) == []

    started = normalize(
        notify("tool/call", {"callId": "value-1", "name": "byq_market_valuation"}), state
    )
    completed = normalize(
        notify(
            "tool/result",
            {"message": {"content": [{"type": "tool-result", "toolCallId": "value-1"}]}},
        ),
        state,
    )

    assert started[0]["payload"]["label"] == "读取估值数据"
    assert started[0]["payload"]["agent_label"] == "量化研究 Agent"
    assert started[0]["payload"]["plugin_label"] == "BeyondQuant MCP"
    assert started[0]["payload"]["skill_label"] == "市场研究 Skill"
    assert completed[0]["payload"]["label"] == "读取估值数据"
    assert "capability" not in started[0]["payload"]

    session_started = normalize(
        notify(
            "tool/call",
            {"callId": "session-context-1", "name": "byq_market_session_context"},
        ),
        state,
    )
    assert session_started[0]["payload"]["label"] == "确认交易日与数据截止"
    assert "capability" not in session_started[0]["payload"]


def test_ml_prediction_and_derived_backtest_have_closed_public_activities() -> None:
    state = NormalizationState()
    prediction = normalize(
        notify("tool/call", {"callId": "ml-pred-1", "name": "byq_ml_prediction_create"}),
        state,
    )
    assert prediction[0]["payload"]["phase"] == "strategy"
    assert prediction[0]["payload"]["label"] == "生成样本外预测与冻结信号"
    assert prediction[0]["payload"]["agent_label"] == "模型研究 Agent"
    assert prediction[0]["payload"]["skill_label"] == "模型研究 Skill"
    assert "capability" not in prediction[0]["payload"]

    backtest = normalize(
        notify("tool/call", {"callId": "ml-bt-1", "name": "byq_backtest_task_execute"}),
        state,
    )
    assert backtest[0]["payload"]["phase"] == "backtest"
    assert backtest[0]["payload"]["label"] == "执行回测任务"
    assert "arguments" not in backtest[0]["payload"]


def test_raw_chunks_and_unknown_events_do_not_cross_the_boundary() -> None:
    assert normalize(notify("assistant/chunk", {"text": "private partial"})) == []
    assert normalize(notify("request/context", {"credentials": "private"})) == []
    assert normalize(notify("future/private-event", {"value": "private"})) == []
