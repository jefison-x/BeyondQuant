"""ADR-0090 one-request scope tests for exact read-only targets."""

import os

import pytest

from app.continuation_scope import authorize
from tests.test_data_ready_continuation import setup_ready

pytestmark = pytest.mark.skipif(not os.environ.get('BYQ_DATABASE_URL'), reason='isolated PostgreSQL required')


def setup(monkeypatch, tmp_path):
    fixture = setup_ready(monkeypatch, tmp_path)
    store, task, context = fixture['store'], fixture['payload']['task_id'], fixture['context']
    store.create_continuation_permission(task, {
        'idempotency_key': 'scope-confirmation',
        'confirmed_artifact_ids': [fixture['payload']['strategy_version_artifact_id']],
    }, trusted_context=context)
    fixture['jobs']._execute("UPDATE signal_producer_jobs SET updated_at=now() WHERE job_id=:job",
        {'job': fixture['job_id']})
    intent = store.claim_conversation_continuation(fixture['conversation'], trusted_context=context)
    assert intent['status'] == 'intent'
    assert store.claim_continuation_dispatch(task, intent['receipt']['reservation_id'],
        trusted_context=context) == {'dispatch': True, 'attempt': 1}
    return fixture, intent['receipt']


def close_fixture(fixture):
    fixture['store'].close()
    fixture['backtests'].close()
    fixture['jobs'].close()


def test_scope_binds_original_task_and_exact_root_after_durable_dispatch_claim(monkeypatch, tmp_path):
    fixture, receipt = setup(monkeypatch, tmp_path)
    store, task, context = fixture['store'], fixture['payload']['task_id'], fixture['context']
    call = {'tool': 'byq_research_get',
        'arguments': {'entity_type': 'research_task', 'entity_id': task},
        'root_run_id': 'a' * 32}
    try:
        reply = authorize(store, receipt['reservation_id'], call, context)
        assert reply['admitted'] is True and reply['task_id'] == task
        row = store._fetch_one('SELECT continuation_budget FROM research_tasks WHERE task_id=:task',
            {'task': task})['continuation_budget'][0]
        assert row['status'] == 'accepted'
        assert row['run_id'] == 'a' * 32
        with pytest.raises(ValueError, match='no longer admitted'):
            authorize(store, receipt['reservation_id'], {**call, 'root_run_id': 'b' * 32}, context)
    finally:
        close_fixture(fixture)


def test_scope_allows_only_the_exact_research_and_linked_backtest_reads(monkeypatch, tmp_path):
    fixture, receipt = setup(monkeypatch, tmp_path)
    store, task, context = fixture['store'], fixture['payload']['task_id'], fixture['context']
    root = 'c' * 32
    try:
        assert authorize(store, receipt['reservation_id'], {
            'tool': 'byq_research_get',
            'arguments': {'entity_type': 'research_task', 'entity_id': task},
            'root_run_id': root,
        }, context)['admitted'] is True

        # The only other domain read is the exact BacktestTask bound to this signal.
        backtest_id = receipt['backtest_task_id']
        assert authorize(store, receipt['reservation_id'], {
            'tool': 'byq_backtest_task_get',
            'arguments': {'backtest_task_id': backtest_id},
            'root_run_id': root,
        }, context)['admitted'] is True
        assert authorize(store, receipt['reservation_id'], {
            'tool': 'byq_backtest_task_get',
            'arguments': {'backtest_task_id': 'backtesttask_' + 'e' * 32},
            'root_run_id': root,
        }, context)['admitted'] is False
    finally:
        close_fixture(fixture)


@pytest.mark.parametrize('tool', [
    'byq_agent_approval_decide', 'byq_research_task_create', 'byq_research_transition',
    'byq_ml_training_create', 'byq_ml_training_get', 'byq_ml_capabilities',
    'byq_backtest_task_prepare', 'byq_backtest_task_create', 'byq_backtest_task_execute',
    'byq_pool_create', 'byq_feedback_submit', 'byq_agent_context',
])
def test_profile_denies_mutation_broad_context_and_nonprofile_tools(monkeypatch, tmp_path, tool):
    fixture, receipt = setup(monkeypatch, tmp_path)
    try:
        assert authorize(fixture['store'], receipt['reservation_id'], {
            'tool': tool, 'arguments': {}, 'root_run_id': 'f' * 32,
        }, fixture['context'])['admitted'] is False
    finally:
        close_fixture(fixture)


@pytest.mark.parametrize('tool', ['byq_agent_authorize', 'byq_agent_audit'])
def test_agent_protocol_tools_are_scoped_to_the_two_exact_read_actions(monkeypatch, tmp_path, tool):
    fixture, receipt = setup(monkeypatch, tmp_path)
    task, context = fixture['payload']['task_id'], fixture['context']
    try:
        assert authorize(fixture['store'], receipt['reservation_id'], {
            'tool': tool,
            'arguments': {'action': 'byq_research_get', 'resource_type': 'research_task',
                          'resource_id': task},
            'root_run_id': '1' * 32,
        }, context)['admitted'] is True
        assert authorize(fixture['store'], receipt['reservation_id'], {
            'tool': tool,
            'arguments': {'action': 'byq_backtest_task_execute', 'resource_type': 'backtest_task',
                          'resource_id': receipt['backtest_task_id']},
            'root_run_id': '1' * 32,
        }, context)['admitted'] is False
    finally:
        close_fixture(fixture)


def test_scope_rejects_same_owner_other_task_and_cross_conversation(monkeypatch, tmp_path):
    fixture, receipt = setup(monkeypatch, tmp_path)
    store, task, context = fixture['store'], fixture['payload']['task_id'], fixture['context']
    try:
        other = store.create_task({'owner_principal': context['owner_principal'],
            'title': 'Other task', 'objective': 'Unrelated', 'trace_id': context['trace_id'],
            'idempotency_key': 'scope-other-task'}, trusted_context=context)
        call = {'tool': 'byq_research_get', 'arguments': {
            'entity_type': 'research_task', 'entity_id': other['task_id']}, 'root_run_id': '2' * 32}
        assert authorize(store, receipt['reservation_id'], call, context)['admitted'] is False
        # The blocked event remains bound to the exact failed reservation.
        row = store._fetch_one('''SELECT continuation_blocked_reason, continuation_blocked_event_key
            FROM research_tasks WHERE task_id=:task''', {'task': task})
        assert row['continuation_blocked_reason'] == 'continuation_needs_attention'
        assert row['continuation_blocked_event_key'] == receipt['event_key']
    finally:
        close_fixture(fixture)


def test_revocation_refuses_new_domain_admission_without_erasing_request_identity(monkeypatch, tmp_path):
    fixture, receipt = setup(monkeypatch, tmp_path)
    store, task, context = fixture['store'], fixture['payload']['task_id'], fixture['context']
    try:
        store.revoke_continuation_permission(task, grant_version=1, trusted_context=context)
        with pytest.raises(ValueError, match='no longer admitted'):
            authorize(store, receipt['reservation_id'], {
                'tool': 'byq_research_get',
                'arguments': {'entity_type': 'research_task', 'entity_id': task},
                'root_run_id': '3' * 32,
            }, context)
        view = store.get_continuation_permission(task, trusted_context=context)
        assert view['blocked_reason'] == 'permission_revoked'
        assert view['request_state']['request_identity']['reservation_id'] == receipt['reservation_id']
    finally:
        close_fixture(fixture)
