#!/usr/bin/env python3
"""Bounded, operator-only U8 sampler. No model calls or production mutations.

Writes private aggregate evidence only. An elapsed window is NOT acceptance.
No restart/resume stitching: every invocation creates a new observation window.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path('/home/jefison/backups/byq-dsh-u7')
SERVICES = ('backend', 'mcp', 'gateway', 'runtime-adapter', 'frontend',
            'postgres', 'data-worker', 'ml-worker', 'signal-worker',
            'signal-sandbox', 'feedback-hub-relay')
# Exact qualified identity, not a mutable profile selector.
COMPOSITION = 'sha256:e584cee23c7e39ffaaf7d4c583d4762556032b4d4d173285c14c038d98ec6f98'
WINDOW = 86400


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=45)
    if result.returncode:
        # stderr may contain operational detail; never persist or print it.
        raise RuntimeError('read-only probe failed: ' + args[0])
    return result.stdout


def validate_release(path):
    if path.is_symlink() or path.resolve().parent != ROOT.resolve() or not re.fullmatch(
            r'release-\d{8}T\d{6}Z', path.name):
        raise ValueError('dedicated approved release directory required')
    baseline = json.loads((path / 'deployment.json').read_text())
    if baseline.get('result') != 'DEPLOYED' or baseline.get('release') != 'dsh-0.1.2rc1':
        raise ValueError('completed exact target deployment required')
    if set(baseline['services']) != set(SERVICES):
        raise ValueError('exact production service baseline required')
    return baseline


def runtime_projection(value):
    runtime = value['runtime']
    return {
        'runtime': {key: runtime[key] for key in (
            'status', 'sdk', 'runtime_bin', 'release_id', 'release_identity',
            'plugin_profile', 'composition_hash', 'enabled_plugin_ids')},
        'sessions': {key: value['sessions'][key] for key in (
            'active', 'active_prompts', 'status_counts')},
        'usage': {key: val for key, val in value['usage'].items()
                  if key in ('input_tokens', 'output_tokens', 'cache_read_tokens',
                             'cache_write_tokens', 'total_tokens') and isinstance(val, int)},
    }


def identity_matches(value):
    return (value['status'] == 'ready' and value['release_identity'] == 'matched'
            and value['release_id'] == 'dsh-0.1.2rc1'
            and value['sdk'] == 'deepseek-harness-sdk==0.1.2rc1'
            and value['runtime_bin'] == 'deepseek-harness-runtime-bin==0.1.2rc1'
            and value['plugin_profile'] == 'byq-product-candidate'
            and value['composition_hash'] == COMPOSITION
            and sorted(value['enabled_plugin_ids']) == ['compaction', 'guard', 'web-search'])


def sample(baseline, release):
    names = ['beyondquant-' + name + '-1' for name in SERVICES]
    containers = json.loads(command(['docker', 'inspect', *names]))
    result = {'at': now(), 'services': {}, 'alerts': []}
    for name, item in zip(SERVICES, containers, strict=True):
        state = item['State']
        current = {'id': item['Id'], 'image': item['Image'],
                   'started_at': state['StartedAt'], 'restart_count': item['RestartCount']}
        if current != baseline['services'][name]:
            result['alerts'].append(name + ':deployment_baseline_changed')
        current.update(running=state['Running'],
                       health=state.get('Health', {}).get('Status', 'not-configured'))
        if not current['running'] or current['health'] not in ('healthy', 'not-configured'):
            result['alerts'].append(name + ':not_healthy')
        result['services'][name] = current
    result['resources'] = [
        {key: value[key] for key in ('Name', 'CPUPerc', 'MemUsage', 'MemPerc', 'PIDs')}
        for value in (json.loads(line) for line in command([
            'docker', 'stats', '--no-stream', '--format', '{{json .}}', *names]).splitlines())]
    raw = command(['docker', 'exec', 'beyondquant-runtime-adapter-1', 'python3', '-c',
                   "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8400/internal/runtime/operations',timeout=5).read().decode())"])
    result.update(runtime_projection(json.loads(raw)))
    if not identity_matches(result['runtime']):
        result['alerts'].append('runtime:identity_mismatch')
    result['runtime_process_count'] = max(0, len(command([
        'docker', 'top', 'beyondquant-runtime-adapter-1', '-eo', 'pid,ppid,comm']).splitlines()) - 1)
    result['session_disk_kib'] = int(command([
        'docker', 'exec', 'beyondquant-runtime-adapter-1', 'du', '-sk',
        '/var/lib/byq/dsh-sessions']).split()[0])
    fs = os.statvfs(release)
    result['host_disk_available_bytes'] = fs.f_bavail * fs.f_frsize
    memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    result['host_memory_available_kib'] = int(memory['MemAvailable'].split()[0])
    if result['host_disk_available_bytes'] < 10 * 1024**3:
        result['alerts'].append('host:disk_below_10GiB_capacity_guardrail')
    if result['host_memory_available_kib'] < 1024**2:
        result['alerts'].append('host:memory_below_1GiB_capacity_guardrail')
    result['admission_gate'] = (release / 'gate/admission.state').read_text().strip()
    if result['admission_gate'] != 'open':
        result['alerts'].append('admission:not_open')
    return result


def interval(elapsed):
    return 60 if elapsed < 1800 else 300


def result_state(elapsed, once=False):
    if once:
        return 'SAMPLE_ONLY'
    return 'WINDOW_ELAPSED_ACCEPTANCE_PENDING_REVIEW' if elapsed >= WINDOW else 'OBSERVING'


def write_new(path, data):
    with path.open('x') as stream:
        json.dump(data, stream, sort_keys=True)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-directory', type=Path, required=True)
    parser.add_argument('--once', action='store_true', help='diagnostic only; never completes U8')
    args = parser.parse_args()
    baseline = validate_release(args.release_directory)
    os.umask(0o077)
    directory = args.release_directory / dt.datetime.now(dt.timezone.utc).strftime('u8-observation-%Y%m%dT%H%M%SZ')
    directory.mkdir(mode=0o700)
    started = time.monotonic()
    write_new(directory / 'manifest.json', {
        'started_at': now(), 'target_seconds': WINDOW, 'once': args.once,
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'baseline_sha256': hashlib.sha256((args.release_directory / 'deployment.json').read_bytes()).hexdigest(),
        'limitations': ['No raw logs or conversations; no model traffic generated.',
                         'Process count is not SDK child state; session metadata is not an active process.',
                         'Approval backlog, duplicate intents and failure causes require separate bounded review.',
                         'No automatic acceptance, rollback, cleanup or production writes.'],
        'retention': 'at least 7 days AND maintainer stable confirmation; no automatic deletion'})
    print(json.dumps({'directory': str(directory), 'state': 'STARTED'}), flush=True)
    samples = alerts = failures = 0
    previous = 0.0
    max_gap = 0.0
    with (directory / 'samples.jsonl').open('x') as stream:
        while True:
            elapsed = time.monotonic() - started
            max_gap = max(max_gap, elapsed - previous)
            previous = elapsed
            try:
                value = sample(baseline, args.release_directory)
            except Exception as error:
                failures += 1
                value = {'at': now(), 'probe_error_class': type(error).__name__,
                         'alerts': ['incomplete_sample']}
            value['elapsed_seconds'] = elapsed
            samples += 1
            alerts += len(value['alerts'])
            stream.write(json.dumps(value, sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
            status = {'at': now(), 'elapsed_seconds': elapsed, 'samples': samples,
                      'alerts': alerts, 'failed_samples': failures,
                      'max_sample_gap_seconds': max_gap,
                      'state': result_state(elapsed, args.once)}
            # Private checkpoint only, never an application or deployment file.
            temp = directory / 'checkpoint.next'
            write_new(temp, status)
            temp.replace(directory / 'checkpoint.json')
            if value['alerts']:
                print(json.dumps(status), flush=True)
            if args.once or elapsed >= WINDOW:
                write_new(directory / 'window-result.json', status)
                break
            target = min(started + WINDOW, started + elapsed + interval(elapsed))
            while time.monotonic() < target:
                time.sleep(min(60, max(0, target - time.monotonic())))


if __name__ == '__main__':
    main()
