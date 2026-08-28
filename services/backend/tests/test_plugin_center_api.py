from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import main
from app.plugin_center import PluginCenterConflict, PluginCenterForbidden, PluginCenterStore


pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set")


@pytest.fixture()
def store() -> PluginCenterStore:
    value = PluginCenterStore()
    with value.engine.begin() as connection:
        connection.execute(text("TRUNCATE plugin_governance_audit, plugin_change_requests, plugin_product_policy"))
    value._bootstrap_policy()
    yield value
    value.close()


def test_projection_is_admin_only_secret_free_and_uses_real_registry(store: PluginCenterStore) -> None:
    with pytest.raises(PluginCenterForbidden):
        store.projection(actor_role="user")
    result = store.projection(actor_role="admin")
    assert result["schema_version"] == "plugin-center.v1"
    assert {plugin["id"] for plugin in result["plugins"]} == {"compaction", "guard", "interaction", "spill", "web-search"}
    assert result["counts"]["QUALIFIED"] == 3
    assert result["counts"]["ENABLED"] == 3
    assert result["boundaries"] == {"online_install": False, "runtime_mutation": False, "secrets_exposed": False}
    serialized = str(result).lower()
    assert "sha512-" not in serialized
    assert "deepseek_api_key" not in serialized
    assert "/home/" not in serialized and "/opt/" not in serialized


def test_policy_change_is_versioned_idempotent_audited_and_not_active(store: PluginCenterStore) -> None:
    payload = {"action": "disable", "plugin_id": "web-search", "expected_version": 1,
               "idempotency_key": "phase65-disable-web", "reason": "bounded rollback exercise"}
    first = store.request_change(payload, actor_principal="admin", actor_role="admin")
    assert first["request"]["status"] == "validated"
    assert first["request"]["deployment_state"] == "awaiting_generation"
    assert first["request"]["target_composition_hash"] is None
    assert store.request_change(payload, actor_principal="admin", actor_role="admin") == first
    projection = store.projection(actor_role="admin")
    assert projection["policy"]["version"] == 2
    assert "web-search" not in projection["policy"]["enabled_plugin_ids"]
    assert projection["audit"][0]["actor_principal"] == "admin"
    with pytest.raises(PluginCenterConflict):
        store.request_change({**payload, "reason": "different"}, actor_principal="admin", actor_role="admin")

    os.environ["BYQ_PLUGIN_DEPLOYMENT_TOKEN"] = "deployment-test"
    request_id = first["request"]["request_id"]
    with pytest.raises(PluginCenterForbidden):
        store.deployment_input(request_id, service_token="wrong")
    # A later request must not retarget this request to a newer policy. Each
    # trusted deployment input is an immutable snapshot of its own transition.
    store.request_change({"action": "disable", "plugin_id": "compaction", "expected_version": 2,
        "idempotency_key": "phase65-disable-compaction", "reason": "concurrent policy exercise"},
        actor_principal="admin", actor_role="admin")
    deployment = store.deployment_input(request_id, service_token="deployment-test")
    assert deployment["policy"]["policy_version"] == 2
    assert "compaction" in deployment["policy"]["enabled_plugin_ids"]
    assert "web-search" not in deployment["policy"]["enabled_plugin_ids"]
    digest = "sha256:" + "a" * 64
    generated = store.record_result(request_id, {"state": "generated", "composition_hash": digest,
        "result": "exact lock and deterministic builder passed"}, service_token="deployment-test")
    assert generated["request"]["deployment_state"] == "generated"
    store.record_result(request_id, {"state": "deploying", "composition_hash": digest,
        "result": "immutable image restart requested"}, service_token="deployment-test")
    active = store.record_result(request_id, {"state": "active", "composition_hash": digest,
        "result": "runtime readiness identity matched"}, service_token="deployment-test")
    assert active["request"]["status"] == "completed"


def test_fail_closed_for_blocked_plugin_assignment_and_unknown_version(store: PluginCenterStore) -> None:
    common = {"expected_version": 1, "reason": "negative qualification test"}
    with pytest.raises(ValueError, match="policy-safe"):
        store.request_change({**common, "action": "enable", "plugin_id": "spill", "idempotency_key": "blocked"}, actor_principal="admin", actor_role="admin")
    with pytest.raises(ValueError, match="allowlist"):
        store.request_change({**common, "action": "assign", "plugin_id": "web-search", "allowed_agents": ["factor-research"], "idempotency_key": "escalation"}, actor_principal="admin", actor_role="admin")
    with pytest.raises(ValueError, match="exact registered version"):
        store.request_qualification({**common, "plugin_id": "web-search", "version": "latest", "idempotency_key": "latest"}, actor_principal="admin", actor_role="admin")


def test_qualification_is_queued_without_policy_mutation(store: PluginCenterStore) -> None:
    result = store.request_qualification({"plugin_id": "guard", "version": "0.1.1-rc.1", "expected_version": 1,
        "idempotency_key": "qualify-guard", "reason": "rerun exact locked gates"}, actor_principal="admin", actor_role="admin")
    assert result["request"]["status"] == "queued"
    assert result["request"]["deployment_state"] == "not_applicable"
    assert store.projection(actor_role="admin")["policy"]["version"] == 1


def test_http_api_rejects_ordinary_user(store: PluginCenterStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "plugin_center_store", store)
    client = TestClient(main.app)
    assert client.get("/v1/plugin-center", headers={"x-byq-actor-role": "user"}).status_code == 403
    allowed = client.get("/v1/plugin-center", headers={"x-byq-actor-role": "admin"})
    assert allowed.status_code == 200
    assert "sha512-" not in allowed.text.lower()
