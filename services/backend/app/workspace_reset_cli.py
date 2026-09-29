"""Offline reset of the current isolated development stack's Workspaces."""

from __future__ import annotations

import argparse
import json
import os
import re

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from .workspace_reset import WorkspaceNotFound, WorkspaceResetBlocked, WorkspaceResetStore


def _assert_isolated_stack() -> None:
    scope = os.environ.get("BYQ_DEV_SCOPE", "")
    if not re.fullmatch(r"byq-dev-[0-9a-f]{10}", scope):
        raise RuntimeError("isolated development scope required")
    if os.environ.get("COMPOSE_PROJECT_NAME") != scope:
        raise RuntimeError("development Compose project identity mismatch")
    database = make_url(os.environ.get("BYQ_DATABASE_URL", ""))
    if database.host != "postgres" or database.drivername != "postgresql+psycopg":
        raise RuntimeError("isolated Compose PostgreSQL connection required")


def reset_all() -> dict[str, int | str]:
    _assert_isolated_stack()
    store = WorkspaceResetStore()
    try:
        with store.engine.connect() as connection:
            present = connection.execute(text("""SELECT to_regclass('workspaces') AS workspaces,
                to_regclass('users') AS users""")).mappings().one()
            if present["workspaces"] is None and present["users"] is None:
                return {"schema_version": "dev-workspace-reset.v1", "workspaces_reset": 0}
            if present["workspaces"] is None or present["users"] is None:
                raise RuntimeError("development Workspace identity schema is incomplete")
            rows = connection.execute(text("""SELECT u.username AS owner_principal, w.workspace_id
                FROM workspaces w JOIN users u ON u.user_id=w.owner_user_id
                WHERE w.kind='personal' ORDER BY w.workspace_id""")).mappings().all()
        # The development stack is stopped, so this catches a blocked Workspace
        # before any other Workspace's data is committed away.
        for row in rows:
            store.reset_workspace(owner_principal=row["owner_principal"],
                                  workspace_id=row["workspace_id"], preview=True)
        for row in rows:
            store.reset_workspace(owner_principal=row["owner_principal"],
                                  workspace_id=row["workspace_id"])
        return {"schema_version": "dev-workspace-reset.v1", "workspaces_reset": len(rows)}
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-workspaces", action="store_true", required=True)
    parser.parse_args()
    try:
        print(json.dumps(reset_all(), sort_keys=True))
    except (RuntimeError, WorkspaceNotFound, WorkspaceResetBlocked, ArgumentError, SQLAlchemyError) as exc:
        # Never print a connection URL or raw SQL from a failing reset.
        print(f"Development Workspace reset refused: {type(exc).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
