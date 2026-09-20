#!/usr/bin/env node
/**
 * D15-4 real native continuable-subagent / fork continuity harness.
 *
 * Evidence-only qualification harness pinned to the fixed DSH 0.1.5-rc.1
 * candidate closure. It boots the REAL native stack (agent loop, JSONL session
 * persistence, `@deepseek-ai/dsh-subagent` + spawn/fork providers, session
 * query) with a scripted keyless LLM adapter. It is NOT a product runtime, NOT
 * a second generic agent harness, and it persists no BYQ subagent state: it
 * drives only the native `startContinuable` / `Activation` / `authorizeLineage`
 * / `sendMessage` / `listChildren` / fork seam that BYQ composes but does not
 * yet wire into its runtime-adapter.
 *
 * The provider is scripted and keyless: this is runtime-continuity evidence,
 * labelled non-real-LLM-quality, never semantic model quality.
 *
 * Usage:
 *   node native_subagent_harness.mjs run [--out <path>] [--keep]
 *   node native_subagent_harness.mjs worker <scenario> <params-json>
 */

import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, existsSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { Context } from '@deepseek-ai/cordis'
import { SessionId } from '@deepseek-ai/dsh-session'
import { LlmAdapter, ReasoningEffortId, createUserMessage } from '@deepseek-ai/dsh-llm'
import { mountAgentLoopTestDependencies, mountAgentLoopTestHarness } from '@deepseek-ai/dsh-agent-loop-testkit'
import JsonlSessionPersistence from '@deepseek-ai/dsh-session-persistence-jsonl'
import SessionQueryEngine from '@deepseek-ai/dsh-session-query'
import * as SubagentSpawn from '@deepseek-ai/dsh-subagent-spawn-in-process'
import * as SubagentFork from '@deepseek-ai/dsh-subagent-fork-in-process'
import SubagentRuntime, {
  SubagentError,
  delegationDepthOf,
  SUBAGENT_DESCRIPTOR_VERSION,
} from '@deepseek-ai/dsh-subagent'

export const EVIDENCE_CLASS = 'native-runtime-isolated'
export const LLM_CLASS = 'scripted-keyless'
export const CANDIDATE_RELEASE = 'dsh-0.1.5rc1'
export const CANDIDATE_NPM = '0.1.5-rc.1'

const PARENT_ID = 'd15-4-parent'
const OTHER_PARENT_ID = 'd15-4-other-parent'

// ---------------------------------------------------------------------------
// scripted keyless adapter (non-real-LLM)
// ---------------------------------------------------------------------------

export function textResponse(text) {
  return [
    { type: 'block-start', index: 0, blockType: 'text' },
    ...Array.from(text, (char) => ({ type: 'text-delta', index: 0, text: char })),
    { type: 'block-end', index: 0, block: { type: 'text', text } },
    { type: 'usage', usage: { inputTokens: 10, outputTokens: text.length } },
    { type: 'finish', reason: { kind: 'stop' } },
  ]
}

/** Stream one chunk then block until the request is aborted (models a crash window). */
export function hangResponse() {
  return [
    { type: 'block-start', index: 0, blockType: 'text' },
    { type: 'text-delta', index: 0, text: 'partial' },
    { hang: true },
  ]
}

/**
 * Fail the model stream (no SIGKILL): an independent child-run fault that
 * exercises the native seam's truthful failure/settlement path while the parent
 * process stays alive. This is NOT a substitute for a child-only process crash.
 */
export function faultResponse(message = 'd15-4 scripted child stream fault') {
  return [{ fault: message }]
}

class ScriptedAdapter extends LlmAdapter {
  requests = []
  constructor(script, efforts) {
    super()
    this.script = script
    this.efforts = efforts
  }

  resolveModel(provider, model) {
    return Promise.resolve({
      provider,
      id: model,
      name: model,
      reasoning: this.efforts === undefined ? undefined : {
        efforts: this.efforts.map((id) => ({ id, name: id })),
        defaultEffort: this.efforts[0],
      },
    })
  }

  async *stream(options) {
    this.requests.push({
      provider: options.provider,
      model: options.model,
      reasoningEffort: options.reasoningEffort,
      toolNames: (options.tools ?? []).map((tool) => tool?.function?.name ?? tool?.name).filter(Boolean),
    })
    const entry = this.script.length > 0 ? this.script.shift() : textResponse('scripted fallback')
    for (const chunk of entry) {
      if (chunk.fault) {
        throw new Error(String(chunk.fault))
      }
      if (chunk.hang) {
        await new Promise((_resolve, reject) => {
          if (options.signal?.aborted) { reject(new Error('aborted')); return }
          options.signal?.addEventListener('abort', () => reject(new Error('aborted')), { once: true })
        })
        return
      }
      yield chunk
    }
  }
}

// ---------------------------------------------------------------------------
// boot + observation helpers
// ---------------------------------------------------------------------------

