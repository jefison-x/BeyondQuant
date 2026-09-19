/**
 * D15-2 fixture builder.
 *
 * Produces deterministic historical Session-log fixtures for the Session V3
 * migration qualification. Physical rows are encoded with the *released v2
 * codec* shipped in the DSH 0.1.5-rc.1 `@deepseek-ai/dsh-session-format-v1-to-v2`
 * package, so the constructed fixtures are byte-accurate released-v2 artifacts
 * (one JSON object per line: a `session` header row followed by event rows).
 *
 * `f-normal` is copied verbatim from a real 0.1.2-rc.1 runtime store when a raw
 * decompressed source is supplied. `f-continuable` is a current-format (v3)
 * child produced by running the real catalog migration over a v2 base and
 * re-encoding with the released v3 codec; the continuable activation descriptor
 * itself remains a D15-4 artifact.
 *
 * Usage:
 *   node build_fixtures.mjs <output-root> [real-v0-source.jsonl]
 */

import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { sessionFormatCatalog } from '@deepseek-ai/dsh-session-format-catalog'
import { releasedV2SessionFormatCodec, releasedV3SessionFormatCodec } from '@deepseek-ai/dsh-session-format-v2-to-v3'

const outputRoot = process.argv[2]
const realV0Source = process.argv[3]
if (!outputRoot) {
  console.error('usage: node build_fixtures.mjs <output-root> [real-v0-source.jsonl]')
  process.exit(2)
}

const MODEL = { provider: 'deepseek-official', model: 'deepseek-v4-flash' }
const CREATED = 1789831223000

let eventClock = CREATED + 100
let seq = 0
const resetSeq = () => { seq = 0 }
const nextTime = () => (eventClock += 1)

const header2 = (id, extra = {}) => ({
  version: 2, id, createdAt: CREATED, delegationDepth: 0, isSeeded: false, ...extra,
})
const row = (type, data, extra = {}) => ({ type, seq: seq++, time: nextTime(), data, ...extra })
const user = (id, text) => ({ role: 'user', id, source: { kind: 'user' }, content: [{ type: 'text', text }] })
const assistant = (id, text, turn = 1, step = 1) => ({
  turn, step,
  message: { id, role: 'assistant', source: { kind: 'model', ...MODEL }, content: [{ type: 'text', text }] },
  stream: [],
})
const toolResult = (id, callId, text, turn = 1, step = 1, isError = false) => ({
  turn, step,
  message: {
    id, role: 'user', source: { kind: 'tool', callId },
    content: [{ type: 'tool-result', toolCallId: callId, isError, content: [{ type: 'text', text }] }],
  },
})
const requestHeader = (system) => ({
  header: { config: { ...MODEL }, ...(system === undefined ? {} : { system }) }, reason: 'initial',
})

function oneTurn({ turn = 1, prompt = 'hello', answer = 'world', tool = false, close = true } = {}) {
  const events = [
    row('turn/start', { turn }),
    row('step/start', { turn, step: 1 }),
    row('user/message', user(`u-${turn}`, prompt), { surfaceOp: 'append' }),
    row('request/header', requestHeader('You are a BYQ synthetic fixture.')),
    row('request/context', { provider: MODEL.provider, model: MODEL.model }),
    row('assistant/message', assistant(`a-${turn}`, tool ? '' : answer, turn, 1), { surfaceOp: 'append' }),
  ]
  if (tool) {
    events.push(row('tool/call', {
      turn, step: 1, callId: `call-${turn}`, name: 'byq_delegate_market_research', arguments: '{}',
    }))
    events.push(row('tool/result', toolResult(`tr-${turn}`, `call-${turn}`, 'fixture tool result', turn, 1), { surfaceOp: 'append' }))
  }
  if (close) {
    events.push(row('step/end', { turn, step: 1 }))
    events.push(row('turn/end', { turn, reason: { kind: 'completed' } }))
  }
  return events
}

