/**
 * D15-2 migration verdict.
 *
 * Pure, dependency-free evaluation of the invariants that the D15-2 harness must
 * fail on. It is deliberately separated from `migration_harness.mjs` so the same
 * logic computes the committed verdict, the live-run verdict and the negative
 * fault-injection controls.
 *
 * Completeness is mandatory: the verdict validates the required fixture set
 * (count + uniqueness + no missing/extra), the required stage set and the
 * required rejection-case set against a single manifest. An empty fixture list,
 * a missing fixture, a duplicate, an unexpected fixture/case, a missing stage or
 * missing required evidence all FAIL — required evidence is never defaulted to an
 * empty/passing value.
 *
 * `legacyStageVerdict` reproduces the older stage-only gate and
 * `preFixV2Verdict` reproduces the pre-fix v2 completeness bug; both exist ONLY
 * so negative controls can prove the contrast and are never used for gating.
 */

export const VERDICT_SCHEMA = 'byq-d15-2-verdict.v3'
export const REQUIREMENTS_SCHEMA = 'byq-d15-2-requirements.v1'

const MESSAGE_EVENT_TYPES = new Set([
  'user/message', 'user', 'message',
  'system/message', 'assistant/message', 'tool/result',
])

const REQUIRED_STAGES = ['read', 'resume', 'append', 'close', 'reopen']
const STAGES = REQUIRED_STAGES

const INVARIANT_KEYS = [
  'manifest_conformance', 'migration_completed', 'stage_states',
  'sequence_continuity', 'id_continuity', 'context_preservation',
  'append_reopen', 'non_downgradable', 'no_blockers',
]

const detail = (id, message) => ({ id, message })
const isPlainObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value)

/**
 * Extract message ids from every released event shape:
 * - `user/message`, `user`, `message`: `data.id`
 * - `assistant/message`, `tool/result`, `system/message`, `message`: `data.message.id`
 * - `agent/inbox/spliced`: `data.inserted[].id`
 *
 * Returns the sorted unique union plus a per-source breakdown so evidence can
 * show which shapes were actually observed.
 */
export function extractMessageIds(rows) {
  const bySource = {}
  const add = (source, id) => {
    if (typeof id !== 'string' || id.length === 0) return
    if (!bySource[source]) bySource[source] = new Set()
    bySource[source].add(id)
  }
  for (const row of rows) {
    const type = row?.type
    const data = row?.data
    if (!data || typeof data !== 'object') continue
    if (MESSAGE_EVENT_TYPES.has(type) && typeof data.id === 'string') add(type, data.id)
    if (data.message && typeof data.message === 'object' && typeof data.message.id === 'string') {
      add(`${type}:messageId`, data.message.id)
    }
    if (type === 'agent/inbox/spliced' && Array.isArray(data.inserted)) {
      for (const message of data.inserted) {
        if (message && typeof message.id === 'string') add('agent/inbox/spliced', message.id)
      }
    }
  }
  const all = [...new Set(Object.values(bySource).flatMap((set) => [...set]))].sort()
  const counts = Object.fromEntries(
    Object.entries(bySource).map(([source, set]) => [source, set.size]).sort(),
  )
  return { all, counts }
}

/**
 * System prompts live in two released shapes: the legacy
 * `request/header.header.system` string and the current `system/message` text
 * blocks the v2->v3 migration emits.
 */
export function systemPrompts(rows) {
  const out = []
  for (const row of rows) {
    if (row?.type === 'request/header' && typeof row.data?.header?.system === 'string'
        && row.data.header.system.length > 0) {
      out.push(row.data.header.system)
    }
    if (row?.type === 'system/message') {
      const content = row.data?.message?.content
      const text = Array.isArray(content)
        ? content.filter((block) => block?.type === 'text').map((block) => block.text).join('')
        : ''
      if (text.length > 0) out.push(text)
    }
  }
  return out
}

export function providerModels(rows) {
  const pairs = []
  for (const row of rows) {
    if (row?.type === 'request/context') pairs.push(`${row.data.provider}/${row.data.model}`)
  }
  return [...new Set(pairs)].sort()
}

