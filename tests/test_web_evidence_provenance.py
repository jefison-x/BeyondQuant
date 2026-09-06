from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/dsh/web_evidence_provenance.py"
SPEC = importlib.util.spec_from_file_location("web_evidence_provenance", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class WebEvidenceProvenanceGenerationTests(unittest.TestCase):
    def test_generated_default_and_candidate_policies_are_deterministic(self) -> None:
        outputs = MODULE.outputs()
        self.assertEqual(outputs[MODULE.DEFAULT_OUTPUT], MODULE.render())
        self.assertEqual(MODULE.DEFAULT_OUTPUT.read_text(), MODULE.render())
        candidate = json.loads(MODULE.render("dsh-0.1.2rc1"))
        self.assertEqual(candidate["mode"], "candidate")
        self.assertEqual(candidate["active_producer"]["plugin_version"], "0.1.2-rc.1")
        self.assertEqual(
            {(item["plugin_version"], item["qualification_state"]) for item in candidate["recognized_producers"]},
            {("0.1.1-rc.1", "QUALIFIED"), ("0.1.2-rc.1", "CANDIDATE")},
        )

    def test_unqualified_default_and_incomplete_candidate_fail_closed(self) -> None:
        registry = MODULE._load(MODULE.REGISTRY)
        plugin = next(item for item in registry["plugins"] if item["id"] == "web-search")
        plugin["qualification"]["state"] = "AVAILABLE"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(json.dumps(registry))
            with patch.object(MODULE, "REGISTRY", path), self.assertRaisesRegex(
                MODULE.ProvenanceError, "not enabled and QUALIFIED"
            ):
                MODULE.render()

        release = MODULE._load(MODULE.RELEASES / "dsh-0.1.2rc1.json")
        release["carrier"].pop("source_manifest_sha256")
        with tempfile.TemporaryDirectory() as directory:
            release_root = Path(directory)
            (release_root / "dsh-0.1.2rc1.json").write_text(json.dumps(release))
            with patch.object(MODULE, "RELEASES", release_root), self.assertRaisesRegex(
                MODULE.ProvenanceError, "incomplete"
            ):
                MODULE.render("dsh-0.1.2rc1")



class WebEvidencePolicyIntegrityTests(unittest.TestCase):
    def test_active_identity_must_match_the_complete_recognized_record(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "backend_web_evidence_policy", ROOT / "services/backend/app/web_evidence_provenance.py"
        )
        assert spec and spec.loader
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)
        policy = json.loads(MODULE.render())
        for field, forged in (
            ("release_id", "dsh-unrelated"),
            ("attestation_sha256", "sha256:" + "0" * 64),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                invalid = copy.deepcopy(policy)
                invalid["active_producer"][field] = forged
                path = Path(directory) / "policy.json"
                path.write_text(json.dumps(invalid))
                with self.assertRaisesRegex(ValueError, "not recognized"):
                    backend.load_web_evidence_provenance(path)

    def test_qualified_policy_cannot_enable_candidate_writes(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "backend_web_evidence_policy", ROOT / "services/backend/app/web_evidence_provenance.py"
        )
        assert spec and spec.loader
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)
        policy = json.loads(MODULE.render("dsh-0.1.2rc1"))
        policy["mode"] = "qualified"
        policy["active_producer"] = policy["recognized_producers"][0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(policy))
            with self.assertRaisesRegex(ValueError, "unqualified"):
                backend.load_web_evidence_provenance(path)

if __name__ == "__main__":
    unittest.main()
