from __future__ import annotations
import os
import pytest
from fastapi.testclient import TestClient
os.environ.setdefault("BYQ_FEEDBACK_HUB_STATUS_SECRET", "test-status-secret-which-is-longer-than-32")
os.environ.setdefault("BYQ_FEEDBACK_GITHUB_REPOSITORY", "jefison-x/BeyondQuant")
from app import main as hub_module  # noqa: E402
from app.main import HubStore, digest  # noqa: E402

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_FEEDBACK_HUB_DATABASE_URL"), reason="hub test database is not set")

@pytest.fixture
def store() -> HubStore:
    value = HubStore(os.environ["BYQ_FEEDBACK_HUB_DATABASE_URL"])
    with value.tx() as connection:
        connection.exec_driver_sql("TRUNCATE central_feedback_audit,central_feedback_outbox,central_feedback CASCADE")
    yield value
    value.engine.dispose()

def snapshot(title: str = "模型研究页面加载较慢") -> dict[str, object]:
    public={
        "category":"performance","component":"model_research",
        "title":title,"description":"打开页面后首屏等待时间较长。","reproduction_steps":["打开模型研究"],
        "expected_behavior":"快速显示目录。","actual_behavior":"长时间等待。","severity":"normal",
        "environment":{"product_version":"0.1.0"}}
    return {"schema_version":"submitted-feedback-snapshot.v1","public_content":public,
            "redactions":{"categories":[],"count":0},
            "preview_hash":digest({"schema_version":"feedback-publication-preview.v1","public_content":public})}

def intake(store: HubStore, index: int = 1) -> dict[str, object]:
    value=snapshot()
    return store.intake({"schema_version":"central-feedback-intake.v1","installation_id":"byq-installation-"+"a"*32,
        "event_id":"feedback_hub_event_"+f"{index:032x}","snapshot_hash":digest(value),"snapshot":value})

def test_intake_is_idempotent_anonymous_and_moderated_before_publish(store: HubStore) -> None:
    receipt=intake(store); assert intake(store)==receipt
    page=store.list("received",20,0); assert page["total"]==1 and "installation" not in str(page["items"])
    identity=str(receipt["receipt_id"])
    assert store.moderate(identity,"triage",{"rationale":"信息完整"})["status"]=="triaged"
    assert store.moderate(identity,"accept",{"rationale":"进入官方发布队列"})["status"]=="accepted"
    event=store.claim({"worker_id":"publisher-test","limit":1,"lease_seconds":30})["events"][0]
    assert event["snapshot"]["schema_version"]=="feedback-publication.v1"
    published=store.result(event["event_id"],{"worker_id":"publisher-test","lease_fence":event["lease_fence"],
        "repository":"jefison-x/BeyondQuant","issue_number":42,"html_url":"https://github.com/jefison-x/BeyondQuant/issues/42",
        "provider_identity":"9001"},True)
    assert published["status"]=="published" and store.status(identity)["github_issue"]["issue_number"]==42

def test_intake_rejects_secret_and_enforces_installation_rate_limit(store: HubStore) -> None:
    unsafe=snapshot("反馈包含敏感信息"); unsafe["public_content"]["description"]="password=do-not-publish"
    with pytest.raises(ValueError,match="cannot enter"):
        store.intake({"schema_version":"central-feedback-intake.v1","installation_id":"byq-installation-"+"b"*32,
            "event_id":"feedback_hub_event_"+"b"*32,"snapshot_hash":digest(unsafe),"snapshot":unsafe})
    for index in range(1,6): intake(store,index)
    with pytest.raises(OverflowError): intake(store,6)

def test_intake_rejects_changed_content_with_stale_preview_hash(store: HubStore) -> None:
    changed=snapshot(); changed["public_content"]["description"]="内容在预览之后被修改。"
    with pytest.raises(ValueError,match="preview hash"):
        store.intake({"schema_version":"central-feedback-intake.v1","installation_id":"byq-installation-"+"c"*32,
            "event_id":"feedback_hub_event_"+"c"*32,"snapshot_hash":digest(changed),"snapshot":changed})

def test_public_status_requires_the_receipt_capability(store: HubStore, monkeypatch) -> None:
    receipt=intake(store)
    monkeypatch.setattr(hub_module,"store",store)
    client=TestClient(hub_module.app)
    path=f"/v1/status/{receipt['receipt_id']}"
    assert client.get(path).status_code==401
    assert client.get(path,headers={"authorization":"Bearer wrong"}).status_code==401
    response=client.get(path,headers={"authorization":f"Bearer {receipt['status_token']}"})
    assert response.status_code==200 and response.json()["status"]=="received"
