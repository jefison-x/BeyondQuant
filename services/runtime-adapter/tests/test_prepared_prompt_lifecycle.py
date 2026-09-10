"""Exercise the real SDK Session after close, without launching a process."""
from importlib.metadata import version
from pathlib import Path

import pytest

from tests.legacy_011 import Dsh011Compatibility
from app.compat.dsh_012 import Dsh012Compatibility


def test_prepared_official_session_cannot_restart_closed_harness(monkeypatch, tmp_path):
    compatibility = Dsh012Compatibility() if version("deepseek-harness-sdk") == "0.1.2rc1" else Dsh011Compatibility()
    profile = tmp_path / "synthetic-profile.yml"
    profile.write_text("{}\n")
    harness = compatibility.build_harness(provider="deepseek-official", model="deepseek-chat",
        composition=profile, session_root=tmp_path / "session",
        runtime_command=compatibility.runtime_command(Path("/opt/dsh-runtime"), "node"), environment={})
    starts = []
    # Stub only the public process-start operation. The Session and transport
    # rejection paths are the installed official SDK, not a FakeHarness.
    monkeypatch.setattr(harness, "start", lambda: starts.append("start"))
    session = compatibility.prepare_prompt(harness, "synthetic-closed-session")
    harness.close()
    with pytest.raises(Exception) as caught:
        compatibility.run_prepared_prompt(session, "synthetic cancelled prompt", lambda event: None)
    assert type(caught.value).__name__ == "TransportClosedError"
    assert starts == ["start"]
