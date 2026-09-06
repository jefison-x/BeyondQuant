#!/usr/bin/env python3
"""Archive exact DSH/WorkflowTrace volumes only after both writers are stopped.

Does not stop containers, restore volumes, copy PostgreSQL storage or deploy.
The trusted operator must first close ingress and drain active prompts. Existing
private release preparation and stopped exact writer identities are mandatory.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

from production_backup import DESTINATION, run, sha256, write_json

VOLUMES = {'runtime-adapter': ('byq_dsh_sessions', '/var/lib/byq/dsh-sessions'),
           'gateway': ('byq_workflow_traces', '/var/lib/byq/workflow-traces')}


def checked_writers(containers):
    if len(containers) != 2:
        raise ValueError('both exact session writers required')
    result = {}
    for container in containers:
        labels = container['Config']['Labels']
        service = labels.get('com.docker.compose.service')
        if (service not in VOLUMES or service in result
                or labels.get('com.docker.compose.project') != 'beyondquant'
                or container['Name'] != '/beyondquant-' + service + '-1'
                or container['State']['Running'] or container['State'].get('Restarting')):
            raise ValueError('exact stopped BYQ session writers required; drain first')
        volume, destination = VOLUMES[service]
        mounts = [m for m in container['Mounts'] if m['Destination'] == destination]
        if len(mounts) != 1 or mounts[0].get('Type') != 'volume' or mounts[0].get('Name') != volume:
            raise ValueError('session/trace volume identity mismatch')
        result[service] = {'container_id': container['Id'], 'volume': volume,
                           'finished_at': container['State']['FinishedAt']}
    return result


def backup(directory):
    if (directory.parent != DESTINATION or directory.resolve() != directory
            or re.fullmatch(r'release-[0-9]{8}T[0-9]{6}Z', directory.name) is None
            or directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077):
        raise ValueError('existing private approved release directory required')
    if (directory / 'gate/admission.state').read_text() != 'closed\n':
        raise ValueError('gate must remain closed')
    names = ['beyondquant-' + name + '-1' for name in VOLUMES]
    writers = checked_writers(json.loads(run(['docker', 'inspect', *names], stdout=subprocess.PIPE).stdout))
    receipt = json.loads((directory / 'retained-artifacts.json').read_text())
    image = receipt['images']['runtime-adapter']['image_id']
    if re.fullmatch(r'sha256:[a-f0-9]{64}', image) is None:
        raise ValueError('immutable retained archive utility image required')
    destination = directory / dt.datetime.now(dt.timezone.utc).strftime('sessions-%Y%m%dT%H%M%SZ')
    destination.mkdir(mode=0o700)
    files = {}
    for service, identity in writers.items():
        path = destination / (service + '.tar')
        scope = 'byq-u7-volume-backup-' + uuid.uuid4().hex[:12]
        with path.open('xb') as output:
            os.chmod(path, 0o600)
            run(['docker', 'run', '--rm', '--name', scope, '--label', 'byq.u7.volume-backup=' + scope,
                 '--network', 'none', '--read-only', '--user', '0:0', '--cap-drop', 'ALL',
                 '--cap-add', 'DAC_OVERRIDE', '--security-opt', 'no-new-privileges',
                 '--mount', 'type=volume,source=' + identity['volume'] + ',target=/source,readonly',
                 '--entrypoint', 'tar', image, '-C', '/source', '-cf', '-', '.'], stdout=output, timeout=300)
        run(['tar', '-tf', str(path)], stdout=subprocess.DEVNULL, timeout=60)
        files[path.name] = {'bytes': path.stat().st_size, 'sha256': sha256(path), 'mode': '0600', 'readable': True}
    # A writer restart during copying invalidates consistency; do not silently pass.
    if checked_writers(json.loads(run(['docker', 'inspect', *names], stdout=subprocess.PIPE).stdout)) != writers:
        raise ValueError('writer identity changed during session backup')
    result = {'schema_version': 'byq-u7-session-backup.v1', 'writers': writers, 'files': files,
              'consistency': 'both exact writers stopped throughout copy', 'database_included': False,
              'production_data_modified': False}
    write_json(destination / 'receipt.json', result)
    print(json.dumps({'directory': str(destination), **result}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-directory', type=Path, required=True)
    backup(parser.parse_args().release_directory)
