"""H5 candidate topology only; no launch, credentials, or qualification claims."""
from __future__ import annotations

import json
from pathlib import Path
import re

from tests.dsh_upgrade.live_stack import manifest as base_manifest

ROOT = Path(__file__).resolve().parents[2]
LABEL = 'org.beyondquant.h5-test-scope'


def manifest(scope: str, port: int = 18850) -> dict:
    if not isinstance(scope, str) or not re.fullmatch(r'byq-h5-[a-z0-9][a-z0-9-]{2,44}', scope):
        raise ValueError('dedicated H5 scope required')
    original = 'byq-u5-' + scope.removeprefix('byq-h5-')
    # Reuse only the closed, generated topology; never read deployment .env/Compose.
    value = json.loads(json.dumps(base_manifest(original, 'dsh-0.1.2rc1', port))
                       .replace(original, scope).replace('org.beyondquant.u5-test-scope', LABEL))
    value['x-byq-scenario'] = 'h5-three-backtests.v1'
    value['x-byq-execution-authorized'] = False
    value['networks']['model']['internal'] = True
    runtime = value['services']['runtime-adapter']
    runtime['environment']['DEEPSEEK_API_KEY'] = ''
    value['networks']['signal'] = {'name': scope + '-signal', 'internal': True, 'labels': {LABEL: scope}}
    value['services']['signal-sandbox'] = {
        'image': scope + '-signal-sandbox:qualification',
        'build': {'context': str(ROOT), 'dockerfile': 'services/signal-sandbox/Dockerfile'},
        'labels': {LABEL: scope}, 'networks': ['signal'], 'restart': 'no',
        'read_only': True, 'tmpfs': ['/tmp:rw,noexec,nosuid,nodev,size=32m'],
        'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
        'pids_limit': 32, 'mem_limit': '896m', 'cpus': 1.0,
        'healthcheck': {'test': ['CMD', 'python3', '-c',
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8500/healthz', timeout=3)"],
            'interval': '3s', 'timeout': '5s', 'retries': 60},
    }
    value['services']['signal-worker'] = {
        'image': scope + '-signal-worker:qualification',
        'build': {'context': str(ROOT), 'dockerfile': 'workers/signal/Dockerfile'},
        'labels': {LABEL: scope}, 'networks': ['product', 'signal'], 'restart': 'no',
        'environment': {
            'BYQ_DATABASE_URL': value['services']['backend']['environment']['BYQ_DATABASE_URL'],
            'BYQ_SIGNAL_SANDBOX_URL': 'http://signal-sandbox:8500', 'BYQ_SIGNAL_POLL_SECONDS': '1',
        },
        'depends_on': {name: {'condition': 'service_healthy'} for name in ('backend', 'signal-sandbox')},
        'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'], 'pids_limit': 256,
    }
    return value


def validate_candidate(value: object) -> dict:
    """Validate raw generated input before any future Compose command.

    Runtime inspection remains a separate gate; equality here cannot prove that
    running containers match this candidate or that model execution is allowed.
    """
    if not isinstance(value, dict):
        raise ValueError('generated H5 candidate required')
    expected = manifest(value.get('name'), value.get('x-byq-port'))
    if value != expected:
        raise ValueError('H5 candidate was altered or uses a different build')
    return value
