#!/usr/bin/env python3
"""Deterministic U7 deployment projections from exact U6 qualification.

This does not certify new U7 images or deploy anything. Historical descriptors,
profiles and qualification reports remain unchanged; final-image gates still run.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'docs/evidence/dsh-012rc1/u6/report-release-ready/qualification-report.json'
REPORT_SHA256 = 'e2460bdff7c1b3d2bb0de3cffa22a0cf6e22df117774f4fbac691220f84a3c16'
TARGET = 'dsh-0.1.2rc1'
BASELINE = 'dsh-0.1.1rc1'


def digest(path):
    return 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()


def validate_report(report):
    if (report.get('schema_version') != 'dsh-qualification-report.v2'
            or report.get('qualification_state') != 'QUALIFIED'
            or report.get('qualification_scope') != 'release-ready'
            or report.get('release_id') != TARGET
            or report.get('baseline_release_id') != BASELINE):
        raise ValueError('exact build-bound U6 readiness required')
    checks = report.get('checks', [])
    if (len(checks) != 40 or [c.get('id') for c in checks] != [f'T{i:02}' for i in range(1,41)]
            or any(c.get('result') != 'PASS' for c in checks[:39])
            or checks[39].get('result') != 'NOT_RUN'):
        raise ValueError('U6 rehearsal not qualified; production observation cannot be inferred')
    for role, release in (('baseline', BASELINE), ('candidate', TARGET)):
        ref = report.get('build_revisions', {}).get(role, {})
        if ref.get('build_id') != release + '-u6.3':
            raise ValueError('unexpected qualified build reference')
        manifest = ROOT / 'config/dsh/builds' / (ref['build_id'] + '.json')
        value = json.loads(manifest.read_text())
        if (digest(manifest) != ref.get('manifest_hash') or value['release_id'] != release
                or value['release_descriptor_hash'] != digest(ROOT / 'config/dsh/releases' / (release + '.json'))):
            raise ValueError('archived qualification manifest/release hash mismatch')
    if report['build_revisions']['candidate']['image_digest'] != report.get('image_digest'):
        raise ValueError('qualification image binding mismatch')


def projections():
    if digest(REPORT) != 'sha256:' + REPORT_SHA256:
        raise ValueError('frozen qualification report changed')
    report = json.loads(REPORT.read_text())
    validate_report(report)
    release = json.loads((ROOT / 'config/dsh/releases' / (TARGET + '.json')).read_text())
    registry = json.loads((ROOT / 'plugins/dsh-byq/registry/plugins.json').read_text())
    registry['runtime_baseline'] = {'python_sdk': '0.1.2rc1', 'runtime_bin': '0.1.2rc1',
                                  'npm_runtime': '0.1.2-rc.1', 'upstream_latest_observed': '0.1.2-rc.1',
                                  'observed_at': '2026-09-06'}
    for plugin in registry['plugins']:
        enabled = plugin['id'] in {'compaction', 'guard', 'web-search'}
        plugin['source'] = {'kind': 'official_python_bundle', 'publisher': 'deepseek-ai'}
        # Report the actual carrier package, not invented npm per-package hashes.
        plugin['packages'] = [{'name': 'deepseek-harness-runtime-bin', 'version': '0.1.2rc1',
                               'integrity': 'sha256:' + release['python']['linux_x86_64_runtime_wheel_sha256']}]
        plugin['compatibility'] = {'dsh_runtime': '0.1.2-rc.1', 'python_sdk': '0.1.2rc1',
                                   'runtime_bin': '0.1.2rc1', 'status': 'COMPATIBLE' if enabled else 'BLOCKED_BY_SECURITY_BOUNDARY'}
        qualification = plugin['qualification']
        qualification.update(state='QUALIFIED' if enabled else 'BLOCKED',
                             qualified_at=report['finished_at'] if enabled else None,
                             evidence=[str(REPORT.relative_to(ROOT))],
                             reason='U6 exact bundled carrier: real capability/lifecycle/MCP and release rehearsal verified.' if enabled
                             else 'Not qualified or enabled in the approved Product profile; no new capability granted.')
        plugin['composition'] = {'entries': []}  # Runtime uses the immutable qualified SDK patch.
    policy = json.loads((ROOT / 'config/dsh/generated/dsh-0.1.2rc1.web-evidence-provenance.json').read_text())
    policy['mode'] = 'qualified'
    qualified = copy.deepcopy(policy['active_producer'])
    qualified['qualification_state'] = 'QUALIFIED'
    qualified['attestation_sha256'] = 'sha256:' + hashlib.sha256(
        (qualified['attestation_sha256'] + ':' + REPORT_SHA256).encode()).hexdigest()
    policy['active_producer'] = qualified
    policy['recognized_producers'] = [p for p in policy['recognized_producers'] if p['release_id'] != TARGET] + [qualified]
    return registry, policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('generate', 'check'))
    args = parser.parse_args()
    registry, policy = projections()
    rollback = copy.deepcopy(policy)
    rollback['active_producer'] = next(p for p in rollback['recognized_producers'] if p['release_id'] == BASELINE)
    for name, value in (('product-plugin-registry.json', registry), ('qualified-web-evidence-provenance.json', policy),
                        ('qualified-rollback-web-evidence-provenance.json', rollback)):
        path = ROOT / 'config/dsh/generated' / name
        expected = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
        if args.action == 'generate':
            path.write_text(expected)
        elif not path.is_file() or path.read_text() != expected:
            raise ValueError('stale promotion projection: ' + name)
    print(json.dumps({'status': 'PASS', 'deployment_performed': False, 'new_image_qualification': 'NOT_IMPLIED'}))


if __name__ == '__main__':
    main()
