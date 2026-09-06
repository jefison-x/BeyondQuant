#!/usr/bin/env python3
"""Prepare private exact-image U7 overlays; NEVER starts/stops production.

This command does not grant deployment authority. Use only after reviewing the
final-image qualification. Deployment additionally requires merged clean main,
ingress closure/drain, final private backups and separate operator verification.
"""
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil

from admission import initialize
from production_application_backup import private_root
from production_backup import sha256, write_json
from retain_u6_ci_images import ROOT, load_receipt, image_id, validate_archive_metadata

SCOPE = 'local-u7-recheck-artifacts-20260906'
SERVICES = ('backend', 'mcp', 'gateway', 'runtime-adapter', 'frontend')


def overlay(receipt, directory, mode):
    if mode not in {'prepare', 'target', 'rollback'}:
        raise ValueError('explicit U7 prepare/target/rollback required')
    if (directory.parent != Path('/home/jefison/backups/byq-dsh-u7')
            or re.fullmatch(r'release-[0-9]{8}T[0-9]{6}Z', directory.name) is None):
        raise ValueError('dedicated approved release directory required')
    target = mode == 'target'
    release = 'dsh-0.1.2rc1' if target else 'dsh-0.1.1rc1'
    members = {}
    for service in SERVICES:
        key = 'runtime-candidate' if target and service == 'runtime-adapter' else service
        identity = receipt['images'][key]['image_id']
        if re.fullmatch(r'sha256:[a-f0-9]{64}', identity) is None:
            raise ValueError('immutable local image ID required')
        members[service] = {'image': identity, 'pull_policy': 'never'}
    policy = '/app/qualified-' + ('' if target else 'rollback-') + 'web-evidence-provenance.json'
    members['backend']['environment'] = {
        'BYQ_PLUGIN_REGISTRY_PATH': '/app/plugin-registry/' + ('product-plugins.json' if target else 'plugins.json'),
        'BYQ_WEB_EVIDENCE_PROVENANCE_POLICY': policy,
    }
    members['mcp']['environment'] = {'BYQ_WEB_EVIDENCE_PROVENANCE_POLICY': policy}
    generation = directory.name + '-' + mode
    members['runtime-adapter']['environment'] = {
        'BYQ_DSH_COMPATIBILITY_RELEASE': release,
        'BYQ_DSH_COMPOSITION': '/opt/byq/profiles/byq-product.patch.yml' if target else '/opt/byq/compositions/byq-product-sdk.cordis.yml',
        'DSH_SESSION_ROOT': '/var/lib/byq/dsh-sessions/' + release + '/' + generation,
    }
    for name in ('gateway', 'runtime-adapter'):
        members[name].setdefault('environment', {})['BYQ_CHAT_ADMISSION_FILE'] = '/opt/byq/admission/admission.state'
        members[name]['volumes'] = [{'type': 'bind', 'source': str(directory / 'gate'),
                                   'target': '/opt/byq/admission', 'read_only': True}]
    return {'services': members}


def prepare():
    receipt = load_receipt(SCOPE)
    source = ROOT / '.ci-artifacts' / SCOPE / 'retained-u7' / 'images.tar'
    validate_archive_metadata(source, receipt)
    for item in receipt['images'].values():
        if image_id(item['retained_tag']) != item['image_id']:
            raise ValueError('retained image no longer matches qualification input')
    root = private_root()
    directory = root / dt.datetime.now(dt.timezone.utc).strftime('release-%Y%m%dT%H%M%SZ')
    directory.mkdir(mode=0o700)
    archive = directory / 'images.tar'
    with source.open('rb') as src, archive.open('xb') as dst:
        os.chmod(archive, 0o600)
        shutil.copyfileobj(src, dst)
    if 'sha256:' + sha256(archive) != receipt['archive']['sha256']:
        raise ValueError('private copied image archive integrity mismatch')
    (directory / 'gate').mkdir(mode=0o755)
    initialize(directory / 'gate/admission.state')
    os.chmod(directory / 'gate/admission.state', 0o644)
    files = {}
    for mode in ('prepare', 'target', 'rollback'):
        path = directory / (mode + '.compose.json')
        write_json(path, overlay(receipt, directory, mode))
        files[path.name] = sha256(path)
    write_json(directory / 'retained-artifacts.json', receipt)
    result = {'schema_version': 'byq-u7-private-release-preparation.v1',
              'ci_scope': SCOPE, 'archive': receipt['archive'], 'overlay_sha256': files,
              'services': list(SERVICES), 'gate_state': 'closed', 'production_changed': False,
              'deployment_result': 'NOT_RUN', 'retention': 'at least 7 days AND maintainer stable confirmation; no automatic deletion'}
    write_json(directory / 'receipt.json', result)
    print(json.dumps({'directory': str(directory), **result}, sort_keys=True))


if __name__ == '__main__':
    prepare()
