"""Keyless qualification of the candidate guard on the exact bundled runtime.

These probes do not qualify the full Product composition or financial limits.
"""
import json
import os
import threading
import time
import hashlib
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get('BYQ_BUDGET_SEMANTICS_TEST') != '1',
    reason='explicit isolated budget qualification')


@pytest.mark.parametrize('behavior,allowance,expected', [
    ('steps', 1048583, 0), ('steps', 1048584, 1),
    ('retry', 1048583, 0), ('retry', 1048584, 1), ('compaction', 1048584, 1)])
def test_guard_refuses_before_next_http_and_retains_durable_ceiling(tmp_path, allowance, expected, behavior):
    from importlib.metadata import version
    from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig
    from deepseek_harness_runtime import bundled_runtime_path

    assert version('deepseek-harness-runtime-bin') == '0.1.2rc1'
    requests = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers['content-length']))
            requests.append(1)
            if behavior == 'retry':
                self.send_error(503, 'synthetic retryable provider failure')
                return
            if len(requests) > 1:
                self.send_error(400, 'synthetic request ceiling exceeded')
                return
            chunks = [{'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': 0,
                'id': 'synthetic', 'type': 'function', 'function': {
                    'name': 'synthetic_nonexistent_tool', 'arguments': '{}'}}]}, 'finish_reason': None}]},
                {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}],
                 'usage': {'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20}}]
            data = (''.join(f'data: {json.dumps(c)}\n\n' for c in chunks) + 'data: [DONE]\n\n').encode()
            self.send_response(200)
            self.send_header('content-type', 'text/event-stream')
            self.send_header('content-length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    journal = tmp_path / 'budget.jsonl'
    patch = tmp_path / 'budget.yml'
    patch.write_text('- insert:\n    - id: byq-budget-probe\n'
        "      name: 'file:///opt/byq/runtime/byq-continuation-budget.js'\n"
        '      config:\n' + ''.join(f'        {key}: {json.dumps(value)}\n' for key, value in {
            'journalPath': str(journal), 'reservationId': 'reservation-synthetic',
            'tokenLimit': allowance, 'expiresAt': int(time.time() * 1000) + 60000}.items()))
    with patch.open('a') as stream:
        stream.write('\n- id: llm-deepseek\n  config:\n    maxTokens: 8\n    retryPolicy:\n      mode: always\n      backoff:\n        initialDelayMs: 1\n        maxDelayMs: 1\n        jitterRatio: 0\n')
    if behavior == 'compaction':
        with patch.open('a') as stream:
            stream.write('\n- id: compaction-basic\n  config:\n    thresholdRatio: 0.00001\n    retainTokens: 0\n    maxTokens: 8192\n    compactionRetries: 1\n')
    config = DeepSeekHarnessConfig(max_tokens=8, dsh_bin=str(bundled_runtime_path()),
        patches=(str(patch),), cwd=str(tmp_path), runtime_cwd=str(tmp_path), dsh_home=str(tmp_path),
        request_timeout_seconds=20, initialize_timeout_seconds=20,
        env={'DEEPSEEK_API_KEY': 'synthetic-only',
             'DEEPSEEK_BASE_URL': f'http://127.0.0.1:{server.server_port}', 'DSH_TELEMETRY_DISABLED': '1'})
    try:
        with DeepSeekHarness(config=config) as harness:
            result = harness.run('Synthetic budget qualification only.' + (' history' * 2000 if behavior == 'compaction' else ''))
        assert result.finish_reason in {'error', 'cancelled', 'aborted'}
        assert len(requests) == expected
        all_rows = [json.loads(line) for line in journal.read_text().splitlines()]
        assert all_rows[0] == {'schema_version': 'continuation-budget-guard.v1',
            'reservation_id': 'reservation-synthetic', 'token_limit': allowance, 'ready': True}
        assert all_rows[-1] == {'blocked_reason': 'BYQ_CONTINUATION_BUDGET_EXHAUSTED', 'blocked_purpose': 'compaction' if behavior == 'compaction' else 'model'}
        rows = all_rows[1:-1]
        assert len(rows) == expected
        if rows:
            assert rows == [{'reservation_id': 'reservation-synthetic', 'call': 1,
                'reserved_tokens': 1048584, 'charged_ceiling': 1048584}]
        # A fresh real process cannot reopen the same reservation and spend it
        # a second time. Zero additional requests is required even if startup
        # reports the failed plugin as a dependency instead of throwing.
        try:
            with DeepSeekHarness(config=config) as reopened:
                replay = reopened.run('Synthetic budget qualification only.')
                assert replay.finish_reason == 'error'
        except Exception as exc:
            assert 'EEXIST' in str(exc) or 'byq-budget-probe' in str(exc)
        assert len(requests) == expected
        assert journal.read_text().splitlines() == [json.dumps(r, separators=(',', ':')) for r in all_rows]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize('delegates', [0, 1, 2])
def test_adapter_requires_guard_startup_and_projects_closed_process_receipt(tmp_path, monkeypatch, delegates):
    from app.runtime import RuntimeAdapter, SessionConflict

    source = Path(os.environ['BYQ_DSH_COMPOSITION']).read_text() + '\n- id: mcp-byq\n  disabled: true\n'
    source += '\n- id: delegate-factor-research\n  config:\n    provider: spawn\n    toolName: byq_delegate_factor_research\n    enableRunInBackground: false\n    maxDepth: 1\n    toolFilter:\n      allow: []\n'
    profile = tmp_path / 'product.yml'
    profile.write_text(source)
    identity = tmp_path / 'identity.json'
    identity.write_text(json.dumps({'root_identity_contract': 'byq-root-process.v1',
        'composition_hash': 'sha256:' + hashlib.sha256(source.encode()).hexdigest()}))
    monkeypatch.setenv('BYQ_DSH_PROCESS_OWNERSHIP', 'root-turn')
    monkeypatch.setenv('BYQ_DSH_COMPOSITION', str(profile))
    monkeypatch.setenv('BYQ_DSH_COMPOSITION_IDENTITY', str(identity))
    monkeypatch.setenv('DSH_SESSION_ROOT', str(tmp_path / 'sessions'))
    monkeypatch.setenv('BYQ_F6_EXECUTOR_ENABLED', '1')
    requests = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['content-length'])))
            requests.append(body['max_tokens'])
            delta = {'content': 'Synthetic completion'}
            reason = 'stop'
            if delegates and len(requests) == 1:
                delta = {'tool_calls': [{'index': 0, 'id': 'budget-delegate', 'type': 'function',
                    'function': {'name': 'byq_delegate_factor_research', 'arguments': json.dumps({
                        'description': 'Synthetic budget child', 'prompt': 'Return synthetic completion only.'})}}]}
                if delegates == 2:
                    delta['tool_calls'].append({**delta['tool_calls'][0], 'index': 1, 'id': 'budget-delegate-two'})
                reason = 'tool_calls'
            data = ('data: ' + json.dumps({'choices': [{'index': 0,
                'delta': delta, 'finish_reason': None}]}) + '\n\n'
                + 'data: ' + json.dumps({'choices': [{'index': 0, 'delta': {}, 'finish_reason': reason}],
                'usage': {'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20}})
                + '\n\ndata: [DONE]\n\n').encode()
            self.send_response(200)
            self.send_header('content-type', 'text/event-stream')
            self.send_header('content-length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    runtime = RuntimeAdapter()
    build = runtime._compatibility.build_harness
    def loopback_build(**kwargs):
        # Only the probe reroutes the immutable official-provider adapter to
        # a synthetic server; production fixes its endpoint to the official origin.
        kwargs['environment']['DEEPSEEK_BASE_URL'] = f'http://127.0.0.1:{server.server_port}'
        return build(**kwargs)
    monkeypatch.setattr(runtime._compatibility, 'build_harness', loopback_build)
    observed = []
    run_prepared = runtime._compatibility.run_prepared_prompt
    def observe(prepared, content, callback):
        def forward(notification):
            observed.append({"method": notification.method, "payload": notification.payload})
            callback(notification)
        return run_prepared(prepared, content, forward)
    monkeypatch.setattr(runtime._compatibility, 'run_prepared_prompt', observe)
    monkeypatch.setattr(runtime, '_resolve_model', lambda **kwargs: {
        'provider': 'deepseek-official', 'model': 'deepseek-v4-flash', 'api_key': 'synthetic-only'})
    reservation = {'schema_version': 'task-continuation-reservation.v1',
        'reservation_id': 'continuation_' + 'a' * 32, 'task_id': 'task_' + 'b' * 32,
        'owner': 'synthetic-owner', 'workspace_id': 'synthetic-workspace', 'token_limit': (1048576 + 8192) * (2 if delegates == 2 else 1),
        'expires_at': (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()}
    try:
        runtime.create_session('budget-adapter', 'budget-trace', 'synthetic-owner', 'synthetic-workspace')
        root = runtime.submit_prompt('budget-adapter', 'Synthetic only.', idempotency_key=reservation['reservation_id'],
            conversation_context=[], continuation_budget=reservation)
        record = runtime._get('budget-adapter')
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with record.lock:
                if record.active_run is None:
                    break
            time.sleep(.02)
        settled = runtime.continuation_receipt('budget-adapter', reservation['reservation_id'])
        assert settled['status'] == 'settled'
        assert settled['run_id'] == root
        assert settled['charged_tokens'] == reservation['token_limit']
        assert requests == [8192] * (2 if delegates == 2 else 1)
        if delegates:
            assert sum(n['method'] == 'subagent.started' for n in observed) >= delegates, json.dumps(observed)
        assert runtime.submit_prompt('budget-adapter', 'Synthetic only.', idempotency_key=reservation['reservation_id'],
            conversation_context=[], continuation_budget=reservation) == root
        with pytest.raises(SessionConflict):
            runtime.submit_prompt('budget-adapter', 'Synthetic only.', idempotency_key=reservation['reservation_id'],
                continuation_budget={**reservation, 'token_limit': reservation['token_limit'] + 1})
        assert requests == [8192] * (2 if delegates == 2 else 1)
        runtime.release_session('budget-adapter')
        assert runtime.continuation_receipt('budget-adapter', reservation['reservation_id']) == settled
        restarted = RuntimeAdapter()
        try:
            assert restarted.continuation_receipt('budget-adapter', reservation['reservation_id']) == settled
            assert requests == [8192] * (2 if delegates == 2 else 1)
        finally:
            restarted.close()
    finally:
        runtime.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize('disable_search,expected', [(False, 1), (True, 0)])
def test_direct_search_bypasses_llm_guard_unless_provider_is_disabled(tmp_path, disable_search, expected):
    from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig
    from deepseek_harness_runtime import bundled_runtime_path

    requests = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['content-length'])))
            requests.append((self.path, body.get('tools', [{}])[0].get('name')))
            self.send_error(400, 'synthetic search refusal')

    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    plugin = tmp_path / 'search-probe.mjs'
    plugin.write_text("""
export const name = 'byq-search-budget-probe';
export const inject = ['llm', 'web'];
export function apply(ctx) {
  ctx.on('llm/stream', async function* () {
    try { await ctx.web.search({query: 'synthetic budget qualification', maxResults: 1}); }
    catch { /* the local provider or missing provider is expected to refuse */ }
    throw new Error('BYQ_SEARCH_PROBE_ROOT_DENIED');
  });
}
""")
    patch = tmp_path / 'search.yml'
    patch.write_text(('- id: web-search-deepseek\n  disabled: true\n' if disable_search else '')
        + '- insert:\n    - id: search-probe\n      name: ' + json.dumps(plugin.as_uri()) + '\n')
    config = DeepSeekHarnessConfig(dsh_bin=str(bundled_runtime_path()), patches=(str(patch),),
        cwd=str(tmp_path), runtime_cwd=str(tmp_path), dsh_home=str(tmp_path),
        request_timeout_seconds=20, initialize_timeout_seconds=20,
        env={'DEEPSEEK_API_KEY': 'synthetic-only',
             'DEEPSEEK_BASE_URL': f'http://127.0.0.1:{server.server_port}',
             'DEEPSEEK_SEARCH_BASE_URL': f'http://127.0.0.1:{server.server_port}',
             'DSH_TELEMETRY_DISABLED': '1'})
    try:
        with DeepSeekHarness(config=config) as harness:
            result = harness.run('Synthetic guard bypass qualification only.')
        assert result.finish_reason == 'error'
        assert 'BYQ_SEARCH_PROBE_ROOT_DENIED' in str(result.events)
        assert requests == [('/messages', 'web_search')] * expected
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
