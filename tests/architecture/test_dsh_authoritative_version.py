"""Offline rejection tests for the ACP authoritative DSH resolver."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.dsh.authoritative_version import AuthoritativeVersionError, load_authoritative_version

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config/dsh/acp/authoritative.json"


class DshAuthoritativeVersionTests(unittest.TestCase):
    def _fixture(self) -> tuple[Path, dict[str, object]]:
        source = json.loads(MANIFEST.read_text(encoding="utf-8"))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        path = root / "config/dsh/acp/authoritative.json"
        path.parent.mkdir(parents=True)
        for entry in source["profiles"].values():
            destination = root / entry["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / entry["path"], destination)
        path.write_text(json.dumps(source, indent=2), encoding="utf-8")
        return root, source

    @staticmethod
    def _write(root: Path, manifest: dict[str, object]) -> None:
        (root / "config/dsh/acp/authoritative.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

    def test_current_manifest_resolves_fixed_build_and_compatibility(self) -> None:
        selected = load_authoritative_version(ROOT)
        self.assertEqual(selected["release_id"], "dsh-v0.2.0-rc.2")
        self.assertEqual(selected["compatibility_family"], "dsh-v0.2.0-rc.2-acp")
        self.assertFalse(selected["sdk_online_fallback"])
        self.assertEqual(set(selected["roles"]), {"adapter", "ordinary_runner", "judgment_runner"})

    def test_rejects_release_version_drift(self) -> None:
        root, manifest = self._fixture()
        manifest["release_id"] = "dsh-v0.2.0-rc.3"
        self._write(root, manifest)
        with self.assertRaises(AuthoritativeVersionError):
            load_authoritative_version(root)

    def test_rejects_role_version_drift(self) -> None:
        root, manifest = self._fixture()
        manifest["roles"]["adapter"] = "dsh-v0.2.0-rc.3"
        self._write(root, manifest)
        with self.assertRaises(AuthoritativeVersionError):
            load_authoritative_version(root)

    def test_rejects_profile_hash_drift(self) -> None:
        root, manifest = self._fixture()
        manifest["profiles"]["product"]["sha256"] = "0" * 64
        self._write(root, manifest)
        with self.assertRaises(AuthoritativeVersionError):
            load_authoritative_version(root)

    def test_rejects_path_escape_and_symlink(self) -> None:
        root, manifest = self._fixture()
        manifest["profiles"]["product"]["path"] = (
            "plugins/dsh-byq/profiles/acp-0.2.0-rc.2/../../../../outside.yml"
        )
        self._write(root, manifest)
        with self.assertRaises(AuthoritativeVersionError):
            load_authoritative_version(root)

        root, manifest = self._fixture()
        entry = manifest["profiles"]["product"]
        target = root / entry["path"]
        target.unlink()
        target.symlink_to(ROOT / entry["path"])
        self._write(root, manifest)
        with self.assertRaises(AuthoritativeVersionError):
            load_authoritative_version(root)

    def test_rejects_malformed_commit_and_lock_hash(self) -> None:
        for field, value in (
            ("source_commit", "not-a-40-hex-commit"),
            ("pnpm_lock_sha256", "not-a-64-hex-lock"),
        ):
            with self.subTest(field=field):
                root, manifest = self._fixture()
                manifest[field] = value
                self._write(root, manifest)
                with self.assertRaises(AuthoritativeVersionError):
                    load_authoritative_version(root)

    def test_rejects_online_sdk_fallback_marker(self) -> None:
        root, manifest = self._fixture()
        manifest["rollback"]["offline_only"] = False
        self._write(root, manifest)
        with self.assertRaises(AuthoritativeVersionError):
            load_authoritative_version(root)


if __name__ == "__main__":
    unittest.main()
