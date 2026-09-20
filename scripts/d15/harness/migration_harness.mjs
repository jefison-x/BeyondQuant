/**
 * D15-2 Session V3 migration qualification harness.
 *
 * For every committed fixture this harness copies the immutable original to a
 * scratch directory (never mutating the original), runs the real DSH
 * 0.1.5-rc.1 migration path (`sessionFormatCatalog` -> `sessionFormatV2ToV3`),
 * then exercises read -> resume -> append -> close -> reopen and records the
 * result as machine-readable JSON. A migration failure is never converted into
 * a fresh session: it is recorded as a blocker and no successor log is written.
 *
 * Usage:
 *   node migration_harness.mjs <fixtures-root> <results.json> [fail-closed.json] [verdict.json]
 *
 * The process exits non-zero unless EVERY qualified invariant, every rejection
 * case and every blocker passes (see `migration_verdict.mjs`). `BYQ_D15_2_FAULT`
 * is a test-only negative control used by `migration_negative_controls.mjs`.
 *
 * The harness is deterministic apart from one generated-at timestamp and the
 * scratch directory names, neither of which enters any per-fixture assertion.
 */

import { createHash } from 'node:crypto'
import { mkdtemp, mkdir, readFile, rm, writeFile, open } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { sessionFormatCatalog } from '@deepseek-ai/dsh-session-format-catalog'
import { createSessionFormatChain } from '@deepseek-ai/dsh-session-format'
import { sessionFormatV0ToV1 } from '@deepseek-ai/dsh-session-format-v0-to-v1'
import { releasedV2SessionFormatCodec, sessionFormatV1ToV2 } from '@deepseek-ai/dsh-session-format-v1-to-v2'
import { Session, SessionId, SessionLogOffset } from '@deepseek-ai/dsh-session'
import {
  computeVerdict, extractMessageIds, providerModels, systemPrompts,
} from './migration_verdict.mjs'

const fixturesRoot = process.argv[2]
const resultsPath = process.argv[3]
const failClosedPath = process.argv[4]
const verdictPath = process.argv[5]
// Test-only negative control. The default (empty) path is the real qualification.
const FAULT = process.env.BYQ_D15_2_FAULT ?? ''
if (!fixturesRoot || !resultsPath) {
  console.error('usage: node migration_harness.mjs <fixtures-root> <results.json> [fail-closed.json] [verdict.json]')
  process.exit(2)
}

const TARGET = {
  release_id: 'dsh-0.1.5rc1',
  python_sdk: '0.1.5rc1',
  python_runtime_bin: '0.1.5rc1',
  bundled_npm_version: '0.1.5-rc.1',
  source_tag: 'dsh-v0.1.5-rc.1',
  source_commit: '183f08e9c6dde7e36cd2318eaee70b0da08fb35e',
}

const PACKAGE_VERSIONS = {
  '@deepseek-ai/dsh-session': '0.1.5-rc.1',
  '@deepseek-ai/dsh-session-format': '0.1.5-rc.1',
  '@deepseek-ai/dsh-session-format-catalog': '0.1.5-rc.1',
  '@deepseek-ai/dsh-session-format-v0-to-v1': '0.1.5-rc.1',
  '@deepseek-ai/dsh-session-format-v1-to-v2': '0.1.5-rc.1',
  '@deepseek-ai/dsh-session-format-v2-to-v3': '0.1.5-rc.1',
}

const CATEGORY = {
  'f-normal': 'normal',
  'f-completed': 'completed',
  'f-interrupted': 'interrupted',
  'f-compacted': 'compacted',
  'f-large': 'large',
  'f-subagent': 'subagent',
  'f-continuable': 'continuable-subagent',
  'f-forked': 'forked',
  'f-old-lifecycle': 'with-old-lifecycle-evidence',
}

const FIXTURE_ORDER = [
  'f-normal', 'f-completed', 'f-interrupted', 'f-compacted', 'f-large',
  'f-subagent', 'f-continuable', 'f-forked', 'f-old-lifecycle',
]

const sha256 = (value) => createHash('sha256').update(value).digest('hex')
const parseRows = (text) => text.split('\n').filter(Boolean).map((line) => JSON.parse(line))
const serializeRows = (rows) => `${rows.map((row) => JSON.stringify(row)).join('\n')}\n`

function lastSeq(rows) {
  const seqs = rows.map((row) => row.seq).filter((seq) => Number.isInteger(seq))
  return seqs.length === 0 ? -1 : Math.max(...seqs)
}

