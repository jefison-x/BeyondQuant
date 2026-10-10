from types import SimpleNamespace
from importlib import metadata

import pytest
from app import runtime


@pytest.mark.parametrize(
    "enabled,key,provider,model,family,root_scoped,expected",
    [
        ("1", "synthetic", "opencode-go-chat", "deepseek-v4.1-flash",
         "dsh-v0.2.0-rc.2-acp", True, True),
        ("0", "synthetic", "opencode-go-chat", "deepseek-v4.1-flash",
         "dsh-v0.2.0-rc.2-acp", True, False),
        ("1", "", "opencode-go-chat", "deepseek-v4.1-flash",
         "dsh-v0.2.0-rc.2-acp", True, False),
        ("1", "synthetic", "other", "deepseek-v4.1-flash",
         "dsh-v0.2.0-rc.2-acp", True, False),
        ("1", "synthetic", "opencode-go-chat", "other",
         "dsh-v0.2.0-rc.2-acp", True, False),
        ("1", "synthetic", "deepseek-official", "deepseek-v4.1-flash",
         "dsh-v0.2.0-rc.2-acp", True, False),
        ("1", "synthetic", "opencode-go-chat", "deepseek-v4.1-flash",
         "dsh-v0.2.0-rc.2-acp", False, False),
        ("1", "synthetic", "opencode-go-chat", "deepseek-v4.1-flash",
         "dsh-0.1.5", True, False),
        ("1", "synthetic", "opencode-go-chat", "deepseek-v4.1-flash",
         "dsh-0.1.2", True, False),
    ],
)
def test_continuation_qualification_requires_fixed_acp_and_existing_business_gates(
    monkeypatch, enabled, key, provider, model, family, root_scoped, expected,
):
    adapter = object.__new__(runtime.RuntimeAdapter)
    adapter._root_scoped = root_scoped
    adapter._compatibility = SimpleNamespace(family=family)
    adapter._provider, adapter._model = "opencode-go-chat", "deepseek-v4.1-flash"
    monkeypatch.setenv("BYQ_F6_EXECUTOR_ENABLED", enabled)

    def no_python_dsh_distribution(_name: str) -> str:
        raise metadata.PackageNotFoundError("Python DSH SDK is not installed")

    monkeypatch.setattr(metadata, "version", no_python_dsh_distribution)
    record = SimpleNamespace(model_resolution=dict(provider=provider, model=model, api_key=key))
    assert adapter.continuation_qualified(record) is expected
