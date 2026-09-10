from types import SimpleNamespace
import pytest
from app import runtime


@pytest.mark.parametrize('enabled,key,provider,model,version,expected', [
    ('1', 'synthetic', 'deepseek-official', 'deepseek-v4-flash', '0.1.2rc1', True),
    ('0', 'synthetic', 'deepseek-official', 'deepseek-v4-flash', '0.1.2rc1', False),
    ('1', '', 'deepseek-official', 'deepseek-v4-flash', '0.1.2rc1', False),
    ('1', 'synthetic', 'other', 'deepseek-v4-flash', '0.1.2rc1', False),
    ('1', 'synthetic', 'deepseek-official', 'other', '0.1.2rc1', False),
    ('1', 'synthetic', 'deepseek-official', 'deepseek-v4-flash', '0.1.1rc1', False),
])
def test_qualification_prevents_reserving_for_unusable_credentials_or_routes(monkeypatch, enabled, key, provider, model, version, expected):
    adapter = object.__new__(runtime.RuntimeAdapter)
    adapter._root_scoped = True
    adapter._compatibility = SimpleNamespace(family='dsh-0.1.2')
    adapter._provider, adapter._model = 'deepseek-official', 'deepseek-v4-flash'
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', enabled)
    monkeypatch.setattr(runtime, 'distribution_version', lambda _: version)
    record = SimpleNamespace(model_resolution=dict(provider=provider, model=model, api_key=key))
    assert adapter.continuation_qualified(record) is expected
