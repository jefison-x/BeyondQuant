"""Archived release checks must not silently bless current application sources."""
import copy
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.dsh import historical_inputs as history
from scripts.dsh import release as releases


class HistoricalInputTests(unittest.TestCase):
    def test_default_current_tree_check_still_rejects_historical_source_drift(self):
        with self.assertRaisesRegex(releases.ReleaseError, "build input drift"):
            releases.load_all()
        with self.assertRaisesRegex(releases.ReleaseError, "cannot disable"):
            releases.load_all(verify_files=False, historical_inputs=True)

    def test_exact_archived_inputs_and_descriptor_match(self):
        for release in history.SOURCE_COMMITS:
            descriptor = history.ROOT / "config/dsh/releases" / f"{release}.json"
            value = json.loads(descriptor.read_text())
            self.assertEqual(history.verify(value), history.SOURCE_COMMITS[release])

    def test_rewritten_descriptor_is_not_new_historical_authority(self):
        value = json.loads((history.ROOT / "config/dsh/releases/dsh-0.1.2rc1.json").read_text())
        forged = copy.deepcopy(value)
        forged["build_inputs"]["services/runtime-adapter/app/runtime.py"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "descriptor"):
            history.verify(forged)

    def test_missing_history_and_corrupt_blob_fail_closed(self):
        value = json.loads((history.ROOT / "config/dsh/releases/dsh-0.1.2rc1.json").read_text())
        with patch.object(history.subprocess, "run", side_effect=subprocess.CalledProcessError(128, "git")):
            with self.assertRaisesRegex(ValueError, "unavailable"):
                history.verify(value)
        real_blob = history.read_blob
        def corrupt(commit, path):
            return b"corrupt" if path.endswith("runtime.py") else real_blob(commit, path)
        with patch.object(history, "read_blob", side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, "input drift"):
                history.verify(value)

    def test_unknown_release_and_escaping_path_rejected(self):
        with self.assertRaises(ValueError):
            history.verify({"release_id": "latest"})
        for path in ("../escape", "/absolute", "a/../escape"):
            with self.assertRaises(ValueError):
                history.read_blob(next(iter(history.SOURCE_COMMITS.values())), path)


if __name__ == "__main__":
    unittest.main()
