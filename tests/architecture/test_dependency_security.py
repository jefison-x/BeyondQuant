import json
from pathlib import Path
import re
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _exact_pin(path: Path, package: str, section: str) -> str:
    document = tomllib.loads(path.read_text())
    requirements = document["project"][section]
    prefix = f"{package}=="
    matches = [item.removeprefix(prefix) for item in requirements if item.startswith(prefix)]
    if len(matches) != 1:
        raise AssertionError(f"expected one exact {package} pin in {path}")
    return matches[0]


class DependencySecurityTests(unittest.TestCase):
    def test_cryptography_runtime_pins_are_aligned_and_patched(self):
        backend = _exact_pin(ROOT / "services/backend/pyproject.toml", "cryptography", "dependencies")
        publisher = re.search(
            r"\bcryptography==([0-9.]+)\b",
            (ROOT / "workers/feedback-publisher/Dockerfile").read_text(),
        )
        self.assertIsNotNone(publisher)
        self.assertEqual(publisher.group(1), backend)
        self.assertGreaterEqual(_version_tuple(backend), (50, 0, 0))

    def test_python_build_and_test_tools_clear_advisory_floors(self):
        projects = [
            ROOT / "services/backend/pyproject.toml",
            ROOT / "services/gateway/pyproject.toml",
            ROOT / "services/runtime-adapter/pyproject.toml",
            ROOT / "services/signal-sandbox/pyproject.toml",
        ]
        setuptools_versions = []
        for path in projects:
            build_requires = tomllib.loads(path.read_text())["build-system"]["requires"]
            matches = [value.removeprefix("setuptools==") for value in build_requires if value.startswith("setuptools==")]
            self.assertEqual(len(matches), 1, path)
            setuptools_versions.extend(matches)
        self.assertEqual(len(set(setuptools_versions)), 1)
        self.assertGreaterEqual(_version_tuple(setuptools_versions[0]), (83, 0, 0))

        pytest_versions = []
        for path in projects[:3]:
            document = tomllib.loads(path.read_text())
            pins = [item.removeprefix("pytest==") for item in document["project"]["optional-dependencies"]["test"] if item.startswith("pytest==")]
            self.assertEqual(len(pins), 1, path)
            pytest_versions.extend(pins)
        self.assertEqual(len(set(pytest_versions)), 1)
        self.assertGreaterEqual(_version_tuple(pytest_versions[0]), (9, 0, 3))

    def test_runtime_qs_lock_clears_both_advisories(self):
        lock = json.loads((ROOT / "services/runtime-adapter/runtime/package-lock.json").read_text())
        version = lock["packages"]["node_modules/qs"]["version"]
        self.assertGreaterEqual(_version_tuple(version), (6, 16, 0))


if __name__ == "__main__":
    unittest.main()
