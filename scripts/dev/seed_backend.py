"""Create a small, idempotent fixture in an isolated BYQ development database.

This Engineering Plane script is mounted for ``make dev-seed``. It is not
included in the Product Backend image or exposed as an API.
"""

from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit

from app.research import ResearchStore
from app.strategy_artifact import prepare_strategy_draft, strategy_draft_content
from app.user_auth import UserAuthStore
from app.workspace_tenancy import WorkspaceTenancyStore


SEED_TRACE = "dev_seed_v1"
SEED_TASK_KEY = "dev-seed-research-v1"
SEED_STRATEGY_KEY = "dev-seed-strategy-v1"
SEED_DATASET_KEY = "dev-seed-dataset-v1"


def seed() -> dict[str, str]:
    scope = os.environ.get("BYQ_DEV_SCOPE", "")
    if not re.fullmatch(r"byq-dev-[0-9a-f]{10}", scope) or os.environ.get("COMPOSE_PROJECT_NAME") != scope:
        raise RuntimeError("dev seed requires an isolated BYQ development scope")
    database = urlsplit(os.environ.get("BYQ_DATABASE_URL", ""))
    if (database.scheme != "postgresql+psycopg" or database.hostname != "postgres"
            or database.port != 5432 or not database.username or not database.path.strip("/")):
        raise RuntimeError("dev seed requires its Compose PostgreSQL database")
    owner = os.environ.get("BYQ_BOOTSTRAP_ADMIN_USERNAME", "")
    password = os.environ.get("BYQ_BOOTSTRAP_ADMIN_PASSWORD", "")
    if not owner or not password:
        raise RuntimeError("dev seed requires bootstrap admin configuration")

    users = UserAuthStore()
    research = ResearchStore()
    tenancy = WorkspaceTenancyStore()
    try:
        admin = users.ensure_bootstrap_admin(owner, password)
        if admin["username"] != owner or admin["role"] != "admin":
            raise RuntimeError("dev bootstrap admin does not match the isolated configuration")
        workspace = tenancy.public_workspace(str(admin["user_id"]))
        reset_receipt = research._fetch_one("""SELECT reset_id FROM workspace_reset_receipts
            WHERE workspace_id=:workspace ORDER BY created_at DESC,reset_id DESC LIMIT 1""",
            {'workspace':workspace['workspace_id']})
        seed_generation = '' if reset_receipt is None else ':'+reset_receipt['reset_id']
        task = research.create_task({
            "owner_principal": owner,
            "title": "Development research fixture",
            "objective": "Explore a synthetic momentum example using fresh BYQ data.",
            "trace_id": SEED_TRACE,
            "idempotency_key": SEED_TASK_KEY + seed_generation,
        })
        strategy = prepare_strategy_draft({
            "strategy_id": "DevMomentumSample",
            "name": "Development Momentum Sample",
            "category": "momentum",
            "description": "Synthetic development fixture; no live signals.",
            "parameters": {"lookback": 2},
            "parameter_schema": {"lookback": {"type": "integer", "minimum": 1}},
            "source_type": "python_script",
            "script": "class CustomStrategy:\n    def generate_signals(self, data, parameters=None):\n        return {}\n",
        })
        strategy_artifact = research.create_artifact({
            "task_id": task["task_id"],
            "kind": "strategy_draft",
            "content": strategy_draft_content(strategy),
            "lineage": [],
            "trace_id": SEED_TRACE,
            "idempotency_key": SEED_STRATEGY_KEY + seed_generation,
        }, trusted_owner=owner, trusted_workspace=workspace["workspace_id"])
        dataset_artifact = research.create_artifact({
            "task_id": task["task_id"],
            "kind": "dataset",
            "content": {
                "schema_version": "byq-dev-synthetic-bars.v1",
                "source": "synthetic_development_fixture",
                "symbol": "SYNTHETIC",
                "bars": [
                    {"date": "2026-01-02", "close": 10.0, "volume": 1000},
                    {"date": "2026-01-05", "close": 10.2, "volume": 1100},
                    {"date": "2026-01-06", "close": 10.1, "volume": 900},
                ],
            },
            "lineage": [],
            "trace_id": SEED_TRACE,
            "idempotency_key": SEED_DATASET_KEY + seed_generation,
        }, trusted_owner=owner, trusted_workspace=workspace["workspace_id"])
        return {"workspace_id": workspace["workspace_id"], "task_id": task["task_id"],
                "strategy_artifact_id": strategy_artifact["artifact_id"],
                "dataset_artifact_id": dataset_artifact["artifact_id"]}
    finally:
        tenancy.close()
        research.close()
        users.close()


if __name__ == "__main__":
    print(json.dumps(seed(), sort_keys=True))
