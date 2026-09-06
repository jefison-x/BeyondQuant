#!/usr/bin/env python3
"""Private B0 image/configuration archive; no service or database changes.

The configured container environment may contain secrets. It is written only to
the approved private backup directory, never stdout or the repository. This is
not the final drained session/WorkflowTrace backup and is not a deploy command.
"""
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess

from production_backup import DESTINATION, run, sha256, write_json

MAIN = Path('/home/jefison/projects/BeyondQuant')
SERVICES = ('backend', 'mcp', 'gateway', 'runtime-adapter', 'frontend')


def private_root():
    if (DESTINATION.resolve() != DESTINATION or not DESTINATION.is_dir()
            or DESTINATION.stat().st_uid != os.getuid()
            or DESTINATION.stat().st_mode & 0o077):
        raise ValueError('existing approved private backup root required')
    return DESTINATION


def backup():
    root = private_root()
    names = ['beyondquant-' + service + '-1' for service in SERVICES]
    containers = json.loads(run(['docker', 'inspect', *names], stdout=subprocess.PIPE).stdout)
    if len(containers) != len(SERVICES):
        raise ValueError('production application inventory incomplete')
    safe = {}
    for service, container in zip(SERVICES, containers):
        labels = container['Config']['Labels']
        if (container['Name'] != '/beyondquant-' + service + '-1'
                or labels.get('com.docker.compose.project') != 'beyondquant'
                or labels.get('com.docker.compose.service') != service
                or not container['State']['Running']
                or not re.fullmatch(r'sha256:[a-f0-9]{64}', container['Image'])):
            raise ValueError('production application identity/readiness mismatch')
        safe[service] = {'container_id': container['Id'], 'image_id': container['Image'],
                         'started_at': container['State']['StartedAt']}
    sources = {name: MAIN / name for name in ('.env', 'compose.yml')}
    if any(path.is_symlink() or not path.is_file() or path.resolve() != path for path in sources.values()):
        raise ValueError('canonical existing production configuration files required')
    directory = root / dt.datetime.now(dt.timezone.utc).strftime('application-%Y%m%dT%H%M%SZ')
    directory.mkdir(mode=0o700)
    write_json(directory / 'container-config.private.json', containers)
    for name, source in sources.items():
        with (directory / name).open('xb') as output:
            os.chmod(output.name, 0o600)
            output.write(source.read_bytes())
    print(json.dumps({'stage': 'private-application-archive', 'directory': str(directory),
                      'services': list(SERVICES)}), flush=True)
    archive = directory / 'original-images.tar'
    with archive.open('xb') as output:
        os.chmod(archive, 0o600)
        run(['docker', 'image', 'save', *sorted({item['image_id'] for item in safe.values()})],
            stdout=output, timeout=300)
    files = {}
    for path in (archive, directory / 'container-config.private.json', *(directory / name for name in sources)):
        files[path.name] = {'bytes': path.stat().st_size, 'sha256': sha256(path), 'mode': '0600'}
    receipt = {'schema_version': 'byq-u7-application-backup.v1', 'services': safe, 'files': files,
               'finished_at': dt.datetime.now(dt.timezone.utc).isoformat(),
               'source_main_commit': run(['git', '-C', str(MAIN), 'rev-parse', 'HEAD'],
                                         stdout=subprocess.PIPE, text=True).stdout.strip(),
               'configuration_scope': 'actual container inspect plus current main Compose/env; not assumed identical',
               'production_changed': False, 'drained_session_backup': 'NOT_INCLUDED'}
    write_json(directory / 'receipt.json', receipt)
    print(json.dumps({'stage': 'application-backup-complete', 'directory': str(directory),
                      'archive': files[archive.name], 'production_changed': False}), flush=True)


if __name__ == '__main__':
    backup()