const v2Builders = {
  'f-completed': () => ({ header: header2('fx-completed'), events: oneTurn({ turn: 1, prompt: 'completed turn', answer: 'done' }) }),
  'f-interrupted': () => {
    const h = header2('fx-interrupted')
    const events = [
      row('turn/start', { turn: 1 }),
      row('step/start', { turn: 1, step: 1 }),
      row('user/message', user('u-1', 'interrupted turn'), { surfaceOp: 'append' }),
      row('request/header', requestHeader('You are a BYQ synthetic fixture.')),
      row('assistant/message', {
        turn: 1, step: 1,
        message: {
          id: 'a-1', role: 'assistant', source: { kind: 'model', ...MODEL },
          content: [{ type: 'tool-call', id: 'call-interrupted', name: 'byq_delegate_market_research', arguments: '{}' }],
        },
        stream: [],
      }, { surfaceOp: 'append' }),
      row('tool/call', { turn: 1, step: 1, callId: 'call-interrupted', name: 'byq_delegate_market_research', arguments: '{}' }),
    ]
    return { header: h, events }
  },
  'f-compacted': () => {
    const h = header2('fx-compacted')
    const events = [
      ...oneTurn({ turn: 1, prompt: 'first user turn', answer: 'first answer' }),
      row('turn/start', { turn: 2 }),
      row('step/start', { turn: 2, step: 1 }),
      row('compaction/start', { compactionId: 'cmp-1', turn: 2 }),
      row('compaction/prune', { shadowedRange: { start: 2, end: 5 }, shadowedSeqs: [2, 5], shadowedTokenCount: 42 }),
      row('compaction/summary', {
        compactionId: 'cmp-1',
        summary: [{ type: 'text', text: 'Summary of the compacted prefix.' }],
        shadowedRange: { start: 2, end: 5 },
        shadowedSeqs: [2, 5],
        shadowedTokenCount: 42,
        provider: MODEL.provider,
        model: MODEL.model,
      }),
      row('compaction/end', { compactionId: 'cmp-1', turn: 2 }),
      row('user/message', user('u-2', 'second user turn after compaction'), { surfaceOp: 'append' }),
      row('assistant/message', assistant('a-2', 'second answer', 2, 1), { surfaceOp: 'append' }),
      row('step/end', { turn: 2, step: 1 }),
      row('turn/end', { turn: 2, reason: { kind: 'completed' } }),
    ]
    return { header: h, events }
  },
  'f-large': () => {
    const h = header2('fx-large')
    const events = []
    const content = 'x'.repeat(2048)
    for (let turn = 1; turn <= 400; turn += 1) {
      events.push(row('turn/start', { turn }))
      events.push(row('step/start', { turn, step: 1 }))
      events.push(row('user/message', user(`u-${turn}`, `${content}-${turn}`), { surfaceOp: 'append' }))
      events.push(row('request/header', requestHeader('You are a BYQ synthetic fixture.')))
      events.push(row('assistant/message', assistant(`a-${turn}`, `${content}-${turn}`, turn, 1), { surfaceOp: 'append' }))
      events.push(row('step/end', { turn, step: 1 }))
      events.push(row('turn/end', { turn, reason: { kind: 'completed' } }))
    }
    return { header: h, events }
  },
  'f-subagent': () => {
    const h = header2('fx-subagent', { origin: 'subagent', parentSession: 'parent-session-0001', delegationDepth: 1 })
    const events = [
      row('subagent/descriptor', {
        mode: 'one-shot', version: 3, provider: 'byq-delegate', label: 'market_research',
      }),
      ...oneTurn({ turn: 1, prompt: 'delegated research question', answer: 'delegated answer' }),
    ]
    return { header: h, events }
  },
  'f-forked': () => {
    const h = header2('fx-forked', { isSeeded: true, parentSession: 'fork-parent-0002', delegationDepth: 0 })
    const events = [
      row('turn/start', { turn: 1 }),
      row('step/start', { turn: 1, step: 1 }),
      row('user/message', user('seed-u-1', 'inherited prefix prompt'), { surfaceOp: 'append' }),
      row('request/header', requestHeader('Inherited prefix system prompt.')),
      row('assistant/message', assistant('seed-a-1', 'inherited prefix answer', 1, 1), { surfaceOp: 'append' }),
      row('step/end', { turn: 1, step: 1 }),
      row('turn/end', { turn: 1, reason: { kind: 'completed' } }),
      row('session/end-seed', { inherited: true }),
      ...oneTurn({ turn: 2, prompt: 'fork child continuation', answer: 'fork child answer' }),
    ]
    return { header: h, events }
  },
  'f-old-lifecycle': () => ({ header: header2('fx-old-lifecycle'), events: oneTurn({ turn: 1, prompt: 'session with BYQ lifecycle evidence', answer: 'ok' }) }),
}

