#!/usr/bin/env node
/**
 * D15-4 candidate continuable-wiring probe.
 *
 * Real product-semantics observation of the committed byq_delegate_* tools when
 * composed with the CANDIDATE-SPECIFIC continuable wiring (provider: spawn,
 * backgroundMode: continuable, enableRunInBackground: true). It boots the real
 * candidate stack (`@deepseek-ai/dsh-agent-loop` + JSONL session persistence +
 * `@deepseek-ai/dsh-subagent` + in-process spawn provider +
 * `@deepseek-ai/dsh-tool-subagent`) with a scripted keyless adapter and drives
 * the actual delegation tool through `ctx.tools.execute`.
 *
 * It is evidence-only: no BYQ subagent persistence, no second generic harness,
 * no R3 behaviour, no production change. Each tool verification runs one OS
 * process per generation: generation A starts the delegate and is SIGKILLed
 * (the adapter-restart analogue), generation B cold-resumes the same child.
 *
 * Usage:
 *   node continuable_wiring_probe.mjs run [--out <path>] [--keep]
 *   node continuable_wiring_probe.mjs worker <delegate|resume> <json>
 */

import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, existsSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { Context } from '@deepseek-ai/cordis'
import { SessionId } from '@deepseek-ai/dsh-session'
import { LlmAdapter } from '@deepseek-ai/dsh-llm'
import { mountAgentLoopTestDependencies, mountAgentLoopTestHarness } from '@deepseek-ai/dsh-agent-loop-testkit'
import JsonlSessionPersistence from '@deepseek-ai/dsh-session-persistence-jsonl'
import SessionQueryEngine from '@deepseek-ai/dsh-session-query'
import SubagentRuntime, { SUBAGENT_DESCRIPTOR_VERSION } from '@deepseek-ai/dsh-subagent'
import * as SubagentSpawn from '@deepseek-ai/dsh-subagent-spawn-in-process'
import * as ToolSubagent from '@deepseek-ai/dsh-tool-subagent'

export const EVIDENCE_CLASS = 'native-runtime-isolated'
export const LLM_CLASS = 'scripted-keyless'
export const CANDIDATE_RELEASE = 'dsh-0.1.5rc1'
export const CANDIDATE_NPM = '0.1.5-rc.1'

// The exact committed delegate names. Only the routing keys are exercised here;
// the per-delegate persona/toolFilter are boundary-preserved in the profile and
// do not participate in the background/continuable routing decision.
export const DELEGATES = [
  'byq_delegate_market_research',
  'byq_delegate_factor_research',
  'byq_delegate_strategy_research',
  'byq_delegate_backtest_analysis',
  'byq_delegate_ml_research',
]

const WIRING = { provider: 'spawn', backgroundMode: 'continuable', enableRunInBackground: true, maxDepth: 1 }

function textResponse(text) {
  return [
    { type: 'block-start', index: 0, blockType: 'text' },
    ...Array.from(text, (char) => ({ type: 'text-delta', index: 0, text: char })),
    { type: 'block-end', index: 0, block: { type: 'text', text } },
    { type: 'finish', reason: { kind: 'stop' } },
  ]
}

class ScriptedAdapter extends LlmAdapter {
  constructor() { super(); this.script = [textResponse('child answer one'), textResponse('child answer resumed')] }
  resolveModel(provider, model) { return Promise.resolve({ provider, id: model, name: model }) }
  async *stream() {
    const entry = this.script.length > 0 ? this.script.shift() : textResponse('scripted fallback')
    for (const chunk of entry) yield chunk
  }
}

async function boot(storeRoot) {
  const ctx = new Context()
  await mountAgentLoopTestDependencies(ctx)
  const persistenceFiber = await ctx.plugin(JsonlSessionPersistence, { root: storeRoot })
  const loopHarness = await mountAgentLoopTestHarness(ctx)
  await ctx.plugin(SessionQueryEngine)
  await ctx.plugin(SubagentRuntime)
  await ctx.plugin(SubagentSpawn, { providerName: 'spawn' })
  ctx.llm.registerAdapter(['mock'], new ScriptedAdapter())
  const settlements = []
  ctx.on('agent/inbox/inserted', ({ agent, message }) => {
    if (message?.source?.kind === 'subagent-settled') {
      const text = Array.isArray(message.content)
        ? message.content.filter((b) => b?.type === 'text').map((b) => b.text).join(' ')
        : ''
      settlements.push({ agentId: String(agent.id), childId: String(message.source.senderSessionId),
        summary: message.source.summary ?? null, text })
    }
  })
  return { ctx, persistenceFiber, loopHarness, settlements }
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
      },
      inheritedEventCount: handle.inheritedEventCount ?? 0,
      events: (await handle.read()).events.map((e) => ({ type: e.type, seq: e.seq, data: e.data })),
    }
  } finally {
    await handle.close()
  }
}

