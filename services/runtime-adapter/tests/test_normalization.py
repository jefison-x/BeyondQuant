import json

from deepseek_harness import Notification

from app.normalization import NormalizationState, normalize_dsh_notification


def notify(event_type: str, data: dict | None = None) -> Notification:
    return Notification(
        method="session.event",
        payload={"sessionId": "s-1", "event": {"type": event_type, "data": data or {}}},
    )


def normalize(notification: Notification, state: NormalizationState | None = None):
    return normalize_dsh_notification(
        notification,
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
    events = normalize_dsh_notification(
        Notification(
            method="session.status",
            payload={"sessionId": "s-1-resume-private", "status": "idle"},
        ),
        trace_id="t-1",
        session_id="s-1",
        runtime_session_id="s-1-resume-private",
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
    }
    assert [event["kind"] for event in completed] == [
        "agent.activity",
        "agent.card.strategy_draft",
    ]
    assert completed[1]["payload"]["authority"] == "proposal"


def test_domain_tool_result_is_only_an_internal_reference_candidate() -> None:
    state = NormalizationState()
    normalize(notify("tool/call", {"callId": "call-2", "name": "byq_backtest_get"}), state)
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


def test_raw_chunks_and_unknown_events_do_not_cross_the_boundary() -> None:
    assert normalize(notify("assistant/chunk", {"text": "private partial"})) == []
    assert normalize(notify("request/context", {"credentials": "private"})) == []
    assert normalize(notify("future/private-event", {"value": "private"})) == []
