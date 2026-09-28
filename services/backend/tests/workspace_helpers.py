from __future__ import annotations

from app.user_auth import UserAuthStore
from app.workspace_tenancy import WorkspaceTenancyStore


def trusted_agent_context(
    owner: str,
    *,
    actor: str | None = None,
    trace_id: str = "trace-test",
    session_id: str = "session-test",
    dsh_run_id: str = "dsh-run-test",
) -> dict[str, str]:
    """Create a real personal workspace and return internal trusted headers."""

    users = UserAuthStore()
    existing = next(
        (item for item in users.list_users(actor_role="admin")["users"] if item["username"] == owner),
        None,
    )
    if existing is None:
        existing = users.create_user(
            {
                "username": owner,
                "password": "test-password-123",
                "display_name": owner,
            },
            actor_role="admin",
        )
    workspaces = WorkspaceTenancyStore()
    workspace = workspaces.public_workspace(str(existing["user_id"]))
    users.close()
    workspaces.close()
    return {
        "x-byq-workspace-id": workspace["workspace_id"],
        "x-byq-owner-principal": owner,
        "x-byq-actor-principal": actor or owner,
        "x-byq-trace-id": trace_id,
        "x-byq-session-id": session_id,
        "x-byq-dsh-run-id": dsh_run_id,
    }


def trusted_product_agent_context(owner: str, **kwargs: str) -> dict[str, str]:
    """Create a test Agent context bound to the current Backend boot."""
    from app.agent_research import AgentResearchStore

    headers = trusted_agent_context(owner, **kwargs)
    if not headers["x-byq-actor-principal"].startswith("byq-product-agent-"):
        raise ValueError("Product Agent test actor required")
    store = AgentResearchStore()
    try:
        current = store.current_runtime_authority()
        if current is None:
            current = store.rotate_runtime_authority("f" * 32)
        headers["x-byq-runtime-boot-id"] = current["boot_id"]
    finally:
        store.close()
    return headers
