#!/usr/bin/env node
/**
 * D15-4 BYQ→native subagent routing / process-boundary probe.
 *
 * Real trial against the installed candidate `@deepseek-ai/dsh-tool-subagent`
 * and `@deepseek-ai/dsh-subagent`: does the committed BYQ delegate configuration
 * reach native `startContinuable`, and does the fixed 0.1.5-rc.1 candidate
 * provide an independent-process *continuable* child provider?
 *
 * Each trial runs in its own OS process (so async agent work cannot outlive the
 * trial), and the orchestrator removes every trial store root in a `finally`
 * with a bounded retry. Evidence-only: no product runtime, no second harness, no
 * BYQ subagent persistence, no production change.
 *
 * Usage:
 *   node routing_probe.mjs run [--out <path>] [--keep]
 *   node routing_probe.mjs worker <trial> <store-root>
 */

import { mkdtempSync, mkdirSync, rmSync, existsSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { tmpdir } from 'node:os'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { Context } from '@deepseek-ai/cordis'
import { SessionId } from '@deepseek-ai/dsh-session'
import { LlmAdapter, ToolCallId } from '@deepseek-ai/dsh-llm'
import { mountAgentLoopTestDependencies, mountAgentLoopTestHarness } from '@deepseek-ai/dsh-agent-loop-testkit'
import JsonlSessionPersistence from '@deepseek-ai/dsh-session-persistence-jsonl'
import * as SubagentSpawn from '@deepseek-ai/dsh-subagent-spawn-in-process'
import SubagentRuntime, { SUBAGENT_DESCRIPTOR_VERSION } from '@deepseek-ai/dsh-subagent'
import * as ToolSubagent from '@deepseek-ai/dsh-tool-subagent'

const TRIALS = {
  'byq-foreground': {
    tool: { provider: 'spawn', toolName: 'byq_delegate_test', enableRunInBackground: false },
    registerStubProvider: false,
  },
  'continuable-in-process': {
    tool: { provider: 'spawn', toolName: 'byq_delegate_test', enableRunInBackground: true, backgroundMode: 'continuable' },
    registerStubProvider: false,
  },
  'continuable-out-of-process': {
    tool: { provider: 'dsh-sdk-like', toolName: 'byq_delegate_test', enableRunInBackground: true, backgroundMode: 'continuable' },
    registerStubProvider: true,
  },
}

class ScriptedAdapter extends LlmAdapter {
  resolveModel(provider, model) {
    return Promise.resolve({ provider, id: model, name: model })
  }
  async *stream() {
    yield { type: 'block-start', index: 0, blockType: 'text' }
    yield { type: 'text-delta', index: 0, text: 'ok' }
    yield { type: 'block-end', index: 0, block: { type: 'text', text: 'ok' } }
    yield { type: 'finish', reason: { kind: 'stop' } }
  }
}

async function workerTrial(trialName, storeRoot) {
  const cfg = TRIALS[trialName]
  if (!cfg) throw new Error(`unknown trial ${trialName}`)
  const ctx = new Context()
  await mountAgentLoopTestDependencies(ctx)
  await ctx.plugin(JsonlSessionPersistence, { root: storeRoot })
  const harness = await mountAgentLoopTestHarness(ctx)
  await ctx.plugin(SubagentRuntime)
  await ctx.plugin(SubagentSpawn, { providerName: 'spawn' })
  ctx.llm.registerAdapter(['mock'], new ScriptedAdapter())
  const parent = await harness.create(SessionId('routing-parent'), { provider: 'mock', model: 'mock' })
  if (cfg.registerStubProvider) {
    // Models an out-of-process backend: no prepareContinuable, capabilities NONE.
    ctx.subagents.registerProvider({
      name: 'dsh-sdk-like',
      capabilities: { agentOptions: true, outputSchema: false, depthLimit: false, toolFilter: false, persona: false },
      inheritsParentContext: false,
      async start() { throw new Error('stub provider must not be dispatched') },
    })
  }
  const start = ctx.subagents.start.bind(ctx.subagents)
  const hasContinuable = typeof ctx.subagents.startContinuable === 'function'
  const startContinuable = hasContinuable ? ctx.subagents.startContinuable.bind(ctx.subagents) : undefined
  const counts = { start: 0, startContinuable: 0 }
  ctx.subagents.start = (...args) => { counts.start += 1; return start(...args) }
  if (startContinuable) {
    ctx.subagents.startContinuable = (...args) => { counts.startContinuable += 1; return startContinuable(...args) }
  }

  let applyError = null
  let result = null
  try {
    ToolSubagent.apply(ctx, cfg.tool)
  } catch (error) {
    applyError = { name: error?.constructor?.name ?? 'Error', message: String(error?.message ?? error).slice(0, 300) }
  }
  if (applyError === null) {
    try {
      result = await ctx.tools.execute({
        callId: ToolCallId(`routing-${trialName}`),
        name: cfg.tool.toolName,
        arguments: { description: 'routing probe', prompt: 'routing probe' },
        agent: parent,
        signal: new AbortController().signal,
      })
    } catch (error) {
      result = { error: String(error?.message ?? error).slice(0, 300) }
    }
  }
  return {
    skill: trialName,
    tool_config: cfg.tool,
    apply_error: applyError,
    result_kind: result?.value?.kind ?? result?.kind ?? null,
    start_calls: counts.start,
    start_continuable_calls: counts.startContinuable,
    start_continuable_supported_on_service: hasContinuable,
  }
}

function removeRootWithRetry(root, attempts = 40) {
  // The worker process has exited, so at most a lingering write handle can delay
  // removal; retry briefly rather than leaking the directory.
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      rmSync(root, { recursive: true, force: true })
    } catch {
      // retry below
    }
    if (!existsSync(root)) return true
    const deadline = Date.now() + 50
    while (Date.now() < deadline) { /* brief spin to let the handle close */ }
  }
  return !existsSync(root)
}

