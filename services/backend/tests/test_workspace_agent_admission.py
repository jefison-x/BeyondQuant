from __future__ import annotations

import os
import uuid

import pytest

from app.agent_research import AgentConflict, AgentResearchStore
from tests.test_agent_run_lifecycle import _ensure_runtime_boot, apply
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"), reason="requires isolated PostgreSQL",
)


def _context(owner: str, session_id: str) -> dict[str, str]:
    return trusted_agent_context(
        owner,
        actor=f"byq-product-agent-{session_id}",
        session_id=session_id,
        trace_id=f"trace-{session_id}",
        dsh_run_id=f"generation-{session_id}",
    )


def _admission(store: AgentResearchStore, context: dict[str, str], root: str, boot: str) -> dict:
    return store.workspace_agent_admission(
        owner_principal=context["x-byq-owner-principal"],
        workspace_id=context["x-byq-workspace-id"],
        root_run_id=root,
        session_id=context["x-byq-session-id"],
        boot_id=boot,
    )


def test_workspace_admission_serializes_unsettled_roots_and_survives_boot_rotation():
    alice = _context(f"acp_slot_alice_{uuid.uuid4().hex[:10]}", "slot-session-one")
    alice_next = _context(alice["x-byq-owner-principal"], "slot-session-two")
    bob = _context(f"acp_slot_bob_{uuid.uuid4().hex[:10]}", "slot-session-bob")
    store = AgentResearchStore()
    try:
        boot = _ensure_runtime_boot(store, alice)
        _ensure_runtime_boot(store, alice_next)
        _ensure_runtime_boot(store, bob)

        first_root = uuid.uuid4().hex
        apply(store, alice, first_root, key="slot-first-root")

        # The exact active root may be resumed in its own scope, but a second
        # root cannot enter this Workspace while its business result is open.
        assert _admission(store, alice, first_root, boot)["can_start"] is True
        assert _admission(store, alice_next, uuid.uuid4().hex, boot)["can_start"] is False

        # Capacity is scoped by trusted Workspace identity; another personal
        # Workspace remains independent while Alice's root is active.
        assert _admission(store, bob, uuid.uuid4().hex, boot)["can_start"] is True

        closed = store.close_runtime_root(
            first_root, boot_id=boot, sequence=2, outcome="completed",
            event_sha256="a" * 64,
        )
        assert closed["root_run_id"] == first_root
        assert _admission(store, alice_next, uuid.uuid4().hex, boot)["can_start"] is True

        # A still-active root from the old Adapter boot has an unknown business
        # outcome. Rotating authority must keep the group fenced across restart.
        second_root = uuid.uuid4().hex
        apply(store, alice_next, second_root, key="slot-second-root")
        next_boot = uuid.uuid4().hex
        store.rotate_runtime_authority(next_boot)
        assert _admission(store, alice_next, uuid.uuid4().hex, next_boot)["can_start"] is False
        with pytest.raises(AgentConflict, match="current workspace authority"):
            _admission(store, alice_next, second_root, next_boot)
        assert _admission(store, bob, uuid.uuid4().hex, next_boot)["can_start"] is True
    finally:
        store.close()