async function boot(storeRoot, { efforts } = {}) {
  const ctx = new Context()
  await mountAgentLoopTestDependencies(ctx)
  const persistenceFiber = await ctx.plugin(JsonlSessionPersistence, { root: storeRoot })
  const loopHarness = await mountAgentLoopTestHarness(ctx)
  await ctx.plugin(SessionQueryEngine)
  await ctx.plugin(SubagentRuntime)
  await ctx.plugin(SubagentSpawn, { providerName: 'spawn' })
  await ctx.plugin(SubagentFork, { providerName: 'fork' })
  const created = []
  ctx.on('agent/created', ({ agent }) => {
    created.push({
      id: agent.id,
      provider: agent.options?.provider,
      model: agent.options?.model,
      reasoningEffort: agent.options?.reasoningEffort,
    })
  })
  // In-process settlement delivery observation: the manager inserts a
  // `subagent-settled` user message into the direct parent's inbox. Parking the
  // parent must not hide the delivery, so count it at the inbox boundary.
  const settlements = []
  ctx.on('agent/inbox/inserted', ({ agent, message }) => {
    if (message?.source?.kind === 'subagent-settled') {
      const text = Array.isArray(message.content)
        ? message.content.filter((block) => block?.type === 'text').map((block) => block.text).join(' ')
        : ''
      settlements.push({
        agentId: String(agent.id),
        childId: String(message.source.senderSessionId),
        summary: message.source.summary ?? null,
        text,
      })
    }
  })
  return { ctx, persistenceFiber, loopHarness, created, settlements }
}

function parkParent(ctx, parent) {
  ctx.on('agent/pre-step', async ({ agent }, next) => {
    if (agent !== parent) return next()
    return { kind: 'reject' }
  })
}

async function readStored(ctx, id) {
  const handle = await ctx.sessionPersistence.open(id, 'read')
  try {
    return {
      header: {
        id: handle.header.id,
        parentSession: handle.header.parentSession ?? null,
        origin: handle.header.origin ?? null,
        isSeeded: handle.header.isSeeded ?? false,
        delegationDepth: handle.header.delegationDepth ?? null,
      },
      inheritedEventCount: handle.inheritedEventCount ?? 0,
      events: (await handle.read()).events.map((event) => ({
        type: event.type,
        seq: event.seq,
        data: event.data,
      })),
    }
  } finally {
    await handle.close()
  }
}

function descriptorOf(stored) {
  const event = stored.events.find((item) => item.type === 'subagent/descriptor')
  return event === undefined ? null : event.data
}

function settlementCount(stored, childId) {
  return stored.events.filter((event) => event.type === 'user/message'
    && event.data?.source?.kind === 'subagent-settled'
    && String(event.data?.source?.senderSessionId) === String(childId)).length
}

function sequencesContiguous(events) {
  const seqs = events.map((event) => event.seq)
  if (seqs.length === 0) return true
  return seqs.every((value, index) => value === index)
}

/** Full-log digest: seq + type + payload, so payload tampering cannot hide. */
function eventLogHash(events) {
  return 'sha256:' + createHash('sha256')
    .update(JSON.stringify(events.map((event) => ({ seq: event.seq, type: event.type, data: event.data }))))
    .digest('hex')
}

async function waitFor(predicate, { timeout = 20000, interval = 100 } = {}) {
  const deadline = Date.now() + timeout
  for (;;) {
    const value = await predicate()
    if (value) return value
    if (Date.now() > deadline) return null
    await new Promise((resolve) => setTimeout(resolve, interval))
  }
}

async function waitTurnEnd(ctx, id, minTurns = 1) {
  return waitFor(async () => {
    try {
      const stored = await readStored(ctx, id)
      const turns = stored.events.filter((event) => event.type === 'turn/end').length
      return turns >= minTurns ? stored : null
    } catch {
      return null
    }
  })
}

async function createParent(ctx, id = PARENT_ID, loopHarness = null) {
  if (loopHarness) return loopHarness.create(SessionId(id), { provider: 'mock', model: 'mock' })
  return ctx.agentLoop.create(SessionId(id), { provider: 'mock', model: 'mock' })
}

async function resumeParent(ctx, id = PARENT_ID) {
  const handle = await ctx.agentLoop.resume(ctx, {
    resumeSessionId: SessionId(id),
    agentOptions: { provider: 'mock', model: 'mock' },
  })
  return handle.agent ?? handle
}

const SIGNAL = () => new AbortController().signal

// ---------------------------------------------------------------------------
// worker scenarios
// ---------------------------------------------------------------------------

async function scenarioStart(params) {
  const { ctx, persistenceFiber, created, settlements } = await boot(params.storeRoot, { efforts: ['max'] })
  const adapter = new ScriptedAdapter([textResponse('child answer one')], ['max'])
  ctx.llm.registerAdapter(['mock'], adapter)
  const parent = await createParent(ctx)
  parkParent(ctx, parent)

  const request = {
    prompt: [{ type: 'text', text: 'child initial task' }],
    parent,
  }
  const composition = params.composition
  if (composition?.reasoningEffort) request.agentOptions = { provider: 'mock', model: 'mock', reasoningEffort: ReasoningEffortId(composition.reasoningEffort) }
  if (composition?.persona) request.persona = composition.persona
  if (composition?.maxDepth !== undefined) request.maxDepth = composition.maxDepth

  const started = await ctx.subagents.startContinuable({
    provider: 'spawn',
    label: 'child task',
    request,
    signal: SIGNAL(),
    ...(params.childId ? { childId: SessionId(params.childId) } : {}),
  })

  const stored = await waitTurnEnd(ctx, started.childId, 1)
  await waitFor(() => settlements.filter((item) => item.childId === String(started.childId)).length >= 1,
    { timeout: 15000 })
  const child = stored ?? await readStored(ctx, started.childId)
  const parentStored = await readStored(ctx, PARENT_ID)
  const children = await ctx.subagents.listChildren(parent.id)

  await persistenceFiber.dispose()
  await ctx.dispose?.()

  return {
    parentId: parent.id,
    childId: started.childId,
    messageId: started.messageId,
    distinctIdentity: String(started.childId) !== String(parent.id),
    header: child.header,
    descriptor: descriptorOf(child),
    descriptorVersion: SUBAGENT_DESCRIPTOR_VERSION,
    childEventTypes: child.events.map((event) => event.type),
    childSequenceContiguous: sequencesContiguous(child.events),
    settlementCount: settlementCount(parentStored, started.childId),
    settlementDeliveries: settlements.filter((item) => item.childId === String(started.childId)).length,
    created: created.map((item) => ({ ...item, id: String(item.id) })),
    listChildren: children.map((item) => ({ id: String(item.id), mode: item.mode, kind: item.kind })),
    adapterRequests: adapter.requests,
  }
}

