"""Reject unusable approvals before opening a database transaction."""
import pytest
from app.agent_research import AgentResearchStore


@pytest.mark.parametrize('resource_type,resource_id', [('artifact','artifact_'+'a'*32),(None,None)])
def test_strategy_approval_requires_exact_resource_type(resource_type, resource_id):
    store = object.__new__(AgentResearchStore)
    payload = dict(run_id='agent_run_'+'a'*32, action='byq_strategy_approve', reason='review',
        resource_type=resource_type, resource_id=resource_id, idempotency_key='approval')
    with pytest.raises(ValueError, match='requires resource_type=strategy_version'):
        store.create_approval(payload)