function openTurn(events) {
  const starts = events.filter((event) => event.type === 'turn/start' && Number.isInteger(event.data?.turn)).map((event) => event.data.turn)
  const ends = new Set(events.filter((event) => event.type === 'turn/end').map((event) => event.data?.turn))
  const open = starts.filter((turn) => !ends.has(turn))
  return open.length === 0 ? undefined : Math.max(...open)
}

function buildAppend(events) {
  const turns = events.filter((event) => event.type === 'turn/start').map((event) => event.data.turn)
  const nextTurn = turns.length === 0 ? 1 : Math.max(...turns) + 1
  const unresolvedCalls = () => {
    const settled = new Set(events
      .filter((event) => event.type === 'tool/result')
      .map((event) => event.data?.message?.source?.callId))
    return events
      .filter((event) => event.type === 'tool/call' && !settled.has(event.data?.callId))
      .map((event) => ({ callId: event.data.callId, turn: event.data.turn, step: event.data.step }))
  }
  const appended = []
  const open = openTurn(events)
  if (open !== undefined) {
    for (const call of unresolvedCalls()) {
      const repairSeq = lastSeq(events) + appended.length + 1
      appended.push({
        type: 'tool/result',
        data: {
          turn: call.turn, step: call.step,
          error: { name: 'ToolNotStartedError', code: 'TOOL_NOT_STARTED' },
          message: {
            id: `interrupted-tool-result-${call.callId}-${repairSeq}`,
            role: 'user',
            source: { kind: 'tool', callId: call.callId },
            content: [{
              type: 'tool-result', toolCallId: call.callId, isError: true,
              content: [{ type: 'text', text: 'The tool call was interrupted before the Harness recorded it as started.' }],
            }],
          },
        },
        surfaceOp: 'append',
      })
    }
    appended.push({ type: 'step/end', data: { turn: open, step: 1 } })
    appended.push({ type: 'turn/end', data: { turn: open, reason: { kind: 'interrupted' } } })
  }
  appended.push({ type: 'turn/start', data: { turn: nextTurn } })
  appended.push({ type: 'step/start', data: { turn: nextTurn, step: 1 } })
  appended.push({
    type: 'user/message',
    data: { role: 'user', id: `d15-2-append-u-${nextTurn}`, source: { kind: 'user' }, content: [{ type: 'text', text: 'D15-2 append qualification probe' }] },
    surfaceOp: 'append',
  })
  appended.push({ type: 'request/header', data: { header: { config: { provider: 'deepseek-official', model: 'deepseek-v4-flash' } }, reason: 'initial' } })
  appended.push({
    type: 'assistant/message',
    data: {
      turn: nextTurn, step: 1,
      message: {
        id: `d15-2-append-a-${nextTurn}`, role: 'assistant',
        source: { kind: 'model', provider: 'deepseek-official', model: 'deepseek-v4-flash' },
        content: [{ type: 'text', text: 'D15-2 append qualification ack' }],
      },
      stream: [],
    },
    surfaceOp: 'append',
  })
  appended.push({ type: 'step/end', data: { turn: nextTurn, step: 1 } })
  appended.push({ type: 'turn/end', data: { turn: nextTurn, reason: { kind: 'completed' } } })
  let seq = lastSeq(events) + 1
  const time = events.length === 0 ? 1_789_831_300_000 : Math.max(...events.map((event) => event.time ?? 0)) + 1
  return appended.map((event, index) => ({ ...event, seq: seq++, time: time + index }))
}

function restore(rows, { strict = true } = {}) {
  const read = sessionFormatCatalog.readHeader(rows[0])
  const re = sessionFormatCatalog.createRestore(rows[0], { recovery: strict ? 'strict' : 'lenient', validation: 'current' })
  for (const row of rows.slice(1)) re.decodeRow(row)
  return { read, artifact: re.finish() }
}

async function writeAndSync(path, text) {
  const handle = await open(path, 'w')
  try {
    await handle.writeFile(text, 'utf8')
    await handle.sync()
  } finally {
    await handle.close()
  }
}

/**
 * Test-only fault injection. It runs the real pipeline and then perturbs exactly
 * one observed invariant (or the wrapped source for a real blocked migration) so
 * the negative controls can prove the verdict and exit code fail closed. It is
 * enabled only through BYQ_D15_2_FAULT and never used by the committed run.
 */
