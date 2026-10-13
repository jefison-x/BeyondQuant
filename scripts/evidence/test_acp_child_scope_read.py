"""Offline contract tests for the bounded ACP child-scope SQL reader.

Fixtures mirror the current PostgreSQL DDL. These tests do not open a database
connection or invoke psql; the reader's executable contract is SQL construction
plus strict validation of the returned projection.
"""

from __future__ import annotations

import importlib.util
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SOURCE = Path(__file__).with_name("acp-child-scope-read.py")
SPEC = importlib.util.spec_from_file_location("acp_child_scope_read", SOURCE)
assert SPEC is not None and SPEC.loader is not None
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)


SCOPE = {
    "workspace_id": "workspace-test",
    "owner_principal": "owner-test",
    "session_id": "session-test",
    "trace_id": "trace-test",
    "root_run_id": "a" * 32,
    "runtime_boot_id": "b" * 32,
    "generation_id": "generation-" + "c" * 32,
    "cwd_leaf": "session-" + "d" * 32,
    "actor_principal": "byq-product-agent-session-test",
}


def root_row(**overrides):
    row = {
        "root_run_id": SCOPE["root_run_id"],
        "owner_principal": SCOPE["owner_principal"],
        "workspace_id": SCOPE["workspace_id"],
        "session_id": SCOPE["session_id"],
        "trace_id": SCOPE["trace_id"],
        "status": "active",
        "authority_status": "active",
        "authority_boot_id": SCOPE["runtime_boot_id"],
        "terminal_sequence": None,
        "terminal_event_sha256": None,
        "terminal_acp_ingress_sequence": None,
        "terminal_acp_ingress_sha256": None,
        "terminal_unknown_claim_count": None,
        "terminal_unknown_claims_sha256": None,
    }
    row.update(overrides)
    return row


def registration(native_id, run_id, *, origin="root", depth=0,
                  native_root=None, native_parent=None, parent_run=None,
                  **overrides):
    root_registration = origin == "root" and depth == 0
    row = {
        # These keys correspond to the actual agent_acp_native_agent_registrations
        # and agent_runs DDL, including agent_run_id NOT NULL and parent_run_id.
        "root_run_id": SCOPE["root_run_id"],
        "native_agent_session_id": native_id,
        "native_root_session_id": native_root or "native-root",
        "native_parent_session_id": native_parent,
        "owner_principal": SCOPE["owner_principal"],
        "workspace_id": SCOPE["workspace_id"],
        "actor_principal": SCOPE["actor_principal"],
        "session_id": SCOPE["session_id"],
        "trace_id": SCOPE["trace_id"],
        "dsh_run_id": SCOPE["generation_id"],
        "runtime_boot_id": SCOPE["runtime_boot_id"],
        "origin": origin,
        "depth": depth,
        "agent_run_id": run_id,
        "parent_run_id": parent_run,
        "registration_status": "bound",
        "joined_run_id": run_id,
        "run_owner": SCOPE["owner_principal"],
        "run_actor": SCOPE["actor_principal"],
        "run_trace": SCOPE["trace_id"],
        "run_session": SCOPE["session_id"],
        # DDL's agent_runs.dsh_run_id is projected as run_generation.
        "run_generation": SCOPE["generation_id"],
        "run_root": SCOPE["root_run_id"],
        "run_parent": parent_run,
        "run_boot": SCOPE["runtime_boot_id"],
        "run_role_id": "quant_orchestrator" if root_registration else "market_researcher",
        "run_role_version": "2.5.0" if root_registration else "1.4.0",
        "run_status": "completed",
        "run_authority_status": "closed",
    }
    row.update(overrides)
    return row