/** Extract the D15-2 requirement sets from the single acceptance-matrix manifest. */
export function requirementsFromAcceptanceMatrix(document) {
  const requirements = document?.requirements
  if (!isPlainObject(requirements)) return undefined
  return {
    schema_version: requirements.schema_version,
    source_index: requirements.source_index,
    fixtures: requirements.fixtures,
    stages: requirements.stages,
    fail_closed_cases: requirements.fail_closed_cases,
  }
}

function isMigrated(fixture) {
  return fixture?.migration?.status === 'migrated' || fixture?.migration?.status === 'current'
}

/** Pre-fix verdict: only stage status strings (and the migration blocked count). */
export function legacyStageVerdict(fixtures) {
  const migrated = (fixtures ?? []).filter(isMigrated)
  const allPostMigrationStagesPass = migrated.length > 0
    && migrated.every((fixture) => STAGES.every((stage) => fixture[stage]?.status === 'pass'))
  const blockedCount = (fixtures ?? []).filter((fixture) => fixture?.migration?.status === 'blocked').length
  return {
    all_post_migration_stages_pass: allPostMigrationStagesPass,
    blocked_count: blockedCount,
    legacy_exit_code: allPostMigrationStagesPass && blockedCount === 0 ? 0 : 1,
  }
}

/**
 * Faithful reproduction of the pre-fix v2 verdict, INCLUDING its completeness
 * bug: no required-set validation, empty fixtures pass vacuously, and a single
 * valid rejection case is enough. Never used for gating.
 */
export function preFixV2Verdict(fixtures, failClosed) {
  const list = fixtures ?? []
  const invariantsPass = list.every((fixture) => {
    const evidence = fixture?.evidence ?? {}
    const preservation = evidence.message_id_preservation ?? {}
    const context = evidence.context_preservation ?? {}
    const ids = evidence.ids ?? {}
    const reopen = fixture?.reopen ?? {}
    const append = fixture?.append ?? {}
    const missingContext = [
      ...(context.missing_system_prompts ?? []),
      ...(context.missing_provider_models ?? []),
    ]
    return isMigrated(fixture)
      && evidence.sequence_continuity === true && reopen.sequence_contiguous === true
      && ids.identical === true
      && (preservation.missing_from_target ?? []).length === 0
      && (preservation.missing_from_reopen ?? []).length === 0
      && missingContext.length === 0
      && append.status === 'pass' && reopen.status === 'pass'
      && (append.appended_event_count ?? 0) > 0
      && (preservation.appended_missing_from_reopen ?? []).length === 0
      && fixture?.downgrade?.feasible === false
      && (fixture?.blockers ?? []).length === 0
  })
  const cases = failClosed?.cases ?? []
  const rejectedPass = cases.length > 0 && cases.every((record) => (
    record?.refused === true && record?.documented_refusal === true
    && record?.treated_as_new_session === false && record?.successor_generation_written === false
  ))
  const blockedCount = list.filter((fixture) => fixture?.migration?.status === 'blocked').length
  const allPass = invariantsPass && rejectedPass && blockedCount === 0
  return { all_pass: allPass, exit_code: allPass ? 0 : 1 }
}

