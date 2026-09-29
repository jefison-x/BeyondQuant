from __future__ import annotations

import pytest

from app.audit_event import AuditEmitter, AuditEvent


def test_audit_event_has_stable_structure_and_redacts_metadata() -> None:
    event = AuditEvent(
        event_id="audit_test",
        occurred_at="2026-09-29T12:00:00+00:00",
        workspace_id="workspace_test",
        owner_principal="owner_test",
        actor_principal="byq.factor_worker",
        action="job.completed",
        resource_type="job",
        resource_id="factorjob_123",
        result="success",
        request_id=None,
        job_id="factorjob_123",
        metadata={
            "artifact_id": "artifact_123",
            "trace_id": "trace_123",
            "api_key": "do-not-emit",
            "details": {
                "Authorization": "Bearer do-not-emit-this-either",
                "note": "password=hunter2",
            },
        },
    )

    assert event.to_dict() == {
        "schema_version": "audit-event.v1",
        "event_id": "audit_test",
        "occurred_at": "2026-09-29T12:00:00+00:00",
        "workspace_id": "workspace_test",
        "owner_principal": "owner_test",
        "actor_principal": "byq.factor_worker",
        "action": "job.completed",
        "resource_type": "job",
        "resource_id": "factorjob_123",
        "result": "success",
        "request_id": None,
        "job_id": "factorjob_123",
        "metadata": {
            "artifact_id": "artifact_123",
            "trace_id": "trace_123",
            "api_key": "[REDACTED]",
            "details": {
                "Authorization": "[REDACTED]",
                "note": "password=[REDACTED]",
            },
        },
    }


def test_audit_emitter_swallows_sink_failure_without_logging_error_contents(caplog) -> None:
    event = AuditEvent(
        workspace_id="workspace_test",
        owner_principal="owner_test",
        actor_principal="byq.factor_worker",
        action="job.completed",
        resource_type="job",
        resource_id="factorjob_123",
        result="success",
        job_id="factorjob_123",
        metadata={"artifact_id": "artifact_123"},
    )

    def broken_sink(_payload):
        raise RuntimeError("secret=must-not-appear")

    assert AuditEmitter(broken_sink).emit(event) is False
    assert "audit event sink failed" in caplog.text
    assert "must-not-appear" not in caplog.text


def test_audit_metadata_is_bounded_json() -> None:
    common = {
        "workspace_id": "workspace_test",
        "owner_principal": "owner_test",
        "actor_principal": "byq.factor_worker",
        "action": "job.completed",
        "resource_type": "job",
        "resource_id": "factorjob_123",
        "result": "success",
    }
    with pytest.raises(ValueError, match="JSON values"):
        AuditEvent(**common, metadata={"value": object()})
    with pytest.raises(ValueError, match="too large"):
        AuditEvent(**common, metadata={f"field_{index}": "x" * 100 for index in range(100)})