function applyFixtureFault(result) {
  if (!FAULT || result.id !== 'f-completed') return result
  switch (FAULT) {
    case 'sequence':
      result.evidence.sequence_continuity = false
      result.reopen.sequence_contiguous = false
      break
    case 'ids':
      result.evidence.message_id_preservation.missing_from_target = ['d15-2-negative-missing-id']
      break
    case 'context':
      result.evidence.context_preservation.missing_system_prompts = ['d15-2-negative-missing-system-prompt']
      break
    case 'reopen':
      result.evidence.message_id_preservation.appended_missing_from_reopen = ['d15-2-negative-appended-id']
      break
    case 'blockers':
      result.blockers.push({ stage: 'negative-control', message: 'D15-2 negative control injected blocker' })
      break
    default:
      break
  }
  return result
}

async function migrateFixture(id, scratchRoot) {
  const sourcePath = join(fixturesRoot, id, 'session.jsonl')
  const original = await readFile(sourcePath)
  const sourceText = original.toString('utf8')
  const sourceRows = parseRows(sourceText)
  if (FAULT === 'blocked_migration' && id === 'f-completed') {
    sourceRows.push({ type: 'totally/unknown-event', seq: lastSeq(sourceRows) + 1, time: 1, data: { negative: true } })
  }

  const workDir = await mkdtemp(join(scratchRoot, `${id}-`))
  const workingSource = join(workDir, 'source.session.jsonl')
  await writeAndSync(workingSource, sourceText)
  const workingHash = sha256(await readFile(workingSource))

  const result = {
    id,
    category: CATEGORY[id],
    source: {
      path: `docs/evidence/d15/fixtures/sessions/${id}/session.jsonl`,
      sha256: sha256(original),
      bytes: original.length,
      rows: sourceRows.length,
      stored_format_version: sourceRows[0].version,
    },
    migration: { attempted: true, status: 'blocked', from_version: sourceRows[0].version, to_version: 3, error_name: null, error_message: null },
    read: { status: 'not-run' },
    resume: { status: 'not-run' },
    append: { status: 'not-run' },
    close: { status: 'not-run' },
    reopen: { status: 'not-run' },
    evidence: {},
    downgrade: { feasible: null, reason: null },
    blockers: [],
  }

  let artifact
  try {
    const { read, artifact: migrated } = restore(sourceRows)
    artifact = migrated
    result.read = {
      status: 'pass',
      catalog_status: read.status,
      stored_version: read.status === 'current' ? 3 : read.storedVersion,
      target_version: read.targetVersion,
      header_id: read.header.id,
    }
    result.migration.status = read.status === 'current' ? 'current' : 'migrated'
    result.migration.from_version = result.read.stored_version
    result.migration.event_count_source = sourceRows.length - 1
    result.migration.event_count_target = migrated.events.length
  } catch (error) {
    result.migration.status = 'blocked'
    result.migration.error_name = error?.name ?? 'Error'
    result.migration.error_message = String(error?.message ?? error).slice(0, 600)
    result.blockers.push({ stage: 'migration', error_name: result.migration.error_name, message: result.migration.error_message })
    return result
  }

  try {
    const session = Session.fromRestore(
      SessionId(artifact.header.id), artifact.events, artifact.header,
      SessionLogOffset(artifact.inheritedEventCount), 'detached',
    )
    result.resume = {
      status: 'pass',
      session_id: String(session.id),
      event_count: artifact.events.length,
      inherited_event_count: artifact.inheritedEventCount,
    }
  } catch (error) {
    result.resume = { status: 'fail', error_name: error?.name ?? 'Error', message: String(error?.message ?? error).slice(0, 600) }
    result.blockers.push({ stage: 'resume', error_name: result.resume.error_name, message: result.resume.message })
    return result
  }

  let appended
  try {
    appended = buildAppend(artifact.events)
    for (const event of appended) sessionFormatCatalog.encodeCurrentEvent(event)
    result.append = {
      status: 'pass',
      appended_event_count: appended.length,
      appended_event_types: appended.map((event) => event.type),
      first_appended_seq: appended[0]?.seq,
      last_appended_seq: appended[appended.length - 1]?.seq,
      closed_open_turn: openTurn(artifact.events) ?? null,
    }
  } catch (error) {
    result.append = { status: 'fail', error_name: error?.name ?? 'Error', message: String(error?.message ?? error).slice(0, 600) }
    result.blockers.push({ stage: 'append', error_name: result.append.error_name, message: result.append.message })
    return result
  }

  const closePath = join(workDir, 'session.v3.jsonl')
  let closedRows
  try {
    const headerRow = sessionFormatCatalog.encodeCurrentHeader(artifact.header, artifact.inheritedEventCount)
    const eventRows = [...artifact.events, ...appended].map((event) => sessionFormatCatalog.encodeCurrentEvent(event))
    closedRows = [headerRow, ...eventRows]
    const text = serializeRows(closedRows)
    await writeAndSync(closePath, text)
    result.close = {
      status: 'pass',
      file: 'session.v3.jsonl',
      bytes: Buffer.byteLength(text, 'utf8'),
      sha256: sha256(text),
      row_count: closedRows.length,
      flushed: true,
    }
  } catch (error) {
    result.close = { status: 'fail', error_name: error?.name ?? 'Error', message: String(error?.message ?? error).slice(0, 600) }
    result.blockers.push({ stage: 'close', error_name: result.close.error_name, message: result.close.message })
    return result
  }

  try {
    const reopenedRows = parseRows(await readFile(closePath, 'utf8'))
    const { read, artifact: reopened } = restore(reopenedRows)
    const seqs = reopened.events.map((event) => event.seq)
    const contiguous = seqs.every((seq, index) => seq === index)
    const expected = extractMessageIds([...artifact.events, ...appended])
    const reopenedIds = extractMessageIds(reopened.events)
    const sourceIds = extractMessageIds(sourceRows)
    const targetIds = extractMessageIds(artifact.events)
    const appendedIds = extractMessageIds(appended)
    const reopenedSet = new Set(reopenedIds.all)
    const targetSet = new Set(targetIds.all)
    const missingFromReopen = expected.all.filter((value) => !reopenedSet.has(value))
    const missingFromTarget = sourceIds.all.filter((value) => !targetSet.has(value))
    const appendedMissingFromReopen = appendedIds.all.filter((value) => !reopenedSet.has(value))
    const sourcePrompts = systemPrompts(sourceRows)
    const targetPrompts = systemPrompts(artifact.events)
    const targetPromptSet = new Set(targetPrompts)
    const sourceModels = providerModels(sourceRows)
    const targetModelSet = new Set(providerModels(artifact.events))
    result.reopen = {
      status: 'pass',
      catalog_status: read.status,
      stored_version: read.status === 'current' ? 3 : read.storedVersion,
      header_id: read.header.id,
      event_count: reopened.events.length,
      sequence_contiguous: contiguous,
      first_seq: seqs[0],
      last_seq: seqs[seqs.length - 1],
    }
    result.evidence = {
      sequence_continuity: contiguous && seqs.length === artifact.events.length + appended.length,
      message_id_preservation: {
        source_ids: sourceIds.all,
        target_ids: targetIds.all,
        appended_ids: appendedIds.all,
        id_sources: { source: sourceIds.counts, target: targetIds.counts, reopened: reopenedIds.counts },
        missing_from_target: missingFromTarget,
        missing_from_reopen: missingFromReopen,
        appended_missing_from_reopen: appendedMissingFromReopen,
      },
      context_preservation: {
        source_system_prompts: sourcePrompts,
        target_system_prompts: targetPrompts,
        source_provider_models: sourceModels,
        target_provider_models: [...targetModelSet].sort(),
        missing_system_prompts: [...new Set(sourcePrompts)].filter((value) => !targetPromptSet.has(value)),
        missing_provider_models: sourceModels.filter((value) => !targetModelSet.has(value)),
      },
      ids: {
        source_session_id: sourceRows[0].id,
        target_session_id: artifact.header.id,
        reopened_session_id: read.header.id,
        identical: sourceRows[0].id === artifact.header.id && artifact.header.id === read.header.id,
      },
      inherited_event_count: { source_marker: sourceRows.find((row) => row.type === 'session/end-seed')?.seq ?? 0, target: artifact.inheritedEventCount },
    }
  } catch (error) {
    result.reopen = { status: 'fail', error_name: error?.name ?? 'Error', message: String(error?.message ?? error).slice(0, 600) }
    result.blockers.push({ stage: 'reopen', error_name: result.reopen.error_name, message: result.reopen.message })
    return result
  }

  try {
    const migratedHeader = closedRows[0]
    let v2CodecError
    try {
      releasedV2SessionFormatCodec.decodeHeader(migratedHeader)
    } catch (error) {
      v2CodecError = { name: error?.name ?? 'Error', message: String(error?.message ?? error).slice(0, 300) }
    }
    const v2MaxChain = createSessionFormatChain({
      currentVersion: 2,
      migrations: [sessionFormatV0ToV1, sessionFormatV1ToV2],
      restoreCurrentHeader: (header) => header,
    })
    let chainError
    try {
      v2MaxChain.migrateHeader(migratedHeader)
    } catch (error) {
      chainError = { name: error?.name ?? 'Error', message: String(error?.message ?? error).slice(0, 300) }
    }
    const refused = Boolean(v2CodecError) || Boolean(chainError)
    result.downgrade = {
      feasible: refused ? false : null,
      method: 'released v2 codec decodeHeader + v2-max migration chain plan on the migrated v3 header',
      v2_codec_refusal: v2CodecError ?? null,
      v2_max_chain_refusal: chainError ?? null,
      migrated_generation_filename: 'session.v3.jsonl',
      legacy_reader_generation_filename: 'session.v2.jsonl / session.jsonl',
      reason: refused
        ? 'DSH 0.1.2-rc.1 predates dsh-session-format and selects session.vN.jsonl by filename; the migrated v3 header is refused by the released v2 codec and by a v2-max migration chain. The migrated store is NOT downgradable.'
        : 'unexpected: v2 reader accepted a v3 header',
    }
    if (result.downgrade.feasible === null) result.blockers.push({ stage: 'downgrade', message: 'v2 reader unexpectedly accepted v3' })
  } catch (error) {
    result.downgrade = { feasible: null, reason: `downgrade probe failed: ${error?.name ?? 'Error'}: ${String(error?.message ?? error).slice(0, 300)}` }
    result.blockers.push({ stage: 'downgrade', message: result.downgrade.reason })
  }

  result.scratch = { working_source_sha256: workingHash }
  return applyFixtureFault(result)
}

