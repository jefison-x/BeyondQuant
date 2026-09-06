#!/usr/bin/env python3
"""U7 trusted-operator backup. Private data never enters stdout or Git.

Exact maintainer-approved destination and production database. No source DB
restore, database deletion, container recreation or Community access.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

DESTINATION = Path('/home/jefison/backups/byq-dsh-u7')
DATABASE_CONTAINER = 'beyondquant-postgres-1'
DATABASE_VOLUME = 'byq-postgres-clean-20260904'
CRITICAL = ('agent_approvals', 'artifacts', 'backtest_jobs',
            'product_conversations', 'product_conversation_messages',
            'product_feedback', 'product_feedback_revisions', 'research_tasks')


def private_directory(path: Path) -> Path:
    if path != DESTINATION or path.resolve() != path:
        raise ValueError('only the approved canonical backup destination is allowed')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir() or path.is_symlink() or path.stat().st_uid != os.getuid():
        raise ValueError('backup directory ownership/type mismatch')
    os.chmod(path, 0o700)
    child = path / dt.datetime.now(dt.timezone.utc).strftime('baseline-%Y%m%dT%H%M%SZ')
    child.mkdir(mode=0o700)
    return child


def run(argv, **kwargs):
    result = subprocess.run(argv, stderr=subprocess.PIPE, **kwargs)
    if result.returncode:
        # stderr may contain database row contents or connection credentials.
        raise RuntimeError(f'operator subprocess failed ({result.returncode}); private evidence retained')
    return result


def psql():
    return ['docker', 'exec', '-i', DATABASE_CONTAINER, 'psql', '-X', '-qAt',
            '-v', 'ON_ERROR_STOP=1', '-U', 'byq_app', '-d', 'byq_domain']


def checked_container():
    value = json.loads(run(['docker', 'inspect', DATABASE_CONTAINER],
                           stdout=subprocess.PIPE).stdout)[0]
    if (value['Config']['Labels'].get('com.docker.compose.project') != 'beyondquant'
            or not value['State']['Running']
            or not any(m.get('Name') == DATABASE_VOLUME
                       and m['Destination'] == '/var/lib/postgresql/data' for m in value['Mounts'])):
        raise ValueError('production database identity/readiness mismatch')
    return {'container_id': value['Id'], 'image_id': value['Image'],
            'volume': DATABASE_VOLUME, 'database': 'byq_domain'}


def sha256(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def write_json(path, value):
    with path.open('x', encoding='utf-8') as output:
        os.chmod(path, 0o600)
        json.dump(value, output, indent=2, sort_keys=True)
        output.write('\n')


def backup():
    identity = checked_container()
    directory = private_directory(DESTINATION)
    write_json(directory / 'started.json', identity)
    print(json.dumps({'stage': 'logical-backup', 'directory': str(directory)}), flush=True)
    # Keep one exported READ ONLY snapshot alive for dump and comparison counts.
    keeper = subprocess.Popen(psql(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True, bufsize=1)
    try:
        keeper.stdin.write('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SELECT pg_export_snapshot();\n')
        keeper.stdin.flush()
        snapshot = keeper.stdout.readline().strip()
        if not re.fullmatch(r'[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+', snapshot):
            raise ValueError('invalid exported database snapshot')
        dump = directory / 'byq-domain.dump'
        with dump.open('xb') as output:
            os.chmod(dump, 0o600)
            run(['docker', 'exec', DATABASE_CONTAINER, 'pg_dump', '-U', 'byq_app',
                 '-d', 'byq_domain', '-Fc', '-Z', '1', '--snapshot', snapshot], stdout=output)
        print(json.dumps({'stage': 'snapshot-counts', 'directory': str(directory)}), flush=True)
        tables = run(psql(), input="SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;\n",
                     stdout=subprocess.PIPE, text=True).stdout.splitlines()
        if not tables or any(not re.fullmatch(r'[a-z][a-z0-9_]*', t) for t in tables):
            raise ValueError('unexpected source table inventory')
        queries = [f"BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET TRANSACTION SNAPSHOT '{snapshot}';"]
        queries += [f'SELECT \'{t}\', count(*) FROM public."{t}";' for t in tables]
        queries += ['COMMIT;']
        counts = run(psql(), input='\n'.join(queries), stdout=subprocess.PIPE, text=True).stdout
        count_map = {line.split('|')[0]: int(line.split('|')[1]) for line in counts.splitlines()}
        fingerprints = {}
        for table in CRITICAL:
            sql = (f"BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET TRANSACTION SNAPSHOT '{snapshot}'; "
                   f"COPY (SELECT row_to_json(t)::text FROM public.\"{table}\" t ORDER BY row_to_json(t)::text) TO STDOUT; COMMIT;")
            # Critical rows are streamed to a digest, never collected or printed.
            proc = subprocess.Popen(psql(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL)
            proc.stdin.write(sql.encode()); proc.stdin.close()
            fingerprints[table] = hashlib.file_digest(proc.stdout, 'sha256').hexdigest()
            if proc.wait():
                raise RuntimeError('critical row fingerprint failed')
        run(['docker', 'exec', '-i', DATABASE_CONTAINER, 'pg_restore', '--list'],
            stdin=dump.open('rb'), stdout=subprocess.DEVNULL)
        receipt = {'schema_version': 'byq-u7-production-backup.v1', **identity,
                   'finished_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                   'dump': {'name': dump.name, 'bytes': dump.stat().st_size,
                            'sha256': sha256(dump), 'mode': '0600'},
                   'table_counts': count_map, 'critical_sha256': fingerprints,
                   'consistency': 'same exported repeatable-read snapshot',
                   'readable': True, 'actual_restore': 'NOT_RUN'}
        write_json(directory / 'receipt.json', receipt)
        print(json.dumps({'stage': 'backup-complete', 'directory': str(directory),
                          'dump': receipt['dump'], 'tables': len(count_map),
                          'actual_restore': 'NOT_RUN'}), flush=True)
        return directory
    finally:
        if keeper.poll() is None:
            try:
                keeper.stdin.write('ROLLBACK;\n'); keeper.stdin.flush(); keeper.stdin.close()
                keeper.wait(timeout=10)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                keeper.terminate(); keeper.wait(timeout=10)


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    backup()
