from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.research import ResearchStore
from app.user_auth import UserAuthStore
from app.workspace_tenancy import CONTRACT_VERSION, WorkspaceTenancyStore


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set"
)


def _create_user(store: UserAuthStore, username: str) -> dict[str, object]:
    return store.create_user(
        {"username": username, "password": "password123", "display_name": username.title()},
        actor_role="admin",
    )


def test_user_creation_atomically_provisions_one_personal_workspace() -> None:
    users = UserAuthStore()
    alice = _create_user(users, "alice")
    tenancy = WorkspaceTenancyStore()

    workspace = tenancy.get_personal_workspace(str(alice["user_id"]))
    assert workspace is not None
    assert workspace["kind"] == "personal"
    assert workspace["membership_role"] == "owner"
    assert workspace["membership_status"] == "active"

    assert tenancy.provision_all_users() == {"users": 1, "created": 0}
    with tenancy.engine.begin() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM workspaces")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM workspace_memberships")).scalar_one() == 1
    tenancy.close()
    users.close()


def test_backfill_maps_only_exact_durable_owner_and_reports_orphan() -> None:
    users = UserAuthStore()
    alice = _create_user(users, "alice")
    research = ResearchStore()
    mapped_task = research.create_task({
        "owner_principal": "alice", "title": "mapped", "objective": "test",
        "trace_id": "trace_mapped", "idempotency_key": "mapped-key",
    })
    research.transition("research_task", mapped_task["task_id"], "running", "transition-key")
    research.create_task({
        "owner_principal": "service:legacy", "title": "orphan", "objective": "test",
        "trace_id": "trace_orphan", "idempotency_key": "orphan-key",
    })
    tenancy = WorkspaceTenancyStore()
    dry_run = tenancy.backfill(dry_run=True)
    assert dry_run["run_id"] is None
    assert dry_run["tables"]["research_transitions"]["mapped"] == 1
    with tenancy.engine.begin() as connection:
        assert connection.execute(text(
            "SELECT workspace_id FROM research_tasks WHERE owner_principal = 'alice'"
        )).scalar_one_or_none() is None
        assert connection.execute(text("SELECT COUNT(*) FROM workspace_migration_runs")).scalar_one() == 0

    report = tenancy.backfill()

    assert report["contract"] == CONTRACT_VERSION
    assert report["verified"] is False
    assert report["tables"]["research_tasks"]["mapped"] == 1
    assert report["tables"]["research_transitions"]["mapped"] == 1
    assert report["tables"]["research_tasks"]["pending"] == 1
    assert any(item["owner_principal"] == "service:legacy" for item in report["quarantine"])

    workspace = tenancy.get_personal_workspace(str(alice["user_id"]))
    with tenancy.engine.begin() as connection:
        mapped = connection.execute(text(
            "SELECT workspace_id FROM research_tasks WHERE owner_principal = 'alice'"
        )).scalar_one()
        orphan = connection.execute(text(
            "SELECT workspace_id FROM research_tasks WHERE owner_principal = 'service:legacy'"
        )).scalar_one_or_none()
        transition_workspace = connection.execute(text(
            "SELECT workspace_id FROM research_transitions WHERE entity_id = :task_id"
        ), {"task_id": mapped_task["task_id"]}).scalar_one()
        run_count = connection.execute(text("SELECT COUNT(*) FROM workspace_migration_runs")).scalar_one()
    assert mapped == workspace["workspace_id"]
    assert transition_workspace == workspace["workspace_id"]
    assert orphan is None
    assert run_count == 1

    repeated = tenancy.backfill()
    assert repeated["tables"]["research_tasks"]["mapped"] == 0
    assert repeated["tables"]["research_tasks"]["already_mapped"] == 1
    tenancy.close()
    research.close()
    users.close()


def test_user_platform_and_engineering_tables_do_not_gain_workspace_column() -> None:
    users = UserAuthStore()
    _create_user(users, "alice")
    tenancy = WorkspaceTenancyStore()
    with tenancy.engine.begin() as connection:
        columns = {
            row[0]
            for row in connection.execute(text("""SELECT table_name FROM information_schema.columns
                WHERE column_name = 'workspace_id'"""))
        }
    assert "research_tasks" in columns
    assert "credentials" not in columns
    assert "user_ui_preferences" not in columns
    assert "user_agent_policy" not in columns
    assert "market_daily_bars" not in columns
    assert "engineering_tasks" not in columns
    tenancy.close()
    users.close()


def test_new_domain_writes_are_stamped_and_mismatched_workspace_is_rejected() -> None:
    users = UserAuthStore()
    alice = _create_user(users, "alice")
    bob = _create_user(users, "bob")
    tenancy = WorkspaceTenancyStore()
    research = ResearchStore()

    task = research.create_task({
        "owner_principal": "alice", "title": "owned", "objective": "boundary",
        "trace_id": "trace-owned", "idempotency_key": "owned-key",
    })
    alice_workspace = tenancy.public_workspace(str(alice["user_id"]))["workspace_id"]
    bob_workspace = tenancy.public_workspace(str(bob["user_id"]))["workspace_id"]
    with tenancy.engine.begin() as connection:
        assert connection.execute(
            text("SELECT workspace_id FROM research_tasks WHERE task_id = :task_id"),
            {"task_id": task["task_id"]},
        ).scalar_one() == alice_workspace

    with pytest.raises(DBAPIError, match="workspace owner mismatch"):
        with tenancy.engine.begin() as connection:
            connection.execute(
                text("UPDATE research_tasks SET workspace_id = :workspace_id WHERE task_id = :task_id"),
                {"workspace_id": bob_workspace, "task_id": task["task_id"]},
            )
    research.close()
    tenancy.close()
    users.close()


def test_verified_contract_makes_workspace_keys_mandatory() -> None:
    users = UserAuthStore()
    _create_user(users, "alice")
    tenancy = WorkspaceTenancyStore()
    report = tenancy.enforce_contract()
    assert report["status"] == "enforced"
    assert all(value == 0 for value in report["relation_checks"].values())
    with tenancy.engine.begin() as connection:
        nullable = connection.execute(text("""SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name = 'research_tasks' AND column_name = 'workspace_id'""")).scalar_one()
    assert nullable == "NO"
    tenancy.close()
    users.close()