def ingress_row(*, native_id="native-child", run_id="run-child", origin="subagent",
                depth=1, native_root="native-root", native_parent="native-root",
                status="settled", **overrides):
    row = {
        "mcp_request_id": "1" * 32,
        "root_run_id": SCOPE["root_run_id"],
        "owner_principal": SCOPE["owner_principal"],
        "workspace_id": SCOPE["workspace_id"],
        "actor_principal": SCOPE["actor_principal"],
        "session_id": SCOPE["session_id"],
        "trace_id": SCOPE["trace_id"],
        "dsh_run_id": SCOPE["generation_id"],
        "runtime_boot_id": SCOPE["runtime_boot_id"],
        "native_root_session_id": native_root,
        "native_agent_session_id": native_id,
        "native_parent_session_id": native_parent,
        "origin": origin,
        "depth": depth,
        "agent_run_id": run_id,
        "tool_name": "byq_example_tool",
        "arguments_sha256": "2" * 64,
        "sequence": 1,
        "event_sha256": "3" * 64,
        "status": status,
        "settlement_outcome": "settled" if status == "settled" else None,
        "settlement_sha256": "4" * 64 if status == "settled" else None,
    }
    row.update(overrides)
    return row


def audit_row(*, native_id="native-child", run_id="run-child", **overrides):
    row = {
        "root_run_id": SCOPE["root_run_id"],
        "native_agent_session_id": native_id,
        "audit_id": "audit-test",
        "run_id": run_id,
        "owner_principal": SCOPE["owner_principal"],
        "actor_principal": SCOPE["actor_principal"],
        "action": "agent_run_completed",
        "outcome": "success",
        "created_at": "2026-10-13T00:00:00+00:00",
    }
    row.update(overrides)
    return row


def projection(mode, registrations=(), *, roots=None, ingress=(), audits=()):
    roots = [root_row()] if roots is None else roots
    registrations = list(registrations)
    ingress = list(ingress)
    audits = list(audits)
    return {
        "schema_version": reader.SCHEMA,
        "mode": mode,
        "foreign_mismatch_count": 0,
        "root_count": len(roots),
        "roots": roots,
        "registration_count": len(registrations),
        "registrations": registrations,
        "ingress_count": len(ingress),
        "ingress": ingress,
        "audit_count": len(audits),
        "audits": audits,
    }


