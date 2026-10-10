"""Runtime selection is ACP-only and does not require Python DSH distributions."""

from importlib import metadata
from pathlib import Path

import pytest

from app.compat import ACP_COMPATIBILITY_FAMILY
from app.runtime import RuntimeAdapter


@pytest.mark.parametrize("legacy_release", ["dsh-0.1.2rc1", "dsh-0.1.5rc1"])
def test_runtime_adapter_rejects_explicit_legacy_selector(monkeypatch, legacy_release: str) -> None:
    monkeypatch.setenv("BYQ_DSH_COMPATIBILITY_RELEASE", legacy_release)
    with pytest.raises(ValueError, match="unsupported DSH compatibility release"):
        RuntimeAdapter()


def test_default_runtime_uses_acp_without_sdk_distribution(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("BYQ_DSH_COMPATIBILITY_RELEASE", raising=False)
    runtime_root = tmp_path / "runtime"
    entry = runtime_root / "apps" / "cli" / "lib" / "bin.js"
    entry.parent.mkdir(parents=True)
    entry.write_text("synthetic ACP entry", encoding="utf-8")
    (runtime_root / "pnpm-lock.yaml").write_text("synthetic lock", encoding="utf-8")
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv("BYQ_DSH_ACP_PROCESS_TRANSPORT", "local")

    def no_python_dsh_distribution(_name: str) -> str:
        raise metadata.PackageNotFoundError("Python DSH SDK is not installed")

    # If normal startup/readiness starts querying the legacy Python distributions,
    # this fails the test rather than silently using a machine-installed SDK.
    monkeypatch.setattr(metadata, "version", no_python_dsh_distribution)
    adapter = RuntimeAdapter()

    assert adapter._compatibility.family == ACP_COMPATIBILITY_FAMILY
    assert adapter.runtime_command[-1] == str(entry)
