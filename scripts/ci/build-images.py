#!/usr/bin/env python3
"""Build exactly the selected Compose targets with bounded, per-service cache."""
import json
import os
from pathlib import Path
import subprocess
import sys

services = sys.argv[1:]
if not services or any(not s.replace('-', '').isalnum() for s in services):
    raise SystemExit('explicit service targets required')
config = json.loads(subprocess.check_output(
    ['docker', 'compose', '--profile', 'feedback-publisher', 'build', '--print', *services], text=True))
for name, target in config['target'].items():
    target['platforms'] = ['linux/amd64']
    target['cache-from'] = [f'type=gha,version=2,scope=byq-{name}-amd64']
    target['cache-to'] = [f'type=gha,version=2,scope=byq-{name}-amd64,mode=min,ignore-error=true']
output = Path('.ci-artifacts') / os.environ['BYQ_CI_SCOPE'] / 'build.json'
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(config))
subprocess.run(['docker', 'buildx', 'bake', '--file', str(output), '--load', *services], check=True)