async function scenarioResume(params) {
  const { ctx, persistenceFiber, created, settlements } = await boot(params.storeRoot, { efforts: ['max'] })
  const adapter = new ScriptedAdapter([textResponse('child answer resumed')], ['max'])
  ctx.llm.registerAdapter(['mock'], adapter)
  const parent = await resumeParent(ctx)
  parkParent(ctx, parent)

  const beforeChild = await readStored(ctx, params.childId)
  const beforeSettlements = settlementCount(await readStored(ctx, PARENT_ID), params.childId)

  const messageId = await ctx.subagents.sendMessage(
    parent, SessionId(params.childId), [{ type: 'text', text: 'resume the child' }], { signal: SIGNAL() },
  )

  const stored = await waitTurnEnd(ctx, params.childId, beforeChild.events.filter((event) => event.type === 'turn/end').length + 1)
  await waitFor(() => settlements.filter((item) => item.childId === String(params.childId)).length >= 1,
    { timeout: 15000 })
  const afterChild = stored ?? await readStored(ctx, params.childId)
  const afterSettlements = settlementCount(await readStored(ctx, PARENT_ID), params.childId)

  await persistenceFiber.dispose()
  await ctx.dispose?.()

  return {
    parentId: parent.id,
    childId: params.childId,
    messageId,
    sameChildId: String(afterChild.header.id) === String(beforeChild.header.id),
    headerBefore: beforeChild.header,
    headerAfter: afterChild.header,
    descriptorBefore: descriptorOf(beforeChild),
    descriptorAfter: descriptorOf(afterChild),
    inheritedEventCountBefore: beforeChild.inheritedEventCount,
    inheritedEventCountAfter: afterChild.inheritedEventCount,
    sequenceContiguousAcrossResume: afterChild.events.every((event, index) => event.seq === index),
    settlementBefore: beforeSettlements,
    settlementAfter: afterSettlements,
    settlementDeliveries: settlements.filter((item) => item.childId === String(params.childId)).length,
    newSettlements: settlements.filter((item) => item.childId === String(params.childId)).length,
    created: created.map((item) => ({ ...item, id: String(item.id) })),
    adapterRequests: adapter.requests,
  }
}

async function scenarioFork(params) {
  const { ctx, persistenceFiber, loopHarness } = await boot(params.storeRoot)
  const adapter = new ScriptedAdapter([textResponse('parent completed answer'), textResponse('fork child answer')])
  ctx.llm.registerAdapter(['mock'], adapter)
  const parent = await createParent(ctx, PARENT_ID, loopHarness)

  // Drive one completed parent turn so a balanced completed-turn prefix exists.
  parent.followup(createUserMessage({
    content: [{ type: 'text', text: 'parent turn for fork seed' }],
    source: { kind: 'user' },
  }))
  await parent.whenIdle()
  const parentTurn = await waitTurnEnd(ctx, PARENT_ID, 1)
  if (parentTurn === null) throw new Error('parent turn did not complete before fork')
  const parentStored = await readStored(ctx, PARENT_ID)
  const parentEventsBefore = parentStored.events
  const parentLogHashBefore = eventLogHash(parentEventsBefore)
  const turnEnds = parentEventsBefore.filter((event) => event.type === 'turn/end')
  if (turnEnds.length === 0) throw new Error('parent has no completed turn/end for the fork cut')
  const parentLastTurnEndSeq = turnEnds[turnEnds.length - 1].seq

  const run = await ctx.subagents.start('fork', {
    prompt: [{ type: 'text', text: 'fork child task' }],
    parent,
    signal: SIGNAL(),
  })
  const forked = await waitTurnEnd(ctx, run.id, 1)
  const child = forked ?? await readStored(ctx, run.id)
  const parentStoredAfter = await readStored(ctx, PARENT_ID)
  const parentEventsAfter = parentStoredAfter.events
  const parentLogHashAfter = eventLogHash(parentEventsAfter)

  await run.dispose?.()
  await persistenceFiber.dispose()
  await ctx.dispose?.()

  return {
    parentId: parent.id,
    forkId: run.id,
    distinctIdentity: String(run.id) !== String(parent.id),
    header: child.header,
    isSeeded: child.header.isSeeded,
    inheritedEventCount: child.inheritedEventCount,
    // The exact inherited cut: the balanced completed-turn prefix of the parent
    // is events[0..lastTurnEndSeq], i.e. lastTurnEndSeq + 1 events.
    parentLastTurnEndSeq,
    parentCompletedTurnPrefixCut: parentLastTurnEndSeq + 1,
    parentCompletedTurnCount: turnEnds.length,
    parentEventCountBefore: parentEventsBefore.length,
    parentEventCountAfter: parentEventsAfter.length,
    parentLogHashBefore,
    parentLogHashAfter,
    parentLogImmutable: parentLogHashBefore === parentLogHashAfter
      && parentEventsBefore.length === parentEventsAfter.length,
    childSequenceContiguous: sequencesContiguous(child.events),
  }
}

