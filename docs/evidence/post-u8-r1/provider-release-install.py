"""Exact-artifact forward-only operator steps for the authorized F7 repair."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/dsh'))
from production_backup import DESTINATION, write_json, sha256
from production_session_backup import backup
from admission import set_state


def command(args, timeout=60):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('operator command failed; private output withheld; admission remains closed')
    return result.stdout


def validate(directory):
    assert directory.parent == DESTINATION and directory.resolve() == directory
    assert directory.is_dir() and not directory.stat().st_mode & 0o077
    receipt = json.loads((directory / 'preparation.json').read_text())
    assert receipt['schema_version'] == 'byq-provider-repair-release.v1'
    assert receipt['ci_scope'] == 'local-u7-f7-provider-repair-20260909'
    assert receipt['mode'] == 'forward-only' and not receipt['historical_replay']
    assert sha256(directory / 'target.compose.json') == receipt['overlay_sha256']
    assert command(['git', '-C', '/home/jefison/projects/BeyondQuant', 'rev-parse', 'HEAD']).strip() == receipt['git_commit']
    return receipt


def drain(directory, receipt):
    old = Path(receipt['old_admission_file'])
    assert old.read_text() == 'open\n'
    assert Path(receipt['admission_file']).read_text() == 'closed\n'
    for service, image in receipt['old_images'].items():
        assert command(['docker', 'inspect', 'beyondquant-' + service + '-1', '--format', '{{.Image}}']).strip() == image
    set_state(old, 'closed')
    try:
        zeros = 0
        deadline = time.monotonic() + 930
        while time.monotonic() < deadline:
            active = int(command(['docker', 'exec', 'beyondquant-runtime-adapter-1', 'python', '-c',
                'import json,urllib.request; print(json.load(urllib.request.urlopen("http://127.0.0.1:8400/internal/runtime/operations",timeout=5))["sessions"]["active_prompts"])']))
            zeros = zeros + 1 if active == 0 else 0
            if zeros == 3:
                write_json(directory / 'drain.json', {'result': 'PASS', 'active_prompts': 0, 'forced_cancel': False})
                print('DRAINED', flush=True)
                return
            time.sleep(2)
        raise RuntimeError('active user work did not drain')
    except BaseException:
        set_state(old, 'open')
        raise


def install(directory, receipt):
    assert json.loads((directory / 'drain.json').read_text())['result'] == 'PASS'
    assert Path(receipt['old_admission_file']).read_text() == 'closed\n'
    assert Path(receipt['admission_file']).read_text() == 'closed\n'
    target = json.loads((directory / 'target.compose.json').read_text())
    for service, expected in receipt['new_images'].items():
        assert command(['docker', 'image', 'inspect', target['services'][service]['image'], '--format', '{{.Id}}']).strip() == expected
    command(['docker', 'stop', '--time', '30', 'beyondquant-gateway-1', 'beyondquant-runtime-adapter-1'], timeout=90)
    backup(directory)
    command(['docker', 'compose', '--project-directory', '/home/jefison/projects/BeyondQuant',
        '--env-file', '/home/jefison/projects/BeyondQuant/.env', '-p', 'beyondquant',
        '-f', '/home/jefison/projects/BeyondQuant/compose.yml', '-f', str(directory / 'target.compose.json'),
        'up', '-d', '--no-build', '--no-deps', '--pull', 'never', '--wait', '--wait-timeout', '240',
        *receipt['services']], timeout=300)
    write_json(directory / 'installed.json', {'result': 'INSTALLED_PENDING_CHECK', 'images': receipt['new_images']})
    print('INSTALLED_PENDING_CHECK', flush=True)


def health(directory, receipt):
    services = receipt['services'] + list(receipt['unchanged_services'])
    values = json.loads(command(['docker', 'inspect', *['beyondquant-' + s + '-1' for s in services]]))
    observed = {}
    for service, value in zip(services, values, strict=True):
        assert value['State']['Running']
        assert value['State'].get('Health', {}).get('Status', 'healthy') == 'healthy'
        assert value['HostConfig']['RestartPolicy']['Name'] == 'unless-stopped'
        state = {'id': value['Id'], 'image': value['Image'], 'started_at': value['State']['StartedAt'],
            'restart_count': value['RestartCount']}
        if service in receipt['new_images']:
            assert value['Image'] == receipt['new_images'][service]
        else:
            assert state == receipt['unchanged_services'][service]
        observed[service] = state
    runtime = json.loads(command(['docker', 'exec', 'beyondquant-runtime-adapter-1', 'python', '-c',
        'import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen("http://127.0.0.1:8400/readyz",timeout=5))))']))
    expected = json.loads((ROOT / 'plugins/dsh-byq/profiles/root-scoped/dsh-0.1.2rc1/byq-product.identity.json').read_text())
    assert runtime['runtime_adapter'] == 'ready' and runtime['release_identity'] == 'matched'
    assert runtime['release_id'] == 'dsh-0.1.2rc1' and runtime['process_ownership'] == 'one-per-root-turn'
    assert runtime['composition_hash'] == expected['composition_hash']
    manifest = command(['docker', 'exec', 'beyondquant-runtime-adapter-1', 'sha256sum', '/opt/byq/builds/build.identity.json']).split()[0]
    assert manifest == sha256(ROOT / 'config/dsh/builds/dsh-0.1.2rc1-post-u8.17.json')
    for url in ('http://127.0.0.1/', 'http://127.0.0.1:8100/readyz'):
        with urllib.request.urlopen(url, timeout=5) as response:
            assert response.status == 200
    gate = Path(receipt['admission_file']).read_text().strip()
    write_json(directory / ('health-' + gate + '.json'), {'result': 'PASS', 'services': observed,
        'runtime_build_sha256': manifest, 'composition_hash': runtime['composition_hash'], 'gate': gate,
        'infrastructure_unchanged': True, 'restart_policy': 'unless-stopped'})
    print(json.dumps({'health': 'PASS', 'services': len(observed), 'gate': gate}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--release-directory', type=Path, required=True)
    parser.add_argument('action', choices=('drain', 'install', 'health', 'open'))
    args = parser.parse_args()
    receipt = validate(args.release_directory)
    if args.action == 'open':
        assert json.loads((args.release_directory / 'health-closed.json').read_text())['result'] == 'PASS'
        set_state(Path(receipt['admission_file']), 'open')
        print('ADMISSION_OPEN')
    else:
        {'drain': drain, 'install': install, 'health': health}[args.action](args.release_directory, receipt)