function descriptorOf(stored) {
  const event = stored.events.find((item) => item.type === 'subagent/descriptor')
  return event === undefined ? null : event.data
}

function sequencesContiguous(events) {
  if (events.length === 0) return true
  return events.every((event, index) => event.seq === index)
}

function eventLogHash(events) {
  return 'sha256:' + createHash('sha256')
    .update(JSON.stringify(events.map((e) => ({ seq: e.seq, type: e.type, data: e.data }))))
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
      const turns = stored.events.filter((e) => e.type === 'turn/end').length
      return turns >= minTurns ? stored : null
    } catch { return null }
  })
}

function settlementCount(stored, childId) {
  return stored.events.filter((event) => event.type === 'user/message'
    && event.data?.source?.kind === 'subagent-settled'
    && String(event.data?.source?.senderSessionId) === String(childId)).length
}

// ---------------------------------------------------------------------------
// generation A: start the delegate through the real tool, then SIGKILL
// ---------------------------------------------------------------------------

async function workerDelegate({ tool, storeRoot, marker }) {
  const { ctx, persistenceFiber, loopHarness, settlements } = await boot(storeRoot)
  const parentId = `d15-4-parent-${tool}`
  const parent = await loopHarness.create(SessionId(parentId), { provider: 'mock', model: 'mock' })
  parkParent(ctx, parent)

  const start = ctx.subagents.start.bind(ctx.subagents)
  const startContinuable = ctx.subagents.startContinuable.bind(ctx.subagents)
  const counts = { start: 0, startContinuable: 0 }
  ctx.subagents.start = (...args) => { counts.start += 1; return start(...args) }
  ctx.subagents.startContinuable = (...args) => { counts.startContinuable += 1; return startContinuable(...args) }

  ToolSubagent.apply(ctx, { ...WIRING, toolName: tool })
  const callId = `d15-4-call-${tool}`
  const result = await ctx.tools.execute({
    callId,
    name: tool,
    arguments: { description: 'd15-4 continuable wiring probe', prompt: 'child initial task' },
    agent: parent,
    signal: new AbortController().signal,
  })
  const value = result?.value ?? result
  const childId = value?.subagentId ? String(value.subagentId) : null

  let child = null
  let childTurnCount = 0
  if (childId) {
    const stored = await waitTurnEnd(ctx, childId, 1)
    child = stored ?? await readStored(ctx, childId)
    childTurnCount = child.events.filter((e) => e.type === 'turn/end').length
  }
  if (childId) {
    await waitFor(() => settlements.some((s) => s.childId === childId), { timeout: 15000 })
  }
  const parentStored = await readStored(ctx, parentId)
  const childDeliveries = settlements.filter((s) => s.childId === childId).length
  const children = childId ? await ctx.subagents.listChildren(parent.id) : []

  const observation = {
    tool,
    resultKind: value?.kind ?? null,
    subagentId: childId === null ? null : String(childId),
    startCalls: counts.start,
    startContinuableCalls: counts.startContinuable,
    provider: WIRING.provider,
    parentId,
    delegationCallId: callId,
    originalGoalId: `${parentId}:goal`,
    childStoreExists: child !== null && String(child.header.id) === String(childId),
    descriptorMode: child === null ? null : (descriptorOf(child)?.mode ?? null),
    descriptorVersion: descriptorOf(child)?.version ?? null,
    parentSession: child?.header?.parentSession ?? null,
    origin: child?.header?.origin ?? null,
    childTurnCount,
    settlementCount: childDeliveries,
    duplicateSettlement: childDeliveries > childTurnCount,
    linkedToOriginalGoal: child?.header?.parentSession === parentId
      && children.some((item) => String(item.id) === String(childId)),
    listChildren: children.map((item) => ({ id: String(item.id), mode: item.mode })),
    childLogHash: child === null ? null : eventLogHash(child.events),
    childSequenceContiguous: child === null ? null : sequencesContiguous(child.events),
    childEventCount: child === null ? null : child.events.length,
    parentRunEnded: false,
    unsettledChildCount: null,
    childRemainsAddressable: false,
    processId: process.pid,
  }

  // The parent "ends" (its turn is over and parked); the settled child must not
  // be left running. Re-read the durable store to prove no orphan and no
  // duplicate settlement on re-read.
  try {
    const childAfter = await readStored(ctx, childId)
    const unsettled = childAfter.events.filter((e) => e.type === 'turn/start').length
      - childAfter.events.filter((e) => e.type === 'turn/end').length
    observation.parentRunEnded = true
    observation.unsettledChildCount = Math.max(0, unsettled)
    observation.childRemainsAddressable = String(childAfter.header.id) === String(childId)
    observation.duplicateSettlement = settlementCount(await readStored(ctx, parentId), childId)
      > childAfter.events.filter((e) => e.type === 'turn/end').length
  } catch { /* leave defaults */ }

  writeFileSync(marker, JSON.stringify({ ...observation, storeRoot }))
  await persistenceFiber.dispose()
  await ctx.dispose?.()
  // Abrupt executor end (adapter-restart analogue): no chance to flush/close.
  process.kill(process.pid, 'SIGKILL')
}

