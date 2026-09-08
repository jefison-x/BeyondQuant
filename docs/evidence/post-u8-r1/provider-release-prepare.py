"""Prepare this authorized forward-only release; no service mutation."""
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/dsh'))
from production_backup import write_json, sha256, DESTINATION
from retain_u6_ci_images import load_receipt, validate_archive_metadata, image_id
from admission import initialize

SCOPE = 'local-u7-f7-provider-repair-20260909'
OLD = DESTINATION / 'release-20260908T152238Z'
SERVICES = ('backend', 'mcp', 'gateway', 'runtime-adapter', 'frontend')
UNCHANGED = ('postgres', 'data-worker', 'ml-worker', 'signal-worker', 'signal-sandbox', 'feedback-hub-relay')


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError('operator check failed; private details withheld')
    return result.stdout


def prepare(backup):
    main = Path('/home/jefison/projects/BeyondQuant')
    assert command(['git', '-C', str(main), 'branch', '--show-current']).strip() == 'main'
    assert not command(['git', '-C', str(main), 'status', '--porcelain', '--untracked-files=no']).strip()
    assert command(['git', '-C', str(main), 'rev-parse', 'HEAD']).strip() == command(
        ['git', '-C', str(main), 'rev-parse', 'origin/main']).strip()
    manifest = 'config/dsh/builds/dsh-0.1.2rc1-post-u8.17.json'
    assert (main / manifest).read_bytes() == (ROOT / manifest).read_bytes(), 'repair must be merged and synchronized first'
    assert backup.parent == DESTINATION and backup.resolve() == backup
    saved = json.loads((backup / 'receipt.json').read_text())
    assert saved['readable'] and sha256(backup / 'byq-domain.dump') == saved['dump']['sha256']
    receipt = load_receipt(SCOPE)
    archive = ROOT / '.ci-artifacts' / SCOPE / 'retained-u7/images.tar'
    validate_archive_metadata(archive, receipt)
    for item in receipt['images'].values():
        assert image_id(item['retained_tag']) == item['image_id']
    values = json.loads(command(['docker', 'inspect', *['beyondquant-' + s + '-1' for s in SERVICES + UNCHANGED]]))
    current, unchanged = {}, {}
    for service, value in zip(SERVICES + UNCHANGED, values, strict=True):
        assert value['State']['Running']
        assert value['State'].get('Health', {}).get('Status', 'healthy') == 'healthy'
        assert value['Config']['Labels']['com.docker.compose.project'] == 'beyondquant'
        assert value['Config']['Labels']['com.docker.compose.service'] == service
        assert value['HostConfig']['RestartPolicy']['Name'] == 'unless-stopped'
        if service in SERVICES:
            current[service] = value['Image']
        else:
            unchanged[service] = {'id': value['Id'], 'image': value['Image'],
                'started_at': value['State']['StartedAt'], 'restart_count': value['RestartCount']}
    directory = DESTINATION / dt.datetime.now(dt.timezone.utc).strftime('release-%Y%m%dT%H%M%SZ')
    directory.mkdir(mode=0o700)
    (directory / 'gate').mkdir(mode=0o755)
    initialize(directory / 'gate/admission.state')
    target = json.loads((OLD / 'target.compose.json').read_text())
    for service in ('gateway', 'runtime-adapter'):
        mounts = target['services'][service]['volumes']
        assert len(mounts) == 1 and mounts[0]['target'] == '/opt/byq/admission'
        mounts[0]['source'] = str(directory / 'gate')
    images = {}
    for service in SERVICES:
        key = 'runtime-candidate' if service == 'runtime-adapter' else service
        artifact = receipt['images'][key]
        # Human-readable immutable-per-release tag, always checked against ID.
        target['services'][service]['image'] = artifact['retained_tag']
        images[service] = artifact['image_id']
    runtime = target['services']['runtime-adapter']['environment']
    # Same official runtime and unchanged lifecycle journal schema: preserve
    # the current namespace so durable terminal receipts are not orphaned.
    # ADR-0067 already creates fresh private processes for each new root.
    actual_runtime = values[SERVICES.index('runtime-adapter')]
    actual_env = dict(item.split('=', 1) for item in actual_runtime['Config']['Env'])
    assert runtime['DSH_SESSION_ROOT'] == actual_env['DSH_SESSION_ROOT']
    with (directory / 'images.tar').open('xb') as output, archive.open('rb') as source:
        os.chmod(output.name, 0o600)
        shutil.copyfileobj(source, output)
    assert 'sha256:' + sha256(directory / 'images.tar') == receipt['archive']['sha256']
    write_json(directory / 'target.compose.json', target)
    write_json(directory / 'retained-artifacts.json', receipt)
    preparation = {'schema_version': 'byq-provider-repair-release.v1',
        'ci_scope': SCOPE, 'git_commit': command(['git', '-C', '/home/jefison/projects/BeyondQuant', 'rev-parse', 'HEAD']).strip(),
        'services': list(SERVICES), 'old_images': current, 'new_images': images,
        'unchanged_services': unchanged, 'old_admission_file': str(OLD / 'gate/admission.state'),
        'admission_file': str(directory / 'gate/admission.state'), 'namespace': runtime['DSH_SESSION_ROOT'],
        'overlay_sha256': sha256(directory / 'target.compose.json'),
        'archive_sha256': sha256(directory / 'images.tar'), 'logical_backup': str(backup),
        'logical_backup_sha256': saved['dump']['sha256'], 'mode': 'forward-only',
        'authorization': 'F7 repair, push/merge, production deploy; opaque Go session header explicitly allowed',
        'failure_policy': 'close admission and report; no old-image or database rollback',
        'historical_replay': False, 'f6_activation': False, 'data_deletion': False}
    write_json(directory / 'preparation.json', preparation)
    print(json.dumps({'directory': str(directory), 'production_changed': False, 'new_images': images}))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--backup', type=Path, required=True)
    prepare(parser.parse_args().backup)