async function scenarioCrash(params) {
  // Generation A: start a child whose turn hangs, then SIGKILL this process.
  const { ctx } = await boot(params.storeRoot, { efforts: ['max'] })
  const adapter = new ScriptedAdapter([hangResponse()], ['max'])
  ctx.llm.registerAdapter(['mock'], adapter)
  const parent = await createParent(ctx)
  parkParent(ctx, parent)
  const started = await ctx.subagents.startContinuable({
    provider: 'spawn',
    label: 'child task',
    request: { prompt: [{ type: 'text', text: 'child initial task (crash window)' }], parent },
    signal: SIGNAL(),
  })
  // Wait until the child's first model request is in flight, then kill hard.
  await waitFor(() => adapter.requests.length >= 1, { timeout: 10000 })
  await new Promise((resolve) => setTimeout(resolve, 200))
  writeFileSync(params.crashMarker, JSON.stringify({ childId: started.childId, parentId: parent.id }))
  process.kill(process.pid, 'SIGKILL')
}

async function scenarioAfterCrash(params) {
  const { ctx, persistenceFiber, settlements } = await boot(params.storeRoot, { efforts: ['max'] })
  const adapter = new ScriptedAdapter([textResponse('child answer after crash')], ['max'])
  ctx.llm.registerAdapter(['mock'], adapter)
  const parent = await resumeParent(ctx)
  parkParent(ctx, parent)
  const stored = await readStored(ctx, params.childId)
  const parentStoredBefore = await readStored(ctx, PARENT_ID)
  const turnsBefore = stored.events.filter((event) => event.type === 'turn/end').length
  const messageId = await ctx.subagents.sendMessage(
    parent, SessionId(params.childId), [{ type: 'text', text: 'resume after crash' }], { signal: SIGNAL() },
  )
  const resumed = await waitTurnEnd(ctx, params.childId, turnsBefore + 1)
  await waitFor(() => settlements.filter((item) => item.childId === String(params.childId)).length >= 1,
    { timeout: 15000 })
  const after = resumed ?? await readStored(ctx, params.childId)
  const parentStoredAfter = await readStored(ctx, PARENT_ID)

  await persistenceFiber.dispose()
  await ctx.dispose?.()

  return {
    parentId: parent.id,
    childId: params.childId,
    messageId,
    sameChildId: String(after.header.id) === String(params.childId),
    headerBefore: stored.header,
    headerAfter: after.header,
    descriptorAfter: descriptorOf(after),
    childIdRetained: String(after.header.id) === String(params.childId),
    parentSurvived: String(parentStoredAfter.header.id) === PARENT_ID,
    parentEventCountBefore: parentStoredBefore.events.length,
    parentEventCountAfter: parentStoredAfter.events.length,
    newSettlements: settlements.filter((item) => item.childId === String(params.childId)).length,
    adapterRequests: adapter.requests,
  }
}

async function scenarioChildFault(params) {
  // An independent child-run fault (the child's model stream fails) while the
  // parent process stays alive. This exercises the native truthful-failure and
  // settlement path; it is NOT a child process SIGKILL.
  const { ctx, persistenceFiber, settlements } = await boot(params.storeRoot, { efforts: ['max'] })
  const adapter = new ScriptedAdapter([faultResponse()], ['max'])
  ctx.llm.registerAdapter(['mock'], adapter)
  const parent = await createParent(ctx)
  parkParent(ctx, parent)
  const started = await ctx.subagents.startContinuable({
    provider: 'spawn',
    label: 'child task',
    request: { prompt: [{ type: 'text', text: 'child initial task (fault window)' }], parent },
    signal: SIGNAL(),
  })
  await waitFor(() => adapter.requests.length >= 1, { timeout: 10000 })
  const settlement = await waitFor(
    () => settlements.find((item) => item.childId === String(started.childId)) ?? null, { timeout: 15000 })
  let child = null
  try {
    child = await readStored(ctx, started.childId)
  } catch {
    child = null
  }
  await persistenceFiber.dispose()
  await ctx.dispose?.()
  const summary = settlement?.summary ?? ''
  const text = settlement?.text ?? ''
  return {
    parentId: parent.id,
    childId: started.childId,
    adapterRequests: adapter.requests.length,
    settlement: settlement ? { summary, text } : null,
    childEventTypes: child?.events.map((event) => event.type) ?? [],
    childIdRetained: child !== null && String(child.header.id) === String(started.childId),
    parentTruthfulFailure: settlement !== null,
    fabricatedCompletion: /completed/i.test(summary),
    descriptor: child === null ? null : descriptorOf(child),
  }
}

