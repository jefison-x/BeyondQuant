#!/usr/bin/env python3
"""Bounded setup/assertions for the isolated F6 real-domain integration test."""
import json
import os
import sys
from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchStore
from app.market_data import MarketDataStore
from app.backtest import membership_fingerprint
from tests.workspace_helpers import trusted_agent_context

if os.environ.get('BYQ_F6_FIXTURE') != '1':
    raise SystemExit('explicit isolated fixture invocation required')
owner = 'f6-chain-user'
action = sys.argv[1]
payload = json.load(sys.stdin) if action != 'user' else {}
if action == 'user':
    trusted_agent_context(owner)
    print(json.dumps({'owner': owner}))
elif action == 'bind':
    catalog = ConversationCatalogStore()
    conversation = catalog.get(owner, payload['conversation_id'])
    catalog.close()
    headers = trusted_agent_context(owner, session_id=conversation['runtime_session_id'], trace_id=conversation['trace_id'])
    context = {k.removeprefix('x-byq-').replace('-', '_'): v for k, v in headers.items()}
    store = ResearchStore()
    task = store.create_task({'owner_principal': owner, 'title': 'F6 自动续接全链验收',
        'objective': 'After the explicitly approved LightGBM training completes, produce predictions and frozen signals, run the native backtest and compare its measured total return with the confirmed baseline. Save a comparison report before completing this task. Inputs are labelled synthetic integration fixtures.',
        'trace_id': context['trace_id'], 'idempotency_key': 'f6-chain-task'}, trusted_context=context)
    market = MarketDataStore()
    bars = market.list_bars(['000001.SZ', '600000.SH'], '20260312', '20260330', limit=100)
    assert len(bars) == 38
    public_bars = [{k: row[k] for k in ('symbol', 'trade_date', 'open', 'high', 'low', 'close')} for row in bars]
    for row in public_bars:
        day = row['trade_date']
        row['trade_date'] = f'{day[:4]}-{day[4:6]}-{day[6:]}'
    print(json.dumps({'task': task, 'bars': public_bars,
        'membership_fingerprint': membership_fingerprint(['000001.SZ', '600000.SH'])}))
    market.close(); store.close()
elif action == 'checkpoint':
    store = ResearchStore()
    store.transition('research_task', payload['task_id'], 'running', 'f6-fixture-checkpoint', progress={
        'schema_version': 'research-progress.v1', 'stage': 'training',
        'next_action': 'Wait for the explicitly approved training, then prediction, signals, backtest and comparison',
        'blocked_reason': None, 'linked_objects': [
            {'kind': 'artifact', 'id': payload['approval_artifact_id']},
            {'kind': 'artifact', 'id': payload['baseline_artifact_id']}], 'completion_evidence': []})
    store.close(); print(json.dumps({'checkpoint': 'saved'}))
elif action == 'verify':
    store = ResearchStore()
    task = store._fetch_one('SELECT * FROM research_tasks WHERE task_id=:task AND owner_principal=:owner',
        {'task': payload['task_id'], 'owner': owner})
    assert task['status'] == 'completed', task['status']
    budget = task['continuation_budget']
    assert len(budget) == 3 and len({r['event_key'] for r in budget}) == 3
    assert all(r['status'] == 'settled' and r['dispatch_attempts'] == 1 for r in budget)
    assert sum(r['charged_tokens'] for r in budget) <= task['continuation_permission']['token_limit']
    counts = {}
    for table in ('ml_training_runs', 'ml_prediction_runs', 'backtest_jobs'):
        rows = store._execute(f'SELECT status FROM {table} WHERE task_id=:task', {'task': task['task_id']})
        assert all(r['status'] == 'completed' for r in rows)
        counts[table] = len(rows)
    assert counts == {'ml_training_runs': 1, 'ml_prediction_runs': 1, 'backtest_jobs': 2}, counts
    evidence = task['progress']['completion_evidence']
    assert len(evidence) == 1
    report = store.get_artifact(evidence[0])
    assert report['kind'] == 'comparison_report' and report['status'] == 'validated'
    result = report['content']
    assert result['delta_total_return'] == result['candidate']['total_return'] - result['baseline']['total_return']
    print(json.dumps({'status': 'passed', 'task_id': task['task_id'], 'counts': counts,
        'turns': len(budget), 'charged_ceiling': sum(r['charged_tokens'] for r in budget), 'evidence': evidence}))
    store.close()
else:
    raise SystemExit('unknown fixture operation')