class ChildScopeReadContractTests(unittest.TestCase):
    def test_preflight_accepts_one_real_root_and_zero_native_registrations(self):
        result = reader.validate_projection(SCOPE, "preflight", projection("preflight"))
        self.assertEqual(result["root"]["root_run_id"], SCOPE["root_run_id"])
        self.assertEqual(result["registration_count"], 0)
        self.assertEqual(result["registrations"], [])

        observed_pending = registration("native-root", "run-root",
                                        registration_status="pending")
        pending_result = reader.validate_projection(
            SCOPE, "preflight", projection("preflight", [observed_pending]))
        self.assertEqual(pending_result["registration_count"], 1)
        self.assertEqual(pending_result["registrations"][0]["registration_status"], "pending")

    def test_root_child_requires_exact_root_child_and_agent_run_parent_chain(self):
        root = registration("native-root", "run-root")
        child = registration("native-child", "run-child", origin="subagent", depth=1,
                             native_root="native-root", native_parent="native-root",
                             parent_run="run-root")
        result = reader.validate_projection(SCOPE, "root_child",
                                            projection("root_child", [root, child]))
        self.assertEqual(result["registration_count"], 2)
        self.assertEqual(result["registrations"][1]["parent_run_id"], "run-root")
        self.assertEqual(result["registrations"][0]["run_role_id"], "quant_orchestrator")
        self.assertEqual(result["registrations"][1]["run_role_id"], "market_researcher")
        self.assertEqual(result["registrations"][1]["run_role_version"], "1.4.0")

    def test_root_child_requires_exact_roles_and_closed_agent_runs(self):
        root = registration("native-root", "run-root")
        child = registration("native-child", "run-child", origin="subagent", depth=1,
                             native_root="native-root", native_parent="native-root",
                             parent_run="run-root")
        for changed, expected in (
            (dict(root, run_role_id="market_researcher"), "root_child_roles_or_terminal_state_invalid"),
            (dict(child, run_role_version="1.4"), "registration_run_mismatch"),
            (dict(child, run_status="running", run_authority_status="active"),
             "root_child_roles_or_terminal_state_invalid"),
        ):
            rows = [root, changed] if changed is not root and changed.get("origin") == "subagent" else [changed, child]
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(reader.ScopeReadError, expected):
                    reader.validate_projection(SCOPE, "root_child", projection("root_child", rows))

    def test_foreign_scope_row_and_wrong_boot_are_rejected(self):
        foreign = registration("native-root", "run-root", workspace_id="another-workspace")
        with self.assertRaisesRegex(reader.ScopeReadError, "registration_scope_mismatch"):
            reader.validate_projection(SCOPE, "preflight", projection("preflight", [foreign]))

        wrong_boot = root_row(authority_boot_id="e" * 32)
        with self.assertRaisesRegex(reader.ScopeReadError, "root_scope_mismatch"):
            reader.validate_projection(SCOPE, "preflight",
                                       projection("preflight", roots=[wrong_boot]))

        foreign_rows = projection("preflight")
        foreign_rows["foreign_mismatch_count"] = 1
        with self.assertRaisesRegex(reader.ScopeReadError, "foreign_scope_or_run_rows"):
            reader.validate_projection(SCOPE, "preflight", foreign_rows)

    def test_missing_root_and_wrong_actor_fail_closed(self):
        with self.assertRaisesRegex(reader.ScopeReadError, "root_scope_not_unique"):
            reader.validate_projection(SCOPE, "preflight",
                                       projection("preflight", roots=[]))

        wrong_actor = dict(SCOPE, actor_principal="byq-product-agent-someone-else")
        with self.assertRaisesRegex(reader.ScopeReadError, "actor_scope_invalid"):
            reader.build_sql(wrong_actor, "preflight")

    def test_multiple_matching_roots_fail_closed_and_sql_is_exactly_scope_filtered(self):
        with self.assertRaisesRegex(reader.ScopeReadError, "root_scope_not_unique"):
            reader.validate_projection(SCOPE, "preflight",
                                       projection("preflight", roots=[root_row(), root_row(
                                           root_run_id="f" * 32)]))
        sql = reader.build_sql(SCOPE, "root_child")
        for predicate in (
            f"root_run_id='{SCOPE['root_run_id']}'",
            f"owner_principal='{SCOPE['owner_principal']}'",
            f"workspace_id='{SCOPE['workspace_id']}'",
            f"session_id='{SCOPE['session_id']}'",
            f"trace_id='{SCOPE['trace_id']}'",
            f"authority_boot_id='{SCOPE['runtime_boot_id']}'",
        ):
            with self.subTest(predicate=predicate):
                self.assertIn(predicate, sql)

    def test_closed_terminal_shape_and_active_null_terminal_fields(self):
        active = root_row()
        terminal_columns = (
            "terminal_sequence", "terminal_event_sha256", "terminal_acp_ingress_sequence",
            "terminal_acp_ingress_sha256", "terminal_unknown_claim_count",
            "terminal_unknown_claims_sha256",
        )
        self.assertTrue(all(active[column] is None for column in terminal_columns))
        reader.validate_projection(SCOPE, "preflight", projection("preflight", roots=[active]))

        closed = root_row(status="completed", authority_status="closed",
                          terminal_sequence=7, terminal_event_sha256="5" * 64,
                          terminal_acp_ingress_sequence=0,
                          terminal_acp_ingress_sha256="6" * 64,
                          terminal_unknown_claim_count=0,
                          terminal_unknown_claims_sha256="7" * 64)
        reader.validate_projection(SCOPE, "preflight", projection("preflight", roots=[closed]))
        partial_active = root_row(status="active", terminal_sequence=7)
        with self.assertRaisesRegex(reader.ScopeReadError, "active_root_terminal_fields_invalid"):
            reader.validate_projection(SCOPE, "preflight",
                                       projection("preflight", roots=[partial_active]))
        incomplete_terminal = root_row(
            status="completed", authority_status="closed", terminal_sequence=None,
            terminal_event_sha256="5" * 64, terminal_acp_ingress_sequence=0,
            terminal_acp_ingress_sha256="6" * 64, terminal_unknown_claim_count=0,
            terminal_unknown_claims_sha256="7" * 64,
        )
        with self.assertRaisesRegex(reader.ScopeReadError, "terminal_root_fields_invalid"):
            reader.validate_projection(SCOPE, "preflight",
                                       projection("preflight", roots=[incomplete_terminal]))

    def test_ingress_and_audit_are_scope_bound_and_settlement_is_projected(self):
        root = registration("native-root", "run-root")
        child = registration("native-child", "run-child", origin="subagent", depth=1,
                             native_root="native-root", native_parent="native-root",
                             parent_run="run-root")
        ingress = ingress_row()
        audit = audit_row()
        result = reader.validate_projection(
            SCOPE, "root_child",
            projection("root_child", [root, child], ingress=[ingress], audits=[audit]),
        )
        self.assertEqual(result["ingress_count"], 1)
        self.assertEqual(result["ingress"][0]["settlement_outcome"], "settled")
        self.assertEqual(result["ingress"][0]["settlement_sha256"], "4" * 64)
        self.assertEqual(result["audits"][0]["run_id"], "run-child")

        # The server does not emit an ingress observation for this bootstrap
        # tool. Even if one is supplied, it cannot be admitted without its
        # registered native session and AgentRun binding.
        unregistered_bootstrap = ingress_row(
            native_id="native-root", run_id=None, origin="root", depth=0,
            native_root="native-root", native_parent=None, status="pending",
            tool_name="byq_agent_run_start", settlement_outcome=None,
            settlement_sha256=None,
        )
        with self.assertRaisesRegex(reader.ScopeReadError, "ingress_registration_mismatch"):
            reader.validate_projection(
                SCOPE, "preflight",
                projection("preflight", ingress=[unregistered_bootstrap]),
            )

        foreign_ingress = ingress_row(workspace_id="workspace-foreign")
        with self.assertRaisesRegex(reader.ScopeReadError, "ingress_scope_mismatch"):
            reader.validate_projection(
                SCOPE, "root_child",
                projection("root_child", [root, child], ingress=[foreign_ingress]),
            )
        foreign_audit = audit_row(actor_principal="foreign-actor")
        with self.assertRaisesRegex(reader.ScopeReadError, "audit_scope_mismatch"):
            reader.validate_projection(
                SCOPE, "root_child",
                projection("root_child", [root, child], audits=[foreign_audit]),
            )
        duplicate_audit = audit_row(audit_id="same-audit")
        duplicate_audit_2 = audit_row(audit_id="same-audit", action="different-action")
        with self.assertRaisesRegex(reader.ScopeReadError, "audit_duplicate_id"):
            reader.validate_projection(
                SCOPE, "root_child",
                projection("root_child", [root, child], audits=[duplicate_audit, duplicate_audit_2]),
            )

    def test_pending_child_registration_is_not_a_qualified_child(self):
        root = registration("native-root", "run-root")
        pending_child = registration("native-child", "run-child", origin="subagent", depth=1,
                                     native_root="native-root", native_parent="native-root",
                                     parent_run="run-root", registration_status="pending")
        with self.assertRaisesRegex(reader.ScopeReadError, "root_child_registration_unbound"):
            reader.validate_projection(SCOPE, "root_child",
                                       projection("root_child", [root, pending_child]))

    def test_root_child_requires_distinct_native_and_agent_run_identities(self):
        root = registration("native-root", "run-root")
        child_same_native = registration("native-root", "run-child", origin="subagent", depth=1,
                                         native_root="native-root", native_parent="native-root",
                                         parent_run="run-root")
        with self.assertRaisesRegex(reader.ScopeReadError, "registration_identity_invalid"):
            reader.validate_projection(SCOPE, "root_child",
                                       projection("root_child", [root, child_same_native]))
        child_same_run = registration("native-child", "run-root", origin="subagent", depth=1,
                                      native_root="native-root", native_parent="native-root",
                                      parent_run="run-root")
        with self.assertRaisesRegex(reader.ScopeReadError, "root_child_parent_mismatch"):
            reader.validate_projection(SCOPE, "root_child",
                                       projection("root_child", [root, child_same_run]))
        malformed_root_native = registration("native-root", "run-root",
                                              native_root="different-native-root")
        child = registration("native-child", "run-child", origin="subagent", depth=1,
                             native_root="different-native-root", native_parent="native-root",
                             parent_run="run-root")
        with self.assertRaisesRegex(reader.ScopeReadError, "root_child_parent_mismatch"):
            reader.validate_projection(SCOPE, "root_child",
                                       projection("root_child", [malformed_root_native, child]))

    def test_ingress_settlement_statuses_have_exact_digest_shapes(self):
        root = registration("native-root", "run-root")
        child = registration("native-child", "run-child", origin="subagent", depth=1,
                             native_root="native-root", native_parent="native-root",
                             parent_run="run-root")
        pending = ingress_row(status="pending", settlement_outcome=None, settlement_sha256=None)
        settled = ingress_row(status="settled", settlement_outcome="settled",
                              settlement_sha256="9" * 64)
        denied = ingress_row(status="settled", settlement_outcome="denied",
                             settlement_sha256="a" * 64)
        aborted = ingress_row(status="settled", settlement_outcome="aborted_before_dispatch",
                              settlement_sha256="b" * 64)
        unknown = ingress_row(status="unknown", settlement_outcome="unknown",
                              settlement_sha256="8" * 64)
        for row in (pending, settled, denied, aborted, unknown):
            result = reader.validate_projection(
                SCOPE, "root_child",
                projection("root_child", [root, child], ingress=[row]),
            )
            self.assertEqual(result["ingress_count"], 1)
        malformed_pending = ingress_row(status="pending", settlement_outcome="settled",
                                        settlement_sha256="4" * 64)
        with self.assertRaisesRegex(reader.ScopeReadError, "pending_ingress_settlement_invalid"):
            reader.validate_projection(
                SCOPE, "root_child",
                projection("root_child", [root, child], ingress=[malformed_pending]),
            )
        malformed_settled = ingress_row(status="settled", settlement_outcome="unknown",
                                        settlement_sha256="4" * 64)
        with self.assertRaisesRegex(reader.ScopeReadError, "settled_ingress_settlement_invalid"):
            reader.validate_projection(
                SCOPE, "root_child",
                projection("root_child", [root, child], ingress=[malformed_settled]),
            )
        malformed_unknown = ingress_row(status="unknown", settlement_outcome="unknown",
                                        settlement_sha256=None)
        with self.assertRaisesRegex(reader.ScopeReadError, "unknown_ingress_settlement_invalid"):
            reader.validate_projection(
                SCOPE, "root_child",
                projection("root_child", [root, child], ingress=[malformed_unknown]),
            )

    def test_cli_rejects_duplicate_keys_and_oversized_stdin(self):
        duplicate = b'{"mode":"preflight","mode":"root_child","scope":{}}'
        output, error = io.StringIO(), io.StringIO()
        with patch.object(reader, "sys", SimpleNamespace(
                stdin=SimpleNamespace(buffer=io.BytesIO(duplicate)), stdout=output, stderr=error)):
            self.assertEqual(reader.main(), 2)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("SCOPE_READ_STOP:json_duplicate_key", error.getvalue())

        output, error = io.StringIO(), io.StringIO()
        with patch.object(reader, "sys", SimpleNamespace(
                stdin=SimpleNamespace(buffer=io.BytesIO(b" " * 16_385)),
                stdout=output, stderr=error)):
            self.assertEqual(reader.main(), 2)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("SCOPE_READ_STOP:request_too_large", error.getvalue())

    def test_two_children_cannot_be_misreported_as_one_child_scope(self):
        root = registration("native-root", "run-root")
        child_a = registration("native-child-a", "run-child-a", origin="subagent", depth=1,
                                native_root="native-root", native_parent="native-root",
                                parent_run="run-root")
        child_b = registration("native-child-b", "run-child-b", origin="subagent", depth=1,
                                native_root="native-root", native_parent="native-root",
                                parent_run="run-root")
        with self.assertRaisesRegex(reader.ScopeReadError, "registrations_projection_invalid"):
            reader.validate_projection(SCOPE, "root_child",
                                       projection("root_child", [root, child_a, child_b]))

    def test_duplicate_native_identity_and_wrong_parent_run_are_rejected(self):
        root = registration("native-root", "run-root")
        duplicate = registration("native-root", "run-child", origin="subagent", depth=1,
                                 native_root="native-root", native_parent="native-root",
                                 parent_run="run-root")
        with self.assertRaisesRegex(reader.ScopeReadError, "registration_identity_invalid"):
            reader.validate_projection(SCOPE, "root_child",
                                       projection("root_child", [root, duplicate]))

        wrong_parent = registration("native-child", "run-child", origin="subagent", depth=1,
                                    native_root="native-root", native_parent="native-root",
                                    parent_run="run-other")
        with self.assertRaisesRegex(reader.ScopeReadError, "root_child_parent_mismatch"):
            reader.validate_projection(SCOPE, "root_child",
                                       projection("root_child", [root, wrong_parent]))

    def test_sql_uses_existing_ddl_columns_and_one_read_only_transaction(self):
        sql = reader.build_sql(SCOPE, "root_child")
        self.assertTrue(sql.startswith("BEGIN READ ONLY;"))
        self.assertTrue(sql.rstrip().endswith("COMMIT;"))
        self.assertIn("ar.dsh_run_id AS run_generation", sql)
        self.assertNotIn("ar.workspace_id", sql)
        self.assertNotIn("ar.generation", sql)
        self.assertIn("agent_acp_native_agent_registrations", sql)
        self.assertIn("agent_runtime_turns", sql)
        self.assertIn("agent_runs ar ON ar.run_id=n.agent_run_id", sql)
        # AgentRun roles are read from the real agent_runs table and are part
        # of the closed root/child contract; they are not inferred from native
        # session events or supplied by the test transport.
        self.assertIn("ar.role_id AS run_role_id", sql)
        self.assertIn("ar.role_version AS run_role_version", sql)
        # Protect raw query output too: same-root registrations/ingress/audit
        # records from another scope must not be materialized before validation.
        for column, scope_key in (
            ("owner_principal", "owner_principal"), ("workspace_id", "workspace_id"),
            ("actor_principal", "actor_principal"), ("session_id", "session_id"),
            ("trace_id", "trace_id"), ("dsh_run_id", "generation_id"),
            ("runtime_boot_id", "runtime_boot_id"),
        ):
            self.assertIn(f"{column}={reader._quote(SCOPE[scope_key])}", sql)
        self.assertIn("n.root_run_id=rs.root_run_id", sql)
        self.assertIn("i.root_run_id=rs.root_run_id", sql)
        self.assertIn(f"c.owner_principal={reader._quote(SCOPE['owner_principal'])}", sql)
        self.assertIn(f"c.actor_principal={reader._quote(SCOPE['actor_principal'])}", sql)

    def test_invalid_identity_never_becomes_a_quoted_sql_command(self):
        for value in ("' OR 1=1 --", "x\x00y", "short"):
            with self.subTest(value=value):
                invalid = dict(SCOPE, root_run_id=value)
                with self.assertRaises(reader.ScopeReadError):
                    reader.build_sql(invalid, "preflight")


if __name__ == "__main__":
    unittest.main(verbosity=2)
