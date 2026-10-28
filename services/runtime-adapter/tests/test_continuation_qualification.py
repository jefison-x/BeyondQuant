import threading
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


@pytest.mark.parametrize(
    "key,provider,model,family,root_scoped,product_slots,owner,workspace,expected",
    [
        ("synthetic", "opencode-go-chat", "deepseek-v4.1-flash",
         "dsh-v0.2.0-rc.2-acp", True, True, "owner-a", "workspace-a", True),
        ("", "opencode-go-chat", "deepseek-v4.1-flash",
         "dsh-v0.2.0-rc.2-acp", True, True, "owner-a", "workspace-a", False),
        ("synthetic", "other", "deepseek-v4.1-flash",
         "dsh-v0.2.0-rc.2-acp", True, True, "owner-a", "workspace-a", False),
        ("synthetic", "opencode-go-chat", "other",
         "dsh-v0.2.0-rc.2-acp", True, True, "owner-a", "workspace-a", False),
        ("synthetic", "opencode-go-chat", "deepseek-v4.1-flash",
         "dsh-v0.2.0-rc.2-acp", False, True, "owner-a", "workspace-a", False),
        ("synthetic", "opencode-go-chat", "deepseek-v4.1-flash",
         "dsh-v0.2.0-rc.2-acp", True, False, "owner-a", "workspace-a", False),
        ("synthetic", "opencode-go-chat", "deepseek-v4.1-flash",
         "dsh-v0.2.0-rc.2-acp", True, True, None, "workspace-a", False),
        ("synthetic", "opencode-go-chat", "deepseek-v4.1-flash",
         "dsh-v0.2.0-rc.2-acp", True, True, "owner-a", None, False),
        ("synthetic", "opencode-go-chat", "deepseek-v4.1-flash",
         "dsh-0.1.5", True, True, "owner-a", "workspace-a", False),
    ],
)
def test_task_ready_qualification_uses_product_acp_without_f6_gate(
    monkeypatch, key, provider, model, family, root_scoped, product_slots,
    owner, workspace, expected,
):
    adapter = object.__new__(runtime.RuntimeAdapter)
    adapter._root_scoped = root_scoped
    adapter._acp_product_slots = product_slots
    adapter._compatibility = SimpleNamespace(family=family)
    adapter._provider, adapter._model = "opencode-go-chat", "deepseek-v4.1-flash"
    monkeypatch.delenv("BYQ_F6_EXECUTOR_ENABLED", raising=False)
    record = SimpleNamespace(
        owner_principal=owner,
        workspace_id=workspace,
        model_resolution=dict(provider=provider, model=model, api_key=key),
    )
    assert adapter.task_ready_qualified(record) is expected


def test_continuation_qualification_endpoint_preserves_legacy_and_adds_task_ready(monkeypatch):
    from app import main

    record = SimpleNamespace(lock=threading.RLock())
    monkeypatch.setattr(main.adapter, "_get", lambda _session_id: record)
    monkeypatch.setattr(main.adapter, "continuation_qualified", lambda _record: False)
    monkeypatch.setattr(main.adapter, "task_ready_qualified", lambda _record: True)

    assert main.continuation_qualification("synthetic-session") == {
        "qualified": False,
        "task_ready_qualified": True,
        "reason": "model_or_executor_unqualified",
    }


def test_missing_continuation_qualification_reports_both_paths_false(monkeypatch):
    from app import main

    def missing(_session_id):
        raise KeyError("missing")

    monkeypatch.setattr(main.adapter, "_get", missing)
    assert main.continuation_qualification("missing-session") == {
        "qualified": False,
        "task_ready_qualified": False,
        "reason": "session_missing",
    }
