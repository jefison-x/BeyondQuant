"""Phase 7 slice 5 archive contract for the obsolete P4 event harness."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PINNED_SOURCE_COMMIT = "2f8aca4a877d01481be556236c8f56d6ad7fa290"

ARCHIVED_PATHS = (
    "packages/contracts/research_continuation_event.py",
    "services/backend/tests/test_research_continuation_event_contract.py",
    "tests/test_v091_continuation_p4.py",
    "tests/test_v091_continuation_p4b.py",
    "tests/test_v091_continuation_p4c1.py",
    "scripts/v091/continuation_p4",
    "scripts/v091/continuation_p4b",
    "scripts/v091/continuation_p4c1",
)

LIVE_RESEARCH_TASK_BOUNDARY = {
    "services/backend/app/research_task_actions.py": (
        "CREATE TABLE IF NOT EXISTS research_task_actions",
        "class ResearchTaskActionMixin",
    ),
    "services/backend/app/research_plan_continuation.py": (
        "request_plan_approval",
    ),
    "packages/contracts/research_plan_approval.py": (
        "PLAN_APPROVAL_ACTION",
        "def bound_approval(",
    ),
}

REPLAY_READMES = {
    "docs/evidence/adr-0085-p4-real-journey/README.md": (
        "scripts/v091/continuation_p4/observer.py",
        "scripts/v091/continuation_p4/capture.py",
        "scripts/v091/continuation_p4/run_journey.py",
        "tests/test_v091_continuation_p4.py",
    ),
    "docs/evidence/adr-0085-p4b-normal-journey/README.md": (
        "scripts/v091/continuation_p4b/observer.py",
        "scripts/v091/continuation_p4b/request_gate_negative_control.py",
        "scripts/v091/continuation_p4b/run_journey.py",
        "tests/test_v091_continuation_p4b.py",
    ),
    "docs/evidence/adr-0085-p4c1-adapter-fault-safe/README.md": (
        "scripts/v091/continuation_p4c1/observer.py",
        "scripts/v091/continuation_p4c1/run_faults.py",
        "tests/test_v091_continuation_p4c1.py",
    ),
}


class HistoricalEventArchiveContractTests(unittest.TestCase):
    def test_obsolete_event_contract_and_p4_harness_group_are_absent(self) -> None:
        present = [path for path in ARCHIVED_PATHS if (ROOT / path).exists()]
        self.assertEqual(present, [], f"obsolete P4 archive paths remain: {present}")

    def test_research_task_action_and_approval_boundary_remains_live(self) -> None:
        for relative, markers in LIVE_RESEARCH_TASK_BOUNDARY.items():
            source = ROOT / relative
            self.assertTrue(source.is_file(), relative)
            contents = source.read_text()
            for marker in markers:
                self.assertIn(marker, contents, f"{relative} lost {marker!r}")

        for relative in (
            "services/backend/tests/test_research_continuation_ledger.py",
            "services/backend/tests/test_research_plan_continuation.py",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_retained_replay_pointers_resolve_at_the_pinned_git_commit(self) -> None:
        pointers = dict(REPLAY_READMES)
        pointers["services/runtime-adapter/tests/test_research_judgment_turn.py"] = (
            "scripts/v091/continuation_p4/carrier_turn_runner_probe.py",
        )
        for readme, source_paths in pointers.items():
            contents = (ROOT / readme).read_text()
            self.assertIn(PINNED_SOURCE_COMMIT, contents, readme)
            normalized = re.sub(r"\s+", " ", contents.lower())
            self.assertIn("not a current acceptance gate", normalized, readme)
            for relative in source_paths:
                self.assertIn(relative, contents, f"{readme} omits replay pointer {relative}")
                result = subprocess.run(
                    ["git", "cat-file", "-t", f"{PINNED_SOURCE_COMMIT}:{relative}"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    (result.returncode, result.stdout.strip()),
                    (0, "blob"),
                    f"{relative} is not a Git blob at {PINNED_SOURCE_COMMIT}: {result.stderr}",
                )


if __name__ == "__main__":
    unittest.main()
