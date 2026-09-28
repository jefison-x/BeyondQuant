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
    "dsh-0.1.5rc1-post-u8.231": (
        "services/runtime-adapter/Dockerfile.post-u8-231-candidate",
        "3adc54d054145cd0f6d8b67b055f57edab5e3bc28acfd055a692ace922c1f2ac",
        "5f3eb1238e9060b0ce14c6ebc75c77215eb20a529a127871656fe78952c7940b"),
    "dsh-0.1.5rc1-post-u8.232": (
        "services/runtime-adapter/Dockerfile.post-u8-232-candidate",
        "88433eed89a7cbf623d1561e0a9cc8c44753fb138eecd3bee4aecc48ed595b45",
        "19f1368959172f06f6a424af029cc655c45172374d077c8f9d1f3b0206ddf436"),
    "dsh-0.1.5rc1-post-u8.233": (
        "services/runtime-adapter/Dockerfile.post-u8-233-candidate",
        "f2f05cf8bb337d43451071b30953efdd0cba61502eecab2d61a20c9f5f8de690",
        "611f7a3460089a776e7e5a5510dce657a34913c858091fa3261a5f37a278fd92"),
    "dsh-0.1.5rc1-post-u8.234": (
        "services/runtime-adapter/Dockerfile.post-u8-234-candidate",
        "e02484721ca6c36b7be0caa1393e4b040db4c807b0a670e370ea4d65b77e75ae",
        "637c0bbba734274e4269c04f159fd723e63a1881aa10575cba10a158c8967c7f"),
    "dsh-0.1.5rc1-post-u8.235": (
        "services/runtime-adapter/Dockerfile.post-u8-235-candidate",
        "f9c49474ffae4e2155ced40ed46db7c4135e728881e0222717e46504177f7735",
        "f06402627e9722f0cd6d543c787c517b8542c8f63d27c79aa04a12ab8d227297"),
    "dsh-0.1.5rc1-post-u8.236": (
        "services/runtime-adapter/Dockerfile.post-u8-236-candidate",
        "b52f0e2631f62e81c5e2843073fc6b09a8f7e7ebaef3710c9c7fc22e909c4221",
        "a380de66f5ba78e11b280a6c975b94b554883d7fb61c2477f9ab07a875a4425b"),
    "dsh-0.1.5rc1-post-u8.237": (
        "services/runtime-adapter/Dockerfile.post-u8-237-candidate",
        "f8384b44707bb186b4329468dd1477c970ed47e4369dae024971e3caf600d3a0",
        "03291d73d94a3786fd1cc57eafbd6aa39e990a1d3d865893a1269f6660ca625f"),
    "dsh-0.1.5rc1-post-u8.238": (
        "services/runtime-adapter/Dockerfile.post-u8-238-candidate",
        "b34652145492d741860def91bfc035b6f20bc5c5ebc18793e0c00fd6c1889a01",
        "5d89ee16e5da6d124e71525ed8411e35d95b4aee085d1c66f9ef5fad7ca5c1a6"),
    "dsh-0.1.5rc1-post-u8.239": (
        "services/runtime-adapter/Dockerfile.post-u8-239-candidate",
        "65a3eae15457923640c76a22cd04d44ff6a31b9336d79d23d02d0f5df71cc13b",
        "6a705ef9d7b81ff64396c3c55dee8daf8c645458a3e33fbb5fa35af8981d4644"),
    "dsh-0.1.5rc1-post-u8.240": (
        "services/runtime-adapter/Dockerfile.post-u8-240-candidate",
        "954d8c0ebc263f9cd9ec0edf754c54d153e304c9e3ba4beeaeafb6f5c9d98e9d",
        "18c73cc1750bae949e8c8cdcd59cf743efe71885aa91e7f0a6237640768a5607"),
    "dsh-0.1.5rc1-post-u8.241": (
        "services/runtime-adapter/Dockerfile.post-u8-241-candidate",
        "56dba24b58d4f142668157d23aa4283ccbd60b7e62102a258f80d36d2dc810e7",
        "9d5bee4499ae7214ea62b9fda017403666f99b415d7c69c8d1050e8670d39a77"),
    "dsh-0.1.5rc1-post-u8.242": (
        "services/runtime-adapter/Dockerfile.post-u8-242-candidate",
        "741b98607250a12821bf758b8c77629f5f057c0b676ba93e9e3ce0e6e4704a4f",
        "986e183b5ecc8d7c0dc773020cc91fa1b1641311ea978dbd229ee62f2fe69be4"),
    "dsh-0.1.5rc1-post-u8.243": (
        "services/runtime-adapter/Dockerfile.post-u8-243-candidate",
        "f24812519793326f0c0f5185247c417a4a393a7db7f08acf67e88342f29cd32a",
        "327b90f7e54b10d61aa7603c97a91bcf0c5f8f254155259fa762b612b990ec2d"),
    "dsh-0.1.5rc1-post-u8.244": (
        "services/runtime-adapter/Dockerfile.post-u8-244-candidate",
        "ed48c935e48b977138b33cd4ca32c71331b65934bad85cb62f27caa231214de0",
        "208f5e6dcb13718d354417b0d5b8f26855c25e51e0f83251f30ad1f3af971d77"),
    "dsh-0.1.5rc1-post-u8.245": (
        "services/runtime-adapter/Dockerfile.post-u8-245-candidate",
        "c4623f05c218385c50fde8ba671d789cbbcc8fe39aeec7bb11e4504edbbed5eb",
        "35f365e672643074aa068692fb649f6ec21e6f6de5bc8166bf844729dc9cf3bc"),
    "dsh-0.1.5rc1-post-u8.246": (
        "services/runtime-adapter/Dockerfile.post-u8-246-candidate",
        "70b38259243693f7e8000b17a79c6316b124d6bc2870b9f03565e2f3a9b88dfd",
        "822dc1e0ef9db7b72347ef6c4d7a0fe0fd98e25e0e93c8a19e58beb8bf49ecc7"),
    "dsh-0.1.5rc1-post-u8.247": (
        "services/runtime-adapter/Dockerfile.post-u8-247-candidate",
        "417ab771429cb55e1d2ccfdaa2ea0e6113ff5703b7b8a638ae129121ca995b5a",
        "f4129d98a4bdaa8c2ac522962ff6919f04ef5870995dae10e2a1946cb42b120c"),
    "dsh-0.1.5rc1-post-u8.248": (
        "services/runtime-adapter/Dockerfile.post-u8-248-candidate",
        "fe00ced20f7ad64799747726b32ec4517bf4065c7173f12aa9ca1c218f9db953",
        "ae04d15c1b536c834377f2b139c6f289fd7c0788fcc9b4d23caed5182a2544ae"),
    "dsh-0.1.5rc1-post-u8.249": (
        "services/runtime-adapter/Dockerfile.post-u8-249-candidate",
        "e47102fab8dbe2a265da2ab32e30a0325c8b56c8d229cd61fec00e40f0262bf7",
        "c7baac77417aef3ed0a018280c2360b638610dbb396d3a4304f4a7f6021c146d"),
    "dsh-0.1.5rc1-post-u8.250": (
        "services/runtime-adapter/Dockerfile.post-u8-250-candidate",
        "a3a194786f7141fe69579b7d4a5cfbc794946a22922b3dc1d19453950290586d",
        "6d874923772ac55ab70b5ca135e64fc452a4ff7016fca74af1efdd799af3ebbf"),
    "dsh-0.1.5rc1-post-u8.251": (
        "services/runtime-adapter/Dockerfile.post-u8-251-candidate",
        "0a4d6bf8024322ff22697faaa412cce75e77cbdd636c04cd1585f963c13ef432",
        "aa50cc001a33e376e0d869f139ea1b2f84460eac7474f683dee91ce3cbb491a3"),
    "dsh-0.1.5rc1-post-u8.252": (
        "services/runtime-adapter/Dockerfile.post-u8-252-candidate",
        "75d9ed7d73410d1d5c47c331fbc75f1f4149ec91ce4859e21f9e7d5e38791588",
        "22f07d07fb9e62eda5a2347fcf28cd4fbe0f6c79f0d76cdcdbeb5c25b5ee9ef2"),
    "dsh-0.1.5rc1-post-u8.253": (
        "services/runtime-adapter/Dockerfile.post-u8-253-candidate",
        "b15c33a83be96ce8128ff70cd6a9ae28c7945108dfd806eec104da68044f9be9",
        "c5fc1bcca29119befe12e385a314a0818e4a0009f49cfe5d18f7193cfd49d5a2"),
    "dsh-0.1.5rc1-post-u8.254": (
        "services/runtime-adapter/Dockerfile.post-u8-254-candidate",
        "981dca9a3d0e5827140b6f153a2984f3dc6be9d53a727a3bab54c1cb36baf766",
        "eca2398031f72f5f76e9bc993ec14abdec0a42fa050d4d290bc1ff00722716ee"),
    "dsh-0.1.5rc1-post-u8.255": (
        "services/runtime-adapter/Dockerfile.post-u8-255-candidate",
        "bc7122df90ee1a16b91260345f1d5c25071e614e037a0e3fb27079b587d2e69f",
        "a364dd3ec288fc1937e8c2c79d66e66c3f52ae7e69b513445fc92ed4d7e5e9ef"),
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
        previous = ROOT / "services/runtime-adapter/Dockerfile.post-u8-255-candidate"
        expected = previous.read_text().replace(
            "dsh-0.1.5rc1-post-u8.255.json", f"{selected}.json")
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
