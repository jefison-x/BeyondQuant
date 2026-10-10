#!/usr/bin/env python3
"""Verify attested manifest, prepare digest overlay or promote without rebuilding."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from images import (
    ACP_PER_ROLE_IMAGE,
    ACP_SINGLE_IMAGE,
    DIGEST,
    PUBLIC_MANIFEST_V2,
    SERVICES,
    checksum,
    release_repository,
    release_sbom_filename,
    validate_acp_release_binding,
    validate_dsh_identity,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.dsh.release_secrets import assert_no_plaintext_secrets  # noqa: E402

# Explicit release tags only: stable version, or a pre-release beta/RC suffix.
VERSION_TAG = re.compile(r'v[0-9]+\.[0-9]+\.[0-9]+(?:-(?:beta|rc)(?:\.[0-9]+)?)?')


def validate(manifest):
    manifest_images = manifest.get('images') if isinstance(manifest, dict) else None
    manifest_sbom = manifest.get('sbom') if isinstance(manifest, dict) else None
    source_sha = manifest.get('source_sha') if isinstance(manifest, dict) else None
    ci_url = manifest.get('ci_url') if isinstance(manifest, dict) else None
    topology = manifest.get('acp_image_topology') if isinstance(manifest, dict) else None
    if (not isinstance(manifest, dict)
            or set(manifest) != {'schema', 'source_sha', 'profile', 'ci_url', 'migration',
                                 'acp_image_topology', 'images', 'sbom', 'dsh_identity'}
            or manifest.get('schema') != PUBLIC_MANIFEST_V2 or manifest.get('profile') != 'full'
            or topology not in (ACP_SINGLE_IMAGE, ACP_PER_ROLE_IMAGE)
            or not isinstance(source_sha, str)
            or not re.fullmatch('[0-9a-f]{40}', source_sha)
            or not isinstance(ci_url, str)
            or not re.fullmatch(r'https://github.com/jefison-x/BeyondQuant/actions/runs/[0-9]+', ci_url)
            or manifest.get('migration') not in ('none', 'forward-compatible', 'operator-required')
            or not isinstance(manifest_images, dict) or set(manifest_images) != set(SERVICES)
            or not isinstance(manifest_sbom, dict) or set(manifest_sbom) != set(SERVICES)):
        raise ValueError('invalid release manifest')
    for service in SERVICES:
        image = manifest_images[service]
        prefix = release_repository(service, topology) + '@'
        if (not isinstance(image, dict) or set(image) != {'ref', 'image_id'}
                or not isinstance(image['ref'], str) or not image['ref'].startswith(prefix)
                or not DIGEST.fullmatch(image['ref'][len(prefix):])
                or not isinstance(image['image_id'], str) or not DIGEST.fullmatch(image['image_id'])):
            raise ValueError('invalid digest-pinned service reference')
        sbom = manifest_sbom[service]
        if (not isinstance(sbom, dict) or set(sbom) != {'file', 'sha256'}
                or sbom['file'] != release_sbom_filename(service, topology)
                or not isinstance(sbom['sha256'], str) or not DIGEST.fullmatch(sbom['sha256'])):
            raise ValueError('invalid SBOM binding')
    validate_dsh_identity(manifest['dsh_identity'], {
        service: item['image_id'] for service, item in manifest_images.items()
    }, topology)
    validate_acp_release_binding(
        {service: item['image_id'] for service, item in manifest_images.items()},
        {service: item['ref'] for service, item in manifest_images.items()},
        {service: (item['file'], item['sha256']) for service, item in manifest_sbom.items()},
        topology,
    )
    return manifest


def verify_sbom_receipts(path, manifest):
    """Checksum each distinct SBOM the manifest lists exactly once.

    The release workflow uploads ``manifest.json`` and every generated
    ``*.spdx.json`` into the same directory, and attests only ``manifest.json``.
    The recorded sha256 per service is therefore meaningful only when the
    accompanying files are re-read from the manifest's own directory (the
    ``path`` argument). Every distinct file is verified once (the single-image
    topology lists one SBOM for three services); a missing, unreadable or
    mismatched SBOM fails closed.
    """
    seen = set()
    for service in SERVICES:
        sbom = manifest['sbom'][service]
        name = sbom['file']
        if name in seen:
            continue
        seen.add(name)
        sbom_path = path.parent / name
        try:
            actual = checksum(sbom_path)
        except OSError as exc:
            raise ValueError(f'release SBOM receipt is missing or unreadable: {name}') from exc
        if actual != sbom['sha256']:
            raise ValueError(f'release SBOM receipt does not match its recorded digest: {name}')


def verified(path):
    manifest = validate(json.loads(path.read_text()))
    # The attested manifest only binds the SBOM hashes; the accompanying SBOM
    # files must actually match those hashes before operator input is produced.
    verify_sbom_receipts(path, manifest)
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


def verify_registry_services(manifest, services):
    """Pull and cross-check each distinct qualified ref exactly once.

    ADR-0110: the single-image topology binds three services to one ref, so a
    release must not pull and re-verify the same registry artifact repeatedly.
    Every distinct ref a requested service binds is still verified before any
    operator input is produced.
    """
    validated = set()
    for name in services:
        image = manifest['images'][name]
        if image['ref'] in validated:
            continue
        subprocess.run(['docker', 'pull', image['ref']], check=True)
        inspection = json.loads(subprocess.check_output(
            ['docker', 'image', 'inspect', image['ref']], text=True))[0]
        remote = json.loads(subprocess.check_output(
            ['docker', 'manifest', 'inspect', image['ref']], text=True))
        verify_pulled_image(image, inspection, remote)
        validated.add(image['ref'])


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
        assert_no_plaintext_secrets(overlay)
        # Validate registry content before producing operator input; never execute
        # image commands. The single-image topology binds three services to one
        # ref, so pull and inspect each distinct ref exactly once.
        verify_registry_services(manifest, services)
        with args.output.open('x') as output:
            json.dump(overlay, output, indent=2)
            output.write('\n')
    else:
        if not args.tag or not VERSION_TAG.fullmatch(args.tag):
            raise ValueError('explicit version, beta or RC tag required')
        promote(manifest, args.tag)


def promote(manifest, tag):
    # Check every destination before changing any tag. Repeated same-image promotion is safe.
    # The single-image topology maps three services to one ref, so inspect and
    # create each distinct destination tag exactly once.
    destinations = {}
    for image in manifest['images'].values():
        repository, _digest = image['ref'].split('@')
        target = repository + ':' + tag
        if target in destinations and destinations[target] != image['ref']:
            raise ValueError('one version tag cannot bind two different images')
        destinations[target] = image['ref']
    pending = []
    for target, source in destinations.items():
        digest = source.split('@', 1)[1]
        probe = subprocess.run(['docker', 'buildx', 'imagetools', 'inspect', target, '--format', '{{json .Manifest}}'], capture_output=True, text=True)
        if probe.returncode == 0:
            if json.loads(probe.stdout)['digest'] != digest:
                raise ValueError('version tag already points to a different image')
        elif 'not found' not in probe.stderr.lower():
            raise ValueError('cannot establish target tag absence')
        else:
            pending.append((target, source))
    for target, source in pending:
        subprocess.run(['docker', 'buildx', 'imagetools', 'create', '--prefer-index=false', '--tag', target, source], check=True)


if __name__ == '__main__':
    main()
