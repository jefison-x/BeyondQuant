from types import SimpleNamespace

import pytest
from app import runtime


@pytest.mark.parametrize(
    "enabled,key,provider,model,sdk_version,runtime_version,family,root_scoped,expected",
    [
        ("1", "synthetic", "deepseek-official", "deepseek-v4-flash", "0.1.5rc1", "0.1.5rc1", "dsh-0.1.5", True, True),
        ("0", "synthetic", "deepseek-official", "deepseek-v4-flash", "0.1.5rc1", "0.1.5rc1", "dsh-0.1.5", True, False),
        ("1", "", "deepseek-official", "deepseek-v4-flash", "0.1.5rc1", "0.1.5rc1", "dsh-0.1.5", True, False),
        ("1", "synthetic", "other", "deepseek-v4-flash", "0.1.5rc1", "0.1.5rc1", "dsh-0.1.5", True, False),
        ("1", "synthetic", "deepseek-official", "other", "0.1.5rc1", "0.1.5rc1", "dsh-0.1.5", True, False),
        ("1", "synthetic", "opencode-go-chat", "deepseek-v4-flash", "0.1.5rc1", "0.1.5rc1", "dsh-0.1.5", True, False),
        ("1", "synthetic", "deepseek-official", "deepseek-v4-flash", "0.1.2rc1", "0.1.2rc1", "dsh-0.1.2", True, False),
        ("1", "synthetic", "deepseek-official", "deepseek-v4-flash", "0.1.5rc1", "0.1.2rc1", "dsh-0.1.5", True, False),
        ("1", "synthetic", "deepseek-official", "deepseek-v4-flash", "0.1.5rc1", "0.1.5rc1", "dsh-0.1.2", True, False),
        ("1", "synthetic", "deepseek-official", "deepseek-v4-flash", "0.1.5rc1", "0.1.5rc1", "dsh-0.1.5", False, False),
    ],
)
def test_qualification_is_exact_to_the_pinned_task_ready_profile(
    monkeypatch, enabled, key, provider, model, sdk_version, runtime_version, family, root_scoped, expected,
):
    adapter = object.__new__(runtime.RuntimeAdapter)
    adapter._root_scoped = root_scoped
    adapter._compatibility = SimpleNamespace(family=family)
    adapter._provider, adapter._model = "deepseek-official", "deepseek-v4-flash"
    monkeypatch.setenv("BYQ_F6_EXECUTOR_ENABLED", enabled)
    versions = {
        "deepseek-harness-sdk": sdk_version,
        "deepseek-harness-runtime-bin": runtime_version,
    }
    monkeypatch.setattr(runtime, "distribution_version", lambda name: versions[name])
    record = SimpleNamespace(model_resolution=dict(provider=provider, model=model, api_key=key))
    assert adapter.continuation_qualified(record) is expected
