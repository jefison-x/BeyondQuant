"""0.9 closeout governance & gap ledger acceptance tests.

These tests assert the factual consistency of the audit batch only. They do not
implement anything: Proposed ADR-0082/0083 stay Proposed, the production DSH
selector/default is unchanged, no deployment happens, and no tag/release is
created or moved.

Runs under ``unittest`` (the architecture lane has no pytest).
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/v090-closeout"
LEDGER = EVIDENCE / "gap-ledger.v1.json"
MATRIX = EVIDENCE / "acceptance-matrix.v1.json"

STATUS_VOCABULARY = ["covered", "superseded", "open", "blocked"]
PRIMARY_BLOCKERS = (
    "subagent-child-crash",
    "subagent-byq-adapter-restart",
    "terminal-adapter-restart",
    "terminal-dsh-runtime-restart",
)
FORMAL_MANIFEST_IDS = (
    "formal-source-sha",
    "formal-ci-url",
    "formal-service-digests",
    "formal-actual-composition",
    "formal-migration-classification",
    "formal-sbom",
    "formal-backup",
    "formal-rollback",
    "formal-independent-acceptance",
    "formal-attestation",
)
AUDIT_BUILD_REVISION = "dsh-0.1.2rc1-post-u8.177"
# The closeout audit revision above is historical and stays immutable. Later
# maintenance batches that change build inputs advance the *selected* revision;
# the full-interface re-baseline batch moved it to .178 and the composite
# research fault-regression batch moved it to .179.
CURRENT_BUILD_REVISION = "dsh-0.1.2rc1-post-u8.179"


def _ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def _matrix() -> dict:
    return json.loads(MATRIX.read_text(encoding="utf-8"))


def _evidence_paths(value) -> list[str]:
    """Collect repo-relative evidence paths from a nested ledger/matrix value."""
    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for key, item in node.items():
                if key in {"evidence", "open_reason_evidence"} and isinstance(item, list):
                    for entry in item:
                        if isinstance(entry, str):
                            found.append(entry)
                        elif isinstance(entry, dict) and isinstance(entry.get("evidence"), str):
                            found.append(entry["evidence"])
                else:
                    walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    return found


def _topological_order(dag) -> tuple[dict, list[str]]:
    """Return (nodes, topological order); fail on an unknown edge or a cycle."""
    nodes = {node["id"]: node for node in dag["nodes"]}
    indegree = {node_id: 0 for node_id in nodes}
    adjacency = {node_id: [] for node_id in nodes}
    for node_id, node in nodes.items():
        for dependency in node.get("depends_on", []):
            if dependency not in nodes:
                raise AssertionError(f"unknown dag dependency: {dependency}")
            adjacency[dependency].append(node_id)
            indegree[node_id] += 1
    queue = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for neighbour in sorted(adjacency[current]):
            indegree[neighbour] -= 1
            if indegree[neighbour] == 0:
                queue.append(neighbour)
        queue.sort()
    if len(order) != len(nodes):
        raise AssertionError(f"dag cycle detected among: {sorted(set(nodes) - set(order))}")
    return nodes, order


class GapLedgerTests(unittest.TestCase):
    def test_schema_base_and_vocabulary(self):
        ledger = _ledger()
        self.assertEqual(ledger["schema_version"], "byq-v090-closeout-gap-ledger.v1")
        self.assertEqual(ledger["status_vocabulary"], STATUS_VOCABULARY)
        self.assertRegex(ledger["base"]["origin_main_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(ledger["base"]["product_phase_marker"], 97)

    def test_every_item_has_valid_status_and_existing_evidence(self):
        ledger = _ledger()
        self.assertTrue(ledger["items"])
        for item in ledger["items"]:
            self.assertIn(item["status"], STATUS_VOCABULARY, item["id"])
            self.assertTrue(item["evidence"], item["id"])
            for relative in _evidence_paths(item):
                self.assertTrue((ROOT / relative).is_file(), f"{item['id']}: {relative}")

    def test_expected_items_are_present(self):
        ids = {item["id"] for item in _ledger()["items"]}
        for required in ("F2", "S3", "full-interface-audit",
                         "composite-research-fault-regression", "H1-H5", "U8", "D15"):
            self.assertIn(required, ids)

    def test_summary_matches_items(self):
        ledger = _ledger()
        counts = {status: 0 for status in STATUS_VOCABULARY}
        for item in ledger["items"]:
            counts[item["status"]] += 1
        self.assertEqual(ledger["summary"], counts)

    def test_version_plan_gates_are_recorded(self):
        gates = {gate["id"]: gate for gate in _ledger()["version_plan_gates"]}
        self.assertEqual(set(gates), {"0.9.0", "0.9.x", "0.10.0"})
        for gate in gates.values():
            self.assertIn(gate["status"], STATUS_VOCABULARY)

    def test_s3_is_deferred_to_0_10_not_a_0_9_gate(self):
        ledger = _ledger()
        s3 = next(item for item in ledger["items"] if item["id"] == "S3")
        self.assertEqual(s3["status"], "superseded")
        self.assertEqual(s3["release_version"], "0.10.0")
        self.assertFalse(s3["gates_0_9_closeout"])
        self.assertTrue(s3["not_a_0_9_blocker"])
        self.assertIn("S3", ledger["deferred_to_0_10"])
        self.assertIn("S3", ledger["not_gating_0_9_closeout"])
        for entry in _matrix()["serial_order"]:
            self.assertNotIn("S3", entry, entry)
        x09_refs = {item["ledger_ref"] for item in _matrix()["x09_requirements"]}
        self.assertNotIn("S3", x09_refs)

    def test_d15_atomic_blockers_are_frozen(self):
        d15 = next(item for item in _ledger()["items"] if item["id"] == "D15")
        self.assertEqual(sorted(d15["atomic_blockers"]), sorted(PRIMARY_BLOCKERS))
        self.assertEqual(d15["sub_stage_results"]["D15-G"], "NO_GO")

    def test_constraints_are_frozen(self):
        constraints = _ledger()["constraints"]
        self.assertEqual(constraints["r3_resume"], "NO")
        self.assertEqual(constraints["production_selector"], "dsh-0.1.2rc1")
        self.assertTrue(constraints["production_default_unchanged"])
        self.assertEqual(constraints["deployment"], "none")
        self.assertFalse(constraints["release_or_tag_created"])
        for adr in ("adr_0082", "adr_0083"):
            self.assertIn("Proposed", constraints[adr])
            self.assertIn("not accepted", constraints[adr])
            self.assertIn("not implemented", constraints[adr])


class AcceptanceMatrixTests(unittest.TestCase):
    def test_schema_and_base(self):
        matrix = _matrix()
        self.assertEqual(matrix["schema_version"], "byq-v090-closeout-acceptance-matrix.v1")
        self.assertRegex(matrix["base"]["origin_main_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(matrix["base"]["audit_build_revision"], AUDIT_BUILD_REVISION)

    def test_all_formal_manifest_requirements_are_missing(self):
        requirements = _matrix()["formal_0_9_0_manifest_requirements"]
        self.assertEqual([item["id"] for item in requirements], list(FORMAL_MANIFEST_IDS))
        for item in requirements:
            self.assertEqual(item["status"], "missing", item["id"])

    def test_x09_requirements_reference_ledger_items(self):
        ledger_ids = {item["id"] for item in _ledger()["items"]}
        requirements = _matrix()["x09_requirements"]
        self.assertEqual(len(requirements), 3)
        for item in requirements:
            self.assertIn(item["status"], STATUS_VOCABULARY)
            self.assertIn(item["ledger_ref"], ledger_ids, item["id"])

    def test_dsh_blocker_slices_are_complete(self):
        slices = {item["blocker"]: item for item in _matrix()["dsh_0_1_5_rc1_closeout_slices"]
                  if item["blocker"]}
        self.assertEqual(sorted(slices), sorted(PRIMARY_BLOCKERS))
        dag_ids = {node["id"] for node in _matrix()["dag"]["nodes"]}
        for blocker, item in slices.items():
            self.assertTrue(item["implementation_owner"], blocker)
            self.assertTrue(item["owner_node"], blocker)
            self.assertIn(item["owner_node"], dag_ids, blocker)
            self.assertTrue(item["reproduction"]["steps"], blocker)
            self.assertTrue(item["reproduction"]["evidence"], blocker)
            self.assertTrue(item["acceptance_criteria"], blocker)
            self.assertTrue(item["failure_closure_criteria"], blocker)
            for relative in _evidence_paths(item):
                self.assertTrue((ROOT / relative).is_file(), f"{blocker}: {relative}")

    def test_dag_is_acyclic(self):
        nodes, topo = _topological_order(_matrix()["dag"])
        self.assertEqual(set(topo), set(nodes))
        self.assertEqual(len(topo), len(nodes))
        gate = _matrix()["dag"]["gate"]
        self.assertIn(gate, nodes)
        self.assertTrue(nodes[gate].get("gate"), gate)

    def test_blocker_owner_lies_before_the_gate(self):
        dag = _matrix()["dag"]
        nodes, topo = _topological_order(dag)
        index = {node_id: position for position, node_id in enumerate(topo)}
        gate = dag["gate"]
        post_gate = {node_id for node_id, node in nodes.items() if node.get("after_gate")}
        self.assertTrue(post_gate)
        for item in _matrix()["dsh_0_1_5_rc1_closeout_slices"]:
            if not item["blocker"]:
                continue
            owner = item["owner_node"]
            self.assertIn(owner, nodes, item["blocker"])
            self.assertLess(index[owner], index[gate], item["blocker"])
            self.assertNotIn(owner, post_gate, item["blocker"])

    def test_external_blocker_and_gate_order_options_are_recorded(self):
        matrix = _matrix()
        b1 = next(item for item in matrix["dsh_0_1_5_rc1_closeout_slices"]
                  if item["blocker"] == "subagent-child-crash")
        self.assertTrue(b1["external_blocker"]["is_external"])
        self.assertFalse(b1["external_blocker"]["available_in_0_1_5_rc1"])
        self.assertNotEqual(b1["owner_node"], "r6-full-runtime-continuity")
        option_ids = {item["id"] for item in matrix["maintainer_gate_order_options"]}
        self.assertTrue({"G-keep", "G-split", "G-reorder", "G-reclassify"} <= option_ids)

    def test_serial_order_gates_d15_g_before_r3(self):
        order = _matrix()["serial_order"]
        d15_g = next(i for i, value in enumerate(order) if "D15-G" in value)
        r3 = next(i for i, value in enumerate(order) if "R3" in value)
        r4 = next(i for i, value in enumerate(order) if "R4" in value)
        r6 = next(i for i, value in enumerate(order) if "R6" in value)
        production = next(i for i, value in enumerate(order) if "production Go/No-Go" in value)
        self.assertLess(d15_g, r3)
        self.assertLess(r3, r4)
        self.assertLess(r4, r6)
        self.assertLess(r6, production)

    def test_blockers_match_d15_g_primary_blockers(self):
        capability = json.loads(
            (ROOT / "docs/evidence/d15/d15-g/capability-matrix.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(capability["primary_named_blockers"]), sorted(PRIMARY_BLOCKERS))
        verdict = json.loads(
            (ROOT / "docs/evidence/d15/d15-g/verdict.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(verdict["verdict"], "NO_GO")
        self.assertEqual(sorted(verdict["derived_blockers"]), sorted(PRIMARY_BLOCKERS))

    def test_adr_sufficiency_stays_proposed(self):
        sufficiency = _matrix()["adr_sufficiency"]
        for name in ("ADR-0082", "ADR-0083"):
            self.assertIn("Proposed", sufficiency[name]["status"])
            self.assertFalse(sufficiency[name]["sufficient_to_resolve_blockers"], name)
            self.assertTrue(sufficiency[name]["required_revisions"], name)

    def test_matrix_constraints_and_non_authorizations(self):
        matrix = _matrix()
        self.assertEqual(matrix["constraints"]["r3_resume"], "NO")
        self.assertEqual(matrix["constraints"]["production_selector"], "dsh-0.1.2rc1")
        self.assertFalse(matrix["constraints"]["release_or_tag_created"])
        joined = " ".join(matrix["not_authorized_this_batch"]).lower()
        for phrase in ("adr-0082", "selector", "deployment", "tag/release"):
            self.assertIn(phrase, joined)


class GovernanceDocTests(unittest.TestCase):
    def _status(self) -> str:
        return (ROOT / "docs/roadmap/STATUS.md").read_text(encoding="utf-8")

    def _plan(self) -> str:
        return (ROOT / "docs/roadmap/IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")

    def test_status_freezes_phase_100_and_names_next_step(self):
        status = self._status()
        for marker in ("<!-- byq:v090-composite-research=active -->",
                       "<!-- byq:v090-closeout-audit=complete -->",
                       "<!-- byq:v090-full-interface-rebaseline=complete -->",
                       "<!-- byq:phase-100-slices-frozen=P100-C,P100-D,P100-E -->",
                       "<!-- byq:phase-100-p100-c=paused-not-delivery -->",
                       "<!-- byq:build-revision=dsh-0.1.2rc1-post-u8.179 -->"):
            self.assertIn(marker, status)
        # Completed historical 0.9 steps must not remain marked active.
        self.assertNotIn("v090-closeout-audit=active", status)
        self.assertNotIn("v090-full-interface-rebaseline=active", status)
        self.assertIn("<!-- byq:current-completed-phase=97 -->", status)
        self.assertIn("P100-A", status)
        self.assertIn("P100-B", status)
        self.assertIn("codex/phase-100c", status)
        self.assertIn("0.9 closeout governance & gap ledger audit", status)

    def test_implementation_plan_freezes_phase_100(self):
        plan = self._plan()
        self.assertIn("<!-- byq:phase-100-p100-c=paused-not-delivery -->", plan)
        self.assertIn("Phase 100 — 0.10 data baseline implementation (`PAUSED`)", plan)
        self.assertIn("0.9 Closeout Governance & Gap Ledger Audit", plan)
        self.assertIn("post-u8.174 → post-u8.177", plan)

    def test_version_plan_links_the_audit_and_the_beta_distinction(self):
        version_plan = (ROOT / "docs/roadmap/VERSION_PLAN.md").read_text(encoding="utf-8")
        self.assertIn("evidence/v090-closeout/", version_plan)
        self.assertIn("v0.9.0-beta", version_plan)

    def test_beta_doc_distinguishes_tag_from_formal_closeout(self):
        beta = (EVIDENCE / "BETA-VS-FORMAL-0.9.0.md").read_text(encoding="utf-8")
        self.assertIn("v0.9.0-beta", beta)
        self.assertIn("135bc7d3f34037689477c08231f1405197e27523", beta)
        self.assertIn("byq-release.v1", beta)
        for requirement in ("Source SHA", "All-service image digests", "Independent acceptance"):
            self.assertIn(requirement, beta)

    def test_readme_and_slices_link_the_adr_review(self):
        readme = (EVIDENCE / "README.md").read_text(encoding="utf-8")
        self.assertIn("ADR-0082-0083-SUFFICIENCY.md", readme)
        slices = (EVIDENCE / "DSH-015RC1-CLOSEOUT-SLICES.md").read_text(encoding="utf-8")
        for blocker in PRIMARY_BLOCKERS:
            self.assertIn(blocker, slices)


class NoImplementationTests(unittest.TestCase):
    def test_adr_0082_and_0083_remain_proposed(self):
        for name in ("ADR-0082-dsh-continuable-child-resume.md",
                     "ADR-0083-terminal-attachment-boundary.md"):
            text = (ROOT / "docs/architecture/adr" / name).read_text(encoding="utf-8")
            self.assertIn("Proposed", text, name)
            self.assertIn("NOT accepted, NOT implemented", text, name)
            self.assertNotIn("Status: Accepted", text, name)

    def test_no_child_resume_or_terminal_wiring_in_services(self):
        services = ROOT / "services"
        offenders = []
        for path in services.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".js", ".ts", ".mjs"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "resume_delegated_child" in text or "dsh-terminal" in text:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_production_selector_is_unchanged(self):
        deployment = json.loads(
            (ROOT / "config/dsh/deployment.json").read_text(encoding="utf-8"))
        self.assertEqual(deployment["default_release"], "dsh-0.1.2rc1")

    def test_audit_build_revision_is_the_next_unused_id(self):
        from scripts.dsh import build_revision as builds
        self.assertEqual(builds.selected_build_id("dsh-0.1.2rc1"), CURRENT_BUILD_REVISION)
        self.assertTrue((ROOT / "config/dsh/builds" / f"{CURRENT_BUILD_REVISION}.json").is_file())
        dockerfile = (ROOT / "services/runtime-adapter/Dockerfile.post-u8-candidate").read_text()
        self.assertIn(CURRENT_BUILD_REVISION, dockerfile)
        # The historical closeout revision remains an immutable committed manifest.
        self.assertTrue((ROOT / "config/dsh/builds" / f"{AUDIT_BUILD_REVISION}.json").is_file())

    def test_no_release_manifest_is_committed(self):
        for candidate in Path(ROOT / "config").rglob("*.json"):
            text = candidate.read_text(encoding="utf-8", errors="ignore")
            if '"schema": "byq-release.v1"' in text or '"schema":"byq-release.v1"' in text:
                self.fail(f"unexpected committed release manifest: {candidate}")


if __name__ == "__main__":
    unittest.main()
