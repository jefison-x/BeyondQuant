/**
 * D15-3 native session resume qualification: shared helpers.
 *
 * These helpers drive the real DSH 0.1.5-rc.1 session-persistence seam
 * (`@deepseek-ai/dsh-session-persistence` service +
 * `@deepseek-ai/dsh-session-persistence-jsonl` backend mounted on a real
 * Cordis context) and the real `readColdSessionLog` cold-read entry point.
 *
 * Native resume is the documented `SessionPersistence.open(id, access)`
 * operation returning a `SessionHandle` over the SAME persisted DSH session
 * (same session id, same validated event log), as opposed to creating a new
 * session and replaying BYQ conversation context. Nothing here invents an API.
 */

import { Context } from '@deepseek-ai/cordis'
import JsonlSessionPersistence from '@deepseek-ai/dsh-session-persistence-jsonl'
import { sessionFormatCatalog } from '@deepseek-ai/dsh-session-format-catalog'

export const SESSION_FORMAT_VERSION = 3
export const TARGET_NPM_VERSION = '0.1.5-rc.1'
export const PACKAGE_VERSIONS = {
  '@deepseek-ai/dsh-session': '0.1.5-rc.1',
  '@deepseek-ai/dsh-session-persistence': '0.1.5-rc.1',
  '@deepseek-ai/dsh-session-persistence-jsonl': '0.1.5-rc.1',
  '@deepseek-ai/dsh-session-query': '0.1.5-rc.1',
  '@deepseek-ai/cordis': '4.0.2',
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

export function sessionHeader(id, cwd) {
  return { id, version: SESSION_FORMAT_VERSION, createdAt: 1, cwd, isSeeded: false, delegationDepth: 0 }
}

export function completedTurn(startSeq, turn, time = 1) {
  return [
    { type: 'turn/start', seq: startSeq, time: time + 0, data: { turn } },
    { type: 'step/start', seq: startSeq + 1, time: time + 1, data: { turn, step: 1 } },
    {
      type: 'user/message', seq: startSeq + 2, time: time + 2,
      data: { role: 'user', id: `u-${turn}`, source: { kind: 'user' }, content: [{ type: 'text', text: `turn ${turn}` }] },
      surfaceOp: 'append',
    },
    {
      type: 'assistant/message', seq: startSeq + 3, time: time + 3,
      data: {
        turn, step: 1,
        message: {
          id: `a-${turn}`, role: 'assistant',
          source: { kind: 'model', provider: 'deepseek-official', model: 'deepseek-v4-flash' },
          content: [{ type: 'text', text: `ack ${turn}` }],
        },
        stream: [],
      },
      surfaceOp: 'append',
    },
    { type: 'step/end', seq: startSeq + 4, time: time + 4, data: { turn, step: 1 } },
    { type: 'turn/end', seq: startSeq + 5, time: time + 5, data: { turn, reason: { kind: 'completed' } } },
  ]
}

export function openTurn(startSeq, turn, time = 1) {
  return [
    { type: 'turn/start', seq: startSeq, time: time + 0, data: { turn } },
    { type: 'step/start', seq: startSeq + 1, time: time + 1, data: { turn, step: 1 } },
    {
      type: 'user/message', seq: startSeq + 2, time: time + 2,
      data: { role: 'user', id: `u-${turn}`, source: { kind: 'user' }, content: [{ type: 'text', text: `open turn ${turn}` }] },
      surfaceOp: 'append',
    },
  ]
}

export function validateEvents(events) {
  for (const event of events) sessionFormatCatalog.encodeCurrentEvent(event)
  return events
}

export function contiguous(events) {
  if (!Array.isArray(events) || events.length === 0) return true
  return events.every((event, index) => event.seq === index)
}

export function eventTypes(events) {
  return events.map((event) => event.type)
}

export function nextTurn(events) {
  const turns = events.filter((event) => event.type === 'turn/start').map((event) => event.data?.turn)
  return turns.length === 0 ? 1 : Math.max(...turns) + 1
}

export function hasOpenTurn(events) {
  const starts = events.filter((event) => event.type === 'turn/start').map((event) => event.data?.turn)
  const ends = new Set(events.filter((event) => event.type === 'turn/end').map((event) => event.data?.turn))
  return starts.some((turn) => !ends.has(turn))
}

export async function mountBackend(root) {
  const ctx = new Context()
  ctx.plugin(JsonlSessionPersistence, { root })
  const deadline = Date.now() + 5000
  while (!ctx.sessionPersistence && Date.now() < deadline) await sleep(10)
  if (!ctx.sessionPersistence) throw new Error('jsonl persistence backend did not mount')
  return ctx
}

export async function closeBackend(ctx) {
  try {
    await ctx?.stop()
  } catch {
    // best-effort teardown; open handles are closed explicitly by callers
  }
}

export function jsonLine(value) {
  process.stdout.write(`${JSON.stringify(value)}\n`)
}