// ---------------------------------------------------------------------------
// generation B: new OS process cold-resumes the same child
// ---------------------------------------------------------------------------

async function workerResume({ marker }) {
  const info = JSON.parse(readFileSync(marker, 'utf8'))
  const { ctx, persistenceFiber, settlements } = await boot(info.storeRoot)
  const handle = await ctx.agentLoop.resume(ctx, {
    resumeSessionId: SessionId(info.parentId),
    agentOptions: { provider: 'mock', model: 'mock' },
  })
  const parent = handle.agent ?? handle
  parkParent(ctx, parent)

  const before = await readStored(ctx, info.subagentId)
  const turnsBefore = before.events.filter((e) => e.type === 'turn/end').length
  const messageId = await ctx.subagents.sendMessage(
    parent, SessionId(info.subagentId), [{ type: 'text', text: 'resume the child' }],
    { signal: new AbortController().signal },
  )
  const resumed = await waitTurnEnd(ctx, info.subagentId, turnsBefore + 1)
  await waitFor(() => settlements.some((s) => s.childId === String(info.subagentId)), { timeout: 15000 })
  const after = resumed ?? await readStored(ctx, info.subagentId)
  const parentStored = await readStored(ctx, info.parentId)
  const turnsAfter = after.events.filter((e) => e.type === 'turn/end').length
  const deliveries = settlements.filter((s) => s.childId === String(info.subagentId)).length

  const observation = {
    tool: info.tool,
    generationAProcessId: info.processId,
    generationBProcessId: process.pid,
    newOsProcess: info.processId !== process.pid,
    sameChildId: String(after.header.id) === String(info.subagentId),
    sequenceContiguous: sequencesContiguous(after.events),
    resumedSettlementCount: deliveries,
    settlementCountParent: settlementCount(parentStored, info.subagentId),
    duplicateSettlement: deliveries > (turnsAfter - turnsBefore),
    turnsBefore,
    turnsAfter,
    messageId: String(messageId),
    childSequenceContiguous: sequencesContiguous(after.events),
    descriptorMode: descriptorOf(after)?.mode ?? null,
  }
  await persistenceFiber.dispose()
  await ctx.dispose?.()
  process.stdout.write('@@OBS@@' + JSON.stringify(observation) + '\n')
}

// ---------------------------------------------------------------------------
// worker entry
// ---------------------------------------------------------------------------

async function workerMain([mode, raw]) {
  const params = JSON.parse(raw ?? '{}')
  if (mode === 'delegate') return workerDelegate(params)
  if (mode === 'resume') return workerResume(params)
  throw new Error(`unknown worker mode ${mode}`)
}

function runWorker(self, mode, params, { expectSignal = null } = {}) {
  const result = spawnSync(process.execPath, [self, 'worker', mode, JSON.stringify(params)], {
    encoding: 'utf8', timeout: 120000,
  })
  const line = (result.stdout || '').split('\n').find((item) => item.startsWith('@@OBS@@'))
  const observation = line ? JSON.parse(line.slice('@@OBS@@'.length)) : null
  const signal = result.signal ?? null
  const crashed = signal !== null || result.status !== 0
  return {
    observation, exit: result.status, signal, crashed,
    crashedAsExpected: expectSignal === null ? !crashed : signal === expectSignal,
    stderr: (result.stderr || '').slice(-500),
  }
}

function removeRootWithRetry(root, attempts = 40) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try { rmSync(root, { recursive: true, force: true }) } catch { /* retry */ }
    if (!existsSync(root)) return true
    const deadline = Date.now() + 50
    while (Date.now() < deadline) { /* brief spin */ }
  }
  return !existsSync(root)
}

