"""Real API/PostgreSQL regressions for factor and imported signal ownership."""
import os

import pytest
from fastapi.testclient import TestClient

from app import main
from test_backtest_api import _create_strategy_chain, _fresh_harness, _snapshot_input
from test_factor_research import factor_payload
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")


def invalid_context(case, owner_headers):
    if case == "missing":
        return {}
    if case == "disabled":
        user = next(user for user in main.user_store.list_users(actor_role="admin")["users"]
                    if user["username"] == "product-user")
        main.user_store.disable_user(user["user_id"], actor_role="admin")
        return owner_headers
    foreign = trusted_agent_context("other-user")
    if case == "foreign":
        return foreign
    return {**owner_headers, "x-byq-workspace-id": foreign["x-byq-workspace-id"]}


@pytest.mark.parametrize("kind", ["factor", "signal"])
@pytest.mark.parametrize("identity", ["missing", "foreign", "mismatched_workspace", "disabled"])
def test_domain_import_rejects_untrusted_owner_before_computation(monkeypatch, tmp_path, kind, identity):
    store, jobs, _, owner = _fresh_harness(monkeypatch, tmp_path)
    chain = _create_strategy_chain(owner, key="input-ownership")
    task_id = chain["task"]["task_id"]
    if kind == "factor":
        path = "/v1/research/factors/compute"
        body = {**factor_payload(), "task_id": task_id}
        computation_name = "compute_factor"
    else:
        path = "/v1/research/signal-snapshots"
        body = {**_snapshot_input(), "task_id": task_id,
                "strategy_version_artifact_id": chain["version"]["artifact"]["artifact_id"],
                "trace_id": "trace-input-test", "idempotency_key": "input-test"}
        computation_name = "normalize_signal_snapshot"
    calls = []
    original = getattr(main, computation_name)
    def observed(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(main, computation_name, observed)
    before = store.list_artifacts(owner_principal="product-user")
    with TestClient(main.app) as client:
        response = client.post(path, json=body, headers=invalid_context(identity, dict(owner.headers)))
    assert response.status_code == (404 if identity == "foreign" else 401), response.text
    assert calls == [], "unauthorized requests must not start computation"
    assert store.list_artifacts(owner_principal="product-user") == before
    store.close()
    jobs.close()


@pytest.mark.parametrize("identity", ["missing", "foreign", "mismatched_workspace", "disabled", "wrong_kind", "owner"])
def test_signal_snapshot_read_is_owned_and_typed(monkeypatch, tmp_path, identity):
    store, jobs, _, owner = _fresh_harness(monkeypatch, tmp_path)
    chain = _create_strategy_chain(owner, key="snapshot-read-ownership")
    created = owner.post("/v1/research/signal-snapshots", json={
        **_snapshot_input(), "task_id": chain["task"]["task_id"],
        "strategy_version_artifact_id": chain["version"]["artifact"]["artifact_id"],
        "trace_id": "trace-snapshot-read", "idempotency_key": "snapshot-read",
    })
    assert created.status_code == 201, created.text
    artifact_id = created.json()["artifact"]["artifact_id"]
    headers = dict(owner.headers) if identity in {"owner", "wrong_kind"} else invalid_context(identity, dict(owner.headers))
    if identity == "wrong_kind":
        artifact_id = chain["version"]["artifact"]["artifact_id"]
    with TestClient(main.app) as client:
        response = client.get(f"/v1/research/signal-snapshots/{artifact_id}", headers=headers)
    expected = 200 if identity == "owner" else 404 if identity in {"foreign", "wrong_kind"} else 401
    assert response.status_code == expected, response.text
    if identity == "owner":
        assert response.json()["snapshot"] == created.json()["artifact"]
    else:
        assert "content" not in response.json()
    store.close()
    jobs.close()


def test_product_agent_cannot_import_raw_signals(monkeypatch, tmp_path):
    store, jobs, _, owner = _fresh_harness(monkeypatch, tmp_path)
    chain = _create_strategy_chain(owner, key="signal-import-actor")
    headers = {**dict(owner.headers), "x-byq-actor-principal": "byq-product-agent-byq-session-product-user"}
    before = store.list_artifacts(owner_principal="product-user")
    response = owner.post("/v1/research/signal-snapshots", headers=headers, json={
        **_snapshot_input(), "task_id": chain["task"]["task_id"],
        "strategy_version_artifact_id": chain["version"]["artifact"]["artifact_id"],
        "trace_id": "trace-signal-import", "idempotency_key": "signal-import",
    })
    assert response.status_code == 403, response.text
    assert store.list_artifacts(owner_principal="product-user") == before
    store.close()
    jobs.close()
