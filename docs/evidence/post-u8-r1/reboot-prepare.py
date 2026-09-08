"""Prepare a configuration-only overlay; never change application images here."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/dsh'))
from production_backup import write_json

RELEASE = Path('/home/jefison/backups/byq-dsh-u7/release-20260908T152238Z')
MAIN = Path('/home/jefison/projects/BeyondQuant')


def run(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError('configuration/probe failed; private output withheld')
    return result.stdout


baseline = json.loads((RELEASE / 'preparation.json').read_text())
config = json.loads(run(['docker', 'compose', '--project-directory', str(MAIN),
    '--env-file', str(MAIN / '.env'), '-p', 'beyondquant', '-f', str(ROOT / 'compose.yml'),
    '-f', str(RELEASE / 'target.compose.json'), 'config', '--format', 'json']))
services = baseline['services'] + list(baseline['unchanged_services'])
overlay = {'services': {name: {'restart': 'unless-stopped'} for name in services}}
for name in ('backend', 'gateway', 'frontend'):
    value = json.loads(run(['docker', 'inspect', 'beyondquant-' + name + '-1']))[0]
    assert value['Image'] == baseline['new_images'][name]
    check = config['services'][name]['healthcheck']
    test = check['test']
    args = test[1:] if test[0] == 'CMD' else ['/bin/sh', '-c', test[1]]
    run(['docker', 'exec', 'beyondquant-' + name + '-1', *args])
    overlay['services'][name]['healthcheck'] = check
write_json(RELEASE / 'reboot-recovery.compose.json', overlay)
write_json(RELEASE / 'reboot-health-probe-preflight.json', {
    'result': 'PASS', 'tested_current_images': {s: baseline['new_images'][s]
        for s in ('backend', 'gateway', 'frontend')},
    'application_images_changed': False, 'production_containers_recreated': False,
    'paid_model_calls': 0})
print('PASS: exact current-image health probes; configuration-only overlay prepared')