async function scenarioChildFaultResume(params) {
  const { ctx, persistenceFiber, settlements } = await boot(params.storeRoot, { efforts: ['max'] })
  const adapter = new ScriptedAdapter([textResponse('child answer after fault')], ['max'])
  ctx.llm.registerAdapter(['mock'], adapter)
  const parent = await resumeParent(ctx)
  parkParent(ctx, parent)
  const before = await readStored(ctx, params.childId)
  const turnsBefore = before.events.filter((event) => event.type === 'turn/end').length
  await ctx.subagents.sendMessage(
    parent, SessionId(params.childId), [{ type: 'text', text: 'resume after child fault' }], { signal: SIGNAL() },
  )
  const resumed = await waitTurnEnd(ctx, params.childId, turnsBefore + 1)
  await waitFor(() => settlements.filter((item) => item.childId === String(params.childId)).length >= 1,
    { timeout: 15000 })
  const after = resumed ?? await readStored(ctx, params.childId)
  await persistenceFiber.dispose()
  await ctx.dispose?.()
  const turnEnded = after.events.filter((event) => event.type === 'turn/end').length > turnsBefore
  return {
    parentId: parent.id,
    childId: params.childId,
    sameChildId: String(after.header.id) === String(params.childId),
    childIdRetained: String(after.header.id) === String(params.childId),
    turnEnded,
    descriptorAfter: descriptorOf(after),
    nativelyResumable: String(after.header.id) === String(params.childId)
      && descriptorOf(after)?.mode === 'continuable' && turnEnded,
    childSequenceContiguous: sequencesContiguous(after.events),
  }
}

async function scenarioNegative(params) {
  const { ctx, persistenceFiber } = await boot(params.storeRoot, { efforts: ['max'] })
  const wantsLiveChild = params.kind === 'max-depth'
  const adapter = new ScriptedAdapter([wantsLiveChild ? hangResponse() : textResponse('child answer one')], ['max'])
  ctx.llm.registerAdapter(['mock'], adapter)
  const parent = await createParent(ctx)
  parkParent(ctx, parent)
  const started = await ctx.subagents.startContinuable({
    provider: 'spawn',
    label: 'child task',
    request: { prompt: [{ type: 'text', text: 'child initial task' }], parent },
    signal: SIGNAL(),
  })
  if (wantsLiveChild) {
    await waitFor(() => adapter.requests.length >= 1, { timeout: 10000 })
  } else {
    await waitTurnEnd(ctx, started.childId, 1)
  }

  let result
  if (params.kind === 'non-direct-parent') {
    const other = await createParent(ctx, OTHER_PARENT_ID)
    parkParent(ctx, other)
    result = await captureRejection(() =>
      ctx.subagents.sendMessage(other, started.childId, [{ type: 'text', text: 'hijack' }], { signal: SIGNAL() }))
  } else if (params.kind === 'stale-parent') {
    // Cold-resume through a live but non-owning parent; the stored
    // header.parentSession belongs to the real parent, never to this one.
    const other = await createParent(ctx, OTHER_PARENT_ID)
    parkParent(ctx, other)
    result = await captureRejection(() =>
      ctx.subagents.sendMessage(other, started.childId, [{ type: 'text', text: 'stale' }], { signal: SIGNAL() }))
  } else if (params.kind === 'unmaterialized') {
    const missing = SessionId('00000000-0000-4000-8000-00000000dead')
    result = await captureRejection(() =>
      ctx.subagents.sendMessage(parent, missing, [{ type: 'text', text: 'resume nothing' }], { signal: SIGNAL() }))
  } else if (params.kind === 'child-claims-root') {
    // A child may not reuse the root parent identity as its durable child id.
    result = await captureRejection(() => ctx.subagents.startContinuable({
      provider: 'spawn',
      label: 'root identity claim',
      childId: SessionId(PARENT_ID),
      request: { prompt: [{ type: 'text', text: 'claim root' }], parent },
      signal: SIGNAL(),
    }))
  } else if (params.kind === 'out-of-filter-tool') {
    // A restart with a non-direct parent must not be able to adopt the child.
    result = await captureRejection(() => ctx.subagents.startContinuable({
      provider: 'spawn',
      label: 'filtered child',
      request: {
        prompt: [{ type: 'text', text: 'filtered child' }],
        parent,
        toolFilter: { allow: ['d15_not_a_registered_tool'] },
      },
      signal: SIGNAL(),
    }))
  } else if (params.kind === 'max-depth') {
    // A real depth-2 attempt: the live depth-1 child tries to delegate again
    // under maxDepth=1; the native resolver must reject before dispatch.
    const outer = ctx.agents.get(SessionId(String(started.childId)))
    if (outer === undefined) {
      result = { rejected: false, error: 'outer child was not live for the depth attempt' }
    } else {
      result = await captureRejection(() => ctx.subagents.start('spawn', {
        prompt: [{ type: 'text', text: 'depth-2 child' }],
        parent: outer,
        maxDepth: 1,
        signal: SIGNAL(),
      }))
      result.outerDepth = delegationDepthOf(outer)
    }
  } else {
    result = { rejected: false, error: `unknown negative ${params.kind}` }
  }

  await persistenceFiber.dispose()
  await ctx.dispose?.()
  return { kind: params.kind, childId: started.childId, ...result }
}

