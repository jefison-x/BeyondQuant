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
    "dsh-0.1.5rc1-post-u8.220": (
        "services/runtime-adapter/Dockerfile.post-u8-220-candidate",
        "9f02f3649ff5dc968157d4fc87d1907e1df04ff95e0cc7024e40b5077ce45eed",
        "0c28f16092192c727f8f1916bc82518cc5652527e4e9705f89a55e7f5f560b63"),
    "dsh-0.1.5rc1-post-u8.221": (
        "services/runtime-adapter/Dockerfile.post-u8-221-candidate",
        "cf0000e93c1616db0640667eb91329fc02b01d95d32003fbf3701903075979c7",
        "6054313d9947fc690df7eecec5b686054a05ffb7b47360912c4f48ab9af90c49"),
    "dsh-0.1.5rc1-post-u8.222": (
        "services/runtime-adapter/Dockerfile.post-u8-222-candidate",
        "f615206b481c0914dc8c53ab8b632c4cf507d6bd1ca77ff51c601ffc5e225a66",
        "d3bc4b46cf476daa91cb703d73fae82da55709ed55e9c6e189edc815933c7d93"),
    "dsh-0.1.5rc1-post-u8.223": (
        "services/runtime-adapter/Dockerfile.post-u8-223-candidate",
        "969e4629dfa95ad494d28a958d9e40b3401393c99acff7d0d8425f3d9b1c1660",
        "622c402b0260a1f87edaa7f067043504d0ae8166207115928ab4cc416ce5146e"),
    "dsh-0.1.5rc1-post-u8.224": (
        "services/runtime-adapter/Dockerfile.post-u8-224-candidate",
        "14728a669b4285fd99b0fffeea035010a6dfbc01355a6ccaf6a5f4520bb2e762",
        "c0a41c014c5de5a6228df3bf407f200e47725aef1d9d087a363fcf4043cbff18"),
    "dsh-0.1.5rc1-post-u8.225": (
        "services/runtime-adapter/Dockerfile.post-u8-225-candidate",
        "ffca2b671d3de7967195d75cd6be689f217caea452117bb9cf825e7d04a4a824",
        "50a9de8aaa89435407a2af1fc6fa55bdba61916b94f2f8a9ed2d0878bebc3085"),
    "dsh-0.1.5rc1-post-u8.226": (
        "services/runtime-adapter/Dockerfile.post-u8-226-candidate",
        "d5b2dc0f1c606d1ae7e063e832f50820d797b9f4f26c9c61fbb6d00bda0d0a14",
        "c947bf9118934a594a23c09b75d28b9edf02bc86d90e3c590b0dd4a5dc35a39b"),
    "dsh-0.1.5rc1-post-u8.227": (
        "services/runtime-adapter/Dockerfile.post-u8-227-candidate",
        "13e0c76bce80fcb46e86617cbf40cd0f67dd699a5391f4fd938edf08f1be6961",
        "c906f4745e3028569e4e70a91872f8159295ea487c4a43599d9636f0f2aec140"),
    "dsh-0.1.5rc1-post-u8.228": (
        "services/runtime-adapter/Dockerfile.post-u8-228-candidate",
        "5a05e4ef0609ac148c98a21b2d18565020591e9db4c12b00636aa18980585afd",
        "5a6b768bfee291b9577180869feeba814809edf1cfc7ac5a79ebe7562207b139"),
    "dsh-0.1.5rc1-post-u8.229": (
        "services/runtime-adapter/Dockerfile.post-u8-229-candidate",
        "c249fedeef8894c532afd2c16e7e850be68910fd6a85447434611d0aed7ad293",
        "69f0fd499255e5ae2f3c6d3868a04b644ead575b4e1969184a34e3194a736697"),
    "dsh-0.1.5rc1-post-u8.230": (
        "services/runtime-adapter/Dockerfile.post-u8-230-candidate",
        "8738222d9e4f216921f93fb8c28730e6858582e6bf8fd80c3d8b141c64211113",
        "6596cd8682584fd8d48d1adb78c4960040e803e5177f32f3e2a039130d7e7659"),
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
        dockerfile_path = ROOT / builds.identity(selected)[1]
        dockerfile = dockerfile_path.read_text()
        self.assertIn(
            f"COPY config/dsh/builds/{selected}.json /opt/byq/builds/build.identity.json",
            dockerfile)
        previous = ROOT / "services/runtime-adapter/Dockerfile.post-u8-230-candidate"
        expected = previous.read_text().replace(
            "dsh-0.1.5rc1-post-u8.230.json", f"{selected}.json")
        self.assertEqual(dockerfile, expected)

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
