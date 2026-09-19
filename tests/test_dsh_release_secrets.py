import json
from pathlib import Path
import contextlib
import io
import tempfile
import unittest

from scripts.dsh import release_secrets as secrets


def overlay_with_environment():
    return {
        "services": {
            "backend": {
                "image": "ghcr.io/jefison-x/beyondquant/backend@sha256:" + "a" * 64,
                "pull_policy": "never",
                "environment": {
                    "BYQ_BACKTEST_OBJECT_ROOT": "/var/lib/byq/domain/backtest-objects",
                    "BYQ_CREDENTIAL_RESOLVER_TOKEN": "example-resolver-token",
                    "BYQ_DATABASE_URL": (
                        "postgresql+psycopg://" + "example-user" + ":" + "example-password" + "@postgres:5432/example_db"
                    ),
                    "TUSHARE_TOKEN": "a" * 64,
                    "BYQ_DATABASE_URL_REFERENCE": "${BYQ_DATABASE_URL}",
                },
            }
        }
    }


class SecretKeyTests(unittest.TestCase):
    def test_known_secret_keys_are_classified(self):
        for name in (
            "TUSHARE_TOKEN", "DEEPSEEK_API_KEY", "BYQ_MCP_TOKEN", "BYQ_PRODUCT_TOKEN",
            "BYQ_FEEDBACK_HUB_RELAY_TOKEN", "BYQ_CREDENTIAL_RESOLVER_TOKEN",
            "BYQ_CREDENTIAL_KEYRING", "BYQ_CREDENTIAL_ACTIVE_KEY_ID",
            "POSTGRES_PASSWORD", "BYQ_DATABASE_URL", "BYQ_BOOTSTRAP_ADMIN_PASSWORD",
        ):
            self.assertTrue(secrets.is_secret_key(name), name)

    def test_non_secret_keys_stay_non_secret(self):
        for name in (
            "BYQ_BACKTEST_OBJECT_ROOT", "BYQ_BACKEND_URL", "BYQ_DSH_COMPOSITION",
            "BYQ_DSH_COMPOSITION_IDENTITY", "BYQ_F6_EXECUTOR_ENABLED",
            "BYQ_PLUGIN_REGISTRY_PATH", "DSH_SESSION_ROOT", "TUSHARE_API_URL",
        ):
            self.assertFalse(secrets.is_secret_key(name), name)


class SanitizeTests(unittest.TestCase):
    def test_secret_literals_become_references(self):
        clean = secrets.sanitize_overlay(overlay_with_environment())
        environment = clean["services"]["backend"]["environment"]
        self.assertEqual(environment["TUSHARE_TOKEN"], "${TUSHARE_TOKEN}")
        self.assertEqual(environment["BYQ_CREDENTIAL_RESOLVER_TOKEN"], "${BYQ_CREDENTIAL_RESOLVER_TOKEN}")
        self.assertEqual(environment["BYQ_DATABASE_URL"], "${BYQ_DATABASE_URL}")
        self.assertEqual(environment["BYQ_BACKTEST_OBJECT_ROOT"], "/var/lib/byq/domain/backtest-objects")
        self.assertEqual(environment["BYQ_DATABASE_URL_REFERENCE"], "${BYQ_DATABASE_URL}")
        # Original input must not be mutated in place.
        self.assertNotEqual(
            overlay_with_environment()["services"]["backend"]["environment"]["TUSHARE_TOKEN"],
            "${TUSHARE_TOKEN}",
        )

    def test_list_form_environment_is_sanitized(self):
        overlay = {"services": {"mcp": {"environment": ["BYQ_MCP_TOKEN=secret-value", "BYQ_BACKEND_URL=http://backend:8000"]}}}
        clean = secrets.sanitize_overlay(overlay)
        self.assertEqual(clean["services"]["mcp"]["environment"][0], "BYQ_MCP_TOKEN=${BYQ_MCP_TOKEN}")

    def test_secret_like_value_under_non_secret_key_fails_closed(self):
        overlay = {"services": {"gateway": {"environment": {"BYQ_NOTE": "Bearer " + "example-token"}}}}
        with self.assertRaises(secrets.SecretBoundaryError):
            secrets.sanitize_overlay(overlay)