async function captureRejection(fn) {
  try {
    await fn()
    return { rejected: false }
  } catch (error) {
    return {
      rejected: true,
      errorClass: error instanceof SubagentError ? 'SubagentError' : error?.constructor?.name ?? 'Error',
      errorCode: error?.code ?? null,
      message: String(error?.message ?? error).slice(0, 200),
    }
  }
}

// ---------------------------------------------------------------------------
// worker entry
// ---------------------------------------------------------------------------

const SCENARIOS = {
  start: scenarioStart,
  resume: scenarioResume,
  fork: scenarioFork,
  crash: scenarioCrash,
  afterCrash: scenarioAfterCrash,
  childFault: scenarioChildFault,
  childFaultResume: scenarioChildFaultResume,
  negative: scenarioNegative,
}

async function workerMain([scenario, rawParams]) {
  const params = JSON.parse(rawParams ?? '{}')
  const handler = SCENARIOS[scenario]
  if (!handler) throw new Error(`unknown worker scenario ${scenario}`)
  const observation = await handler(params)
  process.stdout.write('@@OBS@@' + JSON.stringify(observation) + '\n')
}

// ---------------------------------------------------------------------------
// orchestrator
// ---------------------------------------------------------------------------

function runWorker(self, scenario, params, { expectSignal = null } = {}) {
  const result = spawnSync(process.execPath, [self, 'worker', scenario, JSON.stringify(params)], {
    encoding: 'utf8',
    timeout: 120000,
  })
  const line = (result.stdout || '').split('\n').find((item) => item.startsWith('@@OBS@@'))
  const observation = line ? JSON.parse(line.slice('@@OBS@@'.length)) : null
  const signal = result.signal ?? null
  const crashed = signal !== null || result.status !== 0
  return {
    observation,
    exit: result.status,
    signal,
    crashed,
    crashedAsExpected: expectSignal === null ? !crashed : signal === expectSignal,
    stderr: (result.stderr || '').slice(-500),
  }
}

