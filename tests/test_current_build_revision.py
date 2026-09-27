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
FROZEN_ARTIFACTS = {
    "dsh-0.1.5rc1-post-u8.215": (
        "services/runtime-adapter/Dockerfile.post-u8-candidate",
        "81a7631851ca3d90caa8ce15b27911b45e3d1cb8537189ca973a534271106c56",
        "5d00eab2483a2a780bbbcd0c600a770c4d347b5cd0941104e32a51bd537ee81a"),
    "dsh-0.1.5rc1-post-u8.216": (
        "services/runtime-adapter/Dockerfile.post-u8-216-candidate",
        "0a28e9c6037f82caf367df1928217439f7e3936669f334c60fc1603226aa57ee",
        "5220e479fbfd34e3103c26cd45432ac0b2a510a1113aa0167c3a969032c40e07"),
    "dsh-0.1.5rc1-post-u8.217": (
        "services/runtime-adapter/Dockerfile.post-u8-217-candidate",
        "249ef7d02019b52596f74182164a323a902a7597ba9f5f41f12ddc19c98bcb19",
        "5846687f3ece97ad869dd540eea07f6e82e74caf6cc91467c7bd91c4a1665853"),
    "dsh-0.1.5rc1-post-u8.218": (
        "services/runtime-adapter/Dockerfile.post-u8-218-candidate",
        "c169e2a340ccf83a1b59d1c79a42e8d969ca478601df004dd1df94e306cd30a4",
        "07b1b6d8b4ae63b48eaa3ae279b54121b0777afedf4a8d7aff82f2b785cbea27"),
    "dsh-0.1.5rc1-post-u8.219": (
        "services/runtime-adapter/Dockerfile.post-u8-219-candidate",
        "9e2c09fa832d8dca6fa989bf9a83adb2ebf8f66b2f6ceb79cf1cebe44219357d",
        "5a434b8e62e21e136efa1d73a2ad86604b105882d4903120480cd90be69dec74"),
}


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
        dockerfile = (ROOT / builds.identity(selected)[1]).read_text()
        self.assertIn(
            f"COPY config/dsh/builds/{selected}.json /opt/byq/builds/build.identity.json",
            dockerfile)

    def test_frozen_build_manifests_and_dockerfiles_are_not_rewritten(self) -> None:
        for build_id, (dockerfile, manifest_sha256, dockerfile_sha256) in FROZEN_ARTIFACTS.items():
            manifest = ROOT / "config/dsh/builds" / f"{build_id}.json"
            docker_source = ROOT / dockerfile
            self.assertTrue(manifest.is_file(), build_id)
            self.assertTrue(docker_source.is_file(), dockerfile)
            self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(),
                             manifest_sha256, build_id)
            self.assertEqual(hashlib.sha256(docker_source.read_bytes()).hexdigest(),
                             dockerfile_sha256, dockerfile)


if __name__ == "__main__":
    unittest.main()
