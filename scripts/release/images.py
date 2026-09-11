#!/usr/bin/env python3
"""Trusted-main image handoff and publication. No source rebuild in publish."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

SERVICES = ('backend', 'gateway', 'runtime-adapter', 'mcp', 'frontend', 'data-worker',
            'signal-worker', 'ml-worker', 'signal-sandbox', 'feedback-publisher', 'feedback-hub-relay')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def checksum(path):
    with Path(path).open('rb') as stream:
        return 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()


def trusted_main():
    if (os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_REPOSITORY') != 'jefison-x/BeyondQuant'):
        raise ValueError('release publication requires official trusted-main manual dispatch')
    sha = os.environ['GITHUB_SHA']
    if not re.fullmatch('[0-9a-f]{40}', sha) or command('git', 'rev-parse', 'HEAD') != sha:
        raise ValueError('checkout differs from dispatch source')
    return sha


def validate(receipt, sha, run):
    if (receipt.get('schema') != 'byq-release-images.v1' or receipt.get('source_sha') != sha
            or receipt.get('run_id') != run or receipt.get('profile') != 'full'
            or set(receipt.get('images', {})) != set(SERVICES)
            or not DIGEST.fullmatch(receipt.get('archive_sha256', ''))):
        raise ValueError('release receipt does not match trusted source/run/full service set')
    for service, item in receipt['images'].items():
        if (set(item) != {'tag', 'image_id'} or not DIGEST.fullmatch(item['image_id'])
                or item['tag'] != f'byq-release-{run}-{service}:tested'):
            raise ValueError('invalid release image identity')


def export(directory):
    sha = trusted_main()
    run = os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']
    scope = os.environ['BYQ_CI_SCOPE']
    directory.mkdir(parents=True, exist_ok=False)
    images = {}
    for service in SERVICES:
        source = f'byq-ci-stack-{scope}-{service}'
        image_id = command('docker', 'image', 'inspect', source, '--format', '{{.Id}}')
        tag = f'byq-release-{run}-{service}:tested'
        subprocess.run(['docker', 'tag', image_id, tag], check=True)
        images[service] = {'tag': tag, 'image_id': image_id}
    archive = directory / 'images.tar'
    subprocess.run(['docker', 'save', '-o', str(archive), *[i['tag'] for i in images.values()]], check=True)
    receipt = {'schema': 'byq-release-images.v1', 'source_sha': sha, 'run_id': run,
               'profile': 'full', 'images': images, 'archive_sha256': checksum(archive)}
    validate(receipt, sha, run)
    (directory / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    # Archive is the handoff; release tags must not evade scoped cleanup.
    subprocess.run(['docker', 'image', 'rm', *[i['tag'] for i in images.values()]], check=True)


def publish(directory, migration):
    sha = trusted_main()
    run = os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']
    receipt = json.loads((directory / 'receipt.json').read_text())
    # A failed publish job may be retried without rebuilding the successful
    # qualification job. Accept only an earlier attempt of this exact run.
    produced_run = receipt.get('run_id', '')
    match = re.fullmatch(re.escape(os.environ['GITHUB_RUN_ID']) + r'-([1-9][0-9]*)', produced_run)
    if not match or int(match[1]) > int(os.environ['GITHUB_RUN_ATTEMPT']):
        raise ValueError('handoff belongs to a different run or future attempt')
    validate(receipt, sha, produced_run)
    if checksum(directory / 'images.tar') != receipt['archive_sha256']:
        raise ValueError('archive checksum mismatch')
    subprocess.run(['docker', 'load', '-i', str(directory / 'images.tar')], check=True)
    # Resolve every ID before any public write.
    for item in receipt['images'].values():
        if command('docker', 'image', 'inspect', item['tag'], '--format', '{{.Id}}') != item['image_id']:
            raise ValueError('loaded image differs from tested image')
    output = Path('release-manifest')
    output.mkdir(exist_ok=False)
    manifest = {'schema': 'byq-release.v1', 'source_sha': sha, 'profile': 'full',
                'ci_url': f'https://github.com/jefison-x/BeyondQuant/actions/runs/{os.environ["GITHUB_RUN_ID"]}',
                'migration': migration, 'images': {}, 'sbom': {}}
    for service, item in receipt['images'].items():
        sbom = output / f'{service}.spdx.json'
        subprocess.run(['syft', 'docker:' + item['tag'], '-o', f'spdx-json={sbom}'], check=True)
        manifest['sbom'][service] = {'file': sbom.name, 'sha256': checksum(sbom)}
        repository = f'ghcr.io/jefison-x/beyondquant/{service}'
        tag = repository + f':candidate-{sha[:12]}-{run}'
        subprocess.run(['docker', 'tag', item['image_id'], tag], check=True)
        subprocess.run(['docker', 'push', tag], check=True)
        digests = json.loads(command('docker', 'inspect', tag, '--format', '{{json .RepoDigests}}'))
        exact = [ref for ref in digests if ref.startswith(repository + '@')]
        if len(exact) != 1 or not DIGEST.fullmatch(exact[0].split('@')[1]):
            raise ValueError('registry did not return one exact image digest')
        manifest['images'][service] = {'ref': exact[0], 'image_id': item['image_id']}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('export', 'publish'))
    parser.add_argument('--directory', type=Path, default=Path('.ci-artifacts/release-images'))
    parser.add_argument('--migration', choices=('none', 'forward-compatible', 'operator-required'), default='operator-required')
    args = parser.parse_args()
    if args.action == 'export':
        export(args.directory)
    else:
        publish(args.directory, args.migration)