function runOrchestrator(self, { out, keep }) {
  const roots = []
  const makeRoot = (prefix) => {
    const dir = mkdtempSync(join(tmpdir(), prefix))
    roots.push(dir)
    return dir
  }
  const root = makeRoot('d15-4-native-')
  const crashMarker = join(root, 'crash-marker.json')
  const started = Date.now()
  const scenarios = []
  const negatives = []
  // Evidence version comes from the output filename so a rerun cannot silently
  // overwrite an earlier reviewed artifact.
  const evidenceVersion = (typeof out === 'string' && out.match(/\.(v\d+)\.json$/)?.[1]) || 'v2'
  // Idempotent: every root is removed here on the normal path and again in the
  // outer finally, so worker exceptions/timeouts never leak a temp directory.
  const cleanupRoots = () => {
    const evidence = []
    for (const dir of roots) {
      let removed = false
      try {
        rmSync(dir, { recursive: true, force: true })
        removed = true
      } catch (error) {
        removed = false
      }
      evidence.push({ root: dir, removed })
    }
    return evidence
  }

  try {
    // Test hook: force an orchestrator failure after temp roots exist so the
    // outer finally cleanup can be exercised on the exception path.
    if (process.env.D15_4_FORCE_ORCHESTRATOR_THROW === '1') {
      throw new Error('forced orchestrator throw for cleanup evidence')
    }
    const start = runWorker(self, 'start', { storeRoot: root, composition: {} })
  scenarios.push({
    id: 'parent-child-identity',
    result: start.observation && start.observation.distinctIdentity ? 'PASS' : 'FAIL',
    check: 'childId is a durable SessionId distinct from the root parent; persisted header records the direct parent and origin=subagent; listChildren exposes the continuable child',
    operation: 'real startContinuable on the native spawn provider',
    observation: start.observation,
    fault_applied: false,
  })
  scenarios.push({
    id: 'continuable-descriptor',
    result: start.observation?.descriptor?.version === SUBAGENT_DESCRIPTOR_VERSION
      && start.observation?.descriptor?.mode === 'continuable' ? 'PASS' : 'FAIL',
    check: 'subagent/descriptor v3 is persisted with mode=continuable before the first turn',
    operation: 'read durable descriptor through SessionPersistence.open',
    observation: start.observation?.descriptor,
    fault_applied: false,
  })

  const childId = start.observation?.childId
  const resume = childId
    ? runWorker(self, 'resume', { storeRoot: root, childId })
    : { observation: null }
  scenarios.push({
    id: 'cold-resume',
    result: resume.observation?.sameChildId
      && resume.observation?.newSettlements === 1
      && resume.observation?.sequenceContiguousAcrossResume ? 'PASS' : 'FAIL',
    check: 'a genuinely new OS process cold-resumes the same durable child via sendMessage with the descriptor reapplied and exactly one new settlement',
    operation: 'new OS process + parent resume + sendMessage cold resume',
    observation: resume.observation,
    fault_applied: true,
  })

  const forkRoot = makeRoot('d15-4-fork-')
  const fork = runWorker(self, 'fork', { storeRoot: forkRoot })
  const forkObs = fork.observation
  scenarios.push({
    id: 'fork-lineage',
    result: forkObs?.distinctIdentity && forkObs?.isSeeded
      && forkObs?.inheritedEventCount === forkObs?.parentLastTurnEndSeq + 1
      && forkObs?.parentLogImmutable && forkObs?.childSequenceContiguous ? 'PASS' : 'FAIL',
    check: 'the fork is a distinct seeded child with inheritedEventCount exactly the parent balanced '
      + 'completed-turn prefix (last turn/end seq + 1); the full parent log hash and length are equal '
      + 'before/after; the child log is sequence-contiguous',
    operation: 'real fork provider start over a completed parent turn',
    observation: forkObs,
    fault_applied: true,
  })

  const inheritRoot = makeRoot('d15-4-inherit-')
  const inheritStart = runWorker(self, 'start', {
    storeRoot: inheritRoot,
    composition: { reasoningEffort: 'max', persona: 'd15-4 inherited persona' },
  })
  const inheritResume = inheritStart.observation?.childId
    ? runWorker(self, 'resume', { storeRoot: inheritRoot, childId: inheritStart.observation.childId })
    : { observation: null }
  const inheritedChild = inheritResume.observation?.created?.find((item) => item.id === inheritStart.observation?.childId)
  scenarios.push({
    id: 'inheritance',
    result: inheritStart.observation?.descriptor?.agentProvider === 'mock'
      && inheritStart.observation?.descriptor?.agentModel === 'mock'
      && inheritStart.observation?.descriptor?.agentReasoningEffort === 'max'
      && inheritStart.observation?.descriptor?.persona === 'd15-4 inherited persona'
      && inheritedChild?.reasoningEffort === 'max' ? 'PASS' : 'FAIL',
    check: 'declared provider/model/reasoning-effort/persona are persisted in the descriptor and reapplied to the child on cold resume',
    operation: 'startContinuable with declared composition + cold resume observation of agent/created',
    observation: {
      descriptor: inheritStart.observation?.descriptor,
      reappliedChild: inheritedChild ?? null,
    },
    fault_applied: true,
  })

  const crashRoot = makeRoot('d15-4-crash-')
  const crash = runWorker(self, 'crash',
    { storeRoot: crashRoot, crashMarker: join(crashRoot, 'crash-marker.json') }, { expectSignal: 'SIGKILL' })
  const marker = existsSync(join(crashRoot, 'crash-marker.json'))
    ? JSON.parse(readFileSync(join(crashRoot, 'crash-marker.json'), 'utf8')) : null
  const afterCrash = marker
    ? runWorker(self, 'afterCrash', { storeRoot: crashRoot, childId: marker.childId })
    : { observation: null }
  scenarios.push({
    id: 'parent-crash',
    result: crash.crashedAsExpected && afterCrash.observation?.childIdRetained
      && afterCrash.observation?.parentSurvived ? 'PASS' : 'FAIL',
    check: 'SIGKILL of the executor process is survived by the durable parent identity and the child remains natively resumable with no fabricated completion',
    operation: 'SIGKILL the owning OS process mid child turn, then a new OS process resumes',
    observation: {
      crash: { signal: crash.signal, exit: crash.exit, crashedAsExpected: crash.crashedAsExpected },
      after: afterCrash.observation,
    },
    fault_applied: true,
  })

  // Supporting evidence, not a substitute: a real independent child-run fault
  // (model stream failure) while the parent process stays alive. It is NOT a
  // child process SIGKILL and does not stand in for child-crash.
  const faultRoot = makeRoot('d15-4-childfault-')
  const childFault = runWorker(self, 'childFault', { storeRoot: faultRoot })
  const childFaultResume = childFault.observation?.childId
    ? runWorker(self, 'childFaultResume', { storeRoot: faultRoot, childId: childFault.observation.childId })
    : { observation: null }
  scenarios.push({
    id: 'child-run-fault',
    result: childFault.observation?.childIdRetained && childFault.observation?.parentTruthfulFailure
      && childFault.observation?.fabricatedCompletion !== true
      && childFaultResume.observation?.nativelyResumable ? 'PASS' : 'FAIL',
    check: 'an independent child-run fault (model stream failure, not a SIGKILL) leaves the child id '
      + 'retained, the parent settlement truthful (no fabricated completion), and the child natively '
      + 'resumable in a later OS process',
    operation: 'real child-run fault on the native spawn provider + cold resume',
    observation: { ...(childFault.observation ?? {}), resume: childFaultResume.observation },
    fault_applied: true,
  })

  scenarios.push({
    id: 'child-crash',
    result: 'BLOCKED',
    fault_applied: false,
    not_run_reason: 'not executed: the composed native spawn provider runs children in-process, so an '
      + 'independent child process cannot be SIGKILLed while the parent executor stays alive. The '
      + 'owning-process SIGKILL is recorded only as native executor evidence (parent-crash) and is NOT '
      + 'used for this item. child-run-fault records a real but different independent child fault. '
      + 'Smallest concrete option: an out-of-process child provider or the isolated runtime-adapter '
      + 'stack with a real DSH child process (the D15-3R dsh-process-interruption pattern). No child '
      + 'persistence substitute was built.',
  })
  scenarios.push({
    id: 'byq-adapter-restart',
    result: 'BLOCKED',
    fault_applied: false,
    not_run_reason: 'not executed from BYQ: the committed byq-product-sdk composition loads '
      + 'byq_delegate_* with enableRunInBackground=false, so @deepseek-ai/dsh-tool-subagent always takes '
      + 'the foreground runtimeCtx.subagents.start() path and never startContinuable(); no committed BYQ '
      + 'harness drives the continuable seam and Dsh015Compatibility inherits the 0.1.2 observation '
      + 'contract. The native seam itself is reachable and qualified below in an evidence-only harness; '
      + 'the BYQ runtime-adapter container-restart projection remains unqualified. Smallest concrete '
      + 'option: an isolated D15 compose stack plus a tool-aware scripted provider, without changing the '
      + 'production composition.',
  })

  // Negatives: each must be rejected by the native seam. This records the
  // native rejection only; there is no historical pre-fix gate at this layer, so
  // no claim is made about what such a gate would have done. (The observer's own
  // pre-fix comparison is evidence at the observer layer, not here.)
  for (const kind of ['non-direct-parent', 'stale-parent', 'unmaterialized', 'max-depth',
    'child-claims-root', 'out-of-filter-tool']) {
    const negRoot = makeRoot(`d15-4-neg-${kind}-`)
    let neg = null
    let cleaned = false
    try {
      neg = runWorker(self, 'negative', { storeRoot: negRoot, kind })
    } finally {
      try {
        rmSync(negRoot, { recursive: true, force: true })
        cleaned = true
      } catch {
        cleaned = false
      }
    }
    negatives.push({
      kind,
      rejected: neg?.observation?.rejected === true,
      errorCode: neg?.observation?.errorCode ?? null,
      errorClass: neg?.observation?.errorClass ?? null,
      message: neg?.observation?.message ?? neg?.stderr ?? null,
      root_cleaned: cleaned,
    })
  }

  scenarios.push({
    id: 'host-reboot',
    result: 'NOT_RUN',
    fault_applied: false,
    not_run_reason: 'not executed: rebooting the maintainer host is not authorized and a container/adapter '
      + 'restart is not a host reboot',
  })

  const required = ['parent-child-identity', 'continuable-descriptor', 'cold-resume', 'fork-lineage',
    'inheritance', 'parent-crash', 'child-crash', 'byq-adapter-restart']
  const byId = Object.fromEntries(scenarios.map((item) => [item.id, item]))
  const uncovered = required.filter((id) => byId[id] === undefined || byId[id].result !== 'PASS')
  const negativesPass = negatives.every((item) => item.rejected)

  const observations = {
    schema_version: `byq-d15-4-native-observations.${evidenceVersion}`,
    generated_at: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
    evidence_class: EVIDENCE_CLASS,
    candidate: {
      release: CANDIDATE_RELEASE,
      npm_packages: CANDIDATE_NPM,
      closure: 'agent-loop + jsonl session persistence + @deepseek-ai/dsh-subagent + spawn/fork in-process providers',
    },
    llm: {
      class: LLM_CLASS,
      real_llm_quality: false,
      note: 'Scripted keyless in-process adapter. Runtime-continuity evidence only; never semantic model quality.',
    },
    harness: {
      native_continuable_api: true,
      one_os_process_per_generation: true,
      byq_subagent_persistence: false,
      second_generic_harness: false,
      r3_behavior: false,
    },
    scenarios,
    negatives,
    required_scenarios: required,
    uncovered_required: uncovered,
    negatives_pass: negativesPass,
    host_reboot: {
      result: 'NOT_RUN',
      reason: 'not executed: rebooting the maintainer host is not authorized and a container/adapter restart is not a host reboot',
    },
    runtime_root_cleaned: false,
    cleanup: null,
  }

  if (!keep) {
    observations.cleanup = cleanupRoots()
    observations.runtime_root_cleaned = observations.cleanup.length > 0
      && observations.cleanup.every((item) => item.removed)
  } else {
    observations.runtime_root = root
  }
  observations.duration_ms = Date.now() - started

  if (out) {
    mkdirSync(join(out, '..'), { recursive: true })
    writeFileSync(out, JSON.stringify(observations, null, 2) + '\n')
    const scenarioDir = join(out, '..', 'scenarios')
    mkdirSync(scenarioDir, { recursive: true })
    for (const scenario of scenarios) {
      writeFileSync(join(scenarioDir, `${scenario.id}.${evidenceVersion}.json`), JSON.stringify({
        schema_version: `byq-d15-4-native-scenario.${evidenceVersion}`,
        evidence_class: observations.evidence_class,
        candidate: observations.candidate,
        llm: observations.llm,
        generated_at: observations.generated_at,
        ...scenario,
      }, null, 2) + '\n')
    }
  }
  process.stdout.write(JSON.stringify(observations, null, 2) + '\n')
  return 0
  } finally {
    // Safety net for exception/timeout paths; cleanupRoots is idempotent.
    if (!keep) cleanupRoots()
  }
}

async function main(argv) {
  const [mode, ...rest] = argv
  if (mode === 'worker') {
    await workerMain(rest)
    return 0
  }
  if (mode === 'run') {
    let out = null
    let keep = false
    for (let index = 0; index < rest.length; index += 1) {
      if (rest[index] === '--out') { out = rest[index + 1]; index += 1 } else if (rest[index] === '--keep') { keep = true }
    }
    return runOrchestrator(fileURLToPath(import.meta.url), { out, keep })
  }
  process.stderr.write('usage: native_subagent_harness.mjs run [--out path] [--keep] | worker <scenario> <json>\n')
  return 2
}

main(process.argv.slice(2)).then((code) => { process.exitCode = code }).catch((error) => {
  process.stderr.write(String(error?.stack ?? error) + '\n')
  process.exitCode = 1
})
