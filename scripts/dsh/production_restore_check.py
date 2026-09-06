#!/usr/bin/env python3
"""Restore one approved private U7 dump into a network-isolated disposable DB.

Never mount/read the production data directory, contact a model or restore the
production database. Only the exact newly created test container/volume is removed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

from production_backup import DESTINATION, run, sha256, write_json


def validate_directory(path):
    if (path.parent != DESTINATION or path.resolve() != path or not path.is_dir()
            or not re.fullmatch(r'baseline-\d{8}T\d{6}Z', path.name)
            or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077):
        raise ValueError('exact private approved backup directory required')
    receipt = json.loads((path / 'receipt.json').read_text())
    dump = path / 'byq-domain.dump'
    if (receipt.get('schema_version') != 'byq-u7-production-backup.v1'
            or receipt.get('database') != 'byq_domain'
            or dump.is_symlink() or dump.stat().st_mode & 0o077
            or dump.stat().st_size != receipt['dump']['bytes']
            or sha256(dump) != receipt['dump']['sha256']
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', receipt['image_id'])):
        raise ValueError('backup integrity/identity mismatch')
    return receipt, dump


def restore_check(path):
    receipt, dump = validate_directory(path)
    scope = 'byq-u7-restore-' + uuid.uuid4().hex[:12]
    volume = scope + '-data'
    created_volume = created_container = False
    result = {'schema_version': 'byq-u7-restore-check.v1', 'scope': scope,
              'production_changed': False, 'result': 'FAIL', 'cleanup': 'NOT_RUN'}
    try:
        run(['docker', 'volume', 'create', '--label', 'org.beyondquant.u7-restore=' + scope, volume], stdout=subprocess.DEVNULL)
        created_volume = True
        run(['docker', 'run', '-d', '--name', scope, '--network', 'none',
             '--label', 'org.beyondquant.u7-restore=' + scope,
             '--mount', f'type=volume,source={volume},target=/var/lib/postgresql/data',
             '-e', 'POSTGRES_USER=byq_app', '-e', 'POSTGRES_DB=byq_restore_u7',
             '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', receipt['image_id']], stdout=subprocess.DEVNULL)
        created_container = True
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            probe = subprocess.run(['docker', 'exec', scope, 'pg_isready', '-U', 'byq_app', '-d', 'byq_restore_u7'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if probe.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('isolated restore database not ready')
        print(json.dumps({'stage': 'actual-restore', 'scope': scope}), flush=True)
        with dump.open('rb') as source:
            run(['docker', 'exec', '-i', scope, 'pg_restore', '--exit-on-error', '--no-owner',
                 '--no-privileges', '-U', 'byq_app', '-d', 'byq_restore_u7'], stdin=source, stdout=subprocess.DEVNULL)
        print(json.dumps({'stage': 'verify-restored-content', 'scope': scope}), flush=True)
        command = ['docker', 'exec', '-i', scope, 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-U', 'byq_app', '-d', 'byq_restore_u7']
        tables = run(command, input="SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;",
                     text=True, stdout=subprocess.PIPE).stdout.splitlines()
        if set(tables) != set(receipt['table_counts']) or any(not re.fullmatch(r'[a-z][a-z0-9_]*', t) for t in tables):
            raise ValueError('restored table inventory mismatch')
        query = '\n'.join(f'SELECT \'{t}\', count(*) FROM public."{t}";' for t in tables)
        output = run(command, input=query, stdout=subprocess.PIPE, text=True).stdout
        counts = {line.split('|')[0]: int(line.split('|')[1]) for line in output.splitlines()}
        if counts != receipt['table_counts']:
            raise ValueError('restored table count mismatch')
        fingerprints = {}
        for table in receipt['critical_sha256']:
            if table not in tables:
                raise ValueError('unknown critical table')
            sql = f'COPY (SELECT row_to_json(t)::text FROM public."{table}" t ORDER BY row_to_json(t)::text) TO STDOUT;'
            proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            proc.stdin.write(sql.encode()); proc.stdin.close()
            fingerprints[table] = hashlib.file_digest(proc.stdout, 'sha256').hexdigest()
            if proc.wait():
                raise RuntimeError('restored fingerprint query failed')
        if fingerprints != receipt['critical_sha256']:
            raise ValueError('restored critical content mismatch')
        constraints = run(command, input='SELECT count(*) FROM pg_constraint WHERE NOT convalidated;',
                          stdout=subprocess.PIPE, text=True).stdout.strip()
        if constraints != '0':
            raise ValueError('unvalidated restored constraints')
        result.update(result='PASS', table_count=len(tables), critical_tables=len(fingerprints),
                      constraints_validated=True, dump_sha256=receipt['dump']['sha256'])
    finally:
        if created_container:
            label = run(['docker', 'inspect', '--format', '{{index .Config.Labels "org.beyondquant.u7-restore"}}', scope], stdout=subprocess.PIPE, text=True).stdout.strip()
            if label != scope:
                raise RuntimeError('refusing cleanup: container label changed')
            run(['docker', 'rm', '-f', scope], stdout=subprocess.DEVNULL)
        if created_volume:
            label = run(['docker', 'volume', 'inspect', '--format', '{{index .Labels "org.beyondquant.u7-restore"}}', volume], stdout=subprocess.PIPE, text=True).stdout.strip()
            if label != scope:
                raise RuntimeError('refusing cleanup: volume label changed')
            run(['docker', 'volume', 'rm', volume], stdout=subprocess.DEVNULL)
        result['cleanup'] = 'PASS'
        write_json(path / ('restore-check-' + scope + '.json'), result)
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-directory', required=True, type=Path)
    restore_check(parser.parse_args().backup_directory)
