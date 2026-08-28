from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/dsh/plugin_registry.py"
SPEC = importlib.util.spec_from_file_location("byq_plugin_registry", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
registry_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(registry_module)


def _registry() -> dict[str, object]:
    return json.loads((ROOT / "plugins/dsh-byq/registry/plugins.json").read_text())


class PluginRegistryTests(unittest.TestCase):
    def _assert_registry_error(self, value: object, message: str) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plugins.json"
            path.write_text(json.dumps(value))
            with patch.object(registry_module, "REGISTRY_PATH", path):
                with self.assertRaisesRegex(registry_module.RegistryError, message):
                    registry_module.load_and_validate()

    def test_registry_validates_and_generated_composition_is_current(self) -> None:
        data = registry_module.load_and_validate()
        self.assertEqual(registry_module.build(), registry_module.build())
        self.assertEqual(data["profile_name"], "research")
        registry_module.write_or_check(profile_name=None, check=True)

    def test_enabled_plugin_states_and_agent_web_boundary(self) -> None:
        data = registry_module.load_and_validate()
        states = {
            item["id"]: item
            for item in registry_module.qualification_report(data)["plugins"]
        }
        self.assertEqual({key: states[key]["state"] for key in states}, {
            "compaction": "ENABLED",
            "guard": "ENABLED",
            "interaction": "BLOCKED",
            "spill": "BLOCKED",
            "web-search": "ENABLED",
        })
        composition = (
            ROOT / "plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml"
        ).read_text()
        market = composition.split("- id: delegate-market-research", 1)[1].split(
            "- id: delegate-factor-research", 1
        )[0]
        factor = composition.split("- id: delegate-factor-research", 1)[1].split(
            "- id: delegate-strategy-research", 1
        )[0]
        strategy = composition.split("- id: delegate-strategy-research", 1)[1].split(
            "- id: delegate-backtest-analysis", 1
        )[0]
        backtest = composition.split("- id: delegate-backtest-analysis", 1)[1].split(
            "# Qualified", 1
        )[0]
        self.assertIn("- web_search", market)
        self.assertIn("- byq_web_evidence_create", market)
        self.assertTrue(all("web_search" not in block for block in (factor, strategy, backtest)))
        self.assertTrue(all("byq_web_evidence_create" not in block for block in (factor, strategy, backtest)))
        self.assertNotIn("web_fetch", composition)
        self.assertNotIn("ask_user", composition)
        self.assertNotIn("spill-local", composition)

    def test_registry_invalid_contracts_fail_closed(self) -> None:
        cases = [
            (lambda value: value["plugins"].append(copy.deepcopy(value["plugins"][0])), "duplicate plugin id"),
            (lambda value: value["plugins"][0]["qualification"].update(state="MAYBE"), "unknown qualification state"),
            (lambda value: value["plugins"][0]["packages"][0].update(version="^0.1.1-rc.1"), "must be exact"),
            (lambda value: value["plugins"][0].pop("risk"), "valid risk metadata"),
            (lambda value: value["plugins"][0]["capabilities"].pop("network"), "capability set"),
            (lambda value: value["plugins"][0]["agents"]["allowed"].append("unknown_agent"), "unknown agent"),
            (lambda value: value["plugins"][3]["product_policy"].update(enabled=True), "cannot be enabled"),
            (lambda value: value["plugins"][0]["qualification"]["checks"].update(startup=False), "requires startup"),
        ]
        for mutation, message in cases:
            with self.subTest(message=message):
                value = _registry()
                mutation(value)
                self._assert_registry_error(value, message)

    def test_prohibited_capability_escalation_fails_closed(self) -> None:
        value = _registry()
        value["plugins"][0]["capabilities"]["shell"] = True
        self._assert_registry_error(value, "prohibited capability escalation")

    def test_package_integrity_and_runtime_mixing_fail_closed(self) -> None:
        lock = json.loads(registry_module.LOCK_PATH.read_text())
        lock["packages"]["node_modules/@deepseek-ai/dsh-web"]["version"] = "0.1.1-rc.2"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "package-lock.json"
            path.write_text(json.dumps(lock))
            with patch.object(registry_module, "LOCK_PATH", path):
                with self.assertRaisesRegex(registry_module.RegistryError, "lockfile version mismatch"):
                    registry_module.load_and_validate()

    def test_package_not_found_integrity_peer_and_secret_fail_closed(self) -> None:
        manifest = json.loads(registry_module.MANIFEST_PATH.read_text())
        manifest["dependencies"].pop("@deepseek-ai/dsh-web")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "package.json"
            path.write_text(json.dumps(manifest))
            with patch.object(registry_module, "MANIFEST_PATH", path):
                with self.assertRaisesRegex(registry_module.RegistryError, "manifest missing exact pin"):
                    registry_module.load_and_validate()

        value = _registry()
        value["plugins"][4]["packages"][1]["integrity"] = "sha512-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
        self._assert_registry_error(value, "lockfile integrity mismatch")

        lock = json.loads(registry_module.LOCK_PATH.read_text())
        lock["packages"]["node_modules/@deepseek-ai/dsh-tool-web"]["peerDependencies"][
            "@deepseek-ai/dsh-web"
        ] = "^0.1.1-rc.2"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "package-lock.json"
            path.write_text(json.dumps(lock))
            with patch.object(registry_module, "LOCK_PATH", path):
                with self.assertRaisesRegex(registry_module.RegistryError, "peer dependency range mismatch"):
                    registry_module.load_and_validate()

        value = _registry()
        value["plugins"][4]["credentials"]["references"] = []
        self._assert_registry_error(value, "required credential reference is missing")

    def test_public_identity_is_secret_free_and_bounded(self) -> None:
        identity = json.loads(
            (ROOT / "plugins/dsh-byq/compositions/byq-product-sdk.identity.json").read_text()
        )
        self.assertTrue(identity["composition_hash"].startswith("sha256:"))
        self.assertEqual(identity["enabled_plugin_ids"], ["compaction", "guard", "web-search"])

        def keys(value: object) -> list[str]:
            if isinstance(value, dict):
                return [str(key).lower() for key in value] + [
                    nested for item in value.values() for nested in keys(item)
                ]
            if isinstance(value, list):
                return [nested for item in value for nested in keys(item)]
            return []

        public_keys = keys(identity)
        for forbidden in ("credential", "api_key", "secret", "authorization"):
            self.assertTrue(all(forbidden not in key for key in public_keys))

    def test_managed_policy_build_is_deterministic_and_fail_closed(self) -> None:
        policy = {
            "schema_version": "plugin-deployment-policy.v1",
            "policy_version": 2,
            "enabled_plugin_ids": ["guard", "compaction"],
            "agent_assignments": {
                "guard": ["quant_orchestrator"],
                "compaction": ["quant_orchestrator"],
            },
        }
        first = registry_module.build(policy=policy)
        second = registry_module.build(policy=copy.deepcopy(policy))
        self.assertEqual(first, second)
        composition, identity = first
        self.assertEqual(identity["profile"], "managed-v2")
        self.assertEqual(identity["enabled_plugin_ids"], ["compaction", "guard"])
        self.assertNotIn("web-search-plugin", composition)
        invalid = copy.deepcopy(policy)
        invalid["enabled_plugin_ids"].append("spill")
        invalid["agent_assignments"]["spill"] = []
        with self.assertRaisesRegex(registry_module.RegistryError, "not QUALIFIED"):
            registry_module.build(policy=invalid)
        escalated = copy.deepcopy(policy)
        escalated["agent_assignments"]["guard"] = ["unknown-agent"]
        with self.assertRaisesRegex(registry_module.RegistryError, "exceeds allowlist"):
            registry_module.build(policy=escalated)


if __name__ == "__main__":
    unittest.main()
