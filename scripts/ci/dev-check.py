#!/usr/bin/env python3
"""Fast local feedback. Never starts containers or claims remote CI passed."""
import argparse
import ast
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='origin/main')
    args = parser.parse_args()
    subprocess.run(['git', 'diff', '--check'], check=True)
    baseline = subprocess.check_output(['git', 'merge-base', args.base, 'HEAD'], text=True).strip()
    subprocess.run(['git', 'diff', '--check', baseline], check=True)
    names = set()
    for command in (['git', 'diff', '--name-only', '-z', baseline],
                    ['git', 'ls-files', '--others', '--exclude-standard', '-z']):
        names.update(subprocess.check_output(command).decode().split('\0'))
    checked = []
    for name in sorted(names):
        path = Path(name)
        if not name or not path.is_file():
            continue
        if path.suffix == '.py':
            ast.parse(path.read_text(), filename=name)
        elif path.suffix == '.sh':
            subprocess.run(['bash', '-n', name], check=True)
        elif path.suffix == '.json':
            json.loads(path.read_text())
        else:
            continue
        checked.append(name)
    print(json.dumps({'local_syntax': 'PASS', 'files': len(checked),
                      'component_tests': 'NOT_RUN', 'remote_ci': 'REQUIRED'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
