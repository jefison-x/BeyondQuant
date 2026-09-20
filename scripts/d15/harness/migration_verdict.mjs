/**
 * D15-2 migration verdict.
 *
 * Pure, dependency-free evaluation of the invariants that the D15-2 harness must
 * fail on. It is deliberately separated from `migration_harness.mjs` so the same
 * logic computes the committed verdict, the live-run verdict and the negative
 * fault-injection controls.
 *
 * The pre-fix harness only checked stage status strings. `legacyStageVerdict`
 * below preserves that exact old logic so negative controls can prove the old
 * code would have reported PASS on a broken invariant.
 */

export const VERDICT_SCHEMA = 'byq-d15-2-verdict.v2'

const MESSAGE_EVENT_TYPES = new Set([
  'user/message', 'user', 'message',
  'system/message', 'assistant/message', 'tool/result',
])

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

function multisetMissing(haystack, needles) {
  const remaining = new Map()
  for (const value of haystack) remaining.set(value, (remaining.get(value) ?? 0) + 1)
  const missing = []
  for (const value of needles) {
    const count = remaining.get(value) ?? 0
    if (count === 0) missing.push(value)
    else if (count === 1) remaining.delete(value)
    else remaining.set(value, count - 1)
  }
  return missing
}

const detail = (id, message) => ({ id, message })

const STAGES = ['read', 'resume', 'append', 'close', 'reopen']

function isMigrated(fixture) {
  return fixture.migration?.status === 'migrated' || fixture.migration?.status === 'current'
}

/** Pre-fix verdict: only stage status strings (and the migration blocked count). */
export function legacyStageVerdict(fixtures) {
  const migrated = fixtures.filter(isMigrated)
  const allPostMigrationStagesPass = migrated.length > 0
    && migrated.every((fixture) => STAGES.every((stage) => fixture[stage]?.status === 'pass'))
  const blockedCount = fixtures.filter((fixture) => fixture.migration?.status === 'blocked').length
  return {
    all_post_migration_stages_pass: allPostMigrationStagesPass,
    blocked_count: blockedCount,
    legacy_exit_code: allPostMigrationStagesPass && blockedCount === 0 ? 0 : 1,
  }
}

function fixtureInvariants(fixture) {
  const id = fixture.id
  const evidence = fixture.evidence ?? {}
  const preservation = evidence.message_id_preservation ?? {}
  const context = evidence.context_preservation ?? {}
  const ids = evidence.ids ?? {}
  const reopen = fixture.reopen ?? {}
  const append = fixture.append ?? {}
  const missingContext = [
    ...(context.missing_system_prompts ?? []),
    ...(context.missing_provider_models ?? []),
  ]
  return {
    migration_completed: {
      pass: isMigrated(fixture),
      failures: isMigrated(fixture) ? [] : [detail(id, `migration status ${fixture.migration?.status}`)],
    },
    sequence_continuity: {
      pass: evidence.sequence_continuity === true && reopen.sequence_contiguous === true,
      failures: (evidence.sequence_continuity === true && reopen.sequence_contiguous === true)
        ? [] : [detail(id, `sequence_continuity=${evidence.sequence_continuity} reopen.sequence_contiguous=${reopen.sequence_contiguous}`)],
    },
    id_continuity: {
      pass: ids.identical === true
        && (preservation.missing_from_target ?? []).length === 0
        && (preservation.missing_from_reopen ?? []).length === 0,
      failures: (ids.identical === true
        && (preservation.missing_from_target ?? []).length === 0
        && (preservation.missing_from_reopen ?? []).length === 0)
        ? [] : [detail(id, `ids.identical=${ids.identical} missing_from_target=${JSON.stringify(preservation.missing_from_target ?? [])} missing_from_reopen=${JSON.stringify(preservation.missing_from_reopen ?? [])}`)],
    },
    context_preservation: {
      pass: missingContext.length === 0,
      failures: missingContext.length === 0 ? [] : [detail(id, `missing context evidence: ${JSON.stringify(missingContext)}`)],
    },
    append_reopen: {
      pass: append.status === 'pass' && reopen.status === 'pass'
        && (append.appended_event_count ?? 0) > 0
        && (preservation.appended_missing_from_reopen ?? []).length === 0,
      failures: (append.status === 'pass' && reopen.status === 'pass'
        && (append.appended_event_count ?? 0) > 0
        && (preservation.appended_missing_from_reopen ?? []).length === 0)
        ? [] : [detail(id, `append=${append.status} reopen=${reopen.status} appended=${append.appended_event_count} appended_missing_from_reopen=${JSON.stringify(preservation.appended_missing_from_reopen ?? [])}`)],
    },
    non_downgradable: {
      pass: fixture.downgrade?.feasible === false,
      failures: fixture.downgrade?.feasible === false ? [] : [detail(id, `downgrade.feasible=${fixture.downgrade?.feasible}`)],
    },
    no_blockers: {
      pass: (fixture.blockers ?? []).length === 0,
      failures: (fixture.blockers ?? []).length === 0 ? [] : [detail(id, `blockers=${JSON.stringify(fixture.blockers)}`)],
    },
  }
}

const INVARIANT_KEYS = [
  'migration_completed', 'sequence_continuity', 'id_continuity',
  'context_preservation', 'append_reopen', 'non_downgradable', 'no_blockers',
]

function failClosedVerdict(failClosed) {
  const cases = failClosed?.cases ?? []
  const failures = []
  for (const record of cases) {
    const ok = record.refused === true && record.documented_refusal === true
      && record.treated_as_new_session === false
      && record.successor_generation_written === false
    if (!ok) {
      failures.push(detail(record.id, `refused=${record.refused} documented_refusal=${record.documented_refusal} treated_as_new_session=${record.treated_as_new_session} successor_generation_written=${record.successor_generation_written}`))
    }
  }
  return {
    pass: cases.length > 0 && failures.length === 0,
    case_count: cases.length,
    failures,
  }
}

/**
 * Compute the full verdict over every required invariant, the rejection cases
 * and every blocker. `all_pass` is the single gate; the caller maps it to the
 * process exit code.
 */
export function computeVerdict(fixtures, failClosed) {
  const invariants = {}
  const allFailures = []
  for (const key of INVARIANT_KEYS) {
    const failures = []
    for (const fixture of fixtures) {
      const evaluated = fixtureInvariants(fixture)[key]
      failures.push(...evaluated.failures)
    }
    invariants[key] = { pass: failures.length === 0, failures }
    allFailures.push(...failures)
  }
  const rejected = failClosedVerdict(failClosed)
  const legacy = legacyStageVerdict(fixtures)
  const invariantsPass = INVARIANT_KEYS.every((key) => invariants[key].pass)
  const blockedCount = fixtures.filter((fixture) => fixture.migration?.status === 'blocked').length
  const allPass = invariantsPass && rejected.pass && blockedCount === 0
  return {
    schema_version: VERDICT_SCHEMA,
    all_pass: allPass,
    invariants,
    fail_closed: rejected,
    blockers: allFailures,
    blocked_count: blockedCount,
    legacy_all_post_migration_stages_pass: legacy.all_post_migration_stages_pass,
    legacy_exit_code: legacy.legacy_exit_code,
    exit_code: allPass ? 0 : 1,
  }
}