async function failClosedCases() {
  const cases = []
  const base = (id, expectation) => ({
    id,
    expectation,
    refused: false,
    error_name: null,
    error_message: null,
    catalog_status: null,
    documented_refusal: false,
    treated_as_new_session: false,
    successor_generation_written: false,
  })

  const probe = (record, rows) => {
    try {
      record.catalog_status = sessionFormatCatalog.readHeader(rows[0]).status
    } catch (error) {
      record.refused = true
      record.error_name = record.error_name ?? (error?.name ?? 'Error')
      record.error_message = record.error_message ?? String(error?.message ?? error).slice(0, 300)
    }
    if (!record.refused) {
      try {
        restore(rows)
      } catch (error) {
        record.refused = true
        record.error_name = error?.name ?? 'Error'
        record.error_message = String(error?.message ?? error).slice(0, 300)
      }
    }
    record.documented_refusal = record.refused && (
      record.error_name === 'SessionFormatUnsupportedMigrationError'
      || record.catalog_status === 'malformed'
      || record.catalog_status === 'unsupported'
    )
    cases.push(record)
  }

  // 1. Future/unknown format version must fail closed, not become a new session.
  probe(base('unknown-future-format', 'SessionFormatUnsupportedError on read/migrate; no successor written'), [
    { type: 'session', version: 99, id: 'fx-future', createdAt: 1, isSeeded: false, delegationDepth: 0 },
    { type: 'turn/start', seq: 0, time: 1, data: { turn: 1 } },
  ])

  // 2. Corrupt/unclassified event must refuse instead of silently starting new.
  probe(base('unclassified-event', 'SessionFormatUnsupportedError; not converted to a new session'), [
    { type: 'session', version: 2, id: 'fx-corrupt', createdAt: 1, isSeeded: false, delegationDepth: 0 },
    { type: 'turn/start', seq: 0, time: 1, data: { turn: 1 } },
    { type: 'step/start', seq: 1, time: 2, data: { turn: 1, step: 1 } },
    { type: 'totally/unknown-event', seq: 2, time: 3, data: { anything: true } },
  ])

  // 3. Malformed header must be reported as malformed, not migrated.
  probe(base('malformed-header', "readHeader status 'malformed'; no migration"), [
    { type: 'not-a-session', version: 2, id: 'fx-malformed' },
  ])

  // 4. A schema-valid v2 store that migration refuses must not silently be
  //    re-created as a fresh session.
  probe(base('refused-surface-migration', 'unsupported migration refusal; the existing session is not replaced by a new one'), [
    { type: 'session', version: 2, id: 'fx-refused-surface', createdAt: 1, isSeeded: false, delegationDepth: 0 },
    { type: 'user/message', seq: 0, time: 1, data: { role: 'user', id: 'u', source: { kind: 'user' }, content: [{ type: 'text', text: 'pre-step surface' }] }, surfaceOp: 'append' },
  ])

  if (FAULT === 'fail_closed' && cases.length > 0) cases[0].documented_refusal = false
  return { schema_version: 'byq-d15-2-fail-closed.v1', cases }
}

