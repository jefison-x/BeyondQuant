from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchStore
from tests.test_web_research import evidence_fixture
from tests.workspace_helpers import trusted_agent_context, trusted_product_agent_context


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


def _web_record_request(key: str) -> dict[str, object]:
    content = evidence_fixture()
    for source in content["sources"]:
        source.pop("source_id")
    content["claims"][0]["source_indexes"] = [0]
    content["claims"][0].pop("source_ids")
    return {
        "task": {"title": "Web evidence task", "objective": "Keep this research in its source conversation."},
        "content": content,
        "lineage": [],
        "idempotency_key": key,
    }


def _trusted_context(headers: dict[str, str]) -> dict[str, str]:
    return {
        key.removeprefix("x-byq-").replace("-", "_"): value
        for key, value in headers.items()
        if key.lower().startswith("x-byq-") and key.lower() != "x-byq-runtime-boot-id"
    }


def test_artifact_reference_is_workspace_scoped_and_excludes_storage_content(monkeypatch) -> None:
    context = trusted_agent_context("artifact-reference-owner", trace_id="trace-artifact-reference")
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    task = store.create_task({
        "owner_principal": "artifact-reference-owner", "title": "Artifact reference",
        "objective": "Read a stable reference", "trace_id": "trace-artifact-reference",
        "idempotency_key": "artifact-reference-task",
    })
    artifact = store.create_artifact({
        "task_id": task["task_id"], "kind": "Report with spaces",
        "content": {"metadata": {"title": "A report", "private_field": "hidden"},
                    "result_reference": {"object_key": "private/storage/key"}},
        "lineage": [], "trace_id": "trace-artifact-reference",
        "idempotency_key": "artifact-reference-result",
    })
    client = TestClient(main.app)
    try:
        response = client.get(
            f"/v1/research/artifacts/{artifact['artifact_id']}/reference", headers=context,
        )
        assert response.status_code == 200, response.text
        reference = response.json()
        assert reference["ref"] == {"kind": "artifact", "id": artifact["artifact_id"]}
        assert reference["workspace_id"] == context["x-byq-workspace-id"]
        assert reference["type"] == "Report with spaces"
        assert reference["metadata"] == {"title": "A report"}
        assert "content" not in reference
        assert "private/storage/key" not in response.text
        assert client.get(
            f"/v1/research/artifacts/{artifact['artifact_id']}/reference",
            headers=trusted_agent_context("artifact-reference-other"),
        ).status_code == 404
        # Simulate a second valid workspace for the same owner. The Artifact
        # read boundary must still reject a known ID from another workspace.
        monkeypatch.setattr(main.workspace_tenancy_store, "resolve_context", lambda *_args: None)
        other_workspace = {**context, "x-byq-workspace-id": "workspace_" + "f" * 32}
        assert client.get(
            f"/v1/research/artifacts/{artifact['artifact_id']}", headers=other_workspace,
        ).status_code == 404
        assert client.get(
            f"/v1/research/artifacts/{artifact['artifact_id']}/reference", headers=other_workspace,
        ).status_code == 404
        listed = client.get("/v1/research/artifacts", headers=other_workspace)
        assert listed.status_code == 200, listed.text
        assert listed.json()["artifacts"] == []
    finally:
        store.close()


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


def test_product_web_record_binds_original_conversation_for_discovery_and_handoff(monkeypatch) -> None:
    owner, session, trace = "web-bound-owner", "web-bound-session", "trace-web-bound"
    headers = trusted_product_agent_context(
        owner, actor=f"byq-product-agent-{session}", session_id=session, trace_id=trace,
    )
    catalog = ConversationCatalogStore()
    conversation = catalog.create(owner, session, trace)
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)
    request = _web_record_request("product-bound-web-record")
    try:
        created = client.post("/v1/research/web-evidence-records", headers=headers, json=request)
        assert created.status_code == 201, created.text
        body = created.json()
        task_id = body["task"]["task_id"]
        assert body["task"]["conversation_id"] == conversation["conversation_id"]
        assert store.get_task(task_id)["conversation_id"] == conversation["conversation_id"]

        discovered = client.get("/v1/agent/research-context", headers=headers)
        assert discovered.status_code == 200, discovered.text
        assert [task["task_id"] for task in discovered.json()["tasks"]] == [task_id]
        handoff = client.get(f"/v1/research/tasks/{task_id}/handoff", headers=headers)
        assert handoff.status_code == 200, handoff.text
        assert handoff.json()["task_id"] == task_id
        assert handoff.json()["reason"] != "conversation_binding_missing"

        replay = client.post("/v1/research/web-evidence-records", headers=headers, json=request)
        assert replay.status_code == 201, replay.text
        assert replay.json()["task"]["task_id"] == task_id
        assert replay.json()["artifact"]["artifact_id"] == body["artifact"]["artifact_id"]
    finally:
        store.close()
        catalog.close()


