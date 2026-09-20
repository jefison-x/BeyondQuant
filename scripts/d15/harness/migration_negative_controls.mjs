/**
 * D15-2 negative controls.
 *
 * Runs the REAL `migration_harness.mjs` CLI once per injected fault against the
 * committed fixtures and records whether the verdict and process exit code fail
 * closed. For the result-layer faults the legacy stage-only gate still reports
 * PASS, which is the pre-fix behaviour the verdict must no longer exhibit.
 *
 * Usage:
 *   node migration_negative_controls.mjs <fixtures-root> <output.json>
 *
 * Exit code is 0 only when every control behaved exactly as expected.
 */

import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { mkdirSync } from 'node:fs'
import { computeVerdict, legacyStageVerdict, preFixV2Verdict } from './migration_verdict.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const fixturesRoot = process.argv[2]
const outputPath = process.argv[3]
if (!fixturesRoot || !outputPath) {
  console.error('usage: node migration_negative_controls.mjs <fixtures-root> <output.json>')
  process.exit(2)
}

const CONTROLS = [
  {
    fault: '',
    injects: 'none',
    expectation: 'real qualification passes and exits 0',
    expect: { exit_code: 0, all_pass: true, fail_closed_pass: true, failing_invariants: [], blocked_count: 0 },
  },
  {
    fault: 'sequence',
    injects: 'sequence_continuity=false and reopen.sequence_contiguous=false on f-completed',
    expectation: 'sequence invariant fails; legacy stage-only gate would still pass',
    expect: { exit_code: 1, all_pass: false, failing_invariants: ['sequence_continuity'], legacy_exit_code: 0 },
  },
  {
    fault: 'ids',
    injects: 'missing_from_target on f-completed',
    expectation: 'id invariant fails; legacy stage-only gate would still pass',
    expect: { exit_code: 1, all_pass: false, failing_invariants: ['id_continuity'], legacy_exit_code: 0 },
  },
  {
    fault: 'context',
    injects: 'missing_system_prompts on f-completed',
    expectation: 'context invariant fails; legacy stage-only gate would still pass',
    expect: { exit_code: 1, all_pass: false, failing_invariants: ['context_preservation'], legacy_exit_code: 0 },
  },
  {
    fault: 'reopen',
    injects: 'appended_missing_from_reopen on f-completed',
    expectation: 'append/reopen invariant fails; legacy stage-only gate would still pass',
    expect: { exit_code: 1, all_pass: false, failing_invariants: ['append_reopen'], legacy_exit_code: 0 },
  },
  {
    fault: 'blockers',
    injects: 'an extra non-migration blocker on f-completed',
    expectation: 'no-blockers invariant fails; legacy stage-only exit ignores it and would pass',
    expect: { exit_code: 1, all_pass: false, failing_invariants: ['no_blockers'], legacy_exit_code: 0, blocked_count: 0 },
  },
  {
    fault: 'fail_closed',
    injects: 'documented_refusal=false on the first rejection case',
    expectation: 'rejection-case verdict fails; the pre-fix exit code ignored fail-closed entirely',
    expect: { exit_code: 1, all_pass: false, fail_closed_pass: false, failing_invariants: [], legacy_exit_code: 0 },
  },
  {
    fault: 'blocked_migration',
    injects: 'a real unclassified event into the f-completed source store',
    expectation: 'the real pipeline blocks the migration and the gate fails',
    expect: { exit_code: 1, all_pass: false, failing_invariants_includes: ['migration_completed', 'no_blockers'], blocked_count: 1, legacy_exit_code: 1 },
  },
  {
    fault: 'empty_fixtures',
    injects: 'zero fixtures collected',
    expectation: 'manifest conformance fails on an empty required fixture set',
    expect: { exit_code: 1, all_pass: false, failing_invariants: ['manifest_conformance'], blocked_count: 0, legacy_exit_code: 1 },
  },
  {
    fault: 'drop_fixture',
    injects: 'remove the required f-completed fixture',
    expectation: 'manifest conformance fails on a missing required fixture; legacy stage-only gate would pass',
    expect: { exit_code: 1, all_pass: false, failing_invariants: ['manifest_conformance'], legacy_exit_code: 0 },
  },
  {
    fault: 'duplicate_fixture',
    injects: 'duplicate f-normal',
    expectation: 'manifest conformance fails on a duplicate fixture',
    expect: { exit_code: 1, all_pass: false, failing_invariants: ['manifest_conformance'], legacy_exit_code: 0 },
  },
  {
    fault: 'extra_fixture',
    injects: 'append an unexpected f-unexpected fixture',
    expectation: 'manifest conformance fails on an unexpected fixture',
    expect: { exit_code: 1, all_pass: false, failing_invariants_includes: ['manifest_conformance'], legacy_exit_code: 1 },
  },
  {
    fault: 'drop_fail_closed',
    injects: 'remove one required rejection case',
    expectation: 'manifest conformance fails on a missing required rejection case; legacy stage-only gate would pass',
    expect: { exit_code: 1, all_pass: false, failing_invariants: ['manifest_conformance'], legacy_exit_code: 0 },
  },
  {
    fault: 'extra_fail_closed',
    injects: 'append an unexpected rejection case',
    expectation: 'manifest conformance fails on an unexpected rejection case; legacy stage-only gate would pass',
    expect: { exit_code: 1, all_pass: false, failing_invariants: ['manifest_conformance'], legacy_exit_code: 0 },
  },
  {
    fault: 'missing_evidence',
    injects: 'delete message_id_preservation from f-completed evidence',
    expectation: 'missing required evidence fails id/append instead of defaulting to pass; legacy stage-only gate would pass',
    expect: { exit_code: 1, all_pass: false, failing_invariants: ['id_continuity', 'append_reopen'], legacy_exit_code: 0 },
  },
  {
    fault: 'stage_failure',
    injects: "set f-completed.append.status='fail' while leaving other evidence intact",
    expectation: 'the explicit stage-state check fails',
    expect: { exit_code: 1, all_pass: false, failing_invariants_includes: ['stage_states'], legacy_exit_code: 1 },
  },
  {
    fault: 'requirements_missing',
    injects: 'evaluate without the required-set manifest',
    expectation: 'manifest conformance fails when the requirements manifest is absent; legacy stage-only gate would pass',
    expect: { exit_code: 1, all_pass: false, failing_invariants: ['manifest_conformance'], legacy_exit_code: 0 },
  },
]

