"""Bounded operator verification: exact images, health, synthetic persistence."""
import argparse
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/dsh'))
sys.path.insert(0, str(ROOT / 'tests/dsh_upgrade'))
from admission import set_state
from production_backup import write_json
from live_model_probe import Client, counts

RELEASE = Path('/home/jefison/backups/byq-dsh-u7/release-20260908T152238Z')


def inspect(service):
    return json.loads(subprocess.check_output(
        ['docker', 'inspect', 'beyondquant-' + service + '-1'], timeout=10))[0]


def verify(open_admission=False):
    baseline = json.loads((RELEASE / 'preparation.json').read_text())
    overlay = json.loads((RELEASE / 'reboot-recovery.compose.json').read_text())
    observed = {}
    for service in baseline['services'] + list(baseline['unchanged_services']):
        value = inspect(service)
        expected = baseline['new_images'].get(service) or baseline['unchanged_services'][service]['image']
        assert value['Image'] == expected
        assert value['State']['Running'] and not value['State']['Restarting']
        assert value['State'].get('Health', {}).get('Status', 'healthy') == 'healthy'
        assert value['HostConfig']['RestartPolicy']['Name'] == 'unless-stopped'
        if service in ('backend', 'gateway', 'frontend'):
            check = overlay['services'][service]['healthcheck']['test']
            assert value['Config']['Healthcheck']['Test'] == check
            args = check[1:] if check[0] == 'CMD' else ['/bin/sh', '-c', check[1]]
            result = subprocess.run(['docker', 'exec', 'beyondquant-' + service + '-1', *args],
                capture_output=True, timeout=15)
            assert result.returncode == 0, 'installed dependency probe failed'
        observed[service] = {'id': value['Id'], 'image': value['Image'],
            'restart_count': value['RestartCount'], 'started_at': value['State']['StartedAt']}
    credentials = json.loads(Path('/home/jefison/backups/byq-dsh-u7/release-20260906T220612Z/synthetic-smoke.private.json').read_text())
    assert credentials['role'] == 'user'
    client = Client('http://127.0.0.1:8100', credentials['username'], credentials['password'])
    session = json.loads((RELEASE / 'smoke.json').read_text())['session_id']
    replay = client.call('GET', '/v1/agent/sessions/' + session)
    historical = json.loads((RELEASE / 'smoke-G5.private.json').read_text())
    answers = lambda value: [(m['message_id'], m['content']) for m in value['messages'] if m['role'] == 'assistant']
    assert len(answers(replay)) == 2 and answers(replay) == answers(historical)
    counts(client)
    with urllib.request.urlopen('http://127.0.0.1/', timeout=5) as response:
        assert response.status == 200
    if open_admission:
        set_state(RELEASE / 'gate/admission.state', 'open')
    result = {'result': 'PASS', 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'services': observed, 'synthetic_login_and_persistence': True,
        'dependency_probes': 'PASS', 'model_calls': 0,
        'admission': (RELEASE / 'gate/admission.state').read_text().strip()}
    name = dt.datetime.now(dt.timezone.utc).strftime('reboot-verification-%Y%m%dT%H%M%SZ.json')
    write_json(RELEASE / name, result)
    print(json.dumps({k: v for k, v in result.items() if k != 'services'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--open-admission', action='store_true')
    verify(parser.parse_args().open_admission)