@pytest.mark.parametrize("case", ["missing", "owner", "trace", "inactive"])
def test_product_web_record_rejects_unproven_conversation(case: str, monkeypatch) -> None:
    owner, session, trace = "web-unproven-owner", f"web-unproven-{case}", "trace-web-unproven"
    headers = trusted_product_agent_context(
        owner, actor=f"byq-product-agent-{session}", session_id=session, trace_id=trace,
    )
    catalog = ConversationCatalogStore()
    if case != "missing":
        conversation_owner = "web-other-owner" if case == "owner" else owner
        trusted_agent_context(conversation_owner)
        conversation_trace = "foreign-trace" if case == "trace" else trace
        conversation = catalog.create(conversation_owner, session, conversation_trace)
        if case == "inactive":
            catalog.update(conversation_owner, conversation["conversation_id"], {"status": "archived"})
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    try:
        response = TestClient(main.app).post(
            "/v1/research/web-evidence-records", headers=headers,
            json=_web_record_request(f"unproven-web-record-{case}"),
        )
        assert response.status_code == 422, response.text
        expected_detail = (
            "research requires its original conversation"
            if case == "missing" else "research conversation identity is invalid"
        )
        assert response.json()["detail"] == expected_detail
        assert store.list_tasks(owner_principal=owner)["tasks"] == []
        assert store._fetch_one("SELECT COUNT(*) AS count FROM artifacts WHERE owner_principal=:owner",
                                {"owner": owner}) == {"count": 0}
    finally:
        store.close()
        catalog.close()


@pytest.mark.parametrize("case", ["workspace", "payload_trace"])
def test_product_web_record_store_rejects_context_mismatch(case: str) -> None:
    owner, session, trace = "web-store-owner", f"web-store-{case}", "trace-web-store"
    headers = trusted_product_agent_context(
        owner, actor=f"byq-product-agent-{session}", session_id=session, trace_id=trace,
    )
    catalog = ConversationCatalogStore()
    catalog.create(owner, session, trace)
    store = ResearchStore()
    context = _trusted_context(headers)
    request = _web_record_request(f"store-mismatch-web-record-{case}")
    request.update({"owner_principal": owner, "trace_id": "foreign-trace" if case == "payload_trace" else trace})
    if case == "workspace":
        context["workspace_id"] = "workspace_" + "f" * 32
    try:
        with pytest.raises(ValueError, match="conversation identity"):
            store.create_web_evidence_record(request, trusted_context=context)
        assert store.list_tasks(owner_principal=owner)["tasks"] == []
        assert store._fetch_one("SELECT COUNT(*) AS count FROM artifacts WHERE owner_principal=:owner",
                                {"owner": owner}) == {"count": 0}
    finally:
        store.close()
        catalog.close()