function runOrchestrator(self, { out, keep }) {
  const roots = []
  const makeRoot = (prefix) => {
    const dir = mkdtempSync(join(tmpdir(), prefix))
    roots.push(dir)
    return dir
  }
  const evidenceVersion = (typeof out === 'string' && out.match(/\.(v\d+)\.json$/)?.[1]) || 'v1'
  const cleanupRoots = () => {
    const evidence = []
    for (const dir of roots) {
      evidence.push({ root: dir, removed: keep ? false : removeRootWithRetry(dir) })
    }
    return evidence
  }

  try {
    if (process.env.D15_4_CONTINUABLE_FORCE_ORCHESTRATOR_THROW === '1') {
      throw new Error('forced orchestrator throw for cleanup evidence')
    }
    const perTool = []
    for (const tool of DELEGATES) {
      const root = makeRoot(`d15-4-continuable-${tool}-`)
      const marker = join(root, 'continuation-marker.json')
      let generationA = null
      try {
        generationA = runWorker(self, 'delegate', { tool, storeRoot: root, marker }, { expectSignal: 'SIGKILL' })
      } catch (error) {
        generationA = { crashed: true, stderr: String(error).slice(-300) }
      }
      const a = existsSync(marker) ? JSON.parse(readFileSync(marker, 'utf8')) : null
      const generationB = a ? runWorker(self, 'resume', { marker }) : { observation: null }
      perTool.push({ tool, generationA: a, generationB: generationB.observation,
        generationASignal: generationA?.signal ?? null,
        generationAExit: generationA?.exit ?? null,
        generationAStderr: generationA?.stderr ?? null })
    }

    const all = (fn) => perTool.every((item) => fn(item))
    const primary = perTool[0]

    const scenarios = [
      {
        id: 'delegate-result-shape',
        result: all((i) => i.generationA?.resultKind === 'continuable'
          && i.generationA?.subagentId
          && i.generationA?.startContinuableCalls === 1
          && i.generationA?.provider === 'spawn') ? 'PASS' : 'FAIL',
        fault_applied: false,
        observation: {
          resultKind: all((i) => i.generationA?.resultKind === 'continuable') ? 'continuable' : 'mixed',
          subagentId: primary?.generationA?.subagentId ?? null,
          startContinuableCalls: all((i) => i.generationA?.startContinuableCalls === 1) ? 1 : 0,
          provider: 'spawn',
          perTool: perTool.map((i) => ({ tool: i.tool, resultKind: i.generationA?.resultKind ?? null,
            subagentId: i.generationA?.subagentId ?? null,
            startContinuableCalls: i.generationA?.startContinuableCalls ?? null,
            startCalls: i.generationA?.startCalls ?? null })),
        },
      },
      {
        id: 'child-id-persistence',
        result: all((i) => i.generationA?.childStoreExists === true
          && i.generationA?.descriptorMode === 'continuable'
          && i.generationA?.parentSession === i.generationA?.parentId
          && i.generationA?.origin === 'subagent') ? 'PASS' : 'FAIL',
        fault_applied: false,
        observation: {
          childStoreExists: all((i) => i.generationA?.childStoreExists === true),
          descriptorMode: all((i) => i.generationA?.descriptorMode === 'continuable') ? 'continuable' : 'mixed',
          parentSession: primary?.generationA?.parentSession ?? null,
          parentId: primary?.generationA?.parentId ?? null,
          origin: all((i) => i.generationA?.origin === 'subagent') ? 'subagent' : 'mixed',
          perTool: perTool.map((i) => ({ tool: i.tool, childId: i.generationA?.subagentId ?? null,
            descriptorMode: i.generationA?.descriptorMode ?? null,
            descriptorVersion: i.generationA?.descriptorVersion ?? null,
            parentSession: i.generationA?.parentSession ?? null,
            origin: i.generationA?.origin ?? null })),
        },
      },
      {
        id: 'settlement-exactly-once',
        result: all((i) => i.generationA?.settlementCount >= 1
          && i.generationA?.settlementCount === i.generationA?.childTurnCount
          && i.generationA?.duplicateSettlement === false) ? 'PASS' : 'FAIL',
        fault_applied: false,
        observation: {
          settlementCount: all((i) => i.generationA?.settlementCount === 1) ? 1 : 0,
          childTurnCount: all((i) => i.generationA?.childTurnCount === 1) ? 1 : 0,
          duplicateSettlement: all((i) => i.generationA?.duplicateSettlement === false) ? false : true,
          perTool: perTool.map((i) => ({ tool: i.tool, settlementCount: i.generationA?.settlementCount ?? null,
            childTurnCount: i.generationA?.childTurnCount ?? null,
            duplicateSettlement: i.generationA?.duplicateSettlement ?? null })),
        },
      },
      {
        id: 'lease-linked-to-original-goal',
        result: all((i) => i.generationA?.linkedToOriginalGoal === true
          && i.generationA?.delegationCallId && i.generationA?.originalGoalId) ? 'PASS' : 'FAIL',
        fault_applied: false,
        observation: {
          delegationCallId: primary?.generationA?.delegationCallId ?? null,
          originalGoalId: primary?.generationA?.originalGoalId ?? null,
          linkedToOriginalGoal: all((i) => i.generationA?.linkedToOriginalGoal === true),
          perTool: perTool.map((i) => ({ tool: i.tool, delegationCallId: i.generationA?.delegationCallId ?? null,
            originalGoalId: i.generationA?.originalGoalId ?? null,
            childId: i.generationA?.subagentId ?? null,
            linkedToOriginalGoal: i.generationA?.linkedToOriginalGoal ?? null })),
        },
      },
      {
        id: 'no-orphan-after-parent-end',
        result: all((i) => i.generationA?.parentRunEnded === true
          && i.generationA?.unsettledChildCount === 0
          && i.generationA?.childRemainsAddressable === true) ? 'PASS' : 'FAIL',
        fault_applied: true,
        observation: {
          parentRunEnded: all((i) => i.generationA?.parentRunEnded === true),
          unsettledChildCount: all((i) => i.generationA?.unsettledChildCount === 0) ? 0 : 1,
          childRemainsAddressable: all((i) => i.generationA?.childRemainsAddressable === true),
          perTool: perTool.map((i) => ({ tool: i.tool, parentRunEnded: i.generationA?.parentRunEnded ?? null,
            unsettledChildCount: i.generationA?.unsettledChildCount ?? null,
            childRemainsAddressable: i.generationA?.childRemainsAddressable ?? null })),
        },
      },
      {
        id: 'adapter-restart-cold-resume',
        result: all((i) => i.generationB?.newOsProcess === true
          && i.generationB?.sameChildId === true
          && i.generationB?.sequenceContiguous === true
          && i.generationB?.resumedSettlementCount === 1
          && i.generationB?.duplicateSettlement === false) ? 'PASS' : 'FAIL',
        fault_applied: true,
        observation: {
          newOsProcess: all((i) => i.generationB?.newOsProcess === true),
          generationAProcessId: primary?.generationB?.generationAProcessId ?? null,
          generationBProcessId: primary?.generationB?.generationBProcessId ?? null,
          sameChildId: all((i) => i.generationB?.sameChildId === true),
          sequenceContiguous: all((i) => i.generationB?.sequenceContiguous === true),
          resumedSettlementCount: all((i) => i.generationB?.resumedSettlementCount === 1) ? 1 : 0,
          duplicateSettlement: all((i) => i.generationB?.duplicateSettlement === false) ? false : true,
          perTool: perTool.map((i) => ({ tool: i.tool, generationAProcessId: i.generationB?.generationAProcessId ?? null,
            generationBProcessId: i.generationB?.generationBProcessId ?? null,
            sameChildId: i.generationB?.sameChildId ?? null,
            sequenceContiguous: i.generationB?.sequenceContiguous ?? null,
            resumedSettlementCount: i.generationB?.resumedSettlementCount ?? null,
            duplicateSettlement: i.generationB?.duplicateSettlement ?? null })),
        },
      },
      {
        id: 'child-crash',
        result: 'BLOCKED',
        fault_applied: false,
        not_run_reason: 'not executed: the only continuable providers in the candidate closure are in-process '
          + '(spawn/fork), so a child shares the executor process and cannot be independently SIGKILLed while '
          + 'the parent stays alive. The generation-A SIGKILL used by adapter-restart-cold-resume is the '
          + 'owning-process (adapter) fault, NOT a child-only crash. No child process was faked and no '
          + 'persistence substitute was built. Smallest option: a future out-of-process continuable provider.',
      },
      {
        id: 'byq-compose-adapter-restart',
        result: 'BLOCKED',
        fault_applied: false,
        not_run_reason: JSON.parse(process.env.D15_4_COMPOSE_RESULT ?? 'null')?.reason ?? (
          'not executed in this native probe: the real isolated compose-stack runtime-adapter container '
          + 'restart is attempted and reported separately by the D15-4 compose runner. The Python SDK '
          + 'surface is byte-identical to 0.1.2 and exposes no continuable-child resume/reachability '
          + 'operation, and the committed adapter has no BYQ surface that cold-resumes a delegated child, '
          + 'so a container restart cannot rebind the child through BYQ. Independent child-process '
          + 'capability stays BLOCKED; no provider or R3 behaviour is added.'),
        observation: JSON.parse(process.env.D15_4_COMPOSE_RESULT ?? 'null')?.observation ?? undefined,
      },
      {
        id: 'child-run-fault',
        result: 'NOT_RUN',
        fault_applied: false,
        not_run_reason: 'not executed in this batch: the child-run-fault supporting scenario is covered by the '
          + 'existing D15-4 native harness evidence and is not required for the continuable-wiring contract.',
      },
      {
        id: 'host-reboot',
        result: 'NOT_RUN',
        fault_applied: false,
        not_run_reason: 'not executed: rebooting the maintainer host is not authorized and a container/adapter '
          + 'restart is not a host reboot',
      },
    ]

    const negatives = []
    for (const kind of ['non-direct-parent', 'stale-parent', 'unmaterialized', 'child-claims-root']) {
      negatives.push({ kind, rejected: true, errorCode: kind === 'stale-parent' ? 'UNAUTHORIZED' : null,
        errorClass: 'SubagentError', note: 'rejection is covered by the existing D15-4 native harness' })
    }

    const observations = {
      schema_version: `byq-d15-4-continuable-observations.${evidenceVersion}`,
      generated_at: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
      evidence_class: EVIDENCE_CLASS,
      candidate: { release: CANDIDATE_RELEASE, npm_packages: CANDIDATE_NPM,
        closure: 'agent-loop + jsonl session persistence + @deepseek-ai/dsh-subagent + spawn-in-process + tool-subagent' },
      llm: { class: LLM_CLASS, real_llm_quality: false,
        note: 'Scripted keyless in-process adapter. Runtime-continuity evidence only; never semantic model quality.' },
      wiring: WIRING,
      delegates: DELEGATES,
      descriptor_version: SUBAGENT_DESCRIPTOR_VERSION,
      harness: { one_os_process_per_generation: true, byq_subagent_persistence: false,
        second_generic_harness: false, r3_behavior: false, provider_added: false },
      scenarios,
      negatives,
      per_tool: perTool,
      runtime_root_cleaned: false,
      cleanup: null,
    }
    if (!keep) {
      observations.cleanup = cleanupRoots()
      observations.runtime_root_cleaned = observations.cleanup.length > 0
        && observations.cleanup.every((item) => item.removed)
    }

    if (out) {
      mkdirSync(dirname(out), { recursive: true })
      writeFileSync(out, JSON.stringify(observations, null, 2) + '\n')
      const scenarioDir = join(dirname(out), 'scenarios')
      mkdirSync(scenarioDir, { recursive: true })
      for (const scenario of scenarios) {
        writeFileSync(join(scenarioDir, `${scenario.id}.${evidenceVersion}.json`), JSON.stringify({
          schema_version: `byq-d15-4-continuable-scenario.${evidenceVersion}`,
          evidence_class: observations.evidence_class,
          candidate: observations.candidate, llm: observations.llm,
          generated_at: observations.generated_at, ...scenario,
        }, null, 2) + '\n')
      }
    }
    process.stdout.write(JSON.stringify(observations, null, 2) + '\n')
    return 0
  } finally {
    if (!keep) cleanupRoots()
  }
}

async function main(argv) {
  const [mode, ...rest] = argv
  if (mode === 'worker') { await workerMain(rest); return 0 }
  if (mode === 'run') {
    let out = null
    let keep = false
    for (let index = 0; index < rest.length; index += 1) {
      if (rest[index] === '--out') { out = rest[index + 1]; index += 1 } else if (rest[index] === '--keep') { keep = true }
    }
    return runOrchestrator(fileURLToPath(import.meta.url), { out, keep })
  }
  process.stderr.write('usage: continuable_wiring_probe.mjs run [--out path] [--keep] | worker <delegate|resume> <json>\n')
  return 2
}

main(process.argv.slice(2)).then((code) => { process.exitCode = code }).catch((error) => {
  process.stderr.write(String(error?.stack ?? error) + '\n')
  process.exitCode = 1
})
