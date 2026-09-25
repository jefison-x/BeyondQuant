"""Current immutable build revision is complete; the frozen previous one is intact.

This is the independent CURRENT-build test that decouples the historical
``test_v090_*`` evidence tests from the mutable current artifact identity
(ADR-0084 evidence-reuse / historical-fact principle). It proves:

* the currently selected build manifest renders exactly from the current tree
  (no drift), so the current artifact identity is complete;
* the runtime Dockerfile embeds exactly the selected manifest;
* the immediately previous frozen manifest is byte-identical to its committed
  ``origin/main`` content and was NOT rewritten.
"""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_BUILD = "dsh-0.1.5rc1-post-u8.214"
# sha256 of config/dsh/builds/dsh-0.1.5rc1-post-u8.214.json as committed at
# 561f9db6; the frozen manifest must never be rewritten.
PREVIOUS_BUILD_SHA256 = (
    "fbb1cbd04573d2a97eb2a743225423c621b715b58b0f4eae647ee00534664029")


class CurrentBuildRevisionTests(unittest.TestCase):
    def test_selected_build_renders_exactly_from_the_current_tree(self) -> None:
        from scripts.dsh import build_revision as builds

        selected = builds.selected_build_id("dsh-0.1.5rc1")
        self.assertRegex(selected, r"^dsh-0\.1\.5rc1-post-u8\.\d+$")
        manifest = ROOT / "config/dsh/builds" / f"{selected}.json"
        self.assertTrue(manifest.is_file(), selected)
        # Fail closed on any drift: the manifest must render exactly now.
        self.assertEqual(builds.check(selected), builds.render(selected))

    def test_runtime_dockerfile_embeds_exactly_the_selected_manifest(self) -> None:
        from scripts.dsh import build_revision as builds

        selected = builds.selected_build_id("dsh-0.1.5rc1")
        dockerfile = (ROOT / "services/runtime-adapter/Dockerfile.post-u8-candidate").read_text()
        self.assertIn(
            f"COPY config/dsh/builds/{selected}.json /opt/byq/builds/build.identity.json",
            dockerfile)

    def test_previous_frozen_manifest_is_not_rewritten(self) -> None:
        frozen = ROOT / "config/dsh/builds" / f"{PREVIOUS_BUILD}.json"
        self.assertTrue(frozen.is_file())
        self.assertEqual(
            hashlib.sha256(frozen.read_bytes()).hexdigest(), PREVIOUS_BUILD_SHA256)


if __name__ == "__main__":
    unittest.main()