def test_web_record_replay_cannot_rebind_conversation_or_retrofit_null(monkeypatch) -> None:
    owner, trace = "web-replay-owner", "trace-web-replay"
    first_session = "web-replay-first"
    first_headers = trusted_product_agent_context(
        owner, actor=f"byq-product-agent-{first_session}", session_id=first_session, trace_id=trace,
    )
    second_session = "web-replay-second"
    second_headers = trusted_product_agent_context(
        owner, actor=f"byq-product-agent-{second_session}", session_id=second_session, trace_id=trace,
    )
    legacy_session = "web-replay-legacy"
    legacy_headers = trusted_product_agent_context(
        owner, actor=f"byq-product-agent-{legacy_session}", session_id=legacy_session, trace_id=trace,
    )
    catalog = ConversationCatalogStore()
    first_conversation = catalog.create(owner, first_session, trace)
    second_conversation = catalog.create(owner, second_session, trace)
    catalog.create(owner, legacy_session, trace)
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)
    request = _web_record_request("no-web-record-rebinding")
    legacy_request = _web_record_request("no-null-web-record-retrofit")
    try:
        original = client.post("/v1/research/web-evidence-records", headers=first_headers, json=request)
        assert original.status_code == 201, original.text
        original_task = original.json()["task"]
        assert original_task["conversation_id"] == first_conversation["conversation_id"]

        cross_conversation = client.post(
            "/v1/research/web-evidence-records", headers=second_headers, json=request,
        )
        assert cross_conversation.status_code == 409, cross_conversation.text
        assert cross_conversation.json()["detail"] == "web evidence record conversation cannot be rebound"
        assert store.get_task(original_task["task_id"])["conversation_id"] == first_conversation["conversation_id"]
        assert store.get_task(original_task["task_id"])["conversation_id"] != second_conversation["conversation_id"]

        unbound = store.create_web_evidence_record({
            **legacy_request, "owner_principal": owner, "trace_id": trace,
        })
        assert unbound["task"]["conversation_id"] is None
        retrofit = client.post(
            "/v1/research/web-evidence-records", headers=legacy_headers, json=legacy_request,
        )
        assert retrofit.status_code == 409, retrofit.text
        assert retrofit.json()["detail"] == "web evidence record conversation cannot be rebound"
        assert store.get_task(unbound["task"]["task_id"])["conversation_id"] is None
        assert store._fetch_one("SELECT COUNT(*) AS count FROM research_tasks WHERE owner_principal=:owner",
                                {"owner": owner}) == {"count": 2}
        assert store._fetch_one("SELECT COUNT(*) AS count FROM artifacts WHERE owner_principal=:owner",
                                {"owner": owner}) == {"count": 2}
    finally:
        store.close()
        catalog.close()


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


def test_web_record_original_keys_recover_after_store_restart(monkeypatch):
    import hashlib
    context = trusted_agent_context('web-receipt-owner')
    client = TestClient(main.app)
    store = ResearchStore()
    monkeypatch.setattr(main, 'research_store', store)
    key = 'original-web-receipt-key'
    content = evidence_fixture()
    for source in content['sources']:
        source.pop('source_id')
    content['claims'][0]['source_indexes'] = [0]
    content['claims'][0].pop('source_ids')
    response = client.post('/v1/research/web-evidence-records', headers=context, json={
        'task': {'title': 'Receipt', 'objective': 'Restore original web evidence'},
        'content': content, 'lineage': [], 'idempotency_key': key,
    })
    assert response.status_code == 201, response.text
    original = response.json()
    assert original['idempotency_key'] == key
    assert 'idempotency_key' not in original['task']
    assert 'idempotency_key' not in original['artifact']
    store.close()
    replacement = ResearchStore()
    monkeypatch.setattr(main, 'research_store', replacement)
    def forbidden(*args, **kwargs):
        pytest.fail('receipt recovery cannot write or infer from a list')
    for name in ('create_web_evidence_record', 'create_task', 'create_artifact', 'list_tasks', 'list_artifacts'):
        monkeypatch.setattr(replacement, name, forbidden)
    digest = hashlib.sha256(key.encode()).hexdigest()[:32]
    path = '/v1/research/submissions/reconcile'
    task_query = {'entity_type': 'research_task', 'idempotency_key': f'web-record-task:{digest}'}
    task = client.get(path, headers=context, params=task_query)
    assert task.status_code == 200, task.text
    assert task.json()['status'] == 'confirmed'
    assert task.json()['entity']['task_id'] == original['task']['task_id']
    artifact = client.get(path, headers=context, params={
        'entity_type': 'artifact', 'idempotency_key': f'web-record-artifact:{digest}',
        'task_id': task.json()['entity']['task_id'],
    })
    assert artifact.status_code == 200, artifact.text
    assert artifact.json()['status'] == 'confirmed'
    assert artifact.json()['entity'] == original['artifact']
    foreign = trusted_agent_context('web-receipt-other')
    assert client.get(path, headers=foreign, params=task_query).json()['status'] == 'outcome_unknown'
    replacement.close()
