#!/usr/bin/env python3
"""Verify attested manifest, prepare digest overlay or promote without rebuilding."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from images import DIGEST, SERVICES


def validate(manifest):
    if (manifest.get('schema') != 'byq-release.v1' or manifest.get('profile') != 'full'
            or not re.fullmatch('[0-9a-f]{40}', manifest.get('source_sha', ''))
            or not re.fullmatch(r'https://github.com/jefison-x/BeyondQuant/actions/runs/[0-9]+', manifest.get('ci_url', ''))
            or manifest.get('migration') not in ('none', 'forward-compatible', 'operator-required')
            or set(manifest.get('images', {})) != set(SERVICES)
            or set(manifest.get('sbom', {})) != set(SERVICES)):
        raise ValueError('invalid release manifest')
    for service in SERVICES:
        image = manifest['images'][service]
        prefix = f'ghcr.io/jefison-x/beyondquant/{service}@'
        if (not image['ref'].startswith(prefix) or not DIGEST.fullmatch(image['ref'][len(prefix):])
                or not DIGEST.fullmatch(image['image_id'])):
            raise ValueError('invalid digest-pinned service reference')
        sbom = manifest['sbom'][service]
        if sbom['file'] != service + '.spdx.json' or not DIGEST.fullmatch(sbom['sha256']):
            raise ValueError('invalid SBOM binding')
    return manifest


def verified(path):
    manifest = validate(json.loads(path.read_text()))
    # Repository name alone is insufficient: bind signer workflow and main ref.
    subprocess.run(['gh', 'attestation', 'verify', str(path), '--repo', 'jefison-x/BeyondQuant',
                    '--signer-workflow', 'jefison-x/BeyondQuant/.github/workflows/release-images.yml',
                    '--source-ref', 'refs/heads/main', '--source-digest', manifest['source_sha']], check=True)
    run = manifest['ci_url'].rsplit('/', 1)[1]
    result = json.loads(subprocess.check_output(['gh', 'api', f'repos/jefison-x/BeyondQuant/actions/runs/{run}'], text=True))
    if (result['conclusion'] != 'success' or result['head_sha'] != manifest['source_sha']
            or result['event'] != 'workflow_dispatch' or result['head_branch'] != 'main'
            or result['path'] != '.github/workflows/release-images.yml'):
        raise ValueError('release run is not a successful trusted-main qualification')
    return manifest


def verify_pulled_image(image, inspection, remote):
    """Bind the pulled manifest and its config across Docker image stores.

    Classic store Id is the config digest; containerd store Id is the target
    manifest digest. Neither may be treated as an interchangeable free-form ID.
    """
    manifest_digest = image['ref'].split('@', 1)[1]
    if (remote.get('config', {}).get('digest') != image['image_id']
            or image['ref'] not in inspection.get('RepoDigests', [])
            or inspection.get('Os') != 'linux' or inspection.get('Architecture') != 'amd64'):
        raise ValueError('pulled manifest/config/platform differs from qualified image')
    actual = inspection.get('Id')
    if actual == image['image_id']:
        return
    if (actual == manifest_digest
            and inspection.get('Descriptor', {}).get('digest') == manifest_digest):
        return
    raise ValueError('unbound local image identity')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('overlay', 'promote'))
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--services', default=','.join(SERVICES))
    parser.add_argument('--tag')
    args = parser.parse_args()
    manifest = verified(args.manifest)
    if args.action == 'overlay':
        services = args.services.split(',')
        if not services or len(set(services)) != len(services) or not set(services) <= set(SERVICES) or not args.output:
            raise ValueError('explicit valid services/output required')
        if manifest['migration'] == 'operator-required':
            raise ValueError('migration review unresolved; prepare a reviewed release')
        overlay = {'services': {name: {'image': manifest['images'][name]['ref']} for name in services}}
        # Validate registry content before producing operator input; never execute image commands.
        for name in services:
            image = manifest['images'][name]
            subprocess.run(['docker', 'pull', image['ref']], check=True)
            inspection = json.loads(subprocess.check_output(
                ['docker', 'image', 'inspect', image['ref']], text=True))[0]
            remote = json.loads(subprocess.check_output(
                ['docker', 'manifest', 'inspect', image['ref']], text=True))
            verify_pulled_image(image, inspection, remote)
        with args.output.open('x') as output:
            json.dump(overlay, output, indent=2)
            output.write('\n')
    else:
        if not args.tag or not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+(?:-rc\.[0-9]+)?', args.tag):
            raise ValueError('explicit version or RC tag required')
        promote(manifest, args.tag)


def promote(manifest, tag):
    # Check every destination before changing any tag. Repeated same-image promotion is safe.
    pending = []
    for name, image in manifest['images'].items():
        repository, digest = image['ref'].split('@')
        target = repository + ':' + tag
        probe = subprocess.run(['docker', 'buildx', 'imagetools', 'inspect', target, '--format', '{{json .Manifest}}'], capture_output=True, text=True)
        if probe.returncode == 0:
            if json.loads(probe.stdout)['digest'] != digest:
                raise ValueError('version tag already points to a different image')
        elif 'not found' not in probe.stderr.lower():
            raise ValueError('cannot establish target tag absence')
        else:
            pending.append((target, image['ref']))
    for target, source in pending:
        subprocess.run(['docker', 'buildx', 'imagetools', 'create', '--prefer-index=false', '--tag', target, source], check=True)


if __name__ == '__main__':
    main()
