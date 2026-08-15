from __future__ import annotations

from pathlib import Path

import app.runtime as runtime_module
from app.runtime import RuntimeAdapter


class FakeHarness:
    instances: list["FakeHarness"] = []

    def __init__(self, config: object) -> None:
        self.config = config
        self.started = False
        self.closed = False
        self.__class__.instances.append(self)

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True


def test_dedicated_session_runtime_is_closed_on_hard_cancel(monkeypatch, tmp_path: Path) -> None:
    FakeHarness.instances.clear()
    monkeypatch.setattr(runtime_module, "DeepSeekHarness", FakeHarness)
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(tmp_path / "composition.yml"))
    adapter = RuntimeAdapter()

    created = adapter.create_session("s-1", "t-1")
    assert created["process_ownership"] == "dedicated"
    assert FakeHarness.instances[0].started is True
    config = FakeHarness.instances[0].config
    assert Path(config.launch_args_override[0]).name == "node"
    assert config.cordis == str(tmp_path / "composition.yml")

    cancelled = adapter.cancel_session("s-1", "hard")
    assert cancelled["status"] == "interrupted"
    assert FakeHarness.instances[0].closed is True

    adapter.close()
