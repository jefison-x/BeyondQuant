from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.research import ResearchStore
from app.user_auth import UserAuthStore
from app.workspace_tenancy import WorkspaceTenancyStore


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


def test_fresh_schema_omits_backfill_tables_and_keeps_workspace_tenancy() -> None:
    users = UserAuthStore()
    alice = _create_user(users, "alice")
    tenancy = WorkspaceTenancyStore()

    workspace = tenancy.get_personal_workspace(str(alice["user_id"]))
    assert workspace is not None
    assert workspace["kind"] == "personal"
    assert workspace["membership_role"] == "owner"
    assert workspace["membership_status"] == "active"

    with tenancy.engine.begin() as connection:
        relations = {
            name: connection.execute(
                text("SELECT to_regclass(:name)"), {"name": name}
            ).scalar_one()
            for name in (
                "workspaces",
                "workspace_memberships",
                "workspace_reset_receipts",
                "workspace_migration_runs",
                "workspace_migration_quarantine",
            )
        }
    assert relations["workspaces"] is not None
    assert relations["workspace_memberships"] is not None
    assert relations["workspace_reset_receipts"] is not None
    assert relations["workspace_migration_runs"] is None
    assert relations["workspace_migration_quarantine"] is None

    tenancy.close()
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

    with pytest.raises(DBAPIError, match="owner mismatch"):
        with tenancy.engine.begin() as connection:
            connection.execute(
                text("UPDATE research_tasks SET workspace_id = :workspace_id WHERE task_id = :task_id"),
                {"workspace_id": bob_workspace, "task_id": task["task_id"]},
            )
    assert research._fetch_one("SELECT workspace_id FROM research_tasks WHERE task_id=:task",
                               {"task": task["task_id"]})["workspace_id"] == alice_workspace
    research.close()
    tenancy.close()
    users.close()


def test_owner_trigger_does_not_read_conversation_fields_on_stock_pool_writes() -> None:
    users = UserAuthStore()
    alice = _create_user(users, "alice")
    tenancy = WorkspaceTenancyStore()
    workspace_id = tenancy.public_workspace(str(alice["user_id"]))["workspace_id"]
    with tenancy.engine.begin() as connection:
        connection.execute(text("""INSERT INTO stock_pool_write_idempotency
            (owner_principal, idempotency_key, action, request_hash, result_id, created_at)
            VALUES ('alice', 'stock-pool-create', 'create', 'hash', 'pool-1', now())"""))
        assert connection.execute(text("""SELECT workspace_id FROM stock_pool_write_idempotency
            WHERE owner_principal = 'alice'""")).scalar_one() == workspace_id
    tenancy.close()
    users.close()
