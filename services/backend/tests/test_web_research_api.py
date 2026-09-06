from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.research import ResearchStore
from tests.test_web_research import evidence_fixture
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


def test_web_evidence_promotion_is_owner_scoped_and_trace_bound(monkeypatch) -> None:
    context = trusted_agent_context("alice", trace_id="trace-web-api-1")
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    task = store.create_task(
        {
            "owner_principal": "alice",
            "title": "Web evidence",
            "objective": "Persist qualified public research evidence.",
            "trace_id": "trace-web-api-1",
            "idempotency_key": "web-task-1",
        }
    )
    request = {
        "task_id": task["task_id"],
        "content": evidence_fixture(),
        "lineage": [],
        "idempotency_key": "web-evidence-api-1",
    }
    client = TestClient(main.app)

    missing = client.post("/v1/research/web-evidence", json=request)
    assert missing.status_code == 401

    wrong_owner = client.post(
        "/v1/research/web-evidence",
        headers=trusted_agent_context("bob", trace_id="trace-web-api-bob"),
        json=request,
    )
    assert wrong_owner.status_code == 404

    created = client.post("/v1/research/web-evidence", headers=context, json=request)
    assert created.status_code == 201, created.text
    artifact = created.json()
    assert artifact["kind"] == "web_research_evidence"
    assert artifact["owner_principal"] == "alice"
    assert artifact["trace_id"] == "trace-web-api-1"
    assert artifact["content"]["usage_policy"]["deterministic_input"] is False
    assert "credential" not in created.text.lower()
    store.close()


def test_web_evidence_record_atomically_creates_task_and_system_source_ids(monkeypatch) -> None:
    context = trusted_agent_context("alice", trace_id="trace-web-record-1")
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    content = evidence_fixture()
    for source in content["sources"]:  # type: ignore[index]
        source.pop("source_id")
    content["claims"][0]["source_indexes"] = [0]  # type: ignore[index]
    content["claims"][0].pop("source_ids")  # type: ignore[index]
    request = {
        "task": {"title": "网页研究记录", "objective": "保存本轮公开网页研究证据。"},
        "content": content,
        "lineage": [],
        "idempotency_key": "web-record-api-1",
    }
    client = TestClient(main.app)

    created = client.post("/v1/research/web-evidence-records", headers=context, json=request)

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["record_status"] == "saved"
    assert body["source_count"] == 2
    assert body["task"]["owner_principal"] == "alice"
    assert body["artifact"]["task_id"] == body["task"]["task_id"]
    source_id = body["artifact"]["content"]["sources"][0]["source_id"]
    assert source_id.startswith("source_")
    assert body["artifact"]["content"]["claims"][0]["source_ids"] == [source_id]

    repeated = client.post("/v1/research/web-evidence-records", headers=context, json=request)
    assert repeated.status_code == 201
    assert repeated.json()["task"]["task_id"] == body["task"]["task_id"]
    assert repeated.json()["artifact"]["artifact_id"] == body["artifact"]["artifact_id"]
    store.close()


def test_invalid_web_evidence_record_leaves_no_orphan_task(monkeypatch) -> None:
    context = trusted_agent_context("alice", trace_id="trace-web-record-invalid")
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    content = evidence_fixture()
    for source in content["sources"]:  # type: ignore[index]
        source.pop("source_id")
    content["claims"][0]["source_indexes"] = [999]  # type: ignore[index]
    content["claims"][0].pop("source_ids")  # type: ignore[index]
    client = TestClient(main.app)

    response = client.post(
        "/v1/research/web-evidence-records",
        headers=context,
        json={
            "task": {"title": "不会留下的任务", "objective": "无效证据应整体失败。"},
            "content": content,
            "lineage": [],
            "idempotency_key": "web-record-invalid-1",
        },
    )

    assert response.status_code == 422
    assert store.list_tasks(owner_principal="alice") == {"tasks": []}
    store.close()


def test_candidate_withdrawal_preserves_history_and_rejects_new_candidate_writes(monkeypatch) -> None:
    from app.web_evidence_provenance import default_policy_path

    context = trusted_agent_context("alice", trace_id="trace-web-rolling")
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)
    default_path = default_policy_path()
    candidate_path = default_path.with_name("dsh-0.1.2rc1.web-evidence-provenance.json")
    saved = []
    with monkeypatch.context() as candidate_context:
        candidate_context.setenv("BYQ_WEB_EVIDENCE_PROVENANCE_POLICY", str(candidate_path))
        for version in ("0.1.1-rc.1", "0.1.2-rc.1"):
            content = evidence_fixture()
            for source in content["sources"]:
                source.pop("source_id")
            content["claims"][0]["source_indexes"] = [0]
            content["claims"][0].pop("source_ids")
            content["search"]["plugin_version"] = version
            request = {
                "task": {"title": "Rolling producer", "objective": "Preserve immutable research evidence."},
                "content": content, "lineage": [], "idempotency_key": "rolling-" + version,
            }
            response = client.post("/v1/research/web-evidence-records", headers=context, json=request)
            assert response.status_code == 201, response.text
            saved.append(response.json()["artifact"])

    # Candidate is no longer recognized for writes. Reads do not revalidate or
    # rewrite immutable evidence against today's active deployment policy.
    for artifact in saved:
        response = client.get("/v1/research/artifacts/" + artifact["artifact_id"], headers=context)
        assert response.status_code == 200, response.text
        assert response.json()["content"] == artifact["content"]
        assert response.json()["content_sha256"] == artifact["content_sha256"]
        other = client.get(
            "/v1/research/artifacts/" + artifact["artifact_id"],
            headers=trusted_agent_context("bob", trace_id="trace-web-other"),
        )
        assert other.status_code == 404

    # Request headers cannot select the deployment policy.
    forged_headers = {**context, "X-BYQ-Web-Evidence-Provenance-Policy": str(candidate_path)}
    rejected = client.post("/v1/research/web-evidence-records", headers=forged_headers, json=request)
    assert rejected.status_code == 422
    assert len(store.list_tasks(owner_principal="alice")["tasks"]) == 2
    store.close()


def test_web_evidence_write_failure_rolls_back_created_task(monkeypatch) -> None:
    context = trusted_agent_context("alice", trace_id="trace-web-rollback")
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)

    attempted = []
    def fail_artifact(payload):
        attempted.append(True)
        raise ValueError("injected artifact validation failure")

    content = evidence_fixture()
    for source in content["sources"]:
        source.pop("source_id")
    content["claims"][0]["source_indexes"] = [0]
    content["claims"][0].pop("source_ids")
    monkeypatch.setattr(store, "_artifact_payload", fail_artifact)
    response = TestClient(main.app).post(
        "/v1/research/web-evidence-records", headers=context,
        json={
            "task": {"title": "Atomic failure", "objective": "No orphan task after artifact failure."},
            "content": content, "lineage": [], "idempotency_key": "atomic-failure",
        },
    )
    assert attempted == [True]
    assert response.status_code == 422
    assert store.list_tasks(owner_principal="alice") == {"tasks": []}
    store.close()
