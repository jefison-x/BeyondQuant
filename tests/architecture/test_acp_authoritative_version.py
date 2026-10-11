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

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config/dsh/acp/authoritative.json"
PRODUCT_PATCH = ROOT / "plugins/dsh-byq/profiles/acp-0.2.0-rc.2/byq-product.patch.yml"
PRODUCT_IDENTITY = ROOT / "plugins/dsh-byq/profiles/acp-0.2.0-rc.2/byq-product.identity.json"

# Each ordinary business delegate child must bind its OWN native AgentRun with
# its correct closed role before its first BYQ business tool; it must not inherit
# the parent root's AgentRun (ADR-0094 ingress requires a bound native AgentRun).
DELEGATE_CHILD_ROLES = {
    "delegate-market-research": "market_researcher",
    "delegate-factor-research": "factor_researcher",
    "delegate-strategy-research": "strategy_researcher",
    "delegate-backtest-analysis": "backtest_analyst",
    "delegate-ml-research": "ml_researcher",
}


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

    def test_candidate_dockerfiles_are_resolver_fed_not_literal_pinned(self) -> None:
        # ADR-0110 / resolver-fed builds: the pinned source commit is supplied
        # as a build arg and verified against the clone; no candidate Dockerfile
        # (per-role or unified) may hard-code the manifest commit.
        commit = self.manifest["source_commit"]
        for relative in (
            "services/acp_product_runner/Dockerfile",
            "services/acp_judgment_runner/Dockerfile",
            "services/runtime-adapter/Dockerfile.acp-0.2.0-rc.2-candidate",
            "services/acp_unified/Dockerfile",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("ARG BYQ_DSH_BUILD_SOURCE_COMMIT", source, relative)
            self.assertIn('"$BYQ_DSH_BUILD_SOURCE_COMMIT"', source, relative)
            self.assertNotIn(commit, source, relative)

    def test_single_image_topology_builds_the_three_roles_from_one_dockerfile(self) -> None:
        # ADR-0110: one build (unified Dockerfile) and one shared image
        # expression for the adapter / ordinary-runner / judgment-runner roles.
        roles = {"runtime-adapter", "acp-product-runner", "acp-judgment-runner"}
        # The adopted default route is compose.dsh-acp-rc2-candidate.yml and
        # declares the run-scoped project image tag for all three roles.
        default = yaml.safe_load(
            (ROOT / "compose.dsh-acp-rc2-candidate.yml").read_text(encoding="utf-8")
        )["services"]
        self.assertTrue(roles <= set(default))
        self.assertEqual(
            {default[service]["build"]["dockerfile"] for service in roles},
            {"services/acp_unified/Dockerfile"},
        )
        self.assertEqual(
            {default[service]["image"] for service in roles},
            {"${COMPOSE_PROJECT_NAME:-beyondquant}-acp-unified"},
        )
        self.assertEqual(
            {default[service]["environment"]["BYQ_ACP_ROLE"] for service in roles},
            {"adapter", "product", "judgment"},
        )
        # The additive candidate overlay stays isolated and single-image.
        candidate = yaml.safe_load(
            (ROOT / "compose.dsh-acp-single-image-candidate.yml").read_text(
                encoding="utf-8"
            )
        )
        services = candidate["services"]
        self.assertEqual(set(services), roles)
        self.assertEqual(
            {service["build"]["dockerfile"] for service in services.values()},
            {"services/acp_unified/Dockerfile"},
        )
        self.assertEqual(
            {service["image"] for service in services.values()},
            {"${BYQ_ACP_UNIFIED_IMAGE:-byq-acp-unified:candidate}"},
        )
        # Role selection is runtime-only; every role is the same release version.
        self.assertEqual(set(self.manifest["roles"].values()), {self.manifest["release_id"]})

    def test_sdk_import_is_confined_to_classified_rollback_compat(self) -> None:
        offenders: list[str] = []
        pattern = re.compile(r"^\s*(?:from|import)\s+(?:deepseek_harness|deepseek_harness_runtime)\b", re.M)
        for path in (ROOT / "services/runtime-adapter/app").rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if pattern.search(path.read_text(errors="ignore")):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, ["services/runtime-adapter/app/compat/dsh_012.py"])

    def test_business_delegate_personas_bind_their_own_child_agent_run(self) -> None:
        text = PRODUCT_PATCH.read_text(encoding="utf-8")
        for tool_id, role in DELEGATE_CHILD_ROLES.items():
            block = text.split(f"- id: {tool_id}", 1)[1].split("    - id: ", 1)[0]
            self.assertIn(f'byq_agent_run_start with role_id \\"{role}\\"', block, tool_id)
            self.assertIn("never reuse or inherit the parent's AgentRun", block, tool_id)
            # the binding tool must be in the child's closed allowlist
            self.assertIn("mcp__byq__byq_agent_run_start", block, tool_id)
        # The single bounded research-judgment role keeps its read-only path and
        # must never receive the AgentRun registration tool.
        judgment = text.split("- id: research-judgment-turn", 1)[1]
        self.assertNotIn("byq_agent_run_start", judgment)
        self.assertNotIn("mcp__byq__byq_agent_run_start", judgment)
        # Identity contract: the pinned composition hash equals the patch bytes.
        identity = json.loads(PRODUCT_IDENTITY.read_text(encoding="utf-8"))
        self.assertEqual(identity["composition_hash"], "sha256:" + _sha256(PRODUCT_PATCH))


if __name__ == "__main__":
    unittest.main()
