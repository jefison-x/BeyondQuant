#!/usr/bin/env python3
"""Audit the H4 interface reliability review against the current source.

This is a fail-closed auditor, not a read-only reporter:

* every discovered interface must have exactly one reviewed row (``missing``);
* every reviewed row's recorded source/dependency digest must match the current
  tree (``stale``);
* every reviewed row must be a real review: ``audit_status == VERIFIED_OK`` with
  non-empty owner/authorization/idempotency/timeout/errors/retry/authority/
  recovery/consumers/evidence fields and at least one existing evidence file
  (``fake_pass``);
* manual surfaces get the same treatment.

The process exits non-zero whenever the audit is not ``complete``; a missing row,
a stale hash, or a fake PASS can never be reported as success.
"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / 'docs/evidence/research-handoff-h4/INTERFACE-REVIEW.json'
REQUIRED = {'owner', 'mode', 'authorization', 'idempotency', 'timeout', 'errors',
            'retry', 'authority', 'recovery', 'consumers', 'evidence', 'source_sha256'}
MANUAL = {'mcp_transport', 'feedback_relay', 'local_publisher', 'hub_http', 'hub_admin_static',
          'durable_objects', 'hub_cron', 'cloudflare_publisher', 'framework_middleware_callbacks'}
HEX64 = set('0123456789abcdef')


def key(entry):
    return tuple(entry.get(k) for k in ('kind', 'file', 'method', 'path', 'handler', 'name'))


def _is_digest(value):
    text = str(value).removeprefix('sha256:')
    return len(text) == 64 and set(text) <= HEX64


def _field_defects(entry):
    defects = []
    for field in sorted(REQUIRED):
        if field not in entry:
            defects.append(f'missing review field: {field}')
            continue
        value = entry[field]
        if isinstance(value, str) and not value.strip():
            defects.append(f'empty review field: {field}')
        elif isinstance(value, list) and not value:
            defects.append(f'empty review field: {field}')
    evidence = entry.get('evidence')
    if isinstance(evidence, list) and not evidence:
        defects.append('fake pass: no evidence recorded')
    return defects


def _hash_defects(entry, root):
    defects = []
    if not _is_digest(entry.get('source_sha256')):
        defects.append('fake pass: source_sha256 is not a sha256 digest')
    hashes = {entry.get('file'): entry.get('source_sha256'), **(entry.get('dependencies_sha256') or {})}
    for relative, expected in hashes.items():
        path = root / str(relative)
        if not path.is_file():
            defects.append(f'source drift: missing file {relative}')
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != str(expected).removeprefix('sha256:'):
            defects.append(f'source drift: {relative}')
    return defects


def evaluate(source_entries, value, root):
    """Pure audit over an explicit source inventory and ledger value."""
    source = {key(entry): entry for entry in source_entries}
    errors, seen, unresolved, fake_pass = [], set(), [], []
    for entry in value.get('entries', []):
        identity = key(entry)
        if identity in seen or identity not in source:
            errors.append({'interface': identity, 'error': 'duplicate or absent source interface'})
        seen.add(identity)
        if entry.get('audit_status') != 'VERIFIED_OK':
            unresolved.append(identity)
        defects = _field_defects(entry) + _hash_defects(entry, root)
        for defect in defects:
            if defect.startswith('fake pass'):
                fake_pass.append(identity)
            errors.append({'interface': identity, 'error': defect})
        for evidence in entry.get('evidence', []):
            if not str(evidence).startswith('https://') and not (root / str(evidence)).is_file():
                errors.append({'interface': identity, 'error': 'missing evidence', 'file': evidence})
    manual, manual_fake = {}, []
    for entry in value.get('manual_surfaces', []):
        name = entry.get('name')
        if name in manual or name not in MANUAL:
            errors.append({'surface': name, 'error': 'duplicate or unknown manual surface'})
        manual[name] = entry
        defects = _field_defects(entry) + _hash_defects(entry, root)
        if 'file' not in entry:
            defects.append('missing manual review field: file')
        for defect in defects:
            if defect.startswith('fake pass'):
                manual_fake.append(name)
            errors.append({'surface': name, 'error': defect})
        for evidence in entry.get('evidence', []):
            if not str(evidence).startswith('https://') and not (root / str(evidence)).is_file():
                errors.append({'surface': name, 'error': 'missing manual evidence file', 'file': evidence})
    manual_pending = sorted(name for name in MANUAL if manual.get(name, {}).get('audit_status') != 'VERIFIED_OK')
    missing = [identity for identity in source if identity not in seen]
    stale = sorted({item['error'].split(': ', 1)[-1] for item in errors if item['error'].startswith('source drift')})
    return {
        'schema_version': 'h4-review-check.v2',
        'discovered': len(source),
        'reviewed': len(seen),
        'verified': len(seen) - len(unresolved),
        'missing': len(missing),
        'unreviewed': len(missing),
        'stale': len(stale),
        'stale_files': stale,
        'fake_pass': len(fake_pass) + len(manual_fake),
        'unresolved': unresolved,
        'manual_pending': manual_pending,
        'errors': errors,
        'complete': not (errors or missing or unresolved or manual_pending),
    }


def audit(root=ROOT, ledger=LEDGER):
    inventory = runpy.run_path(str(root / 'scripts/ci/inventory-reliability.py'))['inventory']()
    value = json.loads(Path(ledger).read_text(encoding='utf-8'))
    return evaluate(inventory, value, root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-complete', action='store_true',
                        help='compatibility flag; the auditor is already fail-closed')
    parser.add_argument('--ledger', default=str(LEDGER))
    parser.add_argument('--root', default=str(ROOT))
    args = parser.parse_args()
    result = audit(Path(args.root), Path(args.ledger))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['complete'] else 1)
