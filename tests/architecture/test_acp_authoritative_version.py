"""Single authoritative DSH version manifest (ADR-0103 / single-version phase).

Binds the ACP DSH version and its profile/identity artifacts to one manifest so
consumers cannot drift. Qualification is bound to tested artifacts, not to a
"version >= X" predicate.
"""

from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config/dsh/acp/authoritative.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AcpAuthoritativeVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_release_identity_and_single_version_roles(self) -> None:
        identity = json.loads(
            (ROOT / "config/dsh/acp-0.2.0-rc.2.identity.json").read_text(encoding="utf-8")
        )
        self.assertEqual(self.manifest["schema_version"], "byq-dsh-authoritative-version.v1")
        self.assertEqual(self.manifest["release_id"], identity["release_id"])
        self.assertEqual(self.manifest["source_commit"], identity["source_commit"])
        self.assertEqual(self.manifest["pnpm_lock_sha256"], identity["pnpm_lock_sha256"])
        # Every DSH container role is the same release.
        self.assertEqual(set(self.manifest["roles"].values()), {self.manifest["release_id"]})

    def test_profile_and_identity_hashes_match_worktree(self) -> None:
        for entry in self.manifest["profiles"].values():
            self.assertEqual(entry["sha256"], _sha256(ROOT / entry["path"]), entry["path"])
        product_identity = json.loads(
            (ROOT / self.manifest["profiles"]["product_identity"]["path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(
            product_identity["composition_hash"],
            "sha256:" + self.manifest["profiles"]["product"]["sha256"],
        )

    def test_candidate_dockerfiles_pin_the_manifest_commit(self) -> None:
        commit = self.manifest["source_commit"]
        for relative in (
            "services/acp_product_runner/Dockerfile",
            "services/runtime-adapter/Dockerfile.acp-0.2.0-rc.2-candidate",
        ):
            self.assertIn(commit, (ROOT / relative).read_text(encoding="utf-8"), relative)

    def test_sdk_import_is_confined_to_classified_rollback_compat(self) -> None:
        offenders: list[str] = []
        pattern = re.compile(r"^\s*(?:from|import)\s+(?:deepseek_harness|deepseek_harness_runtime)\b", re.M)
        for path in (ROOT / "services/runtime-adapter/app").rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if pattern.search(path.read_text(errors="ignore")):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, ["services/runtime-adapter/app/compat/dsh_012.py"])


if __name__ == "__main__":
    unittest.main()
