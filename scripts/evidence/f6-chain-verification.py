#!/usr/bin/env python3
"""Product API driver for an isolated scripted-Provider / real-domain F6 journey."""
import http.cookiejar
import json
import os
import re
import subprocess
import time
from urllib.request import Request, build_opener, HTTPCookieProcessor

origin = os.environ['BYQ_GOLDEN_ORIGIN'].rstrip('/')
if not os.environ.get('COMPOSE_PROJECT_NAME', '').startswith('byq-ci-stack-'):
    raise SystemExit('isolated CI stack required')


def fixture(action, payload=None):
    completed = subprocess.run(['docker', 'compose', 'exec', '-T', '-e', 'BYQ_F6_FIXTURE=1', 'backend',
        'python', '/tmp/f6-chain-fixture.py', action], input=json.dumps(payload or {}),
        text=True, capture_output=True, check=True, timeout=30)
    return json.loads(completed.stdout)


client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
def call(method, path, payload=None, *, expected=200, headers=None):
    request = Request(origin + path, data=json.dumps(payload).encode() if payload is not None else None,
        headers={'content-type': 'application/json', **(headers or {})}, method=method)
    with client.open(request, timeout=45) as response:
        assert response.status == expected, (path, response.status)
        return json.load(response)


fixture('user')
call('POST', '/api/product/auth/login', {'username': 'f6-chain-user', 'password': 'test-password-123'})
conversation = call('POST', '/v1/agent/sessions', {}, expected=201)
seed = fixture('bind', {'conversation_id': conversation['session_id']})
task, trace = seed['task']['task_id'], seed['task']['trace_id']
strategy = {'strategy_id': 'F6Baseline', 'name': 'F6 confirmed baseline', 'category': 'momentum',
    'description': 'Synthetic input fixture', 'parameters': {}, 'parameter_schema': {},
    'source_type': 'python_script', 'script': 'class CustomStrategy:\n    def generate_signals(self, data, parameters=None):\n        return {}'}
draft = call('POST', '/api/product/strategies/validate', {'task_id': task, 'strategy': strategy,
    'trace_id': trace, 'idempotency_key': 'f6-baseline-draft'}, expected=201)
version = call('POST', '/api/product/strategies/versions', {'task_id': task, 'draft_artifact_id': draft['artifact']['artifact_id'],
    'trace_id': trace, 'idempotency_key': 'f6-baseline-version'}, expected=201)
approval = call('POST', '/api/product/strategies/approvals', {'task_id': task,
    'strategy_version_artifact_id': version['artifact']['artifact_id'], 'decision': 'approved',
    'trace_id': trace, 'idempotency_key': 'f6-baseline-approval'}, expected=201)
baseline = call('POST', '/api/product/backtests', {'task_id': task,
    'strategy_version_artifact_id': version['artifact']['artifact_id'], 'approval_artifact_id': approval['artifact']['artifact_id'],
    'trace_id': trace, 'idempotency_key': 'f6-baseline-job',
    'universe': {'universe_id': 'f6-fixture', 'version_id': 'f6-baseline-v1',
        'membership_fingerprint': seed['membership_fingerprint'], 'symbols': ['000001.SZ', '600000.SH']},
    'bars': seed['bars'], 'signals': [], 'execution': {'initial_capital': 1000000, 'lot_size': 100}}, expected=202)
baseline = call('POST', f"/api/product/backtests/{baseline['job']['job_id']}/run", {})['job']
assert baseline['status'] == 'completed'
pool = call('POST', '/api/product/paper/pools', {'name': 'F6 frozen fixture pool', 'pool_type': 'custom',
    'description': 'Explicit synthetic integration inputs', 'symbols': ['000001.SZ', '600000.SH']}, expected=201)['pool']
ml = {'schema_version': 'ml-strategy-version.v2', 'name': 'F6 LightGBM task continuation',
    'feature_set': {'id': 'price-volume-basic-v1', 'parameters': {}},
    'target': {'id': 'forward-return-v1', 'parameters': {'horizon_sessions': 5}},
    'validation_plan': {'id': 'walk-forward-purged-v1', 'parameters': {'mode': 'expanding', 'train_sessions': 60,
        'validation_sessions': 10, 'step_sessions': 10, 'folds': 2, 'purge_sessions': 5, 'embargo_sessions': 0}},
    'learner': {'profile': 'byq-lightgbm-cpu-v1', 'parameters': {}},
    'portfolio_policy': {'id': 'top-n-equal-weight-v1', 'parameters': {'top_n': 1, 'rebalance': 'weekly'}},
    'development_window': {'start': '2025-10-01', 'end': '2026-02-28'},
    'prediction_window': {'start': '2026-03-12', 'end': '2026-03-30'}}
ml_version = call('POST', '/api/product/ml/strategies/versions', {'task_id': task, 'strategy': ml}, expected=201)['artifact']
ml_approval = call('POST', '/api/product/ml/strategies/approvals', {'task_id': task,
    'ml_strategy_artifact_id': ml_version['artifact_id'], 'decision': 'approved',
    'rationale': 'Explicit isolated fixture permission for this exact strategy'}, expected=201)['artifact']
fixture('checkpoint', {'task_id': task, 'approval_artifact_id': ml_approval['artifact_id'],
    'baseline_artifact_id': baseline['result_artifact_id']})
permission = call('POST', f'/api/product/research/tasks/{task}/continuation-permission', {
    'idempotency_key': 'f6-explicit-background-permission', 'token_limit': 64000000,
    'confirmed_artifact_ids': [ml_version['artifact_id'], version['artifact']['artifact_id']]}, expected=201,
    headers={'x-byq-continuation-confirmation': 'v1'})
training = call('POST', '/api/product/ml/training-runs', {'task_id': task,
    'ml_strategy_artifact_id': ml_version['artifact_id'], 'stock_pool_snapshot_id': pool['snapshot']['snapshot_id']}, expected=202,
    headers={'x-idempotency-key': 'f6-original-training'})
# Restart only the Gateway consumer: original task/event/receipts survive.
subprocess.run(['docker', 'compose', 'restart', 'gateway'], check=True, capture_output=True, timeout=45)
# Docker may allocate a new host port when restarting an ephemeral-port
# container. The same durable cookie remains valid for the same loopback host.
binding = subprocess.check_output(['docker', 'compose', 'port', 'gateway', '8100'], text=True, timeout=15).strip()
assert re.fullmatch(r'127\.0\.0\.1:[0-9]{1,5}', binding), 'isolated Gateway port required'
origin = 'http://' + binding
deadline = time.monotonic() + 360
last = None
while time.monotonic() < deadline:
    try:
        current = call('GET', '/api/product/research/tasks')
        row = next(r for r in current['tasks'] if r['task_id'] == task)
        view = call('GET', f'/api/product/research/tasks/{task}/continuation-permission')
        state = (row['status'], (row.get('progress') or {}).get('stage'), view.get('blocked_reason'))
        if state != last:
            print(json.dumps({'task_id': task, 'state': state}), flush=True)
            last = state
        if view.get('blocked_reason') == 'continuation_needs_attention':
            raise AssertionError('F6 reported a real blocker; inspect the domain evidence instead of waiting for fabricated completion')
        if row['status'] == 'completed' and view['budget']['unconfirmed_reservations'] == 0:
            assert view['permission']['expires_at'] == permission['permission']['expires_at']
            print(json.dumps(fixture('verify', {'task_id': task})), flush=True)
            break
    except (OSError, StopIteration):
        pass
    time.sleep(2)
else:
    raise AssertionError('F6 chain did not finish; no completion will be fabricated')
