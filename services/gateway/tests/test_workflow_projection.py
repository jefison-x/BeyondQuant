from app.workflow_projection import project_workflow_event


def candidate(kind: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "trace_id": "trace-1",
        "session_id": "session-1",
        "sequence": 3,
        "timestamp": "2026-08-22T00:00:00+00:00",
        "kind": kind,
        "source": "runtime-adapter",
        "payload": payload,
    }


def test_backtest_reference_is_replaced_by_owner_scoped_domain_data() -> None:
    calls: list[str] = []

    def get(path: str) -> dict[str, object]:
        calls.append(path)
        return {
            "job": {
                "job_id": "job-1",
                "owner_principal": "must-not-project",
                "status": "completed",
                "strategy_version_artifact_id": "artifact-strategy-1",
                "result_artifact_id": "artifact-result-1",
                "summary": {
                    "total_return": 0.12,
                    "max_drawdown": -0.03,
                    "trade_count": 7,
                    "reproducibility": {"private": True},
                },
            }
        }

    event = project_workflow_event(
        candidate("agent.card.backtest_context", {"job_id": "job-1", "spoofed": "x"}),
        backend_get=get,
        revision_for=lambda _card_id: 2,
    )

    assert calls == ["/v1/research/backtests/job-1"]
    assert event["source"] == "byq-domain"
    assert event["payload"]["authority"] == "domain"
    assert event["payload"]["revision"] == 2
    assert event["payload"]["metrics"] == {
        "total_return": 0.12,
        "max_drawdown": -0.03,
        "trade_count": 7,
    }
    assert "owner_principal" not in str(event)
    assert "spoofed" not in str(event)


def test_approval_reference_projects_state_and_execution_outcome() -> None:
    event = project_workflow_event(
        candidate("agent.card.approval", {"approval_id": "agent_approval_1"}),
        backend_get=lambda _path: {
            "approval": {
                "approval_id": "agent_approval_1",
                "action": "byq_backtest_run",
                "status": "rejected",
                "execution_outcome": "not_authorized",
                "decision_by": "reviewer",
                "decision_reason": "private detail",
            }
        },
        revision_for=lambda _card_id: 1,
    )

    assert event["payload"]["status"] == "rejected"
    assert event["payload"]["execution_outcome"] == "not_authorized"
    assert event["payload"]["decided_by_display"] == "reviewer"
    assert "decision_reason" not in str(event)


def test_missing_or_cross_owner_resource_degrades_at_same_sequence() -> None:
    event = project_workflow_event(
        candidate("agent.card.backtest_context", {"job_id": "job-foreign"}),
        backend_get=lambda _path: (_ for _ in ()).throw(RuntimeError("not found")),
        revision_for=lambda _card_id: 1,
    )

    assert event["sequence"] == 3
    assert event["kind"] == "session.progress"
    assert event["payload"] == {"reason": "projection-rejected", "truncated": False}
    assert "foreign" not in str(event)


def test_invalid_proposal_degrades_without_persistence_of_unknown_fields() -> None:
    event = project_workflow_event(
        candidate(
            "agent.card.strategy_draft",
            {
                "schema_version": "workflow-card.v1",
                "card_id": "card_" + "a" * 64,
                "revision": 1,
                "authority": "proposal",
                "title": "草稿",
                "name": "策略",
                "summary": "摘要",
                "truncated": False,
                "raw_event": {"private": True},
            },
        ),
        backend_get=lambda _path: {},
        revision_for=lambda _card_id: 1,
    )

    assert event["kind"] == "session.progress"
    assert "raw_event" not in str(event)
