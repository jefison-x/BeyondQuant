#!/usr/bin/env python3
"""Validate evidence references and report incomplete H4 review without inventing PASS."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = {'owner','mode','authorization','idempotency','timeout','errors','retry','authority','recovery','consumers','evidence','source_sha256'}
MANUAL = {'mcp_transport','feedback_relay','local_publisher','hub_http','hub_admin_static','durable_objects','hub_cron','cloudflare_publisher','framework_middleware_callbacks'}


def key(entry):
    return tuple(entry.get(k) for k in ('kind','file','method','path','handler','name'))


def audit():
    inventory = runpy.run_path(str(ROOT/'scripts/ci/inventory-reliability.py'))['inventory']()
    source = {key(e):e for e in inventory}
    value = json.loads((ROOT/'docs/evidence/research-handoff-h4/INTERFACE-REVIEW.json').read_text())
    errors, seen, unresolved = [], set(), []
    for entry in value['entries']:
        identity = key(entry)
        if identity in seen or identity not in source:
            errors.append({'interface':identity,'error':'duplicate or absent source interface'})
        seen.add(identity)
        if REQUIRED-set(entry):errors.append({'interface':identity,'error':'missing review fields'})
        if entry.get('audit_status')!='VERIFIED_OK':unresolved.append(identity)
        hashes = {entry['file']:entry.get('source_sha256'),**entry.get('dependencies_sha256',{})}
        for relative, expected in hashes.items():
            path=ROOT/relative
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=str(expected).removeprefix('sha256:'):
                errors.append({'interface':identity,'error':'source drift','file':relative})
        for evidence in entry.get('evidence',[]):
            if not evidence.startswith('https://') and not (ROOT/evidence).is_file():
                errors.append({'interface':identity,'error':'missing evidence','file':evidence})
    manual={}
    for entry in value.get('manual_surfaces',[]):
        name=entry.get('name')
        if name in manual or name not in MANUAL:errors.append({'surface':name,'error':'duplicate or unknown manual surface'})
        manual[name]=entry
        if (REQUIRED|{'file'})-set(entry):
            errors.append({'surface':name,'error':'missing manual review fields'})
            continue
        path=ROOT/entry['file']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=entry['source_sha256']:
            errors.append({'surface':name,'error':'manual source drift'})
        if not entry['evidence']:errors.append({'surface':name,'error':'missing manual evidence'})
        for evidence in entry['evidence']:
            if not evidence.startswith('https://') and not (ROOT/evidence).is_file():
                errors.append({'surface':name,'error':'missing manual evidence file','file':evidence})
    manual_pending=sorted(name for name in MANUAL if manual.get(name,{}).get('audit_status')!='VERIFIED_OK')
    missing=[identity for identity in source if identity not in seen]
    return {'schema_version':'h4-review-check.v1','discovered':len(source),'reviewed':len(seen),
            'verified':len(seen)-len(unresolved),'unreviewed':len(missing),'unresolved':unresolved,
            'manual_pending':manual_pending,'errors':errors,
            'complete':not(errors or missing or unresolved or manual_pending)}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--require-complete',action='store_true');args=parser.parse_args()
    result=audit();print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(1 if result['errors'] or (args.require_complete and not result['complete']) else 0)
