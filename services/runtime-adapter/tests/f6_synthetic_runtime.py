"""Explicit isolated F6 integration fixture; never a production runtime mode.

The scripted Provider chooses tool calls; actual DSH, MCP, Domain, PostgreSQL,
ML Worker and native backtest execution remain unchanged. This proves wiring,
not real-model research quality.
"""
import hashlib
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def decode_result(value):
    if isinstance(value, str):
        try:
            return decode_result(json.loads(value))
        except (ValueError, TypeError):
            return None
    if isinstance(value, list):
        for item in value:
            result = decode_result(item)
            if result:
                return result
    if isinstance(value, dict):
        if value.get('service') == 'beyondquant-mcp' or value.get('reason') == 'continuation_action_not_admitted':
            return value
        for key in ('content', 'text'):
            if key in value:
                result = decode_result(value[key])
                if result:
                    return result
    return None


def next_action(body):
    messages = body['messages']
    text = '\n'.join(str(m.get('content', '')) for m in messages if m['role'] == 'user')
    matches = re.findall(r'BYQ trusted task continuation.*?task (task_[0-9a-f]{32}).*?A durable domain event is (\{[^\n]+?\})\.', text, re.DOTALL)
    if not matches:
        raise ValueError('the isolated fixture accepts only trusted continuation prompts')
    task_id, event_text = matches[-1]
    event = json.loads(event_text)
    if event['status'] != 'completed':
        print(json.dumps({'f6_fixture_error': 'domain_event_not_completed', 'kind': event['kind']}), flush=True)
        raise ValueError('fixture requires an actually completed domain event')
    calls = {}
    records = []
    for message in messages:
        for call in message.get('tool_calls', []):
            calls[call['id']] = call['function']['name'].removeprefix('mcp__byq__')
        if message['role'] == 'tool' and message.get('tool_call_id') in calls:
            result = decode_result(message.get('content'))
            if result is None:
                print(json.dumps({'f6_fixture_error': 'unrecognized_mcp_result',
                    'tool': calls[message['tool_call_id']]}), flush=True)
                raise ValueError('unrecognized real MCP response')
            records.append((calls[message['tool_call_id']], result))
    def tool(name, args):
        return ('mcp__byq__' + name, args)
    def latest(name):
        return next((result for called, result in reversed(records) if called == name), None)
    print(json.dumps({'f6_fixture_event': event['kind'], 'completed_tools': len(records),
        'last_tool': records[-1][0] if records else None}), flush=True)
    if not records:
        return tool('byq_research_get', {'entity_type': 'research_task', 'entity_id': task_id})
    # First MCP response is the authoritative task. All other identities are
    # obtained from that task checkpoint or exact event-object reads.
    task = records[0][1]
    linked = task['progress']['linked_objects'][:2]
    approval, baseline = (item['id'] for item in linked)
    def transition(stage, *, evidence=None):
        return tool('byq_research_transition', {'entity_type': 'research_task', 'entity_id': task_id,
            'target_status': 'completed' if evidence else 'running',
            'idempotency_key': 'f6-progress-' + event['identity'], 'progress': {
                'schema_version': 'research-progress.v1', 'stage': stage,
                'next_action': None if evidence else 'Wait for the exact next domain result',
                'blocked_reason': None, 'linked_objects': linked,
                'completion_evidence': evidence or []}})
    if any(result.get('status') in {'error', 'blocked', 'outcome_unknown'} for _, result in records):
        raise ValueError('real domain action did not succeed; fixture will not fake completion')
    if event['kind'] == 'ml_training_runs':
        training = latest('byq_ml_training_get')
        if training is None:
            return tool('byq_ml_training_get', {'training_run_id': event['identity']})
        prediction = latest('byq_ml_prediction_create')
        if prediction is None:
            return tool('byq_ml_prediction_create', {'task_id': task_id,
                'model_artifact_id': training['training_run']['model_artifact_id'],
                'approval_artifact_id': approval, 'idempotency_key': 'f6-prediction-' + event['identity'],
                'execution': {'initial_capital': 1000000, 'lot_size': 100}})
        if latest('byq_research_transition') is None:
            return transition('prediction')
    elif event['kind'] == 'ml_prediction_runs':
        prediction = latest('byq_ml_prediction_get')
        if prediction is None:
            return tool('byq_ml_prediction_get', {'prediction_run_id': event['identity']})
        if latest('byq_signal_snapshot_get') is None:
            return tool('byq_signal_snapshot_get', {'artifact_id': prediction['prediction_run']['signal_artifact_id']})
        if latest('byq_backtest_task_execute') is None:
            return tool('byq_backtest_task_execute', {'backtest_task_id': event['identity'].replace('mlpred_', 'backtesttask_ml_', 1)})
        if latest('byq_research_transition') is None:
            return transition('comparison')
    elif event['kind'] == 'backtest_jobs':
        candidate = latest('byq_backtest_get')
        if candidate is None:
            return tool('byq_backtest_get', {'job_id': event['identity']})
        baseline_result = next((r for name, r in records if name == 'byq_research_get' and 'artifact_id' in r), None)
        if baseline_result is None:
            return tool('byq_research_get', {'entity_type': 'artifact', 'entity_id': baseline})
        report = latest('byq_artifact_create')
        if report is None:
            original, current = baseline_result['content']['summary'], candidate['job']['summary']
            return tool('byq_artifact_create', {'task_id': task_id, 'kind': 'research_report',
                'content': {'report_type': 'strategy_comparison', 'synthetic_input_fixture': True, 'baseline': original, 'candidate': current,
                    'delta_total_return': current['total_return'] - original['total_return']},
                'lineage': [{'kind': 'artifact', 'id': baseline},
                    {'kind': 'artifact', 'id': candidate['job']['result_artifact_id']}],
                'trace_id': task['trace_id'], 'idempotency_key': 'f6-comparison-' + event['identity']})
        transitions = [r for name, r in records if name == 'byq_research_transition']
        if not transitions:
            return tool('byq_research_transition', {'entity_type': 'artifact', 'entity_id': report['artifact_id'],
                'target_status': 'validated', 'idempotency_key': 'f6-validate-' + event['identity']})
        if len(transitions) == 1:
            return transition('completed', evidence=[report['artifact_id']])
    else:
        raise ValueError('unsupported fixture domain event')
    return None


