#!/usr/bin/env python3
"""One impact graph for hosted lanes; unknown paths select integration."""
import argparse
import json
import os
import subprocess

COMPONENTS = ('docs', 'architecture', 'backend', 'gateway', 'runtime', 'mcp', 'frontend')


def plan(base, full=False):
    baseline = subprocess.check_output(['git', 'merge-base', base, 'HEAD'], text=True).strip()
    paths = subprocess.check_output(['git', 'diff', '--name-only', baseline, 'HEAD'], text=True)
    raw = subprocess.check_output(['bash', 'scripts/ci/classify-changes.sh'], input=paths,
                                  text=True, env={**os.environ, 'BYQ_CI_DIFF_BASE': baseline})
    impact = dict(line.split('=', 1) for line in raw.splitlines())
    lanes = [name for name in COMPONENTS if full or impact[name] == 'yes']
    if full or impact['integration'] == 'yes':
        lanes.append('integration')
    if not lanes:
        raise ValueError('empty CI plan')
    return {'include': [{'lane': name, 'browser': name in ('frontend', 'integration')}
                        for name in lanes]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='origin/main')
    parser.add_argument('--full', action='store_true')
    args = parser.parse_args()
    print(json.dumps(plan(args.base, args.full), separators=(',', ':')))
