"""Offline boundary checks for the captured ACP F6 release fixture."""
from __future__ import annotations

import ast
import importlib.util
from http.client import IncompleteRead
import io
import json
import os
import re
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import call, patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.dsh.authoritative_version import load_authoritative_version  # noqa: E402
from scripts.release.images import SERVICES  # noqa: E402


def _load_fixture():
    path = ROOT / "scripts/evidence/acp-f6-release-fixture.py"
    spec = importlib.util.spec_from_file_location("acp_f6_release_fixture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load ACP F6 release fixture")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_runtime_entrypoint():
    path = ROOT / "scripts/evidence/acp-f6-runtime-entrypoint.py"
    spec = importlib.util.spec_from_file_location("acp_f6_runtime_entrypoint", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load ACP F6 runtime entrypoint")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AcpF6ReleaseFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = _load_fixture()
        cls.selection = load_authoritative_version(ROOT)

    def test_nested_driver_environment_uses_authoritative_acp_selectors(self) -> None:
        inherited = {
            "BYQ_DSH_BUILD_RELEASE_ID": "dsh-0.1.5rc1",
            "BYQ_DSH_BUILD_UNRECOGNIZED": "ambient-value",
            "BYQ_DSH_BUILD_COMPATIBILITY_FAMILY": "dsh-0.1.5rc1",
            "BYQ_DSH_COMPATIBILITY_RELEASE": "dsh-0.1.5rc1",
            "BYQ_RUNTIME_AUTHORITY_TOKEN": "opaque-test-token",
            "OPENCODE_API_KEY": "f6-synthetic-only",
        }
        gateway = "http://127.0.0.1:49152"
        evidence = ROOT / ".ci-artifacts" / "offline-fixture-test" / "f6.json"
        resolved = self.fixture._f6_driver_environment(
            self.selection, inherited, gateway, evidence)

        self.assertEqual(resolved["BYQ_DSH_BUILD_RELEASE_ID"], self.selection["release_id"])
        self.assertEqual(resolved["BYQ_DSH_BUILD_SOURCE_COMMIT"], self.selection["source_commit"])
        self.assertEqual(resolved["BYQ_DSH_BUILD_PNPM_LOCK_SHA256"],
                         self.selection["pnpm_lock_sha256"])
        self.assertEqual(resolved["BYQ_DSH_BUILD_COMPATIBILITY_FAMILY"],
                         self.selection["compatibility_family"])
        self.assertEqual(resolved["BYQ_DSH_BUILD_SESSION_ROOT"],
                         f"/var/lib/byq/dsh-sessions/{self.selection['compatibility_family']}")
        for role, profile in (("ADAPTER", "product"),
                              ("ORDINARY_RUNNER", "product"),
                              ("JUDGMENT_RUNNER", "judgment")):
            self.assertEqual(resolved[f"BYQ_DSH_BUILD_{role}_PROFILE_PATH"],
                             self.selection["profiles"][profile]["path"])
        self.assertNotIn("BYQ_DSH_BUILD_UNRECOGNIZED", resolved)
        self.assertEqual(resolved["BYQ_RUNTIME_AUTHORITY_TOKEN"], "opaque-test-token")
        self.assertEqual(resolved["OPENCODE_API_KEY"], "f6-synthetic-only")
        self.assertEqual(resolved["BYQ_GOLDEN_ORIGIN"], gateway)
        self.assertEqual(resolved["BYQ_F6_EVIDENCE_PATH"], str(evidence))

    def test_synthetic_adapter_override_replaces_dispatcher_and_clears_command(self) -> None:
        project = "byq-ci-stack-offline-unified"
        override = self.fixture._fixture_override(project)
        adapter = override["services"]["runtime-adapter"]
        self.assertEqual(adapter["entrypoint"], [
            "/opt/byq-venv/bin/python3", "/app/acp-f6-runtime-entrypoint.py",
        ])
        self.assertEqual(adapter["command"], [])
        self.assertEqual(adapter["environment"]["BYQ_F6_CI_PROJECT"], project)

    def test_synthetic_entrypoint_allows_per_role_and_unified_adapter_identity(self) -> None:
        entrypoint = _load_runtime_entrypoint()
        identity = {"COMPOSE_PROJECT_NAME": "byq-ci-stack-offline"}
        entrypoint._validate_startup_identity(identity, 10002, 10002)
        entrypoint._validate_startup_identity(
            {**identity, "BYQ_ACP_ROLE": "adapter"}, 10002, 10002)
        for environment, uid, gid in (
            (identity, 0, 0),
            (identity, 10002, 10001),
            ({**identity, "BYQ_ACP_ROLE": "product"}, 10002, 10002),
            ({**identity, "BYQ_ACP_ROLE": "judgment"}, 10002, 10002),
            ({**identity, "BYQ_ACP_ROLE": "unknown"}, 10002, 10002),
        ):
            with self.subTest(environment=environment, uid=uid, gid=gid):
                with self.assertRaises(SystemExit):
                    entrypoint._validate_startup_identity(environment, uid, gid)

    def test_synthetic_entrypoint_rejects_root_before_fixture_import(self) -> None:
        entrypoint = _load_runtime_entrypoint()
        cases = (({}, 0, 0), ({"BYQ_ACP_ROLE": "product"}, 10002, 10002),
                 ({"BYQ_ACP_ROLE": "judgment"}, 10002, 10002))
        for environment, uid, gid in cases:
            with self.subTest(environment=environment, uid=uid, gid=gid), \
                    patch.dict(os.environ, environment, clear=True), \
                    patch.object(entrypoint.os, "geteuid", return_value=uid), \
                    patch.object(entrypoint.os, "getegid", return_value=gid), \
                    patch.object(entrypoint.importlib.util,
                                 "spec_from_file_location") as load_fixture:
                with self.assertRaises(SystemExit):
                    entrypoint.main()
                load_fixture.assert_not_called()

    def test_product_slot_uses_created_personal_workspace_before_adapter_restart(self) -> None:
        project = "byq-ci-stack-offline-workspace"
        scope = "offline-workspace"
        workspace = "workspace_" + "a" * 32
        environment = {
            "COMPOSE_PROJECT_NAME": project,
            "BYQ_CI_SCOPE": scope,
            "BYQ_F6_EXECUTOR_ENABLED": "0",
            "BYQ_ACP_PRODUCT_WORKSPACE_ID": "workspace_" + "b" * 32,
        }
        events = []

        def fake_compose(_files, env, _project, *args, **_kwargs):
            events.append((args, env.get("BYQ_ACP_PRODUCT_WORKSPACE_ID")))
            if args[0] == "exec" and "/tmp/f6-chain-fixture.py" in args:
                return json.dumps({"owner": "f6-chain-user", "workspace_id": workspace})
            return ""

        with tempfile.TemporaryDirectory() as temporary, \
             patch.dict(os.environ, environment, clear=True), \
             patch.object(self.fixture, "ROOT", Path(temporary)), \
             patch.object(self.fixture, "_compose_files", return_value=[Path("/tmp/base.yml"), Path("/tmp/acp.yml")]), \
             patch.object(self.fixture, "_captured_batch", return_value=({}, {}, {})), \
             patch.object(self.fixture, "_authoritative_compose_environment", side_effect=lambda _selection, env: dict(env)), \
             patch.object(self.fixture, "_fixture_override", return_value={"services": {}}), \
             patch.object(self.fixture, "_compose", side_effect=fake_compose), \
             patch.object(self.fixture, "_verify_captured_running_services",
                          side_effect=self.fixture.FixtureFailure("stop_after_wiring")):
            with self.assertRaises(self.fixture.FixtureFailure) as raised:
                self.fixture.run()
        self.assertEqual(raised.exception.category, "stop_after_wiring")
        self.assertEqual([event[0][0] for event in events[:2]], ["cp", "exec"])
        starts = [event for event in events if event[0][0] == "up"]
        self.assertEqual(len(starts), 3)
        self.assertEqual(starts[0][0][-1], "acp-product-runner")
        self.assertEqual(starts[0][1], workspace)
        self.assertEqual(starts[1][1], workspace)
        copies = [index for index, event in enumerate(events) if event[0][0] == "cp"]
        self.assertEqual(len(copies), 2)
        self.assertLess(events.index(starts[1]), copies[1])
        self.assertEqual(events[copies[1]][0][-1], "backend:/tmp/f6-chain-fixture.py")
        self.assertEqual(events[copies[1]][1], workspace)
        self.assertEqual(starts[2][1], environment["BYQ_ACP_PRODUCT_WORKSPACE_ID"])
        self.assertIn("acp-product-runner", starts[2][0])
        with self.assertRaises(self.fixture.FixtureFailure):
            self.fixture._user_fixture_workspace({"owner": "f6-chain-user",
                                                  "workspace_id": "workspace_invalid"})

    def test_running_signal_worker_is_bound_to_its_captured_batch_image(self) -> None:
        image_ids = {
            service: f"sha256:{index + 1:064x}"
            for index, service in enumerate(SERVICES)
        }
        with patch.object(self.fixture, "_docker_json", return_value=[{
            "Id": "sha256:" + "f" * 64,
        }]), patch.object(self.fixture, "_container_image") as inspect_container:
            self.fixture._verify_captured_running_services(
                [], {}, "byq-ci-stack-offline-fixture", image_ids)

        self.assertIn("signal-worker", self.fixture.CAPTURED_RUNNING_SERVICES)
        self.assertIn("signal-sandbox", self.fixture.CAPTURED_RUNNING_SERVICES)
        self.assertIn(call([], {}, "byq-ci-stack-offline-fixture", "signal-worker",
                           image_ids["signal-worker"]), inspect_container.call_args_list)
        self.assertIn(call([], {}, "byq-ci-stack-offline-fixture", "signal-sandbox",
                           image_ids["signal-sandbox"]), inspect_container.call_args_list)

    def test_prepared_f6_user_reuses_exact_product_slot_without_second_write(self) -> None:
        driver = ROOT / "scripts/evidence/f6-chain-verification.py"
        tree = ast.parse(driver.read_text(encoding="utf-8"), filename=str(driver))
        selected = [node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "_fixture_workspace"]
        self.assertEqual(len(selected), 1)

        class FixtureError(RuntimeError):
            pass

        def require_valid(condition, category):
            if not condition:
                raise FixtureError(category)

        def identifier_valid(value, pattern, category):
            require_valid(isinstance(value, str) and pattern.fullmatch(value) is not None,
                          category)
            return value

        namespace = {"re": re, "require": require_valid, "identifier": identifier_valid}
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(driver), "exec"), namespace)
        workspace = "workspace_" + "a" * 32
        calls = []

        def create_user():
            calls.append("write")
            return {"owner": "f6-chain-user", "workspace_id": workspace}

        resolve = namespace["_fixture_workspace"]
        self.assertEqual(resolve(workspace, workspace, create_user), workspace)
        self.assertEqual(calls, [])
        with self.assertRaisesRegex(FixtureError, "test_user_product_slot_mismatch"):
            resolve(workspace, "workspace_" + "b" * 32, create_user)
        with self.assertRaisesRegex(FixtureError, "test_user_workspace_invalid"):
            resolve("workspace_invalid", workspace, create_user)
        self.assertEqual(calls, [])
        self.assertEqual(resolve(None, None, create_user), workspace)
        self.assertEqual(calls, ["write"])

    def test_product_session_http_diagnostic_excludes_untrusted_response_text(self) -> None:
        driver = ROOT / "scripts/evidence/f6-chain-verification.py"
        tree = ast.parse(driver.read_text(encoding="utf-8"), filename=str(driver))
        selected = [node for node in tree.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "_product_session_public_error_reason"]
        self.assertEqual(len(selected), 1)
        namespace = {"json": json}
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(driver), "exec"), namespace)
        classify = namespace["_product_session_public_error_reason"]
        self.assertEqual(classify(io.BytesIO(b'{"detail":"Agent runtime authority is not ready"}')),
                         "runtime_authority_not_ready")
        self.assertEqual(classify(io.BytesIO(b'{"detail":"product model is unavailable"}')),
                         "product_model_unavailable")
        self.assertEqual(classify(io.BytesIO(b'{"detail":"private-value-should-never-appear"}')),
                         "unclassified")
        self.assertEqual(classify(io.BytesIO(b'not-json')),
                         "unclassified")

        class IncompleteResponse:
            def read(self, _limit):
                raise IncompleteRead(b'partial')

        self.assertEqual(classify(IncompleteResponse()), "unclassified")

    def test_success_writes_primary_before_cleanup_closeout(self) -> None:
        driver = ROOT / "scripts/evidence/f6-chain-verification.py"
        tree = ast.parse(driver.read_text(encoding="utf-8"), filename=str(driver))
        drivers = [node for node in tree.body if isinstance(node, ast.Try)
                   and any(isinstance(item, ast.ExceptHandler) for item in node.handlers)
                   and any(isinstance(item, ast.Call)
                           and isinstance(item.func, ast.Name)
                           and item.func.id == "_write_evidence"
                           for statement in node.finalbody for item in ast.walk(statement))]
        self.assertEqual(len(drivers), 1)
        driver_try = drivers[0]
        success_writes = [item for statement in driver_try.body for item in ast.walk(statement)
                          if isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
                          and item.func.id == "_write_evidence"]
        self.assertEqual(len(success_writes), 1)
        self.assertEqual(success_writes[0].keywords, [])
        self.assertEqual(success_writes[0].args, [])
        self.assertGreater(success_writes[0].lineno, driver_try.body[-2].lineno)
        closeout_writes = [item for statement in driver_try.finalbody for item in ast.walk(statement)
                           if isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
                           and item.func.id == "_write_evidence"]
        self.assertEqual(len(closeout_writes), 1)
        self.assertEqual(len(closeout_writes[0].keywords), 1)
        self.assertEqual(closeout_writes[0].keywords[0].arg, "suffix")

    def test_container_identity_check_rejects_stopped_signal_worker(self) -> None:
        project = "byq-ci-stack-offline-fixture"
        container_id = "a" * 64
        image_id = "sha256:" + "b" * 64
        inspected = [{
            "Id": container_id,
            "Image": image_id,
            "Config": {"Labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.service": "signal-worker",
            }},
            "State": {"Running": False},
        }]
        with patch.object(self.fixture, "_compose", return_value=container_id), \
             patch.object(self.fixture, "_docker_json", return_value=inspected):
            with self.assertRaises(self.fixture.FixtureFailure) as raised:
                self.fixture._container_image([], {}, project, "signal-worker", image_id)
        self.assertEqual(raised.exception.category,
                         "captured_service_container_identity_mismatch")


if __name__ == "__main__":
    unittest.main()