function runControl(fault) {
  const dir = mkdtempSync(join(tmpdir(), `byq-d15-2-negative-${fault || 'default'}-`))
  const resultsPath = join(dir, 'results.json')
  const failClosedPath = join(dir, 'fail-closed.json')
  const verdictPath = join(dir, 'verdict.json')
  try {
    const completed = spawnSync(
      process.execPath,
      ['migration_harness.mjs', fixturesRoot, resultsPath, failClosedPath, verdictPath],
      { cwd: HERE, env: { ...process.env, BYQ_D15_2_FAULT: fault }, encoding: 'utf8', timeout: 600_000 },
    )
    if (completed.error) throw completed.error
    const verdictDocument = JSON.parse(readFileSync(verdictPath, 'utf8'))
    const verdict = verdictDocument.verdict
    const failingInvariants = Object.entries(verdict.invariants)
      .filter(([, value]) => !value.pass)
      .map(([key]) => key)
    return {
      exit_code: completed.status,
      all_pass: verdict.all_pass,
      fail_closed_pass: verdict.fail_closed.pass,
      failing_invariants: failingInvariants,
      blocked_count: verdict.blocked_count,
      legacy_all_post_migration_stages_pass: verdict.legacy_all_post_migration_stages_pass,
      legacy_exit_code: verdict.legacy_exit_code,
      verdict,
    }
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

const controls = []
let ok = true
for (const control of CONTROLS) {
  const observed = runControl(control.fault)
  const failures = []
  for (const [key, expected] of Object.entries(control.expect)) {
    if (key === 'failing_invariants_includes') {
      const missing = expected.filter((value) => !observed.failing_invariants.includes(value))
      if (missing.length > 0) failures.push({ key, expected, actual: observed.failing_invariants })
      continue
    }
    const actual = observed[key]
    const matches = Array.isArray(expected)
      ? JSON.stringify(actual) === JSON.stringify(expected)
      : actual === expected
    if (!matches) failures.push({ key, expected, actual })
  }
  if (failures.length > 0) ok = false
  controls.push({
    fault: control.fault || null,
    injects: control.injects,
    expectation: control.expectation,
    expected: control.expect,
    observed: {
      exit_code: observed.exit_code,
      all_pass: observed.all_pass,
      fail_closed_pass: observed.fail_closed_pass,
      failing_invariants: observed.failing_invariants,
      blocked_count: observed.blocked_count,
      legacy_all_post_migration_stages_pass: observed.legacy_all_post_migration_stages_pass,
      legacy_exit_code: observed.legacy_exit_code,
    },
    failures,
    control_pass: failures.length === 0,
  })
}

// Direct function-level repro from the review: zero fixtures plus a single valid
// rejection case. The pre-fix v2 verdict passed; the fixed verdict must fail.
const oneCase = {
  id: 'one-only', refused: true, documented_refusal: true,
  treated_as_new_session: false, successor_generation_written: false,
}
const reproPreFix = preFixV2Verdict([], { cases: [oneCase] })
const reproPostFix = computeVerdict([], { cases: [oneCase] })
const reproLegacy = legacyStageVerdict([])
const repro = {
  input: 'computeVerdict([], {cases:[one-only valid refusal]})',
  pre_fix_observed: { all_pass: reproPreFix.all_pass, exit_code: reproPreFix.exit_code },
  post_fix_observed: {
    all_pass: reproPostFix.all_pass,
    exit_code: reproPostFix.exit_code,
    failing_invariants: Object.entries(reproPostFix.invariants)
      .filter(([, value]) => !value.pass)
      .map(([key]) => key),
  },
  legacy_exit_code: reproLegacy.legacy_exit_code,
  repro_fixed: reproPreFix.all_pass === true && reproPostFix.all_pass === false,
}
if (!repro.repro_fixed) ok = false

const document = {
  schema_version: 'byq-d15-2-negative-controls.v3',
  generated_at: new Date().toISOString(),
  harness: 'scripts/d15/harness/migration_harness.mjs (BYQ_D15_2_FAULT)',
  note: 'Every control invokes the real harness CLI and observes its process exit code and verdict.v3. Result-layer faults leave all stage statuses passing, so the recorded legacy_exit_code=0 proves the pre-fix gate would have reported PASS on a broken invariant. The completeness controls (empty/drop/duplicate/extra/missing-evidence/requirements-missing) prove the manifest-driven required-set gate fails.',
  repro,
  all_controls_pass: ok,
  controls,
}
mkdirSync(dirname(outputPath), { recursive: true })
writeFileSync(outputPath, `${JSON.stringify(document, null, 2)}\n`, 'utf8')
console.log(JSON.stringify({ all_controls_pass: ok, control_count: controls.length, repro_fixed: repro.repro_fixed, failing_controls: controls.filter((c) => !c.control_pass).map((c) => c.fault) }, null, 2))
process.exit(ok ? 0 : 1)
