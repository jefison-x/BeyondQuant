import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("root_profile", ROOT / "scripts/dsh/root_profile.py")
profile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profile)


class RootProfileTests(unittest.TestCase):
    def test_derivation_changes_only_authorized_headers_and_new_identity(self):
        for release, (source_path, identity_path) in profile.PROFILES.items():
            with self.subTest(release=release):
                source = (ROOT / source_path).read_text()
                original = json.loads((ROOT / identity_path).read_text())
                rendered, identity = profile.render(source, original, release)
                provider_headers = ("        headers:\n"
                    "          x-opencode-session: !!js process.env.BYQ_PROVIDER_SESSION_ID\n"
                    "          User-Agent: BeyondQuant/1.0 (strategy-research-agent)\n")
                self.assertEqual(rendered.count(provider_headers), 3)
                stripped = rendered.replace(provider_headers, "")
                self.assertEqual("\n".join(line for line in stripped.splitlines()
                    if "X-BYQ-Root-Run-ID:" not in line) + "\n", source)
                self.assertEqual(identity["composition_hash"], "sha256:" + hashlib.sha256(rendered.encode()).hexdigest())
                self.assertEqual(identity["source_composition_hash"], original["composition_hash"])
                self.assertNotEqual(identity["composition_hash"], original["composition_hash"])
                self.assertNotIn("root_identity_contract", original)

    def test_ambiguous_or_already_derived_profile_fails_closed(self):
        marker = "  X-BYQ-DSH-Run-ID: !!js process.env.BYQ_DSH_RUN_ID\n"
        for text in ("", marker * 2, marker + "BYQ_ROOT_RUN_ID\n", marker + "X-BYQ-Root-Run-ID\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                profile.render(text, {}, "dsh-0.1.2rc1")

    def test_source_hash_must_match_before_derivation(self):
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            profile.render("  X-BYQ-DSH-Run-ID: !!js process.env.BYQ_DSH_RUN_ID\n", {}, "dsh-0.1.2rc1")


if __name__ == "__main__":
    unittest.main()
