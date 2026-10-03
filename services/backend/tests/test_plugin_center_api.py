from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import main
from app.plugin_center import (
    PluginCenterConflict,
    PluginCenterForbidden,
    PluginCenterStore,
)


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


def test_policy_change_is_versioned_idempotent_audited_and_not_active(
    store: PluginCenterStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    monkeypatch.setenv("BYQ_PLUGIN_DEPLOYMENT_TOKEN", "deployment-test")
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


@pytest.mark.parametrize(("corruption", "mutation"), [
    ("missing_snapshot", "request_json = request_json - 'desired_policy'"),
    ("bad_type", "request_json = jsonb_set(request_json, '{desired_policy,enabled_plugin_ids}', '\"bad\"'::jsonb)"),
    ("schema", "request_json = jsonb_set(request_json, '{desired_policy,schema_version}', '\"plugin-deployment-policy.v0\"'::jsonb)"),
    ("version", "request_json = jsonb_set(request_json, '{desired_policy,policy_version}', '1'::jsonb)"),
    ("version_type", "request_json = jsonb_set(request_json, '{desired_policy,policy_version}', 'true'::jsonb)"),
    ("hash_format", "desired_policy_hash = 'not-a-sha256'"),
    ("hash_mismatch", "desired_policy_hash = CASE WHEN desired_policy_hash = 'sha256:' || repeat('0', 64) THEN 'sha256:' || repeat('1', 64) ELSE 'sha256:' || repeat('0', 64) END"),
])
def test_policy_deployment_input_rejects_missing_or_corrupt_snapshot(
    store: PluginCenterStore,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
    mutation: str,
) -> None:
    monkeypatch.setenv("BYQ_PLUGIN_DEPLOYMENT_TOKEN", "deployment-test")
    requested = store.request_change({
        "action": "disable", "plugin_id": "web-search", "expected_version": 1,
        "idempotency_key": f"phase17-corrupt-{corruption}", "reason": "snapshot integrity test",
    }, actor_principal="admin", actor_role="admin")
    request_id = requested["request"]["request_id"]
    store._execute(
        f"UPDATE plugin_change_requests SET {mutation} WHERE request_id=:request_id",
        {"request_id": request_id},
    )
    monkeypatch.setattr(main, "plugin_center_store", store)
    client = TestClient(main.app)
    response = client.get(
        f"/internal/plugin-center/requests/{request_id}",
        headers={"x-byq-plugin-deployment-token": "deployment-test"},
    )
    assert response.status_code == 503


@pytest.mark.parametrize(("action", "plugin_id", "allowed_agents"), [
    ("disable", "web-search", None),
    ("enable", "guard", None),
    ("assign", "web-search", ["market_researcher"]),
])
def test_policy_change_deployment_input_matches_producer_snapshot(
    store: PluginCenterStore,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    plugin_id: str,
    allowed_agents: list[str] | None,
) -> None:
    monkeypatch.setenv("BYQ_PLUGIN_DEPLOYMENT_TOKEN", "deployment-test")
    payload = {
        "action": action,
        "plugin_id": plugin_id,
        "expected_version": 1,
        "idempotency_key": f"phase17-snapshot-{action}-{plugin_id}",
        "reason": "producer to deployment-input contract",
    }
    if allowed_agents is not None:
        payload["allowed_agents"] = allowed_agents
    requested = store.request_change(payload, actor_principal="admin", actor_role="admin")

    deployment = store.deployment_input(
        requested["request"]["request_id"], service_token="deployment-test")
    assert deployment["schema_version"] == "plugin-deployment-input.v1"
    assert deployment["request"] == requested["request"]
    assert deployment["policy"]["schema_version"] == "plugin-deployment-policy.v1"
    assert deployment["policy"]["policy_version"] == requested["request"]["new_policy_version"]


def test_qualification_deployment_input_has_no_policy_snapshot_after_policy_change(
    store: PluginCenterStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BYQ_PLUGIN_DEPLOYMENT_TOKEN", "deployment-test")
    qualification = store.request_qualification({
        "plugin_id": "guard", "version": "0.1.1-rc.1", "expected_version": 1,
        "idempotency_key": "phase17-qualify-guard", "reason": "Engineering qualification handoff",
    }, actor_principal="admin", actor_role="admin")
    store.request_change({
        "action": "disable", "plugin_id": "web-search", "expected_version": 1,
        "idempotency_key": "phase17-disable-web-search", "reason": "change policy after qualification request",
    }, actor_principal="admin", actor_role="admin")

    monkeypatch.setattr(main, "plugin_center_store", store)
    client = TestClient(main.app)
    response = client.get(
        f"/internal/plugin-center/requests/{qualification['request']['request_id']}",
        headers={"x-byq-plugin-deployment-token": "deployment-test"},
    )
    assert response.status_code == 200
    deployment = response.json()
    assert set(deployment) == {"schema_version", "request", "policy", "runtime_baseline"}
    assert deployment["schema_version"] == "plugin-deployment-input.v1"
    assert deployment["request"] == qualification["request"]
    assert deployment["policy"] is None
    assert deployment["runtime_baseline"] == store.registry["runtime_baseline"]


def test_http_deployment_lane_requires_token_and_rejects_invalid_result_replay(
    store: PluginCenterStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BYQ_PLUGIN_DEPLOYMENT_TOKEN", "deployment-test")
    requested = store.request_change({
        "action": "disable", "plugin_id": "web-search", "expected_version": 1,
        "idempotency_key": "phase17-http-deployment", "reason": "deployment handoff authorization test",
    }, actor_principal="admin", actor_role="admin")
    request_id = requested["request"]["request_id"]
    monkeypatch.setattr(main, "plugin_center_store", store)
    client = TestClient(main.app)
    input_path = f"/internal/plugin-center/requests/{request_id}"
    result_path = f"{input_path}/result"
    generated = {
        "state": "generated", "composition_hash": "sha256:" + "a" * 64,
        "result": "bounded Engineering lane report",
    }
    for headers in ({}, {"x-byq-plugin-deployment-token": "wrong"}):
        assert client.get(input_path, headers=headers).status_code == 403
        assert client.post(result_path, headers=headers, json=generated).status_code == 403

    authorized = {"x-byq-plugin-deployment-token": "deployment-test"}
    deployment = client.get(input_path, headers=authorized)
    assert deployment.status_code == 200
    assert deployment.json()["policy"]["policy_version"] == requested["request"]["new_policy_version"]
    accepted = client.post(result_path, headers=authorized, json=generated)
    assert accepted.status_code == 200
    assert accepted.json()["request"]["deployment_state"] == "generated"
    invalid_transition = client.post(result_path, headers=authorized, json={
        **generated, "state": "active",
    })
    assert invalid_transition.status_code == 409
    replay = client.post(result_path, headers=authorized, json=generated)
    assert replay.status_code == 409


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