function requirementsFailures(requirements) {
  const failures = []
  if (!isPlainObject(requirements)) {
    failures.push(detail('<requirements>', 'missing requirements manifest'))
    return { failures, fixtureIds: null, caseIds: null }
  }
  const { fixtures, stages, fail_closed_cases: caseIds } = requirements
  if (!Array.isArray(fixtures) || fixtures.length === 0) {
    failures.push(detail('<requirements>', 'fixtures must be a non-empty array'))
  } else {
    const seen = new Set()
    for (const id of fixtures) {
      if (typeof id !== 'string' || id.length === 0) failures.push(detail('<requirements>', `invalid fixture id ${JSON.stringify(id)}`))
      else if (seen.has(id)) failures.push(detail('<requirements>', `duplicate required fixture ${id}`))
      else seen.add(id)
    }
  }
  if (!Array.isArray(stages)) {
    failures.push(detail('<requirements>', 'stages must be an array'))
  } else {
    const expected = [...REQUIRED_STAGES].sort().join(',')
    const actual = [...new Set(stages)].sort().join(',')
    if (actual !== expected) failures.push(detail('<requirements>', `stages must be exactly ${expected}, got ${actual}`))
    if (stages.length !== REQUIRED_STAGES.length) failures.push(detail('<requirements>', 'stages must list every required stage exactly once'))
  }
  if (!Array.isArray(caseIds) || caseIds.length === 0) {
    failures.push(detail('<requirements>', 'fail_closed_cases must be a non-empty array'))
  } else {
    const seen = new Set()
    for (const id of caseIds) {
      if (typeof id !== 'string' || id.length === 0) failures.push(detail('<requirements>', `invalid fail-closed case id ${JSON.stringify(id)}`))
      else if (seen.has(id)) failures.push(detail('<requirements>', `duplicate required fail-closed case ${id}`))
      else seen.add(id)
    }
  }
  return {
    failures,
    fixtureIds: Array.isArray(fixtures) ? fixtures : null,
    caseIds: Array.isArray(caseIds) ? caseIds : null,
  }
}

function manifestConformance(fixtures, failClosed, requirements) {
  const failures = []
  if (!Array.isArray(fixtures)) {
    failures.push(detail('<fixtures>', 'fixtures must be an array'))
    return { pass: false, failures }
  }
  const required = requirementsFailures(requirements)
  failures.push(...required.failures)

  const actualIds = fixtures.map((fixture, index) => (
    typeof fixture?.id === 'string' && fixture.id.length > 0 ? fixture.id : `<missing-id-${index}>`
  ))
  const seen = new Set()
  for (const id of actualIds) {
    if (seen.has(id)) failures.push(detail(id, 'duplicate fixture id'))
    else seen.add(id)
  }
  if (required.fixtureIds) {
    const requiredSet = new Set(required.fixtureIds)
    for (const id of required.fixtureIds) {
      if (!seen.has(id)) failures.push(detail(id, 'required fixture missing'))
    }
    for (const id of actualIds) {
      if (!requiredSet.has(id)) failures.push(detail(id, 'unexpected fixture id'))
    }
    if (fixtures.length !== required.fixtureIds.length) {
      failures.push(detail('<fixtures>', `fixture count ${fixtures.length} != required ${required.fixtureIds.length}`))
    }
  }

  const cases = failClosed?.cases
  if (!Array.isArray(cases) || cases.length === 0) {
    failures.push(detail('<fail-closed>', 'fail-closed cases must be a non-empty array'))
  } else {
    const caseIds = cases.map((record, index) => (
      typeof record?.id === 'string' && record.id.length > 0 ? record.id : `<missing-case-id-${index}>`
    ))
    const caseSeen = new Set()
    for (const id of caseIds) {
      if (caseSeen.has(id)) failures.push(detail(id, 'duplicate fail-closed case id'))
      else caseSeen.add(id)
    }
    if (required.caseIds) {
      const requiredSet = new Set(required.caseIds)
      for (const id of required.caseIds) {
        if (!caseSeen.has(id)) failures.push(detail(id, 'required fail-closed case missing'))
      }
      for (const id of caseIds) {
        if (!requiredSet.has(id)) failures.push(detail(id, 'unexpected fail-closed case id'))
      }
      if (cases.length !== required.caseIds.length) {
        failures.push(detail('<fail-closed>', `case count ${cases.length} != required ${required.caseIds.length}`))
      }
    }
  }
  return { pass: failures.length === 0, failures }
}

/**
 * Per-fixture invariant failures. Every required object/array must be present;
 * a missing field is a failure, never an empty-default pass.
 */