class GuardTests(unittest.TestCase):
    def test_plaintext_secret_under_secret_key_is_rejected(self):
        with self.assertRaisesRegex(secrets.SecretBoundaryError, "BYQ_CREDENTIAL_RESOLVER_TOKEN"):
            secrets.assert_no_plaintext_secrets(overlay_with_environment())

    def test_reference_form_passes(self):
        secrets.assert_no_plaintext_secrets(secrets.sanitize_overlay(overlay_with_environment()))

    def test_known_secret_value_is_rejected_anywhere(self):
        artifact = {"services": {"mcp": {"environment": {"BYQ_BACKEND_URL": "leaked-value"}}}}
        with self.assertRaisesRegex(secrets.SecretBoundaryError, "known secret"):
            secrets.assert_no_plaintext_secrets(artifact, secret_values=["leaked-value"])

    def test_secret_like_pattern_is_rejected_anywhere(self):
        with self.assertRaises(secrets.SecretBoundaryError):
            secrets.assert_no_plaintext_secrets({"image": "sk-" + "examplevalue"})
        with self.assertRaises(secrets.SecretBoundaryError):
            secrets.assert_no_plaintext_secrets({"command": ["-----BEGIN " + "RSA PRIVATE KEY-----"]})

    def test_redact_resolved_replaces_secret_values(self):
        resolved = {
            "services": {
                "backend": {
                    "environment": {
                        "TUSHARE_TOKEN": "b" * 32,
                        "BYQ_DATABASE_URL": "postgresql+psycopg://" + "example-user" + ":" + "example-password" + "@postgres:5432/example_db",
                        "BYQ_F6_EXECUTOR_ENABLED": "0",
                    }
                }
            }
        }
        redacted = secrets.redact_resolved(resolved)
        environment = redacted["services"]["backend"]["environment"]
        self.assertEqual(environment["TUSHARE_TOKEN"], "${TUSHARE_TOKEN}")
        self.assertEqual(environment["BYQ_DATABASE_URL"], "${BYQ_DATABASE_URL}")
        self.assertEqual(environment["BYQ_F6_EXECUTOR_ENABLED"], "0")


class ProtectedSourceTests(unittest.TestCase):
    def test_public_source_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("TUSHARE_TOKEN=value\n")
            path.chmod(0o644)
            with self.assertRaisesRegex(secrets.SecretBoundaryError, "group/world"):
                secrets.parse_protected_env(path)

    def test_private_source_parses_without_serializing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("# comment\nexport TUSHARE_TOKEN='quoted-value'\nBYQ_MCP_TOKEN=plain\n")
            path.chmod(0o600)
            values = secrets.parse_protected_env(path)
            self.assertEqual(values["TUSHARE_TOKEN"], "quoted-value")
            self.assertEqual(values["BYQ_MCP_TOKEN"], "plain")

    def test_verify_injection_fails_closed_when_required_secret_missing(self):
        clean = secrets.sanitize_overlay(overlay_with_environment())
        with self.assertRaisesRegex(secrets.SecretBoundaryError, "BYQ_CREDENTIAL_RESOLVER_TOKEN"):
            secrets.verify_injection(clean, {})

    def test_verify_injection_resolves_present_secrets(self):
        clean = secrets.sanitize_overlay(overlay_with_environment())
        source = {"TUSHARE_TOKEN": "tushare-value", "BYQ_DATABASE_URL": "postgresql+psycopg://u:p@h/db",
                  "BYQ_CREDENTIAL_RESOLVER_TOKEN": "resolver-value"}
        resolved = secrets.verify_injection(clean, source)
        self.assertEqual(resolved["backend"]["TUSHARE_TOKEN"], "tushare-value")
        self.assertEqual(resolved["backend"]["BYQ_BACKTEST_OBJECT_ROOT"], "/var/lib/byq/domain/backtest-objects")


class CliTests(unittest.TestCase):
    def test_cli_sanitize_then_check(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "target.compose.json"
            output = Path(directory) / "target.sanitized.json"
            source.write_text(json.dumps(overlay_with_environment()))
            self.assertEqual(
                secrets.main(["sanitize", "--input", str(source), "--output", str(output)]), 0
            )
            self.assertEqual(secrets.main(["check", str(output)]), 0)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("byq-app-dev", output.read_text())
            self.assertIn("${TUSHARE_TOKEN}", output.read_text())

    def test_cli_check_rejects_unsanitized_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "target.compose.json"
            path.write_text(json.dumps(overlay_with_environment()))
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                self.assertEqual(secrets.main(["check", str(path)]), 1)
            report = json.loads(buffer.getvalue())
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("secret key", report["reason"])


if __name__ == "__main__":
    unittest.main()