def main():
    if os.environ.get('BYQ_F6_SYNTHETIC_RUNTIME') != '1' or os.environ.get('DEEPSEEK_API_KEY') != 'f6-synthetic-only':
        raise SystemExit('isolated synthetic F6 runtime invocation required')
    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers['content-length'])))
                action = next_action(body)
                if action:
                    name, args = action
                    delta = {'tool_calls': [{'index': 0, 'id': hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:24],
                        'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}
                    reason = 'tool_calls'
                else:
                    delta, reason = {'content': '已核对本任务的真实领域结果并保存进度。'}, 'stop'
                data = ('data: ' + json.dumps({'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]})
                    + '\n\ndata: ' + json.dumps({'choices': [{'index': 0, 'delta': {}, 'finish_reason': reason}],
                        'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}})
                    + '\n\ndata: [DONE]\n\n').encode()
                self.send_response(200)
                self.send_header('content-type', 'text/event-stream')
                self.send_header('content-length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as exc:
                # Only exception class; never log model request, key or domain data.
                print('f6 synthetic provider failed: ' + type(exc).__name__, flush=True)
                self.send_error(400, 'synthetic fixture rejected the real domain response')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    from app import main as runtime_main
    import uvicorn
    original = runtime_main.adapter._compatibility.build_harness
    def loopback_build(**kwargs):
        kwargs['environment']['DEEPSEEK_BASE_URL'] = f'http://127.0.0.1:{server.server_port}'
        return original(**kwargs)
    runtime_main.adapter._compatibility.build_harness = loopback_build
    try:
        uvicorn.run(runtime_main.app, host='0.0.0.0', port=8400)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