function fixtureInvariants(fixture) {
  const id = typeof fixture?.id === 'string' ? fixture.id : '<missing-id>'
  const failures = Object.fromEntries(INVARIANT_KEYS.map((key) => [key, []]))
  const fail = (key, message) => failures[key].push(detail(id, message))

  if (!isPlainObject(fixture?.migration)) fail('migration_completed', 'missing migration object')
  else if (!isMigrated(fixture)) fail('migration_completed', `migration status ${fixture.migration.status}`)

  for (const stage of STAGES) {
    const state = fixture?.[stage]
    if (!isPlainObject(state)) fail('stage_states', `missing stage object ${stage}`)
    else if (state.status !== 'pass') fail('stage_states', `${stage}.status=${state.status}`)
  }

  const evidence = fixture?.evidence
  if (!isPlainObject(evidence)) {
    for (const key of ['sequence_continuity', 'id_continuity', 'context_preservation', 'append_reopen']) {
      fail(key, 'missing evidence object')
    }
  } else {
    if (typeof evidence.sequence_continuity !== 'boolean') fail('sequence_continuity', 'missing boolean evidence.sequence_continuity')
    else if (evidence.sequence_continuity !== true) fail('sequence_continuity', `evidence.sequence_continuity=${evidence.sequence_continuity}`)
    if (!isPlainObject(fixture?.reopen)) fail('sequence_continuity', 'missing reopen object')
    else if (typeof fixture.reopen.sequence_contiguous !== 'boolean') fail('sequence_continuity', 'missing reopen.sequence_contiguous')
    else if (fixture.reopen.sequence_contiguous !== true) fail('sequence_continuity', `reopen.sequence_contiguous=${fixture.reopen.sequence_contiguous}`)

    const ids = evidence.ids
    if (!isPlainObject(ids)) {
      fail('id_continuity', 'missing evidence.ids')
    } else {
      if (typeof ids.identical !== 'boolean') fail('id_continuity', 'missing ids.identical')
      else if (ids.identical !== true) fail('id_continuity', `ids.identical=${ids.identical}`)
      for (const key of ['source_session_id', 'target_session_id', 'reopened_session_id']) {
        if (typeof ids[key] !== 'string' || ids[key].length === 0) fail('id_continuity', `missing ${key}`)
      }
    }
    const preservation = evidence.message_id_preservation
    if (!isPlainObject(preservation)) {
      fail('id_continuity', 'missing evidence.message_id_preservation')
    } else {
      for (const key of ['missing_from_target', 'missing_from_reopen']) {
        if (!Array.isArray(preservation[key])) fail('id_continuity', `missing array ${key}`)
        else if (preservation[key].length > 0) fail('id_continuity', `${key}=${JSON.stringify(preservation[key])}`)
      }
    }

    const context = evidence.context_preservation
    if (!isPlainObject(context)) {
      fail('context_preservation', 'missing evidence.context_preservation')
    } else {
      for (const key of ['source_system_prompts', 'target_system_prompts', 'source_provider_models', 'target_provider_models', 'missing_system_prompts', 'missing_provider_models']) {
        if (!Array.isArray(context[key])) fail('context_preservation', `missing array ${key}`)
      }
      if (Array.isArray(context.source_system_prompts) && context.source_system_prompts.length === 0) {
        fail('context_preservation', 'source_system_prompts is empty')
      }
      if (Array.isArray(context.target_system_prompts) && context.target_system_prompts.length === 0) {
        fail('context_preservation', 'target_system_prompts is empty')
      }
      for (const key of ['missing_system_prompts', 'missing_provider_models']) {
        if (Array.isArray(context[key]) && context[key].length > 0) {
          fail('context_preservation', `${key}=${JSON.stringify(context[key])}`)
        }
      }
    }

    const append = fixture?.append
    if (!isPlainObject(append)) {
      fail('append_reopen', 'missing append object')
    } else {
      if (append.status !== 'pass') fail('append_reopen', `append.status=${append.status}`)
      if (!Number.isInteger(append.appended_event_count) || append.appended_event_count <= 0) {
        fail('append_reopen', 'appended_event_count must be a positive integer')
      }
    }
    if (!isPlainObject(fixture?.reopen)) fail('append_reopen', 'missing reopen object')
    else if (fixture.reopen.status !== 'pass') fail('append_reopen', `reopen.status=${fixture.reopen.status}`)
    if (!isPlainObject(preservation)) fail('append_reopen', 'missing evidence.message_id_preservation')
    else if (!Array.isArray(preservation.appended_missing_from_reopen)) fail('append_reopen', 'missing array appended_missing_from_reopen')
    else if (preservation.appended_missing_from_reopen.length > 0) fail('append_reopen', `appended_missing_from_reopen=${JSON.stringify(preservation.appended_missing_from_reopen)}`)
  }

  const downgrade = fixture?.downgrade
  if (!isPlainObject(downgrade) || typeof downgrade.feasible !== 'boolean') fail('non_downgradable', 'missing downgrade.feasible')
  else if (downgrade.feasible !== false) fail('non_downgradable', `downgrade.feasible=${downgrade.feasible}`)

  if (!Array.isArray(fixture?.blockers)) fail('no_blockers', 'missing blockers array')
  else if (fixture.blockers.length > 0) fail('no_blockers', `blockers=${JSON.stringify(fixture.blockers)}`)

  return failures
}