function runWorker(self, trialName, storeRoot) {
  const result = spawnSync(process.execPath, [self, 'worker', trialName, storeRoot], {
    encoding: 'utf8', timeout: 120000,
  })
  const line = (result.stdout || '').split('\n').find((item) => item.startsWith('@@OBS@@'))
  return {
    observation: line ? JSON.parse(line.slice('@@OBS@@'.length)) : null,
    exit: result.status,
    crashed: result.status !== 0 || result.signal !== null,
    stderr: (result.stderr || '').slice(-400),
  }
}

function main(argv) {
  const [mode, ...rest] = argv
  if (mode === 'worker') {
    workerTrial(rest[0], rest[1]).then((observation) => {
      process.stdout.write('@@OBS@@' + JSON.stringify(observation) + '\n')
    }).catch((error) => {
      process.stderr.write(String(error?.stack ?? error) + '\n')
      process.exitCode = 1
    })
    return
  }
  if (mode !== 'run') {
    process.stderr.write('usage: routing_probe.mjs run [--out path] [--keep] | worker <trial> <store-root>\n')
    process.exitCode = 2
    return
  }

  const outIndex = rest.indexOf('--out')
  const out = outIndex !== -1 ? rest[outIndex + 1] : null
  const keep = rest.includes('--keep')
  const self = fileURLToPath(import.meta.url)
  const trials = []
  const cleanup = []
  try {
    for (const trialName of Object.keys(TRIALS)) {
      const storeRoot = mkdtempSync(join(tmpdir(), `d15-4-routing-${trialName}-`))
      let worker = null
      try {
        worker = runWorker(self, trialName, storeRoot)
      } finally {
        if (!keep) cleanup.push({ root: storeRoot, removed: removeRootWithRetry(storeRoot) })
      }
      trials.push(worker.observation ?? { skill: trialName, error: worker.stderr, crashed: true })
    }
  } finally {
    if (!keep) {
      for (const entry of cleanup) {
        if (!entry.removed) entry.removed = removeRootWithRetry(entry.root)
      }
    }
  }

  const byq = trials.find((t) => t.skill === 'byq-foreground')
  const inProc = trials.find((t) => t.skill === 'continuable-in-process')
  const outProc = trials.find((t) => t.skill === 'continuable-out-of-process')
  const payload = {
    schema_version: 'byq-d15-4-routing.v1',
    candidate: { release: 'dsh-0.1.5rc1', npm: '0.1.5-rc.1' },
    descriptor_version: SUBAGENT_DESCRIPTOR_VERSION,
    trials,
    cleanup,
    runtime_root_cleaned: keep ? null : cleanup.length > 0 && cleanup.every((item) => item.removed),
    conclusions: {
      byq_foreground_config_reaches_start_continuable: byq?.start_continuable_calls > 0,
      byq_foreground_config_is_foreground: byq?.result_kind === 'foreground' && byq?.start_calls === 1
        && byq?.start_continuable_calls === 0,
      continuable_in_process_is_reachable_when_enabled: inProc?.start_continuable_calls === 1
        && inProc?.result_kind === 'continuable',
      independent_process_continuable_provider_available:
        outProc?.apply_error === null && outProc?.start_continuable_calls === 1,
      out_of_process_provider_without_prepareContinuable_rejected: outProc?.apply_error !== null,
    },
    available_interfaces: [
      {
        interface: 'SubagentRuntime.startContinuable',
        reference: '@deepseek-ai/dsh-subagent index.d.ts; src/index.ts:228; continuation.ts:102',
        kind: 'continuable child (in-process residency)',
      },
      {
        interface: 'SubagentProvider.prepareContinuable',
        reference: '@deepseek-ai/dsh-subagent src/types.ts:389; implemented by subagent-spawn-in-process/src/index.ts:61 and subagent-fork-in-process/src/index.ts:84 only',
        kind: 'capability gate for continuable',
      },
      {
        interface: 'SubagentRuntime.start (foreground/background one-shot)',
        reference: '@deepseek-ai/dsh-subagent index.d.ts; tool-subagent/src/index.ts:557',
        kind: 'one-shot child; process boundary is provider-owned',
      },
      {
        interface: 'tool-subagent background/continuable routing',
        reference: '@deepseek-ai/dsh-tool-subagent src/index.ts:287-305 (resolveDelegationRun), :321-347 (gates), :525-536 (startContinuable)',
        kind: 'BYQ delegate routing',
      },
      {
        interface: 'out-of-process child providers (acp/codex/claude-code)',
        reference: '@deepseek-ai/dsh-subagent src/out-of-process.ts; bundled-015.txt lists dsh-subagent-acp/-codex/-claude-code; NO_START_CAPABILITIES; no prepareContinuable',
        kind: 'independent process, one-shot, fresh context, not continuable',
      },
      {
        interface: 'out-of-process DSH-SDK child provider',
        reference: '@deepseek-ai/dsh-subagent-dsh-sdk src/index.ts (published at 0.1.5-rc.1; NOT in the candidate bundled runtime list; no prepareContinuable)',
        kind: 'independent process, one-shot, fresh context, not continuable, not packaged in the candidate image',
      },
    ],
    required_wiring_for_byq_to_reach_start_continuable: {
      change: "on each byq_delegate_* tool: set backgroundMode: 'continuable' and stop disabling background (enableRunInBackground: true), keeping provider: spawn",
      blast_radius: [
        'composition: plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml (5 delegate tools) and the profile patch override',
        'tool contract: the delegate tool returns {kind: continuable, subagentId} instead of the foreground SubagentResult, so the Product Agent must handle a durable child id, later delivery and settlement',
        'runtime-adapter: services/runtime-adapter/app/runtime.py child-lease/observation path currently models foreground delegation only; a continuable child outlives the parent turn',
        'compat boundary: services/runtime-adapter/app/compat/dsh_015.py still inherits the 0.1.2 observation contract',
      ],
      reversible: 'the composition keys are revertible, but the returned tool-result shape and Product/agent handling change is not transparent to current callers; it is a product-semantics change, not a no-op',
      candidate_specific: 'yes — can be applied to the isolated candidate profile/composition without changing config/dsh/deployment.json, compose.yml or the production selector dsh-0.1.2rc1',
      process_boundary: 'the continuable provider available in the candidate runtime is in-process (spawn/fork); no out-of-process provider implements prepareContinuable, so a continuable child still shares the executor process',
    },
    production_unchanged: {
      selector: 'config/dsh/deployment.json',
      compose: 'compose.yml',
      note: 'probe reads and boots only isolated in-memory/temp topology; it edits no production file',
    },
  }

  const text = JSON.stringify(payload, null, 2) + '\n'
  if (out) {
    mkdirSync(dirname(out), { recursive: true })
    writeFileSync(out, text)
  }
  process.stdout.write(text)
}

main(process.argv.slice(2))
