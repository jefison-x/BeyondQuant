import copy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tarfile
import unittest
from unittest.mock import patch

from scripts.dsh import retain_u6_ci_images as artifacts


class RetainedArtifactTests(unittest.TestCase):
    def test_scope_never_selects_production_or_arbitrary_paths(self):
        for scope in ("main", "beyondquant", "local-u6-../../main", "local-u6-test;bad", "local-u6-"):
            with self.assertRaises(ValueError):
                artifacts.names(scope)
        names = artifacts.names("local-u6-artifact-test")
        self.assertEqual(len(names), 7)
        self.assertTrue(all(v["retained_tag"].startswith("byq-u6-artifact-") for v in names.values()))

    def test_receipt_rejects_identity_tag_and_archive_drift(self):
        scope = "local-u6-artifact-test"
        with tempfile.TemporaryDirectory() as temporary, patch.object(artifacts, "ROOT", Path(temporary)), \
                patch.object(artifacts, "builds", return_value={"synthetic": "build"}):
            directory = Path(temporary) / ".ci-artifacts" / scope / "retained-u6"
            directory.mkdir(parents=True)
            archive = directory / "images.tar"
            archive.write_bytes(b"synthetic archive for checksum tests")
            images = artifacts.names(scope)
            for item in images.values():
                item["image_id"] = "sha256:" + "a" * 64
            valid = {"schema_version": "dsh-u6-retained-artifacts.v1", "ci_scope": scope,
                     "build_revisions": {"synthetic": "build"}, "images": images,
                     "archive": {"name": "images.tar", "bytes": archive.stat().st_size,
                                 "sha256": artifacts.archive_hash(archive)}}
            receipt = directory / "receipt.json"
            receipt.write_text(json.dumps(valid))
            self.assertEqual(artifacts.load_receipt(scope), valid)
            mutations = (
                lambda value: value.update(ci_scope="local-u6-another"),
                lambda value: value.update(build_revisions={}),
                lambda value: value["images"]["backend"].update(retained_tag="beyondquant-backend:latest"),
                lambda value: value["images"].pop("runtime-candidate"),
                lambda value: value["archive"].update(sha256="sha256:" + "0" * 64),
            )
            for mutate in mutations:
                value = copy.deepcopy(valid)
                mutate(value)
                receipt.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    artifacts.load_receipt(scope)
            receipt.write_text(json.dumps(valid))
            archive.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                artifacts.load_receipt(scope)

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(artifacts, "ROOT", Path(temporary)), \
                patch.object(artifacts, "builds", return_value={}), patch.object(artifacts, "image_id") as image:
            (Path(temporary) / ".ci-artifacts/local-u6-artifact-test/retained-u6").mkdir(parents=True)
            with self.assertRaises(ValueError):
                artifacts.retain("local-u6-artifact-test")
            image.assert_not_called()

    def test_artifact_handoff_is_rejected_for_partial_or_hosted_ci(self):
        script = artifacts.ROOT / "scripts/ci/local-ci.sh"
        commands = ((["--retain-u6-artifacts"], {}),
                    (["--retain-u6-artifacts", "--all", "--with-e2e", "--with-smoke"], {"GITHUB_ACTIONS": "true"}))
        for args, extra in commands:
            result = subprocess.run(["bash", str(script), *args], env={**os.environ, **extra},
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertIn("requires explicit local", result.stderr)

    def test_archive_import_metadata_rejects_production_tags_and_links(self):
        images = artifacts.names("local-u6-artifact-test")
        for item in images.values():
            item["image_id"] = "sha256:" + "a" * 64
        index = {"manifests": [{"digest": item["image_id"], "annotations": {
            "io.containerd.image.name": "docker.io/library/" + item["retained_tag"],
            "org.opencontainers.image.ref.name": "retained"}} for item in images.values()]}
        legacy = [{"RepoTags": [item["retained_tag"]]} for item in images.values()]
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "images.tar"
            def write(values, *, link=False):
                with tarfile.open(archive, "w") as output:
                    for name, value in values.items():
                        data = json.dumps(value).encode()
                        info = tarfile.TarInfo(name)
                        info.size = len(data)
                        output.addfile(info, io.BytesIO(data))
                    if link:
                        info = tarfile.TarInfo("escape")
                        info.type, info.linkname = tarfile.SYMTYPE, "/etc"
                        output.addfile(info)
            write({"index.json": index, "manifest.json": legacy})
            artifacts.validate_archive_metadata(archive, {"images": images})
            forged = copy.deepcopy(index)
            forged["manifests"][0]["annotations"]["io.containerd.image.name"] = "docker.io/library/beyondquant-backend:latest"
            for values, link in (({"index.json": forged, "manifest.json": legacy}, False),
                                 ({"index.json": index, "manifest.json": [{"RepoTags": ["beyondquant:latest"]}]}, False),
                                 ({"index.json": index, "manifest.json": legacy}, True)):
                write(values, link=link)
                with self.assertRaises(ValueError):
                    artifacts.validate_archive_metadata(archive, {"images": images})

    def test_restore_refuses_different_existing_identity_before_import(self):
        receipt = {"images": {"runtime-adapter": {"retained_tag": "byq-u6-artifact-test:retained", "image_id": "expected"}}}
        with patch.object(artifacts, "load_receipt", return_value=receipt), \
                patch.object(artifacts, "validate_archive_metadata"), \
                patch.object(artifacts.subprocess, "check_output", return_value="existing"), \
                patch.object(artifacts, "image_id", return_value="different"), \
                patch.object(artifacts.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                artifacts.restore("local-u6-artifact-test")
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