function failClosedVerdict(failClosed) {
  const cases = failClosed?.cases
  if (!Array.isArray(cases) || cases.length === 0) {
    return { pass: false, case_count: 0, failures: [detail('<fail-closed>', 'missing or empty cases')] }
  }
  const failures = []
  for (const record of cases) {
    if (!isPlainObject(record)) {
      failures.push(detail('<case>', 'case must be an object'))
      continue
    }
    if (typeof record.id !== 'string' || record.id.length === 0) failures.push(detail('<case>', 'case id missing'))
    const ok = record.refused === true && record.documented_refusal === true
      && record.treated_as_new_session === false
      && record.successor_generation_written === false
    if (!ok) {
      failures.push(detail(record.id ?? '<case>', `refused=${record.refused} documented_refusal=${record.documented_refusal} treated_as_new_session=${record.treated_as_new_session} successor_generation_written=${record.successor_generation_written}`))
    }
  }
  return { pass: failures.length === 0, case_count: cases.length, failures }
}

/**
 * Compute the full verdict over the manifest conformance, every required
 * invariant, every required rejection case and every blocker. `all_pass` is the
 * single gate; the caller maps it to the process exit code.
 */
export function computeVerdict(fixtures, failClosed, requirements) {
  const list = Array.isArray(fixtures) ? fixtures : []
  const invariants = {}
  const allFailures = []

  const manifest = manifestConformance(fixtures, failClosed, requirements)
  invariants.manifest_conformance = { pass: manifest.pass, failures: manifest.failures }
  allFailures.push(...manifest.failures)

  for (const key of INVARIANT_KEYS) {
    if (key === 'manifest_conformance') continue
    const failures = []
    for (const fixture of list) failures.push(...fixtureInvariants(fixture)[key])
    invariants[key] = { pass: failures.length === 0, failures }
    allFailures.push(...failures)
  }

  const rejected = failClosedVerdict(failClosed)
  const legacy = legacyStageVerdict(list)
  const invariantsPass = INVARIANT_KEYS.every((key) => invariants[key].pass)
  const blockedCount = list.filter((fixture) => fixture?.migration?.status === 'blocked').length
  const allPass = invariantsPass && rejected.pass && blockedCount === 0
  return {
    schema_version: VERDICT_SCHEMA,
    requirements_schema_version: REQUIREMENTS_SCHEMA,
    all_pass: allPass,
    invariants,
    fail_closed: rejected,
    blockers: allFailures,
    blocked_count: blockedCount,
    fixture_count: list.length,
    legacy_all_post_migration_stages_pass: legacy.all_post_migration_stages_pass,
    legacy_exit_code: legacy.legacy_exit_code,
    exit_code: allPass ? 0 : 1,
  }
}
