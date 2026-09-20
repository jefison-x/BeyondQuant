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

const document = {
  schema_version: 'byq-d15-2-negative-controls.v2',
  generated_at: new Date().toISOString(),
  harness: 'scripts/d15/harness/migration_harness.mjs (BYQ_D15_2_FAULT)',
  note: 'Every control invokes the real harness CLI and observes its process exit code and verdict.v2. Result-layer faults leave all stage statuses passing, so the recorded legacy_exit_code=0 proves the pre-fix gate would have reported PASS on a broken invariant.',
  all_controls_pass: ok,
  controls,
}
mkdirSync(dirname(outputPath), { recursive: true })
writeFileSync(outputPath, `${JSON.stringify(document, null, 2)}\n`, 'utf8')
console.log(JSON.stringify({ all_controls_pass: ok, control_count: controls.length, failing_controls: controls.filter((c) => !c.control_pass).map((c) => c.fault) }, null, 2))
process.exit(ok ? 0 : 1)
