#!/usr/bin/env python3
"""Wait for an exact PR head; print state changes and bounded redacted failures."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


def gh(*args):
    return json.loads(subprocess.check_output(['gh', *args], text=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', default='jefison-x/BeyondQuant')
    parser.add_argument('--pr', required=True, type=int)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument('--interval', type=int, default=30)
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout
    previous = None
    while time.monotonic() < deadline:
        pr = gh('pr', 'view', str(args.pr), '--repo', args.repo,
                '--json', 'headRefOid,statusCheckRollup')
        if pr['headRefOid'] != args.expected_head:
            raise SystemExit('STALE: PR head changed; no success claimed')
        checks = pr['statusCheckRollup']
        state = sorted((c.get('name', c.get('context', '?')), c.get('status', 'UNKNOWN'),
                        c.get('conclusion') or '') for c in checks)
        if state != previous:
            print(json.dumps({'head': args.expected_head, 'checks': state}), flush=True)
            previous = state
        required = {c.get('name'): c for c in checks if c.get('name') in ('local-ci', 'ci-gate')}
        if len(required) == 2 and all(c.get('status') == 'COMPLETED' for c in checks):
            success = all(c.get('conclusion') == 'SUCCESS' for c in checks)
            if not success:
                # Fetch logs only after completion; never flood the conversation.
                urls = {c.get('detailsUrl', '') for c in checks if c.get('conclusion') == 'FAILURE'}
                runs = {u.split('/runs/')[1].split('/')[0] for u in urls if '/runs/' in u}
                for run in sorted(runs):
                    if not run.isdigit():
                        continue
                    log = subprocess.run(['gh', 'run', 'view', run, '--repo', args.repo, '--log-failed'],
                                         capture_output=True, text=True, timeout=120)
                    bounded = '\n'.join(log.stdout.splitlines()[-100:])
                    subprocess.run([sys.executable, str(Path(__file__).with_name('redact-log.py'))],
                                   input=bounded, text=True, check=True)
            print(json.dumps({'result': 'PASS' if success else 'FAIL', 'head': args.expected_head}))
            return 0 if success else 1
        time.sleep(max(5, min(args.interval, 60)))
    print('{"result":"NOT_RUN_OR_TIMEOUT"}')
    return 2


if __name__ == '__main__':
    sys.exit(main())
