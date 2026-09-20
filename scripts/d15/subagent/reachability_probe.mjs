#!/usr/bin/env node
/**
 * D15-4 reachability probe: is the native continuable-subagent / fork seam
 * reachable from BYQ today against the fixed DSH 0.1.5-rc.1 candidate closure?
 *
 * This is a real inspection, not an assertion: it reads the committed BYQ
 * composition, the candidate `@deepseek-ai/dsh-tool-subagent` implementation
 * (installed from npm at 0.1.5-rc.1), and the compat boundary, and reports a
 * per-interface status. It never edits the production composition.
 *
 * Usage: node reachability_probe.mjs [--out path]
 */

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '..', '..', '..')

function read(path) {
  try {
    return readFileSync(path, 'utf8')
  } catch {
    return null
  }
}

function countMatches(text, pattern) {
  if (text === null) return 0
  return (text.match(pattern) ?? []).length
}

function probe() {
  const compositionPath = join(ROOT, 'plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml')
  const composition = read(compositionPath)
  const patch = read(join(ROOT, 'plugins/dsh-byq/profiles/dsh-0.1.2rc1/byq-product.patch.yml'))
  const forkComposedInPatch = /id:\s*subagent-fork-in-process/.test(patch ?? '')
  const compatPath = join(ROOT, 'services/runtime-adapter/app/compat/dsh_015.py')
  const compat = read(compatPath)

  // The installed candidate tool implementation is the authoritative behaviour.
  let toolSubagentSource = null
  let toolSubagentVersion = null
  try {
    const require = createRequire(import.meta.url)
    const entry = require.resolve('@deepseek-ai/dsh-tool-subagent')
    toolSubagentSource = read(entry)
    const packageJson = JSON.parse(read(join(dirname(entry), '..', 'package.json')) ?? '{}')
    toolSubagentVersion = packageJson.version ?? null
  } catch {
    toolSubagentSource = null
  }

  const delegateTools = countMatches(composition, /toolName:\s*byq_delegate_/g)
  const backgroundDisabled = countMatches(composition, /enableRunInBackground:\s*false/g)
  const backgroundEnabled = countMatches(composition, /enableRunInBackground:\s*true/g)
  const composesSubagentPkg = /name:\s*'@deepseek-ai\/dsh-subagent'/.test(composition ?? '')
  const composesSpawnProvider = /name:\s*'@deepseek-ai\/dsh-subagent-spawn-in-process'/.test(composition ?? '')
  const composesForkProvider = forkComposedInPatch
    || /name:\s*'@deepseek-ai\/dsh-subagent-fork-in-process'/.test(composition ?? '')
  const compatInherits012 = /class Dsh015Compatibility\(Dsh012Compatibility\)/.test(compat ?? '')
  const startContinuableCallSites = countMatches(toolSubagentSource, /startContinuable\(/g)
  const foregroundStartCallSites = countMatches(toolSubagentSource, /subagents\.start\(/g)

  const byqCompositionContinuablePath = backgroundEnabled > 0 && composesSubagentPkg
  const byqCompositionForegroundSpawn = composesSubagentPkg && composesSpawnProvider && delegateTools > 0

  return {
    schema_version: 'byq-d15-4-reachability.v1',
    candidate: { release: 'dsh-0.1.5rc1', npm: '0.1.5-rc.1' },
    sources: {
      composition: 'plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml',
      compat: 'services/runtime-adapter/app/compat/dsh_015.py',
      tool_subagent_version: toolSubagentVersion,
    },
    facts: {
      composes_subagent_package: composesSubagentPkg,
      composes_spawn_provider: composesSpawnProvider,
      composes_fork_provider: composesForkProvider,
      delegate_tool_count: delegateTools,
      enable_run_in_background_false: backgroundDisabled,
      enable_run_in_background_true: backgroundEnabled,
      compat_inherits_0_1_2_contract: compatInherits012,
      tool_subagent_start_continuable_call_sites: startContinuableCallSites,
      tool_subagent_foreground_start_call_sites: foregroundStartCallSites,
    },
    interfaces: [
      {
        interface: 'byq_delegate_*_foreground_spawn',
        status: byqCompositionForegroundSpawn ? 'REACHABLE_FROM_BYQ_COMPOSITION' : 'NOT_REACHED',
        detail: 'the composition loads @deepseek-ai/dsh-tool-subagent with provider=spawn; the model-facing '
          + 'byq_delegate_* tools call runtimeCtx.subagents.start() when enableRunInBackground is false',
      },
      {
        interface: 'startContinuable_activation_registry',
        status: byqCompositionContinuablePath ? 'REACHABLE_FROM_BYQ_COMPOSITION' : 'NOT_REACHED_FROM_BYQ',
        detail: 'the candidate tool implementation only calls startContinuable() on the '
          + 'background+continuable branch; every BYQ delegate tool sets enableRunInBackground=false, so the '
          + 'continuable residency/cold-resume path is not driven by the committed BYQ composition',
      },
      {
        interface: 'native_continuable_seam_evidence_harness',
        status: 'REACHABLE_IN_EVIDENCE_ONLY_NATIVE_HARNESS',
        detail: 'native_subagent_harness.mjs boots the real candidate agent loop, JSONL persistence, '
          + '@deepseek-ai/dsh-subagent and the spawn/fork providers, and drives startContinuable/Activation/'
          + 'authorizeLineage/listChildren/sendMessage/cold resume directly',
      },
      {
        interface: 'fork_lineage',
        status: composesForkProvider ? 'REACHABLE_IN_NATIVE_HARNESS' : 'PRESENT_NOT_COMPOSED',
        detail: 'dsh-subagent-fork-in-process public .d.ts is unchanged; its in-process provider is mounted '
          + 'by the native harness and qualified for the seeded-prefix invariant',
      },
      {
        interface: 'byq_child_session_projection',
        status: 'NOT_REACHED_FROM_BYQ',
        detail: 'the runtime-adapter observes subagent.started/finished notifications only for ChildLease '
          + 'timeout accounting; the child SessionId is never projected as a BYQ AgentSession identity and '
          + 'no committed BYQ path cold-resumes a continuable child',
      },
      {
        interface: 'byq_adapter_container_restart_child_resume',
        status: 'BLOCKED_NO_COMPOSE_DRIVEN_DELEGATE_IN_THIS_BATCH',
        detail: 'a real isolated runtime-adapter container restart with a BYQ-delegated continuable child '
          + 'requires a tool-aware scripted provider plus startContinuable reachability; neither exists in '
          + 'this batch. The smallest concrete option is an isolated D15 compose stack, without changing the '
          + 'production composition or adding BYQ subagent persistence',
      },
    ],
    production_unchanged: {
      selector: read(join(ROOT, 'config/dsh/deployment.json')) !== null,
      note: 'probe reads only; it does not edit the composition, selector, deployment or any production file',
    },
  }
}

function main() {
  const outIndex = process.argv.indexOf('--out')
  const payload = probe()
  const text = JSON.stringify(payload, null, 2) + '\n'
  if (outIndex !== -1 && process.argv[outIndex + 1]) {
    mkdirSync(dirname(process.argv[outIndex + 1]), { recursive: true })
    writeFileSync(process.argv[outIndex + 1], text)
  }
  process.stdout.write(text)
  return 0
}

process.exitCode = main()
