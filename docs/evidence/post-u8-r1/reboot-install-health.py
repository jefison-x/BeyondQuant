"""Apply only validated health checks to three existing-image production services."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/dsh'))
from admission import set_state
from production_backup import write_json

RELEASE = Path('/home/jefison/backups/byq-dsh-u7/release-20260908T152238Z')
MAIN = Path('/home/jefison/projects/BeyondQuant')
CHANGED = ('backend', 'gateway', 'frontend')


def run(args, timeout=30):
    value = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if value.returncode:
        raise RuntimeError('health configuration command failed; admission remains closed')
    return value.stdout


baseline = json.loads((RELEASE / 'preparation.json').read_text())
assert json.loads((RELEASE / 'reboot-health-probe-preflight.json').read_text())['result'] == 'PASS'
overlay_path = RELEASE / 'reboot-recovery.compose.json'
overlay = json.loads(overlay_path.read_text())
assert set(overlay) == {'services'}
assert set(overlay['services']) == set(baseline['services'] + list(baseline['unchanged_services']))
for name, value in overlay['services'].items():
    assert set(value) == ({'restart', 'healthcheck'} if name in CHANGED else {'restart'})
    assert value['restart'] == 'unless-stopped'
compose = ['docker', 'compose', '--project-directory', str(MAIN), '--env-file', str(MAIN / '.env'),
    '-p', 'beyondquant', '-f', str(MAIN / 'compose.yml'), '-f', str(RELEASE / 'target.compose.json'),
    '-f', str(overlay_path)]
config = json.loads(run(compose + ['config', '--format', 'json']))
before = {}
for name in overlay['services']:
    value = json.loads(run(['docker', 'inspect', 'beyondquant-' + name + '-1']))[0]
    assert value['Image'] == (baseline['new_images'].get(name) or baseline['unchanged_services'][name]['image'])
    before[name] = {'id': value['Id'], 'image': value['Image'], 'started_at': value['State']['StartedAt']}
    if name in CHANGED:
        existing = dict(item.split('=', 1) for item in value['Config']['Env'] if '=' in item)
        assert all(existing.get(key) == str(val) for key, val in config['services'][name]['environment'].items()) if 'environment' in config['services'][name] else True
        assert config['services'][name]['image'] == value['Image']
write_json(RELEASE / 'reboot-health-install-started.json', {
    'before': before, 'services_to_recreate': list(CHANGED),
    'overlay_sha256': hashlib.sha256(overlay_path.read_bytes()).hexdigest(),
    'images_changed': False, 'maintainer_authorized': True})
gate = RELEASE / 'gate/admission.state'
set_state(gate, 'closed')
deadline = time.monotonic() + 930
zeros = 0
while time.monotonic() < deadline:
    value = json.loads(run(['docker', 'exec', 'beyondquant-runtime-adapter-1', 'python3', '-c',
        'import json,urllib.request;v=json.load(urllib.request.urlopen("http://127.0.0.1:8400/internal/runtime/operations",timeout=3));print(json.dumps({"active":v["sessions"]["active_prompts"]}))']))
    zeros = zeros + 1 if value['active'] == 0 else 0
    if zeros >= 3:
        break
    time.sleep(2)
else:
    set_state(gate, 'open')  # No service changes have occurred at this point.
    raise RuntimeError('drain timed out; old service configuration left running')
print('DRAINED; applying three health checks with unchanged images', flush=True)
run(['docker', 'stop', '--timeout', '60', *['beyondquant-' + s + '-1' for s in CHANGED]], timeout=200)
run(compose + ['up', '-d', '--no-build', '--no-deps', '--pull', 'never', '--wait',
              '--wait-timeout', '120', *CHANGED], timeout=200)
for name, expected in before.items():
    value = json.loads(run(['docker', 'inspect', 'beyondquant-' + name + '-1']))[0]
    assert value['Image'] == expected['image']
    if name not in CHANGED:
        assert value['Id'] == expected['id'] and value['State']['StartedAt'] == expected['started_at']
write_json(RELEASE / 'reboot-health-install-result.json', {'result': 'PASS', 'images_changed': False,
    'recreated_services': list(CHANGED), 'other_services_not_restarted': True, 'admission': 'closed'})
print('PASS: three health checks installed; admission closed pending final Product verification')