const OLD_LIFECYCLE = {
  schema_version: 'byq-runtime-lifecycle-evidence.v1',
  session_id: 'fx-old-lifecycle',
  trace_id: 'fixture-trace-0001',
  owner: 'fixture-owner',
  workspace_id: 'fixture-workspace',
  executor_epoch: 7,
  sequence: 3,
  events: [
    { kind: 'session.ready', sequence: 1 },
    { kind: 'turn.started', sequence: 2 },
    { kind: 'turn.completed', sequence: 3 },
  ],
}

function encodeV2(header, events) {
  const cut = header.isSeeded ? events.findIndex((event) => event.type === 'session/end-seed') : 0
  return [releasedV2SessionFormatCodec.encodeHeader(header, cut), ...events.map((event) => releasedV2SessionFormatCodec.encodeEvent(event))]
}

function migrateToV3(rows) {
  const restore = sessionFormatCatalog.createRestore(rows[0], { recovery: 'strict', validation: 'current' })
  for (const row of rows.slice(1)) restore.decodeRow(row)
  return restore.finish()
}

function encodeV3(artifact) {
  return [
    releasedV3SessionFormatCodec.encodeHeader(artifact.header, artifact.inheritedEventCount),
    ...artifact.events.map((event) => releasedV3SessionFormatCodec.encodeEvent(event)),
  ]
}

async function main() {
  await mkdir(outputRoot, { recursive: true })
  for (const [id, build] of Object.entries(v2Builders)) {
    resetSeq()
    const { header, events } = build()
    const rows = encodeV2(header, events)
    const text = `${rows.map((row) => JSON.stringify(row)).join('\n')}\n`
    const dir = join(outputRoot, id)
    await mkdir(dir, { recursive: true })
    await writeFile(join(dir, 'session.jsonl'), text, 'utf8')
    if (id === 'f-old-lifecycle') {
      await writeFile(join(dir, 'byq-lifecycle-evidence.json'), `${JSON.stringify(OLD_LIFECYCLE, null, 2)}\n`, 'utf8')
    }
  }
  // f-continuable: a current-format (v3) child produced by the real migration.
  resetSeq()
  const base = { header: header2('fx-continuable', { origin: 'subagent', parentSession: 'parent-session-0003', delegationDepth: 1 }), events: oneTurn({ turn: 1, prompt: 'continuable child turn', answer: 'continuable child answer' }) }
  const v3rows = encodeV3(migrateToV3(encodeV2(base.header, base.events)))
  {
    const dir = join(outputRoot, 'f-continuable')
    await mkdir(dir, { recursive: true })
    await writeFile(join(dir, 'session.jsonl'), `${v3rows.map((row) => JSON.stringify(row)).join('\n')}\n`, 'utf8')
  }
  if (realV0Source !== undefined && existsSync(realV0Source)) {
    const text = await readFile(realV0Source, 'utf8')
    const dir = join(outputRoot, 'f-normal')
    await mkdir(dir, { recursive: true })
    await writeFile(join(dir, 'session.jsonl'), text, 'utf8')
  }
  console.log(`wrote D15-2 fixtures to ${outputRoot}`)
}

await main()
