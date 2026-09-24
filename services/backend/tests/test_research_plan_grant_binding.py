"""ADR-0085 P4 grant -> execution-plan reference binding (isolated PostgreSQL).

The trusted plan-creation seam must never build a plan from a stale grant or bind
an ambiguous/wrong artifact. These are fail-able tests over the real store.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.conversation_catalog import ConversationCatalogStore
from app.research import InvalidTransition, ResearchStore
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"),
                                reason="isolated PostgreSQL required")


def _setup(owner: str = "grant-user", session: str | None = None,
           trace: str | None = None):
    # Derive unique conversation/runtime identities per owner so a test suite that
    # creates several tasks never violates the product_conversations uniqueness.
    session = session or f"{owner}-session"
    trace = trace or f"{owner}-trace"
    headers = trusted_agent_context(owner, session_id=session, trace_id=trace)
    context = {key.removeprefix("x-byq-").replace("-", "_"): value
               for key, value in headers.items()}
    catalog = ConversationCatalogStore()
    catalog.create(owner, session, trace)
    catalog.close()
    store = ResearchStore()
    task = store.create_task(
        {"owner_principal": owner, "title": "Grant binding task",
         "objective": "Bind granted artifacts", "trace_id": trace,
         "idempotency_key": f"{owner}-task"},
        trusted_context=context)["task_id"]
    return store, task, context


def _artifact(store, task, *, kind: str = "strategy_version", key: str = "v1",
              status: str = "validated") -> tuple[str, str]:
    content = {"strategy_id": "S", "version": key} if kind == "strategy_version" \
        else {"synthetic": key}
    digest = "sha256:" + hashlib.sha256(
        json.dumps(content, sort_keys=True).encode()).hexdigest()
    artifact_id = "artifact_" + hashlib.sha256(
        f"{task}-{kind}-{key}".encode()).hexdigest()[:32]
    row = store._fetch_one("SELECT owner_principal, workspace_id FROM research_tasks "
                           "WHERE task_id = :t", {"t": task})
    now = datetime.now(timezone.utc)
    store._execute("""INSERT INTO artifacts
        (artifact_id, task_id, experiment_id, owner_principal, kind, status, content,
         content_sha256, lineage, trace_id, idempotency_key, request_hash, created_at,
         updated_at, version)
        VALUES (:id, :task, NULL, :owner, :kind, :status, :content, :digest, '[]'::jsonb,
                'grant-trace', :key, :key, :now, :now, 1)""",
        {"id": artifact_id, "task": task, "owner": row["owner_principal"], "kind": kind,
         "status": status, "content": json.dumps(content), "digest": digest, "key": key,
         "now": now})
    return artifact_id, digest


def _grant(store, task, entries: list[dict], *, revoked: bool = False,
           expired: bool = False) -> None:
    now = datetime.now(timezone.utc)
    ledger = {
        "idempotency_key": "grant", "token_limit": 1000, "grant_version": 1,
        "confirmed_artifact_ids": [entry["artifact_id"] for entry in entries],
        "confirmed_artifacts": entries,
        "expires_at": (now - timedelta(seconds=5) if expired else now + timedelta(hours=1)).isoformat(),
        "revoked_at": now.isoformat() if revoked else None,
        "owner_principal": "x", "workspace_id": "x", "handoff_version": 1,
    }
    store._execute("UPDATE research_tasks SET continuation_permission = :l "
                   "WHERE task_id = :t", {"l": ledger, "t": task})


def test_single_validated_version_is_deterministically_bound():
    store, task, context = _setup()
    try:
        artifact_id, digest = _artifact(store, task)
        _grant(store, task, [{"artifact_id": artifact_id, "content_sha256": digest}])
        plan = store.ensure_execution_plan(task, trusted_context=context)
        # The external plan projection is bounded and does not expose references;
        # verify the persisted plan's internal trusted references instead.
        assert "references" not in plan
        persisted = store._fetch_one(
            "SELECT plan FROM research_execution_plans WHERE task_id = :t",
            {"t": task})["plan"]
        assert persisted["references"]["strategy_version"] == {"strategy_version": artifact_id}
        assert persisted["stage"] == "strategy_draft"
    finally:
        store.close()


def test_revoked_and_expired_grants_cannot_create_a_plan():
    for kwargs in ({"revoked": True}, {"expired": True}):
        store, task, context = _setup(owner=f"grant-{list(kwargs)[0]}")
        try:
            artifact_id, digest = _artifact(store, task)
            _grant(store, task, [{"artifact_id": artifact_id, "content_sha256": digest}], **kwargs)
            with pytest.raises(InvalidTransition):
                store.ensure_execution_plan(task, trusted_context=context)
        finally:
            store.close()


def test_digest_or_status_change_fails_closed():
    for mutate in ("status", "digest"):
        store, task, context = _setup(owner=f"grant-{mutate}")
        try:
            artifact_id, digest = _artifact(store, task)
            entry = {"artifact_id": artifact_id, "content_sha256": digest}
            if mutate == "status":
                store._execute("UPDATE artifacts SET status = 'draft' WHERE artifact_id = :a",
                               {"a": artifact_id})
            else:
                entry["content_sha256"] = "sha256:" + "0" * 64
            _grant(store, task, [entry])
            with pytest.raises(InvalidTransition):
                store.ensure_execution_plan(task, trusted_context=context)
        finally:
            store.close()


def test_multiple_same_kind_confirmed_versions_fail_closed():
    store, task, context = _setup(owner="grant-ambiguous")
    try:
        first, first_digest = _artifact(store, task, key="v1")
        second, second_digest = _artifact(store, task, key="v2")
        assert first != second
        _grant(store, task, [
            {"artifact_id": first, "content_sha256": first_digest},
            {"artifact_id": second, "content_sha256": second_digest}])
        with pytest.raises(InvalidTransition):
            store.ensure_execution_plan(task, trusted_context=context)
    finally:
        store.close()


def test_create_plan_rechecks_the_grant_in_its_own_transaction():
    # Reproduces the ensure-read -> create-plan race: the grant is valid when read
    # but revoked before the plan transaction; create_execution_plan must refuse.
    store, task, context = _setup(owner="grant-race")
    try:
        artifact_id, digest = _artifact(store, task)
        _grant(store, task, [{"artifact_id": artifact_id, "content_sha256": digest}])
        _grant(store, task, [{"artifact_id": artifact_id, "content_sha256": digest}],
               revoked=True)
        with pytest.raises(InvalidTransition):
            store.create_execution_plan(
                task, {"idempotency_key": "plan-race"}, trusted_context=context,
                require_active_grant=True, bind_grant_references=True)
        assert store._fetch_one(
            "SELECT COUNT(*) AS c FROM research_execution_plans WHERE task_id = :t",
            {"t": task})["c"] == 0
    finally:
        store.close()


def test_creation_revalidates_artifacts_after_an_earlier_read():
    # The artifact is valid at ensure's early read, then goes invalid before the
    # plan transaction: creation must re-validate it and refuse (no plan).
    for mutate in ("status", "digest"):
        store, task, context = _setup(owner=f"grant-interleave-{mutate}")
        try:
            artifact_id, digest = _artifact(store, task)
            entry = {"artifact_id": artifact_id, "content_sha256": digest}
            _grant(store, task, [entry])
            # Simulate the invalidating change between the two phases.
            if mutate == "status":
                store._execute("UPDATE artifacts SET status = 'draft' WHERE artifact_id = :a",
                               {"a": artifact_id})
            else:
                store._execute("UPDATE artifacts SET content_sha256 = :d WHERE artifact_id = :a",
                               {"d": "sha256:" + "0" * 64, "a": artifact_id})
            with pytest.raises(InvalidTransition):
                store.create_execution_plan(
                    task, {"idempotency_key": "plan-interleave"}, trusted_context=context,
                    require_active_grant=True, bind_grant_references=True)
            assert store._fetch_one(
                "SELECT COUNT(*) AS c FROM research_execution_plans WHERE task_id = :t",
                {"t": task})["c"] == 0
        finally:
            store.close()


def test_missing_pinned_digest_fails_closed():
    # No ID-only fallback: a confirmed entry without the pinned digest is refused.
    store, task, context = _setup(owner="grant-no-digest")
    try:
        artifact_id, _ = _artifact(store, task)
        _grant(store, task, [{"artifact_id": artifact_id}])
        with pytest.raises(InvalidTransition):
            store.ensure_execution_plan(task, trusted_context=context)
    finally:
        store.close()


def _artifact_read_is_waiting_on_a_lock(store, *, timeout: float = 5.0) -> bool:
    """True once another session is observed waiting on an artifacts row lock.

    A row-lock wait appears in ``pg_locks`` as an ungranted ``transactionid``/
    ``tuple`` lock while the relation lock stays granted, so the reliable signal is
    a backend with ``wait_event_type = 'Lock'`` whose current statement reads the
    confirmed artifacts row.
    """

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = store._fetch_one(
            """SELECT COUNT(*) AS c FROM pg_stat_activity
               WHERE wait_event_type = 'Lock' AND query ILIKE '%FROM artifacts%'""")
        if row and row["c"]:
            return True
        time.sleep(0.02)
    return False


def test_plan_creation_is_serialized_against_a_concurrent_artifact_supersede():
    # Real two-transaction race: transaction A supersedes the confirmed artifact
    # and holds its row lock (FOR UPDATE) uncommitted. The plan transaction reads
    # the same artifact FOR SHARE, so it must block until A commits and then fail
    # closed; without the lock it would read the stale `validated` row and insert a
    # plan that references an already-superseded artifact.
    store, task, context = _setup(owner="grant-race-supersede")
    planner = ResearchStore()
    try:
        artifact_id, digest = _artifact(store, task)
        _grant(store, task, [{"artifact_id": artifact_id, "content_sha256": digest}])
        outcome: dict = {}
        started = threading.Event()

        def create_plan():
            started.set()
            try:
                outcome["plan"] = planner.create_execution_plan(
                    task, {"idempotency_key": "plan-race-supersede"},
                    trusted_context=context, require_active_grant=True,
                    bind_grant_references=True)
            except Exception as error:  # asserted below
                outcome["error"] = error

        with store._transaction() as connection:
            store.transition("artifact", artifact_id, "superseded", "race-supersede",
                             _connection=connection)
            worker = threading.Thread(target=create_plan)
            worker.start()
            assert started.wait(timeout=5)
            # The plan transaction must be observed waiting on the artifact lock,
            # proving the FOR SHARE read conflicts with the in-flight supersede.
            assert _artifact_read_is_waiting_on_a_lock(store), \
                "plan creation was not observed waiting on the artifact lock"
            assert worker.is_alive()
            assert store._fetch_one(
                "SELECT COUNT(*) AS c FROM research_execution_plans WHERE task_id = :t",
                {"t": task})["c"] == 0
        # A committed `superseded`; the plan transaction unblocks and re-reads.
        worker.join(timeout=10)
        assert not worker.is_alive()
        assert isinstance(outcome.get("error"), InvalidTransition)
        assert "plan" not in outcome
        assert store._fetch_one(
            "SELECT COUNT(*) AS c FROM research_execution_plans WHERE task_id = :t",
            {"t": task})["c"] == 0
    finally:
        planner.close()
        store.close()


def test_plan_created_before_a_later_supersede_keeps_its_valid_reference():
    # The safe ordering: the plan commits while the artifact is still validated,
    # and a later supersede is a separate transition that cannot retroactively
    # invalidate the already-created plan reference.
    store, task, context = _setup(owner="grant-plan-first")
    try:
        artifact_id, digest = _artifact(store, task)
        _grant(store, task, [{"artifact_id": artifact_id, "content_sha256": digest}])
        plan = store.ensure_execution_plan(task, trusted_context=context)
        assert plan["stage"] == "strategy_draft"
        store.transition("artifact", artifact_id, "superseded", "later-supersede")
        persisted = store._fetch_one(
            "SELECT plan FROM research_execution_plans WHERE task_id = :t",
            {"t": task})["plan"]
        assert persisted["references"]["strategy_version"] == \
            {"strategy_version": artifact_id}
    finally:
        store.close()