async function main() {
  const scratchRoot = await mkdtemp(join(tmpdir(), 'byq-d15-2-'))
  const fixtures = []
  try {
    for (const id of FIXTURE_ORDER) {
      const result = await migrateFixture(id, scratchRoot)
      // A failed migration must never leave a successor generation behind.
      result.migration.no_successor_written = result.migration.status === 'blocked'
      fixtures.push(result)
      console.error(`[d15-2] ${id}: migration=${result.migration.status} read=${result.read.status} resume=${result.resume.status} append=${result.append.status} close=${result.close.status} reopen=${result.reopen.status} downgrade=${result.downgrade.feasible}`)
    }
    const failClosed = await failClosedCases()
    const migrated = fixtures.filter((fixture) => fixture.migration.status === 'migrated' || fixture.migration.status === 'current')
    // The pre-fix gate only looked at stage status strings. It is retained as
    // `legacy_*` so negative controls can prove the old code would have passed.
    const allPass = migrated.every((fixture) => fixture.read.status === 'pass' && fixture.resume.status === 'pass' && fixture.append.status === 'pass' && fixture.close.status === 'pass' && fixture.reopen.status === 'pass')
    const verdict = computeVerdict(fixtures, failClosed)
    const results = {
      schema_version: 'byq-d15-2-session-migration-results.v2',
      generated_at: new Date().toISOString(),
      target: TARGET,
      harness: {
        script: 'scripts/d15/harness/migration_harness.mjs',
        verdict_script: 'scripts/d15/harness/migration_verdict.mjs',
        package_versions: PACKAGE_VERSIONS,
        fault_injection: FAULT || null,
        scope: 'format-catalog layer only, NOT runtime recovery. read/resume via installed Session.fromRestore; append encoded with the released v3 current encoder; close = fsync of the v3 generation; reopen re-reads through the installed Session. No SessionHandle.flush durability barrier, no live SessionWriteLease, no runtime adapter/Gateway/DSH process, and no real AgentSession/goal/approval/result recovery is exercised.',
      },
      fixtures,
      summary: {
        fixture_count: fixtures.length,
        migrated_count: migrated.filter((fixture) => fixture.migration.status === 'migrated').length,
        current_count: migrated.filter((fixture) => fixture.migration.status === 'current').length,
        blocked_count: fixtures.filter((fixture) => fixture.migration.status === 'blocked').length,
        all_post_migration_stages_pass: allPass,
        downgradable_count: fixtures.filter((fixture) => fixture.downgrade.feasible === true).length,
        non_downgradable_count: fixtures.filter((fixture) => fixture.downgrade.feasible === false).length,
      },
      verdict,
    }
    const verdictDocument = {
      schema_version: 'byq-d15-2-verdict.v2',
      generated_at: results.generated_at,
      target: TARGET,
      harness: results.harness,
      summary: results.summary,
      verdict,
    }
    await mkdir(dirname(resultsPath), { recursive: true }).catch(() => {})
    await writeFile(resultsPath, `${JSON.stringify(results, null, 2)}\n`, 'utf8')
    if (failClosedPath) await writeFile(failClosedPath, `${JSON.stringify(failClosed, null, 2)}\n`, 'utf8')
    if (verdictPath) {
      await mkdir(dirname(verdictPath), { recursive: true }).catch(() => {})
      await writeFile(verdictPath, `${JSON.stringify(verdictDocument, null, 2)}\n`, 'utf8')
    }
    console.log(JSON.stringify({ summary: results.summary, verdict: verdict.all_pass, exit_code: verdict.exit_code }, null, 2))
    return verdict.exit_code
  } finally {
    await rm(scratchRoot, { recursive: true, force: true })
  }
}

main().then((code) => process.exit(code)).catch((error) => {
  console.error(error)
  process.exit(2)
})
